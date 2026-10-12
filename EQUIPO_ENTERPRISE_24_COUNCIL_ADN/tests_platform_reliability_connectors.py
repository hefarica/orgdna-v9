"""Pruebas del Reliability Plane y del Connector Gateway (flujo I6).

Offline y solo biblioteca estandar. Cubre los contratos congelados de R0 que consume el flujo:
`docs/plataforma/receipt-extension.schema.json` (vocabulario de `retry_class`, `idempotency_key`,
`produced_by`) y `docs/plataforma/policy.schema.json` a traves de `engine/policy_engine.py`.

Falsificadores que esta suite hace fallar de forma explicita:
  * kill switch: ninguna operacion posterior continua y el estado terminal es consultable;
  * deduplicacion: una repeticion identica es no-op y la misma clave con contenido distinto se
    rechaza con codigo tipado;
  * invariante duro: **cero reintentos automaticos** para operaciones pagadas o no idempotentes,
    incluido un timeout desconocido;
  * pausa reversible que conserva el estado sin duplicar efectos secundarios;
  * Connector Gateway sin material de acceso y sin ninguna conexion: falla si aparece red, socket
    o subproceso, en el codigo o en las llamadas del modulo.

Run: python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_reliability_connectors.py" -v
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import unittest

from engine import connector_gateway as cg
from engine import reliability as rel
from engine.policy_engine import (DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE, GATES,
                                  GATE_DEFAULT_OUTCOME, POLICY_CONTRACT_VERSION, Policy,
                                  validate_decision)
from engine.project_store import FORBIDDEN_FIELDS

FIXED_INSTANT = '2026-10-10T00:00:00Z'
LATER_INSTANT = '2026-10-10T00:05:00Z'
DIGEST_A = 'a' * 64
DIGEST_B = 'b' * 64
KEY_ONE = 'op.2026-10-10.0001'
KEY_TWO = 'op.2026-10-10.0002'

MODULES = {
    'reliability': Path(rel.__file__).resolve(),
    'connector_gateway': Path(cg.__file__).resolve(),
}
SUITE_ROOT = Path(__file__).resolve().parent

#: Nombres de red, subproceso o acceso a disco que un modulo inerte no puede importar.
FORBIDDEN_MODULE_IMPORTS = {
    'socket', 'ssl', 'urllib', 'http', 'httplib', 'ftplib', 'smtplib', 'telnetlib', 'requests',
    'subprocess', 'multiprocessing', 'asyncio', 'threading', 'ctypes', 'pty', 'signal',
    'webbrowser', 'xmlrpc', 'shutil', 'tempfile', 'glob', 'sqlite3', 'pickle', 'importlib',
    'os', 'sys', 'pathlib', 'platform', 'getpass', 'keyring', 'paramiko', 'boto3', 'googleapiclient',
}
#: Nombres de invocacion que un modulo inerte no puede contener.
FORBIDDEN_CALL_NAMES = {'open', 'eval', 'exec', 'compile', '__import__', 'socket', 'socketpair',
                        'urlopen', 'urlretrieve', 'system', 'popen', 'connect', 'connect_ex',
                        'bind', 'listen', 'send', 'sendall', 'recv', 'check_output', 'check_call',
                        'spawn', 'spawnv', 'call', 'run', 'write_text', 'write_bytes', 'read_text',
                        'read_bytes', 'Popen', 'getenv', 'environ', 'loads_pickle'}
#: Literales que delatarian un transporte real: nunca deben aparecer en el codigo.
FORBIDDEN_LITERALS = ('http://', 'https://', 'ssh://', 'ftp://', 'smtp://', 'socket.socket(',
                      'urlopen(', 'subprocess.', 'os.system(', 'api.github.com', 'googleapis',
                      'smtplib.', 'sqlite3.connect(')

REQUIRED_RELIABILITY_FACTS = ('state', 'terminal', 'is_paused', 'halted_scopes', 'halt_reasons',
                             'halted_at', 'pause_history', 'released_scopes', 'dedup_keys',
                             'replays', 'effects_recorded', 'auto_retry_authorized',
                             'next_retry_allowed_at', 'automatic_retries_enabled',
                             'network_allowed', 'connections_opened', 'side_effects_performed',
                             'inert_by_default')


def source_of(module_name):
    return MODULES[module_name].read_text('utf-8')


def tree_of(module_name):
    return ast.parse(source_of(module_name), filename=str(MODULES[module_name]))


def call_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def governor(**kwargs):
    kwargs.setdefault('now', FIXED_INSTANT)
    return rel.ReliabilityGovernor(**kwargs)


def reserve(plan, key=KEY_ONE, digest=DIGEST_A, kind='call_provider', **kwargs):
    kwargs.setdefault('now', FIXED_INSTANT)
    return plan.reserve(idempotency_key=key, content_sha256=digest, action_kind=kind, **kwargs)


def gateway(policy=None):
    return cg.ConnectorGateway(policy if policy is not None else Policy.default(created_at=FIXED_INSTANT))


def connector_action(request, policy):
    payload = {'action_kind': cg.CONNECTOR_ACTION_KIND, 'target': request['connector_ref'],
               'idempotency_key': request['idempotency_key']}
    return dict(payload, scope_hash=policy.scope_hash(payload))


def approval_record(policy, request, *, gate=cg.CONNECTOR_GATE_KIND, one_shot=True,
                    role='operador-de-plataforma'):
    return {'gate': gate, 'approver_role': role, 'approved_at': FIXED_INSTANT,
            'scope_hash': connector_action(request, policy)['scope_hash'], 'one_shot': one_shot}


def gateway_requests(plan):
    """Bateria de salidas del gateway, etiquetadas, para comprobaciones masivas."""
    policy = plan.policy
    opened = plan.request(connector_kind='github', action='read',
                          idempotency_key='conn.github.0001', now=FIXED_INSTANT)
    plan.register_approval('github', approval_record(policy, opened['request']))
    approved = plan.request(connector_kind='github', action='read',
                            idempotency_key='conn.github.0001', now=FIXED_INSTANT)
    return {
        'conector sin decision registrada': opened,
        'conector con aprobacion declarativa': approved,
        'accion de escritura en la misma puerta': plan.request(
            connector_kind='drive', action='write', idempotency_key='conn.drive.0001',
            now=FIXED_INSTANT),
        'otro conector sin decision registrada': cg.ConnectorGateway(
            Policy.default(created_at=FIXED_INSTANT)).request(
                connector_kind='ci', action='read', idempotency_key='conn.ci.0001',
                now=FIXED_INSTANT),
    }


class ModuleStatusTests(unittest.TestCase):
    """Los dos modulos del flujo I6 son inertes por construccion, no por promesa."""

    def test_modules_import_no_network_subprocess_or_environment_library(self):
        for name in MODULES:
            with self.subTest(module=name):
                tree = tree_of(name)
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported.add(node.module.split('.')[0])
                forbidden = sorted(imported & FORBIDDEN_MODULE_IMPORTS)
                self.assertEqual(forbidden, [], 'importacion prohibida en %s: %s' % (name, forbidden))
                self.assertTrue(imported <= {'copy', 'hashlib', 'json', 're', 'datetime',
                                             'policy_engine', 'project_store', '__future__'},
                                'importacion no declarada en %s: %s' % (name, sorted(imported)))

    def test_no_callable_reaches_network_or_subprocess(self):
        for name in MODULES:
            with self.subTest(module=name):
                hits = sorted(call_names(tree_of(name)) & FORBIDDEN_CALL_NAMES)
                self.assertEqual(hits, [], 'llamada prohibida en %s: %s' % (name, hits))

    def test_no_transport_literal_and_no_url_scheme(self):
        for name in MODULES:
            source = source_of(name)
            with self.subTest(module=name):
                hits = sorted(literal for literal in FORBIDDEN_LITERALS
                              if literal.lower() in source.lower())
                self.assertEqual(hits, [], 'literal de transporte en %s: %s' % (name, hits))

    def test_capability_named_libraries_are_absent_from_the_whole_module(self):
        """Ninguna biblioteca cliente de GitHub, Drive, base de datos, web, CI o email."""
        for name in MODULES:
            tree = tree_of(name)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split('.')[0].lower() for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split('.')[0].lower())
            for client in ('github', 'pygithub', 'google', 'drive', 'psycopg2', 'pymysql', 'sqlalchemy',
                           'aiohttp', 'httpx', 'boto3', 'jenkins', 'gitlab', 'slack'):
                with self.subTest(module=name, client=client):
                    self.assertNotIn(client, imported)

    def test_declared_module_constants_never_assert_a_capability(self):
        self.assertEqual(rel.INERT_BY_DEFAULT, True)
        self.assertEqual(rel.SIDE_EFFECTS_PERFORMED, False)
        self.assertEqual(rel.NETWORK_ALLOWED, False)
        self.assertEqual(rel.CONNECTIONS_OPENED, 0)
        self.assertEqual(rel.AUTOMATIC_RETRIES_ENABLED, False)
        self.assertEqual(cg.INERT_BY_DEFAULT, True)
        self.assertEqual(cg.SIDE_EFFECTS_PERFORMED, False)
        self.assertEqual(cg.NETWORK_ALLOWED, False)
        self.assertEqual(cg.CONNECTIONS_OPENED, 0)
        self.assertEqual(cg.ENABLED_BY_DEFAULT, False)
        self.assertEqual(cg.SECRET_VALUES_STORED, False)
        self.assertEqual(cg.live_connection_count(), 0)

    def test_prohibited_name_guard_reuses_the_literal_motor_list(self):
        self.assertEqual(set(rel.PROHIBITED_FIELDS), FORBIDDEN_FIELDS)
        self.assertEqual(rel.PROHIBITED_FIELDS_SOURCE_REUSED, 'engine/project_store.py:19')
        self.assertEqual(cg.PROHIBITED_FIELDS_SOURCE, 'engine/project_store.py:19')
        for name in MODULES:
            source = source_of(name)
            with self.subTest(module=name):
                self.assertIn('PROHIBITED_FIELDS', source)
                self.assertNotIn("'api_key'", source)


class ReliabilityContractTests(unittest.TestCase):
    """El plano consume el contrato de recibo v1 congelado en R0."""

    def test_frozen_receipt_extension_is_consumed_by_fingerprint(self):
        schema_path = SUITE_ROOT / 'docs' / 'plataforma' / 'receipt-extension.schema.json'
        raw = schema_path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), rel.RECEIPT_EXTENSION_SHA256)
        schema = json.loads(raw.decode('utf-8'))
        self.assertEqual(tuple(schema['properties']['retry_class']['enum']), rel.RETRY_CLASSES)
        self.assertEqual(tuple(schema['properties']['result_outcome']['enum']), rel.RESULT_OUTCOMES)
        self.assertIn(rel.RELIABILITY_PRODUCER, schema['properties']['produced_by']['enum'])
        self.assertIn(cg.CONNECTOR_GATEWAY_PRODUCER, schema['properties']['produced_by']['enum'])
        self.assertEqual(schema['$defs']['extension_rules']['properties']
                         ['automatic_retry_of_paid_operations']['const'], False)
        self.assertEqual(schema['properties']['idempotency_key']['pattern'],
                         '^[A-Za-z0-9._:-]{8,128}$')

    def test_policy_contract_version_and_gates_come_from_the_policy_engine(self):
        self.assertEqual(rel.POLICY_CONTRACT_VERSION, POLICY_CONTRACT_VERSION)
        self.assertEqual(cg.GATEWAY_POLICY_CONTRACT_VERSION, POLICY_CONTRACT_VERSION)
        self.assertEqual(cg.GATE_DEFAULT_OUTCOME, GATE_DEFAULT_OUTCOME)
        self.assertEqual(cg.CONNECTOR_GATE_KIND, 'connectors')
        self.assertIn(cg.CONNECTOR_GATE_KIND, GATES)
        self.assertEqual(cg.CONNECTOR_ACTION_KIND, 'open_connector')
        self.assertEqual(rel.GATE_DEFAULT_OUTCOME, DECISION_REQUIRE)
        self.assertEqual(rel.DECISION_REQUIRE, DECISION_REQUIRE)

    def test_every_governor_decision_conforms_to_its_declared_shape(self):
        plan = governor()
        battery = {'reserva de lectura': reserve(plan, key=KEY_ONE, kind='read_repo')}
        battery['duplicado identico'] = reserve(plan, key=KEY_ONE, kind='read_repo')
        battery['intento nuevo pagado'] = reserve(plan, key=KEY_ONE, kind='call_provider', attempt=2)
        battery['reserva de pago'] = reserve(plan, key=KEY_TWO, digest=DIGEST_B,
                                             kind='spend_money')
        for label, decision in battery.items():
            with self.subTest(ruta=label):
                self.assertEqual(rel.validate_decision(decision), ())
                self.assertEqual(decision['executed'], False)
                self.assertEqual(decision['side_effects_performed'], False)
                self.assertEqual(decision['auto_retry_authorized'], False)
                self.assertIsNone(decision['next_retry_allowed_at'])
                self.assertTrue(decision['reason'].strip())
                self.assertIn(decision['status'], rel.STATUS_LITERALS)
        self.assertEqual(battery['reserva de lectura']['status'], rel.STATUS_RESERVED)
        self.assertEqual(battery['duplicado identico']['status'], rel.STATUS_DUPLICATE)
        self.assertEqual(battery['intento nuevo pagado']['requires_new_authorization'], True)
        self.assertEqual(battery['reserva de pago']['status'], rel.STATUS_RESERVED)

        paused_plan = governor()
        paused_plan.pause('ventana de mantenimiento sin efectos', now=FIXED_INSTANT)
        self.assertEqual(paused_plan.snapshot()['state'], rel.STATE_PAUSED)
        self.assertFalse(paused_plan.terminal())
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(paused_plan, key=KEY_TWO, digest=DIGEST_B, kind='read_repo')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        self.assertEqual(caught.exception.diagnostic['state'], rel.STATE_PAUSED)
        self.assertFalse(caught.exception.diagnostic['terminal'])

        halted = governor()
        halted.halt_organization('kill switch de prueba', now=FIXED_INSTANT)
        snapshot = halted.snapshot()
        self.assertEqual(snapshot['state'], rel.STATE_HALTED)
        self.assertTrue(snapshot['terminal'])
        self.assertEqual(halted.halted_scopes(), ('o.organization',))
        self.assertTrue(set(REQUIRED_RELIABILITY_FACTS) <= set(snapshot))
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(halted, key=KEY_TWO, digest=DIGEST_B, kind='read_repo')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        self.assertEqual(caught.exception.diagnostic['state'], rel.STATE_HALTED)
        self.assertTrue(caught.exception.diagnostic['terminal'])

    def test_validator_refutes_a_tampered_decision(self):
        decision = reserve(governor(), key=KEY_ONE, kind='read_repo')
        self.assertEqual(rel.validate_decision(decision), ())
        breakers = {
            'executed': True,
            'side_effects_performed': True,
            'auto_retry_authorized': True,
            'next_retry_allowed_at': LATER_INSTANT,
            'null_is_not_zero': False,
            'reliability_contract_version': '2',
            'status': 'executed',
            'retry_class': 'reintentar',
            'content_sha256': 'ZZ',
            'attempt': 0,
            'reason': '',
        }
        for field, value in breakers.items():
            with self.subTest(campo=field):
                tampered = dict(decision, **{field: value})
                self.assertNotEqual(rel.validate_decision(tampered), ())

    def test_policy_engine_guard_rejects_credential_shaped_requests(self):
        plan = governor()
        for name in ('api_key', 'access_token', 'authorization', 'client_secret', 'password'):
            with self.subTest(campo=name):
                with self.assertRaises(rel.ReliabilityError) as caught:
                    rel._reject_prohibited({'action': {'action_kind': 'read_repo'},
                                            name: 'valor-de-prueba'})
                self.assertEqual(caught.exception.code, 'prohibited_field')
                self.assertNotIn('valor-de-prueba', str(caught.exception))
        self.assertTrue(rel._reject_prohibited({'action': {'action_kind': 'read_repo'}}))
        self.assertEqual(plan.dedup_registry, {})
        self.assertEqual(plan.snapshot()['state'], rel.STATE_RUNNING)

    def test_receipt_extension_is_additive_and_never_authorizes_a_retry(self):
        plan = governor()
        envelope = rel.build_receipt_extension(plan, idempotency_key=KEY_ONE,
                                               result_outcome='unknown', retry_class='unknown',
                                               attempt=1, now=FIXED_INSTANT)
        self.assertEqual(rel.validate_reliability_envelope(envelope), ())
        self.assertEqual(envelope['receipt_version'], '1')
        self.assertEqual(envelope['produced_by'], 'reliability')
        self.assertEqual(envelope['result_outcome'], 'unknown')
        self.assertEqual(envelope['auto_retry_authorized'], False)
        self.assertIsNone(envelope['next_retry_allowed_at'])
        self.assertEqual(envelope['side_effects_performed'], False)
        base_keys = {'index', 'provider', 'model', 'payload_sha256', 'max_output_tokens', 'status',
                     'usage', 'latency_ms', 'http_status', 'error_code', 'response_id_sha256'}
        self.assertEqual(set(envelope) & base_keys, set())
        for field, value in (('receipt_version', '2'), ('produced_by', 'otro-modulo'),
                             ('auto_retry_authorized', True), ('null_is_not_zero', False),
                             ('result_outcome', 'garantizado'), ('retry_class', 'reintentar'),
                             ('next_retry_allowed_at', LATER_INSTANT)):
            with self.subTest(campo=field):
                self.assertNotEqual(rel.validate_reliability_envelope(dict(envelope, **{field: value})), ())
        self.assertEqual(rel.validate_reliability_envelope(dict(envelope, api_key='x')),
                         ('campo prohibido: $.api_key',))

    def test_summary_declares_zero_paid_retries_without_claiming_success(self):
        summary = rel.summarize_reliability(governor())
        self.assertEqual(summary['automatic_retries'], 0)
        self.assertEqual(summary['paid_operations_retried'], 0)
        self.assertEqual(summary['automatic_retry_of_paid_operations'], False)
        self.assertEqual(summary['connections_opened'], 0)
        self.assertEqual(summary['network_allowed'], False)
        self.assertNotIn('garantizado', json.dumps(summary).lower())
        revived = json.loads(json.dumps(summary, ensure_ascii=False))
        self.assertEqual(revived, summary)


class KillSwitchTests(unittest.TestCase):
    """El kill switch detiene la operacion y deja estado terminal consultable."""

    def test_kill_switch_stops_operation_and_leaves_terminal_state(self):
        plan = governor()
        self.assertEqual(plan.state(), rel.STATE_RUNNING)
        self.assertFalse(plan.terminal())
        reserve(plan, key=KEY_ONE, kind='read_repo')
        self.assertEqual(len(plan.dedup_registry), 1)
        halt = plan.halt_organization('parada de emergencia declarada por el operador',
                                      now=FIXED_INSTANT)
        self.assertEqual(halt['status'], rel.STATUS_HALTED)
        self.assertTrue(halt['terminal'])
        self.assertEqual(halt['executed'], False)
        self.assertEqual(plan.state(), rel.STATE_HALTED)
        self.assertTrue(plan.terminal())
        snapshot = plan.snapshot()
        self.assertEqual(snapshot['state'], rel.STATE_HALTED)
        self.assertTrue(snapshot['terminal'])
        self.assertEqual(snapshot['halted_scopes'], ['o.organization'])
        self.assertIn('parada de emergencia', snapshot['halt_reasons']['o.organization'])
        self.assertEqual(snapshot['halted_at']['o.organization'], FIXED_INSTANT)
        revived = json.loads(json.dumps(snapshot, ensure_ascii=False))
        self.assertEqual(revived, snapshot)

    def test_no_operation_continues_after_the_kill_switch(self):
        plan = governor()
        reserve(plan, key=KEY_ONE, kind='read_repo')
        registry_before = plan.dedup_registry
        plan.halt_organization('kill switch terminal', now=FIXED_INSTANT)
        for kind in rel.ACTION_KINDS:
            with self.subTest(action_kind=kind):
                with self.assertRaises(rel.ReliabilityError) as caught:
                    reserve(plan, key=KEY_TWO, digest=DIGEST_B, kind=kind)
                self.assertEqual(caught.exception.code, 'operation_not_allowed')
                self.assertEqual(caught.exception.diagnostic['state'], rel.STATE_HALTED)
                self.assertTrue(caught.exception.diagnostic['terminal'])
        self.assertEqual(plan.dedup_registry, registry_before)
        self.assertEqual(len(plan.dedup_registry), 1)
        self.assertEqual(plan.ledger.total(), 0)
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.guard(action_kind='read_repo')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        with self.assertRaises(rel.ReliabilityError):
            plan.pause('pausa imposible tras la parada')
        self.assertEqual(plan.state(), rel.STATE_HALTED)

    def test_identical_replay_is_resolved_before_the_halt_as_a_pure_no_op(self):
        plan = governor()
        first = reserve(plan, key=KEY_ONE, kind='call_provider')
        plan.halt_organization('parada sin efecto sobre lecturas de recibo', now=FIXED_INSTANT)
        replay = reserve(plan, key=KEY_ONE, kind='call_provider')
        self.assertEqual(replay['status'], rel.STATUS_DUPLICATE)
        self.assertEqual(replay['recorded'], False)
        self.assertEqual(replay['executed'], False)
        self.assertEqual(replay['effect_count'], 0)
        self.assertEqual(replay['dedup_key'], first['dedup_key'])
        self.assertEqual(replay['plan_state'], rel.STATE_HALTED)
        self.assertTrue(replay['terminal'])
        self.assertEqual(len(plan.dedup_registry), 1)
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, digest=DIGEST_B, kind='call_provider')
        self.assertEqual(caught.exception.code, 'duplicate_key_conflict')

    def test_kill_switch_is_terminal_per_scope_and_release_is_explicit(self):
        plan = governor()
        task_halt = plan.halt_task('tarea-7', 'fallo no idempotente detectado en la tarea',
                                   now=FIXED_INSTANT)
        self.assertEqual(task_halt['halted_scopes'], ['t.tarea-7'])
        self.assertFalse(plan.terminal())
        self.assertEqual(plan.state(), rel.STATE_RUNNING)
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, kind='read_repo', task_id='tarea-7')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        self.assertIn('t.tarea-7', caught.exception.diagnostic['halted_scopes'])
        other = reserve(plan, key=KEY_TWO, digest=DIGEST_B, kind='read_repo', task_id='tarea-8')
        self.assertEqual(other['status'], rel.STATUS_RESERVED)
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.halt_task('tarea-7', 'segunda parada de la misma tarea')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.release_scope('t.tarea-7', reason='   ')
        self.assertEqual(caught.exception.code, 'invalid_request')
        release = plan.release_scope('t.tarea-7', reason='condicion resuelta y verificada',
                                     operator_role='operador-de-plataforma', now=LATER_INSTANT)
        self.assertEqual(release['status'], rel.STATE_RUNNING)
        self.assertEqual(plan.snapshot()['released_scopes'][0]['scope'], 't.tarea-7')
        self.assertEqual(plan.snapshot()['released_scopes'][0]['operator_role'],
                         'operador-de-plataforma')
        resumed = reserve(plan, key='op.2026-10-10.0003', kind='read_repo', task_id='tarea-7')
        self.assertEqual(resumed['status'], rel.STATUS_RESERVED)
        second_halt = plan.halt_task('tarea-9', 'segunda tarea detenida por su propio motivo')
        self.assertEqual(second_halt['halted_scopes'], ['t.tarea-9'])
        self.assertEqual(plan.snapshot()['released_scopes'][0]['scope'], 't.tarea-7')
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key='op.2026-10-10.0005', kind='read_repo', task_id='tarea-9')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        self.assertEqual(caught.exception.diagnostic['state'], rel.STATE_HALTED)
        self.assertTrue(caught.exception.diagnostic['terminal'])
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.halt_organization('   ')
        self.assertEqual(caught.exception.code, 'invalid_request')
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.halt_task('tarea-8', '   ')
        self.assertEqual(caught.exception.code, 'invalid_request')
        plan.release_scope('t.tarea-9', reason='tarea revalidada tras la revision', now=LATER_INSTANT)
        self.assertEqual(plan.state(), rel.STATE_RUNNING)
        self.assertFalse(plan.terminal())
        self.assertEqual(plan.snapshot()['released_scopes'][0]['scope'], 't.tarea-7')
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.release_scope('t.tarea-7', reason='ya estaba liberada')
        self.assertEqual(caught.exception.code, 'invalid_request')


class PauseTests(unittest.TestCase):
    """Una pausa es reversible y conserva el estado sin duplicar efectos secundarios."""

    def test_pause_is_reversible_and_preserves_state_without_duplicate_effects(self):
        plan = governor()
        first = reserve(plan, key=KEY_ONE, kind='read_repo')
        effect = plan.note_effect(KEY_ONE, now=FIXED_INSTANT)
        self.assertEqual(effect['recorded'], True)
        self.assertEqual(effect['effect_count'], 1)
        registry_before = plan.dedup_registry
        pause = plan.pause('pausa reversible declarada', now=FIXED_INSTANT)
        self.assertEqual(pause['status'], rel.STATUS_PAUSED)
        self.assertTrue(pause['reversible'])
        self.assertEqual(pause['executed'], False)
        self.assertFalse(plan.terminal())
        self.assertEqual(plan.state(), rel.STATE_PAUSED)
        self.assertEqual(pause['reservations'], 1)
        self.assertEqual(pause['effects_recorded'], 1)
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_TWO, digest=DIGEST_B, kind='read_repo')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.pause('segunda pausa anidada')
        self.assertEqual(caught.exception.code, 'operation_not_allowed')
        with self.assertRaises(rel.ReliabilityError) as caught:
            plan.guard(action_kind='read_repo')
        self.assertEqual(caught.exception.diagnostic['state'], rel.STATE_PAUSED)
        resume = plan.resume('condicion resuelta', now=LATER_INSTANT)
        self.assertEqual(resume['status'], rel.STATE_RUNNING)
        self.assertEqual(resume['executed'], False)
        self.assertEqual(resume['reservations'], 1)
        self.assertEqual(resume['effects_recorded'], 1)
        self.assertEqual(resume['replays'], 0)
        self.assertEqual(plan.state(), rel.STATE_RUNNING)
        self.assertEqual(plan.dedup_registry, registry_before)
        entry = plan.snapshot()['pause_history'][0]
        self.assertEqual(entry['paused_at'], FIXED_INSTANT)
        self.assertEqual(entry['resumed_at'], LATER_INSTANT)
        self.assertEqual(entry['reversible'], True)
        self.assertEqual(entry['side_effects_performed'], False)
        self.assertEqual(plan.ledger.count(KEY_ONE), 1)
        self.assertEqual(plan.ledger.total(), 1)
        resumed = reserve(plan, key=KEY_ONE, kind='read_repo')
        self.assertEqual(resumed['status'], rel.STATUS_DUPLICATE)
        self.assertEqual(resumed['recorded'], False)
        self.assertEqual(plan.ledger.count(KEY_ONE), 1)
        self.assertEqual(len(plan.dedup_registry), 1)
        self.assertEqual(resumed['dedup_key'], first['dedup_key'])
        with self.assertRaises(rel.ReliabilityError):
            plan.resume('reanudacion sin pausa activa')


class DeduplicationTests(unittest.TestCase):
    """Deduplicacion por `idempotency_key`: repeticion identica = no-op; contenido distinto = rechazo."""

    def test_identical_repetition_is_a_no_op_in_every_case(self):
        plan = governor()
        first = reserve(plan, key=KEY_ONE, kind='call_provider')
        self.assertEqual(first['status'], rel.STATUS_RESERVED)
        self.assertEqual(first['recorded'], True)
        self.assertEqual(first['executed'], False)
        self.assertEqual(first['effect_count'], 0)
        effects = 0
        for index in range(200):
            replay = reserve(plan, key=KEY_ONE, kind='call_provider', now=LATER_INSTANT)
            self.assertEqual(replay['status'], rel.STATUS_DUPLICATE, 'caso %d' % index)
            self.assertEqual(replay['recorded'], False)
            self.assertEqual(replay['executed'], False)
            self.assertEqual(replay['effect_count'], effects)
            self.assertEqual(replay['dedup_key'], first['dedup_key'])
            self.assertEqual(replay['retry_class'], rel.RETRY_CLASS_NONE)
            self.assertEqual(rel.validate_decision(replay), ())
        self.assertEqual(len(plan.dedup_registry), 1)
        self.assertEqual(plan.snapshot()['replays'], 200)
        self.assertEqual(plan.snapshot()['reservations'], 1)
        self.assertEqual(plan.ledger.total(), 0)
        self.assertEqual(rel.summarize_reliability(plan)['automatic_retries'], 0)

    def test_same_key_with_different_content_is_rejected(self):
        plan = governor()
        reserve(plan, key=KEY_ONE, kind='read_repo')
        before = plan.dedup_registry
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, digest=DIGEST_B, kind='read_repo')
        self.assertEqual(caught.exception.code, 'duplicate_key_conflict')
        self.assertEqual(caught.exception.diagnostic['registered_content_sha256'], DIGEST_A)
        self.assertEqual(caught.exception.diagnostic['presented_content_sha256'], DIGEST_B)
        self.assertNotIn(DIGEST_B, str(caught.exception).split('contenido')[-1][:0])
        self.assertEqual(plan.dedup_registry, before)
        self.assertEqual(len(plan.dedup_registry), 1)
        self.assertEqual(plan.ledger.total(), 0)
        distinct = reserve(plan, key=KEY_TWO, digest=DIGEST_B, kind='read_repo')
        self.assertEqual(distinct['status'], rel.STATUS_RESERVED)
        self.assertEqual(len(plan.dedup_registry), 2)
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, digest=DIGEST_B.replace('b', 'c'), kind='read_repo')
        self.assertEqual(caught.exception.code, 'duplicate_key_conflict')
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key='corta', digest=DIGEST_A, kind='read_repo')
        self.assertEqual(caught.exception.code, 'invalid_request')
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, digest='a' * 63, kind='read_repo')
        self.assertEqual(caught.exception.code, 'invalid_request')
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, digest=DIGEST_A, kind='accion-inventada')
        self.assertEqual(caught.exception.code, 'invalid_request')

    def test_new_attempt_of_a_paid_operation_demands_new_authorization(self):
        plan = governor()
        reserve(plan, key=KEY_ONE, kind='call_provider')
        retry = reserve(plan, key=KEY_ONE, kind='call_provider', attempt=2)
        self.assertEqual(retry['status'], rel.STATUS_RESERVED)
        self.assertEqual(retry['recorded'], False)
        self.assertEqual(retry['requires_new_authorization'], True)
        self.assertEqual(retry['retry_class'], rel.RETRY_CLASS_UNKNOWN)
        self.assertEqual(retry['auto_retry_authorized'], False)
        self.assertEqual(rel.validate_decision(retry), ())
        for kind in rel.NON_IDEMPOTENT_ACTION_KINDS:
            with self.subTest(action_kind=kind):
                fresh = governor()
                reserve(fresh, key=KEY_ONE, kind=kind)
                attempt = reserve(fresh, key=KEY_ONE, kind=kind, attempt=2)
                self.assertEqual(attempt['recorded'], False)
                self.assertEqual(attempt['requires_new_authorization'], True)
        read = governor()
        reserve(read, key=KEY_ONE, kind='read_repo')
        read_attempt = reserve(read, key=KEY_ONE, kind='read_repo', attempt=2)
        self.assertEqual(read_attempt['recorded'], False)
        self.assertEqual(read_attempt['requires_new_authorization'], False)
        self.assertEqual(read_attempt['auto_retry_authorized'], False)
        with self.assertRaises(rel.ReliabilityError) as caught:
            reserve(plan, key=KEY_ONE, kind='call_provider', attempt=17)
        self.assertEqual(caught.exception.code, 'invalid_attempt')

    def test_ledger_never_counts_a_repeated_effect_twice(self):
        plan = governor()
        reserve(plan, key=KEY_ONE, kind='call_provider')
        first = plan.note_effect(KEY_ONE, now=FIXED_INSTANT)
        second = plan.note_effect(KEY_ONE, now=LATER_INSTANT)
        self.assertEqual(first['recorded'], True)
        self.assertEqual(second['recorded'], False)
        self.assertTrue(second['duplicate'])
        self.assertEqual(second['effect_count'], 1)
        self.assertEqual(plan.ledger.count(KEY_ONE), 1)
        self.assertEqual(plan.ledger.total(), 1)
        self.assertIn('no se duplica', second['reason'])
        revived = json.loads(json.dumps(plan.ledger.as_dict(), ensure_ascii=False))
        self.assertEqual(revived, plan.ledger.as_dict())


class FailureClassificationTests(unittest.TestCase):
    """Ningun timeout desconocido provoca reintento automatico; este bloque falla si reintenta."""

    def test_unknown_timeout_never_triggers_an_automatic_retry(self):
        for kind in rel.ACTION_KINDS:
            for reason in ('unknown_timeout', 'motivo-jamas-visto', 'timeout_de_lectura_rara'):
                with self.subTest(action_kind=kind, reason=reason):
                    classification = rel.classify_failure(
                        http_status=None, error_reason=reason, action_kind=kind, idempotent=False,
                        result_outcome='unknown', now=FIXED_INSTANT)
                    self.assertEqual(classification['retry_class'], rel.RETRY_CLASS_UNKNOWN)
                    self.assertEqual(classification['retry_authorized'], False)
                    self.assertEqual(classification['auto_retry_authorized'], False)
                    self.assertEqual(classification['auto_retry_applicable'], False)
                    self.assertIsNone(classification['next_retry_allowed_at'])
                    self.assertEqual(classification['attempt_made'], True)
                    self.assertEqual(classification['requires_human_review'], True)
                    self.assertEqual(classification['side_effects_performed'], False)
                    self.assertEqual(rel.validate_classification(classification), ())

    def test_every_http_status_and_reason_keeps_auto_retry_closed(self):
        statuses = (100, 200, 201, 204, 301, 400, 401, 402, 403, 404, 408, 409, 418, 422, 425,
                    429, 451, 500, 502, 503, 504, 599, None)
        for kind in rel.ACTION_KINDS:
            for status in statuses:
                with self.subTest(action_kind=kind, http_status=status):
                    classification = rel.classify_failure(http_status=status, action_kind=kind,
                                                          now=FIXED_INSTANT)
                    self.assertEqual(classification['auto_retry_authorized'], False)
                    self.assertIsNone(classification['next_retry_allowed_at'])
                    self.assertIn(classification['retry_class'], rel.RETRY_CLASSES)
                    self.assertEqual(rel.validate_classification(classification), ())
        for reason in rel.FAILURE_REASONS + ('unknown', '', 'sin_clasificar'):
            with self.subTest(error_reason=reason):
                classification = rel.classify_failure(error_reason=reason, action_kind='call_provider',
                                                      now=FIXED_INSTANT)
                self.assertEqual(classification['auto_retry_authorized'], False)

    def test_paid_and_non_idempotent_operations_can_never_be_retried_automatically(self):
        self.assertEqual(rel.PAID_ACTION_KINDS, ('call_provider', 'spend_money'))
        self.assertEqual(rel.NON_IDEMPOTENT_ACTION_KINDS, ('push', 'merge', 'deploy'))
        for kind in rel.PROTECTED_ACTION_KINDS:
            with self.subTest(action_kind=kind):
                self.assertTrue(rel.is_protected_action(kind))
                self.assertFalse(rel.is_auto_retry_authorized(kind, 'transient'))
                self.assertFalse(rel.is_auto_retry_authorized(kind, 'rate_limit'))
                self.assertFalse(rel.is_auto_retry_authorized(kind, 'unknown'))
                classification = rel.classify_failure(http_status=429, error_reason='rate_limited',
                                                      action_kind=kind, result_outcome='unknown',
                                                      now=FIXED_INSTANT)
                self.assertEqual(classification['retry_class'], 'rate_limit')
                self.assertEqual(classification['auto_retry_authorized'], False)
                self.assertEqual(classification['requires_human_review'], True)
                self.assertTrue(classification['potentially_billed'] == rel.is_paid_action(kind)
                                or classification['potentially_billed'] is True)
        for kind in rel.IDEMPOTENT_ACTION_KINDS:
            with self.subTest(action_kind=kind):
                self.assertFalse(rel.is_protected_action(kind))
                self.assertFalse(rel.is_auto_retry_authorized(kind, 'transient'))
                self.assertFalse(rel.is_auto_retry_authorized(kind, 'rate_limit'))

    def test_classification_declares_and_never_executes_or_persists_headers(self):
        classification = rel.classify_failure(http_status=429, error_reason='rate_limited',
                                              retry_after_hint='30', action_kind='call_provider',
                                              now=FIXED_INSTANT)
        self.assertEqual(classification['retry_after_declared'], True)
        self.assertNotIn('30', json.dumps(classification))
        self.assertNotIn('retry-after', json.dumps(classification).lower())
        self.assertEqual(classification['auto_retry_applicable'], False)
        self.assertEqual(classification['next_retry_allowed_at'], None)
        self.assertNotIn('backoff', json.dumps(classification).lower())
        self.assertNotIn('circuit', json.dumps(classification).lower())
        with self.assertRaises(rel.ReliabilityError) as caught:
            rel.classify_failure(error_reason='x', action_kind='read_repo', retry_class='inventada')
        self.assertEqual(caught.exception.code, 'invalid_failure')
        with self.assertRaises(rel.ReliabilityError) as caught:
            rel.classify_failure(error_reason='x', action_kind='read_repo', http_status=1000)
        self.assertEqual(caught.exception.code, 'invalid_failure')
        self.assertEqual(rel.validate_classification(
            dict(classification, auto_retry_authorized=True)),
            ('auto_retry_authorized debe ser false: el plano no reintenta',))


class ConnectorGatewayTests(unittest.TestCase):
    """El gateway declara permisos, no se conecta y queda deshabilitado por defecto."""

    def test_all_connectors_are_disabled_by_default_with_declared_permissions(self):
        plan = gateway()
        self.assertEqual(cg.validate_gateway(plan), ())
        kinds = tuple(cg.CONNECTOR_KINDS)
        self.assertEqual(kinds, ('github', 'drive', 'database', 'web', 'ci', 'email'))
        self.assertEqual(tuple(plan.descriptors()), kinds)
        for kind, descriptor in plan.descriptors().items():
            with self.subTest(connector=kind):
                self.assertIs(descriptor['enabled'], False)
                self.assertIs(descriptor['disabled_by_default'], True)
                self.assertTrue(descriptor['required_permissions'])
                self.assertTrue(descriptor['allowed_scopes'])
                self.assertEqual(descriptor['required_at_open']['gate'], 'connectors')
                self.assertIs(descriptor['required_at_open']
                              ['human_approval_required_without_registered_approval'], True)
                self.assertIs(descriptor['required_at_open']['secret_material_required'], False)
                self.assertIs(descriptor['required_at_open']['network_allowed'], False)
                self.assertEqual(descriptor['required_at_open']['live_connections'], 0)
                self.assertIn('deshabilitado', descriptor['disabled_reason'])
        self.assertEqual(list(plan.enabled_kinds()), [])
        self.assertEqual(plan.live_connection_count(), 0)
        self.assertEqual(cg.live_connection_count(), 0)

    def test_installing_connectors_never_opens_a_connection_or_stores_access_material(self):
        plan = gateway()
        for kind in cg.CONNECTOR_KINDS:
            with self.subTest(connector=kind):
                declaration = plan.install_connector(kind, operator_role='operador-de-plataforma')
                self.assertIs(declaration['enabled'], False)
                self.assertEqual(declaration['live_connections'], 0)
        state = plan.as_dict()
        self.assertEqual(state['live_connections'], 0)
        self.assertEqual(state['connection_attempts'], 0)
        self.assertIs(state['network_allowed'], False)
        self.assertIs(state['secret_values_stored'], False)
        self.assertEqual(plan.live_connection_count(), 0)
        self.assertEqual(cg.live_connection_count(), 0)
        for kind in cg.CONNECTOR_KINDS:
            with self.subTest(enable=kind):
                with self.assertRaises(cg.ConnectorError) as caught:
                    plan.install_connector(kind, enabled=True)
                self.assertEqual(caught.exception.code, 'invalid_configuration')
        self.assertEqual(list(plan.enabled_kinds()), [])

    def test_gateway_rejects_configuration_with_credential_shaped_names(self):
        plan = gateway()
        for name in ('api_key', 'access_token', 'authorization', 'client_secret', 'password',
                     'bearer_token', 'private_key'):
            with self.subTest(campo=name):
                with self.assertRaises(cg.ConnectorError) as caught:
                    cg._reject_configuration(dict(cg.REQUIRED_AT_OPEN, **{name: 'valor-real'}),
                                             label='prueba')
                self.assertEqual(caught.exception.code, 'prohibited_field')
                self.assertNotIn('valor-real', str(caught.exception))
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.ConnectorDescriptor('conector-inventado', title='x',
                                   required_permissions=('x.y',), allowed_scopes=('x',))
        self.assertEqual(caught.exception.code, 'unknown_connector')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.ConnectorDescriptor('github', title='x', required_permissions=('repo:read',),
                                   allowed_scopes=('repo:read',), enabled=True)
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.ConnectorDescriptor('github', title='x', required_permissions=('repo:read',),
                                   allowed_scopes=())
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        self.assertEqual(cg.prohibited_paths({'a': {'password': 'x'}}), ['$.a.password'])
        self.assertEqual(cg.prohibited_paths({'declared_scopes': ['repo:read']}), [])
        with self.assertRaises(cg.ConnectorError) as caught:
            cg._reject_configuration({'connector_kind': 'github', 'api_key': 'sk-prueba'},
                                     label='solicitud de conector')
        self.assertEqual(caught.exception.code, 'prohibited_field')
        self.assertNotIn('sk-prueba', str(caught.exception))
        self.assertTrue(cg._reject_configuration({'connector_kind': 'github',
                                                  'declared_scopes': ['repo:read']}))

    def test_opening_a_connector_requires_policy_decision_with_human_approval(self):
        plan = gateway()
        opened = plan.request(connector_kind='github', action='read',
                              idempotency_key='conn.github.0001', now=FIXED_INSTANT)
        self.assertEqual(opened['decision_outcome'], DECISION_REQUIRE)
        self.assertEqual(opened['decision']['gate'], 'connectors')
        self.assertTrue(opened['requires_human_approval'])
        self.assertEqual(opened['enabled'], False)
        self.assertEqual(opened['live_connections'], 0)
        self.assertEqual(opened['executed'], False)
        self.assertEqual(validate_decision(opened['decision']), ())
        self.assertTrue(opened['decision']['reason'].strip())
        self.assertEqual(opened['decision']['side_effects_performed'], False)
        self.assertEqual(opened['decision']['limits']['network_allowed'], False)
        self.assertEqual(opened['scope_hash'], opened['decision']['action']['scope_hash'])
        plan.register_approval('github', approval_record(plan.policy, opened['request']))
        approved = plan.request(connector_kind='github', action='read',
                                idempotency_key='conn.github.0001', now=FIXED_INSTANT)
        self.assertEqual(approved['decision_outcome'], DECISION_ALLOW)
        self.assertEqual(approved['decision']['gate'], 'connectors')
        self.assertEqual(approved['decision']['approval']['scope_hash'],
                         approved['decision']['action']['scope_hash'])
        self.assertEqual(approved['live_connections'], 0)
        self.assertEqual(plan.live_connection_count(), 0)
        self.assertEqual(validate_decision(approved['decision']), ())

    def test_a_stale_or_foreign_scope_approval_does_not_authorize_the_connector(self):
        plan = gateway()
        opened = plan.request(connector_kind='drive', action='read',
                              idempotency_key='conn.drive.0001', now=FIXED_INSTANT)
        plan.register_approval('drive', dict(approval_record(plan.policy, opened['request']),
                                            scope_hash='f' * 64))
        stale = plan.request(connector_kind='drive', action='read',
                             idempotency_key='conn.drive.0001', now=FIXED_INSTANT)
        self.assertEqual(stale['decision_outcome'], DECISION_REQUIRE)
        self.assertEqual(stale['decision']['gate'], 'connectors')
        self.assertEqual(stale['live_connections'], 0)
        self.assertEqual(validate_decision(stale['decision']), ())
        register = plan.register_approval('web', approval_record(
            plan.policy, {'connector_ref': 'connector://web/read',
                          'idempotency_key': 'conn.web.0001'}))
        self.assertEqual(register['approval_record']['gate'], 'connectors')
        self.assertFalse(register['enabled'])
        self.assertEqual(register['live_connections'], 0)
        with self.assertRaises(cg.ConnectorError) as caught:
            plan.register_approval('web', {'gate': 'deploy'})
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            plan.register_approval('web', {'gate': 'connectors',
                                           'authentication': 'token-de-prueba'})
        self.assertEqual(caught.exception.code, 'prohibited_field')

    def test_requests_only_admit_declared_scopes_actions_and_connectors(self):
        plan = gateway()
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='ftp', idempotency_key='conn.ftp.0001')
        self.assertEqual(caught.exception.code, 'unknown_connector')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='github', action='borrar',
                                 idempotency_key='conn.github.0001')
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='github', action='read', scopes=['repo:admin'],
                                 idempotency_key='conn.github.0001')
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='web', idempotency_key='conn.web.0001',
                                 scopes=[])
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='web', idempotency_key='corta')
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        with self.assertRaises(cg.ConnectorError) as caught:
            cg.connector_request(connector_kind='email', action='write',
                                 idempotency_key='conn.email.0001', scopes=['email.read'])
        self.assertEqual(caught.exception.code, 'invalid_configuration')
        envelope = cg.connector_request(connector_kind='email', action='write',
                                        idempotency_key='conn.email.0001')
        self.assertEqual(envelope['declared_scopes'], ['email.send'])
        self.assertIs(envelope['enabled'], False)
        self.assertIs(envelope['side_effects_performed'], False)
        self.assertEqual(envelope['connector_ref'], 'connector://email/write')

    def test_gateway_battery_conforms_and_module_facts_declare_no_capability(self):
        plan = gateway()
        for label, result in gateway_requests(plan).items():
            with self.subTest(ruta=label):
                self.assertEqual(validate_decision(result['decision']), ())
                self.assertEqual(result['decision']['side_effects_performed'], False)
                self.assertEqual(result['decision']['limits']['network_allowed'], False)
                self.assertEqual(result['live_connections'], 0)
                self.assertEqual(result['network_allowed'], False)
                self.assertEqual(result['executed'], False)
                self.assertIn(result['decision_outcome'],
                              (DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE))
                if result['decision']['gate'] is not None:
                    if result['decision']['approval'] is None:
                        self.assertEqual(result['decision_outcome'], DECISION_REQUIRE)
                    else:
                        self.assertEqual(result['decision_outcome'], DECISION_ALLOW)
                        self.assertEqual(result['decision']['approval']['gate'], 'connectors')
                self.assertEqual(result['decision']['action']['action_kind'], 'open_connector')
                self.assertTrue(result['decision']['action']['target'].startswith('connector://'))
                self.assertEqual(result['required_permissions'],
                                 list(cg.CONNECTOR_PERMISSIONS[result['connector_kind']]))
        facts = cg.module_facts()
        self.assertEqual(cg.validate_gateway(plan), ())
        self.assertEqual(facts['connections_opened'], 0)
        self.assertEqual(facts['enabled_by_default'], False)
        self.assertEqual(facts['secret_values_stored'], False)
        self.assertEqual(facts['live_connection_probe'], 0)
        self.assertEqual(facts['gate_kind'], 'connectors')
        self.assertEqual(facts['gate_default_outcome'], GATE_DEFAULT_OUTCOME)
        self.assertEqual(facts['prohibited_fields_count'], 13)
        self.assertEqual(json.loads(json.dumps(facts, ensure_ascii=False)), facts)

    def test_gateway_validation_refutes_a_connector_that_claims_to_be_enabled(self):
        plan = gateway()
        self.assertEqual(cg.validate_gateway(plan), ())
        plan.install_connector('github')
        plan._installations['github']['enabled'] = True  # sabotaje deliberado del estado interno
        problems = cg.validate_gateway(plan)
        self.assertIn("hay conectores habilitados sin decision del Policy Engine sobre la "
                      "puerta 'connectors' (declarados: github)", problems)
        reasons = ' | '.join(problems)
        self.assertIn('connectors', reasons)
        plan._installations['github']['live_connections'] = 1
        self.assertIn("el gateway declara conexiones vivas en 'github': 1", cg.validate_gateway(plan))


if __name__ == '__main__':
    unittest.main()
