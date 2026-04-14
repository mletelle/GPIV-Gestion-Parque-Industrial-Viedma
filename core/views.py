from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DetailView, View
)
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from .models import Lote, Empresa, TransicionEstado, AvanceConstructivo, SolicitudProrroga, CustomUser
from .forms import (
    LoginForm, LoteForm, RegistroUsuarioForm,
    SolicitudRadicacionForm, RechazarSolicitudForm,
    AvanceConstructivoForm, SolicitudProrrogaForm,
    EscrituraForm, BajaEmpresaForm, RespuestaProrrogaForm,
)


 # landing publica
class LandingPageView(TemplateView):
    template_name = 'core/landing.html'


 # autenticacion
class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('core:dashboard')


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('core:landing')


 # inicio protegido
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/dashboard.html'


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


 # catalogo publico sin login, excluye reservafiscal
class CatalogoPublicoView(ListView):
    model = Lote
    template_name = 'core/catalogo_publico.html'
    context_object_name = 'lotes'
    paginate_by = 10

    def get_queryset(self):
        return Lote.objects.exclude(estado=Lote.Estado.RESERVA_FISCAL).order_by('nro_parcela')


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
        # armar secciones para mostrar los datos
        form = SolicitudRadicacionForm(instance=self.object)
        ctx['secciones'] = list(form.get_secciones())
        ctx['lote'] = self.object.lotes.first()
        ctx['avances'] = self.object.avances_constructivos.all()
        ctx['prorrogas'] = self.object.prorrogas.select_related('resuelta_por').all()
        # verificar si tiene avance 100% validado para habilitar finalizacion
        ctx['tiene_avance_100_validado'] = self.object.avances_constructivos.filter(
            porcentaje_declarado=100, validado_admin=True,
        ).exists()
        return ctx


def _registrar_transicion(empresa, estado_nuevo, usuario, justificacion=''):
    """helper para registrar transicion de estado"""
    estado_anterior = empresa.estado
    empresa.estado = estado_nuevo
    empresa.save(update_fields=['estado'])
    TransicionEstado.objects.create(
        empresa=empresa,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        usuario=usuario,
        justificacion_resolucion=justificacion,
    )


class SolicitudPreAprobarView(AdminEnrepaviMixin, View):
    """accion: EnEvaluacion -> PreAprobado"""
    def post(self, request, pk):
        empresa = get_object_or_404(Empresa, pk=pk, estado=Empresa.Estado.EN_EVALUACION)
        _registrar_transicion(empresa, Empresa.Estado.PRE_APROBADO, request.user, 'Pre-aprobada por administración')
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
            _registrar_transicion(
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
        _registrar_transicion(empresa, Empresa.Estado.RADICADA, request.user, f'Adjudicada en parcela {lote.nro_parcela}')
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
            _registrar_transicion(
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
        _registrar_transicion(empresa, Empresa.Estado.FINALIZADO, request.user, 'Obra finalizada y certificada')
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
            _registrar_transicion(empresa, Empresa.Estado.ESCRITURADO, request.user, 'Escritura registrada')
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
            _registrar_transicion(
                empresa, Empresa.Estado.HISTORICO_BAJA, request.user,
                form.cleaned_data['justificacion'],
            )
            messages.success(request, f'{empresa.razon_social} dada de baja. Lote(s) liberado(s).')
            return redirect('core:solicitud_list')
        return render(request, 'core/baja_empresa.html', {'empresa': empresa, 'form': form})
