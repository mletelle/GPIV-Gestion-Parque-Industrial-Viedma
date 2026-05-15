import logging

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from .models import (
    CustomUser, Empresa, Lote, TransicionEstado,
    AvanceConstructivo, SolicitudProrroga, ConsumoServicio,
    Ticket, MensajeTicket,
    ActivoInventario,
    SolicitudAcceso,
    AvisoVencimiento,
    CaducidadRegistro,
)
from .services import (
    notificar_solicitud_acceso_aprobada,
    notificar_solicitud_acceso_rechazada,
)

logger = logging.getLogger(__name__)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    search_fields = ('username', 'email', 'first_name', 'last_name')


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('razon_social', 'cuit', 'estado', 'tipo_empresa', 'usuario')
    list_filter = ('estado', 'tipo_empresa', 'rubro')
    search_fields = ('razon_social', 'cuit', 'nombre_fantasia')
    autocomplete_fields = ('usuario',)

    fieldsets = (
        ('Usuario vinculado', {
            'fields': ('usuario',),
            'description': (
                'Si la empresa fue registrada por un usuario del portal, '
                'queda vinculada automaticamente. Para empresas historicas '
                'o cargadas a mano se puede asignar un usuario existente aqui.'
            ),
        }),
        ('Datos fiscales', {
            'fields': (
                'razon_social', 'nombre_fantasia', 'cuit', 'ingresos_brutos',
                'tipo_empresa', 'objetivo_proyecto', 'rubro',
                'actividad_principal', 'actividad_secundaria',
                'descripcion_actividad',
            ),
        }),
        ('Contacto', {
            'fields': (
                'direccion', 'persona_referente', 'telefono',
                'correo_electronico',
            ),
        }),
        ('Proyecto', {
            'fields': (
                'emplazamiento_actual', 'personal_jerarquico',
                'personal_produccion', 'personal_administrativo',
                'personal_a_ocupar', 'materias_primas', 'destino_produccion',
            ),
            'classes': ('collapse',),
        }),
        ('Infraestructura', {
            'fields': (
                'necesidad_m2', 'superficie_cubierta_trabajo_m2',
                'superficie_cubierta_deposito_m2', 'superficie_futura_expansion_m2',
                'superficie_estacionamiento_m2', 'tiene_planos',
                'tiempo_radicacion_meses',
            ),
            'classes': ('collapse',),
        }),
        ('Servicios', {
            'fields': (
                'energia_tension', 'energia_potencia_rango',
                'consumo_estimado_agua_potable', 'consumo_estimado_agua_cruda',
                'gas', 'requiere_internet', 'necesidad_balanza_publica',
                'necesidad_comedor', 'necesidad_salon_multiuso',
            ),
            'classes': ('collapse',),
        }),
        ('Impacto ambiental', {
            'fields': (
                'categoria_industrial', 'maneja_inflamables', 'genera_residuos',
                'residuos_efluentes', 'tratamiento_en_planta',
            ),
            'classes': ('collapse',),
        }),
        ('Estado y control', {
            'fields': ('estado', 'fecha_limite_obra', 'escritura_pdf'),
        }),
    )


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        'nro_parcela', 'superficie_m2', 'estado', 'conexion_agua_potable',
        'conexion_agua_cruda', 'conexion_electrica', 'conexion_gas',
        'internet_disponible', 'empresa',
    )
    list_filter = ('estado',)
    search_fields = ('nro_parcela',)
    autocomplete_fields = ('empresa',)


@admin.register(TransicionEstado)
class TransicionEstadoAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'estado_anterior', 'estado_nuevo', 'fecha_cambio', 'usuario')
    list_filter = ('estado_nuevo',)
    autocomplete_fields = ('empresa', 'usuario')


@admin.register(AvanceConstructivo)
class AvanceConstructivoAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'porcentaje_declarado', 'fecha_presentacion', 'validado_admin')
    list_filter = ('validado_admin',)
    autocomplete_fields = ('empresa',)


