import logging

from urllib.parse import urlencode

from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DetailView, View
)
from django.urls import reverse, reverse_lazy
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q, Max
from django.db import transaction, IntegrityError
from django.core.exceptions import MultipleObjectsReturned
from django.utils.decorators import method_decorator
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited

from .models import (
    Lote, Empresa, TransicionEstado, AvanceConstructivo,
    SolicitudProrroga, CustomUser, ConsumoServicio,
    Ticket, MensajeTicket,
    ActivoInventario,
    SolicitudAcceso,
)
from .services import (
    registrar_transicion, get_servicio_proveedor,
    SERVICIO_CAMPOS, SERVICIO_LABELS,
    notificar_ticket_mensaje,
    transferir_titularidad, invitar_usuario, remover_miembro,
    RBACError,
    evaluar_incompatibilidades_lote,
)
from .lote_geometry import build_mapa_data, VIEWBOX_W, VIEWBOX_H, SERVIDUMBRE_Y
from .forms import (
    LoginForm, LoteForm,
    SolicitudRadicacionForm, RechazarSolicitudForm,
    AvanceConstructivoForm, SolicitudProrrogaForm,
    EscrituraForm, BajaEmpresaForm, RespuestaProrrogaForm,
    ConsumoServicioForm, TicketCreateForm, MensajeTicketForm,
    AdminTicketCreateForm, TicketExternoForm, ActivoInventarioForm, BajaActivoForm,
    SolicitudAccesoForm, RegistroEmpresaWizardForm,
    RegistroColaboradorForm,
    AdminCrearUsuarioForm, AdminAsignarColaboradorForm,
    SubirDocumentacionForm, DescartarEmpresaForm,
)
from django import forms as django_forms

logger = logging.getLogger(__name__)


 # landing publica
class LandingPageView(TemplateView):
    template_name = 'core/landing.html'

    def get(self, request, *args, **kwargs):
        # si ya esta logueado, mandalo a su inicio: la landing es publica
        if request.user.is_authenticated:
            return redirect('core:inicio')
        return super().get(request, *args, **kwargs)

 # autenticacion
@method_decorator(
    ratelimit(key='ip', rate='10/5m', method='POST', block=False),
    name='post',
)
class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            return render(request, 'core/429.html', status=429)
        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy('core:inicio')


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('core:landing')


 # mixins de acceso
class AdminEnrepaviMixin(LoginRequiredMixin, UserPassesTestMixin):
    """restringe acceso a usuarios del grupo ADMIN_ENREPAVI"""
    def test_func(self):
        return (
            self.request.user.is_superuser
            or self.request.user.groups.filter(name='ADMIN_ENREPAVI').exists()
        )


class EmpresaMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe acceso a usuarios del grupo EMPRESA que tengan una empresa asociada."""
    def test_func(self):
        return (
            self.request.user.groups.filter(name='EMPRESA').exists()
            and self.request.user.empresa_id is not None
        )


class TitularEmpresaMixin(EmpresaMixin):
    """
    Restringe acceso a usuarios TITULAR de su empresa.
    Usar en vistas de gestión de miembros y transferencia de titularidad.
    """
    def test_func(self):
        return (
            super().test_func()
            and self.request.user.rol_interno == CustomUser.RolInterno.TITULAR
        )


class ProveedorServiciosMixin(LoginRequiredMixin, UserPassesTestMixin):
    """restringe acceso a proveedores de cualquier servicio (agua/luz/gas).
    el usuario tiene que estar en uno de los grupos PROVEEDOR_*."""
    PROVEEDOR_GROUPS = ['PROVEEDOR_AGUA', 'PROVEEDOR_LUZ', 'PROVEEDOR_GAS']

    def test_func(self):
        return (
            self.request.user.is_superuser
            or self.request.user.groups.filter(
                name__in=self.PROVEEDOR_GROUPS,
            ).exists()
        )


class OrganismoPublicoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """restringe acceso a organismos publicos y administradores"""
    def test_func(self):
        return (
            self.request.user.is_superuser
            or self.request.user.groups.filter(
                name__in=['ORGANISMO_PUBLICO', 'ADMIN_ENREPAVI']
            ).exists()
        )


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/inicio.html'

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # tareas pendientes para el admin
        ctx['avances_pendientes'] = AvanceConstructivo.objects.filter(
            validado_admin=False,
        ).count()
        ctx['prorrogas_pendientes'] = SolicitudProrroga.objects.filter(
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        ).count()
        # obras proximas a vencer (30 dias)
        hoy = timezone.now().date()
        limite = hoy + timedelta(days=30)
        ctx['proximos_vencer'] = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__lte=limite,
            fecha_limite_obra__gte=hoy,
        ).prefetch_related('empleados')
        # datos para proveedores
        user = self.request.user
        PROVEEDOR_INFO = {
            'PROVEEDOR_AGUA': ('Agua', 'bi-droplet-fill'),
            'PROVEEDOR_LUZ': ('Electricidad', 'bi-lightning-fill'),
            'PROVEEDOR_GAS': ('Gas', 'bi-fire'),
        }
        for group, (label, icon) in PROVEEDOR_INFO.items():
            if user.groups.filter(name=group).exists():
                ctx['proveedor_label'] = label
                ctx['proveedor_icon'] = icon
                break
        return ctx


 # crud lotes solo admin
class LoteListView(AdminEnrepaviMixin, ListView):
    model = Lote
    template_name = 'core/lote_list.html'
    context_object_name = 'lotes'
    paginate_by = 15

    def get_queryset(self):
        qs = Lote.objects.select_related('empresa').all()
        estado = self.request.GET.get('estado')
        if estado and estado in dict(Lote.Estado.choices):
            qs = qs.filter(estado=estado)
        sup_min = self.request.GET.get('sup_min')
        sup_max = self.request.GET.get('sup_max')
        if sup_min:
            qs = qs.filter(superficie_m2__gte=sup_min)
        if sup_max:
            qs = qs.filter(superficie_m2__lte=sup_max)
        return qs.order_by('nro_parcela')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['estados_choices'] = Lote.Estado.choices
        ctx['filtro_estado'] = self.request.GET.get('estado', '')
        ctx['filtro_sup_min'] = self.request.GET.get('sup_min', '')
        ctx['filtro_sup_max'] = self.request.GET.get('sup_max', '')
        # Mapa: siempre se renderiza con TODOS los lotes (no se ve afectado
        # por los filtros de la tabla, para no romper el layout visual).
        ctx['mapa_lotes'] = build_mapa_data(Lote.objects.all())
        ctx['mapa_viewbox_w'] = VIEWBOX_W
        ctx['mapa_viewbox_h'] = VIEWBOX_H
        ctx['mapa_servidumbre_y'] = SERVIDUMBRE_Y
        return ctx


class LoteCreateView(AdminEnrepaviMixin, CreateView):
    model = Lote
    form_class = LoteForm
    template_name = 'core/lote_form.html'
    success_url = reverse_lazy('core:lote_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = 'Nuevo Lote'
        return ctx


class LoteUpdateView(AdminEnrepaviMixin, UpdateView):
    model = Lote
    form_class = LoteForm
    template_name = 'core/lote_form.html'
    success_url = reverse_lazy('core:lote_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = f'Editar Parcela {self.object.nro_parcela}'
        return ctx


 # registro de empresa y solicitud de radicacion

class RegistroSelectorView(TemplateView):
    """Pantalla de selección del tipo de cuenta (Empresa / Organismo / Proveedor)."""
    template_name = 'core/registro_selector.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('core:inicio')
        return super().get(request, *args, **kwargs)


class RegistroEmpresaView(View):
    """
    Wizard de registro de Empresa en 4 pasos:
    1. Datos de la empresa
    2. Proyecto industrial
    3. Representante legal
    4. Credenciales de acceso

    Submit final crea User (con grupo EMPRESA) + Empresa + TransicionEstado
    inicial (None → EnEvaluacion) en una transacción atómica. Los campos del
    modelo Empresa no presentes en el wizard se completan con defaults
    razonables (tipo_empresa=Nueva, rubro=Otro, etc.) para que la empresa
    quede creada y el admin pueda completar el detalle desde el back-office.
    """
    template_name = 'core/registro_empresa_wizard.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('core:inicio')
        return render(request, self.template_name, {'form': RegistroEmpresaWizardForm()})

    @method_decorator(ratelimit(key='ip', rate='5/10m', method='POST', block=False))
    def post(self, request):
        if request.user.is_authenticated:
            return redirect('core:inicio')
        if getattr(request, 'limited', False):
            return render(request, 'core/429.html', status=429)

        form = RegistroEmpresaWizardForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})

        from django.db import transaction as db_transaction
        cd = form.cleaned_data

        with db_transaction.atomic():
            # 1. Crear el user activo y asignarle el grupo EMPRESA.
            usuario = CustomUser.objects.create_user(
                username=cd['username'],
                email=cd['representante_email'],
                password=cd['password1'],
                first_name=cd['representante_nombre'].split(' ', 1)[0],
                last_name=(
                    cd['representante_nombre'].split(' ', 1)[1]
                    if ' ' in cd['representante_nombre'] else ''
                ),
                is_active=True,
            )
            grupo, _ = Group.objects.get_or_create(name='EMPRESA')
            usuario.groups.add(grupo)

            # 2. Crear la Empresa con datos del wizard + defaults razonables
            #    para los campos NOT NULL no capturados (el admin los completa
            #    desde el back-office si hace falta).
            empresa = Empresa.objects.create(
                # ── paso 1: empresa ──────────────────────────────────────────
                razon_social=cd['razon_social'],
                nombre_fantasia=cd.get('nombre_fantasia') or None,
                cuit=cd['cuit'],
                ingresos_brutos=cd.get('ingresos_brutos') or None,
                tipo_empresa=cd['tipo_empresa'],
                objetivo_proyecto=cd.get('objetivo_proyecto') or None,
                rubro=cd['rubro'],
                tipo_societario=cd['tipo_societario'],
                # ── paso 1: contacto ─────────────────────────────────────────
                direccion=cd.get('direccion') or None,
                persona_referente=cd['persona_referente'],
                telefono=cd['telefono'],
                correo_electronico=cd['correo_electronico'],
                # ── paso 2: actividad ────────────────────────────────────────
                actividad_principal=cd['actividad_principal'],
                actividad_secundaria=cd.get('actividad_secundaria') or None,
                descripcion_actividad=cd['descripcion_actividad'],
                emplazamiento_actual=cd.get('emplazamiento_actual') or None,
                personal_jerarquico=cd.get('personal_jerarquico') or 0,
                personal_administrativo=cd.get('personal_administrativo') or 0,
                personal_produccion=cd.get('personal_produccion') or 0,
                personal_a_ocupar=cd['personal_a_ocupar'],
                materias_primas=cd.get('materias_primas') or None,
                destino_produccion=cd.get('destino_produccion') or None,
                # ── paso 2: infraestructura ──────────────────────────────────
                necesidad_m2=cd['necesidad_m2'],
                tiempo_radicacion_meses=cd['tiempo_radicacion_meses'],
                superficie_cubierta_trabajo_m2=cd['superficie_cubierta_trabajo_m2'],
                superficie_cubierta_deposito_m2=cd['superficie_cubierta_deposito_m2'],
                superficie_futura_expansion_m2=cd.get('superficie_futura_expansion_m2') or None,
                superficie_estacionamiento_m2=cd.get('superficie_estacionamiento_m2') or None,
                tiene_planos=cd['tiene_planos'],
                # ── paso 2: servicios ────────────────────────────────────────
                energia_tension=cd.get('energia_tension') or None,
                energia_potencia_rango=cd.get('energia_potencia_rango') or None,
                consumo_estimado_agua_potable=cd.get('consumo_estimado_agua_potable') or None,
                consumo_estimado_agua_cruda=cd.get('consumo_estimado_agua_cruda') or None,
                gas=cd.get('gas', False),
                requiere_internet=cd.get('requiere_internet', False),
                necesidad_balanza_publica=cd.get('necesidad_balanza_publica', False),
                necesidad_comedor=cd.get('necesidad_comedor', False),
                necesidad_salon_multiuso=cd.get('necesidad_salon_multiuso', False),
                # ── paso 2: impacto ambiental ────────────────────────────────
                categoria_industrial=cd['categoria_industrial'],
                maneja_inflamables=cd.get('maneja_inflamables', False),
                genera_residuos=cd.get('genera_residuos', False),
                tratamiento_en_planta=cd.get('tratamiento_en_planta', False),
                # ── paso 3: representante legal ──────────────────────────────
                representante_nombre=cd['representante_nombre'],
                representante_dni=cd['representante_dni'],
                representante_cargo=cd['representante_cargo'],
                representante_email=cd['representante_email'],
                representante_telefono=cd['representante_telefono'],
                estado=Empresa.Estado.EN_EVALUACION,
            )

            # 3. Registrar la primera transición de estado (None → EnEvaluacion).
            TransicionEstado.objects.create(
                empresa=empresa,
                estado_anterior=None,
                estado_nuevo=Empresa.Estado.EN_EVALUACION,
                usuario=usuario,
                justificacion_resolucion='Creada desde el wizard de registro.',
            )

            # 4. Asignar empresa y rol TITULAR al usuario que registró.
            usuario.empresa = empresa
            usuario.rol_interno = CustomUser.RolInterno.TITULAR
            usuario.save(update_fields=['empresa', 'rol_interno'])

        messages.success(
            request,
            f'Tu solicitud para "{empresa.razon_social}" fue enviada. '
            'Iniciá sesión para hacer seguimiento.',
        )
        return redirect('core:login')


class RegistroColaboradorView(View):
    """Registro liviano para colaboradores de empresa. No crea Empresa."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('core:inicio')
        return render(request, 'core/registro_colaborador.html', {'form': RegistroColaboradorForm()})

    @method_decorator(ratelimit(key='ip', rate='5/10m', method='POST', block=False))
    def post(self, request):
        if request.user.is_authenticated:
            return redirect('core:inicio')
        if getattr(request, 'limited', False):
            return render(request, 'core/429.html', status=429)
        form = RegistroColaboradorForm(request.POST)
        if form.is_valid():
            user = form.save()
            request.session['collab_username'] = user.username
            return redirect('core:registro_colaborador_exitoso')
        return render(request, 'core/registro_colaborador.html', {'form': form})


