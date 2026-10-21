#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion del port P1 — engine/sandbox_executor.py.

Transcribe como casos del destino los vectores de docs/rea/chatdev_vectors.json que el
cuaderno REA (docs/rea/chatdev_notebook.md) asigna al ejecutor PythonNodeExecutor
(OpenBMB/ChatDev@a2ea4a2), reescritos contra las puertas de engine/policy_engine.py:

  * gate / gate_antes_de_fs (I1/I2): sin aprobacion -> excepcion con el NOMBRE de la
    puerta y cero mutacion de disco, cero subprocess (vectores
    python_node_env_no_puede_habilitar, processor_deshabilitado_no_muta_fs,
    optin_rechazado_valores_invalidos);
  * happy_path: con aprobacion declarativa one_shot valida -> ejecuta y ENTREGA al
    canal (vector python_node_ejecuta_codigo_inofensivo + cierre P1);
  * bordes del cuaderno §4: timeout vencido (exit_code del proceso + timed_out
    distinguible), codigo con error (marcador estable), salida enorme (acotada + kill,
    mejora consciente sobre el fuente), ruta que escapa (I4/I7 componente-unico).

El aprobador es un FALSO en memoria: ningun test pide interaccion humana.

Vectores NO PORTABLES (declarados con razon, no omitidos en silencio):

  * optin por env var MAC_ALLOW_UNSAFE_CODE_EXECUTION y sus vectores uv/mcp/workflow
    (uv_entrypoints_no_sobreescriben_politica, mcp_local_env_no_habilita,
    workflow_subido_no_puede_habilitar_ejecucion) — el interruptor del fuente era una
    variable de entorno del servidor; el destino REESCRIBE el gate como la puerta
    'write' del policy_engine (accion write_file). Nada del hijo puede tocarla.
  * isla attachments/ y sus alias de caso (I5) — el workspace de P1 no tiene store de
    attachments; confinamiento por componente + parents post-resolve si se porta.
  * HTTP 403 / SSE event:error (workflow_subido...) — no hay capa HTTP en el engine.
  * cleanup preservando attachments renombrado — el workspace es fresco por corrida
    (decision declarada del port), no hay cleanup destructivo pre-spawn.

CLI:  python -m unittest tests_sandbox_executor -v
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import policy_engine as pe
from engine import sandbox_executor as sx
from engine import team_channel as tc

# Roster tipo cordis (mismas convenciones que tests_team_channel.py): ana asigna,
# coder ejecuta, bob es un tercer destinatario explicito.
MIEMBROS = [
    {'member_id': 'id-ceo', 'name': 'ceo', 'role': 'CEO', 'reports_to': None},
    {'member_id': 'id-ana', 'name': 'ana', 'role': 'Investigacion', 'reports_to': 'id-ceo'},
    {'member_id': 'id-bob', 'name': 'bob', 'role': 'Revision', 'reports_to': 'id-ceo'},
    {'member_id': 'id-coder', 'name': 'coder', 'role': 'Code', 'reports_to': 'id-ana'},
]


def registro_aprobacion(gate, scope_hash):
    """Registro declarativo one_shot del contrato v1 (policy_engine.APPROVAL_FIELDS)."""
    return {'gate': gate, 'approver_role': 'operador-test',
            'approved_at': '2026-01-01T00:00:00Z',
            'scope_hash': scope_hash, 'one_shot': True}


class AprobadorEnMemoria:
    """Falso aprobador: consulta una vez por run y responde segun su modo.

    modos: None (aprueba con registro valido), 'rechazar', 'otra_puerta',
    'otro_alcance', 'autenticacion' (registro con reclamo de token: el policy_engine
    lo DENIEGA por D-R0-5, y el ejecutor debe bloquear, no ejecutar).
    """

    def __init__(self, modo=None):
        self.modo = modo
        self.consultas = []

    def __call__(self, gate, action, expected_scope_hash, decision):
        self.consultas.append({'gate': gate, 'scope_hash': expected_scope_hash})
        if self.modo == 'rechazar':
            return None
        if self.modo == 'otra_puerta':
            return registro_aprobacion('deploy', expected_scope_hash)
        if self.modo == 'otro_alcance':
            return registro_aprobacion(gate, 'f' * 64)
        if self.modo == 'autenticacion':
            registro = registro_aprobacion(gate, expected_scope_hash)
            registro['token'] = 'no-declarativo'
            return registro
        return registro_aprobacion(gate, expected_scope_hash)


