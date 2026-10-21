# Mapa de capacidades del engine vs. modelo GenTeam (Genspark) — 9 capacidades

**Tarea:** `engine-map` · **Misión:** mapear brechas de EQUIPO_ENTERPRISE_24_COUNCIL_ADN contra el modelo GenTeam y rankear candidatos GitHub bajo REA (esta parte es solo el mapa del engine).
**Método:** lectura estática de `engine/` con read/grep/glob. La app NO se ejecutó. Toda evidencia es `archivo:línea` textual del repo local.
**Fecha:** 2026-10-08 (sesión engine-map).

## Contexto estructural que condiciona todos los veredictos

El engine es un **diseñador y gobernador de organizaciones de agentes, inerte por defecto**. No hay runtime de agentes en este árbol, y el propio código lo declara sin disimulo:

- `engine/bridge.py:864` — `'capabilities': {'agents_runtime': False, ...}` (declaración honesta del panel).
- `engine/orchestrator.py:141-145` — el puerto de despacho por defecto `no_runtime_dispatch` lanza `NoRuntimeError`: *"no hay runtime de AgentTeams/DSH en este árbol"*.
- `engine/dsh_connection.py:303-304` — `submit_task_plan` lanza `CAPABILITY_UNAVAILABLE: el envío de planes no está habilitado en esta versión`.
- `engine/DSH_HARNESS_CONTRACT.md:30-36` — `READ_ONLY_VERIFIED` significa roster hash + bridge autenticado, **no** identidad de sesión runtime, **no** dispatch de tareas, **no** wakeup nativo, **no** permiso para ejecutar acciones.
- `engine/gang_registry.py:28` — `NOT_MOUNTED = "Servicio no montado en este arbol (preflight BLOCKED); se registra el hash, no se ejecuta nada."`

Por eso ningún veredicto puede ser EXISTE-pleno en capacidades que exigen agentes *vivos*; el techo real es PARCIAL (mecanismo declarativo/de gobernanza completo, ejecución ausente por diseño).

---

## Resumen de veredictos

| # | Capacidad GenTeam | Veredicto |
|---|---|---|
| 1 | Contratar roles ready-made o por descripción de puesto → derivar perfil | **PARCIAL** |
| 2 | Asignar trabajo como colega (@mention / DM / tarea, rol+historial+contexto persistente) | **PARCIAL** |
| 3 | Sandbox aislado por agente + devolver ARCHIVO terminado al canal | **PARCIAL** |
| 4 | Follow-ups mid-conversation autónomos (hilo, tarea, persecución, reporte) | **AUSENTE** |
| 5 | Memoria de equipo persistente que sobrevive sesiones | **PARCIAL** |
| 6 | Lista privada de trabajo del usuario (save) que agentes trabajan bajo petición | **AUSENTE** |
| 7 | Agente de onboarding que sugiere a quién contratar y abre el primer canal | **AUSENTE** |
| 8 | Puente a agentes CLI externos (Claude Code/Codex) + night-shift a cloud | **AUSENTE** |
| 9 | Roster de roles predefinidos reutilizables | **PARCIAL** |

---

## 1. Contratar roles ready-made o por descripción de puesto y derivar el perfil

**Veredicto: PARCIAL.**

Lo que existe (fuerte en diseño):

