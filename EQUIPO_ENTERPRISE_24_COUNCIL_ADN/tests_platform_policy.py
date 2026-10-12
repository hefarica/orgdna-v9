"""Pruebas del Policy Engine (flujo I3): politica, puertas humanas y decision inerte.

Offline y solo biblioteca estandar. Cubre el contrato congelado
`docs/plataforma/policy.schema.json`: totalidad de la decision, las ocho puertas humanas
con su falsificador, limites por organizacion, hash versionado, invalidacion de
aprobaciones previas, guard de credenciales y ausencia total de efectos.

Run: python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_policy.py" -v
"""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import inspect
import json
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import patch

from engine import policy_engine as policy_engine_module
from engine.policy_engine import (ACTION_KINDS, APPROVAL_FIELDS, APPROVAL_IDENTITY_KIND,
                                  APPROVAL_AUTHENTICATION_CLAIM, APPROVER_AUTHENTICATION, AUTONOMY_CEILING_DEFAULT,
                                  AUTONOMY_LEVELS, DECISION_ALLOW, DECISION_DENY,
                                  DECISION_FIELDS, DECISION_OPTIONAL_FIELDS, DECISION_OUTCOMES,
                                  DECISION_REQUIRE, GATES, GATE_DEFAULT_OUTCOME,
                                  INERT_BY_DEFAULT, LIMIT_FIELDS, PROHIBITED_FIELDS,
                                  PROHIBITED_FIELDS_SOURCE, Policy, PolicyError,
                                  default_policy, evaluate, find_authentication_claims,
                                  find_prohibited_fields, validate_decision)
from engine.project_store import FORBIDDEN_FIELDS

FIXED_INSTANT = '2026-10-10T00:00:00Z'
SCHEMA_PATH = Path(__file__).resolve().parent / 'docs' / 'plataforma' / 'policy.schema.json'
#: Huella publicada en docs/PLATAFORMA_CONTRATOS_V1.md (seccion 8.2) para el contrato de R0.
FROZEN_SCHEMA_SHA256 = 'c6026c70690115c7e37ac0d080510f6f19b36cabc76c89701e7d5443bf54118e'

#: Accion representativa de cada puerta obligatoria (falsificador de su valor por defecto).
GATE_FALSIFIERS = {
    'secrets': {'action_kind': 'call_provider', 'target': 'proveedor-externo'},
    'spend': {'action_kind': 'spend_money', 'target': 'proveedor-externo'},
    'connectors': {'action_kind': 'open_connector', 'target': 'conector-github'},
    'write': {'action_kind': 'write_file', 'target': 'data/informe.json'},
    'install': {'action_kind': 'install_package', 'target': 'paquete-extra'},
    'push': {'action_kind': 'push', 'target': 'origin/main'},
    'merge': {'action_kind': 'merge', 'target': 'origin/main'},
    'deploy': {'action_kind': 'deploy', 'target': 'entorno-produccion'},
}

#: Categorias cuyo valor por defecto no puede ser allow (criterio de aceptacion de I3).
NEVER_ALLOW_BY_DEFAULT = ('write', 'spend', 'install', 'push', 'merge', 'deploy')

ALLOWED_MODULE_IMPORTS = {'json', 'hashlib', 're', 'copy', 'datetime', 'project_store', '__future__'}
FORBIDDEN_MODULE_IMPORTS = {'socket', 'urllib', 'http', 'subprocess', 'requests', 'ftplib',
                            'smtplib', 'telnetlib', 'asyncio', 'os', 'shutil', 'pathlib',
                            'importlib', 'ctypes', 'multiprocessing', 'threading', 'ssl',
                            'xmlrpc', 'webbrowser', 'pickle', 'sqlite3', 'tempfile', 'glob',
                            'sys', 'pty', 'signal', 'resource', 'platform', 'getpass'}
FORBIDDEN_CALL_NAMES = {'open', 'eval', 'exec', 'compile', '__import__', 'input', 'print',
                        'breakpoint'}
FORBIDDEN_ATTRIBUTES = {'system', 'popen', 'run', 'check_output', 'check_call', 'spawn',
                        'spawnv', 'urlopen', 'urlretrieve', 'connect', 'connect_ex', 'bind',
                        'listen', 'send', 'sendall', 'recv', 'write_text', 'write_bytes',
                        'read_text', 'read_bytes', 'unlink', 'mkdir', 'makedirs', 'rename',
                        'remove', 'rmdir', 'socketpair', 'fork'}


def make_policy(organization='orgdna-plataforma', **kwargs):
    kwargs.setdefault('created_at', FIXED_INSTANT)
    return Policy.default(organization, **kwargs)


def scoped_action(policy, action):
    """Accion con el alcance exigido por la politica vigente."""
    return dict(action, scope_hash=policy.scope_hash(action))


def approval_for(policy, action, *, gate=None, role='operador-de-plataforma',
                 approved_at=FIXED_INSTANT, one_shot=True, scope_hash=None, **extra):
    """Aprobacion declarativa valida (o manipulada por el caso de prueba)."""
    scoped = scoped_action(policy, action)
    record = {
        'gate': gate if gate is not None else policy.gates_for(action['action_kind'])[0],
        'approver_role': role,
        'approved_at': approved_at,
        'scope_hash': scope_hash if scope_hash is not None else scoped['scope_hash'],
        'one_shot': one_shot,
    }
    record.update(extra)
    return scoped, record