class RegistroColaboradorExitosoView(TemplateView):
    template_name = 'core/registro_colaborador_exitoso.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['username'] = self.request.session.pop('collab_username', None)
        return ctx


def _es_admin(user):
    return user.is_superuser or user.groups.filter(name='ADMIN_ENREPAVI').exists()


class AdminGestionUsuariosView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Listado de todos los usuarios del sistema."""

    def test_func(self):
        return _es_admin(self.request.user)

    def get(self, request):
        usuarios = (
            CustomUser.objects
            .prefetch_related('groups')
            .select_related('empresa')
            .order_by('username')
        )
        pendientes = CustomUser.objects.filter(
            groups__name='EMPRESA', empresa__isnull=True, is_active=True
        ).order_by('username')
        pendientes_con_form = [
            (u, AdminAsignarColaboradorForm(prefix=f'assign_{u.pk}'))
            for u in pendientes
        ]
        solicitudes_pendientes = (
            SolicitudAcceso.objects
            .filter(estado=SolicitudAcceso.Estado.PENDIENTE)
            .select_related('usuario')
            .order_by('fecha_solicitud')
        )
        return render(request, 'core/admin_gestion_usuarios.html', {
            'usuarios': usuarios,
            'pendientes_con_form': pendientes_con_form,
            'solicitudes_pendientes': solicitudes_pendientes,
        })

    def post(self, request):
        action = request.POST.get('action')

        if action == 'asignar_empresa':
            user_pk = request.POST.get('user_pk')
            usuario = get_object_or_404(
                CustomUser,
                pk=user_pk,
                groups__name='EMPRESA',
                empresa__isnull=True,
                is_active=True,
            )
            assign_form = AdminAsignarColaboradorForm(request.POST, prefix=f'assign_{user_pk}')
            if assign_form.is_valid():
                try:
                    usuario.empresa = assign_form.cleaned_data['empresa']
                    usuario.rol_interno = assign_form.cleaned_data['rol_interno']
                    usuario.save(update_fields=['empresa', 'rol_interno'])
                    messages.success(
                        request,
                        f'\u00ab{usuario.username}\u00bb asignado a {usuario.empresa.razon_social} como {usuario.get_rol_interno_display()}.'
                    )
                except IntegrityError:
                    messages.error(request, 'No se pudo asignar: la empresa ya tiene un Titular activo.')
            else:
                messages.error(request, 'Error al asignar. Verificá los datos.')
            return redirect('core:admin_gestion_usuarios')

        return redirect('core:admin_gestion_usuarios')


class AdminCrearUsuarioView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Crea un usuario de cualquier tipo desde el panel de administración."""

    def test_func(self):
        return _es_admin(self.request.user)

    def get(self, request):
        return render(request, 'core/admin_crear_usuario.html', {
            'form': AdminCrearUsuarioForm(),
        })

    def post(self, request):
        form = AdminCrearUsuarioForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Usuario «{user.username}» creado correctamente.')
            return redirect('core:solicitud_acceso_list')
        return render(request, 'core/admin_crear_usuario.html', {'form': form})


class SolicitudAccesoCreateView(CreateView):
    """
    Solicitud de acceso para Organismo Público o Proveedor.

    Crea un CustomUser inactivo y un registro SolicitudAcceso pendiente.
    Notifica a SUPPORT_INBOX_EMAIL para que el admin lo apruebe/rechace
    desde el admin de Django (donde se envían los mails de resolución).
    """
    template_name = 'core/solicitud_acceso_form.html'
    form_class = SolicitudAccesoForm
    # success_url se setea dinámicamente en form_valid

    # Mapping URL kwarg -> tipo del modelo
    TIPO_POR_SLUG = {
        'organismo': SolicitudAcceso.Tipo.ORGANISMO,
        'proveedor': SolicitudAcceso.Tipo.PROVEEDOR,
    }

    def dispatch(self, request, *args, **kwargs):
        slug = kwargs.get('tipo_slug')
        if slug not in self.TIPO_POR_SLUG:
            return redirect('core:registro')
        if request.user.is_authenticated:
            return redirect('core:inicio')
        self.tipo = self.TIPO_POR_SLUG[slug]
        # Rate limiting solo en POST (intentos de envío del formulario)
        if request.method == 'POST':
            from django_ratelimit.core import is_ratelimited
            limited = is_ratelimited(
                request,
                group='solicitud_acceso',
                key='ip',
                rate='5/10m',
                increment=True,
            )
            if limited:
                return render(request, 'core/429.html', status=429)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tipo'] = self.tipo
        return kwargs

    def get_context_data(self, **kwargs):
        from django.conf import settings as dj_settings
        ctx = super().get_context_data(**kwargs)
        ctx['tipo'] = self.tipo
        ctx['es_organismo'] = self.tipo == SolicitudAcceso.Tipo.ORGANISMO
        ctx['es_proveedor'] = self.tipo == SolicitudAcceso.Tipo.PROVEEDOR
        ctx['titulo'] = (
            'Datos del organismo' if ctx['es_organismo']
            else 'Datos del proveedor'
        )
        ctx['support_email'] = dj_settings.SUPPORT_INBOX_EMAIL
        return ctx

    def form_valid(self, form):
        from .services import notificar_solicitud_acceso_recibida

        with transaction.atomic():
            # 1. Crear usuario inactivo (sin grupo aún, se asigna al aprobar).
            usuario = CustomUser.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email_institucional'],
                password=form.cleaned_data['password1'],
                is_active=False,
            )
            # 2. Crear la solicitud asociada (con PDF si viene).
            self.object = form.save(commit=False)
            self.object.tipo = self.tipo
            self.object.usuario = usuario
            if 'documentacion_pdf' in self.request.FILES:
                self.object.documentacion_pdf = self.request.FILES['documentacion_pdf']
            self.object.save()

            # 3. Generar Ticket ADMINISTRATIVA para la bandeja del admin.
            tipo_display = self.object.get_tipo_display()
            acceso_display = (
                self.object.get_tipo_acceso_display() if self.object.tipo_acceso else '—'
            )
            tiene_doc = 'Sí' if self.object.documentacion_pdf else 'No'
            contenido_ticket = (
                f"Nueva solicitud de acceso al sistema GPIV.\n\n"
                f"Tipo: {tipo_display} ({acceso_display})\n"
                f"Solicitante: {self.object.nombre_apellido} — {self.object.cargo}\n"
                f"Organización: {self.object.organizacion}\n"
                f"Teléfono: {self.object.telefono}\n"
                f"Email institucional: {self.object.email_institucional}\n"
                f"Documentación adjunta: {tiene_doc}\n\n"
                f"Motivo del acceso:\n{self.object.motivo}\n\n"
                f"Para aprobar o rechazar ingresá a:\n"
                f"Panel › Solicitudes de Acceso › #{self.object.pk}"
            )
            ticket = Ticket.objects.create(
                asunto=f'Solicitud de acceso: {tipo_display} — {self.object.organizacion}',
                categoria=Ticket.Categoria.ADMINISTRATIVA,
                creador=None,
                nombre_contacto=self.object.nombre_apellido,
                email_contacto=self.object.email_institucional,
                telefono_contacto=self.object.telefono,
            )
            MensajeTicket.objects.create(
                ticket=ticket,
                autor=None,
                contenido=contenido_ticket,
            )

        # 4. Notificar al admin por email (fuera de atomic para no bloquear rollback).
        try:
            notificar_solicitud_acceso_recibida(self.object)
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Error al notificar solicitud de acceso recibida (pk=%s)", self.object.pk
            )

        return redirect('core:solicitud_acceso_enviada')




class SolicitudAccesoEnviadaView(TemplateView):
    """Confirmación tras enviar una solicitud de acceso."""
    template_name = 'core/solicitud_acceso_enviada.html'


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN: gestión de solicitudes de acceso (Organismos y Proveedores)
# ──────────────────────────────────────────────────────────────────────────────

class SolicitudAccesoListView(AdminEnrepaviMixin, ListView):
    """Admin: bandeja de solicitudes de acceso pendientes de revisión."""
    model = SolicitudAcceso
    template_name = 'core/solicitud_acceso_list.html'
    context_object_name = 'solicitudes'
    paginate_by = 20

    def get_queryset(self):
        qs = SolicitudAcceso.objects.select_related('usuario', 'resuelto_por')
        estado = self.request.GET.get('estado')
        if estado and estado in dict(SolicitudAcceso.Estado.choices):
            qs = qs.filter(estado=estado)
        else:
            qs = qs.filter(estado=SolicitudAcceso.Estado.PENDIENTE)
        tipo = self.request.GET.get('tipo')
        if tipo and tipo in dict(SolicitudAcceso.Tipo.choices):
            qs = qs.filter(tipo=tipo)
        return qs.order_by('-fecha_solicitud')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['estados_choices'] = SolicitudAcceso.Estado.choices
        ctx['tipos_choices'] = SolicitudAcceso.Tipo.choices
        ctx['filtro_estado'] = self.request.GET.get('estado', SolicitudAcceso.Estado.PENDIENTE)
        ctx['filtro_tipo'] = self.request.GET.get('tipo', '')
        ctx['pendientes_count'] = SolicitudAcceso.objects.filter(
            estado=SolicitudAcceso.Estado.PENDIENTE
        ).count()
        return ctx


class SolicitudAccesoDetailView(AdminEnrepaviMixin, DetailView):
    """Admin: detalle de una solicitud de acceso con botones de acción."""
    model = SolicitudAcceso
    template_name = 'core/solicitud_acceso_detail.html'
    context_object_name = 'solicitud'

    def get_queryset(self):
        return SolicitudAcceso.objects.select_related('usuario', 'resuelto_por')


class SolicitudAccesoAprobarView(AdminEnrepaviMixin, View):
    """
    Admin: aprobar una solicitud de acceso.

    En una transacción atómica:
    1. Marca la solicitud como Aprobada.
    2. Activa el usuario (is_active=True).
    3. Asigna el grupo correcto según tipo/tipo_acceso.
    4. Envía email de notificación al usuario (fuera del atomic).
    """
    def post(self, request, pk):
        solicitud = get_object_or_404(
            SolicitudAcceso, pk=pk, estado=SolicitudAcceso.Estado.PENDIENTE
        )
        observaciones = request.POST.get('observaciones_admin', '').strip()

        try:
            with transaction.atomic():
                # 1. Actualizar solicitud
                solicitud.estado = SolicitudAcceso.Estado.APROBADA
                solicitud.fecha_resolucion = timezone.now()
                solicitud.resuelto_por = request.user
                solicitud.motivo_resolucion = observaciones
                solicitud.save(update_fields=[
                    'estado', 'fecha_resolucion', 'resuelto_por', 'motivo_resolucion',
                ])
                # 2. Activar usuario
                usuario = solicitud.usuario
                if usuario is None:
                    raise ValueError('La solicitud no tiene usuario asociado y no puede ser aprobada.')
                usuario.is_active = True
                usuario.save(update_fields=['is_active'])
                # 3. Asignar grupo correcto
                nombre_grupo = solicitud.get_grupo_destino()
                grupo, _ = Group.objects.get_or_create(name=nombre_grupo)
                usuario.groups.add(grupo)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('core:solicitud_acceso_detail', pk=pk)

        # 4. Notificar al usuario por email (fuera del atomic)
        try:
            from .services import notificar_solicitud_acceso_resuelta
            notificar_solicitud_acceso_resuelta(solicitud)
        except Exception:
            logger.exception(
                "Error al notificar aprobación de solicitud de acceso (pk=%s)", pk
            )

        messages.success(
            request,
            f'Solicitud de {solicitud.nombre_apellido} aprobada. '
            f'Usuario activado con grupo {nombre_grupo}.'
        )
        return redirect('core:solicitud_acceso_list')