- Roster semilla versionado: `engine/profiles.py:1-3` — *"Versioned fictional role seeds. No qualification is asserted as earned."*; `engine/profiles.py:4-5` — 24 `BASE_IDENTITIES` con UUID estables (Planner, Implementer, Reviewer, ...); `engine/profiles.py:8-89` — 32 `ROLE_SEEDS` con título, departamento, misión, 5 competencias y 3 entregables cada uno (CEO, CTO, ASSURANCE, ... COST).
- Derivación de perfil por "descripción del puesto" con LLM bajo consentimiento: `engine/org_design.py:1-7` — diseño de perfiles completos ficticios atado a evidencia, sin red al importar, cada petición fijada antes del consentimiento; presupuesto por perfil 3200 tokens (`engine/org_design.py:33`), 1 agente = 1 solicitud (`engine/org_design.py:38`).
- Generación de organización desde análisis de repo/web: `engine/core.py:800` (`generate_organization(config, analysis, model_catalog, profile_specs, ...)`); acción de panel `generate` en `engine/bridge.py:1399-1433` (organización generada localmente, *"sin llamada a una API ni inicio de agentes"* en la variante determinista).
- Edición manual del diseño: `engine/core.py:1422` (`apply_organization_edits`); `engine/bridge.py:1251-1256` (acción `edit-organization`).
- Registro versionado de perfiles (inerte): `engine/agent_registry.py:46` — `ENTRY_KINDS = ('profile', 'instructions', 'skills', 'permissions', 'models')`; `engine/agent_registry.py:478-514` — `register_profile` atómico con secciones derivadas; `engine/agent_registry.py:558-562` — `profile_ref` produce la referencia `agent-registry:profile:<id>@<ver>#<hash>` que consume el TaskGraph.
- Clases de agente por keywords de dominio: `engine/agent_kinds.py:17-44` (26 clases LEGAL..AERO + GENERAL), `engine/agent_kinds.py:54-64` (`resolve_code`), `engine/agent_kinds.py:82-97` (`resolve_preset`).

Lo que falta:

- Un flujo "contratar" unitario: hoy generar/derivar es **diseño**, no alta de un agente en un roster vivo (no hay runtime donde darse de alta). El "hire" real ocurre fuera del engine: el usuario importa manualmente el recipe exportado (`engine/core.py:1138` `export_recipe`, formato `agent-team-gui/recipe`) en DSH.
- Derivación desde una **job description libre** del usuario: el motor deriva perfiles del análisis de repo/web + objetivo (`engine/autonomy.py:76-89` `mission_for_project`), no de un texto de vacante.

## 2. Asignar trabajo como a un colega: @mention en canal compartido, DM o tarea asignada, con rol+historial+contexto persistente

**Veredicto: PARCIAL.**

Lo que existe (la parte "tarea asignada + rol + contexto"):

- Tarea asignada declarativa: `engine/task_graph.py:95-97` — `TASKSPEC_FIELDS` incluye `agent_ref`; `engine/task_graph.py:545` — campo `agent_ref: str | None`; `engine/task_graph.py:558-559` — validación de `agent_ref` (1..120 chars, referencia declarativa cuya presencia no prueba que el agente exista, según `engine/agent_registry.py:10-11`).
- Despacho respetando agente: `engine/scheduler.py:367` — `dispatch(task_id, node.agent_ref, node.lease_id)`; el scheduler decide QUÉ lanzar y a quién refiere, pero el runtime es un puerto inyectado (`engine/scheduler.py:6-11`).
- Contexto por agente+tarea acotado y determinista: `engine/context_compiler.py:27-30` — `_TIERS = ("mandate", "task", "evidence", "skill", "memory", "handoff")`; `engine/context_compiler.py:100-109` — mandate extrae `name, role, title, mission, personality, reports_to`; presupuesto de bytes y "nada se descarta en silencio" (`engine/context_compiler.py:4-9`).
- Historial de desempeño por agente: registros `performance_records`, `promotion_records`, `governance_events` (`engine/bridge.py:518`), scoreboard derivado (`engine/bridge.py:862`).
- Dossier personal → contexto: `engine/agent_dossier.py:107-140` — emite `mandate` + `memory` en las formas exactas de context_compiler.

Lo que NO existe (la parte "@mention / canal / DM"):

- Grep `(?i)(@mention|canal compartido|direct message|dm|inbox|buzón)` sobre `engine/` **sin resultados** en código de mensajería (solo `must_mention` de `engine/instruction_contract.py:21`, que es un check contractual de prosa, y descripciones de herramientas AgentTeams dentro de `engine/tool_catalog.json:7252` — dato de catálogo, no implementación).
- El único "bus de mensajes" es el cartucho Cordis, declarado inerte: `engine/cordis_extension.py:30` — `OPERATIONS = ('state', 'message', 'task', 'evidence', 'memory', 'learning')` como herramientas propuestas `orgdna_<uuid>_<op>` (`engine/cordis_extension.py:47-49`), con `engine/cordis_extension.py:174` — `'message_delivery': {'mode': 'polling_only', 'native_wake_available': False, 'all_members_connected': False}` y activación `BLOCKED_RUNTIME_NOT_VERIFIED` (`engine/cordis_extension.py:210`).
- La gobernanza ya prevé el caso (sin transporte): `engine/policy_engine.py:89-91` — acción `send_message_out` existe como tipo, y levanta la puerta humana `connectors` (`engine/policy_engine.py:86`).

