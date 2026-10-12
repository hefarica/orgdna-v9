"""Pruebas offline del ApprovalReceipt v1 (O1). Los 14 falsificadores del operador se
ejecutan como ASERCIONES DE BLOQUEO, no como comprobaciones de serializacion.

Verifica el contrato `orgdna-approval-receipt-v1`: campos obligatorios, enlace exigido
`receipt.graph_sha256 == compute_graph_sha256(TaskGraph)`, aprobador siempre declarativo
(`authenticated` False) sin autenticacion ficticia, `can_execute()` que devuelve False ante
cualquier duda, serializacion canonica con round-trip sin perdida, contrato de incrustacion
de los cinco canales, y la REGLA DE ORO: el modulo no altera `compute_graph_sha256()`, el
`TaskGraph` serializado, el manifiesto, los permisos, los defaults de autonomia ni la
politica de persistencia efimera.

Solo biblioteca estandar. Sin red, sin claves, sin proveedores, sin dependencias nuevas, sin
tocar DSH. El unico archivo que estas pruebas escriben es la cache de bytecode del interprete.
"""
import ast
import dataclasses
import hashlib
import inspect
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import approval_receipt as ar
from engine import policy_engine, task_graph

#: Politica fija del fixture: mismo hash en cualquier llamada y en cualquier proceso.
FIXTURE_POLICY = policy_engine.Policy.default(created_at='2026-10-10T00:00:00.000000Z')

SUITE_ROOT = Path(__file__).resolve().parent
MODULE_PATH = SUITE_ROOT / 'engine' / 'approval_receipt.py'
MANIFEST_PATH = SUITE_ROOT / 'MANIFIESTO_SHA256.txt'
DOC_PATH = SUITE_ROOT / 'docs' / 'PLATAFORMA_APROBACION_V1.md'

MANIFEST_SHA256_R0 = 'f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96'
GOLDEN_GRAPH_SHA256 = 'c0690c65c91bc5b55be60136f3f4f9b7453eb04708794286e0a54027998d8b53'
INTEGRATION_EXPECTED = ('engine/task_graph.py', 'engine/approval_receipt.py',
                        'tests_platform_approval_receipt.py', 'docs/PLATAFORMA_APROBACION_V1.md',
                        'docs/plataforma/taskspec.schema.json')

NOW = '2026-10-10T00:00:00.000000Z'
LATER = '2026-10-10T12:00:00.000000Z'
EXPIRY = '2026-10-11T00:00:00.000000Z'
AFTER_EXPIRY = '2026-10-12T00:00:00.000000Z'

ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'datetime',
                                  'hashlib', 'json', 'math', 're'})
ENGINE_IMPORT_NAMES = frozenset({'policy_engine', 'task_graph'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'os', 'io', 'pathlib', 'socket', 'ssl', 'urllib', 'http',
                                    'ftplib', 'smtplib', 'telnetlib', 'subprocess', 'shutil',
                                    'tempfile', 'importlib', 'ctypes', 'multiprocessing',
                                    'asyncio', 'webbrowser', 'pickle', 'sqlite3', 'signals'})
FORBIDDEN_CALLS = frozenset({'open', 'eval', 'exec', 'compile', '__import__', 'input', 'breakpoint'})
FORBIDDEN_ATTRIBUTES = frozenset({'system', 'popen', 'Popen', 'check_call', 'check_output', 'run',
                                  'urlopen', 'connect', 'sendall', 'recv', 'write', 'writelines',
                                  'write_text', 'write_bytes', 'read_text', 'read_bytes', 'unlink',
                                  'mkdir', 'rmdir', 'remove', 'spawn', 'fork', 'execv'})
FORBIDDEN_FUNCTION_NAMES = re.compile(r'(?i)^(grant|install|enable|authorize|elevate|unlock|permit|'
                                      r'promote|dispatch|execute|run|deploy|send)')
MUTABLE_CONTAINERS = (list, dict, set, bytearray)
PUBLIC_FUNCTIONS = ('active_receipt', 'answer_security_questions', 'append_receipt', 'approve',
                    'can_execute', 'canonical_receipt_json', 'deny', 'embed_receipt',
                    'evaluate_execution', 'graph_hash_of', 'graph_schema_of', 'issue_receipt',
                    'parse_receipt', 'policy_reference', 'receipt_fingerprint', 'receipt_payload',
                    'revoke_receipt', 'verify_receipt')
FALSIFIER_TESTS = tuple('test_falsifier_%02d_' % index for index in range(1, 15))


def declaration(task_id, depends_on=(), **overrides):
    """Declaracion valida del contrato v1; `overrides` la muta para el caso negativo."""
    record = {'taskspec_version': '1', 'task_id': task_id, 'title': 'Tarea ' + task_id,
              'intent': 'Declarar el resultado pretendido sin ejecutarlo.',
              'agent_ref': 'perfil-observador', 'autonomy_level': 'observe',
              'depends_on': list(depends_on),
              'budget': {'tokens': 1000, 'money_usd': 0.0, 'time_seconds': 60, 'requests': 5},
              'acceptance_criteria': [{'criterion': 'El grafo se construye y su hash es estable.',
                                       'verify': 'python -m unittest tests_platform_task_graph.py'}],
              'falsifiers': [{'falsifier_id': 'fr01',
                              'statement': 'El hash cambia entre dos construcciones equivalentes.',
                              'how_detected': 'Reconstruir el grafo y comparar graph_sha256.'}],
              'idempotency_key': 'idem-' + task_id + '-0001',
              'evidence_refs': ['docs/plataforma/taskspec.schema.json'],
              'created_at': '2026-10-10T00:00:00Z'}
    record.update(overrides)
    return record


