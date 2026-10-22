"""Pruebas offline de engine/team_loop.py (M2). Inertes, deterministas, sin red.

Cubre el contrato CONGELADO `docs/rea/TEAM_API_CONTRACT_v1.md` (t31): §3 (TeamLoop),
§3.3 (recibo), §3.4 (`store`), §3.5 (`lease`), §4 (checkpoint v1 y bloque `loop`), §7.3
(presupuesto por ciclo) y §8 (reanudacion). Los casos `AV-xx` son los de
`docs/rea/agile_vectors.json` (t21) para el segmento `team_loop`: AV-03, AV-05, AV-06, AV-07,
AV-17, AV-20, AV-21, AV-23 y AV-24.

Falsificadores que esta suite hace fallar de forma explicita:
  * un ciclo completo y observable (proceso + compromisos + arriendo + recibo);
  * continuidad SIN demonio por defecto (`run(cycles=N)`), `start()`/`stop()` opt-in,
    idempotentes y compatibles con un hilo daemon del LLAMADOR;
  * barrera de exclusividad: otro supervisor con el arriendo vigente => no avanza nada;
  * cortes controlados: presupuesto por ciclo, backoff determinista y parada limpia;
  * reanudacion sin repetir pasos, cortando en el ciclo 3 de 8;
  * cero red, cero hilos en el modulo, cero subprocesos, cero aperturas de fichero.

Solo biblioteca estandar. El modulo bajo prueba no abre ficheros ni lanza hilos: el hilo
daemon y el directorio temporal los aporta ESTA prueba (lado llamador).

Run: cd EQUIPO_ENTERPRISE_24_COUNCIL_ADN && python -m unittest tests_team_loop -v
"""
import ast
import copy
import inspect
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from engine import coordination as co
from engine import followups as fu
from engine import team_channel as tc
from engine import team_loop as tl
from engine import team_process as tp

SUITE_ROOT = Path(__file__).resolve().parent
MODULE_PATH = SUITE_ROOT / 'engine' / 'team_loop.py'

#: Raices de importacion permitidas: biblioteca estandar sin efectos + modulos LOCALES del
#: repositorio que el contrato autoriza (§3.1, §3.4, §3.5).
ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'copy', 'hashlib', 'json', 'math', 'datetime',
                                  'time', 'team_process', 'coordination'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'socket', 'ssl', 'urllib', 'http', 'ftplib', 'smtplib',
                                    'telnetlib', 'subprocess', 'shutil', 'tempfile', 'importlib',
                                    'ctypes', 'multiprocessing', 'asyncio', 'threading', 'random',
                                    'secrets', 'uuid', 'sqlite3', 'os', 'io', 'pathlib'})
FORBIDDEN_CALLS = frozenset({'open', 'eval', 'exec', 'compile', '__import__', 'input',
                             'breakpoint'})
FROZEN_CONSTANTS = {
    'LOOP_SCHEMA': 'orgdna.team_loop/1',
    'LOOP_TOPIC': 'team_loop',
    'CHECKPOINT_KEY': 'orgdna.team_process.checkpoint',
    'CHECKPOINT_VERSION': 1,
    'RECEIPT_VERSION': 1,
    'MAX_CHECKPOINT_RECEIPTS': 256,
}
FROZEN_TUPLES = {
    'LOOP_STATES': ('not_run', 'running', 'stopped'),
    'STOP_REASONS': ('stop_requested', 'stopped_before_start', 'time_exhausted',
                     'budget_exhausted', 'lease_held', 'cycles_completed'),
    'RECEIPT_MOTIVES': ('completed', 'incomplete', 'budget_exhausted', 'time_exhausted',
                        'stop_requested', 'checkpoint_write_failed'),
    'LEASE_EVENTS': ('acquired', 'renewed', 'released', 'lease_held', 'lease_expired'),
    'LOOP_ERROR_CODES': ('invalid_process', 'invalid_channel', 'invalid_store', 'invalid_lease',
                         'invalid_clock', 'invalid_cycles', 'invalid_budget', 'invalid_worker'),
}
RECEIPT_FIELDS = ('receipt_version', 'cycle', 'mode', 'steps_advanced', 'budget_consumed',
                  'motive', 'at', 'checkpoint_digest', 'stop_reason')
STATUS_FIELDS = ('schema', 'state', 'cycles', 'receipt_count', 'write_failures', 'stop_reason',
                 'checkpoint_written', 'checkpoint_digest', 'lease', 'budget', 'process')
LOOP_BLOCK_FIELDS = ('cycles', 'stop_reason', 'receipts', 'receipts_omitted', 'write_failures',
                     'lease')

#: Roster de canal para la composicion con `engine/followups.py` (mismo estilo que
#: `tests_followups.py`): 'id-ceo' publica los recibos, 'id-fu' es el motor, 'id-ana' se
#: compromete.
CHANNEL_ROSTER = [
    {'member_id': 'id-ceo', 'name': 'ceo', 'role': 'CEO', 'reports_to': None},
    {'member_id': 'id-ana', 'name': 'ana', 'role': 'Investigacion', 'reports_to': 'id-ceo'},
    {'member_id': 'id-bob', 'name': 'bob', 'role': 'Revision', 'reports_to': 'id-ceo'},
    {'member_id': 'id-fu', 'name': 'fu', 'role': 'Followups', 'reports_to': 'id-ceo'},
]


class FakeClock:
    """Reloj inyectable: segundos epoch float, sin depender del reloj del sistema (D3)."""

    def __init__(self, moment=1000.0):
        self.moment = float(moment)

    def __call__(self):
        return self.moment

    def advance(self, seconds):
        self.moment += float(seconds)
        return self.moment


def roster(count=2):
    return [{'slot': slot, 'member_id': 'm%d' % slot, 'role': 'rol-%d' % slot}
            for slot in range(1, count + 1)]


class Calls:
    """Contador externo de invocaciones: evidencia de que un paso no se reejecuta (§8.3)."""

    def __init__(self):
        self.by_slot = {}
        self.total = 0

    def record(self, slot):
        self.by_slot[slot] = self.by_slot.get(slot, 0) + 1
        self.total += 1
        return self.by_slot[slot]


def make_worker(clock, calls=None, seconds=1.0, tokens=0, state='success'):
    """Worker deterministico: avanza el reloj y contabiliza cada invocacion por slot."""
    def worker(request):
        if seconds:
            clock.advance(seconds)
        for slot in request['slots']:
            if calls is not None:
                calls.record(slot)
        return {slot: {'state': state, 'result': 'ok-%d' % slot, 'tokens': tokens}
                for slot in request['slots']}
    return worker


def make_process(clock, count=2, calls=None, worker=None, **kwargs):
    return tp.TeamProcess(roster(count), clock=clock,
                          worker=worker if worker is not None else make_worker(clock, calls),
                          **kwargs)


