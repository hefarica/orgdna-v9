# Motor local de ADN organizacional

Python 3.10+ y biblioteca estándar para el motor local. Compilar una plantilla y exportar no accede a red ni inicia agentes. El flujo de diseño por API llama al proveedor únicamente tras el consentimiento específico; Plugin Shop consulta fuentes públicas sólo mediante una acción explícita. La conexión DSH es local, opcional y de sólo lectura. Ninguno de esos pasos instala plugins, importa definiciones ni ejecuta el repositorio. El addon Cordis opcional requiere el Node y host indicados en su propia guía.

## API

La app web local es la interfaz principal. Excel es un complemento para el árbol automático BFS.

- `generate_organization(config, analysis=None, model_catalog=None, profile_specs=None, provenance=None, base_recipe=None, previous_organization=None)` devuelve el sidecar completo.
- `build_export_snapshot(org, base_recipe=None, exported_at=None)` en `engine/export_artifacts.py` congela nombres nativos, instante y bytes exactos de los JSON; pasarlo también a `build_package_bytes(..., export_snapshot=snapshot)`.
- `validate_organization(org)` devuelve `valid`, `errors`, `warnings`, `metrics`.
- `export_recipe(org, base_recipe=None, phase='implementation')` admite fases `implementation` y `council`.
- `validate_recipe(recipe)` valida el subconjunto estricto DSH v1 emitido.
- `export_definitions(org, base_recipe=None)` genera el segundo formato principal: definitions backup v2, con una sola lista de agentes y dos squads compartidos.
- `validate_definitions(document)` verifica referencias, fases, identidad, límites y ausencia de duplicación.
- `apply_organization_edits(org, edits)` aplica ediciones administrativas atómicas con control de versión.
- `refresh_model_catalog(org, model_catalog=None)` conserva perfiles, árbol y rutas y actualiza la disponibilidad. Sin catálogo invalida afirmaciones de disponibilidad persistidas.
- `apply_functional_subteams(org, teams, expected_state_version=None)` crea/edita grupos funcionales de auditoría o consultoría dentro de N.
- `apply_model_assignments(org, assignments, model_catalog=None, expected_state_version=None)` cambia rutas manuales o restaura selección automática sin perder perfiles, árbol ni subequipos. `assignments` reemplaza el mapa de overrides; `{}` restaura auto.

Config mínimo: `repo_url`, `repo_name`, `template` (`arbitragex` o `generic`), `agent_count` (1–32), `max_direct_reports` (1–8), `provider`, `model`. Opcionales: `implementation_concurrency` (1–3), `council_concurrency` (exactamente N), `model_overrides` (`agent_id → {provider,model}`) y `owner_name`.

El límite N32 preserva compatibilidad con la edición ordinaria del formato público revisado. N>32 se rechaza explícitamente y requiere diseño multi-squad; nunca se trunca.

`model_catalog` puede ser una lista de `{provider,model,available:true|false|null}` o la salida `discover_models` (`{provider,models:[{id,availability_verified}]}`). No tener catálogo produce `unverified`, no disponible ficticiamente. Una ruta ausente del catálogo explícito o marcada false bloquea exportación. Un catálogo abreviado manual nunca demuestra disponibilidad. El preflight final corresponde al runtime DSH y sus proveedores configurados.

La asignación automática sólo considera rutas disponibles (`available=true`). Primero aplica prioridades del usuario (`user_rank`: 1 es la más alta); después usa encaje descriptivo por rol cuando existe metadata explícita de capacidades, modalidades o contexto. Por ejemplo, matemáticas para Quant y visión/código para Frontend. No deduce calidad de nombres como “pro” o “ultra”. Un override manual siempre gana. Sin evidencia suficiente conserva el predeterminado, normalmente `deepseek-flash`, con benchmark pendiente. El coste y calidad reales no quedan verificados por esta heurística.

Cada agente registra `model_assignment_reason`, `selection_source` (`manual_override`, `user_priority_verified_catalog`, `capability_heuristic_verified_route` o `default_unbenchmarked`) y `model_requirements`. Estos campos van en el sidecar/Excel, no se inventan campos nuevos en DSH. Un estado AVAILABLE escrito en una hoja no constituye verificación API; el puente separa preferencias de la disponibilidad comprobada en sesión.

`analysis` admite señales `{technology,evidence_path}`, profesiones `{title,expertise,evidence_paths}` y skills `{name,description,evidence_paths}`. Nada de esto concede autoridad. Las competencias conocidas especializan perfiles; las nuevas permanecen en `competency_gaps` como `PROPOSED`, no verificadas ni instaladas, con fuentes para investigarlas. Los campos `system_prompt`, `tools` e `instructions` de un análisis no se incorporan.

## Jerarquía y supervisión