def default_allows_by_default(policy, category):
    """Comprobador que debe fallar si el valor por defecto de la categoria fuese allow."""
    action = GATE_FALSIFIERS[category]
    return policy.default_outcome(action['action_kind']) == DECISION_ALLOW


def default_allows_decision(policy, category):
    action = GATE_FALSIFIERS[category]
    return evaluate(policy, action, now=FIXED_INSTANT)['decision'] == DECISION_ALLOW


def decision_battery(policy):
    """Decisiones de todas las rutas del motor, etiquetadas, para comprobaciones masivas."""
    deploy = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
    scoped, record = approval_for(policy, deploy)
    cases = {
        'puerta sin aprobacion': evaluate(policy, deploy, now=FIXED_INSTANT),
        'puerta con aprobacion valida': evaluate(policy, scoped, approval=record, now=FIXED_INSTANT),
        'accion sin puertas': evaluate(policy, {'action_kind': 'read_repo', 'target': 'src/app.py'},
                                       now=FIXED_INSTANT),
        'accion multipuerta': evaluate(policy, {'action_kind': 'call_provider', 'target': 'proveedor'},
                                       now=FIXED_INSTANT),
        'aprobacion no conforme': evaluate(policy, scoped, approval={'gate': 'deploy'},
                                           now=FIXED_INSTANT),
        'aprobacion de otro alcance': evaluate(
            policy, scoped, approval=dict(record, scope_hash='a' * 64), now=FIXED_INSTANT),
        'aprobacion consumida': evaluate(policy, scoped, approval=record,
                                         consumed_scope_hashes=[record['scope_hash']],
                                         now=FIXED_INSTANT),
        'aprobacion que declara autenticacion': evaluate(
            policy, scoped, approval=dict(record, signature='firma-de-ejemplo'), now=FIXED_INSTANT),
        'alcance declarado no vigente': evaluate(policy, dict(deploy, scope_hash='b' * 64),
                                                 now=FIXED_INSTANT),
        'acceso fuera de alcance': evaluate(policy, {'action_kind': 'read_repo', 'target': '../etc/passwd'},
                                            now=FIXED_INSTANT),
        'coste sobre el maximo': evaluate(policy, {'action_kind': 'spend_money', 'target': 'api'},
                                          declared_cost_usd=10.0, now=FIXED_INSTANT),
        'autonomia sobre el techo': evaluate(policy, {'action_kind': 'run_tests', 'target': 'suite'},
                                             autonomy_level='execute-approved', now=FIXED_INSTANT),
        'tipo denegado': evaluate(
            make_policy(overrides={'denied_action_kinds': ['merge']}),
            {'action_kind': 'merge', 'target': 'origin/main'}, now=FIXED_INSTANT),
    }
    return cases