Faltaría: bus de mensajes entre agentes con entrega y wake, historial conversacional por hilo, y la unión agent_ref → sesión viva (`engine/cordis_extension.py:213-215` lo lista como bloqueante: "Vinculación de sesiones vivas a UUID de miembros pendiente").

## 3. Cada agente trabaja en sandbox aislado propio y devuelve el ARCHIVO terminado al canal

**Veredicto: PARCIAL (hay aislamiento cooperativo de escrituras y fábrica de archivos locales; no hay sandbox por agente ni canal de devolución).**

Lo que existe:

- Aislamiento de escrituras por tickets (leases): `engine/coordination.py:21` — `MAX_WRITERS = 3`; `engine/coordination.py:54-80` — paths normalizados, conflicto padre/hijo bloqueado; `engine/coordination.py:220-289` — `lease-acquire/renew/release` con `expected_version` (concurrencia optimista) e idempotencia por `request_id`; `engine/coordination.py:37-51` — workspace por agente/tarea con base_sha.
- El scheduler exige lease antes de despachar un nodo con capacidad de escritura: `engine/scheduler.py:361-364` — evento `LEASE_REQUIRED`, "nodo con capacidad de escritura sin lease: no se despacha".
- Autonomía con techo y aprobación explícita para escribir: `engine/task_graph.py:84-86` — `AUTONOMY_LEVELS = ('observe','propose','prepare','execute-approved')`, `WRITE_CAPABLE_AUTONOMY_LEVELS = ('prepare','execute-approved')`; `engine/task_graph.py:373-383` — escribir exige `approved=True` o la tarea no se construye.
- Entregables locales firmados: `engine/artifact_factory.py:74` — `ARTIFACT_KINDS = ('report','patch','ticket','runbook','bundle')`; `engine/artifact_factory.py:10-12` — cada artefacto se escribe bajo la raíz declarada por el llamador, con `sha256` recomprobado y recibo; `engine/artifact_factory.py:14-18` — no push, no PR, no merge, no deploy, no git.
- Contrato textual de aislamiento por escritor embebido en los exports: `engine/core.py:637` — *"Implementar sólo el alcance asignado, con archivos/worktree y puertos aislados si hay paralelismo"*; `engine/core.py:659` — *"Máximo 3 escritores con leases y archivos aislados"* (es prompt-contract para el runtime importado, no enforcement del engine).

Lo que NO existe:

- Sandbox de ejecución: `engine/evaluation_runs.py:1` — *"Explicitly approved, bounded local test runs. This is NOT an OS sandbox."*; `engine/evaluation_runs.py:173` — `'sandboxed': False` con aviso de riesgo. Las herramientas `sandbox_rust/python/js` del catálogo son nombres de herramientas DSH (`engine/tool_catalog.json:6318-6410`) con la advertencia explícita de que *"El nombre sandbox no acredita aislamiento"* (`engine/tool_catalog.json:215`).
- Los tickets son cooperativos y sin lock de FS: `engine/coordination.py:1-5` — *"These tickets coordinate cooperative clients; an external editor can ignore them"*; `engine/coordination.py:205-206` — `'enforcement': 'local_coordination_only', 'filesystem_lock_enforced': False`.
- No hay canal al que devolver el archivo: el "canal" no existe (ver capacidad 2).

## 4. Detección de follow-ups mid-conversation (el agente abre hilo, crea tarea, persigue y reporta sin que se lo pidan)

**Veredicto: AUSENTE.**

Evidencia de ausencia (mecanismos que explícitamente NO son proactivos):

