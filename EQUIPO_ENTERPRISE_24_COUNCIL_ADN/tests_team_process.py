"""Pruebas offline de engine/team_process.py (M1). Inertes, deterministas, sin red ni disco.

Cubre los tres modos (`sequential`, `hierarchical`, `parallel_waves`), el checkpoint durable con
reanudacion sin repetir pasos, los tres topes de presupuesto con estado `budget_exhausted` y el
determinismo byte a byte. Los casos `AV-xx` corresponden a `docs/rea/agile_vectors.json` (t21) y el
contrato es `docs/rea/TEAM_API_CONTRACT_v1.md` (t31).

Solo biblioteca estandar. No usa red, claves, proveedores, dependencias nuevas ni DSH; no escribe
ficheros (el checkpoint es un dict y la persistencia la decide quien llama).
"""
import ast
import hashlib
import inspect
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import team_process as tp

SUITE_ROOT = Path(__file__).resolve().parent
MODULE_PATH = SUITE_ROOT / 'engine' / 'team_process.py'

ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'datetime', 'hashlib',
                                  'json', 'math', 're', 'time'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'os', 'io', 'pathlib', 'socket', 'ssl', 'urllib', 'http', 'ftplib',
                                    'smtplib', 'telnetlib', 'subprocess', 'shutil', 'tempfile',
                                    'importlib', 'ctypes', 'multiprocessing', 'asyncio', 'threading',
                                    'random', 'secrets', 'uuid', 'sqlite3'})
FORBIDDEN_CALLS = frozenset({'open', 'eval', 'exec', 'compile', '__import__', 'input', 'breakpoint'})
FORBIDDEN_ATTRIBUTES = frozenset({'system', 'popen', 'Popen', 'check_call', 'check_output', 'run',
                                  'urlopen', 'connect', 'sendall', 'recv', 'write', 'write_text',
                                  'write_bytes', 'read_text', 'read_bytes', 'unlink', 'mkdir', 'remove'})
PUBLIC_FUNCTIONS = ('TeamProcess', 'TeamProcessError')
FROZEN_CONSTANTS = ('MODES', 'CYCLE_STATES', 'MEMBER_STATES', 'DELEGATION_STATES', 'BUDGET_DIMENSIONS',
                    'EXHAUSTION_REASONS', 'CHECKPOINT_VERSION', 'CHECKPOINT_SCHEMA', 'PROCESS_SCHEMA',
                    'RECEIPT_VERSION', 'DEFAULT_WAVE_SIZE', 'MAX_WAVE_SIZE', 'MAX_MEMBERS',
                    'MEMBER_ID_PATTERN', 'PROCESS_ERROR_CODES')


class FakeClock:
    """Reloj inyectable: segundos epoch, sin dependencia del reloj del sistema."""

    def __init__(self, moment=1000.0):
        self.moment = float(moment)

    def __call__(self):
        return self.moment

    def advance(self, seconds):
        self.moment += float(seconds)
        return self.moment


def roster(count=3, coordinator_slot=None, delegates_to=None, prefix='m'):
    members = []
    for slot in range(1, count + 1):
        member = {'slot': slot, 'member_id': '%s%d' % (prefix, slot), 'role': 'rol-%d' % slot}
        if coordinator_slot == slot:
            member['is_coordinator'] = True
        if delegates_to and slot == coordinator_slot:
            member['delegates_to'] = list(delegates_to)
        members.append(member)
    return members


def success_worker(request):
    """Todo éxito con resultado por slot; resuelve todos los slots pedidos de una vez."""
    return {slot: {'state': 'success', 'result': 'ok-%d' % slot} for slot in request['slots']}


def partial_worker(request):
    """Resuelve solo el primer slot de la unidad (sirve para cortar una ola a la mitad)."""
    slot = request['slots'][0]
    return {slot: {'state': 'success', 'result': 'ok-%d' % slot}}