class ContractConformanceTests(unittest.TestCase):
    """El motor consume el contrato congelado de R0, no una copia interpretada."""

    def test_frozen_schema_is_consumed_byte_to_byte(self):
        raw = SCHEMA_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FROZEN_SCHEMA_SHA256)
        schema = json.loads(raw.decode('utf-8'))
        self.assertEqual(schema['version_field'], 'policy_contract_version')
        self.assertEqual(schema['properties']['policy_contract_version']['const'], '1')
        self.assertEqual(tuple(schema['required']), DECISION_FIELDS)
        self.assertEqual(set(schema['properties']) - set(DECISION_FIELDS), set(DECISION_OPTIONAL_FIELDS))
        self.assertEqual([gate for gate in schema['properties']['gate']['enum'] if gate], list(GATES))
        self.assertIsNone(schema['properties']['gate']['enum'][-1])
        self.assertEqual(schema['$defs']['action']['properties']['action_kind']['enum'], list(ACTION_KINDS))
        self.assertEqual(schema['$defs']['approval_record']['required'], list(APPROVAL_FIELDS))
        self.assertEqual(schema['$defs']['mandatory_gates']['properties']['default_outcome']['const'],
                         GATE_DEFAULT_OUTCOME)
        self.assertEqual(schema['$defs']['mandatory_gates']['properties']['gates']['const'], list(GATES))
        self.assertEqual(set(schema['prohibited_fields']), set(PROHIBITED_FIELDS))
        self.assertTrue(schema['inert_by_default'])
        self.assertEqual(schema['$defs']['limits']['properties']['network_allowed']['const'], False)

    def test_prohibited_fields_reuse_the_literal_motor_list(self):
        self.assertEqual(set(PROHIBITED_FIELDS), FORBIDDEN_FIELDS)
        self.assertEqual(len(PROHIBITED_FIELDS), 13)
        self.assertEqual(PROHIBITED_FIELDS_SOURCE, 'engine/project_store.py:19')

    def test_every_decision_path_conforms_to_the_contract(self):
        for label, decision in decision_battery(make_policy()).items():
            with self.subTest(ruta=label):
                self.assertEqual(validate_decision(decision), ())
                self.assertIn(decision['decision'], DECISION_OUTCOMES)
                self.assertTrue(decision['reason'].strip())
                self.assertEqual(decision['side_effects_performed'], False)
                self.assertEqual(decision['limits']['network_allowed'], False)
                self.assertEqual(find_prohibited_fields(decision, 'decision'), [])
                self.assertTrue(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$',
                                         decision['evaluated_at']))
                self.assertTrue(set(decision) <= set(DECISION_FIELDS + DECISION_OPTIONAL_FIELDS))
                if decision['decision'] == DECISION_REQUIRE:
                    self.assertIn(decision['gate'], GATES)
                if decision['decision'] == DECISION_ALLOW and decision['gate'] is not None:
                    self.assertEqual(decision['approval']['scope_hash'], decision['action']['scope_hash'])

    def test_ungated_allow_is_explicit_and_never_dressed_as_approved(self):
        """Pin de la lectura aplicada de `allOf` para acciones que no levantan ninguna puerta.

        El esquema congelado pide `approval` objeto en toda decision `allow`; con `gate`
        obligatorio en `require_human_approval`, una accion de solo lectura no tendria salida
        valida salvo `deny`. La anotacion `$defs.mandatory_gates` limita la exigencia de
        aprobacion a las ocho puertas, y esta prueba fija esa lectura: allow sin puerta, sin
        aprobacion, sin disfrazarla de autorizacion humana, y con la ruta del operador que
        prefiera la lectura literal (`denied_action_kinds` -> deny).
        """
        policy = make_policy()
        for kind in ('read_repo', 'run_tests'):
            with self.subTest(accion=kind):
                self.assertEqual(policy.gates_for(kind), ())
                decision = evaluate(policy, {'action_kind': kind, 'target': 'src/app.py'},
                                    now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_ALLOW)
                self.assertIsNone(decision['gate'])
                self.assertIsNone(decision['approval'])
                self.assertEqual([rule['rule_id'] for rule in decision['matched_rules']], ['default.open'])
                self.assertEqual(validate_decision(decision), ())
                closed = make_policy(overrides={'denied_action_kinds': [kind]})
                denied = evaluate(closed, {'action_kind': kind, 'target': 'src/app.py'},
                                  now=FIXED_INSTANT)
                self.assertEqual(denied['decision'], DECISION_DENY)
                self.assertIsNone(denied['approval'])
                self.assertEqual(validate_decision(denied), ())
        gated_allows = [decision for decision in decision_battery(policy).values()
                        if decision['decision'] == DECISION_ALLOW and decision['gate'] is not None]
        self.assertTrue(gated_allows)
        for decision in gated_allows:
            with self.subTest(ruta=decision['reason'][:40]):
                self.assertIsNotNone(decision['approval'])
                self.assertEqual(decision['approval']['gate'], decision['gate'])
                self.assertEqual(decision['approval']['scope_hash'], decision['action']['scope_hash'])

    def test_decisions_are_pure_data(self):
        for label, decision in decision_battery(make_policy()).items():
            with self.subTest(ruta=label):
                revived = json.loads(json.dumps(decision, ensure_ascii=False))
                self.assertEqual(revived, decision)
                self.assertEqual(validate_decision(revived), ())


