# RE-A — Barrido de repos agénticos y catálogo de mecanismos adaptables

**Tarea:** `t21` · **Ronda:** RE-A · **Autor:** `evidencia` (worker)
**Fecha de lectura de fuentes:** 2026-10-21, hora local del operador (UTC−5); equivale al
2026-10-22 en UTC. Todas las métricas de esta página se leyeron en esa fecha.
**Naturaleza del entregable:** catálogo de **conceptos y vectores de comportamiento**. No es
código, no es un port y no habilita ninguna fuente.

---

## 0. Qué es y qué NO es este documento

**Es:** un barrido de los proyectos de creación agéntica con más estrellas, con su métrica
observada y su fecha de lectura, y un catálogo de **8 mecanismos** que explican por qué un
equipo de agentes puede trabajar «seguido y continuo», cada uno mapeado a un módulo destino
nuestro o declarado fuera de alcance, más **26 vectores de comportamiento** en
`docs/rea/agile_vectors.json` que nuestras pruebas usarán como especificación derivada.

**No es:**

- **No se copió ni se portó una sola línea de código de ninguna de estas fuentes.** Ninguna de
  las fuentes nuevas de este barrido tiene enmienda FUSILE firmada; la allowlist vigente
  (`docs/security/FUSILE_SOURCE_POLICY.md:32-44`) solo cubre `agentscope-ai/agentscope@26ec620`
  y `OpenBMB/ChatDev@a2ea4a2`, ambas con marca `CONFIRMED` del operador.
- **Ninguna fuente nueva entra a la allowlist por este documento.** La allowlist es un acto
  firmado del operador; este catálogo no la modifica ni la propone implícitamente.
- **No se clonó ningún repo, no se leyó código fuente ajeno y no se ejecutó nada ajeno.** Lo
  que se leyó es: metadatos públicos del repositorio (API de GitHub), páginas de documentación
  oficial y el resumen de un paper. Nada de eso es código.
- **No se pegaron prompts, configuraciones, endpoints ni claves de ninguna fuente.** Los
  únicos literales ajenos de este documento son nombres de repositorio, cifras de métricas,
  fechas, licencias y URLs de citación.

Método y trazabilidad: cada métrica procede de `https://api.github.com/repos/<owner>/<name>`
(HTTP 200, leída el 2026-10-21) y corresponde a los campos `stargazers_count`, `pushed_at`,
`forks_count`, `open_issues_count`, `license.spdx_id`, `language` y `has_discussions`. Las
cifras **cambian**: se citan como «observadas en la fecha de lectura», no como constantes.

---

## 1. Fuentes de repositorio: métrica observada y mecanismo

Las 12 filas siguientes cumplen el mínimo de 10 fuentes con métrica y fecha. Las tres primeras
resolvieron a otro `owner/name` canónico (redirección del propio GitHub): se declara el nombre
pedido y el canónico para que la cita sea verificable.

