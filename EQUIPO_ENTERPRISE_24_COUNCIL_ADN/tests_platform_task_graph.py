"""Pruebas offline del Task Graph Engine (flujo I1). Declarativo, inerte y sin red.

Verifica el contrato congelado `docs/plataforma/taskspec.schema.json` (TaskSpec v1 /
TaskGraph v1): campos obligatorios y version, DAG (ciclos, identificadores duplicados,
dependencias inexistentes, auto-dependencias), orden topologico determinista, hash
determinista, autonomia por tarea con aprobacion explicita, idempotencia, inmutabilidad y
ausencia de efectos (red, ficheros, instalacion, permisos o mutacion de estado global).

Solo biblioteca estandar. No usa red, claves, proveedores, modelos ni instala nada; no
modifica ningun archivo de la suite. Todas las construcciones de este modulo son
declaraciones: construir un grafo no ejecuta, no programa y no despacha ninguna tarea.
"""
import ast
import copy
import dataclasses
import inspect
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from engine import project_store
from engine import task_graph

SUITE_ROOT = Path(__file__).resolve().parent
MODULE_PATH = SUITE_ROOT / 'engine' / 'task_graph.py'
SCHEMA_PATH = SUITE_ROOT / 'docs' / 'plataforma' / 'taskspec.schema.json'

# Literal fijado una vez para la declaracion de `fixture_graph()`: si el algoritmo de
# hash o la declaracion cambian, esta prueba lo detecta en cualquier proceso y con
# cualquier PYTHONHASHSEED, sin depender del estado de esta sesion.
FIXTURE_GRAPH_SHA256 = 'c0690c65c91bc5b55be60136f3f4f9b7453eb04708794286e0a54027998d8b53'
FIXTURE_GRAPH_ORDER = ('t1', 't2', 't3')

ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'hashlib',
                                  'json', 'math', 're'})
ENGINE_IMPORT_NAMES = frozenset({'project_store'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'os', 'io', 'pathlib', 'socket', 'ssl', 'urllib', 'http',
                                    'ftplib', 'smtplib', 'telnetlib', 'subprocess', 'shutil',
                                    'tempfile', 'importlib', 'ctypes', 'multiprocessing',
                                    'asyncio', 'webbrowser', 'pickle', 'sqlite3', 'xmlrpc',
                                    'signal', 'threading'})
FORBIDDEN_CALLS = frozenset({'open', 'eval', 'exec', 'compile', '__import__', 'input', 'breakpoint'})
FORBIDDEN_ATTRIBUTES = frozenset({'system', 'popen', 'Popen', 'check_call', 'check_output', 'run',
                                  'urlopen', 'connect', 'sendall', 'recv', 'write', 'writelines',
                                  'write_text', 'write_bytes', 'read_text', 'read_bytes', 'unlink',
                                  'mkdir', 'rmdir', 'remove', 'spawn', 'fork', 'execv'})
FORBIDDEN_FUNCTION_NAMES = re.compile(r'(?i)^(grant|install|enable|authorize|elevate|unlock|permit|'
                                      r'promote|dispatch|execute|run|deploy|send)')
MUTABLE_CONTAINERS = (list, dict, set, bytearray)
PUBLIC_FUNCTIONS = ('build_graph', 'build_taskspec', 'canonical_task_list', 'compute_graph_sha256',
                    'duplicate_idempotency_keys', 'forbidden_field_name', 'inspect_graph',
                    'is_write_capable_level')
CROSS_PROCESS_CODE = ('import json, sys;'
                      'sys.path.insert(0, sys.argv[1]);'
                      'from engine import task_graph;'
                      'graph = task_graph.build_graph(json.loads(sys.argv[2]));'
                      "print(graph.graph_sha256 + ' ' + ','.join(graph.topological_order))")


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


def fixture_graph():
    return [declaration('t1'), declaration('t2', ('t1',)), declaration('t3', ('t1',))]


def module_tree():
    return ast.parse(MODULE_PATH.read_text('utf-8'), filename=str(MODULE_PATH))


def expected_code(test_case, expected, callable_under_test, *args, **kwargs):
    """Ejecuta algo que debe fallar con el codigo tipado esperado y lo devuelve."""
    with test_case.assertRaises(task_graph.TaskGraphError) as caught:
        callable_under_test(*args, **kwargs)
    test_case.assertEqual(caught.exception.code, expected)
    test_case.assertNotIsInstance(caught.exception, KeyError)
    test_case.assertNotIsInstance(caught.exception, AttributeError)
    test_case.assertIsInstance(caught.exception, ValueError)
    return caught.exception


def reference_verdict(records):
    """Oraculo independiente del veredicto estructural (Kahn + ids + auto/desconocidas).

    No comparte codigo con `engine/task_graph.py`: contrasta el modulo contra una
    implementacion escrita aparte, como la sonda diferencial de la revision RV1.
    """
    identifiers = [record['task_id'] for record in records]
    if not records:
        return 'empty_graph'
    if len(identifiers) != len(set(identifiers)):
        return 'duplicate_task_id'
    known = set(identifiers)
    for record in records:
        for dependency in record['depends_on']:
            if dependency == record['task_id']:
                return 'self_dependency'
            if dependency not in known:
                return 'unknown_dependency'
    remaining = {record['task_id']: set(record['depends_on']) for record in records}
    while remaining:
        ready = [task_id for task_id, dependencies in remaining.items() if not dependencies]
        if not ready:
            return 'cycle_detected'
        for task_id in ready:
            remaining.pop(task_id)
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return 'valid'


def dependency_label(records):
    """Etiqueta compacta de una funcion de dependencia, para diagnosticos del contraste."""
    return ';'.join(record['task_id'] + '>' + ','.join(record['depends_on']) for record in records)


def dependency_space(identifiers):
    """Todas las funciones de dependencia sobre `identifiers`: subconjuntos de cada nodo."""
    return [tuple(combination) for size in range(len(identifiers) + 1)
            for combination in itertools.combinations(identifiers, size)]


