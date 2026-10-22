"""Pruebas del panel del sandbox P1/M4: aprobacion humana en DOS pasos por HTTP local real.

Arnes: el mismo de `tests_bridge.py` / `tests_team_followups_panel.py` (BridgeState +
LocalServer sobre 127.0.0.1:0, cookie de sesion, Origin local y X-CSRF-Token). No usa
proveedores, red externa, DSH ni claves: el unico efecto es ejecutar codigo local dentro
del espacio de trabajo del sandbox (bajo un directorio temporal de la prueba) y registrar
evidencia en el canal EN MEMORIA.

Que fija:
  1. Flujo en dos pasos y fail-closed: `sandbox-request` valida y devuelve request_id +
     scope_hash + vista del codigo SIN ejecutar; `sandbox-approve` registra una aprobacion
     de un solo uso ligada a (request_id, scope_hash); `sandbox-exec` es el unico camino
     que ejecuta y exige esa aprobacion vigente.
  2. Sin aprobacion, `sandbox-exec` devuelve 400 nombrando la puerta y NO ejecuta (se
     comprueba con un codigo que dejaria un archivo marcador que NO existe).
  3. La aprobacion es de un solo uso y ligada al hash: replay_rejected al repetir y
     scope_mismatch al cambiar el codigo (o el agent_id, o el scope_hash al aprobar).
  4. La politica manda: si engine/policy_engine.py devuelve deny, NINGUNA aprobacion del
     panel lo convierte en allow (probado con una politica que deniega).
  5. El agente debe ser miembro del roster vigente; un agent_id desconocido se rechaza
     antes de tocar el filesystem.
  6. La entrega al canal se hace con el sha256 del artefacto y queda como evidencia.
  7. El panel declara en la vista el estado de las 8 puertas (sin anadir ni relajar ninguna).

CLI:  python -m unittest tests_sandbox_panel -v
"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from engine.bridge import (BridgeState, LocalServer, SANDBOX_ACTIONS, SANDBOX_APPROVAL_TTL_SECONDS,
                           SANDBOX_MAX_CODE_CHARS, SANDBOX_MAX_REQUESTS)
from engine.policy_engine import DECISION_DENY, DECISION_REQUIRE, GATES, Policy
from engine.project_store import ProjectStore
from tests_bridge import NullStore

ROOT_PATH = '/api/state'
SUITE = Path(__file__).resolve().parent


class Clock:
    """Reloj inyectable: el bridge no expone control de tiempo por HTTP."""

    def __init__(self, start=1_000_000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class SandboxPanelTests(unittest.TestCase):
    """HTTP real contra el servidor local del bridge. Sin red externa ni proveedores."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.marker = self.root / 'MARCADOR_NO_DEBE_EXISTIR.txt'
        self.clock = Clock()
        self.state = BridgeState(credential_store=NullStore(),
                                 project_store=ProjectStore(self.root / 'projects'),
                                 sandbox_data_root=self.root / 'sandbox',
                                 sandbox_clock=self.clock)
        self.server = LocalServer(('127.0.0.1', 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:%d' % self.server.server_port
        status, headers, _ = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.state.execute('generate', {})
        self.version = self.state.organization.get('state_version', 1)
        self.member = self.state.organization['agents'][0]['id']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    # ------------------------------------------------------------------ utilidades

    def request(self, method, path, body=None, headers=None):
        """Peticion HTTP real con reintento de TRANSPORTE (host compartido)."""
        last = None
        for attempt in range(3):
            try:
                connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port,
                                                        timeout=20)
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                payload = response.read()
                result = (response.status, dict(response.getheaders()), payload)
                connection.close()
                return result
            except (OSError, http.client.HTTPException) as error:
                last = error
                time.sleep(0.2 * (attempt + 1))
        raise AssertionError('transporte HTTP local no disponible tras 3 intentos: %r' % (last,))

    def post_headers(self, **overrides):
        headers = {'Host': self.host, 'Origin': 'http://' + self.host, 'Cookie': self.cookie,
                   'Content-Type': 'application/json', 'X-CSRF-Token': self.state.csrf}
        headers.update(overrides)
        return headers

    def post(self, action, body, **headers):
        status, _, payload = self.request('POST', '/api/' + action, json.dumps(body),
                                          self.post_headers(**headers))
        return status, json.loads(payload)

    def state_view(self):
        status, _, payload = self.request('GET', ROOT_PATH, headers={'Cookie': self.cookie})
        self.assertEqual(status, 200)
        return json.loads(payload)

    def sandbox(self, payload=None):
        return (payload or self.state_view())['sandbox']

    def marker_code(self):
        """Codigo que dejaria un archivo marcador: si se ejecuta, la prueba lo ve."""
        return 'import pathlib\npathlib.Path(%r).write_text("ejecutado", encoding="utf-8")\nprint("ok")\n' % str(self.marker)

    def request_sandbox(self, code=None, agent=None, expect=200, **extra):
        body = {'expected_state_version': self.version,
                'agent_id': agent or self.member,
                'code': self.marker_code() if code is None else code}
        body.update(extra)
        status, payload = self.post('sandbox-request', body)
        self.assertEqual(status, expect, payload)
        return payload

    def approve(self, request_id, scope_hash, expect=200, **extra):
        body = {'expected_state_version': self.version, 'request_id': request_id,
                'scope_hash': scope_hash}
        body.update(extra)
        status, payload = self.post('sandbox-approve', body)
        self.assertEqual(status, expect, payload)
        return payload

    def execute(self, request_id, expect=200, **extra):
        body = {'expected_state_version': self.version, 'request_id': request_id}
        body.update(extra)
        status, payload = self.post('sandbox-exec', body)
        self.assertEqual(status, expect, payload)
        return payload

    def runs(self):
        return self.state.sandbox_runs

    # ------------------------------------------------------------ la vista (puertas)

    def test_view_declares_two_step_flow_gates_and_deny_by_default(self):
        view = self.sandbox()
        self.assertTrue(view['available'], view.get('reason'))
        self.assertEqual(view['flow']['steps'], ['sandbox-request', 'sandbox-approve',
                                                 'sandbox-exec'])
        self.assertIs(view['flow']['two_step_required'], True)
        self.assertIs(view['flow']['single_use_approval'], True)
        self.assertIs(view['flow']['deny_by_default'], True)
        self.assertIs(view['flow']['adds_new_gates'], False)
        self.assertIs(view['flow']['consumes_policy_gates'], True)
        self.assertEqual(view['flow']['approval_ttl_seconds'], SANDBOX_APPROVAL_TTL_SECONDS)
        self.assertIs(view['sandboxed'], False)
        self.assertTrue(view['os_isolation'])
        policy = view['policy']
        self.assertEqual([row['gate'] for row in policy['gates']], list(GATES))
        self.assertEqual(len(GATES), 8)
        for row in policy['gates']:
            self.assertEqual(row['default_outcome'], 'require_human_approval')
            self.assertIs(row['required'], True)
        self.assertEqual(policy['network_allowed'], False)
        self.assertEqual(policy['write_allowed'], False)
        self.assertEqual(policy['autonomy_ceiling'], 'observe')
        self.assertEqual(len(policy['policy_hash']), 64)
        self.assertEqual(view['counts'], {'requests': 0, 'pending': 0, 'approved': 0,
                                          'executed': 0})

    def test_view_without_design_is_unavailable_with_reason_and_never_raises(self):
        state = BridgeState(credential_store=NullStore(),
                            project_store=ProjectStore(self.root / 'projects2'),
                            sandbox_data_root=self.root / 'sandbox2', sandbox_clock=self.clock)
        view = state.sandbox_public()
        self.assertFalse(view['available'])
        self.assertIn('Genera un diseno', view['reason'])
        self.assertIsNone(view['policy'])

    # ------------------------------------------------- paso 1: solicitar (sin ejecutar)

    def test_request_returns_id_scope_and_code_view_without_executing(self):
        payload = self.request_sandbox()
        request = payload['sandbox_request']
        self.assertRegex(request['request_id'], r'^[0-9a-f]{32}$')
        self.assertRegex(request['scope_hash'], r'^[0-9a-f]{64}$')
        self.assertEqual(request['policy']['decision'], DECISION_REQUIRE)
        self.assertEqual(request['policy']['gate'], 'write')
        self.assertEqual(request['blocked_reason'], 'human_approval_required')
        self.assertIs(request['approved'], False)
        self.assertEqual(request['action']['action_kind'], 'write_file')
        self.assertIn('pathlib', request['code_view'])
        self.assertEqual(request['code_bytes'], len(self.marker_code().encode('utf-8')))
        # NO se ejecuto nada: ni marcador, ni ejecuciones, ni workspace materializado.
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.runs(), [])
        self.assertFalse((self.root / 'sandbox').exists())
        self.assertIn(request['request_id'], self.sandbox(payload)['requests'][0]['request_id'])

    def test_exec_without_approval_names_the_gate_and_does_not_execute(self):
        request = self.request_sandbox()['sandbox_request']
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id']})
        self.assertEqual(status, 400, payload)
        self.assertIn("gate 'write'", payload['error'])
        self.assertIn('aprobacion humana en dos pasos', payload['error'])
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sandbox()['requests'][0]['blocked_reason'],
                         'human_approval_required')

    def test_request_validates_code_limits_and_agent_before_touching_disk(self):
        cases = {
            'codigo vacio': {'code': '   '},
            'codigo enorme': {'code': 'x' * (SANDBOX_MAX_CODE_CHARS + 1)},
            'timeout cero': {'code': 'print(1)', 'timeout_seconds': 0},
            'timeout alto': {'code': 'print(1)', 'timeout_seconds': 301},
            'timeout booleano': {'code': 'print(1)', 'timeout_seconds': True},
            'salida corta': {'code': 'print(1)', 'max_output_bytes': 10},
            'salida alta': {'code': 'print(1)', 'max_output_bytes': 10 ** 9},
        }
        for label, extra in cases.items():
            with self.subTest(caso=label):
                body = {'expected_state_version': self.version, 'agent_id': self.member}
                body.update(extra)
                status, payload = self.post('sandbox-request', body)
                self.assertEqual(status, 400, payload)
        self.assertEqual(self.state.sandbox_requests, {})
        self.assertFalse((self.root / 'sandbox').exists())

    def test_unknown_agent_is_rejected_before_the_filesystem(self):
        status, payload = self.post('sandbox-request', {'expected_state_version': self.version,
                                                        'agent_id': 'intruso-sin-roster',
                                                        'code': self.marker_code()})
        self.assertEqual(status, 400, payload)
        self.assertIn('miembro del roster vigente', payload['error'])
        self.assertIn('no se toco el disco', payload['error'])
        self.assertEqual(self.state.sandbox_requests, {})
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / 'sandbox').exists())

    # ------------------------------------------------------- paso 2: aprobar (binding)

    def test_approve_requires_the_exact_scope_hash(self):
        request = self.request_sandbox()['sandbox_request']
        status, payload = self.post('sandbox-approve', {'expected_state_version': self.version,
                                                        'request_id': request['request_id'],
                                                        'scope_hash': 'f' * 64})
        self.assertEqual(status, 400, payload)
        self.assertIn('scope_mismatch', payload['error'])
        self.assertEqual(self.state.sandbox_requests[request['request_id']]['approval'], None)
        approved = self.approve(request['request_id'], request['scope_hash'],
                                approver_role='revisor-humano')['sandbox_approval']
        self.assertIs(approved['approved'], True)
        self.assertEqual(approved['approver_role'], 'revisor-humano')
        self.assertEqual(approved['blocked_reason'], 'ready')
        self.assertEqual(approved['policy']['gate'], 'write')
        stored = self.state.sandbox_requests[request['request_id']]['approval']
        self.assertEqual(stored['gate'], 'write')
        self.assertEqual(stored['scope_hash'], request['scope_hash'])
        self.assertIs(stored['one_shot'], True)
        self.assertFalse(self.marker.exists())

    # ------------------------------------------- paso 3: ejecutar (unica ruta, consume)

    def test_approved_execution_runs_and_delivers_signed_artifact_and_evidence(self):
        request = self.request_sandbox('print("hola desde el sandbox")')['sandbox_request']
        self.approve(request['request_id'], request['scope_hash'])
        execution = self.execute(request['request_id'])['sandbox_execution']
        self.assertEqual(execution['status'], 'completed')
        self.assertEqual(execution['exit_code'], 0)
        self.assertIs(execution['ok'], True)
        self.assertIn('hola desde el sandbox', execution['stdout'])
        artifact = execution['artifact']
        self.assertIsNotNone(artifact, execution.get('artifact_error'))
        self.assertRegex(artifact['sha256'], r'^[0-9a-f]{64}$')
        self.assertTrue(artifact['path'])
        self.assertIn('receipt', artifact)
        self.assertTrue(execution['evidence_id'])
        self.assertEqual(execution['delivered_to'], self.state._sandbox_recipient(
            {'member_id': self.member, 'name': self.member}))
        self.assertEqual(execution['policy']['gate'], 'write')
        self.assertEqual(execution['policy']['decision'], 'allow')
        self.assertIs(execution['policy']['approved'], True)
        self.assertRegex(execution['policy']['scope_hash'], r'^[0-9a-f]{64}$')
        # El artefacto queda en el ledger del canal con su sha256 (evidencia, no solo ejecucion).
        channel = self.state.public()['team_channel']
        self.assertTrue(any(row.get('sha256') == artifact['sha256'] for row in channel['evidence']))
        self.assertTrue(any(row.get('id') == execution['evidence_id'] for row in channel['evidence']))
        self.assertTrue(any('sha256=' + artifact['sha256'] in str(row.get('text', ''))
                            for row in channel['messages']))
        view = self.sandbox()['executions'][0]
        self.assertEqual(view['artifact']['sha256'], artifact['sha256'])

    def test_marker_code_only_runs_after_approval(self):
        request = self.request_sandbox()['sandbox_request']
        self.assertFalse(self.marker.exists())
        self.approve(request['request_id'], request['scope_hash'])
        self.assertFalse(self.marker.exists())
        execution = self.execute(request['request_id'])['sandbox_execution']
        self.assertEqual(execution['status'], 'completed')
        self.assertTrue(self.marker.exists())
        self.assertEqual(len(self.runs()), 1)

    def test_approval_is_single_use_and_replay_is_rejected(self):
        request = self.request_sandbox('print("una vez")')['sandbox_request']
        self.approve(request['request_id'], request['scope_hash'])
        self.execute(request['request_id'])
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id']})
        self.assertEqual(status, 400, payload)
        self.assertIn('replay_rejected', payload['error'])
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.sandbox()['requests'][0]['blocked_reason'], 'approval_consumed')

    def test_changing_the_code_or_the_agent_invalidates_the_approval(self):
        request = self.request_sandbox('print("aprobado")')['sandbox_request']
        self.approve(request['request_id'], request['scope_hash'])
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id'],
                                                     'code': 'print("distinto")'})
        self.assertEqual(status, 400, payload)
        self.assertIn('scope_mismatch', payload['error'])
        other = self.state.organization['agents'][1]['id']
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id'],
                                                     'agent_id': other})
        self.assertEqual(status, 400, payload)
        self.assertIn('scope_mismatch', payload['error'])
        self.assertEqual(self.runs(), [])

    def test_expired_approval_is_rejected(self):
        request = self.request_sandbox('print("tarde")')['sandbox_request']
        self.approve(request['request_id'], request['scope_hash'])
        self.clock.advance(SANDBOX_APPROVAL_TTL_SECONDS + 1)
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id']})
        self.assertEqual(status, 400, payload)
        self.assertIn('approval_expired', payload['error'])
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sandbox()['requests'][0]['blocked_reason'], 'approval_expired')

    # --------------------------------------------------- la politica manda (deny gana)

    def test_policy_denial_after_approval_wins_and_consumes_the_attempt(self):
        request = self.request_sandbox('print("denegado")')['sandbox_request']
        self.approve(request['request_id'], request['scope_hash'])
        denying = Policy.default('orgdna-plataforma',
                                 overrides={'denied_action_kinds': ['write_file']})
        self.state._sandbox_policy_override = denying
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id']})
        self.assertEqual(status, 400, payload)
        self.assertIn('deny', payload['error'])
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.sandbox()['requests'][0]['blocked_reason'], 'approval_consumed')
        self.assertEqual(self.sandbox()['requests'][0]['consumed_reason'], 'policy_denied')

    def test_request_under_a_denying_policy_is_declared_and_never_approvable(self):
        self.state._sandbox_policy_override = Policy.default(
            'orgdna-plataforma', overrides={'denied_action_kinds': ['write_file']})
        request = self.request_sandbox('print("no")')['sandbox_request']
        self.assertEqual(request['policy']['decision'], DECISION_DENY)
        self.assertIs(request['executable'], False)
        self.assertEqual(request['blocked_reason'], 'policy_denied')
        status, payload = self.post('sandbox-approve', {'expected_state_version': self.version,
                                                        'request_id': request['request_id'],
                                                        'scope_hash': request['scope_hash']})
        self.assertEqual(status, 400, payload)
        self.assertIn('ninguna aprobacion del panel la convierte en allow', payload['error'])
        status, payload = self.post('sandbox-exec', {'expected_state_version': self.version,
                                                     'request_id': request['request_id']})
        self.assertEqual(status, 400, payload)
        self.assertEqual(self.runs(), [])
        self.assertFalse(self.marker.exists())

    # ------------------------------------------------------------- bordes del panel

    def test_actions_require_session_origin_and_current_version(self):
        request = self.request_sandbox()['sandbox_request']
        status, _ = self.post('sandbox-exec', {'expected_state_version': self.version,
                                               'request_id': request['request_id']},
                              Cookie='')
        self.assertEqual(status, 403)
        status, _ = self.post('sandbox-exec', {'expected_state_version': self.version,
                                               'request_id': request['request_id']},
                              Origin='http://evil.example')
        self.assertEqual(status, 403)
        for action in sorted(SANDBOX_ACTIONS):
            status, payload = self.post(action, {'expected_state_version': self.version + 99})
            self.assertEqual(status, 400, payload)
            self.assertIn('Versi', payload['error'])

    def test_session_secret_in_the_code_is_refused_by_the_redaction_guard(self):
        self.state._sensitive_values.add('SECRETO-SANDBOX-XYZ')
        status, payload = self.post('sandbox-request', {'expected_state_version': self.version,
                                                        'agent_id': self.member,
                                                        'code': 'print("SECRETO-SANDBOX-XYZ")'})
        self.assertEqual(status, 400, payload)
        self.assertIn('clave de sesión', payload['error'])
        self.assertEqual(self.state.sandbox_requests, {})

    def test_request_queue_is_bounded(self):
        for index in range(SANDBOX_MAX_REQUESTS):
            self.request_sandbox('print(%d)' % index)
        status, payload = self.post('sandbox-request', {'expected_state_version': self.version,
                                                        'agent_id': self.member,
                                                        'code': 'print("extra")'})
        self.assertEqual(status, 400, payload)
        self.assertIn('Cola de solicitudes llena', payload['error'])
        self.assertEqual(len(self.state.sandbox_requests), SANDBOX_MAX_REQUESTS)

    # ------------------------------------------------------------------ el panel

    def test_panel_declares_the_section_and_the_two_step_controls(self):
        html = (SUITE / 'web' / 'index.html').read_text(encoding='utf-8')
        script = (SUITE / 'web' / 'app.js').read_text(encoding='utf-8')
        style = (SUITE / 'web' / 'style.css').read_text(encoding='utf-8')
        for element in ('sandbox-panel', 'sandbox-gates', 'sandbox-agent', 'sandbox-code',
                        'sandbox-request', 'sandbox-request-list', 'sandbox-run-list',
                        'sandbox-verdict', 'sandbox-error', 'sandbox-policy-summary'):
            with self.subTest(elemento=element):
                self.assertIn('id="%s"' % element, html)
        self.assertIn('solicitar → aprobar → ejecutar', html)
        for symbol in ('renderSandbox', 'requestSandbox', 'approveSandbox', 'execSandbox',
                       'sandboxRun', 'updateSandboxControls'):
            with self.subTest(simbolo=symbol):
                self.assertIn('const %s=' % symbol, script)
        # Declaradas con `const` para no alterar el contrato de funciones pineadas.
        self.assertNotIn('\nfunction renderSandbox(', script)
        self.assertIn('renderFollowups();renderSandbox();', script)
        self.assertIn("$('#sandbox-request').onclick", script)
        self.assertIn("$('#sandbox-agent').onchange", script)
        # CSS acotado a #council, como el bloque P3.
        self.assertIn('#council .sandbox-', style)
        self.assertNotIn('\n.sandbox-', style)

    def test_the_eight_frozen_gates_are_consumed_and_no_new_gate_is_added(self):
        request = self.request_sandbox('print("gates")')['sandbox_request']
        self.assertIn(request['policy']['gate'], GATES)
        self.assertEqual(request['policy']['gate'], 'write')
        approved = self.approve(request['request_id'], request['scope_hash'])['sandbox_approval']
        stored = self.state.sandbox_requests[request['request_id']]['approval']
        self.assertIn(stored['gate'], GATES)
        view = self.sandbox()
        self.assertEqual(set(view['policy']['approvals_required']), set(GATES))
        self.assertEqual(approved['policy']['gate'], 'write')
        execution = self.execute(request['request_id'])['sandbox_execution']
        self.assertIn(execution['policy']['gate'], GATES)
        view = self.sandbox()
        self.assertEqual({row['gate'] for row in view['policy']['gates']}, set(GATES))
        self.assertEqual(len(view['policy']['gates']), len(GATES))


if __name__ == '__main__':
    unittest.main()
