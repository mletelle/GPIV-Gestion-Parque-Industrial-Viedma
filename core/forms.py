from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django import forms
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from .models import Lote, Empresa, CustomUser, AvanceConstructivo, SolicitudProrroga, ConsumoServicio, Ticket, MensajeTicket, ActivoInventario, SolicitudAcceso
from .services import SERVICIO_CAMPOS


class LoginForm(AuthenticationForm):
    """Login con estilo institucional GPIV."""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Usuario',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contraseña',
        })
    )


class LoteForm(forms.ModelForm):
    """Formulario para alta y edición de lotes."""
    class Meta:
        model = Lote
        fields = [
            'nro_parcela',
            'superficie_m2',
            'conexion_agua_potable',
            'conexion_agua_cruda',
            'internet_disponible',
            'estado',
        ]
        widgets = {
            'nro_parcela': forms.NumberInput(attrs={'class': 'form-control'}),
            'superficie_m2': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'conexion_agua_potable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'conexion_agua_cruda': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'internet_disponible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }


class GpivPasswordResetForm(PasswordResetForm):
    """PasswordResetForm con estilos GPIV (issue #29)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'correo@ejemplo.com',
            'autocomplete': 'email',
        })


class GpivSetPasswordForm(SetPasswordForm):
    """SetPasswordForm con estilos GPIV (issue #29)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Nueva contraseña',
            'autocomplete': 'new-password',
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirmar nueva contraseña',
            'autocomplete': 'new-password',
        })


class SolicitudRadicacionForm(forms.ModelForm):
    """Formulario de solicitud de radicacion, dividido en secciones."""

    NUMERICOS_NO_NEGATIVOS = [
        'personal_jerarquico', 'personal_produccion', 'personal_administrativo',
        'personal_a_ocupar', 'superficie_cubierta_trabajo_m2',
        'superficie_cubierta_deposito_m2', 'superficie_futura_expansion_m2',
        'superficie_estacionamiento_m2',
    ]

    class Meta:
        model = Empresa
        fields = [
            # informacion fiscal
            'razon_social', 'nombre_fantasia', 'cuit', 'ingresos_brutos',
            'tipo_empresa', 'objetivo_proyecto', 'rubro',
            'actividad_principal', 'actividad_secundaria', 'descripcion_actividad',
            # contacto
            'direccion', 'persona_referente', 'telefono', 'correo_electronico',
            # detalle del proyecto (orden: emplazamiento, plantilla, materiales)
            'emplazamiento_actual',
            'personal_jerarquico', 'personal_administrativo',
            'personal_produccion', 'personal_a_ocupar',
            'materias_primas', 'destino_produccion',
            # infraestructura
            'necesidad_m2', 'superficie_cubierta_trabajo_m2',
            'superficie_cubierta_deposito_m2', 'superficie_futura_expansion_m2',
            'superficie_estacionamiento_m2', 'tiene_planos', 'tiempo_radicacion_meses',
            # servicios
            'energia_tension', 'energia_potencia_rango',
            'consumo_estimado_agua_potable', 'consumo_estimado_agua_cruda',
            'gas', 'requiere_internet',
            'necesidad_balanza_publica', 'necesidad_comedor', 'necesidad_salon_multiuso',
            # impacto ambiental
            'categoria_industrial', 'maneja_inflamables',
            'genera_residuos', 'tratamiento_en_planta',
        ]

    SECCIONES = [
        ('Información Fiscal', [
            'razon_social', 'nombre_fantasia', 'cuit', 'ingresos_brutos',
            'tipo_empresa', 'objetivo_proyecto', 'rubro',
            'actividad_principal', 'actividad_secundaria', 'descripcion_actividad',
        ]),
        ('Información de Contacto', [
            'direccion', 'persona_referente', 'telefono', 'correo_electronico',
        ]),
        ('Detalle del Proyecto', [
            'emplazamiento_actual',
            'personal_jerarquico', 'personal_administrativo',
            'personal_produccion', 'personal_a_ocupar',
            'materias_primas', 'destino_produccion',
        ]),
        ('Requerimientos de Infraestructura', [
            'necesidad_m2', 'tiempo_radicacion_meses',
            'superficie_cubierta_trabajo_m2', 'superficie_cubierta_deposito_m2',
            'superficie_futura_expansion_m2', 'superficie_estacionamiento_m2',
            'tiene_planos',
        ]),
        ('Requerimientos de Servicios', [
            'energia_tension', 'energia_potencia_rango',
            'consumo_estimado_agua_potable', 'consumo_estimado_agua_cruda',
            'gas', 'requiere_internet',
            'necesidad_balanza_publica', 'necesidad_comedor', 'necesidad_salon_multiuso',
        ]),
        ('Impacto Ambiental', [
            'categoria_industrial', 'maneja_inflamables',
            'genera_residuos', 'tratamiento_en_planta',
        ]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.RadioSelect)):
                widget.attrs.setdefault('class', 'form-select')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'form-control')
                widget.attrs.setdefault('rows', 3)
            else:
                widget.attrs.setdefault('class', 'form-control')
            # impedir negativos en los inputs numericos del lado cliente
            if name in self.NUMERICOS_NO_NEGATIVOS:
                widget.attrs['min'] = '0'

    def get_secciones(self):
        for titulo, campos in self.SECCIONES:
            yield titulo, [self[c] for c in campos]