class TaskSpecFieldTests(unittest.TestCase):
    """Campos obligatorios, version, autonomia, presupuesto, criterios e idempotencia."""

    def test_declaration_carries_version_and_every_required_field(self):
        spec = task_graph.build_taskspec(declaration('t1'))
        self.assertEqual(spec.taskspec_version, '1')
        self.assertEqual(spec.task_id, 't1')
        declaration_keys = set(spec.to_dict())
        self.assertLessEqual(set(task_graph.TASKSPEC_REQUIRED_FIELDS), declaration_keys)
        self.assertEqual(declaration_keys, set(task_graph.TASKSPEC_FIELDS))
        self.assertEqual(task_graph.build_graph(fixture_graph()).taskspec_version, '1')
        minimal = declaration('t1')
        for optional in ('agent_ref', 'created_at', 'evidence_refs'):
            minimal.pop(optional)
        minimal_keys = set(task_graph.build_taskspec(minimal).to_dict())
        self.assertNotIn('agent_ref', minimal_keys)
        self.assertNotIn('created_at', minimal_keys)
        self.assertIn('evidence_refs', minimal_keys)
        self.assertLessEqual(minimal_keys, set(task_graph.TASKSPEC_FIELDS))

    def test_missing_required_field_raises_typed_error_never_keyerror(self):
        cases = [name for name in task_graph.TASKSPEC_REQUIRED_FIELDS
                 if name not in task_graph.DEFAULTED_REQUIRED_FIELDS]
        self.assertEqual(len(cases), 9)
        for name in cases:
            with self.subTest(field=name):
                record = declaration('t1')
                record.pop(name)
                expected_code(self, 'missing_required_field', task_graph.build_taskspec, record)

    def test_nested_required_fields_also_fail_with_a_typed_error(self):
        for label, mutate, code in (
                ('budget sin requests', lambda r: r['budget'].pop('requests'), 'missing_required_field'),
                ('budget ausente', lambda r: r.pop('budget'), 'missing_required_field'),
                ('criterio sin verify', lambda r: r['acceptance_criteria'][0].pop('verify'), 'missing_required_field'),
                ('falsificador sin statement', lambda r: r['falsifiers'][0].pop('statement'), 'missing_required_field'),
                ('criterios vacios', lambda r: r.__setitem__('acceptance_criteria', []), 'missing_acceptance_criterion'),
                ('falsificadores vacios', lambda r: r.__setitem__('falsifiers', []), 'missing_falsifier')):
            with self.subTest(case=label):
                record = declaration('t1')
                mutate(record)
                expected_code(self, code, task_graph.build_taskspec, record)

    def test_autonomy_level_defaults_to_observe_and_alias_matches(self):
        without_level = declaration('t1')
        without_level.pop('autonomy_level')
        spec = task_graph.build_taskspec(without_level)
        self.assertEqual(spec.autonomy_level, task_graph.DEFAULT_AUTONOMY_LEVEL)
        self.assertEqual(spec.autonomy_level, 'observe')
        self.assertEqual(spec.autonomy_state, 'observe')
        self.assertIn('autonomy_level', spec.to_dict())

    def test_null_autonomy_level_is_rejected_instead_of_defaulted(self):
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', autonomy_level=None))

    def test_every_autonomy_level_is_declared_and_validated(self):
        self.assertEqual(task_graph.AUTONOMY_LEVELS, ('observe', 'propose', 'prepare', 'execute-approved'))
        self.assertEqual(task_graph.is_write_capable_level('prepare'), True)
        self.assertEqual(task_graph.is_write_capable_level('execute-approved'), True)
        self.assertEqual(task_graph.is_write_capable_level('observe'), False)
        self.assertEqual(task_graph.is_write_capable_level('propose'), False)
        for level in ('observe', 'propose'):
            with self.subTest(level=level):
                self.assertEqual(task_graph.build_taskspec(declaration('t1', autonomy_level=level)).autonomy_level, level)
        for level in ('prepare', 'execute-approved'):
            with self.subTest(level=level):
                spec = task_graph.build_taskspec(declaration('t1', autonomy_level=level), approved=True)
                self.assertEqual(spec.autonomy_level, level)
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', autonomy_level='autonomous'))

    def test_write_capable_levels_require_explicit_boolean_approval(self):
        for level in task_graph.WRITE_CAPABLE_AUTONOMY_LEVELS:
            for approval in (False, None):
                with self.subTest(level=level, approved=approval):
                    expected_code(self, 'approval_required', task_graph.build_taskspec,
                                  declaration('t1', autonomy_level=level), approved=approval)
            for orphan in ('yes', 'true', 1, 0.5, object()):
                with self.subTest(level=level, approved=orphan):
                    expected_code(self, 'invalid_field', task_graph.build_taskspec,
                                  declaration('t1', autonomy_level=level), approved=orphan)
            for ungranted in ({'approved': True}, ['otra-tarea'], []):
                with self.subTest(level=level, approved=ungranted):
                    expected_code(self, 'approval_required', task_graph.build_taskspec,
                                  declaration('t1', autonomy_level=level), approved=ungranted)
            with self.subTest(level=level, approved=True):
                self.assertEqual(task_graph.build_taskspec(declaration('t1', autonomy_level=level),
                                                           approved=True).autonomy_level, level)
        for granted in (True, ['t1'], {'t1': True}):
            with self.subTest(granted=granted):
                graph = task_graph.build_graph([declaration('t1', autonomy_level='prepare')], approved=granted)
                self.assertEqual(graph.tasks[0].autonomy_level, 'prepare')
        expected_code(self, 'invalid_field', task_graph.build_graph,
                      [declaration('t1', autonomy_level='prepare')], approved='yes')

    def test_direct_construction_and_replace_cannot_bypass_approval(self):
        fields = dict(task_id='t1', title='Tarea t1', intent='Declarar sin ejecutar.',
                      budget=task_graph.Budget(tokens=1, money_usd=0.0, time_seconds=1, requests=1),
                      idempotency_key='idem-t1-0001')
        expected_code(self, 'approval_required', task_graph.TaskSpec, autonomy_level='execute-approved', **fields)
        spec = task_graph.build_taskspec(declaration('t1'))
        expected_code(self, 'approval_required', dataclasses.replace, spec, autonomy_level='execute-approved')
        replaced = dataclasses.replace(spec, autonomy_level='prepare', autonomy_approved=True)
        self.assertEqual(replaced.autonomy_level, 'prepare')
        self.assertEqual(replaced.to_dict()['autonomy_level'], 'prepare')

    def test_task_spec_and_budget_are_immutable(self):
        spec = task_graph.build_taskspec(declaration('t1'))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            spec.title = 'otro titulo'
        with self.assertRaises(dataclasses.FrozenInstanceError):
            spec.depends_on = ('t2',)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            spec.budget.tokens = 0
        self.assertIsInstance(spec.depends_on, tuple)
        self.assertIsInstance(spec.acceptance_criteria, tuple)
        self.assertIsInstance(spec.falsifiers, tuple)
        self.assertIsInstance(spec.evidence_refs, tuple)
        self.assertIsInstance(task_graph.build_taskspec(declaration('t1', depends_on=['t2'])).depends_on, tuple)

    def test_budget_requires_the_four_magnitudes(self):
        self.assertEqual(task_graph.BUDGET_FIELDS, ('tokens', 'money_usd', 'time_seconds', 'requests'))
        for name in task_graph.BUDGET_FIELDS:
            with self.subTest(magnitude=name):
                record = declaration('t1')
                record['budget'].pop(name)
                expected_code(self, 'missing_required_field', task_graph.build_taskspec, record)
        expected_code(self, 'invalid_field', task_graph.build_taskspec,
                      declaration('t1', budget=[1000, 0.0, 60, 5]))
        expected_code(self, 'invalid_field', task_graph.build_taskspec,
                      declaration('t1', budget={'tokens': 1, 'money_usd': 0.0, 'time_seconds': 1,
                                                'requests': 1, 'extra': 0}))

    def test_negative_budget_uses_its_own_code(self):
        for name in ('tokens', 'time_seconds', 'requests'):
            with self.subTest(magnitude=name):
                budget = {'tokens': 1, 'money_usd': 0.0, 'time_seconds': 1, 'requests': 1}
                budget[name] = -1
                expected_code(self, 'negative_budget', task_graph.build_taskspec,
                              declaration('t1', budget=budget))
        expected_code(self, 'negative_budget', task_graph.build_taskspec,
                      declaration('t1', budget={'tokens': 1, 'money_usd': -0.01, 'time_seconds': 1, 'requests': 1}))
        expected_code(self, 'negative_budget', task_graph.Budget, tokens=-1, money_usd=0.0,
                      time_seconds=0, requests=0)

    def test_budget_rejects_booleans_non_integers_and_non_finite_numbers(self):
        cases = (('tokens booleano', 'tokens', True), ('tokens fraccionario', 'tokens', 1.5),
                 ('requests texto', 'requests', '5'), ('money booleano', 'money_usd', False),
                 ('money infinito', 'money_usd', float('inf')), ('money nan', 'money_usd', float('nan')))
        for label, name, value in cases:
            with self.subTest(case=label):
                budget = {'tokens': 1, 'money_usd': 0.0, 'time_seconds': 1, 'requests': 1}
                budget[name] = value
                expected_code(self, 'invalid_field', task_graph.build_taskspec,
                              declaration('t1', budget=budget))

    def test_criterion_status_vocabulary_keeps_not_run_distinct(self):
        self.assertEqual(task_graph.CRITERION_STATES, ('pending', 'passed', 'failed', 'not_run'))
        self.assertEqual(task_graph.DEFAULT_CRITERION_STATE, 'pending')
        self.assertEqual(task_graph.build_taskspec(declaration('t1')).acceptance_criteria[0].status, 'pending')
        for state in task_graph.CRITERION_STATES:
            with self.subTest(state=state):
                record = declaration('t1', acceptance_criteria=[{'criterion': 'c', 'verify': 'v', 'status': state}])
                self.assertEqual(task_graph.build_taskspec(record).acceptance_criteria[0].status, state)
        for state in ('PASSED', 'not run', 'unknown', None, True):
            with self.subTest(state=state):
                record = declaration('t1', acceptance_criteria=[{'criterion': 'c', 'verify': 'v', 'status': state}])
                expected_code(self, 'invalid_field', task_graph.build_taskspec, record)

    def test_idempotency_key_is_validated(self):
        self.assertEqual(task_graph.build_taskspec(declaration('t1')).idempotency_key, 'idem-t1-0001')
        for bad in ('short', 'con espacio', 'x' * 129, 42, None, ''):
            with self.subTest(key=bad):
                expected_code(self, 'invalid_idempotency_key', task_graph.build_taskspec,
                              declaration('t1', idempotency_key=bad))

    def test_dependency_list_shape_and_uniqueness(self):
        self.assertEqual(task_graph.build_taskspec(declaration('t1', depends_on=[])).depends_on, ())
        self.assertEqual(task_graph.build_taskspec(declaration('t1', depends_on=['t2', 't3'])).depends_on, ('t2', 't3'))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', depends_on='t2'))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', depends_on=['t2', 't2']))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', depends_on=['T2']))
        expected_code(self, 'self_dependency', task_graph.build_taskspec, declaration('t1', depends_on=['t1']))

    def test_credential_field_names_are_rejected_by_the_project_store_guard(self):
        self.assertEqual(task_graph.PROHIBITED_FIELD_NAMES, frozenset(project_store.FORBIDDEN_FIELDS))
        self.assertEqual(len(task_graph.PROHIBITED_FIELD_NAMES), 13)
        for name in sorted(project_store.FORBIDDEN_FIELDS):
            with self.subTest(field=name):
                record = declaration('t1')
                record[name] = 'no-declarable'
                error = expected_code(self, 'forbidden_field', task_graph.build_taskspec, record)
                self.assertNotIn('no-declarable', str(error))
        for name in ('apiKey', 'refreshToken', 'Authorization', 'a-p-i-k-e-y', 'privateKey'):
            with self.subTest(variant=name):
                record = declaration('t1')
                record[name] = 'no-declarable'
                expected_code(self, 'forbidden_field', task_graph.build_taskspec, record)
        nested = declaration('t1', acceptance_criteria=[{'criterion': 'c', 'verify': 'v', 'password': 'no-declarable'}])
        expected_code(self, 'forbidden_field', task_graph.build_taskspec, nested)
        budget = {'tokens': 1, 'money_usd': 0.0, 'time_seconds': 1, 'requests': 1, 'csrf': 'no-declarable'}
        expected_code(self, 'forbidden_field', task_graph.build_taskspec, declaration('t1', budget=budget))
        # El guard mira nombres de campo, nunca valores: `tokens` es presupuesto (D-R0-1) y un
        # valor con esa palabra no se rechaza.
        self.assertFalse(task_graph.forbidden_field_name('tokens'))
        self.assertTrue(task_graph.forbidden_field_name('password'))
        self.assertEqual(task_graph.build_taskspec(
            declaration('t1', title='Rotar el password del operador')).budget.tokens, 1000)

    def test_unknown_field_is_rejected(self):
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', extra='x'))
        expected_code(self, 'invalid_field', task_graph.build_taskspec,
                      declaration('t1', acceptance_criteria=[{'criterion': 'c', 'verify': 'v', 'extra': 'x'}]))
        expected_code(self, 'invalid_field', task_graph.build_taskspec,
                      declaration('t1', falsifiers=[{'falsifier_id': 'fr01', 'statement': 's',
                                                     'how_detected': 'h', 'extra': 'x'}]))

    def test_direct_construction_normalizes_and_validates_nested_values(self):
        spec = task_graph.TaskSpec(task_id='t1', title='Tarea t1', intent='Declarar sin ejecutar.',
                                   budget={'tokens': 7, 'money_usd': 1, 'time_seconds': 2, 'requests': 3},
                                   idempotency_key='idem-t1-0001',
                                   depends_on=['t2'],
                                   acceptance_criteria=[{'criterion': 'c', 'verify': 'v'}],
                                   falsifiers=[{'falsifier_id': 'fr01', 'statement': 's', 'how_detected': 'h'}])
        self.assertIsInstance(spec.budget, task_graph.Budget)
        self.assertEqual(spec.budget.to_dict(), {'tokens': 7, 'money_usd': 1.0, 'time_seconds': 2, 'requests': 3})
        self.assertEqual(spec.depends_on, ('t2',))
        self.assertEqual(spec.acceptance_criteria[0].status, 'pending')
        self.assertEqual(spec.to_dict()['falsifiers'][0]['falsifier_id'], 'fr01')
        graph = task_graph.build_graph(fixture_graph())
        rebuilt = task_graph.TaskGraph(tasks=list(graph.tasks), topological_order=list(graph.topological_order),
                                       graph_sha256=graph.graph_sha256)
        self.assertIsInstance(rebuilt.tasks, tuple)
        self.assertIsInstance(rebuilt.topological_order, tuple)
        self.assertEqual(rebuilt.to_dict(), graph.to_dict())
        expected_code(self, 'invalid_field', task_graph.TaskGraph, tasks=(declaration('t1'),),
                      topological_order=('t1',), graph_sha256='0' * 64)

    def test_identifier_length_and_timestamp_patterns(self):
        self.assertEqual(task_graph.build_taskspec(declaration('a' * 64)).task_id, 'a' * 64)
        for bad in ('a', 'A1', 'a b', 'a' * 65, '-t1', '_t1', ''):
            with self.subTest(task_id=bad):
                expected_code(self, 'invalid_field', task_graph.build_taskspec,
                              declaration(bad, idempotency_key='idem-fijado-0001'))
        self.assertEqual(task_graph.build_taskspec(
            declaration('t1', created_at='2026-10-10T00:00:00.123456Z')).created_at, '2026-10-10T00:00:00.123456Z')
        for bad in ('2026-10-10', '2026-10-10T00:00:00', '2026-10-10T00:00:00+00:00', 1, None):
            with self.subTest(created_at=bad):
                expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', created_at=bad))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', agent_ref=None))

    def test_text_is_validated_in_utf8_for_deterministic_hashing(self):
        self.assertEqual(task_graph.build_taskspec(declaration('t1', title='Tarea con acentos: evidencia.')).title,
                         'Tarea con acentos: evidencia.')
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', title='a\ud800b'))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', title=''))
        expected_code(self, 'invalid_field', task_graph.build_taskspec, declaration('t1', intent='x' * 4001))

    def test_approval_authorizes_nothing_in_the_declaration(self):
        graph = task_graph.build_graph([declaration('t1', autonomy_level='execute-approved')], approved=True)
        spec = graph.tasks[0]
        twin = task_graph.build_taskspec(declaration('t1'))
        differences = sorted(key for key in set(spec.to_dict()) | set(twin.to_dict())
                             if spec.to_dict().get(key) != twin.to_dict().get(key))
        self.assertEqual(differences, ['autonomy_level'])
        for absent in ('granted', 'permission', 'authorized', 'approval', 'lease', 'token'):
            self.assertNotIn(absent, spec.to_dict())
        self.assertEqual(dataclasses.replace(twin, autonomy_level='execute-approved',
                                             autonomy_approved=True), spec)


