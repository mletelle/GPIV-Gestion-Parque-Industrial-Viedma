"""
Capa de servicios de core.

Centraliza operaciones que usan tanto las vistas como los management
commands, evitando duplicar lógica y circular imports.

Servicios de transición de estado
----------------------------------
- registrar_transicion: registra un cambio de estado en la FSM de Empresa.

Servicios de consumo (proveedores)
------------------------------------
- get_servicio_proveedor: retorna la clave del servicio del proveedor.

Servicios RBAC internos de empresa
------------------------------------
- asociar_titular: vincula un usuario como Titular de una empresa.
- invitar_miembro: vincula un usuario como Estándar en una empresa.
- remover_miembro: desvincula un usuario de una empresa (con validación).
- transferir_titularidad: transfiere el rol Titular entre miembros de forma
  atómica, garantizando que la empresa siempre tenga exactamente un Titular.
"""

from django.db import transaction

from .models import Empresa, TransicionEstado, CustomUser


# ---------------------------------------------------------------------------
# Constantes de proveedor de servicios
# ---------------------------------------------------------------------------

# Mapping de servicio (proveedor) a campos del modelo ConsumoServicio que
# le competen. Agua agrupa potable + cruda porque las administra una sola
# distribuidora local.
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
    """Devuelve la clave de servicio (AGUA/LUZ/GAS) según el grupo del
    usuario, o None si no es un proveedor específico (admin/superuser)."""
    if not user.is_authenticated:
        return None
    nombres = set(user.groups.values_list('name', flat=True))
    for clave in SERVICIO_CAMPOS:
        if f'PROVEEDOR_{clave}' in nombres:
            return clave
    return None


# ---------------------------------------------------------------------------
# Servicio de transición de estado de Empresa
# ---------------------------------------------------------------------------

def registrar_transicion(empresa, estado_nuevo, usuario=None, justificacion=''):
    """Cambia el estado de la empresa y deja traza en el historial.
    No valida la transición; las vistas ya filtran por estado permitido."""
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


# ---------------------------------------------------------------------------
# Servicios RBAC internos de Empresa
# ---------------------------------------------------------------------------

class RBACError(Exception):
    """Error de lógica RBAC interna de empresa."""


def asociar_titular(empresa: Empresa, usuario: CustomUser) -> None:
    """
    Vincula ``usuario`` a ``empresa`` con rol Titular.

    Precondición: el usuario no debe pertenecer ya a otra empresa.
    Se usa al crear la empresa en el flujo de registro (SolicitudCreateView).
    """
    usuario.empresa_asociada = empresa
    usuario.rol_empresa = CustomUser.RolEmpresa.TITULAR
    usuario.save(update_fields=['empresa_asociada', 'rol_empresa'])


def invitar_miembro(empresa: Empresa, usuario: CustomUser) -> None:
    """
    Vincula ``usuario`` a ``empresa`` con rol Estándar.

    Lanza RBACError si el usuario ya pertenece a una empresa (propia u otra).
    """
    if usuario.tiene_empresa_asociada():
        raise RBACError(
            f'El usuario "{usuario.username}" ya está asociado a una empresa. '
            'Debe desvincularse antes de unirse a otra.'
        )
    usuario.empresa_asociada = empresa
    usuario.rol_empresa = CustomUser.RolEmpresa.ESTANDAR
    usuario.save(update_fields=['empresa_asociada', 'rol_empresa'])


def remover_miembro(empresa: Empresa, usuario: CustomUser, ejecutor: CustomUser) -> None:
    """
    Desvincula ``usuario`` de ``empresa``.

    Reglas:
    - El ejecutor debe ser Titular de la empresa.
    - El usuario debe ser miembro de la empresa.
    - No se puede remover al único Titular.

    Lanza RBACError en caso de violación.
    """
    if not ejecutor.es_titular_de(empresa):
        raise RBACError('Solo el Titular puede remover miembros.')

    if not usuario.es_miembro_de(empresa):
        raise RBACError(
            f'El usuario "{usuario.username}" no pertenece a esta empresa.'
        )

    if not empresa.puede_remover_miembro(usuario):
        raise RBACError(
            'No es posible remover al único Titular de la empresa. '
            'Transfiera la titularidad a otro miembro primero.'
        )

    usuario.empresa_asociada = None
    usuario.rol_empresa = None
    usuario.save(update_fields=['empresa_asociada', 'rol_empresa'])


@transaction.atomic
def transferir_titularidad(
    empresa: Empresa,
    titular_actual: CustomUser,
    nuevo_titular: CustomUser,
) -> None:
    """
    Transfiere el rol Titular de ``titular_actual`` a ``nuevo_titular``
    de forma atómica.

    Reglas:
    - ``titular_actual`` debe ser Titular de la empresa.
    - ``nuevo_titular`` debe ser miembro de la empresa (cualquier rol).
    - Ambos deben pertenecer a la misma empresa.
    - La operación es atómica: si falla cualquier parte, se revierte completa.

    Al finalizar:
    - ``titular_actual`` pasa a rol Estándar.
    - ``nuevo_titular`` pasa a rol Titular.
    """
    if not titular_actual.es_titular_de(empresa):
        raise RBACError(
            f'"{titular_actual.username}" no es Titular de esta empresa.'
        )

    if not nuevo_titular.es_miembro_de(empresa):
        raise RBACError(
            f'"{nuevo_titular.username}" no es miembro de esta empresa. '
            'Debe ser invitado primero.'
        )

    if titular_actual.pk == nuevo_titular.pk:
        raise RBACError('No se puede transferir la titularidad al mismo usuario.')

    # Degradar titular actual a Estándar
    titular_actual.rol_empresa = CustomUser.RolEmpresa.ESTANDAR
    titular_actual.save(update_fields=['rol_empresa'])

    # Promover nuevo titular
    nuevo_titular.rol_empresa = CustomUser.RolEmpresa.TITULAR
    nuevo_titular.save(update_fields=['rol_empresa'])
