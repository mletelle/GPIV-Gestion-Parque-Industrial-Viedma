"""
management command: notificar_vencimientos

busca empresas en construccion con vencimiento de obra proximo y manda
mail al contacto. se ejecuta desde crontab del servidor todos los dias
a las 08:00.

"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Empresa


ASUNTO_URGENTE = '[GPIV] Aviso urgente: plazo de obra vence en {dias} dia(s)'
ASUNTO_PROXIMO = '[GPIV] Recordatorio: plazo de obra vence en {dias} dia(s)'

CUERPO = (
    'Estimado/a {razon_social},\n\n'
    'Le informamos que el plazo maximo para la finalizacion de la obra en el '
    'Parque Industrial de Viedma vence el {fecha}. Quedan {dias} dia(s) habiles.\n\n'
    'Si considera que no llegara a finalizar en termino, puede solicitar una '
    'prorroga desde el panel de GPIV.\n\n'
    'Saludos,\nAdministracion ENREPAVI'
)


class Command(BaseCommand):
    help = 'Envia avisos de vencimiento de plazo de obra a empresas en construccion'

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        limite_urgente = hoy + timedelta(days=7)
        limite_proximo = hoy + timedelta(days=30)

        urgentes = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__range=(hoy, limite_urgente),
        )
        proximos = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__gt=limite_urgente,
            fecha_limite_obra__lte=limite_proximo,
        )

        enviados_urgentes = 0
        enviados_proximos = 0

        for empresa in urgentes:
            dias = (empresa.fecha_limite_obra - hoy).days
            send_mail(
                subject=ASUNTO_URGENTE.format(dias=dias),
                message=CUERPO.format(
                    razon_social=empresa.razon_social,
                    fecha=empresa.fecha_limite_obra.strftime('%d/%m/%Y'),
                    dias=dias,
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[empresa.correo_electronico],
                fail_silently=False,
            )
            enviados_urgentes += 1

        for empresa in proximos:
            dias = (empresa.fecha_limite_obra - hoy).days
            send_mail(
                subject=ASUNTO_PROXIMO.format(dias=dias),
                message=CUERPO.format(
                    razon_social=empresa.razon_social,
                    fecha=empresa.fecha_limite_obra.strftime('%d/%m/%Y'),
                    dias=dias,
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[empresa.correo_electronico],
                fail_silently=False,
            )
            enviados_proximos += 1

        self.stdout.write(self.style.SUCCESS(
            f'Avisos urgentes enviados: {enviados_urgentes}'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Avisos proximos enviados: {enviados_proximos}'
        ))
