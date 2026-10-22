#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las tres superficies que ejecutaban sin puerta ahora DENIEGAN por defecto.

E1  `read-excel` lanzaba PowerShell -> Excel COM con un solo POST, mientras su
    hermano `apply-excel` exigía `confirmed:true`. Ahora exige lo mismo y sin
    confirmación no se ejecuta nada.
E2  `gang-mount` abría 3 servidores HTTP locales con endpoints mutantes sin
    ninguna puerta. Ahora pasa por la puerta `connectors` del contrato
    (`action_kind: open_connector`) y exige aprobación en dos pasos con
    one_shot/scope_hash/TTL, igual que el sandbox.
E3  guardar la clave con `auto_discover` ejecutaba `discover-models` pasándose
    `confirmed:true` a sí mismo. Ahora deja el consentimiento PENDIENTE y no
    llama al proveedor hasta que una persona confirme ese consentimiento exacto.

Contra el código anterior este archivo falla (ver N8_EXPOSICIONES.md, secciones rojas).
"""
import unittest
from unittest.mock import patch

from engine import bridge
from engine import policy_engine as platform_policy


class StoreNulo:
    def load(self):
        return {}

    def delete(self):
        pass

    def save(self, value):
        raise RuntimeError('Fixture: almacenamiento persistente no disponible.')


class ProveedorFalso:
    """Fixture offline: no abre red, solo registra llamadas."""

    def __init__(self):
        self.calls = []

    def discover_models(self, provider, api_key):
        self.calls.append(('models', provider))
        return {'models': [{'id': 'fixture-model', 'source': 'live_api', 'availability_verified': True}],
                'source': 'live_api', 'status': 'fixture', 'verified_at': 'FIXTURE'}


class ServidorFalso:
    """Sustituye al servidor HTTP real: registra que se intentó montar."""

    creados = []

    def __init__(self, nodo):
        self.nodo = nodo
        ServidorFalso.creados.append(nodo.id)
        self.puerto = 20000 + len(ServidorFalso.creados)

    def url(self):
        return 'http://127.0.0.1:%d' % self.puerto

    def stop(self):
        pass


def estado(provider=None, sandbox_clock=None):
    st = bridge.BridgeState(credential_store=StoreNulo(), provider_module=provider,
                            sandbox_clock=sandbox_clock)
    return st


class Exposicion1ReadExcel(unittest.TestCase):
    """E1: leer por COM exige confirmación; sin ella no se lanza nada."""

    def setUp(self):
        self.state = estado()

    def test_sin_confirmacion_no_ejecuta_y_devuelve_error_claro(self):
        with patch.object(bridge, 'excel_call', side_effect=AssertionError('no debe llamarse a Excel')) as llamada:
            with self.assertRaises(bridge.BridgeError) as caught:
                self.state.execute('read-excel', {'workbook': 'C:/fixture/libro.xlsx'})
            llamada.assert_not_called()
        mensaje = str(caught.exception)
        self.assertIn('Confirm', mensaje)
        self.assertIn('no se ejecut', mensaje.lower())

    def test_confirmacion_explicita_si_lee(self):
        resultado = {'config': dict(bridge.DEFAULT_CONFIG), 'model_overrides': {}}
        with patch.object(bridge, 'excel_call', return_value=resultado) as llamada:
            self.state.execute('read-excel', {'workbook': 'C:/fixture/libro.xlsx', 'confirmed': True})
            llamada.assert_called_once_with('Read', 'C:/fixture/libro.xlsx')

    def test_import_workbook_sigue_sin_puerta_porque_no_usa_com(self):
        resultado = {'config': dict(bridge.DEFAULT_CONFIG), 'model_overrides': {}}
        with patch.object(bridge, 'read_xlsx_snapshot', return_value=resultado) as snapshot:
            self.state.execute('import-workbook', {'workbook': 'C:/fixture/libro.xlsx'})
            snapshot.assert_called_once()


class Exposicion2GangMount(unittest.TestCase):
    """E2: montar abre listeners locales; exige la puerta `connectors` en dos pasos."""

    def setUp(self):
        ServidorFalso.creados = []
        self.patcher = patch.object(bridge.gang_services, 'ServidorGang', ServidorFalso)
        self.patcher.start()
        self.state = estado()

    def tearDown(self):
        self.patcher.stop()

    def test_sin_confirmacion_no_abre_ningun_servidor(self):
        vista = self.state.execute('gang-mount', {})
        self.assertIsNone(self.state.gang_servers)
        self.assertEqual(ServidorFalso.creados, [], 'no debe crearse ningún servidor')
        pendiente = vista['gang_mount_consent']
        self.assertIsNotNone(pendiente, 'la solicitud debe quedar visible y pendiente')
        self.assertEqual(pendiente['kind'], 'gang_mount')
        self.assertEqual(pendiente['gate'], 'connectors')
        self.assertEqual(pendiente['policy_decision'], platform_policy.DECISION_REQUIRE)
        self.assertEqual(len(pendiente['scope_hash']), 64)
        self.assertEqual(len(pendiente['payload_sha256']), 64)
        self.assertIs(pendiente['one_shot'], True)
        self.assertEqual(pendiente['approval_ttl_seconds'], bridge.SANDBOX_APPROVAL_TTL_SECONDS)
        self.assertEqual(pendiente['service_ids'], sorted(bridge._gang_registry_module.TARGETS))
        self.assertTrue(pendiente['approval_id'])

    def test_confirmacion_con_consentimiento_equivocado_no_monta(self):
        self.state.execute('gang-mount', {})
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('gang-mount', {'confirmed': True, 'consent_id': 'otro',
                                              'payload_sha256': 'f' * 64})
        self.assertIn('scope_mismatch', str(caught.exception))
        self.assertIsNone(self.state.gang_servers)
        self.assertEqual(ServidorFalso.creados, [])
        self.assertIsNotNone(self.state.gang_mount_consent, 'el pendiente no se consume al fallar')

    def test_confirmacion_correcta_monta_los_tres(self):
        self.state.execute('gang-mount', {})
        pendiente = self.state.public()['gang_mount_consent']
        self.state.execute('gang-mount', {'confirmed': True, 'consent_id': pendiente['approval_id'],
                                          'payload_sha256': pendiente['payload_sha256']})
        self.assertEqual(len(self.state.gang_servers), 3)
        self.assertEqual(sorted(ServidorFalso.creados), sorted(bridge._gang_registry_module.TARGETS))
        self.assertIsNone(self.state.gang_mount_consent, 'la aprobación es de un solo uso')
        with self.assertRaises(bridge.BridgeError):
            self.state.execute('gang-mount', {})          # ya montados

    def test_confirmacion_repetida_no_reutiliza_la_aprobacion(self):
        self.state.execute('gang-mount', {})
        pendiente = self.state.public()['gang_mount_consent']
        datos = {'confirmed': True, 'consent_id': pendiente['approval_id'],
                 'payload_sha256': pendiente['payload_sha256']}
        self.state.execute('gang-mount', datos)
        self.state.execute('gang-unmount', {})
        # tras desmontar, la misma aprobación ya consumida no vuelve a montar
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('gang-mount', datos)
        self.assertIn('No hay un consentimiento', str(caught.exception))
        self.assertIsNone(self.state.gang_servers)

    def test_el_pendiente_caduca(self):
        reloj = {'t': 1000.0}
        self.state = estado(sandbox_clock=lambda: reloj['t'])
        self.state.execute('gang-mount', {})
        pendiente = self.state.public()['gang_mount_consent']
        reloj['t'] += bridge.SANDBOX_APPROVAL_TTL_SECONDS + 1
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('gang-mount', {'confirmed': True, 'consent_id': pendiente['approval_id'],
                                              'payload_sha256': pendiente['payload_sha256']})
        self.assertIn('approval_expired', str(caught.exception))
        self.assertEqual(ServidorFalso.creados, [])

    def test_politica_que_deniega_connectors_cierra_antes_de_pedir_aprobacion(self):
        politica = platform_policy.default_policy(overrides={'gate_defaults': dict(
            {puerta: platform_policy.GATE_DEFAULT_OUTCOME for puerta in platform_policy.GATES},
            connectors=platform_policy.DECISION_DENY)})
        self.state = bridge.BridgeState(credential_store=StoreNulo(), sandbox_policy=politica)
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('gang-mount', {})
        self.assertIn('deny', str(caught.exception))
        self.assertIsNone(self.state.gang_mount_consent)
        self.assertEqual(ServidorFalso.creados, [])


class Exposicion3AutoDescubrimiento(unittest.TestCase):
    """E3: auto_discover deja el consentimiento pendiente; no se auto-firma."""

    def setUp(self):
        self.provider = ProveedorFalso()
        self.state = estado(provider=self.provider)

    def _guardar_clave(self, auto=True):
        self.state.execute('credentials', {'provider': 'deepseek-official', 'api_key': 'fixture-key',
                                           'auto_discover': auto})

    def test_auto_discover_no_llama_al_proveedor_y_deja_pendiente_visible(self):
        self._guardar_clave(auto=True)
        self.assertNotIn(('models', 'deepseek'), self.provider.calls,
                         'guardar la clave no debe disparar ninguna llamada al proveedor')
        pendiente = self.state.public()['pending_consent']
        self.assertIsNotNone(pendiente, 'el consentimiento debe quedar pendiente y visible')
        self.assertEqual(pendiente['kind'], 'discover_models')
        self.assertTrue(pendiente['approval_id'])
        self.assertEqual(len(pendiente['payload_sha256']), 64)
        self.assertIs(pendiente['one_shot'], True)

    def test_pendiente_sin_ids_no_ejecuta(self):
        self._guardar_clave(auto=True)
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('discover-models', {'confirmed': True})
        self.assertIn('scope_mismatch', str(caught.exception))
        self.assertEqual(self.provider.calls, [])
        self.assertIsNotNone(self.state.pending_consent, 'el pendiente no se consume al fallar')

    def test_pendiente_con_ids_correctos_ejecuta_una_sola_vez(self):
        self._guardar_clave(auto=True)
        pendiente = self.state.public()['pending_consent']
        self.state.execute('discover-models', {'confirmed': True, 'consent_id': pendiente['approval_id'],
                                               'payload_sha256': pendiente['payload_sha256']})
        self.assertEqual(self.provider.calls, [('models', 'deepseek')])
        self.assertIsNone(self.state.pending_consent, 'el consentimiento se consume antes de la I/O')

    def test_pendiente_caducado_no_ejecuta(self):
        reloj = {'t': 5000.0}
        self.state = estado(provider=self.provider, sandbox_clock=lambda: reloj['t'])
        self._guardar_clave(auto=True)
        pendiente = self.state.public()['pending_consent']
        reloj['t'] += bridge.SANDBOX_APPROVAL_TTL_SECONDS + 1
        with self.assertRaises(bridge.BridgeError) as caught:
            self.state.execute('discover-models', {'confirmed': True, 'consent_id': pendiente['approval_id'],
                                                   'payload_sha256': pendiente['payload_sha256']})
        self.assertIn('approval_expired', str(caught.exception))
        self.assertEqual(self.provider.calls, [])

    def test_boton_manual_sin_pendiente_sigue_funcionando(self):
        self._guardar_clave(auto=False)
        self.assertIsNone(self.state.public()['pending_consent'])
        self.state.execute('discover-models', {'confirmed': True})
        self.assertEqual(self.provider.calls, [('models', 'deepseek')])

    def test_discover_sin_confirmacion_sigue_negando(self):
        self._guardar_clave(auto=False)
        with self.assertRaises(bridge.BridgeError):
            self.state.execute('discover-models', {})
        self.assertEqual(self.provider.calls, [])


if __name__ == '__main__':
    unittest.main()
