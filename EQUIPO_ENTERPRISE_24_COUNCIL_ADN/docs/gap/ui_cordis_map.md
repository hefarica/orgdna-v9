# Mapa de brechas UI/panel + plugin Cordis vs. modelo GenTeam (Genspark)

Tarea `[ui-cordis-map]` · Repo: `EQUIPO_ENTERPRISE_24_COUNCIL_ADN` · Método: lectura estática
(read/grep/glob). Nada fue ejecutado. Veredictos: **EXISTE / PARCIAL / AUSENTE**, siempre
referidos a la capa UI/panel (`web/`, `engine/templates_bundle/`) y al plugin Cordis
(`cordis_extension/`), no a DSH/AgentTeams externos.

Escala de la evidencia leída:
- Leídos completos: `plugin.mjs`, `runtime.mjs`, `live_bridge.mjs`, `native_orchestration.mjs`,
  `skillhub.mjs`, `agentteams-adapter.mjs`, `entry.mjs`, `TOOL_CONTRACT.md`,
  `engine/templates_bundle/viewer.html`, `engine/profiles.py` (L1–95 de 131),
  `engine/dsh_connection.py` (L285–304 + greps dirigidos), `engine/coordination.py` (greps),
  `cordis_extension/README_ES.md` (L1–180 de 289).
- Parciales (líneas >2000 chars truncadas por el lector): `web/index.html` L84, L87, L92, L97,
  L102, L121–125; `web/app.js` (líneas que matchearon grep); `native_stage_ui.mjs` L160 (cola
  del script de la página embebida).
- No leídos (declarados): `preflight.mjs`, `prepare-overlay.mjs`, `skillhub-preflight*.mjs`,
  `skillhub-package.mjs`, `package.json`, `SOURCES.json`, `cordis_extension/tests/*`,
  `web/style.css`, `VISOR_DE_PERFILES.html` (artefacto generado; el generador está auditado en
  `engine/bundle.py`), resto de `engine/*.py` fuera de los greps citados.

---

## C1. Contratar roles ready-made o por descripción de puesto — **PARCIAL**

**Qué existe.**
- Generación de organización completa "por descripción de puesto/proyecto": formulario con
  objetivo, N exacto de perfiles, plantilla y modelo → "Preparar ADN con IA"
  (`web/index.html:44`, `web/index.html:50-56`).
- Catálogo ready-made PROPIO como plantilla offline: `engine/profiles.py:8-89` define
  `ROLE_SEEDS` (32 roles con título, departamento, misión, 5 competencias y 3 entregables) y
  `engine/profiles.py:4-5` fija 24 identidades estables con UUID; selector de plantilla
  "ArbitrageX / General" en `web/index.html:62`.
- Catálogo de squads/perfiles/capitanes YA EXISTENTES en la UI nativa de staging
  (`native_stage_ui.mjs:91-97`, acción `catalog`), solo sobre definiciones propias de Teams.

**Qué no existe.**
- Contratación individual de UN rol nuevo dentro de un equipo existente (siempre se genera o
  se stagen equipos completos; `prepareNativeStagePlan` exige roster 1..32 completo con
  capitán incluido, `native_orchestration.mjs:39-41`).
- Marketplace de roles de terceros: PluginShop busca extensiones/plugins, no agentes
  (`web/index.html:121`, `engine/plugin_shop.py` no leído a fondo).
- La lectura de perfiles del bridge es de catálogo propio: `agentTeamGui.readDefinitionSnapshot`
  (`live_bridge.mjs:73`).

**Faltaría:** flujo "añadir 1 miembro a equipo existente" (hoy bloqueado por diseño:
`EXISTING_TEAM_PRESERVED`, `native_stage_ui.mjs:75`); catálogo de roles contratables externo.

## C2. Asignar trabajo como colega (@mention / DM / tarea con rol+historial+contexto) — **PARCIAL**

