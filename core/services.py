"""
capa de servicios de core. centraliza operaciones que usan tanto las vistas
como los management commands, asi evitamos duplicar logica de transicion
y circular imports.
"""
import logging

import resend
from django.conf import settings
from django.utils.html import escape

from .models import TransicionEstado

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


# =========================================
# emails transaccionales (mensajeria interna)
# =========================================

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