class RecorderChannel:
    """Canal minimo con el protocolo de §3.1: `publish(sender, to=, text=, topic=)`."""

    def __init__(self):
        self.calls = []

    def publish(self, sender, to='all', text='', topic='general'):
        row = {'sender': sender, 'to': to, 'text': text, 'topic': topic}
        self.calls.append(row)
        return {'message': dict(row, id='msg-%d' % len(self.calls)), 'task': None}


class ProtocolStore:
    """Sink de checkpoint con el protocolo §3.4 (`load`/`save`), con fallos inyectables."""

    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self.saves = 0
        self.failures = set()

    def load(self, key):
        return copy.deepcopy(self.data.get(key))

    def save(self, key, checkpoint):
        self.saves += 1
        if self.saves in self.failures:
            raise OSError('fallo de escritura simulado en el intento %d' % self.saves)
        self.data[key] = copy.deepcopy(checkpoint)

    def fingerprint(self, key):
        return json.dumps(self.data.get(key), sort_keys=True, separators=(',', ':'))


class MemoryLease:
    """Protocolo §3.5 en memoria: el llamador aporta la exclusion (prueba de barrera)."""

    def __init__(self, clock, ttl_default=900):
        self._clock = clock
        self._ttl = ttl_default
        self._held = {}
        self._last_owner = None

    def _live(self):
        now = self._clock()
        return {owner: expires for owner, expires in self._held.items() if expires > now}

    @staticmethod
    def _result(acquired, owner, expires_at, previous_owner, event):
        return {'acquired': acquired, 'owner': owner, 'expires_at': expires_at,
                'previous_owner': previous_owner, 'event': event}

    def acquire(self, agent_id, ttl_seconds=60):
        live = self._live()
        self._held = live
        if agent_id in live:
            return self.renew(agent_id, ttl_seconds)
        if live:
            owner = sorted(live)[0]
            return self._result(False, owner, None, None, 'lease_held')
        previous, self._last_owner = self._last_owner, agent_id
        self._held[agent_id] = self._clock() + ttl_seconds
        event = 'lease_expired' if previous not in (None, agent_id) else 'acquired'
        return self._result(True, agent_id, None, previous, event)

    def renew(self, agent_id, ttl_seconds=60):
        live = self._live()
        self._held = live
        if agent_id not in live:
            return self.acquire(agent_id, ttl_seconds)
        self._held[agent_id] = self._clock() + ttl_seconds
        return self._result(True, agent_id, None, None, 'renewed')

    def release(self, agent_id):
        self._held = self._live()
        if agent_id not in self._held:
            return self._result(False, None, None, None, 'released')
        del self._held[agent_id]
        return self._result(True, agent_id, None, None, 'released')


def make_loop(clock, count=2, store=None, calls=None, **kwargs):
    proc = make_process(clock, count, calls, kwargs.pop('worker', None), **kwargs)
    return tl.TeamLoop(proc, store=store, clock=clock)


