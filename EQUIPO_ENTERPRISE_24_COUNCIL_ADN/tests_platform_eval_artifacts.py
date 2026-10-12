"""Pruebas offline del Evaluation Harness y de la Artifact Factory (flujo I5).

Verifica los contratos congelados `docs/plataforma/taskspec.schema.json` (criterios de
aceptacion y falsificadores del TaskSpec, consumidos por I1), `docs/plataforma/policy.schema.json`
(`$defs.approval_record` y `$defs.mandatory_gates`) y `docs/plataforma/receipt-extension.schema.json`
(Recibo de artefacto: version, campos requeridos, productores, codigos congelados y 0 colisiones
con las claves base).

Negativos exigidos por el encargo, todos con prueba que falla si el comportamiento cambia:

  * sin criterios de aceptacion el harness devuelve `not_evaluated` y nunca `passed`;
  * el harness no puede escribir instrucciones de produccion (ni tiene capacidad de escritura);
  * un rollout aprobado declara version nueva y ruta de reversion explicita y verificada;
  * todo artefacto lleva `sha256` y recibo, y un artefacto sin hash se rechaza;
  * ningun modulo hace push, PR, merge, deploy, red ni proceso externo (falsificador explicito,
    con prueba de que el propio detector detecta una fuente infractora);
  * FAIL, BLOCKED y NOT_RUN se conservan y se reportan: ninguno se convierte en PASS.

Solo biblioteca estandar. No usa red, claves, proveedores ni instala nada, y no modifica ningun
archivo de la suite: todos los artefactos de prueba se escriben en un directorio temporal.
"""
import ast
import dataclasses
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

from engine import artifact_factory, evaluation_harness, project_store, task_graph

SUITE_ROOT = Path(__file__).resolve().parent
HARNESS_PATH = SUITE_ROOT / 'engine' / 'evaluation_harness.py'
FACTORY_PATH = SUITE_ROOT / 'engine' / 'artifact_factory.py'
RECEIPT_SCHEMA_PATH = SUITE_ROOT / 'docs' / 'plataforma' / 'receipt-extension.schema.json'
TASKSPEC_SCHEMA_PATH = SUITE_ROOT / 'docs' / 'plataforma' / 'taskspec.schema.json'
POLICY_SCHEMA_PATH = SUITE_ROOT / 'docs' / 'plataforma' / 'policy.schema.json'
FIXED_TIME = '2026-10-10T00:00:00Z'

# --------------------------------------------------------------------------- #
# Vocabulario de los detectores de inercia (falsificador explicito del encargo)
# --------------------------------------------------------------------------- #
HARNESS_ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'hashlib',
                                          'json', 're'})
FACTORY_ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'datetime',
                                          'hashlib', 'json', 'pathlib', 're'})
HARNESS_ENGINE_IMPORTS = frozenset({'task_graph'})
FACTORY_ENGINE_IMPORTS = frozenset({'project_store'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'os', 'io', 'socket', 'ssl', 'urllib', 'http', 'ftplib',
                                    'smtplib', 'telnetlib', 'subprocess', 'shutil', 'requests',
                                    'httpx', 'paramiko', 'boto3', 'webbrowser', 'ctypes',
                                    'multiprocessing', 'asyncio', 'importlib', 'pickle', 'sqlite3',
                                    'xmlrpc', 'threading', 'signal', 'tempfile', 'git'})
FORBIDDEN_WORD_FRAGMENTS = frozenset({'socket', 'urllib', 'subprocess', 'ftplib', 'smtplib',
                                      'telnetlib', 'webbrowser', 'paramiko', 'boto3', 'importlib',
                                      'ctypes', 'multiprocessing', 'asyncio', 'pickle', 'sqlite3',
                                      'xmlrpc', 'httpx'})
FORBIDDEN_MODULE_STRINGS = frozenset({'socket', 'urllib', 'urllib.request', 'http', 'http.client',
                                      'requests', 'httpx', 'subprocess', 'ssl', 'ftplib', 'smtplib',
                                      'telnetlib', 'webbrowser', 'paramiko', 'boto3', 'asyncio',
                                      'multiprocessing', 'importlib', 'ctypes', 'shutil', 'os', 'io'})
FORBIDDEN_BARE_CALLS = frozenset({'open', 'eval', 'exec', 'compile', '__import__', 'input',
                                  'breakpoint'})
FORBIDDEN_ATTRIBUTE_CALLS = frozenset({'system', 'popen', 'Popen', 'check_call', 'check_output',
                                       'run', 'spawn', 'spawnl', 'fork', 'execv', 'execvp', 'execl',
                                       'urlopen', 'urlretrieve', 'connect', 'sendall', 'sendto',
                                       'recv', 'sendmail', 'request', 'push', 'pull', 'merge',
                                       'deploy', 'clone', 'commit', 'upload', 'publish'})
FORBIDDEN_FUNCTION_NAMES = re.compile(r'(?i)^(grant|install|enable|authorize|elevate|unlock|permit|'
                                      r'promote|dispatch|execute|deploy|publish|upload|push|merge|'
                                      r'open_pr|git_)')
MUTABLE_CONTAINERS = (list, dict, set, bytearray)

HARNESS_PUBLIC_FUNCTIONS = ('apply_proposal', 'approve_proposal', 'battery_for', 'build_declaration',
                            'build_hypothesis', 'build_observation', 'build_proposal',
                            'evaluate_agent', 'evaluate_cycle', 'inert_flags', 'instructions_sha256',
                            'is_pass', 'normalize_observation', 'plan_battery', 'production_digest',
                            'proposal_scope_sha256', 'rollback', 'sha256_text', 'suite_proposal',
                            'validate_proposal_target')
FACTORY_PUBLIC_FUNCTIONS = ('artifact_ref', 'build_receipt', 'canonical_json', 'check_declared_root',
                            'check_relative_path', 'inert_flags', 'media_type_for', 'patch_document',
                            'report_document', 'runbook_document', 'sha256_hex', 'ticket_document',
                            'utc_now', 'validate_receipt', 'validate_receipt_or_raise')

# --------------------------------------------------------------------------- #
# Fixtures declarativas
# --------------------------------------------------------------------------- #
CRITERIA_BY_TYPE = (
    ('observer', ('El alcance de la observacion local queda declarado.', 'Revisar el alcance de la observacion.')),
    ('proposer', ('El formato de la hipotesis y de la propuesta queda declarado.', 'Revisar hipotesis y propuesta.')),
    ('preparer', ('El plan de preparacion queda declarado paso a paso.', 'Revisar el plan y la preparacion.')),
    ('executor', ('La puerta de aprobacion humana queda declarada con su gate.', 'Revisar la aprobacion y la puerta.')),
)
FALSIFIERS_BY_TYPE = (
    ('observer', ('El alcance de la observacion queda sin declarar.', 'Revisar el alcance de la observacion.')),
    ('proposer', ('La hipotesis o la propuesta quedan sin formato declarado.', 'Revisar hipotesis y propuesta.')),
    ('preparer', ('El plan de preparacion queda sin declarar.', 'Revisar el plan y la preparacion.')),
    ('executor', ('La puerta de aprobacion humana no queda declarada.', 'Revisar la aprobacion y la puerta.')),
)

BASE_CRITERIA = (
    ('El techo de autonomia declarado no supera el nivel del tipo de agente.',
     'Recomparar el nivel y la autonomia declaradas.'),
    ('La declaracion no se atribuye ningun efecto ni permiso de escritura y no muta estado.',
     'Revisar los efectos y permisos declarados.'),
    ('Las instrucciones no declaran credenciales, ni red, ni garantias de ningun tipo.',
     'Aplicar el patron de instruccion declarado.'),
    ('Toda evidencia citada es una referencia con hash recomprobado.',
     'Revisar cada referencia y su hash.'),
)
BASE_FALSIFIERS = (
    ('El nivel de autonomia supera el techo declarado del tipo de agente.',
     'Recomparar el techo y el nivel.'),
    ('La declaracion se atribuye un permiso o un efecto sin aprobacion y muta estado.',
     'Revisar los efectos y permisos.'),
    ('Las instrucciones mencionan una credencial, una red o una garantia.',
     'Aplicar el patron de instruccion.'),
    ('Una referencia sin hash no es evidencia verificable.',
     'Revisar cada referencia y su hash.'),
)

TYPE_DECLARATION_EXTRA = (
    ('observer', {'observation_scope': 'lectura del arbol local'}),
    ('proposer', {'hypothesis_format': 'afirmacion con observacion citada'}),
    ('preparer', {'prepare_plan': 'pasos declarados sin ejecutar'}),
    ('executor', {'approval_gate': 'write'}),
)


