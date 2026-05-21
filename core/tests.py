"""
Tests de auditoría — Issue #45
Valida que django-simple-history registra correctamente creaciones,
ediciones, eliminaciones y soft-deletes en todas las entidades críticas,
capturando usuario, timestamp y detalle del cambio.
"""
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.forms import RegistroEmpresaWizardForm
from core.models import (
    Empresa, Lote, TransicionEstado, AvanceConstructivo,
    SolicitudProrroga, ConsumoServicio, Ticket, MensajeTicket,
    ActivoInventario, SolicitudAcceso, AvisoVencimiento,
    CaducidadRegistro, CustomUser,
)
from core.services import (
    enviar_aviso_vencimiento,
    ejecutar_caducidad,
    notificar_admin_caducidades,
    tiene_prorroga_vigente,
    evaluar_incompatibilidades_lote,
    transferir_titularidad, invitar_usuario, remover_miembro,
    RBACError, UsuarioYaVinculadoError, UsuarioNoEsMiembroError,
    NoSePuedeDegradarTitularError,
)

User = get_user_model()


def _crear_empresa(**overrides):
    """Crea una Empresa con datos mínimos válidos."""
    defaults = dict(
        razon_social='Acme S.A.',
        cuit='30-12345678-9',
        actividad_principal='Fabricación',
        tipo_empresa=Empresa.TipoEmpresa.NUEVA,
        rubro=Empresa.Rubro.METALURGICA,
        descripcion_actividad='Fabricación de piezas metálicas',
        persona_referente='Juan Pérez',
        telefono='2920-000000',
        correo_electronico='acme@ejemplo.com',
        personal_a_ocupar=10,
        necesidad_m2=Empresa.RangoNecesidadM2.DE_500_A_1000,
        superficie_cubierta_trabajo_m2=Decimal('300.00'),
        superficie_cubierta_deposito_m2=Decimal('100.00'),
        tiene_planos=True,
        tiempo_radicacion_meses=12,
        categoria_industrial=Empresa.CategoriaIndustrial.OTRO,
    )
    defaults.update(overrides)
    return Empresa.objects.create(**defaults)


def _crear_lote(**overrides):
    """Crea un Lote con datos mínimos válidos."""
    defaults = dict(
        nro_parcela=1,
        superficie_m2=Decimal('1000.00'),
    )
    defaults.update(overrides)
    return Lote.objects.create(**defaults)


class HistoricalRecordsPresenciaTest(TestCase):
    """Verifica que los 12 modelos críticos tienen HistoricalRecords."""

    MODELOS_AUDITADOS = [
        Empresa, Lote, TransicionEstado, AvanceConstructivo,
        SolicitudProrroga, ConsumoServicio, Ticket, MensajeTicket,
        ActivoInventario, SolicitudAcceso, AvisoVencimiento,
        CaducidadRegistro,
    ]

    def test_todos_los_modelos_tienen_history(self):
        """Cada modelo auditado debe tener el atributo 'history'
        que es instancia de HistoricalRecords (descriptor)."""
        for modelo in self.MODELOS_AUDITADOS:
            with self.subTest(modelo=modelo.__name__):
                self.assertTrue(
                    hasattr(modelo, 'history'),
                    f'{modelo.__name__} no tiene atributo "history"',
                )
                # Verifica que el manager del historial existe en la instancia
                # a nivel de clase (descriptor de HistoricalRecords).
                history_manager = getattr(modelo, 'history')
                self.assertTrue(
                    hasattr(history_manager, 'model'),
                    f'{modelo.__name__}.history no es un HistoricalManager válido',
                )


# ===========================================================================
# 2. Registro de creación (+)
# ===========================================================================


class HistorialCreacionTest(TestCase):
    """Al crear una entidad se genera un registro con history_type '+'."""

    def test_creacion_empresa(self):
        empresa = _crear_empresa()
        historial = empresa.history.all()
        self.assertEqual(historial.count(), 1)
        registro = historial.first()
        self.assertEqual(registro.history_type, '+')
        self.assertEqual(registro.razon_social, empresa.razon_social)

    def test_creacion_lote(self):
        lote = _crear_lote()
        historial = lote.history.all()
        self.assertEqual(historial.count(), 1)
        self.assertEqual(historial.first().history_type, '+')
        self.assertEqual(historial.first().superficie_m2, lote.superficie_m2)


# ===========================================================================
# 3. Registro de edición (~) y delta de cambios
# ===========================================================================


class HistorialEdicionTest(TestCase):
    """Al modificar campos se genera un registro con history_type '~'
    y diff_against muestra los cambios correctamente."""

    def test_edicion_empresa(self):
        empresa = _crear_empresa()
        empresa.razon_social = 'Acme Renovada S.A.'
        empresa.save()

        historial = empresa.history.all()
        self.assertEqual(historial.count(), 2)
        ultimo = historial.first()
        self.assertEqual(ultimo.history_type, '~')
        self.assertEqual(ultimo.razon_social, 'Acme Renovada S.A.')

    def test_edicion_lote_superficie(self):
        lote = _crear_lote(superficie_m2=Decimal('500.00'))
        lote.superficie_m2 = Decimal('750.00')
        lote.save()

        historial = lote.history.all()
        self.assertEqual(historial.count(), 2)
        self.assertEqual(historial.first().superficie_m2, Decimal('750.00'))

    def test_diff_against_muestra_cambios(self):
        """diff_against() debe reportar los campos que cambiaron."""
        empresa = _crear_empresa()
        empresa.razon_social = 'Nombre Nuevo'
        empresa.save()

        nuevo, viejo = empresa.history.all()[:2]
        delta = nuevo.diff_against(viejo)

        nombres_cambiados = [c.field for c in delta.changes]
        self.assertIn('razon_social', nombres_cambiados)


# ===========================================================================
# 4. Registro de eliminación (-)
# ===========================================================================


class HistorialEliminacionTest(TestCase):
    """Al eliminar un registro se genera un registro con history_type '-'."""

    def test_eliminacion_lote(self):
        lote = _crear_lote(nro_parcela=99)
        lote_pk = lote.pk
        lote.delete()

        historial = Lote.history.filter(id=lote_pk)
        ultimo = historial.first()
        self.assertEqual(ultimo.history_type, '-')


# ===========================================================================
# 5. Captura de usuario (history_user)
# ===========================================================================