class RechazarSolicitudForm(forms.Form):
    """Formulario para rechazar una solicitud con justificacion obligatoria."""
    justificacion = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Motivo del rechazo (obligatorio)',
        }),
        min_length=10,
        label='Justificación del rechazo',
    )


class AvanceConstructivoForm(forms.ModelForm):
    """Formulario para que la empresa registre un avance de obra con certificado PDF."""
    class Meta:
        model = AvanceConstructivo
        fields = ['porcentaje_declarado', 'certificado_pdf']
        widgets = {
            'porcentaje_declarado': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '100',
                'step': '0.01',
                'placeholder': 'Ej: 25.00',
            }),
            'certificado_pdf': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf',
            }),
        }
        labels = {
            'porcentaje_declarado': 'Porcentaje de avance (%)',
            'certificado_pdf': 'Certificado del Director de Obra (PDF)',
        }

    def clean_certificado_pdf(self):
        archivo = self.cleaned_data.get('certificado_pdf')
        if archivo and not archivo.name.lower().endswith('.pdf'):
            raise forms.ValidationError('Solo se aceptan archivos en formato PDF.')
        return archivo


class SolicitudProrrogaForm(forms.ModelForm):
    """Formulario para solicitar extension de plazo de obra."""
    class Meta:
        model = SolicitudProrroga
        fields = ['meses_solicitados', 'justificacion']
        widgets = {
            'meses_solicitados': forms.Select(attrs={'class': 'form-select'}),
            'justificacion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Justificación de la solicitud de prórroga',
            }),
        }
        labels = {
            'meses_solicitados': 'Meses de extensión solicitados',
            'justificacion': 'Justificación',
        }


class EscrituraForm(forms.Form):
    """Formulario para subir el PDF de la escritura del lote."""
    escritura_pdf = forms.FileField(
        label='Escritura escaneada (PDF)',
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': '.pdf',
        }),
    )

    def clean_escritura_pdf(self):
        archivo = self.cleaned_data.get('escritura_pdf')
        if archivo and not archivo.name.lower().endswith('.pdf'):
            raise forms.ValidationError('Solo se aceptan archivos en formato PDF.')
        return archivo


class BajaEmpresaForm(forms.Form):
    """Formulario para dar de baja una empresa con justificacion obligatoria."""
    justificacion = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Causal de resolución (obligatorio)',
        }),
        min_length=10,
        label='Causal de resolución',
    )