class TaskGraphStructureTests(unittest.TestCase):
    """Rechazos estructurales del DAG con el vocabulario congelado."""

    def test_cycle_is_rejected_with_its_own_code(self):
        error = expected_code(self, 'cycle_detected', task_graph.build_graph,
                              [declaration('ta', ('tb',)), declaration('tb', ('ta',))])
        self.assertIn('ta', str(error))
        expected_code(self, 'cycle_detected', task_graph.build_graph,
                      [declaration('ta', ('tc',)), declaration('tb', ('ta',)), declaration('tc', ('tb',))])
        expected_code(self, 'cycle_detected', task_graph.build_graph,
                      [declaration('ta', ('tb',)), declaration('tb', ('tc',)),
                       declaration('tc', ('td',)), declaration('td', ('tb',))])

    def test_duplicate_task_ids_are_rejected(self):
        error = expected_code(self, 'duplicate_task_id', task_graph.build_graph,
                              [declaration('ta'), declaration('ta'), declaration('tb')])
        self.assertIn('ta', str(error))
        first = task_graph.build_taskspec(declaration('ta'))
        second = task_graph.build_taskspec(declaration('ta'))
        expected_code(self, 'duplicate_task_id', task_graph.TaskGraph, tasks=(first, second),
                      topological_order=('ta',), graph_sha256='0' * 64)

    def test_unknown_dependency_is_rejected(self):
        error = expected_code(self, 'unknown_dependency', task_graph.build_graph,
                              [declaration('ta', ('zz',)), declaration('tb', ('zz',))])
        self.assertIn('ta -> zz', str(error))
        self.assertIn('tb -> zz', str(error))

    def test_self_dependency_is_rejected(self):
        expected_code(self, 'self_dependency', task_graph.build_graph, [declaration('ta', ('ta',))])

    def test_empty_graph_is_rejected(self):
        expected_code(self, 'empty_graph', task_graph.build_graph, [])
        self.assertEqual(task_graph.inspect_graph([])['code'], 'empty_graph')

    def test_unsupported_version_is_rejected(self):
        for version in ('2', 1, None, '1.0', ''):
            with self.subTest(version=version):
                expected_code(self, 'unsupported_version', task_graph.build_graph,
                              [dict(declaration('ta'), taskspec_version=version)])
        with self.assertRaises(task_graph.UnsupportedVersionError):
            task_graph.TaskGraph(tasks=task_graph.build_graph(fixture_graph()).tasks,
                                 topological_order=FIXTURE_GRAPH_ORDER,
                                 graph_sha256=FIXTURE_GRAPH_SHA256, graph_version='2')

    def test_every_structural_rejection_uses_the_frozen_vocabulary(self):
        self.assertEqual(len(task_graph.GRAPH_ERROR_CODES), 10)
        cases = ((('cycle_detected'), [declaration('ta', ('tb',)), declaration('tb', ('ta',))]),
                 (('duplicate_task_id'), [declaration('ta'), declaration('ta')]),
                 (('unknown_dependency'), [declaration('ta', ('zz',))]),
                 (('self_dependency'), [declaration('ta', ('ta',))]),
                 (('empty_graph'), []),
                 (('unsupported_version'), [dict(declaration('ta'), taskspec_version='2')]))
        for code, records in cases:
            with self.subTest(expected=code):
                error = expected_code(self, code, task_graph.build_graph, records)
                self.assertIn(error.code, task_graph.GRAPH_ERROR_CODES)
                self.assertIsInstance(error, task_graph.GraphValidationError)
        for error_type in task_graph.ERROR_CLASSES:
            with self.subTest(error=error_type.__name__):
                self.assertIn(error_type.code, task_graph.ERROR_CODES)
        self.assertEqual({error_type.code for error_type in task_graph.ERROR_CLASSES},
                         set(task_graph.ERROR_CODES))
        self.assertEqual(len(task_graph.ERROR_CLASSES), 14)
        structural = {error_type.code for error_type in task_graph.ERROR_CLASSES
                      if issubclass(error_type, task_graph.GraphValidationError)}
        self.assertEqual(structural, set(task_graph.GRAPH_ERROR_CODES))
        self.assertEqual({error_type.code for error_type in task_graph.ERROR_CLASSES} - structural,
                         set(task_graph.FIELD_ERROR_CODES))
        self.assertNotIn(task_graph.TaskGraphError.code, task_graph.ERROR_CODES)
        self.assertNotIn(task_graph.GraphValidationError.code, task_graph.ERROR_CODES)

    def test_topological_order_follows_the_frozen_rule(self):
        records = [declaration('r1'), declaration('a1', ('r1',)), declaration('b1', ('r1',)),
                   declaration('c1', ('a1', 'b1')), declaration('z1', ('c1',)), declaration('e1', ('r1', 'a1'))]
        self.assertEqual(task_graph.build_graph(records).topological_order,
                         ('r1', 'a1', 'b1', 'c1', 'e1', 'z1'))
        self.assertEqual(task_graph.build_graph(list(reversed(records))).topological_order,
                         ('r1', 'a1', 'b1', 'c1', 'e1', 'z1'))
        self.assertIn('cadena de dependencias mas larga', task_graph.ORDER_RULE)
        self.assertIn('JSON canonico', task_graph.HASH_RULE)

    def test_specs_and_declarations_can_be_mixed_and_are_equivalent(self):
        records = fixture_graph()
        from_records = task_graph.build_graph(records)
        from_specs = task_graph.build_graph([task_graph.build_taskspec(record) for record in records])
        mixed = task_graph.build_graph([task_graph.build_taskspec(records[0]), records[1], records[2]])
        for candidate in (from_specs, mixed):
            self.assertEqual(candidate.topological_order, from_records.topological_order)
            self.assertEqual(candidate.graph_sha256, from_records.graph_sha256)