def golden_graph():
    """Fixture dorado de I1, replicado literalmente: su hash es el literal congelado."""
    return task_graph.build_graph([declaration('t1'), declaration('t2', ('t1',)),
                                   declaration('t3', ('t1',))])


def scoped_graph():
    """Grafo de trabajo: una tarea de observacion y una de escritura ya aprobada."""
    return task_graph.build_graph([declaration('ta'), declaration('tb', ('ta',)),
                                   declaration('ex', autonomy_level='execute-approved')], approved=True)


def scope_for(task_ids, **overrides):
    fields = {'task_ids': task_ids, 'max_autonomy': 'execute-approved',
              'allowed_write_scopes': ('engine/aprobado.py',), 'allowed_connectors': ('local-fs',),
              'max_requests': 10, 'max_output_tokens': 2000, 'max_estimated_cost_usd': 10.0}
    fields.update(overrides)
    return ar.ApprovalScope(**fields)


def current_policy():
    return FIXTURE_POLICY


def approval(graph, **overrides):
    options = {'role': 'operador', 'policy': current_policy(),
               'scope': scope_for(tuple(task.task_id for task in graph.tasks)),
               'now': NOW, 'expires_at': EXPIRY}
    options.update(overrides)
    return ar.approve(graph, **options)


def run_options(**overrides):
    options = {'now': LATER, 'policy': current_policy()}
    options.update(overrides)
    return options


def module_tree():
    return ast.parse(MODULE_PATH.read_text('utf-8'), filename=str(MODULE_PATH))


def manifest_entries():
    entries = []
    for line in MANIFEST_PATH.read_text('utf-8').splitlines():
        digest, name = line.split('  ', 1)
        entries.append((digest, name))
    return tuple(entries)