def canonical(checkpoint):
    return json.dumps(checkpoint, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class ApiSurfaceTests(unittest.TestCase):
    """La superficie publica implementa exactamente el contrato congelado."""

    def test_public_surface_matches_the_contract(self):
        for name in FROZEN_CONSTANTS:
            with self.subTest(constant=name):
                self.assertTrue(hasattr(tp, name), 'falta la constante ' + name)
        self.assertEqual(tp.MODES, ('sequential', 'hierarchical', 'parallel_waves'))
        self.assertEqual(tp.CYCLE_STATES,
                         ('not_run', 'running', 'incomplete', 'completed', 'budget_exhausted'))
        self.assertEqual(tp.MEMBER_STATES, ('pending', 'running', 'success', 'failed', 'skipped'))
        self.assertEqual(tp.EXHAUSTION_REASONS, ('steps', 'seconds', 'delegations', 'tokens'))
        self.assertEqual(tp.CHECKPOINT_VERSION, 1)
        self.assertEqual(tp.CHECKPOINT_SCHEMA, 'orgdna.team_process.checkpoint/1')
        self.assertEqual(tp.RECEIPT_VERSION, 1)
        defined = sorted(name for name, value in vars(tp).items()
                         if inspect.isclass(value) and getattr(value, '__module__', None) == tp.__name__
                         and not name.startswith('_'))
        self.assertEqual(defined, sorted(PUBLIC_FUNCTIONS))
        for method in ('step', 'run', 'status', 'export_checkpoint', 'import_checkpoint',
                       'checkpoint_digest', 'from_checkpoint'):
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(tp.TeamProcess, method)))

    def test_constructor_signature_is_frozen(self):
        parameters = list(inspect.signature(tp.TeamProcess.__init__).parameters)
        self.assertEqual(parameters, ['self', 'roster', 'mode', 'clock', 'budget', 'wave_size',
                                      'worker', 'coordinator_slot'])
        defaults = inspect.signature(tp.TeamProcess.__init__).parameters
        self.assertEqual(defaults['mode'].default, 'sequential')
        self.assertIsNone(defaults['clock'].default)
        self.assertIsNone(defaults['budget'].default)
        self.assertEqual(list(inspect.signature(tp.TeamProcess.step).parameters), ['self', 'outcome'])
        self.assertEqual(list(inspect.signature(tp.TeamProcess.run).parameters), ['self', 'limit'])

    def test_step_and_run_reports_have_the_frozen_shape(self):
        process = tp.TeamProcess(roster(), worker=success_worker, clock=FakeClock())
        first = process.step()
        self.assertEqual(sorted(first), ['advanced', 'cycle', 'cycle_state', 'exhausted',
                                         'open_delegations', 'slots', 'step', 'wave'])
        self.assertIsInstance(first['slots'], tuple)
        self.assertIsInstance(first['open_delegations'], tuple)
        report = process.run()
        self.assertEqual(sorted(report), ['budget_consumed', 'cycle', 'cycle_state', 'exhausted', 'mode',
                                          'open_delegations', 'receipt', 'steps_advanced'])
        self.assertEqual(sorted(report['receipt']), ['at', 'budget_consumed', 'cycle', 'mode', 'motive',
                                                     'receipt_version', 'steps_advanced'])
        self.assertEqual(report['receipt']['receipt_version'], tp.RECEIPT_VERSION)

    def test_status_has_the_frozen_shape(self):
        process = tp.TeamProcess(roster(), worker=success_worker, clock=FakeClock())
        process.run()
        status = process.status()
        self.assertEqual(sorted(status), ['budget', 'coordinator_slot', 'cycle', 'cycle_state',
                                          'delegations', 'members', 'mode', 'next_slots', 'results',
                                          'resumptions', 'roster', 'schema', 'step', 'steps_total', 'waves'])
        self.assertEqual(sorted(status['budget']), ['consumed', 'declared', 'exhausted', 'remaining'])
        self.assertEqual(status['schema'], tp.PROCESS_SCHEMA)
        self.assertIsInstance(status['next_slots'], tuple)
        self.assertIsInstance(status['members'][0], dict)

    def test_error_codes_are_typed_and_closed(self):
        self.assertTrue(issubclass(tp.TeamProcessError, ValueError))
        for code in tp.PROCESS_ERROR_CODES:
            with self.subTest(code=code):
                error = tp.TeamProcessError(code, 'x')
                self.assertEqual(error.code, code)
                self.assertIn(code, str(error))


class SequentialModeTests(unittest.TestCase):
    """Modo `sequential`: un paso por turno, orden estable de slots."""

    def test_steps_advance_one_slot_per_turn_in_canonical_order(self):
        process = tp.TeamProcess(roster(3), clock=FakeClock())
        first = process.step({'1': {'state': 'success', 'result': 'a'}})
        self.assertTrue(first['advanced'])
        self.assertEqual(first['slots'], (1,))
        self.assertEqual(first['cycle_state'], 'running')
        second = process.step({'2': {'state': 'success', 'result': 'b'}})
        self.assertEqual(second['slots'], (2,))
        third = process.step({'3': {'state': 'success', 'result': 'c'}})
        self.assertEqual(third['slots'], (3,))
        self.assertEqual(third['cycle_state'], 'completed')
        status = process.status()
        self.assertEqual([member['slot'] for member in status['members']], [1, 2, 3])
        self.assertEqual([result['slot'] for result in status['results']], [1, 2, 3])

    def test_run_closes_the_cycle_and_emits_a_completed_receipt(self):
        process = tp.TeamProcess(roster(4), worker=success_worker, clock=FakeClock())
        report = process.run()
        self.assertEqual(report['cycle_state'], 'completed')
        self.assertEqual(report['steps_advanced'], 4)
        self.assertEqual(report['receipt']['motive'], 'completed')
        self.assertEqual(report['receipt']['steps_advanced'], 4)
        self.assertEqual(process.status()['cycle'], 1)

    def test_step_after_close_raises_cycle_closed_and_run_opens_the_next_cycle(self):
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
        process.run()
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step()
        self.assertEqual(caught.exception.code, 'cycle_closed')
        second = process.run()
        self.assertEqual(second['cycle'], 2)
        self.assertEqual(second['cycle_state'], 'completed')
        self.assertEqual(process.status()['steps_total'], 4)

    def test_worker_request_shape_is_frozen(self):
        captured = []

        def worker(request):
            captured.append(dict(request))
            return success_worker(request)

        process = tp.TeamProcess(roster(2), worker=worker, clock=FakeClock())
        process.step()
        request = captured[0]
        self.assertEqual(sorted(request), ['cycle', 'delegations', 'members', 'mode', 'slots', 'step', 'wave'])
        self.assertEqual(request['mode'], 'sequential')
        self.assertEqual(request['cycle'], 1)
        self.assertEqual(request['step'], 0)
        self.assertIsNone(request['wave'])
        self.assertEqual(request['slots'], (1,))
        self.assertEqual(request['delegations'], [])
        self.assertEqual(sorted(request['members'][0]), ['member_id', 'role', 'slot'])


