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


def enviar_aviso_vencimiento(empresa, dias_restantes, nivel):
    """
    envia un email de recordatorio de vencimiento de obra y crea el
    registro de auditoria ``AvisoVencimiento``.

    parametros:
        empresa: instancia de Empresa (debe tener correo_electronico).
        dias_restantes: int con la cantidad de dias hasta la fecha limite.
        nivel: str, uno de AvisoVencimiento.Nivel ('Urgente' o 'Proximo').

    retorna:
        AvisoVencimiento creado si el envio fue exitoso, None en caso contrario.
    """
    from django.template.loader import render_to_string
    from .models import AvisoVencimiento

    destino = empresa.correo_electronico
    if not destino:
        logger.warning(
            "Empresa %s (pk=%s) sin correo_electronico. Aviso omitido.",
            empresa.razon_social, empresa.pk,
        )
        return None

    fecha_limite_str = (
        empresa.fecha_limite_obra.strftime('%d/%m/%Y')
        if empresa.fecha_limite_obra else '—'
    )
    site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')

    es_urgente = nivel == AvisoVencimiento.Nivel.URGENTE
    context = {
        'razon_social': empresa.razon_social,
        'cuit': empresa.cuit,
        'fecha_limite': fecha_limite_str,
        'dias_restantes': dias_restantes,
        'nivel': nivel,
        'site_url': site_url,
        # colores precalculados para evitar {% if %} dentro de style=""
        'header_bg': '#DC2626' if es_urgente else '#D97706',
        'badge_bg': '#FEF2F2' if es_urgente else '#FFFBEB',
        'badge_border': '#FECACA' if es_urgente else '#FDE68A',
        'badge_text': '#991B1B' if es_urgente else '#92400E',
        'dias_color': '#DC2626' if es_urgente else '#D97706',
    }
    html = render_to_string('core/emails/recordatorio_vencimiento.html', context)

    subject = _sanitizar_subject(
        f'[GPIV] {"Aviso urgente" if es_urgente else "Recordatorio"}: '
        f'plazo de obra vence en {dias_restantes} día(s)'
    )

    resultado = enviar_email_resend(destino, subject, html)
    if not resultado:
        return None

    from django.utils import timezone as tz
    aviso = AvisoVencimiento.objects.create(
        empresa=empresa,
        nivel=nivel,
        dias_restantes=dias_restantes,
        email_destino=destino,
    )
    empresa.ultimo_aviso_vencimiento = tz.now().date()
    empresa.save(update_fields=['ultimo_aviso_vencimiento'])

    logger.info(
        "Aviso de vencimiento enviado: empresa=%s, nivel=%s, dias=%d, destino=%s",
        empresa.razon_social, nivel, dias_restantes, destino,
    )
    return aviso


def tiene_prorroga_vigente(empresa):
    """
    retorna True si la empresa tiene al menos una prorroga aprobada o
    pendiente. una prorroga pendiente se considera vigente porque la
    empresa ya solicito extension y aun no fue resuelta.
    """
    from .models import SolicitudProrroga
    return empresa.prorrogas.filter(
        estado__in=[
            SolicitudProrroga.EstadoProrroga.APROBADA,
            SolicitudProrroga.EstadoProrroga.PENDIENTE,
        ],
    ).exists()


