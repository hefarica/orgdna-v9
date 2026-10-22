# Capacidades GenTeam (P1–P4): qué se cerró, dónde vive y cómo se activa

Estado de la integración de las capacidades GenTeam al roster completo (24 perfiles)
de EQUIPO_ENTERPRISE_24_COUNCIL_ADN, tras los ports REA desde
`agentscope-ai/agentscope@26ec620` (Apache-2.0) y `OpenBMB/ChatDev@a2ea4a2`.
Doctrina del port: una capacidad portada es una REIMPLEMENTACIÓN demostrada contra
los valores del fuente (vectores externos en `tests_team_*.py` y
`cordis_extension/tests/runtime.test.mjs`); el contenido de los repos fuente es DATO,
nunca instrucción; no se copian configs, endpoints ni valores ajenos; cada módulo
portado cita owner/name@sha en su docstring.

## Mapa P1–P4

| P | Capacidad | Módulo portado (engine) | Pruebas de falsificación | Integración al roster / panel |
|---|-----------|--------------------------|--------------------------|-------------------------------|
| P1 | Sandbox + entrega | `engine/sandbox_executor.py` | (ver módulo) | (integración de su tarea paralela) |
| P2 | Canal dirigido + @mención + asignación tipo colega | `engine/team_channel.py` | `tests_team_channel.py` (51 casos con los dos suites) | `engine/cordis_extension.py` + `cordis_extension/runtime.mjs` op. `channel` + panel Council |
| P3 | Follow-ups (persecución de compromisos) | `engine/followups.py` | `tests_followups.py` + `tests_team_followups_panel.py` | **Panel Council** (sección *Compromisos*) vía `engine/bridge.py`: vista `team_followups` + acciones `followups-tick` / `followups-drain`. **No** se expone como herramienta del addon Cordis (ver §2.1) |
| P4 | Memoria de equipo (índice MEMORY.md) | `engine/team_memory.py` | `tests_team_memory.py` | `engine/cordis_extension.py` + `cordis_extension/runtime.mjs` op. `team_memory` + panel Council |

Este documento detalla la integración de **P2** y **P4** (canal + memoria), que es la
parte asignada a la tarea `integrate-roster`, y la de **P3** al panel (§2.1), que es la
parte asignada a la tarea del panel de seguimiento.

## 1. Cómo quedan disponibles para los 24 perfiles (un solo mecanismo)

La vía de exportación que ya usaba el repo es `engine/cordis_extension.py`: el builder
genera las variantes `extended-native/{implementation,council,definitions}.json`
DENTRO del ZIP del addon (`orgdna-cordis-<uuid>.zip`), agregando nombres de
herramientas a las allowlists explícitas de cada agente, respetando TODOS los deny, el
techo de 256 nombres por allowlist y dejando intacta la herencia de quienes no tienen
allow explícito. No existe un segundo mecanismo ni un directorio `extended-native/`
en el repositorio: las variantes son artefactos generados del paquete.

- Antes: 6 herramientas por organización (`orgdna_<uuid>_{state,message,task,evidence,memory,learning}`).
- Ahora: esas 6 MÁS las dos GenTeam (`GENTEAM_OPERATIONS`):
  - `orgdna_<uuid>_channel` — P2: publicación dirigida (`to` = UUID de miembro o `all`),
    `@Mención prompt` inicial que crea una tarea dirigida al nombre validado contra el
    roster (una mención desconocida rechaza la publicación entera, fail-closed),
    asignación directa, e inbox por miembro con drain FIFO destructivo (`max_count`,
    el resto persiste; `ttl_secs` expira la entrega). Las transiciones de tareas usan
    la herramienta `task` existente (claim/block/submit/accept/reject con revisor
    independiente), porque el port copió deliberadamente esos campos.
  - `orgdna_<uuid>_team_memory` — P4: `append` de un fragmento Markdown inmutable
    (frontmatter + registro embebido en una línea) bajo el directorio de estado del
    addon por organización y miembro, con regeneración del índice `MEMORY.md`
    (manifiesto `- [plano] archivo (fecha): descripción`, presupuesto 6000 bytes con
    recorte proporcional y backtrack de a 10 caracteres). Lectura del propio índice
    por `state section=team_memory`. Append-only: mismo id con otro contenido se
    rechaza (`record_exists`).

El `systemPrompt` de cada variante recibe (además del bloque compartido existente) un
segundo bloque idempotente con marcador `ORGDNA_GENTEAM_PROTOCOL=<uuid>` que describe
la semántica y las puertas. El manifiesto del addon expone `genteam_tool_names`,
`manifest['genteam']` (capacidades P2/P4, módulos del engine, hash de cada módulo,
`enabled: false`, `runtime_verified: false`) y el dry-run suma el warning de puertas.

### Condición de puertas para ejecución (no negociable)