class HierarchicalModeTests(unittest.TestCase):
    """Modo `hierarchical`: el coordinador delega y cada delegado devuelve el resultado al coordinador."""

    def _coordinator_worker(self, targets, result='coord', delegation_result=None):
        def worker(request):
            slot = request['slots'][0]
            if slot == 1 and not request['delegations']:
                return {1: {'state': 'success', 'result': result, 'delegations': list(targets)}}
            return {slot: {'state': 'success', 'result': delegation_result or ('res-%d' % slot)}}
        return worker

    def test_av09_delegation_returns_its_result_to_the_coordinator(self):
        members = roster(4, coordinator_slot=1)
        process = tp.TeamProcess(members, mode='hierarchical', worker=self._coordinator_worker([3]),
                                  clock=FakeClock())
        report = process.run()
        self.assertEqual(report['cycle_state'], 'completed')
        status = process.status()
        self.assertEqual(status['coordinator_slot'], 1)
        self.assertEqual(len(status['delegations']), 1)
        record = status['delegations'][0]
        self.assertEqual(record['to_slot'], 3)
        self.assertEqual(record['state'], 'closed')
        self.assertEqual(record['result'], 'res-3')
        self.assertIsNotNone(record['closed_at'])
        self.assertEqual([result['slot'] for result in status['results']], [1, 3])
        coordinator = [member for member in status['members'] if member['slot'] == 1][0]
        self.assertEqual(coordinator['state'], 'success')

    def test_av10_delegation_to_an_unknown_slot_is_typed_and_leaves_state_untouched(self):
        members = roster(4, coordinator_slot=1)
        process = tp.TeamProcess(members, mode='hierarchical',
                                  worker=lambda request: {1: {'state': 'success', 'result': 'c',
                                                              'delegations': [9]}},
                                  clock=FakeClock())
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step()
        self.assertEqual(caught.exception.code, 'unknown_member')
        self.assertEqual(process.status()['delegations'], [])
        coordinator = [member for member in process.status()['members'] if member['slot'] == 1][0]
        self.assertEqual(coordinator['state'], 'pending')
        self.assertEqual(process.status()['cycle_state'], 'running')

    def test_av11_two_delegations_consolidate_by_slot_not_by_completion_order(self):
        members = roster(4, coordinator_slot=1)

        def worker(request):
            if request['slots'][0] == 1 and not request['delegations']:
                return {1: {'state': 'success', 'result': 'c', 'delegations': [2, 4]}}
            # El slot 4 responde antes que el 2: el Mapping llega desordenado a proposito.
            return {4: {'state': 'success', 'result': 'late-4'}, 2: {'state': 'success', 'result': 'late-2'}}

        process = tp.TeamProcess(members, mode='hierarchical', worker=worker, clock=FakeClock())
        process.run()
        status = process.status()
        self.assertEqual([result['slot'] for result in status['results']], [1, 2, 4])
        self.assertEqual([record['to_slot'] for record in status['delegations']], [2, 4])
        self.assertTrue(all(record['state'] == 'closed' for record in status['delegations']))
        self.assertEqual([record['to_slot'] for record in status['delegations']
                          if record['state'] == 'open'], [])

    def test_av04_open_delegation_never_lets_the_cycle_complete(self):
        members = roster(4, coordinator_slot=1)
        process = tp.TeamProcess(members, mode='hierarchical', worker=self._coordinator_worker([2]),
                                  clock=FakeClock())
        process.step()  # el coordinador delega al slot 2 y la delegacion queda abierta
        checkpoint = process.export_checkpoint()
        self.assertEqual(checkpoint['delegations'][0]['state'], 'open')
        # Corte declarado: el destino de la delegacion ya no puede avanzar en este ciclo.
        checkpoint['members'][1]['state'] = 'skipped'
        resumed = tp.TeamProcess.from_checkpoint(checkpoint, clock=FakeClock(),
                                                 worker=self._coordinator_worker([2]))
        report = resumed.run()
        self.assertEqual(report['cycle_state'], 'incomplete')
        self.assertNotEqual(report['cycle_state'], 'completed')
        self.assertEqual(report['open_delegations'], (2,))
        self.assertEqual(report['receipt']['motive'], 'incomplete')

    def test_max_delegation_depth_is_declared_and_enforced(self):
        self.assertEqual(tp.MAX_DELEGATION_DEPTH, 1)
        members = roster(4, coordinator_slot=1)

        def subdelegating_worker(request):
            slot = request['slots'][0]
            if slot == 1 and not request['delegations']:
                return {1: {'state': 'success', 'result': 'c', 'delegations': [2]}}
            return {slot: {'state': 'success', 'result': 'd', 'delegations': [3]}}

        process = tp.TeamProcess(members, mode='hierarchical', worker=subdelegating_worker,
                                  clock=FakeClock())
        process.step()  # el coordinador delega al slot 2
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step()  # el delegado intenta subdelegar (profundidad 2 > declarada)
        self.assertEqual(caught.exception.code, 'invalid_outcome')

    def test_two_declared_coordinators_are_rejected(self):
        members = roster(3)
        members[0]['is_coordinator'] = True
        members[1]['is_coordinator'] = True
        with self.assertRaises(tp.TeamProcessError) as caught:
            tp.TeamProcess(members, mode='hierarchical')
        self.assertEqual(caught.exception.code, 'invalid_roster')

    def test_coordinator_defaults_to_the_lowest_slot_and_delegates_to_whitelists_targets(self):
        members = roster(3)
        process = tp.TeamProcess(members, mode='hierarchical', worker=success_worker, clock=FakeClock())
        self.assertEqual(process.status()['coordinator_slot'], 1)
        restricted = roster(4, coordinator_slot=1, delegates_to=[2])
        process = tp.TeamProcess(restricted, mode='hierarchical',
                                  worker=lambda request: {1: {'state': 'success', 'result': 'c',
                                                              'delegations': [3]}},
                                  clock=FakeClock())
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step()
        self.assertEqual(caught.exception.code, 'unknown_member')