Slots BFS estables, con `parent_slot = floor((slot-2)/span)+1` para slot>1. CEO en slot1 reporta a `OWNER_EXTERNAL`. Con span3, sus tres ramas son Architect, QA y PersonalOps. La rama de QA contiene Reviewer, Security y EvidenceAuditor; la de Architect contiene Implementer, Backend y Frontend. Cambiar span conserva límites y ciclos cero, pero exige revisar adecuación funcional.

Cada CV explicita Maestría y Doctorado (PhD) como niveles objetivo ficticios por disciplina, con `evaluation_required=true`, nunca títulos obtenidos ni universidades reales inventadas.

Los auditores y consultores están incluidos dentro de N. Sus vínculos funcionales no crean subordinados ocultos. Cada perfil incluye supervisor, reportes, responsabilidades, journeys, competencias objetivo y CV ficticio aspiracional. La hoja y sidecar son el organigrama; DSH no promete mostrarlo como gráfico nativo.

Las asignaciones de auditoría excluyen autoauditoría y cualquier relación ancestro/descendiente. Son candidaturas, no firmas: hay que comprobar conflicto real por artefacto, autoría compartida, pruebas y SHA. Si no existe candidato interno, Owner debe nombrar un auditor externo independiente. Un árbol de span1 siempre requiere esa intervención.

## Dos formatos principales

1. Recipe v1 de implementación: un squad y sus agentes.
2. Definitions backup v2: los mismos agentes una sola vez y dos squads (implementación y Council).

El recipe Council separado es opcional. El backup generado contiene esta organización, no un snapshot de toda una instalación DSH; revisar antes de usar replace, que podría afectar otras definiciones. Se recomienda preview de merge con backup previo. `base_recipe` admite el recipe original o el definitions backup v1/v2 aportado como ancla de identidad, sin modificarlos.

## Council e implementación, mismas definiciones de agente

Council: `all`, `maxConcurrency=N`, `parallel`, `fork`, `stop`. Con backend `teams_gui`, el preset predeterminado autónomo usa `activationMode=always`, `triggerMode=guaranteed`, `planningContext=full` y `plannerMaxTokens=8192`; manual y smart siguen disponibles explícitamente. Deliberación sólo lectura, sin ejecutar el proyecto ni producción. Una intervención por agente. CEO consolida después en una tarea individual nueva, fuera del dispatch Council-all. No relanza a N miembros para consolidar.

Implementación: `adaptive`, concurrencia máxima3, `parallel`, `fork`, `stop`, sin `executionOrder`. Cada rol exige DAG/tarea/permiso y devuelve `NEEDS_PLAN/BLOCKED` si el fallback no proporciona prerrequisitos.

Una organización nueva recibe `organization_id` propio; los UUID de perfiles y squads derivan de él, y las revisiones preservan esa identidad. El modo explícito `import_legacy` requiere exactamente N agentes del backup aportado y conserva esos UUID y el squad de implementación; nunca rellena un equipo de 24 con la muestra de 3 o 21. La plantilla implícita histórica sigue disponible para compatibilidad. Council tiene un UUID distinto de implementación. Los dos squads tienen UUID distintos, pero usan los mismos IDs y exactamente el mismo prompt bifásico por agente. La fase se fija en `collabNote`; así importar ambos por merge no sustituye un prompt Council-only por uno implementation-only.

Atención: merge actualiza definiciones de agentes globales y puede afectar squads anteriores que compartan sus IDs. Conservar backup y verificar el preview de `affectedSquads` antes de importar. Usar los recipes nuevos y no ejecutar un squad anterior sin contrato `ORGDNA_PHASE`; sus perfiles compartidos podrían bloquearse por fase ausente. Copy puede remapear UUID estructurales sin corregir UUID escritos en textos; exige reconciliación de identidad antes de operar.

En la actualización explícita de un equipo heredado se preservan sus IDs/names; cambia el orden para alinear jerarquía. Los prompts se reconstruyen de forma compacta y autocontenida, no concatenan literalmente las 49k unidades de los originales. El archivo base nunca se modifica. El sidecar conserva el perfil completo.

## Edición web y jerarquía manual

Cada organización tiene `state_version`. Las ediciones usan `{expected_state_version, agents:[{id,...campos}], hierarchy_mode?, functional_subteams?}`. La versión debe coincidir; el objeto original no se modifica. Se permiten display_name, title, department, mission, personality, responsibilities, deliverables, skills, proposed_skills, cv y reports_to. IDs, nombre técnico original, permisos, prompts directos y modelos no son campos de esta operación. Las rutas de modelo se gestionan aparte.

