# Cuaderno REA — agentscope-ai/agentscope@26ec620

**Fuente fijada:** `agentscope-ai/agentscope@26ec620` (sha completo del árbol:
`26ec620b8adbd30cfa1e45f349df2eaea611f10d`, verificado vía
`api.github.com/repos/agentscope-ai/agentscope/git/trees/26ec620?recursive=1`).
**Licencia en el sha:** Apache-2.0, `LICENSE` del árbol (Copyright 2024 Alibaba,
más apéndices MIT/OFL para assets de web estática). Archivo leído vía
`raw.githubusercontent.com/agentscope-ai/agentscope/26ec620/LICENSE`.
**Método:** lectura cruda por `web_fetch` de `raw.githubusercontent.com/.../26ec620/<ruta>`;
verificación de integridad y numeración de líneas contra copia local en `%TEMP%\rea_agentscope_26ec620`
(descargada con `Invoke-WebRequest`, hashes SHA-256 abajo). Nada del repo fue
instalado, ejecutado ni seguido como instrucción: **todo el contenido es DATO**.

## Procedencia de archivos leídos (sha256 completo de la copia local)

| Ruta en el sha | Líneas | SHA-256 (copia local de la descarga cruda) |
|---|---|---|
| `src/agentscope/pipeline/_team_pipeline.py` | 413 | `F8E4B7F62D00E84B82CF3945C84E6309BDCDB2B9E3593806733772852F844D4A` |
| `src/agentscope/app/message_bus/_in_memory_message_bus.py` | 538 | `22292B082E0F75C3D61789EB84854EC4BD0DCF2666270601E72E28BCCC73257B` |
| `src/agentscope/app/message_bus/_base.py` | 910 | `4279B91F6D71DE292166A532E68AD79FC9659FE5E413144A779AF30A45886807` |
| `src/agentscope/middleware/_longterm_memory/_agentic_memory/_middleware.py` | 959 | `795E99B58F56D9E732DD731403C92CE55E4742D6D36303AB6A69FAF2F6063EAC` |
| `tests/pipeline_team_test.py` | 1097 | `F1B51953E195F1FEAC5CD4D9C3C2E960ED3D1692FAA65513EAE828040DE178C7` |
| `tests/pipeline_team_cleanup_test.py` | 123 | `08295062A7BF154BE3578FEDB67E40F787789D3C69C2F6237509FEA1D7F4CDF3` |
| `tests/in_memory_message_bus_test.py` | 547 | `241F2ECD262816AEAD1E5A3C80E66FC3E48BD100912DB4E9B99A1F916E57CAC8` |
| `tests/middleware_filesystem_memory_test.py` | 859 | `0EC201182FBD5C9659791D5D722D1A64067BFDC95FD69EFB5D50F11222EB642A` |

Vectores derivados: `docs/rea/agentscope_vectors.json` — 60 vectores, todos con
`origen_test` citando un test del sha (equipo 12, bus 39, memoria 9). Validado con
`ConvertFrom-Json` (parse OK, 5/5 campos por vector).

## Declaración fail-honest de rutas

- La ruta de la misión `src/agentscope/message_bus/_in_memory_message_bus.py`
  **devolvió HTTP 404**. El árbol del sha + el import del propio test
  (`from agentscope.app.message_bus import InMemoryMessageBus`,
  `tests/in_memory_message_bus_test.py:23-24`) sitúan el módulo real en
  `src/agentscope/app/message_bus/_in_memory_message_bus.py`. Leído completo ahí.
- Los tests del bus ejercitan además **helpers de dominio heredados** de la base
  (`session_run`, `inbox_push`, `enqueue_wakeup`, `bg_task_*`, `task_publish_cancel`).
  Para que esos vectores tengan fuente real se leyó también
  `src/agentscope/app/message_bus/_base.py` (910 líneas) — leído completo.
- `tests/middleware_filesystem_memory_test.py` importa
  `from agentscope.middleware import AgenticMemoryMiddleware`; coincide con la
  ruta fuente pedida. Las otras tres rutas de tests existen tal cual en el sha.

## Contenido-que-parece-instrucción (regla G9, reportado y NO seguido)