| # | Fuente pedida | `owner/name` canónico | Estrellas | Lectura | Último push (UTC) | Licencia | Forks · issues | Mecanismo(s) |
|---|---|---|---|---|---|---|---|---|
| 1 | `All-Hands-AI/OpenHands` | `OpenHands/OpenHands` | **91 514** | 2026-10-21 | 2026-10-22T03:39:59Z | MIT | 12 148 · 1 085 | M2, M8 |
| 2 | `geekan/MetaGPT` | `FoundationAgents/MetaGPT` | **70 957** | 2026-10-21 | 2026-01-21T10:12:33Z | MIT | 9 035 · 139 | M3 |
| 3 | `OpenInterpreter/open-interpreter` | `openinterpreter/openinterpreter` | **68 631** | 2026-10-21 | 2026-10-11T00:56:06Z | Apache-2.0 | 5 910 · 21 | M8 |
| 4 | `microsoft/autogen` | `microsoft/autogen` | **61 518** | 2026-10-21 | 2026-10-16T16:14:37Z | **CC-BY-4.0** | 9 303 · 1 123 | M1, M2, M5, M6 |
| 5 | `crewAIInc/crewAI` | `crewAIInc/crewAI` | **59 966** | 2026-10-21 | 2026-10-21T21:43:43Z | MIT | 8 827 · 809 | M3, M4, M6 |
| 6 | `langchain-ai/langgraph` | `langchain-ai/langgraph` | **43 682** | 2026-10-21 | 2026-10-22T04:17:19Z | MIT | 7 482 · 504 | M1, M2, M6 |
| 7 | `OpenBMB/ChatDev` *(ya permitido)* | `OpenBMB/ChatDev` | **34 563** | 2026-10-21 | 2026-10-16T15:55:30Z | Apache-2.0 | 4 327 · 86 | M3, M8 |
| 8 | `agentscope-ai/agentscope` *(ya permitido)* | `agentscope-ai/agentscope` | **33 613** | 2026-10-21 | 2026-10-22T03:06:31Z | Apache-2.0 | 3 691 · 633 | M1, M3, M4 |
| 9 | `SWE-agent/SWE-agent` | `SWE-agent/SWE-agent` | **20 606** | 2026-10-21 | 2026-10-19T22:57:44Z | MIT | 2 259 · 163 | M8 |
| 10 | `stitionai/devika` | `stitionai/devika` | **19 549** | 2026-10-21 | **2025-09-25T08:47:36Z** | MIT | 2 562 · 196 | M8 (y contraejemplo de continuidad) |
| 11 | `ag2ai/ag2` (AG2, ex-AutoGen) | `ag2ai/ag2` | **5 010** | 2026-10-21 | 2026-10-21T20:29:20Z | Apache-2.0 | 754 · 70 | M2, M5 |
| 12 | *(extra por estrellas)* `Significant-Gravitas/AutoGPT` | `Significant-Gravitas/AutoGPT` | **187 703** | 2026-10-21 | 2026-10-22T04:05:59Z | **NOASSERTION** | 45 905 · 720 | referencia de escala; sin mecanismo adoptado |

**Columnas:** `Estrellas` = `stargazers_count`; `Lectura` = fecha de la lectura (2026-10-21,
UTC−5; 2026-10-22 en UTC); `Último push` = `pushed_at` en UTC; `Forks · issues` =
`forks_count` · `open_issues_count`. Las 12 filas se leyeron el mismo día, por lo que son
comparables entre sí como una foto, no como una tendencia.

**Lectura de actividad (dato, no opinión):** 9 de las 12 fuentes registran push en los últimos 7
días respecto de la lectura y una más (`openinterpreter/openinterpreter`, 2026-10-11) en los
últimos 11; `FoundationAgents/MetaGPT` acumula ~9 meses sin push y `stitionai/devika` ~13 meses.
Un repo con muchas estrellas y sin actividad reciente **no** sostiene un bucle vivo: es el caso
de `devika` (§6).

## 2. Fuentes documentales y de comunidad

No se leyó ningún hilo de foro de terceros (Discord, Reddit, Stack Overflow). Lo que sí se leyó
—y se cita con su alcance exacto— es documentación oficial de los propios proyectos y un paper
primario. La limitación se declara en §8.

| Fuente documental | URL leída | Qué se leyó exactamente | Qué quedó truncado | Mecanismo |
|---|---|---|---|---|
| AutoGen — *Teams* | `https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html` | Cuerpo completo: creación de equipo, `run`/`run_stream`, observación, `reset`, parada externa, **reanudación sin tarea nueva**, aborto con token de cancelación, equipo de un solo agente con condición de terminación | nada relevante | M1, M2, M5, M6 |
| AutoGen — navegación | misma | Índice: *Human-in-the-Loop*, *Termination*, *Managing State*, *Selector Group Chat*, *Swarm*, *Tracing and Observability*, *Logging*, *Serializing Components* | solo títulos | M1, M2, M3, M6 |
| LangChain/LangGraph — *Persistence* | `https://docs.langchain.com/oss/python/langgraph/durable-execution` (redirige a `/persistence`) | Título y navegación de capacidades | cuerpo (la página se cortó en la navegación) | M1, M2, M6 |
| LangGraph — índice de capacidades | misma | *Persistence*, *Checkpointers*, *Fault tolerance*, *Event streaming*, *Streaming*, *Interrupts*, *Time travel*, *Subgraphs*, *Observability* | solo títulos | M1, M2, M6, M9 (fuera de alcance) |
| CrewAI — *Processes* | `https://docs.crewai.com/en/concepts/processes` (sirve `v1.15.28`) | Título y navegación de *Core Concepts* | cuerpo truncado | M3, M4, M6 |
| CrewAI — índice de conceptos | misma | *Agents*, *Tasks*, *Crews*, *Flows*, *Processes*, *Collaboration*, *Memory*, *Planning*, *Reasoning*, *Testing*, *Event Listener* | solo títulos | M3, M4, M6 |
| MetaGPT — paper | `https://arxiv.org/abs/2308.00352` (v7, 2024-11-01) | Resumen completo | — | M3 |
| AG2 — descripción del repo | API de GitHub (campo `description`) | «AG2 (formerly AutoGen): The Open-Source AgentOS», enlace a su Discord | — | M2, M5 |
| AutoGen — descripción y enlaces | API de GitHub + cabecera de la página *Teams* | Enlaces a Discord y a su tracker | — | M6 |