class BaseSandbox(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        self.politica = pe.Policy.default('orgdna-platform')

    def ejecutor(self, aprobador=None, politica=None):
        return sx.SandboxExecutor(politica if politica is not None else self.politica,
                                  data_root=self.data, approver=aprobador)

    def canal(self):
        return tc.TeamChannel(MIEMBROS, clock=lambda: 1000.0)

    def tarea_para_coder(self, canal, prompt='calcular 6*7'):
        return canal.assign('ana', 'coder', prompt)


class GateTests(BaseSandbox):
    """Vectores gate/gate_antes_de_fs (I1/I2): sin aprobacion honrada no se ejecuta NADA."""

    def test_vector_sin_aprobador_nada_se_ejecuta(self):
        # python_node_env_no_puede_habilitar + optin_rechazado_valores_invalidos —
        # tests/test_code_execution_security.py:94,17
        ejecutor = self.ejecutor(aprobador=None)
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxPolicyError) as ctx:
                ejecutor.execute('id-coder', 'print("ejecutado")')
        self.assertEqual(ctx.exception.gate, 'write')
        self.assertIn("'write'", str(ctx.exception))          # nombre de la puerta
        popen.assert_not_called()                             # subprocess_run_llamado: false
        self.assertFalse((self.data / 'work').exists())       # workspace_existe: false (I2)

    def test_vector_aprobador_que_rechaza_no_ejecuta(self):
        aprobador = AprobadorEnMemoria(modo='rechazar')
        ejecutor = self.ejecutor(aprobador=aprobador)
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxPolicyError) as ctx:
                ejecutor.execute('id-coder', 'print("x")')
        self.assertEqual(ctx.exception.gate, 'write')
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())
        self.assertEqual(len(aprobador.consultas), 1)         # se consulto una sola vez

    def test_vector_aprobacion_de_otra_puerta_no_autoriza(self):
        # Adaptacion de approval.gate_mismatch (policy_engine): la aprobacion de
        # 'deploy' no abre la puerta 'write' que esta accion levanta.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria(modo='otra_puerta'))
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxPolicyError) as ctx:
                ejecutor.execute('id-coder', 'print("x")')
        self.assertEqual(ctx.exception.gate, 'write')
        self.assertIn("'write'", str(ctx.exception))
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())

    def test_vector_aprobacion_de_otro_alcance_no_autoriza(self):
        # approval.scope_mismatch: un scope_hash ajeno no autoriza esta accion.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria(modo='otro_alcance'))
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxPolicyError):
                ejecutor.execute('id-coder', 'print("x")')
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())

    def test_vector_aprobacion_que_reclama_autenticacion_se_deniega(self):
        # D-R0-5 del policy_engine: un registro que declara autenticacion se DENIEGA;
        # el ejecutor bloquea (no hay salida laxa propia).
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria(modo='autenticacion'))
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxPolicyError):
                ejecutor.execute('id-coder', 'print("x")')
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())

    def test_las_puertas_del_policy_engine_no_se_relajan(self):
        # El ejecutor solo consulta al motor: la politica queda intacta tras un bloqueo.
        hash_antes = self.politica.policy_hash
        ejecutor = self.ejecutor(aprobador=None)
        with mock.patch.object(sx.subprocess, 'Popen'):
            with self.assertRaises(sx.SandboxPolicyError):
                ejecutor.execute('id-coder', 'print("x")')
        self.assertEqual(self.politica.policy_hash, hash_antes)
        self.assertEqual(self.politica.gate_default_outcome('write'),
                         pe.DECISION_REQUIRE)
        self.assertIn('write', self.politica.limits['approvals_required'])
        accion = {'action_kind': 'write_file', 'target': 'work/x.py'}
        decision = pe.evaluate(self.politica, accion)
        self.assertEqual(decision['decision'], pe.DECISION_REQUIRE)
        self.assertEqual(decision['gate'], 'write')


