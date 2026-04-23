from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Empresa, Lote, TransicionEstado,
    AvanceConstructivo, SolicitudProrroga, ConsumoServicio,
    ActivoInventario,
)


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
                'energia_tension', 'energia_potencia_kw',
                'consumo_estimado_agua_potable_m3', 'consumo_estimado_agua_cruda_m3',
                'gas', 'requiere_internet', 'necesidad_balanza_publica',
                'necesidad_comedor', 'necesidad_salon_multiuso',
            ),
            'classes': ('collapse',),
        }),
        ('Impacto ambiental', {
            'fields': (
                'categoria_industrial', 'maneja_inflamables',
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
    list_display = ('nro_parcela', 'superficie_m2', 'estado', 'empresa')
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