class PolicyDataTests(unittest.TestCase):
    """La politica es central, por organizacion, versionada y con hash reproducible."""

    def test_policy_is_central_per_organization_versioned_and_hashed(self):
        acme = make_policy('acme')
        beta = make_policy('beta')
        self.assertEqual(acme.policy_id, 'orgdna.platform.acme')
        self.assertEqual(acme.organization_id, 'acme')
        self.assertEqual(beta.policy_id, 'orgdna.platform.beta')
        self.assertNotEqual(acme.policy_hash, beta.policy_hash)
        self.assertGreaterEqual(acme.policy_revision, 1)
        self.assertTrue(re.match(r'^[0-9a-f]{64}$', acme.policy_hash))
        self.assertEqual(acme.limits, beta.limits)
        data = acme.as_dict()
        self.assertEqual(data['policy_contract_version'], '1')
        self.assertTrue(data['inert_by_default'])
        self.assertEqual(data['organization_id'], 'acme')
        self.assertEqual(data['gate_defaults']['deploy'], GATE_DEFAULT_OUTCOME)
        self.assertTrue(default_policy('acme', created_at=FIXED_INSTANT).policy_hash == acme.policy_hash)

    def test_policy_hash_is_stable_and_changes_with_any_value(self):
        base = make_policy('acme')
        self.assertEqual(base.policy_hash, make_policy('acme').policy_hash)
        self.assertEqual(base.policy_hash, Policy.from_dict(base.as_dict()).policy_hash)
        variants = {
            'revision': base.with_overrides({'limits': {'spend_usd_max': 1.0}}),
            'spend_usd_max': make_policy('acme', overrides={'limits': {'spend_usd_max': 250.0}}),
            'autonomy_ceiling': make_policy('acme', overrides={'limits': {'autonomy_ceiling': 'prepare'}}),
            'gate_defaults': make_policy('acme', overrides={'gate_defaults': {'deploy': 'deny'}}),
            'action_gates': make_policy('acme', overrides={'action_gates': {'deploy': ['deploy', 'push']}}),
            'denied_action_kinds': make_policy('acme', overrides={'denied_action_kinds': ['merge']}),
            'acceso': make_policy('acme', overrides={'target_deny_patterns': [
                {'rule_id': 'access.extra', 'pattern': r'^secreto'}]}),
            'policy_id': make_policy('acme', policy_id='orgdna.platform.acme.estricta'),
            'revision_explicita': base.with_overrides({'limits': {'spend_usd_max': 1.0}}, revision=9),
        }
        hashes = {label: variant.policy_hash for label, variant in variants.items()}
        for label, candidate in hashes.items():
            with self.subTest(cambio=label):
                self.assertNotEqual(candidate, base.policy_hash)
        self.assertEqual(len(set(hashes.values())), len(hashes))

    def test_unsupported_contract_version_is_rejected(self):
        data = make_policy().as_dict()
        data['policy_contract_version'] = '2'
        with self.assertRaises(PolicyError) as raised:
            Policy.from_dict(data)
        self.assertEqual(raised.exception.code, 'unsupported_version')

    def test_unsafe_policy_values_are_rejected(self):
        data = make_policy().as_dict()
        data['inert_by_default'] = False
        with self.assertRaises(PolicyError) as raised:
            Policy.from_dict(data)
        self.assertEqual(raised.exception.code, 'invalid_policy')
        with self.assertRaises(PolicyError) as raised:
            make_policy(overrides={'limits': {'network_allowed': True}})
        self.assertEqual(raised.exception.code, 'invalid_policy')
        with self.assertRaises(PolicyError) as raised:
            make_policy(overrides={'gate_defaults': {'deploy': 'allow', 'inexistente': 'allow'}})
        self.assertEqual(raised.exception.code, 'invalid_policy')
        with self.assertRaises(PolicyError) as raised:
            make_policy(overrides={'limits': {'autonomy_ceiling': 'sin-limite'}})
        self.assertEqual(raised.exception.code, 'invalid_policy')

    def test_policy_change_requires_a_new_revision(self):
        base = make_policy('acme')
        changed = base.with_overrides({'limits': {'spend_usd_max': 10.0}})
        self.assertEqual(changed.policy_revision, base.policy_revision + 1)
        self.assertEqual(base.with_overrides({'limits': {'spend_usd_max': 10.0}}, revision=4).policy_revision, 4)
        with self.assertRaises(PolicyError) as raised:
            base.with_overrides({})
        self.assertEqual(raised.exception.code, 'invalid_policy')


class MandatoryGateTests(unittest.TestCase):
    """Las ocho puertas humanas: puerta explicita y salida por defecto require_human_approval."""

    def test_all_eight_gates_have_explicit_gate_and_safe_default(self):
        policy = make_policy()
        self.assertEqual(tuple(policy.gate_defaults), GATES)
        for gate in GATES:
            with self.subTest(puerta=gate):
                self.assertEqual(policy.gate_default_outcome(gate), GATE_DEFAULT_OUTCOME)
                self.assertEqual(GATE_DEFAULT_OUTCOME, DECISION_REQUIRE)
                self.assertIn(gate, policy.limits['approvals_required'])
        self.assertTrue(INERT_BY_DEFAULT)

    def _gate_falsifier(self, gate):
        policy = make_policy()
        action = dict(GATE_FALSIFIERS[gate])
        self.assertEqual(policy.gates_for(action['action_kind'])[0], gate)
        decision = evaluate(policy, action, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_REQUIRE)
        self.assertEqual(decision['gate'], gate)
        self.assertTrue(decision['reason'].strip())
        self.assertEqual(validate_decision(decision), ())
        scoped, record = approval_for(policy, action, gate=gate)
        allowed = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(allowed['decision'], DECISION_ALLOW)
        self.assertEqual(allowed['gate'], gate)
        self.assertEqual(allowed['approval']['gate'], gate)
        self.assertEqual(allowed['approval']['scope_hash'], scoped['scope_hash'])
        self.assertEqual(validate_decision(allowed), ())

    def test_gate_secrets_requires_human_approval(self):
        self._gate_falsifier('secrets')

    def test_gate_spend_requires_human_approval(self):
        self._gate_falsifier('spend')

    def test_gate_connectors_requires_human_approval(self):
        self._gate_falsifier('connectors')

    def test_gate_write_requires_human_approval(self):
        self._gate_falsifier('write')

    def test_gate_install_requires_human_approval(self):
        self._gate_falsifier('install')

    def test_gate_push_requires_human_approval(self):
        self._gate_falsifier('push')

    def test_gate_merge_requires_human_approval(self):
        self._gate_falsifier('merge')

    def test_gate_deploy_requires_human_approval(self):
        self._gate_falsifier('deploy')

    def test_no_default_allows_mutating_categories(self):
        policy = make_policy()
        for category in NEVER_ALLOW_BY_DEFAULT:
            with self.subTest(categoria=category):
                self.assertFalse(default_allows_by_default(policy, category))
                self.assertFalse(default_allows_decision(policy, category))
                decision = evaluate(policy, GATE_FALSIFIERS[category], now=FIXED_INSTANT)
                self.assertNotEqual(decision['decision'], DECISION_ALLOW)
                self.assertEqual(decision['decision'], DECISION_REQUIRE)

    def test_default_allow_checker_is_not_vacuous(self):
        permissive = make_policy(overrides={'gate_defaults': {gate: DECISION_ALLOW for gate in GATES}})
        for category in NEVER_ALLOW_BY_DEFAULT:
            with self.subTest(categoria=category):
                self.assertTrue(default_allows_by_default(permissive, category))
                self.assertTrue(default_allows_decision(permissive, category))
                decision = evaluate(permissive, GATE_FALSIFIERS[category], now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_ALLOW)
                self.assertIsNone(decision['approval'])
                self.assertEqual(validate_decision(decision), ())