@admin.register(SolicitudProrroga)
class SolicitudProrrogaAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'meses_solicitados', 'estado', 'fecha_solicitud')
    list_filter = ('estado',)
    autocomplete_fields = ('empresa',)


@admin.register(ConsumoServicio)
class ConsumoServicioAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'periodo_mes', 'periodo_anio', 'fecha_carga')
    list_filter = ('periodo_anio',)
    autocomplete_fields = ('empresa',)


class MensajeTicketInline(admin.TabularInline):
    model = MensajeTicket
    extra = 0
    fields = ('autor', 'contenido', 'fecha_creacion', 'is_active')
    readonly_fields = ('fecha_creacion',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('asunto', 'creador', 'estado', 'fecha_creacion', 'is_active')
    list_filter = ('estado', 'is_active', 'fecha_creacion')
    search_fields = ('asunto', 'creador__username', 'creador__email')
    autocomplete_fields = ('creador',)
    inlines = [MensajeTicketInline]
    
    actions = ['soft_delete_tickets']
    
    @admin.action(description='Dar de baja lógica a los tickets seleccionados')
    def soft_delete_tickets(self, request, queryset):
        for ticket in queryset:
            ticket.soft_delete()


@admin.register(MensajeTicket)
class MensajeTicketAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'autor', 'fecha_creacion', 'is_active')
    list_filter = ('is_active', 'fecha_creacion')
    search_fields = ('ticket__asunto', 'autor__username', 'contenido')
    autocomplete_fields = ('ticket', 'autor')


