# PRIORIDADES — brechas GenTeam priorizadas + ranking rubricado de candidatos REA

**Tarea:** `[sintesis]` · **Misión:** mapear brechas de EQUIPO_ENTERPRISE_24_COUNCIL_ADN contra el modelo GenTeam (Genspark) y rankear candidatos GitHub de cierre bajo metodología REA (port-with-validation). Solo análisis: esta tarea no escribió código.
**Fecha:** 2026-10-21 (sesión síntesis).

**Método:** síntesis documental estática. Entradas:
- `docs/gap/engine_map.md` (219 líneas, en el repo) — veredictos del engine Python.
- `docs/gap/ui_cordis_map.md` (310 líneas, en el repo) — veredictos UI/panel + plugin Cordis.
- `docs/gap/gh_candidates.md` (168 líneas) — **hallado en `docs\gap\` del workspace raíz, NO en `docs\gap\` del subdirectorio del repo** (discrepancia de ruta declarada; el contenido se usó tal como fue medido el 2026-10-21 por la tarea `gh-candidates`, sin re-fetch). En adelante se cita como `gh_candidates.md:NN` por su número de línea.

Nada fue ejecutado y ningún archivo del engine ni de GitHub fue reabierto en esta tarea: la evidencia de brechas se hereda de los dos mapas (el engine-map pasó auditoría de evidencia 12/12 fragmentos soportados, según su informe) y la de candidatos de `gh_candidates.md`, cuyos comandos reproducibles están en `gh_candidates.md:162-168`.

---

## 0. El destino contra el que se evalúa `encaje_arquitectonico`

Cuatro restricciones del destino, con su evidencia:

1. **Motor Python puro, offline, inerte por defecto.** 29 módulos `engine/*.py` (`engine_map.md:215-216`); "sin red al importar" (`engine/org_design.py:1-7`, citado en `engine_map.md:44`); el despacho por defecto lanza `NoRuntimeError` — "no hay runtime de AgentTeams/DSH en este árbol" (`engine/orchestrator.py:141-145`, `engine_map.md:12`).
2. **Sin runtime JS server-side.** El plugin Cordis es client-side dentro de DSH (`cordis_extension/*.mjs`, leídos completos según `ui_cordis_map.md:9-13`); el panel web es estático local (`web/index.html`, `web/app.js`).
3. **Integración existente con DSH/AgentTeams, read-only.** Bridge loopback "No tool execution" (`live_bridge.mjs:1-6`, `ui_cordis_map.md:170-172`); `prepare_task_plan` → `BLOCKED_CAPABILITY` y `submit_task_plan` → `CAPABILITY_UNAVAILABLE` (`engine/dsh_connection.py:298-304`, `engine_map.md:13`).
4. **Plugin Cordis propio (ledger compartido).** 6 tools `orgdna_<uuid>_{state,message,task,evidence,memory,learning}` sobre un ledger JSON con escritura atómica y versión CAS (`runtime.mjs:10`, `runtime.mjs:58-100`, `ui_cordis_map.md:201-207`).

Un candidato encaja si el segmento a portar es **semántica Python portable a ese motor inerte** (o al ledger del plugin), sin arrastrar runtimes async, servicios externos ni dependencias de red.

---

## 1. TABLA DE BRECHAS — capacidades GenTeam ausentes o parciales, priorizadas

**Criterio de prioridad:** impacto directo sobre el loop *"asignar el trabajo una vez → ejecución aislada → persecución hasta el fin → recibir el ARCHIVO terminado → recordar para la próxima"*. Prioridad 1 = la ausencia que más bloquea recibir el trabajo terminado. Los veredictos combinados provienen de los dos mapas; cada evidencia es `archivo:línea` del repo tal como la citan los mapas.

| P | Capacidad GenTeam | Engine | UI/Cordis | Estado combinado | Impacto en el loop |
|---|---|---|---|---|---|
| **1** | C3 Sandbox aislado por agente + devolver ARCHIVO al canal | PARCIAL | AUSENTE | **CRÍTICO** | Sin ejecutor aislado ni devolución no hay "trabajo terminado" que recibir |
| **2** | C2 Asignar trabajo como colega (@mention / DM / tarea, con wake) | PARCIAL | PARCIAL | **ALTO** | La asignación existe como registro, pero sin canal vivo ni wake nadie la recibe solo |
| **3** | C4 Follow-ups autónomos mid-conversation | AUSENTE | AUSENTE | **ALTO** | Sin persecución, terminar el trabajo exige supervisión humana continua: rompe el "una vez" |
| **4** | C5 Memoria de equipo persistente que sobrevive sesiones | PARCIAL | EXISTE (registro) | **MEDIO** | El registro persiste; falta almacén materializado + recuperación + ligazón a agentes vivos |
| **5** | C1 Contratar roles ready-made / por descripción de puesto | PARCIAL | PARCIAL | **MEDIO** | La creación de equipo completo funciona; falta hire incremental y derivación desde vacante libre |
| **6** | C6 Lista privada de trabajo del usuario (save → bajo petición) | AUSENTE | PARCIAL | **MEDIO-BAJO** | Habilita "asignar bajo petición", pero no bloquea el loop central |
| **7** | C7 Onboarding que sugiere contrataciones y abre el primer canal | AUSENTE | PARCIAL | **BAJO** | Depende de C2 (canal) para tener sustrato |
| **8** | C8 Puente a agentes CLI externos + night-shift cloud | AUSENTE | AUSENTE | **BAJO** | Fuera del loop central de un producto local offline (`ui_cordis_map.md:308-310`: "alcance menor para un producto local") |
| **9** | C9 Roster de roles predefinidos reutilizables | PARCIAL | EXISTE | **MÍNIMO** | Cubierto como catálogo; lo que falta (instanciación viva) ya está en P1/P5 |

### P1 — C3: sandbox por agente + archivo terminado al canal (CRÍTICO)

- **Engine PARCIAL:** leases cooperativos **sin** enforcement de filesystem — `engine/coordination.py:205-206` (`'filesystem_lock_enforced': False`); ejecución local declarada no-sandbox — `engine/evaluation_runs.py:173` (`'sandboxed': False`) y `engine/evaluation_runs.py:1` ("This is NOT an OS sandbox"); artefactos locales firmados (`engine/artifact_factory.py:74`, kinds `report/patch/ticket/runbook/bundle`) **pero no hay canal al que devolverlos** (`engine_map.md:84-91`).
- **UI AUSENTE:** "Esta app no inicia agentes ni tareas en DSH" — `web/index.html:48` (`ui_cordis_map.md:79-80`); sin mecanismo de sandbox/ejecución en `cordis_extension/` (`runtime.mjs:1` "No agent engine, network, or executable learning"); el "worktree aislado" del handoff es doctrina en texto, no código (`10_COORDINACION_Y_RESERVAS.md:17`, `ui_cordis_map.md:88`).
- **Por qué P1:** es la única brecha donde ambos mapas coinciden en que falta la mitad de ejecución Y la de devolución; el resto del loop asigna y registra, pero nunca produce un archivo recibido.

### P2 — C2: asignar trabajo como colega (@mention/DM/tarea con wake) (ALTO)

- **Engine PARCIAL:** tarea con `agent_ref` — `engine/task_graph.py:545`; contexto por tiers (mandate/task/evidence/skill/memory/handoff) — `engine/context_compiler.py:27-30`; PERO grep de `@mention|canal|DM|inbox` sin resultados, y el único bus es polling-only — `engine/cordis_extension.py:174` (`'message_delivery': {'mode': 'polling_only', 'native_wake_available': False, 'all_members_connected': False}`); "Vinculación de sesiones vivas a UUID de miembros pendiente" — `engine/cordis_extension.py:213-215` (`engine_map.md:61-73`).
- **UI PARCIAL:** `message` con `to: member_id|"all"` y tareas claim/submit/accept/reject en el ledger — `runtime.mjs:175-215`; PERO "Stored inbox only; no wake" — `plugin.mjs:5`, `live_messages: available:false` — `live_bridge.mjs:65`; sin UI de chat en el panel (`ui_cordis_map.md:52-71`).

### P3 — C4: follow-ups autónomos (ALTO)

- **Engine AUSENTE:** "Un 'failed' o 'blocked' no vuelve a estar listo jamas: no hay reintento automatico" — `engine/scheduler.py:298-303`; reapertura solo por decisión explícita — `engine/scheduler.py:436-444`; tick del supervisor manual — `engine/gang_supervisor.py:19-21` (`engine_map.md:99-103`).
- **UI AUSENTE:** `realtime_events: available:false` — `live_bridge.mjs:66`; el único polling es del harness local — `web/app.js:1085`; sin temporizadores de follow-up en `runtime.mjs`/`live_bridge.mjs` (`ui_cordis_map.md:96-104`).
- **Dependencia declarada:** sin C2 no hay canal vivo que perseguir (`ui_cordis_map.md:106-107`).

### P4 — C5: memoria de equipo persistente (MEDIO)

- **Engine PARCIAL:** registros versionados en snapshots — `engine/bridge.py:518,999`; journal append-only con replay — `engine/gang_journal.py:1-12`; PERO `memory_governance` es INERTE: "no ejecuta agentes, no escribe ficheros... no materializa ningun almacen" — `engine/memory_governance.py:4-6`, planos definidos en `:53` (`engine_map.md:115-124`).
- **UI EXISTE (registro):** memory append-only con evidencia — `runtime.mjs:184-189`; persistencia atómica — `runtime.mjs:61-100`; límites: `content_verified:false` por fila, sin recuperación semántica (`ui_cordis_map.md:112-125`).

### P5 — C1: contratar roles / derivar perfil (MEDIO)

- **Engine PARCIAL:** 32 ROLE_SEEDS — `engine/profiles.py:8-89`; derivación desde análisis de repo/web, **no** desde job description libre — `engine/autonomy.py:76-89`; el "hire" real ocurre fuera del engine (import manual del recipe) — `engine/core.py:1138` (`engine_map.md:43-53`).
- **UI PARCIAL:** generación por descripción — `web/index.html:50-56`; sin contratación individual: `EXISTING_TEAM_PRESERVED` — `native_stage_ui.mjs:75` (`ui_cordis_map.md:27-47`).

### P6 — C6: lista privada de trabajo (MEDIO-BAJO)

- **Engine AUSENTE:** grep `backlog|todo list|lista de trabajo|save for later` sin resultados; TaskGraph inerte (`engine_map.md:130-134`).
- **UI PARCIAL:** guardado versionado de proyectos — `web/index.html:88`; biblioteca privada — `web/index.html:114,118`; lo guardable es diseño organizacional, no trabajo (`ui_cordis_map.md:129-141`).

### P7 — C7: agente de onboarding (BAJO)

- **Engine AUSENTE:** grep `onboarding|a quien contratar` sin resultados; `IntegrationRecommendations` sugiere plugins, no hires — `engine/bridge.py:1141-1142` (`engine_map.md:140-144`).
- **UI PARCIAL:** contrato de saludo "Qué hará al recibir tu saludo" — `web/index.html:87`, `engine/autonomy.py:179-229`; sin sugerencia de contrataciones ni canal que abrir (`ui_cordis_map.md:145-161`).

### P8 — C8: puente CLI externo / night-shift (BAJO)

- **Engine AUSENTE:** `submit_task_plan` lanza `CAPABILITY_UNAVAILABLE` — `engine/dsh_connection.py:303-304`; `native_orchestration: enabled: False` — `engine/cordis_extension.py:183-188`; cero integración CLIs (`engine_map.md:150-154`).
- **UI AUSENTE:** grep `claude|codex|night` = 0 matches en `cordis_extension/*.mjs`; único puente es loopback read-only — `live_bridge.mjs:1-6` (`ui_cordis_map.md:164-177`).

### P9 — C9: roster predefinido (MÍNIMO)

- **Engine PARCIAL:** semillas estables — `engine/profiles.py:2-3,8-89`; roster de diseño, no vivo (`engine_map.md:162-167`).
- **UI EXISTE:** 24 identidades + 32 roles materializados — `engine/profiles.py:4-5,8-89`; plantillas — `web/index.html:62` (`ui_cordis_map.md:182-195`).

---

## 2. RANKING DE CANDIDATOS — rúbrica exacta del encargo

### 2.1 Rúbrica declarada

| Dimensión | Peso | Escala | Nota |
|---|---|---|---|
| madurez | 20 | 0..1 | hace de verdad lo pedido (tests legibles + uso real medido) |
| licencia | 25 | 0..1 | leída LITERAL al sha fijado |
| actividad | 15 | 0..1 | vivo y respondiendo (fecha último commit, medición 2026-10-21) |
| encaje_arquitectonico | 25 | 0..1 | contra el destino de §0 (Python puro offline, sin runtime JS server-side, integración DSH/AgentTeams, plugin Cordis propio) |
| riesgo_de_copia | 15 | 0..1 **INVERTIDA** | se DECLARA el riesgo (0 = ninguno) y se APLICA `valor = 1 − riesgo` |

**Fórmula:** `puntaje = Σ(peso × valor) / 100` · **Umbral: 0.70** · Mínimo 2 candidatos puntuados; dimensión sin puntuar ⇒ score `null`.

### 2.2 Anclas de puntaje (publicadas para auditoría)

- **madurez:** 0.9 = tests específicos al segmento + uso masivo (#1-4 del barrido) · 0.85 = tests específicos + uso alto · 0.8 = tests presentes, uso menor · 0.4 = el segmento objetivo ya no existe al sha.
- **licencia:** 1.0 = permisiva (Apache-2.0/MIT) leída al sha — los 8 candidatos la tienen (fue filtro duro del barrido); autogen se anota su dualidad.
- **actividad (días antes de 2026-10-21):** 0d = 1.0 · 1d = 0.95 · 2d = 0.90 · 5d = 0.85 · 9 meses = 0.40 · auto-declarado no mantenido en su HEAD = 0.10.
- **encaje:** 0.75 = segmentos Python puro/filesystem que calzan directo sobre TaskGraph/ledger/context_compiler · 0.7 = calzan con arrastre de framework · 0.6 = semántica útil pero app de dominio · 0.55 = útiles pero con dependencias de servicios externos · 0.4 = modelo reescrito que no coincide con el destino.
- **riesgo (declarado):** 0.25-0.30 = superficie de arrastre chica (clases autocontenidas) · 0.35 = framework pesado · 0.4-0.45 = reestructura/dependencias de servicios.

### 2.3 Tabla de puntajes (ordenada por score)

| # | Repo@sha7 | madurez (20) | licencia (25) | actividad (15) | encaje (25) | riesgo decl. → valor (15) | **Score** | ≥0.70 |
|---|---|---|---|---|---|---|---|---|
| 1 | **agentscope-ai/agentscope@26ec620** | 0.85 | 1.0 | 1.0 | 0.75 | 0.30 → 0.70 | **0.8625** | ✓ |
| 2 | **OpenBMB/ChatDev@a2ea4a2** | 0.85 | 1.0 | 0.85 | 0.75 | 0.25 → 0.75 | **0.8475** | ✓ |
| 3 | camel-ai/camel@797296a | 0.80 | 1.0 | 0.90 | 0.70 | 0.35 → 0.65 | **0.8175** | ✓ |
| 4 | TauricResearch/TradingAgents@e8f5503 | 0.90 | 1.0 | 0.85 | 0.60 | 0.30 → 0.70 | **0.8125** | ✓ |
| 5 | crewAIInc/crewAI@af4efdc | 0.90 | 1.0 | 1.0 | 0.55 | 0.45 → 0.55 | **0.8000** | ✓ |
| 6 | FoundationAgents/MetaGPT@11cdf46 | 0.85 | 1.0 | 0.40 | 0.65 | 0.35 → 0.65 | **0.7400** | ✓ |
| 7 | microsoft/autogen@004749e | 0.90 | 1.0 | 0.10 | 0.60 | 0.45 → 0.55 | **0.6775** | ✗ |
| 8 | ag2ai/ag2@b4c5b53 | 0.40 | 1.0 | 0.95 | 0.40 | 0.40 → 0.60 | **0.6625** | ✗ |

8/8 candidatos puntuados en las 5 dimensiones ⇒ **ningún score null** (mínimo exigido: 2). Seis superan 0.70: **no hay EMPATE técnico**. El margen #1–#2 es 0.015 — dentro de la granularidad de las anclas (0.05): la lectura correcta es que cierran **brechas distintas y complementarias** (ver §3).

### 2.4 Justificación por candidato (cada dimensión con su artefacto)

**1. agentscope-ai/agentscope@26ec620 — 0.8625**
- madurez 0.85: tests específicos al segmento listados al sha — `tests/pipeline_team_test.py`, `tests/in_memory_message_bus_test.py`, `tests/middleware_filesystem_memory_test.py` (`gh_candidates.md:111`); 33,589 stars (`gh_candidates.md:21`).
- licencia 1.0: Apache-2.0 leída al sha (`gh_candidates.md:104`).
- actividad 1.0: último commit 2026-10-21, día de la medición (`gh_candidates.md:105`).
- encaje 0.75: los tres segmentos son Python/filesystem-local sin runtime JS ni servicios: `TeamMember` con descripción + `_TeamAssign` por tool call (`_team_pipeline.py:37-56`, `gh_candidates.md:107-108`) calzan sobre `agent_ref` del TaskGraph y el claim/assign del ledger; memoria "Filesystem-backed long-term memory middleware... workspace-local Markdown memory store, injects a bounded `MEMORY.md` index into the system prompt" (`_middleware.py:2-5,44-46`, `gh_candidates.md:109`) calza sobre los planos inertes de `memory_governance.py:53` + el tier `memory` de `context_compiler.py:27-30`. Descuenta: su bus es in-memory (se porta semántica, no mecanismo) y el middleware pertenece a su arquitectura propia.
- riesgo declarado 0.30 → 0.70: framework con abstracciones propias (middleware, ToolBase); port = reescritura en convenciones del destino.
- Cálculo: (20·0.85 + 25·1.0 + 15·1.0 + 25·0.75 + 15·0.70)/100 = (17+25+15+18.75+10.5)/100 = **0.8625**.

**2. OpenBMB/ChatDev@a2ea4a2 — 0.8475**
- madurez 0.85: tests de robustez/seguridad al sha (`gh_candidates.md:99`); 34,560 stars (`gh_candidates.md:20`).
- licencia 1.0: Apache-2.0 al sha (`gh_candidates.md:91`).
- actividad 0.85: commit 2026-10-16, 5 días antes de la medición (`gh_candidates.md:92`).
- encaje 0.75: **único candidato del barrido con segmento real de ejecución aislada** — `PythonNodeExecutor` con `subprocess.run(..., timeout=config.timeout_seconds)` (`python_executor.py:30-36,139-146`, `gh_candidates.md:95`), Python puro offline; y `BlackboardMemory` "Lightweight append-only" (`blackboard_memory.py:1,19-20`, `gh_candidates.md:94`), misma doctrina que gang_journal/ledger. Su config declarativa de nodos espeja el estilo del TaskGraph. Descuenta: es un runtime de grafo completo; solo se portan los nodos ejecutor/memoria.
- riesgo declarado 0.25 → 0.75: el ejecutor es una clase autocontenida; los tests de seguridad guían el port.
- Cálculo: (17+25+12.75+18.75+11.25)/100 = **0.8475**.

**3. camel-ai/camel@797296a — 0.8175**
- madurez 0.80: tests workforce/role-assignment/memories (`gh_candidates.md:123`); 17,943 stars (`gh_candidates.md:22`).
- licencia 1.0: Apache-2.0 (`gh_candidates.md:116`).
- actividad 0.90: commit 2026-10-19, 2 días antes (`gh_candidates.md:117`).
- encaje 0.70: `RoleAssignmentAgent` "generates role names based on the task prompt" (`role_assignment_agent.py:36-37,64`, `gh_candidates.md:119`) — único segmento ✓✓ del barrido para derivación de roles por descripción (matriz `gh_candidates.md:131`); `task_channel` con `PacketStatus` SENT/PROCESSING/RETURNED/ARCHIVED (`task_channel.py:25-33,45-46`, `gh_candidates.md:120`) — ciclo de vida portable al ledger; `WorkflowMemoryManager` persiste workflows a rutas de archivo (`workflow_memory_manager.py:56-60,96-98`, `gh_candidates.md:121`). Descuenta: la sociedad/workforce es framework pesado.
- riesgo declarado 0.35 → 0.65.
- Cálculo: (16+25+13.5+17.5+9.75)/100 = **0.8175**.

**4. TauricResearch/TradingAgents@e8f5503 — 0.8125**
- madurez 0.90: suite "enorme y legible" (+60 archivos: `test_memory_log.py`, `test_debate_opening.py`, `test_graph_end_to_end.py`, `test_checkpoint_resume.py`; `gh_candidates.md:39`); #1 del barrido, 112,479 stars (`gh_candidates.md:16,33`).
- licencia 1.0: Apache-2.0 (`gh_candidates.md:32`).
- actividad 0.85: commit 2026-10-16 (`gh_candidates.md:33`).
- encaje 0.60: `TradingMemoryLog` append-only markdown (`memory/log.py:11-12`, `gh_candidates.md:37`) y debate con `max_debate_rounds` (`trading_graph.py:85`, `gh_candidates.md:36`) cierran C5-extensión y semántica de council; PERO es **aplicación de dominio trading** (`gh_candidates.md:40`), sin canal/wake, sin sandbox (matriz: "◐ entregable=decisión/report", `gh_candidates.md:135`) y sin follow-ups.
- riesgo declarado 0.30 → 0.70: el dominio financiero contamina un paste; el port es solo semántica memory-log + rondas.
- Cálculo: (18+25+12.75+15+10.5)/100 = **0.8125**.

**5. crewAIInc/crewAI@af4efdc — 0.8000**
- madurez 0.90: tests memory/agent/crew en layout nuevo (`gh_candidates.md:86`); 59,951 stars (`gh_candidates.md:19`).
- licencia 1.0: MIT (`gh_candidates.md:78`).
- actividad 1.0: commit 2026-10-21 (`gh_candidates.md:79`).
- encaje 0.55: rol triple role/goal/backstory (`core.py:213-216`, `gh_candidates.md:81`) y `Task` con expected output + agente responsable (`task.py:120-123`, `gh_candidates.md:82`) calzan sobre ROLE_SEEDS/TaskSpec; PERO la memoria unificada depende de backends **lancedb/qdrant** (`gh_candidates.md:83`) — servicios externos incompatibles con "Python puro offline"; y "Sin chat grupal compartido con menciones" (`gh_candidates.md:85`).
- riesgo declarado 0.45 → 0.55: dependencias de vector DB + monorepo `lib/`.
- Cálculo: (18+25+15+13.75+8.25)/100 = **0.8000**.

**6. FoundationAgents/MetaGPT@11cdf46 — 0.7400**
- madurez 0.85: tests memory/env/role_zero (`gh_candidates.md:52`); 70,948 stars (`gh_candidates.md:17`).
- licencia 1.0: MIT (`gh_candidates.md:45`).
- actividad 0.40: último commit 2026-01-21 — "9 meses sin commits al sha medido" (`gh_candidates.md:46`).
- encaje 0.65: `Environment.publish_message` con routing al destinatario (`base_env.py:175,181`, `gh_candidates.md:49`) es la semántica de direccionamiento de C2; acciones que escriben archivos (`write_code.py`, `gh_candidates.md:51`) tocan la mitad de entrega de C3; perfil `{profile}` (`role.py:51`, `gh_candidates.md:48`). Descuenta: framework SOP completo con runtime propio.
- riesgo declarado 0.35 → 0.65.
- Cálculo: (17+25+6+16.25+9.75)/100 = **0.7400**. Pasa umbral, pero la actividad lo hace inadecuado como fuente de la que el port dependa del futuro.

**7. microsoft/autogen@004749e — 0.6775 ✗**
- madurez 0.90: tests deterministas de group chat/magentic/memory (`gh_candidates.md:64`); 61,508 stars (`gh_candidates.md:18`).
- licencia 1.0: dual verificada al sha — código MIT (`LICENSE-CODE`), docs CC-BY-4.0 (`gh_candidates.md:57`); el código Python es MIT.
- actividad 0.10: su HEAD se auto-declara "AutoGen is archived and no longer maintained" (`gh_candidates.md:58`).
- encaje 0.60: `SelectorGroupChatManager` (`_selector_group_chat.py:50-52`, `gh_candidates.md:60`) y el ledger hechos/plan/progreso de MagenticOne (`_magentic_one_orchestrator.py:46-51,58`, `gh_candidates.md:61`) son la semántica más rica de C2/C4; PERO routing por topic types de runtime async (`gh_candidates.md:65`) — fricción alta con un motor offline síncrono e inerte.
- riesgo declarado 0.45 → 0.55.
- Cálculo: (18+25+1.5+15+8.25)/100 = **0.6775** — bajo umbral, y además descalificación práctica por mantenimiento.

**8. ag2ai/ag2@b4c5b53 — 0.6625 ✗**
- madurez 0.40: "0 rutas conteniendo `groupchat` en el árbol completo" — el GroupChat clásico no existe al sha (`gh_candidates.md:72`); tests parciales de memoria (`gh_candidates.md:73`).
- licencia 1.0: Apache-2.0 (`gh_candidates.md:70`).
- actividad 0.95: commit 2026-10-20 (`gh_candidates.md:71`).
- encaje 0.40: reescrito a events/streams/policies (`gh_candidates.md:72`) — no coincide con el destino para los segmentos buscados.
- riesgo declarado 0.40 → 0.60.
- Cálculo: (8+25+14.25+10+9)/100 = **0.6625** — bajo umbral.

---

## 3. RECOMENDACIÓN

### 3.1 Ganador: `agentscope-ai/agentscope@26ec620` (score 0.8625)

Con la advertencia honesta de que el margen sobre ChatDev (0.015) está dentro de la granularidad de las anclas: **agentscope gana el ranking como fuente primaria para P2 y P4; ChatDev se designa fuente de P1 porque el ganador no tiene segmento de ejecución**. Ningún candidato se elige sin score: ambos están puntuados (0.8625 y 0.8475).

**Ports desde agentscope@26ec620:**

| Brecha | Segmento portado | Destino | Vectores de validación (tests del fuente) |
|---|---|---|---|
| P2 (C2) | `TeamMember` + `_TeamAssign` (`src/agentscope/pipeline/_team_pipeline.py:37-56`, `gh_candidates.md:107-108`): miembro con descripción + asignación explícita por tool | claim/assign del ledger Cordis + validación `agent_ref` del TaskGraph (`engine/task_graph.py:545`) | `tests/pipeline_team_test.py` (asignación entrada→salida) + `tests/pipeline_team_cleanup_test.py` (borde: limpieza de estado) — `gh_candidates.md:111` |
| P2 (C2) | routing del bus (`src/agentscope/message_bus/_in_memory_message_bus.py`, `gh_candidates.md:108`): publicar/suscribir dirigido | el ledger ya tiene `to: member_id|"all"` (`runtime.mjs:175-178`); se porta la semántica de routing, no el mecanismo in-memory | `tests/in_memory_message_bus_test.py` — `gh_candidates.md:111` |
| P4 (C5) | middleware de memoria filesystem (`src/agentscope/middleware/_longterm_memory/_agentic_memory/_middleware.py:2-5,44-46`, `gh_candidates.md:109`): store Markdown workspace-local + índice `MEMORY.md` acotado inyectado al system prompt | materializar los planos project/organizational de `engine/memory_governance.py:53` (hoy inertes, `engine_map.md:122`) + inyección por el tier `memory` de `engine/context_compiler.py:27-30` con su presupuesto de bytes | `tests/middleware_filesystem_memory_test.py` — `gh_candidates.md:111` |

(El test `tests/mem0_agentscope_adapter_test.py` del mismo repo NO aplica: es del backend mem0, que no se porta.)

### 3.2 Fuente designada para P1 (C3): `OpenBMB/ChatDev@a2ea4a2` (score 0.8475)

| Brecha | Segmento portado | Destino | Vectores de validación |
|---|---|---|---|
| P1 (C3), mitad ejecución | `PythonNodeExecutor` (`runtime/node/executor/python_executor.py:30-36,139-146`, `gh_candidates.md:95`): subprocess + timeout + workspace | extender `engine/evaluation_runs.py` (hoy `'sandboxed': False`, `engine/evaluation_runs.py:173`) bajo las puertas de aprobación existentes (`engine/policy_engine.py:86-87`) | `tests/test_code_execution_security.py`, `tests/test_session_workspace_security.py`, `tests/test_attachment_boundary_security.py` — `gh_candidates.md:99` |
| P1 (C3), mitad entrega | el "canal" de devolución NO tiene fuente: se compone del routing de agentscope (§3.1) + el artifact_factory existente (`engine/artifact_factory.py:74`) | — | — |
| P4 (C5), estado compartido | `BlackboardMemory` append-only (`runtime/node/agent/memory/blackboard_memory.py:1,19-20`, `gh_candidates.md:94`) | doctrina journal/ledger existente | **PENDIENTE**: el barrido no listó test dedicado de blackboard; identificar vector al sha antes del port |

### 3.3 Brechas sin fuente en este barrido (declaradas, no disimuladas)

- **P3 (C4, follow-ups autónomos):** ningún candidato tiene mecanismo de persecución/follow-up en los segmentos leídos. Lo más cercano es el ledger hechos/plan/progreso de MagenticOne (autogen, 0.6775, bajo umbral y auto-declarado no mantenido). Cierre: composicional (ledger de progreso + wake aprobado) o nuevo barrido con vocabulario específico.
- **Capa @mention literal de C2:** hallazgo transversal del barrido — "ningún candidato implementa chat grupal compartido con menciones '@' literales como mecanismo nativo" (`gh_candidates.md:137`). Se reconstruye composicionalmente: routing por destinatario (agentscope/MetaGPT) + selección de siguiente hablante (autogen).
- **P8 (C8, CLI externo/night-shift):** sin segmento en el barrido y fuera del top de prioridad para un producto local.
- **P5 (C1, derivación por vacante):** si se decide cerrarla, la fuente es `camel-ai/camel@797296a` (0.8175) — `RoleAssignmentAgent` es el único ✓✓ (`gh_candidates.md:119,131`); requiere su propia enmienda de allowlist.

---

## 4. Lo que el operador debe confirmar

1. **Enmienda de allowlist (gate G3/G4 de REA):** `CONFIRMED: allowlist amendment agentscope-ai/agentscope` — sin la marca exacta, el port de §3.1 no puede ejecutarse. Tier propuesto: 2 (segmentos de arquitectura al engine/ledger).
2. **Enmienda de allowlist para P1:** `CONFIRMED: allowlist amendment OpenBMB/ChatDev` si se procede con el ejecutor de §3.2. Tier 2.
3. **Decisión de producto para C3:** un ejecutor rompe la doctrina "inerte por defecto" ("Esta app no inicia agentes ni tareas en DSH" — `web/index.html:48`; "This is NOT an OS sandbox" — `engine/evaluation_runs.py:1`). Confirmar que se quiere ejecución viva y bajo cuál de las 8 puertas `require_human_approval` (`engine/policy_engine.py:86-87`).
4. **Enmienda adicional si se cierra C1:** `CONFIRMED: allowlist amendment camel-ai/camel` (fuente: `RoleAssignmentAgent`).
5. **Re-fijar sha al momento de cada port:** los sha citados son HEAD medidos el 2026-10-21 (`gh_candidates.md:6`); REA exige `repo@<sha>` exacto y los HEADs se mueven. Ninguna fuente no-allowlisted (MetaGPT, TradingAgents, crewAI, autogen, ag2) entra sin su propia enmienda; autogen además no debe usarse como fuente de la que dependa el futuro (`gh_candidates.md:58`).

---

## 5. Notas fail-honest

- **Ruta de gh_candidates.md:** no estaba en `<repo>\docs\gap\` sino en `<workspace>\docs\gap\`. Se leyó ahí. No se movió (ámbito de escritura de esta tarea: solo `PRIORIDADES.md`); unificar rutas es decisión del capitán.
- **Proveniencia de datos:** stars/sha/licencias/fechas/segmentos/tests provienen de `gh_candidates.md` (medidos 2026-10-21 con API pública GitHub, comandos reproducibles en `gh_candidates.md:162-168`). Esta tarea no re-consultó GitHub ni reabrió archivos del engine: la evidencia de brechas se hereda de los dos mapas ya auditados.
- **Juicio vs. medición:** los valores 0..1 por dimensión son juicio del sintetizador aplicado sobre artefactos medidos; las anclas de §2.2 están publicadas para que el puntaje sea auditable y reproducible.
- **Divergencia de rúbricas declarada:** esta rúbrica (20/25/15/25/15, escala 0..1, umbral 0.70) es la del encargo y difiere de la rúbrica del gate `arbx-rea` (30/20/20/15/10/5, escala 0..3, umbral 70, con `vectores_externos` como sexto criterio). Al ejecutarse los ports, `rea_adopt`/`rea_verify` reaplican sus propias gates y sus veredictos mandan sobre este ranking.
- **Sin EMPATE técnico:** 6 de 8 candidatos superan 0.70. Margen #1–#2 = 0.015 (dentro de la granularidad de anclas 0.05): por eso la recomendación designa dos fuentes por brecha en vez de descartar al segundo.
- **Vectores pendientes:** test dedicado de `BlackboardMemory` no identificado en el barrido (§3.2); C4 y capa @mention sin fuente directa (§3.3).
- **No computado:** análisis costo/beneficio de ports (esfuerzo estimado por segmento) — no pedido por el encargo y sin métrica disponible en los insumos.