- Sin reintentos automáticos: `engine/scheduler.py:298-303` — `ready_tasks`: *"Un 'failed' o 'blocked' no vuelve a estar listo jamas: no hay reintento automatico"*.
- Reapertura solo por decisión explícita: `engine/scheduler.py:436-444` — `reopen(...)`: *"Saca un nodo de 'blocked' por DECISION EXPLICITA. Nunca ocurre sola."*
- El tick del supervisor es manual: `engine/gang_supervisor.py:19-21` — *"El tick es EXPLICITO: este producto es offline y dirigido por panel, asi que no hay demonio por defecto."*
- El improvement loop es conducido, no autónomo: `engine/improvement_loop.py:11-12` — *"No instala, no ejecuta, no entrena. La recompensa y la propagación son del llamador"*; estados `FAIL_OBSERVED -> ... -> PUBLISHED_VERSION` (`engine/improvement_loop.py:7-10`) son una máquina que alguien conduce.
- Terminación del orquestador por progreso, sin persecución de pendientes: `engine/orchestrator.py:16-19` — si un tick no avanza, para en BLOCKED; nunca inventa `passed`.

Grep `(?i)(follow.?up|hilo|thread)` sobre `engine/`: solo `threading` de Python y herramientas de catálogo. No hay hilos conversacionales, ni cola de seguimiento, ni creación autónoma de tareas por un agente.

Faltaría: un observador con iniciativa (hoy ni siquiera hay runtime), detectores de compromiso-no-cumplido en conversación, y el derecho (política) a crear tareas sin petición — la política actual exige aprobación humana para casi toda acción con efecto (`engine/policy_engine.py:86-87`: 8 puertas con default `require_human_approval`).

## 5. Memoria de equipo persistente que sobrevive sesiones

**Veredicto: PARCIAL.**

Lo que existe (persistencia real en disco):

- Registros de equipo versionados en snapshots de proyecto: `engine/bridge.py:518` — `records = {'council_sessions': [], 'skill_registry': [], 'remediation_records': [], 'subteams': [], 'performance_records': [], 'promotion_records': [], 'governance_events': []}`; se guardan en el snapshot (`engine/bridge.py:999`) y se recargan con validación y límites (`engine/bridge.py:1045-1055`); el store escribe versiones inmutables con `.sha256` (observado: `data/projects/98d8ec4f-.../versions/*.json` + `.sha256`).
- Journal del gang en disco que sobrevive crashes: `engine/gang_journal.py:1-12` — *"Journal del gang: append-only en disco, con replay que sobrevive al crash"*; montado en `data/projects/_gang_journal.jsonl` (`engine/bridge.py:532-533`); replay fail-closed (`engine/gang_journal.py:47-60`).
- Biblioteca de capacidades persistente: `engine/capability_hub.py:22` — sqlite en `data/projects/_capabilities/registry.sqlite3` con asignaciones CAS por agente.
- Ledger de coordinación global: `engine/bridge.py:514-515` — `CoordinationStore(self.project_store.root / '_coordination')`; contrato en `engine/LOCAL_COORDINATION_CONTRACT.md:44` (ledger único cubre todos los proyectos del store, serializado entre procesos).

La capa de gobierno (que existe pero no materializa almacén):

- `engine/memory_governance.py:53` — cuatro planos `('execution','project','organizational','personal')` con `PROMOTION_ROUTES` (`engine/memory_governance.py:70-71`), TTL explícito, `read_permissions` y aislamiento por tenant (`engine/memory_governance.py:14-21`); plano de ejecución efímero (`engine/memory_governance.py:75` — *"efimero: vive en el proceso; sin persistencia autorizada no sobrevive"*). El módulo es INERTE: `engine/memory_governance.py:4-6` — *"No ejecuta agentes, no escribe ficheros, no abre red y no materializa ningun almacen."*

Faltaría: materializar el almacén de planos (project/organizational) detrás de memory_governance y ligar memoria por agente a un runtime (hoy no hay agentes vivos que recuerden). El dossier personal (`engine/agent_dossier.py`) sí alimenta contexto, pero vive dentro del snapshot del proyecto, no como memoria consultable por agentes en ejecución.

## 6. Lista privada de trabajo que el usuario guarda (save) y los agentes trabajan bajo petición

**Veredicto: AUSENTE.**

- Grep de mecanismos (`(?i)(backlog|todo list|lista de trabajo|save for later|trabajo bajo peticion|on demand)`) sobre `engine/`: sin resultados.
- Lo más cercano es el TaskGraph declarativo (`engine/task_graph.py:1-20`): construye y valida DAGs, pero es inerte (`engine/task_graph.py:12-14` — *"no ejecuta, no programa ni despacha ninguna tarea, y no escribe ningun artefacto"*), no hay store de "lista del usuario" ni flujo save→trabajo-bajo-petición.
- El ProjectStore guarda diseños y registros de gobernanza (`engine/bridge.py:988-1002`), no una cola privada de pendientes del usuario.

