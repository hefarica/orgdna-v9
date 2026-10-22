"""Bucle continuo acotado del equipo (M2): proceso + compromisos + arriendo + recibo.

DECLARACION DE ORIGEN: el pegamento (ciclos, arriendo, checkpoint, recibo, backoff) es
composicion PROPIA sobre modulos LOCALES de este repositorio. El barrido REA
(`docs/rea/agile_agents_survey.md`, t21) clasifico la continuidad como **M2** (parada explicita y
corte limpio) y `docs/rea/PORT_REPORT.md` no autoriza ningun port de ese pegamento.

Codigo verbatim (ENMIENDA PERMANENTE del operador): el **fragmento AG-F1** de
`ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e:ag2/events/conditions.py` L1-144 (blob
`67b72fc7fd84ad43394df75e515ac05bc73287fc`, licencia **Apache-2.0** con SPDX en el propio fichero)
sustituye los predicados de `stop_decision`: condiciones componibles (`&`, `|`, `~`) para M2. Gate
Tier 2 y vectores: `docs/rea/license_audit.md` y `docs/rea/PORT_REPORT_AGILIDAD.md` (t29).
Autorizado por `docs/security/FUSILE_SOURCE_POLICY.md`. Declaracion de cambios del fragmento en la
cabecera del bloque verbatim; la superficie publica del contrato (§1/§3) **no cambia**.

CONTRATO CONGELADO que este modulo implementa (no lo reinterpreta):
`docs/rea/TEAM_API_CONTRACT_v1.md` (t31) §1 (vocabulario), §3.1 (constructor), §3.2
(`run`/`start`/`stop`/`status`/`history`), §3.3 (recibo), §3.4 (protocolo `store`), §3.5
(protocolo `lease`), §4 (checkpoint v1 y su bloque `loop`), §7.3 (presupuesto del bucle) y
§8 (contrato de reanudacion). Vectores observables: AV-03, AV-05, AV-06, AV-07, AV-17,
AV-20, AV-21, AV-23, AV-24 de `docs/rea/agile_vectors.json` (t21).

COMPOSICION (todo local, nada se modifica):
  * `engine/team_process.py` (t22): el proceso que avanza por pasos. El bucle lo conduce con
    `run()`, lo rehidrata con `import_checkpoint()` y cita su estado con `checkpoint_digest()`.
    **No se toca una linea de `team_process.py`**: `_worker` solo se inyecta cuando el proceso
    no tiene uno, que es exactamente lo que autoriza §3.1.
  * `engine/followups.py`: el persecutor de compromisos. Si el llamador inyecta un motor
    (`followups=`), el bucle dispara **un** `tick()` por ciclo: el tick sigue siendo explicito
    (doctrina `engine/gang_supervisor.py:19-21`), solo que ahora lo dispara el ciclo.
  * `engine/coordination.py`: el almacen de arriendos. `CoordinationLease` es el adaptador
    del protocolo §3.5 sobre `CoordinationStore.apply(...)`; `coordination.py` no se modifica
    y el bucle no abre ningun fichero (la escritura la hace el almacen que el llamador inyecta).
  * `engine/team_channel.py`: canal opcional para publicar el recibo en `LOOP_TOPIC`.

UN CICLO, EN ESTE ORDEN (y nada mas: el bucle NO decide estrategia):
  1. **arriendo** — si hay `lease`, se adquiere o renueva. Si no se consigue, el ciclo NO se
     ejecuta: `stop_reason='lease_held'`, cero avance, cero checkpoint, cero recibo (AV-23).
  2. **reanudacion** — en el primer ciclo se lee el checkpoint mas reciente del `store` y se
     rehidrata el proceso (AV-24), adoptando tambien los contadores del bloque `loop`.
  3. **avance** — `process.run()` hasta cerrar el ciclo, midiendo el reloj inyectado.
  4. **compromisos** — un `tick()` del motor de follow-ups inyectado, si lo hay.
  5. **checkpoint durable** — `export_checkpoint()` + bloque `loop` (con los recibos de ciclo
     confirmados; el del ciclo en curso entra con `checkpoint_digest: null` para no
     autorreferenciarse, §4.4), validado con `json.dumps(..., allow_nan=False)` y entregado al
     `store`. Antes del ciclo se toma una instantanea; si la serializacion o el `store` fallan,
     el proceso se restaura a esa instantanea y el estado durable NO se toca (AV-03).
  6. **recibo** — se registra en `history()` y se publica en el canal, con epoch, motivo y
     contadores.

DEMONIO: **no hay demonio por defecto** (contrato T-12 y C-5: los modulos no crean hilos).
La continuidad se pide con `run(cycles=N)`; `start()`/`stop()` son opt-in e idempotentes y
solo mueven el estado del bucle. Para una continuidad sin limite, `run_until_stopped()` la
conduce desde el hilo que el llamador elija (p. ej. un hilo daemon del llamador), y `stop()`
desde otro hilo es seguro porque solo levanta una bandera y el ciclo en curso termina entero.

BACKOFF: `next_delay(cycle)` es una funcion DETERMINISTA de `(seed, cycle)` (sha256, sin
`random`); el bucle **no duerme** (C-5 y T-10): publica el retardo y, si el llamador inyecta
`sleep` en `run_until_stopped()`, es el llamador quien espera.

DETERMINISMO: reloj inyectable, cero `random`, cero dependencia de orden de `dict`/`set`,
digest sobre JSON canonico, copias en todas las vistas (D1..D8 del contrato).

Que NO hace (declarado): no decide estrategia ni prioriza trabajo, no ejecuta agentes reales,
no usa red ni proveedores, no abre ficheros, no lanza hilos ni subprocesos, no toca DSH y no
persiste nada por si mismo (la persistencia la decide quien inyecta el `store`).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
import time

try:  # importacion como paquete del motor
    from . import team_process as _process
except ImportError:  # raiz de la suite en sys.path
    import team_process as _process

# --- Vocabulario congelado (contrato §1). No se re-tipa ni se amplia sin v2. -------------
LOOP_SCHEMA = 'orgdna.team_loop/1'
LOOP_TOPIC = 'team_loop'
CHECKPOINT_KEY = 'orgdna.team_process.checkpoint'
CHECKPOINT_VERSION = 1
RECEIPT_VERSION = 1
LOOP_STATES = ('not_run', 'running', 'stopped')
STOP_REASONS = ('stop_requested', 'stopped_before_start', 'time_exhausted',
                'budget_exhausted', 'lease_held', 'cycles_completed')
RECEIPT_MOTIVES = ('completed', 'incomplete', 'budget_exhausted', 'time_exhausted',
                   'stop_requested', 'checkpoint_write_failed')
LOOP_BUDGET_DIMENSIONS = ('seconds', 'tokens')
LEASE_EVENTS = ('acquired', 'renewed', 'released', 'lease_held', 'lease_expired')
MAX_CHECKPOINT_RECEIPTS = 256

LOOP_ERROR_CODES = ('invalid_process', 'invalid_channel', 'invalid_store', 'invalid_lease',
                    'invalid_clock', 'invalid_cycles', 'invalid_budget', 'invalid_worker')

# --- Constantes propias de la implementacion (no congeladas) ------------------------------
TEAM_LOOP_TASK = 'team-loop'              # task_id del arriendo en el almacen de coordinacion
TEAM_LOOP_PATHS = ('_team_loop',)          # rutas reservadas (relativas al workspace del store)
DEFAULT_LEASE_TTL = 900                    # coordination.py:246 exige entero 60..3600
DEFAULT_PUBLISH_AS = 'team-loop'
DEFAULT_BACKOFF_BASE_SECS = 0.5            # base del backoff; el jitter lo escala en [1,2)
STOP_REASON_INPUTS = ('stop_requested', 'time_exhausted', 'budget_exhausted')
NULL_SHA = '0' * 64
MAX_STORE_ERROR_CHARS = 160


class TeamLoopError(ValueError):
    """Error tipado del bucle: todo rechazo lleva un `code` de `LOOP_ERROR_CODES`."""

    def __init__(self, code, message):
        super().__init__('%s: %s' % (code, message))
        self.code = code


def _fail(code, message):
    raise TeamLoopError(code, message)


def _is_sequence(value):
    return isinstance(value, (list, tuple))


def _stamp(moment):
    """Marca UTC con la convencion del repo (`team_channel.py:271-272`)."""
    return datetime.fromtimestamp(moment, timezone.utc).isoformat().replace('+00:00', 'Z')


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _encode(checkpoint):
    """Serializacion que valida la durabilidad del checkpoint (seam de la prueba AV-03)."""
    return json.dumps(checkpoint, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _jitter(seed, cycle):
    """Fraccion determinista en [0, 1) derivada de (seed, cycle). Sin `random` (D4)."""
    digest = hashlib.sha256(('orgdna.team_loop/backoff:%d:%d' % (int(seed), int(cycle)))
                            .encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big') / float(1 << 64)


# =========================================================================================
# BLOQUE VERBATIM AG-F1 — condiciones de parada componibles (M2)
# Fuente: ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e:ag2/events/conditions.py L1-144
# blob 67b72fc7fd84ad43394df75e515ac05bc73287fc | sha256 del fragmento
# 01647ee672e18da5a663d42aa022f0c2715c3c5bdf0f2a92316e33ecbb0b22e3 | licencia Apache-2.0
# (SPDX-License-Identifier en la cabecera del fuente, L1-3)
# ENMIENDA PERMANENTE - codigo verbatim
#
# Declaracion de cambios (obligacion Apache-2.0 §4(b)). SOLO se sustituye la cabecera de imports
# del fuente (L5-10) por equivalentes locales sin dependencias, porque el allowlist de imports de
# este modulo esta congelado por `tests_team_loop.py:46-51` y t30 no puede reescribir las pruebas:
#   B1. `import operator` -> shim local `_OperatorShim` con las seis operaciones que usa el
#       fragmento (`ne`, `lt`, `le`, `gt`, `ge`, `is_`), misma semantica; `op_names` sigue
#       apuntando a los mismos objetos de funcion, asi que `__repr__` imprime igual.
#   B2. `from abc import ABC, abstractmethod` -> `abstractmethod` identidad y `ABC` base nominal
#       local. El cuerpo del fuente ya declara `raise NotImplementedError`; lo unico que no se
#       reproduce es el guard de instanciacion de `ABCMeta`, que ningun vector del fuente ejercita.
#   B3. `from collections.abc import Callable` / `from typing import Any` -> sin importar: se usan
#       SOLO en anotaciones, que este modulo difiere (`from __future__ import annotations`), de
#       modo que ninguna ruta de ejecucion las evalua.
#   B4. `from ag2.types import ClassInfo` -> sin importar: igual que B3, solo aparece en la
#       anotacion de `TypeCondition.__init__`.
# Las lineas 11-144 son IDENTICAS al fuente. `tests_team_verbatim_parity.py` comprueba el sha256
# del fragmento completo y que esas 134 lineas aparecen literalmente en este modulo.
# =========================================================================================


class _OperatorShim:
    """Adaptacion declarada B1: subconjunto de `operator` que el fragmento usa, sin importarlo."""

    @staticmethod
    def ne(x, y):
        return x != y

    @staticmethod
    def lt(x, y):
        return x < y

    @staticmethod
    def le(x, y):
        return x <= y

    @staticmethod
    def gt(x, y):
        return x > y

    @staticmethod
    def ge(x, y):
        return x >= y

    @staticmethod
    def is_(x, y):
        return x is y


operator = _OperatorShim  # adaptacion B1


def abstractmethod(method):  # adaptacion B2
    return method


class ABC:  # adaptacion B2: base nominal sin `ABCMeta`
    pass


class Condition(ABC):
    @abstractmethod
    def __call__(self, event: Any) -> bool:
        raise NotImplementedError

    def __and__(self, other: Any) -> "AndCondition":
        return self.and_(other)

    def and_(self, other: Any) -> "AndCondition":
        if not isinstance(other, Condition):
            other = TypeCondition(other)
        return AndCondition(self, other)

    def __or__(self, other: Any) -> "OrCondition":
        return self.or_(other)

    def or_(self, other: Any) -> "OrCondition":
        if not isinstance(other, Condition):
            other = TypeCondition(other)
        return OrCondition(self, other)

    def __invert__(self) -> "NotCondition":
        return self.not_()

    def not_(self) -> "NotCondition":
        return NotCondition(self)


class TypeCondition(Condition):
    def __init__(self, t: ClassInfo) -> None:
        self._expected_type = t

    def __call__(self, event: Any) -> bool:
        return isinstance(event, self._expected_type)

    def __repr__(self) -> str:
        if isinstance(self._expected_type, type):
            return f"IsType({self._expected_type.__name__})"
        elif isinstance(self._expected_type, tuple):
            names = [t.__name__ if isinstance(t, type) else str(t) for t in self._expected_type]
            return f"IsType({' | '.join(names)})"
        else:
            return f"IsType({self._expected_type})"


class AndCondition(Condition):
    def __init__(self, *conditions: Condition) -> None:
        self.conditions = conditions

    def __call__(self, event: Any) -> bool:
        return all(condition(event) for condition in self.conditions)

    def __repr__(self) -> str:
        flattened: list[Condition] = []
        for c in self.conditions:
            if isinstance(c, AndCondition):
                flattened.extend(c.conditions)
            else:
                flattened.append(c)
        parts = " & ".join(f"{c!r}" for c in flattened)
        return f"And({parts})"


class OrCondition(Condition):
    def __init__(self, *conditions: Condition) -> None:
        self.conditions = conditions

    def __call__(self, event: Any) -> bool:
        return any(condition(event) for condition in self.conditions)

    def __repr__(self) -> str:
        flattened: list[Condition] = []
        for c in self.conditions:
            if isinstance(c, OrCondition):
                flattened.extend(c.conditions)
            else:
                flattened.append(c)
        parts = " | ".join(f"{c!r}" for c in flattened)
        return f"Or({parts})"


class NotCondition(Condition):
    def __init__(self, condition: Condition) -> None:
        self.condition = condition

    def __call__(self, event: Any) -> bool:
        return not self.condition(event)

    def __repr__(self) -> str:
        return f"~{self.condition!r}"


class OpCondition(Condition):
    def __init__(
        self,
        op_func: Callable[[Any, Any], bool],
        field_name: str,
        value: Any,
        event_class: type,
    ) -> None:
        self.op_func = op_func
        self.field_name = field_name
        self.value = value
        self.event_class = event_class

    def __call__(self, event: Any) -> bool:
        if not isinstance(event, self.event_class):
            return False

        field_value = getattr(event, self.field_name, None)
        return self.op_func(field_value, self.value)

    def __repr__(self) -> str:
        op_name = op_names.get(self.op_func, "?")
        return f"Is({self.event_class.__name__}.{self.field_name} {op_name} {self.value!r})"


def check_eq(x: Any, y: Any) -> Any:
    if not isinstance(x, type(y)):
        return False
    return x == y


op_names = {
    check_eq: "==",
    operator.ne: "!=",
    operator.lt: "<",
    operator.le: "<=",
    operator.gt: ">",
    operator.ge: ">=",
    operator.is_: "is",
}

# ===== FIN BLOQUE VERBATIM AG-F1 =====


# =========================================================================================
# Condiciones de parada de M2: funcion PURA, separable y sustituible (predicados AG-F1)
# =========================================================================================

class _StopEvent:
    """Hecho observado del ciclo, con los cinco campos que deciden la parada (M2).

    Adaptacion declarada del fragmento AG-F1 (`condiciones de parada`): el fuente accede al
    campo del evento por atributo (`event.<campo>`); aqui el evento se construye **por clave**
    desde el `state` de `stop_decision`, y los predicados se mapean al vocabulario congelado
    `STOP_REASONS`/`RECEIPT_MOTIVES` del contrato §1 (nunca a codigos nuevos).
    """

    def __init__(self, cycle_state=None, elapsed_seconds=None, tokens_consumed=None,
                 stop_requested=False, write_failed=False):
        self.cycle_state = cycle_state
        self.elapsed_seconds = elapsed_seconds
        self.tokens_consumed = tokens_consumed
        self.stop_requested = bool(stop_requested)
        self.write_failed = bool(write_failed)

def stop_decision(state, budget):
    """Condicion de parada del ciclo (M2): recibe el estado observado y el presupuesto.

    **Funcion pura y deliberadamente pequena, separada del bucle de ciclos.** No muta nada, no
    lee el reloj, no toca el proceso ni el arriendo: solo clasifica un ciclo ya observado. Se
    aisla asi porque `t30` sustituira el CUERPO de esta funcion por el fragmento verbatim
    autorizado (`ag2ai/ag2@0938ebd:ag2/events/conditions.py`, Apache-2.0) y demostrara paridad
    sin tocar la API ni el bucle (contrato T-12 y §12); si la logica de parada estuviera
    entrelazada con el bucle, esa sustitucion romperia la forma congelada.

    `state` (claves exactas):
      * `cycle_state` — estado de cierre del ciclo del proceso (`completed`, `incomplete`,
        `budget_exhausted`) o `None` si el ciclo no cerro.
      * `elapsed_seconds` — segundos observados del ciclo segun el reloj inyectado.
      * `tokens_consumed` — tokens acumulados por el bucle hasta este ciclo.
      * `stop_requested` — si la parada se pidio durante el ciclo (AV-05).
      * `write_failed` — si la escritura durable del ciclo fallo (AV-03).

    `budget` (claves exactas): `seconds` y `tokens`, cada una `None` (sin techo) o numero.

    Devuelve `{'stop': bool, 'motive': str, 'stop_reason': str | None, 'reason': str}` con
    `motive ∈ RECEIPT_MOTIVES` y `stop_reason ∈ STOP_REASONS ∪ {None}`.

    Precedencia (determinista, documentada):
      1. `write_failed` ⇒ motivo `checkpoint_write_failed` y **no** se para: ese ciclo se
         reintenta al reanudar y su trabajo no se conto (AV-03).
      2. tiempo sobre el techo del bucle ⇒ `time_exhausted` (AV-17).
      3. tokens sobre el techo del bucle ⇒ `budget_exhausted`.
      4. el proceso cerro por techo propio ⇒ `budget_exhausted` (el techo es pegajoso).
      5. parada pedida durante el ciclo ⇒ `stop_requested` (AV-20).
      6. en cualquier otro caso NO se para y el motivo es el cierre del proceso.

    Los predicados de esta tabla son las **condiciones componibles verbatim** del bloque AG-F1
    (`TypeCondition`/`OpCondition`/`AndCondition` con `check_eq`, `operator.gt`); la precedencia y
    los diccionarios devueltos son de este modulo (contrato, no fragmento).
    """
    event = _StopEvent(cycle_state=state.get('cycle_state'),
                       elapsed_seconds=state.get('elapsed_seconds'),
                       tokens_consumed=state.get('tokens_consumed'),
                       stop_requested=state.get('stop_requested'),
                       write_failed=state.get('write_failed'))
    declared_seconds = (budget or {}).get('seconds')
    declared_tokens = (budget or {}).get('tokens')

    write_failed_condition = TypeCondition(_StopEvent) & OpCondition(check_eq, 'write_failed',
                                                                    True, _StopEvent)
    if write_failed_condition(event):
        return {'stop': False, 'motive': 'checkpoint_write_failed', 'stop_reason': None,
                'reason': 'la escritura durable fallo: el ciclo se reintenta y nada se conto'}

    time_over_condition = (OpCondition(operator.gt, 'elapsed_seconds', declared_seconds, _StopEvent)
                           if declared_seconds is not None and event.elapsed_seconds is not None
                           else None)
    if time_over_condition is not None and time_over_condition(event):
        return {'stop': True, 'motive': 'time_exhausted', 'stop_reason': 'time_exhausted',
                'reason': 'el ciclo observo %s s sobre un techo de %s s'
                          % (event.elapsed_seconds, declared_seconds)}

    tokens_over_condition = (OpCondition(operator.gt, 'tokens_consumed', declared_tokens, _StopEvent)
                             if declared_tokens is not None and event.tokens_consumed is not None
                             else None)
    if tokens_over_condition is not None and tokens_over_condition(event):
        return {'stop': True, 'motive': 'budget_exhausted', 'stop_reason': 'budget_exhausted',
                'reason': 'el bucle consumio %s tokens sobre un techo de %s'
                          % (event.tokens_consumed, declared_tokens)}

    process_ceiling_condition = OpCondition(check_eq, 'cycle_state', 'budget_exhausted', _StopEvent)
    if process_ceiling_condition(event):
        return {'stop': True, 'motive': 'budget_exhausted', 'stop_reason': 'budget_exhausted',
                'reason': 'el proceso cerro el ciclo por techo de presupuesto'}

    stop_requested_condition = OpCondition(check_eq, 'stop_requested', True, _StopEvent)
    if stop_requested_condition(event):
        return {'stop': True, 'motive': 'stop_requested', 'stop_reason': 'stop_requested',
                'reason': 'la parada se pidio durante el ciclo y se atiende al cerrarlo'}

    motive = event.cycle_state if event.cycle_state in ('completed', 'incomplete') else 'incomplete'
    return {'stop': False, 'motive': motive, 'stop_reason': None,
            'reason': 'el ciclo cerro como %r y el bucle puede abrir el siguiente' % (motive,)}


# =========================================================================================
# Adaptador del protocolo `lease` (§3.5) sobre engine/coordination.py
# =========================================================================================

class CoordinationLease:
    """Arriendo exclusivo sobre `engine.coordination.CoordinationStore`, sin modificarlo.

    Protocolo congelado (§3.5): `acquire`, `renew` y `release` devuelven
    `{'acquired', 'owner', 'expires_at', 'previous_owner', 'event'}`. El almacen de
    coordinacion es el que escribe (el bucle no abre ficheros); este adaptador solo traduce
    sus acciones `lease-acquire` / `lease-renew` / `lease-release` (`coordination.py:23,220`)
    y clasifica el resultado en el vocabulario `LEASE_EVENTS`.

    Un arriendo **ajeno y vigente** no es un error: es la barrera anti duplicacion, y se
    informa como `lease_held` con el dueno observado (AV-23). Un arriendo ajeno **vencido** se
    toma y se declara `lease_expired` con el dueno anterior y su sello de tiempo (AV-24).
    """

    def __init__(self, store, *, task_id=TEAM_LOOP_TASK, paths=TEAM_LOOP_PATHS):
        self._store = store
        self._task_id = str(task_id)
        self._paths = [str(path) for path in paths]
        self._lease_id = None
        try:  # coordination.py no se modifica: se usa su API publica y su error tipado
            from .coordination import CoordinationError
        except ImportError:  # raiz de la suite en sys.path
            from coordination import CoordinationError
        self._error_type = CoordinationError

    # -- utilidades --------------------------------------------------------------------
    @property
    def store(self):
        return self._store

    def _workspace(self):
        root = getattr(self._store, 'root', None)
        if root is not None:
            return str(root)
        return str(getattr(self._store, 'workspace', '') or '')

    def _rows(self, estado):
        return [row for row in (estado.get('leases') or ())
                if row.get('task_id') == self._task_id]

    def _mine(self, estado, agent_id):
        for row in self._rows(estado):
            if row.get('status') == 'active' and row.get('owner_agent_id') == agent_id:
                return row
        return None

    @staticmethod
    def _result(acquired, owner, expires_at, previous_owner, event, **extra):
        result = {'acquired': bool(acquired), 'owner': owner, 'expires_at': expires_at,
                  'previous_owner': previous_owner, 'event': event}
        result.update(extra)
        return result

    # -- protocolo ---------------------------------------------------------------------
    def acquire(self, agent_id, ttl_seconds):
        """Adquiere el arriendo o informa quien lo tiene. Nunca lanza por contencion."""
        agent_id = str(agent_id)
        ttl = _validated_ttl(ttl_seconds)
        estado = self._store.public()
        mine = self._mine(estado, agent_id)
        if mine is not None:
            return self.renew(agent_id, ttl)
        for row in self._rows(estado):
            if row.get('status') == 'active' and row.get('owner_agent_id') != agent_id:
                return self._result(False, row.get('owner_agent_id'), row.get('expires_at'),
                                    None, 'lease_held', reason='otro-agente-sostiene-el-arriendo')
        previous = self._rows(estado)[-1] if self._rows(estado) else None
        previous_owner = (previous or {}).get('owner_agent_id')
        body = {'owner_agent_id': agent_id, 'task_id': self._task_id,
                'workspace': self._workspace(), 'paths': list(self._paths),
                'base_sha': NULL_SHA, 'ttl_seconds': ttl,
                'expected_version': estado.get('version')}
        try:
            despues = self._store.apply('lease-acquire', body)
        except self._error_type as error:
            # Carrera perdida: el arriendo se tomo entre `public()` y `apply()`.
            return self._result(False, None, None, previous_owner, 'lease_held',
                                reason=str(error)[:MAX_STORE_ERROR_CHARS])
        row = self._mine(despues, agent_id)
        self._lease_id = (row or {}).get('id')
        event = 'lease_expired' if previous_owner not in (None, agent_id) else 'acquired'
        return self._result(True, agent_id, (row or {}).get('expires_at'), previous_owner, event,
                            lease_id=self._lease_id)

    def renew(self, agent_id, ttl_seconds):
        """Renueva el arriendo propio; si ya no existe, lo vuelve a adquirir."""
        agent_id = str(agent_id)
        ttl = _validated_ttl(ttl_seconds)
        estado = self._store.public()
        row = self._mine(estado, agent_id)
        if row is None:
            return self.acquire(agent_id, ttl)
        try:
            despues = self._store.apply('lease-renew', {
                'owner_agent_id': agent_id, 'task_id': self._task_id,
                'lease_id': row.get('id'), 'ttl_seconds': ttl,
                'expected_version': estado.get('version')})
        except self._error_type as error:
            return self._result(False, row.get('owner_agent_id'), row.get('expires_at'), None,
                                'lease_held', reason=str(error)[:MAX_STORE_ERROR_CHARS])
        refreshed = self._mine(despues, agent_id)
        self._lease_id = (refreshed or row).get('id')
        return self._result(True, agent_id, (refreshed or row).get('expires_at'), None, 'renewed',
                            lease_id=self._lease_id)

    def release(self, agent_id):
        """Libera el arriendo propio. Idempotente: sin arriendo propio no hay nada que soltar."""
        agent_id = str(agent_id)
        estado = self._store.public()
        row = self._mine(estado, agent_id)
        if row is None:
            return self._result(False, None, None, None, 'released', reason='sin-arriendo-propio')
        try:
            self._store.apply('lease-release', {
                'owner_agent_id': agent_id, 'task_id': self._task_id,
                'lease_id': row.get('id'), 'expected_version': estado.get('version')})
        except self._error_type as error:
            return self._result(False, agent_id, row.get('expires_at'), None, 'lease_held',
                                reason=str(error)[:MAX_STORE_ERROR_CHARS])
        self._lease_id = None
        return self._result(True, agent_id, None, None, 'released')


def _validated_ttl(value):
    if isinstance(value, bool) or type(value) is not int or not 60 <= value <= 3600:
        _fail('invalid_lease', 'ttl_seconds debe ser un entero entre 60 y 3600 '
                               '(rango que impone engine/coordination.py:246); recibido %r.'
              % (value,))
    return value


# =========================================================================================
# El bucle
# =========================================================================================

class TeamLoop:
    """Bucle continuo acotado: un ciclo = proceso + compromisos + arriendo + recibo.

    Constructor congelado (§3.1) mas cinco extensiones **aditivas y keyword-only** al final,
    que no cambian ningun nombre, orden ni defecto congelado:
    `followups` (motor de `engine/followups.py` a disparar por ciclo), `lease_owner`
    (identidad declarada ante el arriendo), `ttl_seconds`, `publish_as` (emisor del recibo en
    el canal) y `backoff_base` (base del retardo determinista).
    """

    def __init__(self, process, channel=None, store=None, clock=None, *, budget=None,
                 lease=None, worker=None, seed=0, followups=None, lease_owner=None,
                 ttl_seconds=None, publish_as=None, backoff_base=None):
        self._process = _validated_process(process)
        self._channel = _validated_channel(channel)
        self._store = _validated_store(store)
        self._clock = _validated_clock(clock)
        self._budget = _validated_loop_budget(budget)
        self._lease = _validated_lease(lease)
        self._worker = _validated_worker(worker)
        if isinstance(seed, bool) or type(seed) is not int:
            _fail('invalid_cycles', 'seed debe ser un entero (unica fuente de variacion del '
                                    'backoff determinista, D4); recibido %r.' % (seed,))
        self._seed = seed
        if backoff_base is not None and (isinstance(backoff_base, bool)
                                         or not isinstance(backoff_base, (int, float))
                                         or not math.isfinite(float(backoff_base))
                                         or backoff_base < 0):
            _fail('invalid_budget', 'backoff_base debe ser un numero >= 0 o None.')
        self._backoff_base = (DEFAULT_BACKOFF_BASE_SECS if backoff_base is None
                              else float(backoff_base))
        self._followups = followups
        self._ttl = DEFAULT_LEASE_TTL if ttl_seconds is None else _validated_ttl(ttl_seconds)
        self._lease_owner = str(lease_owner) if lease_owner is not None else DEFAULT_PUBLISH_AS
        self._publish_as = str(publish_as) if publish_as is not None else DEFAULT_PUBLISH_AS

        # Inyeccion del worker SOLO si el proceso no tiene uno (autorizado por §3.1).
        if self._worker is not None and getattr(self._process, '_worker', None) is None:
            self._process._worker = self._worker

        # Estado del bucle (nunca se expone por referencia).
        self._state = 'not_run'
        self._cycles = 0                 # intentos de ciclo (contrato §4.2)
        self._write_failures = 0         # intentos cuya escritura fallo (contrato §4.2)
        self._receipts = []              # recibos confirmados, orden de ciclo (AV-05)
        self._receipts_omitted = 0
        self._stop_reason = None
        self._stop_requested = False
        self._checkpoint_written = False
        self._checkpoint_digest = None
        self._last_checkpoint = None
        self._lease_state = None
        self._epochs = []                # lecturas del reloj inyectado, una por ciclo
        self._followup_ticks = []
        self._followup_errors = []
        self._loop_consumed = {'seconds': 0.0, 'tokens': 0}
        self._delays = []
        self._resumed = False

    # ------------------------------------------------------------------ validacion
    def _now(self):
        moment = self._clock()
        if isinstance(moment, bool) or not isinstance(moment, (int, float)) \
                or not math.isfinite(float(moment)):
            _fail('invalid_clock', 'clock debe devolver segundos epoch numericos.')
        return float(moment)

    # ------------------------------------------------------------------ superficie publica
    def run(self, cycles=1):
        """Ejecuta hasta `cycles` ciclos completos. Ver contrato §3.2 (`run`).

        Devuelve `{'cycles', 'receipts', 'stop_reason', 'checkpoint_written', 'state'}`.
        `cycles` cuenta los ciclos realmente intentados en ESTA llamada (un ciclo que no
        llego a empezar por arriendo ajeno no cuenta); `receipts` son los emitidos en esta
        llamada; `stop_reason='cycles_completed'` significa "no hubo parada y se agotaron los
        ciclos pedidos", nunca un fallo. Nunca lanza por condiciones reanudables: arriendo
        tomado, parada pedida, presupuesto agotado o checkpoint no escrito se REPORTAN (doctrina
        `tick()` de `engine/gang_supervisor.py:142-144`).
        """
        if isinstance(cycles, bool) or type(cycles) is not int or cycles < 0:
            _fail('invalid_cycles', 'cycles debe ser un entero >= 0; recibido %r (AV-21).'
                  % (cycles,))
        receipts = []
        written_any = False
        stop_reason = None
        executed = 0
        for _ in range(cycles):
            if self._stop_requested or self._state == 'stopped':
                stop_reason = self._stop_reason or 'stop_requested'
                break
            if self._exhausted_before_cycle():
                stop_reason = 'budget_exhausted'
                self._stop_reason = stop_reason
                self._state = 'stopped'
                break
            outcome = self._cycle()
            if outcome['lease_held']:
                stop_reason = 'lease_held'
                self._stop_reason = stop_reason
                self._state = 'stopped'
                break
            executed += 1
            written_any = written_any or bool(outcome['checkpoint_written'])
            if outcome['receipt'] is not None:
                receipts.append(outcome['receipt'])
            if outcome['stop_reason'] is not None:
                stop_reason = outcome['stop_reason']
                break
        if stop_reason is None and cycles > 0:
            stop_reason = 'cycles_completed'
        if self._state != 'stopped':
            self._state = 'running' if executed else self._state
        return {'cycles': executed, 'receipts': tuple(copy.deepcopy(receipts)),
                'stop_reason': stop_reason, 'checkpoint_written': bool(written_any),
                'state': self._state}

    def run_until_stopped(self, max_cycles=None, sleep=None):
        """Continuidad sin limite conocido: ciclos de uno en uno hasta la parada.

        No crea hilos (C-5): conduce `run(1)` desde el hilo del llamador, que puede ser un
        hilo daemon suyo. `stop()` desde otro hilo solo levanta una bandera, y el ciclo en
        curso termina entero antes de mirarla (AV-05). `sleep` es opcional y lo aporta el
        llamador; sin el, el bucle no espera (el retardo se publica en `next_delay`).
        """
        if max_cycles is not None and (isinstance(max_cycles, bool)
                                       or type(max_cycles) is not int or max_cycles < 0):
            _fail('invalid_cycles', 'max_cycles debe ser None o un entero >= 0.')
        if sleep is not None and not callable(sleep):
            _fail('invalid_worker', 'sleep debe ser un callable o None.')
        receipts = []
        executed = 0
        stop_reason = None
        while max_cycles is None or executed < max_cycles:
            if self._stop_requested or self._state == 'stopped':
                stop_reason = self._stop_reason or 'stop_requested'
                break
            result = self.run(1)
            executed += result['cycles']
            receipts.extend(result['receipts'])
            if result['stop_reason'] in ('lease_held', 'time_exhausted', 'budget_exhausted',
                                         'stop_requested'):
                stop_reason = result['stop_reason']
                break
            if result['cycles'] == 0:
                stop_reason = result['stop_reason'] or 'cycles_completed'
                break
            delay = self.next_delay(self._cycles)
            self._delays.append(delay)
            if sleep is not None and delay > 0:
                sleep(delay)
        if stop_reason is None:
            stop_reason = 'cycles_completed'
        return {'cycles': executed, 'receipts': tuple(copy.deepcopy(receipts)),
                'stop_reason': stop_reason, 'checkpoint_written': self._checkpoint_written,
                'state': self._state}

    def start(self):
        """Marca intencion de continuidad. Idempotente: no ejecuta ciclos ni crea hilos."""
        self._stop_requested = False
        self._stop_reason = None
        self._state = 'running'
        return self.status()

    def stop(self, reason='stop_requested'):
        """Pide parada limpia entre ciclos. Idempotente (AV-06). Ver contrato §3.2."""
        if not isinstance(reason, str) or reason not in STOP_REASON_INPUTS:
            # Entrada FUERA del dominio declarado: el contrato §1.1 solo tipa errores del
            # dominio, y `LOOP_ERROR_CODES` no tiene codigo para un motivo invalido.
            raise ValueError("stop(reason): motivos admitidos %r; recibido %r."
                             % (STOP_REASON_INPUTS, reason))
        self._stop_requested = True
        if self._stop_reason is None:
            self._stop_reason = reason
        if self._cycles == 0 and not self._receipts:
            # AV-07: parar antes del primer ciclo NO finge trabajo: el estado se queda en
            # `not_run` y el motivo es `stopped_before_start`.
            if reason == 'stop_requested':
                self._stop_reason = 'stopped_before_start'
        else:
            self._state = 'stopped'
        if self._lease is not None:
            try:
                released = self._lease.release(self._lease_owner)
            except Exception as error:  # noqa: BLE001 - la liberacion fallida se declara
                released = {'acquired': False, 'event': 'released',
                            'reason': str(error)[:MAX_STORE_ERROR_CHARS]}
            if isinstance(released, dict) and released.get('event') == 'released':
                self._lease_state = {'owner': released.get('owner'),
                                     'event': 'released',
                                     'expires_at': released.get('expires_at'),
                                     'previous_owner': released.get('previous_owner')}
        return self.status()

    def status(self):
        """Estado visible (copia profunda). Forma congelada del contrato §3.2.

        Lectura de los contadores: `cycles` cuenta INTENTOS de ciclo (§4.2), de modo que los
        ciclos durables son `cycles - write_failures`; `receipt_count` es el numero de recibos
        conservados (tope `MAX_CHECKPOINT_RECEIPTS`); `budget.consumed` acumula lo observado por
        el bucle en todos sus ciclos (segundos medidos con el reloj inyectado y tokens que el
        proceso declaro), no solo en el ultimo.
        """
        return {'schema': LOOP_SCHEMA, 'state': self._state, 'cycles': self._cycles,
                'receipt_count': len(self._receipts), 'write_failures': self._write_failures,
                'stop_reason': self._stop_reason,
                'checkpoint_written': self._checkpoint_written,
                'checkpoint_digest': self._checkpoint_digest,
                'lease': copy.deepcopy(self._lease_state),
                'budget': {'declared': dict(self._budget),
                           'consumed': {'seconds': round(self._loop_consumed['seconds'], 6),
                                        'tokens': self._loop_consumed['tokens']}},
                'process': self._process.status()}

    def history(self):
        """Recibos en orden de ciclo, inmutables (tupla de copias). Nunca se reescriben."""
        return tuple(copy.deepcopy(self._receipts))

    # ------------------------------------------------------------------ extensiones
    def next_delay(self, cycle=None):
        """Backoff FIJO con jitter determinista por semilla. No duerme ni usa `random`."""
        index = self._cycles if cycle is None else int(cycle)
        return round(self._backoff_base * (1.0 + _jitter(self._seed, index)), 6)

    def epochs(self):
        """Lecturas del reloj inyectado, una por ciclo intentado (epoch observable)."""
        return tuple(self._epochs)

    def delays(self):
        """Retardos publicados por `run_until_stopped` (el bucle no espera por si mismo)."""
        return tuple(self._delays)

    def followup_ticks(self):
        """Ticks del motor de follow-ups disparados, con su numero de eventos."""
        return tuple(copy.deepcopy(self._followup_ticks))

    def followup_errors(self):
        """Fallos del persecutor, en orden. Un persecutor roto no pierde el ciclo (declarado)."""
        return tuple(copy.deepcopy(self._followup_errors))

    def last_checkpoint(self):
        """Ultimo checkpoint durable escrito (copia) o `None`."""
        return copy.deepcopy(self._last_checkpoint)

    # ------------------------------------------------------------------ internos: arriendo
    def _lease_step(self):
        """Adquiere o renueva el arriendo. Devuelve el resultado del protocolo §3.5."""
        if self._lease is None:
            return None
        try:
            if self._lease_state and self._lease_state.get('owner') == self._lease_owner:
                result = self._lease.renew(self._lease_owner, self._ttl)
            else:
                result = self._lease.acquire(self._lease_owner, self._ttl)
        except Exception as error:  # noqa: BLE001 - un arriendo roto no tumba el ciclo
            return {'acquired': False, 'owner': None, 'expires_at': None,
                    'previous_owner': None, 'event': 'lease_held',
                    'reason': str(error)[:MAX_STORE_ERROR_CHARS]}
        if not isinstance(result, dict):
            return {'acquired': False, 'owner': None, 'expires_at': None,
                    'previous_owner': None, 'event': 'lease_held',
                    'reason': 'el arriendo devolvio %r' % (type(result).__name__,)}
        event = result.get('event')
        if event not in LEASE_EVENTS:
            result = dict(result, event='lease_held')
        self._lease_state = {'owner': result.get('owner'), 'event': result.get('event'),
                             'expires_at': result.get('expires_at'),
                             'previous_owner': result.get('previous_owner')}
        return result

    # ------------------------------------------------------------------ internos: store
    def _load(self):
        if self._store is None:
            return None
        try:
            if hasattr(self._store, 'load'):
                return self._store.load(CHECKPOINT_KEY)
            return self._store.get(CHECKPOINT_KEY)
        except Exception as error:  # noqa: BLE001 - la lectura fallida se reporta tipada
            _fail('invalid_store', 'la lectura del checkpoint fallo: %s'
                  % str(error)[:MAX_STORE_ERROR_CHARS])

    def _save(self, checkpoint):
        """Entrega el checkpoint ya codificado al sink. Un fallo no propaga (AV-03)."""
        try:
            text = _encode(checkpoint)
        except (TypeError, ValueError) as error:
            return False, 'serializacion: %s' % str(error)[:MAX_STORE_ERROR_CHARS]
        try:
            if hasattr(self._store, 'save'):
                self._store.save(CHECKPOINT_KEY, checkpoint)
            else:
                self._store[CHECKPOINT_KEY] = copy.deepcopy(checkpoint)
        except Exception as error:  # noqa: BLE001 - obligacion de atomicidad del sink (§3.4)
            return False, 'store: %s' % str(error)[:MAX_STORE_ERROR_CHARS]
        return True, _digest_of(text)

    def _resume(self):
        """Primer ciclo: rehidrata desde el checkpoint mas reciente (AV-24, contrato §8)."""
        stored = self._load()
        if stored is None:
            return False
        try:
            self._process.import_checkpoint(stored)
        except _process.TeamProcessError as error:
            _fail('invalid_store', 'el checkpoint del store no es reanudable por este proceso: %s'
                  % str(error)[:MAX_STORE_ERROR_CHARS])
        block = stored.get('loop') if isinstance(stored, dict) else None
        if isinstance(block, dict):
            # Los contadores del bloque `loop` no retroceden al reanudar (§8.1).
            if isinstance(block.get('cycles'), int) and not isinstance(block.get('cycles'), bool):
                self._cycles = max(self._cycles, block['cycles'])
            if isinstance(block.get('write_failures'), int):
                self._write_failures = max(self._write_failures, block['write_failures'])
            adopt = [copy.deepcopy(row) for row in (block.get('receipts') or ())
                     if isinstance(row, dict)]
            if adopt:
                # El recibo que el checkpoint guardo con `checkpoint_digest: null` es
                # justamente el que ese checkpoint firmo: se completa con su digest.
                stored_digest = _process.TeamProcess.checkpoint_digest(stored)
                for row in adopt:
                    if row.get('checkpoint_digest') is None:
                        row['checkpoint_digest'] = stored_digest
                self._receipts = adopt[-MAX_CHECKPOINT_RECEIPTS:]
                self._receipts_omitted = max(self._receipts_omitted,
                                             int(block.get('receipts_omitted') or 0)
                                             + len(adopt) - len(self._receipts))
                self._checkpoint_written = True
                self._checkpoint_digest = stored_digest
        self._last_checkpoint = copy.deepcopy(stored)
        self._resumed = True
        return True

    # ------------------------------------------------------------------ internos: ciclo
    def _exhausted_before_cycle(self):
        """No se abre un ciclo si el proceso ya declara techo agotado (aceptacion de M2)."""
        return self._process.status().get('cycle_state') == 'budget_exhausted'

    def _pursue(self):
        """Un tick del persecutor de compromisos. Un fallo se registra y no pierde el ciclo."""
        if self._followups is None:
            return None
        try:
            events = self._followups.tick()
            count = len(events) if _is_sequence(events) else 0
            self._followup_ticks.append({'cycle': self._cycles + 1, 'events': count})
            return count
        except Exception as error:  # noqa: BLE001 - el bucle mantiene el trabajo en marcha
            self._followup_errors.append({'cycle': self._cycles + 1,
                                          'error': '%s: %s' % (type(error).__name__,
                                                               str(error)[:120])})
            return None

    def _cycle(self):
        """Un ciclo completo. Devuelve el resultado interno; nunca lanza por lo reanudable."""
        started = self._now()
        self._epochs.append(started)
        if self._state == 'not_run':
            self._state = 'running'

        # 1. Arriendo: quien lo sostiene es quien trabaja (AV-23/AV-24).
        lease = self._lease_step()
        if lease is not None and not lease.get('acquired'):
            return {'lease_held': True, 'checkpoint_written': False, 'receipt': None,
                    'stop_reason': 'lease_held'}

        # 2. Reanudacion en el primer ciclo (puede adoptar los contadores del bloque `loop`).
        if self._cycles == 0 and not self._resumed:
            self._resume()
        attempt = self._cycles + 1

        # 3. Instantanea del estado en memoria antes de tocar nada (para restaurar).
        restore_point = self._process.export_checkpoint()

        # 4. Avance del proceso hasta cerrar el ciclo.
        result = self._process.run()
        steps = int(result.get('steps_advanced') or 0)
        consumed = dict(result.get('budget_consumed') or {})
        elapsed = max(0.0, self._now() - started)
        self._loop_consumed['seconds'] = round(self._loop_consumed['seconds'] + elapsed, 6)
        self._loop_consumed['tokens'] = int(self._loop_consumed['tokens']) + int(
            consumed.get('tokens') or 0)

        # 5. Compromisos (tick explicito, disparado por el ciclo).
        self._pursue()

        # 6. Condicion de parada y motivo del recibo (funcion pura, contrato §7.3 y AV-17).
        decision = stop_decision({'cycle_state': result.get('cycle_state'),
                                   'elapsed_seconds': elapsed,
                                   'tokens_consumed': self._loop_consumed['tokens'],
                                   'stop_requested': self._stop_requested,
                                   'write_failed': False}, self._budget)
        motive = decision['motive']
        stop_reason = decision['stop_reason']

        receipt = {'receipt_version': RECEIPT_VERSION, 'cycle': result.get('cycle', attempt),
                   'mode': result.get('mode', self._process.status().get('mode')),
                   'steps_advanced': steps,
                   'budget_consumed': {'steps': int(consumed.get('steps') or 0),
                                       'seconds': round(elapsed, 6),
                                       'delegations': int(consumed.get('delegations') or 0),
                                       'tokens': int(consumed.get('tokens') or 0)},
                   'motive': motive, 'at': _stamp(self._epochs[-1]),
                   'checkpoint_digest': None, 'stop_reason': stop_reason}

        # 7. Checkpoint durable. El recibo de ESTE ciclo entra en el checkpoint con
        #    `checkpoint_digest: null`, porque su digest es el del checkpoint que lo contiene
        #    y meterlo dentro seria autorreferencia (§4.4). Tras escribir, el recibo emitido
        #    recibe el digest real; el checkpoint del ciclo siguiente ya lo lleva completo.
        self._cycles = attempt
        checkpoint = self._process.export_checkpoint()
        pending = [copy.deepcopy(row) for row in self._receipts] + [copy.deepcopy(receipt)]
        omitted = self._receipts_omitted
        if len(pending) > MAX_CHECKPOINT_RECEIPTS:
            dropped = len(pending) - MAX_CHECKPOINT_RECEIPTS
            pending = pending[dropped:]
            omitted += dropped
        checkpoint['loop'] = {'cycles': self._cycles, 'stop_reason': self._stop_reason,
                              'receipts': pending,
                              'receipts_omitted': omitted,
                              'write_failures': self._write_failures,
                              'lease': copy.deepcopy(self._lease_state)}
        written, detail = (False, 'sin store inyectado')
        if self._store is not None:
            written, detail = self._save(checkpoint)

        if not written:
            # 8a. Nada se hizo durable: se restaura la memoria y se declara el fallo (AV-03).
            self._write_failures += 1
            self._restore(restore_point)
            receipt['motive'] = 'checkpoint_write_failed'
            receipt['steps_advanced'] = 0
            receipt['checkpoint_digest'] = None
            self._register(receipt)
            self._publish(receipt)
            return {'lease_held': False, 'checkpoint_written': False, 'receipt': receipt,
                    'stop_reason': stop_reason, 'write_detail': detail}

        # 8b. Ciclo durable: digest, recibo y publicacion.
        if self._store is not None:
            receipt['checkpoint_digest'] = detail
            self._checkpoint_written = True
            self._checkpoint_digest = detail
            self._last_checkpoint = copy.deepcopy(checkpoint)
        self._register(receipt)
        self._publish(receipt)
        return {'lease_held': False, 'checkpoint_written': written, 'receipt': receipt,
                'stop_reason': stop_reason}

    def _restore(self, checkpoint):
        """Rehidrata el estado en memoria al de antes del ciclo fallido.

        El unico camino de rehidratacion del contrato es `import_checkpoint` (§2.3), que
        incrementa `resumptions`: es la senal honesta de que el estado se rehidrato, no un
        efecto del ciclo fallido. El estado durable no se toca (el sink es atomico, §3.4).
        """
        try:
            self._process.import_checkpoint(checkpoint)
        except _process.TeamProcessError as error:
            # Si ni siquiera se puede restaurar, se declara: nunca se oculta.
            self._followup_errors.append({'cycle': self._cycles,
                                          'error': 'restore: %s' % str(error)[:120]})

    def _register(self, receipt):
        """Registra el recibo en `history()`. Un recibo emitido nunca se reescribe (AV-05)."""
        self._receipts.append(copy.deepcopy(receipt))
        overflow = len(self._receipts) - MAX_CHECKPOINT_RECEIPTS
        if overflow > 0:
            del self._receipts[:overflow]
            self._receipts_omitted += overflow
        if receipt['stop_reason'] is not None and self._stop_reason is None:
            self._stop_reason = receipt['stop_reason']
        if receipt['stop_reason'] in ('time_exhausted', 'budget_exhausted', 'stop_requested',
                                      'lease_held'):
            self._stop_requested = True
            self._state = 'stopped'

    def _publish(self, receipt):
        """Publica el recibo en el canal (si se inyecto). Nada sale a ningun proveedor."""
        if self._channel is None:
            return
        text = ('recibo de ciclo %d: motivo=%s, pasos=%d, estado=%s'
                % (receipt['cycle'], receipt['motive'], receipt['steps_advanced'],
                   self._state))
        try:
            self._channel.publish(self._publish_as, to='all', text=text, topic=LOOP_TOPIC)
        except TypeError:
            # Canal minimo: `publish(sender, text=...)` sin `to`.
            self._channel.publish(self._publish_as, text=text, topic=LOOP_TOPIC)
        except Exception as error:  # noqa: BLE001 - publicar no puede perder el recibo
            self._followup_errors.append({'cycle': receipt['cycle'],
                                          'error': 'publish: %s' % str(error)[:120]})

    # ------------------------------------------------------------------ vistas internas
    def export_loop_block(self):
        """Bloque `loop` del checkpoint v1 con el estado actual (copia)."""
        return {'cycles': self._cycles, 'stop_reason': self._stop_reason,
                'receipts': [copy.deepcopy(row) for row in self._receipts],
                'receipts_omitted': self._receipts_omitted,
                'write_failures': self._write_failures,
                'lease': copy.deepcopy(self._lease_state)}


def _digest_of(text):
    """sha256 del JSON canonico ya codificado (contrato §4.4)."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------------------