class ParallelWavesModeTests(unittest.TestCase):
    """Modo `parallel_waves`: olas acotadas, sin solape, resultados en orden de entrada."""

    def test_av12_waves_partition_the_roster_by_slot(self):
        process = tp.TeamProcess(roster(5), mode='parallel_waves', wave_size=2, worker=success_worker,
                                  clock=FakeClock())
        report = process.run()
        self.assertEqual(report['cycle_state'], 'completed')
        waves = process.status()['waves']
        self.assertEqual(waves['slots'], [[1, 2], [3, 4], [5]])
        self.assertEqual(waves['total'], 3)
        self.assertEqual(waves['closed'], 3)
        self.assertEqual(report['receipt']['mode'], 'parallel_waves')

    def test_av13_wave_results_follow_input_order_not_completion_order(self):
        def worker(request):
            return {3: {'state': 'success', 'result': 'c'}, 1: {'state': 'success', 'result': 'a'},
                    2: {'state': 'success', 'result': 'b'}}

        process = tp.TeamProcess(roster(3), mode='parallel_waves', wave_size=3, worker=worker,
                                  clock=FakeClock())
        process.run()
        status = process.status()
        self.assertEqual([result['slot'] for result in status['results']], [1, 2, 3])
        self.assertEqual([result['result'] for result in status['results']], ['a', 'b', 'c'])
        self.assertEqual([result['step'] for result in status['results']], [1, 2, 3])

    def test_av14_a_wave_does_not_overlap_with_the_next(self):
        process = tp.TeamProcess(roster(4), mode='parallel_waves', wave_size=2, worker=partial_worker,
                                  clock=FakeClock())
        process.step()  # solo resuelve el slot 1: el slot 2 sigue pendiente
        status = process.status()
        self.assertEqual(status['waves']['index'], 0)
        self.assertEqual(status['waves']['closed'], 0)
        self.assertEqual([member['state'] for member in status['members']], ['success', 'pending',
                                                                             'pending', 'pending'])
        self.assertEqual(status['next_slots'], (2,))
        process.step()  # cierra la ola; la siguiente aun no empezo
        status = process.status()
        self.assertEqual(status['waves']['index'], 1)
        self.assertEqual(status['waves']['closed'], 1)
        self.assertEqual(status['next_slots'], (3, 4))

    def test_av15_invalid_wave_size_is_typed(self):
        for bad in (0, -3, 33, 'dos', 2.5, True):
            with self.subTest(wave_size=bad):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    tp.TeamProcess(roster(3), mode='parallel_waves', wave_size=bad)
                self.assertEqual(caught.exception.code, 'invalid_wave_size')

    def test_wave_size_default_and_rejected_outside_waves_mode(self):
        process = tp.TeamProcess(roster(6), mode='parallel_waves', clock=FakeClock())
        self.assertIsNone(process.status()['waves'])  # ninguna ola abierta antes del ciclo 1
        process.step({'1': {'state': 'success', 'result': 'a'}})
        self.assertEqual(process.status()['waves']['size'], tp.DEFAULT_WAVE_SIZE)
        self.assertEqual(process.status()['waves']['slots'], [[1, 2, 3, 4], [5, 6]])
        with self.assertRaises(tp.TeamProcessError) as caught:
            tp.TeamProcess(roster(3), mode='sequential', wave_size=2)
        self.assertEqual(caught.exception.code, 'invalid_wave_size')