class SolicitudAccesoRechazarView(AdminEnrepaviMixin, View):
    """
    Admin: rechazar una solicitud de acceso.

    Marca la solicitud como Rechazada y mantiene el usuario inactivo.
    Envía email con el motivo de rechazo.
    """
    def post(self, request, pk):
        solicitud = get_object_or_404(
            SolicitudAcceso, pk=pk, estado=SolicitudAcceso.Estado.PENDIENTE
        )
        observaciones = request.POST.get('observaciones_admin', '').strip()
        if not observaciones:
            messages.error(request, 'Debe ingresar un motivo de rechazo.')
            return redirect('core:solicitud_acceso_detail', pk=pk)

        with transaction.atomic():
            solicitud.estado = SolicitudAcceso.Estado.RECHAZADA
            solicitud.fecha_resolucion = timezone.now()
            solicitud.resuelto_por = request.user
            solicitud.motivo_resolucion = observaciones
            solicitud.save(update_fields=[
                'estado', 'fecha_resolucion', 'resuelto_por', 'motivo_resolucion',
            ])

        try:
            from .services import notificar_solicitud_acceso_resuelta
            notificar_solicitud_acceso_resuelta(solicitud)
        except Exception:
            logger.exception(
                "Error al notificar rechazo de solicitud de acceso (pk=%s)", pk
            )

        messages.warning(
            request,
            f'Solicitud de {solicitud.nombre_apellido} rechazada.'
        )
        return redirect('core:solicitud_acceso_list')




class SolicitudCreateView(EmpresaMixin, CreateView):
    """formulario de solicitud de radicacion, solo para empresas sin solicitud previa"""
    template_name = 'core/solicitud_form.html'
    form_class = SolicitudRadicacionForm
    success_url = reverse_lazy('core:mi_solicitud')

    def test_func(self):
        # requiere ser usuario EMPRESA, pero sin empresa asociada todavía
        return (
            self.request.user.groups.filter(name='EMPRESA').exists()
            and self.request.user.empresa_id is None
        )

    def form_valid(self, form):
        form.instance.usuario = self.request.user
        form.instance.estado = Empresa.Estado.EN_EVALUACION
        response = super().form_valid(form)
        # registrar primera transicion
        TransicionEstado.objects.create(
            empresa=self.object,
            estado_anterior=None,
            estado_nuevo=Empresa.Estado.EN_EVALUACION,
            usuario=self.request.user,
            justificacion_resolucion='Solicitud de radicación enviada',
        )
        messages.success(self.request, 'Solicitud enviada correctamente.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['secciones'] = list(ctx['form'].get_secciones())
        return ctx


class MiSolicitudView(EmpresaMixin, TemplateView):
    """panel de la empresa: ve su solicitud, lote, avances, prorrogas e historial"""
    template_name = 'core/mi_solicitud.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # La relación ahora es FK directa en user.empresa (no reverse 1:1)
        empresa = self.request.user.empresa
        ctx['empresa'] = empresa
        if empresa:
            ctx['historial'] = empresa.historial_estados.select_related('usuario').all()
            ctx['lote'] = empresa.lotes.first()
            ctx['avances'] = empresa.avances_constructivos.all()
            ctx['prorrogas'] = empresa.prorrogas.all()
            # puede cargar avance si esta radicada o en construccion
            ctx['puede_cargar_avance'] = empresa.estado in [
                Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION,
            ]
            # puede pedir prorroga si esta en construccion
            ctx['puede_pedir_prorroga'] = empresa.estado == Empresa.Estado.EN_CONSTRUCCION
            # flujo preaprobación → documentación
            ctx['puede_subir_documentacion'] = empresa.estado == Empresa.Estado.PRE_APROBADO
            ctx['documentacion_subida'] = bool(empresa.documentacion_proyecto)
            ctx['form_documentacion'] = SubirDocumentacionForm()
        return ctx


class MisConsumosView(EmpresaMixin, ListView):
    """empresa: consulta sus consumos de servicios en pantalla propia."""
    model = ConsumoServicio
    template_name = 'core/mis_consumos.html'
    context_object_name = 'consumos'
    paginate_by = 20

    def get_queryset(self):
        return ConsumoServicio.objects.filter(
            empresa=self.request.user.empresa,
        ).order_by('-periodo_anio', '-periodo_mes')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa'] = self.request.user.empresa
        return ctx


 # evaluacion de solicitudes admin

class SolicitudListView(AdminEnrepaviMixin, ListView):
    """listado de empresas con filtro por estado"""
    model = Empresa
    template_name = 'core/solicitud_list.html'
    context_object_name = 'solicitudes'
    paginate_by = 20

    GRUPOS_FILTRO = {
        'obras_activas': 'Obras activas',
        'con_avance': 'Con avance validado',
        'vencidas': 'Obras vencidas',
        'proximas_vencer': 'Obras por vencer',
    }

    def get_queryset(self):
        qs = Empresa.objects.prefetch_related('empleados').order_by('-pk')
        grupo = self.request.GET.get('grupo')
        estado = self.request.GET.get('estado')
        hoy = timezone.now().date()
        if grupo == 'obras_activas':
            qs = qs.filter(
                estado__in=[Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION],
            )
        elif grupo == 'con_avance':
            qs = qs.filter(
                estado__in=[
                    Empresa.Estado.RADICADA,
                    Empresa.Estado.EN_CONSTRUCCION,
                    Empresa.Estado.FINALIZADO,
                    Empresa.Estado.ESCRITURADO,
                ],
                avances_constructivos__validado_admin=True,
            ).distinct()
        elif grupo == 'vencidas':
            qs = qs.filter(
                estado__in=[Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION],
                fecha_limite_obra__lt=hoy,
            )
        elif grupo == 'proximas_vencer':
            limite = hoy + timedelta(days=30)
            qs = qs.filter(
                estado=Empresa.Estado.EN_CONSTRUCCION,
                fecha_limite_obra__gte=hoy,
                fecha_limite_obra__lte=limite,
            )
        elif estado and estado in dict(Empresa.Estado.choices):
            qs = qs.filter(estado=estado)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        grupo = self.request.GET.get('grupo', '')
        ctx['estados_choices'] = Empresa.Estado.choices
        ctx['filtro_estado'] = self.request.GET.get('estado', '')
        ctx['filtro_grupo'] = grupo if grupo in self.GRUPOS_FILTRO else ''
        ctx['filtro_grupo_label'] = self.GRUPOS_FILTRO.get(grupo, '')
        return ctx


class SolicitudDetailView(AdminEnrepaviMixin, DetailView):
    """detalle completo de una solicitud"""
    model = Empresa
    template_name = 'core/solicitud_detail.html'
    context_object_name = 'empresa'

    def get_queryset(self):
        return Empresa.objects.prefetch_related('lotes', 'avances_constructivos')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['historial'] = self.object.historial_estados.select_related('usuario').all()
        # armar secciones con valores legibles (no el raw del field.value)
        form = SolicitudRadicacionForm(instance=self.object)
        secciones = []
        for titulo, campos in form.get_secciones():
            filas = []
            for bf in campos:
                field = bf.field
                valor = bf.value()
                if isinstance(field.widget, django_forms.CheckboxInput):
                    display = 'Sí' if valor else 'No'
                elif isinstance(field.widget, (django_forms.Select, django_forms.RadioSelect)):
                    # buscar el label del choice seleccionado
                    choices_dict = dict(field.choices)
                    display = choices_dict.get(valor, valor) or '—'
                else:
                    display = valor if valor not in (None, '') else '—'
                filas.append((bf.label, display))
            secciones.append((titulo, filas))
        ctx['secciones'] = secciones
        ctx['lote'] = self.object.lotes.first()
        ctx['avances'] = self.object.avances_constructivos.all()
        ctx['prorrogas'] = self.object.prorrogas.select_related('resuelta_por').all()
        # verificar si tiene avance 100% validado para habilitar finalizacion
        ctx['tiene_avance_100_validado'] = self.object.avances_constructivos.filter(
            porcentaje_declarado=100, validado_admin=True,
        ).exists()
        # flujo preaprobación → documentación
        ctx['documentacion_subida'] = bool(self.object.documentacion_proyecto)
        ctx['puede_tomar_decision'] = (
            self.object.estado == Empresa.Estado.PRE_APROBADO
            and bool(self.object.documentacion_proyecto)
        )
        return ctx


class SolicitudPreAprobarView(AdminEnrepaviMixin, View):
    """accion: EnEvaluacion -> PreAprobado.
    A partir de aquí, la empresa debe subir la documentación del proyecto.
    El admin solo puede avanzar a ListoAdjudicar o Descartada desde DecisionFinalView.
    """
    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.EN_EVALUACION)
        registrar_transicion(empresa, Empresa.Estado.PRE_APROBADO, request.user, 'Pre-aprobada por administración')
        messages.success(request, f'{empresa.razon_social} pre-aprobada. La empresa debe subir la documentación del proyecto.')
        return redirect('core:solicitud_detail', pk=pk)


class SolicitudRechazarView(AdminEnrepaviMixin, View):
    """accion: rechazar con justificacion obligatoria (solo EnEvaluacion o PreAprobado)"""
    ESTADOS_RECHAZABLES = [Empresa.Estado.EN_EVALUACION, Empresa.Estado.PRE_APROBADO]

    def get(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado__in=self.ESTADOS_RECHAZABLES)
        form = RechazarSolicitudForm()
        return render(request, 'core/solicitud_rechazar.html', {'empresa': empresa, 'form': form})

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado__in=self.ESTADOS_RECHAZABLES)
        form = RechazarSolicitudForm(request.POST)
        if form.is_valid():
            registrar_transicion(
                empresa, Empresa.Estado.RECHAZADO, request.user,
                form.cleaned_data['justificacion']
            )
            messages.success(request, f'{empresa.razon_social} rechazada.')
            return redirect('core:solicitud_list')
        return render(request, 'core/solicitud_rechazar.html', {'empresa': empresa, 'form': form})


# ──────────────────────────────────────────────────────────────────────────────
# EMPRESA: Subir documentación del proyecto (estado PRE_APROBADO)
# ──────────────────────────────────────────────────────────────────────────────