class HistorialUsuarioTest(TestCase):
    """Los cambios realizados con el middleware deben capturar history_user.
    En tests sin middleware usamos _history_user para verificar."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_test', password='test1234', is_staff=True,
        )

    def test_history_user_capturado(self):
        """Asignar _history_user en el save() para simular middleware."""
        empresa = _crear_empresa()
        empresa.razon_social = 'Cambio con usuario'
        empresa._history_user = self.admin
        empresa.save()

        ultimo = empresa.history.first()
        self.assertEqual(ultimo.history_user, self.admin)

    def test_history_user_en_lote(self):
        lote = _crear_lote()
        lote.estado = Lote.Estado.EN_USO
        lote._history_user = self.admin
        lote.save()

        ultimo = lote.history.first()
        self.assertEqual(ultimo.history_user, self.admin)


# ===========================================================================
# 6. Compatibilidad con save(update_fields=...)
# ===========================================================================


class HistorialUpdateFieldsTest(TestCase):
    """save(update_fields=[...]) también genera registros históricos."""

    def test_update_fields_empresa_estado(self):
        empresa = _crear_empresa()
        empresa.estado = Empresa.Estado.PRE_APROBADO
        empresa.save(update_fields=['estado'])

        historial = empresa.history.all()
        self.assertEqual(historial.count(), 2)
        self.assertEqual(historial.first().estado, Empresa.Estado.PRE_APROBADO)

    def test_update_fields_lote(self):
        lote = _crear_lote()
        lote.conexion_gas = True
        lote.save(update_fields=['conexion_gas'])

        historial = lote.history.all()
        self.assertEqual(historial.count(), 2)
        self.assertTrue(historial.first().conexion_gas)


# ===========================================================================
# 7. Integración con soft-delete
# ===========================================================================


class HistorialSoftDeleteTest(TestCase):
    """soft_delete() genera un registro de cambio ('~'), NO de eliminación ('-')."""

    def test_soft_delete_ticket(self):
        user = User.objects.create_user(username='u1', password='p')
        ticket = Ticket.objects.create(
            asunto='Test ticket', creador=user,
        )
        ticket.soft_delete()

        historial = ticket.history.all()
        # creación + soft_delete = 2 registros
        self.assertEqual(historial.count(), 2)
        ultimo = historial.first()
        self.assertEqual(ultimo.history_type, '~')
        self.assertFalse(ultimo.is_active)
        self.assertIsNotNone(ultimo.deleted_at)

    def test_soft_delete_aviso_vencimiento(self):
        empresa = _crear_empresa()
        aviso = AvisoVencimiento.objects.create(
            empresa=empresa,
            nivel=AvisoVencimiento.Nivel.URGENTE,
            dias_restantes=5,
            email_destino='test@ejemplo.com',
        )
        aviso.soft_delete()

        historial = aviso.history.all()
        self.assertEqual(historial.count(), 2)
        ultimo = historial.first()
        self.assertEqual(ultimo.history_type, '~')
        self.assertFalse(ultimo.is_active)

    def test_soft_delete_caducidad_registro(self):
        empresa = _crear_empresa()
        registro = CaducidadRegistro.objects.create(
            empresa=empresa,
            estado_anterior=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_original=date.today(),
            justificacion='Vencimiento automático',
        )
        registro.soft_delete()

        historial = registro.history.all()
        self.assertEqual(historial.count(), 2)
        self.assertEqual(historial.first().history_type, '~')
        self.assertFalse(historial.first().is_active)

    def test_soft_delete_mensaje_ticket(self):
        user = User.objects.create_user(username='u2', password='p')
        ticket = Ticket.objects.create(asunto='T2', creador=user)
        mensaje = MensajeTicket.objects.create(
            ticket=ticket, autor=user, contenido='Hola',
        )
        mensaje.soft_delete()

        historial = mensaje.history.all()
        self.assertEqual(historial.count(), 2)
        self.assertEqual(historial.first().history_type, '~')
        self.assertFalse(historial.first().is_active)


# ===========================================================================
# 8. Modelos complementarios: verificar registros en todos los auditados
# ===========================================================================


class HistorialModelosComplementariosTest(TestCase):
    """Verifica creación de historial en modelos que no cubren los tests
    anteriores: TransicionEstado, AvanceConstructivo, SolicitudProrroga,
    ConsumoServicio, ActivoInventario, SolicitudAcceso."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.empresa = _crear_empresa()
        self.user = User.objects.create_user(
            username='auditor', password='test1234',
        )

    def test_transicion_estado(self):
        t = TransicionEstado.objects.create(
            empresa=self.empresa,
            estado_anterior=Empresa.Estado.EN_EVALUACION,
            estado_nuevo=Empresa.Estado.PRE_APROBADO,
            usuario=self.user,
        )
        self.assertEqual(t.history.count(), 1)
        self.assertEqual(t.history.first().history_type, '+')

    def test_avance_constructivo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf = SimpleUploadedFile('cert.pdf', b'%PDF-test', content_type='application/pdf')
        av = AvanceConstructivo.objects.create(
            empresa=self.empresa,
            porcentaje_declarado=Decimal('25.00'),
            certificado_pdf=pdf,
        )
        self.assertEqual(av.history.count(), 1)

        # edición
        av.validado_admin = True
        av.save(update_fields=['validado_admin'])
        self.assertEqual(av.history.count(), 2)
        self.assertTrue(av.history.first().validado_admin)

    def test_solicitud_prorroga(self):
        sp = SolicitudProrroga.objects.create(
            empresa=self.empresa,
            meses_solicitados=12,
            justificacion='Necesitamos más tiempo',
        )
        self.assertEqual(sp.history.count(), 1)

        sp.estado = SolicitudProrroga.EstadoProrroga.APROBADA
        sp.save()
        self.assertEqual(sp.history.count(), 2)
        self.assertEqual(
            sp.history.first().estado,
            SolicitudProrroga.EstadoProrroga.APROBADA,
        )

    def test_consumo_servicio(self):
        cs = ConsumoServicio.objects.create(
            empresa=self.empresa,
            periodo_mes=5,
            periodo_anio=2026,
            consumo_luz_kwh=Decimal('150.50'),
            cargado_por=self.user,
        )
        self.assertEqual(cs.history.count(), 1)

    def test_activo_inventario(self):
        activo = ActivoInventario.objects.create(
            categoria=ActivoInventario.Categoria.INFORMATICO_MOBILIARIO,
            nombre='Notebook Dell',
            codigo_inventario='INF-2026001',
            fecha_alta=date.today(),
            registrado_por=self.user,
        )
        self.assertEqual(activo.history.count(), 1)

        # baja lógica
        activo.activo = False
        activo.motivo_baja = 'Obsoleto'
        activo.fecha_baja = date.today()
        activo.dado_de_baja_por = self.user
        activo.save()
        self.assertEqual(activo.history.count(), 2)
        self.assertFalse(activo.history.first().activo)

    def test_solicitud_acceso(self):
        user_solicitante = User.objects.create_user(
            username='solicitante', password='test', is_active=False,
        )
        sa = SolicitudAcceso.objects.create(
            tipo=SolicitudAcceso.Tipo.ORGANISMO,
            nombre_apellido='María López',
            cargo='Directora',
            organizacion='Municipio de Viedma',
            telefono='2920-111111',
            email_institucional='maria@municipio.gob.ar',
            tipo_acceso='MUNICIPAL',
            motivo='Necesito consultar datos del parque',
            usuario=user_solicitante,
        )
        self.assertEqual(sa.history.count(), 1)

        sa.estado = SolicitudAcceso.Estado.APROBADA
        sa.save()
        self.assertEqual(sa.history.count(), 2)
        self.assertEqual(
            sa.history.first().estado,
            SolicitudAcceso.Estado.APROBADA,
        )


# ===========================================================================
# 9. Integración con registrar_transicion del servicio
# ===========================================================================


class HistorialRegistrarTransicionTest(TestCase):
    """Verifica que registrar_transicion() (services.py) genera historial
    tanto en la Empresa como en TransicionEstado."""

    def test_transicion_genera_historial_empresa_y_transicion(self):
        from core.services import registrar_transicion

        empresa = _crear_empresa()
        user = User.objects.create_user(username='admin_tr', password='p')

        registrar_transicion(
            empresa,
            Empresa.Estado.PRE_APROBADO,
            usuario=user,
            justificacion='Aprobación inicial',
        )

        # Empresa: creación + cambio de estado = 2
        self.assertEqual(empresa.history.count(), 2)
        self.assertEqual(
            empresa.history.first().estado,
            Empresa.Estado.PRE_APROBADO,
        )

        # TransicionEstado: 1 creación
        transicion = TransicionEstado.objects.get(empresa=empresa)
        self.assertEqual(transicion.history.count(), 1)
        self.assertEqual(transicion.history.first().history_type, '+')


"""
tests para el sistema de avisos automaticos de vencimiento (issue #14).

valida:
- envio de aviso urgente (<=7 dias)
- envio de aviso proximo (8-30 dias)
- idempotencia (no duplica avisos recientes)
- empresa fuera de estado EN_CONSTRUCCION no recibe aviso
- empresa sin fecha_limite_obra no recibe aviso
- dry-run no envia ni crea registros
- funcion de servicio enviar_aviso_vencimiento directamente

usa mock de enviar_email_resend para no depender de Resend API.
"""

def _crear_empresa_aviso(razon_social, cuit, estado, fecha_limite_obra=None,
                         ultimo_aviso=None):
    """helper: crea una empresa minima para tests."""
    return Empresa.objects.create(
        razon_social=razon_social,
        cuit=cuit,
        estado=estado,
        actividad_principal='Test',
        rubro=Empresa.Rubro.SERVICIOS,
        descripcion_actividad='Test desc',
        persona_referente='Test',
        telefono='2920000000',
        correo_electronico=f'{cuit}@test.local',
        personal_a_ocupar=1,
        necesidad_m2=Empresa.RangoNecesidadM2.HASTA_200,
        superficie_cubierta_trabajo_m2=100,
        superficie_cubierta_deposito_m2=50,
        tiene_planos=True,
        tiempo_radicacion_meses=12,
        categoria_industrial=Empresa.CategoriaIndustrial.OTRO,
        fecha_limite_obra=fecha_limite_obra,
        ultimo_aviso_vencimiento=ultimo_aviso,
    )


