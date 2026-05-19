"""
Tests de auditoría — Issue #45
Valida que django-simple-history registra correctamente creaciones,
ediciones, eliminaciones y soft-deletes en todas las entidades críticas,
capturando usuario, timestamp y detalle del cambio.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from simple_history.models import HistoricalRecords

from core.models import (
    Empresa, Lote, TransicionEstado, AvanceConstructivo,
    SolicitudProrroga, ConsumoServicio, Ticket, MensajeTicket,
    ActivoInventario, SolicitudAcceso, AvisoVencimiento,
    CaducidadRegistro,
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