Faltaría: un store de backlog del usuario (con estado saved/requested), una acción de panel para agregar ítems, y un dispatcher que convierta un ítem en TaskSpec bajo petición explícita.

## 7. Agente de onboarding que sugiere a quién contratar y abre el primer canal

**Veredicto: AUSENTE.**

- No existe capa de canales (ver capacidad 2), así que "abre el primer canal" no tiene sustrato.
- No existe agente de onboarding: grep `(?i)(onboarding|primer canal|who to hire|a quien contratar)` sobre `engine/`: sin resultados.
- Vecinos parciales (no onboarding): la generación de organización propone roles desde el inventario del repo (`engine/core.py:800`; prompt que infiere profesiones con evidencia en `engine/providers.py:1137`); `IntegrationRecommendations` sugiere **capacidades/plugins** a importar (`engine/bridge.py:1141-1142`, acciones `engine/integration_recommendations.py`), no contrataciones.

Faltaría: un recomendador de contratación (qué rol cubre qué brecha del repo, con evidencia), y la apertura de un canal inicial — que a su vez exige la capa de mensajería de la capacidad 2.

## 8. Puente a agentes CLI externos (Claude Code/Codex CLI) con traspaso night-shift a agentes cloud

**Veredicto: AUSENTE.**

- El único "puente" que existe es READ-ONLY hacia DSH local: `engine/dsh_connection.py:298-301` — `prepare_task_plan` devuelve `BLOCKED_CAPABILITY` con razón textual; `engine/dsh_connection.py:303-304` — `submit_task_plan` lanza `CAPABILITY_UNAVAILABLE`; `engine/DSH_HARNESS_CONTRACT.md:30-36` — verificación read-only ≠ dispatch/wakeup/ejecución.
- El cartucho de orquestación nativa está deshabilitado por diseño: `engine/cordis_extension.py:183-188` — `native_orchestration: {'enabled': False, ..., 'automatic_approval': False, 'runtime_verified': False}`; el adaptador AgentTeams vive en `BLOCKED_UNVERIFIED_HOST_BINDING` (`engine/cordis_extension.py:200-203`).
- Grep `(?i)(claude|codex|night.?shift|cli externo)` sobre `engine/`: solo detección de directorios auxiliares al analizar repos ajenos (`engine/providers.py:458` — `_AUXILIARY_DIRS = {".agent", ".agents", ".claude", ...}`) y descripciones de las herramientas `why_*` en `engine/tool_catalog.json:8264,8298` (catálogo). Cero integración de ejecución con CLIs de agentes; cero mecanismo de turno nocturno o traspaso a agentes cloud.

Faltaría: (a) un adaptador de proceso CLI (spawn + protocolo de entrada/salida) por agente externo, (b) política de traspaso de contexto (el tier `handoff` de `engine/context_compiler.py:47` y `handoff_summary_max_chars` de `engine/autonomy.py:53` son el embrión declarativo del resumen de traspaso), (c) gates de supply-chain antes de ejecutar binarios externos.

## 9. Roster de roles predefinidos reutilizables

**Veredicto: PARCIAL.**

Lo que existe:

- `engine/profiles.py:2-3` — `PROFILE_VERSION = '1.0'`, semillas estables ("Names and UUIDs are stable identifiers from the user-provided ArbitrageX recipe"); `engine/profiles.py:8-89` — 32 roles con misión/competencias/entregables; roles de auditor y consultor tipados (`engine/profiles.py:90-91`).
- Clases de agente reutilizables para cualquier dominio: `engine/agent_kinds.py:17-44` (26 clases + GENERAL) con resolución determinista y presets de herramientas contra el catálogo del usuario (`engine/agent_kinds.py:82-97`).
- Presets por rol del catálogo: `engine/tool_permissions.py:15` (`ROLE_NAMES`), `engine/tool_permissions.py:100` (match contra `role_presets` del catálogo), `engine/bridge.py:587-589` (catálogo con `role_presets`).
- Roles por playbook: `engine/playbooks.py:18-25` (VALUE, LAYEXEC, BANKROLL, LIVESTATS, LEARNLOSS, ORCH para el único playbook shipped `betfair_value_lay`, `engine/playbooks.py:31`).

