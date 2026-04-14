"""
Management command: cargar_lotes
Carga las 64 parcelas del Parque Industrial + Reserva Fiscal (parcela 005).
Datos extraídos de lotes_catastro.md.
Idempotente con update_or_create.
"""
from django.core.management.base import BaseCommand
from core.models import Lote


# parcela: superficie_m2
PARCELAS = {
    1: 1355.24,
    2: 1346.54,
    3: 1337.61,
    4: 1339.86,
    5: 5151.15,   # reserva fiscal
    6: 2575.58,
    7: 2575.58,
    8: 2575.58,
    9: 2493.75,
    10: 2507.11,
    11: 2495.07,
    12: 2575.58,
    13: 2575.58,
    14: 2575.58,
    15: 5002.93,
    16: 5011.01,
    17: 5974.99,
    18: 5968.95,
    19: 5000.34,
    20: 5002.67,
    22: 7292.39,
    23: 7255.56,
    24: 1245.21,
    25: 1250.83,
    26: 1250.36,
    27: 1250.23,
    28: 1267.09,
    29: 1815.00,
    30: 1815.00,
    31: 1815.00,
    32: 1815.00,
    33: 1815.00,
    34: 1815.00,
    35: 1815.00,
    36: 1705.60,
    37: 1713.60,
    38: 1800.00,
    39: 1800.00,
    40: 1705.60,
    41: 1713.60,
    42: 1815.00,
    43: 1815.00,
    44: 1815.00,
    45: 1815.00,
    46: 1815.00,
    47: 1815.00,
    48: 1815.00,
    49: 2496.70,
    50: 2504.70,
    51: 2504.70,
    52: 2504.70,
    53: 3339.62,
    54: 3339.62,
    55: 2496.70,
    56: 2504.70,
    57: 2504.70,
    58: 2496.70,
    59: 3339.62,
    60: 3339.62,
    61: 2927.25,
    62: 2927.46,
    63: 2919.67,
    64: 2911.88,
    65: 2921.15,
}


class Command(BaseCommand):
    help = 'Carga las 64 parcelas del parque industrial + reserva fiscal'

    def handle(self, *args, **options):
        creados = 0
        actualizados = 0

        for nro, superficie in PARCELAS.items():
            estado = Lote.Estado.RESERVA_FISCAL if nro == 5 else Lote.Estado.DISPONIBLE

            _, created = Lote.objects.update_or_create(
                nro_parcela=nro,
                defaults={
                    'superficie_m2': superficie,
                    'estado': estado,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1

        total = creados + actualizados
        self.stdout.write(self.style.SUCCESS(
            f'{total} parcelas procesadas ({creados} creadas, {actualizados} actualizadas)'
        ))
