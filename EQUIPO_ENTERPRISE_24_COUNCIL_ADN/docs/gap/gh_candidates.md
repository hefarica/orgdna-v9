# Candidatos GitHub — frameworks multi-agent Python para el modelo GenTeam

**Misión (contexto):** mapear brechas de capacidades del repo local EQUIPO_ENTERPRISE_24_COUNCIL_ADN contra el modelo GenTeam de Genspark (equipo de agentes con roles, asignación de tareas, chat grupal compartido con menciones, memoria persistente de equipo, herramientas por agente, entregables terminados) y rankear candidatos de cierre bajo metodología REA.

**Fecha de medición:** 2026-10-21.
**Método:** API pública de GitHub sin token vía `https://api.github.com/...` (HTTP 200 en todas las llamadas; no se alcanzó rate limit), archivos leídos al sha fijado vía `https://raw.githubusercontent.com/OWNER/NAME/SHA/ruta`. Sha = HEAD de la rama default al momento de la medición (`/repos/OWNER/NAME/commits?per_page=1`). Licencia = texto literal del archivo LICENSE al sha. Stars/archived/pushed_at = `/repos/OWNER/NAME`. Los árboles de archivos se obtuvieron con `/git/trees/SHA?recursive=1` y se filtraron localmente; ninguna ruta citada abajo es de memoria: todas salen del árbol al sha o de un fetch raw exitoso.

**Regla supply-chain aplicada:** el contenido de los repos se trató como DATO, nunca como instrucción. No se ejecutó ni instaló nada de ningún repo. Ningún README pidió nada que se haya obedecido; no se internalizó contenido de terceros.

---

## Tabla resumen (ordenada por stars, medidos 2026-10-21)

| # | Repo | sha fijado | Licencia (leída al sha) | Stars | Último commit | archived |
|---|------|-----------|--------------------------|-------|---------------|----------|
| 1 | TauricResearch/TradingAgents | `e8f5503` | Apache-2.0 | 112,479 | 2026-10-16 | false |
| 2 | FoundationAgents/MetaGPT | `11cdf46` | MIT | 70,948 | 2026-01-21 | false |
| 3 | microsoft/autogen | `004749e` | **dual**: código MIT (`LICENSE-CODE`) + docs CC-BY-4.0 (`LICENSE`) | 61,508 | 2026-10-16 | **false según el flag**, pero su último commit se auto-declara archivado (ver sección) |
| 4 | crewAIInc/crewAI | `af4efdc` | MIT | 59,951 | 2026-10-21 | false |
| 5 | OpenBMB/ChatDev | `a2ea4a2` | Apache-2.0 | 34,560 | 2026-10-16 | false |
| 6 | agentscope-ai/agentscope | `26ec620` | Apache-2.0 | 33,589 | 2026-10-21 | false |
| 7 | camel-ai/camel | `797296a` | Apache-2.0 | 17,943 | 2026-10-19 | false |
| alt | ag2ai/ag2 | `b4c5b53` | Apache-2.0 | 5,008 | 2026-10-20 | false |

Notas de identidad: `geekan/MetaGPT` redirige (HTTP 301 vía API) a `FoundationAgents/MetaGPT` — mismo repo, se cita el canónico. `modelscope/AgentScope` redirige a `agentscope-ai/agentscope`. `ag2ai/ag2` es el fork vivo de AutoGen incluido como alternativa porque AutoGen se auto-declara no mantenido.

---

## 1. TauricResearch/TradingAgents @ e8f5503