class SubirDocumentacionView(EmpresaMixin, View):
    """
    La empresa sube la documentación completa del proyecto cuando está PRE_APROBADO.

    Validación en dispatch:
    - Estado debe ser PRE_APROBADO.
    - Si la empresa ya subió documentación, igualmente puede reemplazarla.

    Una vez subida, el admin puede tomar la decisión final desde DecisionFinalView.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        empresa = getattr(request.user, 'empresa', None)
        if empresa is None or empresa.estado != Empresa.Estado.PRE_APROBADO:
            messages.error(
                request,
                'La subida de documentación solo está habilitada cuando tu solicitud está pre-aprobada.'
            )
            return redirect('core:mi_solicitud')
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        empresa = request.user.empresa
        form = SubirDocumentacionForm(request.POST, request.FILES, instance=empresa)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                TransicionEstado.objects.create(
                    empresa=empresa,
                    estado_anterior=empresa.estado,
                    estado_nuevo=empresa.estado,  # no cambia el estado, solo se registra el hecho
                    usuario=request.user,
                    justificacion_resolucion='Documentación del proyecto subida por la empresa.',
                )
            messages.success(
                request,
                'Documentación subida correctamente. La administración la revisará a la brevedad.'
            )
        else:
            for error in form.errors.values():
                messages.error(request, error.as_text())
        return redirect('core:mi_solicitud')


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN: Decisión final (PRE_APROBADO + doc → LISTO_ADJUDICAR o DESCARTADA)
# ──────────────────────────────────────────────────────────────────────────────

class DecisionFinalView(AdminEnrepaviMixin, View):
    """
    Admin: tomá la decisión final sobre una empresa en estado PRE_APROBADO que
    ya subió su documentación.

    Acciones posibles:
    - aprobar → LISTO_ADJUDICAR (la empresa queda lista para adjudicación de lote).
    - descartar → DESCARTADA (se registra motivo, queda en bandeja de descartadas).

    Validación crítica (backend):
    - Si la empresa no tiene documentacion_proyecto cargado, no se puede aprobar.
      (PermissionDenied como defensa en profundidad).
    """

    def _get_empresa(self, pk):
        """Retorna la empresa solo si está en PRE_APROBADO."""
        return get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.PRE_APROBADO)

    def get(self, request, pk):
        empresa = self._get_empresa(pk)
        return render(request, 'core/decision_final.html', {
            'empresa': empresa,
            'form_descartar': DescartarEmpresaForm(),
            'documentacion_subida': bool(empresa.documentacion_proyecto),
        })

    def post(self, request, pk):
        empresa = self._get_empresa(pk)
        accion = request.POST.get('accion')

        if accion == 'aprobar':
            # ── Validación crítica: la empresa DEBE haber subido documentación ──
            if not empresa.documentacion_proyecto:
                messages.error(
                    request,
                    'No se puede aprobar: la empresa todavía no subió la documentación del proyecto.'
                )
                return redirect('core:decision_final', pk=pk)

            with transaction.atomic():
                registrar_transicion(
                    empresa,
                    Empresa.Estado.LISTO_ADJUDICAR,
                    request.user,
                    'Proyecto aprobado por administración. Listo para adjudicación de lote.',
                )
            messages.success(
                request,
                f'{empresa.razon_social} aprobada. Queda lista para adjudicación de lote.'
            )
            return redirect('core:solicitud_detail', pk=pk)

        if accion == 'descartar':
            form = DescartarEmpresaForm(request.POST)
            if form.is_valid():
                motivo = form.cleaned_data['motivo']
                with transaction.atomic():
                    empresa.motivo_descarte = motivo
                    empresa.save(update_fields=['motivo_descarte'])
                    registrar_transicion(
                        empresa,
                        Empresa.Estado.DESCARTADA,
                        request.user,
                        f'Empresa descartada. Motivo: {motivo}',
                    )
                messages.warning(
                    request,
                    f'{empresa.razon_social} descartada. Quedó registrada en la bandeja de descartadas.'
                )
                return redirect('core:solicitudes_descartadas')
            # form inválido: volver a renderizar con errores
            return render(request, 'core/decision_final.html', {
                'empresa': empresa,
                'form_descartar': form,
                'documentacion_subida': bool(empresa.documentacion_proyecto),
            })

        # accion desconocida
        messages.error(request, 'Acción no reconocida.')
        return redirect('core:decision_final', pk=pk)


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN: Bandeja de empresas descartadas
# ──────────────────────────────────────────────────────────────────────────────

class EmpresasDescartadasView(AdminEnrepaviMixin, ListView):
    """
    Admin: listado de empresas en estado DESCARTADA.

    Permite consultar quiénes fueron descartadas, cuándo y por qué motivo,
    cumpliendo el requerimiento de trazabilidad y auditoría del flujo.
    """
    model = Empresa
    template_name = 'core/solicitudes_descartadas.html'
    context_object_name = 'empresas'
    paginate_by = 20

    def get_queryset(self):
        return (
            Empresa.objects
            .filter(estado=Empresa.Estado.DESCARTADA)
            .prefetch_related('historial_estados')
            .order_by('-pk')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_descartadas'] = Empresa.objects.filter(
            estado=Empresa.Estado.DESCARTADA
        ).count()
        return ctx



 # adjudicacion de lote

class AdjudicacionView(AdminEnrepaviMixin, View):
    """
    Adjudicar un lote a una empresa en estado LISTO_ADJUDICAR.

    IMPORTANTE: el estado requerido cambió de PRE_APROBADO a LISTO_ADJUDICAR.
    Para llegar a este estado la empresa debe haber subido la documentación
    y el admin debe haberla aprobado desde DecisionFinalView.
    """

    def get(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.LISTO_ADJUDICAR)
        m2_min = empresa.get_necesidad_m2_minimo()
        lotes = list(Lote.objects.filter(
            estado=Lote.Estado.DISPONIBLE,
            superficie_m2__gte=m2_min,
        ).order_by('nro_parcela'))
        alertas_por_lote = {}
        for lote in lotes:
            lote.alertas_incompatibilidad = evaluar_incompatibilidades_lote(
                empresa, lote,
            )
            alertas_por_lote[lote.pk] = lote.alertas_incompatibilidad

        lotes_mapa = list(Lote.objects.select_related('empresa').all())
        lotes_candidatos = {lote.pk for lote in lotes}
        for lote in lotes_mapa:
            lote.adjudicable = lote.pk in lotes_candidatos
            alertas = alertas_por_lote.get(lote.pk, [])
            lote.alerta_ambiental = bool(alertas)
            lote.alerta_resumen = '; '.join(
                f'Parcela {a["lote_vecino"].nro_parcela}: '
                f'{a["empresa_vecina"].razon_social}'
                for a in alertas
            )
        return render(request, 'core/adjudicacion.html', {
            'empresa': empresa,
            'lotes': lotes,
            'mapa_lotes': build_mapa_data(lotes_mapa),
            'mapa_viewbox_w': VIEWBOX_W,
            'mapa_viewbox_h': VIEWBOX_H,
            'mapa_servidumbre_y': SERVIDUMBRE_Y,
            'mapa_adjudicacion': True,
        })

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.LISTO_ADJUDICAR)
        # Defensa en profundidad: verificar documentación aunque el estado ya lo garantiza
        if not empresa.documentacion_proyecto:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(
                'No se puede adjudicar: la empresa no tiene documentación del proyecto registrada.'
            )
        lote_id = request.POST.get('lote_id')
        m2_min = empresa.get_necesidad_m2_minimo()
        lote = get_object_or_404(
            Lote, pk=lote_id, estado=Lote.Estado.DISPONIBLE,
            superficie_m2__gte=m2_min,
        )
        alertas = evaluar_incompatibilidades_lote(empresa, lote)
        with transaction.atomic():
            # asignar lote
            lote.estado = Lote.Estado.EN_USO
            lote.empresa = empresa
            lote.save(update_fields=['estado', 'empresa'])
            # calcular fecha limite
            empresa.fecha_limite_obra = (
                timezone.now().date() + relativedelta(months=empresa.tiempo_radicacion_meses)
            )
            empresa.save(update_fields=['fecha_limite_obra'])
            # transicion a radicada
            registrar_transicion(empresa, Empresa.Estado.RADICADA, request.user, f'Adjudicada en parcela {lote.nro_parcela}')
        if alertas:
            detalle = '; '.join(
                f'Parcela {a["lote_vecino"].nro_parcela}: '
                f'{a["empresa_vecina"].razon_social} ({a["motivo"]})'
                for a in alertas
            )
            messages.warning(
                request,
                'Advertencia ambiental registrada: la adjudicación se realizó, '
                f'pero el lote tiene vecinos sensibles. {detalle}'
            )
        messages.success(request, f'{empresa.razon_social} radicada en Parcela {lote.nro_parcela}.')
        return redirect('core:solicitud_list')


 # etapa 2 seguimiento post radicacion

 # avance constructivo hu-05 hu-06 cu-03

class AvanceCreateView(EmpresaMixin, CreateView):
    """empresa radicada o en construccion carga un avance de obra"""
    template_name = 'core/avance_form.html'
    form_class = AvanceConstructivoForm
    success_url = reverse_lazy('core:mi_solicitud')

    def test_func(self):
        if not super().test_func():
            return False
        empresa = self.request.user.empresa
        if not empresa:
            return False
        return empresa.estado in [Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION]

    def form_valid(self, form):
        empresa = self.request.user.empresa
        form.instance.empresa = empresa
        response = super().form_valid(form)
        # primer avance: Radicada -> EnConstruccion
        if empresa.estado == Empresa.Estado.RADICADA:
            registrar_transicion(
                empresa, Empresa.Estado.EN_CONSTRUCCION, self.request.user,
                f'Primer avance constructivo registrado ({form.instance.porcentaje_declarado}%)',
            )
        messages.success(self.request, 'Avance constructivo registrado correctamente.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa'] = self.request.user.empresa
        return ctx


class AvancesPendientesView(AdminEnrepaviMixin, ListView):
    """admin: listado de avances pendientes de validacion"""
    model = AvanceConstructivo
    template_name = 'core/avances_pendientes.html'
    context_object_name = 'avances'
    paginate_by = 20

    def get_queryset(self):
        return AvanceConstructivo.objects.filter(
            validado_admin=False,
        ).select_related('empresa').order_by('-fecha_presentacion')


class AvanceValidarView(AdminEnrepaviMixin, View):
    """admin: validar un avance constructivo"""
    def post(self, request, pk):
        with transaction.atomic():
            avance = get_object_or_404(
                AvanceConstructivo.objects.select_for_update(),
                pk=pk,
                validado_admin=False,
            )
            empresa = Empresa.objects.select_for_update().get(pk=avance.empresa_id)
            avance.validado_admin = True
            avance.validado_por = request.user
            avance.fecha_validacion = timezone.now()
            avance.save(update_fields=['validado_admin', 'validado_por', 'fecha_validacion'])

            finaliza_obra = (
                avance.porcentaje_declarado >= 100
                and empresa.estado == Empresa.Estado.EN_CONSTRUCCION
            )
            if finaliza_obra:
                registrar_transicion(
                    empresa, Empresa.Estado.FINALIZADO, request.user,
                    'Obra finalizada por avance validado al 100%',
                )

        if finaliza_obra:
            messages.success(
                request,
                f'Avance de {empresa.razon_social} (100%) validado. La empresa pasó a Finalizado.',
            )
        else:
            messages.success(
                request,
                f'Avance de {empresa.razon_social} ({avance.porcentaje_declarado}%) validado.',
            )
        return redirect('core:avances_pendientes')


 # solicitud de prorroga hu-07 cu-05

class ProrrogaCreateView(EmpresaMixin, CreateView):
    """empresa en construccion solicita extension de plazo"""
    template_name = 'core/prorroga_form.html'
    form_class = SolicitudProrrogaForm
    success_url = reverse_lazy('core:mi_solicitud')

    def test_func(self):
        if not super().test_func():
            return False
        empresa = self.request.user.empresa
        if not empresa:
            return False
        return empresa.estado == Empresa.Estado.EN_CONSTRUCCION

    def form_valid(self, form):
        form.instance.empresa = self.request.user.empresa
        response = super().form_valid(form)
        messages.success(self.request, 'Solicitud de prórroga enviada correctamente.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa'] = self.request.user.empresa
        return ctx


class ProrrogasPendientesView(AdminEnrepaviMixin, ListView):
    """admin: listado de prorrogas pendientes"""
    model = SolicitudProrroga
    template_name = 'core/prorrogas_pendientes.html'
    context_object_name = 'prorrogas'
    paginate_by = 20

    def get_queryset(self):
        return SolicitudProrroga.objects.filter(
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        ).select_related('empresa').order_by('-fecha_solicitud')


class ProrrogaAprobarView(AdminEnrepaviMixin, View):
    """admin: aprobar prorroga, extiende fecha_limite_obra"""
    def post(self, request, pk):
        prorroga = get_object_or_404(
            SolicitudProrroga, pk=pk,
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        )
        form = RespuestaProrrogaForm(request.POST)
        if form.is_valid():
            empresa = prorroga.empresa
            if not empresa.fecha_limite_obra:
                messages.error(
                    request,
                    f'{empresa.razon_social} no tiene fecha límite de obra definida. '
                    'Asignala desde el admin antes de aprobar una prórroga.',
                )
                return redirect('core:prorrogas_pendientes')
            empresa.fecha_limite_obra = (
                empresa.fecha_limite_obra + relativedelta(months=prorroga.meses_solicitados)
            )
            empresa.save(update_fields=['fecha_limite_obra'])
            prorroga.estado = SolicitudProrroga.EstadoProrroga.APROBADA
            prorroga.respuesta_admin = form.cleaned_data.get('respuesta', '')
            prorroga.fecha_respuesta = timezone.now()
            prorroga.resuelta_por = request.user
            prorroga.save(update_fields=['estado', 'respuesta_admin', 'fecha_respuesta', 'resuelta_por'])
            messages.success(request, f'Prórroga de {prorroga.meses_solicitados} meses aprobada para {empresa.razon_social}.')
        return redirect('core:prorrogas_pendientes')


class ProrrogaRechazarView(AdminEnrepaviMixin, View):
    """admin: rechazar prorroga"""
    def post(self, request, pk):
        prorroga = get_object_or_404(
            SolicitudProrroga, pk=pk,
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        )
        form = RespuestaProrrogaForm(request.POST)
        if form.is_valid():
            prorroga.estado = SolicitudProrroga.EstadoProrroga.RECHAZADA
            prorroga.respuesta_admin = form.cleaned_data.get('respuesta', '')
            prorroga.fecha_respuesta = timezone.now()
            prorroga.resuelta_por = request.user
            prorroga.save(update_fields=['estado', 'respuesta_admin', 'fecha_respuesta', 'resuelta_por'])
            messages.success(request, f'Prórroga rechazada para {prorroga.empresa.razon_social}.')
        return redirect('core:prorrogas_pendientes')


 # finalizacion y escrituracion hu-16 cu-07

class FinalizarObraView(AdminEnrepaviMixin, View):
    """admin: marca obra como finalizada (EnConstruccion -> Finalizado)"""
    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.EN_CONSTRUCCION)
        # verificar que tenga avance validado al 100%
        avance_100 = empresa.avances_constructivos.filter(
            porcentaje_declarado=100, validado_admin=True,
        ).exists()
        if not avance_100:
            messages.error(request, 'La empresa no tiene un avance del 100% validado.')
            return redirect('core:solicitud_detail', pk=pk)
        registrar_transicion(empresa, Empresa.Estado.FINALIZADO, request.user, 'Obra finalizada y certificada')
        messages.success(request, f'Obra de {empresa.razon_social} marcada como finalizada.')
        return redirect('core:solicitud_detail', pk=pk)


class EscrituracionView(AdminEnrepaviMixin, View):
    """admin: registrar escritura del lote (Finalizado -> Escriturado)"""
    def get(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.FINALIZADO)
        form = EscrituraForm()
        return render(request, 'core/escrituracion.html', {'empresa': empresa, 'form': form})

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.FINALIZADO)
        form = EscrituraForm(request.POST, request.FILES)
        if form.is_valid():
            empresa.escritura_pdf = form.cleaned_data['escritura_pdf']
            empresa.save(update_fields=['escritura_pdf'])
            registrar_transicion(empresa, Empresa.Estado.ESCRITURADO, request.user, 'Escritura registrada')
            messages.success(request, f'Escrituración de {empresa.razon_social} completada.')
            return redirect('core:solicitud_detail', pk=pk)
        return render(request, 'core/escrituracion.html', {'empresa': empresa, 'form': form})


 # baja y desadjudicacion hu-09 cu-02

class BajaEmpresaView(AdminEnrepaviMixin, View):
    """admin: dar de baja empresa y liberar lote"""
    ESTADOS_BAJA = [Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION, Empresa.Estado.CADUCADO]

    def get(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado__in=self.ESTADOS_BAJA)
        form = BajaEmpresaForm()
        return render(request, 'core/baja_empresa.html', {'empresa': empresa, 'form': form})

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado__in=self.ESTADOS_BAJA)
        form = BajaEmpresaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # liberar lotes asignados
                for lote in empresa.lotes.filter(estado=Lote.Estado.EN_USO):
                    lote.estado = Lote.Estado.DISPONIBLE
                    lote.empresa = None
                    lote.save(update_fields=['estado', 'empresa'])
                registrar_transicion(
                    empresa, Empresa.Estado.HISTORICO_BAJA, request.user,
                    form.cleaned_data['justificacion'],
                )
            messages.success(request, f'{empresa.razon_social} dada de baja. Lote(s) liberado(s).')
            return redirect('core:solicitud_list')
        return render(request, 'core/baja_empresa.html', {'empresa': empresa, 'form': form})


 # etapa 3 operacion y monitoreo

 # consumos de servicios hu-08 cu-04

class ConsumoCreateView(ProveedorServiciosMixin, CreateView):
    """proveedor: declarar consumo mensual por empresa.
    el formulario se segrega por servicio (agua/luz/gas) segun el grupo
    del usuario; un proveedor solo puede cargar el consumo del que es."""
    template_name = 'core/consumo_form.html'
    form_class = ConsumoServicioForm
    success_url = reverse_lazy('core:consumo_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['servicio'] = get_servicio_proveedor(self.request.user)
        return kwargs

    def form_valid(self, form):
        servicio = get_servicio_proveedor(self.request.user)
        empresa = form.cleaned_data['empresa']
        mes = form.cleaned_data['periodo_mes']
        anio = form.cleaned_data['periodo_anio']
        # solo persiste los campos del servicio del proveedor; el resto
        # queda como esta (otro proveedor puede cargar su parte despues)
        defaults = {'cargado_por': self.request.user}
        if servicio in SERVICIO_CAMPOS:
            for campo in SERVICIO_CAMPOS[servicio]:
                defaults[campo] = form.cleaned_data.get(campo)
        else:
            # superuser u otro caso: persiste todo lo que venga
            for campo in ['consumo_agua_potable_m3', 'consumo_agua_cruda_m3',
                          'consumo_luz_kwh', 'consumo_gas_m3']:
                if campo in form.cleaned_data:
                    defaults[campo] = form.cleaned_data[campo]
        consumo, _ = ConsumoServicio.objects.update_or_create(
            empresa=empresa, periodo_mes=mes, periodo_anio=anio,
            defaults=defaults,
        )
        messages.success(
            self.request,
            f'Consumo de {empresa.razon_social} '
            f'({mes:02d}/{anio}) registrado.'
        )
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        servicio = get_servicio_proveedor(self.request.user)
        ctx['servicio'] = servicio
        ctx['servicio_label'] = SERVICIO_LABELS.get(servicio, 'Servicios')
        return ctx


class ConsumoListView(ProveedorServiciosMixin, ListView):
    """proveedor: listado de consumos declarados.
    si el usuario es proveedor de un servicio, solo ve los consumos
    donde su servicio tenga datos cargados."""
    model = ConsumoServicio
    template_name = 'core/consumo_list.html'
    context_object_name = 'consumos'
    paginate_by = 20

    def get_queryset(self):
        qs = ConsumoServicio.objects.select_related('empresa').order_by(
            '-periodo_anio', '-periodo_mes', 'empresa__razon_social'
        )
        servicio = get_servicio_proveedor(self.request.user)
        if servicio in SERVICIO_CAMPOS:
            # mostrar solo registros con al menos un campo del servicio cargado
            from django.db.models import Q
            filtro = Q()
            for campo in SERVICIO_CAMPOS[servicio]:
                filtro |= Q(**{f'{campo}__isnull': False})
            qs = qs.filter(filtro)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        servicio = get_servicio_proveedor(self.request.user)
        ctx['servicio'] = servicio
        ctx['servicio_label'] = SERVICIO_LABELS.get(servicio, 'Servicios')
        ctx['campos_servicio'] = SERVICIO_CAMPOS.get(servicio, [
            'consumo_agua_potable_m3', 'consumo_agua_cruda_m3',
            'consumo_luz_kwh', 'consumo_gas_m3',
        ])
        return ctx


 # consulta publica para organismos hu-10

class ConsultaParqueView(OrganismoPublicoMixin, TemplateView):
    """dashboard del parque, accesible por organismos publicos y admins.
    consolida los KPIs del parque (ocupacion, empresas por estado, consumo
    del ultimo periodo, distribucion por categoria industrial)."""
    template_name = 'core/consulta_parque.html'

    ESTADOS_ACTIVOS = [
        Empresa.Estado.RADICADA,
        Empresa.Estado.EN_CONSTRUCCION,
        Empresa.Estado.FINALIZADO,
        Empresa.Estado.ESCRITURADO,
    ]

    COLORES_ESTADO = [
        '#F59E0B', '#38BDF8', '#EF4444', '#22C55E', '#6366F1',
        '#14B8A6', '#06B6D4', '#F97316', '#94A3B8',
    ]
    COLORES_DONA = ['#22C55E', '#64748B', '#FBBF24', '#38BDF8', '#F97316', '#A855F7']

    @staticmethod
    def _conic_gradient(items):
        total = sum(item['cantidad'] for item in items)
        if not total:
            return '#E5E7EB'
        inicio = 0
        partes = []
        for item in items:
            pct = item['cantidad'] / total * 100
            fin = inicio + pct
            item['pct'] = f'{pct:.1f}'
            partes.append(f'{item["color"]} {inicio:.2f}% {fin:.2f}%')
            inicio = fin
        return f'conic-gradient({", ".join(partes)})'

    @staticmethod
    def _linea_svg(valores, ancho=220, alto=80, margen=12):
        if not valores:
            return ''
        vals = [float(v or 0) for v in valores]
        minimo = min(vals)
        maximo = max(vals)
        rango = maximo - minimo
        puntos = []
        paso = (ancho - margen * 2) / (len(vals) - 1 or 1)
        for idx, valor in enumerate(vals):
            x = margen + idx * paso
            if rango:
                y = alto - margen - ((valor - minimo) / rango) * (alto - margen * 2)
            else:
                y = alto / 2
            puntos.append(f'{x:.1f},{y:.1f}')
        return ' '.join(puntos)

    @staticmethod
    def _periodos_ultimos_meses(ultimo, cantidad=4):
        if not ultimo:
            return []
        base = date(ultimo.periodo_anio, ultimo.periodo_mes, 1)
        periodos = []
        for offset in range(cantidad - 1, -1, -1):
            periodo = base - relativedelta(months=offset)
            periodos.append((periodo.year, periodo.month, f'{periodo.month:02d}/{str(periodo.year)[2:]}'))
        return periodos

    @staticmethod
    def _dashboard_url(nombre, **params):
        url = reverse(nombre)
        params_limpios = {k: v for k, v in params.items() if v not in (None, '')}
        if params_limpios:
            return f'{url}?{urlencode(params_limpios)}'
        return url

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        puede_gestionar = (
            self.request.user.is_superuser
            or self.request.user.groups.filter(name='ADMIN_ENREPAVI').exists()
        )

        def action_url(nombre, **params):
            if not puede_gestionar:
                return ''
            return self._dashboard_url(nombre, **params)

        empresas = Empresa.objects.filter(
            estado__in=self.ESTADOS_ACTIVOS,
        ).prefetch_related('lotes').order_by('razon_social')

        total_lotes = Lote.objects.count()
        lotes_en_uso = Lote.objects.filter(estado=Lote.Estado.EN_USO).count()
        lotes_disponibles = Lote.objects.filter(
            estado=Lote.Estado.DISPONIBLE,
        ).count()
        lotes_reserva = Lote.objects.filter(
            estado=Lote.Estado.RESERVA_FISCAL,
        ).count()
        pct_num = (lotes_en_uso / total_lotes * 100) if total_lotes else 0
        pct_ocupacion = f'{pct_num:.1f}'
        ocupacion_items = [
            {
                'label': 'Disponibles',
                'cantidad': lotes_disponibles,
                'color': '#22C55E',
                'href': action_url('core:lote_list', estado=Lote.Estado.DISPONIBLE),
            },
            {
                'label': 'En uso',
                'cantidad': lotes_en_uso,
                'color': '#64748B',
                'href': action_url('core:lote_list', estado=Lote.Estado.EN_USO),
            },
            {
                'label': 'Reserva fiscal',
                'cantidad': lotes_reserva,
                'color': '#FBBF24',
                'href': action_url('core:lote_list', estado=Lote.Estado.RESERVA_FISCAL),
            },
        ]
        ocupacion_gradient = self._conic_gradient(ocupacion_items)
        ocupacion_total_href = action_url('core:lote_list')

        empresas_por_estado = []
        for idx, (valor, label) in enumerate(Empresa.Estado.choices):
            cant = Empresa.objects.filter(estado=valor).count()
            if cant:
                empresas_por_estado.append({
                    'label': label,
                    'cantidad': cant,
                    'color': self.COLORES_ESTADO[idx % len(self.COLORES_ESTADO)],
                    'href': action_url('core:solicitud_list', estado=valor),
                })
        max_empresas_estado = max(
            [item['cantidad'] for item in empresas_por_estado] or [1]
        )
        for item in empresas_por_estado:
            pct = item['cantidad'] / max_empresas_estado * 100
            item['pct_barra'] = pct
            item['pct_barra_css'] = f'{pct:.1f}'

        # distribucion por categoria industrial (solo activas)
        categorias = []
        for idx, (valor, label) in enumerate(Empresa.CategoriaIndustrial.choices):
            cant = empresas.filter(categoria_industrial=valor).count()
            if cant:
                categorias.append({
                    'label': label,
                    'cantidad': cant,
                    'color': self.COLORES_DONA[idx % len(self.COLORES_DONA)],
                })
        categorias_gradient = self._conic_gradient(categorias)

        # distribucion por rubro (solo activas)
        rubros = []
        for idx, (valor, label) in enumerate(Empresa.Rubro.choices):
            cant = empresas.filter(rubro=valor).count()
            if cant:
                rubros.append({
                    'label': label,
                    'cantidad': cant,
                    'color': self.COLORES_DONA[(idx + 2) % len(self.COLORES_DONA)],
                })
        rubros_gradient = self._conic_gradient(rubros)

        ultimo = ConsumoServicio.objects.order_by(
            '-periodo_anio', '-periodo_mes',
        ).first()
        servicios_consumo = [
            {
                'clave': 'agua_potable',
                'label': 'Agua potable',
                'icono': 'bi-droplet',
                'campo': 'consumo_agua_potable_m3',
                'total_key': 'total_agua_potable',
                'unidad': 'm³',
                'color': '#0EA5E9',
            },
            {
                'clave': 'agua_cruda',
                'label': 'Agua cruda',
                'icono': 'bi-water',
                'campo': 'consumo_agua_cruda_m3',
                'total_key': 'total_agua_cruda',
                'unidad': 'm³',
                'color': '#14B8A6',
            },
            {
                'clave': 'electricidad',
                'label': 'Electricidad',
                'icono': 'bi-lightning-charge',
                'campo': 'consumo_luz_kwh',
                'total_key': 'total_kwh',
                'unidad': 'kWh',
                'color': '#F59E0B',
            },
            {
                'clave': 'gas',
                'label': 'Gas',
                'icono': 'bi-fire',
                'campo': 'consumo_gas_m3',
                'total_key': 'total_gas',
                'unidad': 'm³',
                'color': '#EF4444',
            },
        ]
        periodos_consumo = self._periodos_ultimos_meses(ultimo, cantidad=6)
        consumo_evolucion = []
        if periodos_consumo:
            filtro_periodos = Q()
            for anio, mes, _ in periodos_consumo:
                filtro_periodos |= Q(periodo_anio=anio, periodo_mes=mes)
            agregados_periodo = {
                (item['periodo_anio'], item['periodo_mes']): item
                for item in ConsumoServicio.objects.filter(filtro_periodos).values(
                    'periodo_anio',
                    'periodo_mes',
                ).annotate(
                    total_agua_potable=Sum('consumo_agua_potable_m3'),
                    total_agua_cruda=Sum('consumo_agua_cruda_m3'),
                    total_kwh=Sum('consumo_luz_kwh'),
                    total_gas=Sum('consumo_gas_m3'),
                )
            }
            for servicio in servicios_consumo:
                valores = [
                    float(
                        agregados_periodo.get((anio, mes), {}).get(servicio['total_key'])
                        or 0
                    )
                    for anio, mes, _ in periodos_consumo
                ]
                primero = valores[0] if valores else 0
                ultimo_valor = valores[-1] if valores else 0
                delta = ultimo_valor - primero
                delta_pct = (delta / primero * 100) if primero else 0
                consumo_evolucion.append({
                    **servicio,
                    'valores': valores,
                    'puntos': self._linea_svg(valores),
                    'valor_actual': ultimo_valor,
                    'delta': delta,
                    'delta_pct': delta_pct,
                })

        # tareas pendientes y kpis operativos
        avances_pendientes = AvanceConstructivo.objects.filter(
            validado_admin=False,
        ).count()
        prorrogas_pendientes = SolicitudProrroga.objects.filter(
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        ).count()
        solicitudes_evaluacion = Empresa.objects.filter(
            estado=Empresa.Estado.EN_EVALUACION,
        ).count()
        solicitudes_preaprobadas = Empresa.objects.filter(
            estado=Empresa.Estado.PRE_APROBADO,
        ).count()

        hoy = timezone.now().date()
        limite = hoy + timedelta(days=30)
        obras_activas = Empresa.objects.filter(
            estado__in=[Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION],
        ).count()
        obras_finalizadas_sin_escritura = Empresa.objects.filter(
            estado=Empresa.Estado.FINALIZADO,
        ).count()
        obras_vencidas = Empresa.objects.filter(
            estado__in=[Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION],
            fecha_limite_obra__lt=hoy,
        ).count()
        avances_por_empresa = list(
            Empresa.objects.filter(
                estado__in=[
                    Empresa.Estado.RADICADA,
                    Empresa.Estado.EN_CONSTRUCCION,
                    Empresa.Estado.FINALIZADO,
                    Empresa.Estado.ESCRITURADO,
                ],
            ).annotate(
                max_avance_validado=Max(
                    'avances_constructivos__porcentaje_declarado',
                    filter=Q(avances_constructivos__validado_admin=True),
                )
            )
            .values_list('max_avance_validado', flat=True)
        )
        if avances_por_empresa:
            avance_promedio = sum(
                float(valor or 0) for valor in avances_por_empresa
            ) / len(avances_por_empresa)
        else:
            avance_promedio = 0
        kpis_operativos = [
            {
                'label': 'Avance promedio',
                'valor': f'{avance_promedio:.0f}%',
                'detalle': 'avance validado sobre empresas activas',
                'icono': 'bi-graph-up-arrow',
                'tono': 'verde',
                'href': action_url('core:solicitud_list', grupo='con_avance'),
            },
            {
                'label': 'Obras activas',
                'valor': obras_activas,
                'detalle': 'radicadas o en construccion',
                'icono': 'bi-hammer',
                'tono': 'azul',
                'href': action_url('core:solicitud_list', grupo='obras_activas'),
            },
            {
                'label': 'Finalizadas',
                'valor': obras_finalizadas_sin_escritura,
                'detalle': 'pendientes de escrituracion',
                'icono': 'bi-check2-circle',
                'tono': 'verde',
                'href': action_url('core:solicitud_list', estado=Empresa.Estado.FINALIZADO),
            },
            {
                'label': 'Vencidas',
                'valor': obras_vencidas,
                'detalle': 'con plazo de obra excedido',
                'icono': 'bi-exclamation-triangle',
                'tono': 'rojo' if obras_vencidas else 'gris',
                'href': action_url('core:solicitud_list', grupo='vencidas'),
            },
            {
                'label': 'Preaprobadas',
                'valor': solicitudes_preaprobadas,
                'detalle': 'listas para evaluar adjudicacion',
                'icono': 'bi-clipboard-check',
                'tono': 'amarillo',
                'href': action_url('core:solicitud_list', estado=Empresa.Estado.PRE_APROBADO),
            },
        ]
        # obras proximas a vencer (30 dias)
        proximos_vencer = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__lte=limite,
            fecha_limite_obra__gte=hoy,
        ).prefetch_related('empleados')
        proximos_vencer_count = proximos_vencer.count()
        tareas_pendientes = [
            {
                'label': 'Solicitudes en evaluación',
                'valor': solicitudes_evaluacion,
                'href': action_url('core:solicitud_list', estado=Empresa.Estado.EN_EVALUACION),
            },
            {
                'label': 'Avances por validar',
                'valor': avances_pendientes,
                'href': action_url('core:avances_pendientes'),
            },
            {
                'label': 'Prórrogas por resolver',
                'valor': prorrogas_pendientes,
                'href': action_url('core:prorrogas_pendientes'),
            },
            {
                'label': 'Obras por vencer (30 días)',
                'valor': proximos_vencer_count,
                'href': action_url('core:solicitud_list', grupo='proximas_vencer'),
            },
        ]
        obras_semaforo = []
        obras_con_plazo = Empresa.objects.filter(
            estado__in=[Empresa.Estado.RADICADA, Empresa.Estado.EN_CONSTRUCCION],
            fecha_limite_obra__isnull=False,
        ).order_by('fecha_limite_obra', 'razon_social')
        for obra in obras_con_plazo:
            dias = (obra.fecha_limite_obra - hoy).days
            if dias <= 7:
                nivel = 'rojo'
                nivel_label = 'Urgente'
            elif dias <= 30:
                nivel = 'amarillo'
                nivel_label = 'Próxima'
            else:
                nivel = 'verde'
                nivel_label = 'Sin urgencia'
            obras_semaforo.append({
                'empresa': obra,
                'dias': dias,
                'nivel': nivel,
                'nivel_label': nivel_label,
            })

        ctx.update({
            'empresas': empresas,
            'total_empresas': empresas.count(),
            'total_lotes': total_lotes,
            'lotes_en_uso': lotes_en_uso,
            'lotes_disponibles': lotes_disponibles,
            'lotes_reserva': lotes_reserva,
            'ocupacion_total_href': ocupacion_total_href,
            'puede_gestionar_dashboard': puede_gestionar,
            'pct_ocupacion': pct_ocupacion,
            'empresas_por_estado': empresas_por_estado,
            'categorias': categorias,
            'categorias_gradient': categorias_gradient,
            'rubros': rubros,
            'rubros_gradient': rubros_gradient,
            'ocupacion_items': ocupacion_items,
            'ocupacion_gradient': ocupacion_gradient,
            'periodos_consumo': periodos_consumo,
            'periodos_consumo_labels': [label for _, _, label in periodos_consumo],
            'consumo_evolucion': consumo_evolucion,
            'avances_pendientes': avances_pendientes,
            'prorrogas_pendientes': prorrogas_pendientes,
            'solicitudes_evaluacion': solicitudes_evaluacion,
            'solicitudes_preaprobadas': solicitudes_preaprobadas,
            'kpis_operativos': kpis_operativos,
            'tareas_pendientes': tareas_pendientes,
            'proximos_vencer': proximos_vencer,
            'obras_semaforo': obras_semaforo,
        })
        return ctx


 # editor visual de mapa (admin)
class MapaEditorView(AdminEnrepaviMixin, TemplateView):
    """editor visual interactivo del mapa de lotes. solo admin."""
    template_name = 'core/mapa_editor.html'

    def get_context_data(self, **kwargs):
        import json
        ctx = super().get_context_data(**kwargs)
        ctx['mapa_viewbox_w'] = VIEWBOX_W
        ctx['mapa_viewbox_h'] = VIEWBOX_H
        ctx['mapa_servidumbre_y'] = SERVIDUMBRE_Y
        ctx['mapa_lotes_json'] = json.dumps(build_mapa_data(Lote.objects.all()))
        return ctx


class MapaEditorSaveView(AdminEnrepaviMixin, View):
    """guarda posiciones svg de los lotes desde el editor visual (ajax post)."""
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'json invalido'}, status=400)
        lotes_data = data.get('lotes', [])
        if not lotes_data:
            return JsonResponse({'ok': False, 'error': 'sin datos'}, status=400)
        count = 0
        for item in lotes_data:
            nro = item.get('nro')
            if nro is None:
                continue
            updated = Lote.objects.filter(nro_parcela=nro).update(
                mapa_x=item.get('x'),
                mapa_y=item.get('y'),
                mapa_w=item.get('w'),
                mapa_h=item.get('h'),
            )
            count += updated
        return JsonResponse({'ok': True, 'updated': count})


 # reportes pdf hu-15

def _pdf_response(filename):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _build_pdf(response, titulo, secciones):
    """
    helper para generar un pdf con reportlab.
    secciones: lista de tuplas (subtitulo_opcional, headers, filas) o
    (subtitulo, mensaje_texto)
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    doc = SimpleDocTemplate(
        response, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='TituloGpiv', parent=styles['Title'],
        fontSize=16, textColor=colors.HexColor('#6ac64f'),
        spaceAfter=6, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='SubGpiv', parent=styles['Heading3'],
        fontSize=11, textColor=colors.HexColor('#6ac64f'),
        spaceBefore=10, spaceAfter=4,
    ))
    elementos = []
    elementos.append(Paragraph(titulo, styles['TituloGpiv']))
    elementos.append(Paragraph(
        f'Generado el {timezone.now().strftime("%d/%m/%Y %H:%M")} — GPIV Viedma',
        styles['Italic'],
    ))
    elementos.append(Spacer(1, 0.4 * cm))

    for seccion in secciones:
        if len(seccion) == 2:
            subtitulo, texto = seccion
            if subtitulo:
                elementos.append(Paragraph(subtitulo, styles['SubGpiv']))
            elementos.append(Paragraph(texto, styles['Normal']))
            elementos.append(Spacer(1, 0.3 * cm))
            continue
        subtitulo, headers, filas = seccion
        if subtitulo:
            elementos.append(Paragraph(subtitulo, styles['SubGpiv']))
        data = [headers] + filas if headers else filas
        tabla = Table(data, repeatRows=1 if headers else 0)
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6ac64f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla)
        elementos.append(Spacer(1, 0.4 * cm))

    doc.build(elementos)