class ProbeP01CycleRegressionTests(unittest.TestCase):
    """Regresion RV1-01: el recorrido del ciclo no puede abandonar los nodos no resueltos.

    Formas B/C/D de la sonda p01 de la revision RV1 mas la entrada minima y el ciclo puro
    de control. `inspect_graph` se llama SIN `try/except`: un escape (IndexError, cualquier
    excepcion no tipada) falla la prueba por si mismo, no se oculta.
    """

    SHAPES = (
        ('A ciclo puro (control)', [('ta', ('tb',)), ('tb', ('ta',))]),
        ('entrada minima de p01 (ciclo con raiz resuelta de por medio)',
         [('aaa', ()), ('qqq', ('zzz',)), ('zzz', ('aaa', 'qqq'))]),
        ('B ciclo con raiz resuelta de por medio',
         [('aaa', ()), ('qqq', ('zzz',)), ('zzz', ('aaa', 'qqq'))]),
        ('C cadena larga hasta hoja resuelta',
         [('a0', ()), ('c1', ('c2',)), ('c2', ('c3',)), ('c3', ('a0', 'c1'))]),
        ('D hoja resuelta en medio del ciclo',
         [('m0', ()), ('p1', ('p2', 'm0')), ('p2', ('p1',))]),
    )

    def test_inspect_graph_returns_cycle_detected_without_escaping(self):
        for label, shape in self.SHAPES:
            with self.subTest(shape=label):
                records = [declaration(task_id, dependencies) for task_id, dependencies in shape]
                verdict = task_graph.inspect_graph(records)
                self.assertFalse(verdict['valid'])
                self.assertEqual(verdict['code'], 'cycle_detected')
                self.assertIsNone(verdict['graph_sha256'])
                self.assertIsNone(verdict['task_count'])
                self.assertEqual(verdict['topological_order'], ())
                self.assertIn('cycle_detected', verdict['message'])

    def test_build_graph_raises_the_typed_code_and_names_the_cycle(self):
        for label, shape in self.SHAPES:
            with self.subTest(shape=label):
                records = [declaration(task_id, dependencies) for task_id, dependencies in shape]
                error = expected_code(self, 'cycle_detected', task_graph.build_graph, records)
                self.assertIn(' -> ', str(error))
                self.assertIsInstance(error, task_graph.GraphValidationError)

    def test_cycle_message_stays_inside_the_unresolved_nodes(self):
        records = [declaration(task_id, dependencies)
                   for task_id, dependencies in self.SHAPES[1][1]]
        error = expected_code(self, 'cycle_detected', task_graph.build_graph, records)
        reported = str(error).split('ciclo de dependencias en el grafo: ')[1].rstrip('.')
        path = reported.split(' -> ')
        self.assertEqual(path[0], path[-1])
        self.assertEqual(set(path), {'qqq', 'zzz'})
        self.assertNotIn('aaa', path)

    def test_reference_verdict_agrees_on_the_shape_family(self):
        for label, shape in self.SHAPES:
            with self.subTest(shape=label):
                records = [declaration(task_id, dependencies) for task_id, dependencies in shape]
                self.assertEqual(reference_verdict(records), 'cycle_detected')

    def test_exhaustive_three_node_space_matches_an_independent_oracle(self):
        """512 grafos (espacio completo de 3 nodos) contra un oraculo escrito aparte."""
        identifiers = ('n0', 'n1', 'n2')
        subsets = dependency_space(identifiers)
        self.assertEqual(len(subsets) ** len(identifiers), 512)
        observed_codes = set()
        for combination in itertools.product(subsets, repeat=len(identifiers)):
            records = [declaration(identifiers[index], combination[index]) for index in range(len(identifiers))]
            with self.subTest(function=dependency_label(records)):
                # Sin try/except: cualquier escape no tipado falla la prueba aqui.
                verdict = task_graph.inspect_graph(records)
                observed = 'valid' if verdict['valid'] else verdict['code']
                self.assertEqual(observed, reference_verdict(records))
                observed_codes.add(observed)
        self.assertIn('cycle_detected', observed_codes)
        self.assertIn('self_dependency', observed_codes)
        self.assertIn('valid', observed_codes)

    def test_deterministic_four_node_sample_matches_an_independent_oracle(self):
        """Muestra determinista del espacio completo de 4 nodos (65 536 funciones)."""
        identifiers = ('n0', 'n1', 'n2', 'n3')
        subsets = dependency_space(identifiers)
        self.assertEqual(len(subsets) ** len(identifiers), 65536)
        sampled = codes = 0
        for index, combination in enumerate(itertools.product(subsets, repeat=len(identifiers))):
            if index % 210:
                continue
            records = [declaration(identifiers[position], combination[position])
                       for position in range(len(identifiers))]
            with self.subTest(function=dependency_label(records)):
                verdict = task_graph.inspect_graph(records)
                observed = 'valid' if verdict['valid'] else verdict['code']
                self.assertEqual(observed, reference_verdict(records))
            sampled += 1
            codes += observed != 'valid'
        self.assertGreaterEqual(sampled, 300)
        self.assertGreater(codes, 0)


