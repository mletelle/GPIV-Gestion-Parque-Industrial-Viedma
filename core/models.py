from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator

class CustomUser(AbstractUser):
    """
    Usuario del SGPIV extendido de AbstractUser.
    Los roles (ADMIN_ENREPAVI, EMPRESA) se manejan por instancias de Group.
    """
    pass

class Empresa(models.Model):
    # Enums de estado y clasificaciones
    class Estado(models.TextChoices):
        EN_EVALUACION = 'EnEvaluacion', _('En Evaluación')
        PRE_APROBADO = 'PreAprobado', _('Pre-Aprobado')
        RECHAZADO = 'Rechazado', _('Rechazado')
        RADICADA = 'Radicada', _('Radicada')
        EN_CONSTRUCCION = 'EnConstruccion', _('En Construcción')
        FINALIZADO = 'Finalizado', _('Finalizado')
        ESCRITURADO = 'Escriturado', _('Escriturado')
        CADUCADO = 'Caducado', _('Caducado')
        HISTORICO_BAJA = 'Historico_Baja', _('Clausurado / Baja')

    class TipoEmpresa(models.TextChoices):
        NUEVA = 'Nueva', _('Nueva')
        EXISTENTE = 'Existente', _('Existente')

    class ObjetivoProyecto(models.TextChoices):
        TRASLADO = 'Traslado', _('Traslado total o parcial')
        NUEVOS_PRODUCTOS = 'NuevosProductos', _('Elaborar nuevos productos')
        INCREMENTAR_PRODUCCION = 'IncrementarProduccion', _('Incrementar producción total')

    class Rubro(models.TextChoices):
        SERVICIOS = 'Servicios', _('Servicios')
        BIENES = 'Bienes', _('Bienes')
        BIENES_Y_SERVICIOS = 'BienesYServicios', _('Bienes y Servicios')
        OTRO = 'Otro', _('Otro')

    class EmplazamientoActual(models.TextChoices):
        PROPIO = 'Propio', _('Propio')
        ALQUILADO = 'Alquilado', _('Alquilado')

    class CategoriaIndustrial(models.TextChoices):
        ALIMENTICIA = 'Alimenticia', _('Alimenticia')
        QUIMICA = 'Quimica', _('Química')
        TECNOLOGICA = 'Tecnologica', _('Tecnológica')
        OTRO = 'Otro', _('Otro')

    class TiempoRadicacion(models.IntegerChoices):
        MESES_6 = 6, _('6 Meses')
        MESES_12 = 12, _('12 Meses')
        MESES_24 = 24, _('24 Meses')
        MESES_36 = 36, _('36 o más Meses')

    class TensionElectrica(models.TextChoices):
        MEDIA = 'Media', _('Media Tensión')
        BAJA = 'Baja', _('Baja Tensión')

    # Relación 1:1 con Usuario — SET_NULL: borrar el usuario no elimina la empresa ni su historial
    usuario = models.OneToOneField(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='empresa'
    )

    # Información Fiscal
    razon_social = models.CharField(max_length=150)
    nombre_fantasia = models.CharField(max_length=150, blank=True, null=True)
    cuit = models.CharField(max_length=13, unique=True)
    ingresos_brutos = models.CharField(max_length=50, blank=True, null=True)
    actividad_principal = models.CharField(max_length=200)
    actividad_secundaria = models.CharField(max_length=200, blank=True, null=True)
    tipo_empresa = models.CharField(max_length=20, choices=TipoEmpresa.choices)
    objetivo_proyecto = models.CharField(max_length=50, choices=ObjetivoProyecto.choices, blank=True, null=True)
    rubro = models.CharField(max_length=30, choices=Rubro.choices)
    descripcion_actividad = models.TextField()

    # Información de Contacto
    direccion = models.CharField(max_length=200, blank=True, null=True)
    persona_referente = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30)
    correo_electronico = models.EmailField(max_length=254)

    # Detalle del Proyecto / Actividad
    emplazamiento_actual = models.CharField(max_length=20, choices=EmplazamientoActual.choices, blank=True, null=True)
    personal_jerarquico = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    personal_produccion = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    personal_administrativo = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    personal_a_ocupar = models.IntegerField(validators=[MinValueValidator(0)])
    materias_primas = models.TextField(blank=True, null=True)
    destino_produccion = models.TextField(blank=True, null=True)

    # Requerimientos de Infraestructura Lote
    necesidad_m2 = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    superficie_cubierta_trabajo_m2 = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    superficie_cubierta_deposito_m2 = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    superficie_futura_expansion_m2 = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    superficie_estacionamiento_m2 = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    tiene_planos = models.BooleanField()
    tiempo_radicacion_meses = models.IntegerField(choices=TiempoRadicacion.choices)

    # Requerimientos de Servicios
    energia_tension = models.CharField(max_length=10, choices=TensionElectrica.choices, blank=True, null=True)
    energia_potencia_kw = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    consumo_estimado_agua_potable_m3 = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    consumo_estimado_agua_cruda_m3 = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    gas = models.BooleanField(default=False)
    requiere_internet = models.BooleanField(default=False)
    necesidad_balanza_publica = models.BooleanField(default=False)
    necesidad_comedor = models.BooleanField(default=False)
    necesidad_salon_multiuso = models.BooleanField(default=False)

    # Impacto Ambiental y Clasificación
    categoria_industrial = models.CharField(max_length=30, choices=CategoriaIndustrial.choices)
    maneja_inflamables = models.BooleanField(default=False)
    residuos_efluentes = models.TextField(blank=True, null=True)
    tratamiento_en_planta = models.BooleanField(default=False)

    # Estado y Control
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.EN_EVALUACION)
    fecha_limite_obra = models.DateField(blank=True, null=True)
    escritura_pdf = models.FileField(upload_to='escrituras/', blank=True, null=True)

    class Meta:
        verbose_name = _("Empresa")
        verbose_name_plural = _("Empresas")
        ordering = ['razon_social']

    def __str__(self):
        return f"{self.razon_social} ({self.cuit})"