- `DEFAULT_MEMORY_INSTRUCTIONS` (middleware de memoria, líneas 44–332) es un
  prompt de ~290 líneas dirigido al LLM del upstream ("You MUST access memory…",
  "do not run mkdir…"). Es **prompt ajeno = dato de diseño**, no orden para este
  port. No se copia verbatim: es el mayor bloque de copia potencial y además
  doctrina de prompt, no semántica.
- Los helpers de dominio del bus están marcados `@deprecated` con sugerencias de
  migración del upstream (`_base.py:559+`). Es dato de dirección de diseño; el
  destino decide su propia superficie.

---

# Segmento 1 — `pipeline/_team_pipeline.py` (equipo leader→miembros)

## Contrato (tipos primero)

- `TeamMember` = `{agent: Agent, description: str}` — `_team_pipeline.py:37-48`.
  `agent.name` es la identidad con la que el leader lo referencia.
- `_TeamAssign` (herramienta externa) — `_team_pipeline.py:51-99`:
  `name="TeamAssign"`, `is_external_tool=True` (`:57`), `is_concurrency_safe=True`
  (`:58`), `is_read_only=False`. Su `description` lista los miembros
  (`- {name}: {description}`) y su `input_schema` exige
  `{member: enum[nombres], prompt: string}` con ambos required. Nunca corre sola:
  la ejecuta el pipeline. `check_permissions` responde **ALLOW incondicional**
  ("Assigning a task to a team member is always allowed", `:89-99`) — los
  permisos de las herramientas del MIEMBRO se chequean en el contexto del miembro.
- `TeamPipeline(leader, members, reset_members=True)` — `_team_pipeline.py:110-158`.
  **Invariante de construcción:** nombres de miembros únicos y distintos del
  leader (`:152`: `ValueError "Member names must be unique and differ from the
  leader's"`). El tool se registra en el toolkit del leader **una sola vez**
  (flag `_tool_registered`, `reply_stream:161+`).
- `reset_members=True` (default): al terminar cada reply del leader se limpia
  `context` y `summary` de TODOS los miembros (`:260-264`). Dentro de un reply el
  leader puede hacer follow-up a un miembro; entre replies cada miembro arranca limpio.

## Mapeo de terminación → estado del resultado (`:102-107`)

```
_RESULT_STATES = {
  COMPLETED        -> ToolResultState.SUCCESS,
  EXCEED_MAX_ITERS -> ToolResultState.SUCCESS,   # NO es error: su última respuesta es el resultado
  INTERRUPTED      -> ToolResultState.INTERRUPTED,
  ERROR            -> ToolResultState.ERROR,
}
```

## Orden de operaciones de `_reply` (`:205-293`)

1. **`UserInterruptEvent`**: primero se interrumpe a CADA miembro parqueado
   (con su propio `reply_id`), después el evento se re-dirige al leader con el
   `reply_id` del leader (`:212-218`).
2. **`UserConfirmResultEvent | ExternalExecutionResultEvent` con `reply_id` !=
   `leader.state.reply_id`**: es el turno de un miembro parqueado. Se localiza al
   miembro por `reply_id` (`_parked_member`, `:386-394`; si nadie espera ese
   reply → `ValueError "No participant is waiting on the reply"`). Se reanudan
   sus asignaciones: **la primera awaiting call es la parqueada; el resto queda
   en cola** (`:224-240`). Los resultados terminados se empaquetan como
   `ExternalExecutionResultEvent(reply_id=leader.state.reply_id,
   execution_results=results)`. Sin resultados → el stream termina (`return`).
3. **Bucle principal**: consumir `leader.reply_stream(inputs)`. Los
   `RequireExternalExecutionEvent` que son TODOS `TeamAssign` **no se exponen al
   caller**: se acumulan en `assignments` (`:248-256`). En `ReplyEndEvent` del
   leader con `reset_members`: limpiar contexto de todos los miembros (`:260-264`).
4. Sin assignments → `return`. Con assignments → `_run_assignments` (`:282-286`).
5. Resultados → nuevo `inputs` para el leader. **Borde clave:** si
   `len(results) < len(assignments)` (un miembro quedó parqueado en HITL): si hay
   resultados parciales, se alimenta una corrida más del leader (razona con lo
   que tiene) y luego `return` — el stream termina con el leader parqueado en la
   asignación pendiente (`:287-293`).