class ConsumoServicioForm(forms.ModelForm):
    """Formulario para que el Proveedor de Servicios cargue un consumo mensual."""

    MESES_CHOICES = [
        (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
        (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
        (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
    ]

    periodo_mes = forms.TypedChoiceField(
        choices=MESES_CHOICES,
        coerce=int,
        label='Mes del período',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = ConsumoServicio
        fields = [
            'empresa', 'periodo_mes', 'periodo_anio',
            'consumo_agua_potable_m3', 'consumo_agua_cruda_m3',
            'consumo_luz_kwh', 'consumo_gas_m3',
        ]
        widgets = {
            'empresa': forms.Select(attrs={'class': 'form-select'}),
            'periodo_anio': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '2024',
                'placeholder': 'Ej: 2026',
            }),
            'consumo_agua_potable_m3': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0',
            }),
            'consumo_agua_cruda_m3': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0',
            }),
            'consumo_luz_kwh': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0',
            }),
            'consumo_gas_m3': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0',
            }),
        }
        labels = {
            'empresa': 'Empresa',
            'periodo_anio': 'Año del período',
            'consumo_agua_potable_m3': 'Agua potable (m³)',
            'consumo_agua_cruda_m3': 'Agua cruda (m³)',
            'consumo_luz_kwh': 'Electricidad (kWh)',
            'consumo_gas_m3': 'Gas (m³)',
        }

    def __init__(self, *args, servicio=None, **kwargs):
        # servicio: 'AGUA', 'LUZ' o 'GAS'. si viene seteado, el formulario
        # solo expone los campos que le competen al proveedor; el resto se
        # quita para que no pueda pisar consumos de otros servicios.
        super().__init__(*args, **kwargs)
        self.servicio = servicio
        # solo empresas con radicacion vigente pueden declarar consumos
        self.fields['empresa'].queryset = Empresa.objects.filter(
            estado__in=[
                Empresa.Estado.RADICADA,
                Empresa.Estado.EN_CONSTRUCCION,
                Empresa.Estado.FINALIZADO,
            ]
        ).order_by('razon_social')

        # defaults: mes y anio actual
        hoy = timezone.now().date()
        self.fields['periodo_mes'].initial = hoy.month
        self.fields['periodo_anio'].initial = hoy.year

        # segregacion por servicio: borra los campos que no le corresponden
        if servicio in SERVICIO_CAMPOS:
            permitidos = set(SERVICIO_CAMPOS[servicio])
            todos = {'consumo_agua_potable_m3', 'consumo_agua_cruda_m3',
                     'consumo_luz_kwh', 'consumo_gas_m3'}
            for campo in todos - permitidos:
                self.fields.pop(campo, None)

    def clean(self):
        cleaned = super().clean()
        empresa = cleaned.get('empresa')
        mes = cleaned.get('periodo_mes')
        anio = cleaned.get('periodo_anio')

        if empresa and mes and anio and self.servicio in SERVICIO_CAMPOS:
            existente = ConsumoServicio.objects.filter(
                empresa=empresa, periodo_mes=mes, periodo_anio=anio,
            ).first()
            if existente:
                ya_cargado = any(
                    getattr(existente, c) is not None
                    for c in SERVICIO_CAMPOS[self.servicio]
                )
                if ya_cargado:
                    raise forms.ValidationError(
                        f'Ya hay un consumo de {self.servicio.lower()} cargado '
                        f'para {empresa.razon_social} en {mes:02d}/{anio}.'
                    )
        return cleaned


class RespuestaProrrogaForm(forms.Form):
    """Formulario para que el admin responda una solicitud de prorroga."""
    respuesta = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Observaciones (opcional)',
        }),
        required=False,
        label='Observaciones',
    )


