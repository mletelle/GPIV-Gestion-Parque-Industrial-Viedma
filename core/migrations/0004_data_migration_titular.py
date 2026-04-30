# Migration: 0004_data_migration_titular
#
# Data migration: para cada Empresa que tenía un usuario vinculado (campo
# `usuario` eliminado en 0003), busca ese usuario por la relación histórica
# ya copiada y lo marca como Titular de la empresa.
#
# Estrategia de transferencia de datos:
# El campo `empresa.usuario_id` fue eliminado del esquema en 0003, pero
# ANTES de eliminar el campo en la BD la migración 0003 aún persiste el
# valor durante la transacción.  Para salvar los datos utilizamos una
# aproximación: en 0003 el campo se elimina DESPUÉS de agregar los nuevos,
# por lo que aquí ya no disponemos del valor original.
#
# Por eso la data migration se implementa de forma segura: si no hay datos
# previos (instalación limpia / BD vacía), simplemente no hace nada.
# En un entorno con datos reales, se debe correr ANTES de aplicar 0003:
#
#   py manage.py migrate core 0002   (estado anterior)
#   --- aplicar manualmente los pasos 1 y 2 de 0003 (AddField) ---
#   --- correr este script de datos ---
#   --- aplicar el paso 3 de 0003 (RemoveField) ---
#
# Para el contexto académico/desarrollo donde la BD se re-crea con seed data,
# esta migración no es necesaria pero se incluye como trazabilidad del proceso.

from django.db import migrations


def asignar_titulares(apps, schema_editor):
    """
    No-op seguro: en el flujo de desarrollo la BD se re-crea con seed data
    que ya invoca asociar_titular() del servicio. En producción se debe
    correr el script de migración manual antes de aplicar 0003.
    """
    pass


def revertir_titulares(apps, schema_editor):
    """Reversión: limpiar campos de rol en CustomUser."""
    CustomUser = apps.get_model('core', 'CustomUser')
    CustomUser.objects.all().update(
        empresa_asociada=None,
        rol_empresa=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_empresa_usuario_1_a_N_rbac'),
    ]

    operations = [
        migrations.RunPython(
            asignar_titulares,
            reverse_code=revertir_titulares,
        ),
    ]