def ejecutar_caducidad(empresa):
    """
    ejecuta la caducidad de una empresa: transicion de estado, registro
    auditable, y notificacion por email a la empresa.

    parametros:
        empresa: instancia de Empresa con fecha_limite_obra vencida.

    retorna:
        CaducidadRegistro creado, o None si la empresa tiene prorroga vigente.
    """
    from django.template.loader import render_to_string
    from .models import CaducidadRegistro, Empresa

    if tiene_prorroga_vigente(empresa):
        logger.info(
            "Empresa %s (pk=%s) tiene prorroga vigente. Caducidad omitida.",
            empresa.razon_social, empresa.pk,
        )
        return None

    estado_anterior = empresa.estado
    justificacion = (
        f'Vencimiento automático de plazo de obra '
        f'(fecha límite: {empresa.fecha_limite_obra}). '
        f'Sin prórroga aprobada ni pendiente.'
    )

    registrar_transicion(
        empresa,
        Empresa.Estado.CADUCADO,
        usuario=None,
        justificacion=justificacion,
    )

    # notificar a la empresa por email
    destino = empresa.correo_electronico
    notificacion_ok = False
    if destino:
        fecha_limite_str = (
            empresa.fecha_limite_obra.strftime('%d/%m/%Y')
            if empresa.fecha_limite_obra else '—'
        )
        site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        context = {
            'razon_social': empresa.razon_social,
            'cuit': empresa.cuit,
            'fecha_limite': fecha_limite_str,
            'estado_anterior': dict(Empresa.Estado.choices).get(
                estado_anterior, estado_anterior,
            ),
            'site_url': site_url,
        }
        html = render_to_string(
            'core/emails/notificacion_caducidad.html', context,
        )
        subject = _sanitizar_subject(
            f'[GPIV] Caducidad de adjudicación — {empresa.razon_social}'
        )
        resultado = enviar_email_resend(destino, subject, html)
        notificacion_ok = bool(resultado)

    registro = CaducidadRegistro.objects.create(
        empresa=empresa,
        estado_anterior=estado_anterior,
        fecha_limite_original=empresa.fecha_limite_obra,
        justificacion=justificacion,
        email_destino=destino or '',
        notificacion_enviada=notificacion_ok,
    )

    logger.info(
        "Caducidad ejecutada: empresa=%s, estado_anterior=%s, email=%s",
        empresa.razon_social, estado_anterior, 'OK' if notificacion_ok else 'NO',
    )
    return registro


def notificar_admin_caducidades(registros):
    """
    envia un email resumen a SUPPORT_INBOX_EMAIL con la lista de empresas
    que fueron marcadas como caducadas en la ejecucion del batch.

    parametros:
        registros: lista de CaducidadRegistro creados en el batch.

    retorna:
        resultado de enviar_email_resend o None si no hay registros.
    """
    if not registros:
        return None

    filas = ''.join(
        f'<tr>'
        f'<td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">'
        f'{escape(r.empresa.razon_social)}</td>'
        f'<td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">'
        f'{escape(r.empresa.cuit)}</td>'
        f'<td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">'
        f'{r.fecha_limite_original.strftime("%d/%m/%Y")}</td>'
        f'<td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">'
        f'{"✅" if r.notificacion_enviada else "❌"}</td>'
        f'</tr>'
        for r in registros
    )

    html = (
        '<h2>Resumen de caducidades automáticas — GPIV</h2>'
        f'<p>Se ejecutaron <strong>{len(registros)}</strong> '
        f'caducidad(es) automática(s).</p>'
        '<table style="border-collapse:collapse; width:100%; font-size:14px;">'
        '<thead><tr style="background-color:#F3F4F6;">'
        '<th style="padding:8px 12px; text-align:left;">Empresa</th>'
        '<th style="padding:8px 12px; text-align:left;">CUIT</th>'
        '<th style="padding:8px 12px; text-align:left;">Fecha límite</th>'
        '<th style="padding:8px 12px; text-align:left;">Email enviado</th>'
        '</tr></thead>'
        f'<tbody>{filas}</tbody></table>'
        '<hr>'
        '<p style="font-size:12px; color:#6B7280;">'
        'Mensaje automático del Sistema de Gestión del Parque Industrial de'
        ' Viedma.</p>'
    )
    subject = _sanitizar_subject(
        f'[GPIV] {len(registros)} caducidad(es) automática(s) ejecutada(s)'
    )
    return enviar_email_resend(settings.SUPPORT_INBOX_EMAIL, subject, html)


