"""
capa de servicios de core. centraliza operaciones que usan tanto las vistas
como los management commands, asi evitamos duplicar logica de transicion
y circular imports.
"""
import logging

import resend
from django.conf import settings
from django.utils.html import escape

from django.db import transaction

from .models import TransicionEstado


# ──────────────────────────────────────────────────────────────────────────────
# Excepciones de dominio RBAC
# ──────────────────────────────────────────────────────────────────────────────

class RBACError(Exception):
    """Base para errores de negocio del dominio RBAC de empresa."""


class SinTitularError(RBACError):
    """Se lanzaría si una operación dejara a la empresa sin titular activo."""


class UsuarioYaVinculadoError(RBACError):
    """El usuario ya pertenece a una empresa."""


class UsuarioNoEsMiembroError(RBACError):
    """El usuario no pertenece a esta empresa."""


class NoSePuedeDegradarTitularError(RBACError):
    """No se puede degradar / remover al titular sin asignar uno nuevo."""


# ──────────────────────────────────────────────────────────────────────────────
# Servicios RBAC de empresa
# ──────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def transferir_titularidad(empresa, titular_actual, nuevo_titular):
    """
    Transfiere el rol TITULAR de ``titular_actual`` a ``nuevo_titular``
    de forma atómica:
      1. ``titular_actual`` pasa a ESTANDAR.
      2. ``nuevo_titular`` pasa a TITULAR.

    Restricciones:
    - ``titular_actual`` debe ser TITULAR de ``empresa``.
    - ``nuevo_titular`` debe ser ESTANDAR de ``empresa``.
    - Ambos usuarios deben estar activos.

    Raises:
        RBACError / subclases si alguna restricción no se cumple.
    """
    from .models import CustomUser

    # Refetch con lock para evitar race conditions concurrentes.
    titular_actual = (
        empresa.empleados
        .select_for_update()
        .filter(pk=titular_actual.pk, rol_interno=CustomUser.RolInterno.TITULAR, is_active=True)
        .first()
    )
    if titular_actual is None:
        raise RBACError("El usuario actual no es un TITULAR activo de esta empresa.")

    nuevo_titular = (
        empresa.empleados
        .select_for_update()
        .filter(pk=nuevo_titular.pk, rol_interno=CustomUser.RolInterno.ESTANDAR, is_active=True)
        .first()
    )
    if nuevo_titular is None:
        raise RBACError("El nuevo titular debe ser un usuario ESTÁNDAR activo de esta empresa.")

    titular_actual.rol_interno = CustomUser.RolInterno.ESTANDAR
    titular_actual.save(update_fields=['rol_interno'])

    nuevo_titular.rol_interno = CustomUser.RolInterno.TITULAR
    nuevo_titular.save(update_fields=['rol_interno'])


@transaction.atomic
def invitar_usuario(empresa, titular, usuario_a_invitar):
    """
    Asocia ``usuario_a_invitar`` (sin empresa) a ``empresa`` como ESTANDAR.

    Restricciones:
    - ``titular`` debe ser TITULAR activo de ``empresa``.
    - ``usuario_a_invitar`` no debe pertenecer ya a ninguna empresa.
    - ``usuario_a_invitar`` debe pertenecer al grupo EMPRESA.

    Raises:
        RBACError / subclases.
    """
    from .models import CustomUser

    titular = (
        empresa.empleados
        .select_for_update()
        .filter(pk=titular.pk, rol_interno=CustomUser.RolInterno.TITULAR, is_active=True)
        .first()
    )
    if titular is None:
        raise RBACError("Solo un TITULAR activo puede invitar usuarios.")

    usuario_a_invitar = (
        CustomUser.objects
        .select_for_update()
        .filter(pk=usuario_a_invitar.pk)
        .first()
    )
    if usuario_a_invitar is None:
        raise RBACError("Usuario no encontrado.")

    if usuario_a_invitar.empresa_id is not None:
        raise UsuarioYaVinculadoError(
            f"El usuario «{usuario_a_invitar.username}» ya pertenece a otra empresa."
        )

    if not usuario_a_invitar.groups.filter(name='EMPRESA').exists():
        raise RBACError(
            f"El usuario «{usuario_a_invitar.username}» no pertenece al grupo EMPRESA."
        )

    usuario_a_invitar.empresa = empresa
    usuario_a_invitar.rol_interno = CustomUser.RolInterno.ESTANDAR
    usuario_a_invitar.save(update_fields=['empresa', 'rol_interno'])


