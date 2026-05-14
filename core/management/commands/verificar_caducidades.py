"""
management command: verificar_caducidades

marca como Caducado a las empresas en construccion cuyo plazo de obra
ya vencio y no tienen prorroga aprobada ni pendiente. notifica a cada
empresa afectada y envia un resumen a la administracion.

se ejecuta desde crontab del servidor todos los dias a las 06:00,
antes de notificar_vencimientos (08:00), para que las empresas ya
caducadas no reciban avisos de vencimiento innecesarios.

ejemplo de cron:
  0 6 * * * /ruta/venv/bin/python /ruta/proyecto/manage.py \
      verificar_caducidades >> /var/log/gpiv/caducidades.log 2>&1
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Empresa, SolicitudProrroga
from core.services import ejecutar_caducidad, notificar_admin_caducidades


class Command(BaseCommand):
    help = (
        'Marca como Caducado los proyectos con plazo vencido '
        'que no tengan prórroga aprobada o pendiente'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista las empresas que serian caducadas sin ejecutar cambios.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        hoy = timezone.now().date()

        # empresas en construccion con plazo vencido
        vencidas = Empresa.objects.filter(
            estado=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra__lt=hoy,
        )

        # excluir las que tienen prorroga aprobada o pendiente
        empresas_con_prorroga = SolicitudProrroga.objects.filter(
            estado__in=[
                SolicitudProrroga.EstadoProrroga.APROBADA,
                SolicitudProrroga.EstadoProrroga.PENDIENTE,
            ],
        ).values_list('empresa_id', flat=True)

        candidatas = vencidas.exclude(pk__in=empresas_con_prorroga)

        registros = []

        for empresa in candidatas:
            dias_vencida = (hoy - empresa.fecha_limite_obra).days
            if dry_run:
                self.stdout.write(
                    f'  [DRY-RUN] {empresa.razon_social} '
                    f'(CUIT: {empresa.cuit}, '
                    f'venció hace {dias_vencida}d, '
                    f'límite: {empresa.fecha_limite_obra})'
                )
                registros.append(empresa)  # solo para contar
                continue

            registro = ejecutar_caducidad(empresa)
            if registro:
                registros.append(registro)

        # enviar resumen a la administracion (solo si no es dry-run y hay registros)
        if not dry_run and registros:
            notificar_admin_caducidades(registros)

        prefijo = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefijo}{len(registros)} empresa(s) '
            f'{"listadas para caducidad" if dry_run else "marcadas como Caducadas"}.'
        ))