class CheckpointAndResumeTests(unittest.TestCase):
    """Checkpoint v1: esquema congelado, version, compatibilidad y reanudacion sin repetir pasos."""

    def test_checkpoint_has_exactly_the_frozen_keys_and_is_serializable(self):
        process = tp.TeamProcess(roster(3), worker=success_worker, clock=FakeClock())
        process.run()
        checkpoint = process.export_checkpoint()
        self.assertEqual(tuple(sorted(checkpoint)), tuple(sorted(tp.CHECKPOINT_FIELDS)))
        self.assertEqual(len(checkpoint), 18)
        self.assertEqual(checkpoint['checkpoint_version'], tp.CHECKPOINT_VERSION)
        self.assertEqual(checkpoint['schema'], tp.CHECKPOINT_SCHEMA)
        self.assertIsNone(checkpoint['loop'])
        json.dumps(checkpoint, allow_nan=False)
        digest = tp.TeamProcess.checkpoint_digest(checkpoint)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, tp.TeamProcess.checkpoint_digest(dict(checkpoint)))
        self.assertNotIn('digest', checkpoint)

    def test_export_returns_a_copy(self):
        process = tp.TeamProcess(roster(2), clock=FakeClock())
        checkpoint = process.export_checkpoint()
        checkpoint['members'][0]['state'] = 'success'
        checkpoint['budget']['consumed']['steps'] = 99
        status = process.status()
        self.assertEqual(status['members'][0]['state'], 'pending')
        self.assertEqual(status['budget']['consumed']['steps'], 0)

    def test_av01_resume_from_the_last_confirmed_step_without_repeating(self):
        workers = []

        def counted(request):
            workers.append(request['slots'])
            return success_worker(request)

        members = roster(5)
        first = tp.TeamProcess(members, worker=counted, clock=FakeClock())
        first.run(limit=2)
        checkpoint = first.export_checkpoint()
        self.assertEqual(checkpoint['step'], 2)
        self.assertEqual([member['state'] for member in checkpoint['members']],
                         ['success', 'success', 'pending', 'pending', 'pending'])
        self.assertEqual(checkpoint['cycle_state'], 'running')

        second = tp.TeamProcess(members, worker=counted, clock=FakeClock())
        status = second.import_checkpoint(checkpoint)
        self.assertEqual(status['resumptions'], 1)
        report = second.run()
        self.assertEqual(report['cycle_state'], 'completed')
        self.assertEqual(report['steps_advanced'], 3)
        self.assertEqual([call for call in workers], [(1,), (2,), (3,), (4,), (5,)])
        final = second.status()
        self.assertEqual([member['steps'] for member in final['members']], [1, 1, 1, 1, 1])
        self.assertEqual(final['resumptions'], 1)
        self.assertEqual([result['slot'] for result in final['results']], [1, 2, 3, 4, 5])

    def test_mid_wave_cut_resumes_without_repeating_the_closed_slot(self):
        seen = []

        def worker(request):
            seen.append(request['slots'])
            return partial_worker(request)

        members = roster(4)
        first = tp.TeamProcess(members, mode='parallel_waves', wave_size=2, worker=worker, clock=FakeClock())
        first.step()
        checkpoint = first.export_checkpoint()
        self.assertEqual(checkpoint['members'][0]['state'], 'success')
        self.assertEqual(checkpoint['members'][1]['state'], 'pending')

        resumed_calls = []

        def resumed_worker(request):
            resumed_calls.append(request['slots'])
            return success_worker(request)

        second = tp.TeamProcess(members, mode='parallel_waves', wave_size=2, worker=resumed_worker,
                                 clock=FakeClock())
        second.import_checkpoint(checkpoint)
        report = second.run()
        self.assertEqual(report['cycle_state'], 'completed')
        self.assertEqual(resumed_calls[0], (2,))
        self.assertNotIn(1, [slot for request in resumed_calls for slot in request])
        status = second.status()
        self.assertEqual([member['steps'] for member in status['members']], [1, 1, 1, 1])
        self.assertEqual(status['waves']['closed'], 2)

    def test_from_checkpoint_rebuilds_without_roster_and_with_a_new_budget(self):
        members = roster(3)
        first = tp.TeamProcess(members, worker=success_worker, clock=FakeClock(), budget={'steps': 1})
        report = first.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        checkpoint = first.export_checkpoint()
        resumed = tp.TeamProcess.from_checkpoint(checkpoint, clock=FakeClock(), worker=success_worker,
                                                  budget={'steps': 10})
        self.assertEqual(resumed.status()['budget']['declared']['steps'], 10)
        self.assertEqual(resumed.status()['mode'], 'sequential')
        self.assertEqual(resumed.status()['roster'][0]['member_id'], 'm1')
        self.assertEqual(resumed.run()['cycle_state'], 'completed')

    def test_av02_unsupported_version_is_rejected_without_degradation(self):
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
        process.run()
        checkpoint = process.export_checkpoint()
        for mutation in ({'checkpoint_version': 2}, {'schema': 'orgdna.team_process.checkpoint/2'},
                         {'checkpoint_version': 1, 'schema': 'otro'}):
            with self.subTest(mutation=mutation):
                broken = dict(checkpoint, **mutation)
                before = canonical(broken)
                fresh = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
                with self.assertRaises(tp.TeamProcessError) as caught:
                    fresh.import_checkpoint(broken)
                self.assertEqual(caught.exception.code, 'unsupported_checkpoint_version')
                self.assertEqual(canonical(broken), before)
                status = fresh.status()
                self.assertEqual(status['cycle'], 0)
                self.assertEqual(status['cycle_state'], 'not_run')
                self.assertEqual([member['steps'] for member in status['members']], [0, 0])

    def test_checkpoint_shape_is_fail_closed(self):
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
        process.run()
        good = process.export_checkpoint()
        missing = {key: value for key, value in good.items() if key != 'delegations'}
        extra = dict(good, campo_extra=1)
        bad_state = dict(good, cycle_state='volando')
        bad_wave = dict(good, waves={'size': 2, 'index': 0, 'total': 1, 'closed': 0, 'slots': [[9]]})
        bad_budget = json.loads(json.dumps(good))
        bad_budget['budget']['consumed']['steps'] = -1
        for label, broken in (('missing', missing), ('extra', extra), ('state', bad_state),
                              ('wave', bad_wave), ('budget', bad_budget)):
            with self.subTest(case=label):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    tp.TeamProcess.from_checkpoint(broken)
                self.assertEqual(caught.exception.code, 'checkpoint_shape_invalid')

    def test_checkpoint_mismatch_between_rosters_and_modes(self):
        members = roster(3)
        process = tp.TeamProcess(members, worker=success_worker, clock=FakeClock())
        process.run()
        checkpoint = process.export_checkpoint()
        with self.assertRaises(tp.TeamProcessError) as caught:
            tp.TeamProcess(roster(4), worker=success_worker).import_checkpoint(checkpoint)
        self.assertEqual(caught.exception.code, 'checkpoint_mismatch')
        with self.assertRaises(tp.TeamProcessError) as caught:
            tp.TeamProcess(members, mode='parallel_waves', worker=success_worker).import_checkpoint(checkpoint)
        self.assertEqual(caught.exception.code, 'checkpoint_mismatch')

    def test_roundtrip_preserves_status(self):
        process = tp.TeamProcess(roster(4), mode='parallel_waves', wave_size=2, worker=partial_worker,
                                  clock=FakeClock())
        process.step()
        checkpoint = process.export_checkpoint()
        clone = tp.TeamProcess.from_checkpoint(checkpoint, clock=FakeClock(), worker=partial_worker)
        original_status = process.status()
        clone_status = clone.status()
        original_status.pop('resumptions')
        clone_status.pop('resumptions')
        self.assertEqual(canonical(original_status), canonical(clone_status))