**Qué existe.**
- DM y broadcast en el ledger compartido: operación `message` con `to: member_id|"all"` +
  `topic` (`runtime.mjs:175-178`); bandeja filtrada al leer (solo destinatario/remitente/broadcast,
  `runtime.mjs:151`); contrato en `TOOL_CONTRACT.md:15` ("Registro compartido; no wake").
- Tareas con ciclo claim/block/submit/accept/reject, dueño, dependencias, historial y evidencia
  (`runtime.mjs:190-215`; `TOOL_CONTRACT.md:20-25`). Revisión independiente fuera de la cadena
  de mando (`runtime.mjs:240-251`).
- Ruta NATIVA (solo tras staging en DSH, no en este panel): los tools `agent_teams_send_message`,
  `agent_teams_claim_task`, `agent_teams_update_task`, `agent_teams_status` se inyectan al scope
  de miembros/capitán (`native_orchestration.mjs:10-11`, `native_orchestration.mjs:48`,
  `native_orchestration.mjs:55`).

**Qué no existe.**
- @mention como sintaxis/canal compartido en vivo: los mensajes son registros en inbox sin wake
  (`plugin.mjs:5` "Stored inbox only; no wake"); `live_messages` está explícitamente `available:false`
  ("Shared coordination records do not wake native agents", `live_bridge.mjs:65`).
- Cualquier superficie de chat/DM en el panel web: en `web/index.html` no existe UI de
  mensajería; el Council es registro manual preparatorio ("Esta vista no ejecuta agentes",
  `web/index.html:102`).
- "rol+historial+contexto" enriquecido al asignar: la tarea del ledger lleva título/dueño/deps,
  no adjunta CV ni historial del miembro (sí lo hace el ADN exportado, fuera del ledger).

**Faltaría:** UI de canal/hilo sobre el ledger; despertar (wake) aprobado; adjuntar dossier del
miembro al asignar (el dossier existe: `engine/agent_dossier.py`, no leído).

## C3. Sandbox aislado por agente que devuelve el archivo terminado al canal — **AUSENTE**

**Evidencia de ausencia.**
- La app declara no ejecutar agentes: "Esta app no inicia agentes ni tareas en DSH"
  (`web/index.html:48`).
- No hay ningún mecanismo de sandbox/ejecución en `cordis_extension/` (los 6 tools son
  registro; `runtime.mjs:1` "No agent engine, network, or executable learning") ni en `web/`.
- Lo más cercano son RESERVAS DE RUTAS (leases), que son coordinación declarativa, no aislamiento:
  `engine/coordination.py:21` (`MAX_WRITERS = 3`), leases con expiración/renovación
  (`engine/coordination.py:193-288`), pero autoetiquetados `filesystem_lock_enforced: False`,
  `dsh_enforced: False` (`engine/coordination.py:158-160`); el panel lo dice explícitamente
  ("no bloquean el sistema de archivos ni fuerzan permisos en DSH", `web/index.html:102`).
- El "worktree aislado" del handoff es doctrina en texto, no código (`10_COORDINACION_Y_RESERVAS.md:17`).

**Faltaría:** ejecutor con sandbox por agente + entrega del artefacto al canal. Hoy la ejecución
es externa (AgentTeams nativo) y la devolución de archivos no existe como flujo de UI.

## C4. Follow-ups automáticos mid-conversation (hilo, persecución de progreso, reporte) — **AUSENTE**

**Evidencia de ausencia.**
- `realtime_events: available:false` — "reads are explicit, not background polling"
  (`live_bridge.mjs:66`).
- Sin wake: el bus nunca inicia sesiones ni solicitudes a modelos (`plugin.mjs:5`;
  `README_ES.md:15-17`).
- El único polling del panel es `pollHarness` (1 s) mientras se espera el arranque del runtime
  local DSH, y es contra el motor local propio, no contra conversaciones de agentes
  (`web/app.js:1085`).
- Ni `runtime.mjs` ni `live_bridge.mjs` definen temporizadores de follow-up, recordatorios ni
  re-intentos de mensaje.