@transaction.atomic
def remover_miembro(empresa, titular, usuario_a_remover):
    """
    Desvincula ``usuario_a_remover`` de ``empresa`` (pone empresa=None,
    rol_interno=None).

    Restricciones:
    - ``titular`` debe ser TITULAR activo de ``empresa``.
    - ``usuario_a_remover`` debe ser ESTANDAR de ``empresa`` (no se puede
      remover al titular directamente; usar transferir_titularidad primero).

    Raises:
        RBACError / subclases.
    """
    from .models import CustomUser

    titular = (
        empresa.empleados
        .select_for_update()
        .filter(pk=titular.pk, rol_interno=CustomUser.RolInterno.TITULAR, is_active=True)
        .first()
    )
    if titular is None:
        raise RBACError("Solo un TITULAR activo puede remover miembros.")

    usuario_a_remover = (
        empresa.empleados
        .select_for_update()
        .filter(pk=usuario_a_remover.pk)
        .first()
    )
    if usuario_a_remover is None:
        raise UsuarioNoEsMiembroError("El usuario no pertenece a esta empresa.")

    if usuario_a_remover.rol_interno == CustomUser.RolInterno.TITULAR:
        raise NoSePuedeDegradarTitularError(
            "No se puede remover al TITULAR directamente. "
            "Transferí la titularidad antes de remover este usuario."
        )

    usuario_a_remover.empresa = None
    usuario_a_remover.rol_interno = None
    usuario_a_remover.save(update_fields=['empresa', 'rol_interno'])

logger = logging.getLogger(__name__)