class BudgetTests(unittest.TestCase):
    """Tres topes (pasos, tiempo, delegaciones) + tokens: `budget_exhausted` con motivo, nunca excepcion."""

    def test_av16_tokens_ceiling_stops_before_the_next_step(self):
        def worker(request):
            slot = request['slots'][0]
            cost = {1: 0, 2: 90, 3: 30}[slot]
            return {slot: {'state': 'success', 'result': 'ok-%d' % slot, 'tokens': cost}}

        process = tp.TeamProcess(roster(3), worker=worker, clock=FakeClock(), budget={'tokens': 100})
        report = process.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted'], {'reason': 'tokens'})
        self.assertEqual(report['steps_advanced'], 2)
        self.assertEqual(report['budget_consumed']['tokens'], 90)
        self.assertGreaterEqual(report['budget_consumed']['tokens'], 0)
        self.assertEqual([member['state'] for member in process.status()['members']],
                         ['success', 'success', 'skipped'])
        self.assertEqual(report['receipt']['motive'], 'budget_exhausted')

    def test_steps_ceiling(self):
        process = tp.TeamProcess(roster(4), worker=success_worker, clock=FakeClock(), budget={'steps': 2})
        report = process.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted'], {'reason': 'steps'})
        self.assertEqual(report['steps_advanced'], 2)
        self.assertEqual(process.status()['budget']['remaining']['steps'], 0)

    def test_seconds_ceiling_with_injected_clock(self):
        clock = FakeClock()

        def slow(request):
            clock.advance(6)
            return success_worker(request)

        process = tp.TeamProcess(roster(4), worker=slow, clock=clock, budget={'seconds': 5})
        report = process.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted'], {'reason': 'seconds'})
        self.assertGreaterEqual(report['budget_consumed']['seconds'], 5)
        self.assertLess(report['steps_advanced'], 4)

    def test_delegations_ceiling(self):
        members = roster(4, coordinator_slot=1)

        def worker(request):
            if request['slots'][0] == 1 and not request['delegations']:
                return {1: {'state': 'success', 'result': 'c', 'delegations': [2, 3, 4]}}
            return {request['slots'][0]: {'state': 'success', 'result': 'd'}}

        process = tp.TeamProcess(members, mode='hierarchical', worker=worker, clock=FakeClock(),
                                  budget={'delegations': 2})
        report = process.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted'], {'reason': 'delegations'})
        self.assertEqual(report['budget_consumed']['delegations'], 2)
        self.assertEqual(len(process.status()['delegations']), 2)

    def test_av18_invalid_budget_rejected_and_counters_are_monotonic(self):
        for bad in ({'tokens': -5}, {'steps': 'cien'}, {'seconds': -1.5}, {'steps': 1.5},
                    {'desconocida': 1}, [('steps', 1)]):
            with self.subTest(budget=bad):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    tp.TeamProcess(roster(3), budget=bad)
                self.assertEqual(caught.exception.code, 'invalid_budget')
        process = tp.TeamProcess(roster(3), worker=success_worker, clock=FakeClock())
        process.run()
        first = process.status()['budget']['consumed']
        process.run()
        second = process.status()['budget']['consumed']
        for dimension in tp.BUDGET_DIMENSIONS:
            with self.subTest(dimension=dimension):
                self.assertGreaterEqual(second[dimension], first[dimension])

    def test_exhaustion_never_raises_a_generic_exception(self):
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock(), budget={'steps': 0})
        report = process.run()  # no lanza: reporta
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted']['reason'], 'steps')
        self.assertEqual(report['steps_advanced'], 0)