class TaskGraphDeterminismTests(unittest.TestCase):
    """Orden y hash deterministas; integridad del grafo declarado."""

    def test_equivalent_constructions_share_order_and_hash(self):
        baseline = task_graph.build_graph(fixture_graph())
        self.assertEqual(baseline.topological_order, FIXTURE_GRAPH_ORDER)
        self.assertEqual(baseline.graph_sha256, FIXTURE_GRAPH_SHA256)
        self.assertRegex(baseline.graph_sha256, r'^[0-9a-f]{64}$')
        variants = [list(reversed(fixture_graph())),
                    [declaration('t3', ('t1',)), declaration('t2', ('t1',)), declaration('t1')],
                    [dict(reversed(list(record.items()))) for record in fixture_graph()],
                    [dict(record, budget=dict(reversed(list(record['budget'].items())))) for record in fixture_graph()]]
        for records in variants:
            with self.subTest(variant=records[0]['task_id']):
                graph = task_graph.build_graph(records)
                self.assertEqual(graph.topological_order, baseline.topological_order)
                self.assertEqual(graph.graph_sha256, baseline.graph_sha256)
                self.assertEqual(graph.to_dict(), baseline.to_dict())

    def test_hash_changes_when_any_field_changes(self):
        baseline = task_graph.build_graph(fixture_graph())
        mutations = (
            ('task_id', lambda rows: rows[2].__setitem__('task_id', 't3b')),
            ('title', lambda rows: rows[2].__setitem__('title', 'Otro titulo')),
            ('intent', lambda rows: rows[2].__setitem__('intent', 'Otro resultado pretendido.')),
            ('agent_ref', lambda rows: rows[2].__setitem__('agent_ref', 'perfil-2')),
            ('agent_ref ausente', lambda rows: rows[2].pop('agent_ref')),
            ('autonomy_level', lambda rows: rows[2].__setitem__('autonomy_level', 'propose')),
            ('depends_on', lambda rows: rows[2].__setitem__('depends_on', ['t2'])),
            ('budget.tokens', lambda rows: rows[2]['budget'].__setitem__('tokens', 1001)),
            ('budget.money_usd', lambda rows: rows[2]['budget'].__setitem__('money_usd', 0.01)),
            ('budget.time_seconds', lambda rows: rows[2]['budget'].__setitem__('time_seconds', 61)),
            ('budget.requests', lambda rows: rows[2]['budget'].__setitem__('requests', 6)),
            ('criterio', lambda rows: rows[2]['acceptance_criteria'][0].__setitem__('criterion', 'Otro criterio.')),
            ('verificacion', lambda rows: rows[2]['acceptance_criteria'][0].__setitem__('verify', 'otra comprobacion')),
            ('estado del criterio', lambda rows: rows[2]['acceptance_criteria'][0].__setitem__('status', 'not_run')),
            ('falsifier_id', lambda rows: rows[2]['falsifiers'][0].__setitem__('falsifier_id', 'fr02')),
            ('falsificador', lambda rows: rows[2]['falsifiers'][0].__setitem__('statement', 'Otra refutacion.')),
            ('deteccion', lambda rows: rows[2]['falsifiers'][0].__setitem__('how_detected', 'Otra deteccion.')),
            ('idempotency_key', lambda rows: rows[2].__setitem__('idempotency_key', 'idem-t3-0002')),
            ('evidence_refs', lambda rows: rows[2].__setitem__('evidence_refs', ['otra/ruta.md'])),
            ('created_at', lambda rows: rows[2].__setitem__('created_at', '2026-10-11T00:00:00Z')),
        )
        for label, mutate in mutations:
            with self.subTest(field=label):
                records = copy.deepcopy(fixture_graph())
                mutate(records)
                changed = task_graph.build_graph(records)
                self.assertNotEqual(changed.to_dict(), baseline.to_dict())
                self.assertNotEqual(changed.graph_sha256, baseline.graph_sha256)

    def test_approval_mechanism_does_not_change_the_hash(self):
        records = [declaration('t1', autonomy_level='prepare'), declaration('t2', ('t1',))]
        granted_all = task_graph.build_graph(records, approved=True)
        granted_one = task_graph.build_graph(records, approved={'t1': True})
        self.assertEqual(granted_all.graph_sha256, granted_one.graph_sha256)

    def test_graph_rejects_a_tampered_hash_or_order(self):
        graph = task_graph.build_graph(fixture_graph())
        with self.assertRaises(task_graph.InvalidFieldError):
            task_graph.TaskGraph(tasks=graph.tasks, topological_order=graph.topological_order,
                                 graph_sha256='0' * 64)
        with self.assertRaises(task_graph.InvalidFieldError):
            task_graph.TaskGraph(tasks=graph.tasks, topological_order=('t3', 't2', 't1'),
                                 graph_sha256=graph.graph_sha256)
        self.assertEqual(task_graph.canonical_task_list(graph.tasks),
                         json.dumps([task.to_dict() for task in graph.tasks], sort_keys=True,
                                    separators=(',', ':'), ensure_ascii=False))
        self.assertEqual(task_graph.compute_graph_sha256(graph.tasks), graph.graph_sha256)

    def test_inspect_graph_reports_typed_codes_without_raising(self):
        valid = task_graph.inspect_graph(fixture_graph())
        self.assertEqual((valid['valid'], valid['code'], valid['task_count']), (True, None, 3))
        self.assertEqual(valid['topological_order'], FIXTURE_GRAPH_ORDER)
        self.assertEqual(valid['graph_sha256'], FIXTURE_GRAPH_SHA256)
        invalid = task_graph.inspect_graph([declaration('ta', ('zz',))])
        self.assertEqual((invalid['valid'], invalid['code']), (False, 'unknown_dependency'))
        self.assertIsNone(invalid['graph_sha256'])
        self.assertIsNone(invalid['task_count'])
        self.assertEqual(invalid['topological_order'], ())
        self.assertIn('unknown_dependency', invalid['message'])

    def test_duplicate_idempotency_keys_are_reported_not_rejected(self):
        records = [declaration('ta'), declaration('tb', idempotency_key='idem-ta-0001'), declaration('tc')]
        graph = task_graph.build_graph(records)
        self.assertEqual(graph.topological_order, ('ta', 'tb', 'tc'))
        self.assertEqual(task_graph.duplicate_idempotency_keys(graph.tasks), ('idem-ta-0001',))
        self.assertEqual(task_graph.inspect_graph(records)['duplicate_idempotency_keys'], ('idem-ta-0001',))
        self.assertEqual(task_graph.duplicate_idempotency_keys(task_graph.build_graph(fixture_graph()).tasks), ())

    def test_policy_reference_and_graph_timestamp_are_metadata(self):
        baseline = task_graph.build_graph(fixture_graph())
        annotated = task_graph.build_graph(fixture_graph(), policy_ref='policy-local-0001',
                                          created_at='2026-10-10T00:00:00Z')
        self.assertEqual(annotated.graph_sha256, baseline.graph_sha256)
        self.assertEqual(annotated.to_dict()['policy_ref'], 'policy-local-0001')
        expected_code(self, 'invalid_field', task_graph.build_graph, fixture_graph(), policy_ref='')
        expected_code(self, 'invalid_field', task_graph.build_graph, fixture_graph(), created_at='2026-10-10')


