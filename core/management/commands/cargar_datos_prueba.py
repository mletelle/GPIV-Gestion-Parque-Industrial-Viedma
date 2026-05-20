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
    ActivoInventario,
    AvanceConstructivo,
    ConsumoServicio,
    CustomUser,
    Empresa,
    Lote,
    MensajeTicket,
    SolicitudAcceso,
    SolicitudProrroga,
    Ticket,
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

# parcelas del parque con medidas del plano catastral y posiciones svg.
# formato: nro -> (superficie, ancho_m, alto_m, mapa_x, mapa_y, mapa_w, mapa_h)
# la parcela 5 es reserva fiscal. la 21 no existe.
# posiciones svg calculadas a escala ~2px/m, viewBox 1400x700, servidumbre y=355.
PARCELAS = {
    # manzana A (x=20 y=20 w=184 h=316)
    22: (7292.39, 92.07, 79.35,   20,  20, 184, 158),
    23: (7255.56, 91.36, 79.16,   20, 178, 184, 158),
    # manzana B (x=254 y=20 w=460 h=278) todos tocan base y=298
    20: (5002.67, 72.10, 69.39,  254,  20, 144, 139),
    19: (5000.34, 68.10, 65.39,  254, 159, 144, 139),
    18: (5968.95, 42.95, 139.02, 398,  20,  86, 278),
    17: (5974.99, 42.95, 139.12, 484,  20,  86, 278),
    15: (5002.93, 72.00, 69.49,  570,  20, 144, 139),
    16: (5011.01, 68.00, 65.79,  570, 159, 144, 139),
    # manzana C (x=764 y=40 right=1315) calle arriba 20px
    11: (2495.07, 61.70, 34.16,  764,  40, 134,  76),
    10: (2507.11, 65.70, 38.16,  764, 116, 134,  76),
     9: (2493.75, 61.70, 34.01,  764, 192, 134,  76),
    12: (2575.58, 45.00, 57.24,  898,  40,  90, 114),
    13: (2575.58, 45.00, 57.24,  988,  40,  90, 114),
    14: (2575.58, 45.00, 57.24, 1078,  40,  90, 114),
     8: (2575.58, 45.00, 57.24,  898, 154,  90, 114),
     7: (2575.58, 45.00, 57.24,  988, 154,  90, 114),
     6: (2575.58, 45.00, 57.24, 1078, 154,  90, 114),
     5: (5151.15, 45.00, 114.47, 1168,  40,  90, 228),
     1: (1355.24, 28.62, 43.52, 1258,  40,  57,  57),
     2: (1346.54, 28.62, 47.21, 1258,  97,  57,  57),
     3: (1337.61, 28.62, 46.89, 1258, 154,  57,  57),
     4: (1339.86, 29.11, 46.58, 1258, 211,  57,  57),
    # manzana D (x=20 y=380 w=184 h=280) independiente
    61: (2927.25, 86.45, 34.00,   20, 380, 184,  56),
    62: (2927.46, 85.99, 34.00,   20, 436, 184,  56),
    63: (2919.67, 85.76, 34.00,   20, 492, 184,  56),
    64: (2911.88, 85.53, 34.00,   20, 548, 184,  56),
    65: (2921.15, 85.30, 34.20,   20, 604, 184,  56),
    # manzana E (x=254 y=380 w=460 h=280 right=714) rectangulo cerrado
    # subcols: 135 + 95 + 95 + 135 = 460
    58: (2496.70, 65.00, 32.30,  254, 380, 135,  70),
    57: (2504.70, 69.00, 36.30,  254, 450, 135,  70),
    56: (2504.70, 69.00, 36.30,  254, 520, 135,  70),
    55: (2496.70, 65.00, 32.30,  254, 590, 135,  70),
    59: (3339.62, 46.00, 72.60,  389, 380,  95, 140),
    54: (3339.62, 46.00, 72.60,  389, 520,  95, 140),
    60: (3339.62, 46.00, 72.60,  484, 380,  95, 140),
    53: (3339.62, 46.00, 72.60,  484, 520,  95, 140),
    49: (2496.70, 65.00, 32.30,  579, 380, 135,  70),
    50: (2504.70, 69.00, 36.30,  579, 450, 135,  70),
    51: (2504.70, 69.00, 36.30,  579, 520, 135,  70),
    52: (2504.70, 65.00, 32.30,  579, 590, 135,  70),
    # manzana F (x=764 y=380 right=1315 h=280) todo flush, sin gaps
    # sub-bloque G (x=764 w=144): 92+48+48+92=280
    40: (1705.60, 36.00, 47.60,  764, 380,  72,  92),
    41: (1713.60, 36.00, 47.60,  836, 380,  72,  92),
    39: (1800.00, 72.00, 25.00,  764, 472, 144,  48),
    38: (1800.00, 72.00, 25.00,  764, 520, 144,  48),
    36: (1705.60, 36.00, 47.60,  764, 568,  72,  92),
    37: (1713.60, 36.00, 47.60,  836, 568,  72,  92),
    # sub-bloque H (x=908 w=350) flush con G, 2 filas de 140
    42: (1815.00, 25.00, 72.60,  908, 380,  50, 140),
    43: (1815.00, 25.00, 72.60,  958, 380,  50, 140),
    44: (1815.00, 25.00, 72.60, 1008, 380,  50, 140),
    45: (1815.00, 25.00, 72.60, 1058, 380,  50, 140),
    46: (1815.00, 25.00, 72.60, 1108, 380,  50, 140),
    47: (1815.00, 25.00, 72.60, 1158, 380,  50, 140),
    48: (1815.00, 25.00, 72.60, 1208, 380,  50, 140),
    35: (1815.00, 25.00, 72.60,  908, 520,  50, 140),
    34: (1815.00, 25.00, 72.60,  958, 520,  50, 140),
    33: (1815.00, 25.00, 72.60, 1008, 520,  50, 140),
    32: (1815.00, 25.00, 72.60, 1058, 520,  50, 140),
    31: (1815.00, 25.00, 72.60, 1108, 520,  50, 140),
    30: (1815.00, 25.00, 72.60, 1158, 520,  50, 140),
    29: (1815.00, 25.00, 72.60, 1208, 520,  50, 140),
    # columna I (x=1258 w=57) flush con H
    24: (1245.21, 39.88, 28.64, 1258, 380,  57,  56),
    25: (1250.83, 43.63, 28.75, 1258, 436,  57,  56),
    26: (1250.36, 43.38, 28.97, 1258, 492,  57,  56),
    27: (1250.23, 43.13, 29.07, 1258, 548,  57,  56),
    28: (1267.09, 42.88, 29.83, 1258, 604,  57,  56),
}

