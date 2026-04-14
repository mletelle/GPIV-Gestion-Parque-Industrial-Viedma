from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django import forms
from django.core.validators import FileExtensionValidator
from .models import Lote, Empresa, CustomUser, AvanceConstructivo, SolicitudProrroga


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

    class Meta:
        model = Empresa
        fields = [
            # informacion fiscal
            'razon_social', 'nombre_fantasia', 'cuit', 'ingresos_brutos',
            'tipo_empresa', 'objetivo_proyecto', 'rubro',
            'actividad_principal', 'actividad_secundaria', 'descripcion_actividad',
            # contacto
            'direccion', 'persona_referente', 'telefono', 'correo_electronico',
            # detalle del proyecto
            'emplazamiento_actual', 'personal_jerarquico', 'personal_produccion',
            'personal_administrativo', 'personal_a_ocupar',
            'materias_primas', 'destino_produccion',
            # infraestructura
            'necesidad_m2', 'superficie_cubierta_trabajo_m2',
            'superficie_cubierta_deposito_m2', 'superficie_futura_expansion_m2',
            'superficie_estacionamiento_m2', 'tiene_planos', 'tiempo_radicacion_meses',
            # servicios
            'energia_tension', 'energia_potencia_kw',
            'consumo_estimado_agua_potable_m3', 'consumo_estimado_agua_cruda_m3',
            'gas', 'requiere_internet',
            'necesidad_balanza_publica', 'necesidad_comedor', 'necesidad_salon_multiuso',
            # impacto ambiental
            'categoria_industrial', 'maneja_inflamables',
            'residuos_efluentes', 'tratamiento_en_planta',
        ]

    # campos agrupados por seccion para renderizar en el template
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
            'emplazamiento_actual', 'personal_jerarquico', 'personal_produccion',
            'personal_administrativo', 'personal_a_ocupar',
            'materias_primas', 'destino_produccion',
        ]),
        ('Requerimientos de Infraestructura', [
            'necesidad_m2', 'superficie_cubierta_trabajo_m2',
            'superficie_cubierta_deposito_m2', 'superficie_futura_expansion_m2',
            'superficie_estacionamiento_m2', 'tiene_planos', 'tiempo_radicacion_meses',
        ]),
        ('Requerimientos de Servicios', [
            'energia_tension', 'energia_potencia_kw',
            'consumo_estimado_agua_potable_m3', 'consumo_estimado_agua_cruda_m3',
            'gas', 'requiere_internet',
            'necesidad_balanza_publica', 'necesidad_comedor', 'necesidad_salon_multiuso',
        ]),
        ('Impacto Ambiental', [
            'categoria_industrial', 'maneja_inflamables',
            'residuos_efluentes', 'tratamiento_en_planta',
        ]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # aplicar clases css a todos los campos
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

    def get_secciones(self):
        """devuelve las secciones con los campos bound para iterar en template"""
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