class FalsifierTests(unittest.TestCase):
    """Los 14 falsificadores exigidos por el operador: cada uno BLOQUEA la ejecucion."""

    def test_falsifier_01_graph_without_receipt_blocks_execute_approved(self):
        graph = scoped_graph()
        self.assertFalse(ar.can_execute('ex', graph, None, **run_options()))
        verdict = ar.evaluate_execution(graph, None, 'ex', **run_options())
        self.assertEqual(verdict['blockers'], ('receipt_missing',))
        self.assertFalse(verdict['allowed'])
        answers = ar.answer_security_questions(graph, 'ex', None, **run_options())
        self.assertFalse(answers['approved'])
        self.assertFalse(answers['scope_covers'])

    def test_falsifier_02_correct_hash_approves_only_inside_scope(self):
        graph = scoped_graph()
        receipt = approval(graph, scope=scope_for(('ta',)))
        self.assertTrue(ar.can_execute('ta', graph, receipt, **run_options()))
        self.assertFalse(ar.can_execute('tb', graph, receipt, **run_options()))
        blockers = ar.evaluate_execution(graph, receipt, 'tb', **run_options())['blockers']
        self.assertIn('task_out_of_scope', blockers)

    def test_falsifier_03_receipt_with_another_graph_hash_blocks(self):
        graph = scoped_graph()
        other = task_graph.build_graph([declaration('zz')])
        foreign = approval(other, scope=scope_for(('zz',)))
        self.assertNotEqual(foreign.graph_sha256, ar.graph_hash_of(graph))
        self.assertFalse(ar.can_execute('ta', graph, foreign, **run_options()))
        self.assertIn('graph_hash_mismatch',
                      ar.evaluate_execution(graph, foreign, 'ta', **run_options())['blockers'])

    def test_falsifier_04_graph_modified_after_approval_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph)
        self.assertEqual(receipt.graph_sha256, task_graph.compute_graph_sha256(graph.tasks))
        modified = task_graph.build_graph([declaration('ta'), declaration('tb', ('ta',)),
                                           declaration('ex', autonomy_level='execute-approved'),
                                           declaration('nueva')], approved=True)
        self.assertNotEqual(ar.graph_hash_of(modified), receipt.graph_sha256)
        self.assertFalse(ar.can_execute('ta', modified, receipt, **run_options()))
        self.assertIn('graph_hash_mismatch',
                      ar.evaluate_execution(modified, receipt, 'ta', **run_options())['blockers'])
        renamed = task_graph.build_graph([declaration('ta', title='Otro titulo')])
        self.assertNotEqual(ar.graph_hash_of(renamed), ar.graph_hash_of(
            task_graph.build_graph([declaration('ta')])))

    def test_falsifier_05_task_id_out_of_scope_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph, scope=scope_for(('ta',)))
        self.assertFalse(ar.can_execute('tb', graph, receipt, **run_options()))
        blockers = ar.evaluate_execution(graph, receipt, 'tb', **run_options())['blockers']
        self.assertIn('task_out_of_scope', blockers)
        self.assertNotIn('autonomy_not_covered', blockers)
        self.assertFalse(ar.can_execute('ex', graph, receipt,
                                        **run_options(requested_write_scopes=('engine/aprobado.py',))))

    def test_falsifier_06_execute_approved_with_prepare_only_receipt_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph, scope=scope_for(tuple(task.task_id for task in graph.tasks),
                                                 max_autonomy='prepare'))
        blockers = ar.evaluate_execution(graph, receipt, 'ex',
                                         **run_options(requested_write_scopes=('engine/aprobado.py',)))['blockers']
        self.assertIn('autonomy_not_covered', blockers)
        self.assertFalse(ar.can_execute('ex', graph, receipt,
                                        **run_options(requested_write_scopes=('engine/aprobado.py',))))
        self.assertTrue(ar.can_execute('ta', graph, receipt, **run_options()))

    def test_falsifier_07_tool_or_connector_not_included_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph)
        options = run_options(requested_connectors=('conector-remoto',))
        self.assertFalse(ar.can_execute('ta', graph, receipt, **options))
        self.assertIn('connector_not_covered', ar.evaluate_execution(graph, receipt, 'ta', **options)['blockers'])
        write_options = run_options(requested_write_scopes=('fuera/del/alcance.py',))
        self.assertFalse(ar.can_execute('ex', graph, receipt, **write_options))
        self.assertIn('write_scope_not_covered',
                      ar.evaluate_execution(graph, receipt, 'ex', **write_options)['blockers'])
        allowed = run_options(requested_connectors=('local-fs',))
        self.assertTrue(ar.can_execute('ta', graph, receipt, **allowed))

    def test_falsifier_08_budget_exceeding_the_receipt_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph)
        cases = (('tokens_exceeded', {'requested_output_tokens': 2001}),
                 ('requests_exceeded', {'requested_requests': 11}),
                 ('cost_exceeded', {'requested_cost_usd': 10.01}))
        for code, overrides in cases:
            with self.subTest(code=code):
                options = run_options(**overrides)
                self.assertFalse(ar.can_execute('ta', graph, receipt, **options))
                self.assertIn(code, ar.evaluate_execution(graph, receipt, 'ta', **options)['blockers'])
        tight = approval(graph, scope=scope_for(tuple(task.task_id for task in graph.tasks),
                                                max_output_tokens=10))
        blockers = ar.evaluate_execution(graph, tight, 'ta', **run_options())['blockers']
        self.assertIn('tokens_exceeded', blockers)
        self.assertFalse(ar.can_execute('ta', graph, tight, **run_options()))

    def test_falsifier_09_expired_receipt_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph)
        self.assertTrue(ar.can_execute('ta', graph, receipt, **run_options()))
        expired = run_options(now=AFTER_EXPIRY)
        self.assertFalse(ar.can_execute('ta', graph, receipt, **expired))
        self.assertIn('receipt_expired', ar.evaluate_execution(graph, receipt, 'ta', **expired)['blockers'])
        self.assertFalse(receipt.is_active(now=AFTER_EXPIRY))
        self.assertTrue(receipt.is_active(now=LATER))
        self.assertIn('receipt_expired', ar.verify_receipt(receipt, graph=graph, now=AFTER_EXPIRY)['problems'])

    def test_falsifier_10_revoked_receipt_blocks(self):
        graph = scoped_graph()
        receipt = approval(graph)
        revoked = ar.revoke_receipt(receipt, role='operador', reason='cambio de alcance',
                                   now='2026-10-10T13:00:00.000000Z')
        self.assertEqual(revoked.decision, 'revoked')
        self.assertFalse(ar.can_execute('ta', graph, revoked, **run_options()))
        blockers = ar.evaluate_execution(graph, revoked, 'ta', **run_options())['blockers']
        self.assertIn('receipt_not_approved', blockers)
        self.assertIn('receipt_revoked', blockers)
        self.assertFalse(revoked.is_active(now=LATER))
        # La revocacion surte efecto desde su revoked_at: antes de ese instante la auditoria
        # punto a punto sigue viendo la aprobacion vigente; despues, ninguna.
        self.assertIs(ar.active_receipt((receipt, revoked), graph_sha256=receipt.graph_sha256, now=LATER),
                      receipt)
        self.assertIsNone(ar.active_receipt((receipt, revoked), graph_sha256=receipt.graph_sha256,
                                            now='2026-10-10T14:00:00.000000Z'))
        problems = ar.verify_receipt(revoked, graph=graph, now=LATER)['problems']
        self.assertIn('receipt_revoked', problems)
        self.assertIn('receipt_not_approved', problems)

    def test_falsifier_11_authenticated_false_cannot_be_presented_as_verified(self):
        with self.assertRaises(ar.AuthenticationClaimError):
            ar.Approver(role='operador', authenticated=True)
        with self.assertRaises(ar.AuthenticationClaimError):
            ar.Approver(role='operador', mode='authenticated_user')
        graph = scoped_graph()
        payload = approval(graph).to_dict()
        self.assertIs(payload['approver']['authenticated'], False)
        for name in ('signature', 'signed', 'verified', 'attestation', 'identity_verified', 'jwt',
                     'fingerprint', 'public_key', 'certificate'):
            with self.subTest(claim=name):
                tampered = dict(payload, approver=dict(payload['approver'], **{name: 'declarado'}))
                with self.assertRaises(ar.ApprovalReceiptError) as caught:
                    ar.parse_receipt(tampered)
                self.assertEqual(caught.exception.code, 'authentication_claim')
        answers = ar.answer_security_questions(graph, 'ta', approval(graph), **run_options())
        self.assertIs(answers['approver']['authenticated'], False)
        self.assertIs(answers['approver']['identity_verified'], False)
        self.assertEqual(answers['approver']['mode'], 'declarative_role')
        self.assertEqual(ar.APPROVER_AUTHENTICATION, policy_engine.APPROVER_AUTHENTICATION)

    def test_falsifier_12_same_approval_twice_does_not_duplicate_effect(self):
        graph = scoped_graph()
        receipt = approval(graph)
        first = ar.append_receipt((), receipt)
        second = ar.append_receipt(first['receipts'], receipt)
        self.assertTrue(first['appended'])
        self.assertFalse(second['appended'])
        self.assertEqual(second['duplicate_of'], receipt.receipt_id)
        self.assertEqual(second['duplicates'], (receipt.receipt_id,))
        self.assertEqual(second['receipt_count'], 1)
        self.assertEqual(len(second['receipts']), 1)
        self.assertEqual(first['receipts'][0].receipt_sha256, receipt.receipt_sha256)

    def test_falsifier_13_altered_receipt_fails_verification(self):
        graph = scoped_graph()
        receipt = approval(graph)
        original = receipt.to_dict()
        self.assertTrue(ar.verify_receipt(original, graph=graph, now=LATER)['valid'])
        alterations = (('approval_scope', lambda payload: payload['approval_scope'].__setitem__('max_requests', 99)),
                       ('graph_sha256', lambda payload: payload.__setitem__('graph_sha256', '0' * 64)),
                       ('decision', lambda payload: payload.__setitem__('decision', 'denied')),
                       ('notes', lambda payload: payload.__setitem__('notes', 'otra nota')),
                       ('policy', lambda payload: payload['policy'].__setitem__('policy_hash', '1' * 64)))
        for label, mutate in alterations:
            with self.subTest(field=label):
                tampered = json.loads(json.dumps(original))
                mutate(tampered)
                self.assertNotEqual(ar.receipt_fingerprint(tampered), original['receipt_sha256'])
                self.assertIn('receipt_hash_mismatch',
                              ar.verify_receipt(tampered, graph=graph, now=LATER)['problems'])
                with self.assertRaises(ar.ReceiptIntegrityError):
                    ar.parse_receipt(tampered)
        resealed = json.loads(json.dumps(original))
        resealed['approval_scope']['max_requests'] = 99
        resealed['receipt_sha256'] = ar.receipt_fingerprint(resealed)
        # LIMITE DECLARADO: el sello no es una firma. Quien puede recalcularlo produce un recibo
        # coherente consigo mismo; su alcance alterado (99) pasa a ser el vigente de ESA
        # declaracion y solo el enlace con el grafo y la politica siguen acotando la ejecucion.
        self.assertTrue(ar.verify_receipt(resealed, graph=graph, now=LATER)['valid'])
        self.assertTrue(ar.can_execute('ta', graph, resealed, **run_options(requested_requests=50)))
        self.assertFalse(ar.can_execute('ta', graph, resealed, **run_options(requested_requests=100)))

    def test_falsifier_14_manifest_remains_intact(self):
        entries = manifest_entries()
        mismatched = sorted(name for digest, name in entries
                            if hashlib.sha256((SUITE_ROOT / name).read_bytes()).hexdigest() != digest)
        self.assertEqual(mismatched, [])
        listed = {name for _, name in entries}
        self.assertNotIn('MANIFIESTO_SHA256.txt', listed)
        if 'engine/approval_receipt.py' not in listed:
            # Estado al cerrar O1: el manifiesto es el de R0, byte a byte.
            self.assertEqual(len(entries), 268)
            self.assertEqual(hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(), MANIFEST_SHA256_R0)
        else:
            # Estado posterior a t9 (D-R0-2): el manifiesto se regenera por diseño y debe
            # cubrir los artefactos de la plataforma; la integridad entrada-a-archivo sigue
            # siendo la garantia comprobable y la huella nueva no es una regresion.
            for expected in INTEGRATION_EXPECTED:
                with self.subTest(listed=expected):
                    self.assertIn(expected, listed)