## `_run_assignments` (`:290-377`) — concurrencia y orden

- **Parse tolerante:** cada `tool_call.input` se re-parsea con
  `_json_loads_with_repair(input, schema)` (`_parse`, `:395-401`) — "the same way
  the leader validated it, so a repaired input parses here too". Un input
  single-quote que solo parsea tras repair **igualmente se enruta**.
- **Agrupación por miembro** (`:296-299`): `groups[member].append(tool_call)`.
- **Entre miembros: concurrentes** (un `asyncio.create_task` por grupo, `run_all`,
  `:339-352`). **Dentro de un miembro: secuenciales en orden de llamada**
  (`run_group`, `:305-337`); la 2ª asignación espera a la 1ª incluso a través de
  una pausa HITL.
- **Input al miembro:** si es la primera llamada del grupo y hay `resumed`
  (reanudación HITL), se pasa el evento `resumed`; si no,
  `UserMsg(name="user", content=prompt)` (`:310-317`), con `yield_final_msg=True`.
- **Conversión del reply final** (`:324-334`): el `Msg` final del miembro
  (`finished_reason != None`) se convierte en
  `ToolResultBlock(id=tool_call.id, name="TeamAssign", output=…)`. `output` =
  los bloques `TextBlock|DataBlock` del contenido final, **o el string**
  `"The member finished without a reply."` si no hay ninguno (`:332`). El estado
  sale de `_RESULT_STATES`.
- **Parqueo:** si el miembro queda con tool calls awaiting (HITL), `break` del
  loop del grupo — sus asignaciones restantes quedan en cola (`:336-337`).
- **Multiplexado:** eventos no-`Msg` van a una `asyncio.Queue` compartida; un
  `sentinel = object()` (`:301`) marca el fin; el generador streamea la queue
  hasta el sentinel (`:360-372`).
