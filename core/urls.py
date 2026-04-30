from django.urls import path
from .views import (
    LandingPageView,
    CustomLoginView,
    CustomLogoutView,
    DashboardView,
    LoteListView,
    LoteCreateView,
    LoteUpdateView,
    RegistroView,
    SolicitudCreateView,
    MiSolicitudView,
    SolicitudListView,
    SolicitudDetailView,
    SolicitudPreAprobarView,
    SolicitudRechazarView,
    AdjudicacionView,
    # etapa 2
    AvanceCreateView,
    AvancesPendientesView,
    AvanceValidarView,
    ProrrogaCreateView,
    ProrrogasPendientesView,
    ProrrogaAprobarView,
    ProrrogaRechazarView,
    FinalizarObraView,
    EscrituracionView,
    BajaEmpresaView,
    # etapa 3
    ConsumoCreateView,
    ConsumoListView,
    ConsultaParqueView,
    ReporteOcupacionView,
    ReporteEmpresasView,
    ReporteConsumoView,
    # mensajeria interna (ticketera)
    TicketListView,
    TicketCreateView,
    TicketDetailView,
    AdminTicketListView,
    AdminTicketDetailView,
    TicketSoftDeleteView,
    TicketExternoCreateView,
)

app_name = 'core'

urlpatterns = [
    # publico
    path('', LandingPageView.as_view(), name='landing'),

    # autenticacion
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('registro/', RegistroView.as_view(), name='registro'),

    # inicio (protegido)
    path('inicio/', DashboardView.as_view(), name='inicio'),

    # empresa: solicitud
    path('solicitud/nueva/', SolicitudCreateView.as_view(), name='solicitud_create'),
    path('mi-solicitud/', MiSolicitudView.as_view(), name='mi_solicitud'),

    # empresa: avance constructivo
    path('avance/nuevo/', AvanceCreateView.as_view(), name='avance_create'),

    # empresa: prorroga
    path('prorroga/nueva/', ProrrogaCreateView.as_view(), name='prorroga_create'),

    # admin: gestion de lotes
    path('lotes/', LoteListView.as_view(), name='lote_list'),
    path('lotes/nuevo/', LoteCreateView.as_view(), name='lote_create'),
    path('lotes/<int:pk>/editar/', LoteUpdateView.as_view(), name='lote_update'),

    # admin: evaluacion de solicitudes
    path('solicitudes/', SolicitudListView.as_view(), name='solicitud_list'),
    path('solicitudes/<int:pk>/', SolicitudDetailView.as_view(), name='solicitud_detail'),
    path('solicitudes/<int:pk>/pre-aprobar/', SolicitudPreAprobarView.as_view(), name='solicitud_preaprobar'),
    path('solicitudes/<int:pk>/rechazar/', SolicitudRechazarView.as_view(), name='solicitud_rechazar'),
    path('solicitudes/<int:pk>/adjudicar/', AdjudicacionView.as_view(), name='adjudicacion'),
    path('solicitudes/<int:pk>/finalizar/', FinalizarObraView.as_view(), name='finalizar_obra'),
    path('solicitudes/<int:pk>/escriturar/', EscrituracionView.as_view(), name='escrituracion'),
    path('solicitudes/<int:pk>/baja/', BajaEmpresaView.as_view(), name='baja_empresa'),

    # admin: avances pendientes
    path('avances/pendientes/', AvancesPendientesView.as_view(), name='avances_pendientes'),
    path('avances/<int:pk>/validar/', AvanceValidarView.as_view(), name='avance_validar'),

    # admin: prorrogas pendientes
    path('prorrogas/pendientes/', ProrrogasPendientesView.as_view(), name='prorrogas_pendientes'),
    path('prorrogas/<int:pk>/aprobar/', ProrrogaAprobarView.as_view(), name='prorroga_aprobar'),
    path('prorrogas/<int:pk>/rechazar/', ProrrogaRechazarView.as_view(), name='prorroga_rechazar'),

    # proveedor: consumos de servicios
    path('consumos/', ConsumoListView.as_view(), name='consumo_list'),
    path('consumos/nuevo/', ConsumoCreateView.as_view(), name='consumo_create'),

    # organismo publico: consulta del parque
    path('parque/consulta/', ConsultaParqueView.as_view(), name='consulta_parque'),

    # admin: reportes pdf
    path('reportes/ocupacion/', ReporteOcupacionView.as_view(), name='reporte_ocupacion'),
    path('reportes/empresas/', ReporteEmpresasView.as_view(), name='reporte_empresas'),
    path('reportes/consumos/', ReporteConsumoView.as_view(), name='reporte_consumos'),

    # mensajería interna / ticketera (usuario)
    path('mensajes/', TicketListView.as_view(), name='ticket_list'),
    path('mensajes/nuevo/', TicketCreateView.as_view(), name='ticket_create'),
    path('mensajes/<int:pk>/', TicketDetailView.as_view(), name='ticket_detail'),

    # mensajería interna / ticketera (admin)
    path('panel/mensajes/', AdminTicketListView.as_view(), name='admin_ticket_list'),
    path('panel/mensajes/<int:pk>/', AdminTicketDetailView.as_view(), name='admin_ticket_detail'),
    path('panel/mensajes/<int:pk>/eliminar/', TicketSoftDeleteView.as_view(), name='ticket_delete'),

    # contacto externo
    path('contacto/externo/', TicketExternoCreateView.as_view(), name='ticket_externo'),
]
