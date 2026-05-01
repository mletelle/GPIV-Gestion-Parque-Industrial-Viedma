from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

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
        INSTALACION_NUEVA = 'InstalacionNueva', _('Instalación nueva')
        RECONVERSION = 'Reconversion', _('Reconversión productiva')
        AMPLIACION = 'Ampliacion', _('Ampliación de planta')

    class Rubro(models.TextChoices):
        SERVICIOS = 'Servicios', _('Servicios')
        BIENES = 'Bienes', _('Bienes')
        BIENES_Y_SERVICIOS = 'BienesYServicios', _('Bienes y Servicios')
        METALURGICA = 'Metalurgica', _('Metalúrgica')
        MADERERA = 'Maderera', _('Maderera')
        TEXTIL = 'Textil', _('Textil')
        AGROINDUSTRIA = 'Agroindustria', _('Agroindustria')
        CONSTRUCCION = 'Construccion', _('Construcción')
        LOGISTICA = 'Logistica', _('Logística')
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

    class RangoPotencia(models.TextChoices):
        HASTA_10 = 'Hasta10', _('Hasta 10 kW')
        DE_10_A_50 = '10a50', _('10 – 50 kW')
        DE_50_A_100 = '50a100', _('50 – 100 kW')
        DE_100_A_500 = '100a500', _('100 – 500 kW')
        MAS_500 = 'Mas500', _('Más de 500 kW')

    class RangoConsumoAgua(models.TextChoices):
        HASTA_50 = 'Hasta50', _('Hasta 50 m³/mes')
        DE_50_A_200 = '50a200', _('50 – 200 m³/mes')
        DE_200_A_500 = '200a500', _('200 – 500 m³/mes')
        MAS_500 = 'Mas500', _('Más de 500 m³/mes')

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
    energia_potencia_rango = models.CharField(max_length=20, choices=RangoPotencia.choices, blank=True, null=True)
    consumo_estimado_agua_potable = models.CharField(max_length=20, choices=RangoConsumoAgua.choices, blank=True, null=True)
    consumo_estimado_agua_cruda = models.CharField(max_length=20, choices=RangoConsumoAgua.choices, blank=True, null=True)
    gas = models.BooleanField(default=False)
    requiere_internet = models.BooleanField(default=False)
    necesidad_balanza_publica = models.BooleanField(default=False)
    necesidad_comedor = models.BooleanField(default=False)
    necesidad_salon_multiuso = models.BooleanField(default=False)

    # Impacto Ambiental y Clasificación
    categoria_industrial = models.CharField(max_length=30, choices=CategoriaIndustrial.choices)
    maneja_inflamables = models.BooleanField(default=False)
    genera_residuos = models.BooleanField(default=False)
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


class Ticket(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = 'Abierto', _('Abierto')
        CERRADO = 'Cerrado', _('Cerrado')

    class Categoria(models.TextChoices):
        LOTE = 'Lote', _('Consulta de Lote')
        ADMINISTRATIVA = 'Administrativa', _('Administrativa')
        TECNICA = 'Tecnica', _('Soporte Técnico')
        EXTERNA = 'Externa', _('Consulta Externa')
        OTRAS = 'Otras', _('Otras Consultas')

    asunto = models.CharField(max_length=200)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.OTRAS)
    creador = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, related_name='tickets_creados', null=True, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.ABIERTO)
    
    # Datos para tickets externos (cuando creador es nulo)
    nombre_contacto = models.CharField(max_length=100, null=True, blank=True)
    email_contacto = models.EmailField(null=True, blank=True)
    telefono_contacto = models.CharField(max_length=50, null=True, blank=True)
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    # Baja lógica
    is_active = models.BooleanField(default=True, help_text=_('Indica si el ticket está activo. Desmarcar para baja lógica.'))
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Ticket")
        verbose_name_plural = _("Tickets")
        ordering = ['-fecha_actualizacion']

    def __str__(self):
        return f"Ticket #{self.id}: {self.asunto} ({self.get_estado_display()})"

    def soft_delete(self):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save()


class MensajeTicket(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='mensajes')
    autor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, related_name='mensajes_ticket', null=True, blank=True)
    contenido = models.TextField()
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Baja lógica
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Mensaje de Ticket")
        verbose_name_plural = _("Mensajes de Ticket")
        ordering = ['fecha_creacion']

    def __str__(self):
        autor_name = self.autor.username if self.autor else "Usuario Externo"
        return f"Mensaje en Ticket #{self.ticket_id} por {autor_name}"

    def soft_delete(self):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save()