Por qué no es EXISTE: el roster es **semilla de diseño**, no roster vivo instanciable. La reutilización operativa real ocurre al re-importar el recipe/definitions exportado (`engine/core.py:1138`, `engine/core.py:1263`, formato `agent-team-gui/*`) en DSH, fuera de este engine. No hay "contratar del roster → agente corriendo" dentro del árbol.

---

## Inventario de mecanismos de mensajes / wake / sandbox / entregables (aunque no mapeen a las 9)

### Mensajería y wake

1. **Bus Cordis polling-only (inerte):** herramientas `orgdna_<uuid>_{state,message,task,evidence,memory,learning}` (`engine/cordis_extension.py:30,47-49`); entrega `polling_only`, `native_wake_available: False`, `all_members_connected: False` (`engine/cordis_extension.py:174`); advertencia de que el bus "no despierta miembros ni inyecta mensajes en otras sesiones" (`engine/cordis_extension.py:218`).
2. **Wake nativo: declarado no disponible/no verificado:** `engine/cordis_extension.py:74` — *"polling_only/native_wake_unavailable hasta comprobar adaptador nativo"*; `engine/dsh_connection.py:258` — `'native_agent_wakeup_verified': False`.
3. **`send_message_out` como acción de política (sin transporte):** `engine/policy_engine.py:89-91`; levanta la puerta humana `connectors` (`engine/policy_engine.py:86`; también `engine/memory_governance.py:23-26` para hand-offs externos de memoria).
4. **Eventos del loop de orquestación (mensajería máquina, no conversacional):** `GATE_BLOCKED`, `PENDING_NO_SLOT`, `LEASE_REQUIRED`, `DISPATCH_UNAVAILABLE`, `DISPATCH_FAILED`, `DISPATCHED` (`engine/scheduler.py:349,359,364,372,382,385`) y `COMPLETED` (`engine/orchestrator.py:192`); agrupados por `blocked_reasons` (`engine/orchestrator.py:221-228`).
5. **Contratos de fase embebidos en el squad (mensajes al runtime importado):** `engine/core.py:634-659` — `ORGDNA_PHASE=council|implementation`, NEEDS_PLAN/BLOCKED, máximo 3 escritores.

### Sandbox / aislamiento

6. **Tickets de escritura globales (cooperativos):** `engine/coordination.py` completo; `MAX_WRITERS=3` (`engine/coordination.py:21`), TTL 60..3600s (`engine/coordination.py:245-247`), concurrencia optimista por `expected_version` (`engine/coordination.py:255-256`), idempotencia por `request_id` con fingerprint (`engine/coordination.py:248-254`); enforcement declarado `local_coordination_only` (`engine/coordination.py:205-206`); contrato completo en `engine/LOCAL_COORDINATION_CONTRACT.md:44`.
7. **Aislamiento por tenant y dominios:** `engine/tenants.py:50-82` — 6 dominios (`organizations, projects, sensitive_material, budgets, memories, artifacts`), `sensitive_material` no materializable, `memories` nunca exportado, lectura con `tenant_id` exacto o error tipado (`engine/tenants.py:62-63`).
8. **Planos de memoria con reglas de contaminación:** `engine/memory_governance.py:78-82` — `READ_RULE`, `CROSS_PLANE_READS=False`, `CROSS_TENANT_READS=False`, `CONTAMINATES=False`.
9. **No-sandbox honesto para ejecución local:** `engine/evaluation_runs.py:1,76,173` — `'sandboxed': False`, riesgo textual; ejecución aprobada por plan exacto (hash) y cancelable (`engine/evaluation_runs.py:216-217`).
10. **Autonomía con techo y aprobación:** `engine/task_graph.py:84-86,373-383`; techo por defecto `observe` (`engine/policy_engine.py:93-94`); 8 puertas humanas default `require_human_approval` (`engine/policy_engine.py:86-87`).

### Entregables

