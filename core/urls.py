from django.urls import path
from .views import (
    LandingPageView,
    CustomLoginView,
    CustomLogoutView,
    DashboardView,
    CatalogoPublicoView,
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
)

app_name = 'core'

urlpatterns = [
    # publico
    path('', LandingPageView.as_view(), name='landing'),
    path('catalogo/', CatalogoPublicoView.as_view(), name='catalogo'),

    # autenticacion
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('registro/', RegistroView.as_view(), name='registro'),

    # inicio (protegido)
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

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
]