class AdmittedInputDomainTests(unittest.TestCase):
    """Dominio admitido y errores tipados: cierra RV1-02, RV1-03 y RV1-04 de la revision.

    El modulo declara su dominio (documento JSON sin ciclos y de profundidad acotada, con
    mapeos coherentes como los de `json.loads`) y decide la ausencia de clave con el valor
    leido por el centinela `_MISSING`, de modo que ni un mapeo inconsistente ni una
    estructura ciclica escapan como excepcion cruda.
    """

    class Liar(dict):
        """`in` miente y `[]` levanta: mismo caso que la sonda p02 de la revision RV1."""

        def __contains__(self, key):
            return True

        def __getitem__(self, key):
            raise KeyError(key)

        def __iter__(self):
            return iter(())

    class InverseLiar(dict):
        """`in` niega claves que `get` si devuelve: la decision debe salir del valor leido."""

        def __contains__(self, key):
            return False

        def __getitem__(self, key):
            raise KeyError(key)

    def test_incoherent_mapping_produces_typed_errors_never_keyerror(self):
        expected_code(self, 'missing_required_field', task_graph.build_taskspec, self.Liar())
        expected_code(self, 'missing_required_field', task_graph.build_taskspec,
                      dict(declaration('t1'), budget=self.Liar()))
        expected_code(self, 'missing_required_field', task_graph.build_taskspec,
                      dict(declaration('t1'), acceptance_criteria=[self.Liar()]))
        expected_code(self, 'missing_required_field', task_graph.build_graph, [self.Liar()])

    def test_presence_is_decided_with_the_read_value_not_with_in(self):
        inverted = task_graph.build_taskspec(self.InverseLiar(declaration('t1')))
        self.assertEqual(inverted.to_dict(), task_graph.build_taskspec(declaration('t1')).to_dict())
        graph = task_graph.build_graph([self.InverseLiar(declaration('t1'))])
        self.assertEqual(graph.graph_sha256, task_graph.build_graph([declaration('t1')]).graph_sha256)

    def test_list_helpers_accept_task_specs_and_declarations_uniformly(self):
        records = [declaration('ta'), declaration('tb')]
        records[1]['idempotency_key'] = 'idem-ta-0001'
        for record in records:
            record['acceptance_criteria'][0]['status'] = 'pending'
        specs = [task_graph.build_taskspec(record) for record in records]
        for helper in (task_graph.canonical_task_list, task_graph.compute_graph_sha256):
            with self.subTest(helper=helper.__name__):
                self.assertEqual(helper(records), helper(specs))
        self.assertEqual(task_graph.duplicate_idempotency_keys(records), ('idem-ta-0001',))
        self.assertEqual(task_graph.duplicate_idempotency_keys(specs), ('idem-ta-0001',))

    def test_canonical_helpers_dump_raw_declarations_as_is(self):
        """Documentado: las funciones canonicas aceptan declaraciones crudas sin normalizarlas."""
        spec = task_graph.build_taskspec(declaration('ta'))
        canonical_spec = task_graph.canonical_task_list([spec])
        canonical_raw = task_graph.canonical_task_list([declaration('ta')])
        self.assertIn('"status":"pending"', canonical_spec)
        self.assertNotIn('"status"', canonical_raw)
        self.assertNotEqual(canonical_raw, canonical_spec)
        self.assertEqual(task_graph.compute_graph_sha256([spec]),
                         task_graph.compute_graph_sha256([task_graph.build_taskspec(declaration('ta'))]))

    def test_list_helpers_reject_missing_keys_and_foreign_types(self):
        incomplete = [{name: value for name, value in declaration('tb').items()
                       if name != 'idempotency_key'}]
        error = expected_code(self, 'missing_required_field', task_graph.duplicate_idempotency_keys, incomplete)
        self.assertNotIsInstance(error, AttributeError)
        for foreign in (42, 'texto', None, True):
            with self.subTest(element=foreign):
                expected_code(self, 'invalid_field', task_graph.duplicate_idempotency_keys,
                              [declaration('ta'), foreign])
                expected_code(self, 'invalid_field', task_graph.canonical_task_list, [foreign])
                expected_code(self, 'invalid_field', task_graph.compute_graph_sha256, [foreign])

    def test_build_graph_rejects_records_outside_the_admitted_types(self):
        for foreign in (42, 'texto', None, [], ()):
            with self.subTest(record=foreign):
                expected_code(self, 'invalid_field', task_graph.build_graph, [foreign])
        expected_code(self, 'invalid_field', task_graph.build_graph, 'texto')
        incomplete = {name: value for name, value in declaration('ta').items() if name != 'title'}
        error = expected_code(self, 'missing_required_field', task_graph.build_graph, [incomplete])
        self.assertNotIsInstance(error, AttributeError)

    def test_deep_or_cyclic_structures_are_rejected_with_a_typed_error(self):
        deep = {'nivel': 1}
        for _ in range(task_graph.MAX_DECLARATION_DEPTH * 2):
            deep = {'nivel': deep}
        error = expected_code(self, 'invalid_field', task_graph.build_taskspec,
                              dict(declaration('t1'), extra=deep))
        self.assertIn('profundidad', str(error))
        cyclic = {}
        cyclic['self'] = cyclic
        error = expected_code(self, 'invalid_field', task_graph.build_taskspec,
                              dict(declaration('t1'), extra=cyclic))
        self.assertIn('profundidad', str(error))
        shallow = {'nivel': {'nivel': {'nivel': 1}}}
        error = expected_code(self, 'invalid_field', task_graph.build_taskspec,
                              dict(declaration('t1'), extra=shallow))
        self.assertIn('campo no declarado', str(error))

    def test_module_documents_the_admitted_input_domain(self):
        self.assertEqual(task_graph.MAX_DECLARATION_DEPTH, 32)
        self.assertGreaterEqual(task_graph.MAX_DECLARATION_DEPTH, 8)
        for token in ('Dominio de entrada admitido', 'json.loads', 'MAX_DECLARATION_DEPTH',
                      '_MISSING', 'InvalidFieldError', 'MissingFieldError'):
            with self.subTest(token=token):
                self.assertIn(token, task_graph.__doc__)
        for function in (task_graph.build_taskspec, task_graph.build_graph,
                         task_graph.canonical_task_list, task_graph.compute_graph_sha256,
                         task_graph.duplicate_idempotency_keys):
            with self.subTest(function=function.__name__):
                self.assertIn('Mapping', function.__doc__)


