# Contrato local de mando, méritos y coordinación

El puente escucha exclusivamente en loopback. Los POST siguen el control existente de Host, Origin local, cookie HttpOnly de sesión y X-CSRF-Token; no se añade endpoint abierto, credencial persistente ni adaptador DSH. Las identidades agent/reviewer/owner enviadas son declaradas por el usuario local: no autentican un agente conectado. Un futuro adaptador requerirá autorización y autenticación propias antes de certificar ejecución o identidad.

## Estado y versiones

GET `/api/state` devuelve la organización, `tool_catalog`, `scoreboard`, `records_version`, `performance_records`, `promotion_records`, `governance_events`, registros de Council/skills/correcciones y `coordination`.

Los endpoints nuevos de diseño/méritos exigen `expected_state_version` igual a `organization.state_version`. Cada cambio aceptado incrementa esa versión; los méritos también incrementan `records_version`. Error JSON `{error: texto}` y HTTP 400 no autoriza repetir sobre estado diferente: refrescar el estado y revisar antes de reintentar. Los clientes existentes de registros conservan compatibilidad, pero deben enviar versión para evitar editar formularios antiguos.

`project-save {name,as_new?}` conserva lifecycle en versiones inmutables. El guardado de un proyecto existente hace comparación atómica con la versión cargada: si otra sesión guardó una nueva, rechaza sobrescribir su puntero. Guardar como nuevo es una acción explícita separada. El hash detecta corrupción, no autentica a quien tiene acceso de escritura al almacén.

## Políticas de herramientas

POST `/api/tool-policy` recibe `{agent_id,allow:[nombre],deny:[nombre],expected_state_version}`. Alternativamente `reset_to_role_proposal:true` repone la propuesta del catálogo. Allow vacío requiere `inherit_parent_tools:true` y deny no vacío conforme al schema; no significa denegar todo. El helper valida sintaxis y límites, acepta nombres manuales desconocidos sólo como no verificados y reconstruye prompts/exports actuales. Nunca instala herramientas, concede acceso al equipo ni comprueba disponibilidad DSH.

## Méritos

POST `/api/performance-create` registra `{agent_id,task_id,title,comparison_group,candidate_sha,acceptance_criteria:[texto],budget,budget_unit,evidence:[referencia],author_ids?,expected_state_version}`. La tarea es única; el presupuesto y criterios quedan fijados antes de revisar.

POST `/api/performance-review` registra `{performance_id,reviewer_id,measurements,evidence,rationale,conflict_of_interest:false,includes_failures:true,expected_state_version}`. `measurements` contiene quality/compliance/collaboration/evidence con `{numerator,denominator}` y efficiency con `{budget,actual}`. El denominador quality incluye todos los criterios acordados; efficiency conserva el presupuesto. Corregir una revisión exige `supersedes_review_id`; el historial permanece. Se rechaza autoevaluación, coautoría, cadena de mando y revisor interno sin función auditora. Un externo usa `EXTERNAL:identificador`, `external_reviewer_name`, `appointed_by:'OWNER_EXTERNAL'`, `appointment_evidence`.

POST `/api/promotion-create` y `/api/promotion-update` aplican las transiciones de `governance.py`. Son recomendaciones y aprobación registradas, nunca cambian árbol, ACL, toolScope, modelo ni runtime. Score y ranking se recalculan de evidencia declarada revisada por grupo comparable; sin datos, score/rank son null. La app no ejecuta pruebas ni verifica las identidades/evidencias registradas.

POST `/api/skill-feedback` recibe `{skill_id,agent_id,failure,proposed_change,retest_result,evidence,expected_state_version}`. Añade feedback y revisión de skill preservando `installed=false`, `verified=false`. Es aprendizaje operativo registrado, no entrenamiento de pesos ni despliegue automático.

Cada sesión Council preserva el snapshot de los mismos N IDs del diseño. `participation` cuenta una identidad sólo una vez, muestra faltantes y distingue todas las aportaciones registradas de un Council runtime verificado. Cerrar un acta incompleta no simula participaciones.

## Tickets exclusivos de escritura

POST `/api/lease-acquire`:

- `owner_agent_id`: ID del diseño actual; `task_id`: tarea concreta
- `workspace`: ruta local absoluta POSIX o Windows; no URL, UNC ni traversal
- `paths`: 1–100 rutas relativas, normalizadas, sin escape del workspace; se rechazan symlinks que escapen
- `base_sha`: 40 o 64 caracteres hexadecimales; referencia declarada, no comprobada contra Git
- `ttl_seconds`: 60–3600, por defecto 900
- `expected_version`: `coordination.version` actual
- `request_id`: opcional; sólo replay idéntico de una adquisición aún activa es idempotente

POST `/api/lease-renew`: `{lease_id,owner_agent_id,task_id,ttl_seconds?,expected_version}`.
POST `/api/lease-release`: `{lease_id,owner_agent_id,task_id,expected_version}`.

El ledger único en `data/projects/_coordination/` cubre todos los proyectos/workspaces que usan ese almacén. El guardado atómico, mutex de threads y bloqueo OS del ledger serializan cambios incluso entre procesos. Se permiten como máximo tres tickets activos globales; no tres por proyecto. Cualquier igualdad o relación padre/hijo de destino canónico bloquea la adquisición, también entre workspaces anidados. Windows compara sin distinguir mayúsculas/minúsculas. Distintos SHA no permiten compartir la misma ruta.

Expirar, renovar y liberar deja eventos de auditoría. Sólo el propietario/tarea declarados pueden renovar o liberar. Un ticket expirado no revive; debe crearse una adquisición nueva con revisión de versión. La expiración ocurre al consultar o modificar el ledger, sin proceso de ejecución en segundo plano.

`coordination` devuelve `{version,max_writers:3,active_writer_count,leases,audit,enforcement:'local_coordination_only',filesystem_lock_enforced:false,dsh_enforced:false}`. Cada lease tiene `id`, propietario/tarea/workspace/paths/SHA, estado, vencimiento y versión. La exclusión coordina clientes cooperativos: NO bloquea archivos del sistema ni impide que un editor externo ignore los tickets. No se comprueba que el SHA local siga intacto; un adaptador autorizado debe comprobarlo antes de aplicar cambios.

El snapshot del proyecto incluye una copia histórica, pero cargar o duplicar proyectos nunca reemplaza el ledger global ni reactiva tickets guardados. El ZIP distributivo excluye actas, scores personales y tickets. `/download/lifecycle.json` es una descarga local explícita del historial, con banderas de no verificación; no es un archivo importable como permisos.