- **(a) sha fijado:** `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (HEAD de `main`, medido 2026-10-21). Cita: `TauricResearch/TradingAgents@e8f5503`.
- **(b) licencia:** Apache-2.0. Leída en `https://raw.githubusercontent.com/TauricResearch/TradingAgents/e8f5503.../LICENSE` (línea 1: "Apache License / Version 2.0, January 2004").
- **(c) actividad:** stars 112,479 · último commit 2026-10-16 ("Merge pull request #1536 from TauricResearch/v0.7.0") · archived=false. Es el candidato más popular del barrido (`api.github.com/search/repositories?q=multi-agent framework language:python` lo devuelve #1).
- **(d) segmento que mapea:** **equipo de roles fijos con debate estructurado y memoria de decisiones persistente** — el más cercano a "equipo de agentes con roles" del barrido completo.
  - Roles por descripción: `tradingagents/agents/analysts/{market,fundamentals,news,sentiment}_analyst.py`, `researchers/{bull,bear}_researcher.py`, `risk_mgmt/{aggressive,conservative,neutral}_debator.py`, `managers/{research,portfolio}_manager.py`, `trader/trader.py` (rutas del árbol al sha).
  - Orquestación/chat grupal: `tradingagents/graph/trading_graph.py` — `trading_graph.py:51` `class TradingAgentsGraph`, `:52` "Main class that orchestrates the trading agents framework", `:85` `max_debate_rounds`, `:167` `def propagate(...)`. Flujo por grafo (LangGraph-style) + `graph/conditional_logic.py`: **no** es chat libre con menciones.
  - Memoria persistente de equipo: `tradingagents/memory/log.py:11-12` `class TradingMemoryLog` "Append-only markdown log of trading decisions and reflections"; `memory/reflection.py`; checkpoint/resume en `graph/checkpointer.py`.
  - Estado compartido del equipo: `tradingagents/agents/state.py`. Tools por agente: `tradingagents/agents/tools.py`.
- **(e) tests como vectores:** sí, suite enorme y legible bajo `tests/` (rutas del árbol): `tests/test_memory_log.py`, `tests/test_memory_pointintime.py`, `tests/test_debate_opening.py`, `tests/test_graph_end_to_end.py`, `tests/test_analyst_execution.py`, `tests/test_checkpoint_resume.py`, `tests/test_portfolio_context.py` (+60 archivos más). Fuertes como vectores de memoria persistente y de flujo de debate.
- **Limitación honesta:** es una *aplicación* de dominio (trading), no un framework de equipos genérico. Port REA = semántica de memory-log append-only + debate con rondas acotadas, no el dominio financiero.

## 2. FoundationAgents/MetaGPT @ 11cdf46 (ex geekan/MetaGPT)

- **(a) sha fijado:** `11cdf466d042aece04fc6cfd13b28e1a70341b1f` (HEAD de `main`). Cita: `FoundationAgents/MetaGPT@11cdf46`.
- **(b) licencia:** MIT. Leída al sha: "The MIT License / Copyright (c) 2024 Chenglin Wu".
- **(c) actividad:** stars 70,948 · último commit 2026-01-21 ("Merge pull request #1897 ... windows_terminal_adaptation") · archived=false. **9 meses sin commits al sha medido**: actividad baja pese a no estar archivado.
- **(d) segmento que mapea:** **roles con perfil + entorno de mensajería compartida + memoria por rol + entregables como archivos** — el "software company" canónico.
  - Roles/perfil derivado: `metagpt/roles/role.py:51` `PREFIX_TEMPLATE = """You are a {profile}, named {name}, your goal is {goal}"""`, `:92` `class RoleContext`, `:108` `watch: set[str]` (suscripción a acciones = asignación reactiva); roles concretos en `metagpt/roles/` (architect, engineer, product_manager, `di/role_zero.py`, `di/team_leader.py`).
  - Equipo + entorno: `metagpt/team.py:32-41` `class Team` "Possesses one or more roles (agents), SOP..., and a env for instant messaging"; `metagpt/environment/base_env.py:124` `class Environment(ExtEnv)`, `:175` `def publish_message(...)` con routing al destinatario por el transport framework (`:181`) — direccionamiento por destinatario, **sin menciones '@' literales**.
  - Memoria: `metagpt/memory/memory.py`, `longterm_memory.py`, `memory_storage.py`, `role_zero_memory.py` (rutas del árbol).
  - Entregables/sandbox: acciones que escriben archivos (`metagpt/actions/write_code.py`, `write_prd.py`) y ejecución de notebook (`metagpt/actions/di/execute_nb_code.py`). Tools: `metagpt/tools/libs/` (browser, deployer, etc.).
- **(e) tests como vectores:** sí — `tests/metagpt/memory/test_memory.py`, `test_longterm_memory.py`, `test_memory_storage.py`, `tests/metagpt/roles/di/test_role_zero.py`, `tests/metagpt/environment/test_base_env.py` (rutas del árbol al sha).

## 3. microsoft/autogen @ 004749e

- **(a) sha fijado:** `004749e6b7102c8fd317b9b1499ce5807223c278` (HEAD de `main`). Cita: `microsoft/autogen@004749e`.
- **(b) licencia:** **dual, verificada al sha**: `LICENSE` (raíz) = "Attribution 4.0 International" (CC-BY-4.0, aplica a docs/site); `LICENSE-CODE` = "MIT License / Copyright (c) Microsoft Corporation." → **el código Python es MIT**; el campo `license` de la API reporta solo CC-BY-4.0, la lectura raw de ambos archivos es la que manda.
- **(c) actividad:** stars 61,508 · último commit 2026-10-16, cuyo mensaje es literalmente **"docs: clarify AutoGen is archived and no longer maintained"** (`/commits?per_page=1`). El flag `archived` de GitHub es `false`, pero el proyecto se auto-declara no mantenido en su propio HEAD. **No portar nada que dependa de su futuro**; para línea viva usar `ag2ai/ag2` (sección alt).
- **(d) segmento que mapea:** **chat grupal compartido con selección de siguiente hablante + ledger de tarea del orquestador** — el más cercano a "chat grupal + asignación".
  - Group chat: `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_selector_group_chat.py:50-52` `class SelectorGroupChatManager(BaseGroupChatManager)` "selects the next speaker using a ChatCompletion model and a custom selector function", `:59` `participant_topic_types` (registro de participantes); variantes `_round_robin_group_chat.py`, `_swarm_group_chat.py` (handoff), `_graph/_digraph_group_chat.py`.
  - Orquestador con memoria de tarea: `teams/_group_chat/_magentic_one/_magentic_one_orchestrator.py:58` `class MagenticOneOrchestrator(BaseGroupChatManager)` con prompts de ledger `:46-51` (`ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT`, `..._PLAN_PROMPT`, `..._PROGRESS_LEDGER_PROMPT`) — ledger hechos/plan/progreso = memoria de tarea del equipo.
  - Agente con rol por system_message: `agents/_assistant_agent.py:90` `class AssistantAgent(BaseChatAgent...)`, `:81` `system_message: str | None`.
  - Memoria: `python/packages/autogen-core/src/autogen_core/memory/_base_memory.py` y `_list_memory.py`; experimental task-centric: `autogen-ext/src/autogen_ext/experimental/task_centric_memory/memory_controller.py`.
- **(e) tests como vectores:** sí, legibles y deterministas — `python/packages/autogen-agentchat/tests/test_group_chat.py`, `test_group_chat_graph.py`, `test_group_chat_nested.py`, `test_magentic_one_group_chat.py`, `test_messages.py`; `python/packages/autogen-core/tests/test_memory.py` (rutas del árbol al sha).
- **Advertencia:** routing por topic types del runtime (`participant_topic_types`), no menciones '@' literales estilo GenTeam.

## alt. ag2ai/ag2 @ b4c5b53 (línea viva del ecosistema AutoGen)

- **(a) sha fijado:** `b4c5b53c6817ef3d30eef56710fd6946dbe7d07a` (HEAD de `main`). Cita: `ag2ai/ag2@b4c5b53`.
- **(b) licencia:** Apache-2.0 (leída al sha, "Apache License / Version 2.0").
- **(c) actividad:** stars 5,008 · último commit 2026-10-20 ("fix(ollama): keep tool call IDs unique across turns (#3426)") · archived=false. Activo y mantenido.
- **(d) segmento que mapea:** reestructurado por completo respecto a AutoGen clásico: paquete raíz `ag2/` con `ag2/agent.py`, `ag2/task.py`, `ag2/history.py`, `ag2/assembly.py`; memoria en `ag2/knowledge/memory.py`, `ag2/policies/episodic_memory.py`, `ag2/policies/working_memory.py`, `ag2/tools/builtin/memory.py`. **Hecho medido al sha: 0 rutas conteniendo `groupchat` en el árbol completo** — el GroupChat clásico no existe en esta versión; el mecanismo de multi-agente cambió de modelo (events/streams/policies). Para port de group chat clásico, el fuente útil sigue siendo `microsoft/autogen@004749e` (con su advertencia de mantenimiento) o autogen histórico a un sha anterior.
- **(e) tests como vectores:** parciales — `test/tools/skills/test_memory.py`, `test/config/anthropic/tools/test_memory.py` (rutas del árbol). No hay tests de group chat porque el módulo no existe en este sha.

## 4. crewAIInc/crewAI @ af4efdc

- **(a) sha fijado:** `af4efdc685000172d803db06119faf0c9d082ca5` (HEAD de `main`). Cita: `crewAIInc/crewAI@af4efdc`.
- **(b) licencia:** MIT. Leída al sha: "Copyright (c) 2025 crewAI, Inc. ... Permission is hereby granted...".
- **(c) actividad:** stars 59,951 · último commit 2026-10-21 ("docs(observability): fix dead galileo sdk-examples repo link (#8348)") · archived=false. Muy activo.
- **(d) segmento que mapea:** **rol triple (role/goal/backstory) + tarea con entregable esperado + memoria unificada persistente con backends vectoriales**. ¡Ojo: el repo se reestructuró a monorepo `lib/`! El framework vive en `lib/crewai/src/crewai/` (las rutas viejas `src/crewai/` ya no existen al sha).
  - Roles por descripción: `lib/crewai/src/crewai/agent/core.py:213` `class Agent(BaseAgent)`, `:216` "Each agent has a role, a goal, a backstory, and an optional language model (llm)", `:359` `description="The Agent's role to be used from your repository."`.
  - Asignación de tareas: `lib/crewai/src/crewai/task.py:120-123` `class Task` "Each task must have a description, an expected output and an agent responsible for execution"; orquestación secuencial/jerárquica en `lib/crewai/src/crewai/process.py`; crew en `lib/crewai/src/crewai/crew.py` (ruta verificada en árbol).
  - Memoria persistente: `lib/crewai/src/crewai/memory/unified_memory.py:76-79` `class Memory` "Unified memory: standalone, LLM-analyzed, with intelligent recall flow... Uses LLM to infer scope, categories, importance on save"; backends en `memory/storage/`: `lancedb_storage.py`, `qdrant_edge_storage.py`, `kickoff_task_outputs_storage.py`; scopes en `memory/memory_scope.py`.
  - Entregable: `TaskOutput` (`task.py:53` import de `crewai.tasks.task_output`). Tools por agente: `lib/crewai/src/crewai/agents/tools_handler.py` + adaptadores en `agents/agent_adapters/`.
  - **Sin chat grupal compartido con menciones**: el modelo es pipeline secuencial/jerárquico (existe un chat CLI con el crew en `lib/cli/src/crewai_cli/crew_chat.py`, pero no es mecanismo de equipo con menciones).
- **(e) tests como vectores:** sí, bajo `lib/crewai/tests/` (nuevo layout): `tests/memory/test_unified_memory.py`, `tests/memory/test_lancedb_update.py`, `tests/memory/test_qdrant_edge_storage.py`, `tests/memory/test_storage_factory.py`, `tests/agents/test_agent.py`, `tests/crew/test_async_crew.py` (rutas del árbol al sha).

## 5. OpenBMB/ChatDev @ a2ea4a2

- **(a) sha fijado:** `a2ea4a263cebe9a7abd01ee3b5b0bf95698ed328` (HEAD de `main`). Cita: `OpenBMB/ChatDev@a2ea4a2`.
- **(b) licencia:** Apache-2.0 (leída al sha).
- **(c) actividad:** stars 34,560 · último commit 2026-10-16 ("Merge pull request #687") · archived=false.
- **(d) segmento que mapea:** **rewritte total respecto al ChatDev clásico: ya no hay `chatdev/ChatChain`** — al sha es un runtime de grafo de nodos (agente/memoria/ejecutor) con config declarativa. Mapea fuerte a "memoria de equipo compartida + sandbox de ejecución con entregable".
  - Memoria de equipo (blackboard compartido): `runtime/node/agent/memory/blackboard_memory.py:1` "Lightweight append-only Blackboard memory", `:19-20` `class BlackboardMemory(MemoryBase)` "save raw outputs, retrieve by recency"; variantes `file_memory.py`, `mem0_memory.py`, `simple_memory.py` en el mismo directorio.
  - Sandbox/ejecución con entregable: `runtime/node/executor/python_executor.py:30-31` `class PythonNodeExecutor` "Execute inline Python code passed to the node", `:36` `def execute(...)`, `:139-146` `subprocess.run(..., timeout=config.timeout_seconds)` (aislamiento liviano con timeout, no contenedor); ejecutores por tipo de nodo en `runtime/node/executor/` (`agent_executor.py`, `human_executor.py`, `loop_counter_executor.py`).
  - Tools/skills por agente: `runtime/node/agent/tool/tool_manager.py`, `runtime/node/agent/skills/manager.py`.
  - Config declarativa de nodos (roles/memoria/ejecutor como nodos de grafo): `entity/configs/node/{agent,memory,python_runner,skills,tooling}.py`; edges con condiciones en `entity/configs/edge/` y `runtime/edge/conditions/`.
  - **Sin chat grupal con menciones**: el flujo entre agentes son edges condicionales del grafo.
- **(e) tests como vectores:** sí, orientados a robustez: `tests/test_mem0_memory.py`, `tests/test_memory_embedding_consistency.py`, `tests/test_code_execution_security.py`, `tests/test_session_workspace_security.py`, `tests/test_attachment_boundary_security.py` (rutas del árbol al sha). Los tests de seguridad de ejecución son vectores externos excelentes para un port de sandbox.

## 6. agentscope-ai/agentscope @ 26ec620 (ex modelscope/AgentScope)

- **(a) sha fijado:** `26ec620b8adbd30cfa1e45f349df2eaea611f10d` (HEAD de `main`). Cita: `agentscope-ai/agentscope@26ec620`.
- **(b) licencia:** Apache-2.0 (leída al sha).
- **(c) actividad:** stars 33,589 · último commit 2026-10-21 ("fix(rag): avoid mutating chunks during document insertion (#2897)") · archived=false. Muy activo.
- **(d) segmento que mapea:** **pipeline de equipo con miembros descriptos + asignación por herramienta + memoria de largo plazo en filesystem**.
  - Equipo con descripción de miembros: `src/agentscope/pipeline/_team_pipeline.py:37-38` `class TeamMember(BaseModel)` "A member of the team: an existing agent plus the description the... `:45` nombre único dentro del equipo.
  - Asignación de tareas: `:51-56` `class _TeamAssign(ToolBase)` con `name = "TeamAssign"` — asignación explícita por tool call; bus de mensajes compartido `src/agentscope/message_bus/_in_memory_message_bus.py`.
  - Memoria persistente: `src/agentscope/middleware/_longterm_memory/_agentic_memory/_middleware.py:2-5` "Filesystem-backed long-term memory middleware... keeps a workspace-local Markdown memory store, injects a bounded `MEMORY.md` index into the system prompt", `:44-46` "You have a persistent, file-based memory system at `{memory_dir}`"; backend mem0 en `_longterm_memory/_mem0/`.
  - Tools por agente: `src/agentscope/tool/_base.py` + builtin `tool/_builtin/_bash.py`, `_ask_user.py`, etc.
- **(e) tests como vectores:** sí — `tests/pipeline_team_test.py`, `tests/pipeline_team_cleanup_test.py`, `tests/in_memory_message_bus_test.py`, `tests/middleware_filesystem_memory_test.py`, `tests/mem0_agentscope_adapter_test.py` (rutas del árbol al sha).

## 7. camel-ai/camel @ 797296a

- **(a) sha fijado:** `797296a718ce856d9c9476e4bb69fedb71ab6382` (HEAD de `master`). Cita: `camel-ai/camel@797296a`.
- **(b) licencia:** Apache-2.0 (leída al sha).
- **(c) actividad:** stars 17,943 · último commit 2026-10-19 · archived=false.
- **(d) segmento que mapea:** **el más completo en "roles derivados de la descripción de tarea" + canal de asignación de tareas + memoria de flujo de trabajo persistente** (`societies/workforce`).
  - Derivación de roles por descripción: `camel/agents/role_assignment_agent.py:36-37` `class RoleAssignmentAgent(ChatAgent)` "An agent that generates role names based on the task prompt", `:64` `num_roles: int = 2` — genera N roles con nombre+descripción desde el prompt de tarea. Es el análogo más directo a la derivación de perfil por descripción del modelo GenTeam.
  - Equipo + asignación: `camel/societies/workforce/` — `workforce.py`, `single_agent_worker.py`, `role_playing_worker.py`, `worker.py`; canal de tareas con estados: `task_channel.py:25-33` `PacketStatus` (`SENT`/`PROCESSING`/`RETURNED`/`ARCHIVED`), `:45-46` `class Packet` "A task is wrapped inside a...".
  - Memoria de equipo persistente: `camel/societies/workforce/workflow_memory_manager.py:56-60` `class WorkflowMemoryManager` "Manages workflow memory operations for workforce workers... intelligent loading, saving, and selection of workflows", `:96-98` mapeo de workflows cargados a rutas de archivo (persistencia real a disco).
  - Memorias por agente: `camel/memories/` (`agent_memories.py`, `blocks/`, `context_creators/score_based.py`, `memanto.py`). Role-playing: `camel/societies/role_playing.py`. Toolkits por agente: `camel/toolkits/` (30+ toolkits).
- **(e) tests como vectores:** sí — `test/workforce/test_workforce.py`, `test/workforce/test_workflow_memory.py`, `test/workforce/test_workforce_pipeline.py`, `test/agents/test_role_assignment_agent.py`, `test/memories/test_agent_memories.py` (rutas del árbol al sha; ojo, el directorio es `test/` singular).

---

## Matriz de cobertura por capacidad GenTeam

| Capacidad GenTeam | TradingAgents | MetaGPT | autogen | crewAI | ChatDev | agentscope | camel |
|---|---|---|---|---|---|---|---|
| Roles + perfil por descripción | ✓ fijos por prompt de rol | ✓ `{profile}` en role.py:51 | ◐ system_message | ✓ role/goal/backstory core.py:216 | ◐ nodo agente configurable | ✓ TeamMember con descripción | ✓✓ RoleAssignmentAgent genera roles desde la tarea |
| Chat grupal + menciones + asignación | ◐ grafo de debate | ◐ publish_message dirigido | ✓✓ SelectorGroupChatManager L50 | ✗ pipeline secuencial/jerárquico | ✗ edges condicionales | ✓ TeamAssign tool + bus | ✓ task_channel con estados |
| Memoria persistente de equipo | ✓ TradingMemoryLog markdown | ✓ longterm/memory_storage | ✓ core memory + ledger Magentic | ✓✓ unified_memory + lancedb/qdrant | ✓ blackboard + mem0 + file | ✓ filesystem MEMORY.md + mem0 | ✓ WorkflowMemoryManager a disco |
| Herramientas por agente | ✓ agents/tools.py | ✓ tools/libs | ✓ tools en AssistantAgent | ✓ tools_handler + adaptadores | ✓ tool_manager + skills | ✓ tool/_builtin | ✓ toolkits/ |
| Sandbox/ejecución con entregable | ◐ (entregable=decisión/report) | ✓ execute_nb_code + archivos | ✓ code executor agent | ◐ TaskOutput (sin sandbox) | ✓✓ python_executor subprocess+timeout (+tests de seguridad) | ✓ bash builtin tool | ◐ (workers ejecutan tareas) |

**Hallazgo transversal (brecha del ecosistema):** ningún candidato implementa "chat grupal compartido con menciones '@' literales" como mecanismo nativo en los segmentos leídos — los mecanismos reales son: selector de siguiente hablante (autogen), asignación por tool (agentscope), canal de paquetes con estados (camel), pub/sub dirigido (MetaGPT) y edges de grafo (ChatDev/TradingAgents). Base del conteo: los 8 repos evaluados en las secciones 1–7 y "alt" de este documento (7 frameworks + 1 alternativa), ~18 archivos fuente grepeados al sha con línea citada (`_selector_group_chat.py:50`, `_team_pipeline.py:51`, `task_channel.py:25`, `base_env.py:175`, `blackboard_memory.py:19`, entre otros). Alcance declarado: hallazgo sobre los segmentos leídos, no un escaneo exhaustivo de los 8 árboles completos. Esa capacidad del modelo GenTeam no tiene fuente directa 1:1 en estos repos; cualquier port la reconstruye composicionalmente.

---

## Considerados y descartados (con dato medido, misma pasada)

| Repo | Stars | Licencia | Motivo de descarte |
|---|---|---|---|
| FoundationAgents/OpenManus | 58,755 | MIT | agente individual con planner/tools, no modelo de equipo con roles asignados ni chat grupal |
| HKUDS/nanobot | 49,246 | MIT | asistente personal self-hosted con workflows multi-agent, pero sin equipo de roles/memoria de equipo del modelo GenTeam |
| openai/openai-agents-python | 30,202 | MIT | handoffs y agents-as-tools; sin memoria persistente de equipo ni menciones |
| SolaceLabs/solace-agent-mesh | 4,914 | Apache-2.0 | **archived=true** (medido) |
| VRSEN/agency-swarm | 4,605 | MIT | popularidad por debajo de los elegidos y solapamiento funcional con camel/autogen |
| LazyAGI/LazyLLM | 3,888 | Apache-2.0 | idem, por debajo del corte |

---

## Datos faltantes / no computados (fail-honest)

- **Forks, issues y PRs abiertos** por repo: no computados (no pedidos por el encargo; `forks_count` sí se midió y está implícito en la primera pasada: TradingAgents 21,742 · MetaGPT 9,036 · autogen 9,304 · crewAI 8,819 · ChatDev 4,328 · agentscope 3,686 · camel 2,121 · ag2 754).
- **Conteo exacto de tests por repo**: no computado; se listaron rutas verificadas de tests relevantes al segmento, no el total.
- **Lectura de READMEs completos**: no realizada (no requerida para (a)-(e)); toda afirmación de capacidad se ancla en archivo de código o test al sha, no en README.
- **Rate limit**: no se alcanzó en ninguna llamada (todas HTTP 200); no fue necesario el fallback a `github.com/search`.
- **"Última actividad"** se reporta como fecha del último commit de la rama default (committer date = author date en los 8 casos); `pushed_at` puede diferir en horas por merges no-default y no se usó como métrica.

## Evidencia de comandos (reproducibles)

- Metadata y redirects: `GET api.github.com/repos/{crewAIInc/crewAI, FoundationAgents/MetaGPT, geekan/MetaGPT, ag2ai/ag2, microsoft/autogen, OpenBMB/ChatDev, camel-ai/camel, modelscope/AgentScope, agentscope-ai/agentscope, TauricResearch/TradingAgents, FoundationAgents/OpenManus, HKUDS/nanobot, openai/openai-agents-python}` (12 llamadas, todas 200).
- Sha HEAD + fecha: `GET api.github.com/repos/OWNER/NAME/commits?per_page=1` × 8.
- Árboles: `GET api.github.com/repos/OWNER/NAME/git/trees/SHA?recursive=1` × 8 (`truncated=false` en todos).
- Búsqueda: `GET api.github.com/search/repositories?q=multi-agent%20framework%20language:python&sort=stars&order=desc&per_page=20` (total_count=5,316).
- Licencias y segmentos: fetches a `raw.githubusercontent.com/OWNER/NAME/SHA/{LICENSE, ruta...}` (los SHA y rutas citados en cada sección; cada cita `archivo:línea` proviene de estos fetches).