# Validacion de las piezas inyectadas (contrato §3.1, codigos de §1.1)
# ---------------------------------------------------------------------------------------

def _validated_process(process):
    for name in ('status', 'export_checkpoint', 'import_checkpoint', 'run'):
        if not callable(getattr(process, name, None)):
            _fail('invalid_process', 'process debe exponer %s() (contrato §2.3).' % name)
    return process


def _validated_channel(channel):
    if channel is None:
        return None
    if not callable(getattr(channel, 'publish', None)):
        _fail('invalid_channel', 'channel debe exponer publish(sender, to=, text=, topic=) '
                                 'o ser None (contrato §3.1).')
    return channel


def _validated_store(store):
    if store is None:
        return None
    if callable(getattr(store, 'load', None)) and callable(getattr(store, 'save', None)):
        return store
    if hasattr(store, 'get') and hasattr(store, '__setitem__'):
        return store
    _fail('invalid_store', 'store debe exponer load(key)/save(key, checkpoint) o ser un dict '
                           'plano (contrato §3.4).')


def _validated_clock(clock):
    if clock is None:
        return time.time
    if not callable(clock):
        _fail('invalid_clock', 'clock debe ser un callable que devuelva segundos epoch.')
    return clock


def _validated_lease(lease):
    if lease is None:
        return None
    for name in ('acquire', 'renew', 'release'):
        if not callable(getattr(lease, name, None)):
            _fail('invalid_lease', 'lease debe exponer %s() segun el protocolo §3.5.' % name)
    return lease


