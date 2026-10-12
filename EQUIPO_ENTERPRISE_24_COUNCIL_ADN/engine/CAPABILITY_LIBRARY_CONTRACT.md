# Biblioteca local de capacidades

`CapabilityLibrary(path, project_id)` usa SQLite stdlib. La ruta la decide la aplicación dentro del almacén autorizado. El adapter actual usa `data/projects/_capabilities/registry.sqlite3`, con namespace de biblioteca UUID validado guardado en cada snapshot. No acepta rutas de base de datos desde el navegador. Para migrar, cerrar OrgDNA y copiar TODO `data/projects`, incluida la subcarpeta `_capabilities` y auxiliares SQLite presentes. Copiar sólo el JSON de un proyecto no mueve su biblioteca. La base es estado privado: nunca miembro de un ZIP público ni una copia de claves, grants, credenciales o consentimientos.

Save As llama `fork(new_project_id, expected_revision=None)` con UUID nuevo. Copia registros, asignaciones y eventos a un namespace independiente en la misma base; conserva números de versiones y añade un evento `fork` en revisión origen+1. No copia claves de replay de solicitudes. Cambios futuros del destino no modifican el origen. El destino existente se rechaza, nunca se sobrescribe. Fork y sus copias son una transacción. Si guardar el JSON después falla, el adapter no cambia el proyecto activo; puede quedar una copia privada sin referencia, que no comparte estado con el origen.

Los snapshots JSON no congelan ni revierten SQLite. Al cargar una versión histórica, el adapter muestra explícitamente revisión de biblioteca guardada y actual (o guardada desconocida en snapshots antiguos); una diferencia no equivale a restauración de capacidades. Deshacer asignaciones requiere su acción CAS explícita. El importador nunca consulta URLs ni ejecuta contenido.

## Estados y datos

Tipos independientes: `skill_instructions`, `plugin_package`, `connector`, `memory_policy`. Asignado no significa activo, instalado, disponible ni verificado. Sólo instrucciones y políticas pueden activarse como contexto. Activación tampoco cambia herramientas, permisos manuales, autoridad, identidad, formación real ni pesos del modelo.

Un registro acepta `id` opcional, `kind`, `name`, `description`, `content`, listas de texto `tags`, `role_evidence`, `tool_needs` y `provenance`. La procedencia requiere `type` (`catalog_snapshot`, `page_evidence`, `html_summary`, `user_authored`) y `evidence`, con `url`, `source_id`, `retrieved_at`, `sha256` opcionales. URLs son referencias HTTPS sin query/credenciales; nunca permiso para fetch. Evidencia consultada es una afirmación del llamador, no prueba independiente de calidad de la fuente. Hashes propios preservan integridad del snapshot, no confiabilidad. Los registros son inmutables: cambiar contenido requiere nuevo ID.

No hay tope lógico de 500 registros. Cuotas predeterminadas: 2 MiB/solicitud, 128 KiB/registro, 256 MiB de payload lógico por proyecto; overhead de SQLite/índices puede ocupar más disco. Páginas de 1–200; búsqueda y auditoría ajustan además bytes de respuesta. El caller debe continuar `next_offset`, no asumir que `limit` siempre se devuelve completo.

## API

- `status()` devuelve revision, item_count, assigned_count, active_count, assigned_agent_count y cuotas.
- `import_items(items, expected_revision, idempotency_key)` guarda referencias explícitamente, sin asignar. No usar importación dentro de un botón presentado como previsualización read-only.
- `preview_import_items(org, items, existing_ids, selection, expected_revision=None, action='assign')` simula en SQLite en memoria, sin escribir estado persistente. `apply_import_preview(org, preview, idempotency_key)` importa y asigna en una única transacción con rollback integral. Devuelve revision final (dos eventos: import y asignación). El adapter debe revalidar el hash del catálogo actual si la fuente es un catálogo de sesión.
- `search(query='', kind=None, offset=0, limit=50)` devuelve items, total, next_offset, revision.
- `read_items(item_ids)` devuelve registros exactos; falla si alguno falta.
- `preview(org, item_ids, selection, action='assign', expected_revision=None)` es read-only. Selection: `{mode:'all'}`, `{mode:'selected',agent_ids:[...]}`, `{mode:'subteam',subteam_id:'...'}`. Resuelve IDs reales, deduplica y valida subequipos de org.functional_subteams. Acciones: assign, activate, deactivate, unassign. Devuelve efectos before/after, cambios, IDs y hash del plan completo.
- `apply(org, preview, idempotency_key)` recomputa y compara previsualización/organización, rechaza revisión obsoleta; realiza transacción atómica. No modifica org ni sus denegaciones manuales.
- `undo(org, version, expected_revision, idempotency_key)` revierte efectos de esa versión; rechaza organización distinta o ediciones posteriores sobre las mismas asignaciones, incluso ABA.
- `audit_page(offset=0, limit=50)` devuelve eventos versionados; `manifest_page(offset=0, limit=100, agent_ids=None)` devuelve referencias de asignación paginadas, no cuerpos de instrucciones. Un roster `agent_ids` filtra antes de contar/paginar; `[]` devuelve vacío.
- `active_context(org, agent_id, budget_bytes=12000)` entrega texto íntegro de cada registro que cabe; difiere el resto, nunca lo corta. Máximo 24.000 bytes; caller debe dejar margen para el prompt base y los límites nativos DSH. El orden estable de IDs hace el resultado determinista. Sólo texto va a prompts; manifest y biblioteca permanecen sidecars.
- `recommend(org,selection,offset=0,limit=50)` calcula coincidencias de rol/brechas declaradas, nunca CV/credenciales ficticias. Son candidaturas sin verificación ni auto-install. El contrato advisory futuro exige fuentes y prohíbe conceder autoridad.

CAS/idempotencia se verifican en transacción `BEGIN IMMEDIATE`. Repetir exactamente la clave/solicitud devuelve resultado previo; reutilizarla con otra carga falla. Undo, import y apply son eventos auditados. No hay endpoint delete permanente ni instalación.