class ReporteOcupacionView(AdminEnrepaviMixin, View):
    """reporte pdf de ocupacion del parque"""
    def get(self, request):
        response = _pdf_response('reporte_ocupacion.pdf')
        lotes = Lote.objects.select_related('empresa').order_by('nro_parcela')

        secciones = []
        estados_orden = [
            (Lote.Estado.DISPONIBLE, 'Lotes Disponibles'),
            (Lote.Estado.EN_USO, 'Lotes En Uso'),
            (Lote.Estado.RESERVA_FISCAL, 'Reserva Fiscal'),
        ]
        headers = ['Parcela', 'Superficie (m²)', 'Estado', 'Empresa']
        for estado, titulo in estados_orden:
            grupo = [l for l in lotes if l.estado == estado]
            filas = [[
                f'{l.nro_parcela:03d}',
                f'{l.superficie_m2:,.2f}',
                l.get_estado_display(),
                l.empresa.razon_social if l.empresa else '—',
            ] for l in grupo]
            if filas:
                secciones.append((f'{titulo} ({len(grupo)})', headers, filas))

        superficie_total = sum((l.superficie_m2 for l in lotes), start=0) or 0
        superficie_en_uso = sum(
            (l.superficie_m2 for l in lotes if l.estado == Lote.Estado.EN_USO),
            start=0,
        ) or 0
        pct = (superficie_en_uso / superficie_total * 100) if superficie_total else 0
        resumen_headers = ['Indicador', 'Valor']
        resumen_filas = [
            ['Total de lotes', str(lotes.count())],
            ['Superficie total', f'{superficie_total:,.2f} m²'],
            ['Superficie en uso', f'{superficie_en_uso:,.2f} m²'],
            ['Porcentaje de ocupación', f'{pct:.1f}%'],
        ]
        secciones.append(('Totales', resumen_headers, resumen_filas))

        _build_pdf(response, 'Reporte de Ocupación del Parque Industrial', secciones)
        return response