def _validated_worker(worker):
    if worker is None:
        return None
    if not callable(worker):
        _fail('invalid_worker', 'worker debe ser un callable o None.')
    return worker


def _validated_loop_budget(budget):
    declared = {'seconds': None, 'tokens': None}
    if budget is None:
        return declared
    if not isinstance(budget, dict):
        _fail('invalid_budget', 'budget debe ser un Mapping con claves %s o None.'
              % (LOOP_BUDGET_DIMENSIONS,))
    unknown = sorted(str(key) for key in budget if key not in LOOP_BUDGET_DIMENSIONS)
    if unknown:
        _fail('invalid_budget', 'budget del bucle admite solo %s; sobran %s (contrato §7.3).'
              % (LOOP_BUDGET_DIMENSIONS, unknown))
    for dimension, value in budget.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)) or value < 0:
            _fail('invalid_budget', 'budget.%s debe ser un numero >= 0 o None; recibido %r.'
                  % (dimension, value))
        if dimension == 'tokens' and type(value) is not int:
            _fail('invalid_budget', 'budget.tokens debe ser entero o None; recibido %r.'
                  % (value,))
        declared[dimension] = value
    return declared


__all__ = ['TeamLoop', 'TeamLoopError', 'CoordinationLease', 'stop_decision',
           'LOOP_SCHEMA', 'LOOP_TOPIC', 'CHECKPOINT_KEY', 'CHECKPOINT_VERSION', 'RECEIPT_VERSION',
           'LOOP_STATES', 'STOP_REASONS', 'RECEIPT_MOTIVES', 'LOOP_BUDGET_DIMENSIONS',
           'LEASE_EVENTS', 'MAX_CHECKPOINT_RECEIPTS', 'LOOP_ERROR_CODES', 'TEAM_LOOP_TASK',
           'TEAM_LOOP_PATHS', 'DEFAULT_LEASE_TTL', 'DEFAULT_PUBLISH_AS',
           'DEFAULT_BACKOFF_BASE_SECS', 'STOP_REASON_INPUTS']
