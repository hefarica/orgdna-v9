# Permisos de herramientas y skills de OrgDNA

Fecha de revisión: 7 de octubre de 2026. Estado: propuesta local, no aplicada en DSH. No se accedió ni se cambió el equipo del usuario.

## Resultado principal

El texto aportado contiene **271 nombres de herramientas únicos**. Las dos copias son idénticas. Los nombres se conservaron exactamente, incluidos puntos y guiones bajos, y se preservaron las descripciones. La cadena CSV de los 271 nombres, separados por coma y espacio, tiene **3.730 caracteres**. Los botones repetidos “Allowed tools” y “Denied tools” son etiquetas de interfaz, no herramientas adicionales.

En la revisión pública de `dsh-agent-team-gui` 1.3.0, commit `14ea11960b20b1f93c33541ba9df7746ed16d08a`, las nuevas escrituras y definitions v2 aceptan **hasta 256 herramientas en allow y hasta 256 en deny por agente**. Por tanto, los 271 nombres no caben juntos en una allowlist v2, aunque el texto sea corto. No se recortó el catálogo ni se inventaron nombres para evitar ese límite.

El contador **0/51455 mide caracteres del textarea**. El componente utiliza `maxLength={51_455}`. El validador separado controla cantidad y longitud de los nombres. 51.455 también corresponde a 256 nombres de 200 caracteres más 255 comas; no significa 51.455 permisos.