# longitud maxima razonable para el subject de un email
_MAX_SUBJECT_LEN = 150


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
    usuario, o None si no es un proveedor especifico (admin/superuser).
    si el usuario pertenece a mas de un grupo proveedor, loguea un warning
    y retorna None para que no opere con un servicio arbitrario."""
    if not user.is_authenticated:
        return None
    nombres = set(user.groups.values_list('name', flat=True))
    encontrados = [
        clave for clave in SERVICIO_CAMPOS
        if f'PROVEEDOR_{clave}' in nombres
    ]
    if len(encontrados) > 1:
        logger.warning(
            "Usuario %s pertenece a multiples grupos proveedor (%s). "
            "No se puede determinar un servicio unico.",
            user.username, ', '.join(encontrados),
        )
        return None
    return encontrados[0] if encontrados else None


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


# 
# emails transaccionales (mensajeria interna)
# 

def enviar_email_resend(to_email, subject, html_content):
    """
    envia un email transaccional via API de Resend.
    si RESEND_API_KEY no esta configurada, loguea un warning y devuelve False
    (modo dev: no rompe el flujo de la vista que lo llama).
    """
    api_key = settings.RESEND_API_KEY
    if not api_key:
        logger.warning(
            "RESEND_API_KEY no configurada. Email omitido (to=%s, subject=%r)",
            to_email, subject,
        )
        return False

    resend.api_key = api_key
    try:
        return resend.Emails.send({
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_content,
        })
    except Exception:
        # capturamos cualquier excepcion del SDK para que la respuesta del
        # usuario no falle si el proveedor de mail tiene un hipo. log con
        # traceback completo para diagnostico.
        logger.exception(
            "Error enviando email via Resend (to=%s, subject=%r)",
            to_email, subject,
        )
        return False


def _sanitizar_subject(subject):
    """remueve caracteres que podrian inyectar headers smtp y limita la
    longitud para evitar problemas con proveedores de correo."""
    limpio = subject.replace('\r', '').replace('\n', '')
    if len(limpio) > _MAX_SUBJECT_LEN:
        limpio = limpio[:_MAX_SUBJECT_LEN] + '…'
    return limpio


def _es_admin(user):
    return bool(
        user and (
            user.is_superuser
            or user.groups.filter(name='ADMIN_ENREPAVI').exists()
        )
    )


def notificar_ticket_mensaje(ticket, mensaje):
    """
    decide a quien hay que avisar de un nuevo mensaje en un ticket.
    - si el autor es admin: avisa al creador (interno: solo aviso de "tenes
      respuesta nueva, ingresa al sistema"; externo: incluye la respuesta
      porque el visitante no vuelve al sistema).
    - si el autor es usuario / externo: avisa a SUPPORT_INBOX_EMAIL.
    todo dato proveniente del usuario se escapa con `escape()` para evitar
    inyeccion de HTML en el cuerpo del mail.
    """
    autor_es_admin = _es_admin(mensaje.autor)
    asunto_safe = escape(ticket.asunto)
    contenido_safe = escape(mensaje.contenido)

    if autor_es_admin:
        if ticket.creador:
            destino = ticket.creador.email
            nombre = ticket.creador.get_full_name() or ticket.creador.username
            site_url = getattr(settings, 'SITE_URL', 'https://gpiv.tivena.com.ar')
            link = f'{site_url}/mensajes/{ticket.id}/'
            cuerpo_extra = (
                '<p>Por favor, ingresá al sistema para leer la respuesta:</p>'
                f'<p><a href="{link}">{link}</a></p>'
            )
        else:
            destino = ticket.email_contacto
            nombre = ticket.nombre_contacto or 'visitante'
            cuerpo_extra = (
                '<p>La respuesta es:</p>'
                f'<blockquote style="border-left:3px solid #6ac64f;'
                ' padding:0.5rem 1rem; background:#f5f5f5;'
                f' white-space:pre-wrap;">{contenido_safe}</blockquote>'
            )

        if not destino:
            logger.warning(
                "Ticket #%s sin destinatario para notificar respuesta.",
                ticket.id,
            )
            return False

        html = (
            f'<p>Hola {escape(nombre)},</p>'
            f'<p>El administrador del GPIV respondió a tu consulta '
            f'<strong>"{asunto_safe}"</strong>.</p>'
            f'{cuerpo_extra}'
            '<hr>'
            '<p style="font-size:12px; color:#6B7280;">'
            'Mensaje automático del Sistema de Gestión del Parque Industrial de'
            ' Viedma. No respondas a este correo.</p>'
        )
        subject = _sanitizar_subject(f'Respuesta a tu consulta — {ticket.asunto}')
        return enviar_email_resend(destino, subject, html)

    # autor: usuario logueado (no admin) o externo. avisa al admin.
    nombre_emisor = (
        ticket.creador.get_full_name() or ticket.creador.username
        if ticket.creador
        else (ticket.nombre_contacto or 'Externo')
    )
    nombre_safe = escape(nombre_emisor)
    es_externo = ticket.creador is None
    detalle_externo = ''
    if es_externo:
        detalle_externo = (
            f'<p><strong>Email:</strong> {escape(ticket.email_contacto or "")}'
            + (
                f'<br><strong>Teléfono:</strong>'
                f' {escape(ticket.telefono_contacto)}'
                if ticket.telefono_contacto else ''
            )
            + '</p>'
        )

    site_url = getattr(settings, 'SITE_URL', 'https://gpiv.tivena.com.ar')
    link = f'{site_url}/panel/mensajes/{ticket.id}/'
    html = (
        '<p>Hola Administración ENREPAVI,</p>'
        f'<p>{"Llegó una nueva consulta desde la landing." if es_externo else "Llegó un nuevo mensaje de un usuario registrado."}</p>'
        f'<p><strong>Ticket:</strong> #{ticket.id}<br>'
        f'<strong>Asunto:</strong> {asunto_safe}<br>'
        f'<strong>Categoría:</strong> {escape(ticket.get_categoria_display())}<br>'
        f'<strong>Remitente:</strong> {nombre_safe}</p>'
        f'{detalle_externo}'
        '<p><strong>Mensaje:</strong></p>'
        f'<blockquote style="border-left:3px solid #6ac64f;'
        ' padding:0.5rem 1rem; background:#f5f5f5;'
        f' white-space:pre-wrap;">{contenido_safe}</blockquote>'
        f'<p>Ingresá al panel: <a href="{link}">'
        f'{link}</a></p>'
        '<hr>'
        '<p style="font-size:12px; color:#6B7280;">'
        'Mensaje automático del Sistema de Gestión del Parque Industrial de'
        ' Viedma.</p>'
    )
    subject = _sanitizar_subject(f'[GPIV] Nuevo mensaje en ticket #{ticket.id} — {nombre_emisor}')
    return enviar_email_resend(settings.SUPPORT_INBOX_EMAIL, subject, html)



def notificar_solicitud_acceso_recibida(solicitud):
    """
    Avisa a SUPPORT_INBOX_EMAIL que llegó una solicitud nueva para auditar.
    Se invoca desde la vista pública al crear la solicitud.
    """
    nombre_safe = escape(solicitud.nombre_apellido)
    organizacion_safe = escape(solicitud.organizacion)
    motivo_safe = escape(solicitud.motivo)
    tipo_label = solicitud.get_tipo_display()
    tipo_acceso_label = solicitud.get_tipo_acceso_display()
    email_safe = escape(solicitud.email_institucional)
    cargo_safe = escape(solicitud.cargo)
    telefono_safe = escape(solicitud.telefono)

    html = (
        f'<h2>Nueva solicitud de acceso — {tipo_label}</h2>'
        f'<p><strong>Solicitante:</strong> {nombre_safe} ({cargo_safe})<br>'
        f'<strong>Organización:</strong> {organizacion_safe}<br>'
        f'<strong>Tipo de acceso:</strong> {tipo_acceso_label}<br>'
        f'<strong>Email institucional:</strong> {email_safe}<br>'
        f'<strong>Teléfono:</strong> {telefono_safe}</p>'
        '<p><strong>Motivo:</strong></p>'
        f'<blockquote style="border-left:3px solid #6ac64f;'
        ' padding:0.5rem 1rem; background:#f5f5f5;'
        f' white-space:pre-wrap;">{motivo_safe}</blockquote>'
        '<p>Revisá la solicitud en el admin de Django para aprobarla o rechazarla.</p>'
        '<hr>'
        '<p style="font-size:12px; color:#6B7280;">'
        'Mensaje automático del Sistema de Gestión del Parque Industrial de'
        ' Viedma.</p>'
    )
    subject = _sanitizar_subject(
        f'[GPIV] Nueva solicitud de acceso ({tipo_label}) — {solicitud.nombre_apellido}'
    )
    return enviar_email_resend(settings.SUPPORT_INBOX_EMAIL, subject, html)


def notificar_solicitud_acceso_aprobada(solicitud):
    """Avisa al solicitante que su acceso fue habilitado."""
    nombre_safe = escape(solicitud.nombre_apellido)
    motivo_safe = escape(solicitud.motivo_resolucion or '')
    motivo_block = (
        '<p><strong>Comentario del administrador:</strong></p>'
        f'<blockquote style="border-left:3px solid #6ac64f;'
        ' padding:0.5rem 1rem; background:#f5f5f5;'
        f' white-space:pre-wrap;">{motivo_safe}</blockquote>'
    ) if solicitud.motivo_resolucion else ''
    html = (
        f'<h2>Tu solicitud de acceso fue aprobada</h2>'
        f'<p>Hola {nombre_safe},</p>'
        '<p>Tu solicitud de acceso al Sistema de Gestión del Parque Industrial '
        'de Viedma fue <strong>aprobada</strong>. Ya podés iniciar sesión con '
        'el usuario y la contraseña que registraste.</p>'
        f'{motivo_block}'
        '<hr>'
        '<p style="font-size:12px; color:#6B7280;">'
        'Mensaje automático de ENREPAVI · Parque Industrial de Viedma.</p>'
    )
    subject = _sanitizar_subject('[GPIV] Tu solicitud de acceso fue aprobada')
    return enviar_email_resend(solicitud.email_institucional, subject, html)


def notificar_solicitud_acceso_rechazada(solicitud):
    """Avisa al solicitante que su acceso fue denegado."""
    nombre_safe = escape(solicitud.nombre_apellido)
    motivo_safe = escape(solicitud.motivo_resolucion or '')
    motivo_block = (
        '<p><strong>Motivo del rechazo:</strong></p>'
        f'<blockquote style="border-left:3px solid #DC2626;'
        ' padding:0.5rem 1rem; background:#FEF2F2;'
        f' white-space:pre-wrap;">{motivo_safe}</blockquote>'
    ) if solicitud.motivo_resolucion else ''
    html = (
        f'<h2>Tu solicitud de acceso fue rechazada</h2>'
        f'<p>Hola {nombre_safe},</p>'
        '<p>Lamentamos informarte que tu solicitud de acceso al Sistema de '
        'Gestión del Parque Industrial de Viedma fue <strong>rechazada</strong>.</p>'
        f'{motivo_block}'
        '<p>Si considerás que se trata de un error, podés enviar documentación '
        'adicional respondiendo a este correo.</p>'
        '<hr>'
        '<p style="font-size:12px; color:#6B7280;">'
        'Mensaje automático de ENREPAVI · Parque Industrial de Viedma.</p>'
    )
    subject = _sanitizar_subject('[GPIV] Tu solicitud de acceso fue rechazada')
    return enviar_email_resend(solicitud.email_institucional, subject, html)


def notificar_solicitud_acceso_resuelta(solicitud):
    """
    Delega en el notificador apropiado según el estado de la solicitud.
    Llamar desde las vistas de aprobación/rechazo (fuera del atomic).
    """
    from .models import SolicitudAcceso
    if solicitud.estado == SolicitudAcceso.Estado.APROBADA:
        return notificar_solicitud_acceso_aprobada(solicitud)
    return notificar_solicitud_acceso_rechazada(solicitud)