# lindantes por lote (comparten borde fisico; no cuenta contacto por vertice
# ni lotes separados por calles/servidumbre).
LINDANTES = {
    22: [23], 23: [22],
    20: [19, 18], 19: [20, 18], 18: [20, 19, 17], 17: [18, 15, 16],
    15: [17, 16], 16: [15, 17],
    11: [10, 12], 10: [8, 9, 11, 12], 9: [8, 10],
    12: [8, 10, 11, 13], 13: [7, 12, 14], 14: [5, 6, 13],
    8: [7, 9, 10, 12], 7: [6, 8, 13], 6: [5, 7, 14],
    5: [1, 2, 3, 4, 6, 14],
    1: [2, 5], 2: [1, 3, 5], 3: [2, 4, 5], 4: [3, 5],
    61: [62], 62: [61, 63], 63: [62, 64], 64: [63, 65], 65: [64],
    58: [57, 59], 57: [56, 58, 59], 56: [54, 55, 57],
    55: [56, 54], 59: [58, 57, 60, 54], 54: [59, 56, 55, 53],
    60: [49, 50, 53, 59], 53: [51, 52, 54, 60],
    49: [50, 60], 50: [49, 51, 60], 51: [50, 52, 53], 52: [51, 53],
    40: [39, 41], 41: [39, 40, 42], 39: [38, 40, 41, 42], 38: [35, 36, 37, 39],
    36: [37, 38], 37: [35, 36, 38],
    42: [35, 39, 41, 43], 43: [34, 42, 44], 44: [33, 43, 45], 45: [32, 44, 46],
    46: [45, 47, 31], 47: [46, 48, 30], 48: [24, 25, 26, 29, 47],
    35: [34, 37, 38, 42], 34: [33, 35, 43], 33: [32, 34, 44], 32: [31, 33, 45],
    31: [46, 32, 30], 30: [47, 31, 29],
    24: [25, 48], 25: [24, 26, 48], 26: [25, 27, 29, 48],
    27: [26, 28, 29], 28: [27, 29], 29: [26, 27, 28, 30, 48],
}


