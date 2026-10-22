# TEAM_API_CONTRACT_v1 — Contrato congelado de API pública de `team_process` y `team_loop`

**Tarea:** `t31` (M0) · **Naturaleza:** CONTRATO, no implementación · **Estado:** **CONGELADO** para `t22`, `t23` y `t30`.
**Módulos que gobierna:** `engine/team_process.py` (t22) y `engine/team_loop.py` (t23).
**Insumos:** `docs/rea/agile_vectors.json` (22 vectores `AV-01…AV-24` de `t21`), `docs/rea/PORT_REPORT.md`,
`engine/team_channel.py`, `engine/team_memory.py`, `engine/followups.py`, `engine/coordination.py`,
`engine/gang_supervisor.py` (doctrina de *tick* explícito) y la enmienda de código verbatim
(`docs/security/FUSILE_SOURCE_POLICY.md`).
**Convención de citas:** `archivo:línea` sobre el código leído en esta sesión.
**Convención de rutas:** relativas a `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`.

Este documento **no implementa nada**: no escribe módulos, no ejecuta la suite, no corre
`resella_paquete.py` y no toca el manifiesto. Fija la forma para que tres tareas distintas (`t22`, `t23`,
`t30`) no se pisen: `t22` y `t23` implementan contra esta forma; `t30` puede sustituir el **algoritmo**
interno por código verbatim, pero **no** puede cambiar nada de §9.

---

## 0. Regla de congelamiento

| Regla | Enunciado |
| --- | --- |
| C-1 | Las firmas de §2 y §3, los nombres de estado y los códigos de §1 son **vinculantes**. Un cambio exige `TEAM_API_CONTRACT_v2.md` y una versión nueva de checkpoint; no se edita en caliente. |
| C-2 | El checkpoint v1 de §4 es el **único** formato de estado durable. Añadir, quitar o re-tipar una clave exige `checkpoint_version = 2`. |
| C-3 | Los 22 vectores de `docs/rea/agile_vectors.json` son la especificación de comportamiento observable. Una implementación que no los satisfaga no está completa. |
| C-4 | `t30` (verbatim) preserva la API, los estados, los códigos y los vectores; sólo puede cambiar el algoritmo interno, y cada adaptación se anota. |
| C-5 | Prohibido en ambos módulos: red, hilos, `subprocess`, `multiprocessing`, apertura de ficheros, claves y cualquier contacto con DSH. El checkpoint es un `dict`; **la persistencia la decide quien llama**. |

---

## 1. Vocabulario congelado

```python
MODES              = ('sequential', 'hierarchical', 'parallel_waves')
CYCLE_STATES       = ('not_run', 'running', 'incomplete', 'completed', 'budget_exhausted')
MEMBER_STATES      = ('pending', 'running', 'success', 'failed', 'skipped')
DELEGATION_STATES  = ('open', 'closed')
LOOP_STATES        = ('not_run', 'running', 'stopped')
STOP_REASONS       = ('stop_requested', 'stopped_before_start', 'time_exhausted',
                      'budget_exhausted', 'lease_held', 'cycles_completed')
RECEIPT_MOTIVES    = ('completed', 'incomplete', 'budget_exhausted', 'time_exhausted',
                      'stop_requested', 'checkpoint_write_failed')
BUDGET_DIMENSIONS  = ('steps', 'seconds', 'delegations', 'tokens')
EXHAUSTION_REASONS = ('steps', 'seconds', 'delegations', 'tokens')
LEASE_EVENTS       = ('acquired', 'renewed', 'released', 'lease_held', 'lease_expired')

CHECKPOINT_VERSION = 1
CHECKPOINT_SCHEMA  = 'orgdna.team_process.checkpoint/1'
PROCESS_SCHEMA     = 'orgdna.team_process/1'
LOOP_SCHEMA        = 'orgdna.team_loop/1'
RECEIPT_VERSION    = 1
CHECKPOINT_KEY     = 'orgdna.team_process.checkpoint'
DEFAULT_WAVE_SIZE  = 4
MAX_WAVE_SIZE      = 32          # == team_channel.MAX_MEMBERS (engine/team_channel.py:89)
MAX_MEMBERS        = 32
MAX_CHECKPOINT_RECEIPTS = 256
LOOP_TOPIC         = 'team_loop' # tópico de publicación en el canal (si se inyecta)
MEMBER_ID_PATTERN  = r'^[a-z0-9][a-z0-9._-]{1,63}$'   # == team_memory._MEMBER_RE (engine/team_memory.py:95)
```

**`clock` (convención del repo, no se reinventa).** Un `clock` es un *callable* sin argumentos que
devuelve **segundos epoch como `float`**, por defecto `time.time`; es exactamente lo que ya usan
`TeamChannel` (`engine/team_channel.py:187-188`) y `FollowupsEngine` (`engine/followups.py:186`).
Las marcas se formatean con la convención del repo
(`engine/team_channel.py:271-272`):

```python
datetime.fromtimestamp(self._clock(), timezone.utc).isoformat().replace('+00:00', 'Z')
```

**JSON canónico (para digests y comparaciones).** `json.dumps(valor, sort_keys=True,
separators=(',', ':'), ensure_ascii=False, allow_nan=False)`. Ninguna decisión del módulo puede depender
del orden de inserción de un `dict` ni del hash de un `set`.

### 1.1 Excepciones tipadas

Ambos módulos siguen la convención de error del repo (`ChannelError`, `FollowupsError`,
`CoordinationError`, `TaskGraphError` son `ValueError` con `.code`):

```python
class TeamProcessError(ValueError):   # .code en PROCESS_ERROR_CODES
class TeamLoopError(ValueError):      # .code en LOOP_ERROR_CODES
```

```python
PROCESS_ERROR_CODES = (
    'invalid_roster', 'unknown_mode', 'unknown_member', 'invalid_wave_size', 'invalid_budget',
    'invalid_limit', 'invalid_clock', 'invalid_worker', 'invalid_outcome', 'unknown_delegation',
    'unsupported_checkpoint_version', 'checkpoint_shape_invalid', 'checkpoint_mismatch',
    'worker_required', 'cycle_closed',
)
LOOP_ERROR_CODES = (
    'invalid_process', 'invalid_channel', 'invalid_store', 'invalid_lease', 'invalid_clock',
    'invalid_cycles', 'invalid_budget', 'invalid_worker',
)
```