def assert_receipt_shape(case, receipt):
    case.assertEqual(tuple(sorted(receipt)), tuple(sorted(RECEIPT_FIELDS)))
    case.assertIs(type(receipt['receipt_version']), int)
    case.assertEqual(receipt['receipt_version'], tl.RECEIPT_VERSION)
    case.assertIs(type(receipt['cycle']), int)
    case.assertIn(receipt['mode'], tp.MODES)
    case.assertIs(type(receipt['steps_advanced']), int)
    case.assertEqual(sorted(receipt['budget_consumed']),
                     ['delegations', 'seconds', 'steps', 'tokens'])
    case.assertIn(receipt['motive'], tl.RECEIPT_MOTIVES)
    case.assertRegex(receipt['at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
    case.assertTrue(receipt['checkpoint_digest'] is None
                    or len(receipt['checkpoint_digest']) == 64)
    case.assertTrue(receipt['stop_reason'] is None or receipt['stop_reason'] in tl.STOP_REASONS)
    if receipt['motive'] == 'completed':
        case.assertGreater(receipt['steps_advanced'], 0,
                           'un recibo completed con 0 pasos seria una afirmacion falsa (AV-21)')


# =========================================================================================

class ContractSurfaceTests(unittest.TestCase):
    """El modulo implementa la forma congelada, no una variante propia."""

    def test_frozen_vocabulary_is_declared_verbatim(self):
        for name, value in FROZEN_CONSTANTS.items():
            with self.subTest(constante=name):
                self.assertEqual(getattr(tl, name), value)
        for name, value in FROZEN_TUPLES.items():
            with self.subTest(constante=name):
                self.assertEqual(tuple(getattr(tl, name)), value)
        self.assertEqual(len(tl.LOOP_ERROR_CODES), 8)
        self.assertTrue(callable(getattr(tl, 'stop_decision', None)))

    def test_frozen_signatures_keep_names_order_and_defaults(self):
        init = inspect.signature(tl.TeamLoop.__init__).parameters
        frozen = ['self', 'process', 'channel', 'store', 'clock', 'budget', 'lease',
                  'worker', 'seed']
        self.assertEqual(list(init)[:len(frozen)], frozen)
        self.assertIs(init['process'].default, inspect.Parameter.empty)
        for name in ('channel', 'store', 'clock'):
            self.assertIsNone(init[name].default)
        for name in ('budget', 'lease', 'worker'):
            self.assertEqual(init[name].kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIsNone(init[name].default)
        self.assertEqual(init['seed'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(init['seed'].default, 0)
        self.assertEqual(inspect.signature(tl.TeamLoop.run).parameters['cycles'].default, 1)
        self.assertEqual(inspect.signature(tl.TeamLoop.stop).parameters['reason'].default,
                         'stop_requested')
        for name in ('run', 'start', 'stop', 'status', 'history'):
            self.assertTrue(callable(getattr(tl.TeamLoop, name, None)), name)

    def test_public_surface_exposes_the_contract_names(self):
        public = sorted(name for name in dir(tl) if not name.startswith('_'))
        for name in ('TeamLoop', 'TeamLoopError', 'CoordinationLease', 'stop_decision',
                     'LOOP_SCHEMA', 'LOOP_STATES', 'STOP_REASONS', 'RECEIPT_MOTIVES',
                     'LOOP_ERROR_CODES', 'CHECKPOINT_KEY', 'LOOP_TOPIC'):
            with self.subTest(nombre=name):
                self.assertIn(name, public)

    def test_module_imports_no_network_threads_or_subprocess(self):
        tree = ast.parse(MODULE_PATH.read_text('utf-8'), filename=str(MODULE_PATH))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.lstrip('.').split('.')[0])
        self.assertEqual(sorted(roots & FORBIDDEN_IMPORT_ROOTS), [],
                         'importacion prohibida en el modulo: %s'
                         % sorted(roots & FORBIDDEN_IMPORT_ROOTS))
        self.assertEqual(sorted(roots - ALLOWED_IMPORT_ROOTS), [],
                         'importacion no declarada: %s' % sorted(roots - ALLOWED_IMPORT_ROOTS))
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    calls.add(func.id)
                elif isinstance(func, ast.Attribute):
                    calls.add(func.attr)
        self.assertEqual(sorted(calls & FORBIDDEN_CALLS), [],
                         'llamada prohibida: %s' % sorted(calls & FORBIDDEN_CALLS))

    def test_no_random_no_direct_clock_and_digest_is_canonical(self):
        source = MODULE_PATH.read_text('utf-8')
        self.assertNotIn('import random', source)
        tree = ast.parse(source)
        direct_clock_calls = [node for node in ast.walk(tree)
                              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                              and isinstance(node.func.value, ast.Name)
                              and (node.func.value.id, node.func.attr) in {('time', 'time'),
                                                                           ('datetime', 'now')}]
        self.assertEqual(direct_clock_calls, [],
                         'el unico reloj valido es el inyectado (D6)')
        reference = {'b': 2, 'a': [1, {'d': 4, 'c': 3}]}
        reordered = {'a': [1, {'c': 3, 'd': 4}], 'b': 2}
        self.assertEqual(tl._encode(reference), tl._encode(reordered))
        self.assertEqual(tl._digest_of(tl._encode(reference)),
                         tp.TeamProcess.checkpoint_digest(reference))

    def test_invalid_inputs_are_typed_with_loop_codes(self):
        clock = FakeClock()
        proc = make_process(clock)
        cases = [
            ('invalid_process', lambda: tl.TeamLoop(object())),
            ('invalid_channel', lambda: tl.TeamLoop(proc, channel=object())),
            ('invalid_store', lambda: tl.TeamLoop(proc, store=object())),
            ('invalid_lease', lambda: tl.TeamLoop(proc, lease=object())),
            ('invalid_clock', lambda: tl.TeamLoop(proc, clock='ahora')),
            ('invalid_worker', lambda: tl.TeamLoop(proc, worker='no-callable')),
            ('invalid_budget', lambda: tl.TeamLoop(proc, budget={'steps': 3})),
            ('invalid_budget', lambda: tl.TeamLoop(proc, budget={'seconds': -1})),
            ('invalid_budget', lambda: tl.TeamLoop(proc, budget={'tokens': 1.5})),
            ('invalid_cycles', lambda: tl.TeamLoop(proc, seed=True)),
        ]
        for code, call in cases:
            with self.subTest(code=code):
                with self.assertRaises(tl.TeamLoopError) as caught:
                    call()
                self.assertEqual(caught.exception.code, code)
        loop = tl.TeamLoop(proc, clock=clock)
        for cycles in (-1, 1.0, True, '3'):
            with self.subTest(cycles=cycles):
                with self.assertRaises(tl.TeamLoopError) as caught:
                    loop.run(cycles)
                self.assertEqual(caught.exception.code, 'invalid_cycles')


class CycleReceiptTests(unittest.TestCase):
    """Un ciclo hace las cuatro cosas y deja recibo observable (aceptacion 1)."""

    def test_one_cycle_advances_process_pursues_followups_and_receipts(self):
        clock = FakeClock()
        calls = Calls()
        channel = RecorderChannel()
        followups = Followups()
        loop = tl.TeamLoop(make_process(clock, 2, calls), channel=channel, store={},
                           clock=clock, followups=followups)
        result = loop.run(1)
        self.assertEqual(result['cycles'], 1)
        self.assertEqual(result['stop_reason'], 'cycles_completed')
        self.assertTrue(result['checkpoint_written'])
        receipt = result['receipts'][0]
        assert_receipt_shape(self, receipt)
        self.assertEqual(receipt['cycle'], 1)
        self.assertEqual(receipt['mode'], 'sequential')
        self.assertEqual(receipt['steps_advanced'], 2, 'avanza los dos slots del roster')
        self.assertEqual(receipt['motive'], 'completed')
        self.assertEqual(receipt['budget_consumed']['steps'], 2)
        self.assertEqual(receipt['budget_consumed']['seconds'], 2.0)
        self.assertEqual(calls.total, 2, 'el proceso avanzo de verdad')
        self.assertEqual(followups.ticks, 1, 'persiguio compromisos en el ciclo')
        self.assertEqual(loop.followup_ticks()[0]['cycle'], 1)
        self.assertEqual(len(channel.calls), 1, 'publico el recibo')
        self.assertEqual(channel.calls[0]['topic'], tl.LOOP_TOPIC)
        self.assertEqual(channel.calls[0]['sender'], tl.DEFAULT_PUBLISH_AS)
        self.assertEqual(loop.epochs(), (1000.0,), 'epoch observable por ciclo')

    def test_receipt_and_status_have_the_frozen_shapes(self):
        clock = FakeClock()
        loop = make_loop(clock, 2, store={})
        loop.run(2)
        for receipt in loop.history():
            with self.subTest(ciclo=receipt['cycle']):
                assert_receipt_shape(self, receipt)
        status = loop.status()
        self.assertEqual(tuple(sorted(status)), tuple(sorted(STATUS_FIELDS)))
        self.assertEqual(status['schema'], tl.LOOP_SCHEMA)
        self.assertEqual(status['cycles'], 2)
        self.assertEqual(status['receipt_count'], 2)
        self.assertEqual(status['write_failures'], 0)
        self.assertTrue(status['checkpoint_written'])
        self.assertEqual(len(status['checkpoint_digest']), 64)
        self.assertEqual(status['process'], loop._process.status())
        checkpoint = loop.last_checkpoint()
        self.assertEqual(tuple(sorted(checkpoint['loop'])), tuple(sorted(LOOP_BLOCK_FIELDS)))
        self.assertEqual(checkpoint['loop']['cycles'], 2)
        self.assertEqual(len(checkpoint['loop']['receipts']), 2)
        self.assertEqual(checkpoint['loop']['receipts_omitted'], 0)
        self.assertEqual(checkpoint['loop']['write_failures'], 0)
        self.assertIsNone(checkpoint['loop']['lease'])
        self.assertEqual(tp.TeamProcess.checkpoint_digest(checkpoint),
                         status['checkpoint_digest'])
        self.assertEqual(json.loads(json.dumps(checkpoint, allow_nan=False)), checkpoint)

    def test_history_and_status_return_copies(self):
        clock = FakeClock()
        loop = make_loop(clock, 1, store={})
        loop.run(1)
        history = loop.history()
        first = history[0]
        first['motive'] = 'sabotaje'
        self.assertEqual(loop.history()[0]['motive'], 'completed')
        status = loop.status()
        status['process']['members'][0]['state'] = 'sabotaje'
        self.assertEqual(loop.status()['process']['members'][0]['state'], 'success')
        self.assertIsInstance(loop.history(), tuple)

    def test_worker_can_be_injected_only_when_the_process_has_none(self):
        clock = FakeClock()
        rota = tp.TeamProcess(roster(2), clock=clock)
        calls = Calls()
        loop = tl.TeamLoop(rota, clock=clock, worker=make_worker(clock, calls))
        loop.run(1)
        self.assertEqual(calls.total, 2, 'el bucle inyecto el worker que faltaba')
        ya_tenia = make_process(FakeClock())
        otro = Calls()
        tl.TeamLoop(ya_tenia, clock=FakeClock(), worker=make_worker(FakeClock(), otro))
        ya_tenia.run()
        self.assertEqual(otro.total, 0, 'no se pisa el worker que el proceso ya tenia')

    def test_followups_compose_without_closing_other_members_chases(self):
        clock = FakeClock()
        channel = tc.TeamChannel(CHANNEL_ROSTER, clock=clock)
        engine = fu.FollowupsEngine(channel, agent='id-fu', supervisor='id-ceo', clock=clock,
                                    reminder_interval=0.0, max_reminders=2)
        channel.publish('id-ana', to='id-ceo', text='luego entrego el informe de la fase uno')
        loop = tl.TeamLoop(make_process(clock, 2), channel=channel, clock=clock,
                           followups=engine, publish_as='id-ceo')
        loop.run(2)
        self.assertEqual(engine.stats()['chasing'], 1,
                         'el recibo del bucle no cierra compromisos de otros miembros')
        self.assertEqual(len(loop.followup_ticks()), 2)
        topics = [row for row in channel.ledger_view()['messages']
                  if row['topic'] == tl.LOOP_TOPIC]
        self.assertEqual(len(topics), 2)
        self.assertEqual({row['actor'] for row in topics}, {'id-ceo'})

    def test_a_broken_followups_engine_does_not_lose_the_cycle(self):
        clock = FakeClock()
        loop = tl.TeamLoop(make_process(clock, 1), store={}, clock=clock,
                           followups=ExplodingFollowups())
        result = loop.run(1)
        self.assertEqual(result['cycles'], 1)
        self.assertTrue(result['checkpoint_written'])
        self.assertEqual(len(loop.followup_errors()), 1)
        self.assertIn('Explosion', loop.followup_errors()[0]['error'])


class Followups:
    """Doble del motor de follow-ups: cuenta sus ticks sin tocar el canal."""

    def __init__(self):
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        return ()


class ExplodingFollowups:
    def tick(self):
        raise RuntimeError('Explosion simulada del persecutor')


class ContinuityTests(unittest.TestCase):
    """Continuidad SIN demonio por defecto; start/stop opt-in e idempotentes (aceptacion 2)."""

    def test_eight_cycles_in_a_row_return_the_history(self):
        clock = FakeClock()
        calls = Calls()
        loop = make_loop(clock, 2, store={}, calls=calls)
        result = loop.run(8)
        self.assertEqual(result['cycles'], 8)
        self.assertEqual(len(result['receipts']), 8)
        self.assertEqual(result['stop_reason'], 'cycles_completed')
        self.assertEqual(result['state'], 'running')
        self.assertEqual(len(loop.history()), 8)
        self.assertEqual([row['cycle'] for row in loop.history()], list(range(1, 9)))
        self.assertEqual([row['motive'] for row in loop.history()], ['completed'] * 8)
        self.assertEqual(calls.total, 16, '8 ciclos x 2 slots, sin repetir ninguno')
        self.assertEqual(loop.status()['cycles'], 8)
        self.assertEqual(loop.status()['receipt_count'], 8)
        self.assertEqual(loop.status()['process']['steps_total'], 16)
        self.assertEqual(len(loop.last_checkpoint()['loop']['receipts']), 8)

    def test_run_is_synchronous_and_creates_no_threads(self):
        before = {thread.name for thread in threading.enumerate()}
        clock = FakeClock()
        loop = make_loop(clock, 2, store={})
        result = loop.run(3)
        new_threads = {thread.name for thread in threading.enumerate()} - before
        self.assertEqual(new_threads, set(), 'run() no crea hilos: es sincrono')
        self.assertEqual(result['cycles'], 3)
        self.assertEqual(loop.history()[-1]['cycle'], 3)

    def test_start_is_opt_in_idempotent_and_runs_nothing(self):
        clock = FakeClock()
        calls = Calls()
        loop = make_loop(clock, 2, store={}, calls=calls)
        first = loop.start()
        second = loop.start()
        self.assertEqual(first['state'], 'running')
        self.assertEqual(second['state'], 'running')
        self.assertEqual(first, second, 'start() es idempotente')
        self.assertEqual(loop.status()['receipt_count'], 0, 'start() no ejecuta ciclos')
        self.assertEqual(calls.total, 0)
        self.assertEqual(loop.epochs(), ())

    def test_stop_is_idempotent_and_keeps_the_last_receipt(self):
        clock = FakeClock()
        loop = make_loop(clock, 2, store={})
        loop.run(2)
        snapshot = [copy.deepcopy(row) for row in loop.history()]
        first = loop.stop('stop_requested')
        second = loop.stop('stop_requested')
        self.assertEqual(first['stop_reason'], second['stop_reason'])
        self.assertEqual(first['cycles'], second['cycles'])
        self.assertEqual(first['receipt_count'], second['receipt_count'])
        self.assertEqual(loop.history(), tuple(snapshot), 'un recibo emitido no se reescribe')
        self.assertEqual(loop.status()['state'], 'stopped')
        with self.assertRaises(ValueError):
            loop.stop('motivo-inventado')

    def test_stop_before_the_first_cycle_does_not_fake_work(self):
        clock = FakeClock()
        calls = Calls()
        loop = make_loop(clock, 2, store={}, calls=calls)
        status = loop.stop('stop_requested')
        self.assertEqual(status['state'], 'not_run')
        self.assertEqual(status['stop_reason'], 'stopped_before_start')
        self.assertEqual(status['receipt_count'], 0)
        self.assertEqual(status['cycles'], 0)
        self.assertEqual(calls.total, 0)
        self.assertFalse(status['checkpoint_written'])
        result = loop.run(3)
        self.assertEqual(result['cycles'], 0, 'tras la parada no se inicia ningun ciclo')
        self.assertEqual(loop.history(), ())
        self.assertEqual(calls.total, 0)

    def test_zero_cycles_means_zero_receipts(self):
        clock = FakeClock()
        calls = Calls()
        loop = make_loop(clock, 2, store={}, calls=calls)
        result = loop.run(0)
        self.assertEqual(result['cycles'], 0)
        self.assertEqual(result['receipts'], ())
        self.assertIsNone(result['stop_reason'])
        self.assertEqual(result['state'], 'not_run')
        self.assertEqual(loop.history(), ())
        self.assertEqual(calls.total, 0)
        self.assertEqual(loop.status()['checkpoint_written'], False)

    def test_stop_between_cycles_keeps_the_checkpoint_and_adds_no_receipt(self):
        clock = FakeClock()
        loop = make_loop(clock, 2, store={})
        loop.run(2)
        before = loop.last_checkpoint()
        loop.stop('stop_requested')
        result = loop.run(5)
        self.assertEqual(result['cycles'], 0)
        self.assertEqual(result['stop_reason'], 'stop_requested')
        self.assertEqual(loop.status()['receipt_count'], 2)
        after = loop.last_checkpoint()
        self.assertEqual(tp.TeamProcess.checkpoint_digest(before),
                         tp.TeamProcess.checkpoint_digest(after),
                         'el checkpoint conserva los 2 ciclos intactos')
        self.assertEqual(after['loop']['cycles'], 2)

    def test_two_motives_are_distinct_within_the_frozen_vocabulary(self):
        clock = FakeClock()
        tokens_budget = make_loop(clock, 1, store={})
        tokens_budget = tl.TeamLoop(make_process(clock, 1, worker=make_worker(clock, tokens=90)),
                                    store={}, clock=clock, budget={'tokens': 50})
        result = tokens_budget.run(1)
        self.assertEqual(result['receipts'][0]['motive'], 'budget_exhausted')
        self.assertEqual(result['stop_reason'], 'budget_exhausted')

        clock2 = FakeClock()
        holder = {}

        def worker(request):
            clock2.advance(1.0)
            holder['loop'].stop('stop_requested')
            return {slot: {'state': 'success', 'result': 'ok-%d' % slot}
                    for slot in request['slots']}

        stopped = tl.TeamLoop(make_process(clock2, 1, worker=worker), store={}, clock=clock2)
        holder['loop'] = stopped
        result2 = stopped.run(4)
        self.assertEqual(len(result2['receipts']), 1)
        self.assertEqual(result2['receipts'][0]['motive'], 'stop_requested')
        self.assertEqual(result2['stop_reason'], 'stop_requested')
        motives = {result['receipts'][0]['motive'], result2['receipts'][0]['motive']}
        self.assertEqual(len(motives), 2, 'dos ciclos cerrados por motivos distintos (AV-20)')
        for receipt in (result['receipts'][0], result2['receipts'][0]):
            assert_receipt_shape(self, receipt)

    def test_a_caller_daemon_thread_drives_continuity_and_stop_is_clean(self):
        clock = FakeClock()
        store = ProtocolStore()
        calls = Calls()
        loop = make_loop(clock, 2, store=store, calls=calls)
        gate = threading.Event()
        gate.set()
        outcome = {}

        def sleep(seconds):
            gate.wait(2.0)   # el bucle no duerme: cede el turno para que la prueba pueda parar

        def drive():
            outcome.update(loop.run_until_stopped(max_cycles=200, sleep=sleep))

        driver = threading.Thread(target=drive, name='team-loop-daemon', daemon=True)
        self.assertTrue(driver.daemon, 'el hilo daemon lo aporta el llamador (opt-in)')
        driver.start()
        deadline = time.time() + 10.0
        while loop.status()['receipt_count'] < 3 and time.time() < deadline:
            time.sleep(0.002)
        first = loop.stop('stop_requested')
        second = loop.stop('stop_requested')
        driver.join(10.0)
        self.assertFalse(driver.is_alive(), 'stop() detuvo la continuidad')
        self.assertEqual(first['stop_reason'], second['stop_reason'])
        self.assertEqual(first['cycles'], second['cycles'])
        self.assertEqual(first['receipt_count'], second['receipt_count'])
        self.assertGreaterEqual(loop.status()['receipt_count'], 3)
        self.assertEqual(outcome['stop_reason'], 'stop_requested')
        checkpoint = loop.last_checkpoint()
        self.assertEqual(checkpoint['loop']['cycles'], loop.status()['cycles'],
                         'el ciclo en curso se cerro entero: sin estado a medias')
        self.assertEqual(store.data[tl.CHECKPOINT_KEY]['loop']['cycles'],
                         loop.status()['cycles'])
        self.assertEqual(tp.TeamProcess.checkpoint_digest(checkpoint),
                         loop.status()['checkpoint_digest'])
        for receipt in loop.history():
            assert_receipt_shape(self, receipt)
        self.assertEqual(loop.status()['state'], 'stopped')
        self.assertGreater(len(loop.delays()), 0, 'publico el retardo determinista')


class LeaseBarrierTests(unittest.TestCase):
    """Exclusividad: dos bucles no duplican trabajo (aceptacion 3, AV-23/AV-24)."""

    def test_a_held_lease_blocks_the_second_loop_without_advancing(self):
        clock = FakeClock()
        shared_lease = MemoryLease(clock)
        store = ProtocolStore()
        first_calls, second_calls = Calls(), Calls()
        first = tl.TeamLoop(make_process(clock, 2, first_calls), store=store, clock=clock,
                            lease=shared_lease, lease_owner='loop-a')
        second = tl.TeamLoop(make_process(clock, 2, second_calls), store=store, clock=clock,
                             lease=shared_lease, lease_owner='loop-b')
        self.assertEqual(first.run(1)['cycles'], 1)
        fingerprint = store.fingerprint(tl.CHECKPOINT_KEY)
        result = second.run(1)
        self.assertEqual(result['cycles'], 0, 'el segundo bucle NO avanza nada')
        self.assertEqual(result['stop_reason'], 'lease_held')
        self.assertFalse(result['checkpoint_written'])
        self.assertEqual(result['receipts'], ())
        self.assertEqual(second.status()['receipt_count'], 0)
        self.assertEqual(second_calls.total, 0, 'sin trabajo duplicado')
        self.assertEqual(store.fingerprint(tl.CHECKPOINT_KEY), fingerprint,
                         'no escribe checkpoint')
        self.assertEqual(second.status()['lease']['event'], 'lease_held')
        self.assertEqual(second.status()['lease']['owner'], 'loop-a')
        self.assertEqual(second.status()['state'], 'stopped')

    def test_a_lease_on_the_real_coordination_store_blocks_the_second_loop(self):
        clock = FakeClock()
        root = tempfile.mkdtemp(prefix='team-loop-coord-')
        self.addCleanup(shutil.rmtree, root, True)
        store = co.CoordinationStore(root, clock=clock)
        checkpoints = ProtocolStore()
        first = tl.TeamLoop(make_process(clock, 1), store=checkpoints, clock=clock,
                            lease=tl.CoordinationLease(store), lease_owner='loop-a')
        second = tl.TeamLoop(make_process(clock, 1), store=checkpoints, clock=clock,
                             lease=tl.CoordinationLease(store), lease_owner='loop-b')
        self.assertEqual(first.run(1)['cycles'], 1)
        result = second.run(1)
        self.assertEqual((result['cycles'], result['stop_reason']), (0, 'lease_held'))
        self.assertEqual(second.status()['lease']['owner'], 'loop-a')
        self.assertEqual(len(checkpoints.data[tl.CHECKPOINT_KEY]['loop']['receipts']), 1)
        files = [path.name for path in Path(root).iterdir() if path.is_file()]
        self.assertIn('coordination.json', files,
                      'el almacen inyectado es el unico que escribe')
        self.assertTrue(all(path.startswith(('coordination.json', '.coordination')) for path in files))

    def test_an_expired_lease_is_taken_and_declared_then_resumes_from_the_checkpoint(self):
        clock = FakeClock()
        root = tempfile.mkdtemp(prefix='team-loop-exp-')
        self.addCleanup(shutil.rmtree, root, True)
        coordination = co.CoordinationStore(root, clock=clock)
        store = ProtocolStore()
        first = tl.TeamLoop(make_process(clock, 1), store=store, clock=clock,
                            lease=tl.CoordinationLease(coordination), lease_owner='loop-a')
        first.run(2)
        self.assertIn(first.status()['lease']['event'], ('acquired', 'renewed'))
        # El primer bucle suelta su arriendo (p. ej. el operador lo apaga) y un agente ajeno
        # lo toma y muere sin liberarlo: ese es el arriendo huerfano de AV-24.
        tl.CoordinationLease(coordination).release('loop-a')
        ajeno = tl.CoordinationLease(coordination).acquire('agente-caido', 60)
        self.assertTrue(ajeno['acquired'])
        clock.advance(120)   # el ttl vence: el arriendo queda huerfano
        checkpoint = store.data[tl.CHECKPOINT_KEY]
        revived = tp.TeamProcess.from_checkpoint(checkpoint, clock=clock,
                                                 worker=make_worker(clock))
        second = tl.TeamLoop(revived, store=store, clock=clock,
                             lease=tl.CoordinationLease(coordination), lease_owner='loop-b')
        result = second.run(1)
        self.assertEqual(result['cycles'], 1)
        lease_state = second.status()['lease']
        self.assertEqual(lease_state['event'], 'lease_expired')
        self.assertEqual(lease_state['previous_owner'], 'agente-caido')
        self.assertEqual(lease_state['owner'], 'loop-b')
        receipt = result['receipts'][0]
        self.assertEqual(receipt['cycle'], 3, 'el primer ciclo continua desde el checkpoint')
        self.assertGreaterEqual(second.status()['process']['resumptions'], 1)
        self.assertEqual(second.status()['cycles'], 3, 'loop.cycles no retrocede')

    def test_lease_is_renewed_on_every_cycle(self):
        clock = FakeClock()
        shared = MemoryLease(clock)
        loop = tl.TeamLoop(make_process(clock, 1), store={}, clock=clock, lease=shared,
                           lease_owner='loop-a')
        loop.run(1)
        self.assertEqual(loop.status()['lease']['event'], 'acquired')
        loop.run(1)
        self.assertEqual(loop.status()['lease']['event'], 'renewed',
                         'cada ciclo renueva su arriendo antes de avanzar')
        self.assertEqual(loop.status()['lease']['owner'], 'loop-a')

    def test_lease_release_on_stop_is_idempotent(self):
        clock = FakeClock()
        root = tempfile.mkdtemp(prefix='team-loop-rel-')
        self.addCleanup(shutil.rmtree, root, True)
        coordination = co.CoordinationStore(root, clock=clock)
        loop = tl.TeamLoop(make_process(clock, 1), clock=clock,
                           lease=tl.CoordinationLease(coordination), lease_owner='loop-a')
        loop.run(1)
        self.assertEqual(loop.stop('stop_requested')['lease']['event'], 'released')
        self.assertEqual(loop.stop('stop_requested')['lease']['event'], 'released')
        self.assertEqual(coordination.public()['active_writer_count'], 0)


class BudgetAndBackoffTests(unittest.TestCase):
    """Cortes controlados: presupuesto por ciclo y backoff determinista (aceptacion 4)."""

    def test_time_budget_cuts_the_cycle_and_reports_the_observed_seconds(self):
        clock = FakeClock()
        loop = tl.TeamLoop(make_process(clock, 2, worker=make_worker(clock, seconds=3.0)),
                           store={}, clock=clock, budget={'seconds': 5.0})
        result = loop.run(4)
        self.assertEqual(result['cycles'], 1)
        self.assertEqual(result['stop_reason'], 'time_exhausted')
        receipt = result['receipts'][0]
        assert_receipt_shape(self, receipt)
        self.assertEqual(receipt['motive'], 'time_exhausted')
        self.assertEqual(receipt['stop_reason'], 'time_exhausted')
        self.assertEqual(receipt['budget_consumed']['seconds'], 6.0,
                         '6 s observados con limite de 5 s (AV-17)')
        self.assertEqual(receipt['steps_advanced'], 2, 'el ciclo cierra con lo avanzado')
        self.assertEqual(loop.status()['state'], 'stopped')

    def test_token_budget_cuts_after_the_observed_consumption(self):
        clock = FakeClock()
        loop = tl.TeamLoop(make_process(clock, 1, worker=make_worker(clock, tokens=90)),
                           store={}, clock=clock, budget={'tokens': 50})
        result = loop.run(3)
        self.assertEqual(result['cycles'], 1)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['receipts'][0]['budget_consumed']['tokens'], 90)

    def test_backoff_is_deterministic_per_seed_and_never_sleeps(self):
        clock = FakeClock()
        first = tl.TeamLoop(make_process(clock, 1), clock=clock, seed=7)
        second = tl.TeamLoop(make_process(FakeClock(), 1), clock=FakeClock(), seed=7)
        other = tl.TeamLoop(make_process(FakeClock(), 1), clock=FakeClock(), seed=8)
        self.assertEqual(first.next_delay(1), second.next_delay(1))
        self.assertEqual(first.next_delay(1), first.next_delay(1))
        self.assertNotEqual(first.next_delay(1), other.next_delay(1))
        delays = [first.next_delay(cycle) for cycle in range(1, 6)]
        self.assertEqual(len(set(delays)), len(delays), 'el jitter varia por ciclo')
        for delay in delays:
            self.assertGreaterEqual(delay, tl.DEFAULT_BACKOFF_BASE_SECS)
            self.assertLess(delay, 2 * tl.DEFAULT_BACKOFF_BASE_SECS)
        self.assertEqual(first.delays(), (), 'el bucle no espera por si mismo')

    def test_run_until_stopped_publishes_delays_only_when_the_caller_sleeps(self):
        clock = FakeClock()
        loop = make_loop(clock, 1, store={})
        slept = []
        result = loop.run_until_stopped(max_cycles=3, sleep=slept.append)
        self.assertEqual(result['cycles'], 3)
        self.assertEqual(len(slept), 3)
        self.assertEqual(loop.delays(), tuple(slept))
        self.assertTrue(all(delay > 0 for delay in slept))
        sin_reloj = make_loop(FakeClock(), 1, store={})
        sin_reloj.run_until_stopped(max_cycles=2)
        self.assertEqual(len(sin_reloj.delays()), 2)

    def test_invalid_budget_and_cycles_are_typed(self):
        clock = FakeClock()
        proc = make_process(clock)
        for budget in ({'minutes': 1}, {'seconds': -3}, {'tokens': -1}, {'tokens': True},
                       {'seconds': 'mucho'}, [('seconds', 1)]):
            with self.subTest(budget=budget):
                with self.assertRaises(tl.TeamLoopError) as caught:
                    tl.TeamLoop(proc, budget=budget)
                self.assertEqual(caught.exception.code, 'invalid_budget')
        loop = tl.TeamLoop(proc, clock=clock)
        with self.assertRaises(tl.TeamLoopError) as caught:
            loop.run_until_stopped(max_cycles=-1)
        self.assertEqual(caught.exception.code, 'invalid_cycles')
        with self.assertRaises(tl.TeamLoopError) as caught:
            loop.run_until_stopped(sleep='deprisa')
        self.assertEqual(caught.exception.code, 'invalid_worker')


class ResumptionTests(unittest.TestCase):
    """Reanudacion sin repetir pasos, cortando en el ciclo 3 de 8 (aceptacion 5)."""

    def test_cut_at_cycle_three_of_eight_resumes_without_repeating_steps(self):
        clock = FakeClock()
        store = ProtocolStore()
        expected_slots = 2
        first_calls = Calls()
        first = tl.TeamLoop(make_process(clock, expected_slots, first_calls), store=store,
                            clock=clock)
        first.run(2)
        self.assertEqual(len(first.history()), 2)
        durable = [copy.deepcopy(row) for row in first.history()]
        checkpoint = store.data[tl.CHECKPOINT_KEY]
        self.assertEqual(checkpoint['loop']['cycles'], 2)

        # Corte: el proceso "muere" tras el ciclo 2 y se levanta desde el checkpoint.
        second_calls = Calls()
        revived = tp.TeamProcess.from_checkpoint(checkpoint, clock=clock,
                                                 worker=make_worker(clock, second_calls))
        resumed = tl.TeamLoop(revived, store=store, clock=clock)
        result = resumed.run(6)
        self.assertEqual(result['cycles'], 6)
        self.assertEqual(len(resumed.history()), 8, '2 adoptados + 6 nuevos')
        self.assertEqual([row['cycle'] for row in resumed.history()], list(range(1, 9)))
        self.assertEqual(resumed.history()[:2], tuple(durable),
                         'los recibos adoptados son los mismos, no se reescriben')
        self.assertEqual(second_calls.total, 6 * expected_slots,
                         'solo se ejecutan los slots de los ciclos nuevos')
        self.assertEqual(resumed.status()['process']['steps_total'], 8 * expected_slots)
        self.assertEqual(resumed.status()['cycles'], 8)
        self.assertGreaterEqual(resumed.status()['process']['resumptions'], 1)
        self.assertEqual(len(resumed.last_checkpoint()['loop']['receipts']), 8)

    def test_a_process_interrupted_mid_cycle_does_not_lose_durable_state(self):
        clock = FakeClock()
        store = ProtocolStore()
        first = tl.TeamLoop(make_process(clock, 2), store=store, clock=clock)
        first.run(2)
        fingerprint = store.fingerprint(tl.CHECKPOINT_KEY)

        def explota(request):
            raise RuntimeError('interrupcion simulada a mitad de ciclo')

        revived = tp.TeamProcess.from_checkpoint(store.data[tl.CHECKPOINT_KEY], clock=clock,
                                                 worker=explota)
        broken = tl.TeamLoop(revived, store=store, clock=clock)
        with self.assertRaises(RuntimeError):
            broken.run(1)
        self.assertEqual(store.fingerprint(tl.CHECKPOINT_KEY), fingerprint,
                         'una interrupcion no reescribe el estado durable')
        self.assertEqual(len(broken.history()), 2, 'no inventa un recibo para el ciclo roto')

    def test_resumption_adopts_loop_counters_and_keeps_receipts_complete(self):
        clock = FakeClock()
        store = ProtocolStore()
        first = tl.TeamLoop(make_process(clock, 1), store=store, clock=clock)
        first.run(3)
        admitted = first.history()
        self.assertEqual(len(admitted), 3)
        self.assertTrue(all(len(row['checkpoint_digest'] or '') == 64 for row in admitted),
                        'cada recibo confirmado lleva su digest')
        revived = tp.TeamProcess.from_checkpoint(store.data[tl.CHECKPOINT_KEY], clock=clock,
                                                 worker=make_worker(clock))
        resumed = tl.TeamLoop(revived, store=store, clock=clock)
        self.assertEqual(resumed.run(0)['cycles'], 0)
        self.assertEqual(resumed.history(), (), 'sin ciclo no se adopta nada aun')
        resumed.run(1)
        self.assertEqual(len(resumed.history()), 4)
        self.assertEqual([row['motive'] for row in resumed.history()][:3],
                         [row['motive'] for row in admitted])


class WriteFailureTests(unittest.TestCase):
    """Un ciclo fallido no deja estado parcial: AV-03 (aceptacion 4/5)."""

    def test_failed_write_restores_state_and_counts_two_durable_steps(self):
        clock = FakeClock()
        store = ProtocolStore()
        store.failures = {2}
        calls = Calls()
        loop = tl.TeamLoop(make_process(clock, 1, calls), store=store, clock=clock)
        fingerprint_before = None
        result = loop.run(3)
        self.assertEqual(result['cycles'], 3)
        motives = [row['motive'] for row in result['receipts']]
        self.assertEqual(motives, ['completed', 'checkpoint_write_failed', 'completed'])
        steps = [row['steps_advanced'] for row in result['receipts']]
        self.assertEqual(steps, [1, 0, 1], 'pasos avanzados 2, nunca 3 (AV-03)')
        self.assertEqual(sum(steps), 2)
        self.assertIsNone(result['receipts'][1]['checkpoint_digest'])
        self.assertEqual(loop.status()['write_failures'], 1)
        self.assertEqual(loop.status()['cycles'], 3, 'cycles cuenta intentos')
        self.assertEqual(loop.status()['cycles'] - loop.status()['write_failures'], 2,
                         'ciclos durables = intentos - fallos')
        self.assertEqual(loop.status()['process']['steps_total'], 2,
                         'el estado en memoria se restauro al de antes del ciclo fallido')
        self.assertEqual(store.data[tl.CHECKPOINT_KEY]['loop']['write_failures'], 1)
        self.assertEqual(len(store.data[tl.CHECKPOINT_KEY]['loop']['receipts']), 3)
        self.assertEqual(tp.TeamProcess.checkpoint_digest(store.data[tl.CHECKPOINT_KEY]),
                         loop.status()['checkpoint_digest'])

    def test_the_previous_checkpoint_stays_byte_identical(self):
        clock = FakeClock()
        store = ProtocolStore()
        loop = tl.TeamLoop(make_process(clock, 1), store=store, clock=clock)
        loop.run(1)
        before = store.fingerprint(tl.CHECKPOINT_KEY)
        digest_before = loop.status()['checkpoint_digest']
        store.failures = {store.saves + 1}
        loop.run(1)
        self.assertEqual(store.fingerprint(tl.CHECKPOINT_KEY), before,
                         'el checkpoint anterior queda intacto byte a byte')
        self.assertEqual(loop.status()['checkpoint_digest'], digest_before)
        self.assertEqual(loop.history()[-1]['motive'], 'checkpoint_write_failed')

    def test_serialization_failure_is_a_checkpoint_write_failure(self):
        clock = FakeClock()
        store = ProtocolStore()
        loop = tl.TeamLoop(make_process(clock, 1), store=store, clock=clock)
        loop.run(1)
        with patch.object(tl, '_encode', side_effect=ValueError('serializacion simulada')):
            result = loop.run(1)
        self.assertEqual(result['receipts'][0]['motive'], 'checkpoint_write_failed')
        self.assertEqual(result['receipts'][0]['steps_advanced'], 0)
        self.assertEqual(result['checkpoints'] if 'checkpoints' in result else False, False)
        self.assertEqual(loop.status()['write_failures'], 1)
        self.assertEqual(len(store.data[tl.CHECKPOINT_KEY]['loop']['receipts']), 1,
                         'el checkpoint durable no crecio con el ciclo fallido')

    def test_without_store_the_state_lives_in_memory_and_says_so(self):
        clock = FakeClock()
        loop = tl.TeamLoop(make_process(clock, 2), clock=clock)
        result = loop.run(2)
        self.assertFalse(result['checkpoint_written'])
        self.assertFalse(loop.status()['checkpoint_written'])
        self.assertIsNone(loop.status()['checkpoint_digest'])
        self.assertIsNone(loop.last_checkpoint())
        self.assertEqual(len(loop.history()), 2)
        self.assertEqual([row['checkpoint_digest'] for row in loop.history()], [None, None])


class ExhaustedProcessTests(unittest.TestCase):
    """El bucle NO avanza si el proceso esta `budget_exhausted` (aceptacion 7)."""

    def test_loop_does_not_advance_an_exhausted_process(self):
        clock = FakeClock()
        calls = Calls()
        proc = tp.TeamProcess(roster(3), clock=clock, budget={'steps': 2},
                              worker=make_worker(clock, calls))
        loop = tl.TeamLoop(proc, store={}, clock=clock)
        first = loop.run(1)
        self.assertEqual(first['receipts'][0]['motive'], 'budget_exhausted')
        self.assertEqual(first['receipts'][0]['steps_advanced'], 2)
        self.assertEqual(first['stop_reason'], 'budget_exhausted')
        self.assertEqual(loop.status()['process']['cycle_state'], 'budget_exhausted')
        steps_after_first = loop.status()['process']['steps_total']
        receipts_after_first = loop.status()['receipt_count']
        second = loop.run(1)
        self.assertEqual(second['cycles'], 0, 'no avanza un proceso agotado')
        self.assertEqual(second['receipts'], (), 'no emite un recibo vacio')
        self.assertEqual(second['stop_reason'], 'budget_exhausted')
        self.assertEqual(loop.status()['process']['steps_total'], steps_after_first)
        self.assertEqual(loop.status()['receipt_count'], receipts_after_first)

    def test_process_budget_exhausted_stops_the_loop_even_with_cycles_left(self):
        clock = FakeClock()
        loop = tl.TeamLoop(
            tp.TeamProcess(roster(3), clock=clock, budget={'steps': 2},
                           worker=make_worker(clock)), store={}, clock=clock)
        result = loop.run(5)
        self.assertEqual(result['cycles'], 1)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(len(loop.history()), 1)
        self.assertEqual(loop.status()['state'], 'stopped')


class StopDecisionTests(unittest.TestCase):
    """Las condiciones de parada son una funcion PURA y separable (costura de t30)."""

    def test_signature_is_small_and_takes_state_plus_budget(self):
        parameters = list(inspect.signature(tl.stop_decision).parameters)
        self.assertEqual(parameters, ['state', 'budget'])

    def test_each_rule_and_its_precedence(self):
        budget = {'seconds': 5.0, 'tokens': 100}
        base = {'cycle_state': 'completed', 'elapsed_seconds': 1.0, 'tokens_consumed': 10,
                'stop_requested': False, 'write_failed': False}
        self.assertEqual(tl.stop_decision(base, budget)['stop'], False)
        self.assertEqual(tl.stop_decision(base, budget)['motive'], 'completed')
        self.assertEqual(tl.stop_decision(dict(base, cycle_state='incomplete'), budget)['motive'],
                         'incomplete')
        self.assertEqual(tl.stop_decision(dict(base, write_failed=True), budget),
                         {'stop': False, 'motive': 'checkpoint_write_failed',
                          'stop_reason': None,
                          'reason': 'la escritura durable fallo: el ciclo se reintenta y nada '
                                    'se conto'})
        time_out = tl.stop_decision(dict(base, elapsed_seconds=6.0), budget)
        self.assertEqual((time_out['stop'], time_out['motive'], time_out['stop_reason']),
                         (True, 'time_exhausted', 'time_exhausted'))
        tokens_out = tl.stop_decision(dict(base, tokens_consumed=101), budget)
        self.assertEqual((tokens_out['stop'], tokens_out['motive']), (True, 'budget_exhausted'))
        process_out = tl.stop_decision(dict(base, cycle_state='budget_exhausted'), budget)
        self.assertEqual((process_out['stop'], process_out['motive']), (True, 'budget_exhausted'))
        stop_out = tl.stop_decision(dict(base, stop_requested=True), budget)
        self.assertEqual((stop_out['stop'], stop_out['motive'], stop_out['stop_reason']),
                         (True, 'stop_requested', 'stop_requested'))
        # Precedencia: write_failed manda sobre todo; el tiempo manda sobre los tokens.
        self.assertEqual(tl.stop_decision(dict(base, write_failed=True, elapsed_seconds=99.0),
                                          budget)['motive'], 'checkpoint_write_failed')
        self.assertEqual(tl.stop_decision(dict(base, elapsed_seconds=9.0, tokens_consumed=999),
                                          budget)['motive'], 'time_exhausted')
        # Un techo en None no corta nunca.
        self.assertEqual(tl.stop_decision(dict(base, elapsed_seconds=10 ** 6),
                                          {'seconds': None, 'tokens': None})['stop'], False)

    def test_the_function_is_pure_and_deterministic(self):
        state = {'cycle_state': 'completed', 'elapsed_seconds': 6.0, 'tokens_consumed': 1,
                 'stop_requested': False, 'write_failed': False}
        budget = {'seconds': 5.0, 'tokens': 50}
        frozen_state = copy.deepcopy(state)
        frozen_budget = copy.deepcopy(budget)
        first = tl.stop_decision(state, budget)
        second = tl.stop_decision(state, budget)
        self.assertEqual(first, second, 'misma entrada, misma salida')
        self.assertEqual(state, frozen_state, 'no muta el estado')
        self.assertEqual(budget, frozen_budget, 'no muta el presupuesto')
        self.assertIn(first['motive'], tl.RECEIPT_MOTIVES)
        self.assertIn(first['stop_reason'], tl.STOP_REASONS)

    def test_no_verdict_path_is_silent(self):
        for cycle_state in (None, 'completed', 'incomplete', 'budget_exhausted', 'inventado'):
            with self.subTest(cycle_state=cycle_state):
                verdict = tl.stop_decision({'cycle_state': cycle_state,
                                            'elapsed_seconds': 0.0, 'tokens_consumed': 0,
                                            'stop_requested': False, 'write_failed': False},
                                           {'seconds': None, 'tokens': None})
                self.assertIn(verdict['motive'], tl.RECEIPT_MOTIVES)
                self.assertTrue(verdict['reason'].strip(), 'toda decision lleva motivo')


if __name__ == '__main__':
    unittest.main()