class Lote(models.Model):
    class Estado(models.TextChoices):
        DISPONIBLE = 'Disponible', _('Disponible')
        EN_USO = 'EnUso', _('En Uso')
        RESERVA_FISCAL = 'ReservaFiscal', _('Reserva Fiscal')

    nro_parcela = models.IntegerField(unique=True)
    superficie_m2 = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    conexion_agua_potable = models.BooleanField(default=False)
    conexion_agua_cruda = models.BooleanField(default=False)
    internet_disponible = models.BooleanField(default=False)
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.DISPONIBLE)
    empresa = models.ForeignKey(Empresa, on_delete=models.SET_NULL, null=True, blank=True, related_name='lotes')
    lotes_colindantes = models.ManyToManyField('self', blank=True, symmetrical=True)

    class Meta:
        verbose_name = _("Lote")
        verbose_name_plural = _("Lotes")
        ordering = ['nro_parcela']

    def __str__(self):
        return f"Parcela {self.nro_parcela} - {self.estado}"


class TransicionEstado(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='historial_estados')
    estado_anterior = models.CharField(max_length=30, choices=Empresa.Estado.choices, blank=True, null=True)
    estado_nuevo = models.CharField(max_length=30, choices=Empresa.Estado.choices)
    fecha_cambio = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='transiciones_registradas')
    justificacion_resolucion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = _("Transición de Estado")
        verbose_name_plural = _("Transiciones de Estado")
        ordering = ['-fecha_cambio']

    def __str__(self):
        # empresa_id evita query adicional al listar transiciones en el admin
        return f"Empresa #{self.empresa_id}: {self.estado_anterior} → {self.estado_nuevo}"


class AvanceConstructivo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='avances_constructivos')
    porcentaje_declarado = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)])
    certificado_pdf = models.FileField(upload_to='certificados/')
    fecha_presentacion = models.DateField(auto_now_add=True)
    validado_admin = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Avance Constructivo")
        verbose_name_plural = _("Avances Constructivos")
        ordering = ['-fecha_presentacion']

    def __str__(self):
        return f"Avance {self.porcentaje_declarado}% - Empresa #{self.empresa_id}"


class SolicitudProrroga(models.Model):
    """Solicitud de extensión de plazo de obra (HU-07, CU-05)."""
    class EstadoProrroga(models.TextChoices):
        PENDIENTE = 'Pendiente', _('Pendiente')
        APROBADA = 'Aprobada', _('Aprobada')
        RECHAZADA = 'Rechazada', _('Rechazada')

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='prorrogas')
    meses_solicitados = models.IntegerField(choices=Empresa.TiempoRadicacion.choices)
    justificacion = models.TextField()
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=EstadoProrroga.choices, default=EstadoProrroga.PENDIENTE)
    respuesta_admin = models.TextField(blank=True, null=True)
    fecha_respuesta = models.DateTimeField(blank=True, null=True)
    resuelta_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='prorrogas_resueltas')

    class Meta:
        verbose_name = _("Solicitud de Prórroga")
        verbose_name_plural = _("Solicitudes de Prórroga")
        ordering = ['-fecha_solicitud']

    def __str__(self):
        return f"Prórroga {self.meses_solicitados}m - Empresa #{self.empresa_id} ({self.estado})"


class ConsumoServicio(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='consumos')
    periodo_mes = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    periodo_anio = models.IntegerField(validators=[MinValueValidator(2024)])
    consumo_agua_potable_m3 = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    consumo_agua_cruda_m3 = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    consumo_luz_kwh = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    consumo_gas_m3 = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    fecha_carga = models.DateTimeField(auto_now_add=True)
    cargado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='consumos_cargados')

    class Meta:
        verbose_name = _("Consumo de Servicio")
        verbose_name_plural = _("Consumos de Servicios")
        ordering = ['-periodo_anio', '-periodo_mes']
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'periodo_mes', 'periodo_anio'], name='unique_consumo_periodo')
        ]

    def __str__(self):
        return f"Consumo {self.periodo_mes}/{self.periodo_anio} - Empresa #{self.empresa_id}"