# mock de enviar_email_resend que siempre retorna exitoso
MOCK_RESEND_PATH = 'core.services.enviar_email_resend'


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
)
class AvisoVencimientoServiceTest(TestCase):
    """tests unitarios de la funcion de servicio enviar_aviso_vencimiento."""

    def setUp(self):
        self.hoy = timezone.now().date()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-email-id'})
    def test_envio_urgente_no_actualiza_tracking_global(self, mock_email):
        """empresa con 5 dias → aviso urgente creado, email enviado."""
        empresa = _crear_empresa_aviso(
            'Urgente SA', '20-11111111-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )
        aviso = enviar_aviso_vencimiento(
            empresa, 5, AvisoVencimiento.Nivel.URGENTE,
        )

        self.assertIsNotNone(aviso)
        self.assertEqual(aviso.nivel, AvisoVencimiento.Nivel.URGENTE)
        self.assertEqual(aviso.dias_restantes, 5)
        self.assertEqual(aviso.email_destino, empresa.correo_electronico)

        # verificar que el mock fue llamado con los args correctos
        mock_email.assert_called_once()
        call_args = mock_email.call_args
        self.assertEqual(call_args[0][0], empresa.correo_electronico)
        self.assertIn('urgente', call_args[0][1].lower())

        # el tracking por nivel queda en AvisoVencimiento
        empresa.refresh_from_db()
        self.assertIsNone(empresa.ultimo_aviso_vencimiento)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-email-id'})
    def test_envio_proximo_crea_aviso(self, mock_email):
        """empresa con 20 dias → aviso proximo creado."""
        empresa = _crear_empresa_aviso(
            'Proxima SRL', '20-22222222-2',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=20),
        )
        aviso = enviar_aviso_vencimiento(
            empresa, 20, AvisoVencimiento.Nivel.PROXIMO,
        )

        self.assertIsNotNone(aviso)
        self.assertEqual(aviso.nivel, AvisoVencimiento.Nivel.PROXIMO)
        self.assertEqual(aviso.dias_restantes, 20)
        mock_email.assert_called_once()

    @patch(MOCK_RESEND_PATH, return_value=False)
    def test_fallo_email_no_crea_aviso(self, mock_email):
        """si enviar_email_resend retorna False, no se crea AvisoVencimiento."""
        empresa = _crear_empresa_aviso(
            'Fallida SA', '20-33333333-3',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )
        aviso = enviar_aviso_vencimiento(
            empresa, 5, AvisoVencimiento.Nivel.URGENTE,
        )

        self.assertIsNone(aviso)
        self.assertEqual(AvisoVencimiento.objects.count(), 0)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-email-id'})
    def test_empresa_sin_email_no_envia(self, mock_email):
        """empresa sin correo_electronico → aviso omitido."""
        empresa = _crear_empresa_aviso(
            'SinMail SA', '20-44444444-4',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )
        empresa.correo_electronico = ''
        empresa.save(update_fields=['correo_electronico'])

        aviso = enviar_aviso_vencimiento(
            empresa, 5, AvisoVencimiento.Nivel.URGENTE,
        )

        self.assertIsNone(aviso)
        mock_email.assert_not_called()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-email-id'})
    def test_html_contiene_datos_empresa(self, mock_email):
        """el html enviado contiene razon social, cuit, fecha limite."""
        empresa = _crear_empresa_aviso(
            'DatosVerif SAS', '20-55555555-5',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=3),
        )
        enviar_aviso_vencimiento(
            empresa, 3, AvisoVencimiento.Nivel.URGENTE,
        )

        html_enviado = mock_email.call_args[0][2]
        self.assertIn('DatosVerif SAS', html_enviado)
        self.assertIn('20-55555555-5', html_enviado)
        self.assertIn(empresa.fecha_limite_obra.strftime('%d/%m/%Y'), html_enviado)


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
)
class NotificarVencimientosCommandTest(TestCase):
    """tests del management command notificar_vencimientos."""

    def setUp(self):
        self.hoy = timezone.now().date()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_urgente_recibe_email(self, mock_email):
        """empresa con vencimiento en 5 dias → email urgente enviado."""
        _crear_empresa_aviso(
            'Urgente CMD SA', '20-66666666-6',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 1)
        aviso = AvisoVencimiento.objects.first()
        self.assertEqual(aviso.nivel, AvisoVencimiento.Nivel.URGENTE)
        self.assertIn('Avisos urgentes: 1', out.getvalue())
        mock_email.assert_called_once()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_proximo_recibe_email(self, mock_email):
        """empresa con vencimiento en 20 dias → email proximo enviado."""
        _crear_empresa_aviso(
            'Proximo CMD SRL', '20-77777777-7',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=20),
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 1)
        aviso = AvisoVencimiento.objects.first()
        self.assertEqual(aviso.nivel, AvisoVencimiento.Nivel.PROXIMO)
        self.assertIn('Avisos proximos: 1', out.getvalue())

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_idempotencia_urgente_no_duplica(self, mock_email):
        """empresa con aviso urgente reciente (<7 dias) no recibe duplicado."""
        empresa = _crear_empresa_aviso(
            'NoDup SA', '20-88888888-8',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )
        AvisoVencimiento.objects.create(
            empresa=empresa,
            nivel=AvisoVencimiento.Nivel.URGENTE,
            dias_restantes=6,
            email_destino=empresa.correo_electronico,
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 1)
        mock_email.assert_not_called()
        self.assertIn('Avisos urgentes: 0', out.getvalue())

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_aviso_proximo_reciente_no_bloquea_aviso_urgente(self, mock_email):
        """un aviso proximo reciente no impide enviar luego el urgente."""
        empresa = _crear_empresa_aviso(
            'CambioUmbral SA', '20-89898989-8',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=7),
        )
        AvisoVencimiento.objects.create(
            empresa=empresa,
            nivel=AvisoVencimiento.Nivel.PROXIMO,
            dias_restantes=8,
            email_destino=empresa.correo_electronico,
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 2)
        self.assertEqual(
            AvisoVencimiento.objects.latest('fecha_envio').nivel,
            AvisoVencimiento.Nivel.URGENTE,
        )
        mock_email.assert_called_once()
        self.assertIn('Avisos urgentes: 1', out.getvalue())

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_radicada_no_recibe(self, mock_email):
        """empresa en estado Radicada no recibe aviso aunque tenga fecha."""
        _crear_empresa_aviso(
            'Radicada SA', '20-99999999-9',
            Empresa.Estado.RADICADA,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 0)
        mock_email.assert_not_called()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_sin_fecha_no_recibe(self, mock_email):
        """empresa sin fecha_limite_obra no recibe aviso."""
        _crear_empresa_aviso(
            'SinFecha SA', '20-10101010-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=None,
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 0)
        mock_email.assert_not_called()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_dry_run_no_envia_ni_crea(self, mock_email):
        """--dry-run lista pero no envia emails ni crea registros."""
        _crear_empresa_aviso(
            'DryRun SA', '20-12121212-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
        )

        out = StringIO()
        call_command('notificar_vencimientos', '--dry-run', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 0)
        mock_email.assert_not_called()
        output = out.getvalue()
        self.assertIn('DRY-RUN', output)
        self.assertIn('DryRun SA', output)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_multiples_empresas_reciben_correctamente(self, mock_email):
        """varias empresas con distintos plazos reciben el aviso correcto."""
        _crear_empresa_aviso(
            'Urgente1', '20-13131313-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=3),
        )
        _crear_empresa_aviso(
            'Proximo1', '20-14141414-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=15),
        )
        _crear_empresa_aviso(
            'FueraRango', '20-15151515-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=60),
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 2)
        self.assertEqual(mock_email.call_count, 2)

        niveles = set(
            AvisoVencimiento.objects.values_list('nivel', flat=True)
        )
        self.assertEqual(niveles, {'Urgente', 'Proximo'})


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
)
class AvisoVencimientoModelTest(TestCase):
    """tests del modelo AvisoVencimiento."""

    def test_soft_delete(self):
        """soft_delete desactiva el registro y setea deleted_at."""
        empresa = _crear_empresa_aviso(
            'SoftDel SA', '20-16161616-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=date.today() + timedelta(days=5),
        )
        aviso = AvisoVencimiento.objects.create(
            empresa=empresa,
            nivel=AvisoVencimiento.Nivel.URGENTE,
            dias_restantes=5,
            email_destino=empresa.correo_electronico,
        )

        self.assertTrue(aviso.is_active)
        self.assertIsNone(aviso.deleted_at)

        aviso.soft_delete()
        aviso.refresh_from_db()

        self.assertFalse(aviso.is_active)
        self.assertIsNotNone(aviso.deleted_at)

    def test_str_representation(self):
        """__str__ incluye nivel, empresa y dias."""
        empresa = _crear_empresa_aviso(
            'StrTest SA', '20-17171717-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=date.today() + timedelta(days=10),
        )
        aviso = AvisoVencimiento.objects.create(
            empresa=empresa,
            nivel=AvisoVencimiento.Nivel.PROXIMO,
            dias_restantes=10,
            email_destino='test@test.local',
        )
        s = str(aviso)
        self.assertIn('StrTest SA', s)
        self.assertIn('10d', s)


"""
tests para el sistema de caducidad automatica de obras vencidas (issue #48).

valida:
- empresa vencida sin prorroga → se caduca + email a empresa + email admin
- empresa vencida con prorroga aprobada → NO se caduca
- empresa vencida con prorroga pendiente → NO se caduca
- empresa vencida con prorroga rechazada → SI se caduca
- empresa sin fecha_limite_obra → no se caduca
- empresa no en construccion → no se caduca
- dry-run lista pero no caduca
- multiples empresas con distintos escenarios
- baja logica de CaducidadRegistro
- servicio directo ejecutar_caducidad
- notificacion admin con resumen

usa mock de enviar_email_resend para no depender de Resend API.
"""

