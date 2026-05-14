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
from datetime import timedelta
from io import StringIO
from unittest.mock import patch, call

from django.test import TestCase, override_settings
from django.core.management import call_command
from django.utils import timezone

from core.models import (
    Empresa, SolicitudProrroga, CaducidadRegistro, TransicionEstado,
)
from core.services import (
    ejecutar_caducidad, notificar_admin_caducidades, tiene_prorroga_vigente,
)


def _crear_empresa(razon_social, cuit, estado, fecha_limite_obra=None):
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
            'SinProrr', '20-77777777-7',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        self.assertFalse(tiene_prorroga_vigente(empresa))

    def test_prorroga_aprobada_retorna_true(self):
        empresa = _crear_empresa(
            'Aprobada', '20-88888888-8',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.APROBADA)
        self.assertTrue(tiene_prorroga_vigente(empresa))

    def test_prorroga_pendiente_retorna_true(self):
        empresa = _crear_empresa(
            'Pendiente', '20-99999999-9',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(empresa, SolicitudProrroga.EstadoProrroga.PENDIENTE)
        self.assertTrue(tiene_prorroga_vigente(empresa))

    def test_prorroga_rechazada_retorna_false(self):
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
        _crear_empresa(
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
        _crear_empresa(
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
        empresa = _crear_empresa(
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
        e1 = _crear_empresa(
            'Caduca1', '20-19191919-1',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        # no debe caducar (prorroga aprobada)
        e2 = _crear_empresa(
            'NoCaduca', '20-20202020-2',
            Empresa.Estado.EN_CONSTRUCCION,
            fecha_limite_obra=self.ayer,
        )
        _crear_prorroga(e2, SolicitudProrroga.EstadoProrroga.APROBADA)
        # debe caducar (prorroga rechazada)
        e3 = _crear_empresa(
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
        empresa = _crear_empresa(
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
        empresa = _crear_empresa(
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