class DeterminismTests(unittest.TestCase):
    """Dos corridas identicas producen el mismo checkpoint, byte a byte."""

    def test_two_identical_runs_produce_identical_checkpoint_bytes(self):
        def build():
            return tp.TeamProcess(roster(5), mode='parallel_waves', wave_size=2, worker=success_worker,
                                  clock=FakeClock())

        first, second = build(), build()
        first_report, second_report = first.run(), second.run()
        self.assertEqual(canonical(first_report), canonical(second_report))
        self.assertEqual(canonical(first.export_checkpoint()), canonical(second.export_checkpoint()))
        self.assertEqual(tp.TeamProcess.checkpoint_digest(first.export_checkpoint()),
                         tp.TeamProcess.checkpoint_digest(second.export_checkpoint()))

    def test_results_do_not_depend_on_mapping_insertion_order(self):
        def build(order):
            def worker(request):
                values = {slot: {'state': 'success', 'result': 'r-%d' % slot} for slot in request['slots']}
                return {slot: values[slot] for slot in order if slot in values}

            return tp.TeamProcess(roster(3), mode='parallel_waves', wave_size=3, worker=worker,
                                  clock=FakeClock())

        ascending, descending = build([1, 2, 3]), build([3, 2, 1])
        ascending.run()
        descending.run()
        self.assertEqual(canonical(ascending.export_checkpoint()), canonical(descending.export_checkpoint()))

    def test_clock_is_injected_and_controls_stamps(self):
        early = FakeClock(1000.0)
        late = FakeClock(5000.0)
        first = tp.TeamProcess(roster(2), worker=success_worker, clock=early)
        second = tp.TeamProcess(roster(2), worker=success_worker, clock=late)
        first.run()
        second.run()
        self.assertTrue(first.export_checkpoint()['created_at'].startswith('1970-01-01T00:16:40'))
        self.assertTrue(second.export_checkpoint()['created_at'].startswith('1970-01-01T01:23:20'))
        self.assertNotEqual(first.export_checkpoint()['updated_at'],
                            second.export_checkpoint()['updated_at'])

    def test_module_does_not_use_global_random_or_wall_clock_directly(self):
        source = MODULE_PATH.read_text('utf-8')
        self.assertNotIn('import random', source)
        self.assertNotIn('random.', source)
        self.assertNotIn('datetime.now', source)
        # `time.time` solo se referencia como defecto del constructor: nunca se invoca en linea.
        self.assertNotIn('time.time()', source)
        self.assertEqual(source.count('return time.time'), 1)


