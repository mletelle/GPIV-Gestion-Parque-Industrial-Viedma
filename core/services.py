"""
capa de servicios de core. centraliza operaciones que usan tanto las vistas
como los management commands, asi evitamos duplicar logica de transicion
y circular imports.
"""
from .models import Empresa, TransicionEstado


# mapping de servicio (proveedor) a campos del modelo ConsumoServicio que
# le competen. agua agrupa potable + cruda porque las administra una sola
# distribuidora local. se usa para segregar el formulario y el listado.
SERVICIO_CAMPOS = {
    'AGUA': ['consumo_agua_potable_m3', 'consumo_agua_cruda_m3'],
    'LUZ': ['consumo_luz_kwh'],
    'GAS': ['consumo_gas_m3'],
}

SERVICIO_LABELS = {
    'AGUA': 'Agua',
    'LUZ': 'Electricidad',
    'GAS': 'Gas',
}


def get_servicio_proveedor(user):
    """devuelve la clave de servicio (AGUA/LUZ/GAS) segun el grupo del
    usuario, o None si no es un proveedor especifico (admin/superuser)."""
    if not user.is_authenticated:
        return None
    nombres = set(user.groups.values_list('name', flat=True))
    for clave in SERVICIO_CAMPOS:
        if f'PROVEEDOR_{clave}' in nombres:
            return clave
    return None


def registrar_transicion(empresa, estado_nuevo, usuario=None, justificacion=''):
    """cambia el estado de la empresa y deja traza en el historial.
    no valida la transicion, las vistas ya filtran por estado permitido."""
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
