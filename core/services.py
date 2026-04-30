"""
capa de servicios de core. centraliza operaciones que usan tanto las vistas
como los management commands, asi evitamos duplicar logica de transicion
y circular imports.
"""
import os
import resend
from django.conf import settings
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


def enviar_email_resend(to_email, subject, html_content):
    """
    Envía un email transaccional usando la API de Resend.
    Requiere que la variable de entorno RESEND_API_KEY esté configurada.
    """
    api_key = os.getenv('RESEND_API_KEY')
    if not api_key:
        print(f"WARN: RESEND_API_KEY no configurada. Simulado envío a {to_email}: {subject}")
        return False

    resend.api_key = api_key
    try:
        r = resend.Emails.send({
            "from": "GPIV <noreply@tivena.com.ar>",
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
        return r
    except Exception as e:
        print(f"ERROR enviando email vía Resend: {e}")
        return False


def notificar_ticket_mensaje(ticket, mensaje):
    """
    Determina a quién hay que notificar de un nuevo mensaje en un ticket.
    Si el autor es el creador del ticket (ej: empresa), notifica al admin.
    Si el autor es otro (admin), notifica al creador del ticket.
    """
    # Si es externo, no tiene creador ni el mensaje tiene autor (en su primer mensaje)
    es_admin = mensaje.autor and (mensaje.autor.is_superuser or mensaje.autor.groups.filter(name='ADMIN_ENREPAVI').exists())
    
    if es_admin:
        # Administrador respondió, notificar al usuario
        if ticket.creador:
            to_email = ticket.creador.email
            nombre = ticket.creador.username
        else:
            to_email = ticket.email_contacto
            nombre = ticket.nombre_contacto

        if to_email:
            subject = f"Respuesta a tu consulta: {ticket.asunto}"
            html_content = f"""
            <p>Hola {nombre},</p>
            <p>El administrador del GPIV ha respondido a tu consulta: <strong>"{ticket.asunto}"</strong>.</p>
            """
            if ticket.creador:
                html_content += "<p>Por favor, ingresá al sistema para leer la respuesta.</p>"
            else:
                html_content += f"<p>La respuesta es:</p><blockquote>{mensaje.contenido}</blockquote>"
                
            html_content += """
            <hr>
            <p><small>Este es un mensaje automático, por favor no respondas a este correo.</small></p>
            """
            enviar_email_resend(to_email, subject, html_content)
    else:
        # Usuario envió mensaje, notificar al administrador
        to_email = "admin@tivena.com.ar"
        nombre_emisor = ticket.creador.username if ticket.creador else ticket.nombre_contacto
        subject = f"Nuevo mensaje en ticket #{ticket.id} - {nombre_emisor}"
        html_content = f"""
        <p>Hola Administrador,</p>
        <p>El usuario <strong>{nombre_emisor}</strong> ha enviado un nuevo mensaje en el ticket: <strong>"{ticket.asunto}"</strong>.</p>
        <p>Por favor, ingresá al panel de administración para responder.</p>
        """
        enviar_email_resend(to_email, subject, html_content)