**Sobre «foros»:** lo que la comunidad valora se ha recogido **indirectamente** de la
documentación que esos proyectos escriben para su comunidad y de las señales de actividad
públicas (`stargazers_count`, `pushed_at`, `open_issues_count`, `has_discussions`), no de hilos.
En §5 se detalla qué se valora y a qué fuente se atribuye, con esa salvedad explícita.

---

## 3. Los 8 mecanismos, clasificados

Cada mecanismo se enuncia como **comportamiento observable** (entrada → salida esperada), no
como implementación. «Módulo destino» es el archivo nuestro que debe materializarlo.

### M1 · `checkpoint_durable_y_reanudacion` → `engine/team_process.py` + `engine/team_loop.py`

- **Concepto:** el avance del equipo es un **estado serializable** que se escribe tras cada
  paso; un ciclo nuevo continúa desde el último estado confirmado en vez de reiniciar el trabajo.
- **Qué se leyó:** AutoGen documenta que los equipos «son stateful y mantienen el historial y el
  contexto tras cada ejecución» y que se pueden **reanudar sin una tarea nueva**, continuando por
  el siguiente agente del turno (`tests` de la página *Teams*, sección *Resuming a Team*).
  LangGraph expone el concepto como capacidad de primera clase: *Persistence*, *Checkpointers*,
  *Fault tolerance* (títulos de su índice de capacidades).
- **Por qué aporta agilidad/continuidad:** convierte un fallo o una pausa en una **interrupción
  reanudable** en vez de una pérdida de trabajo; y permite ciclos cortos (baratos) porque el
  coste de retomar es bajo.
- **Cómo se adapta:** `team_process` guarda un **checkpoint** con versión de formato, modo,
  paso actual, resultados por miembro, delegaciones abiertas y contadores de presupuesto;
  `team_loop` lo lee antes de cada ciclo y lo reescribe al cerrar el ciclo. Nada de hilos ni de
  bucles infinitos dentro del módulo: el avance es explícito (§4, decisión D-REA-3).
- **Qué NO se toma:** su modelo de estado concreto (serialización de componentes, historial de
  mensajes del framework) ni sus checkpointer backends.

### M2 · `parada_explicita_y_corte_limpio` → `engine/team_loop.py` + `engine/team_process.py`

- **Concepto:** el bucle **solo** avanza mientras no exista una señal de parada; la parada es
  observable (`stop_reason`), externa (la pide un humano o el panel) e idempotente, y deja el
  estado en un punto consistente. Además, «parar» y «abortar» son cosas distintas: parar deja
  terminar el paso en curso; abortar corta de inmediato.
- **Qué se leyó:** AutoGen *Teams*: condiciones de terminación (`TextMentionTermination`,
  `TextMessageTermination`), **parada externa** (`ExternalTermination`), **aborto** con token de
  cancelación que lanza cancelación de la tarea en curso, `reset` que limpia el estado, y un
  `stop_reason` devuelto con el resultado. La navegación añade la página *Termination*.
  AG2 declara el mismo linaje («ex-AutoGen»).
- **Por qué aporta agilidad/continuidad:** un equipo que **no se puede parar en limpio** no se
  puede operar 24/7; el corte limpio es la condición para reiniciar rápido y sin estado a medias.
- **Cómo se adapta:** `team_loop` expone `start`/`stop` con `stop_reason` tipado, corta entre
  ciclos (nunca a mitad de una escritura de checkpoint) y registra el recibo del ciclo cerrado;
  `team_process` declara el final de ciclo como estado explícito (`completed`, `budget_exhausted`,
  `stopped`, `not_run`). Se reutiliza el estado `not_run` ya congelado en el contrato TaskSpec v1.
- **Qué NO se toma:** sus objetos de condición de terminación ni su token de cancelación.

### M3 · `delegacion_jerarquica_con_retorno` → `engine/team_process.py`