Ninguna otra excepción forma parte del contrato: los módulos **no** lanzan `KeyError`, `AttributeError`,
`TypeError` ni `ValueError` sin `.code` para entradas del dominio declarado.

---

## 2. `engine/team_process.py` — `TeamProcess`

Motor de proceso: convierte un roster pasivo en un grupo que avanza por pasos explícitos. **No hay hilo,
ni bucle interno, ni espera**: la continuidad la orquesta `TeamLoop` (§3).

### 2.1 Constructor

```python
class TeamProcess:
    def __init__(self, roster, mode='sequential', clock=None, budget=None,
                 wave_size=None, worker=None, coordinator_slot=None): ...
```

| Parámetro | Tipo | Defecto | Regla |
| --- | --- | --- | --- |
| `roster` | secuencia de `Mapping` | — (obligatorio) | 1..32 miembros; esquema en §2.2; `invalid_roster` si no cumple |
| `mode` | `str` | `'sequential'` | ∈ `MODES`; si no, `unknown_mode` (AV-08) |
| `clock` | `Callable[[], float]` | `time.time` | §1; si no es *callable*, `invalid_clock` |
| `budget` | `Mapping` o `None` | `None` | §7; clave≠`BUDGET_DIMENSIONS`, valor negativo o no numérico ⇒ `invalid_budget` (AV-18) |
| `wave_size` | `int` o `None` | `None` → `DEFAULT_WAVE_SIZE` | sólo `parallel_waves`; `0`, negativo, no entero o `> MAX_WAVE_SIZE` ⇒ `invalid_wave_size` (AV-15) |
| `worker` | `Callable[[dict], Mapping]` o `None` | `None` | protocolo §2.4; si no es *callable*, `invalid_worker` |
| `coordinator_slot` | `int` o `None` | `None` → `is_coordinator` del roster, o el slot menor | sólo `hierarchical`; debe existir en el roster ⇒ si no, `unknown_member` |

### 2.2 Roster

Cada miembro es un `Mapping` con claves exactas (`additionalProperties: false`):

| Clave | Tipo | Obligatoria | Regla |
| --- | --- | --- | --- |
| `slot` | `int` | sí | 1..32, **único**; es el orden canónico (§5) |
| `member_id` | `str` | sí | `MEMBER_ID_PATTERN`; único |
| `role` | `str` | sí | 1..120 caracteres |
| `is_coordinator` | `bool` | no (defecto `False`) | como máximo **uno** `True`; dos ⇒ `invalid_roster` |
| `delegates_to` | `list[int]` | no (defecto `[]`) | `hierarchical`: slots destino permitidos; deben existir ⇒ si no, `unknown_member` |

El roster se normaliza a orden ascendente de `slot` al construir; esa lista normalizada es la que se
serializa en el checkpoint (§4).

### 2.3 Métodos públicos

```python
def step(self, outcome=None) -> dict
def run(self, limit=None) -> dict
def status(self) -> dict
def export_checkpoint(self) -> dict
def import_checkpoint(self, checkpoint) -> dict

@classmethod
def from_checkpoint(cls, checkpoint, *, clock=None, worker=None, budget=None) -> 'TeamProcess'
@staticmethod
def checkpoint_digest(checkpoint) -> str
```

`from_checkpoint` y `checkpoint_digest` son superficie **también congelada** (necesarias para reanudar sin
conocer el roster y para citar el estado en un recibo); el resto de métodos exigidos son los cinco
primeros.

#### `step(outcome=None) -> dict`

Avanza **una unidad de trabajo** del ciclo abierto. Dos modos de uso, excluyentes por disponibilidad:

- **Con `worker` inyectado** y `outcome=None`: el proceso selecciona la siguiente unidad en orden canónico,
  llama a `worker(request)` (§2.4), valida y aplica los resultados, y devuelve el avance.
- **Sin `worker`** y con `outcome` no nulo: el llamador aporta el resultado (§2.5) y el proceso lo aplica.
  `outcome` puede describir uno o **varios** slots (una ola o una ronda de delegaciones).
- Sin `worker` y con `outcome=None` ⇒ `worker_required`.

Precondición: `cycle_state ∈ ('not_run', 'running')`. Si el ciclo ya cerró, `step()` **no** lo reabre: lanza
`cycle_closed` (D8). Abrir el ciclo siguiente es competencia exclusiva de `run()`.

Devuelve (claves exactas, orden fijo):

```python
{'advanced': bool, 'slots': tuple[int, ...], 'cycle': int, 'step': int,
 'cycle_state': str, 'exhausted': None | {'reason': str},
 'open_delegations': tuple[int, ...], 'wave': int | None}
```

Nunca lanza por condiciones **reanudables** (presupuesto, delegación abierta, ola en curso): las reporta.
Sólo lanza por violación de contrato, con `TeamProcessError.code`.

#### `run(limit=None) -> dict`

Avanza hasta cerrar el ciclo, hasta `limit` unidades o hasta un techo de presupuesto, lo primero que ocurra.
Requiere el `worker` del constructor (no se acepta por argumento); sin `worker` ⇒ `worker_required`. Si el
ciclo almacenado ya está cerrado, `run()` **abre** el ciclo siguiente (`cycle+1`) antes de avanzar; si el
ciclo está en `not_run`, abre el ciclo 1. `limit` es `None` o `int ≥ 1`; cualquier otro valor ⇒
`invalid_limit`.

Devuelve:

```python
{'cycle': int, 'mode': str, 'steps_advanced': int, 'cycle_state': str,
 'budget_consumed': dict, 'exhausted': None | {'reason': str},
 'open_delegations': tuple[int, ...], 'receipt': dict}
```

