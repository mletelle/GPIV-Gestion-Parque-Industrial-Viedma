"""
Management command: cargar_datos_prueba

Crea todo el set de datos de prueba del GPIV de forma idempotente:
  - grupos de permisos
  - 65 parcelas del parque
  - usuarios de admin, empresas, proveedores y organismos
  - empresas cubriendo todos los estados de la FSM
  - avances constructivos, solicitudes de prorroga y consumos coherentes
  - vencimientos proximos para probar el dashboard

Uso:
  docker compose run --rm web python manage.py cargar_datos_prueba

Credenciales: todos los usuarios usan password 'gpiv1234' salvo el superuser.
El listado completo queda en el README.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    AvanceConstructivo,
    ConsumoServicio,
    CustomUser,
    Empresa,
    Lote,
    SolicitudProrroga,
    TransicionEstado,
)


PASSWORD_DEFAULT = 'gpiv1234'
PASSWORD_ADMIN = 'admin1234'

GRUPOS = [
    'ADMIN_ENREPAVI',
    'EMPRESA',
    'ORGANISMO_PUBLICO',
    'PROVEEDOR_AGUA',
    'PROVEEDOR_LUZ',
    'PROVEEDOR_GAS',
]

# parcelas del parque, la 5 es reserva fiscal
PARCELAS = {
    1: 1355.24, 2: 1346.54, 3: 1337.61, 4: 1339.86, 5: 5151.15,
    6: 2575.58, 7: 2575.58, 8: 2575.58, 9: 2493.75, 10: 2507.11,
    11: 2495.07, 12: 2575.58, 13: 2575.58, 14: 2575.58, 15: 5002.93,
    16: 5011.01, 17: 5974.99, 18: 5968.95, 19: 5000.34, 20: 5002.67,
    22: 7292.39, 23: 7255.56, 24: 1245.21, 25: 1250.83, 26: 1250.36,
    27: 1250.23, 28: 1267.09, 29: 1815.00, 30: 1815.00, 31: 1815.00,
    32: 1815.00, 33: 1815.00, 34: 1815.00, 35: 1815.00, 36: 1705.60,
    37: 1713.60, 38: 1800.00, 39: 1800.00, 40: 1705.60, 41: 1713.60,
    42: 1815.00, 43: 1815.00, 44: 1815.00, 45: 1815.00, 46: 1815.00,
    47: 1815.00, 48: 1815.00, 49: 2496.70, 50: 2504.70, 51: 2504.70,
    52: 2504.70, 53: 3339.62, 54: 3339.62, 55: 2496.70, 56: 2504.70,
    57: 2504.70, 58: 2496.70, 59: 3339.62, 60: 3339.62, 61: 2927.25,
    62: 2927.46, 63: 2919.67, 64: 2911.88, 65: 2921.15,
}


# catalogo de empresas de prueba
# los que estan con lote tienen parcela asignada (numero de parcela)
# los consumos se generan automaticamente segun estado
EMPRESAS_PRUEBA = [
    {
        'username': 'empresa_alfa',
        'email': 'alfa@test.local',
        'razon_social': 'Alfa Alimentos S.A.',
        'cuit': '30-11111111-1',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.ALIMENTICIA,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': Decimal('1500.00'),
        'estado': Empresa.Estado.EN_EVALUACION,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
    },
    {
        'username': 'empresa_beta',
        'email': 'beta@test.local',
        'razon_social': 'Beta Tech S.R.L.',
        'cuit': '30-22222222-2',
        'rubro': Empresa.Rubro.BIENES_Y_SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.TECNOLOGICA,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': Decimal('2400.00'),
        'estado': Empresa.Estado.PRE_APROBADO,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
    },
    {
        'username': 'empresa_gamma',
        'email': 'gamma@test.local',
        'razon_social': 'Gamma Quimica S.A.',
        'cuit': '30-33333333-3',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.QUIMICA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('5000.00'),
        'estado': Empresa.Estado.RECHAZADO,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
    },
    {
        'username': 'empresa_delta',
        'email': 'delta@test.local',
        'razon_social': 'Delta Servicios S.R.L.',
        'cuit': '30-44444444-4',
        'rubro': Empresa.Rubro.SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': Decimal('1300.00'),
        'estado': Empresa.Estado.RADICADA,
        'parcela': 24,
        'fecha_limite_offset_dias': 180,
        'avances': [],
    },
    {
        'username': 'empresa_epsilon',
        'email': 'epsilon@test.local',
        'razon_social': 'Epsilon Construcciones S.A.',
        'cuit': '30-55555555-5',
        'rubro': Empresa.Rubro.BIENES_Y_SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('1800.00'),
        'estado': Empresa.Estado.EN_CONSTRUCCION,
        # vencimiento a 18 dias para aparecer en el dashboard
        'parcela': 29,
        'fecha_limite_offset_dias': 18,
        'avances': [(25, True), (55, True)],
    },
    {
        'username': 'empresa_zeta',
        'email': 'zeta@test.local',
        'razon_social': 'Zeta Metalurgica S.A.',
        'cuit': '30-66666666-6',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': Decimal('1800.00'),
        'estado': Empresa.Estado.EN_CONSTRUCCION,
        # vencimiento urgente a 7 dias
        'parcela': 30,
        'fecha_limite_offset_dias': 7,
        'avances': [(30, True), (60, False)],
    },
    {
        'username': 'empresa_eta',
        'email': 'eta@test.local',
        'razon_social': 'Eta Logistica S.R.L.',
        'cuit': '30-77777777-7',
        'rubro': Empresa.Rubro.SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('1700.00'),
        'estado': Empresa.Estado.FINALIZADO,
        'parcela': 36,
        'fecha_limite_offset_dias': 60,
        'avances': [(40, True), (75, True), (100, True)],
    },
    {
        'username': 'empresa_theta',
        'email': 'theta@test.local',
        'razon_social': 'Theta Alimentos del Sur S.A.',
        'cuit': '30-88888888-8',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.ALIMENTICIA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('2500.00'),
        'estado': Empresa.Estado.FINALIZADO,
        'parcela': 6,
        'fecha_limite_offset_dias': 90,
        'avances': [(50, True), (100, True)],
    },
    # empresas "viejas" sin usuario asignado, ya escrituradas
    {
        'username': None,
        'email': None,
        'razon_social': 'Fundidora del Atlantico S.A.',
        'cuit': '30-99999991-0',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('5000.00'),
        'estado': Empresa.Estado.ESCRITURADO,
        'parcela': 15,
        'fecha_limite_offset_dias': None,
        'avances': [(100, True)],
    },
    {
        'username': None,
        'email': None,
        'razon_social': 'Molinos Patagonicos S.R.L.',
        'cuit': '30-99999992-1',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.ALIMENTICIA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': Decimal('2500.00'),
        'estado': Empresa.Estado.ESCRITURADO,
        'parcela': 7,
        'fecha_limite_offset_dias': None,
        'avances': [(100, True)],
    },
]


# defaults para completar campos obligatorios del modelo Empresa
EMPRESA_DEFAULTS = {
    'actividad_principal': 'Actividad principal de prueba',
    'descripcion_actividad': 'Descripcion generada por cargar_datos_prueba',
    'persona_referente': 'Referente de Prueba',
    'telefono': '+54 9 2920 000000',
    'personal_jerarquico': 1,
    'personal_produccion': 10,
    'personal_administrativo': 2,
    'personal_a_ocupar': 15,
    'superficie_cubierta_trabajo_m2': Decimal('400.00'),
    'superficie_cubierta_deposito_m2': Decimal('200.00'),
    'tiene_planos': True,
    'tiempo_radicacion_meses': Empresa.TiempoRadicacion.MESES_12,
    'maneja_inflamables': False,
    'tratamiento_en_planta': False,
}


ADMINS = [
    ('admin', 'admin@gpiv.local', 'Administrador Principal', True),
    ('admin_enrepavi', 'enrepavi@gpiv.local', 'Admin ENREPAVI', False),
]

PROVEEDORES = [
    ('proveedor_agua', 'agua@proveedores.gpiv.local', 'Proveedor Agua', 'PROVEEDOR_AGUA'),
    ('proveedor_luz', 'luz@proveedores.gpiv.local', 'Proveedor Electricidad', 'PROVEEDOR_LUZ'),
    ('proveedor_gas', 'gas@proveedores.gpiv.local', 'Proveedor Gas', 'PROVEEDOR_GAS'),
]

ORGANISMOS = [
    ('organismo_municipal', 'municipal@gob.gpiv.local', 'Municipio de Viedma'),
    ('organismo_provincial', 'provincial@gob.gpiv.local', 'Gobierno Rio Negro'),
]


def _crear_user(username, email, full_name, password,
                grupos=None, is_superuser=False):
    """crea o actualiza un usuario asegurando password y grupos"""
    partes = full_name.split(' ', 1)
    defaults = {
        'email': email or '',
        'first_name': partes[0],
        'last_name': partes[1] if len(partes) > 1 else '',
        'is_staff': is_superuser or 'ADMIN_ENREPAVI' in (grupos or []),
        'is_superuser': is_superuser,
    }
    user, creado = CustomUser.objects.update_or_create(
        username=username, defaults=defaults,
    )
    user.set_password(password)
    user.save()
    if grupos:
        for nombre in grupos:
            grupo = Group.objects.get(name=nombre)
            user.groups.add(grupo)
    return user, creado


def _consumos_para(empresa, meses=6):
    """genera consumos mensuales coherentes segun el estado.
    solo estados con radicacion vigente tienen consumo."""
    if empresa.estado not in [
        Empresa.Estado.RADICADA,
        Empresa.Estado.EN_CONSTRUCCION,
        Empresa.Estado.FINALIZADO,
        Empresa.Estado.ESCRITURADO,
    ]:
        return []

    hoy = timezone.now().date()
    consumos = []
    for i in range(1, meses + 1):
        # retrocede aproximadamente un mes por iteracion
        anio = hoy.year
        mes = hoy.month - i
        while mes <= 0:
            mes += 12
            anio -= 1
        # radicada: solo agua, aun no opera maquinaria
        if empresa.estado == Empresa.Estado.RADICADA:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': Decimal('8.50') + Decimal(i) * Decimal('0.5'),
                'consumo_agua_cruda_m3': None,
                'consumo_luz_kwh': Decimal('120.00') + Decimal(i) * Decimal('10'),
                'consumo_gas_m3': None,
            })
        # en construccion: agua + luz de obra, sin gas industrial
        elif empresa.estado == Empresa.Estado.EN_CONSTRUCCION:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': Decimal('25.00') + Decimal(i) * Decimal('2'),
                'consumo_agua_cruda_m3': Decimal('15.00'),
                'consumo_luz_kwh': Decimal('850.00') + Decimal(i) * Decimal('25'),
                'consumo_gas_m3': None,
            })
        # finalizado/escriturado: operacion completa
        else:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': Decimal('45.00') + Decimal(i) * Decimal('1.5'),
                'consumo_agua_cruda_m3': Decimal('120.00'),
                'consumo_luz_kwh': Decimal('3200.00') + Decimal(i) * Decimal('80'),
                'consumo_gas_m3': Decimal('450.00') + Decimal(i) * Decimal('10'),
            })
    return consumos


class Command(BaseCommand):
    help = 'Carga grupos, lotes, usuarios, empresas y consumos de prueba'

    @transaction.atomic
    def handle(self, *args, **options):
        self._log('-- Cargando grupos...')
        for nombre in GRUPOS:
            Group.objects.get_or_create(name=nombre)

        self._log('-- Cargando parcelas...')
        for nro, superficie in PARCELAS.items():
            estado = Lote.Estado.RESERVA_FISCAL if nro == 5 else Lote.Estado.DISPONIBLE
            Lote.objects.update_or_create(
                nro_parcela=nro,
                defaults={'superficie_m2': superficie, 'estado': estado},
            )

        self._log('-- Cargando admins...')
        for username, email, nombre, is_super in ADMINS:
            _crear_user(
                username, email, nombre,
                PASSWORD_ADMIN if is_super else PASSWORD_DEFAULT,
                grupos=['ADMIN_ENREPAVI'],
                is_superuser=is_super,
            )

        self._log('-- Cargando proveedores...')
        for username, email, nombre, grupo in PROVEEDORES:
            _crear_user(
                username, email, nombre, PASSWORD_DEFAULT,
                grupos=[grupo],
            )

        self._log('-- Cargando organismos publicos...')
        for username, email, nombre in ORGANISMOS:
            _crear_user(
                username, email, nombre, PASSWORD_DEFAULT,
                grupos=['ORGANISMO_PUBLICO'],
            )

        self._log('-- Cargando empresas de prueba...')
        for spec in EMPRESAS_PRUEBA:
            self._crear_empresa(spec)

        self._imprimir_resumen()

    def _crear_empresa(self, spec):
        usuario = None
        if spec['username']:
            usuario, _ = _crear_user(
                spec['username'],
                spec['email'],
                spec['razon_social'],
                PASSWORD_DEFAULT,
                grupos=['EMPRESA'],
            )

        hoy = timezone.now().date()
        fecha_limite = None
        if spec['fecha_limite_offset_dias'] is not None:
            fecha_limite = hoy + timedelta(days=spec['fecha_limite_offset_dias'])

        empresa_defaults = dict(EMPRESA_DEFAULTS)
        empresa_defaults.update({
            'usuario': usuario,
            'razon_social': spec['razon_social'],
            'rubro': spec['rubro'],
            'categoria_industrial': spec['categoria_industrial'],
            'tipo_empresa': spec['tipo_empresa'],
            'necesidad_m2': spec['necesidad_m2'],
            'estado': spec['estado'],
            'correo_electronico': spec['email'] or f'contacto@{spec["cuit"]}.local',
            'fecha_limite_obra': fecha_limite,
        })

        empresa, creada = Empresa.objects.update_or_create(
            cuit=spec['cuit'],
            defaults=empresa_defaults,
        )

        # asignar lote si corresponde y liberar el anterior si hubiera
        if spec['parcela']:
            # liberar lote que esta empresa tuviera asignado y no sea el target
            empresa.lotes.exclude(nro_parcela=spec['parcela']).update(
                estado=Lote.Estado.DISPONIBLE, empresa=None,
            )
            lote = Lote.objects.get(nro_parcela=spec['parcela'])
            lote.estado = Lote.Estado.EN_USO
            lote.empresa = empresa
            lote.save(update_fields=['estado', 'empresa'])

        # limpiar y recrear avances
        empresa.avances_constructivos.all().delete()
        for pct, validado in spec['avances']:
            AvanceConstructivo.objects.create(
                empresa=empresa,
                porcentaje_declarado=Decimal(pct),
                certificado_pdf='certificados/placeholder.pdf',
                validado_admin=validado,
            )

        # limpiar historial y dejar una transicion representativa
        empresa.historial_estados.all().delete()
        TransicionEstado.objects.create(
            empresa=empresa,
            estado_anterior=None,
            estado_nuevo=spec['estado'],
            usuario=usuario,
            justificacion_resolucion='Cargado por cargar_datos_prueba',
        )

        # recrear consumos coherentes con el estado
        empresa.consumos.all().delete()
        for c in _consumos_para(empresa):
            ConsumoServicio.objects.create(empresa=empresa, **c)

        # prorroga pendiente de ejemplo en una empresa en construccion
        if spec['username'] == 'empresa_zeta':
            empresa.prorrogas.all().delete()
            SolicitudProrroga.objects.create(
                empresa=empresa,
                meses_solicitados=Empresa.TiempoRadicacion.MESES_6,
                justificacion='Demora en entrega de maquinaria importada.',
            )

        marca = '+' if creada else '='
        self._log(f'   {marca} {empresa.razon_social} [{empresa.estado}]')

    def _imprimir_resumen(self):
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('DATOS DE PRUEBA LISTOS'))
        self.stdout.write('=' * 70)
        self.stdout.write('Password por defecto: ' + PASSWORD_DEFAULT)
        self.stdout.write('Password superuser  : ' + PASSWORD_ADMIN)
        self.stdout.write('')

        self.stdout.write(self.style.MIGRATE_HEADING('ADMINISTRADORES'))
        for u, _, n, sup in ADMINS:
            rol = 'superuser' if sup else 'ADMIN_ENREPAVI'
            self.stdout.write(f'  {u:22s} {rol:16s} {n}')

        self.stdout.write(self.style.MIGRATE_HEADING('\nPROVEEDORES'))
        for u, _, n, g in PROVEEDORES:
            self.stdout.write(f'  {u:22s} {g:20s} {n}')

        self.stdout.write(self.style.MIGRATE_HEADING('\nORGANISMOS PUBLICOS'))
        for u, _, n in ORGANISMOS:
            self.stdout.write(f'  {u:22s} ORGANISMO_PUBLICO    {n}')

        self.stdout.write(self.style.MIGRATE_HEADING('\nEMPRESAS'))
        for spec in EMPRESAS_PRUEBA:
            user = spec['username'] or '(sin usuario)'
            parcela = f'parcela {spec["parcela"]:03d}' if spec['parcela'] else 'sin lote'
            self.stdout.write(
                f'  {user:22s} {spec["estado"]:15s} '
                f'{parcela:13s} {spec["razon_social"]}'
            )
        self.stdout.write('=' * 70)

    def _log(self, msg):
        self.stdout.write(msg)
