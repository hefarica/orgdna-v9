# Workflows revisables por recurso y agente

## Qué existe

`engine/resource_workflows.py` convierte una referencia documental consultada y
los roles actuales de una organización en propuestas estructuradas. Dos rutas:

- `baseline_resource_workflows`: plantilla local determinista, sin API. Se muestra
  explícitamente como plan base no generado por IA.
- `prepare_workflow_consent` + `workflows_with_llm`: usa exclusivamente el proveedor
  y modelo API seleccionado, después de revisar roles, evidencia, endpoint,
  llamadas y límite de tokens. No cambia de proveedor ni usa aliases runtime.
  Hashes fijan organización, referencia, payload y presupuesto. Cambios requieren
  otro consentimiento. Una solicitud fallida consume su autorización; no hay
  reintentos automáticos ni publicación parcial de lotes.

Cada agente recibe objetivo, requisitos previos, pasos condicionales,
entregables, pruebas independientes, fuentes conocidas y límites propuestos.
El modelo no puede retirar los requisitos, guardrails, límites ni las pruebas
independientes añadidas desde código. Los IDs de agentes y fuentes deben existir.
Se rechazan claves de esquema inesperadas, endpoints y claims de instalación.
El contenido del modelo sigue siendo una propuesta que requiere revisión humana;
la validación de esquema no prueba la veracidad de todas sus frases.

## Biblioteca y exportación

`ResourceWorkflows` en `engine/resource_workflows_adapter.py` maneja los jobs
asíncronos y el flujo explícito preview/apply. Las propuestas se serializan como
`skill_instructions`, sin migración del esquema de CapabilityLibrary.

La previsualización de importación y asignación usa una base SQLite en memoria.
Aplicar comprueba la fuente, revisión de biblioteca, organización y proyecto;
importa y asigna cada workflow únicamente a su agente. Toda la operación tiene
una transacción: un fallo tardío revierte importaciones y asignaciones anteriores.
Un subset de agentes debe identificarse por sus IDs actuales, sin asignación
cruzada. Replay con la misma clave devuelve la operación sin repetir efectos.

Asignar mantiene las instrucciones inactivas. Activar sólo afecta al contexto
del agente mediante el compilador/exportador existente. No instala herramientas,
no concede permisos, no cambia pesos ni verifica runtime. El presupuesto de
contexto puede diferir un item completo; nunca se debe afirmar que un item
excluido está dentro del prompt. Consentimientos y claves no se exportan.

## Prerrequisito al arrancar DSH

Cada workflow incluye un `startup_gate` invariable, añadido tanto al baseline
como a la respuesta del LLM. Su instrucción inicial exige comprobar la capacidad
instalada, versión, configuración y contrato antes de las tareas de negocio.
Si falta, prepara un skill/adaptador y plan de instalación compatibles desde una
fuente, licencia y contrato verificados. La instalación requiere el mecanismo real
comprobado y la autorización aplicable; no se inventa un instalador ni se ejecuta
código al activar estas instrucciones.

La configuración prevista tiene un namespace estable por organización, agente y
recurso. Su persistencia, sin secretos, debe preservar la configuración DSH y de
otros agentes, y verificarse mediante lectura posterior. El gate comienza en
`pending_integration`, instalación `unverified`, configuración `not_persisted` y
aceptación `not_run`. Sólo puede considerarse READY con instalación compatible,
contrato/licencia verificados, autorización/presupuesto, persistencia verificada
y aceptación independiente PASS. Las tareas dependientes permanecen bloqueadas;
la investigación de sólo lectura y la preparación de un plan revisable siguen
permitidas para resolver requisitos faltantes. Son instrucciones exportables,
no un instalador o hook runtime ejecutado por OrgDNA.

## DataInventor

El botón de ejemplo usa `datainventor_research_reference()`, snapshot de
investigación pública revisada del 2026-10-08. No hace fetch ni afirma haber leído
la URL en vivo. Los hashes fijan los extractos locales de investigación, no los
bytes remotos ni el backend.

La referencia LocalLLaMA es una envoltura HTML estática que enlaza la app
codelion/data-inventor. Commit conocido de la envoltura:
`d2ccaf86768d19785b951c42895c6b872b334455`. Este SHA no versiona el backend.
Contrato de API, licencia del backend, dependencias, modelo efectivo, secretos,
retención y costes siguen sin verificar. La licencia Apache-2.0 de un dataset de
ejemplo no se extrapola a la aplicación. OptiLLM no demuestra una API equivalente.
No se asume `/predict`, Gradio Client ni un servidor MCP.

El plan de ingeniería de datos pide contrato de adaptador, `dataset.jsonl`,
`manifest.json` y `quality-report.json`. IA planifica cobertura y QA comprueba
independientemente esquema, límites, duplicados, contenido sensible, inyección,
timeouts, cancelación, parciales, autenticación y consumo. La generación sólo
podría ocurrir tras verificar requisitos y recibir autorización separada.
Límites de partida propuestos: 100 filas, 20 000 tokens totales, cero reintentos;
presupuesto monetario desconocido y no autorizado. Los outputs permanecen en
staging: nunca evaluación canónica, verdad, memoria o entrenamiento automático.

## API del adapter

- `resource-workflow-example`: carga snapshot local revisado, no consulta remota.
- `resource-workflow-baseline` / `resource-workflow-plan`: `expected_state_version`,
  `reference_hash`, `selection`, `idempotency_key`; límites opcionales.
- `resource-workflow-confirm`: `job_id`, `approval_id`, `payload_sha256` y
  `confirmed`, `data_reviewed`, `budget_acknowledged` exactamente verdaderos.
- `resource-workflow-cancel`: `job_id`.
- `resource-workflow-preview`: `job_id`, `expected_state_version`,
  `expected_revision`, `action` (`assign`/`activate`), subset opcional
  `workflow_agent_ids`.
- `resource-workflow-apply`: `expected_state_version`, `preview_hash`,
  `confirmed: true`, `idempotency_key`.

`public()` expone `job` y `preview`. Las referencias live deben venir de
`capability_sources.read_reference`; la URL no basta para autorizar nada.

## Verificación reproducible

`python -m unittest tests.test_resource_workflows tests_resource_workflows_adapter -v`

24 tests offline cubren planes por rol, fuentes observadas frente a backend
sin verificar, consentimiento exacto, modelo/proveedor, IDs, límites, cancelación,
cambio de contexto, replay, secretos, permisos, activación, CAS y rollback total.
No se ejecuta código externo, no se hace inferencia real ni se genera un dataset.
No se añaden dependencias.