11. **Artifact Factory local firmado:** `engine/artifact_factory.py:74-77` — kinds `report/patch/ticket/runbook/bundle` con media types; recibo con `sha256` y anti-sobrescritura (`artifact_already_written`, `engine/artifact_factory.py:26-27`); directorios fuente protegidos (`engine/artifact_factory.py:101-102`).
12. **Export nativo agent-team-gui (el entregable real hacia el runtime):** `engine/core.py:1138` (`export_recipe`, fases implementation/council), `engine/core.py:1263` (`export_definitions`); archivos de export observados en la raíz del repo (`agent-team-recipe-*.json`, `agent-team-export-manifest.json`, `agent-team-backup-*.json`).
13. **Cartucho Cordis empaquetado (ZIP inerte):** `engine/cordis_extension.py:231-287` — zip con manifest, dry-run, scope-diff, exports extendidos y `SHA256SUMS.txt`; `activation.enabled=False`, `requires_owner_review=True` (`engine/cordis_extension.py:176-177`).
14. **Gang assembly sellado:** `engine/gang_assembly.py:98-120` — invariantes N exacto, ids únicos, slots 1..N, jerarquía sin ciclos ni huérfanos; orden topológico jefes-antes-que-subordinados (`engine/gang_assembly.py:47-95`); SHA-256 + changelog versionado.
15. **Publicación 2PC idempotente del gang:** `engine/gang_registry.py:99-156` — prepare/commit con abort y compensación; idempotencia por SHA de contenido (`engine/gang_registry.py:110-118`); targets `('cordi','agent-team','team')` (`engine/gang_registry.py:27`).
16. **Nodos de servicio HTTP con fencing por epoch:** `engine/gang_services.py:4-10` — superficie `GET /health`, `GET /dna`, `POST /prepare|commit|abort|compensate`, `POST /dna/rollback`; `_fence` rechaza epoch obsoleto (`engine/gang_services.py:71-78`); compensación sube epoch (anti split-brain).
17. **Montaje/desmontaje desde el panel:** `engine/bridge.py:1319-1336` (`gang-mount`: 3 procesos HTTP locales reales, supervisor con lease), `engine/bridge.py:1337-1347` (`gang-unmount`), `engine/bridge.py:1348-1359` (`gang-tick`: *"esto coordina los nodos locales, no ejecuta nada en DSH"*).
18. **Supervisor con lease anti-split-brain:** `engine/gang_supervisor.py:5-17` (tres garantías), lease de supervisión vía CoordinationStore (`engine/gang_supervisor.py:107-128`), revalidación adoptando epoch máximo (`engine/gang_supervisor.py:86-93`), reanudación idempotente desde el journal.
19. **Fitness del gang sobre recibos facturados reales:** `engine/gang_fitness.py:20` — pesos `{exito:0.60, latencia:0.20, costo:0.15, continuaciones:0.05}`; métrica para el bucle de evolución (`engine/gang_fitness.py:1-6`).
20. **Journal append-only con replay fail-closed:** `engine/gang_journal.py:1-12,47-60`.
21. **Mejora continua como máquina de estados:** `engine/improvement_loop.py:7-12` — `FAIL_OBSERVED -> ROOT_CAUSE_REVIEWED -> SKILL_DRAFTED -> SUPERVISOR_APPROVED -> RETEST_PASS -> INDEPENDENT_APPROVED -> PUBLISHED_VERSION`, retest fallido regresa a `SKILL_DRAFTED` (intentos acotados `MAX_ATTEMPTS=9`, `engine/improvement_loop.py:22`).
22. **Contrato de instrucción (anti-drift del LLM):** `engine/instruction_contract.py:5-11` — faltas `dropped/added/softened`; `reconcile` repara solo con reglas declaradas; `retry_prompt` devuelve la corrección literal (`engine/instruction_contract.py:9-10`).
23. **Compilador de contexto con presupuesto:** `engine/context_compiler.py:19-30` (1024..96000 bytes, 64 ítems/sección, `mandate` nunca se descarta); tier `handoff` con forma `{id, from, to, summary}` (`engine/context_compiler.py:47`).
24. **Autonomía DSH preview:** presets `autonomous/smart/manual` (`engine/autonomy.py:17`), backend `teams_gui|agentteams_native` (`engine/autonomy.py:38-40`), quality gate con par revisor/reparador independiente (`engine/autonomy.py:102-116`), `handoff_summary_max_chars` y `runtime_token_budget` (`engine/autonomy.py:53-54`).
25. **Connector Gateway declarativo (todo deshabilitado):** `engine/connector_gateway.py:71` — `ENABLED_BY_DEFAULT = False`; conectores `github/drive/database/web/ci/email` (`engine/connector_gateway.py:74`) con permisos y alcances de lista cerrada (`engine/connector_gateway.py:89-105`); cero conexiones vivas por construcción (`engine/connector_gateway.py:22-26`).
26. **DSH launcher + harness (read-only):** arranque headless del EXE original con backups (`engine/bridge.py:545`, contrato `engine/DSH_HARNESS_CONTRACT.md:8-38`); pairing efímero de un uso, `diagnose` con scopes `teams.profiles.read / agentteams.state.read / cordis.capabilities.read` (`engine/dsh_connection.py:262-264`).
27. **Almacén de secretos DPAPI:** `engine/bridge.py:371-420` — opt-in, CurrentUser, nunca archivo de texto plano; redacción de secretos en toda salida (`engine/bridge.py:565-579`).
28. **Workflows recurso→rol (planes, no ejecución):** `engine/resource_workflows.py:1-7` — *"Resource-to-role work plans, never resource execution or installation"*; guardrails y pasos de arranque en staging (`engine/resource_workflows.py:37-64`).
29. **Biblioteca de capacidades con asignaciones por agente:** `engine/capability_hub.py:13-14` (acciones search/import/apply/audit...), sqlite con revisiones (`engine/capability_hub.py:22`), planes de deployment `applied=False, runtime_verified=False` (`engine/capability_hub.py:53-54`).

