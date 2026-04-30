# Migration: 0003_empresa_usuario_1_a_N_rbac
#
# Migra la relación Empresa-Usuario de 1:1 a 1:N.
#
# Cambios de esquema:
#   - Elimina el campo OneToOneField `usuario` de core_empresa.
#   - Agrega FK `empresa_asociada_id` en core_customuser (nullable, SET_NULL).
#   - Agrega campo CharField `rol_empresa` en core_customuser.
#
# La migración de datos (poblar los nuevos campos desde los datos existentes)
# se realiza en la migración 0004_data_migration_titular.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_activoinventario'),
    ]

    operations = [
        # 1. Agregar FK empresa_asociada en CustomUser (nullable al inicio)
        migrations.AddField(
            model_name='customuser',
            name='empresa_asociada',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='miembros',
                to='core.empresa',
                verbose_name='Empresa asociada',
            ),
        ),

        # 2. Agregar campo rol_empresa en CustomUser
        migrations.AddField(
            model_name='customuser',
            name='rol_empresa',
            field=models.CharField(
                blank=True,
                choices=[('Titular', 'Titular'), ('Estandar', 'Estándar')],
                max_length=20,
                null=True,
                verbose_name='Rol en la empresa',
            ),
        ),

        # 3. Eliminar el campo usuario (OneToOneField) de Empresa
        migrations.RemoveField(
            model_name='empresa',
            name='usuario',
        ),
    ]