**Faltaría:** suscripción a eventos aprobada + cola de follow-ups; hoy ni siquiera hay canal vivo
(C2) que perseguir.

## C5. Memoria de equipo persistente entre sesiones — **EXISTE** (como registro verificable, no memoria automática)

**Qué existe.**
- Operación `memory`: append-only con `title/text/evidence_ids/supersedes`, estado
  `recorded_not_verified` (`runtime.mjs:184-189`); toda memoria exige evidencia previa
  (`runtime.mjs:170-173`); revisiones encadenadas sin reescribir historia (`TOOL_CONTRACT.md:18-19`).
- Persistencia real entre sesiones: ledger JSON en disco con escritura atómica, versión CAS,
  recibos de idempotencia y auditoría (`runtime.mjs:61-100`, commit `runtime.mjs:230-238`).
- SkillHub: biblioteca hash-pinned inmutable con asignaciones por miembro y presupuesto de
  contexto (`skillhub.mjs:9-41`), recarga solo por recibo explícito del owner
  (`skillhub.mjs:71-85`).
- Aprendizaje compartido con revisión independiente que JAMÁS instala ni entrena
  (`runtime.mjs:216-228`).

**Límites declarados (por qué no es "memoria GenTeam").** Es un registro consultable bajo
consent, no memoria inyectada automáticamente en cada conversación; `content_verified:false`
en cada fila (`runtime.mjs:168`); sin recuperación semántica (solo paginación/offset).

## C6. Lista privada de trabajo guardada por el usuario (save button) — **PARCIAL**

**Qué existe.**
- Guardado versionado de proyectos del usuario: formularios "Guardar versión" / "Guardar como
  nuevo" / "Cargar proyecto" con lista y versión (`web/index.html:88`); motor en
  `engine/project_store.py` (no leído a fondo; datos en `data/projects/*/versions/*.json` + `.sha256`).
- Biblioteca privada de capacidades: botón "Guardar sólo en biblioteca" en la barra de selección
  (`web/index.html:114`), pestaña "Mi biblioteca" con creación manual de skills/versiones
  (`web/index.html:118`).
- Preferencias de modelos persistidas (`web/app.js:245`).

**Qué no existe.** Una lista de TAREAS/trabajo pendiente del usuario con save (tipo to-do
personal). Lo guardable es diseño organizacional + biblioteca, no trabajo.

**Faltaría:** entidad "lista de trabajo del usuario" con persistencia propia.

## C7. Agente onboarding que sugiere contrataciones y abre el primer canal — **PARCIAL**

**Qué existe.**
- Contrato de saludo/onboarding del equipo: panel "Qué hará al recibir tu saludo" con misión,
  orquestación, capacidades propuestas y Plan preview copiable (`web/index.html:87`);
  `engine/autonomy.py:179-229` compila `greeting_contract` + `plan_preview` + `capabilities`
  (CEO presenta la organización ante un saludo; "Un saludo inicia una presentación y un plan",
  `web/index.html:87`).
- Greeting por perfil: `engine/agent_context.py:58` (presentar nombre operativo, rol, misión,
  siguiente dato necesario).

**Qué no existe.**
- Sugerencia de CONTRATACIONES: el onboarding presenta el equipo ya generado; no propone
  "deberías contratar a X" (la generación es de roster completo, ver C1).
- Apertura del primer canal: no existe canal que abrir (ver C2); el saludo ocurre en DSH tras
  importar, fuera de esta UI (`web/index.html:87`: el JSON nativo no admite `previewTask`; el
  contexto viaja en `collabNote` y prompts).

**Faltaría:** recomendador incremental de hires + acción "abrir canal" enlazada a un bus vivo.

## C8. Puente a agentes CLI externos (Claude Code / Codex CLI) y night-shift a agentes cloud — **AUSENTE**