class ReceiptShapeTests(unittest.TestCase):
    """Forma del recibo v1: campos obligatorios, inmutabilidad, enlace y validaciones."""

    def test_required_fields_are_present_and_typed(self):
        receipt = approval(scoped_graph())
        payload = receipt.to_dict()
        self.assertLessEqual(set(ar.RECEIPT_REQUIRED_FIELDS), set(payload))
        self.assertLessEqual(set(ar.RECEIPT_REQUIRED_FIELDS), set(ar.RECEIPT_FIELDS))
        self.assertEqual(payload['kind'], 'task_graph_approval')
        self.assertEqual(payload['receipt_schema'], 'orgdna-approval-receipt-v1')
        self.assertEqual(payload['receipt_version'], '1')
        self.assertIn(payload['decision'], ar.DECISIONS)
        self.assertEqual(set(payload['approval_scope']), set(ar.APPROVAL_SCOPE_FIELDS))
        self.assertEqual(set(payload['approver']), set(ar.APPROVER_FIELDS))
        self.assertEqual(payload['approver']['mode'], 'declarative_role')
        self.assertEqual(set(payload['policy']), set(ar.POLICY_REFERENCE_FIELDS))
        self.assertIn(payload['expires_at'], (None, EXPIRY))
        self.assertEqual(ar.GRAPH_SCHEMAS, ('orgdna-task-graph-v1',))
        self.assertIsNone(payload['revocation'])

    def test_receipt_is_immutable(self):
        receipt = approval(scoped_graph())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.graph_sha256 = '0' * 64
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.approver.role = 'otro'
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.approval_scope.max_requests = 99
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.policy.policy_hash = '0' * 64

    def test_link_equals_compute_graph_sha256(self):
        graph = scoped_graph()
        receipt = approval(graph)
        self.assertEqual(receipt.graph_sha256, task_graph.compute_graph_sha256(graph.tasks))
        self.assertEqual(receipt.graph_sha256, ar.graph_hash_of(graph))
        self.assertEqual(receipt.graph_schema, 'orgdna-task-graph-v1')
        self.assertEqual(receipt.graph_schema, ar.graph_schema_of(graph))
        self.assertEqual(ar.graph_hash_of(golden_graph()), GOLDEN_GRAPH_SHA256)

    def test_issue_refuses_a_wrong_hash_or_schema(self):
        graph = scoped_graph()
        with self.assertRaises(ar.GraphHashMismatchError):
            approval(graph, graph_sha256='0' * 64)
        with self.assertRaises(ar.GraphSchemaMismatchError):
            approval(graph, graph_schema='orgdna-task-graph-v9')
        with self.assertRaises(ar.GraphSchemaMismatchError):
            ar.ApprovalReceipt(graph_sha256=ar.graph_hash_of(graph), graph_schema='otro-esquema',
                               approval_scope=scope_for(('ta',)), approver=ar.Approver(role='operador'),
                               policy=ar.policy_reference(current_policy()), created_at=NOW)
        with self.assertRaises(ar.InvalidFieldError):
            ar.graph_hash_of({'no': 'es un grafo'})
        with self.assertRaises(ar.InvalidFieldError):
            ar.graph_schema_of(None)

    def test_identifier_and_seal_are_content_derived(self):
        graph = scoped_graph()
        first = approval(graph)
        second = approval(graph)
        self.assertEqual(first.receipt_id, second.receipt_id)
        self.assertEqual(first.receipt_sha256, second.receipt_sha256)
        self.assertEqual(first.receipt_sha256, ar.receipt_fingerprint(first))
        other = approval(graph, notes='otra nota')
        self.assertNotEqual(other.receipt_id, first.receipt_id)
        self.assertNotEqual(other.receipt_sha256, first.receipt_sha256)
        self.assertTrue(ar.RECEIPT_ID_PATTERN.fullmatch(first.receipt_id))
        self.assertEqual(first.receipt_id, ar.parse_receipt(first.to_dict()).receipt_id)

    def test_domain_validations(self):
        policy = current_policy()
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=())
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=('ta', 'ta'))
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=('ta',), max_autonomy='autonomous')
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=('ta',), max_requests=-1)
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=('ta',), max_requests=True)
        with self.assertRaises(ar.InvalidFieldError):
            ar.ApprovalScope(task_ids=('ta',), max_estimated_cost_usd=float('inf'))
        with self.assertRaises(ar.InvalidFieldError):
            ar.PolicyReference(policy_version='1', policy_hash='no-es-hash')
        with self.assertRaises(ar.InvalidFieldError):
            ar.PolicyReference(policy_version='1', policy_hash=policy.policy_hash, approval_required='si')
        with self.assertRaises(ar.InvalidFieldError):
            ar.Approver(role='')
        with self.assertRaises(ar.InvalidFieldError):
            approval(scoped_graph(), expires_at='2026-10-09T00:00:00.000000Z')
        with self.assertRaises(ar.InvalidFieldError):
            ar.issue_receipt(scoped_graph(), role='operador', policy=current_policy(),
                             scope=scope_for(('ta',)), decision='quizas', now=NOW)
        with self.assertRaises(ar.InvalidFieldError):
            ar.issue_receipt(scoped_graph(), role='operador', policy='no-es-politica',
                             scope=scope_for(('ta',)), now=NOW)

    def test_denied_and_expired_receipts_are_never_active(self):
        graph = scoped_graph()
        denied = ar.deny(graph, role='operador', policy=current_policy(), scope=scope_for(('ta',)),
                         now=NOW, notes='no autorizado')
        self.assertEqual(denied.decision, 'denied')
        self.assertNotEqual(denied.receipt_id, approval(graph, scope=scope_for(('ta',))).receipt_id)
        self.assertFalse(denied.is_active(now=LATER))
        self.assertFalse(ar.can_execute('ta', graph, denied, **run_options()))
        self.assertIn('receipt_not_approved', ar.evaluate_execution(graph, denied, 'ta', **run_options())['blockers'])
        expired = ar.issue_receipt(graph, role='operador', policy=current_policy(), scope=scope_for(('ta',)),
                                   decision='expired', now=NOW)
        self.assertEqual(expired.decision, 'expired')
        self.assertFalse(expired.is_active(now=LATER))
        self.assertFalse(ar.can_execute('ta', graph, expired, **run_options()))
        self.assertIn('receipt_not_approved',
                      ar.evaluate_execution(graph, expired, 'ta', **run_options())['blockers'])