`receipt` es el **resumen de ciclo** con la forma de §3.3 salvo los dos campos que sólo el bucle conoce
(`checkpoint_digest`, `stop_reason`): `{'receipt_version': 1, 'cycle', 'mode', 'steps_advanced',
'budget_consumed', 'motive', 'at'}`. El `TeamLoop` lo completa con `checkpoint_digest` y `stop_reason`, lo
registra en `history()` y lo publica. `motive` = `'completed' | 'incomplete' | 'budget_exhausted'`.

#### `status() -> dict`

Copia profunda e inmutable-por-convención del estado visible (nunca referencias internas):

```python
{'schema': PROCESS_SCHEMA, 'mode': str, 'cycle': int, 'step': int, 'steps_total': int,
 'cycle_state': str, 'resumptions': int, 'coordinator_slot': int | None,
 'roster': [{'slot','member_id','role','is_coordinator','delegates_to'}...],     # orden canónico
 'members': [{'slot','member_id','state','steps'}...],                            # orden canónico
 'results': [{'slot','state','result','cycle','step'}...],                        # orden canónico
 'delegations': [{'delegation_id','from_slot','to_slot','state','cycle','result'}...],
 'waves': None | {'size': int, 'index': int, 'total': int, 'closed': int, 'slots': [[int]]},
 'next_slots': tuple[int, ...],
 'budget': {'declared': dict, 'consumed': dict, 'remaining': dict, 'exhausted': None | {'reason': str}}}
```

#### `export_checkpoint() -> dict`

Checkpoint v1 (§4) **JSON-serializable**: `json.dumps(..., allow_nan=False)` debe funcionar. No incluye el
digest (se calcula con `checkpoint_digest`, §4.4). Es una copia: mutarla no altera el proceso.

#### `import_checkpoint(checkpoint) -> dict`

Restaura el estado desde un checkpoint v1 sobre una instancia ya construida (mismo `mode` y mismo roster).
Pasos y errores:

1. `checkpoint_version != 1` o `schema != CHECKPOINT_SCHEMA` ⇒ `unsupported_checkpoint_version`
   (AV-02): cero miembros avanzados, el checkpoint recibido **no** se modifica ni se degrada.
2. Claves/forma/tipos fuera de §4 ⇒ `checkpoint_shape_invalid`.
3. `mode` o roster (slots y `member_id`) distintos de los de la instancia ⇒ `checkpoint_mismatch`.
4. Restaura `cycle`, `step`, `steps_total`, `cycle_state`, `members`, `results`, `delegations`, `waves`,
   `budget.consumed` y `budget.exhausted`; incrementa `resumptions` en 1.
5. Devuelve `status()`.

No reejecuta nada por sí mismo: sólo rehidrata estado (§8).

### 2.4 Protocolo `worker`

```python
worker(request: dict) -> Mapping
```

`request` (claves exactas):

```python
{'mode': str, 'cycle': int, 'step': int, 'wave': int | None,
 'slots': tuple[int, ...],                      # unidades pendientes de esta llamada, orden canónico
 'members': [{'slot','member_id','role'}...],   # subconjunto de slots, orden canónico
 'delegations': [{'delegation_id','from_slot','to_slot'}...]}   # vacío salvo hierarchical
```

Respuesta: `Mapping` de `slot -> outcome`, o `{'outcomes': [...]}`; **el orden de inserción es
irrelevante** y se consolida por slot (§5, D2). `outcome`:

```python
{'state': 'success' | 'failed', 'result': <valor JSON> | None}
```

`state` fuera del vocabulario, slot inexistente, slot no solicitado o resultado no JSON-serializable ⇒
`invalid_outcome`. Un worker que lance propaga su excepción: el contrato no la convierte en estado.

### 2.5 `outcome` de `step()` (sin worker)

Misma forma que la respuesta del worker (`Mapping slot -> outcome`), o un único `outcome` cuando el paso
espera exactamente un slot. Slot fuera del roster ⇒ `unknown_member`; slot no pendiente ⇒ `invalid_outcome`.

---

## 3. `engine/team_loop.py` — `TeamLoop`

Bucle continuo: **un ciclo = avanzar proceso + perseguir compromisos + renovar arriendo + registrar recibo**.
No decide estrategia, no es un demonio y no usa hilos. La continuidad se pide con `run(cycles=N)`.

### 3.1 Constructor

```python
class TeamLoop:
    def __init__(self, process, channel=None, store=None, clock=None, *,
                 budget=None, lease=None, worker=None, seed=0): ...
```

| Parámetro | Tipo | Defecto | Regla |
| --- | --- | --- | --- |
| `process` | `TeamProcess` | — (obligatorio) | debe exponer `status/export_checkpoint/import_checkpoint/run`; si no, `invalid_process` |
| `channel` | objeto con `publish(sender, to=..., text=..., topic=...)` o `None` | `None` | se usa **tal cual** `TeamChannel` (`engine/team_channel.py:301`); no se modifica; si no cumple, `invalid_channel` |
| `store` | *sink* de checkpoint o `None` | `None` | protocolo §3.4; `None` ⇒ sin persistencia |
| `clock` | `Callable[[], float]` | `time.time` | §1 |
| `budget` | `Mapping` o `None` | `None` | **por ciclo**: `{'seconds': number|None, 'tokens': int|None}`; inválido ⇒ `invalid_budget` |
| `lease` | protocolo §3.5 o `None` | `None` | `None` ⇒ sin exclusividad (se declara en `status()`) |
| `worker` | *callable* o `None` | `None` | se pasa al proceso **sólo si** el proceso no tiene uno; si no es *callable*, `invalid_worker` |
| `seed` | `int` | `0` | única fuente de variación del backoff determinista (§5, D4) |

### 3.2 Métodos públicos

```python
def run(self, cycles=1) -> dict
def start(self) -> dict
def stop(self, reason='stop_requested') -> dict
def status(self) -> dict
def history(self) -> tuple
```

#### `run(cycles=1) -> dict`

Ejecuta hasta `cycles` ciclos **completos**. `cycles` es `int ≥ 0`; otro valor ⇒ `invalid_cycles` (AV-21:
`cycles=0` ⇒ cero recibos y ningún avance). Por cada ciclo:

1. Arriendo (§3.5): si `lease` está inyectado, adquirir/renovar. Si no se consigue ⇒ `stop_reason='lease_held'`,
   `cycles=0` respecto de este ciclo, **sin** escritura de checkpoint y **sin** recibo (AV-23).