class ActivoInventario(models.Model):
    """
    Activo físico o recurso perteneciente al ente administrador (ENREPAVI).

    El módulo cubre dos categorías definidas en la entrevista de relevamiento:
    - Informático / Mobiliario de oficina (computadoras, impresoras, escritorios, etc.)
    - Equipamiento de mantenimiento (herramientas, vehículos ligeros, maquinaria menor, etc.)

    La baja es lógica: el campo ``activo`` se establece en False; el registro
    permanece en la base de datos para conservar el historial patrimonial.
    El código de inventario sigue el patrón ``<PREFIJO>-YYYYNNN`` y se genera
    automáticamente al crear el activo si no se provee uno manualmente.
    """

    class Categoria(models.TextChoices):
        INFORMATICO_MOBILIARIO = 'InformaticoMobiliario', _('Informático / Mobiliario de Oficina')
        EQUIPAMIENTO_MANTENIMIENTO = 'EquipamientoMantenimiento', _('Equipamiento de Mantenimiento')

    class Estado(models.TextChoices):
        EN_USO = 'EnUso', _('En uso')
        EN_DEPOSITO = 'EnDeposito', _('En depósito')
        EN_REPARACION = 'EnReparacion', _('En reparación')
        DE_BAJA = 'DeBaja', _('De baja')

    # prefijos de código por categoría: INF para informático/mobiliario, MNT para mantenimiento
    _PREFIJOS_CATEGORIA = {
        Categoria.INFORMATICO_MOBILIARIO: 'INF',
        Categoria.EQUIPAMIENTO_MANTENIMIENTO: 'MNT',
    }

    categoria = models.CharField(
        max_length=40,
        choices=Categoria.choices,
        verbose_name=_('Categoría'),
    )
    nombre = models.CharField(max_length=200, verbose_name=_('Nombre del activo'))
    descripcion = models.TextField(blank=True, null=True, verbose_name=_('Descripción'))
    codigo_inventario = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_('Código de inventario'),
        help_text=_('Generado automáticamente. Formato: INF-YYYYNNN / MNT-YYYYNNN.'),
    )

    marca = models.CharField(max_length=100, blank=True, null=True, verbose_name=_('Marca'))
    modelo = models.CharField(max_length=100, blank=True, null=True, verbose_name=_('Modelo'))
    numero_serie = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_('Número de serie'),
    )

    fecha_alta = models.DateField(verbose_name=_('Fecha de alta'))
    estado = models.CharField(
        max_length=30,
        choices=Estado.choices,
        default=Estado.EN_USO,
        verbose_name=_('Estado'),
    )
    ubicacion = models.CharField(
        max_length=200, blank=True, null=True, verbose_name=_('Ubicación'),
    )
    responsable = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activos_a_cargo',
        verbose_name=_('Responsable'),
    )
    observaciones = models.TextField(blank=True, null=True, verbose_name=_('Observaciones'))

    activo = models.BooleanField(
        default=True,
        verbose_name=_('Activo'),
        help_text=_('Desmarcar equivale a dar de baja el activo (baja lógica). El registro se conserva.'),
    )
    motivo_baja = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Motivo de baja'),
        help_text=_('Obligatorio al dar de baja el activo.'),
    )
    fecha_baja = models.DateField(
        blank=True, null=True, verbose_name=_('Fecha de baja'),
    )
    dado_de_baja_por = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bajas_de_inventario_registradas',
        verbose_name=_('Dado de baja por'),
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name=_('Fecha de creación'))
    fecha_modificacion = models.DateTimeField(auto_now=True, verbose_name=_('Última modificación'))
    registrado_por = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activos_registrados',
        verbose_name=_('Registrado por'),
    )

    class Meta:
        verbose_name = _('Activo de Inventario')
        verbose_name_plural = _('Inventario')
        ordering = ['categoria', 'codigo_inventario']
        indexes = [
            models.Index(fields=['categoria', 'activo'], name='idx_activo_cat_activo'),
            models.Index(fields=['estado'], name='idx_activo_estado'),
        ]

    def __str__(self):
        return f'[{self.codigo_inventario}] {self.nombre}'

    @classmethod
    def _generar_codigo(cls, categoria: str, anio: int) -> str:
        """Genera PREFIJO-YYYYNNN. En caso de colisión concurrente, la constraint
        UNIQUE actúa como salvaguarda definitiva."""
        prefijo = cls._PREFIJOS_CATEGORIA.get(categoria, 'ACT')
        cantidad = cls.objects.filter(
            categoria=categoria,
            fecha_alta__year=anio,
        ).count()
        correlativo = cantidad + 1
        return f'{prefijo}-{anio}{correlativo:03d}'

    def save(self, *args, **kwargs):
        """Auto-genera el código de inventario si no fue provisto."""
        if not self.codigo_inventario:
            from django.utils import timezone as tz
            anio = self.fecha_alta.year if self.fecha_alta else tz.now().year
            self.codigo_inventario = self._generar_codigo(self.categoria, anio)
        super().save(*args, **kwargs)