class ReporteEmpresasView(AdminEnrepaviMixin, View):
    """reporte pdf de empresas activas"""
    def get(self, request):
        response = _pdf_response('reporte_empresas.pdf')
        excluidos = [
            Empresa.Estado.EN_EVALUACION,
            Empresa.Estado.RECHAZADO,
            Empresa.Estado.HISTORICO_BAJA,
        ]
        empresas = Empresa.objects.exclude(
            estado__in=excluidos,
        ).prefetch_related('lotes').order_by('razon_social')

        headers = ['Razón Social', 'CUIT', 'Rubro', 'Categoría', 'Estado', 'Parcela']
        filas = []
        for e in empresas:
            lote = e.lotes.first()
            filas.append([
                e.razon_social,
                e.cuit,
                e.get_rubro_display(),
                e.get_categoria_industrial_display(),
                e.get_estado_display(),
                f'{lote.nro_parcela:03d}' if lote else '—',
            ])

        if not filas:
            secciones = [(None, 'No hay empresas activas registradas.')]
        else:
            secciones = [(f'{len(filas)} empresa(s) activa(s)', headers, filas)]
        _build_pdf(response, 'Reporte de Empresas Activas', secciones)
        return response


class ReporteConsumoView(AdminEnrepaviMixin, View):
    """reporte pdf de consumos del ultimo periodo cargado"""
    def get(self, request):
        response = _pdf_response('reporte_consumos.pdf')
        ultimo = ConsumoServicio.objects.order_by(
            '-periodo_anio', '-periodo_mes'
        ).first()

        if not ultimo:
            _build_pdf(
                response, 'Reporte de Consumo de Servicios',
                [(None, 'Sin datos de consumo cargados.')],
            )
            return response

        consumos = ConsumoServicio.objects.filter(
            periodo_mes=ultimo.periodo_mes,
            periodo_anio=ultimo.periodo_anio,
        ).select_related('empresa').order_by('empresa__razon_social')

        headers = [
            'Empresa', 'Agua Potable (m³)', 'Agua Cruda (m³)',
            'Electricidad (kWh)', 'Gas (m³)',
        ]
        filas = []

        def _fmt(v):
            return f'{v:,.2f}' if v is not None else '—'

        for c in consumos:
            filas.append([
                c.empresa.razon_social,
                _fmt(c.consumo_agua_potable_m3),
                _fmt(c.consumo_agua_cruda_m3),
                _fmt(c.consumo_luz_kwh),
                _fmt(c.consumo_gas_m3),
            ])

        periodo = f'{ultimo.periodo_mes:02d}/{ultimo.periodo_anio}'
        secciones = [(f'Período: {periodo}', headers, filas)]
        _build_pdf(response, 'Reporte de Consumo de Servicios', secciones)
        return response


 # 
 # TICKETERA / MENSAJERIA INTERNA
 # 