class CanonicalizationTests(unittest.TestCase):
    """Serializacion canonica, round-trip sin perdida y contrato de incrustacion."""

    def test_canonical_json_is_deterministic_and_round_trips(self):
        receipt = approval(scoped_graph())
        text = ar.canonical_receipt_json(receipt)
        self.assertEqual(text, ar.canonical_receipt_json(approval(scoped_graph())))
        self.assertEqual(ar.parse_receipt(text), receipt)
        self.assertEqual(ar.parse_receipt(json.loads(text)), receipt)
        self.assertEqual(ar.parse_receipt(receipt.to_dict()), receipt)
        self.assertEqual(ar.receipt_fingerprint(receipt.to_dict()), receipt.receipt_sha256)
        self.assertEqual(json.loads(text)['receipt_sha256'], receipt.receipt_sha256)
        revoked = ar.revoke_receipt(receipt, role='operador', reason='prueba', now=LATER)
        self.assertEqual(ar.parse_receipt(ar.canonical_receipt_json(revoked)), revoked)
        self.assertEqual(revoked.revocation.supersedes, receipt.receipt_id)

    def test_embedding_contract_covers_the_five_channels(self):
        receipt = approval(scoped_graph())
        self.assertEqual(len(ar.CHANNELS), 5)
        self.assertEqual(tuple(entry[0] for entry in ar.CHANNEL_CONTRACT), ar.CHANNELS)
        for channel in ar.CHANNELS:
            with self.subTest(channel=channel):
                embedded = ar.embed_receipt(receipt, channel)
                self.assertEqual(embedded['channel'], channel)
                self.assertEqual(embedded['receipt_schema'], ar.RECEIPT_SCHEMA)
                self.assertEqual(embedded['receipt_sha256'], receipt.receipt_sha256)
                self.assertEqual(ar.parse_receipt(embedded['payload']), receipt)
                self.assertIn(embedded['key'], ('approval_receipt', 'approval_receipts'))
        with self.assertRaises(ar.UnknownChannelError):
            ar.embed_receipt(receipt, 'canal-inventado')

    def test_payload_is_a_copy_and_inputs_are_not_mutated(self):
        graph = scoped_graph()
        before = graph.to_dict()
        receipt = approval(graph)
        payload = ar.receipt_payload(receipt)
        payload['notes'] = 'alterado fuera'
        payload['approval_scope']['max_requests'] = 999
        payload['approver']['role'] = 'otro'
        self.assertEqual(receipt.notes, '')
        self.assertEqual(receipt.approval_scope.max_requests, 10)
        self.assertEqual(receipt.approver.role, 'operador')
        self.assertEqual(graph.to_dict(), before)
        embedded = ar.embed_receipt(receipt, ar.CHANNEL_SAVED_PROJECT)
        embedded['payload']['notes'] = 'alterado fuera'
        self.assertEqual(receipt.notes, '')

    def test_no_store_is_opened_and_no_file_is_written(self):
        source = MODULE_PATH.read_text('utf-8')
        self.assertNotIn('data/', source)
        graph = scoped_graph()
        with patch('builtins.open', side_effect=AssertionError('el modulo no debe abrir ficheros')):
            receipt = approval(graph)
            ar.verify_receipt(receipt.to_dict(), graph=graph, now=LATER)
            ar.parse_receipt(ar.canonical_receipt_json(receipt))
            ar.evaluate_execution(graph, receipt, 'ta', **run_options())
            ar.embed_receipt(receipt, ar.CHANNEL_APPROVAL_ARTIFACT)
            ar.append_receipt((), receipt)
            ar.active_receipt((receipt,), graph_sha256=receipt.graph_sha256, now=LATER)
            ar.answer_security_questions(graph, 'ta', receipt, **run_options())