class TicketCreateForm(forms.ModelForm):
    """Formulario para iniciar un nuevo ticket de mensajería interna."""
    mensaje_inicial = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Describa su consulta o solicitud...',
        }),
        label='Mensaje'
    )

    class Meta:
        model = Ticket
        fields = ['categoria', 'asunto']
        widgets = {
            'categoria': forms.Select(attrs={
                'class': 'form-select',
            }),
            'asunto': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Consulta sobre habilitación comercial',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Quitar "Externa" de las opciones para usuarios logueados
        choices = [(k, v) for k, v in Ticket.Categoria.choices if k != Ticket.Categoria.EXTERNA]
        self.fields['categoria'].choices = choices


class TicketExternoForm(forms.ModelForm):
    """Formulario para recibir consultas desde la landing page (sin usuario)."""
    mensaje = forms.CharField(widget=forms.Textarea)

    class Meta:
        model = Ticket
        fields = ['nombre_contacto', 'email_contacto', 'telefono_contacto', 'asunto']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # el modelo permite blank (para tickets internos sin contacto) pero
        # el formulario externo necesita email para responder y nombre para
        # identificar al remitente.
        self.fields['nombre_contacto'].required = True
        self.fields['email_contacto'].required = True


class MensajeTicketForm(forms.ModelForm):
    """Formulario para responder en un ticket existente."""
    class Meta:
        model = MensajeTicket
        fields = ['contenido']
        widgets = {
            'contenido': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Escriba su respuesta...',
            }),
        }
        labels = {
            'contenido': '',
        }


class ActivoInventarioForm(forms.ModelForm):
    """Formulario para registrar o editar un activo de inventario del ENREPAVI.

    El código de inventario se omite del formulario porque se genera automáticamente
    en el método ``save()`` del modelo. El campo ``activo`` y los de baja lógica
    (``motivo_baja``, ``fecha_baja``) tampoco se exponen aquí; la baja se gestiona
    a través de la vista dedicada ``InventarioBajaView``.
    """

    class Meta:
        model = ActivoInventario
        fields = [
            'categoria',
            'nombre',
            'descripcion',
            'marca',
            'modelo',
            'numero_serie',
            'fecha_alta',
            'estado',
            'ubicacion',
            'responsable',
            'observaciones',
        ]
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Computadora de escritorio Dell OptiPlex',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Descripción opcional del activo',
            }),
            'marca': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Dell'}),
            'modelo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: OptiPlex 3000'}),
            'numero_serie': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de serie del fabricante'}),
            'fecha_alta': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'ubicacion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Oficina administrativa — escritorio 3',
            }),
            'responsable': forms.Select(attrs={'class': 'form-select'}),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Notas adicionales (opcional)',
            }),
        }
        labels = {
            'categoria': 'Categoría',
            'nombre': 'Nombre del activo',
            'descripcion': 'Descripción',
            'marca': 'Marca',
            'modelo': 'Modelo',
            'numero_serie': 'Número de serie',
            'fecha_alta': 'Fecha de alta',
            'estado': 'Estado',
            'ubicacion': 'Ubicación',
            'responsable': 'Responsable',
            'observaciones': 'Observaciones',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restringir responsable a usuarios con acceso al sistema (staff o admin)
        self.fields['responsable'].queryset = (
            ActivoInventario._meta.get_field('responsable').related_model.objects
            .filter(is_active=True)
            .order_by('last_name', 'first_name', 'username')
        )
        self.fields['responsable'].empty_label = '— Sin responsable asignado —'


class BajaActivoForm(forms.Form):
    """Formulario para registrar la baja lógica de un activo de inventario.

    No elimina el registro: marca ``activo=False``, guarda el motivo y la fecha,
    y registra el usuario que ejecutó la baja, preservando el historial patrimonial.
    """
    motivo_baja = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Describa el motivo de la baja (rotura irreparable, reemplazo, extravío, etc.)',
        }),
        min_length=10,
        label='Motivo de la baja',
    )


