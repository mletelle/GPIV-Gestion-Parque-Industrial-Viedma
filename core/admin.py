from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Empresa, Lote, TransicionEstado, AvanceConstructivo, SolicitudProrroga, ConsumoServicio


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    pass


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('razon_social', 'cuit', 'estado', 'tipo_empresa')
    list_filter = ('estado', 'tipo_empresa', 'rubro')
    search_fields = ('razon_social', 'cuit', 'nombre_fantasia')


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ('nro_parcela', 'superficie_m2', 'estado', 'empresa')
    list_filter = ('estado',)
    search_fields = ('nro_parcela',)


@admin.register(TransicionEstado)
class TransicionEstadoAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'estado_anterior', 'estado_nuevo', 'fecha_cambio', 'usuario')
    list_filter = ('estado_nuevo',)


@admin.register(AvanceConstructivo)
class AvanceConstructivoAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'porcentaje_declarado', 'fecha_presentacion', 'validado_admin')
    list_filter = ('validado_admin',)


@admin.register(SolicitudProrroga)
class SolicitudProrrogaAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'meses_solicitados', 'estado', 'fecha_solicitud')
    list_filter = ('estado',)


@admin.register(ConsumoServicio)
class ConsumoServicioAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'periodo_mes', 'periodo_anio', 'fecha_carga')
    list_filter = ('periodo_anio',)