@admin.register(ActivoInventario)
class ActivoInventarioAdmin(admin.ModelAdmin):
    list_display = (
        'codigo_inventario', 'nombre', 'categoria', 'estado', 'activo',
        'ubicacion', 'responsable', 'fecha_alta',
    )
    list_filter = ('categoria', 'estado', 'activo')
    search_fields = ('codigo_inventario', 'nombre', 'marca', 'numero_serie')
    readonly_fields = (
        'codigo_inventario', 'fecha_creacion', 'fecha_modificacion',
        'registrado_por', 'dado_de_baja_por', 'fecha_baja',
    )
    autocomplete_fields = ('responsable',)
    date_hierarchy = 'fecha_alta'

    fieldsets = (
        ('Identificación', {
            'fields': (
                'codigo_inventario', 'categoria', 'nombre', 'descripcion',
            ),
        }),
        ('Bien físico', {
            'fields': ('marca', 'modelo', 'numero_serie'),
            'classes': ('collapse',),
        }),
        ('Trazabilidad operativa', {
            'fields': ('fecha_alta', 'estado', 'ubicacion', 'responsable', 'observaciones'),
        }),
        ('Baja lógica', {
            'fields': ('activo', 'motivo_baja', 'fecha_baja', 'dado_de_baja_por'),
            'description': 'Para dar de baja un activo use la vista del sistema en lugar de editar estos campos directamente.',
        }),
        ('Auditoría', {
            'fields': ('registrado_por', 'fecha_creacion', 'fecha_modificacion'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('responsable', 'registrado_por')


@admin.register(SolicitudAcceso)
class SolicitudAccesoAdmin(admin.ModelAdmin):
    """
    Bandeja de auditoría de solicitudes de acceso (Organismo / Proveedor).
    Las acciones de aprobar/rechazar activan o dejan inactivo el usuario
    asociado y notifican por email al solicitante.
    """
    list_display = (
        'nombre_apellido', 'tipo', 'organizacion', 'tipo_acceso',
        'estado', 'fecha_solicitud',
    )
    list_filter = ('estado', 'tipo', 'tipo_acceso')
    search_fields = (
        'nombre_apellido', 'organizacion', 'email_institucional',
        'usuario__username',
    )
    readonly_fields = (
        'tipo', 'nombre_apellido', 'cargo', 'organizacion', 'telefono',
        'email_institucional', 'tipo_acceso', 'motivo',
        'fecha_solicitud', 'fecha_resolucion', 'resuelto_por', 'usuario',
    )
    fieldsets = (
        ('Solicitante', {
            'fields': (
                'tipo', 'nombre_apellido', 'cargo', 'organizacion',
                'telefono', 'email_institucional', 'tipo_acceso', 'motivo',
            ),
        }),
        ('Resolución', {
            'fields': (
                'estado', 'motivo_resolucion',
                'fecha_resolucion', 'resuelto_por', 'usuario',
            ),
        }),
    )
    actions = ['aprobar_solicitudes', 'rechazar_solicitudes']

    def has_add_permission(self, request):
        # Las solicitudes solo nacen del flujo público.
        return False

    @admin.action(description='Aprobar solicitudes seleccionadas (activa el usuario)')
    def aprobar_solicitudes(self, request, queryset):
        aprobadas = 0
        for solicitud in queryset.filter(estado=SolicitudAcceso.Estado.PENDIENTE):
            self._aprobar(request, solicitud)
            aprobadas += 1
        if aprobadas:
            self.message_user(
                request,
                f'{aprobadas} solicitud(es) aprobada(s) y notificada(s) por email.',
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                'No había solicitudes pendientes en la selección.',
                level=messages.WARNING,
            )

    @admin.action(description='Rechazar solicitudes seleccionadas (mantiene usuario inactivo)')
    def rechazar_solicitudes(self, request, queryset):
        rechazadas = 0
        for solicitud in queryset.filter(estado=SolicitudAcceso.Estado.PENDIENTE):
            self._rechazar(request, solicitud)
            rechazadas += 1
        if rechazadas:
            self.message_user(
                request,
                f'{rechazadas} solicitud(es) rechazada(s) y notificada(s) por email.',
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                'No había solicitudes pendientes en la selección.',
                level=messages.WARNING,
            )

    def save_model(self, request, obj, form, change):
        """
        Si el admin cambia el estado desde el formulario (en vez de usar la
        action), aplicamos el mismo efecto: activar/desactivar usuario y
        notificar por email. Detecta la transición comparando el estado
        anterior persistido contra el nuevo.

        Usa select_for_update dentro de un atomic para evitar la race
        condition en la que dos admins procesan la misma solicitud a la vez.
        """
        previo = None
        with transaction.atomic():
            if obj.pk:
                try:
                    locked = SolicitudAcceso.objects.select_for_update().get(pk=obj.pk)
                    previo = locked.estado
                except SolicitudAcceso.DoesNotExist:
                    pass

            super().save_model(request, obj, form, change)

            if previo == SolicitudAcceso.Estado.PENDIENTE:
                if obj.estado == SolicitudAcceso.Estado.APROBADA:
                    self._aprobar(request, obj, ya_guardado=True)
                elif obj.estado == SolicitudAcceso.Estado.RECHAZADA:
                    self._rechazar(request, obj, ya_guardado=True)

    def _aprobar(self, request, solicitud, ya_guardado=False):
        with transaction.atomic():
            if not ya_guardado:
                # Refetch con lock para evitar doble procesamiento concurrente.
                try:
                    solicitud = SolicitudAcceso.objects.select_for_update().get(pk=solicitud.pk)
                except SolicitudAcceso.DoesNotExist:
                    return
                if solicitud.estado != SolicitudAcceso.Estado.PENDIENTE:
                    return  # ya fue procesada por otro admin

            usuario = solicitud.usuario
            if usuario is not None:
                grupo_nombre = solicitud.get_grupo_destino()
                grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
                usuario.is_active = True
                usuario.save(update_fields=['is_active'])
                usuario.groups.add(grupo)

            solicitud.estado = SolicitudAcceso.Estado.APROBADA
            solicitud.fecha_resolucion = timezone.now()
            solicitud.resuelto_por = request.user if request.user.is_authenticated else None
            if not ya_guardado:
                solicitud.save(update_fields=[
                    'estado', 'fecha_resolucion', 'resuelto_por',
                ])
            else:
                solicitud.save(update_fields=['fecha_resolucion', 'resuelto_por'])

        try:
            notificar_solicitud_acceso_aprobada(solicitud)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Error al notificar aprobación de solicitud (pk=%s)", solicitud.pk)

    def _rechazar(self, request, solicitud, ya_guardado=False):
        with transaction.atomic():
            if not ya_guardado:
                # Refetch con lock para evitar doble procesamiento concurrente.
                try:
                    solicitud = SolicitudAcceso.objects.select_for_update().get(pk=solicitud.pk)
                except SolicitudAcceso.DoesNotExist:
                    return
                if solicitud.estado != SolicitudAcceso.Estado.PENDIENTE:
                    return  # ya fue procesada por otro admin

            # Liberar credenciales: borrar el user inactivo para que el email/
            # username quede disponible si el solicitante quiere reintentar.
            usuario = solicitud.usuario
            if usuario is not None and not usuario.is_active:
                solicitud.usuario = None
                usuario.delete()

            solicitud.estado = SolicitudAcceso.Estado.RECHAZADA
            solicitud.fecha_resolucion = timezone.now()
            solicitud.resuelto_por = request.user if request.user.is_authenticated else None
            if not ya_guardado:
                solicitud.save(update_fields=[
                    'estado', 'fecha_resolucion', 'resuelto_por', 'usuario',
                ])
            else:
                solicitud.save(update_fields=['fecha_resolucion', 'resuelto_por', 'usuario'])

        try:
            notificar_solicitud_acceso_rechazada(solicitud)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Error al notificar rechazo de solicitud (pk=%s)", solicitud.pk)


@admin.register(AvisoVencimiento)
class AvisoVencimientoAdmin(admin.ModelAdmin):
    """Bandeja de auditoría de avisos automáticos de vencimiento."""
    list_display = (
        'empresa', 'nivel', 'dias_restantes', 'email_destino',
        'fecha_envio', 'is_active',
    )
    list_filter = ('nivel', 'is_active', 'fecha_envio')
    search_fields = ('empresa__razon_social', 'empresa__cuit', 'email_destino')
    readonly_fields = (
        'empresa', 'nivel', 'dias_restantes', 'email_destino',
        'fecha_envio', 'is_active', 'deleted_at',
    )
    date_hierarchy = 'fecha_envio'

    def has_add_permission(self, request):
        # Los avisos solo se crean desde el command automatizado.
        return False

    actions = ['soft_delete_avisos']

    @admin.action(description='Dar de baja lógica los avisos seleccionados')
    def soft_delete_avisos(self, request, queryset):
        count = 0
        for aviso in queryset.filter(is_active=True):
            aviso.soft_delete()
            count += 1
        self.message_user(
            request,
            f'{count} aviso(s) dado(s) de baja lógica.',
            level=messages.SUCCESS,
        )


@admin.register(CaducidadRegistro)
class CaducidadRegistroAdmin(admin.ModelAdmin):
    """Bandeja de auditoría de caducidades automáticas."""
    list_display = (
        'empresa', 'estado_anterior', 'fecha_limite_original',
        'notificacion_enviada', 'fecha_ejecucion', 'is_active',
    )
    list_filter = ('is_active', 'notificacion_enviada', 'fecha_ejecucion')
    search_fields = ('empresa__razon_social', 'empresa__cuit', 'email_destino')
    readonly_fields = (
        'empresa', 'estado_anterior', 'fecha_limite_original',
        'justificacion', 'email_destino', 'notificacion_enviada',
        'fecha_ejecucion', 'is_active', 'deleted_at',
    )
    date_hierarchy = 'fecha_ejecucion'

    def has_add_permission(self, request):
        # Los registros solo se crean desde el command automatizado.
        return False

    actions = ['soft_delete_registros']

    @admin.action(description='Dar de baja lógica los registros seleccionados')
    def soft_delete_registros(self, request, queryset):
        count = 0
        for registro in queryset.filter(is_active=True):
            registro.soft_delete()
            count += 1
        self.message_user(
            request,
            f'{count} registro(s) dado(s) de baja lógica.',
            level=messages.SUCCESS,
        )