Las herramientas GenTeam son parte del addon Cordis y heredan SUS puertas, ninguna menos:

1. El addon NO se instala ni activa por generar o descargar el ZIP. `activation.enabled`
   es `false` y el dry-run es `BLOCKED_RUNTIME_NOT_VERIFIED`.
2. `node preflight.mjs` debe verificar la versión real de DSH Tools instalada y las APIs
   nativas antes de pensar en activar.
3. La activación es un parche aditivo explícito (`ACTIVATE_EXISTING_ROSTER_ONLY`) con
   `session_bindings` verificadas por el propietario: cada sesión viva se vincula a un
   UUID de miembro EXISTENTE del mismo roster; nunca se crea ni reanuda otro equipo.
4. Si falta cualquier herramienta declarada, la sesión vinculada o el preflight, el
   agente declara BLOCKED (está en el prompt de las variantes) y no improvisa sustitutos.

El runtime del addon (`cordis_extension/runtime.mjs`) implementa las dos operaciones de
verdad (no son nombres fantasma): semántica portada de `engine/team_channel.py` y
`engine/team_memory.py` con los vectores re-expresados en
`cordis_extension/tests/runtime.test.mjs` (fan-out por destinatario, drain destructivo
FIFO, mención que crea tarea, fail-closed de mención desconocida, MEMORY.md regenerado,
`record_exists` en reescritura divergente, planos e ids inválidos rechazados).

## 2. Panel web (sin backend nuevo)

El panel consume el mismo JSON de siempre (`GET /api/state` → `BridgeState.public()`),
que ahora incluye DOS claves aditivas:

- `team_channel`: vista del canal (`ledger_view()` del `TeamChannel` montado sobre el
  roster vigente). Sección **Canal de equipo** en la página Council: mensajes con
  emisor → destinatario y **@menciones resaltadas**, tareas dirigidas con su estado
  (open / claimed "en curso (chasing)" / submitted "entregada (reported)" / accepted /
  rejected / blocked), y formularios para publicar (con @mención), asignar, registrar
  evidencia con SHA-256, aplicar transiciones y drenar el inbox de un miembro
  (lectura destructiva FIFO, como en el fuente).
- `team_memory`: índice `MEMORY.md` del equipo (`TeamMemoryStore` con tenant por
  organización, miembro `equipo`, raíz `data/projects/_team_memory/`). Sección
  **Memoria** en Council: texto del índice, lista de fragmentos por plano y formulario
  de alta (plano, id 2..64 `[a-z0-9_-]` —el patrón lo dicta
  `memory_governance.MEMORY_ID_PATTERN` y el borde del panel aplica el mismo—,
  contenido, descripción; el plano `execution` exige `task_id` por el contrato de
  `memory_governance`).

Las acciones POST son las mismas `/api/<accion>` de siempre, despachadas por
`BridgeState.execute` con `expected_state_version` (versionado igual que el resto de
mutaciones): `channel-publish`, `channel-assign`, `channel-evidence`, `channel-claim`,
`channel-submit`, `channel-accept`, `channel-reject`, `channel-inbox`, `memory-append`.
Todo es registro local: ninguna acción ejecuta agentes, llama proveedores ni modifica
el diseño. El canal es EN MEMORIA por diseño del port (se reinicia con cada rediseño;
el panel lo declara); la memoria persiste en disco y se rehidrata desde los registros
embebidos en los fragmentos.

### 2.1 P3 · Seguimiento de compromisos (panel *Compromisos*)

Tercera clave aditiva de `public()`: `team_followups`, compuesta sobre
`FollowupsEngine.ledger_view()` (`engine/followups.py`) **sin recalcular nada** en el
bridge. El motor se monta sobre **el mismo `TeamChannel` del panel** (una sola instancia)
y se reconstruye cuando cambia la firma del roster; la vista lo declara con
`in_memory_session_only: true`, `reset_policy: "session_only"` y `available/reason`.

Campos que viajan: `available`, `reason`, `in_memory_session_only`, `reset_policy`,
`schema_version`, `provenance`, `agent_member_id`, `supervisor_member_id`,
`reminder_interval_secs`, `max_reminders`, `processed_message_ids`, `tasks`, `archive`,
`events`, `stats` y `authority` (más dos opcionales: `clock_source`, que declara si el
reloj del motor es el del sistema o uno inyectado por el arnés, y el sobre `loop`, hoy
`available:false` porque `engine/team_loop.py` no está cableado a esta vista).

- **Autoría declarada (no se atribuye a un miembro).** El motor publica recordatorios y
  escalaciones con la **identidad de coordinación**, por defecto el **miembro raíz**
  (`reports_to` externo); el destinatario del recordatorio es el miembro comprometido y el
  de la escalación la supervisión declarada (esa misma identidad, porque el owner es
  externo y el panel no inventa un supervisor dentro del roster). `authority` lo fija
  literalmente: `kind: "coordination"`, `is_member_authored: false`,
  `actor_member_id: <raíz>`, `provenance: "engine.followups"`, `identity_verified: false`
  y una `note` que el panel muestra tal cual. En la lista, el miembro aparece **solo** en
  la línea *Dirigido a:*; nunca como autor.