2. Avanzar el proceso hasta cerrar el ciclo (`process.run()`), respetando el presupuesto del bucle (§7.3).
3. Construir el checkpoint (`process.export_checkpoint()` + bloque `loop`), validarlo con
   `json.dumps(..., allow_nan=False)` y entregarlo al `store` si existe. **Antes** del ciclo el bucle toma una
   instantánea del estado durable; si la serialización **o** el `store` fallan, el bucle **restaura esa
   instantánea** (no deja estado parcial en memoria ni en disco), emite el recibo con
   `motive='checkpoint_write_failed'` y `steps_advanced=0` (nada se hizo durable), incrementa
   `loop.write_failures` y **no** incrementa el contador de ciclos durables (AV-03: pasos avanzados 2, nunca 3).
4. Registrar el recibo (§3.3) en `history()` y publicarlo en `channel` (tema `LOOP_TOPIC`) si se inyectó.
5. Comprobar parada/presupuesto antes de iniciar el ciclo siguiente.

Devuelve:

```python
{'cycles': int, 'receipts': tuple[dict, ...], 'stop_reason': str | None,
 'checkpoint_written': bool, 'state': str}
```

Nunca lanza por condiciones reanudables (arriendo tomado, parada pedida, presupuesto agotado,
checkpoint no escrito): las reporta (doctrina `tick()` de `engine/gang_supervisor.py:142-144`).

#### `start() -> dict`

Marca intención de continuidad: `state='running'`; **idempotente**; **no ejecuta ciclos** y no crea hilos.
Devuelve `status()`. `run()` arranca implícitamente si no se llamó a `start()` ni a `stop()`.

#### `stop(reason='stop_requested') -> dict`

Pide parada limpia entre ciclos. `reason` ∈ `('stop_requested', 'time_exhausted', 'budget_exhausted')`.
**Idempotente** (AV-06): repetir devuelve el mismo `stop_reason` y el mismo `cycles`, sin excepción.
Si se llama antes del primer ciclo, `state='not_run'` y `stop_reason='stopped_before_start'` (AV-07).
Devuelve `status()`.

#### `status() -> dict`

```python
{'schema': LOOP_SCHEMA, 'state': str, 'cycles': int, 'receipt_count': int, 'write_failures': int,
 'stop_reason': str | None, 'checkpoint_written': bool, 'checkpoint_digest': str | None,
 'lease': None | {'owner': str, 'event': str, 'expires_at': str | None, 'previous_owner': str | None},
 'budget': {'declared': dict, 'consumed': dict},
 'process': dict}     # == process.status()
```

#### `history() -> tuple`

Recibos en orden de ciclo, **inmutables** (tupla de copias). Un recibo emitido nunca se reescribe (AV-05).

### 3.3 Recibo de ciclo (forma congelada)

```python
{'receipt_version': 1, 'cycle': int, 'mode': str, 'steps_advanced': int,
 'budget_consumed': {'steps': int, 'seconds': float, 'delegations': int, 'tokens': int},
 'motive': str,                       # ∈ RECEIPT_MOTIVES
 'at': str,                           # instantánea UTC del reloj inyectado
 'checkpoint_digest': str | None,     # sha256 canónico del checkpoint escrito, o None
 'stop_reason': str | None}
```

Reglas: `motive='completed'` sólo si el ciclo cerró completo; nunca un recibo con `steps_advanced=0` y
`motive='completed'` (AV-21); dos ciclos cerrados por motivos distintos producen motivos distintos (AV-20);
el recibo del último ciclo cerrado no se altera al parar (AV-05); un ciclo con escritura fallida emite
`motive='checkpoint_write_failed'` con `steps_advanced=0` (nada durable) y `checkpoint_digest=null` (AV-03).

### 3.4 Protocolo `store` (persistencia **decidida por quien llama**)

```python
load(key: str) -> Mapping | None
save(key: str, checkpoint: Mapping) -> None
```

- Clave congelada: `CHECKPOINT_KEY`. También se admite un `dict` plano (`get`/`__setitem__`).
- `save` **debe ser atómico** (todo o nada): el bucle no puede garantizar la atomicidad de un sink ajeno; lo
  declara como obligación del sink. Si `save` lanza o el checkpoint no es serializable, el resultado es
  `motive='checkpoint_write_failed'` y el estado previo debe quedar intacto (AV-03).
- Si `store is None`: `checkpoint_written=False` y `checkpoint_digest=None`; el estado vive sólo en memoria y
  en `export_checkpoint()`.
- **Ningún** módulo abre ficheros: un sink sobre disco, sobre el almacén de proyectos o sobre un servicio del
  llamador es responsabilidad del llamador; el contrato sólo fija la clave y el momento de la escritura.

### 3.5 Protocolo `lease` (exclusividad, sin acoplarse a `engine/coordination.py`)

```python
acquire(agent_id: str, ttl_seconds: int) -> {'acquired': bool, 'owner': str | None,
                                             'expires_at': str | None, 'previous_owner': str | None,
                                             'event': str}
renew(agent_id: str, ttl_seconds: int) -> mismo dict
release(agent_id: str) -> mismo dict
```

- La implementación adaptadora sobre `CoordinationStore.apply('lease-acquire' | 'lease-renew' | 'lease-release', …)`
  (`engine/coordination.py:23,220`) la decide `t23`; **`coordination.py` no se modifica**.
- `lease_held` ⇒ `stop_reason='lease_held'`, `cycles=0`, sin checkpoint y sin recibo (AV-23).
- Arriendo vencido ⇒ se toma y se registra `event='lease_expired'` con `previous_owner` y `at` (AV-24); el
  primer ciclo continúa desde el checkpoint más reciente (`store.load`).

---

## 4. Checkpoint v1 (esquema congelado)