class HappyPathTests(BaseSandbox):
    """Vectores happy_path: con aprobacion valida se ejecuta Y se entrega (P1 completa)."""

    def test_vector_ejecuta_codigo_inofensivo(self):
        # python_node_ejecuta_codigo_inofensivo —
        # tests/test_code_execution_security.py:97: print(6 * 7) -> "42"
        aprobador = AprobadorEnMemoria()
        ejecutor = self.ejecutor(aprobador=aprobador)
        run = ejecutor.execute('id-coder', 'print(6 * 7)')
        self.assertTrue(run['ok'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['exit_code'], 0)
        self.assertEqual(run['stdout'].strip(), '42')
        self.assertEqual(run['policy']['gate'], 'write')      # puerta levantada: write
        self.assertTrue(run['policy']['approved'])
        self.assertEqual(len(aprobador.consultas), 1)

    def test_vector_con_aprobacion_ejecuta_y_entrega_al_canal(self):
        # Cierre de P1: workspace dedicado + artefacto firmado + entrega al que asigno.
        canal = self.canal()
        tarea = self.tarea_para_coder(canal)
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('coder', 'print(6 * 7)', channel=canal, task_id=tarea['id'])

        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['stdout'].strip(), '42')
        # workspace dedicado por agente por ejecucion, con el script del sistema
        workspace = Path(run['workspace'])
        self.assertTrue(workspace.is_dir())
        self.assertTrue((workspace / 'id-coder.py').is_file())
        self.assertEqual(workspace.parent.name, 'id-coder')
        # artefacto firmado via artifact_factory: existe, hash real, recibo con consent
        artefacto = run['artifact']
        self.assertIsNotNone(artefacto, run.get('artifact_error'))
        archivo = self.data / 'artifacts' / artefacto['path']
        self.assertTrue(archivo.is_file())
        self.assertEqual(hashlib.sha256(archivo.read_bytes()).hexdigest(), artefacto['sha256'])
        recibo = artefacto['receipt']
        self.assertEqual(recibo['result_outcome'], 'completed')
        self.assertEqual(recibo['consent_ref'], run['policy']['scope_hash'])
        # entrega al destinatario que asigno (actor de la tarea = ana)
        self.assertEqual(run['delivered_to'], 'id-ana')
        bandeja = canal.inbox('ana')
        self.assertEqual(len(bandeja), 1)
        self.assertIn(run['run_id'], bandeja[0]['text'])
        self.assertIn(artefacto['sha256'], bandeja[0]['text'])
        # evidencia firmada + tarea claim->submit con esa evidencia
        vista = canal.ledger_view()
        evidencias = [fila for fila in vista['evidence'] if fila['id'] == run['evidence_id']]
        self.assertEqual(len(evidencias), 1)
        self.assertEqual(evidencias[0]['sha256'], artefacto['sha256'])
        tarea_final = [fila for fila in vista['tasks'] if fila['id'] == tarea['id']][0]
        self.assertEqual(tarea_final['status'], 'submitted')
        self.assertEqual(tarea_final['evidence_ids'], [run['evidence_id']])
        self.assertEqual(run['task_status'], 'submitted')
        self.assertIsNone(run['delivery_error'])

    def test_workspace_dedicado_por_ejecucion_y_limpiable(self):
        # Dos corridas del mismo agente: workspaces distintos (uuid por ejecucion) y
        # cleanup() borra SOLO el pedido (directorio temporal limpiable por diseno).
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run1 = ejecutor.execute('id-coder', 'print(1)')
        run2 = ejecutor.execute('id-coder', 'print(2)')
        self.assertNotEqual(run1['workspace'], run2['workspace'])
        self.assertTrue(Path(run1['workspace']).is_dir())
        self.assertTrue(Path(run2['workspace']).is_dir())
        self.assertTrue(ejecutor.cleanup(run1))
        self.assertFalse(Path(run1['workspace']).exists())
        self.assertTrue(Path(run2['workspace']).is_dir())     # la otra queda intacta
        self.assertFalse(ejecutor.cleanup(run1))              # ya borrado: False, no lanza
        self.assertTrue(ejecutor.cleanup_agent('id-coder'))
        self.assertFalse(Path(run2['workspace']).exists())

    def test_receptor_explicito_sin_tarea_entrega_igual(self):
        canal = self.canal()
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('coder', 'print("para bob")', channel=canal, recipient='bob')
        self.assertEqual(run['delivered_to'], 'id-bob')
        # inbox es destructivo (Mode A del bus): UN drain, y de ahi todas las aserciones.
        bandeja_bob = canal.inbox('bob')
        self.assertEqual(len(bandeja_bob), 1)
        # run_id viaja en el texto Y dentro del nombre del artefacto firmado:
        # assertIn (el count exacto depende del nombre del artefacto).
        self.assertIn(run['run_id'], bandeja_bob[0]['text'])
        self.assertIn(run['artifact']['sha256'], bandeja_bob[0]['text'])
        self.assertEqual(canal.inbox('ana'), [])              # solo el receptor pedido
        self.assertEqual(run['task_id'], None)

    def test_sin_canal_firma_artefacto_sin_entrega(self):
        # channel=None: el run ocurre y el artefacto se firma; no hay entrega (declarado).
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('id-coder', 'print(3)')
        self.assertIsNotNone(run['artifact'])
        self.assertIsNone(run['delivered_to'])
        self.assertIsNone(run['delivery_error'])