---

## Notas fail-honest de esta lectura

- Archivos leídos **completos**: `coordination.py`, `task_graph.py`, `scheduler.py`, `orchestrator.py`, `agent_registry.py`, `agent_kinds.py`, `agent_dossier.py`, `playbooks.py`, `limits.py`, `cordis_extension.py`, `DSH_HARNESS_CONTRACT.md`, `gang_fitness.py` (hasta línea 60 de 96 — resto es desglose de la misma fórmula), `gang_journal.py` (60/109 — resto es escritura/replay simétrico a lo leído).
- Archivos leídos **parcialmente** (cabecera + secciones clave citadas): `bridge.py` (líneas 1-1530 de ~1700; acciones gang y stores cubiertas; el tramo final son handlers HTTP de descarga), `gang_assembly.py` (120/162), `gang_registry.py` (150/156), `gang_services.py` (130/273 — la mitad restante es el handler HTTP de la superficie ya documentada), `gang_supervisor.py` (130/181 — falta el cuerpo final de `tick`, cuyo contrato está citado del docstring y de `bridge.py:1348-1359`), `instruction_contract.py` (150/220 — falta el final de `reconcile`/`retry_prompt`, citados por docstring), `context_compiler.py` (150/257), `memory_governance.py` (120/724 — constantes y reglas congeladas cubiertas), `tenants.py` (100/548), `autonomy.py` (140/248), `org_design.py` (130/1083), `dna.py` (130/411), `profiles.py` (100/131), `policy_engine.py` (110/915), `connector_gateway.py` (120/645), `artifact_factory.py` (120/792), `capability_hub.py` (100/194), `improvement_loop.py` (90/240), `resource_workflows.py` (70/345), `dsh_connection.py` (250-304).
- `tool_permissions.py` se inspeccionó por grep dirigido (`ROLE_NAMES`, `apply_tool_policy`, presets), no lectura completa.
- No ejecuté la app, ningún test ni ningún módulo: veredictos basados solo en lectura estática. Los states `runtime_verified: False` citados son declaraciones del propio código, no mediciones mías.
- Ausencia declarada como ausencia: los greps de `@mention/canal/DM`, `onboarding`, `follow-up/hilo`, `claude/codex/night-shift` y `backlog/lista de trabajo` no arrojaron mecanismos en `engine/`; eso es evidencia de búsqueda negativa, no certeza absoluta de inexistencia fuera de `engine/` (no auditué `web/`, `cordis_extension/` JS ni `docs/` completos para estas capacidades — fuera del alcance de esta tarea).
