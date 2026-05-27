# Generated manually for feature/autenticacion-dual-email
# Hace el campo email de CustomUser único para garantizar autenticación
# confiable por correo electrónico.
#
# IMPORTANTE: antes de aplicar la restricción UNIQUE se ejecuta una migración
# de datos que:
#   1. Normaliza todos los emails existentes a minúsculas (consistente con
#      CustomUser.save() añadido en el mismo feature).
#   2. Resuelve los duplicados que pudieran surgir de esa normalización
#      (ej. "User@x.com" y "user@x.com") añadiendo el sufijo +migrated_<pk>
#      a los registros más recientes, preservando siempre el más antiguo.
#
# Sin este paso previo, un `migrate` sobre una base de datos con emails
# duplicados o con distinta capitalización fallaría con un IntegrityError
# y bloquearía el despliegue.

from django.db import migrations, models


def normalize_and_deduplicate_emails(apps, schema_editor):
    """
    Prepara la columna email para la restricción UNIQUE:

    Paso 1 — Normalización
        Convierte todos los emails a minúsculas usando UPDATE directo (sin
        instanciar objetos) para minimizar el impacto en tablas grandes.
        Solo toca filas cuyo email difiere de su versión en minúsculas.

    Paso 2 — Deduplicación
        Detecta grupos de usuarios que comparten el mismo email tras la
        normalización. Dentro de cada grupo, el usuario con menor pk (el
        más antiguo) se preserva intacto; los demás reciben el sufijo
        +migrated_<pk> antes del '@' para hacerlos únicos y rastreables.
        Un administrador puede corregir estos emails manualmente tras el
        despliegue desde el panel de Django.
    """
    User = apps.get_model('core', 'CustomUser')

    # ── Paso 1: normalizar a minúsculas ──────────────────────────────────────
    for user in User.objects.exclude(email='').iterator():
        lowered = user.email.lower()
        if user.email != lowered:
            # update() bypasses save() signals and is faster for bulk changes.
            User.objects.filter(pk=user.pk).update(email=lowered)

    # ── Paso 2: resolver duplicados ──────────────────────────────────────────
    from django.db.models import Count

    emails_duplicados = (
        User.objects
        .exclude(email='')
        .values('email')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .values_list('email', flat=True)
    )

    for email in emails_duplicados:
        # Ordenar por pk ASC: el primero (pk menor = más antiguo) se preserva;
        # los siguientes reciben un alias único.
        pks_a_renombrar = list(
            User.objects
            .filter(email=email)
            .order_by('id')
            .values_list('id', flat=True)
        )[1:]  # salta el primero

        for pk in pks_a_renombrar:
            # email ya está en minúsculas tras el paso 1.
            if '@' in email:
                local, domain = email.rsplit('@', 1)
                nuevo_email = f'{local}+migrated_{pk}@{domain}'
            else:
                # Formato inusual sin '@': añadir sufijo directo.
                nuevo_email = f'{email}+migrated_{pk}'
            User.objects.filter(pk=pk).update(email=nuevo_email)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_avisovencimiento_caducidadregistro_and_more'),
    ]

    operations = [
        # 1. Limpiar datos ANTES de aplicar la restricción.
        migrations.RunPython(
            normalize_and_deduplicate_emails,
            reverse_code=migrations.RunPython.noop,
        ),
        # 2. Ahora es seguro añadir UNIQUE al campo email.
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
