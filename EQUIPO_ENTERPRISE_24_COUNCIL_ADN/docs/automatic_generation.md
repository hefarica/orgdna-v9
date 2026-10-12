# Generación automática local: contrato de la app

Este flujo diseña perfiles con la API elegida y conserva por separado el modo de plantilla offline. No importa archivos en DSH, no abre una instalación de DSH, no inicia agentes ni ejecuta código del repositorio.

## Recorrido único

1. Introducir URL HTTPS del repositorio, N (1–32), proveedor y modelo exacto. La clave se introduce exclusivamente en el panel local; por defecto sólo permanece en memoria. Guardarla con DPAPI requiere la opción expresa del usuario en Windows.
2. `POST /api/generation-plan` recibe `idempotency_key`, configuración opcional, `new_project`, `max_output_tokens` y, cuando corresponde, confirmación del reemplazo de ediciones. Devuelve inmediatamente un trabajo. El inventario de sólo lectura sucede en un hilo local; puede reutilizar el inventario ya fijado a un SHA.
3. Consultar `GET /api/state` hasta `generation_job.status=awaiting_consent`. La vista previa muestra contenido exacto, destinatario, modelo, N, hashes por solicitud y límites totales. Un límite de tokens no es un importe máximo en USD. No se ha enviado el repositorio al LLM todavía.
4. `POST /api/generation-confirm` confirma `job_id`, `config_version`, `consent_id`, `payload_sha256` y las banderas `confirmed`, `data_reviewed`, `budget_acknowledged`. La autorización se consume antes de iniciar el lote. Todos los mensajes de todos los lotes están fijados de antemano. No hay reintentos ni fallback de modelo.
5. La app valida exactamente N perfiles completos, compila el ADN, valida ambos JSON DSH y verifica el ZIP antes de reemplazar el estado anterior. `completed` expone nombres nativos, bytes y SHA-256 reales de los artefactos. El formato DSH permanece estricto; los hashes viven en el manifiesto aparte.

Estados: `planned`, `awaiting_consent`, `running`, `validating`, `completed`, `failed`, `cancelled`. El progreso corresponde a trabajo local y solicitudes completadas; nunca acredita ejecución de agentes.

## Repetición, cancelación y cambios

- Repetir la misma clave de idempotencia con la misma configuración devuelve el trabajo existente. Cambiar sus parámetros con la misma clave se rechaza. Las confirmaciones concurrentes o repetidas nunca vuelven a llamar al proveedor.
- `POST /api/generation-cancel` con `job_id` evita lotes posteriores y el commit. Una solicitud HTTP ya enviada puede finalizar y generar cargos. Cancelar no la deshace ni devuelve su coste.
- Cambiar la configuración, cargar otro proyecto o editar el diseño invalida el trabajo pendiente. No se aplican resultados calculados para otro estado.
- Un timeout, respuesta incompleta, esquema inválido o fallo de exportación conserva el ADN anterior. Un lote parcial no es un diseño nuevo exportable. La app no fabrica perfiles faltantes.
- Tras reiniciar el servidor no se restauran autorizaciones ni trabajos pagados pendientes. Una nueva tentativa necesita revisar y confirmar un lote nuevo. La ausencia de respuesta anterior no demuestra ausencia de cargos.

## Identidad y exportación

`new_project=true` asigna un UUID nuevo una sola vez, antes de la autorización; vuelve a aparecer en los artefactos del trabajo final. Una revisión conserva `organization_id` y los UUID por slot, e incrementa `dna_revision`. Reexportar no regenera identidad.

Ambos JSON principales y el ZIP comparten una instantánea de exportación: misma fecha y mismos bytes de los JSON dentro y fuera del ZIP. Los nombres siguen `agent-team-backup-YYYY-MM-DD.json` y `agent-team-recipe-UUID.json`. El UUID es el del squad, no el hash. El manifiesto no incluye su propio hash ni el del ZIP; evita referencias circulares. La app calcula el SHA-256 del ZIP terminado para mostrarlo.

Las versiones de proyecto pueden guardar el ADN, su identidad, revisión y hash; excluyen claves, cookies, autorizaciones y payloads de consentimiento. Cargar una versión no verifica nuevamente la disponibilidad de la cuenta/modelo. Los métodos, CV e instituciones son ficticios aspiracionales y las capacidades necesitan evaluación independiente.

## Integraciones desde la misma aplicación

- Cordis: `cordis-prepare` exige la versión actual del ADN y genera un ZIP inerte para exactamente los mismos miembros. La app conserva únicamente versión solicitada y `enabled=false`; descargar no instala, activa ni amplía permisos. Cambiar el ADN deja obsoleto el ZIP anterior hasta prepararlo de nuevo.
- Plugin Shop: la app consulta metadatos públicos, busca, inspecciona y prepara planes versionados. El catálogo completo queda sólo en memoria; el panel recibe resultados acotados. Los planes son `PLAN_ONLY`; pruebas/activaciones reportadas son declaraciones del operador. Cargar un proyecto no restaura flags de instalación o activación, y obliga a revisar de nuevo el catálogo vigente antes de otro plan.
- Conexión DSH: opt-in de sólo lectura mediante puerto loopback y código efímero mostrado por el addon local. No hay descubrimiento automático ni reutilización de cookies. El código y la sesión no se guardan en proyectos; el panel recibe estado seguro y snapshots de lectura. Consultar el estado de la app no envía peticiones DSH: sólo revisa la caducidad local de la última conexión comprobada.
- La vista previa de importación usa los mismos JSON congelados del ADN actual y queda obsoleta si cambia el diseño. No importa nada. No existe un endpoint de envío/ejecución de planes: la capacidad permanece bloqueada mientras no haya una interfaz nativa verificada que preserve permisos y aprobaciones.

La conexión de lectura pertenece a la sesión de la app y puede conservarse al cambiar entre proyectos. Los previews y planes del proyecto anterior se eliminan al cambiar. Cerrar la app cancela lotes de API futuros y desconecta la sesión local; ninguna de estas acciones revierte una solicitud que ya haya sido transmitida.