- **Concepto:** un coordinador reparte trabajo a miembros y **recibe el resultado de vuelta** en
  su propio contexto; el trabajo se ordena por **procedimiento** (quién hace qué y en qué orden),
  no por conversación libre.
- **Qué se leyó:** (a) el paper de MetaGPT describe codificar *Standardized Operating Procedures*
  en secuencias y usar un «paradigma de línea de ensamblaje» para asignar roles diversos;
  (b) AutoGen usa un `SelectorGroupChat` que **elige al siguiente hablante** con un modelo, y un
  patrón `Swarm` con mensajes de traspaso; (c) nuestros propios cuadernos REA de AgentScope
  (`docs/rea/agentscope_notebook.md`, fuente **ya permitida**) documentan la delegación
  líder→miembro con retorno y con resultado tipado — ese port ya existe en `engine/team_channel.py`.
- **Por qué aporta agilidad/continuidad:** elimina la conversación infinita: hay un responsable
  de cerrar cada delegación, y el resultado vuelve con un formato que el coordinador puede usar.
- **Cómo se adapta:** `team_process` implementa el modo `hierarchical` como **delegación con
  retorno al coordinador**: cada delegación abierta queda en el checkpoint hasta que vuelve su
  resultado; una delegación a un miembro inexistente es error tipado, no un silencio.
- **Qué NO se toma:** SOPs concretas de MetaGPT, prompts de rol, ni el selector por modelo
  (elegir el siguiente hablante con una llamada a modelo añade coste y no determinismo: nosotros
  ordenamos por `slot` canónico).

### M4 · `olas_paralelas_acotadas_con_orden_determinista` → `engine/team_process.py`

- **Concepto:** el paralelismo se ejecuta **por olas de tamaño acotado** y los resultados se
  devuelven en el **orden de entrada**, no en el orden de finalización.
- **Qué se leyó:** nuestros cuadernos REA de AgentScope documentan el caso de **delegaciones
  concurrentes** cuyos resultados vuelven «en orden de llamada» aunque los miembros terminen en
  otro orden (vector `delegaciones_concurrentes_resultados_en_orden_de_llamada` en
  `docs/rea/agentscope_vectors.json`). CrewAI expone *Processes* y *Flows* como conceptos de
  orquestación (títulos de su índice).
- **Por qué aporta agilidad/continuidad:** una ola acotada sube el rendimiento sin perder
  determinismo; el orden estable es lo que hace **reproducibles** las pruebas y los recibos.
- **Cómo se adapta:** `team_process` añade el modo `parallel_waves` con tamaño de ola declarado;
  la ola se compone por orden canónico de `slot`, y los resultados se consolidan por ese mismo
  orden. Es **síntesis nuestra** sobre el concepto, no un port: se declara así.
- **Qué NO se toma:** el runtime de grafos de CrewAI ni su planificador.

### M5 · `presupuesto_por_ciclo_con_corte` → `engine/team_process.py` + `engine/team_loop.py`

- **Concepto:** cada ciclo tiene un presupuesto declarado (tokens, dinero, tiempo, intentos);
  al agotarse, el ciclo **corta con estado explícito** en vez de seguir «un poco más».
- **Qué se leyó:** AutoGen *Teams* contabiliza consumo por mensaje (`models_usage` con tokens de
  prompt y de completion) y lo totaliza al final; su ejemplo de equipo de un solo agente usa
  `max_tool_iterations` como cota de iteraciones. AG2, que se presenta como su continuación
  («AG2 (formerly AutoGen)»), hereda ese contrato de equipo; su documentación no se leyó en esta
  ronda, así que se cita por linaje declarado, no por contenido.
- **Por qué aporta agilidad/continuidad:** sin corte por presupuesto, la continuidad se paga con
  coste ilimitado; con corte, el bucle puede correr de forma sostenida y predecible.
- **Cómo se adapta:** `team_process` lleva **contadores de presupuesto** por ciclo en el
  checkpoint (magnitudes ya congeladas en `docs/plataforma/taskspec.schema.json`: `tokens`,
  `money_usd`, `time_seconds`, `requests`); `team_loop` decide continuar o cortar con backoff y
  registra el motivo en el recibo. Cero reintentos automáticos de operaciones pagadas: eso ya
  está cerrado en el contrato de recibo v1 (`docs/plataforma/receipt-extension.schema.json`).