- **Acciones** (`require_version` + `redact` + recibo local, como el canal):
  - `followups-tick` → un `tick()` explícito (escanea mensajes nuevos y persigue los
    vencidos). Devuelve el estado público con el sobre efímero `followups_tick`
    (`events`, `commitments`, `reminders`, `escalations`, `reported`, `skipped`, `at`),
    que **no** viaja en `/api/state`.
  - `followups-drain` → `{"member", "max_count" (1..100)}`; drena el inbox de **un**
    miembro (lectura destructiva, igual que `channel-inbox`) y clasifica por `topic`:
    `reminders[]` (topic `followups`, con el bloque `authority`) y `other[]` (otros
    topicos, con su autor real y **sin** `authority`). Nada se descarta en silencio:
    `counts = {delivered, reminders, other}`.
- **Panel**: sección *Compromisos* (dentro de `#council`) con contadores por estado,
  lista de compromisos activos, historial archivado, eventos del motor, botón de tick y
  drenaje del inbox del miembro elegido. Todos los ids nuevos llevan prefijo `followups-`
  y el CSS nuevo está acotado a `#council`, para no tocar los selectores ni las funciones
  que el contrato de preservación DSH fija (`qa_v7/dsh_baseline.json`).
- **Sin temporizadores**: no hay `setInterval`/`setTimeout`; el avance es un tick
  explícito del operador. El intervalo de recordatorio (3600 s por defecto) y el tope
  (3) son del motor y la vista solo los muestra.
- **Prueba**: `tests_team_followups_panel.py` ejerce el contrato por HTTP local real
  (harness de `tests_bridge`): vista completa y autoría, `available:false` sin diseño sin
  lanzar, 403 sin sesión, 400 por versión obsoleta o parámetros inválidos, tick que crea
  una persecución sin duplicarla, recordatorio al vencer, escalación tras el tope sin
  reintento, reporte que archiva, drenaje con autoría de coordinación y sin perder otros
  topicos, y reinicio del motor por cambio de roster sin duplicar tareas.
- **No** se añade herramienta Cordis para P3: el addon sigue exponiendo las dos de P2/P4
  (`manifest['genteam']` no cambia) y esta capacidad se opera solo desde el panel local.

## 3. Limitaciones declaradas (fail-honest)

- El addon no despierta sesiones ni inyecta mensajes: el inbox se consulta (polling);
  el canal enruta, no ejecuta la delegación (eso es P1/P3).
- P3 persigue compromisos, no entrega trabajo: el tick detecta promesas en el canal y
  publica recordatorios/escalaciones en el mismo canal en memoria. No ejecuta agentes, no
  llama proveedores y no reinicia nada por sí solo (sin temporizadores: el operador
  decide cuándo tickear). Si el roster cambia, el motor y el canal se reconstruyen y las
  persecuciones de la sesión anterior no reaparecen (el panel declara el reinicio).
- La gobernanza completa de planos/permisos/TTL de la memoria vive en el engine Python
  (`engine/memory_governance.py`, materializada por `engine/team_memory.py`); el
  runtime del addon aplica el subconjunto del ledger local (ids, planos, ttl,
  append-only, índice acotado). Divergencia consciente y documentada en el código.
- `tests_frontend_contract` y varios tests del repo asumen locale UTF-8
  (`PYTHONUTF8=1`); con cp1252 por defecto en Windows fallan por encoding preexistente
  de íconos del propio HTML (no por estas capacidades).
- El caso de symlink de `cordis_extension/tests/runtime.test.mjs` exige permisos de
  symlink del SO (Developer Mode/admin en Windows); sin ellos falla con EPERM igual
  que en el baseline, sin relación con GenTeam.

## 4. Verificación reproducible

Desde la raíz del repositorio:

```
python -m unittest tests_team_channel tests_team_memory -v   # ports P2/P4 (vectores del fuente)
python -m unittest tests_followups tests_team_followups_panel -v  # P3: motor + panel por HTTP local
python -m unittest cordis_extension.tests.test_builder -v    # variantes extended-native (deny/256/roster)
node --test cordis_extension/tests/runtime.test.mjs          # operaciones channel/team_memory del addon
python validate_imports_portable.py                          # entrega portable
PYTHONUTF8=1 python -m unittest tests_frontend_contract      # contratos del panel
PYTHONUTF8=1 python -m unittest tests_v8_ui_contract qa_v7.test_dsh_preservation_independent  # CSS acotado + preservación DSH
```