**Evidencia de ausencia.**
- Grep de `claude|codex|night|hire|onboard|suggest` en `cordis_extension/*.mjs`: **0 matches**
  (salvo nada). En `engine/`, las únicas menciones a "claude" son heurísticas de INVENTARIO de
  fuentes externas (directorios `.claude`, archivo `claude.md` como señales de repo:
  `engine/providers.py:458`, `engine/providers.py:466`). Nada integra esos agentes.
- El único puente es el bridge local LOOPBACK READ-ONLY al DSH propio: "Native DSH ↔ OrgDNA
  read-only connection. No tool execution" (`live_bridge.mjs:1-6`), restringido a
  127.0.0.1 + origin exacto (`live_bridge.mjs:173-176`).
- El relanzador (`dsh-launcher`) reinicia el DSH EXE local con backup/hash
  (`web/app.js:946-999`; `docs/DSH_RELANZAMIENTO_LOCAL.md` no leído a fondo) — es infraestructura
  local, no integración de agentes CLI externos ni cloud.
- No hay ninguna noción de "night-shift" o delegación cloud en código ni docs del repo.

**Faltaría:** adaptadores CLI externos y_scheduler de turno nocturno; hoy ni el diseño lo menciona.

## C9. Roster de roles predefinidos — **EXISTE**

**Evidencia.**
- `engine/profiles.py:4-5`: 24 identidades base estables con UUID (Planner…EvidenceAuditor).
- `engine/profiles.py:8-89`: `ROLE_SEEDS` — 32 roles predefinidos (CEO, CTO, ASSURANCE,
  ARCHITECTURE, BACKEND, FRONTEND, DATA, INTEGRATION, QUANT, CONTRACTS, SECURITY, QA,
  PERFORMANCE, SRE, RELEASE, LEDGER, GRAPH, MARKET, AI, SPEC, OWNEROPS, E2E, PARITY, EVIDENCE,
  UX, PRIVACY, MOBILE, SEARCH, BUILD, DOCS, CHAOS, COST), cada uno con misión, 5 competencias y
  3 entregables; personas ficticias estables (`engine/profiles.py:6`); roles auditor/consultor
  clasificados (`engine/profiles.py:90-91`).
- Plantillas offline seleccionables "ArbitrageX / General" (`web/index.html:62`); el ADN de 24
  materializado en `05_ROLES_Y_MISIONES.md` (3.600+ líneas) y `EQUIPO_ENTERPRISE_24_PROMPTS_COMPLETOS.md`.
- Versionado de perfiles: `PROFILE_VERSION` (`engine/profiles.py:2`).

**Matiz:** es roster predefinido de ESTE producto (catálogo cerrado versionado), no un roster
editable de contratación rápida.

---

## Cómo fluyen los mensajes hoy (bus, wake, approvals)

1. **Bus de mensajes = ledger JSON local.** El plugin `orgdna-shared-coordination`
   (`entry.mjs:10`) registra 6 tools `orgdna_<uuid>_{state,message,task,evidence,memory,learning}`
   (`runtime.mjs:10`, `plugin.mjs:41-66`) sobre `SharedLedger`, un archivo
   `coordination.json` por organización con lock de doble proceso, escritura atómica y versión
   CAS (`runtime.mjs:58-100`). El actor se identifica SOLO por `exec.agent.id` mapeado vía
   `session_bindings` aprobadas por el owner (`runtime.mjs:114-121`) o `bindRuntimeSession`
   (`runtime.mjs:122-130`, cableado en `native_stage_ui.mjs:143-145`).
2. **Wake: no existe.** "El bus no despierta sesiones ni inicia solicitudes a modelos"
   (`README_ES.md:15-17`); cada tool lo repite ("Stored inbox only; no wake", `plugin.mjs:5`).
   El scheduler de DSH/AgentTeams sigue siendo el único ejecutor. El adaptador evita hasta la
   invocación de `agent_teams_status` (que SÍ despierta al scheduler): lee `team.json` a mano
   (`live_bridge.mjs:104-144`; advertencia en `README_ES.md:61-63`).