- **Qué NO se toma:** sus cuentas de tokens internas ni sus límites por defecto.

### M6 · `observabilidad_por_eventos_y_recibo` → `engine/team_loop.py`

- **Concepto:** el avance se puede **observar mientras ocurre** (streaming de eventos) y queda un
  registro consultable después (traza/recibo); sin eso, «continuo» es una caja negra.
- **Qué se leyó:** AutoGen *Teams*: `run_stream` entrega los mensajes «a medida que se generan»,
  con el resultado final como último elemento, y su índice incluye *Tracing and Observability* y
  *Logging*. LangGraph indexa *Event streaming*, *Streaming* y *Observability*. CrewAI indexa
  *Event Listener*. AG2 se presenta como «AgentOS» con su tracker público.
- **Por qué aporta agilidad/continuidad:** permite diagnosticar un ciclo sin detenerlo y auditar
  uno ya cerrado; es la base para medir «agilidad» en vez de afirmarla.
- **Cómo se adapta:** `team_loop` emite, por ciclo cerrado, un **recibo local** (número de ciclo,
  modo, pasos avanzados, presupuesto consumido, motivo de corte) con la forma aditiva del
  contrato de recibo v1, y expone los contadores que el panel (t24) puede leer. No manda nada a
  ningún proveedor ni escribe fuera del almacén local.
- **Qué NO se toma:** sus trazas propietarias, sus exportadores ni sus servicios de observación.

### M7 · `exclusividad_un_dueno_del_bucle` → `engine/team_loop.py`

- **Concepto:** un solo dueño puede avanzar el trabajo a la vez; si otro lo intenta, **espera o
  se niega con motivo**, y una concesión vencida se puede tomar declarándolo.
- **Qué se leyó:** **ninguna** de las fuentes del barrido declara un mecanismo de exclusión local
  por arrendamiento entre procesos. Este mecanismo es **propio de este repo**: la doctrina y el
  almacén de coordinación ya existen en `engine/coordination.py` (lease con `owner_agent_id`,
  `task_id`, `ttl_seconds`, `expected_version`).
- **Por qué aporta agilidad/continuidad:** dos bucles duplicando trabajo es la forma más rápida
  de romper la continuidad y el presupuesto; la exclusividad es requisito, no adorno.
- **Cómo se adapta:** `team_loop` pide el lease antes de cada ciclo y lo renueva; si no lo
  obtiene, registra `lease_held` y no avanza. **No se copia nada: es doctrina local** (se
  declara así para no atribuir a terceros lo que es nuestro).
- **Qué NO se toma:** nada (no hay fuente).

### M8 · `ejecucion_en_sandbox_bajo_aprobacion` → `engine/sandbox_executor.py`

- **Concepto:** el código generado se ejecuta en un espacio acotado (workspace por agente,
  tiempo máximo), y **solo** después de la aprobación humana correspondiente.
- **Qué se leyó:** `OpenBMB/ChatDev` (ya permitido) documenta el ejecutor por subproceso con
  timeout y workspace por agente — es la fuente del port P1 ya presente en
  `engine/sandbox_executor.py`. `openinterpreter/openinterpreter` (68 631 ★) se describe como
  «coding agent for open models», `stitionai/devika` (19 549 ★) como «agentic software engineer»,
  `SWE-agent/SWE-agent` (20 606 ★) como agente que intenta arreglar un issue de un repositorio, y
  `OpenHands/OpenHands` (91 514 ★) se describe como «AI-Driven Development»: son corroboración
  conceptual de «agente que actúa sobre un entorno de código», leída en la descripción pública de
  cada repo, no en su código.
- **Por qué aporta agilidad/continuidad:** poder ejecutar es lo que cierra el ciclo; hacerlo bajo
  puertas y con workspace acotado es lo que permite ejecutar **muchas veces** sin incidentes.
- **Cómo se adapta:** ya está materializado (P1). RE-A **no añade nada** aquí: solo confirma que
  la decisión del operador («ejecución viva bajo puertas»,
  `docs/security/FUSILE_SOURCE_POLICY.md:48-51`) está alineada con lo que hacen los proyectos
  mejor valorados.
- **Qué NO se toma:** nada nuevo (ChatDev ya está permitido; el resto es solo corroboración).

### Fuera de alcance (declarado, no adoptado)