El reparentado activa `hierarchy_mode=manual`. Se recalculan descendientes, profundidad, supervisor, competencias de liderazgo, revisión independiente y prompts. CEO permanece bajo Owner, sin ciclos ni exceso del span. Un reset explícito a `automatic` reconstruye BFS. Generar desde cero no descarta silenciosamente un árbol manual: exige la conversión explícita. El Excel con fórmulas BFS no representa esta jerarquía manual; el puente debe bloquear esa sincronización o avisar y convertir sólo con decisión expresa.

Subequipos: `{id?,name,type:"audit"|"consulting",member_ids,facilitator_id?,scope?}`. Máximo16 grupos; todos sus miembros ya cuentan dentro de N. Facilitación no crea jefatura ni acredita independencia. Las afiliaciones quedan en el sidecar y dentro de los prompts exportados.

Las profesiones del análisis se distribuyen de manera única por encaje con competencias/función, con rutas de evidencia y estado PROPOSED_NOT_VALIDATED. `competency_coverage` expone propuestas asignadas, compuestas y brechas por falta de N, evidencia o revisión de contenido. Nunca afirma cobertura total por el mero número de agentes. Se preservan las señales de cobertura parcial del lector.

## Seguridad y verificación

Para ArbitrageX la meta declarada puede incluir despliegue mainnet, capital real y beneficio neto realizado en USD, siempre sujeto a evidencia, costes y riesgo; no es una promesa de rentabilidad. Esa meta, un saludo o el preset no autorizan transacciones, uso de capital, firmas ni cambios de credenciales: cada acción requiere la autorización aplicable y, cuando corresponda, intervención del usuario. Roles y prompts no son ACL. Las herramientas efectivas, el aislamiento y las autorizaciones corresponden al host. No se instalan herramientas ni se garantiza un modelo por mencionar su nombre.

Skills correctivas sólo tras fallo demostrado, causa raíz, corrección versionada, retest y aprobación del supervisor más un revisor independiente. No hay entrenamiento de pesos ni ciclo automático de aprendizaje conectado a DSH.

Límites de exportación: prompts <50.000 unidades UTF16, collabNote <8.000, recipe indentado UTF8 <4MiB, sin campos DSH inventados. La validación detecta IDs repetidos, ciclos, cobertura, independencia, metadatos jerárquicos contradictorios, rutas de modelos editadas sin nueva validación y configuración obsoleta. Cambiar config requiere regenerar.

Pruebas locales: `python -m unittest discover -s tests -p 'test_core.py' -v`. Cubren todos los 256 árboles N1–32/span1–8 y casos negativos. Esta prueba no sustituye una importación real en la versión DSH instalada.


## Autonomía, generación por API y contexto

`engine/autonomy.py` compila el objetivo, contrato de saludo, Plan Preview y campos nativos soportados. `autonomy_preset` admite `autonomous`, `smart` y `manual`; `planning_context` admite `current`, `recent` y `full`. Los topes de planificación, tokens por run, timeout, resumen de handoff y rondas de quality gate son configurables dentro de los límites revisados. El quality gate sólo se propone cuando hay revisor e implementador estructuralmente independientes; no prueba independencia por artefacto ni una revisión ejecutada.

Un equipo debe estar seleccionado en una sesión compatible para que el host lo use. Con always/guaranteed un mensaje, incluso un saludo, puede consumir tokens. Full utiliza el contexto disponible; no otorga acceso al repositorio ni memoria entre sesiones. `PLAN_PREVIEW_TAREA.txt` es la tarea específica del repositorio para copiar en Plan Preview; no se inventa un campo `previewTask` en DSH. Ver `docs/automatic_generation.md` y `docs/export_artifacts.md`.

## Cordis, Plugin Shop y conexión DSH

La app integra preparación de un addon aditivo para el mismo roster, búsqueda/inspección de candidatos reales del catálogo público y una conexión local emparejada de sólo lectura. Los JSON nativos contienen los contratos de los perfiles; no pueden instalar ni registrar capacidades de un host por sí mismos.

La variante Cordis extendida es opt-in, conserva organización y UUID de agentes/squads, añade el contrato compartido y propone hasta seis nombres de herramientas namespaced en allowlists explícitas, respetando deny y el límite 256. El motor no instala ni activa el addon. Los archivos fuente y pruebas incluidos permiten prepararlo desde la app extraída; no se distribuyen estados, credenciales, códigos de emparejamiento ni la caché completa del catálogo remoto.

Ver `docs/integration_runtime.md`, `docs/plugin_shop.md` y `cordis_extension/README_ES.md`. Una prueba de transporte Node/Python con servicios simulados acredita sólo ese recorrido de prueba: no la instalación DSH del usuario, sus latencias de producción, sesiones vinculadas ni entrega realtime. El bus Cordis se consulta y no despierta sesiones; envío de planes y otras operaciones permanecen bloqueados si el adaptador no las ofrece y verifica.