class FlowAndLedgerTests(unittest.TestCase):
    """Flujo aprobar/denegar, localizacion del recibo vigente y respuestas separadas."""

    def test_approve_and_deny_emit_evidence_of_the_same_link(self):
        graph = scoped_graph()
        granted = approval(graph)
        refused = ar.deny(graph, role='operador', policy=current_policy(), scope=scope_for(('ta',)),
                          now=NOW, notes='denegado')
        self.assertEqual((granted.decision, refused.decision), ('approved', 'denied'))
        self.assertEqual(granted.graph_sha256, refused.graph_sha256)
        self.assertEqual(granted.graph_schema, refused.graph_schema)
        self.assertEqual(granted.approver.role, refused.approver.role)
        self.assertTrue(ar.can_execute('ta', graph, granted, **run_options()))
        self.assertFalse(ar.can_execute('ta', graph, refused, **run_options()))

    def test_verify_receipt_declares_problems_without_authorizing(self):
        graph = scoped_graph()
        receipt = approval(graph)
        policy_hash = current_policy().policy_hash
        self.assertTrue(ar.verify_receipt(receipt, graph=graph, policy_hash=policy_hash, now=LATER)['valid'])
        wrong_policy = ar.verify_receipt(receipt, graph=graph, policy_hash='1' * 64, now=LATER)
        self.assertIn('policy_hash_mismatch', wrong_policy['problems'])
        other = task_graph.build_graph([declaration('zz')])
        self.assertIn('graph_hash_mismatch', ar.verify_receipt(receipt, graph=other, now=LATER)['problems'])
        self.assertEqual(ar.verify_receipt({'no': 'es-un-recibo'})['problems'], ('receipt_invalid',))
        self.assertEqual(ar.verify_receipt(None)['problems'], ('receipt_invalid',))
        self.assertFalse(ar.verify_receipt(receipt, graph='no-es-un-grafo', now=LATER)['valid'])

    def test_answering_the_five_questions_separately(self):
        graph = scoped_graph()
        receipt = approval(graph)
        answers = ar.answer_security_questions(graph, 'ta', receipt, **run_options())
        self.assertTrue(answers['graph_intact'])
        self.assertTrue(answers['approved'])
        self.assertTrue(answers['active'])
        self.assertTrue(answers['scope_covers'])
        self.assertIs(answers['approver']['authenticated'], False)
        self.assertEqual(answers['blockers'], ())
        blind = ar.answer_security_questions(graph, 'ta', None, **run_options())
        self.assertTrue(blind['graph_intact'])
        self.assertFalse(blind['approved'])
        self.assertFalse(blind['active'])
        self.assertFalse(blind['scope_covers'])
        self.assertIn('receipt_missing', blind['blockers'])
        mutated = task_graph.build_graph([declaration('ta')])
        questions = ar.answer_security_questions(mutated, 'ta', receipt, **run_options())
        self.assertFalse(questions['graph_intact'])
        self.assertFalse(questions['approved'])
        self.assertIn('graph_hash_mismatch', questions['blockers'])

    def test_can_execute_returns_false_on_every_doubt(self):
        graph = scoped_graph()
        receipt = approval(graph)
        self.assertFalse(ar.can_execute('ta', graph, receipt))                      # sin politica en vigor
        self.assertFalse(ar.can_execute('ta', graph, receipt, now='ayer'))          # marca invalida
        self.assertFalse(ar.can_execute('ta', graph, receipt, policy='no-es-politica', **{'now': LATER}))
        self.assertFalse(ar.can_execute('ta', graph, {'no': 'es-un-recibo'}, **run_options()))
        self.assertFalse(ar.can_execute('ta', 'no-es-un-grafo', receipt, **run_options()))
        self.assertFalse(ar.can_execute('inexistente', graph, receipt, **run_options()))
        self.assertFalse(ar.can_execute(42, graph, receipt, **run_options()))
        self.assertFalse(ar.can_execute('ta', graph, receipt, **run_options(requested_requests='muchas')))
        self.assertTrue(ar.can_execute('ta', graph, receipt, **run_options(policy_hash=receipt.policy.policy_hash)))
        self.assertTrue(ar.can_execute('ta', graph, receipt, **run_options(policy=current_policy())))
        self.assertTrue(ar.can_execute(task_graph.build_taskspec(declaration('ta')), graph, receipt,
                                       **run_options(policy=current_policy())))
        self.assertFalse(ar.can_execute(task_graph.build_taskspec(declaration('ta', title='Otro titulo')),
                                        graph, receipt, **run_options(policy=current_policy())))