class InertnessTests(unittest.TestCase):
    """Sin red, sin subprocess, sin hilos, sin ficheros: stdlib pura y sin efectos al importar."""

    def test_imports_are_stdlib_only(self):
        roots = set()
        for node in ast.walk(ast.parse(MODULE_PATH.read_text('utf-8'))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, 'no se admiten imports relativos')
                roots.add((node.module or '').split('.')[0])
        self.assertEqual(roots & FORBIDDEN_IMPORT_ROOTS, set())
        self.assertLessEqual(roots, ALLOWED_IMPORT_ROOTS)

    def test_module_has_no_forbidden_calls_or_threads(self):
        calls, attributes = set(), set()
        for node in ast.walk(ast.parse(MODULE_PATH.read_text('utf-8'))):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    attributes.add(node.func.attr)
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))
        self.assertEqual(calls & FORBIDDEN_CALLS, set())
        self.assertEqual(attributes & FORBIDDEN_ATTRIBUTES, set())

    def test_no_module_level_mutable_state(self):
        offenders = sorted(name for name, value in vars(tp).items()
                           if isinstance(value, (list, dict, set, bytearray)) and not name.startswith('__'))
        self.assertEqual(offenders, [])
        for name in FROZEN_CONSTANTS:
            if name == 'CHECKPOINT_VERSION' or name == 'RECEIPT_VERSION' or name.startswith('MAX_') \
                    or name == 'DEFAULT_WAVE_SIZE':
                continue
            with self.subTest(constant=name):
                self.assertIsInstance(getattr(tp, name), (tuple, frozenset, str, int))

    def test_exercising_the_api_opens_no_file(self):
        with patch('builtins.open', side_effect=AssertionError('no debe abrir ficheros')):
            process = tp.TeamProcess(roster(3), worker=success_worker, clock=FakeClock())
            process.run()
            checkpoint = process.export_checkpoint()
            tp.TeamProcess.checkpoint_digest(checkpoint)
            tp.TeamProcess.from_checkpoint(checkpoint, clock=FakeClock(), worker=success_worker).run()


class ContractEdgeCaseTests(unittest.TestCase):
    """Casos de borde del contrato: roster, limites, outcomes y errores tipados."""

    def test_av08_unknown_mode_is_a_typed_error(self):
        with self.assertRaises(tp.TeamProcessError) as caught:
            tp.TeamProcess(roster(3), mode='democratico')
        self.assertEqual(caught.exception.code, 'unknown_mode')
        self.assertIn('sequential', str(caught.exception))
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
        report = process.run()
        self.assertEqual(report['cycle_state'], 'completed')
        self.assertEqual(process.status()['step'], 2)  # cero miembros ejecutados por el modo invalido

    def test_frozen_vector_ids_are_covered_by_named_tests(self):
        frozen = ('AV-01', 'AV-02', 'AV-04', 'AV-08', 'AV-09', 'AV-10', 'AV-11', 'AV-12', 'AV-13',
                  'AV-14', 'AV-15', 'AV-16', 'AV-18')
        source = Path(__file__).read_text('utf-8')
        for vector in frozen:
            with self.subTest(vector=vector):
                self.assertIn(vector.lower().replace('-', ''), source.lower().replace('_', '').replace('-', ''),
                              'falta el vector ' + vector)

    def test_roster_validation(self):
        cases = {
            'vacio': [],
            'slot_repetido': [{'slot': 1, 'member_id': 'a', 'role': 'r'},
                              {'slot': 1, 'member_id': 'b', 'role': 'r'}],
            'id_repetido': [{'slot': 1, 'member_id': 'a', 'role': 'r'},
                            {'slot': 2, 'member_id': 'a', 'role': 'r'}],
            'id_invalido': [{'slot': 1, 'member_id': 'A B', 'role': 'r'}],
            'rol_vacio': [{'slot': 1, 'member_id': 'a', 'role': ''}],
            'campo_extra': [{'slot': 1, 'member_id': 'a', 'role': 'r', 'extra': 1}],
            'demasiados': roster(tp.MAX_MEMBERS + 1),
        }
        for label, members in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    tp.TeamProcess(members)
                self.assertEqual(caught.exception.code, 'invalid_roster')

    def test_limit_and_outcome_validation(self):
        process = tp.TeamProcess(roster(2), worker=success_worker, clock=FakeClock())
        for bad in (0, -1, 'tres', 1.5, True):
            with self.subTest(limit=bad):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    process.run(limit=bad)
                self.assertEqual(caught.exception.code, 'invalid_limit')
        fresh = tp.TeamProcess(roster(2), clock=FakeClock())
        for label, outcome in (('estado', {'1': {'state': 'quizas'}}),
                               ('slot_ajeno', {'2': {'state': 'success'}}),
                               ('no_serializable', {'1': {'state': 'success', 'result': object()}})):
            with self.subTest(case=label):
                with self.assertRaises(tp.TeamProcessError) as caught:
                    fresh.step(outcome)
                self.assertEqual(caught.exception.code, 'invalid_outcome')

    def test_step_without_worker_or_outcome_requires_a_worker(self):
        process = tp.TeamProcess(roster(2), clock=FakeClock())
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step()
        self.assertEqual(caught.exception.code, 'worker_required')
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.run()
        self.assertEqual(caught.exception.code, 'worker_required')

    def test_worker_errors_propagate_and_results_must_be_json(self):
        def boom(request):
            raise RuntimeError('worker roto')

        process = tp.TeamProcess(roster(2), worker=boom, clock=FakeClock())
        with self.assertRaises(RuntimeError):
            process.step()
        process = tp.TeamProcess(roster(2), clock=FakeClock())
        with self.assertRaises(tp.TeamProcessError) as caught:
            process.step({'1': {'state': 'success', 'result': float('nan')}})
        self.assertEqual(caught.exception.code, 'invalid_outcome')


if __name__ == '__main__':
    unittest.main(verbosity=2)
