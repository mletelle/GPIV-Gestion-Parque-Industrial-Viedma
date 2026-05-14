"""
management command: notificar_vencimientos

busca empresas en construccion con vencimiento de obra proximo y manda
mail al contacto via la funcion de servicio enviar_aviso_vencimiento.
se ejecuta desde crontab del servidor todos los dias a las 08:00.

ejemplo de cron:
  0 8 * * * /ruta/venv/bin/python /ruta/proyecto/manage.py \
      notificar_vencimientos >> /var/log/gpiv/vencimientos.log 2>&1

idempotencia: no repite aviso urgente antes de 7 dias ni proximo antes
de 30 dias, consultando AvisoVencimiento por empresa y nivel.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.models import Empresa, AvisoVencimiento
from core.services import enviar_aviso_vencimiento


# no repetir aviso urgente antes de 7 dias ni proximo antes de 30
INTERVALO_URGENTE = timedelta(days=7)
INTERVALO_PROXIMO = timedelta(days=30)


class Command(BaseCommand):
    help = 'Envia avisos de vencimiento de plazo de obra a empresas en construccion'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista las empresas que recibirian aviso sin enviar emails ni crear registros.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        hoy = timezone.now().date()
        limite_urgente = hoy + timedelta(days=7)
        limite_proximo = hoy + timedelta(days=30)
        avisos_urgentes_recientes = AvisoVencimiento.objects.filter(
            empresa=OuterRef('pk'),
            nivel=AvisoVencimiento.Nivel.URGENTE,
            is_active=True,
            fecha_envio__date__gte=hoy - INTERVALO_URGENTE,
        )
        avisos_proximos_recientes = AvisoVencimiento.objects.filter(
            empresa=OuterRef('pk'),
            nivel=AvisoVencimiento.Nivel.PROXIMO,
            is_active=True,
            fecha_envio__date__gte=hoy - INTERVALO_PROXIMO,
        )

        # empresas con vencimiento <= 7 dias (urgentes)
        urgentes = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__range=(hoy, limite_urgente),
        ).annotate(
            aviso_urgente_reciente=Exists(avisos_urgentes_recientes),
        ).filter(
            aviso_urgente_reciente=False,
        )

        # empresas con vencimiento entre 8 y 30 dias (proximos)
        proximos = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__gt=limite_urgente,
            fecha_limite_obra__lte=limite_proximo,
        ).annotate(
            aviso_proximo_reciente=Exists(avisos_proximos_recientes),
        ).filter(
            aviso_proximo_reciente=False,
        )

        enviados_urgentes = 0
        enviados_proximos = 0

        for empresa in urgentes:
            dias = (empresa.fecha_limite_obra - hoy).days
            if dry_run:
                self.stdout.write(
                    f'  [DRY-RUN] URGENTE: {empresa.razon_social} '
                    f'(vence {empresa.fecha_limite_obra}, {dias}d)'
                )
                enviados_urgentes += 1
                continue

            resultado = enviar_aviso_vencimiento(
                empresa, dias, AvisoVencimiento.Nivel.URGENTE,
            )
            if resultado:
                enviados_urgentes += 1

        for empresa in proximos:
            dias = (empresa.fecha_limite_obra - hoy).days
            if dry_run:
                self.stdout.write(
                    f'  [DRY-RUN] PROXIMO: {empresa.razon_social} '
                    f'(vence {empresa.fecha_limite_obra}, {dias}d)'
                )
                enviados_proximos += 1
                continue

            resultado = enviar_aviso_vencimiento(
                empresa, dias, AvisoVencimiento.Nivel.PROXIMO,
            )
            if resultado:
                enviados_proximos += 1

        prefijo = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefijo}Avisos urgentes: {enviados_urgentes}'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'{prefijo}Avisos proximos: {enviados_proximos}'
        ))