class GuardAndInertnessTests(unittest.TestCase):
    """Blindaje de lectura reutilizando los guards del Policy Engine e inercia del modulo."""

    def test_read_guard_reuses_the_policy_engine_criteria(self):
        graph = scoped_graph()
        payload = approval(graph).to_dict()
        for name in ('password', 'apiKey', 'access-token', 'pendingConsent', 'private_key'):
            with self.subTest(field=name):
                tampered = json.loads(json.dumps(payload))
                tampered[name] = 'no-declarable'
                with self.assertRaises(ar.ApprovalReceiptError) as caught:
                    ar.parse_receipt(tampered)
                self.assertEqual(caught.exception.code, 'prohibited_field')
        self.assertEqual(ar.AUTHENTICATION_EXEMPT_FIELDS, (('approver', 'authenticated'),))
        # Todo nombre que el criterio del Policy Engine considera declaracion de autenticacion
        # se rechaza; la unica exencion es `approver.authenticated` con valor False.
        for claim in policy_engine.AUTHENTICATION_CLAIM_KEYS:
            with self.subTest(claim=claim):
                tampered = json.loads(json.dumps(payload))
                tampered[claim] = 'declarado'
                with self.assertRaises(ar.AuthenticationClaimError):
                    ar.parse_receipt(tampered)
        with self.assertRaises(ar.ProhibitedFieldError):
            ar.parse_receipt(dict(payload, cookie='x'))
        with self.assertRaises(ar.ProhibitedFieldError):
            ar.parse_receipt(dict(payload, authorization='Bearer x'))

    def test_module_imports_only_stdlib_and_engine(self):
        roots, relative = set(), set()
        for node in ast.walk(module_tree()):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative.update(alias.name for alias in node.names)
                    continue
                roots.add((node.module or '').split('.')[0])
        self.assertEqual(roots & FORBIDDEN_IMPORT_ROOTS, set())
        self.assertLessEqual(roots, ALLOWED_IMPORT_ROOTS | ENGINE_IMPORT_NAMES)
        self.assertEqual(relative, {'policy_engine', 'task_graph'})

    def test_module_opens_no_file_and_no_network(self):
        calls, attributes = set(), set()
        for node in ast.walk(module_tree()):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    attributes.add(node.func.attr)
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))
        self.assertEqual(calls & FORBIDDEN_CALLS, set())
        self.assertEqual(attributes & FORBIDDEN_ATTRIBUTES, set())
        source = MODULE_PATH.read_text('utf-8')
        for absent in ('://', 'open(', 'http.client'):
            with self.subTest(token=absent):
                self.assertNotIn(absent, source)

    def test_module_has_no_mutable_global_state(self):
        offenders = sorted(name for name, value in vars(ar).items()
                           if isinstance(value, MUTABLE_CONTAINERS) and name != '__builtins__')
        self.assertEqual(offenders, [])
        for name in ('RECEIPT_FIELDS', 'RECEIPT_REQUIRED_FIELDS', 'APPROVAL_SCOPE_FIELDS',
                     'APPROVER_FIELDS', 'POLICY_REFERENCE_FIELDS', 'REVOCATION_FIELDS', 'DECISIONS',
                     'CHANNELS', 'CHANNEL_CONTRACT', 'BLOCKER_CODES', 'VERIFICATION_PROBLEMS',
                     'ERROR_CLASSES', 'ERROR_CODES', 'AUTHENTICATION_EXEMPT_FIELDS'):
            with self.subTest(constant=name):
                self.assertIsInstance(getattr(ar, name), tuple)

    def test_public_surface_is_declared_and_grants_nothing(self):
        own_functions = sorted(name for name, value in vars(ar).items()
                               if inspect.isfunction(value)
                               and getattr(value, '__module__', None) == ar.__name__
                               and not name.startswith('_'))
        self.assertEqual(own_functions, sorted(PUBLIC_FUNCTIONS))
        for name in own_functions:
            with self.subTest(function=name):
                self.assertIsNone(FORBIDDEN_FUNCTION_NAMES.match(name))

    def test_functions_do_not_mutate_module_state(self):
        before = {name: id(value) for name, value in vars(ar).items()}
        snapshot = sorted((name, type(value).__name__) for name, value in vars(ar).items())
        graph = scoped_graph()
        receipt = approval(graph)
        ar.can_execute('ta', graph, receipt, **run_options())
        ar.can_execute('ta', graph, None, **run_options())
        ar.verify_receipt(receipt.to_dict(), graph=graph, now=LATER)
        ar.parse_receipt(ar.canonical_receipt_json(receipt))
        ar.embed_receipt(receipt, ar.CHANNEL_DOWNLOADED_DIAGNOSTIC)
        ar.append_receipt((receipt,), receipt)
        ar.active_receipt((receipt,), graph_sha256=receipt.graph_sha256, now=LATER)
        ar.answer_security_questions(graph, 'ta', receipt, **run_options())
        after = {name: id(value) for name, value in vars(ar).items()}
        self.assertEqual(before, after)
        self.assertEqual(snapshot, sorted((name, type(value).__name__) for name, value in vars(ar).items()))