| Mecanismo observado | Fuente | Por qué NO se adopta ahora |
|---|---|---|
| M9 `time_travel_replay` (rebobinar a un checkpoint anterior y re-ejecutar) | LangGraph (*Time travel*) | Exigiría registro de eventos con historia completa; multiplica el estado y no lo pide ningún criterio de aceptación de la misión. |
| M10 `swarm_handoff` (traspaso entre pares sin coordinador) | AutoGen (*Swarm*, `HandoffMessage`) | Nuestra topología es coordinador + arrendamiento; un traspaso entre pares rompería la exclusividad y la atribución por `slot`. |
| M11 `selector_por_modelo` (elegir el siguiente hablante con una llamada a modelo) | AutoGen (*Selector Group Chat*) | Añade coste por paso y no determinismo; el orden por `slot` es más barato y reproducible. |
| M12 `runtime distribuido / actores` | AutoGen Core, LangGraph Platform | Fuera de alcance: la suite es local, sin red y sin demonios. |
| M13 `adaptadores multi-proveedor de modelos` | todas las fuentes | Prohibido por el encargo (sin proveedores, sin claves, sin envíos). |
| M14 `instalación automática de skills` | ninguna fuente lo declara como mecanismo | Prohibido: la suite no instala nada (0 instalación declarada en la capa de plataforma). |

---

## 4. Mapa mecanismo → módulo destino (y decisiones derivadas)

| Mecanismo | `engine/team_process.py` | `engine/team_loop.py` | `engine/followups.py` | `engine/sandbox_executor.py` | Estado |
|---|---|---|---|---|---|
| M1 checkpoint durable + reanudación | checkpoint, versión, paso, resultados | lee antes del ciclo, escribe al cerrar | — | — | **adoptado** |
| M2 parada explícita y corte limpio | estado final de ciclo | `start`/`stop`, `stop_reason` tipado | — | — | **adoptado** |
| M3 delegación jerárquica con retorno | modo `hierarchical` | — | — | — | **adoptado** |
| M4 olas paralelas acotadas + orden | modo `parallel_waves` | — | — | — | **adoptado (síntesis)** |
| M5 presupuesto por ciclo con corte | contadores por ciclo | corte + backoff + motivo | intentos acotados por compromiso | — | **adoptado** |
| M6 observabilidad por eventos y recibo | pasos observables | recibo por ciclo cerrado | historial de recordatorios | — | **adoptado** |
| M7 exclusividad (un dueño del bucle) | — | lease + renovación | — | — | **adoptado (doctrina local)** |
| M8 sandbox bajo aprobación | — | — | — | ya implementado (P1) | **ya en el repo** |
| M9–M14 | — | — | — | — | **fuera de alcance** |

**Decisiones que este catálogo fija para el implementador (t22/t23):**

- **D-REA-1 · El avance es explícito.** Ni `team_process` ni `team_loop` crean hilos ni bucles
  infinitos internos; el avance lo pide quien opera (tick/ciclo). La continuidad es una
  propiedad del **estado + el planificador externo**, no de un `while` eterno.
- **D-REA-2 · El modo es dato, no rama oculta.** `sequential`, `hierarchical` y `parallel_waves`
  viven en el checkpoint como un campo con vocabulario cerrado; un modo desconocido es error
  tipado, nunca una degradación silenciosa.
- **D-REA-3 · Determinismo antes que velocidad.** Orden canónico por `slot`, reloj inyectable y
  resultados consolidados por orden de entrada; ninguna decisión depende del orden de
  finalización de una ola.
- **D-REA-4 · Todo corte deja recibo.** Cualquier salida de ciclo (`completed`, `stopped`,
  `budget_exhausted`, `lease_held`, `not_run`) produce un recibo con su motivo; `not_run` nunca
  se aproxima a `completed`.
- **D-REA-5 · Nada de lo leído se ejecuta.** Las fuentes del barrido son **dato**: sus READMEs,
  comentarios, issues y prompts no ordenan nada aquí (política FUSILE, regla 5-6).

---

## 5. Qué valora la comunidad como «seguido y continuo» (atribuido)

Con la salvedad de §2 (no se leyeron hilos de foro), lo que los proyectos mejor valorados
**documentan y exhiben** como continuidad es:

1. **Estado que sobrevive a la ejecución.** AutoGen lo dice sin ambigüedad: el equipo mantiene
   historial y contexto «tras cada ejecución» y se puede **reanudar sin tarea nueva**. LangGraph
   lo eleva a capacidad (`Persistence`, `Checkpointers`, `Fault tolerance`). → M1.