SERVICIOS_NO_DISPONIBLES = {
    # La mayoria de los lotes tiene servicios completos. Estas excepciones
    # dejan casos visibles para probar filtros, edicion y adjudicacion.
    'agua_potable': {65},
    'agua_cruda': {1, 2, 3, 4, 24, 25, 26, 27, 28, 61, 62, 63, 64, 65},
    'electricidad': {65},
    'gas': {1, 2, 3, 4, 24, 25, 26, 27, 28, 40, 41, 65},
    'internet': {22, 23, 61, 65},
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
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.EN_EVALUACION,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
        'miembros_estandar': [],
    },
    {
        'username': 'empresa_beta',
        'email': 'beta@test.local',
        'razon_social': 'Beta Insumos Quimicos S.R.L.',
        'cuit': '30-22222222-2',
        'rubro': Empresa.Rubro.BIENES_Y_SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.QUIMICA,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': '2000a5000',
        'estado': Empresa.Estado.PRE_APROBADO,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
        'miembros_estandar': [],
    },
    {
        'username': 'empresa_gamma',
        'email': 'gamma@test.local',
        'razon_social': 'Gamma Quimica S.A.',
        'cuit': '30-33333333-3',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.QUIMICA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': 'Mas5000',
        'estado': Empresa.Estado.RECHAZADO,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [],
        'miembros_estandar': [],
    },
    {
        'username': 'empresa_delta',
        'email': 'delta@test.local',
        'razon_social': 'Delta Servicios S.R.L.',
        'cuit': '30-44444444-4',
        'rubro': Empresa.Rubro.SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.RADICADA,
        'parcela': 24,
        'fecha_limite_offset_dias': 180,
        'avances': [],
        # equipo con 1 miembro: ejercita vista Mi Equipo y flujo de remocion
        'miembros_estandar': [
            ('miembro_delta_1', 'miembro1.delta@test.local', 'Laura Castillo'),
        ],
    },
    {
        'username': 'empresa_epsilon',
        'email': 'epsilon@test.local',
        'razon_social': 'Epsilon Construcciones S.A.',
        'cuit': '30-55555555-5',
        'rubro': Empresa.Rubro.BIENES_Y_SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.EN_CONSTRUCCION,
        # vencimiento a 18 dias para aparecer en el dashboard
        'parcela': 29,
        'fecha_limite_offset_dias': 18,
        'avances': [(25, True), (55, True)],
        # equipo con 2 miembros: ejercita flujo de transferencia de titularidad
        'miembros_estandar': [
            ('miembro_epsilon_1', 'miembro1.epsilon@test.local', 'Rodrigo Perez'),
            ('miembro_epsilon_2', 'miembro2.epsilon@test.local', 'Sofia Vera'),
        ],
    },
    {
        'username': 'empresa_zeta',
        'email': 'zeta@test.local',
        'razon_social': 'Zeta Metalurgica S.A.',
        'cuit': '30-66666666-6',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.NUEVA,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.EN_CONSTRUCCION,
        # vencimiento urgente a 7 dias
        'parcela': 30,
        'fecha_limite_offset_dias': 7,
        'avances': [(30, True), (60, False)],
        'miembros_estandar': [],
    },
    {
        'username': 'empresa_eta',
        'email': 'eta@test.local',
        'razon_social': 'Eta Logistica S.R.L.',
        'cuit': '30-77777777-7',
        'rubro': Empresa.Rubro.SERVICIOS,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.FINALIZADO,
        'parcela': 36,
        'fecha_limite_offset_dias': 60,
        'avances': [(40, True), (75, True), (100, True)],
        'miembros_estandar': [],
    },
    {
        'username': 'empresa_pix',
        'email': 'pix@test.local',
        'razon_social': 'Pix Alimentos del Sur S.A.',
        'cuit': '30-88888888-8',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.ALIMENTICIA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '2000a5000',
        'estado': Empresa.Estado.FINALIZADO,
        'parcela': 6,
        'fecha_limite_offset_dias': 90,
        'avances': [(50, True), (100, True)],
        'miembros_estandar': [],
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
        'necesidad_m2': 'Mas5000',
        'estado': Empresa.Estado.ESCRITURADO,
        'parcela': 15,
        'fecha_limite_offset_dias': None,
        'avances': [(100, True)],
        'miembros_estandar': [],
    },
    {
        'username': None,
        'email': None,
        'razon_social': 'Molinos Patagonicos S.R.L.',
        'cuit': '30-99999992-1',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.ALIMENTICIA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '2000a5000',
        'estado': Empresa.Estado.ESCRITURADO,
        'parcela': 7,
        'fecha_limite_offset_dias': None,
        'avances': [(100, True)],
        'miembros_estandar': [],
    },
    # caducada: vencio el plazo de obra, todavia sin baja
    {
        'username': 'empresa_iota',
        'email': 'iota@test.local',
        'razon_social': 'Iota Maderas S.R.L.',
        'cuit': '30-10101010-1',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.OTRO,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.CADUCADO,
        'parcela': 31,
        'fecha_limite_offset_dias': -45,
        'avances': [(15, True), (30, False)],
        'miembros_estandar': [],
    },
    # baja historica: lote liberado, registro conservado por trazabilidad
    {
        'username': None,
        'email': None,
        'razon_social': 'Kappa Plasticos S.A.',
        'cuit': '30-11111212-2',
        'rubro': Empresa.Rubro.BIENES,
        'categoria_industrial': Empresa.CategoriaIndustrial.QUIMICA,
        'tipo_empresa': Empresa.TipoEmpresa.EXISTENTE,
        'necesidad_m2': '1000a2000',
        'estado': Empresa.Estado.HISTORICO_BAJA,
        'parcela': None,
        'fecha_limite_offset_dias': None,
        'avances': [(20, True)],
        'miembros_estandar': [],
    },
]


# usuarios en grupo EMPRESA sin empresa asignada.
# representan cuentas listas para ser invitadas por un TITULAR
# (flujo: Mi Equipo → Invitar → POST /empresa/usuarios/invitar/).
USUARIOS_LIBRES_EMPRESA = [
    ('empresa_libre_1', 'libre1@test.local', 'Pedro Martinez'),
    ('empresa_libre_2', 'libre2@test.local', 'Ana Rodriguez'),
]