### 4.1 Esquema máquina-legible

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:orgdna:team:checkpoint:1",
  "title": "TeamProcess checkpoint v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["checkpoint_version", "schema", "mode", "coordinator_slot", "roster", "cycle", "step",
               "steps_total", "cycle_state", "resumptions", "members", "results", "delegations",
               "waves", "budget", "loop", "created_at", "updated_at"],
  "properties": {
    "checkpoint_version": {"const": 1},
    "schema": {"const": "orgdna.team_process.checkpoint/1"},
    "mode": {"enum": ["sequential", "hierarchical", "parallel_waves"]},
    "coordinator_slot": {"type": ["integer", "null"], "minimum": 1, "maximum": 32},
    "roster": {
      "type": "array", "minItems": 1, "maxItems": 32,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["slot", "member_id", "role", "is_coordinator", "delegates_to"],
        "properties": {
          "slot": {"type": "integer", "minimum": 1, "maximum": 32},
          "member_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{1,63}$"},
          "role": {"type": "string", "minLength": 1, "maxLength": 120},
          "is_coordinator": {"type": "boolean"},
          "delegates_to": {"type": "array", "items": {"type": "integer"}}
        }
      }
    },
    "cycle": {"type": "integer", "minimum": 0},
    "step": {"type": "integer", "minimum": 0},
    "steps_total": {"type": "integer", "minimum": 0},
    "cycle_state": {"enum": ["not_run", "running", "incomplete", "completed", "budget_exhausted"]},
    "resumptions": {"type": "integer", "minimum": 0},
    "members": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["slot", "state", "steps"],
        "properties": {
          "slot": {"type": "integer"},
          "state": {"enum": ["pending", "running", "success", "failed", "skipped"]},
          "steps": {"type": "integer", "minimum": 0}
        }
      }
    },
    "results": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["slot", "state", "result", "cycle", "step"],
        "properties": {
          "slot": {"type": "integer"},
          "state": {"enum": ["success", "failed"]},
          "result": {},
          "cycle": {"type": "integer", "minimum": 0},
          "step": {"type": "integer", "minimum": 0}
        }
      }
    },
    "delegations": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["delegation_id", "from_slot", "to_slot", "state", "cycle", "result", "closed_at"],
        "properties": {
          "delegation_id": {"type": "string", "minLength": 1},
          "from_slot": {"type": "integer"},
          "to_slot": {"type": "integer"},
          "state": {"enum": ["open", "closed"]},
          "cycle": {"type": "integer", "minimum": 0},
          "result": {},
          "closed_at": {"type": ["string", "null"]}
        }
      }
    },
    "waves": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["size", "index", "total", "closed", "slots"],
      "properties": {
        "size": {"type": "integer", "minimum": 1, "maximum": 32},
        "index": {"type": "integer", "minimum": 0},
        "total": {"type": "integer", "minimum": 1},
        "closed": {"type": "integer", "minimum": 0},
        "slots": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}
      }
    },
    "budget": {
      "type": "object", "additionalProperties": false,
      "required": ["declared", "consumed", "exhausted"],
      "properties": {
        "declared": {"type": "object", "additionalProperties": false,
          "required": ["steps", "seconds", "delegations", "tokens"],
          "properties": {"steps": {"type": ["integer", "null"]}, "seconds": {"type": ["number", "null"]},
                         "delegations": {"type": ["integer", "null"]}, "tokens": {"type": ["integer", "null"]}}},
        "consumed": {"type": "object", "additionalProperties": false,
          "required": ["steps", "seconds", "delegations", "tokens"],
          "properties": {"steps": {"type": "integer", "minimum": 0}, "seconds": {"type": "number", "minimum": 0},
                         "delegations": {"type": "integer", "minimum": 0}, "tokens": {"type": "integer", "minimum": 0}}},
        "exhausted": {"type": ["object", "null"], "additionalProperties": false,
          "required": ["reason"],
          "properties": {"reason": {"enum": ["steps", "seconds", "delegations", "tokens"]}}}
      }
    },
    "loop": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["cycles", "stop_reason", "receipts", "receipts_omitted", "write_failures", "lease"],
      "properties": {
        "cycles": {"type": "integer", "minimum": 0},
        "stop_reason": {"type": ["string", "null"]},
        "receipts": {"type": "array", "maxItems": 256, "items": {"type": "object"}},
        "receipts_omitted": {"type": "integer", "minimum": 0},
        "write_failures": {"type": "integer", "minimum": 0},
        "lease": {"type": ["object", "null"]}
      }
    },
    "created_at": {"type": "string"},
    "updated_at": {"type": "string"}
  }
}
```

### 4.2 Reglas de obligatoriedad

- **Todas** las claves de `required` deben existir, incluidas `loop` (`null` cuando el proceso se usa suelto)
  y `waves` (`null` fuera de `parallel_waves`).
- Los arrays `roster`, `members`, `results`, `delegations` van en **orden canónico** (§5, D1).
- `result` admite cualquier valor JSON (objeto, número, texto, `null`); lo que **no** admite es un objeto no
  serializable.
- `loop.receipts` guarda como máximo `MAX_CHECKPOINT_RECEIPTS`; el resto se resume en `receipts_omitted`.
- `loop.cycles` cuenta **intentos** de ciclo; `loop.write_failures` cuenta los intentos cuya escritura falló,
  de modo que los ciclos durables son `cycles - write_failures` (AV-03: 3 intentos, 1 fallo, 2 durables).

### 4.3 Versión y compatibilidad hacia atrás

| Regla | Enunciado |
| --- | --- |
| V-1 | `checkpoint_version` es `int`; v1 lectores aceptan **sólo** `1` y `schema == CHECKPOINT_SCHEMA`. Cualquier otro valor ⇒ `unsupported_checkpoint_version` listando las versiones conocidas (`[1]`), **cero** miembros avanzados y **cero** reescritura o degradación (AV-02). |
| V-2 | Claves desconocidas, claves faltantes o tipos fuera de §4.1 ⇒ `checkpoint_shape_invalid` (fail-closed): un lector v1 **nunca** interpreta un checkpoint v2 recortado. |
| V-3 | La evolución aditiva dentro de v1 **no** está permitida. Añadir una clave, cambiar un tipo o cambiar semántica exige `checkpoint_version=2` y `schema='orgdna.team_process.checkpoint/2'`, con lector v2 propio. El lector v1 rechaza v2; nunca lo degrada. |
| V-4 | Un checkpoint v1 escrito por `t22` debe poder reanudarse con `t23` y, tras `t30`, con el código verbatim: la forma es la invariante, el algoritmo no. |
| V-5 | `loop` es opcional en la práctica (`null`), pero la clave es obligatoria: un proceso suelto no finge estado de bucle. |

### 4.4 Digest

```python
TeamProcess.checkpoint_digest(checkpoint)  # -> sha256 hex del JSON canónico (§1)
```

El digest **no** se almacena dentro del checkpoint (evita autorreferencia). Es el valor que el recibo cita en
`checkpoint_digest` y el que un test compara byte a byte para demostrar que un ciclo fallido no reescribió el
estado (AV-03).

---

## 5. Determinismo y orden (reglas vinculantes)

| Id | Regla | Cómo se comprueba |
| --- | --- | --- |
| **D1** | **Orden canónico = `slot` ascendente** en roster, `members`, `results`, `delegations` (por `(cycle, delegation_id)`), olas y listas de recibos. | AV-11, AV-12, AV-13 |
| **D2** | Los resultados se consolidan por **orden de entrada** (`slot`), **nunca** por orden de finalización ni por orden de inserción en el `Mapping` del worker. | AV-11 (el slot 4 responde antes que el 2), AV-13 (finalizan 3,1,2 y se consolidan 1,2,3) |
| **D3** | Reloj **inyectable** (`clock() -> float` epoch, defecto `time.time`), con el formateo del repo (§1). Sin reloj no hay marcas ni presupuestos de tiempo. | AV-17 (6 s observados con límite 5 s) |
| **D4** | **Cero `random` global**: el módulo no importa `random`; cualquier backoff es función determinista de `(seed, cycle)` con `seed` inyectada. | búsqueda AST de import de `random` = 0; dos corridas con la misma semilla dan el mismo recibo |
| **D5** | **Cero dependencia del hash/orden de `dict`/`set`**: ninguna decisión ni salida puede depender de la iteración de un conjunto; el digest usa JSON canónico. | el mismo estado exporta el mismo digest en dos procesos con `PYTHONHASHSEED` distinto |
| **D6** | Sólo el reloj inyectado puede introducir variación temporal; nada de `datetime.now()` ni `time.time()` directos fuera del defecto del constructor. | AST: 0 llamadas a `now(`/`time()` fuera del defecto |
| **D7** | `status()`/`export_checkpoint()` devuelven **copias**; mutarlas no altera el proceso ni el checkpoint. | prueba de mutación del resultado |
| **D8** | Un ciclo cerrado no se reabre: `cycle_state` de cierre se conserva hasta que `run()` abre el ciclo siguiente e incrementa `cycle`. | tabla de §6.3 |

---

## 6. Máquina de estados

### 6.1 Estados de ciclo (`cycle_state`)

`not_run` → `running` → {`completed`, `incomplete`, `budget_exhausted`}; luego `run()` abre el ciclo
siguiente: `{completed|incomplete|budget_exhausted}` → `running` con `cycle+1`.

| Transición | ¿Válida? | Condición |
| --- | --- | --- |
| `not_run → running` | sí | primera unidad de trabajo del ciclo 1 |
| `running → running` | sí | unidad aplicada sin cerrar el ciclo |
| `running → completed` | sí | **sequential**: todos los slots en `success`/`failed`; **hierarchical**: 0 delegaciones abiertas y coordinador cerrado; **parallel_waves**: última ola cerrada |
| `running → incomplete` | sí | no queda trabajo accionable (ningún slot `pending`/`running` puede avanzar) y hay delegaciones abiertas (AV-04) |
| `running → budget_exhausted` | sí | el siguiente avance excedería un techo (§7) (AV-16) |
| `completed/incomplete/budget_exhausted → running` | sí | `run()` abre ciclo `cycle+1` |
| `not_run → completed/incomplete/budget_exhausted` | **no** | un ciclo sin trabajo no finge cierre (AV-07, AV-21) |
| `completed → incomplete` | **no** | un ciclo cerrado no se reabre (D8) |
| `completed → completed` sin `cycle+1` | **no** | exigiría reabrir |
| `budget_exhausted → completed` sin ciclo nuevo | **no** | el techo es pegajoso hasta un ciclo nuevo |
| `incomplete → completed` sin cerrar delegaciones | **no** | AV-04 |

### 6.2 Estados de miembro

`pending` (no avanzado en el ciclo) · `running` (en curso dentro de una ola o delegación) · `success` ·
`failed` · `skipped` (no se avanzó porque el ciclo cerró por techo o por delegación abierta).

Prohibidas: `success → pending` dentro del mismo ciclo; `skipped → success` en el mismo ciclo; cualquier
estado distinto de `pending` al abrir un ciclo nuevo.

### 6.3 Reglas por modo

**`sequential`**
- Un paso = el slot `pending` de menor valor; estrictamente uno tras otro (nada de adelantar slots).
- El ciclo cierra `completed` cuando todos los slots están en `success`/`failed`.
- Prohibido: avanzar el slot 3 con el slot 2 en `pending`.

**`hierarchical`**
- `coordinator_slot` (declarado, o el menor) es el único responsable del cierre; `is_coordinator=True` en dos
  miembros ⇒ `invalid_roster`.
- El coordinador **delega** (`delegation_id` determinista = `f'{cycle}:{from_slot}:{to_slot}:{n}'`), lo que
  crea delegaciones `open`; cada delegación se cierra con el `outcome` del slot destino, que **vuelve al
  coordinador** (AV-09).
- Dos delegaciones del mismo coordinador se consolidan **por slot** aunque el destino responda antes el de
  slot mayor (AV-11).
- Delegar a un slot inexistente o no permitido por `delegates_to` ⇒ `unknown_member` con slot y roster
  declarado; no se crea delegación y el ciclo sigue reanudable (AV-10).
- Cerrar con delegaciones `open` ⇒ `incomplete` con la lista de slots pendientes; **jamás** `completed`
  (AV-04).

**`parallel_waves`**
- Partición determinista del roster ascendente en olas de `wave_size`: roster 1..5, tamaño 2 ⇒
  `[[1,2],[3,4],[5]]` (AV-12).
- Las olas **no se solapan**: la ola `i+1` no empieza hasta cerrar la `i`; a mitad de ola el estado es
  `running` con los slots ya cerrados en `success` y el resto en `pending` (AV-14).
- Los resultados de una ola se consolidan por slot (AV-13).
- `wave_size` inválido ⇒ `invalid_wave_size` y **el checkpoint no se escribe** (AV-15).

---

## 7. Presupuestos

### 7.1 Dimensiones

`budget = {'steps': int|None, 'seconds': number|None, 'delegations': int|None, 'tokens': int|None}`, todas
opcionales; `None` = sin techo declarado. Los **tres topes del contrato** son `steps`, `seconds` y
`delegations`; `tokens` es la cuarta dimensión de coste que exige el vector AV-16 y usa el mismo mecanismo.

Validación: clave desconocida, valor negativo, booleano o no numérico ⇒ `invalid_budget`; cero contadores
escritos y tras un ciclo válido los contadores son **monótonos no decrecientes** (AV-18).

### 7.2 Estado de agotamiento (`exhausted`)

Antes de aplicar una unidad, si excedería un techo: `cycle_state='budget_exhausted'`,
`budget.exhausted={'reason': <primera dimensión excedida en el orden de `EXHAUSTION_REASONS`>}`, y el
consumo declarado es el real (**nunca negativo**) (AV-16: tokens 100, paso 2 consume 90, el paso 3 no se
ejecuta y `consumed.tokens=90`).

`reason ∈ ('steps', 'seconds', 'delegations', 'tokens')`. `remaining[d] = max(declared[d] - consumed[d], 0)`
o `null` si no hay techo.

### 7.3 Presupuesto del bucle (por ciclo)

`TeamLoop` acepta `budget={'seconds': number|None, 'tokens': int|None}`. Al excederse:
`stop_reason='time_exhausted'` (tiempo) o `stop_reason='budget_exhausted'` (tokens), el ciclo cierra con lo
avanzado y el recibo declara `budget_consumed` con el valor observado y el límite (AV-17: 6 s observados,
límite 5 s).

---

## 8. Contrato de reanudación

### 8.1 Qué **no** se reejecuta

| Unidad | Regla |
| --- | --- |
| Slot con `members[slot].state == 'success'` en el ciclo en curso | **no** se vuelve a pedir al worker ni se aplica de nuevo |
| Delegación `closed` | **no** se reabre; su `result` se conserva (AV-09) |
| Ola `closed` | **no** se reejecuta; `waves.closed` no decrece (AV-12/AV-14) |
| Ciclo cerrado del bucle | **no** se repite; `loop.cycles` no retrocede (AV-03, AV-05) |
| Contadores de presupuesto | **no** se reinician al reanudar; sólo crecen (AV-18) |

### 8.2 Qué **sí** se repite (declarado)

- Un slot en `running` al guardar el checkpoint se vuelve a pedir: su resultado no era durable.
- Un slot en `pending` se pide en el intento reanudado (es trabajo no hecho).
- Si un ciclo del bucle falló al escribir el checkpoint (`checkpoint_write_failed`), ese ciclo **se
  reintenta** al reanudar y su contador de pasos no se incrementó (AV-03: pasos avanzados 2, nunca 3).
- `import_checkpoint` incrementa `resumptions` (AV-01: `resumptions=1`).

### 8.3 Cómo se demuestra que un paso completado no se reejecuta

Evidencia **obligatoria** en las pruebas de `t22`/`t23` (y en la paridad de `t30`):

1. **Contador por slot.** `members[slot].steps` sólo crece cuando se aplica un `outcome` a ese slot. En AV-01,
   tras reanudar un checkpoint con `slot1`/`slot2` en `success`, sus `steps` no cambian.
2. **Contador de efectos del llamador.** El worker (o el test) incrementa un contador externo por invocación;
   al reanudar, las invocaciones deben ser exactamente las de los slots **no** completados. Un solo
   reinicio indebido hace fallar la prueba.
3. **Digest.** `checkpoint_digest` antes y después del intento fallido es idéntico (AV-03); y el digest del
   checkpoint reanudado difiere del anterior sólo en los campos esperados (`resumptions`, contadores,
   `updated_at`).

Ninguna de las tres se sustituye por leer el código: se ejecutan.

---

## 9. Decisiones de diseño que `t30` NO puede cambiar (aunque copie verbatim)

Aunque `t30` sustituya el algoritmo interno por código literal de una fuente COMPATIBLE (con cita
`owner/name@<sha>`, nota `ENMIENDA PERMANENTE - codigo verbatim`, SPDX y paridad en
`tests_team_verbatim_parity.py`), **estas decisiones quedan congeladas**:

| # | Decisión inmutable |
| --- | --- |
| T-1 | Las firmas de §2.1, §2.3, §3.1 y §3.2, con sus nombres, orden de parámetros y valores por defecto. |
| T-2 | `MODES`, `CYCLE_STATES`, `MEMBER_STATES`, `DELEGATION_STATES`, `LOOP_STATES`, `STOP_REASONS`, `RECEIPT_MOTIVES`, `EXHAUSTION_REASONS` y los códigos de error de §1.1. |
| T-3 | El checkpoint v1 de §4 (claves, tipos, `additionalProperties: false`, versión y reglas V-1..V-5). |
| T-4 | El `clock` inyectable con la convención del repo y el digest sobre JSON canónico. |
| T-5 | Orden canónico por `slot` y consolidación por orden de **entrada** (D1/D2). |
| T-6 | Cero `random` global, cero dependencia de hash de `dict`/`set` (D4/D5). |
| T-7 | Los tres topes + `tokens`, el estado `budget_exhausted` y su `reason`. |
| T-8 | La semántica de reanudación de §8, incluido `resumptions` y la no-reejecución de slots completados. |
| T-9 | Los protocolos `store` y `lease` de §3.4/§3.5 y el recibo de §3.3. |
| T-10 | La prohibición de red, hilos, `subprocess`, ficheros, claves y DSH (C-5). |
| T-11 | Los 22 vectores de `docs/rea/agile_vectors.json` como criterio de aceptación observable. |
| T-12 | Que el bucle **no** decide estrategia, no es demonio por defecto y `start()`/`stop()` son opt-in e idempotentes. |

**Exclusiones de la enmienda verbatim (recortar y declarar si aparecen en el fragmento):** exfiltración de
datos o claves; apertura de red o de proveedores; evasión o debilitamiento de las ocho puertas de
`engine/policy_engine.py`; ejecución fuera del sandbox gobernado; cualquier contacto con DSH. Si el fragmento
las contiene, se recorta, se declara el recorte y no se copia esa parte.

---

## 10. Trazabilidad vectores → superficie congelada

| Vector | Superficie que lo satisface |
| --- | --- |
| AV-01 `checkpoint_reanuda…` | `import_checkpoint` + §8 (`resumptions`, `members[*].steps`) |
| AV-02 `checkpoint_de_version_desconocida…` | §4.3 V-1 (`unsupported_checkpoint_version`) |
| AV-03 `el_bucle_lee_y_reescribe…` | §3.2 paso 3 + §3.3 (`checkpoint_write_failed`) + §4.4 |
| AV-04 `delegacion_abierta_impide_cerrar…` | §6.1 (`running → incomplete`) + §6.3 hierarchical |
| AV-05 `parada_entre_ciclos…` | §3.2 `stop()` + §3.3 (recibo inmutable) |
| AV-06 `parada_repetida_es_idempotente` | §3.2 `stop()` idempotente |
| AV-07 `parada_antes_del_primer_ciclo…` | §3.2 `stop()` + `LOOP_STATES` (`not_run`) |
| AV-08 `modo_desconocido_es_error_tipado` | §2.1 (`unknown_mode`) |
| AV-09 `delegacion_jerarquica_devuelve…` | §6.3 hierarchical + `delegations[]` |
| AV-10 `delegacion_a_miembro_inexistente…` | §6.3 hierarchical (`unknown_member`) |
| AV-11 `dos_delegaciones…consolidan_por_slot` | §5 D1/D2 + §6.3 hierarchical |
| AV-12 `olas_paralelas_acotadas…` | §6.3 `parallel_waves` + `waves.slots` |
| AV-13 `resultados_de_ola_en_orden_de_entrada` | §5 D2 + `results[]` |
| AV-14 `una_ola_no_se_solapa…` | §6.3 `parallel_waves` + `MEMBER_STATES` |
| AV-15 `tamano_de_ola_invalido…` | §2.1 (`invalid_wave_size`) |
| AV-16 `presupuesto_de_tokens_agotado…` | §7.1/§7.2 (`budget_exhausted`, `reason='tokens'`) |
| AV-17 `presupuesto_de_tiempo_agotado…` | §7.3 + §3.3 (`time_exhausted`) |
| AV-18 `presupuesto_invalido_o_negativo…` | §7.1 (`invalid_budget`) + monotonía |
| AV-20 `cada_ciclo_cerrado_emite_recibo…` | §3.3 (`RECEIPT_MOTIVES`) |
| AV-21 `cero_ciclos_cero_recibos` | §3.2 `run(0)` + §3.3 |
| AV-23 `dos_bucles_no_duplican_trabajo` | §3.5 (`lease_held`) |
| AV-24 `arrendamiento_vencido_se_toma…` | §3.5 (`lease_expired`) |

Los vectores `followups` (2) y `sandbox_executor` (2) del mismo barrido pertenecen a módulos ya existentes
(`engine/followups.py`, `engine/sandbox_executor.py`) y **no** forman parte de este contrato.

**Lectura de congelamiento de `agile_vectors.json`:** `sha256 =
a8a498fda5a44132647ddef746cf8813cc77293a95ae7ae1c26e81c8cb7279e8`, 31 025 bytes, 26 vectores totales de
los cuales **22** son `team_process`/`team_loop` (ids en la tabla de arriba: `AV-01…AV-18`, `AV-20`,
`AV-21`, `AV-23`, `AV-24`). `t21` puede **añadir** vectores mientras corre el barrido: un vector nuevo se
incorpora a las pruebas de `t22`/`t23` y a la paridad de `t30` **sin cambiar la API** de este contrato, y se
anota en el acta de M0. Lo que no puede cambiar sin `v2` son §2, §3, §4, §6 y §9.

---

## 11. Verificación de este contrato

Comprobaciones ejecutadas al congelar (script de lectura, sin escribir nada fuera de este archivo):

1. El bloque `json` de §4.1 parsea con `json.loads` y su `required` es exactamente la lista de 18 claves
   congeladas.
2. `MODES`, `CYCLE_STATES`, `MEMBER_STATES`, `LOOP_STATES`, `STOP_REASONS`, `RECEIPT_MOTIVES`,
   `EXHAUSTION_REASONS` y `PROCESS_ERROR_CODES`/`LOOP_ERROR_CODES` aparecen en §1 con sus valores.
3. Las cuatro firmas exigidas (`TeamProcess(...)`, `step`, `run(limit)`, `status`, `export_checkpoint`,
   `import_checkpoint`; `TeamLoop(process, channel, store, clock)`, `run(cycles)`, `start`, `stop`, `status`,
   `history`) están escritas en §2/§3.
4. Los 22 identificadores `AV-01…AV-24` de `team_process`/`team_loop` están en la tabla de §10.
5. El documento no contiene código ejecutable del producto: es contrato.

---

## 12. Lo que este contrato NO decide (libertad de implementación)

- La estructura interna de clases, helpers y nombres privados.
- Cómo se persiste el checkpoint (fichero, JSONL, base local): lo decide el llamador; los módulos no abren
  ficheros (C-5).
- La redacción de los mensajes de error (sólo se congelan los `code`).
- El adaptador concreto de `lease` sobre `engine/coordination.py` (se congela el protocolo, no la clase).
- El algoritmo de backoff, siempre que sea determinista con `seed` y no supere el presupuesto.
- La decisión de `t30` sobre qué fragmentos valen la pena copiar verbatim: la gobiernan
  `docs/rea/license_audit.md` (t29) y §9 de este documento.