def _crear_empresa_caducidad(razon_social, cuit, estado, fecha_limite_obra=None):
    """helper: crea una empresa minima para tests."""
    return Empresa.objects.create(
        razon_social=razon_social,
        cuit=cuit,
        estado=estado,
        actividad_principal='Test',
        rubro=Empresa.Rubro.SERVICIOS,
        descripcion_actividad='Test desc',
        persona_referente='Test',
        telefono='2920000000',
        correo_electronico=f'{cuit}@test.local',
        personal_a_ocupar=1,
        necesidad_m2=Empresa.RangoNecesidadM2.HASTA_200,
        superficie_cubierta_trabajo_m2=100,
        superficie_cubierta_deposito_m2=50,
        tiene_planos=True,
        tiempo_radicacion_meses=12,
        categoria_industrial=Empresa.CategoriaIndustrial.OTRO,
        fecha_limite_obra=fecha_limite_obra,
    )


def _crear_prorroga(empresa, estado):
    """helper: crea una prorroga para la empresa."""
    return SolicitudProrroga.objects.create(
        empresa=empresa,
        meses_solicitados=6,
        justificacion='Test prorroga',
        estado=estado,
    )


MOCK_RESEND_PATH = 'core.services.enviar_email_resend'


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
    SUPPORT_INBOX_EMAIL='admin@gpiv.local',
)
class EjecutarCaducidadServiceTest(TestCase):
    """tests unitarios de la funcion de servicio ejecutar_caducidad."""

    def setUp(self):
        self.ayer = timezone.now().date() - timedelta(days=1)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_vencida_sin_prorroga_se_caduca(self, mock_email):
        """empresa vencida sin prorroga → transicion + registro + email."""
        empresa = _crear_empresa_caducidad(
            'Vencida SA', '20-11111111-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )

        registro = ejecutar_caducidad(empresa)

        # se creo el registro
        self.assertIsNotNone(registro)
        self.assertEqual(registro.estado_anterior, Empresa.Estado.EN_CONSTRUCCION)
        self.assertEqual(registro.fecha_limite_original, self.ayer)
        self.assertTrue(registro.notificacion_enviada)
        self.assertEqual(registro.email_destino, empresa.correo_electronico)

        # la empresa cambio de estado
        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.CADUCADO)

        # se registro la transicion
        transicion = TransicionEstado.objects.filter(empresa=empresa).first()
        self.assertIsNotNone(transicion)
        self.assertEqual(transicion.estado_nuevo, Empresa.Estado.CADUCADO)

        # se envio email a la empresa
        mock_email.assert_called_once()
        destino_llamado = mock_email.call_args[0][0]
        self.assertEqual(destino_llamado, empresa.correo_electronico)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_con_prorroga_aprobada_no_caduca(self, mock_email):
        """empresa con prorroga aprobada → NO se caduca."""
        empresa = _crear_empresa_caducidad(
            'ConProrroga SA', '20-22222222-2',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.APROBADA)

        registro = ejecutar_caducidad(empresa)

        self.assertIsNone(registro)
        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.EN_CONSTRUCCION)
        mock_email.assert_not_called()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_con_prorroga_pendiente_no_caduca(self, mock_email):
        """empresa con prorroga pendiente → NO se caduca."""
        empresa = _crear_empresa_caducidad(
            'Pendiente SA', '20-33333333-3',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.PENDIENTE)

        registro = ejecutar_caducidad(empresa)

        self.assertIsNone(registro)
        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.EN_CONSTRUCCION)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_con_prorroga_rechazada_si_caduca(self, mock_email):
        """empresa con prorroga rechazada → SI se caduca."""
        empresa = _crear_empresa_caducidad(
            'Rechazada SA', '20-44444444-4',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.RECHAZADA)

        registro = ejecutar_caducidad(empresa)

        self.assertIsNotNone(registro)
        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.CADUCADO)

    @patch(MOCK_RESEND_PATH, return_value=False)
    def test_fallo_email_crea_registro_sin_notificacion(self, mock_email):
        """si el email falla, se crea registro con notificacion_enviada=False."""
        empresa = _crear_empresa_caducidad(
            'FalloMail SA', '20-55555555-5',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )

        registro = ejecutar_caducidad(empresa)

        self.assertIsNotNone(registro)
        self.assertFalse(registro.notificacion_enviada)
        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.CADUCADO)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_html_contiene_datos_empresa(self, mock_email):
        """el html del email contiene razon social, cuit, fecha limite."""
        empresa = _crear_empresa_caducidad(
            'HtmlVerif SAS', '20-66666666-6',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )

        ejecutar_caducidad(empresa)

        html_enviado = mock_email.call_args[0][2]
        self.assertIn('HtmlVerif SAS', html_enviado)
        self.assertIn('20-66666666-6', html_enviado)
        self.assertIn('Caducado', html_enviado)


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
    SUPPORT_INBOX_EMAIL='admin@gpiv.local',
)
class TieneProrrogaVigenteTest(TestCase):
    """tests de la funcion tiene_prorroga_vigente."""

    def setUp(self):
        self.ayer = timezone.now().date() - timedelta(days=1)

    def test_sin_prorroga_retorna_false(self):
        empresa = _crear_empresa_caducidad(
            'SinProrr', '20-77777777-7',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        self.assertFalse(tiene_prorroga_vigente(empresa))

    def test_prorroga_aprobada_retorna_true(self):
        empresa = _crear_empresa_caducidad(
            'Aprobada', '20-88888888-8',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.APROBADA)
        self.assertTrue(tiene_prorroga_vigente(empresa))

    def test_prorroga_pendiente_retorna_true(self):
        empresa = _crear_empresa_caducidad(
            'Pendiente', '20-99999999-9',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.PENDIENTE)
        self.assertTrue(tiene_prorroga_vigente(empresa))

    def test_prorroga_rechazada_retorna_false(self):
        empresa = _crear_empresa_caducidad(
            'Rechazada', '20-10101010-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.RECHAZADA)
        self.assertFalse(tiene_prorroga_vigente(empresa))


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
    SUPPORT_INBOX_EMAIL='admin@gpiv.local',
)
class NotificarAdminCaducidadesTest(TestCase):
    """tests de la funcion notificar_admin_caducidades."""

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_envia_resumen_a_admin(self, mock_email):
        """envia email con tabla de empresas caducadas a admin."""
        empresa = _crear_empresa_caducidad(
            'AdminNotif SA', '20-12121212-1',
            Empresa.Estado.CADUCADO,
            fecha_limite_obra=timezone.now().date() - timedelta(days=1),
        )
        registro = CaducidadRegistro.objects.create(
            empresa=empresa,
            estado_anterior=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_original=empresa.fecha_limite_obra,
            justificacion='Test',
            email_destino=empresa.correo_electronico,
            notificacion_enviada=True,
        )

        notificar_admin_caducidades([registro])

        mock_email.assert_called_once()
        destino = mock_email.call_args[0][0]
        self.assertEqual(destino, 'admin@gpiv.local')
        html = mock_email.call_args[0][2]
        self.assertIn('AdminNotif SA', html)
        self.assertIn('12121212', html)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_lista_vacia_no_envia(self, mock_email):
        """lista vacia → no envia email."""
        result = notificar_admin_caducidades([])
        self.assertIsNone(result)
        mock_email.assert_not_called()


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
    SUPPORT_INBOX_EMAIL='admin@gpiv.local',
)
class VerificarCaducidadesCommandTest(TestCase):
    """tests del management command verificar_caducidades."""

    def setUp(self):
        self.ayer = timezone.now().date() - timedelta(days=1)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_vencida_sin_prorroga_se_caduca(self, mock_email):
        """empresa vencida sin prorroga → caducada via command."""
        empresa = _crear_empresa_caducidad(
            'CMD Vencida', '20-13131313-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.CADUCADO)
        self.assertEqual(CaducidadRegistro.objects.count(), 1)
        self.assertIn('1 empresa(s) marcadas como Caducadas', out.getvalue())
        # 2 emails: 1 a empresa + 1 resumen a admin
        self.assertEqual(mock_email.call_count, 2)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_vencida_con_prorroga_aprobada_no_caduca(self, mock_email):
        """empresa con prorroga aprobada → excluida del command."""
        empresa = _crear_empresa_caducidad(
            'CMD Prorr', '20-14141414-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.APROBADA)

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.EN_CONSTRUCCION)
        self.assertEqual(CaducidadRegistro.objects.count(), 0)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_vencida_con_prorroga_pendiente_no_caduca(self, mock_email):
        """empresa con prorroga pendiente → excluida del command."""
        empresa = _crear_empresa_caducidad(
            'CMD Pend', '20-15151515-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.PENDIENTE)

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.EN_CONSTRUCCION)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_no_en_construccion_no_caduca(self, mock_email):
        """empresa en otro estado → no se caduca."""
        _crear_empresa_caducidad(
            'CMD Radicada', '20-16161616-1',
            Empresa.Estado.RADICADA,
            fecha_limite_obra=self.ayer,
        )

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        self.assertEqual(CaducidadRegistro.objects.count(), 0)
        mock_email.assert_not_called()

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_sin_fecha_no_caduca(self, mock_email):
        """empresa sin fecha_limite_obra → no se caduca."""
        _crear_empresa_caducidad(
            'CMD SinFecha', '20-17171717-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=None,
        )

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        self.assertEqual(CaducidadRegistro.objects.count(), 0)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_dry_run_no_caduca_ni_envia(self, mock_email):
        """--dry-run lista pero no caduca ni envia emails."""
        empresa = _crear_empresa_caducidad(
            'CMD DryRun', '20-18181818-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )

        out = StringIO()
        call_command('verificar_caducidades', '--dry-run', stdout=out)

        empresa.refresh_from_db()
        self.assertEqual(empresa.estado, Empresa.Estado.EN_CONSTRUCCION)
        self.assertEqual(CaducidadRegistro.objects.count(), 0)
        mock_email.assert_not_called()
        output = out.getvalue()
        self.assertIn('DRY-RUN', output)
        self.assertIn('CMD DryRun', output)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_multiples_empresas_escenarios_mixtos(self, mock_email):
        """mix: vencida sin prorroga, con aprobada, con rechazada."""
        # debe caducar
        e1 = _crear_empresa_caducidad(
            'Caduca1', '20-19191919-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        # no debe caducar (prorroga aprobada)
        e2 = _crear_empresa_caducidad(
            'NoCaduca', '20-20202020-2',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(e2, SolicitudProrroga.EstadoProrroga.APROBADA)
        # debe caducar (prorroga rechazada)
        e3 = _crear_empresa_caducidad(
            'Caduca2', '20-21212121-2',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(e3, SolicitudProrroga.EstadoProrroga.RECHAZADA)

        out = StringIO()
        call_command('verificar_caducidades', stdout=out)

        e1.refresh_from_db()
        e2.refresh_from_db()
        e3.refresh_from_db()

        self.assertEqual(e1.estado, Empresa.Estado.CADUCADO)
        self.assertEqual(e2.estado, Empresa.Estado.EN_CONSTRUCCION)
        self.assertEqual(e3.estado, Empresa.Estado.CADUCADO)

        self.assertEqual(CaducidadRegistro.objects.count(), 2)
        self.assertIn('2 empresa(s) marcadas como Caducadas', out.getvalue())


@override_settings(
    RESEND_API_KEY='test-key-fake',
    SITE_URL='http://localhost:8000',
    DEFAULT_FROM_EMAIL='test@gpiv.local',
    SUPPORT_INBOX_EMAIL='admin@gpiv.local',
)
class CaducidadRegistroModelTest(TestCase):
    """tests del modelo CaducidadRegistro."""

    def test_soft_delete(self):
        """soft_delete desactiva el registro y setea deleted_at."""
        empresa = _crear_empresa_caducidad(
            'SoftDel', '20-22222222-2',
            Empresa.Estado.CADUCADO,
            fecha_limite_obra=timezone.now().date() - timedelta(days=1),
        )
        registro = CaducidadRegistro.objects.create(
            empresa=empresa,
            estado_anterior=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_original=empresa.fecha_limite_obra,
            justificacion='Test',
            email_destino='test@test.local',
            notificacion_enviada=True,
        )

        self.assertTrue(registro.is_active)
        self.assertIsNone(registro.deleted_at)

        registro.soft_delete()
        registro.refresh_from_db()

        self.assertFalse(registro.is_active)
        self.assertIsNotNone(registro.deleted_at)

    def test_str_representation(self):
        """__str__ incluye empresa y fecha limite."""
        empresa = _crear_empresa_caducidad(
            'StrTest', '20-23232323-2',
            Empresa.Estado.CADUCADO,
            fecha_limite_obra=timezone.now().date() - timedelta(days=1),
        )
        registro = CaducidadRegistro.objects.create(
            empresa=empresa,
            estado_anterior=Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_original=empresa.fecha_limite_obra,
            justificacion='Test',
            email_destino='test@test.local',
        )
        s = str(registro)
        self.assertIn('StrTest', s)
        self.assertIn(str(empresa.fecha_limite_obra), s)


PASSWORD = "GpvTest12345!"


def group(nombre):
    return Group.objects.get_or_create(name=nombre)[0]


def user(username, *groups):
    usuario = CustomUser.objects.create_user(username=username, password=PASSWORD)
    for nombre_grupo in groups:
        usuario.groups.add(group(nombre_grupo))
    return usuario


def empresa(
    razon_social="Empresa Test SA",
    cuit="30-00000000-1",
    estado=Empresa.Estado.EN_EVALUACION,
    usuario=None,
    necesidad_m2=Empresa.RangoNecesidadM2.DE_500_A_1000,
    **overrides,
):
    datos = {
        "razon_social": razon_social,
        "cuit": cuit,
        "correo_electronico": f"{cuit.replace('-', '')}@example.com",
        "telefono": "2920123456",
        "direccion": "Parque Industrial",
        "estado": estado,
        "tipo_societario": Empresa.TipoSocietario.SRL,
        "tipo_empresa": Empresa.TipoEmpresa.NUEVA,
        "rubro": Empresa.Rubro.SERVICIOS,
        "persona_referente": "Referente",
        "actividad_principal": "Servicios industriales",
        "descripcion_actividad": "Actividad industrial de prueba",
        "personal_jerarquico": 1,
        "personal_administrativo": 1,
        "personal_produccion": 3,
        "personal_a_ocupar": 5,
        "materias_primas": "Insumos generales",
        "destino_produccion": "Mercado local",
        "necesidad_m2": necesidad_m2,
        "tiempo_radicacion_meses": Empresa.TiempoRadicacion.MESES_12,
        "superficie_cubierta_trabajo_m2": Decimal("100.00"),
        "superficie_cubierta_deposito_m2": Decimal("50.00"),
        "superficie_futura_expansion_m2": Decimal("25.00"),
        "superficie_estacionamiento_m2": Decimal("25.00"),
        "energia_tension": Empresa.TensionElectrica.BAJA,
        "energia_potencia_rango": Empresa.RangoPotencia.HASTA_10,
        "consumo_estimado_agua_potable": Empresa.RangoConsumoAgua.HASTA_50,
        "consumo_estimado_agua_cruda": Empresa.RangoConsumoAgua.HASTA_50,
        "gas": False,
        "categoria_industrial": Empresa.CategoriaIndustrial.OTRO,
        "tiene_planos": True,
        "representante_nombre": "Representante",
        "representante_dni": "12345678",
        "representante_cargo": "Gerente",
        "representante_email": f"rep-{cuit.replace('-', '')}@example.com",
        "representante_telefono": "2920654321",
    }
    datos.update(overrides)
    emp = Empresa.objects.create(**datos)
    if usuario is not None:
        usuario.empresa = emp
        usuario.rol_interno = CustomUser.RolInterno.TITULAR
        usuario.save(update_fields=['empresa', 'rol_interno'])
    return emp


def lote(
    nro_parcela=1,
    superficie_m2=Decimal("1000.00"),
    estado=Lote.Estado.DISPONIBLE,
    empresa=None,
    **overrides,
):
    datos = {
        "nro_parcela": nro_parcela,
        "superficie_m2": superficie_m2,
        "estado": estado,
        "empresa": empresa,
    }
    datos.update(overrides)
    return Lote.objects.create(**datos)


def payload_registro(**overrides):
    datos = {
        "razon_social": "Nueva Radicacion SRL",
        "cuit": "30-12345678-9",
        "direccion": "Ruta 1",
        "telefono": "2920123456",
        "correo_electronico": "nueva@example.com",
        "tipo_societario": Empresa.TipoSocietario.SRL,
        "nombre_fantasia": "Nueva Radicacion",
        "ingresos_brutos": "IB-123",
        "tipo_empresa": Empresa.TipoEmpresa.NUEVA,
        "objetivo_proyecto": Empresa.ObjetivoProyecto.INSTALACION_NUEVA,
        "rubro": Empresa.Rubro.SERVICIOS,
        "persona_referente": "Mauro",
        "actividad_principal": "Servicios industriales",
        "actividad_secundaria": "Logistica",
        "descripcion_actividad": "Proyecto productivo industrial",
        "emplazamiento_actual": Empresa.EmplazamientoActual.PROPIO,
        "personal_jerarquico": "1",
        "personal_administrativo": "2",
        "personal_produccion": "4",
        "personal_a_ocupar": "7",
        "materias_primas": "Insumos",
        "destino_produccion": "Patagonia",
        "necesidad_m2": Empresa.RangoNecesidadM2.DE_500_A_1000,
        "tiempo_radicacion_meses": Empresa.TiempoRadicacion.MESES_12,
        "superficie_cubierta_trabajo_m2": "120.00",
        "superficie_cubierta_deposito_m2": "80.00",
        "superficie_futura_expansion_m2": "40.00",
        "superficie_estacionamiento_m2": "30.00",
        "tiene_planos": "on",
        "energia_tension": Empresa.TensionElectrica.BAJA,
        "energia_potencia_rango": Empresa.RangoPotencia.HASTA_10,
        "consumo_estimado_agua_potable": Empresa.RangoConsumoAgua.HASTA_50,
        "consumo_estimado_agua_cruda": Empresa.RangoConsumoAgua.HASTA_50,
        "gas": "",
        "requiere_internet": "on",
        "necesidad_balanza_publica": "",
        "necesidad_comedor": "",
        "necesidad_salon_multiuso": "",
        "categoria_industrial": Empresa.CategoriaIndustrial.OTRO,
        "maneja_inflamables": "",
        "genera_residuos": "",
        "tratamiento_en_planta": "",
        "representante_nombre": "Representante Legal",
        "representante_dni": "30123456",
        "representante_cargo": "Socio gerente",
        "representante_email": "representante@example.com",
        "representante_telefono": "2920654321",
        "username": "empresa-nueva",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    datos.update(overrides)
    return datos


class TempMediaMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()


class RegistroEmpresaTests(TestCase):
    def test_registro_crea_usuario_empresa_estado_inicial_y_trazabilidad(self):
        response = self.client.post(reverse("core:registro_empresa"), payload_registro())

        self.assertRedirects(response, reverse("core:login"))
        usuario = CustomUser.objects.get(username="empresa-nueva")
        self.assertTrue(usuario.is_active)
        self.assertTrue(usuario.groups.filter(name="EMPRESA").exists())

        nueva_empresa = Empresa.objects.get(cuit="30-12345678-9")
        usuario.refresh_from_db()
        self.assertEqual(usuario.empresa, nueva_empresa)
        self.assertEqual(usuario.rol_interno, CustomUser.RolInterno.TITULAR)
        self.assertEqual(nueva_empresa.estado, Empresa.Estado.EN_EVALUACION)
        self.assertEqual(nueva_empresa.correo_electronico, "nueva@example.com")
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=nueva_empresa,
                estado_nuevo=Empresa.Estado.EN_EVALUACION,
                justificacion_resolucion__icontains="wizard de registro",
            ).exists()
        )

    def test_registro_rechaza_cuit_invalido_y_cuit_repetido(self):
        form_cuit_invalido = RegistroEmpresaWizardForm(
            data=payload_registro(cuit="123", username="otro")
        )
        self.assertFalse(form_cuit_invalido.is_valid())
        self.assertIn("cuit", form_cuit_invalido.errors)

        empresa(cuit="30-99999999-9")
        form_cuit_repetido = RegistroEmpresaWizardForm(
            data=payload_registro(cuit="30-99999999-9", username="tercero")
        )
        self.assertFalse(form_cuit_repetido.is_valid())
        self.assertIn("cuit", form_cuit_repetido.errors)


class EvaluacionSolicitudTests(TestCase):
    def setUp(self):
        self.admin = user("admin-evaluacion", "ADMIN_ENREPAVI")

    def test_admin_lista_solicitudes_y_empresa_no_puede_acceder(self):
        empresa(razon_social="Solicitud Visible", cuit="30-00000001-1")

        self.client.force_login(self.admin)
        response_admin = self.client.get(reverse("core:solicitud_list"))
        self.assertEqual(response_admin.status_code, 200)
        self.assertContains(response_admin, "Solicitud Visible")

        usuario_empresa = user("empresa-evaluacion", "EMPRESA")
        self.client.force_login(usuario_empresa)
        response_empresa = self.client.get(reverse("core:solicitud_list"))
        self.assertEqual(response_empresa.status_code, 403)

    def test_preaprobar_cambia_estado_y_registra_transicion(self):
        solicitud = empresa(cuit="30-00000002-2")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("core:solicitud_preaprobar", args=[solicitud.pk])
        )

        self.assertRedirects(response, reverse("core:solicitud_detail", args=[solicitud.pk]))
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, Empresa.Estado.PRE_APROBADO)
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=solicitud,
                estado_anterior=Empresa.Estado.EN_EVALUACION,
                estado_nuevo=Empresa.Estado.PRE_APROBADO,
                usuario=self.admin,
            ).exists()
        )

    def test_rechazar_exige_justificacion_suficiente(self):
        solicitud = empresa(cuit="30-00000003-3")
        self.client.force_login(self.admin)

        response_invalida = self.client.post(
            reverse("core:solicitud_rechazar", args=[solicitud.pk]),
            {"justificacion": "corta"},
        )
        self.assertEqual(response_invalida.status_code, 200)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, Empresa.Estado.EN_EVALUACION)

        response_valida = self.client.post(
            reverse("core:solicitud_rechazar", args=[solicitud.pk]),
            {"justificacion": "No cumple con la documentacion tecnica minima"},
        )
        self.assertRedirects(response_valida, reverse("core:solicitud_list"))
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, Empresa.Estado.RECHAZADO)
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=solicitud,
                estado_nuevo=Empresa.Estado.RECHAZADO,
                justificacion_resolucion__icontains="documentacion tecnica",
            ).exists()
        )


