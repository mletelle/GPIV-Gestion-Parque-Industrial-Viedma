"""
Management command: crear_datos_iniciales
Crea los 4 Groups del sistema y un superusuario si se proporcionan credenciales.
Idempotente — se puede ejecutar multiples veces sin duplicar datos.

Uso:
  python manage.py crear_datos_iniciales
  python manage.py crear_datos_iniciales --crear-admin --password mipassword
  DJANGO_SUPERUSER_PASSWORD=1234 python manage.py crear_datos_iniciales --crear-admin
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from core.models import CustomUser


GRUPOS = [
    'ADMIN_ENREPAVI',
    'EMPRESA',
    'ORGANISMO_PUBLICO',
    'PROVEEDOR_SERVICIOS',
]


class Command(BaseCommand):
    help = 'Crea los grupos de permisos y opcionalmente un superusuario'

    def add_arguments(self, parser):
        parser.add_argument(
            '--crear-admin',
            action='store_true',
            help='Crear superusuario admin (requiere --password o DJANGO_SUPERUSER_PASSWORD)',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password del superusuario (alternativa a DJANGO_SUPERUSER_PASSWORD)',
        )

    def handle(self, *args, **options):
        for nombre in GRUPOS:
            grupo, creado = Group.objects.get_or_create(name=nombre)
            estado = 'creado' if creado else 'ya existia'
            self.stdout.write(f'  Grupo {nombre}: {estado}')

        if options['crear_admin']:
            password = options['password'] or os.environ.get('DJANGO_SUPERUSER_PASSWORD')
            if not password:
                self.stderr.write(self.style.ERROR(
                    'Debes pasar --password o definir DJANGO_SUPERUSER_PASSWORD'
                ))
                return

            username = 'admin'
            if not CustomUser.objects.filter(username=username).exists():
                user = CustomUser.objects.create_superuser(
                    username=username,
                    password=password,
                    email='admin@gpiv.local',
                )
                grupo_admin = Group.objects.get(name='ADMIN_ENREPAVI')
                user.groups.add(grupo_admin)
                self.stdout.write(self.style.SUCCESS(
                    f'  Superusuario "{username}" creado y asignado a ADMIN_ENREPAVI'
                ))
            else:
                self.stdout.write(f'  Superusuario "{username}" ya existe')

        self.stdout.write(self.style.SUCCESS('Datos iniciales listos.'))