class TicketListView(LoginRequiredMixin, ListView):
    """Listado de tickets del usuario logueado."""
    model = Ticket
    template_name = 'core/ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 15

    def get_queryset(self):
        return Ticket.objects.filter(
            creador=self.request.user,
            is_active=True
        ).order_by('-fecha_actualizacion')


class TicketCreateView(LoginRequiredMixin, CreateView):
    """Crear un nuevo ticket por parte de un usuario."""
    model = Ticket
    form_class = TicketCreateForm
    template_name = 'core/ticket_form.html'
    success_url = reverse_lazy('core:ticket_list')

    def form_valid(self, form):
        form.instance.creador = self.request.user
        response = super().form_valid(form)
        
        # Crear el primer mensaje con el texto inicial
        mensaje_texto = form.cleaned_data.get('mensaje_inicial')
        if mensaje_texto:
            mensaje = MensajeTicket.objects.create(
                ticket=self.object,
                autor=self.request.user,
                contenido=mensaje_texto
            )
            notificar_ticket_mensaje(self.object, mensaje)
        
        messages.success(self.request, 'Consulta enviada correctamente.')
        return response


class TicketExternoCreateView(View):
    """Recibe consultas desde la landing page vía AJAX."""
    def post(self, request, *args, **kwargs):
        form = TicketExternoForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.categoria = Ticket.Categoria.EXTERNA
            ticket.creador = None
            ticket.save()
            
            # Crear el primer mensaje
            MensajeTicket.objects.create(
                ticket=ticket,
                autor=None, # no hay usuario
                contenido=form.cleaned_data['mensaje']
            )
            
            # Notificar al admin sobre este nuevo ticket externo
            # Usaremos una instancia temporal dummy o el servicio manejará autor=None
            # Para simplificar, pasamos el primer mensaje (autor=None)
            mensaje = ticket.mensajes.first()
            notificar_ticket_mensaje(ticket, mensaje)

            return JsonResponse({'status': 'ok'})
        else:
            return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


def _anotar_mensajes_es_admin(mensajes):
    """marca cada mensaje con .es_admin para que el template no tenga que
    razonar sobre grupos. evita la logica fragil de 'request.user.groups.all.0
    in mensaje.autor.groups.all' que misclasifica casos comunes."""
    mensajes = list(mensajes.select_related('autor').prefetch_related('autor__groups'))
    for m in mensajes:
        autor = m.autor
        m.es_admin = bool(
            autor and (
                autor.is_superuser
                or autor.groups.filter(name='ADMIN_ENREPAVI').exists()
            )
        )
    return mensajes


class TicketDetailView(LoginRequiredMixin, DetailView):
    """Detalle de un ticket y envío de respuestas (usuario normal)."""
    model = Ticket
    template_name = 'core/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.filter(creador=self.request.user, is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mensajes_qs = self.object.mensajes.filter(is_active=True).order_by('fecha_creacion')
        ctx['mensajes'] = _anotar_mensajes_es_admin(mensajes_qs)
        ctx['form'] = MensajeTicketForm()
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.estado == Ticket.Estado.CERRADO:
            messages.error(request, 'No se puede responder un ticket cerrado.')
            return redirect('core:ticket_detail', pk=self.object.pk)

        form = MensajeTicketForm(request.POST)
        if form.is_valid():
            mensaje = form.save(commit=False)
            mensaje.ticket = self.object
            mensaje.autor = request.user
            mensaje.save()
            
            # Notificar vía email
            notificar_ticket_mensaje(self.object, mensaje)
            
            # Actualizar fecha del ticket
            self.object.fecha_actualizacion = timezone.now()
            # Si estaba cerrado, lo reabre? Según el doc el admin lo cierra. 
            # Dejaremos que siga Abierto.
            self.object.save(update_fields=['fecha_actualizacion'])
            
            messages.success(request, 'Mensaje enviado.')
            return redirect('core:ticket_detail', pk=self.object.pk)
            
        ctx = self.get_context_data(object=self.object)
        ctx['form'] = form
        return self.render_to_response(ctx)


class AdminTicketListView(AdminEnrepaviMixin, ListView):
    """Bandeja de entrada del administrador."""
    model = Ticket
    template_name = 'core/admin_ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 20

    def get_queryset(self):
        qs = Ticket.objects.filter(is_active=True).select_related('creador')
        estado = self.request.GET.get('estado')
        if estado and estado in dict(Ticket.Estado.choices):
            qs = qs.filter(estado=estado)
        return qs.order_by('-fecha_actualizacion')
        
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['estados_choices'] = Ticket.Estado.choices
        ctx['filtro_estado'] = self.request.GET.get('estado', '')
        return ctx


class AdminTicketCreateView(AdminEnrepaviMixin, View):
    """Crea un ticket iniciado por administración para pedir documentación."""
    template_name = 'core/admin_ticket_form.html'

    def _get_pk_param(self, name):
        value = self.request.GET.get(name)
        if value and value.isdigit():
            return int(value)
        return None

    def _add_destinatario(self, choices, destinatarios, key, label, data):
        if key in destinatarios:
            return
        choices.append((key, label))
        destinatarios[key] = data

    def _add_usuario(self, choices, destinatarios, usuario, label_prefix='Usuario'):
        email = usuario.email or 'sin email'
        nombre = usuario.get_full_name() or usuario.username
        self._add_destinatario(
            choices,
            destinatarios,
            f'user:{usuario.pk}',
            f'{label_prefix}: {nombre} ({email})',
            {'tipo': 'user', 'usuario': usuario},
        )

    def _add_empresa_destinatarios(self, choices, destinatarios, empresa):
        if empresa.correo_electronico:
            self._add_destinatario(
                choices,
                destinatarios,
                f'empresa_email:{empresa.pk}',
                f'Empresa: {empresa.razon_social} ({empresa.correo_electronico})',
                {
                    'tipo': 'external',
                    'nombre': empresa.razon_social,
                    'email': empresa.correo_electronico,
                    'telefono': empresa.telefono,
                },
            )
        titular = empresa.empleados.filter(
            rol_interno=CustomUser.RolInterno.TITULAR,
            is_active=True,
        ).order_by('username').first()
        if titular:
            self._add_usuario(choices, destinatarios, titular, 'Titular')

    def _build_contexto_destino(self):
        choices = []
        destinatarios = {}
        source_label = ''
        initial_asunto = 'Solicitud de documentación adicional'

        solicitud_pk = self._get_pk_param('solicitud_acceso')
        user_pk = self._get_pk_param('user')
        empresa_pk = self._get_pk_param('empresa')

        if solicitud_pk:
            solicitud = get_object_or_404(SolicitudAcceso, pk=solicitud_pk)
            self._add_destinatario(
                choices,
                destinatarios,
                f'solicitud_acceso:{solicitud.pk}',
                f'{solicitud.nombre_apellido} ({solicitud.email_institucional})',
                {
                    'tipo': 'external',
                    'nombre': solicitud.nombre_apellido,
                    'email': solicitud.email_institucional,
                    'telefono': solicitud.telefono,
                },
            )
            source_label = (
                f'Solicitud de acceso #{solicitud.pk} - {solicitud.organizacion}'
            )
            initial_asunto = f'Documentación adicional - {solicitud.organizacion}'
        elif user_pk:
            usuario = get_object_or_404(
                CustomUser.objects.select_related('empresa'),
                pk=user_pk,
            )
            self._add_usuario(choices, destinatarios, usuario)
            if usuario.empresa_id:
                self._add_empresa_destinatarios(choices, destinatarios, usuario.empresa)
                source_label = (
                    f'Usuario {usuario.username} - {usuario.empresa.razon_social}'
                )
            else:
                source_label = f'Usuario {usuario.username}'
        elif empresa_pk:
            empresa = get_object_or_404(Empresa, pk=empresa_pk)
            self._add_empresa_destinatarios(choices, destinatarios, empresa)
            for usuario in empresa.empleados.filter(is_active=True).order_by('username'):
                self._add_usuario(choices, destinatarios, usuario)
            source_label = f'Empresa {empresa.razon_social}'
            initial_asunto = f'Documentación adicional - {empresa.razon_social}'

        return {
            'choices': choices,
            'destinatarios': destinatarios,
            'source_label': source_label,
            'initial_asunto': initial_asunto,
        }

    def get(self, request):
        destino_ctx = self._build_contexto_destino()
        if not destino_ctx['choices']:
            messages.error(request, 'No se encontró un destinatario para contactar.')
            return redirect('core:admin_gestion_usuarios')

        form = AdminTicketCreateForm(
            destinatario_choices=destino_ctx['choices'],
            initial={
                'categoria': Ticket.Categoria.ADMINISTRATIVA,
                'asunto': destino_ctx['initial_asunto'],
            },
        )
        return render(request, self.template_name, {
            'form': form,
            'source_label': destino_ctx['source_label'],
        })

    def post(self, request):
        destino_ctx = self._build_contexto_destino()
        if not destino_ctx['choices']:
            messages.error(request, 'No se encontró un destinatario para contactar.')
            return redirect('core:admin_gestion_usuarios')

        form = AdminTicketCreateForm(
            request.POST,
            destinatario_choices=destino_ctx['choices'],
        )
        if form.is_valid():
            destino = destino_ctx['destinatarios'][form.cleaned_data['destinatario']]
            ticket_kwargs = {
                'asunto': form.cleaned_data['asunto'],
                'categoria': form.cleaned_data['categoria'],
            }
            if destino['tipo'] == 'user':
                ticket_kwargs['creador'] = destino['usuario']
            else:
                ticket_kwargs.update({
                    'creador': None,
                    'nombre_contacto': destino['nombre'],
                    'email_contacto': destino['email'],
                    'telefono_contacto': destino.get('telefono') or '',
                })

            ticket = Ticket.objects.create(**ticket_kwargs)
            mensaje = MensajeTicket.objects.create(
                ticket=ticket,
                autor=request.user,
                contenido=form.cleaned_data['mensaje_inicial'],
            )
            notificar_ticket_mensaje(ticket, mensaje)
            messages.success(request, 'Mensaje enviado y ticket creado correctamente.')
            return redirect('core:admin_ticket_detail', pk=ticket.pk)

        return render(request, self.template_name, {
            'form': form,
            'source_label': destino_ctx['source_label'],
        })