class SolicitudAccesoForm(forms.ModelForm):
    """
    Formulario único para solicitar acceso como Organismo Público o Proveedor.

    El `tipo` se inyecta vía `__init__` (lo fija la vista, no el usuario), y
    según el tipo se ajustan label de organización y choices de tipo_acceso.
    """

    # Credenciales para crear el usuario asociado a la solicitud.
    username = forms.CharField(
        max_length=150,
        label='Nombre de usuario',
        help_text='Lo usarás para iniciar sesión cuando se apruebe tu solicitud.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'username'}),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model = SolicitudAcceso
        fields = [
            'nombre_apellido', 'cargo', 'organizacion', 'telefono',
            'email_institucional', 'tipo_acceso', 'motivo', 'documentacion',
        ]
        widgets = {
            'nombre_apellido': forms.TextInput(attrs={'class': 'form-control'}),
            'cargo': forms.TextInput(attrs={'class': 'form-control'}),
            'organizacion': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'email_institucional': forms.EmailInput(attrs={'class': 'form-control'}),
            'tipo_acceso': forms.Select(attrs={'class': 'form-select'}),
            'motivo': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Describí brevemente para qué necesitás acceso al sistema...',
            }),
            'documentacion': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, tipo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tipo is None:
            raise ValueError('SolicitudAccesoForm requiere `tipo` (ORGANISMO o PROVEEDOR).')
        self.tipo = tipo

        # Filtra choices y ajusta labels según el tipo.
        if tipo == SolicitudAcceso.Tipo.ORGANISMO:
            self.fields['organizacion'].label = 'Organismo'
            self.fields['tipo_acceso'].choices = (
                [('', 'Seleccioná...')] + SolicitudAcceso.TIPO_ACCESO_ORGANISMO
            )
        else:
            self.fields['organizacion'].label = 'Empresa'
            self.fields['tipo_acceso'].choices = (
                [('', 'Seleccioná...')] + SolicitudAcceso.TIPO_ACCESO_PROVEEDOR
            )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                'No se puede usar ese nombre de usuario. Elegí otro.'
            )
        return username

    def clean_email_institucional(self):
        email = self.cleaned_data['email_institucional'].strip().lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'No se pudo procesar la solicitud con esos datos. '
                'Si ya tenés cuenta, iniciá sesión.'
            )
        if SolicitudAcceso.objects.filter(
            email_institucional__iexact=email,
            estado=SolicitudAcceso.Estado.PENDIENTE,
        ).exists():
            raise forms.ValidationError('Ya hay una solicitud pendiente para ese email.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        if p1:
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(p1)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return cleaned


class RegistroEmpresaWizardForm(forms.Form):
    """
    Form único que recolecta los 4 pasos del wizard de registro de empresa:
    1. Datos de la empresa
    2. Proyecto industrial
    3. Representante legal
    4. Credenciales de acceso

    El submit final crea User + Empresa + TransicionEstado en una transacción
    atómica (lo hace la vista). Los campos del modelo Empresa no incluidos
    aquí se completan con defaults razonables.
    """

    _TXT = {'class': 'form-control'}
    _NUM = {'class': 'form-control'}
    _SEL = {'class': 'form-select'}

    razon_social = forms.CharField(
        label='Razón social', max_length=150,
        widget=forms.TextInput(attrs=_TXT),
    )
    cuit = forms.CharField(
        label='CUIT', max_length=13,
        widget=forms.TextInput(attrs={**_TXT, 'placeholder': '20-12345678-9'}),
    )
    direccion = forms.CharField(
        label='Domicilio legal', max_length=200,
        widget=forms.TextInput(attrs=_TXT),
    )
    telefono = forms.CharField(
        label='Teléfono', max_length=30,
        widget=forms.TextInput(attrs=_TXT),
    )
    correo_electronico = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs=_TXT),
    )
    tipo_societario = forms.ChoiceField(
        label='Tipo societario',
        choices=[('', 'Seleccioná...')] + list(Empresa.TipoSocietario.choices),
        widget=forms.Select(attrs=_SEL),
    )
    nombre_fantasia = forms.CharField(
        label='Nombre de fantasía', max_length=150, required=False,
        widget=forms.TextInput(attrs=_TXT),
    )
    ingresos_brutos = forms.CharField(
        label='Ingresos brutos', max_length=50, required=False,
        widget=forms.TextInput(attrs=_TXT),
    )
    tipo_empresa = forms.ChoiceField(
        label='Tipo de empresa',
        choices=[('', 'Seleccioná...')] + list(Empresa.TipoEmpresa.choices),
        widget=forms.Select(attrs=_SEL),
    )
    objetivo_proyecto = forms.ChoiceField(
        label='Objetivo del proyecto', required=False,
        choices=[('', '—')] + list(Empresa.ObjetivoProyecto.choices),
        widget=forms.Select(attrs=_SEL),
    )
    rubro = forms.ChoiceField(
        label='Rubro',
        choices=[('', 'Seleccioná...')] + list(Empresa.Rubro.choices),
        widget=forms.Select(attrs=_SEL),
    )
    persona_referente = forms.CharField(
        label='Persona referente', max_length=150,
        widget=forms.TextInput(attrs=_TXT),
    )

    # ── Paso 2: Proyecto industrial ──────────────────────────────────────────
    actividad_principal = forms.CharField(
        label='Actividad principal', max_length=200,
        widget=forms.TextInput(attrs=_TXT),
    )
    actividad_secundaria = forms.CharField(
        label='Actividad secundaria', max_length=200, required=False,
        widget=forms.TextInput(attrs=_TXT),
    )
    descripcion_actividad = forms.CharField(
        label='Descripción del servicio o bien ofrecido',
        widget=forms.Textarea(attrs={**_TXT, 'rows': 3}),
    )
    emplazamiento_actual = forms.ChoiceField(
        label='Emplazamiento actual', required=False,
        choices=[('', '—')] + list(Empresa.EmplazamientoActual.choices),
        widget=forms.Select(attrs=_SEL),
    )
    personal_jerarquico = forms.IntegerField(
        label='Personal jerárquico', min_value=0, required=False, initial=0,
        widget=forms.NumberInput(attrs={**_NUM, 'min': '0'}),
    )
    personal_administrativo = forms.IntegerField(
        label='Personal administrativo', min_value=0, required=False, initial=0,
        widget=forms.NumberInput(attrs={**_NUM, 'min': '0'}),
    )
    personal_produccion = forms.IntegerField(
        label='Personal de producción', min_value=0, required=False, initial=0,
        widget=forms.NumberInput(attrs={**_NUM, 'min': '0'}),
    )
    personal_a_ocupar = forms.IntegerField(
        label='Personal total a ocupar', min_value=0,
        widget=forms.NumberInput(attrs=_NUM),
    )
    materias_primas = forms.CharField(
        label='Materias primas (tipo y origen)', required=False,
        widget=forms.Textarea(attrs={**_TXT, 'rows': 2}),
    )
    destino_produccion = forms.CharField(
        label='Destino de la producción', required=False,
        widget=forms.Textarea(attrs={**_TXT, 'rows': 2}),
    )
    necesidad_m2 = forms.ChoiceField(
        label='Necesidad de lote (m²)',
        choices=[('', 'Seleccioná...')] + list(Empresa.RangoNecesidadM2.choices),
        widget=forms.Select(attrs=_SEL),
    )
    tiempo_radicacion_meses = forms.ChoiceField(
        label='Tiempo de radicación',
        choices=[('', 'Seleccioná...')] + list(Empresa.TiempoRadicacion.choices),
        widget=forms.Select(attrs=_SEL),
    )
    superficie_cubierta_trabajo_m2 = forms.DecimalField(
        label='Sup. cubierta de trabajo (m²)', min_value=0,
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={**_NUM, 'step': '0.01', 'min': '0'}),
    )
    superficie_cubierta_deposito_m2 = forms.DecimalField(
        label='Sup. cubierta de depósito (m²)', min_value=0,
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={**_NUM, 'step': '0.01', 'min': '0'}),
    )
    superficie_futura_expansion_m2 = forms.DecimalField(
        label='Sup. futura expansión (m²)', min_value=0,
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={**_NUM, 'step': '0.01', 'min': '0'}),
    )
    superficie_estacionamiento_m2 = forms.DecimalField(
        label='Sup. estacionamiento (m²)', min_value=0,
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={**_NUM, 'step': '0.01', 'min': '0'}),
    )
    tiene_planos = forms.BooleanField(
        label='Tiene planos confeccionados', required=False,
    )
    energia_tension = forms.ChoiceField(
        label='Energía eléctrica — tensión', required=False,
        choices=[('', '—')] + list(Empresa.TensionElectrica.choices),
        widget=forms.Select(attrs=_SEL),
    )
    energia_potencia_rango = forms.ChoiceField(
        label='Energía eléctrica — potencia (kW)', required=False,
        choices=[('', '—')] + list(Empresa.RangoPotencia.choices),
        widget=forms.Select(attrs=_SEL),
    )
    consumo_estimado_agua_potable = forms.ChoiceField(
        label='Consumo agua potable estimado', required=False,
        choices=[('', '—')] + list(Empresa.RangoConsumoAgua.choices),
        widget=forms.Select(attrs=_SEL),
    )
    consumo_estimado_agua_cruda = forms.ChoiceField(
        label='Consumo agua cruda/industrial estimado', required=False,
        choices=[('', '—')] + list(Empresa.RangoConsumoAgua.choices),
        widget=forms.Select(attrs=_SEL),
    )
    gas = forms.BooleanField(label='Gas', required=False)
    requiere_internet = forms.BooleanField(label='Requiere internet', required=False)
    necesidad_balanza_publica = forms.BooleanField(label='Necesidad de balanza pública', required=False)
    necesidad_comedor = forms.BooleanField(label='Necesidad de comedor comunitario', required=False)
    necesidad_salon_multiuso = forms.BooleanField(label='Necesidad de salón de usos múltiples', required=False)
    categoria_industrial = forms.ChoiceField(
        label='Categoría industrial',
        choices=[('', 'Seleccioná...')] + list(Empresa.CategoriaIndustrial.choices),
        widget=forms.Select(attrs=_SEL),
    )
    maneja_inflamables = forms.BooleanField(label='Maneja materiales inflamables', required=False)
    genera_residuos = forms.BooleanField(label='Genera residuos / efluentes', required=False)
    tratamiento_en_planta = forms.BooleanField(label='Prevé tratamiento en planta', required=False)

    representante_nombre = forms.CharField(
        label='Nombre y apellido', max_length=150,
        widget=forms.TextInput(attrs=_TXT),
    )
    representante_dni = forms.CharField(
        label='DNI', max_length=20,
        widget=forms.TextInput(attrs=_TXT),
    )
    representante_cargo = forms.CharField(
        label='Cargo', max_length=100,
        widget=forms.TextInput(attrs=_TXT),
    )
    representante_email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs=_TXT),
    )
    representante_telefono = forms.CharField(
        label='Teléfono', max_length=30,
        widget=forms.TextInput(attrs=_TXT),
    )

    username = forms.CharField(
        label='Nombre de usuario', max_length=150,
        help_text='Lo usarás para iniciar sesión en el sistema.',
        widget=forms.TextInput(attrs={**_TXT, 'autocomplete': 'username'}),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={**_TXT, 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={**_TXT, 'autocomplete': 'new-password'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya está en uso.')
        return username

    def clean_cuit(self):
        import re
        cuit = self.cleaned_data['cuit'].strip()
        if not re.match(r'^\d{2}-\d{8}-\d{1}$', cuit):
            raise forms.ValidationError('El CUIT debe tener el formato XX-XXXXXXXX-X.')
        if Empresa.objects.filter(cuit=cuit).exists():
            raise forms.ValidationError('Ya existe una empresa registrada con ese CUIT.')
        return cuit

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        if p1:
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(p1)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return cleaned
