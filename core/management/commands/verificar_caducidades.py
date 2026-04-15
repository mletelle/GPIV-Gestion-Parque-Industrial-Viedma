"""
management command: verificar_caducidades

marca como Caducado a las empresas en construccion cuyo plazo de obra
ya vencio. se ejecuta desde crontab del servidor todos los dias a las
06:00, antes de notificar_vencimientos.

ejemplo de cron:
  0 6 * * * /ruta/venv/bin/python /ruta/proyecto/manage.py \
      verificar_caducidades >> /var/log/gpiv/caducidades.log 2>&1
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Empresa
from core.services import registrar_transicion


class Command(BaseCommand):
    help = 'Marca como Caducado los proyectos con plazo vencido'

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        vencidas = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__lt=hoy,
        )
        count = 0
        for empresa in vencidas:
            registrar_transicion(
                empresa,
                Empresa.Estado.CADUCADO,
                usuario=None,
                justificacion='Vencimiento automatico de plazo de obra',
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(
            f'{count} empresa(s) marcadas como Caducadas.'
        ))