def full_spec(agent_type):
    """Declaracion de TaskSpec con criterios y falsificadores que cubren la bateria completa."""
    typed_criteria = dict(CRITERIA_BY_TYPE)[agent_type]
    typed_falsifier = dict(FALSIFIERS_BY_TYPE)[agent_type]
    criteria = BASE_CRITERIA + (typed_criteria,)
    falsifiers = BASE_FALSIFIERS + (typed_falsifier,)
    return {'taskspec_version': '1', 'task_id': 't6', 'title': 'Harness del agente',
            'intent': 'Declarar el resultado pretendido sin ejecutarlo.',
            'agent_ref': 'perfil-' + agent_type, 'autonomy_level': 'observe', 'depends_on': [],
            'budget': {'tokens': 1000, 'money_usd': 0.0, 'time_seconds': 60, 'requests': 5},
            'acceptance_criteria': [{'criterion': criterion, 'verify': verify}
                                    for criterion, verify in criteria],
            'falsifiers': [{'falsifier_id': 'fr%02d' % (index + 1), 'statement': statement,
                            'how_detected': how}
                           for index, (statement, how) in enumerate(falsifiers)],
            'idempotency_key': 'idem-t6-' + agent_type}


def single_criterion_spec(agent_type):
    """Declaracion con un unico criterio: el resto de casos queda sin vincular."""
    typed_criteria = dict(CRITERIA_BY_TYPE)[agent_type]
    typed_falsifier = dict(FALSIFIERS_BY_TYPE)[agent_type]
    return {'taskspec_version': '1', 'task_id': 't6b', 'title': 'Un solo criterio',
            'intent': 'Declarar un unico criterio medible.', 'autonomy_level': 'observe',
            'depends_on': [],
            'budget': {'tokens': 100, 'money_usd': 0.0, 'time_seconds': 60, 'requests': 3},
            'acceptance_criteria': [{'criterion': typed_criteria[0], 'verify': typed_criteria[1]}],
            'falsifiers': [{'falsifier_id': 'fr01', 'statement': typed_falsifier[0],
                            'how_detected': typed_falsifier[1]}],
            'idempotency_key': 'idem-t6b-' + agent_type}


def agent_declaration(agent_type, **overrides):
    """Declaracion de agente completa para la bateria del tipo indicado."""
    record = {'agent_id': 'agente-' + agent_type + '-01', 'agent_type': agent_type,
              'instructions': 'Observar, declarar y proponer sin tocar produccion.',
              'autonomy_level': 'observe', 'capabilities': ['read', 'verify'],
              'evidence_refs': ['docs/plataforma/taskspec.schema.json']}
    record.update(dict(TYPE_DECLARATION_EXTRA)[agent_type])
    record.update(overrides)
    return record


def production_map(agent_type, instructions=None):
    return {'agente-' + agent_type + '-01': instructions or
            'Observar, declarar y proponer sin tocar produccion.',
            'agente-verificador-02': 'Instrucciones de produccion ajenas a la corrida.'}


def module_tree(path):
    return ast.parse(path.read_text('utf-8'), filename=str(path))


def words_of(name):
    """Palabras de un identificador: separa snake_case y camelCase y normaliza a minusculas."""
    words = []
    for part in re.split(r'[^A-Za-z0-9]+', str(name)):
        words.extend(re.findall(r'[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+', part))
    return tuple(word.lower() for word in words)


def imported_roots(tree):
    roots, relative = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative.add(node.module)
                continue
            roots.add((node.module or '').split('.')[0])
    return roots, relative