3. **Aprobaciones (3 superficies separadas).**
   a. *Pairing local*: página `GET/POST /api/orgdna-local-connect` dentro de la Connection
      autenticada de DSH, con click humano "Autorizar lectura local durante 30 minutos" /
      "Revocar"; genera listener 127.0.0.1 + código de un solo uso (120 s), sesión máx 30 min
      (`live_bridge.mjs:19-21`, `live_bridge.mjs:230`, `live_bridge.mjs:240-263`).
   b. *Staging nativo*: `GET/POST /api/orgdna-native-stage` → `catalog` (perfiles/squads/capitanes
      idle) → `prepare` (plan inmutable con `plan_sha256`, nonce de revisión 120 s, un solo uso)
      → `stage` (ACK `STAGE_ONLY_KEEP_NATIVE_EXECUTION_APPROVAL` + checkbox + hash exacto)
      (`native_stage_ui.mjs:10-11`, `native_stage_ui.mjs:114-124`, `native_stage_ui.mjs:160`).
      La EJECUCIÓN requiere otra aprobación en la UI nativa de AgentTeams
      (`native_orchestration.mjs:76`); al modelo se le NIEGAN `agent_teams_approve`/`resume`
      (`native_orchestration.mjs:12`, guard en `native_orchestration.mjs:128`).
   c. *Consentimientos del panel web*: checkbox por plan exacto de generación
      ("Revisé este plan y autorizo…", `web/index.html:84`), consentimientos de IA para
      capacidades/recursos (`web/index.html:111`, `web/index.html:117`), consent del harness
      (`web/app.js:1088`, `web/app.js:1092`).

## Qué puede y qué NO puede hacer el live_bridge (según `live_bridge.mjs`, no el README)

**PUEDE (todo read-only, loopback, con token Bearer de sesión):**
- `pair` (1 uso, 120 s, máx 5 intentos) y `handshake` con capacidades/ámbitos declarados
  (`live_bridge.mjs:179-188`).
- `profiles`: snapshot de definiciones de Teams 1.3.0 vía `agentTeamGui.readDefinitionSnapshot`
  (`live_bridge.mjs:71-81`).
- `import_preview`: `previewRecipe` / `previewDefinitionsImport(document,'merge')` — dry-run,
  sin importar (`live_bridge.mjs:82-89`).
- `team_state`: lectura de solo lectura de `<root>/<team>/team.json` del state root de
  AgentTools EXPLÍCITAMENTE elegido (validación de realpath, no-symlink, tamaño, schema
  `98aac03-teamstate`; `writes_performed:false`) (`live_bridge.mjs:104-144`).