class EdgeTests(BaseSandbox):
    """Bordes del fuente (cuaderno §4): timeout, error de codigo, salida enorme, escape."""

    def test_vector_timeout_vencido(self):
        # Timeout vencido (ejecutor): resultado fallido acotado, timed_out=True
        # distinguible de crash — python_executor.py::_run_process.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('id-coder', 'while True:\n    pass\n', timeout_seconds=1)
        self.assertEqual(run['status'], 'timeout')
        self.assertFalse(run['ok'])
        self.assertTrue(run['timed_out'])
        self.assertIn('1s', run['error'])
        self.assertIsNotNone(run['artifact'])                 # el fallo tambien se firma
        self.assertEqual(run['artifact']['receipt']['result_outcome'], 'failed')

    def test_vector_codigo_con_error(self):
        # Codigo que falla: rc != 0 -> resultado estructurado con marcador estable y
        # stderr embebido (_build_failure_message), NO excepcion.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('id-coder', 'raise ValueError("boom")')
        self.assertEqual(run['status'], 'failed')
        self.assertFalse(run['ok'])
        self.assertFalse(run['timed_out'])
        self.assertNotEqual(run['exit_code'], 0)
        self.assertIn('Traceback', run['stderr'])
        self.assertIn(sx.EXECUTION_FAILED_MARKER, run['error'])
        self.assertIn('exit_code=', run['error'])

    def test_vector_salida_enorme_acotada(self):
        # Salida enorme: el fuente NO truncaba (cuaderno §4); el port anade tope propio
        # con kill — stdout acotado al limite, bytes totales contados, salida marcada.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('id-coder', 'print("A" * 200000)', max_output_bytes=4096)
        self.assertEqual(run['status'], 'failed')
        self.assertFalse(run['ok'])
        self.assertTrue(run['output_truncated'])
        self.assertLessEqual(len(run['stdout'].encode('utf-8')), 4096)
        # counts mide lo LEIDO hasta el kill (el lector corta al cruzar el tope):
        # prueba que efectivamente supero el limite, no que drenara los 200k del hijo.
        self.assertGreater(run['stdout_bytes'], 4096)
        self.assertIn('4096', run['error'])

    def test_vector_ruta_que_escapa_rechazada(self):
        # I4/I7 (validate_path_component / session traversal): componente hostil en
        # agent_id -> rechazo ANTES de la puerta, sin directorio y sin proceso.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        hostiles = ['../../../outside', 'src/../../x', '..', '.', 'C:escape',
                    '\\\\server\\share', 'bad\x00name', '   ']
        for agente in hostiles:
            with self.subTest(agente=agente):
                with mock.patch.object(sx.subprocess, 'Popen') as popen:
                    with self.assertRaises(sx.SandboxConfigError):
                        ejecutor.execute(agente, 'print("x")')
                popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())

    def test_vector_codigo_vacio_rechazado_sin_puerta(self):
        # Borde 'sin segmento de codigo': divergencia declarada — la entrada es codigo
        # explicito, se rechaza por validacion ANTES de gastar la consulta de aprobacion.
        aprobador = AprobadorEnMemoria()
        ejecutor = self.ejecutor(aprobador=aprobador)
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxConfigError) as ctx:
                ejecutor.execute('id-coder', '   \n\t ')
        self.assertIn(sx.NO_CODE_MESSAGE.split(':')[0], str(ctx.exception))
        popen.assert_not_called()
        self.assertEqual(aprobador.consultas, [])             # ni se consulto la puerta
        self.assertFalse((self.data / 'work').exists())

    def test_limites_invalidos_rechazados(self):
        # Port de python_runner.py::from_dict: timeout debe ser entero > 0.
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        for timeout in (0, -1, 'x', 1.5, True, None):
            with self.subTest(timeout=timeout):
                with self.assertRaises(sx.SandboxConfigError):
                    ejecutor.execute('id-coder', 'print(1)', timeout_seconds=timeout)
        with self.assertRaises(sx.SandboxConfigError):
            ejecutor.execute('id-coder', 'print(1)', max_output_bytes=10)