def forbidden_usage(tree):
    """Hallazgos del falsificador: importaciones, llamadas, identificadores y literales prohibidos."""
    findings = set()
    roots, _ = imported_roots(tree)
    findings.update(roots & FORBIDDEN_IMPORT_ROOTS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BARE_CALLS:
                findings.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTE_CALLS:
                findings.add(node.func.attr)
        if isinstance(node, (ast.Name, ast.Attribute)):
            label = node.id if isinstance(node, ast.Name) else node.attr
            findings.update(word for word in words_of(label) if word in FORBIDDEN_WORD_FRAGMENTS)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value.lower() in FORBIDDEN_MODULE_STRINGS:
                findings.add('module-string:' + value.lower())
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', value):
                findings.add('url_literal')
    return findings


def expected_code(test_case, expected, callable_under_test, *args, **kwargs):
    with test_case.assertRaises(evaluation_harness.EvaluationHarnessError) as caught:
        callable_under_test(*args, **kwargs)
    test_case.assertEqual(caught.exception.code, expected)
    test_case.assertIsInstance(caught.exception, ValueError)
    return caught.exception


def expected_factory_code(test_case, expected, callable_under_test, *args, **kwargs):
    with test_case.assertRaises(artifact_factory.ArtifactFactoryError) as caught:
        callable_under_test(*args, **kwargs)
    test_case.assertEqual(caught.exception.code, expected)
    test_case.assertIsInstance(caught.exception, ValueError)
    return caught.exception


# --------------------------------------------------------------------------- #
# Acceptance 1: criterios obligatorios; sin criterios nunca `passed`
# --------------------------------------------------------------------------- #
class HarnessAcceptanceCriteriaTests(unittest.TestCase):
    """El harness exige criterios de aceptacion del TaskSpec y nunca aprueba sin ellos."""

    def test_spec_without_criteria_is_not_evaluated_and_never_pass(self):
        empty = types.SimpleNamespace(acceptance_criteria=(), falsifiers=())
        report = evaluation_harness.evaluate_agent(empty, agent_declaration('observer'))
        self.assertEqual(report.verdict, 'not_evaluated')
        self.assertNotEqual(report.verdict, 'passed')
        self.assertFalse(report.is_pass)
        self.assertEqual(report.cases, ())
        self.assertEqual(report.counts, (('passed', 0), ('failed', 0), ('not_run', 0)))
        self.assertEqual(report.guarantee, evaluation_harness.GUARANTEE_LABEL)

    def test_mapping_without_acceptance_criteria_is_not_evaluated(self):
        spec = full_spec('observer')
        spec.pop('acceptance_criteria')
        report = evaluation_harness.evaluate_agent(spec, agent_declaration('observer'))
        self.assertEqual(report.verdict, 'not_evaluated')
        self.assertEqual(report.code, 'missing_required_field')
        self.assertNotEqual(report.verdict, 'passed')

    def test_empty_criteria_list_is_not_evaluated_with_the_frozen_code(self):
        spec = full_spec('observer')
        spec['acceptance_criteria'] = []
        report = evaluation_harness.evaluate_agent(spec, agent_declaration('observer'))
        self.assertEqual(report.verdict, 'not_evaluated')
        self.assertEqual(report.code, 'missing_acceptance_criterion')
        self.assertNotEqual(report.verdict, 'passed')

    def test_spec_without_falsifiers_is_not_evaluated(self):
        spec = full_spec('observer')
        spec['falsifiers'] = []
        report = evaluation_harness.evaluate_agent(spec, agent_declaration('observer'))
        self.assertEqual(report.verdict, 'not_evaluated')
        self.assertEqual(report.code, 'missing_falsifier')
        self.assertNotEqual(report.verdict, 'passed')

    def test_every_case_declares_the_criterion_it_checks(self):
        spec = task_graph.build_taskspec(full_spec('observer'))
        for declared in (spec, full_spec('observer')):
            planned = evaluation_harness.plan_battery(declared, 'observer')
            self.assertEqual(len(planned), 5)
            for case in planned:
                with self.subTest(case=case.case_id):
                    self.assertIsNotNone(case.criterion)
                    self.assertIsNotNone(case.criterion_index)
                    self.assertIsNotNone(case.falsifier_id)
                    self.assertNotEqual(case.falsifier, '')
        report = evaluation_harness.evaluate_agent(spec, agent_declaration('observer'),
                                                   production=production_map('observer'))
        self.assertEqual(report.verdict, 'passed')
        for case in report.cases:
            self.assertIn(case.criterion, tuple(text for _, text in report.criteria))
            self.assertIsNotNone(case.criterion_index)

    def test_case_without_a_bound_criterion_never_passes(self):
        report = evaluation_harness.evaluate_agent(single_criterion_spec('observer'),
                                                   agent_declaration('observer'),
                                                   production=production_map('observer'))
        unbound = [case for case in report.cases if case.criterion_index is None]
        self.assertEqual(len(unbound), 4)
        for case in unbound:
            with self.subTest(case=case.check_id):
                self.assertEqual(case.result, 'not_run')
                self.assertEqual(case.state, 'unbound')
                self.assertNotEqual(case.result, 'passed')
        self.assertEqual(report.verdict, 'partial')
        self.assertEqual(report.code, 'unbound_criterion')

    def test_a_report_cannot_be_forged_into_a_pass(self):
        partial = evaluation_harness.evaluate_agent(single_criterion_spec('observer'),
                                                    agent_declaration('observer'),
                                                    production=production_map('observer'))
        self.assertEqual(partial.verdict, 'partial')
        for changes in ({'verdict': 'passed'}, {'verdict': 'passed', 'cases': ()},
                        {'verdict': 'passed', 'production_instructions_unchanged': None},
                        {'verdict': 'resultado-garantizado'}):
            with self.subTest(changes=changes):
                with self.assertRaises(evaluation_harness.EvaluationHarnessError) as caught:
                    dataclasses.replace(partial, **changes)
                self.assertEqual(caught.exception.code, 'invalid_battery')
        expected_code(self, 'guarantee_claim_forbidden', dataclasses.replace, partial,
                      guarantee='garantizado')
        passed = evaluation_harness.evaluate_agent(full_spec('observer'),
                                                   agent_declaration('observer'),
                                                   production=production_map('observer'))
        self.assertEqual(passed.verdict, 'passed')
        self.assertIs(passed.is_pass, True)

    def test_full_pass_requires_all_eight_conditions(self):
        report = evaluation_harness.evaluate_agent(full_spec('observer'),
                                                   agent_declaration('observer'),
                                                   production=production_map('observer'))
        self.assertEqual(report.verdict, 'passed')
        self.assertEqual(len(report.pass_conditions), 8)
        self.assertTrue(all(value for _, value in report.pass_conditions))
        self.assertEqual(report.guarantee, 'not_guaranteed')
        self.assertNotIn('garantizado', json.dumps(report.to_dict(), ensure_ascii=False).lower())

    def test_a_declaration_that_omits_a_declared_field_fails_that_case(self):
        declaration = agent_declaration('observer')
        declaration.pop('observation_scope')
        report = evaluation_harness.evaluate_agent(full_spec('observer'), declaration,
                                                   production=production_map('observer'))
        case = dict((item.check_id, item) for item in report.cases)['observation_scope_declared']
        self.assertEqual(case.result, 'failed')
        self.assertEqual(case.state, 'executed')
        self.assertNotEqual(case.result, 'passed')
        self.assertEqual(report.verdict, 'failed')
        self.assertFalse(report.is_pass)

    def test_an_absent_observation_blocks_the_case_and_degrades_the_verdict(self):
        check = evaluation_harness.CheckSpec(
            check_id='hypothesis_format_typed', target='hypothesis_format', kind='in_set',
            expected=('afirmacion con observacion citada',), mutant_value='formato-invalido',
            mutant_mode='replace', criterion_keywords=('hipotesis', 'propuesta'),
            refutation='El formato de la hipotesis no es el declarado.')
        battery = evaluation_harness.Battery(battery_id='battery-proposer', agent_type='proposer',
                                             max_autonomy='propose', checks=(check,))
        declaration = agent_declaration('proposer', hypothesis_format=None)
        report = evaluation_harness.evaluate_agent(full_spec('proposer'), declaration,
                                                   production=production_map('proposer'),
                                                   batteries=(battery,))
        case = report.cases[0]
        self.assertIsNone(case.observation_preview)
        self.assertIsNone(case.observation_sha256)
        self.assertEqual(case.result, 'not_run')
        self.assertEqual(case.state, 'blocked')
        self.assertEqual(case.reason, 'observation_missing')
        self.assertEqual(report.verdict, 'partial')
        self.assertEqual(report.code, 'case_not_evaluated')
        self.assertNotEqual(report.verdict, 'passed')
        declared = evaluation_harness.evaluate_agent(
            full_spec('proposer'), declaration, production=production_map('proposer'),
            batteries=(battery,), observed={'hypothesis_format_typed': 'passed'})
        self.assertEqual(declared.cases[0].observed, 'passed')
        self.assertEqual(declared.cases[0].result, 'passed')

    def test_a_declaration_without_evidence_fails_the_case(self):
        declaration = agent_declaration('observer', evidence_refs=[])
        report = evaluation_harness.evaluate_agent(full_spec('observer'), declaration,
                                                   production=production_map('observer'))
        case = dict((item.check_id, item) for item in report.cases)['evidence_cited']
        self.assertEqual(case.result, 'failed')
        self.assertEqual(case.state, 'executed')
        self.assertEqual(report.verdict, 'failed')

    def test_each_agent_type_has_its_own_autonomy_ceiling_battery(self):
        self.assertEqual(tuple(battery.agent_type for battery in evaluation_harness.BATTERY_LIBRARY),
                         evaluation_harness.AGENT_TYPES)
        for agent_type in evaluation_harness.AGENT_TYPES:
            with self.subTest(agent_type=agent_type):
                battery = evaluation_harness.battery_for(agent_type)
                self.assertEqual(len(battery.checks), 5)
                self.assertIn(battery.max_autonomy, task_graph.AUTONOMY_LEVELS)
                report = evaluation_harness.evaluate_agent(full_spec(agent_type),
                                                           agent_declaration(agent_type),
                                                           production=production_map(agent_type))
                self.assertEqual(report.verdict, 'passed', report.to_dict())
        expected_code(self, 'unknown_agent_type', evaluation_harness.battery_for, 'auditor-externo')

    def test_a_case_that_cannot_fail_is_not_evaluated(self):
        huge = evaluation_harness.CheckSpec(check_id='in_set_without_mutant', target='agent_type',
                                            kind='in_set', expected=('observer', 'proposer', 'preparer',
                                                                     'executor'),
                                            mutant_value='observer', mutant_mode='replace',
                                            criterion_keywords=('autonomia',), refutation='x')
        battery = evaluation_harness.Battery(battery_id='battery-observer', agent_type='observer',
                                             max_autonomy='observe', checks=(huge,))
        report = evaluation_harness.evaluate_agent(full_spec('observer'), agent_declaration('observer'),
                                                   production=production_map('observer'),
                                                   batteries=(battery,))
        case = report.cases[0]
        self.assertEqual(case.mutant_result, True)
        self.assertFalse(case.is_falsifiable)
        self.assertEqual(case.result, 'not_run')
        self.assertEqual(case.reason, 'case_not_falsifiable')
        self.assertNotEqual(report.verdict, 'passed')


# --------------------------------------------------------------------------- #
# Acceptance 2: una propuesta no puede mutar instrucciones de produccion
# --------------------------------------------------------------------------- #
class HarnessProductionImmutabilityTests(unittest.TestCase):
    """El harness declara propuestas y versiones; nunca escribe produccion."""

    def _proposal(self):
        declaration = evaluation_harness.build_declaration(agent_declaration('observer'))
        observation = evaluation_harness.build_observation('obs01', 'observer', 'observacion del alcance',
                                                           'El alcance quedo sin declarar.')
        hypothesis = evaluation_harness.build_hypothesis('hyp01', 'El alcance debe declararse explicitamente.',
                                                         ('obs01',), 'declarar el alcance',
                                                         observations=(observation,))
        return declaration, evaluation_harness.build_proposal(
            'prop01', hypothesis, declaration, 'Observar y declarar el alcance explicitamente.',
            'La declaracion actual omite el alcance.', 'El caso de alcance deja de quedar bloqueado.')

    def test_apply_proposal_returns_a_new_declaration_and_never_mutates(self):
        declaration, proposal = self._proposal()
        production = production_map('observer')
        before_sha = declaration.instructions_sha256
        before_production = dict(production)
        applied = evaluation_harness.apply_proposal(declaration, proposal)
        self.assertIsNot(applied, declaration)
        self.assertEqual(declaration.instructions_sha256, before_sha)
        self.assertEqual(declaration.instructions, production['agente-observer-01'])
        self.assertEqual(production, before_production)
        self.assertEqual(applied.instructions, proposal.new_instructions)
        self.assertNotEqual(applied.instructions_sha256, before_sha)

    def test_proposal_targeting_a_production_path_is_rejected(self):
        for target in ('engine/prompts/observer.md', 'engine\\prompts\\observer.md',
                       '/etc/passwd', 'C:/produccion/agente.py', '../fuera/agente.txt'):
            with self.subTest(target=target):
                expected_code(self, 'production_mutation_forbidden',
                              evaluation_harness.validate_proposal_target, target)
        self.assertEqual(evaluation_harness.validate_proposal_target('agente-observador-01'),
                         'agente-observador-01')

    def test_production_hash_is_identical_before_and_after_the_run(self):
        declaration = agent_declaration('observer')
        production = production_map('observer')
        report = evaluation_harness.evaluate_agent(full_spec('observer'), declaration,
                                                   production=production)
        self.assertIsNotNone(report.production_instructions_sha256_before)
        self.assertEqual(report.production_instructions_sha256_before,
                         report.production_instructions_sha256_after)
        self.assertTrue(report.production_instructions_unchanged)
        self.assertEqual(production['agente-observer-01'], declaration['instructions'])
        self.assertNotIn('agente-verificador-02', json.dumps(report.to_dict(), ensure_ascii=False))
        self.assertNotIn(production['agente-verificador-02'],
                         json.dumps(report.to_dict(), ensure_ascii=False))

    def test_without_a_declared_production_map_the_full_pass_is_not_granted(self):
        report = evaluation_harness.evaluate_agent(full_spec('observer'), agent_declaration('observer'))
        self.assertIsNone(report.production_instructions_sha256_before)
        self.assertIsNone(report.production_instructions_unchanged)
        self.assertEqual(report.verdict, 'partial')
        self.assertEqual(report.code, 'production_not_declared')

    def test_cycle_without_approval_declares_no_version_and_no_rollout(self):
        declaration = agent_declaration('observer')
        cycle = evaluation_harness.evaluate_cycle(
            single_criterion_spec('observer'), declaration, signal='observacion del alcance',
            detail='El alcance quedo sin declarar.',
            statement='El alcance debe declararse explicitamente.',
            proposed_change='declarar el alcance',
            new_instructions='Observar y declarar el alcance explicitamente.',
            rationale='La declaracion omite el alcance.',
            expected_effect='El caso de alcance deja de quedar bloqueado.',
            production=production_map('observer'))
        self.assertEqual(cycle.status, 'awaiting_approval')
        self.assertIsNone(cycle.version)
        self.assertIsNone(cycle.rollout)
        self.assertEqual(cycle.observation.observation_id, 'obs01')
        self.assertEqual(cycle.hypothesis.observation_ids, ('obs01',))
        self.assertEqual(cycle.report_before.production_instructions_sha256_before,
                         cycle.report_before.production_instructions_sha256_after)
        self.assertEqual(cycle.proposed_instructions_sha256,
                         evaluation_harness.instructions_sha256(cycle.proposal.new_instructions))

    def test_hypothesis_without_an_existing_observation_is_rejected(self):
        expected_code(self, 'hypothesis_evidence_missing',
                      evaluation_harness.build_hypothesis, 'hyp01', 'afirmacion', ('obs-inexistente',),
                      'cambio', observations=())

    def test_guarantee_claims_are_refused(self):
        for text in ('El agente garantiza 0 fallos.', 'Resultado sin fallos garantizado.',
                     'El sistema nunca falla.'):
            with self.subTest(text=text):
                expected_code(self, 'guarantee_claim_forbidden',
                              evaluation_harness.build_observation, 'obs01', 'observer', text,
                              'detalle observado')


# --------------------------------------------------------------------------- #
# Acceptance 3: todo rollout es reversible y versionado
# --------------------------------------------------------------------------- #
class HarnessRolloutTests(unittest.TestCase):
    """Una propuesta aprobada produce version nueva y ruta de reversion explicita."""

    def _approved(self, **overrides):
        declaration = evaluation_harness.build_declaration(agent_declaration('observer'))
        observation = evaluation_harness.build_observation('obs01', 'observer', 'alcance',
                                                           'El alcance quedo sin declarar.')
        hypothesis = evaluation_harness.build_hypothesis('hyp01', 'El alcance debe declararse.',
                                                         ('obs01',), 'declarar el alcance',
                                                         observations=(observation,))
        proposal = evaluation_harness.build_proposal(
            'prop01', hypothesis, declaration, 'Observar y declarar el alcance explicitamente.',
            'La declaracion omite el alcance.', 'El caso de alcance deja de quedar bloqueado.')
        kwargs = {'gate': 'write', 'approver_role': 'operador-humano',
                  'approved_at': FIXED_TIME,
                  'scope_hash': evaluation_harness.proposal_scope_sha256(proposal)}
        kwargs.update(overrides)
        return declaration, proposal, evaluation_harness.Approval(**kwargs)

    def test_approved_proposal_versions_and_declares_an_explicit_rollback_route(self):
        declaration, proposal, approval = self._approved()
        version = evaluation_harness.approve_proposal(proposal, approval, current_version=3,
                                                      current_instructions=declaration.instructions)
        self.assertEqual(version.version, 4)
        self.assertEqual(version.previous_version, 3)
        self.assertEqual(version.previous_instructions_sha256, declaration.instructions_sha256)
        route = dict(version.rollback_route)
        self.assertEqual(route['to_version'], '3')
        self.assertEqual(route['instructions_sha256'], declaration.instructions_sha256)
        self.assertIn('verification', route)
        restored = evaluation_harness.rollback(version, current_instructions=declaration.instructions)
        self.assertTrue(restored.verified)
        self.assertEqual(restored.to_version, 3)
        self.assertEqual(restored.instructions_sha256, declaration.instructions_sha256)
        self.assertEqual(restored.restored_instructions, declaration.instructions)
        self.assertNotEqual(version.new_instructions_sha256, version.previous_instructions_sha256)

    def test_rollback_with_a_snapshot_that_does_not_match_is_unavailable(self):
        declaration, proposal, approval = self._approved()
        version = evaluation_harness.approve_proposal(proposal, approval, current_version=1,
                                                      current_instructions=declaration.instructions)
        expected_code(self, 'rollback_unavailable', evaluation_harness.rollback, version,
                      current_instructions='Otras instrucciones distintas de las versionadas.')

    def test_approval_of_another_scope_does_not_authorize(self):
        declaration, proposal, approval = self._approved()
        other = evaluation_harness.Approval(gate='write', approver_role='operador-humano',
                                            approved_at=FIXED_TIME, scope_hash='0' * 64)
        expected_code(self, 'approval_scope_mismatch', evaluation_harness.approve_proposal, proposal,
                      other, current_version=1, current_instructions=declaration.instructions)

    def test_approval_requires_the_write_gate_and_one_shot(self):
        declaration, proposal, _ = self._approved()
        scope = evaluation_harness.proposal_scope_sha256(proposal)
        for gate in ('push', 'merge', 'deploy', 'secrets'):
            with self.subTest(gate=gate):
                approval = evaluation_harness.Approval(gate=gate, approver_role='operador-humano',
                                                       approved_at=FIXED_TIME, scope_hash=scope)
                expected_code(self, 'approval_required', evaluation_harness.approve_proposal, proposal,
                              approval, current_version=1, current_instructions=declaration.instructions)
        reusable = evaluation_harness.Approval(gate='write', approver_role='operador-humano',
                                               approved_at=FIXED_TIME, scope_hash=scope,
                                               one_shot=False)
        expected_code(self, 'approval_not_one_shot', evaluation_harness.approve_proposal, proposal,
                      reusable, current_version=1, current_instructions=declaration.instructions)

    def test_a_malformed_scope_hash_or_timestamp_is_refused(self):
        declaration, proposal, _ = self._approved()
        for scope in ('', 'no-hash', 'A' * 64, '0' * 63):
            with self.subTest(scope_hash=scope):
                approval = evaluation_harness.Approval(gate='write', approver_role='operador-humano',
                                                       approved_at=FIXED_TIME, scope_hash=scope)
                expected_code(self, 'approval_required', evaluation_harness.approve_proposal, proposal,
                              approval, current_version=1,
                              current_instructions=declaration.instructions)
        wrong_time = evaluation_harness.Approval(
            gate='write', approver_role='operador-humano', approved_at='2026-10-10',
            scope_hash=evaluation_harness.proposal_scope_sha256(proposal))
        expected_code(self, 'approval_required', evaluation_harness.approve_proposal, proposal,
                      wrong_time, current_version=1, current_instructions=declaration.instructions)

    def test_a_consumed_approval_is_refused(self):
        declaration, proposal, approval = self._approved()
        expected_code(self, 'approval_consumed', evaluation_harness.approve_proposal, proposal,
                      approval, current_version=1, current_instructions=declaration.instructions,
                      consumed_scope_hashes=(approval.scope_hash,))

    def test_stale_proposal_and_target_mismatch_are_refused(self):
        declaration = evaluation_harness.build_declaration(agent_declaration('observer'))
        observation = evaluation_harness.build_observation('obs01', 'observer', 'alcance', 'sin alcance')
        hypothesis = evaluation_harness.build_hypothesis('hyp01', 'declarar alcance', ('obs01',),
                                                         'cambio', observations=(observation,))
        other = evaluation_harness.build_declaration(agent_declaration('proposer'))
        proposal = evaluation_harness.build_proposal('prop01', hypothesis, declaration,
                                                     'Instrucciones nuevas.', 'razon', 'efecto')
        expected_code(self, 'target_mismatch', evaluation_harness.apply_proposal, other, proposal)
        advanced = evaluation_harness.AgentDeclaration(
            agent_id=declaration.agent_id, agent_type=declaration.agent_type,
            instructions='Otras instrucciones vigentes.', capabilities=('read',),
            evidence_refs=('ref',), observation_scope='alcance')
        expected_code(self, 'stale_proposal', evaluation_harness.apply_proposal, advanced, proposal)

    def test_cycle_with_approval_rolls_out_and_proves_reversion(self):
        declaration = agent_declaration('observer')
        proposal_instructions = 'Observar y declarar el alcance explicitamente.'
        agent = evaluation_harness.build_declaration(declaration)
        trial = evaluation_harness.build_proposal(
            'prop01', evaluation_harness.build_hypothesis(
                'hyp01', 'declarar alcance', ('obs01',), 'cambio',
                observations=(evaluation_harness.build_observation('obs01', 'observer', 'alcance',
                                                                   'sin alcance'),)),
            agent, proposal_instructions, 'razon', 'efecto')
        approval = evaluation_harness.Approval(
            gate='write', approver_role='operador-humano', approved_at=FIXED_TIME,
            scope_hash=evaluation_harness.proposal_scope_sha256(trial))
        cycle = evaluation_harness.evaluate_cycle(
            full_spec('observer'), declaration, signal='alcance sin declarar',
            detail='El alcance de la observacion quedo sin declarar.',
            statement='El alcance debe declararse.', proposed_change='declarar el alcance',
            new_instructions=proposal_instructions, rationale='omitido',
            expected_effect='el caso de alcance se evalua', approval=approval, current_version=2,
            production=production_map('observer'))
        self.assertEqual(cycle.status, 'rolled_out')
        self.assertEqual(cycle.version.version, 3)
        self.assertTrue(cycle.rollout.verified)
        self.assertEqual(cycle.rollout.restored_instructions, declaration['instructions'])
        self.assertEqual(cycle.rollout.instructions_sha256,
                         evaluation_harness.instructions_sha256(declaration['instructions']))


# --------------------------------------------------------------------------- #
# Acceptance 6: FAIL / BLOCKED / NOT_RUN se conservan, nunca se convierten en PASS
# --------------------------------------------------------------------------- #
class HarnessObservationVocabularyTests(unittest.TestCase):
    """El vocabulario observado se conserva y nunca se aproxima a un PASS."""

    def test_fail_blocked_and_not_run_are_preserved_and_never_pass(self):
        declared = {'FAIL': ('failed', 'executed'), 'BLOCKED': ('not_run', 'blocked'),
                    'NOT RUN': ('not_run', 'blocked'), 'not_run': ('not_run', 'blocked'),
                    'passed': ('passed', 'executed')}
        for token, (result, state) in declared.items():
            with self.subTest(token=token):
                self.assertEqual(evaluation_harness.normalize_observation(token)[:2], (result, state))
                if token != 'passed':
                    self.assertFalse(evaluation_harness.is_pass(token))
        report = evaluation_harness.evaluate_agent(
            full_spec('observer'), agent_declaration('observer'),
            production=production_map('observer'),
            observed={'instructions_hygiene': 'BLOCKED', 'evidence_cited': 'FAIL',
                      'autonomy_ceiling': 'NOT RUN'})
        cases = dict((case.check_id, case) for case in report.cases)
        self.assertEqual(cases['instructions_hygiene'].observed, 'BLOCKED')
        self.assertEqual(cases['instructions_hygiene'].result, 'not_run')
        self.assertEqual(cases['instructions_hygiene'].state, 'blocked')
        self.assertEqual(cases['evidence_cited'].observed, 'FAIL')
        self.assertEqual(cases['evidence_cited'].result, 'failed')
        self.assertEqual(cases['autonomy_ceiling'].observed, 'NOT RUN')
        self.assertEqual(cases['autonomy_ceiling'].result, 'not_run')
        self.assertEqual(report.verdict, 'failed')
        self.assertFalse(report.is_pass)
        for case in report.cases:
            if case.observed is not None:
                with self.subTest(case=case.check_id):
                    self.assertFalse(evaluation_harness.is_pass(case))

    def test_an_unknown_observation_token_is_rejected_not_approximated(self):
        for token in ('probablemente-ok', 'quizas', '2', 'casi'):
            with self.subTest(token=token):
                expected_code(self, 'unknown_observation',
                              evaluation_harness.normalize_observation, token)
        self.assertFalse(evaluation_harness.is_pass('probablemente-ok'))

    def test_a_declared_observation_cannot_promote_an_unbound_case(self):
        report = evaluation_harness.evaluate_agent(
            single_criterion_spec('observer'), agent_declaration('observer'),
            production=production_map('observer'),
            observed={'evidence_cited': 'passed', 'instructions_hygiene': 'PASS'})
        for case in report.cases:
            if case.observed is not None:
                with self.subTest(case=case.check_id):
                    self.assertEqual(case.result, 'not_run')
                    self.assertNotEqual(case.result, 'passed')
        self.assertNotEqual(report.verdict, 'passed')

    def test_a_declared_fail_wins_over_a_measured_pass(self):
        report = evaluation_harness.evaluate_agent(
            full_spec('observer'), agent_declaration('observer'),
            production=production_map('observer'), observed={'autonomy_ceiling': 'FAIL'})
        case = dict((item.check_id, item) for item in report.cases)['autonomy_ceiling']
        self.assertEqual(case.result, 'failed')
        self.assertEqual(report.verdict, 'failed')

    def test_cases_without_a_bound_falsifier_never_pass(self):
        spec = full_spec('observer')
        spec['falsifiers'] = [item for item in spec['falsifiers'] if item['falsifier_id'] != 'fr04']
        report = evaluation_harness.evaluate_agent(spec, agent_declaration('observer'),
                                                   production=production_map('observer'))
        case = dict((item.check_id, item) for item in report.cases)['evidence_cited']
        self.assertEqual(case.falsifier_id, None)
        self.assertEqual(case.result, 'not_run')
        self.assertEqual(case.state, 'blocked')
        self.assertEqual(case.reason, 'case_without_falsifier')
        self.assertEqual(report.code, 'case_without_falsifier')
        self.assertNotEqual(report.verdict, 'passed')

    def test_an_unknown_observed_case_is_rejected(self):
        expected_code(self, 'invalid_observation', evaluation_harness.evaluate_agent,
                      full_spec('observer'), agent_declaration('observer'),
                      observed={'caso-inexistente': 'passed'})


# --------------------------------------------------------------------------- #
# Acceptance 5 (harness): sin red, sin subprocess, sin escritura
# --------------------------------------------------------------------------- #
class HarnessInertnessTests(unittest.TestCase):
    """El harness no escribe, no abre red y no lanza procesos: se comprueba sobre el AST."""

    def test_module_imports_only_declared_stdlib_and_the_task_graph(self):
        roots, relative = imported_roots(module_tree(HARNESS_PATH))
        self.assertEqual(roots & FORBIDDEN_IMPORT_ROOTS, set())
        self.assertLessEqual(roots, HARNESS_ALLOWED_IMPORT_ROOTS | HARNESS_ENGINE_IMPORTS)
        self.assertIn('task_graph', relative)

    def test_module_has_no_write_or_process_capability(self):
        tree = module_tree(HARNESS_PATH)
        self.assertEqual(forbidden_usage(tree), set())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, ('write', 'writelines', 'write_text', 'write_bytes',
                                                  'mkdir', 'unlink', 'rmdir', 'remove'))
        for absent in ('open(', 'os.system', 'shutil', 'urlopen'):
            with self.subTest(token=absent):
                self.assertNotIn(absent, HARNESS_PATH.read_text('utf-8'))

    def test_module_has_no_mutable_global_state(self):
        offenders = sorted(name for name, value in vars(evaluation_harness).items()
                           if isinstance(value, MUTABLE_CONTAINERS) and name != '__builtins__')
        self.assertEqual(offenders, [])
        for name in ('AGENT_TYPES', 'CASE_RESULTS', 'CASE_STATES', 'VERDICTS', 'CHECK_KINDS',
                     'PASS_CONDITION_NAMES', 'HARNESS_ERROR_CODES', 'ERROR_CLASSES',
                     'MANDATORY_GATES', 'FORBIDDEN_DECLARED_EFFECTS', 'BATTERY_LIBRARY',
                     'INERT_FLAGS', 'AUTONOMY_CEILING', 'INSTRUCTION_FORBIDDEN_SOURCES'):
            with self.subTest(constant=name):
                self.assertIsInstance(getattr(evaluation_harness, name), tuple)

    def test_declared_inert_flags_are_false_for_every_effect(self):
        flags = evaluation_harness.inert_flags()
        for name in ('writes_to_disk', 'opens_files', 'network_allowed', 'spawns_processes',
                     'pushes', 'opens_pull_requests', 'merges', 'deploys',
                     'mutates_production_instructions', 'grants_permissions',
                     'consumes_credentials'):
            with self.subTest(flag=name):
                self.assertIs(flags[name], False)

    def test_public_surface_is_declared_and_promises_nothing(self):
        own = sorted(name for name, value in vars(evaluation_harness).items()
                     if inspect.isfunction(value)
                     and getattr(value, '__module__', None) == evaluation_harness.__name__
                     and not name.startswith('_'))
        self.assertEqual(own, sorted(HARNESS_PUBLIC_FUNCTIONS))
        for name in own:
            with self.subTest(function=name):
                self.assertIsNone(FORBIDDEN_FUNCTION_NAMES.match(name))
        self.assertEqual(tuple(error_class.code for error_class in evaluation_harness.ERROR_CLASSES),
                         tuple(dict.fromkeys(evaluation_harness.HARNESS_ERROR_CODES)))

    def test_evaluation_does_not_mutate_module_state(self):
        before = {name: id(value) for name, value in vars(evaluation_harness).items()}
        evaluation_harness.evaluate_agent(full_spec('observer'), agent_declaration('observer'),
                                          production=production_map('observer'))
        evaluation_harness.normalize_observation('BLOCKED')
        evaluation_harness.plan_battery(single_criterion_spec('proposer'), 'proposer')
        after = {name: id(value) for name, value in vars(evaluation_harness).items()}
        self.assertEqual(before, after)