# activos de inventario del ENREPAVI: codigo_inventario se autogenera en el modelo.
# textos en estilo "cargado a mano": minusculas, marcas/modelos abreviados,
# observaciones cortas, varios campos vacios. evita la sensacion de fixture
# autogenerada (tipo prefijos largos de numero de serie).
INVENTARIO_PRUEBA = [
    # informatico / mobiliario de oficina
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'pc oficina dell',
        'descripcion': 'pc de escritorio',
        'marca': 'dell',
        'modelo': None,
        'numero_serie': '001',
        'fecha_alta_offset_dias': -730,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'oficina administrativa - escritorio 1',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'pc oficina dell',
        'descripcion': 'pc de escritorio',
        'marca': 'dell',
        'modelo': None,
        'numero_serie': '002',
        'fecha_alta_offset_dias': -730,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'oficina administrativa - escritorio 2',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'notebook lenovo',
        'descripcion': 'notebook para trabajo en campo',
        'marca': 'lenovo',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -400,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'direccion',
        'observaciones': 'la usa el director',
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'impresora hp',
        'descripcion': 'impresora multifuncion compartida',
        'marca': 'hp',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -900,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'sala comun',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'monitor 24',
        'descripcion': None,
        'marca': 'samsung',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -365,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'oficina administrativa - escritorio 3',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'switch tplink',
        'descripcion': 'switch 24 puertos',
        'marca': 'tplink',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -1100,
        'estado': ActivoInventario.Estado.EN_DEPOSITO,
        'ubicacion': 'sala de servidores',
        'observaciones': 'queda de backup',
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'escritorio',
        'descripcion': None,
        'marca': None,
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -1460,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'oficina administrativa - escritorio 1',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'silla oficina',
        'descripcion': None,
        'marca': None,
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -1460,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'oficina administrativa - escritorio 1',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
        'nombre': 'proyector',
        'descripcion': 'proyector sala de reuniones',
        'marca': 'epson',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -800,
        'estado': ActivoInventario.Estado.EN_REPARACION,
        'ubicacion': 'sala de reuniones',
        'observaciones': 'falla la lampara, en service',
    },
    # equipamiento de mantenimiento
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'camioneta',
        'descripcion': 'camioneta de servicio',
        'marca': 'toyota',
        'modelo': 'hilux',
        'numero_serie': None,
        'fecha_alta_offset_dias': -500,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'playa de vehiculos',
        'observaciones': 'dominio ab 123 cd',
    },
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'hidrolavadora',
        'descripcion': None,
        'marca': 'karcher',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -750,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'deposito de mantenimiento',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'generador',
        'descripcion': 'grupo electrogeno de emergencia',
        'marca': None,
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -1500,
        'estado': ActivoInventario.Estado.EN_DEPOSITO,
        'ubicacion': 'galpon 2',
        'observaciones': 'verificar 1er lunes de cada mes',
    },
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'taladro',
        'descripcion': None,
        'marca': 'bosch',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -950,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'deposito de herramientas',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'cortadora pasto',
        'descripcion': None,
        'marca': 'honda',
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -800,
        'estado': ActivoInventario.Estado.EN_USO,
        'ubicacion': 'deposito de herramientas',
        'observaciones': None,
    },
    {
        'categoria': ActivoInventario.Categoria.EQUIPAMIENTO_MANTENIMIENTO,
        'nombre': 'escalera',
        'descripcion': 'escalera de aluminio 3 cuerpos',
        'marca': None,
        'modelo': None,
        'numero_serie': None,
        'fecha_alta_offset_dias': -1200,
        'estado': ActivoInventario.Estado.DE_BAJA,
        'ubicacion': None,
        'observaciones': 'rota, descartada',
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


SOLICITUDES_ACCESO_PRUEBA = [
    {
        'tipo': SolicitudAcceso.Tipo.PROVEEDOR,
        'nombre_apellido': 'Carlos Benitez',
        'cargo': 'Supervisor de Redes',
        'organizacion': 'Gasnor S.A.',
        'telefono': '+54 9 2920 444222',
        'email_institucional': 'cbenitez@gasnor.com.ar',
        'tipo_acceso': 'GAS',
        'motivo': 'Necesito acceso para registrar los consumos mensuales de gas '
                  'de las empresas radicadas en el parque.',
        'estado': SolicitudAcceso.Estado.PENDIENTE,
    },
    {
        'tipo': SolicitudAcceso.Tipo.ORGANISMO,
        'nombre_apellido': 'Florencia Aguirre',
        'cargo': 'Directora de Desarrollo Productivo',
        'organizacion': 'Ministerio de Produccion — Provincia de Rio Negro',
        'telefono': '+54 9 2920 333111',
        'email_institucional': 'faguirre@mprod.rionegro.gov.ar',
        'tipo_acceso': 'PROVINCIAL',
        'motivo': 'Seguimiento del estado de ocupacion y avance constructivo '
                  'del parque para informes de gestion provincial.',
        'estado': SolicitudAcceso.Estado.PENDIENTE,
    },
]


# tickets de mensajeria interna y consultas externas (issue #25).
# 'creador' = username del usuario logueado, o None para externos.
# cada entry tiene una lista de mensajes con (autor_username, contenido) en
# orden cronologico. autor=None marca el mensaje inicial de un externo.
TICKETS_PRUEBA = [
    {
        'creador': None,
        'nombre_contacto': 'Juan Perez',
        'email_contacto': 'juan.perez@example.com',
        'telefono_contacto': '+54 9 2920 555111',
        'asunto': 'consulta por disponibilidad de lotes',
        'categoria': Ticket.Categoria.EXTERNA,
        'estado': Ticket.Estado.ABIERTO,
        'mensajes': [
            (None, 'hola, queria saber si quedan lotes disponibles para una metalurgica chica. gracias.'),
        ],
    },
    {
        'creador': None,
        'nombre_contacto': 'Maria Lopez',
        'email_contacto': 'maria.lopez@example.com',
        'telefono_contacto': None,
        'asunto': 'requisitos para habilitacion comercial',
        'categoria': Ticket.Categoria.EXTERNA,
        'estado': Ticket.Estado.CERRADO,
        'mensajes': [
            (None, 'buenas, donde puedo ver los requisitos para iniciar la habilitacion?'),
            ('admin_enrepavi', 'Hola Maria, los requisitos estan publicados en la seccion '
                              '"Solicitudes" del sitio. Cualquier duda mas especifica nos '
                              'escribis nuevamente. Saludos.'),
        ],
    },
    {
        'creador': 'empresa_delta',
        'nombre_contacto': None,
        'email_contacto': None,
        'telefono_contacto': None,
        'asunto': 'duda sobre conexion de agua',
        'categoria': Ticket.Categoria.LOTE,
        'estado': Ticket.Estado.ABIERTO,
        'mensajes': [
            ('empresa_delta', 'En la parcela 24 figura conexion de agua potable pero no '
                              'la encontramos en obra. Pueden chequear con la cooperativa?'),
            ('admin_enrepavi', 'Hola, vamos a coordinar con la cooperativa esta semana '
                               'y te confirmamos. Mientras tanto, el medidor deberia '
                               'estar sobre el lateral este del lote.'),
            ('empresa_delta', 'Perfecto, lo revisamos manana. Gracias.'),
        ],
    },
    {
        'creador': 'empresa_eta',
        'nombre_contacto': None,
        'email_contacto': None,
        'telefono_contacto': None,
        'asunto': 'pedido de copia de escritura',
        'categoria': Ticket.Categoria.ADMINISTRATIVA,
        'estado': Ticket.Estado.ABIERTO,
        'mensajes': [
            ('empresa_eta', 'Buenas, necesitamos una copia digital de la escritura de la '
                            'parcela para gestiones bancarias. Como podemos solicitarla?'),
        ],
    },
    {
        'creador': 'proveedor_agua',
        'nombre_contacto': None,
        'email_contacto': None,
        'telefono_contacto': None,
        'asunto': 'falla en formulario de carga de consumos',
        'categoria': Ticket.Categoria.TECNICA,
        'estado': Ticket.Estado.CERRADO,
        'mensajes': [
            ('proveedor_agua', 'No me deja cargar el consumo de marzo, tira un error.'),
            ('admin_enrepavi', 'Lo revisamos: era un periodo ya cargado por error. Lo '
                               'limpiamos, ya podes volver a intentar. Gracias por avisar.'),
            ('proveedor_agua', 'Perfecto, ya cargo bien. Cierro el ticket.'),
        ],
    },
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
    factores = {
        'agua_potable': [
            Decimal('1.10'), Decimal('0.95'), Decimal('1.12'),
            Decimal('0.90'), Decimal('1.03'), Decimal('0.88'),
        ],
        'agua_cruda': [
            Decimal('1.04'), Decimal('0.98'), Decimal('1.09'),
            Decimal('0.93'), Decimal('1.02'), Decimal('0.90'),
        ],
        'luz': [
            Decimal('1.08'), Decimal('0.96'), Decimal('1.14'),
            Decimal('0.92'), Decimal('1.05'), Decimal('0.89'),
        ],
        'gas': [
            Decimal('1.06'), Decimal('0.97'), Decimal('1.10'),
            Decimal('0.91'), Decimal('1.04'), Decimal('0.90'),
        ],
    }

    def ajustar(valor, servicio, indice):
        factor = factores[servicio][(indice - 1) % len(factores[servicio])]
        return (valor * factor).quantize(Decimal('0.01'))

    for i in range(1, meses + 1):
        # retrocede aproximadamente un mes por iteracion
        anio = hoy.year
        mes = hoy.month - i
        while mes <= 0:
            mes += 12
            anio -= 1
        nivel = Decimal(meses - i + 1)
        # radicada: solo agua, aun no opera maquinaria
        if empresa.estado == Empresa.Estado.RADICADA:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': ajustar(
                    Decimal('8.50') + nivel * Decimal('0.5'), 'agua_potable', i,
                ),
                'consumo_agua_cruda_m3': None,
                'consumo_luz_kwh': ajustar(
                    Decimal('120.00') + nivel * Decimal('10'), 'luz', i,
                ),
                'consumo_gas_m3': None,
            })
        # en construccion: agua + luz de obra, sin gas industrial
        elif empresa.estado == Empresa.Estado.EN_CONSTRUCCION:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': ajustar(
                    Decimal('25.00') + nivel * Decimal('2'), 'agua_potable', i,
                ),
                'consumo_agua_cruda_m3': ajustar(
                    Decimal('12.00') + nivel * Decimal('1.5'), 'agua_cruda', i,
                ),
                'consumo_luz_kwh': ajustar(
                    Decimal('850.00') + nivel * Decimal('25'), 'luz', i,
                ),
                'consumo_gas_m3': None,
            })
        # finalizado/escriturado: operacion completa
        else:
            consumos.append({
                'periodo_mes': mes,
                'periodo_anio': anio,
                'consumo_agua_potable_m3': ajustar(
                    Decimal('45.00') + nivel * Decimal('1.5'), 'agua_potable', i,
                ),
                'consumo_agua_cruda_m3': ajustar(
                    Decimal('110.00') + nivel * Decimal('5'), 'agua_cruda', i,
                ),
                'consumo_luz_kwh': ajustar(
                    Decimal('3200.00') + nivel * Decimal('80'), 'luz', i,
                ),
                'consumo_gas_m3': ajustar(
                    Decimal('450.00') + nivel * Decimal('10'), 'gas', i,
                ),
            })
    return consumos