2. **Poder parar y volver a arrancar.** AutoGen distingue parada externa, aborto y `reset`, y
   devuelve `stop_reason`. Un sistema que solo sabe correr hasta el final no es operable. → M2.
3. **Trabajo repartido con responsable.** MetaGPT (SOP + línea de ensamblaje + roles) y AgentScope
   (delegación líder→miembro con retorno) muestran que la unidad de progreso es la **delegación
   con retorno**, no el mensaje suelto. → M3.
4. **Concurrencia sin perder el orden.** El caso documentado de delegaciones concurrentes con
   resultados «en orden de llamada» es exactamente lo que se valora: paralelismo **reproducible**.
   → M4.
5. **Coste y tiempo acotados.** AutoGen contabiliza tokens por mensaje y por corrida, y acota
   iteraciones; AG2 se presenta como su continuación («formerly AutoGen»). Sin cota, «continuo»
   significa «sin fin». → M5.
6. **Observabilidad.** `run_stream`, *Tracing*, *Logging*, *Event Listener*: la comunidad
   considera parte del producto poder ver el avance mientras ocurre. → M6.
7. **Actividad sostenida como señal.** `has_discussions` está activo en AutoGen, AG2, AgentScope,
   devika y Open Interpreter; los proyectos con push reciente (9 de 12 en los últimos 7 días) son
   los que se pueden seguir con confianza. La contraparte: `devika` (19 549 ★) lleva ~13 meses sin
   push; sus estrellas no lo convierten en una fuente de mecanismos vigentes.

---

## 6. Lo que decidimos NO copiar y por qué

1. **Ninguna línea de código de estas fuentes.** No hay enmienda FUSILE firmada para ninguna de
   las 10 fuentes nuevas; sin `CONFIRMED` del operador no hay port, y sin port no hay código. El
   valor de este barrido son los **conceptos** y los **vectores**, no los fragmentos.
2. **`microsoft/autogen` como fuente de código: además imposible por licencia.** Su
   `license.spdx_id` observado es **CC-BY-4.0**, que es una licencia de contenido, no de software;
   aunque el operador firmara una enmienda, el código no es porteable con esa licencia.
3. **`Significant-Gravitas/AutoGPT` como fuente de código:** su licencia aparece como
   **NOASSERTION** («Other») en la lectura; no hay licencia resuelta que citar, así que se queda
   como referencia de escala, sin mecanismo adoptado.
4. **`stitionai/devika`:** contraejemplo de continuidad (sin push desde 2025-09-25). No se toma
   ni su arquitectura ni su interfaz; se cita solo como dato de actividad.
5. **Sus prompts, plantillas de rol, SOPs, configuraciones, endpoints y nombres internos.** Son
   configuración y contenido del fuente: dato de referencia, nunca literal (FUSILE regla 4).
6. **Sus runtimes propietarios** (grafos de ChatDev/CrewAI, actores de AutoGen Core, plataforma de
   LangGraph) y **sus servicios de observación**. Implicarían dependencias nuevas y red.
7. **`time travel`, `swarm handoff`, selector por modelo, adaptadores multi-proveedor,
   instalación automática de skills.** Ver M9–M14: fuera de alcance por coste, por topología o
   por prohibición expresa del encargo.
8. **La idea de «agente autónomo sin puertas».** Ningún proyecto del barrido se toma como modelo
   de permisos: aquí la ejecución viva solo ocurre bajo las 8 puertas
   `require_human_approval` de `engine/policy_engine.py`, por decisión del operador
   (`docs/security/FUSILE_SOURCE_POLICY.md:48-51`).

---

## 7. Declaración FUSILE

- **Código copiado: cero.** Este documento y `docs/rea/agile_vectors.json` no contienen código,
  prompts, configuraciones, endpoints ni claves de ninguna fuente ajena. Los vectores son
  **especificaciones de comportamiento** en lenguaje natural derivadas de documentación pública.
- **Allowlist: sin cambios.** Ninguna fuente nueva queda habilitada por este barrido. La
  allowlist sigue siendo la de `docs/security/FUSILE_SOURCE_POLICY.md:32-44` con sus dos marcas
  `CONFIRMED` (AgentScope, ChatDev). Si el operador quiere habilitar alguna de las 10 fuentes
  nuevas, hace falta su marca `CONFIRMED: allowlist amendment <owner/name>@<sha>` y una tarea de
  port distinta de esta.