class InertnessTests(unittest.TestCase):
    """El modulo declara: no ejecuta, no instala, no concede y no muta estado global."""

    def test_module_imports_only_stdlib_and_engine(self):
        roots, relative = set(), set()
        for node in ast.walk(module_tree()):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative.add(node.module)
                    continue
                roots.add((node.module or '').split('.')[0])
        self.assertEqual(roots & FORBIDDEN_IMPORT_ROOTS, set())
        self.assertLessEqual(roots, ALLOWED_IMPORT_ROOTS | ENGINE_IMPORT_NAMES)
        self.assertIn('project_store', relative)

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
        for absent in ('://', 'socket', 'urllib', 'subprocess', 'http.client', 'open('):
            with self.subTest(token=absent):
                self.assertNotIn(absent, source)

    def test_module_has_no_mutable_global_state(self):
        offenders = sorted(name for name, value in vars(task_graph).items()
                           if isinstance(value, MUTABLE_CONTAINERS) and name != '__builtins__')
        self.assertEqual(offenders, [])
        for name in ('GRAPH_ERROR_CODES', 'FIELD_ERROR_CODES', 'ERROR_CODES', 'AUTONOMY_LEVELS',
                     'WRITE_CAPABLE_AUTONOMY_LEVELS', 'CRITERION_STATES', 'BUDGET_FIELDS',
                     'TASKSPEC_FIELDS', 'TASKSPEC_REQUIRED_FIELDS', 'DEFAULTED_REQUIRED_FIELDS',
                     'ERROR_CLASSES'):
            with self.subTest(constant=name):
                self.assertIsInstance(getattr(task_graph, name), tuple)
        self.assertIsInstance(task_graph.PROHIBITED_FIELD_NAMES, frozenset)

    def test_public_surface_is_declared_and_grants_nothing(self):
        own_functions = sorted(name for name, value in vars(task_graph).items()
                               if inspect.isfunction(value)
                               and getattr(value, '__module__', None) == task_graph.__name__
                               and not name.startswith('_'))
        self.assertEqual(own_functions, sorted(PUBLIC_FUNCTIONS))
        for name in own_functions:
            with self.subTest(function=name):
                self.assertIsNone(FORBIDDEN_FUNCTION_NAMES.match(name))

    def test_building_graphs_does_not_mutate_module_state(self):
        before = {name: id(value) for name, value in vars(task_graph).items()}
        snapshot = sorted((name, type(value).__name__) for name, value in vars(task_graph).items())
        task_graph.inspect_graph(fixture_graph())
        task_graph.inspect_graph([declaration('ta', ('zz',))])
        task_graph.build_graph(fixture_graph(), approved=True)
        task_graph.build_graph([declaration('tb', autonomy_level='prepare')], approved=['tb'])
        task_graph.canonical_task_list(task_graph.build_graph(fixture_graph()).tasks)
        task_graph.compute_graph_sha256(task_graph.build_graph(fixture_graph()).tasks)
        task_graph.duplicate_idempotency_keys(task_graph.build_graph(fixture_graph()).tasks)
        task_graph.forbidden_field_name('password')
        task_graph.is_write_capable_level('prepare')
        after = {name: id(value) for name, value in vars(task_graph).items()}
        self.assertEqual(before, after)
        self.assertEqual(snapshot, sorted((name, type(value).__name__) for name, value in vars(task_graph).items()))
        self.assertEqual(task_graph.build_graph(fixture_graph()).graph_sha256, FIXTURE_GRAPH_SHA256)