- `capabilities`: nombres de tools vía `ctx.tools.schemas()` (≤4000, "registry is not a
  permission grant") (`live_bridge.mjs:94-99`).
- `disconnect` (`live_bridge.mjs:193`).
- Higiene: redacción de secretos por clave y de `sk-…`/`Bearer …` (`live_bridge.mjs:24-32`),
  respuestas ≤2 MB, timeouts 5 s, origen exacto 127.0.0.1 (`live_bridge.mjs:173-176`).

**NO PUEDE (constantes en el propio código):**
- `task_plan_submit`: `available:false` — "No verified native existing-team command seam
  preserving action-time approvals" (`live_bridge.mjs:64`); el cliente Python coincide:
  `prepare_task_plan` devuelve `BLOCKED_CAPABILITY` (`engine/dsh_connection.py:298-301`) y
  `submit_task_plan` lanza `CAPABILITY_UNAVAILABLE` (`engine/dsh_connection.py:303-304`).
- `live_messages` / wake: `available:false` (`live_bridge.mjs:65`).
- `realtime_events` / suscripciones: `available:false` (`live_bridge.mjs:66`).
- Escribir perfiles, importar de verdad, crear miembros, reanudar equipos: todas las respuestas
  llevan `writes_performed:false` / `creates_members:false` / `resumes_team:false`
  (`live_bridge.mjs:80`, `live_bridge.mjs:88`, `live_bridge.mjs:142-143`).
- Autenticar identidad de sesiones runtime: `runtime_session_identity_verified:false`
  (`live_bridge.mjs:142`); el mapeo snapshot→miembros es revisión manual, no conexión viva
  (`agentteams-adapter.mjs:24-27`).

## Piezas de UI que ya existen (inventario)

**Panel web local (`web/index.html`, 133 líneas densas + `web/app.js`):**
- Inicio / Generation Studio: config → clave → consentimiento por plan exacto → generación con
  progreso y receipts (`web/index.html:44-88`), gang services (montaje/despliegue registrado,
  `web/index.html:83`), recuperación de diseño (`web/index.html:49`).
- Organigrama SVG interactivo con búsqueda/zoom (`web/index.html:91-92`).
- Perfiles + inspector editable con cadena de mando, toolScope y CV ficticio (`web/index.html:94`,
  `web/index.html:131`); mérito/gobernanza manual con evidencias (`web/index.html:95-101`).
- Council preparatorio con leases de escritura (max 3) (`web/index.html:102`).
- Capability Hub: 5 pestañas (buscar/sugeridas/biblioteca/asignaciones/evidencias), workflows
  por recurso, PluginShop, lectura de referencias públicas (`web/index.html:103-121`).
- Modelos por proveedor con catálogo y asignación por perfil (`web/index.html:122`).
- Repositorio: lectura acotada de GitHub/web + análisis LLM con consentimiento (`web/index.html:123`).
- Exportaciones: recipe DSH + backup + ZIP, dsh-harness (semáforos con doble readback del roster,
  `web/app.js:1084`), dsh-launcher (relanzar DSH local con backup/hash, `web/app.js:946-999`),
  cap-deployment (delta de SkillHub), **dsh-connection** (pairing port+código, leer perfiles,
  leer equipo, preview importación, desconectar — `web/app.js:819-830`).
- Registro de recibos con límites de verificación explícitos (`web/index.html:126`).

**Visor exportable offline:** `engine/templates_bundle/viewer.html` (CSP sin red
`connect-src 'none'`, `engine/templates_bundle/viewer.html:3`; búsqueda, roster, prompts,
políticas, catálogo de tools) generado como `VISOR_DE_PERFILES.html` con datos embebidos y
checks de seguridad (`engine/bundle.py:741`, `engine/bundle.py:895-896`).

**UI embebida del addon dentro de DSH:** página de pairing (`live_bridge.mjs:230`) y página de
staging nativo (`native_stage_ui.mjs:160`), ambas servidas por `connection.fetch.register` tras
autenticación nativa.

**UI que NO existe:** chat/canal/hilo, timeline de mensajes, vista interactiva de equipo vivo
(hay JSON read-only), notificaciones, lista de tareas del usuario, contratación individual.

## Resumen de veredictos

| # | Capacidad GenTeam | Veredicto |
|---|---|---|
| 1 | Contratar roles ready-made / por descripción | PARCIAL |
| 2 | Asignar trabajo como colega (@mention/DM/tarea) | PARCIAL |
| 3 | Sandbox por agente → archivo al canal | AUSENTE |
| 4 | Follow-ups automáticos mid-conversation | AUSENTE |
| 5 | Memoria de equipo persistente | EXISTE (registro, no automática) |
| 6 | Lista privada guardada por el usuario | PARCIAL |
| 7 | Onboarding que sugiere hires y abre canal | PARCIAL |
| 8 | Puente a CLI externos / night-shift cloud | AUSENTE |
| 9 | Roster de roles predefinidos | EXISTE |

Prioridad de brechas para el ranking REA de candidatos: C3 y C4 (ausentes y centrales en el
modelo GenTeam), luego C8 (ausente, alcance menor para un producto local), luego C1/C2/C6/C7
(parciales: requieren extensión del panel y/o seam nativo aprobado).
