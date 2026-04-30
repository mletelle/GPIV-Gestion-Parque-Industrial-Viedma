from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DetailView, View
)
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from .models import (
    Lote, Empresa, TransicionEstado, AvanceConstructivo,
    SolicitudProrroga, CustomUser, ConsumoServicio,
    Ticket, MensajeTicket,
)
from .services import (
    registrar_transicion, get_servicio_proveedor,
    SERVICIO_CAMPOS, SERVICIO_LABELS,
    notificar_ticket_mensaje,
)
from .forms import (
    LoginForm, LoteForm, RegistroUsuarioForm,
    SolicitudRadicacionForm, RechazarSolicitudForm,
    AvanceConstructivoForm, SolicitudProrrogaForm,
    EscrituraForm, BajaEmpresaForm, RespuestaProrrogaForm,
    ConsumoServicioForm, TicketCreateForm, MensajeTicketForm,
    TicketExternoForm,
)
from django import forms as django_forms


 # landing publica
class LandingPageView(TemplateView):
    template_name = 'core/landing.html'

    def get(self, request, *args, **kwargs):
        # si ya esta logueado, mandalo a su inicio: la landing es publica
        if request.user.is_authenticated:
            return redirect('core:inicio')
        return super().get(request, *args, **kwargs)

 # autenticacion
class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

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
    """restringe acceso a usuarios del grupo EMPRESA"""
    def test_func(self):
        return self.request.user.groups.filter(name='EMPRESA').exists()


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
        user = request.user
        # redireccion por rol, admin ve el inicio con accesos rapidos
        if user.is_superuser or user.groups.filter(name='ADMIN_ENREPAVI').exists():
            return super().get(request, *args, **kwargs)
        if user.groups.filter(name='EMPRESA').exists():
            return redirect('core:mi_solicitud')
        if user.groups.filter(
            name__in=['PROVEEDOR_AGUA', 'PROVEEDOR_LUZ', 'PROVEEDOR_GAS'],
        ).exists():
            return redirect('core:consumo_list')
        if user.groups.filter(name='ORGANISMO_PUBLICO').exists():
            return redirect('core:consulta_parque')
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
        ).select_related('usuario')
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

class RegistroView(CreateView):
    """registro de usuario empresa, le asigna grupo EMPRESA"""
    template_name = 'core/registro.html'
    form_class = RegistroUsuarioForm
    success_url = reverse_lazy('core:login')

    def form_valid(self, form):
        response = super().form_valid(form)
        grupo = Group.objects.get(name='EMPRESA')
        self.object.groups.add(grupo)
        messages.success(self.request, 'Cuenta creada. Iniciá sesión para completar tu solicitud.')
        return response


class SolicitudCreateView(EmpresaMixin, CreateView):
    """formulario de solicitud de radicacion, solo para empresas sin solicitud previa"""
    template_name = 'core/solicitud_form.html'
    form_class = SolicitudRadicacionForm
    success_url = reverse_lazy('core:mi_solicitud')

    def test_func(self):
        # empresa sin solicitud previa
        if not super().test_func():
            return False
        return not hasattr(self.request.user, 'empresa')

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
        empresa = getattr(self.request.user, 'empresa', None)
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
            # ultimos 12 consumos declarados
            ctx['consumos'] = empresa.consumos.order_by(
                '-periodo_anio', '-periodo_mes'
            )[:12]
        return ctx


 # evaluacion de solicitudes admin

class SolicitudListView(AdminEnrepaviMixin, ListView):
    """listado de empresas con filtro por estado"""
    model = Empresa
    template_name = 'core/solicitud_list.html'
    context_object_name = 'solicitudes'
    paginate_by = 20

    def get_queryset(self):
        qs = Empresa.objects.select_related('usuario').order_by('-pk')
        estado = self.request.GET.get('estado')
        if estado and estado in dict(Empresa.Estado.choices):
            qs = qs.filter(estado=estado)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['estados_choices'] = Empresa.Estado.choices
        ctx['filtro_estado'] = self.request.GET.get('estado', '')
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
        return ctx


class SolicitudPreAprobarView(AdminEnrepaviMixin, View):
    """accion: EnEvaluacion -> PreAprobado"""
    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.EN_EVALUACION)
        registrar_transicion(empresa, Empresa.Estado.PRE_APROBADO, request.user, 'Pre-aprobada por administración')
        messages.success(request, f'{empresa.razon_social} pre-aprobada.')
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


 # adjudicacion de lote

