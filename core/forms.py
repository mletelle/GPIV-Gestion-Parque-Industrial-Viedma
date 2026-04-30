from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django import forms
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from .models import Lote, Empresa, CustomUser, AvanceConstructivo, SolicitudProrroga, ConsumoServicio, ActivoInventario
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


class RegistroUsuarioForm(UserCreationForm):
    """Registro de usuario empresa."""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'correo@ejemplo.com',
        })
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Nombre de usuario',
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Contraseña',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirmar contraseña',
        })


class SolicitudRadicacionForm(forms.ModelForm):
    """Formulario de solicitud de radicacion, dividido en secciones."""

    NUMERICOS_NO_NEGATIVOS = [
        'personal_jerarquico', 'personal_produccion', 'personal_administrativo',
        'personal_a_ocupar', 'necesidad_m2', 'superficie_cubierta_trabajo_m2',
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


# ---------------------------------------------------------------------------
# Formularios RBAC internos de Empresa
# ---------------------------------------------------------------------------

class InvitarMiembroForm(forms.Form):
    """
    Formulario para que el Titular invite a un usuario existente como miembro
    Estándar de su empresa.

    Busca al usuario por nombre de usuario (username) y valida que:
    - El usuario exista en el sistema.
    - El usuario esté en el grupo EMPRESA (es un representante de empresa).
    - No pertenezca ya a ninguna empresa.
    """
    username = forms.CharField(
        max_length=150,
        label='Nombre de usuario',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre de usuario del nuevo miembro',
            'autofocus': True,
        }),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        try:
            usuario = CustomUser.objects.get(username=username, is_active=True)
        except CustomUser.DoesNotExist:
            raise forms.ValidationError(
                f'No existe ningún usuario activo con el nombre "{username}".'
            )

        if not usuario.groups.filter(name='EMPRESA').exists():
            raise forms.ValidationError(
                'El usuario no tiene el perfil de empresa requerido para ser miembro.'
            )

        if usuario.tiene_empresa_asociada():
            raise forms.ValidationError(
                f'El usuario "{username}" ya está asociado a una empresa.'
            )

        self.cleaned_data['usuario_obj'] = usuario
        return username

    def get_usuario(self):
        """Devuelve el objeto CustomUser validado."""
        return self.cleaned_data.get('usuario_obj')


class TransferirTitularidadForm(forms.Form):
    """
    Formulario para que el Titular transfiera su rol a otro miembro de la empresa.

    El queryset del campo ``nuevo_titular`` se limita a los miembros activos
    de la empresa, excluyendo al titular actual. Se inyecta vía ``__init__``.
    """
    nuevo_titular = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        label='Nuevo Titular',
        empty_label='— Seleccione un miembro —',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, empresa=None, titular_actual=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa and titular_actual:
            self.fields['nuevo_titular'].queryset = (
                empresa.get_miembros()
                .exclude(pk=titular_actual.pk)
            )