class DecisionTotalityTests(unittest.TestCase):
    """No existe ruta sin decision para una accion conforme al contrato."""

    def test_every_action_kind_gets_a_decision_with_reason(self):
        policy = make_policy()
        contexts = (
            ({}, 'sin contexto'),
            ({'approval': 'no-es-un-registro'}, 'aprobacion no conforme'),
            ({'declared_cost_usd': 0.0}, 'coste cero declarado'),
            ({'requires_secret_material': True}, 'declara material secreto'),
        )
        seen = set()
        for kind in ACTION_KINDS:
            for extra, label in contexts:
                with self.subTest(accion=kind, contexto=label):
                    action = {'action_kind': kind, 'target': 'destino-de-prueba'}
                    decision = evaluate(policy, action, now=FIXED_INSTANT, **extra)
                    seen.add(decision['decision'])
                    self.assertIn(decision['decision'], DECISION_OUTCOMES)
                    self.assertTrue(decision['reason'].strip())
                    self.assertLessEqual(len(decision['reason']), 600)
                    self.assertEqual(validate_decision(decision), ())
                    self.assertTrue(decision['matched_rules'])
                    for rule in decision['matched_rules']:
                        self.assertIn(rule['outcome'], DECISION_OUTCOMES)
                        self.assertTrue(re.match(r'^[a-z0-9][a-z0-9._-]{1,63}$', rule['rule_id']))
                    if decision['decision'] == DECISION_REQUIRE:
                        self.assertIn(decision['gate'], GATES)
                    if decision['decision'] == DECISION_ALLOW:
                        self.assertEqual(decision['side_effects_performed'], False)
        self.assertEqual(seen, {DECISION_ALLOW, DECISION_REQUIRE})

    def test_require_human_approval_always_names_the_levied_gate(self):
        policy = make_policy()
        for kind in ACTION_KINDS:
            gates = policy.gates_for(kind)
            if not gates:
                continue
            with self.subTest(accion=kind):
                decision = evaluate(policy, {'action_kind': kind, 'target': 'destino-de-prueba'},
                                    now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_REQUIRE)
                self.assertEqual(decision['gate'], gates[0])
                self.assertIn('gate.' + gates[0], [rule['rule_id'] for rule in decision['matched_rules']])

    def test_deny_paths_are_reachable_with_specific_reasons(self):
        policy = make_policy()
        denials = {
            'deny.kind.merge': evaluate(make_policy(overrides={'denied_action_kinds': ['merge']}),
                                        {'action_kind': 'merge', 'target': 'origin/main'},
                                        now=FIXED_INSTANT),
            'access.parent_traversal': evaluate(policy, {'action_kind': 'read_repo', 'target': '../etc/passwd'},
                                                now=FIXED_INSTANT),
            'access.drive_absolute': evaluate(policy, {'action_kind': 'write_file', 'target': 'C:/Windows/x'},
                                              now=FIXED_INSTANT),
            'access.system_absolute': evaluate(policy, {'action_kind': 'read_repo', 'target': '/etc/passwd'},
                                               now=FIXED_INSTANT),
            'deny.scope.stale': evaluate(policy, {'action_kind': 'deploy', 'target': 'prod', 'scope_hash': 'c' * 64},
                                         now=FIXED_INSTANT),
            'deny.cost.over_cap': evaluate(policy, {'action_kind': 'spend_money', 'target': 'api'},
                                           declared_cost_usd=0.01, now=FIXED_INSTANT),
            'deny.autonomy.above_ceiling': evaluate(policy, {'action_kind': 'run_tests', 'target': 'suite'},
                                                    autonomy_level='execute-approved', now=FIXED_INSTANT),
        }
        for rule_id, decision in denials.items():
            with self.subTest(regla=rule_id):
                self.assertEqual(decision['decision'], DECISION_DENY)
                self.assertIsNone(decision['gate'])
                self.assertIsNone(decision['approval'])
                self.assertIn(rule_id, [rule['rule_id'] for rule in decision['matched_rules']])
                self.assertTrue(decision['reason'].strip())
                self.assertEqual(validate_decision(decision), ())

    def test_unknown_or_non_conformant_actions_are_rejected_with_typed_errors(self):
        policy = make_policy()
        cases = (
            {'action_kind': 'sudo_rm_rf', 'target': 'x'},
            {'action_kind': 'deploy'},
            {'target': 'x'},
            {'action_kind': 'deploy', 'target': ''},
            {'action_kind': 'deploy', 'target': 'x' * 401},
            {'action_kind': 'deploy', 'target': 'prod', 'scope_hash': 'zz'},
            {'action_kind': 'deploy', 'target': 'prod', 'idempotency_key': 'corta'},
            {'action_kind': 'deploy', 'target': 'prod', 'campo_extra': 1},
        )
        for action in cases:
            with self.subTest(accion=action):
                with self.assertRaises(PolicyError) as raised:
                    evaluate(policy, action, now=FIXED_INSTANT)
                self.assertEqual(raised.exception.code, 'invalid_action')
        with self.assertRaises(PolicyError) as raised:
            evaluate(policy, ['deploy', 'prod'], now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'invalid_action')

    def test_credential_shaped_fields_are_rejected_and_never_echoed(self):
        policy = make_policy()
        bad_actions = (
            {'action_kind': 'read_repo', 'target': 'x', 'apiKey': 'secreto'},
            {'action_kind': 'deploy', 'target': 'prod', 'api-key': 'secreto'},
            {'action_kind': 'read_repo', 'target': 'x', 'Bearer Token': 'secreto'},
            {'action_kind': 'read_repo', 'target': 'x', 'clientSecret': 'secreto'},
        )
        for action in bad_actions:
            with self.subTest(accion=sorted(action)):
                with self.assertRaises(PolicyError) as raised:
                    evaluate(policy, action, now=FIXED_INSTANT)
                self.assertEqual(raised.exception.code, 'prohibited_field')
                self.assertIn(PROHIBITED_FIELDS_SOURCE, str(raised.exception))
        scoped, record = approval_for(policy, {'action_kind': 'deploy', 'target': 'prod'})
        with self.assertRaises(PolicyError) as raised:
            evaluate(policy, scoped, approval=dict(record, access_token='secreto'), now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'prohibited_field')
        with self.assertRaises(PolicyError) as raised:
            make_policy(overrides={'api_key': 'secreto'})
        self.assertEqual(raised.exception.code, 'prohibited_field')
        self.assertEqual(find_prohibited_fields({'a': [{'password': 'x'}]}), ['$.a[0].password'])