class AdjudicacionView(AdminEnrepaviMixin, View):
    """adjudicar un lote a una empresa pre-aprobada"""

    def get(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.PRE_APROBADO)
        lotes = Lote.objects.filter(
            estado=Lote.Estado.DISPONIBLE,
            superficie_m2__gte=empresa.necesidad_m2,
        ).order_by('nro_parcela')
        return render(request, 'core/adjudicacion.html', {
            'empresa': empresa,
            'lotes': lotes,
        })

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.PRE_APROBADO)
        lote_id = request.POST.get('lote_id')
        lote = get_object_or_404(
            Lote, pk=lote_id, estado=Lote.Estado.DISPONIBLE,
            superficie_m2__gte=empresa.necesidad_m2,
        )
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
        empresa = getattr(self.request.user, 'empresa', None)
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
        avance = get_object_or_404(AvanceConstructivo, pk=pk, validado_admin=False)
        avance.validado_admin = True
        avance.save(update_fields=['validado_admin'])
        messages.success(request, f'Avance de {avance.empresa.razon_social} ({avance.porcentaje_declarado}%) validado.')
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
        empresa = getattr(self.request.user, 'empresa', None)
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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

        # empresas agrupadas por estado, solo estados con count>0
        empresas_por_estado = [
            (label, Empresa.objects.filter(estado=valor).count())
            for valor, label in Empresa.Estado.choices
        ]
        empresas_por_estado = [(lbl, n) for lbl, n in empresas_por_estado if n > 0]

        # distribucion por categoria industrial (solo activas)
        categorias = []
        for valor, label in Empresa.CategoriaIndustrial.choices:
            cant = empresas.filter(categoria_industrial=valor).count()
            if cant:
                categorias.append((label, cant))

        # distribucion por rubro (solo activas)
        rubros = []
        for valor, label in Empresa.Rubro.choices:
            cant = empresas.filter(rubro=valor).count()
            if cant:
                rubros.append((label, cant))

        # consumos del ultimo periodo cargado
        ultimo = ConsumoServicio.objects.order_by(
            '-periodo_anio', '-periodo_mes',
        ).first()
        consumos_periodo = None
        periodo_consumo = None
        if ultimo:
            consumos_periodo = ConsumoServicio.objects.filter(
                periodo_mes=ultimo.periodo_mes,
                periodo_anio=ultimo.periodo_anio,
            ).aggregate(
                total_agua_potable=Sum('consumo_agua_potable_m3'),
                total_agua_cruda=Sum('consumo_agua_cruda_m3'),
                total_kwh=Sum('consumo_luz_kwh'),
                total_gas=Sum('consumo_gas_m3'),
            )
            periodo_consumo = f'{ultimo.periodo_mes:02d}/{ultimo.periodo_anio}'

        # tareas pendientes
        avances_pendientes = AvanceConstructivo.objects.filter(
            validado_admin=False,
        ).count()
        prorrogas_pendientes = SolicitudProrroga.objects.filter(
            estado=SolicitudProrroga.EstadoProrroga.PENDIENTE,
        ).count()
        solicitudes_evaluacion = Empresa.objects.filter(
            estado=Empresa.Estado.EN_EVALUACION,
        ).count()

        # obras proximas a vencer (30 dias)
        hoy = timezone.now().date()
        limite = hoy + timedelta(days=30)
        proximos_vencer = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__lte=limite,
            fecha_limite_obra__gte=hoy,
        ).select_related('usuario')

        ctx.update({
            'empresas': empresas,
            'total_empresas': empresas.count(),
            'total_lotes': total_lotes,
            'lotes_en_uso': lotes_en_uso,
            'lotes_disponibles': lotes_disponibles,
            'lotes_reserva': lotes_reserva,
            'pct_ocupacion': pct_ocupacion,
            'empresas_por_estado': empresas_por_estado,
            'categorias': categorias,
            'rubros': rubros,
            'consumos_periodo': consumos_periodo,
            'periodo_consumo': periodo_consumo,
            'avances_pendientes': avances_pendientes,
            'prorrogas_pendientes': prorrogas_pendientes,
            'solicitudes_evaluacion': solicitudes_evaluacion,
            'proximos_vencer': proximos_vencer,
        })
        return ctx


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
        fontSize=16, textColor=colors.HexColor('#0b6623'),
        spaceAfter=6, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='SubGpiv', parent=styles['Heading3'],
        fontSize=11, textColor=colors.HexColor('#0b6623'),
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
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0b6623')),
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


 # =========================================
 # TICKETERA / MENSAJERIA INTERNA
 # =========================================

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


class TicketDetailView(LoginRequiredMixin, DetailView):
    """Detalle de un ticket y envío de respuestas (usuario normal)."""
    model = Ticket
    template_name = 'core/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.filter(creador=self.request.user, is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['mensajes'] = self.object.mensajes.filter(is_active=True).order_by('fecha_creacion')
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


class AdminTicketDetailView(AdminEnrepaviMixin, DetailView):
    """Detalle de ticket para el admin."""
    model = Ticket
    template_name = 'core/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['mensajes'] = self.object.mensajes.filter(is_active=True).order_by('fecha_creacion')
        ctx['form'] = MensajeTicketForm()
        ctx['is_admin_view'] = True
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        # Acción para cerrar/abrir ticket
        if 'cerrar_ticket' in request.POST:
            self.object.estado = Ticket.Estado.CERRADO
            self.object.save(update_fields=['estado', 'fecha_actualizacion'])
            messages.success(request, 'El ticket ha sido cerrado.')
            return redirect('core:admin_ticket_detail', pk=self.object.pk)
            
        if 'abrir_ticket' in request.POST:
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