class AdjudicacionLoteTests(TestCase):
    def setUp(self):
        self.admin = user("admin-adjudicacion", "ADMIN_ENREPAVI")
        self.client.force_login(self.admin)

    def test_asigna_lote_disponible_y_adecuado_a_empresa_preaprobada(self):
        solicitud = empresa(
            razon_social="Proyecto Aprobado",
            cuit="30-00000004-4",
            estado=Empresa.Estado.PRE_APROBADO,
            necesidad_m2=Empresa.RangoNecesidadM2.DE_500_A_1000,
        )
        parcela = lote(nro_parcela=10, superficie_m2=Decimal("800.00"))

        response = self.client.post(
            reverse("core:adjudicacion", args=[solicitud.pk]),
            {"lote_id": parcela.pk},
        )

        self.assertRedirects(response, reverse("core:solicitud_list"))
        solicitud.refresh_from_db()
        parcela.refresh_from_db()
        self.assertEqual(solicitud.estado, Empresa.Estado.RADICADA)
        self.assertIsNotNone(solicitud.fecha_limite_obra)
        self.assertEqual(parcela.estado, Lote.Estado.EN_USO)
        self.assertEqual(parcela.empresa, solicitud)
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=solicitud,
                estado_nuevo=Empresa.Estado.RADICADA,
                justificacion_resolucion__icontains="parcela 10",
            ).exists()
        )

    def test_no_permite_elegir_lote_no_disponible_o_con_superficie_insuficiente(self):
        solicitud = empresa(
            cuit="30-00000005-5",
            estado=Empresa.Estado.PRE_APROBADO,
            necesidad_m2=Empresa.RangoNecesidadM2.DE_500_A_1000,
        )
        lote_chico = lote(nro_parcela=11, superficie_m2=Decimal("250.00"))
        lote_ocupado = lote(
            nro_parcela=12,
            superficie_m2=Decimal("1000.00"),
            estado=Lote.Estado.EN_USO,
            empresa=empresa(
                razon_social="Ocupante",
                cuit="30-00000006-6",
                estado=Empresa.Estado.RADICADA,
            ),
        )

        response_chico = self.client.post(
            reverse("core:adjudicacion", args=[solicitud.pk]),
            {"lote_id": lote_chico.pk},
        )
        response_ocupado = self.client.post(
            reverse("core:adjudicacion", args=[solicitud.pk]),
            {"lote_id": lote_ocupado.pk},
        )

        self.assertEqual(response_chico.status_code, 404)
        self.assertEqual(response_ocupado.status_code, 404)
        solicitud.refresh_from_db()
        lote_chico.refresh_from_db()
        lote_ocupado.refresh_from_db()
        self.assertEqual(solicitud.estado, Empresa.Estado.PRE_APROBADO)
        self.assertEqual(lote_chico.estado, Lote.Estado.DISPONIBLE)
        self.assertEqual(lote_ocupado.empresa.cuit, "30-00000006-6")

    def test_detecta_incompatibilidad_por_rubro_entre_lotes_colindantes(self):
        alimenticia = empresa(
            razon_social="Alimentos SA",
            cuit="30-00000007-7",
            estado=Empresa.Estado.RADICADA,
            categoria_industrial=Empresa.CategoriaIndustrial.ALIMENTICIA,
        )
        lote_alimentos = lote(
            nro_parcela=20,
            empresa=alimenticia,
            estado=Lote.Estado.EN_USO,
        )
        lote_quimico = lote(nro_parcela=21)
        lote_quimico.lotes_colindantes.add(lote_alimentos)
        proyecto_quimico = empresa(
            razon_social="Quimica SA",
            cuit="30-00000008-8",
            categoria_industrial=Empresa.CategoriaIndustrial.QUIMICA,
        )

        incompatibilidades = evaluar_incompatibilidades_lote(proyecto_quimico, lote_quimico)

        self.assertEqual(len(incompatibilidades), 1)
        self.assertIn("actividad química junto a actividad alimenticia", incompatibilidades[0]["motivo"])


class AvancesProrrogasYBajaTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.admin = user("admin-obras", "ADMIN_ENREPAVI")
        self.usuario_empresa = user("empresa-obras", "EMPRESA")
        self.empresa = empresa(
            razon_social="Obras SRL",
            cuit="30-00000009-9",
            estado=Empresa.Estado.RADICADA,
            usuario=self.usuario_empresa,
            fecha_limite_obra=date(2026, 12, 31),
        )

    def test_empresa_registra_avance_con_pdf_y_queda_pendiente_de_validacion(self):
        self.client.force_login(self.usuario_empresa)
        archivo = SimpleUploadedFile(
            "certificado.pdf", b"%PDF-1.4 test", content_type="application/pdf"
        )

        response = self.client.post(
            reverse("core:avance_create"),
            {"porcentaje_declarado": "35.50", "certificado_pdf": archivo},
        )

        self.assertRedirects(response, reverse("core:mi_solicitud"))
        avance = AvanceConstructivo.objects.get(empresa=self.empresa)
        self.assertEqual(avance.porcentaje_declarado, Decimal("35.50"))
        self.assertFalse(avance.validado_admin)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.estado, Empresa.Estado.EN_CONSTRUCCION)
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=self.empresa,
                estado_nuevo=Empresa.Estado.EN_CONSTRUCCION,
                justificacion_resolucion__icontains="Primer avance constructivo",
            ).exists()
        )

    def test_avance_rechaza_archivo_que_no_es_pdf(self):
        self.client.force_login(self.usuario_empresa)
        archivo = SimpleUploadedFile(
            "certificado.txt", b"texto plano", content_type="text/plain"
        )

        response = self.client.post(
            reverse("core:avance_create"),
            {"porcentaje_declarado": "10.00", "certificado_pdf": archivo},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AvanceConstructivo.objects.filter(empresa=self.empresa).exists())
        self.assertContains(response, "Solo se aceptan archivos PDF")

    def test_admin_valida_avance_pendiente(self):
        avance = AvanceConstructivo.objects.create(
            empresa=self.empresa,
            porcentaje_declarado=Decimal("20.00"),
            certificado_pdf=SimpleUploadedFile(
                "avance.pdf", b"%PDF-1.4", content_type="application/pdf"
            ),
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("core:avance_validar", args=[avance.pk]))

        self.assertRedirects(response, reverse("core:avances_pendientes"))
        avance.refresh_from_db()
        self.assertTrue(avance.validado_admin)

    def test_empresa_solicita_prorroga_y_admin_aprueba_actualizando_fecha_limite(self):
        self.empresa.estado = Empresa.Estado.EN_CONSTRUCCION
        self.empresa.fecha_limite_obra = date(2026, 6, 30)
        self.empresa.save(update_fields=["estado", "fecha_limite_obra"])

        self.client.force_login(self.usuario_empresa)
        response_creacion = self.client.post(
            reverse("core:prorroga_create"),
            {
                "meses_solicitados": "6",
                "justificacion": "Demora por entrega tardia de materiales importados",
            },
        )
        self.assertRedirects(response_creacion, reverse("core:mi_solicitud"))
        solicitud = SolicitudProrroga.objects.get(empresa=self.empresa)
        self.assertEqual(solicitud.estado, SolicitudProrroga.EstadoProrroga.PENDIENTE)

        self.client.force_login(self.admin)
        response_aprobacion = self.client.post(
            reverse("core:prorroga_aprobar", args=[solicitud.pk]),
            {"respuesta": "Aprobada por retraso documentado"},
        )

        self.assertRedirects(response_aprobacion, reverse("core:prorrogas_pendientes"))
        solicitud.refresh_from_db()
        self.empresa.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudProrroga.EstadoProrroga.APROBADA)
        self.assertEqual(self.empresa.fecha_limite_obra, date(2026, 6, 30) + relativedelta(months=6))
        self.assertEqual(solicitud.resuelta_por, self.admin)

    def test_baja_de_empresa_registra_motivo_y_libera_lote(self):
        parcela = lote(
            nro_parcela=30,
            estado=Lote.Estado.EN_USO,
            empresa=self.empresa,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("core:baja_empresa", args=[self.empresa.pk]),
            {"justificacion": "Finalizacion anticipada del proyecto por decision formal"},
        )

        self.assertRedirects(response, reverse("core:solicitud_list"))
        self.empresa.refresh_from_db()
        parcela.refresh_from_db()
        self.assertEqual(self.empresa.estado, Empresa.Estado.HISTORICO_BAJA)
        self.assertEqual(parcela.estado, Lote.Estado.DISPONIBLE)
        self.assertIsNone(parcela.empresa)
        self.assertTrue(
            TransicionEstado.objects.filter(
                empresa=self.empresa,
                estado_nuevo=Empresa.Estado.HISTORICO_BAJA,
                justificacion_resolucion__icontains="Finalizacion anticipada",
            ).exists()
        )


