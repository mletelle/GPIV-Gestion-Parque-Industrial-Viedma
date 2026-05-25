# Generated manually for feature/autenticacion-dual-email
# Hace el campo email de CustomUser único para garantizar autenticación
# confiable por correo electrónico.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_avisovencimiento_caducidadregistro_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='email',
            field=models.EmailField(
                error_messages={'unique': 'Ya existe un usuario con este correo electrónico.'},
                max_length=254,
                unique=True,
                verbose_name='correo electrónico',
            ),
        ),
    ]