class AdminTicketDetailView(AdminEnrepaviMixin, DetailView):
    """Detalle de ticket para el admin."""
    model = Ticket
    template_name = 'core/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mensajes_qs = self.object.mensajes.filter(is_active=True).order_by('fecha_creacion')
        ctx['mensajes'] = _anotar_mensajes_es_admin(mensajes_qs)
        ctx['form'] = MensajeTicketForm()
        ctx['is_admin_view'] = True
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        # cerrar/abrir ticket: solo para tickets internos (con creador).
        # los externos se cierran automaticamente al responder (linea 1209+),
        # nunca de forma manual. el template ya oculta los botones pero hay
        # que reforzar del lado servidor por si alguien envia el POST a mano.
        if 'cerrar_ticket' in request.POST:
            if not self.object.creador:
                messages.error(request, 'Los tickets externos no se pueden cerrar manualmente.')
                return redirect('core:admin_ticket_detail', pk=self.object.pk)
            self.object.estado = Ticket.Estado.CERRADO
            self.object.save(update_fields=['estado', 'fecha_actualizacion'])
            messages.success(request, 'El ticket ha sido cerrado.')
            return redirect('core:admin_ticket_detail', pk=self.object.pk)
            
        if 'abrir_ticket' in request.POST:
            if not self.object.creador:
                messages.error(request, 'Los tickets externos no se pueden reabrir.')
                return redirect('core:admin_ticket_detail', pk=self.object.pk)
            self.object.estado = Ticket.Estado.ABIERTO
            self.object.save(update_fields=['estado', 'fecha_actualizacion'])
            messages.success(request, 'El ticket ha sido reabierto.')
            return redirect('core:admin_ticket_detail', pk=self.object.pk)

        # Enviar mensaje
        if self.object.estado == Ticket.Estado.CERRADO:
            messages.error(request, 'El ticket está cerrado. Reábrelo para enviar un mensaje.')
            return redirect('core:admin_ticket_detail', pk=self.object.pk)

        form = MensajeTicketForm(request.POST)
        if form.is_valid():
            mensaje = form.save(commit=False)
            mensaje.ticket = self.object
            mensaje.autor = request.user
            mensaje.save()
            
            # Notificar vía email
            notificar_ticket_mensaje(self.object, mensaje)
            
            # Si es ticket externo, se cierra automáticamente
            if not self.object.creador:
                self.object.estado = Ticket.Estado.CERRADO
            
            self.object.fecha_actualizacion = timezone.now()
            self.object.save(update_fields=['estado', 'fecha_actualizacion'])
            
            messages.success(request, 'Mensaje enviado.')
            return redirect('core:admin_ticket_detail', pk=self.object.pk)
            
        ctx = self.get_context_data(object=self.object)
        ctx['form'] = form
        return self.render_to_response(ctx)


class TicketSoftDeleteView(AdminEnrepaviMixin, View):
    """Baja lógica de un ticket por parte del admin."""
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk, is_active=True)
        ticket.soft_delete()
        messages.success(request, f'El ticket #{ticket.id} fue eliminado.')
        return redirect('core:admin_ticket_list')


# inventario de activos del ENREPAVI
class InventarioListView(AdminEnrepaviMixin, ListView):
    """Lista paginada de activos de inventario con filtros por categoría y estado.

    Por defecto muestra solo los activos vigentes (``activo=True``). El parámetro
    ``mostrar_bajas=1`` incluye también los dados de baja para auditoría.
    """
    model = ActivoInventario
    template_name = 'core/inventario_list.html'
    context_object_name = 'activos'
    paginate_by = 20

    def get_queryset(self):
        qs = ActivoInventario.objects.select_related('responsable')

        # filtro de bajas lógicas
        mostrar_bajas = self.request.GET.get('mostrar_bajas') == '1'
        if not mostrar_bajas:
            qs = qs.filter(activo=True)

        categoria = self.request.GET.get('categoria')
        if categoria and categoria in dict(ActivoInventario.Categoria.choices):
            qs = qs.filter(categoria=categoria)

        estado = self.request.GET.get('estado')
        if estado and estado in dict(ActivoInventario.Estado.choices):
            qs = qs.filter(estado=estado)

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(codigo_inventario__icontains=q)
                | Q(marca__icontains=q)
                | Q(numero_serie__icontains=q)
            )

        return qs.order_by('categoria', 'codigo_inventario')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categorias_choices'] = ActivoInventario.Categoria.choices
        ctx['estados_choices'] = ActivoInventario.Estado.choices
        ctx['filtro_categoria'] = self.request.GET.get('categoria', '')
        ctx['filtro_estado'] = self.request.GET.get('estado', '')
        ctx['filtro_q'] = self.request.GET.get('q', '')
        ctx['mostrar_bajas'] = self.request.GET.get('mostrar_bajas') == '1'
        return ctx


class InventarioDetailView(AdminEnrepaviMixin, DetailView):
    """Detalle completo de un activo de inventario."""
    model = ActivoInventario
    template_name = 'core/inventario_detail.html'
    context_object_name = 'activo'

    def get_queryset(self):
        return ActivoInventario.objects.select_related(
            'responsable', 'registrado_por', 'dado_de_baja_por',
        )


class InventarioCreateView(AdminEnrepaviMixin, CreateView):
    """Alta de un nuevo activo de inventario."""
    model = ActivoInventario
    form_class = ActivoInventarioForm
    template_name = 'core/inventario_form.html'
    success_url = reverse_lazy('core:inventario_list')

    def form_valid(self, form):
        form.instance.registrado_por = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Activo "{self.object.nombre}" registrado con código {self.object.codigo_inventario}.'
        )
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = 'Registrar Activo'
        ctx['es_nuevo'] = True
        return ctx


class InventarioUpdateView(AdminEnrepaviMixin, UpdateView):
    """Edición de un activo de inventario existente. Solo activos vigentes."""
    model = ActivoInventario
    form_class = ActivoInventarioForm
    template_name = 'core/inventario_form.html'

    def get_queryset(self):
        return ActivoInventario.objects.filter(activo=True)

    def get_success_url(self):
        return reverse_lazy('core:inventario_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            f'Activo "{self.object.nombre}" ({self.object.codigo_inventario}) actualizado.'
        )
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = f'Editar: {self.object.nombre}'
        ctx['es_nuevo'] = False
        return ctx


class InventarioBajaView(AdminEnrepaviMixin, View):
    """Baja lógica de un activo de inventario (rf-inv-05).

    No elimina el registro de la base de datos. Marca ``activo=False``,
    guarda el motivo, la fecha y el usuario responsable de la baja.
    La vista solo acepta activos vigentes; los ya dados de baja redirigen
    al detalle con un mensaje informativo.
    """

    def get(self, request, pk):
        activo = get_object_or_404(ActivoInventario, pk=pk)
        if not activo.activo:
            messages.info(request, f'"{activo.nombre}" ya figura como dado de baja.')
            return redirect('core:inventario_detail', pk=pk)
        form = BajaActivoForm()
        return render(request, 'core/inventario_baja_confirm.html', {
            'activo': activo,
            'form': form,
        })

    def post(self, request, pk):
        activo = get_object_or_404(ActivoInventario, pk=pk, activo=True)
        form = BajaActivoForm(request.POST)
        if form.is_valid():
            activo.activo = False
            activo.motivo_baja = form.cleaned_data['motivo_baja']
            activo.fecha_baja = timezone.now().date()
            activo.dado_de_baja_por = request.user
            activo.estado = ActivoInventario.Estado.DE_BAJA
            activo.save(update_fields=[
                'activo', 'motivo_baja', 'fecha_baja', 'dado_de_baja_por', 'estado',
            ])
            messages.success(
                request,
                f'Activo "{activo.nombre}" ({activo.codigo_inventario}) dado de baja correctamente.'
            )
            return redirect('core:inventario_list')
        return render(request, 'core/inventario_baja_confirm.html', {
            'activo': activo,
            'form': form,
        })


# ──────────────────────────────────────────────────────────────────────────────
# RBAC: Gestión de equipo de empresa (solo TITULAR)
# ──────────────────────────────────────────────────────────────────────────────

class EmpresaUsuariosView(TitularEmpresaMixin, TemplateView):
    """
    Panel del TITULAR: lista todos los miembros de su empresa.
    Desde aquí puede invitar, remover o iniciar la transferencia de titularidad.
    """
    template_name = 'core/empresa_usuarios.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        empresa = self.request.user.empresa
        ctx['empresa'] = empresa
        ctx['miembros'] = empresa.empleados.order_by('rol_interno', 'username')
        ctx['RolInterno'] = CustomUser.RolInterno
        return ctx


class EmpresaInvitarView(TitularEmpresaMixin, View):
    """
    TITULAR: busca un usuario existente del grupo EMPRESA (sin empresa asignada)
    por username o email y lo asocia a la empresa como ESTÁNDAR.
    GET  → formulario de búsqueda
    POST → ejecuta la invitación
    """
    template_name = 'core/empresa_invitar.html'

    def get(self, request):
        return render(request, self.template_name, {
            'empresa': request.user.empresa,
        })

    def post(self, request):
        empresa = request.user.empresa
        identificador = request.POST.get('identificador', '').strip()

        if not identificador:
            messages.error(request, 'Ingresá un nombre de usuario o email.')
            return render(request, self.template_name, {'empresa': empresa})

        base_qs = CustomUser.objects.filter(
            groups__name='EMPRESA',
            empresa__isnull=True,
        )

        # Priorizar username (único). Email puede no ser único.
        candidato = base_qs.filter(username__iexact=identificador).first()
        if candidato is None:
            try:
                candidato = base_qs.get(email__iexact=identificador)
            except MultipleObjectsReturned:
                messages.error(
                    request,
                    'Hay múltiples usuarios sin empresa con ese email. '
                    'Usá el nombre de usuario para invitar correctamente.'
                )
                return render(request, self.template_name, {'empresa': empresa})
            except CustomUser.DoesNotExist:
                candidato = None

        if candidato is None:
            messages.error(
                request,
                f'No se encontró un usuario EMPRESA sin empresa asignada '
                f'con el identificador «{identificador}».'
            )
            return render(request, self.template_name, {'empresa': empresa})

        try:
            invitar_usuario(empresa, request.user, candidato)
            messages.success(
                request,
                f'Usuario «{candidato.username}» invitado como Estándar correctamente.'
            )
        except RBACError as exc:
            messages.error(request, str(exc))

        return redirect('core:empresa_usuarios')


class EmpresaTransferirView(TitularEmpresaMixin, View):
    """
    TITULAR: transfiere su rol a un usuario ESTÁNDAR de la misma empresa.
    GET  → formulario de selección
    POST → ejecuta la transferencia atómica
    """
    template_name = 'core/empresa_transferir.html'

    def get(self, request):
        empresa = request.user.empresa
        estandares = empresa.empleados.filter(
            rol_interno=CustomUser.RolInterno.ESTANDAR,
            is_active=True,
        ).order_by('username')
        return render(request, self.template_name, {
            'empresa': empresa,
            'estandares': estandares,
        })

    def post(self, request):
        empresa = request.user.empresa
        nuevo_titular_pk = request.POST.get('nuevo_titular_pk')

        if not nuevo_titular_pk:
            messages.error(request, 'Seleccioná el usuario al que querés transferir la titularidad.')
            return redirect('core:empresa_transferir')

        nuevo_titular = get_object_or_404(
            CustomUser,
            pk=nuevo_titular_pk,
            empresa=empresa,
            rol_interno=CustomUser.RolInterno.ESTANDAR,
            is_active=True,
        )

        try:
            transferir_titularidad(empresa, request.user, nuevo_titular)
            messages.success(
                request,
                f'Titularidad transferida a «{nuevo_titular.username}». '
                'Ahora sos usuario Estándar.'
            )
        except RBACError as exc:
            messages.error(request, str(exc))

        # Redirigir al panel de la empresa (ya no tiene acceso al panel de titulares)
        return redirect('core:mi_solicitud')


class EmpresaRemoverMiembroView(TitularEmpresaMixin, View):
    """
    TITULAR: remueve (desvincula) a un usuario ESTÁNDAR de la empresa.
    Solo acepta POST (no hay vista GET propia; el botón está en empresa_usuarios).
    """
    def post(self, request, pk):
        empresa = request.user.empresa
        usuario_a_remover = get_object_or_404(
            CustomUser,
            pk=pk,
            empresa=empresa,
        )

        try:
            remover_miembro(empresa, request.user, usuario_a_remover)
            messages.success(
                request,
                f'Usuario «{usuario_a_remover.username}» removido de la empresa.'
            )
        except RBACError as exc:
            messages.error(request, str(exc))

        return redirect('core:empresa_usuarios')