# --------------------------------------------------------------------------- #
# Acceptance 4 (fabrica): hash + recibo, y artefacto sin hash rechazado
# --------------------------------------------------------------------------- #
class FactoryReceiptTests(unittest.TestCase):
    """Todo artefacto lleva sha256 y recibo de la extension; sin hash no hay artefacto."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'artefactos'
        self.factory = artifact_factory.ArtifactFactory(self.root, clock=lambda: FIXED_TIME)

    def test_every_written_artifact_carries_sha256_and_its_receipt(self):
        records = (self.factory.write_report('informe-01', 'Bateria', ['caso evaluado']),
                   self.factory.write_patch('parche-01', [{'file': 'engine/task_graph.py',
                                                           'before': 'vieja', 'after': 'nueva'}]),
                   self.factory.write_ticket('ticket-01', 'TK-1', 'Fallo observado', ['Reproducir']),
                   self.factory.write_runbook('runbook-01', 'Reversion', ['Paso 1'],
                                              stop_conditions=['hash distinto']))
        for record in records:
            with self.subTest(path=record.path):
                self.assertRegex(record.sha256, r'^[0-9a-f]{64}$')
                self.assertEqual(record.sha256, hashlib.sha256(self.factory.read_bytes(record)).hexdigest())
                self.assertEqual(record.bytes, len(self.factory.read_bytes(record)))
                receipt = dict(record.receipt)
                self.assertEqual(set(artifact_factory.REQUIRED_RECEIPT_FIELDS) - set(receipt), set())
                self.assertTrue(artifact_factory.validate_receipt(receipt)['valid'])
                self.assertEqual(receipt['artifact']['sha256'], record.sha256)
                self.assertEqual(receipt['artifact']['path'], record.path)
                self.assertEqual(receipt['artifact']['bytes'], record.bytes)
                self.assertIs(receipt['side_effects_performed'], False)
                self.assertIs(receipt['null_is_not_zero'], True)
                self.assertEqual(receipt['produced_by'], 'artifact_factory')
                self.assertTrue(self.factory.verify(record)['valid'])
        bundle = self.factory.write_bundle('bundle-01', records)
        self.assertEqual(bundle.kind, 'bundle')
        self.assertEqual(dict(bundle.receipt)['artifact']['sha256'], bundle.sha256)
        self.assertTrue(self.factory.verify_bundle(bundle)['valid'])

    def test_artifact_without_hash_is_rejected(self):
        expected_factory_code(self, 'artifact_without_hash', artifact_factory.artifact_ref,
                              'report/informe-01', None, 10)
        expected_factory_code(self, 'artifact_without_hash', artifact_factory.artifact_ref,
                              'report/informe-01', 'no-es-un-hash', 10)
        receipt = artifact_factory.build_receipt(idempotency_key='clave-de-prueba-01',
                                                 recorded_at=FIXED_TIME)
        receipt['artifact'] = {'path': 'report/informe-01', 'bytes': 10}
        report = artifact_factory.validate_receipt(receipt)
        self.assertFalse(report['valid'])
        self.assertEqual(report['code'], 'artifact_without_hash')
        expected_factory_code(self, 'artifact_without_hash', artifact_factory.validate_receipt_or_raise,
                              receipt)

    def test_base_keys_cannot_be_redefined(self):
        receipt = artifact_factory.build_receipt(idempotency_key='clave-de-prueba-02',
                                                 recorded_at=FIXED_TIME)
        for base_key in artifact_factory.BASE_RECEIPT_KEYS + artifact_factory.BASE_USAGE_KEYS:
            with self.subTest(base_key=base_key):
                mutated = dict(receipt)
                mutated[base_key] = 'redefinida'
                report = artifact_factory.validate_receipt(mutated)
                self.assertFalse(report['valid'])
                self.assertEqual(report['code'], 'base_key_collision')
        self.assertEqual(set(receipt) & set(artifact_factory.BASE_RECEIPT_KEYS), set())
        self.assertEqual(set(receipt) & set(artifact_factory.BASE_USAGE_KEYS), set())

    def test_null_is_not_coerced_to_zero(self):
        for value in ('', 0, False, 'no-es-hash'):
            with self.subTest(consent_ref=value):
                expected_factory_code(self, 'null_coerced_to_zero', artifact_factory.build_receipt,
                                      idempotency_key='clave-de-prueba-03', consent_ref=value)
        receipt = artifact_factory.build_receipt(idempotency_key='clave-de-prueba-04',
                                                 consent_ref=None, recorded_at=FIXED_TIME)
        self.assertIsNone(receipt['consent_ref'])

    def test_retry_requires_a_new_authorization(self):
        expected_factory_code(self, 'retry_not_authorized', artifact_factory.build_receipt,
                              idempotency_key='clave-de-prueba-05', attempt=2)
        authorized = artifact_factory.build_receipt(idempotency_key='clave-de-prueba-06', attempt=2,
                                                    authorized_retry=True, recorded_at=FIXED_TIME)
        self.assertEqual(authorized['attempt'], 2)
        expected_factory_code(self, 'invalid_field', artifact_factory.build_receipt,
                              idempotency_key='clave-de-prueba-07', attempt=0)
        expected_factory_code(self, 'invalid_field', artifact_factory.build_receipt,
                              idempotency_key='corta')

    def test_version_and_producer_are_enforced(self):
        receipt = artifact_factory.build_receipt(idempotency_key='clave-de-prueba-08',
                                                 recorded_at=FIXED_TIME)
        mutated = dict(receipt, receipt_version='2')
        self.assertEqual(artifact_factory.validate_receipt(mutated)['code'], 'unsupported_version')
        expected_factory_code(self, 'unsupported_version', artifact_factory.build_receipt,
                              idempotency_key='clave-de-prueba-09', receipt_version='2')
        expected_factory_code(self, 'unknown_producer', artifact_factory.build_receipt,
                              idempotency_key='clave-de-prueba-10', produced_by='agente-libre')
        expected_factory_code(self, 'unknown_producer', artifact_factory.ArtifactFactory, self.root,
                              producer='agente-libre')

    def test_receipt_vocabulary_matches_the_frozen_contract(self):
        schema = json.loads(RECEIPT_SCHEMA_PATH.read_text('utf-8'))
        rules = schema['$defs']['extension_rules']['properties']
        self.assertEqual(list(artifact_factory.FROZEN_ERROR_CODES), rules['error_codes']['const'])
        self.assertEqual(set(artifact_factory.REQUIRED_RECEIPT_FIELDS), set(schema['required']))
        self.assertEqual(artifact_factory.RECEIPT_VERSION, schema['properties']
                         [artifact_factory.RECEIPT_VERSION_FIELD]['const'])
        self.assertEqual(list(artifact_factory.PRODUCERS),
                         schema['properties']['produced_by']['enum'])
        self.assertEqual(list(artifact_factory.RESULT_OUTCOMES),
                         schema['properties']['result_outcome']['enum'])
        self.assertEqual(list(artifact_factory.RETRY_CLASSES),
                         schema['properties']['retry_class']['enum'])
        self.assertEqual(set(schema['prohibited_fields']), set(project_store.FORBIDDEN_FIELDS))
        self.assertEqual(set(artifact_factory.PROHIBITED_FIELD_NAMES),
                         set(project_store.FORBIDDEN_FIELDS))
        compatibility = schema['base_receipt_compatibility']
        self.assertEqual(list(artifact_factory.BASE_RECEIPT_KEYS), compatibility['base_top_level_keys'])
        self.assertEqual(list(artifact_factory.BASE_USAGE_KEYS), compatibility['base_usage_keys'])
        self.assertTrue(compatibility['redefinition_forbidden'])
        for const_rule in ('additive_only', 'base_key_redefinition', 'automatic_retry_of_paid_operations'):
            with self.subTest(rule=const_rule):
                self.assertIn(rules[const_rule]['const'], (True, False))


# --------------------------------------------------------------------------- #
# Fabrica: escritura local bajo la raiz declarada
# --------------------------------------------------------------------------- #
class FactoryWriteTests(unittest.TestCase):
    """La fabrica escribe solo bajo la raiz declarada, no reescribe y no aplica patches."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'artefactos'
        self.factory = artifact_factory.ArtifactFactory(self.root, clock=lambda: FIXED_TIME)

    def test_every_file_lives_under_the_declared_root_and_is_registered(self):
        records = (self.factory.write_report('informe-01', 'Informe', ['hallazgo']),
                   self.factory.write_ticket('ticket-01', 'TK-1', 'Resumen', ['Paso']),
                   self.factory.write_runbook('runbook-01', 'Runbook', ['Paso']))
        written = sorted(str(path.relative_to(self.root)).replace('\\', '/')
                         for path in self.root.rglob('*') if path.is_file())
        self.assertEqual(written, sorted(record.path for record in records))
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), ['artefactos'])
        self.assertEqual([record.path for record in self.factory.list_records()],
                         [record.path for record in records])

    def test_paths_outside_the_root_are_refused(self):
        for name in ('../fuera', 'sub/ruta', 'C:/absoluta', '/absoluta', 'Mayusculas', 'con espacio'):
            with self.subTest(name=name):
                with self.assertRaises(artifact_factory.ArtifactFactoryError) as caught:
                    self.factory.write('report', name, 'contenido')
                self.assertIn(caught.exception.code, ('unsafe_artifact_path', 'invalid_field'))
        for kind in ('deploy', 'script'):
            with self.subTest(kind=kind):
                expected_factory_code(self, 'unknown_artifact_kind', self.factory.write, kind,
                                      'nombre-01', 'contenido')
        expected_factory_code(self, 'unsafe_artifact_path', artifact_factory.check_relative_path,
                              '../fuera.md')
        expected_factory_code(self, 'unsafe_artifact_path', artifact_factory.check_relative_path,
                              'C:/produccion/archivo.md')

    def test_protected_suite_directories_are_refused(self):
        for directory in ('engine', 'web', 'docs', 'prompts', 'tests'):
            with self.subTest(directory=directory):
                expected_factory_code(self, 'protected_root', artifact_factory.check_declared_root,
                                      artifact_factory.SUITE_ROOT / directory)
        expected_factory_code(self, 'protected_root', artifact_factory.check_declared_root,
                              artifact_factory.SUITE_ROOT)
        self.assertEqual(artifact_factory.check_declared_root(self.root), self.root.resolve())

    def test_symlinked_directories_inside_the_root_are_not_followed(self):
        outside = self.base / 'fuera'
        outside.mkdir()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            (self.root / 'report').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest('El sistema no permite crear enlaces simbolicos: ' + type(error).__name__)
        expected_factory_code(self, 'unsafe_artifact_path', self.factory.write, 'report',
                              'informe-01', 'contenido')
        self.assertEqual([], sorted(path.name for path in outside.iterdir()))

    def test_an_artifact_is_not_rewritten_with_other_content(self):
        record = self.factory.write('report', 'informe-01', 'contenido original')
        expected_factory_code(self, 'artifact_already_written', self.factory.write, 'report',
                              'informe-01', 'otro contenido')
        self.assertEqual(record.sha256, hashlib.sha256(
            self.factory.read_bytes(record)).hexdigest())

    def test_repeating_the_idempotency_key_does_not_duplicate_the_effect(self):
        first = self.factory.write('report', 'informe-01', 'contenido', idempotency_key='clave-repetida-01')
        second = self.factory.write('report', 'informe-01', 'contenido', idempotency_key='clave-repetida-01')
        self.assertEqual(first.sha256, second.sha256)
        self.assertFalse(second.created)
        self.assertEqual(len(self.factory.list_records()), 1)
        expected_factory_code(self, 'idempotency_conflict', self.factory.write, 'report',
                              'informe-02', 'contenido distinto',
                              idempotency_key='clave-repetida-01')

    def test_tampering_is_detected_on_read_and_on_verify(self):
        record = self.factory.write('report', 'informe-01', 'contenido original')
        target = self.root / record.path
        target.write_text('contenido alterado', encoding='utf-8')
        report = self.factory.verify(record)
        self.assertFalse(report['valid'])
        self.assertEqual(report['code'], 'artifact_hash_mismatch')
        expected_factory_code(self, 'artifact_hash_mismatch', self.factory.read_text, record)
        target.unlink()
        self.assertEqual(self.factory.verify(record)['code'], 'artifact_missing')

    def test_credential_shaped_content_is_refused(self):
        for secret_key in ('api_key', 'password', 'access_token'):
            with self.subTest(key=secret_key):
                payload = json.dumps({'informe': {'agente': secret_key + ': valor'},
                                      secret_key: 'material'}, ensure_ascii=False)
                expected_factory_code(self, 'forbidden_field', self.factory.write, 'report',
                                      'informe-clave-01', payload)
        expected_factory_code(self, 'forbidden_field', self.factory.write, 'ticket', 'ticket-clave-01',
                              'El operador anoto password = material en el ticket.')
        self.assertEqual([], [path for path in self.root.rglob('*') if path.is_file()])

    def test_a_patch_is_text_and_is_not_applied(self):
        target = SUITE_ROOT / 'engine' / 'task_graph.py'
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        record = self.factory.write_patch('parche-01', [{'file': 'engine/task_graph.py',
                                                         'before': 'GRAPH_VERSION = 1',
                                                         'after': 'GRAPH_VERSION = 2'}],
                                          note='propuesta declarativa')
        text = self.factory.read_text(record)
        self.assertIn('--- a/engine/task_graph.py', text)
        self.assertIn('-GRAPH_VERSION = 1', text)
        self.assertIn('+GRAPH_VERSION = 2', text)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)
        self.assertIs(artifact_factory.inert_flags()['applies_patches'], False)
        other = SUITE_ROOT / 'engine' / 'evaluation_harness.py'
        self.assertNotIn('GRAPH_VERSION = 2', other.read_text('utf-8'))

    def test_documents_declare_no_guarantee_and_stay_local(self):
        report = artifact_factory.report_document('Auditoria', ['Caso A', 'Caso B'])
        ticket = artifact_factory.ticket_document('TK-1', 'Resumen', ['paso'], severity='high')
        runbook = artifact_factory.runbook_document('Reversion', ['paso'],
                                                   stop_conditions=['hash distinto'])
        for document in (report, ticket, runbook):
            with self.subTest(document=document.splitlines()[0]):
                self.assertIn('no constituye una garantia', document)


