"""TeamProcess (M1) — motor de proceso por pasos, determinista y durable.

Contrato congelado: `docs/rea/TEAM_API_CONTRACT_v1.md` (`TEAM_API_CONTRACT_v1`, tarea `t31`).
Vectores de comportamiento: `docs/rea/agile_vectors.json` (`AV-01…AV-24`, tarea `t21`).

Este modulo convierte un roster pasivo en un grupo que avanza de forma seguida y continua sin perder
estado. Hace **solo** tres cosas: modelar el modo de trabajo `sequential`, `hierarchical` o
`parallel_waves`; avanzar **por pasos explicitos** (`step()` / `run(limit)`) sin hilos, sin bucles
infinitos y sin demonios; y exportar/importar un checkpoint v1 (`dict` JSON) para reanudar sin repetir
trabajo ya completado. La continuidad la orquesta `engine/team_loop.py` (t23).

Lo que este modulo NO hace, por contrato:
  * no abre red, no lanza `subprocess`, no crea hilos, no usa `random` global y **no escribe ficheros**:
    el checkpoint es un `dict` y la persistencia la decide quien llama;
  * no decide estrategia ni politica: no evalua puertas, no concede permisos, no toca DSH;
  * no ejecuta el trabajo de un miembro: lo aporta el `worker` inyectado o el `outcome` del llamador.

Determinismo (contrato §5): orden canonico por `slot`; consolidacion por orden de **entrada**, nunca de
finalizacion; reloj inyectable (`clock() -> float` epoch, defecto `time.time`) con el formateo del repo;
cero dependencia del orden de `dict`/`set`; digest sobre JSON canonico.

Presupuestos (contrato §7): los tres topes del contrato son `steps`, `seconds` y `delegations`; `tokens`
es la cuarta dimension de coste (AV-16) y usa el mismo mecanismo. Los techos declarados son **duros y
acumulativos** y el consumo es **monotono no decreciente** y auditable (AV-18): agotar un techo cierra el
ciclo con `cycle_state='budget_exhausted'` y `budget.exhausted={'reason': ...}`, nunca con una excepcion
generica. Para conceder una asignacion nueva, el llamador reanuda con `from_checkpoint(..., budget=...)`.

Reanudacion (contrato §8): `import_checkpoint()` rehidrata el estado e incrementa `resumptions`; un slot ya
`success` en el ciclo en curso, una delegacion cerrada, una ola cerrada y los contadores de presupuesto no
se reejecutan ni se reinician.

Solo biblioteca estandar (`collections.abc`, `dataclasses`, `datetime`, `hashlib`, `json`, `math`, `re`,
`time`). Python 3.10+. Sin efectos al importar.

Codigo verbatim (ENMIENDA PERMANENTE del operador):
  Fragmento **MG-F1** de `FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f`
  (`metagpt/team.py` L87-100, blob `5a9838885070add38a7cdd3ddf034ea40768d4b2`, licencia **MIT**),
  adoptado como `_BudgetBalance` (corte de presupuesto de M5) tras el gate Tier 2 de `t29`
  (`docs/rea/license_audit.md`, `docs/rea/PORT_REPORT_AGILIDAD.md`). Autorizado por
  `docs/security/FUSILE_SOURCE_POLICY.md`. Declaracion de cambios en el bloque y en el informe; la
  superficie publica del contrato (`TeamProcess`, `TeamProcessError` y §1) **no cambia**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

MODES = ('sequential', 'hierarchical', 'parallel_waves')
CYCLE_STATES = ('not_run', 'running', 'incomplete', 'completed', 'budget_exhausted')
MEMBER_STATES = ('pending', 'running', 'success', 'failed', 'skipped')
DELEGATION_STATES = ('open', 'closed')
BUDGET_DIMENSIONS = ('steps', 'seconds', 'delegations', 'tokens')
EXHAUSTION_REASONS = ('steps', 'seconds', 'delegations', 'tokens')

CHECKPOINT_VERSION = 1
CHECKPOINT_SCHEMA = 'orgdna.team_process.checkpoint/1'
PROCESS_SCHEMA = 'orgdna.team_process/1'
RECEIPT_VERSION = 1
DEFAULT_WAVE_SIZE = 4
MAX_WAVE_SIZE = 32
MAX_MEMBERS = 32
MAX_UNITS_PER_RUN = 4096
#: Profundidad maxima declarada de delegacion: el coordinador delega (1) y un delegado NO subdelega.
MAX_DELEGATION_DEPTH = 1
MEMBER_ID_PATTERN = r'^[a-z0-9][a-z0-9._-]{1,63}$'

PROCESS_ERROR_CODES = (
    'invalid_roster', 'unknown_mode', 'unknown_member', 'invalid_wave_size', 'invalid_budget',
    'invalid_limit', 'invalid_clock', 'invalid_worker', 'invalid_outcome', 'unknown_delegation',
    'unsupported_checkpoint_version', 'checkpoint_shape_invalid', 'checkpoint_mismatch',
    'worker_required', 'cycle_closed',
)

CHECKPOINT_FIELDS = ('checkpoint_version', 'schema', 'mode', 'coordinator_slot', 'roster', 'cycle', 'step',
                     'steps_total', 'cycle_state', 'resumptions', 'members', 'results', 'delegations',
                     'waves', 'budget', 'loop', 'created_at', 'updated_at')
ROSTER_FIELDS = ('slot', 'member_id', 'role', 'is_coordinator', 'delegates_to')
MEMBER_FIELDS = ('slot', 'state', 'steps')
RESULT_FIELDS = ('slot', 'state', 'result', 'cycle', 'step')
DELEGATION_FIELDS = ('delegation_id', 'from_slot', 'to_slot', 'state', 'cycle', 'result', 'closed_at')
WAVE_FIELDS = ('size', 'index', 'total', 'closed', 'slots')
BUDGET_FIELDS = ('declared', 'consumed', 'exhausted')
LOOP_FIELDS = ('cycles', 'stop_reason', 'receipts', 'receipts_omitted', 'write_failures', 'lease')
MEMBER_ID_RE = re.compile(MEMBER_ID_PATTERN)
TERMINAL_MEMBER_STATES = ('success', 'failed')
OUTCOME_FIELDS = ('state', 'result', 'tokens', 'delegations')

_MISSING = object()


class TeamProcessError(ValueError):
    """Error tipado del motor de proceso. `code` pertenece a `PROCESS_ERROR_CODES`."""

    def __init__(self, code, message):
        super().__init__('%s: %s' % (code, message))
        self.code = code


def _fail(code, message):
    raise TeamProcessError(code, message)


# =========================================================================================
# BLOQUE VERBATIM MG-F1 — corte por presupuesto (M5)
# Fuente: FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f:metagpt/team.py L87-100
# blob 5a9838885070add38a7cdd3ddf034ea40768d4b2 | sha256 del fragmento
# d13e885a69080987ea0d5d541cecb2e1a60ce1c57165eca9a505dbc24083b192 | licencia MIT
# ENMIENDA PERMANENTE - codigo verbatim
#
# Declaracion de cambios (las 14 lineas del fuente, sustituidas SOLO en lo declarado):
#   A1. `self.env.context.cost_manager` -> `self._cost`: aqui el cost manager se inyecta en el
#       constructor y sus campos (`total_cost`, `max_budget`) son los contadores de
#       `BUDGET_DIMENSIONS` de este modulo.
#   A2. `logger.info(f"Investment: ${investment}.")` (L96) se elimina: el modulo no tiene logger,
#       no hace E/S y no escribe nada (contrato C-5). El resto de `invest` es literal.
#   A3. `NoMoneyException(...)` -> `_BudgetExhausted(...)`, con el codigo congelado
#       `budget_exhausted` (contrato §1) y el mensaje del fuente identico.
#   A4. Se anade constructor: en el fuente el cost manager viene del contexto del equipo; aqui se
#       inyecta (techo declarado + consumo observado) para que el predicado sea puro y testeable.
# El predicado L98-100 (`total_cost >= max_budget` => corte, borde exacto incluido) es literal.
# tests_team_verbatim_parity.py comprueba el sha256 del fragmento y que, aplicando SOLO A1-A4,
# las lineas del fuente aparecen en este bloque.
# =========================================================================================

class _BudgetExhausted(TeamProcessError):
    """Equivalente local de `NoMoneyException`: mismo hecho, codigo congelado `budget_exhausted`."""

    def __init__(self, total_cost, message):
        super().__init__('budget_exhausted', message)
        self.total_cost = total_cost


class _CostState:
    """`cost_manager` minimo del fragmento: contadores de `BUDGET_DIMENSIONS` (adaptacion A1)."""

    def __init__(self, max_budget=None, total_cost=0):
        self.max_budget = max_budget
        self.total_cost = total_cost

    def update_cost(self, cost):
        """Acumulacion monotona no decreciente (forma del test del fuente `test_cost_manager.py`)."""
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            _fail('invalid_budget', 'update_cost admite numeros >= 0.')
        self.total_cost = round(self.total_cost + float(cost), 6)
        return self.total_cost


class _BudgetBalance:
    """Corte por presupuesto del fuente, con las adaptaciones declaradas A1-A4.

    Fuente: FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f:metagpt/team.py
    L87-100 (MIT). `ENMIENDA PERMANENTE - codigo verbatim`.
    """

    def __init__(self, max_budget=None, total_cost=0):
        self.investment = None
        self._cost = _CostState(max_budget=max_budget, total_cost=total_cost)

    @property
    def cost_manager(self):
        """Get cost manager"""
        return self._cost

    def invest(self, investment: float):
        """Invest company. raise NoMoneyException when exceed max_budget."""
        self.investment = investment
        self.cost_manager.max_budget = investment

    def _check_balance(self):
        if self.cost_manager.total_cost >= self.cost_manager.max_budget:
            raise _BudgetExhausted(self.cost_manager.total_cost, f"Insufficient funds: {self.cost_manager.max_budget}")

    def is_exhausted(self):
        """Predicado booleano del fragmento (`_check_balance` sin lanzar). No sustituye al original."""
        try:
            self._check_balance()
        except _BudgetExhausted:
            return True
        except TypeError:  # techo no declarado (`max_budget is None`): sin corte
            return False
        return False


# ===== FIN BLOQUE VERBATIM MG-F1 =====


def _is_sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _jsonable(value, name, code='invalid_outcome'):
    try:
        json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        _fail(code, '%s no es serializable a JSON (%s).' % (name, type(error).__name__))
    return value


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _stamp(moment):
    return datetime.fromtimestamp(moment, timezone.utc).isoformat().replace('+00:00', 'Z')


def _epoch_of(stamp):
    """Epoch de una marca UTC. Acepta la forma del repo con y sin microsegundos (isoformat los omite si son 0)."""
    text = stamp[:-1] if isinstance(stamp, str) and stamp.endswith('Z') else stamp
    for pattern in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def _clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _require_exact_keys(entry, fields, label):
    if not isinstance(entry, Mapping):
        _fail('checkpoint_shape_invalid', '%s debe ser un objeto.' % label)
    missing = [field for field in fields if field not in entry]
    unknown = sorted(str(field) for field in entry if field not in fields)
    if missing or unknown:
        _fail('checkpoint_shape_invalid', '%s con claves fuera del esquema (faltan=%s, sobran=%s).'
              % (label, missing, unknown))


@dataclass(frozen=True)
class _Unit:
    """Unidad de trabajo seleccionada: slots pendientes, ola (si aplica) y delegaciones implicadas."""

    slots: tuple
    wave: int | None = None
    delegations: tuple = ()


class TeamProcess:
    """Motor de proceso por pasos con checkpoint durable. Ver `docs/rea/TEAM_API_CONTRACT_v1.md`."""

    def __init__(self, roster, mode='sequential', clock=None, budget=None, wave_size=None,
                 worker=None, coordinator_slot=None):
        self._clock = self._validated_clock(clock)
        self._worker = self._validated_worker(worker)
        if mode not in MODES:
            _fail('unknown_mode', 'mode debe ser uno de %s; recibido %r.' % (', '.join(MODES), mode))
        self._mode = mode
        self._roster = self._validated_roster(roster)
        self._slots = tuple(member['slot'] for member in self._roster)
        self._members_by_slot = {member['slot']: member for member in self._roster}
        self._coordinator_slot = self._validated_coordinator(coordinator_slot)
        self._wave_size = self._validated_wave_size(wave_size)
        self._budget_declared = self._validated_budget(budget)
        self._budget_consumed = {'steps': 0, 'seconds': 0.0, 'delegations': 0, 'tokens': 0}
        self._budget_exhausted = None
        self._cycle = 0
        self._step = 0
        self._steps_total = 0
        self._cycle_state = 'not_run'
        self._resumptions = 0
        self._members = {slot: {'state': 'pending', 'steps': 0} for slot in self._slots}
        self._results = {}
        self._delegations = []
        self._waves = None
        self._created_at = _stamp(self._now())
        self._updated_at = self._created_at

    # ------------------------------------------------------------------ construccion / validacion

    @staticmethod
    def _validated_clock(clock):
        if clock is None:
            return time.time
        if not callable(clock):
            _fail('invalid_clock', 'clock debe ser un callable sin argumentos que devuelva segundos epoch.')
        return clock

    @staticmethod
    def _validated_worker(worker):
        if worker is None:
            return None
        if not callable(worker):
            _fail('invalid_worker', 'worker debe ser un callable (request) -> Mapping.')
        return worker

    @staticmethod
    def _validated_roster(roster):
        if not _is_sequence(roster) or not roster:
            _fail('invalid_roster', 'roster debe ser una secuencia no vacia de miembros.')
        if len(roster) > MAX_MEMBERS:
            _fail('invalid_roster', 'roster admite como maximo %d miembros.' % MAX_MEMBERS)
        normalized = []
        seen_slots = set()
        seen_ids = set()
        coordinators = 0
        for member in roster:
            if not isinstance(member, Mapping):
                _fail('invalid_roster', 'cada miembro debe ser un Mapping.')
            unknown = sorted(str(key) for key in member if key not in ROSTER_FIELDS)
            if unknown:
                _fail('invalid_roster', 'campos no declarados en el roster: %s.' % ', '.join(unknown))
            slot = member.get('slot', _MISSING)
            if isinstance(slot, bool) or type(slot) is not int or not 1 <= slot <= MAX_MEMBERS:
                _fail('invalid_roster', 'slot debe ser entero 1..%d.' % MAX_MEMBERS)
            if slot in seen_slots:
                _fail('invalid_roster', 'slot %d repetido.' % slot)
            member_id = member.get('member_id', _MISSING)
            if not isinstance(member_id, str) or not MEMBER_ID_RE.match(member_id):
                _fail('invalid_roster', 'member_id debe cumplir %s.' % MEMBER_ID_PATTERN)
            if member_id in seen_ids:
                _fail('invalid_roster', 'member_id %r repetido.' % member_id)
            role = member.get('role', _MISSING)
            if not isinstance(role, str) or not 1 <= len(role) <= 120:
                _fail('invalid_roster', 'role debe ser texto de 1..120 caracteres.')
            is_coordinator = member.get('is_coordinator', False)
            if not isinstance(is_coordinator, bool):
                _fail('invalid_roster', 'is_coordinator debe ser booleano.')
            if is_coordinator:
                coordinators += 1
            delegates_to = member.get('delegates_to', ())
            if not _is_sequence(delegates_to):
                _fail('invalid_roster', 'delegates_to debe ser una secuencia de slots.')
            targets = []
            for target in delegates_to:
                if isinstance(target, bool) or type(target) is not int or not 1 <= target <= MAX_MEMBERS:
                    _fail('invalid_roster', 'delegates_to admite slots 1..%d.' % MAX_MEMBERS)
                if target in targets:
                    _fail('invalid_roster', 'delegates_to repite el slot %d.' % target)
                targets.append(target)
            normalized.append({'slot': slot, 'member_id': member_id, 'role': role,
                               'is_coordinator': is_coordinator, 'delegates_to': tuple(targets)})
            seen_slots.add(slot)
            seen_ids.add(member_id)
        if coordinators > 1:
            _fail('invalid_roster', 'solo un miembro puede declararse coordinador (%d declarados).' % coordinators)
        normalized.sort(key=lambda member: member['slot'])
        return tuple(normalized)

    def _validated_coordinator(self, coordinator_slot):
        if self._mode != 'hierarchical':
            if coordinator_slot is not None:
                _fail('invalid_roster', 'coordinator_slot solo aplica al modo hierarchical.')
            return None
        declared = [member['slot'] for member in self._roster if member['is_coordinator']]
        if coordinator_slot is None:
            slot = declared[0] if declared else self._slots[0]
        else:
            if isinstance(coordinator_slot, bool) or type(coordinator_slot) is not int:
                _fail('invalid_roster', 'coordinator_slot debe ser un entero.')
            slot = coordinator_slot
        if slot not in self._members_by_slot:
            _fail('unknown_member', 'coordinator_slot %r no existe en el roster declarado %s.'
                  % (slot, list(self._slots)))
        if declared and declared[0] != slot:
            _fail('invalid_roster', 'coordinator_slot contradice is_coordinator del roster.')
        return slot

    def _validated_wave_size(self, wave_size):
        if self._mode != 'parallel_waves':
            if wave_size is not None:
                _fail('invalid_wave_size', 'wave_size solo aplica al modo parallel_waves.')
            return None
        size = DEFAULT_WAVE_SIZE if wave_size is None else wave_size
        if isinstance(size, bool) or type(size) is not int or not 1 <= size <= MAX_WAVE_SIZE:
            _fail('invalid_wave_size', 'wave_size debe ser entero 1..%d; recibido %r.'
                  % (MAX_WAVE_SIZE, wave_size))
        return size

    @staticmethod
    def _validated_budget(budget):
        declared = {dimension: None for dimension in BUDGET_DIMENSIONS}
        if budget is None:
            return declared
        if not isinstance(budget, Mapping):
            _fail('invalid_budget', 'budget debe ser un Mapping con dimensiones %s.' % ', '.join(BUDGET_DIMENSIONS))
        unknown = sorted(str(key) for key in budget if key not in BUDGET_DIMENSIONS)
        if unknown:
            _fail('invalid_budget', 'dimensiones de presupuesto no declaradas: %s.' % ', '.join(unknown))
        for dimension in BUDGET_DIMENSIONS:
            value = budget.get(dimension, None)
            if value is None:
                declared[dimension] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _fail('invalid_budget', 'budget.%s debe ser numerico o None; recibido %r.' % (dimension, value))
            if not math.isfinite(float(value)):
                _fail('invalid_budget', 'budget.%s debe ser finito.' % dimension)
            if value < 0:
                _fail('invalid_budget', 'budget.%s no admite valores negativos.' % dimension)
            if dimension == 'seconds':
                declared[dimension] = float(value)
            else:
                if float(value) != int(value):
                    _fail('invalid_budget', 'budget.%s debe ser entero.' % dimension)
                declared[dimension] = int(value)
        return declared

    # ------------------------------------------------------------------ utilidades internas

    def _now(self):
        moment = self._clock()
        if isinstance(moment, bool) or not isinstance(moment, (int, float)) or not math.isfinite(float(moment)):
            _fail('invalid_clock', 'clock debe devolver segundos epoch numericos.')
        return float(moment)

    def _touch(self, moment, elapsed=0.0):
        if elapsed > 0:
            self._budget_consumed['seconds'] = round(self._budget_consumed['seconds'] + elapsed, 6)
        self._updated_at = _stamp(moment)

    def _elapsed_since_update(self, moment):
        previous = _epoch_of(self._updated_at)
        if previous is None:
            return 0.0
        return max(0.0, moment - previous)

    def _open_cycle(self):
        self._cycle += 1
        self._step = 0
        self._cycle_state = 'running'
        self._budget_exhausted = None
        for slot in self._slots:
            self._members[slot] = {'state': 'pending', 'steps': self._members[slot]['steps']}
        if self._mode == 'parallel_waves':
            partitions = [list(self._slots[index:index + self._wave_size])
                          for index in range(0, len(self._slots), self._wave_size)]
            self._waves = {'size': self._wave_size, 'index': 0, 'total': len(partitions),
                           'closed': 0, 'slots': partitions}
        else:
            self._waves = None

    def _open_delegations(self):
        return [record for record in self._delegations
                if record['state'] == 'open' and record['cycle'] == self._cycle]

    def _wave_pending(self):
        if self._waves is None or self._waves['index'] >= self._waves['total']:
            return ()
        return tuple(slot for slot in self._waves['slots'][self._waves['index']]
                     if self._members[slot]['state'] == 'pending')

    def _next_unit(self):
        """Unidad siguiente en orden canonico, sin mutar el estado."""
        if self._cycle_state != 'running':
            return None
        if self._mode == 'sequential':
            for slot in self._slots:
                if self._members[slot]['state'] == 'pending':
                    return _Unit(slots=(slot,))
            return None
        if self._mode == 'parallel_waves':
            pending = self._wave_pending()
            return _Unit(slots=pending, wave=self._waves['index']) if pending else None
        coordinator = self._coordinator_slot
        if self._members[coordinator]['state'] == 'pending':
            return _Unit(slots=(coordinator,))
        actionable = [record for record in self._open_delegations()
                      if self._members[record['to_slot']]['state'] == 'pending']
        if actionable:
            actionable.sort(key=lambda record: record['to_slot'])
            return _Unit(slots=tuple(record['to_slot'] for record in actionable),
                         delegations=tuple(record['delegation_id'] for record in actionable))
        return None

    def _cycle_complete(self):
        if self._mode == 'sequential':
            return all(self._members[slot]['state'] in TERMINAL_MEMBER_STATES for slot in self._slots)
        if self._mode == 'parallel_waves':
            return self._waves is not None and self._waves['index'] >= self._waves['total']
        coordinator = self._coordinator_slot
        return (self._members[coordinator]['state'] in TERMINAL_MEMBER_STATES
                and not self._open_delegations())

    def _mark_skipped(self):
        for slot in self._slots:
            if self._members[slot]['state'] == 'pending':
                self._members[slot]['state'] = 'skipped'

    def _close_cycle(self):
        self._cycle_state = 'completed' if self._cycle_complete() else 'incomplete'

    def _ceiling_for(self, dimension, cost):
        declared = self._budget_declared[dimension]
        if declared is None:
            return False
        return self._budget_consumed[dimension] + cost > declared

    def _first_ceiling_hit(self, steps_cost=1, delegations_cost=0, tokens_cost=0):
        for dimension, cost in (('steps', steps_cost), ('seconds', 0.0),
                                ('delegations', delegations_cost), ('tokens', tokens_cost)):
            if dimension == 'seconds':
                declared = self._budget_declared['seconds']
                if declared is not None and self._budget_consumed['seconds'] >= declared:
                    return 'seconds'
                continue
            if self._ceiling_for(dimension, cost):
                return dimension
        return None

    def _balance_exhausted(self):
        """Corte en el borde exacto con el predicado verbatim MG-F1 (consumo **alcanza** el techo).

        Complementa a `_first_ceiling_hit` (que evita pasarse al aplicar la siguiente unidad): este
        es el corte del fuente, `total_cost >= max_budget`, evaluado tras consumir la unidad.
        """
        for dimension in BUDGET_DIMENSIONS:
            declared = self._budget_declared[dimension]
            if declared is None:
                continue
            balance = _BudgetBalance(max_budget=declared,
                                     total_cost=self._budget_consumed[dimension])
            if balance.is_exhausted():
                return dimension
        return None

    def _exhaust(self, reason):
        self._budget_exhausted = {'reason': reason}
        self._mark_skipped()
        self._cycle_state = 'budget_exhausted'

    # ------------------------------------------------------------------ outcomes

    def _normalize_outcomes(self, payload):
        """Normaliza la respuesta del worker / `outcome` a {slot: outcome}. El orden de insercion es irrelevante."""
        if payload is None:
            _fail('invalid_outcome', 'outcome no puede ser nulo cuando el llamador lo aporta.')
        if not isinstance(payload, Mapping):
            _fail('invalid_outcome', 'outcome debe ser un Mapping slot -> outcome o {"outcomes": [...]}.')
        raw = {}
        if 'outcomes' in payload:
            if set(payload) != {'outcomes'}:
                _fail('invalid_outcome', 'junto a "outcomes" no se admiten otras claves.')
            entries = payload['outcomes']
            if not _is_sequence(entries):
                _fail('invalid_outcome', '"outcomes" debe ser una secuencia.')
            for entry in entries:
                if not isinstance(entry, Mapping) or 'slot' not in entry:
                    _fail('invalid_outcome', 'cada entrada de "outcomes" necesita slot y state.')
                raw[entry['slot']] = {key: value for key, value in entry.items() if key != 'slot'}
        elif 'state' in payload and set(payload) <= set(OUTCOME_FIELDS + ('slot',)):
            if 'slot' in payload:
                raw[payload['slot']] = {key: value for key, value in payload.items() if key != 'slot'}
            else:
                raw[None] = dict(payload)
        else:
            for key, value in payload.items():
                if isinstance(key, bool) or not isinstance(key, int):
                    try:
                        key = int(str(key))
                    except (TypeError, ValueError):
                        _fail('invalid_outcome', 'las claves del outcome deben ser slots enteros.')
                raw[key] = value
        normalized = {}
        for slot, value in raw.items():
            if not isinstance(value, Mapping):
                _fail('invalid_outcome', 'cada outcome debe ser un Mapping con state y result.')
            unknown = sorted(str(key) for key in value if key not in OUTCOME_FIELDS)
            if unknown:
                _fail('invalid_outcome', 'campos no declarados en el outcome: %s.' % ', '.join(unknown))
            state = value.get('state', _MISSING)
            if state not in TERMINAL_MEMBER_STATES:
                _fail('invalid_outcome', 'outcome.state debe ser success o failed; recibido %r.' % (state,))
            result = value.get('result', None)
            _jsonable(result, 'outcome.result')
            tokens = value.get('tokens', 0)
            if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
                _fail('invalid_outcome', 'outcome.tokens debe ser entero >= 0.')
            delegations = value.get('delegations', ())
            if not _is_sequence(delegations):
                _fail('invalid_outcome', 'outcome.delegations debe ser una secuencia de slots.')
            normalized[slot] = {'state': state, 'result': result, 'tokens': tokens,
                                'delegations': tuple(delegations)}
        return normalized

    def _resolve_single_slot(self, outcomes, requested):
        if None in outcomes:
            if len(requested) != 1:
                _fail('invalid_outcome', 'un outcome sin slot solo se admite cuando la unidad pide un slot.')
            outcomes = {requested[0]: outcomes[None]}
        validated = {}
        for slot, value in outcomes.items():
            if slot not in self._members_by_slot:
                _fail('unknown_member', 'el outcome apunta al slot %r, que no existe en el roster %s.'
                      % (slot, list(self._slots)))
            if slot not in requested:
                _fail('invalid_outcome', 'el slot %s no estaba solicitado en esta unidad (%s).'
                      % (slot, list(requested)))
            validated[slot] = value
        if not validated:
            _fail('invalid_outcome', 'el outcome no resolvio ninguna unidad solicitada (%s).' % list(requested))
        return validated

    def _validate_delegation_targets(self, from_slot, targets):
        """Valida destinos ANTES de mutar nada: un destino invalido no deja estado a medias (AV-10)."""
        existing = {record['to_slot'] for record in self._open_delegations()}
        allowed = self._members_by_slot[from_slot]['delegates_to']
        for target in targets:
            if isinstance(target, bool) or type(target) is not int or target not in self._members_by_slot:
                _fail('unknown_member', 'delegacion al slot %r: no existe en el roster declarado %s.'
                      % (target, list(self._slots)))
            if target == from_slot:
                _fail('unknown_member', 'el coordinador no puede delegarse a si mismo (slot %d).' % from_slot)
            if allowed and target not in allowed:
                _fail('unknown_member', 'delegacion al slot %d no permitida por delegates_to %s del slot %d.'
                      % (target, list(allowed), from_slot))
            if target in existing:
                _fail('invalid_outcome', 'delegacion abierta duplicada al slot %d.' % target)

    def _register_delegations(self, from_slot, targets, moment):
        self._validate_delegation_targets(from_slot, targets)
        existing = {record['to_slot'] for record in self._open_delegations()}
        counter = sum(1 for record in self._delegations if record['cycle'] == self._cycle
                      and record['from_slot'] == from_slot)
        for target in targets:
            if self._first_ceiling_hit(steps_cost=0, delegations_cost=1) == 'delegations':
                return False
            counter += 1
            self._delegations.append({'delegation_id': '%d:%d:%d:%d' % (self._cycle, from_slot, target, counter),
                                      'from_slot': from_slot, 'to_slot': target, 'state': 'open',
                                      'cycle': self._cycle, 'result': None, 'closed_at': None})
            existing.add(target)
            self._budget_consumed['delegations'] += 1
        return True

    def _apply_outcomes(self, outcomes, unit, moment):
        applied = []
        for slot in sorted(outcomes):
            value = outcomes[slot]
            if value['delegations'] and slot != self._coordinator_slot:
                _fail('invalid_outcome', 'el slot %s no puede subdelegar: la profundidad maxima declarada es '
                                         '%d y solo el coordinador delega.' % (slot, MAX_DELEGATION_DEPTH))
            if self._mode == 'hierarchical' and slot == self._coordinator_slot and value['delegations']:
                self._validate_delegation_targets(slot, value['delegations'])
            reason = self._first_ceiling_hit(steps_cost=1, tokens_cost=value['tokens'])
            if reason is not None:
                self._exhaust(reason)
                break
            self._members[slot]['state'] = value['state']
            self._members[slot]['steps'] += 1
            self._step += 1
            self._steps_total += 1
            self._budget_consumed['steps'] += 1
            self._budget_consumed['tokens'] += value['tokens']
            self._results[slot] = {'slot': slot, 'state': value['state'], 'result': value['result'],
                                   'cycle': self._cycle, 'step': self._step}
            for record in self._open_delegations():
                if record['to_slot'] == slot:
                    record['state'] = 'closed'
                    record['result'] = value['result']
                    record['closed_at'] = _stamp(moment)
            applied.append(slot)
            if self._mode == 'hierarchical' and slot == self._coordinator_slot and value['delegations']:
                if not self._register_delegations(slot, value['delegations'], moment):
                    self._exhaust('delegations')
                    break
        if self._mode == 'parallel_waves' and self._waves is not None:
            while self._waves['index'] < self._waves['total']:
                current = self._waves['slots'][self._waves['index']]
                if any(self._members[slot]['state'] == 'pending' for slot in current):
                    break
                self._waves['closed'] += 1
                self._waves['index'] += 1
        if self._cycle_state == 'running' and self._cycle_complete():
            self._cycle_state = 'completed'
        return applied

    def _request(self, unit):
        return {'mode': self._mode, 'cycle': self._cycle, 'step': self._step, 'wave': unit.wave,
                'slots': unit.slots,
                'members': [{'slot': slot, 'member_id': self._members_by_slot[slot]['member_id'],
                             'role': self._members_by_slot[slot]['role']} for slot in unit.slots],
                'delegations': [{'delegation_id': record['delegation_id'], 'from_slot': record['from_slot'],
                                 'to_slot': record['to_slot']} for record in self._open_delegations()
                                if record['to_slot'] in unit.slots]}

    def _step_report(self, advanced, applied, unit):
        return {'advanced': bool(advanced), 'slots': tuple(applied), 'cycle': self._cycle, 'step': self._step,
                'cycle_state': self._cycle_state,
                'exhausted': None if self._budget_exhausted is None else dict(self._budget_exhausted),
                'open_delegations': tuple(sorted(record['to_slot'] for record in self._open_delegations())),
                'wave': None if unit is None else unit.wave}

    # ------------------------------------------------------------------ API publica

    def step(self, outcome=None):
        """Avanza una unidad de trabajo. Ver contrato §2.3 (`step`)."""
        if self._cycle_state not in ('not_run', 'running'):
            _fail('cycle_closed', 'el ciclo %d ya cerro (%s): un ciclo cerrado no se reabre; abrir el '
                                  'siguiente es competencia de run().' % (self._cycle, self._cycle_state))
        if self._cycle_state == 'not_run':
            self._open_cycle()
        moment = self._now()
        elapsed = self._elapsed_since_update(moment)
        if outcome is None and self._worker is None:
            _fail('worker_required', 'sin worker inyectado, step() necesita un outcome del llamador.')
        unit = self._next_unit()
        if unit is None:
            self._touch(moment, elapsed)
            self._close_cycle()
            return self._step_report(False, (), None)
        reason = self._first_ceiling_hit()
        if reason is not None:
            self._touch(moment, elapsed)
            self._exhaust(reason)
            return self._step_report(False, (), unit)
        payload = self._worker(self._request(unit)) if outcome is None else outcome
        validated = self._resolve_single_slot(self._normalize_outcomes(payload), unit.slots)
        applied = self._apply_outcomes(validated, unit, moment)
        self._touch(moment, elapsed)
        boundary = self._balance_exhausted() if applied else None
        if boundary is not None and self._cycle_state == 'running':
            self._exhaust(boundary)
        elif self._cycle_state == 'running' and not self._next_unit():
            self._close_cycle()
        return self._step_report(bool(applied), applied, unit)

    def run(self, limit=None):
        """Avanza hasta cerrar el ciclo, hasta `limit` unidades o hasta un techo. Ver contrato §2.3."""
        if limit is not None and (isinstance(limit, bool) or type(limit) is not int or limit < 1):
            _fail('invalid_limit', 'limit debe ser None o entero >= 1; recibido %r.' % (limit,))
        if self._worker is None:
            _fail('worker_required', 'run() requiere el worker del constructor; usa step(outcome) para '
                                     'conducir manualmente.')
        if self._cycle_state != 'running':
            self._open_cycle()
        start_steps = self._steps_total
        units = 0
        while self._cycle_state == 'running':
            if limit is not None and units >= limit:
                break
            units += 1
            if units > MAX_UNITS_PER_RUN:
                _fail('invalid_outcome', 'el ciclo no avanzo en %d unidades; revisa el worker.'
                      % MAX_UNITS_PER_RUN)
            report = self.step()
            if not report['advanced'] and self._cycle_state == 'running':
                _fail('invalid_outcome', 'el worker no resolvio la unidad solicitada (%s).'
                      % list(report['slots'] or ()))
        moment = self._now()
        self._touch(moment)
        motive = self._cycle_state if self._cycle_state in ('completed', 'incomplete', 'budget_exhausted') \
            else 'incomplete'
        receipt = {'receipt_version': RECEIPT_VERSION, 'cycle': self._cycle, 'mode': self._mode,
                   'steps_advanced': self._steps_total - start_steps,
                   'budget_consumed': dict(self._budget_consumed), 'motive': motive, 'at': _stamp(moment)}
        return {'cycle': self._cycle, 'mode': self._mode, 'steps_advanced': self._steps_total - start_steps,
                'cycle_state': self._cycle_state, 'budget_consumed': dict(self._budget_consumed),
                'exhausted': None if self._budget_exhausted is None else dict(self._budget_exhausted),
                'open_delegations': tuple(sorted(record['to_slot'] for record in self._open_delegations())),
                'receipt': receipt}

    def status(self):
        """Estado visible (copia). Ver contrato §2.3 (`status`)."""
        unit = self._next_unit()
        remaining = {}
        for dimension in BUDGET_DIMENSIONS:
            declared = self._budget_declared[dimension]
            remaining[dimension] = (None if declared is None
                                    else max(round(declared - self._budget_consumed[dimension], 6), 0))
        return {'schema': PROCESS_SCHEMA, 'mode': self._mode, 'cycle': self._cycle, 'step': self._step,
                'steps_total': self._steps_total, 'cycle_state': self._cycle_state,
                'resumptions': self._resumptions, 'coordinator_slot': self._coordinator_slot,
                'roster': [dict(member, delegates_to=list(member['delegates_to'])) for member in self._roster],
                'members': [{'slot': slot, 'member_id': self._members_by_slot[slot]['member_id'],
                             'state': self._members[slot]['state'], 'steps': self._members[slot]['steps']}
                            for slot in self._slots],
                'results': [dict(self._results[slot]) for slot in sorted(self._results)],
                'delegations': _clone(sorted((dict(record) for record in self._delegations),
                                             key=lambda record: (record['cycle'], record['delegation_id']))),
                'waves': None if self._waves is None else _clone(self._waves),
                'next_slots': () if unit is None else tuple(unit.slots),
                'budget': {'declared': dict(self._budget_declared), 'consumed': dict(self._budget_consumed),
                           'remaining': remaining,
                           'exhausted': None if self._budget_exhausted is None else dict(self._budget_exhausted)}}

    def export_checkpoint(self):
        """Checkpoint v1 (dict JSON-serializable). Ver contrato §4."""
        checkpoint = {'checkpoint_version': CHECKPOINT_VERSION, 'schema': CHECKPOINT_SCHEMA,
                      'mode': self._mode, 'coordinator_slot': self._coordinator_slot,
                      'roster': [dict(member, delegates_to=list(member['delegates_to']))
                                 for member in self._roster],
                      'cycle': self._cycle, 'step': self._step, 'steps_total': self._steps_total,
                      'cycle_state': self._cycle_state, 'resumptions': self._resumptions,
                      'members': [{'slot': slot, 'state': self._members[slot]['state'],
                                   'steps': self._members[slot]['steps']} for slot in self._slots],
                      'results': [dict(self._results[slot]) for slot in sorted(self._results)],
                      'delegations': _clone(sorted((dict(record) for record in self._delegations),
                                                   key=lambda record: (record['cycle'], record['delegation_id']))),
                      'waves': None if self._waves is None else _clone(self._waves),
                      'budget': {'declared': dict(self._budget_declared),
                                 'consumed': dict(self._budget_consumed),
                                 'exhausted': None if self._budget_exhausted is None
                                 else dict(self._budget_exhausted)},
                      'loop': None, 'created_at': self._created_at, 'updated_at': self._updated_at}
        _jsonable(checkpoint, 'checkpoint', code='checkpoint_shape_invalid')
        return checkpoint

    @staticmethod
    def checkpoint_digest(checkpoint):
        """sha256 del JSON canonico del checkpoint (no se almacena dentro de el). Ver contrato §4.4."""
        if not isinstance(checkpoint, Mapping):
            _fail('checkpoint_shape_invalid', 'checkpoint debe ser un Mapping.')
        try:
            return hashlib.sha256(_canonical_bytes(checkpoint)).hexdigest()
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            _fail('checkpoint_shape_invalid', 'checkpoint no canonicalizable (%s).' % type(error).__name__)

    def import_checkpoint(self, checkpoint):
        """Rehidrata el estado desde un checkpoint v1. Ver contrato §4.3/§2.3."""
        self._validate_checkpoint(checkpoint)
        if checkpoint['mode'] != self._mode:
            _fail('checkpoint_mismatch', 'el checkpoint declara modo %r y el proceso es %r.'
                  % (checkpoint['mode'], self._mode))
        checkpoint_roster = [(member['slot'], member['member_id']) for member in checkpoint['roster']]
        own_roster = [(member['slot'], member['member_id']) for member in self._roster]
        if checkpoint_roster != own_roster:
            _fail('checkpoint_mismatch', 'el roster del checkpoint no coincide con el del proceso.')
        self._cycle = checkpoint['cycle']
        self._step = checkpoint['step']
        self._steps_total = checkpoint['steps_total']
        self._cycle_state = checkpoint['cycle_state']
        self._resumptions = checkpoint['resumptions'] + 1
        self._members = {entry['slot']: {'state': entry['state'], 'steps': entry['steps']}
                         for entry in checkpoint['members']}
        self._results = {entry['slot']: dict(entry) for entry in checkpoint['results']}
        self._delegations = [dict(record) for record in checkpoint['delegations']]
        self._waves = None if checkpoint['waves'] is None else _clone(checkpoint['waves'])
        self._budget_consumed = dict(checkpoint['budget']['consumed'])
        self._budget_exhausted = (None if checkpoint['budget']['exhausted'] is None
                                  else dict(checkpoint['budget']['exhausted']))
        self._created_at = checkpoint['created_at']
        self._updated_at = checkpoint['updated_at']
        return self.status()

    @classmethod
    def from_checkpoint(cls, checkpoint, *, clock=None, worker=None, budget=None):
        """Construye un proceso desde un checkpoint v1 sin conocer previamente roster ni modo."""
        cls._validate_checkpoint(checkpoint)
        wave_size = None
        if checkpoint['mode'] == 'parallel_waves':
            if checkpoint['waves'] is None:
                _fail('checkpoint_shape_invalid', 'parallel_waves exige bloque waves no nulo.')
            wave_size = checkpoint['waves']['size']
        declared = budget if budget is not None else checkpoint['budget']['declared']
        process = cls(checkpoint['roster'], mode=checkpoint['mode'], clock=clock, budget=declared,
                      wave_size=wave_size, worker=worker,
                      coordinator_slot=(checkpoint['coordinator_slot']
                                        if checkpoint['mode'] == 'hierarchical' else None))
        process.import_checkpoint(checkpoint)
        return process

    # ------------------------------------------------------------------ validacion de checkpoint

    @staticmethod
    def _validate_checkpoint(checkpoint):
        if not isinstance(checkpoint, Mapping):
            _fail('checkpoint_shape_invalid', 'checkpoint debe ser un Mapping.')
        version = checkpoint.get('checkpoint_version', _MISSING)
        schema = checkpoint.get('schema', _MISSING)
        if version != CHECKPOINT_VERSION or schema != CHECKPOINT_SCHEMA:
            _fail('unsupported_checkpoint_version',
                  'se acepta solo checkpoint_version=%d con schema %r (versiones conocidas [%d]); recibido '
                  'version=%r schema=%r. No se degrada ni se reescribe.'
                  % (CHECKPOINT_VERSION, CHECKPOINT_SCHEMA, CHECKPOINT_VERSION, version, schema))
        missing = [field for field in CHECKPOINT_FIELDS if field not in checkpoint]
        unknown = sorted(str(field) for field in checkpoint if field not in CHECKPOINT_FIELDS)
        if missing or unknown:
            _fail('checkpoint_shape_invalid', 'claves del checkpoint fuera del esquema v1 '
                                              '(faltan=%s, sobran=%s).' % (missing, unknown))
        if checkpoint['mode'] not in MODES:
            _fail('checkpoint_shape_invalid', 'mode del checkpoint fuera del vocabulario.')
        for field in ('cycle', 'step', 'steps_total', 'resumptions'):
            value = checkpoint[field]
            if isinstance(value, bool) or type(value) is not int or value < 0:
                _fail('checkpoint_shape_invalid', '%s debe ser entero >= 0.' % field)
        if checkpoint['cycle_state'] not in CYCLE_STATES:
            _fail('checkpoint_shape_invalid', 'cycle_state del checkpoint fuera del vocabulario.')
        coordinator = checkpoint['coordinator_slot']
        if coordinator is not None and (isinstance(coordinator, bool) or type(coordinator) is not int):
            _fail('checkpoint_shape_invalid', 'coordinator_slot debe ser entero o null.')
        _validate_checkpoint_body(checkpoint)


def _validate_checkpoint_body(checkpoint):
    """Validacion estructural pura del checkpoint v1 (fail-closed) y de su coherencia con el roster."""
    roster = checkpoint['roster']
    if not _is_sequence(roster) or not roster:
        _fail('checkpoint_shape_invalid', 'roster del checkpoint debe ser una secuencia no vacia.')
    for member in roster:
        _require_exact_keys(member, ROSTER_FIELDS, 'roster')
    slots = [member['slot'] for member in roster]
    if len(set(slots)) != len(slots):
        _fail('checkpoint_shape_invalid', 'roster del checkpoint repite slots.')
    members = checkpoint['members']
    if not _is_sequence(members) or sorted(entry['slot'] for entry in members) != sorted(slots):
        _fail('checkpoint_shape_invalid', 'members del checkpoint debe cubrir el roster completo.')
    for entry in members:
        _require_exact_keys(entry, MEMBER_FIELDS, 'members')
        if entry['state'] not in MEMBER_STATES:
            _fail('checkpoint_shape_invalid', 'members.state fuera del vocabulario.')
        if isinstance(entry['steps'], bool) or type(entry['steps']) is not int or entry['steps'] < 0:
            _fail('checkpoint_shape_invalid', 'members.steps debe ser entero >= 0.')
    for entry in checkpoint['results']:
        _require_exact_keys(entry, RESULT_FIELDS, 'results')
        if entry['state'] not in TERMINAL_MEMBER_STATES:
            _fail('checkpoint_shape_invalid', 'results.state fuera del vocabulario.')
        if entry['slot'] not in slots:
            _fail('checkpoint_shape_invalid', 'results apunta a un slot fuera del roster.')
    for record in checkpoint['delegations']:
        _require_exact_keys(record, DELEGATION_FIELDS, 'delegations')
        if record['state'] not in DELEGATION_STATES:
            _fail('checkpoint_shape_invalid', 'delegations.state fuera del vocabulario.')
        if record['from_slot'] not in slots or record['to_slot'] not in slots:
            _fail('checkpoint_shape_invalid', 'delegations apunta a slots fuera del roster.')
    waves = checkpoint['waves']
    if waves is not None:
        _require_exact_keys(waves, WAVE_FIELDS, 'waves')
        if not _is_sequence(waves['slots']) or not waves['slots']:
            _fail('checkpoint_shape_invalid', 'waves.slots debe ser una secuencia no vacia.')
        for partition in waves['slots']:
            if not _is_sequence(partition) or any(slot not in slots for slot in partition):
                _fail('checkpoint_shape_invalid', 'waves.slots apunta a slots fuera del roster.')
    budget = checkpoint['budget']
    _require_exact_keys(budget, BUDGET_FIELDS, 'budget')
    for part in ('declared', 'consumed'):
        _require_exact_keys(budget[part], BUDGET_DIMENSIONS, 'budget.' + part)
        for dimension in BUDGET_DIMENSIONS:
            value = budget[part][dimension]
            if value is None and part == 'declared':
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                _fail('checkpoint_shape_invalid', 'budget.%s.%s debe ser numerico >= 0.' % (part, dimension))
    if budget['exhausted'] is not None:
        _require_exact_keys(budget['exhausted'], ('reason',), 'budget.exhausted')
        if budget['exhausted']['reason'] not in EXHAUSTION_REASONS:
            _fail('checkpoint_shape_invalid', 'budget.exhausted.reason fuera del vocabulario.')
    loop = checkpoint['loop']
    if loop is not None:
        _require_exact_keys(loop, LOOP_FIELDS, 'loop')
        if isinstance(loop['cycles'], bool) or type(loop['cycles']) is not int or loop['cycles'] < 0:
            _fail('checkpoint_shape_invalid', 'loop.cycles debe ser entero >= 0.')
        if isinstance(loop['receipts_omitted'], bool) or type(loop['receipts_omitted']) is not int:
            _fail('checkpoint_shape_invalid', 'loop.receipts_omitted debe ser entero.')
        if isinstance(loop['write_failures'], bool) or type(loop['write_failures']) is not int \
                or loop['write_failures'] < 0:
            _fail('checkpoint_shape_invalid', 'loop.write_failures debe ser entero >= 0.')
        if not _is_sequence(loop['receipts']):
            _fail('checkpoint_shape_invalid', 'loop.receipts debe ser una secuencia.')
    for field in ('created_at', 'updated_at'):
        if not isinstance(checkpoint[field], str) or _epoch_of(checkpoint[field]) is None:
            _fail('checkpoint_shape_invalid', '%s debe ser una marca UTC ...Z.' % field)


__all__ = ['TeamProcess', 'TeamProcessError', 'MODES', 'CYCLE_STATES', 'MEMBER_STATES',
           'DELEGATION_STATES', 'BUDGET_DIMENSIONS', 'EXHAUSTION_REASONS', 'CHECKPOINT_VERSION',
           'CHECKPOINT_SCHEMA', 'PROCESS_SCHEMA', 'RECEIPT_VERSION', 'DEFAULT_WAVE_SIZE',
           'MAX_WAVE_SIZE', 'MAX_MEMBERS', 'MAX_DELEGATION_DEPTH', 'MEMBER_ID_PATTERN',
           'PROCESS_ERROR_CODES']