class DocumentationTests(unittest.TestCase):
    """La documentacion contiene literalmente el bloque del operador y su semantica."""

    def test_documentation_contains_the_operator_invariant_block(self):
        text = DOC_PATH.read_text('utf-8')
        for fragment in ('INVARIANTE DE APROBACIÓN',
                         'O1-APPROVAL-RECEIPT-LINK-01',
                         'TaskGraphHash != ProofOfApproval',
                         'ApprovalReceipt.graph_sha256 == compute_graph_sha256(TaskGraph)',
                         'REGLA DE ORO',
                         '¿el grafo es íntegro?', '¿fue aprobado?', '¿sigue vigente?',
                         '¿el alcance de la tarea cabe en la aprobación?', '¿quién aprobó?',
                         'NO se afirma identidad autenticada',
                         'denegar emite ApprovalReceipt(decision=',
                         'aprobar emite recibo inmutable',
                         'la persistencia local es opcional y explícita',
                         'la AUSENCIA de archivo de recibo NO se interpreta como aprobación',
                         'project/approval_receipts.jsonl', 'project/generation_diagnostics.json',
                         'project/artifacts/'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_documentation_declares_the_channels_and_the_falsifiers(self):
        text = DOC_PATH.read_text('utf-8')
        for channel in ar.CHANNELS:
            with self.subTest(channel=channel):
                self.assertIn(channel, text)
        for index in range(1, 15):
            with self.subTest(falsifier=index):
                self.assertIn('F%d ' % index, text)


class SuiteSizeTests(unittest.TestCase):
    """Criterio del encargo: al menos 18 casos y los 14 falsificadores presentes."""

    def test_module_declares_at_least_eighteen_cases_and_the_fourteen_falsifiers(self):
        module = sys.modules[__name__]
        case_count = unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
        self.assertGreaterEqual(case_count, 18)
        names = {name for name, value in vars(module).items()
                 if isinstance(value, type) and issubclass(value, unittest.TestCase)
                 for name in dir(value) if name.startswith('test_')}
        for prefix in FALSIFIER_TESTS:
            with self.subTest(prefix=prefix):
                self.assertTrue(any(name.startswith(prefix) for name in names),
                                'falta el falsificador ' + prefix)


if __name__ == '__main__':
    unittest.main(verbosity=2)