class EntregaGuardTests(BaseSandbox):
    """La entrega no relaja guards: fabrica y canal siguen cerrando sus propias puertas."""

    def test_el_guard_de_credenciales_de_la_fabrica_no_se_relaja(self):
        # Si la salida impresa tiene forma de credencial, artifact_factory rechaza el
        # reporte (forbidden_field): el run YA ocurrio, se entrega el estado sin firma
        # y la tarea queda claimed SIN submit (no hay evidencia honesta que citar).
        canal = self.canal()
        tarea = self.tarea_para_coder(canal)
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        run = ejecutor.execute('coder', 'print("password = hunter2")',
                               channel=canal, task_id=tarea['id'])
        self.assertEqual(run['status'], 'completed')          # la ejecucion fue valida
        self.assertIsNone(run['artifact'])
        self.assertEqual(run['artifact_error'], 'forbidden_field')
        self.assertEqual(run['delivered_to'], 'id-ana')       # el estado SI se entrega
        mensaje = canal.inbox('ana')[0]['text']
        self.assertIn('Sin artefacto firmado', mensaje)
        vista = canal.ledger_view()
        self.assertEqual(vista['evidence'], [])               # sin evidencia inventada
        tarea_final = [fila for fila in vista['tasks'] if fila['id'] == tarea['id']][0]
        self.assertEqual(tarea_final['status'], 'claimed')    # sin submit sin evidencia
        self.assertIn('sin submit', run['delivery_error'])

    def test_tarea_de_otro_dueno_rechazada_antes_de_la_puerta(self):
        canal = self.canal()
        tarea = canal.assign('ana', 'bob', 'tarea de bob')    # bob es el dueno
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxConfigError):
                ejecutor.execute('coder', 'print("x")', channel=canal, task_id=tarea['id'])
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())

    def test_receptor_desconocido_rechazado_antes_de_ejecutar(self):
        canal = self.canal()
        ejecutor = self.ejecutor(aprobador=AprobadorEnMemoria())
        with mock.patch.object(sx.subprocess, 'Popen') as popen:
            with self.assertRaises(sx.SandboxConfigError):
                ejecutor.execute('coder', 'print("x")', channel=canal, recipient='fantasma')
        popen.assert_not_called()
        self.assertFalse((self.data / 'work').exists())


if __name__ == '__main__':
    unittest.main()