Fuentes: [schema de escritura](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/spec.ts#L32-L46), [componente de interfaz](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/client/SettingsPage.tsx#L379), [validación del formulario](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/client/forms.ts#L131-L145).

## Tres conceptos diferentes

1. **Competencia del perfil:** conocimiento objetivo, por ejemplo Python, revisión independiente o microestructura. No crea una herramienta ni acredita habilidad demostrada.
2. **Skill:** instrucciones versionadas, normalmente un `SKILL.md`. El DSH público actual distingue su registro y su cargador `skill({name})` de las herramientas que utiliza el procedimiento. El catálogo aportado no incluye el nombre `skill`.
3. **Herramienta:** nombre exacto registrado y visible para el runtime, como `ops_validate`, `test.fuzz` o `chain_balance`. Estos nombres son los que pertenecen a `toolScope`.

Las guías `webapp-testing` y `systematic-debugging` del paquete siguen siendo propuestas no instaladas. Su nombre no debe añadirse a Allowed tools como si fuera una herramienta. Un texto que menciona una ruta tampoco carga automáticamente la guía. No se encontró un máximo global de cantidad de skills en el registro público inspeccionado; los límites de caché y de longitud de descripción son otra cosa. No se verificó la versión instalada.

El editor administrativo previo de OrgDNA limita las competencias de perfil a 24 y las propuestas a 32 por agente. Son límites de la aplicación, distintos de los permisos DSH.

Fuente: [sistema oficial de skills](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/docs/subsystems/skills.md).

## Contrato exacto de importación

- Campo por agente: `agents[].toolScope` con `allow` y/o `deny`, ambos arrays de strings.
- Cada array presente contiene 1 a 256 nombres; cada nombre se recorta en extremos y contiene 1 a 200 caracteres.
- Nombres únicos y sin intersección entre allow y deny.
- No se admite `toolScope: {}` ni listas presentes vacías en ese schema. Omitir una lista es diferente de usar una lista vacía.
- No hay campo `toolScope` en el squad. El schema del squad es estricto.
- Un mismo ID de agente usado en Council e Implementation comparte su definición y su permiso. El prompt de Council no convierte una herramienta de escritura en sólo lectura.
- El GUI separa por **comas**; no pegar descripciones, etiquetas de botones ni la lista completa en líneas sin comas.
- El schema no impone una expresión regular de nombre. No eliminar puntos ni convertir los nombres a otra convención.

**Compatibilidad legacy:** recipe v1 usa un schema histórico que no limita numéricamente cada lista de herramientas. Conserva un máximo global de 4 MiB por receta y hasta 256 agentes/miembros de esa receta. Eso no elimina el límite de 256 de nuevas escrituras, ni justifica generar una receta legacy para saltarse la validación de escritura. Definitions tiene un máximo global de 16 MiB. El máximo ordinario de un squad nuevo es 32 miembros.

Fuente: [schemas legacy y versiones](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/spec.ts#L8-L173), [límites de importación](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/tools/application/definition-service.ts#L140-L167).

## Disponibilidad y comportamiento real

El catálogo muestra lo aportado por el usuario, no un descubrimiento ejecutado en la sesión. Cada herramienta tiene `availability: UNKNOWN` y `runtime_verified: false`. La clasificación de riesgo se infiere de su descripción, no de una auditoría o prueba del plugin.

Al despachar, el plugin comprueba los nombres allow contra las herramientas visibles en la sesión padre. Un nombre faltante produce `INVALID_DISPATCH`; no debe eliminarse silenciosamente para que el plan parezca funcionar. El editor permite nombres fuera de su catálogo rápido porque pueden existir sólo en un preset. OrgDNA también puede conservar un nombre manual con estado no verificado, siempre que respete el schema.

Omitir allow hereda herramientas sujetas a restricciones: **no significa bloquear todo**. Un deny-only admite herramientas heredadas nuevas que no estén negadas. Un allow explícito excluye herramientas no enumeradas. Son decisiones distintas, con costes de mantenimiento distintos.

`run_code` es transporte reservado y no pertenece al conjunto ordinario de herramientas restringibles del plugin. Además, el registro DSH distingue herramientas heredadas de registros propios de scope. Una lista de nombres no demuestra aislamiento de archivos, red, credenciales o argumentos.

Fuentes: [preflight y filtro de miembros](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/tools/application/execution-service.ts#L730-L767), [restricciones del runtime DSH](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/docs/subsystems/tools.md#toolrestriction--one-scopes-live-filter-over-what-it-inherits).

## Mando, equipos y delegación

`dsh-agent-team-gui` y `dsh-agent-teams` son plugins distintos. El catálogo incluye `agent_teams_*`, `equipo_mision`, `dispatch_to_squad` y `continue_squad_run`; no incluye `agent_team_delegate`.

El guard público de agent-team-gui prohíbe a sus miembros `dispatch_to_squad`, `continue_squad_run`, `subagent`, `subagent_fork`, `subagent_spawn` y `workflow`. También reconoce ciertos alias por schema: parámetros requeridos `description:string` + `prompt:string`, o `script:string` + `meta:object`. Mantiene un guard de ejecución incluso para llamadas anidadas. Exige que el backend soporte filtro y límite de profundidad; falla cerrado si no puede imponerlos.

No se aportaron schemas completos de `agent_teams_*` ni del plugin que implementa `equipo_mision`. Por ello no se afirma que todas estas herramientas sean reconocidas por aquel guard. La propuesta reserva mutadores de equipo al orquestador y exige revisar compatibilidad. `agent_teams_status` es una consulta; no crea autoridad sobre los 24 perfiles. Las herramientas de enviar mensajes, reclamar o actualizar tareas pertenecen a la identidad y al tablero de su plugin: sólo serían útiles para miembros realmente registrados allí.

El plugin público AgentTeams documenta capitán, miembros durables, tareas con dependencias y `memberMaxDepth` por defecto 0. Esto es evidencia de su diseño público, no de la configuración del usuario. No hay una traducción automática entre un organigrama OrgDNA y ese tablero.

Fuentes: [guard de agent-team-gui](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/tools/delegation-policy.ts), [AgentTeams](https://github.com/NanmiCoder/dsh-agent-teams).

## Selección funcional por perfil

`engine/tool_catalog.json` conserva el catálogo completo y 24 presets propuestos. Cada preset contiene:

- `allow_candidates`: selección funcional por rol, incluyendo herramientas condicionales pertinentes.
- `low_risk_candidates`: subconjunto de consultas o cálculos de menor riesgo descrito.
- `conditional_candidates`: subconjunto de allow que requiere precondiciones, supervisión o autorización por acción.
- `excluded_candidates`: herramientas fuera del preset ordinario; no es una denylist global ni una prohibición absoluta.
- `capability_gaps`: capacidades que el catálogo no demuestra.

Por ejemplo, QA e Implementer sí disponen en su propuesta de ejecución/pruebas pertinentes. Un riesgo alto no sustituye al análisis de qué necesita el rol. Las precondiciones aparecen separadas en cada herramienta. El usuario puede revisar el CSV y la selección antes de guardar.

**Brechas reales:** no aparece editor/lector de archivos genérico, shell/bash genérico, navegador general/E2E ni loader `skill` entre los 271 nombres. Los sandboxes de snippets no prueban edición del repositorio; `ui.compile` no es navegador; `univer_screenshot` sólo describe Unidades Univer. Hay que descubrir los nombres reales en el runtime y añadirlos manualmente cuando corresponda. No se inventaron `read_file`, `edit_file`, `browser` ni otros IDs para rellenar estas brechas.

## Riesgo, supervisión y datos

- `ops_validate`, `sandbox_*`, property tests y evaluadores de funciones pueden ejecutar código. Comprobar aislamiento, rutas, tiempo, red y datos. No asumir una sandbox por el nombre.
- `sql_query` acepta SQL remoto. `sql_explain` usa EXPLAIN ANALYZE y ejecuta la sentencia. No equivalen a un lector seguro genérico: quedan fuera de los presets ordinarios hasta revisar schema y privilegios efectivos.
- `api.token` recibe un secreto para firmar. No usar claves de producción en prompts; datos de prueba o flujo seguro autorizado.
- Herramientas de historial y memoria pueden exponer contenido privado. Limitar la consulta y la información redistribuida.
- Los nombres DeFi/Quant/Ledger no autorizan compras, transferencias, firmas ni movimientos de activos. Las descripciones de `forge_pool` y `forge_swap` declaran simulación paper; no se ejecutó ni verificó esa implementación. Una operación financiera real requiere su autorización y, cuando corresponda, intervención del usuario.

Las precondiciones son instrucciones de uso. `toolScope` no implementa ACL de argumentos, acceso read-only, presupuesto, aprobación, sandbox ni una frontera de seguridad completa. El fallback de modelo tampoco amplía permisos: conserva el toolScope del agente y sólo entra cuando la política de reintento y el diagnóstico lo permiten.

## Verificación pendiente antes de operar

1. Identificar versión instalada del plugin y backend de subagentes.
2. Obtener nombres y schemas visibles en la sesión padre concreta, con su preset.
3. Contrastar allow/deny y resolver faltantes sin sustituir IDs ni ampliar permisos automáticamente.
4. Verificar herramientas de edición, shell, navegador y skills necesarias para cada rol.
5. Confirmar identidades de equipo, límites de profundidad y quién puede crear/asignar tareas.
6. Probar primero consultas y fixtures sin secretos ni activos reales; documentar efectos y reversión.

Esta revisión no inició una sesión DSH, no importó recetas y no probó herramientas del catálogo.