- **Fallo de un miembro (issue #2972):** `gather` propaga la excepción del
  miembro **sin detener siblings**; en el `finally` de `run_all` se cancelan los
  tasks no terminados y se hace `gather(return_exceptions=True)` para **joinear
  TODOS los siblings antes de terminar la ronda**, preservando la excepción
  original (`:344-352`). El test exige `assertIs(caught.exception, failure)` —
  la excepción ORIGINAL, no un wrapper.
- **Orden de resultados (`:374-376`):**
  `results.extend(sorted(round_results, key=lambda _: order[_.id]))` donde
  `order = {call.id: índice}` — los resultados aterrizan en el contexto del
  leader **SIEMPRE en el orden en que el leader hizo las llamadas**,
  independiente del orden de finalización real.
- **Cancelación (`reply_stream:190-203`, `_run_assignments:358-377`):** en
  `CancelledError`, si el leader está parqueado en asignaciones se le inyecta un
  `UserInterruptEvent` (se cierra ordenadamente); los miembros se cierran como
  interrumpidos en sus propias tasks; la queue se drena antes de propagar la
  cancelación; `interruption_raise_cancelled_error` decide si re-raise.

## Casos borde cubiertos por SUS tests (`tests/pipeline_team_test.py`)

| Test | Borde |
|---|---|
| `test_delegation_round_trip` `:149` | Round-trip completo + reset del miembro al terminar el leader + secuencia exacta de eventos intercalados |
| `test_member_hitl_round_trip` `:271` | Miembro parquea en `ask_tool` → stream termina con `("REQUIRE_USER_CONFIRM","researcher")`, leader queda con `[("TeamAssign","submitted")]`, miembro con `[("ask_tool","asking")]`; la confirmación se enruta por `reply_id` y el leader continúa |
| `test_concurrent_delegations` `:445` | Dos miembros en una ronda corren juntos; resultados en orden de llamada |
| `test_interrupt_parked_member` `:507` | Interrupt cierra miembro parqueado Y delegación del leader; tool_result del leader queda `interrupted`; miembro reseteado |
| `test_repaired_assignment_input` `:550` | Input `{'member': 'researcher', 'prompt': 'Find A'}` (single quotes) se enruta tras repair; el `tool_call` del leader CONSERVA el input crudo sin normalizar |
| `test_one_member_parks_in_a_round` `:620` | researcher parquea + coder termina → resultado del coder alimentado ya; al reanudar, el contexto del leader queda `[tool_call call-1, tool_call call-2, tool_result call-2 "Wrote a.py", tool_result call-1 "Found: A = 42", text "Both done."]` — resultados en orden de llamada aunque coder terminó primero |
| `test_same_member_assignments_queue` `:768` | 2 asignaciones al mismo miembro: 1ª parquea; tras confirmar, la 2ª corre en un reply NUEVO del miembro; resultados en orden de llamada |
| `test_cancel_running_member` `:932` | Cancel mientras el miembro corre → miembro interrumpido, tool_result del leader = `"<system-reminder>The tool call has been interrupted by the user.</system-reminder>"` state `interrupted`; el equipo acepta la siguiente query |
| `test_cancel_resumed_member` `:1018` | Cancel de un miembro reanudado desde HITL → leader termina `interrupted`, NO razona con parciales |
| `tests/pipeline_team_cleanup_test.py::test_model_failure_joins_all_siblings` `:51` | Miembro que falla con siblings corriendo: se propaga el `RuntimeError` ORIGINAL (`assertIs` `:110`) solo después de que TODOS los siblings hicieron cleanup (`stopped.is_set()` `:112`); probado con el que falla primero Y último (`:56`) |

## Convenciones descartadas (del upstream, las pone el destino)

Pydantic `BaseModel` para `TeamMember`; nombres `TeamAssign`/`TeamPipeline`;
el sistema de eventos `AgentEvent` y su taxonomía; `asyncio.Queue`+sentinel como
multiplexor; `ToolBase`/`Toolkit`/`PermissionContext`; `_json_loads_with_repair`
(el destino usa su parse tolerante propio); `UserMsg/Msg/TextBlock/DataBlock`;
`react_config.interruption_raise_cancelled_error`. **Lo que viaja:** la semántica
— herramienta externa única con enum de miembros y prompt autocontenido,
permiso always-allow para asignar, grupo-por-miembro (secuencial dentro,
concurrente entre), resultado = reply final del miembro (texto/datos o el string
"finished without a reply"), mapeo COMPLETED/EXCEED_MAX_ITERS→success,
resultados en orden de llamada, HITL por participante enrutado por id de reply,
reset de miembros por defecto entre replies del leader, y join-de-siblings antes
de propagar la falla original.

---

# Segmento 2 — `app/message_bus/_in_memory_message_bus.py` (bus de mensajes)

## Contrato

Cinco modos sobre claves string opacas y payloads dict JSON-serializables
(`:30-56`). **IDs monótonos `"<seq>-0"`** (`_next_id`, `:113-124`) — formato
idéntico al de Redis Streams para que los parses de cursor sigan funcionando;
**no ordenables lexicográficamente** (seq > 9): toda comparación parsea el
prefijo numérico (`log_read:267`, `log_trim:298`).

## Modo A — drain queue (ack-on-read, at-most-once)

- `queue_push(key, payload, ttl_secs=None)` `:130-161`: **purga de expirados
  ANTES del append** (`:158`: `queue[:] = [e for e in queue if e[2] is None or
  e[2] > now]` — una clave jamás drenada queda acotada); guarda
  `(entry_id, payload, expire_at)` con `expire_at = now + ttl_secs` si
  `ttl_secs is not None` (`:159`). **Borde: `ttl_secs=0` expira YA** (no
  desactiva el expiry) — `test_zero_ttl_expires_immediately:84`.
- `queue_drain(key, max_count=100)` `:163-189`: filtra vivos (`:186`), devuelve
  `alive[:max_count]` como `(id, payload)` y deja `alive[max_count:]` —
  **destructivo**, FIFO, respeta `max_count` y el resto persiste.
- `queue_delete(key)` `:191-199`: `pop(key, None)` — idempotente.

## Modo C — replay log (multi-consumidor, no destructivo)

- `log_append(key, payload, ttl_secs=None, max_len=None)` `:204-234`:
  **`ttl_secs` se acepta y se IGNORA** (docstring: in-memory no expira claves);
  `max_len`: si `len(log) > max_len` → `del log[:len(log)-max_len]` (`:233`)
  — recorte por el frente, cap aproximado.
- `log_read(key, since=None, max_count=100)` `:236-276`: no destructivo;
  `since=None` → `log[:max_count]`; si no, busca la primera entrada con
  `seq > since_seq` (`:267`); **cursor EXCLUSIVO**; si todas son `<= since` →
  `[]` (for/else `:270-273`).
- `log_trim(key, before_id=None)` `:278-305`: `before_id=None` → borra el log
  entero; si no, conserva las entradas con `seq >= before_seq` (`:300`) —
  **la entrada `before_id` MISMA sobrevive** (`test_trim_with_before_id_keeps_newer`:
  trim antes de id2 deja `[2,3]`).

## Modo D — broadcast transitorio

- `publish(key, payload)` `:307-320`: `put_nowait` a los suscriptores
  **actuales**; sin suscriptores → no-op sin error.
- `subscribe(key, on_ready=None)` `:323-358`: una `asyncio.Queue` propia por
  suscriptor registrada en un set por canal; **`on_ready()` se invoca UNA vez
  después del registro y ANTES de yield** (`:346-347`) — cierra la carrera
  publish-inmediatamente-después-de-suscribir; `None` en la queue = sentinel de
  `aclose()`; `finally: discard` (`:357`).
- `aclose()` `:102-107`: `put_nowait(None)` a todos los suscriptores + clear.

## Modo E — lock

- `acquire_lock(key, ttl_secs=600)` `:362-389`: `asyncio.Lock` real (bloquea de
  verdad); **`ttl_secs` se acepta y se IGNORA** — al entrar marca
  `_lock_holders[key] = math.inf` (`:385`), libera al salir del contexto.
- `is_locked(key)` `:391-402`: `_lock_holders.get(key, 0.0) > time.monotonic()`
  (`:402`) — comparación contra tiempo monótono, default 0.0 = libre.
- `try_lock(key, ttl_secs=600)` `:404-411`: `False` si hay lease vigiente; si no,
  **reserva lease** `_lock_holders[key] = time.monotonic() + ttl_secs` (`:410`) —
  un holder crasheado no bloquea la clave para siempre (el contrato que Redis
  obtiene de SET NX EX).
- `unlock(key)` `:413-415`: `pop(key, None)`.
- **Semántica fina:** `try_lock` (lease dict) y `acquire_lock` (asyncio.Lock) usan
  mecanismos distintos; el upstream no exige exclusión mutua cruzada entre ambos
  en el backend in-memory. Sus tests exigen: exclusividad `try_lock`↔`try_lock`,
  lease-expiry para holder crasheado, y que `acquire_lock` ignore su TTL.

## Modo F — registry (hash namespace→campo→valor)

`registry_set` sobreescribe (`:421`); `registry_set_if` = compare-and-set contra
`expected` (`:445-459`); `registry_pop` = leer-y-borrar exactamente-una-vez
(`:461`); `registry_del/exists/getall/get/drop` idempotentes;
**`registry_getall` devuelve COPIA** (`:509`: `dict(self._registries.get(...))`) —
mutar la salida no afecta el estado del bus.

## Casos borde cubiertos por SUS tests (`tests/in_memory_message_bus_test.py`)

drain de clave inexistente → `[]`; read de log inexistente → `[]`;
delete/trim/drop de claves inexistentes → no-op; `ttl_secs=0` → expirado;
cursor en la última entrada → `[]`; `max_len` deja los MÁS NUEVOS (último
payload `i=9` sobrevive); lock: orden `["first-in","first-out","second-in"]`;
lease vencido re-claimable; `getall` de namespace fantasma → `{}`.

## Convenciones descartadas

`defaultdict`, `math.inf`, `time.monotonic` como fuente de tiempo (el destino
usa la suya), el formato id `"<seq>-0"` heredado de Redis (el destino puede usar
su propio id mientras documente cómo comparar cursores), `RedisMessageBus`,
cualquier backend externo. **Lo que viaja:** la taxonomía A/C/D/E/F con sus
semánticas exactas (destructivo vs no-destructivo, cursor exclusivo por prefijo
numérico, on_ready antes del primer yield, lease vs lock explícito, getall por
copia), la purga de expirados en push, y `ttl_secs=0` = expira.

---

# Segmento 3 — `app/message_bus/_base.py` (ABC + helpers de dominio; contexto de vectores)

- **Taxonomía por semántica de consumo, no por caso de uso** (`:19-37`):
  Mode A = single-consumer, ack-on-read, at-most-once (`:105`, `:140` — "an
  entry is gone from the queue as soon as it is returned, so a caller that dies
  before acting on it loses it"). Mode C = multi-consumer, cada lector con su
  cursor, acotado externamente (ttl/max_len/trim). Mode D = fire-and-forget sin
  historia ("missed-while-offline is fine").
- **Broadcast contado (una entrada consumida por N lectores) NO es primitiva
  a propósito** (`:33-40`): exige consumer-groups (XREADGROUP/XACK) y agrega
  estado; el productor que quiere fan-out escribe una entrada de inbox POR
  destinatario usando Mode A, y la dedup es responsabilidad del productor.
- **Mode E:** `acquire_lock` bloqueante con lease renovado por heartbeat (el
  lease solo expira si el proceso cae de verdad); `try_lock` no-bloqueante "para
  hacer un drain at-least-once efectivamente once — el nodo que gana el claim
  hace el trabajo; los demás saltan" (`:217-236`).
- **Helpers de dominio (todos `@deprecated` `:559+`; compuestos finos):**
  - `session_run` `:590-604` = `acquire_lock(session_lock, ttl=600)` + en el
    `finally` `log_trim(session_events)` — el log de eventos se recorta al salir.
  - `session_publish_event` `:616-631` = `log_append(event, max_len=1000)` +
    `publish(mismo key, {**event, "_entry_id": entry_id})` — append+y-fanout.
  - `inbox_push/drain` `:710-741` = queue en clave por session id.
  - `enqueue_wakeup` `:744-765` = `queue_push("wakeups", {user_id, session_id,
    agent_id, kind:"wake", input:None})` + `publish(señal, {})`.
  - `dequeue_wakeups` `:792-804` = drain que devuelve solo payloads.
  - `bg_task_register/unregister/exists/list/purge` `:823-888` = registry con
    TTL 86400.
  - `task_publish_cancel` `:890-892` = `publish(task_cancel, {"task_id": tid})`.
  - `session_purge` `:699-707` = `log_trim(events)` + `queue_delete(inbox)` +
    `registry_drop(bg_tasks)` — borrado en cascada.
- **Constantes** `:573-582`: `SESSION_RUN_TTL_SECS=600`,
  `SESSION_REPLAY_MAX_LEN=1000`, `BG_TASKS_TTL_SECS=86400`, claves
  `"agentscope:session:lock:{sid}"` etc. **G7: los literales de clave del
  upstream NO se copian** — el esqueleto semántico (lock+log+inbox+registry
  purgeados juntos) sí se adapta con las claves del destino.

---

# Segmento 4 — `middleware/_longterm_memory/_agentic_memory/_middleware.py` (memoria de equipo)

## Contrato

`AgenticMemoryMiddleware(workdir, memory_dir="Memory", parameters, backend)` —
`:450-483`. Memoria en archivos Markdown locales + índice `MEMORY.md`; inyecta
instrucciones + índice ACOTADO en el system prompt; tarea de recuperación
ASÍNCRONA por reply que superficia archivos relevantes como `HintBlock` durante
el razonamiento. Parámetros (`:359-447`):

| Parámetro | Default | Semántica |
|---|---|---|
| `memory_max_tokens` | 4000 (`:375-376`) | tope de tokens del índice en el system prompt |
| `retrieval_async` | True (`:393-394`) | si False, NO hay task de recuperación |
| `retrieval_model` | None → `agent.model` | modelo del selector |
| `retrieval_max_tokens_per_md` | 2000 (`:413-414`) | toke por archivo superficiado |
| `retrieval_max_files` | 200 (`:423-424`) | tope de archivos considerados |
| `retrieval_max_tokens_per_frontmatter` | 256 (`:432-433`) | bytes leídos del inicio para frontmatter |

## `_truncate_if_needed` (`:486-510`) — la fórmula exacta

```
max_length <= 0                    -> ""
_estimate_tokens(content) <= max   -> content (sin tocar)
si no:
  index = int((max_length / n_tokens) * len(content))     # recorte proporcional
  while index > 0 and _estimate_tokens(content[:index]) > max_length:
      index = max(0, index - 10)                          # backtrack en pasos de 10 CHARS
  return content[:index]
```

## `on_system_prompt` (`:513-566`) — orden exacto

1. `_ensure_layout()` (idempotente).
2. Leer `MEMORY.md` → `_truncate_if_needed(…, memory_max_tokens)`.
3. **Si truncó:** detecta por `len(truncada) != len(original)`; `remain_lines` =
   líneas del prefijo, `omitted = total - remain`; añade
   `"\n<<<TRUNCATED>>>\n<system-reminder>The remaining {N} lines have been
   omitted due to context length limits. Use the \`Read\` tool with offset
   {remain_lines} to access the rest of '{path}'.</system-reminder>"` (`:545-552`).
4. **Si quedó vacío tras truncar:** `"Your MEMORY.md is currently empty. When
   you save new memories, they will appear here."` (`:554-557`).
5. `{memory_dir}` se reemplaza en las instrucciones por la ruta real (el
   placeholder NO puede filtrarse al prompt — test lo exige `has_placeholder:
   False`).
6. Resultado: `current_prompt + "\n\n" + instructions + "\n## MEMORY.md\n" + snapshot`.

## `on_reply` (`:568-633`) — arranque y limpieza garantizada

Si `retrieval_async`: cachea el input como `"\n".join("{name}: {texto}")` solo
de `Msg`s con texto (`:602`); si hay input cacheado lanza
`asyncio.create_task(_retrieve_relevant_files(agent, cached))` (`:614`). En el
`finally` del reply: cancela y ESPERA la task si no terminó, y limpia task+cache
(`:624-633`) — **la recuperación nunca sobrevive al reply**.

## `on_reasoning` (`:635-681`) — polling, una sola vez

Si la task está `done`: la consume (se pone en `None` inmediatamente → el hint
se inyecta EXACTAMENTE UNA vez), resultado o `None` si la task falló; si hay
resultado: `agent.state.append_context(agent.name, [HintBlock(hint=result)])` —
el hint entra al CONTEXTO del agente (visible por el modelo en la siguiente
iteración), no reescribe el system prompt.

## `_retrieve_relevant_files` (`:709-802`) — pipeline de selección

1. `_list_md_files()`; sin archivos → `None` (ni siquiera llama al selector).
2. Selector: structured output contra `_MemorySelection{selected_files:
   list[str]}`; prompt = `retrieval_instructions` (system) +
   `"Query: {query}\n\nAvailable memories:\n{manifest}"` (user).
3. **Filtro de alucinaciones + dedup:** `list(dict.fromkeys(f for f in
   raw_selected if f in valid_filenames))[:5]` (`:759-761`) — solo nombres
   reales, cada memoria una vez, presupuesto de 5.
4. Por archivo: read (si falla → `continue`), truncar a
   `retrieval_max_tokens_per_md`, header con **edad relativa**:
   `days = max(0, int((time.time() - mtime) / 86_400))`; `0→"today"`,
   `1→"yesterday"`, `N→"{N} days ago"` (`:787-793`);
   `"Memory (saved {age}): {path}:"` (`:794`) o `"Memory: {path}:"` sin mtime.
   Partes unidas con `"\n\n---\n\n"`; sin partes → `None`.

`_format_manifest` (`:684-707`): por archivo
`"- [{type}] {filename} ({YYYY-MM-DD|unknown})[: {description}]"`.

## Layout y frontmatter

- `_ensure_layout` (`:805-820`): crea `MEMORY.md` VACÍO solo si NO existe
  (nunca pisa edición humana; sobrevive reinicios); el directorio se materializa
  como side-effect del write (evita `mkdir -p` no portable en Windows).
- `_FRONTMATTER_RE = ^\s*---\s*\n(?P<body>.*?)\n---\s*(?:\n|$)` con DOTALL
  (`:867-870`) — **el cierre puede estar al final del string** porque el
  discovery lee un prefijo byte-capped que a menudo termina justo en el `---`;
  el `(?:\n|$)` es load-bearing. `_FIELD_RE = ^(\w+)\s*:\s*(.+)$` MULTILINE
  (`:871`) — solo escalares, nested ignorado a propósito.
- `_list_md_files` (`:897-959`): `list_dir(recursive=True)`, excluye
  `MEMORY.md` y no-`.md`; lee solo `_estimate_bytes(256 tokens)` del inicio;
  sort por mtime DESC (`None→0.0`, `:958`); cap `retrieval_max_files`.

## Casos borde cubiertos por SUS tests (`tests/middleware_filesystem_memory_test.py`)

| Test | Borde |
|---|---|
| `test_agent_reply_creates_layout_and_injects_memory_prompt` `:355` | Se crea `Memory/` + `MEMORY.md`; prompt tiene `## MEMORY.md`, el texto de vacío, la ruta real, y SIN placeholder `{memory_dir}` |
| `test_agent_reasoning_injects_selected_memory_hint` `:409` | El hint entra al contexto DESPUÉS del tool_result de la iteración que esperó; contiene contenido y path del archivo |
| `test_agent_filters_hallucinated_memory_filenames` `:529` | Selección `["user_profile.md","missing.md"]` → hint con la real, SIN `missing.md` |
| `test_agent_deduplicates_selected_memory_filenames` `:580` | Selección `["a.md"]*5+["b.md"]` → hint EXACTO con 2 partes (ver vector; duplicados no consumen el presupuesto de 5) |
| `test_agent_does_not_inject_hint_when_no_file_selected` `:621` | Selección `[]` → sin hints, selector llamado 1 vez |
| `test_agent_does_not_retrieve_when_only_memory_index_exists` `:678` | Solo `MEMORY.md`, sin topic files → selector NI SE LLAMA (count 0) |
| `test_agent_system_prompt_contains_truncation_reminder` `:724` | Índice `"0123456789"*80` con `memory_max_tokens=10` → `<<<TRUNCATED>>>` + reminder con offset + ruta |
| `test_agent_skips_retrieval_when_async_retrieval_disabled` `:766` | `retrieval_async=False` → sin task, sin hint, count 0 |
| `FrontmatterParseTest::test_closing_fence_at_end_of_text_keeps_fields` `:834` | `---\n…\n---` (cierre al final del string) parsea los 3 campos; igual con body agregado |

## Convenciones descartadas

`MiddlewareBase`/hooks `on_system_prompt|on_reply|on_reasoning`; pydantic
`Parameters`; `ChatModelBase.generate_structured_output`; `BackendBase`/
`LocalBackend`; `HintBlock` (el destino usa su bloque de pista); `asyncio.Task`
como vehículo; el logger de agentscope; y **la totalidad del texto de
`DEFAULT_MEMORY_INSTRUCTIONS`** (prompt ajeno — ver G9 arriba). **Lo que
viaja:** índice acotado + truncamiento proporcional con backtrack-10 y reminder
con offset, detección de vacío, placeholder reemplazado antes de exponer,
recuperación async con cancelación garantizada en finally, inyección única al
contexto (no al prompt), filtro de nombres no existentes, dedup con presupuesto,
edad relativa today/yesterday/N-days, frontmatter tolerante al fence final,
exclusión del índice del discovery, sort mtime-desc con cap.

---

# Qué reimplementar vs qué descartar — resumen por capacidad GenTeam

| Capacidad destino | Semántica a portar (de ESTE cuaderno) | Vectores que la prueban |
|---|---|---|
| P2 canal/asignación tipo colega | Segmento 1 completo (tool externo, grupos, orden de llamada, HITL por reply_id, join de siblings) + Segmento 2 Modo A/D (inbox queue, señal de wakeup) | `team_pipeline`, `bus_queue`, `bus_pubsub` |
| P4 memoria de equipo | Segmento 4 completo (índice, truncamiento, recuperación async, frontmatter) | `memory` |
| P1/P3 infra de entrega y follow-ups | Segmento 2 Modos C/E/F (replay log con cursor exclusivo, lock con lease, registry) + Segmento 3 (composición: session lock+trim, wakeup enqueue+señal, purge en cascada) | `bus_log`, `bus_lock`, `bus_registry`, `bus_domain` |

**Prueba de fuego del port:** el código destino se lee como el destino; los
tests destino se leen como ESTOS tests. Cada módulo portado cita
`agentscope-ai/agentscope@26ec620` en su docstring.