class ConsumosConsultaDashboardYReportesTests(TestCase):
    def setUp(self):
        self.admin = user("admin-reportes", "ADMIN_ENREPAVI")
        self.proveedor_agua = user("proveedor-agua", "PROVEEDOR_AGUA")
        self.proveedor_luz = user("proveedor-luz", "PROVEEDOR_LUZ")
        self.usuario_empresa = user("empresa-consumos", "EMPRESA")
        self.empresa = empresa(
            razon_social="Consumos SRL",
            cuit="30-00000010-0",
            estado=Empresa.Estado.RADICADA,
            usuario=self.usuario_empresa,
            actividad_principal="Metalurgica",
        )

    def test_proveedor_registra_consumo_y_bloquea_periodo_duplicado_actual(self):
        self.client.force_login(self.proveedor_agua)
        response_agua = self.client.post(
            reverse("core:consumo_create"),
            {
                "empresa": self.empresa.pk,
                "periodo_mes": "5",
                "periodo_anio": "2026",
                "consumo_agua_potable_m3": "12.34",
                "consumo_agua_cruda_m3": "2.00",
            },
        )
        self.assertRedirects(response_agua, reverse("core:consumo_list"))
        consumo = ConsumoServicio.objects.get(empresa=self.empresa, periodo_mes=5, periodo_anio=2026)
        self.assertEqual(consumo.consumo_agua_potable_m3, Decimal("12.34"))
        self.assertEqual(consumo.cargado_por, self.proveedor_agua)

        response_duplicado = self.client.post(
            reverse("core:consumo_create"),
            {
                "empresa": self.empresa.pk,
                "periodo_mes": "5",
                "periodo_anio": "2026",
                "consumo_agua_potable_m3": "99.99",
                "consumo_agua_cruda_m3": "3.00",
            },
        )
        self.assertEqual(response_duplicado.status_code, 200)
        self.assertEqual(ConsumoServicio.objects.count(), 1)
        consumo.refresh_from_db()
        self.assertEqual(consumo.consumo_agua_potable_m3, Decimal("12.34"))
        self.assertContains(response_duplicado, "Ya hay un consumo de agua")

        self.client.force_login(self.proveedor_luz)
        response_luz = self.client.post(
            reverse("core:consumo_create"),
            {
                "empresa": self.empresa.pk,
                "periodo_mes": "5",
                "periodo_anio": "2026",
                "consumo_luz_kwh": "88.50",
            },
        )
        # Limitacion actual: la UniqueConstraint del modelo es por empresa/mes/anio,
        # por lo que tambien impide agregar otro servicio al mismo periodo.
        self.assertEqual(response_luz.status_code, 200)
        self.assertEqual(ConsumoServicio.objects.count(), 1)
        consumo.refresh_from_db()
        self.assertEqual(consumo.consumo_agua_potable_m3, Decimal("12.34"))
        self.assertIsNone(consumo.consumo_luz_kwh)

    def test_inicio_empresa_muestra_accesos_separados(self):
        self.client.force_login(self.usuario_empresa)
        response = self.client.get(reverse("core:inicio"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mi solicitud")
        self.assertContains(response, "Mi equipo")
        self.assertContains(response, "Mis consumos")
        self.assertContains(response, reverse("core:mi_solicitud"))
        self.assertContains(response, reverse("core:empresa_usuarios"))
        self.assertContains(response, reverse("core:mis_consumos"))

    def test_mi_solicitud_no_muestra_consumos_ni_equipo(self):
        self.client.force_login(self.usuario_empresa)
        response = self.client.get(reverse("core:mi_solicitud"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Consumos SRL")
        self.assertNotContains(response, "Consumos de servicios")
        self.assertNotContains(response, "Gestión del equipo")

    def test_empresa_consulta_solo_sus_consumos_propios(self):
        otra_usuario = user("otra-empresa", "EMPRESA")
        otra_empresa = empresa(
            razon_social="Otra SRL",
            cuit="30-00000011-1",
            estado=Empresa.Estado.RADICADA,
            usuario=otra_usuario,
        )
        ConsumoServicio.objects.create(
            empresa=self.empresa,
            periodo_mes=4,
            periodo_anio=2026,
            consumo_agua_potable_m3=Decimal("12.34"),
        )
        ConsumoServicio.objects.create(
            empresa=otra_empresa,
            periodo_mes=4,
            periodo_anio=2026,
            consumo_agua_potable_m3=Decimal("99.99"),
        )

        self.client.force_login(self.usuario_empresa)
        response = self.client.get(reverse("core:mis_consumos"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Consumos SRL")
        self.assertContains(response, "12,34")
        self.assertNotContains(response, "Otra SRL")
        self.assertNotContains(response, "99,99")

    def test_organismo_publico_accede_dashboard_de_consulta_y_empresa_no(self):
        organismo = user("organismo", "ORGANISMO_PUBLICO")
        lote(nro_parcela=40, estado=Lote.Estado.EN_USO, empresa=self.empresa)
        lote(nro_parcela=41, estado=Lote.Estado.DISPONIBLE)

        self.client.force_login(organismo)
        response_organismo = self.client.get(reverse("core:consulta_parque"))
        self.assertEqual(response_organismo.status_code, 200)
        self.assertContains(response_organismo, "Consumos SRL")
        self.assertEqual(response_organismo.context["lotes_en_uso"], 1)
        self.assertEqual(response_organismo.context["lotes_disponibles"], 1)

        self.client.force_login(self.usuario_empresa)
        response_empresa = self.client.get(reverse("core:consulta_parque"))
        self.assertEqual(response_empresa.status_code, 403)

    def test_reportes_admin_generan_respuestas_pdf_con_datos_actuales(self):
        lote(nro_parcela=50, estado=Lote.Estado.EN_USO, empresa=self.empresa)
        ConsumoServicio.objects.create(
            empresa=self.empresa,
            periodo_mes=5,
            periodo_anio=2026,
            consumo_agua_potable_m3=Decimal("12.34"),
        )

        self.client.force_login(self.admin)
        for url_name in (
            "reporte_ocupacion",
            "reporte_empresas",
            "reporte_consumos",
        ):
            response = self.client.get(reverse(f"core:{url_name}"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response.content.startswith(b"%PDF"))


class AdminGestionUsuariosContactarTests(TestCase):
    def setUp(self):
        self.admin = user("admin-contactar", "ADMIN_ENREPAVI")
        self.admin.email = "admin@example.com"
        self.admin.save(update_fields=["email"])
        self.usuario = user("usuario-contacto", "EMPRESA")
        self.usuario.email = "usuario@example.com"
        self.usuario.first_name = "Usuario"
        self.usuario.last_name = "Contacto"
        self.usuario.save(update_fields=["email", "first_name", "last_name"])
        self.solicitud = SolicitudAcceso.objects.create(
            tipo=SolicitudAcceso.Tipo.PROVEEDOR,
            nombre_apellido="Proveedor Pendiente",
            cargo="Representante",
            organizacion="Aguas Test",
            telefono="2920123456",
            email_institucional="proveedor@example.com",
            tipo_acceso="AGUA",
            motivo="Necesito cargar consumos de agua.",
        )

    def test_gestion_usuarios_muestra_botones_contactar(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:admin_gestion_usuarios"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'{reverse("core:admin_ticket_create")}?solicitud_acceso={self.solicitud.pk}',
        )
        self.assertContains(
            response,
            f'{reverse("core:admin_ticket_create")}?user={self.usuario.pk}',
        )
        self.assertContains(response, "Contactar")

    @patch("core.views.notificar_ticket_mensaje")
    def test_admin_crea_ticket_interno_para_usuario(self, mock_notificar):
        self.client.force_login(self.admin)
        url = f'{reverse("core:admin_ticket_create")}?user={self.usuario.pk}'

        response = self.client.post(url, {
            "destinatario": f"user:{self.usuario.pk}",
            "categoria": Ticket.Categoria.ADMINISTRATIVA,
            "asunto": "Solicitud de documentación adicional",
            "mensaje_inicial": "Por favor adjuntá la documentación faltante.",
        })

        ticket = Ticket.objects.get(asunto="Solicitud de documentación adicional")
        self.assertRedirects(response, reverse("core:admin_ticket_detail", args=[ticket.pk]))
        self.assertEqual(ticket.creador, self.usuario)
        mensaje = ticket.mensajes.get()
        self.assertEqual(mensaje.autor, self.admin)
        self.assertIn("documentación faltante", mensaje.contenido)
        mock_notificar.assert_called_once_with(ticket, mensaje)

    @patch("core.views.notificar_ticket_mensaje")
    def test_admin_crea_ticket_externo_para_solicitud_de_acceso(self, mock_notificar):
        self.client.force_login(self.admin)
        url = f'{reverse("core:admin_ticket_create")}?solicitud_acceso={self.solicitud.pk}'

        response = self.client.post(url, {
            "destinatario": f"solicitud_acceso:{self.solicitud.pk}",
            "categoria": Ticket.Categoria.ADMINISTRATIVA,
            "asunto": "Documentación adicional - Aguas Test",
            "mensaje_inicial": "Necesitamos una nota institucional actualizada.",
        })

        ticket = Ticket.objects.get(asunto="Documentación adicional - Aguas Test")
        self.assertRedirects(response, reverse("core:admin_ticket_detail", args=[ticket.pk]))
        self.assertIsNone(ticket.creador)
        self.assertEqual(ticket.nombre_contacto, "Proveedor Pendiente")
        self.assertEqual(ticket.email_contacto, "proveedor@example.com")
        mensaje = ticket.mensajes.get()
        self.assertEqual(mensaje.autor, self.admin)
        mock_notificar.assert_called_once_with(ticket, mensaje)

    def test_usuario_no_admin_no_puede_contactar_desde_panel(self):
        self.client.force_login(self.usuario)
        response = self.client.get(
            f'{reverse("core:admin_ticket_create")}?user={self.usuario.pk}'
        )

        self.assertEqual(response.status_code, 403)


class RBACServicesTests(TestCase):
    """Tests unitarios para los servicios RBAC de equipo de empresa."""

    def setUp(self):
        self.emp = empresa('RBAC SA', '30-99887766-5', Empresa.Estado.RADICADA)
        self.titular = user('titular_rbac_test', 'EMPRESA')
        self.titular.empresa = self.emp
        self.titular.rol_interno = CustomUser.RolInterno.TITULAR
        self.titular.save(update_fields=['empresa', 'rol_interno'])
        self.libre = user('libre_rbac_test', 'EMPRESA')

    def test_invitar_vincula_como_estandar(self):
        invitar_usuario(self.emp, self.titular, self.libre)
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.empresa, self.emp)
        self.assertEqual(self.libre.rol_interno, CustomUser.RolInterno.ESTANDAR)

    def test_invitar_ya_vinculado_lanza_excepcion(self):
        invitar_usuario(self.emp, self.titular, self.libre)
        with self.assertRaises(UsuarioYaVinculadoError):
            invitar_usuario(self.emp, self.titular, self.libre)

    def test_transferir_cambia_ambos_roles(self):
        invitar_usuario(self.emp, self.titular, self.libre)
        transferir_titularidad(self.emp, self.titular, self.libre)
        self.titular.refresh_from_db()
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.rol_interno, CustomUser.RolInterno.TITULAR)
        self.assertEqual(self.titular.rol_interno, CustomUser.RolInterno.ESTANDAR)

    def test_remover_desvincula_usuario(self):
        invitar_usuario(self.emp, self.titular, self.libre)
        remover_miembro(self.emp, self.titular, self.libre)
        self.libre.refresh_from_db()
        self.assertIsNone(self.libre.empresa)
        self.assertIsNone(self.libre.rol_interno)

    def test_remover_titular_lanza_excepcion(self):
        with self.assertRaises(NoSePuedeDegradarTitularError):
            remover_miembro(self.emp, self.titular, self.titular)