# --------------------------------------------------------------------------- #
# Fabrica: bundles sellados
# --------------------------------------------------------------------------- #
class FactoryBundleTests(unittest.TestCase):
    """El bundle sella cada miembro con su hash y su recibo, y detecta manipulacion."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'artefactos'
        self.factory = artifact_factory.ArtifactFactory(self.root, clock=lambda: FIXED_TIME)

    def test_bundle_seals_members_and_verifies_them(self):
        report = self.factory.write_report('informe-01', 'Informe', ['hallazgo'])
        runbook = self.factory.write_runbook('runbook-01', 'Reversion', ['paso'])
        bundle = self.factory.write_bundle('bundle-01', (report, runbook))
        document = json.loads(self.factory.read_text(bundle))
        self.assertEqual(document['bundle_version'], artifact_factory.BUNDLE_VERSION)
        self.assertEqual(document['member_count'], 2)
        self.assertEqual([member['sha256'] for member in document['members']],
                         [report.sha256, runbook.sha256])
        self.assertEqual(document['factory_seal'],
                         artifact_factory.sha256_hex(artifact_factory.canonical_json(
                             tuple(document['members']))))
        self.assertEqual([member['receipt']['artifact']['path'] for member in document['members']],
                         [report.path, runbook.path])
        verification = self.factory.verify_bundle(bundle)
        self.assertTrue(verification['valid'])
        self.assertTrue(verification['seal_valid'])
        self.assertEqual(verification['member_count'], 2)

    def test_bundle_detects_a_tampered_member(self):
        report = self.factory.write_report('informe-01', 'Informe', ['hallazgo'])
        bundle = self.factory.write_bundle('bundle-01', (report,))
        (self.root / report.path).write_text('alterado', encoding='utf-8')
        verification = self.factory.verify_bundle(bundle)
        self.assertFalse(verification['valid'])
        self.assertEqual(verification['code'], 'artifact_hash_mismatch')
        self.assertFalse(verification['members'][0]['valid'])

    def test_bundle_requires_members_and_a_registered_record(self):
        expected_factory_code(self, 'invalid_field', self.factory.write_bundle, 'bundle-01', ())
        expected_factory_code(self, 'invalid_field', self.factory.write_bundle, 'bundle-01',
                              ({'path': 'report/informe-01'},))


# --------------------------------------------------------------------------- #
# Acceptance 5: falsificador explicito de red / subprocess / push / merge / deploy
# --------------------------------------------------------------------------- #
class NetworkAndProcessFalsifierTests(unittest.TestCase):
    """Ningun modulo declara capacidad de red, proceso, push, merge o deploy."""

    def test_neither_module_declares_network_or_process_capability(self):
        for path in (HARNESS_PATH, FACTORY_PATH):
            with self.subTest(module=path.name):
                self.assertEqual(forbidden_usage(module_tree(path)), set())

    def test_the_detector_flags_a_network_or_process_source(self):
        sample = ('import subprocess\n'
                  'import urllib.request\n'
                  "def enviar():\n"
                  "    subprocess.run(['git', 'push'])\n"
                  "    urllib.request.urlopen('https://ejemplo.invalido/x')\n")
        findings = forbidden_usage(ast.parse(sample))
        self.assertIn('subprocess', findings)
        self.assertIn('urllib', findings)
        self.assertIn('run', findings)
        self.assertIn('urlopen', findings)
        other = 'def tarea():\n    mod.system("rm -rf /")\n'
        self.assertIn('system', forbidden_usage(ast.parse(other)))

    def test_the_detector_flags_a_network_url_literal(self):
        sample = "ENDPOINT = 'https://proveedor.invalido/v1/chat'\n"
        self.assertIn('url_literal', forbidden_usage(ast.parse(sample)))
        self.assertNotIn('url_literal', forbidden_usage(ast.parse(HARNESS_PATH.read_text('utf-8'))))

    def test_no_module_defines_a_deployment_or_push_function(self):
        for module in (evaluation_harness, artifact_factory):
            names = [name for name, value in vars(module).items()
                     if (inspect.isfunction(value) or inspect.isclass(value))
                     and getattr(value, '__module__', None) == module.__name__]
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIsNone(FORBIDDEN_FUNCTION_NAMES.match(name))
            methods = [method for _, klass in inspect.getmembers(module, inspect.isclass)
                       if klass.__module__ == module.__name__
                       for method in vars(klass) if not method.startswith('__')]
            for method in methods:
                with self.subTest(module=module.__name__, method=method):
                    self.assertIsNone(FORBIDDEN_FUNCTION_NAMES.match(method))

    def test_deployment_flags_are_declared_false(self):
        flags = artifact_factory.inert_flags()
        for name in ('network_allowed', 'spawns_processes', 'runs_git', 'pushes',
                     'opens_pull_requests', 'merges', 'deploys', 'sends_to_providers',
                     'applies_patches', 'mutates_production_instruction_files',
                     'stores_credentials', 'persists_a_ledger'):
            with self.subTest(flag=name):
                self.assertIs(flags[name], False)
        self.assertIs(flags['writes_to_disk'], True)
        self.assertIs(flags['writes_only_under_declared_root'], True)

    def test_factory_has_no_mutable_global_state_and_only_declared_imports(self):
        offenders = sorted(name for name, value in vars(artifact_factory).items()
                           if isinstance(value, MUTABLE_CONTAINERS) and name != '__builtins__')
        self.assertEqual(offenders, [])
        roots, relative = imported_roots(module_tree(FACTORY_PATH))
        self.assertEqual(roots & FORBIDDEN_IMPORT_ROOTS, set())
        self.assertLessEqual(roots, FACTORY_ALLOWED_IMPORT_ROOTS | FACTORY_ENGINE_IMPORTS)
        self.assertIn('project_store', relative)
        own = sorted(name for name, value in vars(artifact_factory).items()
                     if inspect.isfunction(value)
                     and getattr(value, '__module__', None) == artifact_factory.__name__
                     and not name.startswith('_'))
        self.assertEqual(own, sorted(FACTORY_PUBLIC_FUNCTIONS))
        self.assertEqual(tuple(error_class.code for error_class in artifact_factory.ERROR_CLASSES),
                         tuple(dict.fromkeys(artifact_factory.FACTORY_ERROR_CODES)))


# --------------------------------------------------------------------------- #
# Contratos congelados: TaskSpec, politica y recepcion
# --------------------------------------------------------------------------- #
class FrozenContractCrossCheckTests(unittest.TestCase):
    """Los modulos consumen los tres contratos congelados sin reinterpretarlos."""

    def test_case_results_are_a_subset_of_the_frozen_criterion_states(self):
        taskspec = json.loads(TASKSPEC_SCHEMA_PATH.read_text('utf-8'))
        criterion_states = taskspec['properties']['acceptance_criteria']['items']['properties']['status']['enum']
        self.assertLessEqual(set(evaluation_harness.CASE_RESULTS), set(criterion_states))
        self.assertIn('not_run', evaluation_harness.CASE_RESULTS)
        self.assertNotIn('pending', evaluation_harness.CASE_RESULTS)
        self.assertEqual(evaluation_harness.HARNESS_VERSION,
                         taskspec['properties']['taskspec_version']['const'])

    def test_falsifiers_and_criteria_are_read_from_the_frozen_contract(self):
        taskspec = json.loads(TASKSPEC_SCHEMA_PATH.read_text('utf-8'))
        self.assertEqual(set(taskspec['properties']['falsifiers']['items']['required']),
                         {'falsifier_id', 'statement', 'how_detected'})
        self.assertEqual(set(taskspec['properties']['acceptance_criteria']['items']['required']),
                         {'criterion', 'verify'})
        policy = json.loads(POLICY_SCHEMA_PATH.read_text('utf-8'))
        self.assertEqual(list(evaluation_harness.MANDATORY_GATES),
                         policy['$defs']['mandatory_gates']['properties']['gates']['const'])
        approval = policy['$defs']['approval_record']
        self.assertEqual(set(approval['required']),
                         {'gate', 'approver_role', 'approved_at', 'scope_hash', 'one_shot'})
        self.assertEqual(set(vars(evaluation_harness.Approval(gate='write', approver_role='rol',
                                                              approved_at=FIXED_TIME,
                                                              scope_hash='0' * 64))),
                         {'gate', 'approver_role', 'approved_at', 'scope_hash', 'one_shot'})
        self.assertEqual(approval['properties']['one_shot']['const'], True)

    def test_autonomy_ceiling_follows_the_task_graph_vocabulary(self):
        self.assertEqual(tuple(ceiling[-1] for _, ceiling in evaluation_harness.AUTONOMY_CEILING),
                         task_graph.AUTONOMY_LEVELS)
        for _, ceiling in evaluation_harness.AUTONOMY_CEILING:
            with self.subTest(ceiling=ceiling):
                self.assertLessEqual(set(ceiling), set(task_graph.AUTONOMY_LEVELS))
        battery = evaluation_harness.battery_for('executor')
        gate_check = [check for check in battery.checks if check.check_id == 'approval_gate_declared'][0]
        self.assertEqual(gate_check.expected, evaluation_harness.MANDATORY_GATES)


# --------------------------------------------------------------------------- #
# Tamano de la suite
# --------------------------------------------------------------------------- #
class SuiteSizeTests(unittest.TestCase):
    """Criterio del encargo: al menos 16 casos, incluidos todos los negativos."""

    def test_module_declares_at_least_sixteen_cases_and_the_required_negatives(self):
        module = sys.modules[__name__]
        case_count = unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
        self.assertGreaterEqual(case_count, 16)
        names = {name for name, value in vars(module).items()
                 if isinstance(value, type) and issubclass(value, unittest.TestCase)
                 for name in dir(value) if name.startswith('test_')}
        required = {'test_spec_without_criteria_is_not_evaluated_and_never_pass',
                    'test_apply_proposal_returns_a_new_declaration_and_never_mutates',
                    'test_proposal_targeting_a_production_path_is_rejected',
                    'test_module_has_no_write_or_process_capability',
                    'test_approved_proposal_versions_and_declares_an_explicit_rollback_route',
                    'test_rollback_with_a_snapshot_that_does_not_match_is_unavailable',
                    'test_every_written_artifact_carries_sha256_and_its_receipt',
                    'test_artifact_without_hash_is_rejected',
                    'test_neither_module_declares_network_or_process_capability',
                    'test_the_detector_flags_a_network_or_process_source',
                    'test_fail_blocked_and_not_run_are_preserved_and_never_pass',
                    'test_protected_suite_directories_are_refused'}
        self.assertLessEqual(required, names)


if __name__ == '__main__':
    unittest.main(verbosity=2)