class ApprovalGateTests(unittest.TestCase):
    """Puertas humanas: aprobacion declarativa, atada al alcance y sin reutilizacion."""

    def test_approval_must_match_the_action_scope_hash(self):
        policy = make_policy()
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        other = {'action_kind': 'deploy', 'target': 'otro-entorno'}
        scoped, record = approval_for(policy, action, scope_hash=policy.scope_hash(other))
        decision = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_REQUIRE)
        self.assertEqual(decision['gate'], 'deploy')
        self.assertIsNone(decision['approval'])
        self.assertIn('approval.scope_mismatch', [rule['rule_id'] for rule in decision['matched_rules']])
        self.assertEqual(validate_decision(decision), ())

    def test_approval_gate_must_match_the_levied_gate(self):
        policy = make_policy()
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        scoped, record = approval_for(policy, action, gate='write')
        decision = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_REQUIRE)
        self.assertEqual(decision['gate'], 'deploy')
        self.assertIn('approval.gate_mismatch', [rule['rule_id'] for rule in decision['matched_rules']])

    def test_approval_needs_the_action_to_declare_its_scope(self):
        policy = make_policy()
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        _, record = approval_for(policy, action)
        decision = evaluate(policy, action, approval=record, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_REQUIRE)
        self.assertEqual(decision['gate'], 'deploy')
        self.assertIsNone(decision['approval'])
        self.assertIn('approval.scope_missing', [rule['rule_id'] for rule in decision['matched_rules']])

    def test_consumed_one_shot_approval_is_denied_and_not_consumed_by_the_engine(self):
        policy = make_policy()
        action = {'action_kind': 'push', 'target': 'origin/main'}
        scoped, record = approval_for(policy, action)
        self.assertTrue(record['one_shot'])
        first = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(first['decision'], DECISION_ALLOW)
        again = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(again['decision'], DECISION_ALLOW)
        self.assertEqual(again['approval'], record)
        consumed = evaluate(policy, scoped, approval=record,
                            consumed_scope_hashes=[record['scope_hash']], now=FIXED_INSTANT)
        self.assertEqual(consumed['decision'], DECISION_DENY)
        self.assertIsNone(consumed['approval'])
        self.assertIn('deny.approval.consumed', [rule['rule_id'] for rule in consumed['matched_rules']])
        with self.assertRaises(PolicyError) as raised:
            evaluate(policy, scoped, approval=record, consumed_scope_hashes=['no-es-un-hash'],
                     now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'invalid_request')

    def test_invalid_approval_records_are_never_honored(self):
        policy = make_policy()
        action = {'action_kind': 'write_file', 'target': 'data/informe.json'}
        scoped, record = approval_for(policy, action, gate='write')
        invalid = {
            'no es objeto': 'registro',
            'campo no admitido': dict(record, nota='libre'),
            'rol vacio': dict(record, approver_role='   '),
            'instante sin formato': dict(record, approved_at='2026-10-10'),
            'one_shot falso': dict(record, one_shot=False),
            'gate ausente': {key: value for key, value in record.items() if key != 'gate'},
        }
        for label, candidate in invalid.items():
            with self.subTest(caso=label):
                decision = evaluate(policy, scoped, approval=candidate, now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_REQUIRE)
                self.assertEqual(decision['gate'], 'write')
                self.assertIsNone(decision['approval'])
                self.assertIn('approval.invalid', [rule['rule_id'] for rule in decision['matched_rules']])
                self.assertEqual(validate_decision(decision), ())

    def test_policy_change_invalidates_previous_approval(self):
        base = make_policy('acme')
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        scoped, record = approval_for(base, action)
        self.assertEqual(evaluate(base, scoped, approval=record, now=FIXED_INSTANT)['decision'],
                         DECISION_ALLOW)
        changed = base.with_overrides({'limits': {'spend_usd_max': 250.0}})
        self.assertNotEqual(changed.policy_hash, base.policy_hash)
        self.assertNotEqual(changed.scope_hash(action), base.scope_hash(action))
        stale = evaluate(changed, scoped, approval=record, now=FIXED_INSTANT)
        self.assertNotEqual(stale['decision'], DECISION_ALLOW)
        self.assertEqual(stale['decision'], DECISION_DENY)
        self.assertIn('deny.scope.stale', [rule['rule_id'] for rule in stale['matched_rules']])
        rescoped = scoped_action(changed, action)
        reuse = evaluate(changed, rescoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(reuse['decision'], DECISION_REQUIRE)
        self.assertIn('approval.scope_mismatch', [rule['rule_id'] for rule in reuse['matched_rules']])
        fresh = approval_for(changed, action)[1]
        self.assertEqual(evaluate(changed, rescoped, approval=fresh, now=FIXED_INSTANT)['decision'],
                         DECISION_ALLOW)

    def test_engine_never_records_an_authenticated_approval(self):
        policy = make_policy()
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        scoped, record = approval_for(policy, action)
        self.assertEqual(APPROVAL_IDENTITY_KIND, 'declarative_role')
        self.assertEqual(APPROVER_AUTHENTICATION, 'not_verified')
        self.assertEqual(APPROVAL_AUTHENTICATION_CLAIM,
                         'ninguna; el rol del aprobador es declarativo y no verificado')
        self.assertEqual(find_authentication_claims(record, 'approval'), [])
        claims = ('authenticated', 'signature', 'verified', 'jwt', 'notarized', 'identityVerified')
        for claim in claims:
            with self.subTest(declaracion=claim):
                candidate = dict(record)
                candidate[claim] = True if claim in ('authenticated', 'verified', 'identityVerified') else 'dato-de-ejemplo'
                decision = evaluate(policy, scoped, approval=candidate, now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_DENY)
                self.assertIsNone(decision['approval'])
                self.assertIn('deny.approval.authentication_claim',
                              [rule['rule_id'] for rule in decision['matched_rules']])
                self.assertEqual(validate_decision(decision), ())
        self.assertTrue(find_authentication_claims({'signature': 'x'}, 'approval'))
        self.assertTrue(find_authentication_claims({'identityVerified': True}, 'approval'))
        self.assertEqual(find_authentication_claims({'approver_role': 'operador'}, 'approval'), [])
        allowed = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(allowed['decision'], DECISION_ALLOW)
        self.assertEqual(set(allowed['approval']), set(APPROVAL_FIELDS))
        self.assertEqual(validate_decision(allowed), ())


class LimitsTests(unittest.TestCase):
    """Limites por organizacion: acceso, coste, escritura, red y autonomia."""

    def test_limits_are_echoed_unchanged_and_network_is_never_true(self):
        policy = make_policy('acme', overrides={'limits': {'spend_usd_max': 25.0}})
        decision = evaluate(policy, {'action_kind': 'write_file', 'target': 'data/informe.json'},
                            now=FIXED_INSTANT)
        self.assertEqual(decision['limits'], {
            'write_allowed': False,
            'network_allowed': False,
            'autonomy_ceiling': 'observe',
            'approvals_required': list(GATES),
            'spend_usd_max': 25.0,
        })
        self.assertEqual(validate_decision(decision), ())
        self.assertIs(decision['limits']['network_allowed'], False)
        self.assertTrue(set(decision['limits']) <= set(LIMIT_FIELDS))

    def test_cost_above_the_declared_maximum_is_denied(self):
        policy = make_policy('acme', overrides={'limits': {'spend_usd_max': 10.0}})
        action = {'action_kind': 'spend_money', 'target': 'proveedor-externo'}
        over = evaluate(policy, action, declared_cost_usd=10.01, now=FIXED_INSTANT)
        self.assertEqual(over['decision'], DECISION_DENY)
        self.assertIn('deny.cost.over_cap', [rule['rule_id'] for rule in over['matched_rules']])
        within = evaluate(policy, action, declared_cost_usd=10.0, now=FIXED_INSTANT)
        self.assertEqual(within['decision'], DECISION_REQUIRE)
        self.assertEqual(within['gate'], 'spend')
        free = evaluate(policy, action, declared_cost_usd=0, now=FIXED_INSTANT)
        self.assertEqual(free['decision'], DECISION_REQUIRE)

    def test_access_limits_deny_out_of_scope_targets(self):
        policy = make_policy()
        for target in ('../fuera.txt', 'sub/../../fuera.txt', 'C:/Windows/system32', '/etc/shadow',
                       '/proc/self/environ'):
            with self.subTest(destino=target):
                kind = 'write_file' if not target.startswith('/') else 'read_repo'
                decision = evaluate(policy, {'action_kind': kind, 'target': target}, now=FIXED_INSTANT)
                self.assertEqual(decision['decision'], DECISION_DENY)
                self.assertTrue(any(rule['rule_id'].startswith('access.')
                                    for rule in decision['matched_rules']))
        allowed = evaluate(policy, {'action_kind': 'read_repo', 'target': 'src/app.py'}, now=FIXED_INSTANT)
        self.assertEqual(allowed['decision'], DECISION_ALLOW)

    def test_autonomy_ceiling_defaults_to_observe_and_is_never_elevated(self):
        self.assertEqual(AUTONOMY_CEILING_DEFAULT, 'observe')
        policy = make_policy('acme')
        self.assertEqual(policy.autonomy_ceiling, 'observe')
        self.assertEqual(policy.limits['autonomy_ceiling'], 'observe')
        for level in AUTONOMY_LEVELS:
            with self.subTest(nivel=level):
                decision = evaluate(policy, {'action_kind': 'run_tests', 'target': 'suite'},
                                    autonomy_level=level, now=FIXED_INSTANT)
                if AUTONOMY_LEVELS.index(level) > AUTONOMY_LEVELS.index('observe'):
                    self.assertEqual(decision['decision'], DECISION_DENY)
                    self.assertIn('deny.autonomy.above_ceiling',
                                  [rule['rule_id'] for rule in decision['matched_rules']])
                else:
                    self.assertEqual(decision['decision'], DECISION_ALLOW)
                self.assertEqual(decision['limits']['autonomy_ceiling'], 'observe')
        parameters = set(inspect.signature(evaluate).parameters)
        self.assertEqual(parameters & {'objective', 'goal', 'preset', 'autonomy_preset',
                                       'project_objective', 'elevar_autonomia'}, set())
        signature = inspect.signature(evaluate)
        self.assertIsNone(signature.parameters['autonomy_level'].default)
        self.assertIs(signature.parameters['requires_secret_material'].default, False)


class InertnessTests(unittest.TestCase):
    """El motor nunca ejecuta la accion: sin red, sin ficheros y sin subprocesos."""

    def setUp(self):
        self.source = Path(policy_engine_module.__file__).read_text('utf-8')
        self.tree = ast.parse(self.source)

    def test_module_imports_only_the_stdlib_allowlist(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0] or 'relativo')
        self.assertEqual(imported - ALLOWED_MODULE_IMPORTS, set())
        self.assertEqual(imported & FORBIDDEN_MODULE_IMPORTS, set())

    def test_module_has_no_file_process_or_dynamic_execution_calls(self):
        offenders = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALL_NAMES:
                offenders.append(node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTES:
                offenders.append(node.func.attr)
        self.assertEqual(offenders, [])
        self.assertNotIn("'network_allowed': True", self.source)
        self.assertNotIn('network_allowed = True', self.source)
        self.assertNotIn('importlib', self.source)

    def test_evaluating_touches_no_file_and_no_network(self):
        policy = make_policy()
        with patch.object(builtins, 'open', side_effect=AssertionError('el motor abrio un fichero')), \
                patch.object(socket, 'socket', side_effect=AssertionError('el motor abrio red')):
            decisions = decision_battery(policy)
            direct = evaluate(policy, {'action_kind': 'deploy', 'target': 'entorno-produccion'},
                              now=FIXED_INSTANT)
            allowed = evaluate(policy, scoped_action(policy, {'action_kind': 'read_repo',
                                                              'target': 'src/app.py'}),
                               now=FIXED_INSTANT)
        self.assertEqual(len(decisions), 13)
        self.assertEqual(direct['decision'], DECISION_REQUIRE)
        self.assertEqual(allowed['decision'], DECISION_ALLOW)
        for label, decision in decisions.items():
            with self.subTest(ruta=label):
                self.assertIs(decision['side_effects_performed'], False)

    def test_inputs_are_not_mutated_and_no_approval_is_consumed(self):
        policy = make_policy()
        action = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        scoped, record = approval_for(policy, action)
        action_before = copy.deepcopy(scoped)
        record_before = copy.deepcopy(record)
        policy_before = policy.as_dict()
        decision = evaluate(policy, scoped, approval=record, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(scoped, action_before)
        self.assertEqual(record, record_before)
        self.assertEqual(policy.as_dict(), policy_before)
        self.assertIsNot(decision['approval'], record)
        decision['approval']['approver_role'] = 'mutado-en-la-copia'
        self.assertEqual(record['approver_role'], record_before['approver_role'])


if __name__ == '__main__':
    unittest.main()