class CrossProcessDeterminismTests(unittest.TestCase):
    """El mismo JSON produce el mismo orden y hash en procesos distintos."""

    def test_two_processes_with_different_hash_seeds_agree(self):
        payload = json.dumps(fixture_graph(), ensure_ascii=False)
        outputs = []
        for seed in ('0', '12345'):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            try:
                completed = subprocess.run([sys.executable, '-B', '-c', CROSS_PROCESS_CODE,
                                            str(SUITE_ROOT), payload],
                                           cwd=str(SUITE_ROOT), capture_output=True, text=True,
                                           timeout=300, env=environment)
            except (OSError, subprocess.SubprocessError) as error:
                self.skipTest('No se pudo lanzar un segundo proceso Python: ' + type(error).__name__)
            if completed.returncode != 0:
                detail = ((completed.stderr or '').strip().splitlines() or ['sin detalle'])[-1]
                if 'ImportError' in (completed.stderr or ''):
                    self.skipTest('El segundo proceso no puede importar el paquete: ' + detail)
                self.fail('El proceso de comprobacion fallo: ' + detail)
            outputs.append(completed.stdout.strip())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], FIXTURE_GRAPH_SHA256 + ' ' + ','.join(FIXTURE_GRAPH_ORDER))


@unittest.skipUnless(SCHEMA_PATH.is_file(),
                     'docs/plataforma/taskspec.schema.json no esta en el arbol: no viaja en el ZIP '
                     'hasta que t9 amplie RUNTIME_ALLOWLIST (decision D-R0-2).')
class FrozenContractCrossCheckTests(unittest.TestCase):
    """El modulo y sus constantes consumen el contrato congelado sin reinterpretarlo."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text('utf-8'))
        cls.rules = cls.schema['$defs']['graph_rules']['properties']

    def test_error_vocabulary_and_rules_match_the_frozen_contract(self):
        self.assertEqual(list(task_graph.GRAPH_ERROR_CODES), self.rules['error_codes']['const'])
        self.assertEqual(task_graph.ORDER_RULE, self.rules['deterministic_order_rule']['const'])
        self.assertEqual(task_graph.HASH_RULE, self.rules['hash_rule']['const'])
        for rule in ('acyclic', 'unique_task_ids', 'dependencies_must_exist', 'self_dependency_forbidden'):
            with self.subTest(rule=rule):
                self.assertTrue(self.rules[rule]['const'])
        self.assertFalse(self.rules['executes_actions']['const'])

    def test_required_fields_and_enums_match_the_frozen_contract(self):
        properties = self.schema['properties']
        self.assertEqual(set(task_graph.TASKSPEC_REQUIRED_FIELDS), set(self.schema['required']))
        self.assertEqual(set(task_graph.TASKSPEC_FIELDS), set(properties))
        self.assertEqual(task_graph.TASKSPEC_VERSION, properties['taskspec_version']['const'])
        self.assertEqual(task_graph.GRAPH_VERSION, self.schema['$defs']['task_graph']['properties']['graph_version']['const'])
        self.assertEqual(list(task_graph.AUTONOMY_LEVELS), properties['autonomy_level']['enum'])
        self.assertEqual(task_graph.DEFAULT_AUTONOMY_LEVEL, properties['autonomy_level']['default'])
        self.assertEqual(list(task_graph.BUDGET_FIELDS), properties['budget']['required'])
        self.assertEqual(list(task_graph.CRITERION_STATES),
                         [state for state in properties['acceptance_criteria']['items']['properties']['status']['enum']])
        self.assertEqual(task_graph.DEFAULT_CRITERION_STATE,
                         properties['acceptance_criteria']['items']['properties']['status']['default'])
        self.assertEqual(properties['task_id']['pattern'].strip('^$'), task_graph.TASK_ID_PATTERN.pattern.strip('^$'))
        self.assertEqual(properties['idempotency_key']['pattern'].strip('^$'),
                         task_graph.IDEMPOTENCY_KEY_PATTERN.pattern.strip('^$'))

    def test_declaration_keys_belong_to_the_frozen_schema(self):
        spec = task_graph.build_taskspec(declaration('t1'))
        self.assertLessEqual(set(spec.to_dict()), set(self.schema['properties']))
        self.assertNotIn('autonomy_approved', spec.to_dict())
        graph = task_graph.build_graph(fixture_graph(), policy_ref='policy-local-0001',
                                       created_at='2026-10-10T00:00:00Z')
        envelope = self.schema['$defs']['task_graph']['properties']
        self.assertLessEqual(set(graph.to_dict()), set(envelope))
        self.assertEqual(envelope['graph_sha256']['pattern'], r'^[0-9a-f]{64}$')
        self.assertRegex(graph.graph_sha256, envelope['graph_sha256']['pattern'])
        self.assertEqual(list(graph.topological_order), graph.to_dict()['topological_order'])

    def test_prohibited_fields_match_the_project_store_guard(self):
        self.assertEqual(frozenset(self.schema['prohibited_fields']), frozenset(project_store.FORBIDDEN_FIELDS))
        self.assertEqual(frozenset(self.schema['prohibited_fields']), task_graph.PROHIBITED_FIELD_NAMES)
        self.assertTrue(self.schema['inert_by_default'])
        self.assertEqual(self.schema['version_field'], 'taskspec_version')


class SuiteSizeTests(unittest.TestCase):
    """Criterio del encargo: al menos 12 casos y los negativos anteriores presentes."""

    def test_module_declares_at_least_twelve_cases_and_the_required_negatives(self):
        module = sys.modules[__name__]
        case_count = unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
        self.assertGreaterEqual(case_count, 12)
        names = {name for name, value in vars(module).items()
                 if isinstance(value, type) and issubclass(value, unittest.TestCase)
                 for name in dir(value) if name.startswith('test_')}
        required = {'test_cycle_is_rejected_with_its_own_code', 'test_duplicate_task_ids_are_rejected',
                    'test_unknown_dependency_is_rejected', 'test_self_dependency_is_rejected',
                    'test_missing_required_field_raises_typed_error_never_keyerror',
                    'test_write_capable_levels_require_explicit_boolean_approval',
                    'test_credential_field_names_are_rejected_by_the_project_store_guard',
                    'test_graph_rejects_a_tampered_hash_or_order',
                    'test_inspect_graph_returns_cycle_detected_without_escaping',
                    'test_exhaustive_three_node_space_matches_an_independent_oracle',
                    'test_incoherent_mapping_produces_typed_errors_never_keyerror',
                    'test_deep_or_cyclic_structures_are_rejected_with_a_typed_error'}
        self.assertLessEqual(required, names)


if __name__ == '__main__':
    unittest.main(verbosity=2)