class Command(BaseCommand):
    help = 'Carga grupos, lotes, usuarios, empresas y consumos de prueba'

    @transaction.atomic
    def handle(self, *args, **options):
        self._log('-- Cargando grupos...')
        for nombre in GRUPOS:
            Group.objects.get_or_create(name=nombre)
        # limpia grupos huerfanos de fixtures previos (ej. PROVEEDOR_SERVICIOS)
        Group.objects.exclude(name__in=GRUPOS).delete()

        self._log('-- Limpiando usuarios huerfanos...')
        # borra usuarios que no son parte del set de prueba (preserva
        # superusuarios y staff manuales). evita que queden cuentas dangling
        # de iteraciones previas.
        usernames_validos = {u for u, *_ in ADMINS}
        usernames_validos.update(u for u, *_ in PROVEEDORES)
        usernames_validos.update(u for u, *_ in ORGANISMOS)
        usernames_validos.update(
            spec['username'] for spec in EMPRESAS_PRUEBA if spec['username']
        )
        for spec in EMPRESAS_PRUEBA:
            usernames_validos.update(
                uname for uname, *_ in spec.get('miembros_estandar', [])
            )
        usernames_validos.update(u for u, *_ in USUARIOS_LIBRES_EMPRESA)
        CustomUser.objects.exclude(
            username__in=usernames_validos,
        ).filter(is_superuser=False, is_staff=False).delete()

        self._log('-- Cargando parcelas...')
        for nro, datos in PARCELAS.items():
            superficie, ancho, alto, mx, my, mw, mh = datos
            estado = Lote.Estado.RESERVA_FISCAL if nro == 5 else Lote.Estado.DISPONIBLE
            Lote.objects.update_or_create(
                nro_parcela=nro,
                defaults={
                    'superficie_m2': superficie,
                    'ancho_m': Decimal(str(ancho)),
                    'alto_m': Decimal(str(alto)),
                    'mapa_x': mx, 'mapa_y': my,
                    'mapa_w': mw, 'mapa_h': mh,
                    'conexion_agua_potable': nro not in SERVICIOS_NO_DISPONIBLES['agua_potable'],
                    'conexion_agua_cruda': nro not in SERVICIOS_NO_DISPONIBLES['agua_cruda'],
                    'conexion_electrica': nro not in SERVICIOS_NO_DISPONIBLES['electricidad'],
                    'conexion_gas': nro not in SERVICIOS_NO_DISPONIBLES['gas'],
                    'internet_disponible': nro not in SERVICIOS_NO_DISPONIBLES['internet'],
                    'estado': estado,
                },
            )

        self._log('-- Cargando lindantes...')
        for nro, vecinos in LINDANTES.items():
            lote = Lote.objects.get(nro_parcela=nro)
            lote.lotes_colindantes.set(
                Lote.objects.filter(nro_parcela__in=vecinos)
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
        # cleanup destructivo: borra empresas previas y libera todos los lotes
        # (excepto la reserva fiscal). garantiza que el set de prueba sea el
        # unico presente y refleja exactamente EMPRESAS_PRUEBA.
        Empresa.objects.all().delete()
        Lote.objects.exclude(nro_parcela=5).update(
            estado=Lote.Estado.DISPONIBLE, empresa=None,
        )
        for spec in EMPRESAS_PRUEBA:
            self._crear_empresa(spec)

        self._log('-- Cargando usuarios libres (EMPRESA sin empresa)...')
        for username, email, nombre in USUARIOS_LIBRES_EMPRESA:
            u, creado = _crear_user(username, email, nombre, PASSWORD_DEFAULT, grupos=['EMPRESA'])
            # garantizar que queden desvinculados en re-ejecuciones
            u.empresa = None
            u.rol_interno = None
            u.save(update_fields=['empresa', 'rol_interno'])
            marca = '+' if creado else '='
            self._log(f'   {marca} {username} (libre — puede ser invitado)')

        self._log('-- Cargando inventario de activos...')
        self._cargar_inventario()

        self._log('-- Cargando tickets de mensajeria...')
        self._cargar_tickets()

        self._log('-- Cargando solicitudes de acceso...')
        self._cargar_solicitudes_acceso()

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

        # Vincular el usuario a la empresa con rol TITULAR (FK ahora está en
        # CustomUser, no en Empresa — ver migración 0002/0004).
        if usuario is not None:
            usuario.empresa = empresa
            usuario.rol_interno = CustomUser.RolInterno.TITULAR
            usuario.save(update_fields=['empresa', 'rol_interno'])

        # crear y vincular miembros ESTANDAR
        for uname, uemail, unombre in spec.get('miembros_estandar', []):
            miembro, _ = _crear_user(
                uname, uemail, unombre, PASSWORD_DEFAULT, grupos=['EMPRESA'],
            )
            miembro.empresa = empresa
            miembro.rol_interno = CustomUser.RolInterno.ESTANDAR
            miembro.save(update_fields=['empresa', 'rol_interno'])

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

        # prorrogas de ejemplo: una pendiente, una aprobada historica y una rechazada
        # historica. cubren los tres estados del flujo CU-05 / HU-07.
        if spec['username'] == 'empresa_zeta':
            empresa.prorrogas.all().delete()
            SolicitudProrroga.objects.create(
                empresa=empresa,
                meses_solicitados=Empresa.TiempoRadicacion.MESES_6,
                justificacion='Demora en entrega de maquinaria importada.',
            )
        elif spec['username'] == 'empresa_epsilon':
            empresa.prorrogas.all().delete()
            admin_user = CustomUser.objects.filter(
                groups__name='ADMIN_ENREPAVI',
            ).first()
            SolicitudProrroga.objects.create(
                empresa=empresa,
                meses_solicitados=Empresa.TiempoRadicacion.MESES_12,
                justificacion='Atraso por importacion de equipamiento.',
                estado=SolicitudProrroga.EstadoProrroga.APROBADA,
                respuesta_admin='Aprobada por unica vez.',
                fecha_respuesta=timezone.now() - timedelta(days=20),
                resuelta_por=admin_user,
            )
        elif spec['username'] == 'empresa_eta':
            empresa.prorrogas.all().delete()
            admin_user = CustomUser.objects.filter(
                groups__name='ADMIN_ENREPAVI',
            ).first()
            SolicitudProrroga.objects.create(
                empresa=empresa,
                meses_solicitados=Empresa.TiempoRadicacion.MESES_24,
                justificacion='Solicitud sin documentacion respaldatoria.',
                estado=SolicitudProrroga.EstadoProrroga.RECHAZADA,
                respuesta_admin='Rechazada por falta de documentacion.',
                fecha_respuesta=timezone.now() - timedelta(days=120),
                resuelta_por=admin_user,
            )

        marca = '+' if creada else '='
        self._log(f'   {marca} {empresa.razon_social} [{empresa.estado}]')
        for uname, *_ in spec.get('miembros_estandar', []):
            self._log(f'      └─ {uname} [ESTANDAR]')

    def _cargar_inventario(self):
        """Carga el catálogo de activos de inventario del ENREPAVI.

        Borra el inventario existente y lo recrea desde cero para garantizar
        idempotencia: si cambian nombres/categorías/ubicaciones entre corridas,
        no quedan duplicados huérfanos. El comando es de "datos de prueba",
        no debe usarse en producción.
        """
        ActivoInventario.objects.all().delete()
        hoy = timezone.now().date()
        admin = CustomUser.objects.filter(is_superuser=True).first()

        for spec in INVENTARIO_PRUEBA:
            fecha_alta = hoy + timedelta(days=spec['fecha_alta_offset_dias'])
            es_baja = spec['estado'] == ActivoInventario.Estado.DE_BAJA

            # clave de busqueda: numero de serie si existe, si no nombre+categoria+ubicacion
            if spec['numero_serie']:
                lookup = {'numero_serie': spec['numero_serie']}
            else:
                lookup = {
                    'nombre': spec['nombre'],
                    'categoria': spec['categoria'],
                    'ubicacion': spec['ubicacion'],
                }

            defaults = {
                'categoria': spec['categoria'],
                'nombre': spec['nombre'],
                'descripcion': spec['descripcion'],
                'marca': spec['marca'],
                'modelo': spec['modelo'],
                'numero_serie': spec['numero_serie'],
                'fecha_alta': fecha_alta,
                'estado': spec['estado'],
                'ubicacion': spec['ubicacion'],
                'observaciones': spec['observaciones'],
                'activo': not es_baja,
                'registrado_por': admin,
            }

            if es_baja:
                defaults.update({
                    'motivo_baja': 'Cargado como baja por cargar_datos_prueba.',
                    'fecha_baja': hoy + timedelta(days=spec['fecha_alta_offset_dias'] + 30),
                    'dado_de_baja_por': admin,
                })

            activo, creado = ActivoInventario.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
            marca = '+' if creado else '='
            self._log(f'   {marca} [{activo.codigo_inventario}] {activo.nombre}')

    def _cargar_tickets(self):
        """Carga tickets y mensajes de mensajeria interna (issue #25).

        Borra todos los tickets existentes y los recrea desde cero. Igual que
        con inventario, prioriza idempotencia sobre preservacion de datos: este
        comando es solo para entornos de prueba.
        """
        Ticket.objects.all().delete()
        for spec in TICKETS_PRUEBA:
            creador = None
            if spec['creador']:
                creador = CustomUser.objects.filter(username=spec['creador']).first()
                if not creador:
                    self._log(f'   ! creador {spec["creador"]} no existe; salto ticket')
                    continue
                lookup = {'creador': creador, 'asunto': spec['asunto']}
            else:
                lookup = {
                    'creador__isnull': True,
                    'email_contacto': spec['email_contacto'],
                    'asunto': spec['asunto'],
                }

            defaults = {
                'categoria': spec['categoria'],
                'estado': spec['estado'],
                'creador': creador,
                'nombre_contacto': spec['nombre_contacto'],
                'email_contacto': spec['email_contacto'],
                'telefono_contacto': spec['telefono_contacto'],
                'is_active': True,
            }
            ticket, creado = Ticket.objects.update_or_create(
                **lookup, defaults=defaults,
            )

            # recrear mensajes desde cero para evitar duplicados al reejecutar
            ticket.mensajes.all().delete()
            for autor_username, contenido in spec['mensajes']:
                autor = None
                if autor_username:
                    autor = CustomUser.objects.filter(username=autor_username).first()
                MensajeTicket.objects.create(
                    ticket=ticket,
                    autor=autor,
                    contenido=contenido,
                )

            marca = '+' if creado else '='
            origen = creador.username if creador else 'externo'
            self._log(f'   {marca} #{ticket.id} [{ticket.estado}] {origen}: {ticket.asunto}')

    def _cargar_solicitudes_acceso(self):
        """Carga solicitudes de acceso de prueba (proveedor y organismo)."""
        SolicitudAcceso.objects.all().delete()
        for spec in SOLICITUDES_ACCESO_PRUEBA:
            sol = SolicitudAcceso.objects.create(**spec)
            self._log(f'   + [{sol.tipo}] {sol.nombre_apellido} — {sol.organizacion}')

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
            for uname, *_ in spec.get('miembros_estandar', []):
                self.stdout.write(f'    └─ {uname:20s} [ESTANDAR]')

        self.stdout.write(self.style.MIGRATE_HEADING('\nUSUARIOS LIBRES (invitables por cualquier TITULAR)'))
        for u, _, n in USUARIOS_LIBRES_EMPRESA:
            self.stdout.write(f'  {u:22s} {n}')
        self.stdout.write('=' * 70)

        total_activos = ActivoInventario.objects.count()
        activos_vigentes = ActivoInventario.objects.filter(activo=True).count()
        self.stdout.write(self.style.MIGRATE_HEADING('\nINVENTARIO'))
        self.stdout.write(
            f'  {total_activos} activos totales '
            f'({activos_vigentes} vigentes, {total_activos - activos_vigentes} de baja)'
        )

        total_tickets = Ticket.objects.filter(is_active=True).count()
        tickets_abiertos = Ticket.objects.filter(
            is_active=True, estado=Ticket.Estado.ABIERTO,
        ).count()
        tickets_externos = Ticket.objects.filter(
            is_active=True, creador__isnull=True,
        ).count()
        total_mensajes = MensajeTicket.objects.filter(is_active=True).count()
        self.stdout.write(self.style.MIGRATE_HEADING('\nTICKETS'))
        self.stdout.write(
            f'  {total_tickets} tickets ({tickets_abiertos} abiertos, '
            f'{total_tickets - tickets_abiertos} cerrados, '
            f'{tickets_externos} externos) — {total_mensajes} mensajes en total'
        )
        self.stdout.write('=' * 70)

    def _log(self, msg):
        self.stdout.write(msg)
