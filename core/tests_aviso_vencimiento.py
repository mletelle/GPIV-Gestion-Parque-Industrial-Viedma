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
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.core.management import call_command
from django.utils import timezone

from core.models import Empresa, AvisoVencimiento
from core.services import enviar_aviso_vencimiento


def _crear_empresa(razon_social, cuit, estado, fecha_limite_obra=None,
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
    def test_envio_urgente_crea_aviso_y_actualiza_empresa(self, mock_email):
        """empresa con 5 dias → aviso urgente creado, email enviado."""
        empresa = _crear_empresa(
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

        # verificar que se actualizo ultimo_aviso_vencimiento
        empresa.refresh_from_db()
        self.assertEqual(empresa.ultimo_aviso_vencimiento, self.hoy)

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-email-id'})
    def test_envio_proximo_crea_aviso(self, mock_email):
        """empresa con 20 dias → aviso proximo creado."""
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        _crear_empresa(
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
        _crear_empresa(
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
        """empresa con aviso reciente (<7 dias) no recibe duplicado."""
        _crear_empresa(
            'NoDup SA', '20-88888888-8',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=5),
            ultimo_aviso=self.hoy - timedelta(days=3),  # hace 3 dias
        )

        out = StringIO()
        call_command('notificar_vencimientos', stdout=out)

        self.assertEqual(AvisoVencimiento.objects.count(), 0)
        mock_email.assert_not_called()
        self.assertIn('Avisos urgentes: 0', out.getvalue())

    @patch(MOCK_RESEND_PATH, return_value={'id': 'mock-id'})
    def test_empresa_radicada_no_recibe(self, mock_email):
        """empresa en estado Radicada no recibe aviso aunque tenga fecha."""
        _crear_empresa(
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
        _crear_empresa(
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
        _crear_empresa(
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
        _crear_empresa(
            'Urgente1', '20-13131313-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=3),
        )
        _crear_empresa(
            'Proximo1', '20-14141414-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.hoy + timedelta(days=15),
        )
        _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