- **Lectura, no ejecución:** no se clonó, no se instaló, no se ejecutó nada de las fuentes; las
  únicas peticiones fueron de lectura pública (API de GitHub, sitios de documentación, arXiv).
- **Una sola fuente ya permitida se cita como evidencia de mecanismo** (AgentScope y ChatDev, vía
  nuestros cuadernos REA y el port ya verificado). Esa cita no amplía su alcance: se usa lo ya
  portado bajo sus marcas.

---

## 8. Límites de esta investigación (fail-honest)

- **No se leyeron hilos de foro de terceros.** Discord/Reddit/Stack Overflow no se consultaron;
  lo de §5 se atribuye a documentación oficial y a señales públicas de actividad. Un estudio de
  foros queda pendiente y **no se declara hecho**.
- **Las páginas de CrewAI y LangGraph se truncaron** en la navegación: de ellas se citan títulos y
  la existencia de los conceptos, **no** su contenido. Las afirmaciones de M3/M4 sobre CrewAI se
  limitan a «expone Processes y Flows como conceptos de orquestación».
- **No se leyó código fuente ajeno**, así que los mecanismos se describen por su
  **comportamiento documentado**, sin afirmar detalles de implementación (estructuras internas,
  algoritmos, nombres de clase).
- **Las cifras de estrellas y de actividad son volátiles** y corresponden a la fecha de lectura;
  no se comparan entre sí como ranking definitivo.
- **Los vectores de `agile_vectors.json` son una especificación derivada, no una prueba.** Solo
  demuestran algo cuando las pruebas del destino los ejecutan; hoy no están ejecutados.
- **`followups` no tiene fuente en este barrido.** Su mecanismo (persecución de compromisos con
  recordatorios acotados y escalado) ya está declarado como diseño propio en
  `docs/rea/PORT_REPORT.md:28`; RE-A solo le impone las cotas de M5/M6.

---

## 9. Vectores de comportamiento

`docs/rea/agile_vectors.json` contiene **26 vectores** con la forma de los vectores REA ya
existentes (`segmento`, `nombre`, `entrada`, `salida_esperada`) más los campos que exige este
encargo: `source` (repo o documento), `mechanism` (una frase) y `modulo_destino`. Cada vector
lleva además `mecanismo_id` (M1–M8), `source_metric` (métrica observada y fecha de lectura),
`fuentes_corroborantes` (los repos del §1 que sostienen el mismo mecanismo), `derivacion` (por qué
el vector se sigue del mecanismo) y `no_es_port: true`. Son **especificaciones**: dicen qué salida
debe producir el módulo destino ante qué entrada, sin decir cómo.

Entre `source` y `fuentes_corroborantes`, el JSON cita **11 de los 12 repositorios** del §1; el
duodécimo (`Significant-Gravitas/AutoGPT`) queda fuera a propósito porque no aporta ningún
mecanismo adoptado (solo referencia de escala).

| Mecanismo | Vectores | Módulos destino tocados por esos vectores |
|---|---|---|
| M1 checkpoint durable y reanudación | AV-01 … AV-04 | `team_process` (3), `team_loop` (1) |
| M2 parada explícita y corte limpio | AV-05 … AV-08 | `team_loop` (3), `team_process` (1) |
| M3 delegación jerárquica con retorno | AV-09 … AV-11 | `team_process` (3) |
| M4 olas paralelas acotadas | AV-12 … AV-15 | `team_process` (4) |
| M5 presupuesto por ciclo con corte | AV-16 … AV-19 | `team_process` (2), `team_loop` (1), `followups` (1) |
| M6 observabilidad por eventos y recibo | AV-20 … AV-22 | `team_loop` (2), `followups` (1) |
| M7 exclusividad (un dueño del bucle) | AV-23 … AV-24 | `team_loop` (2) |
| M8 sandbox bajo aprobación | AV-25 … AV-26 | `sandbox_executor` (2) |

Los 26 vectores cubren los cuatro módulos destino: `engine/team_process.py` (13),
`engine/team_loop.py` (9), `engine/followups.py` (2) y `engine/sandbox_executor.py` (2). Cada
vector es una **especificación** de entrada → salida esperada; ninguno contiene código ni se
ejecuta en esta tarea. Cada vector declara además `source_metric` con la métrica y la fecha de
lectura de su fuente, para que la cita sea verificable sin salir del JSON.
