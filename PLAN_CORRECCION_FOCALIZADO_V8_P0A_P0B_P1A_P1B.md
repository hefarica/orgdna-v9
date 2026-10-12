# PLAN DE CORRECCIÓN FOCALIZADO — OrgDNA / "Preparar ADN con IA"
## Paquetes P0-A · P0-B · P1-A · P1-B sobre la base V8 realmente presente

**Naturaleza del entregable:** documento de diseño técnico y mapa de cambios. **No es el patch aplicado.**
**Modo:** `propose` (lectura y diseño). No se envió ninguna solicitud a ningún proveedor, no se consumieron claves, no se modificó DSH, no se instalaron dependencias, no se escribió ningún archivo dentro del paquete entregado.
**Convención de rutas:** todas las rutas son relativas a `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`, raíz de la suite.
**Convención de citas:** `archivo:línea` sobre el código leído en esta sesión, o `archivo:línea-línea` para rangos. Ninguna afirmación técnica de este documento se apoya en memoria: cada una cita el artefacto.

---

## 1. Resumen ejecutivo

1. La base presente **no es V7**: es un parche **V8** ya aplicado (`LEEME_V8.txt`, `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md`), con el código de P0-A, P0-B y P1-A **parcialmente implementado y con pruebas escritas** (`tests_v8_models_receipts.py`, `tests_v8_evidence.py`, `tests_v8_ui_contract.py`).
2. En consecuencia, este plan **no reimplementa** esos paquetes: cierra sus huecos residuales, ya declarados por la propia suite (`docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:22-36`).
3. **Hallazgo que contradice la premisa central del encargo:** la única evidencia local del fallo (la imagen aportada) mapea 1:1 al diagnóstico `output_truncated` — categoría `output_limit` (`engine/org_design.py:46`), que **sólo** se emite cuando `finish_reason == "length"` (`engine/org_design.py:648`), es decir **tras una respuesta HTTP aceptada y completada por el proveedor**. No es el texto de un HTTP 400.
4. `job_id` `d560a3f9-22e5-4f52-96ec-8710c19b5a50`, el HTTP 400/`invalid_request_error`, las cifras de inventario (254/18/236/4/86/2) y el 88,52 % de duplicación **no tienen ningún artefacto en este paquete**: no son verificables aquí. Búsqueda **byte-level** del `job_id` sobre todo el árbol, incluidos `.pyc`/`.sqlite3`/`.exe`/`.xlsx`: sin coincidencias. Se solicitan en el Anexo B.
5. El `DeepSeek-V41-Flash` **no aparece en ningún código ni catálogo**: sólo en datos de proyecto ya guardados (`data/projects/98d8ec4f-…/versions/*.json:19,23,…`). El catálogo documentado usa `id = "deepseek-flash"` y `name = "DeepSeek-V4.1-Flash"` (`engine/providers.py:56`), exactamente la separación ID/nombre que el encargo exige.
6. **Hipótesis principal, supported por el código y falsificable:** el fallo observado es una **truncación por dimensionado de lote**, no un rechazo por identificador. El plan calcula el tope de salida consumiéndolo casi exactamente (`cap = 1024 + 2400·perfiles`, `engine/org_design.py:28,469,491`) sobre una estimación local que el propio código declara no ser tokenizer (`engine/org_design.py:509-511`).
7. El identificador de modelo **sí contribuye**, pero por un mecanismo distinto del que el encargo supone: sin catálogo de cuenta no hay metadatos de límites, y la ausencia de límites **no bloquea ni adapta el plan**, sólo añade una advertencia (`engine/org_design.py:545-546`; `engine/bridge.py:785-786`).
8. Por tanto P0-A sigue siendo el paquete prioritario, pero su cambio obligatorio **no** es "rechazar display names" (ya se rechazan, `engine/bridge.py:804-832`) sino **hacer de `limits_reported == False` una condición que bloquee o reduzca el lote** antes del consentimiento.
9. P0-B, P1-A y P1-B conservan huecos reales verificados: ledger durable inexistente, esquema de recibo sin `attempt`/`idempotency_key`/`result_outcome`, lectura fragmentada de archivos >40 KB ausente (`engine/providers.py:32`), y **`TaskSpec` no existe en ninguna parte del árbol** (búsqueda sin coincidencias).
10. El plan se mantiene **bloqueado a cuatro paquetes**; todo hallazgo adicional se registra como *dependencia nueva no autorizada* (Anexo A) sin consumir presupuesto ni ampliar alcance.
11. No se promete éxito de proveedor, ni 99,9 %, ni "sin fallos". Se proponen SLO medibles y se separa éxito de request, éxito de esquema y éxito útil (sección 14).
12. Todo cambio propuesto es compatible con los formatos vigentes: proyecto `orgdna-local-project` v1 (`engine/project_store.py:126,163`) y export `orgdna/export-manifest` v1 (`engine/export_artifacts.py:124`).

---

## 2. Estado probado vs hipótesis vs no verificado

### 2.1 Método de esta sección

Se distinguen tres estatutos epistémicos y **no se mezclan**:

- **[V]** Verificado en esta sesión por lectura directa de artefactos del paquete.
- **[H]** Hipótesis sostenida por el código, con falsificador declarado, no demostrada.
- **[NV]** No verificado: ni confirmado ni refutado, por ausencia del artefacto necesario.

Los hechos aportados por el operador sobre su instalación viva (autoridad externa a este paquete) se registran como **[O]** y **no se convierten en hechos de código**.

### 2.2 Hechos aportados por el operador [O] — autoridad externa, no verificables aquí

| Hecho aportado | ¿Artefacto en el paquete? | Estatuto |
|---|---|---|
| `job_id: d560a3f9-22e5-4f52-96ec-8710c19b5a50` | **No.** Búsqueda byte-level sobre todo el árbol, incluidos binarios: sin coincidencias | **[NV]** |
| `HTTP: 400`, `provider_error_code: invalid_request_error` | **No** | **[NV]** — y en tensión con 2.3 |
| `sent_requests: 1`, `completed_requests: 0`, `completed_profiles: 0` | Parcial: la forma del job existe (`engine/generation_pipeline.py:382-392`), el valor no | **[NV]** |
| `potentially_billed: true`, `billing outcome: unknown` | El campo y su semántica existen (`engine/generation_pipeline.py:549`, `engine/providers.py` no expone usage en error) | **[V]** el campo; **[NV]** el valor |
| `retry_requires_new_consent: true` | **[V]** `engine/generation_pipeline.py:215` | **[V]** |
| `stage: api_design` | **[V]** etapa válida y presente en el enum de etapas (`engine/generation_pipeline.py:158`) | **[V]** |
| Inventario: 254 seguros / 18 leídos / 236 sin leer / 4 grandes / 86 no cubiertos / 2 binarios | **No hay ningún artefacto con estas cifras.** El código *calcula* equivalentes (`engine/providers.py:970-987`) pero no se conserva el resultado de aquel intento | **[NV]** |
| 88,52 % de cada payload era evidencia repetida | **No hay artefacto.** El código ahora *mide* esa magnitud (`engine/org_design.py:534-537`: `sent_file_occurrences` vs `full_repeat_file_occurrences`) | **[NV]** |
| `QUANTUMX/Bienvenido.md`, 204 bytes, referencia genérica | **No.** El token `Bienvenido` no aparece en **ningún** archivo del árbol | **[NV]** |

### 2.3 Trazabilidad exacta de la imagen aportada [V] — la contradicción

La imagen es un mensaje de la UI. Se reconstruye su composición literal desde el código, que la ensambla en una sola línea:

`web/app.js:454` → `(stage ? 'Etapa: ' + stage + '. ' : '') + detail + ' ' + generationFailureAction(job) + ' ' + generationBillingNote(job)`

| Fragmento de la imagen | Origen exacto en el código | Estatuto |
|---|---|---|
| `Etapa: api_design.` | `web/app.js:454` (plantilla) + `engine/generation_pipeline.py:158` (etapa válida) | **[V]** |
| `La respuesta alcanzó su límite de salida antes de completar el lote.` | `engine/org_design.py:46` — campo `message` de `_FAILURES["output_truncated"]` | **[V]** |
| `Reduce los perfiles por solicitud o aumenta el límite de salida compatible. Revisa el nuevo plan y sus posibles cargos.` | `engine/org_design.py:46` — campo `next_action` del mismo registro | **[V]** |
| `Puede haber cargos por solicitudes iniciadas, aunque no se haya completado ningún perfil. Iniciar no confirma que el proveedor recibiera o facturara la solicitud. Consulta el consumo en tu proveedor antes de aprobar otro intento.` | `web/app.js:558` — `generationBillingNote(job)`, activada por `job.potentially_billed \|\| job.sent_requests > 0` | **[V]** |

**Consecuencia [V]:** el código `output_truncated` se emite en **un único punto** del motor: `engine/org_design.py:648`, cuando la respuesta trae `finish_reason == "length"`. Esa rama exige que exista `choices[0]` con `message` — es decir, **una respuesta de chat válida del proveedor**. Un HTTP 400 recorre una ruta distinta y produce otro texto: `engine/providers.py:307` → `engine/providers.py:102-116` → `engine/org_design.py:136-137` → código `provider_http_error` o `unsupported_parameter`, cuyo mensaje es `"El proveedor rechazó la solicitud HTTP (HTTP 400)."` o el de parámetro no admitido (`engine/org_design.py:71-72,100-103`).

**Por tanto [V]:** la imagen **no puede** ser la pantalla de un HTTP 400. Afirma lo contrario de la premisa "HTTP: 400 / invalid_request_error" para ese intento concreto.

**Concesión honesta [NV]:** la imagen y los hechos [O] pueden pertenecer a **intentos distintos**. Este documento no puede resolverlo porque el cuerpo crudo de la respuesta no se conserva **por diseño** (`engine/bridge.py:700-701`: `raw_response_included: False`). La resolución exige el artefacto del Anexo B.

**Lo que sí queda refutado [V]:** la premisa de que el síntoma fuera *necesariamente* un rechazo de modelo. Cualquier plan que trate el HTTP 400 como causa demostrada estaría construyendo sobre una hipótesis.

### 2.4 Mecanismo del fallo: hipótesis principal [H] con falsificador

**[H1] Dimensionado de lote sin holgura sobre una estimación no verificada.**

Cadena verificada paso a paso en el código:

| # | Paso | Evidencia | Estatuto |
|---|---|---|---|
| 1 | `PROFILE_TOKEN_BUDGET = 2400` es una **estimación local** de coste de salida por perfil | `engine/org_design.py:28` | **[V]** |
| 2 | El comentario del motor declara que la estimación **no es un tokenizer del proveedor** | `engine/org_design.py:509-511` | **[V]** |
| 3 | En modo automático el tope de salida se fija como `1024 + 2400·perfiles`, es decir **el presupuesto entero sin margen** | `engine/org_design.py:469,491` | **[V]** |
| 4 | `per_batch = (effective_cap - 1024) // 2400`, truncado hacia abajo | `engine/org_design.py:469` | **[V]** |
| 5 | Si el modelo no reporta límites, `effective_cap = requested_cap` y **no se aplica ninguna reducción** | `engine/org_design.py:297-300,316` | **[V]** |
| 6 | El tope de contexto sólo se comprueba **si** el catálogo reportó `context_window`; si no, se omite | `engine/org_design.py:512-513` | **[V]** |
| 7 | La ausencia de límites añade **una advertencia**, no un bloqueo | `engine/org_design.py:545-546` | **[V]** |
| 8 | El proveedor devuelve `finish_reason = "length"` → `output_truncated` → fallo de todo el trabajo, consentimiento consumido | `engine/org_design.py:648`; `engine/generation_pipeline.py:548-551,715-734` | **[V]** |

**[H1] enunciada:** con N perfiles y `per_batch` calculado al límite exacto, un perfil real que cueste más de 2400 tokens de salida agota el tope y produce `finish_reason = "length"`. El primer lote que desborda aborta el trabajo completo: `completed_requests = 0`, `completed_profiles = 0`, `sent_requests ≥ 1`, facturación desconocida — **exactamente la forma de hechos reportada en [O]**.

**Falsificador de [H1]:** el `generation-diagnostic.json` de ese `job_id` mostrará `error.code = "output_truncated"`, `error.finish_reason = "length"` y `request_receipts[0].max_output_tokens` igual al tope planificado. **Si en su lugar** aparece `error.code ∈ {provider_http_error, unsupported_parameter}` con `http_status = 400` y `provider_error_code = "invalid_request_error"`, entonces [H1] queda refutada y la premisa del encargo prevalece: el plan pasa a ejecutar P0-A en su forma literal (rechazo de identificadores) sin necesidad del cambio de dimensionado. **Los dos desenlaces están previstos; el plan no elige por adelantado.**

**[H2] Contribución real del identificador no verificado — y por qué no es la que el encargo supone.**

| Afirmación | Evidencia | Estatuto |
|---|---|---|
| Un ID no verificado no puede preparar un envío: `validate_api_model_choice` lanza `BridgeError` | `engine/bridge.py:832`, invocado en `engine/generation_pipeline.py:363` (plan) y `:544` (confirmación) | **[V]** |
| Un nombre visible o alias DSH nunca se reinterpreta como ID | `engine/bridge.py:805-810` | **[V]** |
| Sin clave, DeepSeek devuelve snapshot documental marcado `UNVERIFIED_ACCOUNT_AVAILABILITY` | `engine/providers.py:390-391` | **[V]** |
| Un snapshot documental **no** verifica a un proveedor con descubrimiento (DeepSeek: `discovery: True`) | `engine/providers.py:44`; `engine/bridge.py:785-786,824-832` | **[V]** |
| El catálogo de cuenta de DeepSeek **no garantiza límites**: `_clean_model` sólo conserva `context_window`/`max_output_tokens` *si el proveedor los envía* | `engine/providers.py:364-366` | **[V]** |
| La verificación de catálogo se emite con `capabilities_verified: False` | `engine/bridge.py:819-821` | **[V]** |
| El catálogo guardado en proyecto **se degrada** al cargar: `available=None`, `source='saved_project_reference'`, `status='UNVERIFIED_SAVED_PROJECT'` | `engine/bridge.py:890-894` | **[V]** |
| Los sellos de cuenta son efímeros: `HMAC(csrf, clave)`, y `csrf` no sobrevive a la sesión | `engine/bridge.py:764-767` | **[V]** |

**[H2] enunciada:** el identificador no verificado no produce el 400; produce **la ausencia de metadatos de límites**, que a su vez desactiva los guardas de [H1] pasos 5-7. Es decir: **P0-A sigue siendo el paquete correcto, pero su cambio obligatorio es el guarda de capacidad, no el rechazo de identificadores** (que ya existe y está probado).

**Comprobación aritmética reproducible [V, no concluyente]:** `LEEME_V8.txt:73` declara que 77.120 tokens era el máximo de salida de un plan anterior. Con `effective_cap = 15424` resultan `(15424 − 1024) // 2400 = 6` perfiles por lote y `15424 × 5 = 77120` tokens. La aritmética del motor **reproduce esa cifra exactamente**, lo que es compatible con `per_batch = 6` y `request_count = 5`. Se registra como consistencia, **no como prueba**, porque el plan exacto de aquel intento no está en el paquete.

### 2.5 Estado verificado de la premisa "el fallo ocurrió en api_design" [V]

`api_design` es la etapa que se fija **inmediatamente antes de entrar al transporte**, en el mismo acto en que se consume el consentimiento y se marca facturación potencial:

`engine/generation_pipeline.py:548-549` → `stage='api_design'`, `confirmation_consumed=True`, `potentially_billed=True`, `sent_requests=None`, `receipts_pending=True`.

Esto es coherente tanto con [H1] como con la premisa [O], y por sí solo **no discrimina** entre ambas.

### 2.6 Traza residual del incidente que sí existe en el paquete [V]

| Artefacto | Contenido | Lectura correcta |
|---|---|---|
| `data/projects/98d8ec4f-4ada-44a2-98a2-27eb1370519a/versions/20261007T194223292343Z-6c5b1c17.json:19` | `"model": "DeepSeek-V41-Flash"` | Un identificador no verificado quedó guardado en la configuración de un proyecto |
| `…/20261008T045234518426Z-d3c1f33e.json:23` y ~60 ocurrencias más | `"model": "DeepSeek-V41-Flash"` en config, perfiles y overrides | El valor se propagó a todo el diseño |
| `…/20261007T195458822111Z-aa55abe3.json:19128-19160` | `"valid": false` y 30 errores `"Modelo no disponible: <rol>: deepseek-official/DeepSeek-V41-Flash"` | **Otro** fallo, distinto del de la imagen: una ruta DSH inexistente invalidó la organización completa |
| `engine/bridge.py:883` | `structural = [e for e in validation['errors'] if not e.startswith('Modelo no disponible:')]` | El código ya distingue este error como no estructural al cargar |

**Advertencia de no-sobreinterpretación:** estos archivos son de un proyecto generado **de forma determinista y local** (`engine/bridge.py:1216`, `source='local_deterministic'`), sin llamada a proveedor. **No documentan el intento fallido de IA.** Cualquier lectura que los presente como el recibo del incidente sería falsa.

---

## 3. Matriz de los cuatro paquetes

Estado medido contra el código presente (V8), no contra V7.

| Paquete | Objetivo del encargo | Estado real verificado | Hueco residual que este plan cierra | Riesgo dominante | Archivos autorizados |
|---|---|---|---|---|---|
| **P0-A** Model discovery y validación de request | Evitar display names, IDs manuales y combinaciones incompatibles | **Parcial-alto.** `GET /models` implementado (`engine/providers.py:374-405`); validación en plan y confirmación (`engine/bridge.py:804-832`; `engine/generation_pipeline.py:363,544`); sellado por cuenta (`:764-767`); límites aplicados si existen (`engine/org_design.py:297-316`); `response_format` por proveedor (`:505-507`) | **`limits_reported == False` no bloquea ni adapta.** Catálogo sin TTL ni caducidad. Catálogo guardado se invalida duro, sin ruta offline declarada. Sin enum `catalog_source: live\|cached\|manual-unverified` | **Alto:** es el paquete que toca el camino que produjo el fallo | `engine/providers.py`, `engine/bridge.py`, `engine/org_design.py`, `engine/generation_pipeline.py`, `web/app.js` |
| **P0-B** Receipt ledger y recuperación | No perder diagnóstico ni usage de intentos fallidos | **Parcial-medio.** Frontera tipada y allowlist (`engine/generation_pipeline.py:24-57`); usage nunca 0 inventado (`:60-66`); recibos tardíos tras cancelación (`:715-734`); extracción HTTP acotada sin cuerpo (`engine/providers.py:94-116`); diagnóstico descargable (`engine/bridge.py:673-702`) | **Ledger durable inexistente:** los recibos viven en memoria y sólo persisten al guardar proyecto o descargar diagnóstico (`LEEME_V8.txt:53-56`). Esquema sin `attempt`, `idempotency_key`, `result_outcome`, `started_at/finished_at` por recibo, ni `schema_version` | **Medio:** pérdida de evidencia, no de dinero | `engine/generation_pipeline.py`, `engine/org_design.py`, `engine/bridge.py`, `engine/project_store.py`, `web/app.js` |
| **P1-A** Evidence planner arquitectónico | Inventario priorizado, fragmentos, packs por rol, métricas | **Parcial-medio.** Prioridad por subsistema (`engine/providers.py:443-483`); diversidad familia/módulo (`:541-579`); reemplazo dentro del presupuesto (`:918-941`); huecos explícitos (`:950-969`); packs común+dirigido (`engine/org_design.py:398-444`); métricas de duplicación (`:534-537`) | **Archivos > 40 KB siguen siendo huecos** (`engine/providers.py:32,911-912,955-956`). Sin grafo de dependencias ni centralidad real: la selección es heurística de rutas, declarada como tal (`:544`; `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:29`) | **Bajo-medio:** degrada calidad del ADN, no corre riesgo | `engine/providers.py`, `engine/org_design.py`, `web/app.js` |
| **P1-B** Agent Teams gobernados y export compatible | TaskSpec, autonomía, políticas, export, hashes | **Parcial-bajo.** Autonomía con presets y preflight (`engine/autonomy.py:30-50,113-227`); export versionado (`engine/export_artifacts.py:124`); bundle y validación (`engine/bundle.py`); CAS y recibo de publicación (`engine/capability_deployment.py:303-373`); verificación de hashes en el relanzador (`engine/dsh_launcher.py:488-493`) | **`TaskSpec` no existe** (búsqueda sin coincidencias). No hay estados `observe/propose/prepare/execute-approved`. Sin verificación de hash en el arranque `launch.cmd` | **Bajo:** alcance de exportación | `engine/autonomy.py`, `engine/export_artifacts.py`, `engine/bundle.py`, `engine/capability_deployment.py`, `launch.cmd`, `web/app.js` |

**Regla de secuencia conservada:** P0-A → P0-B → P1-A → P1-B. P0-A primero porque gobierna el envío; P0-B segundo porque sin recibo durable no hay verificación posible de que P0-A funcionó.

---

## 4. Mapa archivo por archivo

Formato: **archivo · función/clase · cambio requerido · motivo · riesgo · test asociado.**
Los identificadores de cambio (`A1`, `B2`, …) se usan en las secciones 10 y 12.

### 4.1 P0-A — Model discovery y validación de request

| # | Archivo · función/clase | Cambio requerido | Motivo | Riesgo | Test asociado |
|---|---|---|---|---|---|
| **A1** | `engine/org_design.py` · `_plan` (447-549), líneas 469 y 491 | Introducir **holgura obligatoria** en el cálculo del lote: aplicar un factor de seguridad declarado sobre `PROFILE_TOKEN_BUDGET`, y fijar `cap = effective_cap` (no `1024 + 2400·n`) siempre que el plan vaya a consumir el presupuesto completo | [H1]: el presupuesto se consume exactamente y un perfil real de >2400 tokens trunca el lote. Corrección focalizada y reversible | **Medio:** lotes más pequeños ⇒ más solicitudes ⇒ más peticiones HTTP (no más coste garantizado). Debe respetar `MAX_REQUESTS = 16` (`:25`) o fallar con `request_budget_exceeded` ya existente (`:64`) | `tests_org_design.py:101` (plan exacto de slots y presupuestos); `tests_generation_robustness_v7.py:127` (`test_explicit_batch_has_output_headroom_and_frozen_approval`) — **extender a la ruta automática**, que es la no cubierta |
| **A2** | `engine/org_design.py` · `_model_limits` (297-316) y `_plan` (545-546) | Convertir `limits_reported == False` en **condición de bloqueo o de reducción forzada**, no en advertencia. Propuesta: sin límites reportados, exigir `profiles_per_request` explícito y conservador, o rechazar con código nuevo `unverified_limits_requires_explicit_batch` | [H2]: el guarda de contexto sólo opera si `context_window` existe (`:512-513`); sin límites, el plan es optimista y silencioso | **Medio:** puede bloquear envíos que hoy funcionan. Mitigación: mensaje accionable + ruta explícita de desbloqueo informado (mismo patrón que `partial_inventory_acknowledged`, `engine/generation_pipeline.py:535-538`) | Nuevo: `test_no_reported_limits_blocks_automatic_batch`, con falsificador en sección 10 |
| **A3** | `engine/providers.py` · `discover_models` (374-405), `_clean_model` (357-371) | Añadir al retorno **`catalog_sha256`** (hash canónico de la lista de ids ordenada), **`fetched_at`** y **`expires_at`** calculados desde una política TTL explícita por fuente | El encargo exige cache con timestamp, TTL, fuente y hash. Hoy sólo existe `verified_at` (`:401`), sin caducidad ni hash | **Bajo:** campos aditivos; `_coverage_view` y consumidores no se alteran | `tests_providers.py:104` (`test_live_discovery_preserves_real_ids_and_metadata`); nuevo `test_catalog_hash_and_ttl_are_deterministic` |
| **A4** | `engine/bridge.py` · `execute` caso `discover-models` (1217-1253) y `load_project` (890-894) | Conservar procedencia y caducidad por fila: añadir `catalog_source ∈ {live, cached, manual-unverified}`, `expires_at` y `catalog_sha256`. Al cargar proyecto, **no degradar a ciegas**: marcar `cached` con su `expires_at` en lugar de `UNVERIFIED_SAVED_PROJECT` | Permite trabajo offline declarado sin debilitar la regla de envío. El encargo lo exige explícitamente | **Alto si se hace mal:** un catálogo cacheado que autorice un envío rompería la garantía de verificación por cuenta. **Regla dura: `cached` NUNCA satisface `validate_api_model_choice`** | `tests_v8_models_receipts.py:92` (`test_catalog_from_another_key_or_alias_account_cannot_verify_current_account`), `:86`, `:102`, `:122` — **deben seguir PASS sin modificación** (son el candado) |
| **A5** | `engine/bridge.py` · `validate_api_model_choice` (804-832) | Mantener la semántica actual y **añadir** el caso explícito "proveedor sin modelos compatibles": si el catálogo de cuenta se consultó y ninguna fila sirve, devolver razón específica en lugar del mensaje genérico de `:832` | El encargo pide prueba de "provider sin modelos compatibles". Hoy el caso cae en el mensaje genérico | **Bajo:** sólo enriquece el diagnóstico | Nuevo: `test_consulted_catalog_without_compatible_model_gives_specific_reason` |
| **A6** | `engine/generation_pipeline.py` · `plan` (363) y `confirm` (544) | Sin cambio de lógica. **Añadir** que el manifest sellado incluya `model_selection` completo (`model_id`, `display_name`, `catalog_source`, `catalog_sha256`, `expires_at`) | El encargo exige manifest inmutable con separación ID/nombre y procedencia | **Bajo:** aditivo; `_saved_job` debe aceptar los campos nuevos | `tests_v8_models_receipts.py:147` (`test_account_changed_after_plan_requires_new_plan_without_paid_send`) — preservar |
| **A7** | `engine/org_design.py` · `JSON_MODE_SOURCES` (33-37) y `_plan` (505-507) | Documentar y acotar: la compatibilidad de `response_mode` se decide por **mapa estático**, no por capacidad declarada por el catálogo. Si el catálogo reporta `output_modalities` incompatibles, bloquear antes del envío | El encargo pide "validación de response_mode y límites contra la capacidad del modelo". Hoy la mitad estática existe, la parte de capacidad no | **Bajo-medio:** un bloqueo mal calibrado impide el modo texto legítimo | `tests_org_design.py:343` (`test_zai_and_custom_preserve_exact_routes`); nuevo `test_output_modalities_incompatible_blocks_before_send` |
| **A8** | `web/app.js` · 59, 221, 229, 236-240, 266, 519 | Mostrar `catalog_source`, `expires_at` y "límites no reportados" con la etiqueta honesta ya existente (`generationVerificationLabel`, `:519`). Sin afirmar capacidad | El encargo exige que UI y motor no diverjan, y que `manual-unverified` sea visible como tal | **Bajo** | `tests_v8_ui_contract.py:25,34,48` |

### 4.2 P0-B — Request receipt ledger y recuperación

| # | Archivo · función/clase | Cambio requerido | Motivo | Riesgo | Test asociado |
|---|---|---|---|---|---|
| **B1** | `engine/generation_pipeline.py` · `safe_request_receipts` (24-57) | **Versionar y ampliar el esquema** del recibo: `schema_version`, `attempt`, `idempotency_key`, `result_outcome ∈ {success, rejected, timeout_unknown, cancelled, transport_failure}`, `billing_outcome ∈ {known, unknown, not_applicable}`, `started_at`, `finished_at`, `provider_request_id_sha256` | El encargo enumera estos campos. Hoy faltan todos salvo `http_status`, `error_code`, `usage`, `latency_ms`, `response_id_sha256` (`:48-56`) | **Medio:** `_saved_job` (`:186`) y `load_saved` (`:221-231`) validan estrictamente; un campo nuevo mal tipado rompe la carga de proyectos existentes | `tests_v8_models_receipts.py:19,37,213,227,238,265,279`; `tests_generation_robustness_v7.py:151` (`test_diagnostic_attributes_are_revalidated_not_copied`) |
| **B2** | `engine/generation_pipeline.py` · `_capture_receipts` (126-137) y `_fail` (715-803) | Persistir el recibo **en el momento de crearse**, no sólo al guardar. Requiere el ledger de B3 | `LEEME_V8.txt:53-56`: "un cierre abrupto puede perderlos. No es un ledger inmutable ni un registro durable automático" | **Alto:** escritura en disco en el camino de fallo. Debe ser best-effort y no enmascarar la excepción original | `tests_v8_models_receipts.py:187` (`test_success_receipts_survive_save_load_and_diagnostic`) — **extender** a "sobrevive a cierre sin guardar" |
| **B3** | **Nuevo destino de persistencia** (ver Anexo A-1) · p. ej. `data/ledger/generation-<año>.jsonl` con escritura `append` + `fsync` | Ledger append-only, una línea JSON por recibo, con hash de encadenamiento | El encargo exige ledger durable antes de cada envío y recuperación de job interrumpido | **Alto:** nueva superficie de disco y de privacidad. **Requiere autorización explícita**, no se asume | Nuevo: `test_ledger_survives_process_kill`, `test_ledger_contains_no_secret` |
| **B4** | `engine/providers.py` · `_http_failure` (102-116), `HTTP_ERROR_CODES` (94-97), `HTTP_ERROR_PARAMETERS` (98-99) | **Sin cambio de política.** Documentar como invariante que el cuerpo remoto no se conserva y que sólo se extraen `code` y `param` allowlisteados | El encargo pide "mensaje de error sanitizado". La suite eligió **no** guardar cuerpo: es una decisión de privacidad válida y debe declararse, no revertirse | **Bajo** si no se toca; **crítico** si alguien "mejora" guardando el body | `tests_repository_inventory.py:71`; `tests_v8_evidence.py:244` (`test_http_receipt_retains_only_allowlisted_error_metadata`) |
| **B5** | `engine/org_design.py` · `_diagnostic` (85-116), `_FAILURES` (42-73) | Añadir clasificación de reintento **derivada**, no ejecutada: `retry_class ∈ {deterministic_reject, auth, rate_limit, provider_transient, unknown_outcome, cancelled}` | El encargo exige diferenciar 400/401/403/429/5xx/timeout/cancelación. Hoy hay categorías (`:100-115`) pero no una clase de reintento consumible por UI y política | **Bajo:** campo derivado de datos ya allowlisteados | `tests_generation_robustness_v7.py:32`; nuevo `test_retry_class_mapping_is_total` |
| **B6** | `engine/bridge.py` · `generation_diagnostic` (673-702) | Incluir los campos nuevos de B1 y la clase de B5, manteniendo `privacy` explícito | El diagnóstico es el único artefacto que el operador puede entregar para auditoría | **Bajo** | `tests_generation_diagnostics.py`; `tests_v8_ui_contract.py:53` |
| **B7** | `web/app.js` · `renderGenerationUsage` (526-535), `generationSafeReceipts` (522-525), 531, 558, 569 | Mostrar `result_outcome`, `billing_outcome`, `attempt` y la clase de reintento. Conservar la regla "No informado ≠ 0 ≠ gratis" | El encargo pide vista UI "estimado / real / desconocido" — ya existe parcialmente (`:494-502`, `:526-535`); falta la clasificación y el `attempt` | **Bajo** | `tests_v8_ui_contract.py:42,48,53`; `tests_v8_ui_dom.js` |
| **B8** | `engine/project_store.py` · `FORBIDDEN_FIELDS` (19), `_reject_secret_fields` (38-46) | Sin cambio. **Verificar** que ningún campo nuevo de B1/B3 pueda portar credenciales y que el ledger de B3 aplique la misma lista | El ledger es la nueva superficie donde un secreto podría filtrarse | **Bajo si se reutiliza**, alto si se reimplementa | Nuevo: `test_ledger_rejects_secret_fields` reutilizando `_reject_secret_fields` |

### 4.3 P1-A — Evidence planner arquitectónico

| # | Archivo · función/clase | Cambio requerido | Motivo | Riesgo | Test asociado |
|---|---|---|---|---|---|
| **C1** | `engine/providers.py` · `MAX_FILE_BYTES` (32), `analyze_repository` (894-914, 955-956), `_fetch_repo_file` (801-833) | **Lectura fragmentada dirigida** para archivos > 40 KB: cabecera, imports/exports, definiciones públicas, handlers y tests asociados, mediante el `sha` ya conocido del blob. Sustituir la declaración de hueco (`:956`) por evidencia parcial **etiquetada como parcial** | El encargo lo pide y `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:30` lo declara no implementado | **Alto:** toca presupuesto de bytes/red y la semántica de `coverage`. Requiere autorización (Anexo A-2) | `tests_v8_evidence.py:124` (`test_oversize_is_a_gap_not_a_fragment_claim`) — **cambia de semántica: debe actualizarse de forma explícita, no silenciosa** |
| **C2** | `engine/providers.py` · `_file_family` (497-521), `_module` (522-530), `_priority` (466-484), `_RUNTIME_DIRS` (443), `_FAMILY_ORDER` (538) | **Sin cambio de mecanismo** (la heurística de rutas se conserva). Añadir un `repo_map` derivado y explícito con los subsistemas que el encargo enumera, marcando cada uno como *observado / no observado* | El encargo pide `repo_map` con frontend, edge, backend/api-server, etc. Hoy la información existe dispersa en `families`/`modules` (`:942-948`) pero no como mapa declarado | **Bajo:** vista derivada, no nueva lógica | `tests_v8_evidence.py:67,84` |
| **C3** | `engine/org_design.py` · `_evidence_packages` (398-444) y `_plan` (534-537) | **Sin cambio estructural** (el reparto común+dirigido ya existe). Exponer en el manifest las métricas de C2 y declarar `heuristic_only: true` ya presente | El encargo pide medir bytes compartidos/específicos, duplicación y cobertura por perfil: `sent_file_occurrences` y `full_repeat_file_occurrences` (`:535-536`) ya lo hacen | **Bajo** | `tests_v8_evidence.py:148` (`test_thirty_slots_directed_packages_exact_caps_and_complete_read_ledger`) |
| **C4** | `engine/providers.py` · `_diverse_plan` (541-579) | Añadir **sustitución de referencias irrelevantes** ya cubierta (`:938-941`) y un umbral de diversidad medido por familia+módulo, reutilizando `_FAMILY_ORDER` | El encargo pide ranking por centralidad. La centralidad real requiere grafo (C5) | **Bajo** | `tests_v8_evidence.py:84,105,112` |
| **C5** | **Grafo de dependencias/AST** | **NO IMPLEMENTAR en este plan.** Se registra como dependencia nueva no autorizada (Anexo A-3) porque exigiría parsers por lenguaje y una dependencia externa, prohibida por el encargo | Honestidad de alcance: confundir heurística de rutas con análisis AST es exactamente el error que el encargo prohíbe | **N/A** | `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:29,40-41` |
| **C6** | `web/app.js` · `renderGenerationEvidence` (541-556) | Mostrar el `repo_map` de C2 y los huecos con su razón, conservando el texto ya honesto de `:543-544` | El encargo exige informar cobertura sin presentarla como conocimiento total | **Bajo** | `tests_v8_ui_contract.py:70` (`test_evidence_is_path_specific_and_never_claims_semantic_completeness`) |

### 4.4 P1-B — Agent Teams gobernados y exportación compatible

| # | Archivo · función/clase | Cambio requerido | Motivo | Riesgo | Test asociado |
|---|---|---|---|---|---|
| **D1** | `engine/export_artifacts.py` · `_manifest` (109-146), `PRIVATE_RUNTIME_KEYS` (28-39) | **`TaskSpec` canónico y versionado** como documento de exportación: `taskspec_version`, `task_id`, `subject`, `owner_agent_id`, `autonomy_state`, `tool_policy`, `evidence_refs`, `acceptance`, `dependencies` | El encargo lo pide y **hoy no existe** en el árbol. Ubicarlo en el export evita crear módulo nuevo | **Medio:** toca el manifest exportado ⇒ obligación de retrocompatibilidad (versión nueva, lectura de v1) | `tests_capability_exports.py:23,31,45,83`; `tests_frontend_contract.py:44` |
| **D2** | `engine/autonomy.py` · `normalize_autonomy_config` (30-50), `build_autonomy` (113-227) | Añadir los cuatro estados **`observe / propose / prepare / execute-approved`** como campo de diseño por tarea, mapeados sobre los presets existentes (`PRESETS`, `:11`) sin sustituirlos. Por defecto `observe` | El encargo exige cuatro niveles con `observe`/`propose` por defecto. Hoy existen tres presets de equipo, no cuatro niveles por tarea | **Medio:** `validate_autonomy` (`:230-242`) compara igualdad estricta con `build_autonomy`; cualquier campo nuevo obliga a prever compatibilidad de snapshots previos (ya hay precedente en `:234-241`) | `tests_org_design.py:334` (`test_autonomy_is_reviewed_design_data_never_runtime_authority`); nuevo `test_legacy_autonomy_snapshot_still_validates` |
| **D3** | `engine/autonomy.py` · limitaciones (184-197) y `engine/tool_permissions.py` (124-125) | Políticas de herramientas **por tarea** derivadas del mismo catálogo, con `catalog_source: user_supplied_catalog` conservado y sin conceder permisos | El encargo pide políticas de herramientas por tarea. Hoy son por perfil | **Bajo-medio:** riesgo de que se lea como concesión. Debe declararse propuesta, como ya hace `build_autonomy` (`runtime_verified: False`, `:227`) | `tests_integration_tools.py:98,158`; `tests_org_design.py:334` |
| **D4** | `engine/bundle.py` · `build_package_bytes` / `validate_bundle` (según `engine/generation_pipeline.py:658-661`) | Incluir `taskspec` en el paquete y **verificar su hash** en la validación final | El encargo pide export bundle compatible y verificación de hashes | **Medio:** `validate_bundle` es la última puerta; un documento nuevo debe entrar en su lista de verificación | `tests_capability_exports.py:83` (`test_bundle_roundtrip_accepts_companion`) |
| **D5** | `launch.cmd` (24 líneas) y `relanzador_dsh/PROVENANCE.json` | Añadir **verificación de hash previa a la ejecución** del relanzador, reutilizando el patrón ya probado en `engine/dsh_launcher.py:488-493` y `engine/capability_deployment.py:130-149`. Si el hash no coincide: **abortar**, no continuar | El encargo pide "verificación de hashes antes de instalar/actualizar" y prohíbe instalaciones autónomas. `launch.cmd` hoy sólo comprueba la versión de Python (`:6,14`) | **Medio:** un fallo del verificador bloquearía el arranque. Mitigación: modo degradado explícito, nunca silencioso | Nuevo: `test_launcher_hash_mismatch_aborts`; `tests_launcher.py` |
| **D6** | `engine/generation_pipeline.py` · `plan` (345-352) | **Sin cambio.** Documentar la idempotencia **local** y su no equivalencia con la del proveedor | El encargo lo exige como regla. La suite ya distingue: `keys[key]` local (`:345,408`) sin cabecera de idempotencia hacia el proveedor | **Bajo** | `tests_generation_robustness_v7.py:203` (`test_real_facade_accepts_generation_options_and_idempotency_binds_them`) |
| **D7** | `engine/project_store.py` · `_save` (99-141) | **Sin cambio.** Confirmar que la reanudación idempotente se apoya en `expected_version` (`:107-110`) | El encargo pide reanudación idempotente; ya existe control optimista de versión | **Bajo** | `tests_evaluation_runs.py:77` (`test_doubleclick_idempotent`) |

---

## 5. Esquemas de datos

Todos los esquemas son **aditivos** y versionados. `_actual` indica el campo ya existente del que provienen.

### 5.1 `ModelCatalogEntry`

```json
{
  "schema_version": 1,
  "provider": "deepseek",
  "model_id": "deepseek-flash",
  "display_name": "DeepSeek-V4.1-Flash",
  "catalog_source": "live",
  "catalog_scope": "provider_api",
  "catalog_sha256": "hex64",
  "fetched_at": "2026-10-10T10:40:45Z",
  "expires_at": "2026-10-11T10:40:45Z",
  "available": true,
  "availability_verified": true,
  "capabilities_verified": false,
  "limits_reported": true,
  "context_window": 1048576,
  "max_output_tokens": 393216,
  "output_modalities": ["text"],
  "account_binding": "ephemeral_hmac_not_exported"
}
```
`_actual`: `id`, `name`, `source`, `status`, `checked_at`, `available`, `availability_verified`, `context_window`, `max_output_tokens`, `input_modalities`, `output_modalities` (`engine/providers.py:357-371`; `engine/bridge.py:1227-1230`).
**Regla dura:** `catalog_source ∈ {cached, manual-unverified}` ⇒ **prohibido** satisfacer `validate_api_model_choice` para un envío (`engine/bridge.py:811-814`).

### 5.2 `ModelSelection`

```json
{
  "schema_version": 1,
  "model_id": "deepseek-flash",
  "display_name": "DeepSeek-V4.1-Flash",
  "catalog_source": "live",
  "catalog_sha256": "hex64",
  "catalog_expires_at": "2026-10-11T10:40:45Z",
  "verification_status": "catalog_verified",
  "account_verified": true,
  "capabilities_verified": false,
  "limits_used": {"context_window": 1048576, "max_output_tokens": 393216, "limits_reported": true}
}
```
`_actual`: `{'status': 'catalog_verified'|'inference_verified'|'manual_documented', 'account_verified', 'capabilities_verified'}` (`engine/bridge.py:819-831`).

### 5.3 `RequestManifest`

Ya existe casi completo y **no debe rediseñarse**: `engine/org_design.py:523-546`. Se añade lo que el encargo exige y hoy falta.

```json
{
  "schema_version": "org-design-1.0",
  "provider": "deepseek",
  "endpoint": "https://api.deepseek.com/chat/completions",
  "model_selection": { "...": "ver 5.2" },
  "response_mode": "json_object",
  "max_output_tokens": 15424,
  "effective_max_output_tokens": 15424,
  "profiles_per_request": null,
  "effective_profiles_per_request": 6,
  "max_requests": 5,
  "request_limit": 16,
  "request_timeout_seconds": 300,
  "request_hashes": ["hex64"],
  "payload_sha256": "hex64",
  "source_ref": {"sha": "…", "tree_sha": "…", "url": "…"},
  "evidence_hashes": ["hex64"],
  "evidence_distribution": {"strategy": "common_plus_subsystem_directed_v1", "heuristic_only": true,
                            "sent_file_occurrences": 0, "full_repeat_file_occurrences": 0},
  "budget": {"type": "bounded_batch_requests_and_output_tokens_not_currency_cap", "cost": "unknown"},
  "idempotency_key": "<local>",
  "created_at": "2026-10-10T10:40:45Z",
  "limits_reported": false,
  "limits_warning": "El proveedor no ha reportado límites de contexto/salida; …",
  "approval": {"approval_id": "<token>", "config_version": 7, "coverage_sha256": "hex64",
               "partial_inventory_required": true, "consumed": false}
}
```
**Invariante exigida por el encargo:** tras confirmar, el request enviado se deriva **exclusivamente** de este manifest. Ya se cumple por comparación estructural: `engine/org_design.py:755-762` verifica campo por campo contra el plan recalculado y lanza `ConsentRequired` ante cualquier divergencia.

### 5.4 `RequestReceipt`

```json
{
  "schema_version": 2,
  "receipt_id": "uuid",
  "index": 1,
  "attempt": 1,
  "job_id": "<job>",
  "idempotency_key": "<local>",
  "provider": "deepseek",
  "endpoint": "https://api.deepseek.com/chat/completions",
  "model_id_sent": "deepseek-flash",
  "display_name_at_plan_time": "DeepSeek-V4.1-Flash",
  "catalog_provenance": {"catalog_source": "live", "catalog_sha256": "hex64", "fetched_at": "…"},
  "payload_sha256": "hex64",
  "max_output_tokens": 15424,
  "http_status": 200,
  "provider_request_id_sha256": "hex64",
  "provider_error_code": null,
  "sanitized_error_message": null,
  "usage": {"prompt_tokens": null, "completion_tokens": null, "total_tokens": null},
  "billing_outcome": "unknown",
  "result_outcome": "rejected",
  "latency_ms": 41230,
  "started_at": "2026-10-10T10:41:02Z",
  "finished_at": "2026-10-10T10:41:43Z"
}
```
`_actual` v1: `index`, `provider`, `model`, `payload_sha256`, `max_output_tokens`, `status`, `usage{prompt,completion,total}`, `latency_ms`, `http_status`, `error_code`, `response_id_sha256` (`engine/generation_pipeline.py:48-56`).
**Reglas duras conservadas:** `usage` ausente ⇒ `null`, jamás `0` (`:52,60-66`); error remoto ⇒ sólo `code`/`param` allowlisteados (`engine/providers.py:102-116`); prohibido guardar claves, cabeceras `Authorization`, prompts con credenciales o cuerpos sin sanitizar (`engine/project_store.py:19`; `engine/bridge.py:700-701`).

### 5.5 `TaskSpec`

```json
{
  "taskspec_version": 1,
  "organization_id": "uuid",
  "tasks": [{
    "task_id": "T-01",
    "subject": "…",
    "owner_agent_id": "P02_DOMAIN",
    "autonomy_state": "observe",
    "tool_policy": {"derived_from": "user_supplied_catalog", "allowed": [], "denied": [], "granted": false},
    "evidence_refs": ["path/o/url"],
    "acceptance": ["criterio verificable"],
    "dependencies": [],
    "push_or_deploy": false,
    "state": "PROPOSED_NOT_EXECUTED"
  }]
}
```
**Estado actual: no existe.** Búsqueda de `TaskSpec|task_spec|taskspec` en todo el árbol: **sin coincidencias**. Es el hueco más grande de P1-B.

### 5.6 `EvidencePack`

```json
{
  "schema_version": 1,
  "strategy": "common_plus_subsystem_directed_v1",
  "batch_index": 1,
  "slots": [1,2,3,4,5,6],
  "common_paths": ["package.json"],
  "targeted_paths": ["backend/api-server/src/routes.ts"],
  "omitted_read_paths": ["frontend/app.tsx"],
  "ledger": [{"path": "…", "sha": "…", "content_sha256": "…", "bytes": 1234,
              "read_source": "github_blob", "family": "backend", "module": "backend/api-server"}],
  "duplication_metrics": {"unique_read_paths": 18, "sent_file_occurrences": 30,
                          "full_repeat_file_occurrences": 90, "omitted_from_all_batches": []},
  "heuristic_only": true,
  "coverage_delta": {"reason": "over_40kb_gap", "path": "…", "bytes": 918273}
}
```
`_actual`: `engine/org_design.py:432-443` (ledger, `strategy`, `common_paths`, `targeted_paths`, `omitted_read_paths`) y `:534-537` (métricas).

---

## 6. Diagramas ASCII

### 6.1 prepare → validate → approve → send → receipt → recover

```
 UI (web/app.js)                Bridge (bridge.py)                  Motor (org_design.py)          Proveedor
 ───────────────                ───────────────────                 ──────────────────────         ─────────
 [Consultar catálogo] ──────► execute('discover-models') 1217
                               discover_models() providers:374 ────► GET /models ───────────────► [HTTP]
                               sella por cuenta :764-767  ◄─────────  {id,name,limits?}
                               validate_api_model_choice :804
                                 ├─ sin verificación ⇒ BridgeError :832  ╳ (no se prepara envío)
                                 └─ verificado ⇒ status catalog_verified :819
                                          │
 [Preparar ADN] ────────────► generation-plan :271
                               validate_api_model_choice(363)
                               prepare_design_consent ─────────────► _plan :447
                                                                      _model_limits :297
                                                                        └ limits_reported? :314
                                                                      per_batch :469  cap :491
                                                                      manifest :523  consent :531
                               pending_consent ◄──────────────────── consent
 [Revisar + 3 casillas] ────► generation-confirm :513
                               revalida sello de cuenta :542
                               revalida modelo :544
                               verifica manifest campo a campo (755-762)
                               confirmation_consumed=true
                               potentially_billed=true
                               stage=api_design :548
                                          │
                                          ▼
                               design_with_llm :743 ──────────────► bucle de lotes :794
                                                                      _response :641
                                                                        finish_reason :646-648
                                                                          ├ "stop"    ⇒ valida esquema
                                                                          └ "length"  ⇒ output_truncated ╳
                               _capture_receipts :126 ◄─────────────  audit.receipts :770
                               usage_summary :60 (null ≠ 0)
                                          │
                    ┌─────────────────────┴──────────────────────┐
                    ▼                                            ▼
             success: commit único :675-706            fail: _fail :715-803
             (dos JSON + ZIP validados)                 ├ consentimiento NO se devuelve
                                                        ├ recibo tardío tras cancelar :724-734
                                                        └ retry_requires_new_consent :215
                                          │
 [Descargar diagnóstico] ───► generation_diagnostic :673  ──►  orgdna-generation-diagnostic-<job>.json (:1412)
 [Guardar proyecto] ────────► ProjectStore.save :95-141 (SHA-256 por versión, sin credenciales)
```

### 6.2 Evidencia → packs → perfiles → validación

```
GitHub API (SHA fijado, sólo lectura)
  │  repository_metadata → commit_resolution → commit_metadata          providers:870-886
  ▼
Árbol inmutable (tree_sha) ──► _repository_inventory :659 / caché :779
  │   MAX_TREE_ENTRIES 5000 · MAX_TREE_REQUESTS 24 · MAX_TREE_BYTES 12MB · MAX_TREE_DEPTH 16
  ▼
Clasificación por rutas (heurística declarada :544)
  _safe_path :432  _auxiliary_path :447  _file_family :497  _module :522  _priority :466
  │
  ├── excluidos: sensibles/generados · symlink/submódulo · no UTF-8 · > MAX_FILE_BYTES 40000 (:32)
  │        └──► HUECO EXPLÍCITO :955-956   ◄── C1 lo convierte en lectura fragmentada
  ▼
_diverse_plan :541  (tier auxiliar último; familia → módulo → round-robin)
  ▼
Lectura acotada + reemplazo dentro del presupuesto existente :918-941
  ▼
coverage { families, modules, gaps, budget } :970-987      ◄── C2 añade repo_map declarado
  ▼
prepare_summary → _slot_map :350 → _evidence_packages :398
  │        común ≤ 2 archivos ≤ 12 000 B (:412-418)
  │        dirigido por módulo del slot (:419)
  │        resto repartido al lote más ligero (:423-431)
  ▼
Lote i = DESIGN_CONTROL + UNTRUSTED_PROJECT_CONFIG + UNTRUSTED_PROJECT_DATA :494-496
  ▼
Proveedor ──► _response :641 ──► _validate_profile_shape :558 ──► _unique :699
  │                                    │
  │                                    └── evidence_paths ⊆ evidencia DEL LOTE :675  (no del global)
  ▼
profile_specs (N exactos) ──► core.generate_organization ──► validate_organization :648-650
  ▼
Dos JSON nativos + ZIP validados ──► commit único :675-706
```

### 6.3 Máquina de estados del request

```
                        ┌──────────────┐
                        │   planned    │  job creado, idempotency_key registrada (:382-408)
                        └──────┬───────┘
                               │ inventory + prepare_design_consent
                               ▼
                     ┌───────────────────┐
                     │ awaiting_consent  │  stage=review · consentimiento NO consumido
                     └────┬─────────┬────┘
        cancelar/abandonar│         │ confirm: 3 casillas + approval_id + payload_sha256
                          │         │ + config_version + coverage_sha256 si inventario parcial (:530-538)
                          ▼         ▼
                   ┌──────────┐  ┌─────────┐   confirmation_consumed = true
                   │cancelled │  │ running │   potentially_billed = true
                   └──────────┘  │ stage=  │   receipts_pending = true
                                 │api_design│  ⚠ A PARTIR DE AQUÍ PUEDE HABER CARGO
                                 └────┬────┘
                    ┌─────────────────┼──────────────────┬─────────────────┐
                    ▼                 ▼                  ▼                 ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐
            │  validando   │  │   fallo      │  │ cancelado    │  │ timeout/       │
            │  perfiles    │  │ determinista │  │ en vuelo     │  │ transporte     │
            └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────┬───────┘
                   ▼                 ▼                 ▼                   ▼
            ┌──────────────┐  result_outcome:   result_outcome:    result_outcome:
            │  completed   │  rejected           cancelled          timeout_unknown
            │  (artefactos │  billing: unknown   billing: unknown   billing: unknown
            │   + recibos) │                     (recibo tardío     (NO se reenvía solo:
            └──────────────┘                      retenido :724-734)  sólo hay idempotencia LOCAL)
                    │
                    └──► terminal. Cualquier intento nuevo exige plan y consentimiento nuevos (:215).
                         En NINGÚN estado terminal se devuelve ni se renueva el consentimiento.
```

---

## 7. Política de reintento por código de error

**Principio rector verificado en el código:** la suite **no reintenta automáticamente ningún envío pagado** en ningún caso (`engine/generation_pipeline.py:1-5,551,585`; `LEEME_V8.txt:50-51`). Este plan **no cambia ese principio**: sólo añade **clasificación** para que la UI y el operador decidan con información.

| Condición | Clase derivada (B5) | Acción automática | Acción humana exigida | Evidencia |
|---|---|---|---|---|
| HTTP 400 determinista | `deterministic_reject` | **Ninguna.** No rotar clave, no cambiar de proveedor | Reparar request/modelo/`response_mode` y **preparar plan nuevo** | `engine/org_design.py:71,100-103`; `engine/providers.py:94-99` |
| `unsupported_parameter` / `unsupported_value` / `invalid_parameter` | `deterministic_reject` | Ninguna | Revisar el parámetro señalado (`param` allowlisteado). Si es `response_format`, elegir modo Texto explícitamente | `engine/providers.py:98-99`; `engine/org_design.py:72` |
| `context_length_exceeded` | `deterministic_reject` (categoría `configuration`) | Ninguna | Reducir evidencia o salida; mismo modelo | `engine/org_design.py:104-105` |
| `max_tokens_exceeded` | `deterministic_reject` (categoría `configuration`) | Ninguna | Reducir el tope de salida y perfiles por solicitud | `engine/org_design.py:106-107` |
| `insufficient_quota` | `deterministic_reject` (categoría `quota`) | Ninguna | Revisar saldo/cuota antes de otra solicitud | `engine/org_design.py:108-109` |
| HTTP 401 / 403 | `auth` | **Ninguna rotación en bucle** | Revisar clave local y permisos. Marcar credencial como inválida | `engine/org_design.py:110-111` |
| HTTP 429 | `rate_limit` | Ninguna. **No hay backoff implementado** y este plan no lo añade: un 429 puede ser cuota | Revisar cuenta. `Retry-After` se registraría sólo como metadato si se autoriza (Anexo A-4) | `engine/org_design.py:112-113` |
| HTTP ≥ 500 | `provider_transient` | Ninguna. **No hay circuit breaker** y este plan no añade reintentos pagados | Revisar estado del proveedor y cargos posibles | `engine/org_design.py:114-115` |
| Timeout / conexión caída tras envío | `unknown_outcome` | Ninguna. **No se reenvía**: no hay idempotencia de proveedor, sólo local (`:345,408`) | Revisar cargos. Estado explícito `resultado_desconocido` | `engine/org_design.py:67-68,146-148` |
| Cancelación local durante el vuelo | `cancelled` | Ninguna. Se guarda cancelación y se retiene recibo tardío | Revisar cargos posibles | `engine/generation_pipeline.py:724-734`; `engine/org_design.py:85` |
| Cancelación antes de arrancar el worker | `cancelled` | Ninguna | Ninguna: no se entró al transporte (`sent_requests = 0`) | `engine/generation_pipeline.py:579-588` |
| `finish_reason = "length"` | `deterministic_reject` (capacidad) | Ninguna | Reducir perfiles por solicitud o elevar tope compatible. **Es el caso del fallo observado [H1]** | `engine/org_design.py:46,648` |
| Fallback a otro proveedor | — | **Prohibido sin política preaprobada, compatibilidad, presupuesto y consentimiento que cubra el alterno** | No existe hoy y este plan no lo crea | `LEEME_V8.txt:50-51` |

**Regla dura adicional:** `HTTP 400` **nunca** se corrige con rotación de claves. La política de claves es de un solo proveedor por plan, sin recorrido de claves (`engine/generation_pipeline.py:539-543`, `:542` revalida sello de cuenta).

---

## 8. Estrategia de cache y expiración del catálogo

**Estado verificado:** existe cache **en memoria** de repositorio (`engine/providers.py:582-626`, sesión-local, LRU, nunca persistente) y existe persistencia **de catálogo dentro del proyecto** (`engine/bridge.py:847`, restaurado en `:890-894`). **No existe TTL ni caducidad de catálogo en ninguna ruta** (`docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:26` lo declara).

| Fuente | `catalog_source` | Persistencia propuesta | TTL propuesto | ¿Puede autorizar un envío? |
|---|---|---|---|---|
| `GET /models` con clave de la sesión | `live` | Memoria + proyecto | 24 h (`expires_at`) | **Sí**, y sólo mientras el sello de cuenta coincida (`engine/bridge.py:811-814`) |
| Snapshot documental sin clave (DeepSeek/OpenAI) | `cached` | Proyecto | 30 días, marcado `UNVERIFIED_ACCOUNT_AVAILABILITY` (`engine/providers.py:391`) | **No.** `discovery: True` ⇒ nunca verifica (`engine/bridge.py:785-786,824-832`) |
| Documentación de proveedor sin endpoint (Z.AI, `discovery: False`) | `manual-unverified` | Proyecto | Sin caducidad | **No**, salvo confirmación manual explícita, y aun así `account_verified: False` (`engine/bridge.py:827-831`) |
| Catálogo guardado y recargado de proyecto | `cached` | Ya en proyecto | `expires_at` heredado; si venció ⇒ `recheck_required` | **No.** Hoy se degrada duro a `available=None` (`:893-894`); se propone degradación **con caducidad declarada** en lugar de pérdida total de información |
| Alias de runtime DSH | `cached` (`catalog_scope: dsh_runtime_reference`) | Proyecto | N/A | **No**, nunca reinterpretado como ID de API (`engine/bridge.py:805-810`) |

**Reglas no negociables de la cache:**
1. La caducidad **nunca** amplía autoridad: sólo reduce la necesidad de otra consulta de red.
2. `expires_at` vencido ⇒ `ACCOUNT_RECHECK_REQUIRED` (estado ya existente, `engine/bridge.py:798`).
3. El sello de cuenta es `HMAC(csrf, clave)` y **no sobrevive a la sesión** (`:764-767`). **Consecuencia deliberada que el plan preserva:** no existe forma de que un catálogo cacheado autorice un envío sin volver a consultar. Cualquier diseño que lo permita queda **rechazado por este plan**.
4. La caché es de **una sola cuenta**. El catálogo de otra clave o de un alias de la misma cuenta no verifica (`tests_v8_models_receipts.py:92,107`).
5. Nunca se guarda precio ni calidad: el catálogo demuestra qué IDs existen, no qué cuestan (`engine/providers.py:400-405`).

---

## 9. Estrategia de privacidad y redacción de secretos

**Controles ya verificados (se conservan sin cambios):**

| Control | Ubicación |
|---|---|
| Redacción de texto de fuente | `engine/providers.py:485-496` (`redact_text`) |
| Rutas sensibles excluidas por patrón | `engine/providers.py:426` (`_SECRET_PATH`: `.env*`, `.git`, `.aws`, `.ssh`, `.npmrc`, `id_rsa*`, `credentials*`, `secrets*`, `token*`, `vault*`, `*.pem/.p12/.pfx/.key`) |
| Directorios de runtime ignorados | `engine/providers.py:427` |
| Redacción en el estado del bridge | `engine/bridge.py:524-539` |
| Rechazo de salida con credencial en el ADN | `engine/org_design.py:192-203` (`_OUTPUT_SECRET`) |
| Campos prohibidos al guardar proyecto | `engine/project_store.py:19,38-46` |
| Claves sólo en DPAPI de Windows, por usuario | `engine/bridge.py:335-386` (ruta `%LOCALAPPDATA%\OrgDNA\keys.dpapi`, `CryptProtectData` en `:354-361`) |
| Clave pasada sólo en la pila del worker efímero | `engine/generation_pipeline.py:552-555`, `:710` |
| Frontera tipada de recibos, sin cuerpo ni claves | `engine/generation_pipeline.py:24-35` |
| Extracción HTTP acotada a `code`/`param` allowlisteados | `engine/providers.py:102-116` |
| Diagnóstico declara qué NO incluye | `engine/bridge.py:700-701` |

**Huecos que este plan cierra:** el ledger durable de B3 es una **superficie nueva** de disco. Debe aplicar obligatoriamente `_reject_secret_fields` (`engine/project_store.py:38-46`) y `redact_text` antes de escribir, y su test negativo (`test_ledger_rejects_secret_fields`) es condición de aceptación, no recomendación.

**Prohibiciones explícitas que ninguna propuesta de este documento relaja:** guardar claves API, cabeceras `Authorization`, secretos, prompts con credenciales, cuerpos de error crudos del proveedor ni respuestas sin sanitizar. El encargo pide "mensaje de error sanitizado"; la suite resuelve esto **no guardando texto remoto**, y ese diseño se mantiene (`tests_v8_evidence.py:244`).

---

## 10. Plan de pruebas de regresión, con falsificadores

Cada prueba declara **condición positiva**, **falsificador negativo** y **resultado esperado**. No se usan mocks para ocultar incompatibilidades del proveedor: los transportes sintéticos sólo validan contrato local y así se etiquetan (`LEEME_V8.txt:8`).

### 10.1 P0-A

| Prueba | Condición positiva | Falsificador negativo | Resultado esperado | Estado |
|---|---|---|---|---|
| ID válido de catálogo | `GET /models` devuelve `deepseek-flash` y el sello de cuenta coincide | — | `status = catalog_verified`, `capabilities_verified = False` | Ya existe (`tests_v8_models_receipts.py:54`) |
| Display name rechazado como ID | Se envía `DeepSeek-V4.1-Flash` a `validate_api_model_choice` | — | `BridgeError`, **sin** llamada de diseño | Ya existe (`:54`) |
| Manual no verificado bloqueado | `manual_model_confirmed=True` en proveedor con descubrimiento | — | Sigue bloqueado | Ya existe (`:86`) |
| Catálogo expirado | Catálogo `live` con `expires_at` pasado | — | `ACCOUNT_RECHECK_REQUIRED`, sin envío | **Nuevo (A3/A4)** |
| Catálogo cacheado válido offline | Proyecto cargado sin red ni clave; catálogo dentro de TTL | Un cacheado que **sí** autoriza un envío ⇒ **FAIL del diseño** | Visible en UI, **jamás** habilitante de envío | **Nuevo (A4)** |
| Discrepancia manifest/modelo enviado | Se altera `model_selection` tras confirmar | — | `ConsentRequired` | Ya existe (`engine/org_design.py:755-762`; `tests_org_design.py:196`) |
| Proveedor sin modelos compatibles | Catálogo consultado, ninguna fila utilizable | — | Razón **específica**, no el mensaje genérico | **Nuevo (A5)** |
| **Sin límites reportados ⇒ lote no automático** | `model_metadata` sin `max_output_tokens` y `profiles_per_request={}` | Si el plan sigue adelante con `per_batch` calculado sólo desde el tope solicitado ⇒ **FAIL** | Bloqueo con código accionable o reducción forzada | **Nuevo (A2) — es el test del fallo observado** |
| Holgura en la ruta automática | `per_batch` resultante y `cap` calculado | `cap == 1024 + 2400·n` ⇒ **FAIL** | `cap` con holgura declarada, o `cap = effective_cap` | **Extiende** `tests_generation_robustness_v7.py:127` |

### 10.2 P0-B

| Prueba | Positiva | Falsificador | Esperado | Estado |
|---|---|---|---|---|
| HTTP 400 con usage ausente | Fallo con cuerpo sin `usage` | Un `0` en cualquier campo de `usage` ⇒ **FAIL** | `null` en los tres campos; `unknown_requests ≥ 1` | Ya existe (`tests_v8_models_receipts.py:213`; `:37`) |
| HTTP 429 con backoff | 429 registrado | Que el motor reintente solo ⇒ **FAIL** | Sin reintento; clase `rate_limit` | Ya existe parcial; clase nueva (B5) |
| HTTP 500 reintentable | 500 registrado | Ídem: reintento automático ⇒ **FAIL** | Sin reintento; clase `provider_transient` | Ídem |
| Timeout con resultado desconocido | Timeout tras envío | `billing_outcome = known` ⇒ **FAIL** | `result_outcome = timeout_unknown`, billing `unknown` | Ya existe (`:227`) |
| Cancelación tras posible envío | Cancelar durante el transporte | Que el diseño se aplique ⇒ **FAIL** | Recibo tardío retenido sin revivir el job | Ya existe (`:238`, `:265`) |
| Redacción de API key y `Authorization` | Diagnóstico y proyecto completos | Cualquier clave o cabecera serializada ⇒ **FAIL** | Ausente; `privacy.*_included = false` | Ya existe (`tests_bridge.py:84`; `:90`) |
| Restore/recovery de job interrumpido | Job no terminal guardado y recargado | Que reviva o recupere permiso de gasto ⇒ **FAIL** | `status = cancelled`, `interrupted_snapshot = true` | Ya existe (`:279`) |
| **Recibo sobrevive a cierre abrupto** | Fallo forzado antes de guardar proyecto | Pérdida del recibo ⇒ **FAIL** | Presente en el ledger durable | **Nuevo (B2/B3)** |
| **`attempt` e `idempotency_key` por recibo** | Dos intentos del mismo plan | Recibos indistinguibles ⇒ **FAIL** | `attempt` distintos, misma clave local | **Nuevo (B1)** |
| **El ledger no acepta secretos** | Escritura con un valor tipo clave | Secreto en disco ⇒ **FAIL** | Rechazo con `ProjectStoreError` | **Nuevo (B8)** |

### 10.3 P1-A

| Prueba | Positiva | Falsificador | Esperado | Estado |
|---|---|---|---|---|
| Repositorio parcial | Árbol truncado | Que declare cobertura completa ⇒ **FAIL** | `inventory_complete = false` + hueco | Ya existe (`tests_repository_inventory.py:107-138`) |
| Árbol truncado | Presupuesto de solicitudes/depth/entradas/bytes agotado | Ídem | Hueco explícito | Ya existe |
| Archivo grande | Blob > 40 KB | Que afirme haber leído fragmentos **sin** leerlos ⇒ **FAIL** | Hoy: hueco. **Con C1: fragmento etiquetado `partial_fragment`** | Ya existe (`tests_v8_evidence.py:124`) — **cambia con C1** |
| Archivo binario | Blob no UTF-8 | Que invente contenido ⇒ **FAIL** | Reemplazo acotado o hueco | Ya existe (`:91`) |
| Módulo crítico sin contenido | Familia/módulo sin lectura | Silencio ⇒ **FAIL** | Hueco nominado por familia y módulo | Ya existe (`:67`) |
| Perfil sin evidencia suficiente | Lote con evidencia escasa | Inventar dominio para llegar a N ⇒ **FAIL** | Incertidumbre explícita | Ya existe (`:216`) |
| No duplicación excesiva entre lotes | N=30, 5 lotes | `full_repeat_file_occurrences == unique×lotes` ⇒ **FAIL** | Paquetes dirigidos por módulo | Ya existe (`:148`, `:170`) |
| Cita de ruta global ausente del lote | Perfil cita un path del mapa global no enviado | Aceptarlo ⇒ **FAIL** | `unreviewed_evidence` | Ya existe (`:200`) |

### 10.4 P1-B

| Prueba | Positiva | Falsificador | Esperado | Estado |
|---|---|---|---|---|
| Misma versión/mismo hash ⇒ no-op | Reejecutar el arranque con hash idéntico | Reinstalar o reescribir ⇒ **FAIL** | No-op verificado | **Nuevo (D5)** |
| Hash distinto ⇒ abortar | Hash del relanzador alterado | Continuar ⇒ **FAIL** | Aborto con mensaje | **Nuevo (D5)** |
| Bundle incompleto ⇒ abortar | Falta un documento del paquete | Exportar igual ⇒ **FAIL** | `validate_bundle.valid = false` | Ya existe (`tests_capability_exports.py:45,83`) |
| Tarea `observe` sin escritura | `TaskSpec` con `autonomy_state = observe` | Permitir escritura ⇒ **FAIL** | `tool_policy.granted = false` | **Nuevo (D1/D2)** |
| Tarea `prepare` sin push/deploy | `push_or_deploy = false` en `prepare` | Permitirlo ⇒ **FAIL** | Bloqueado | **Nuevo (D1/D2)** |
| Ejecución aprobada con manifest exacto | Manifest idéntico al aprobado | Ejecutar con manifest divergente ⇒ **FAIL** | `ConsentRequired` | Ya existe el patrón (`engine/org_design.py:755-762`) |
| Export y reimport compatibles | Ciclo completo con `taskspec` | Romper v1 ⇒ **FAIL** | `orgdna/export-manifest` v1 legible; v2 aditiva | **Extiende** (`tests_capability_exports.py:83`) |

**Regla anti-ocultamiento:** ninguna prueba de P1-A ni P1-B puede declarar éxito basándose en ausencia de datos. El patrón ya establecido —`no_tests_does_not_pass` (`tests_evaluation_runs.py:61`), `test_no_empty_partial_success` (`tests_repository_inventory.py:91`)— se aplica tal cual a `TaskSpec` y al ledger.

---

## 11. Plan de migración compatible con V7

**Contexto real:** la instalación del operador está en V7 y este paquete es V8. La migración **ya está descrita** y se respeta sin reinterpretarla (`LEEME_V8.txt:25-37`).

| Paso | Acción | Garantía | Evidencia |
|---|---|---|---|
| 1 | Copia de seguridad completa de la carpeta V7 | Reversibilidad total | `LEEME_V8.txt:26` |
| 2 | Detener **sólo** OrgDNA; extraer el ZIP en carpeta nueva; **no** mezclar motores de versiones distintas; **no** cerrar DSH | Aislamiento de motor | `LEEME_V8.txt:27` |
| 3 | Con ambas instancias cerradas, copiar `data/projects` completa (incluye `_capabilities` y SQLite auxiliares) | Continuidad de proyectos y versiones | `LEEME_V8.txt:29-32`; verificado en `data/projects/98d8ec4f-…/` con `.sha256` por versión |
| 4 | **No** copiar secretos, tokens, claves, sesiones ni credenciales | Las claves viven en DPAPI del usuario, no en el proyecto | `LEEME_V8.txt:33`; `engine/project_store.py:19`; `engine/bridge.py:338` |
| 5 | Ejecutar `launch.cmd` (Python ≥ 3.10), cargar proyecto, comprobar nombre/N/diseño, guardar y reabrir | Verificación funcional mínima | `launch.cmd:6,14`; `engine/project_store.py:143-176` |
| 6 | Conservar el respaldo | Reversión | `LEEME_V8.txt:36` |

**Compatibilidad de formatos que este plan NO rompe:**

| Formato | Versión actual | Tratamiento |
|---|---|---|
| Proyecto local | `orgdna-local-project` v1 (`engine/project_store.py:126,163`) | Se conserva v1. Los campos nuevos de recibo entran **dentro** del snapshot; `load_saved` debe aceptar historial v1 y v2 (`engine/generation_pipeline.py:218-231` hoy exige `version == 1`) |
| Export DSH | `orgdna/export-manifest` v1 (`engine/export_artifacts.py:124`) | Se conserva v1; `taskspec` entra como **documento nuevo** con su propio `taskspec_version` |
| SkillHub | `orgdna-skillhub/1` (`engine/capability_deployment.py:205`) | Sin cambios |
| Recibo de request | hoy sin versión (`engine/generation_pipeline.py:48-56`) | Se introduce `schema_version`, valor inicial 2, con lectura de 1 |
| Autonomía | `'version': '1.0'` (`engine/autonomy.py:221`) | Se conserva; ya existe precedente de lectura de snapshots v3 previos (`:234-241`) |
| Diagnóstico | `orgdna-generation-diagnostic` v2 (`engine/bridge.py:693`) | Sube a v3 de forma aditiva |

**Regla de migración de datos históricos:** un proyecto V7 sin `generation_history` debe seguir cargando. Ya está previsto y probado (`tests_v8_models_receipts.py:279`, `test_old_project_without_generation_history_still_loads`). Cualquier cambio de B1/B2/B3 **debe** preservar ese test sin excepción.

---

## 12. Criterios de aceptación medibles por paquete

### P0-A
1. `limits_reported == False` **impide** un plan automático: existe un test que falla si el plan continúa con `per_batch` derivado sólo del tope solicitado. **[A2]**
2. La ruta automática de dimensionado produce `cap` con holgura verificable, o `cap = effective_cap`. **[A1]**
3. `GET /models` devuelve `catalog_sha256`, `fetched_at` y `expires_at` deterministas: dos consultas idénticas producen el mismo hash. **[A3]**
4. Un catálogo `cached` **nunca** satisface `validate_api_model_choice`: los tests `tests_v8_models_receipts.py:92,102,107,122` siguen **PASS sin modificación**. **[A4]**
5. Un catálogo vencido produce `ACCOUNT_RECHECK_REQUIRED` y **cero** solicitudes al proveedor. **[A4]**
6. Proveedor con catálogo consultado y sin modelos compatibles devuelve razón específica. **[A5]**
7. El manifest sellado incluye `model_id`, `display_name`, `catalog_source`, `catalog_sha256`, `expires_at`. **[A6]**
8. `response_mode` incompatible con `output_modalities` del catálogo bloquea **antes** del envío. **[A7]**

### P0-B
9. Un recibo existe en disco **sin** que el usuario haya guardado el proyecto, verificado con muerte forzada del proceso. **[B2/B3]**
10. `usage` ausente es `null` en el 100 % de los casos; **ninguna** ruta escribe `0` por defecto. **[conservado]**
11. Todo recibo lleva `schema_version`, `attempt`, `idempotency_key`, `result_outcome`, `billing_outcome`, `started_at`, `finished_at`. **[B1]**
12. `retry_class` es una función total sobre los códigos de `_FAILURES` ∪ `HTTP_ERROR_CODES`: ningún código queda sin clase. **[B5]**
13. El ledger rechaza campos de credencial con el mismo error que `ProjectStore`. **[B8]**
14. El diagnóstico descargable incluye los campos nuevos y mantiene `privacy` explícito. **[B6]**
15. `tests_v8_models_receipts.py` completo **y** `tests_generation_pipeline.py` completo siguen PASS.

### P1-A
16. Todo archivo > 40 KB produce, o bien un fragmento **etiquetado `partial_fragment`**, o bien un hueco con razón; **nunca** una afirmación de lectura completa. **[C1]**
17. El `repo_map` enumera los subsistemas del encargo marcando *observado / no observado*, sin inferir contenido. **[C2]**
18. Las métricas de duplicación por lote son visibles en el manifest y en la UI. **[C3/C6]**
19. Ningún perfil puede citar una ruta ausente de su lote (se conserva `unreviewed_evidence`). **[conservado]**

### P1-B
20. `TaskSpec` existe, está versionado y se exporta; un `TaskSpec` ausente hace fallar `validate_bundle`. **[D1/D4]**
21. Los cuatro estados `observe/propose/prepare/execute-approved` existen, con `observe` por defecto, y un snapshot de autonomía previo sigue validando. **[D2]**
22. Una tarea `observe` no puede obtener escritura, y `prepare` no puede hacer push/deploy. **[D3]**
23. `launch.cmd` aborta ante hash distinto y es no-op ante hash idéntico. **[D5]**
24. El ciclo export→reimport con `taskspec` conserva compatibilidad v1. **[D4]**

**Criterio de éxito global, honesto:** éxito de request ≠ éxito de esquema ≠ éxito útil. `HTTP 200` **no** es éxito. Éxito útil exige: respuesta válida + esquema válido + N perfiles completos + contrato por perfil + artefacto descargable + recibo persistido (`engine/generation_pipeline.py:622-624,648-650,659-661,698-705`).

---

## 13. Fuera de alcance (lista explícita)

1. Docker, Kubernetes, cualquier plataforma de orquestación nueva.
2. Reinstalación, actualización o modificación de la configuración de DSH. El encargo lo prohíbe y `LEEME_V8.txt:37` lo confirma.
3. Reescritura del sistema de generación.
4. Cambios de formato de exportación que rompan compatibilidad: sólo campos nuevos versionados y documentados.
5. Reintentos pagados automáticos, backoff o circuit breaker que **envíen** solicitudes.
6. Fallback automático de proveedor o rotación de claves.
7. Instalación autónoma de skills, paquetes, plugins, binarios, conectores o dependencias.
8. Grafo AST/dependencias real y centralidad semántica (ver Anexo A-3).
9. Concesión real de permisos o `toolScope` a agentes: todo permanece propuesta (`engine/autonomy.py:227`).
10. Afirmar instalación, ejecución o rentabilidad. `runtime_verified: False`, `applied_to_runtime: False` (`engine/autonomy.py:227`).
11. Prueba pagada real contra DeepSeek: **NOT_RUN** por diseño del encargo y de la suite (`docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:34`).
12. Certificación de Chromium real, Excel COM o la instalación DSH del operador: **NOT_RUN** (`docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:35`).
13. Niveles de autonomía de todo el equipo: este plan sólo añade estado **por tarea** (D2).
14. Garantía económica o límite duro en USD: no se ofrece, y ningún campo de la UI puede insinuarlo (`engine/org_design.py:538`).
15. Modificación de los archivos protegidos del paquete y de su manifiesto de hashes. Por eso este documento se escribió **fuera** de `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`.

---

## 14. Riesgos residuales y límites

### 14.1 Límites de conocimiento de este documento

| Límite | Consecuencia |
|---|---|
| El cuerpo crudo de la respuesta del proveedor no se conserva por diseño (`engine/bridge.py:700-701`) | La causa del fallo observado **no puede** confirmarse desde el paquete. [H1] queda como hipótesis hasta disponer del diagnóstico |
| El `job_id` aportado no existe en el paquete | Imposible correlacionar hechos [O] con artefactos |
| No se ejecutó ninguna prueba en esta sesión; sólo se leyó el código y los datos | Ningún PASS/FAIL se acredita aquí. Los estados "Ya existe" significan *existe la prueba*, **no** *se ejecutó ni pasó* |
| Los archivos `.pyc` presentes (`engine/__pycache__/`, 10-10 10:45-10:48) indican que algo se importó o ejecutó tras extraer el paquete | Se desconoce qué se ejecutó y con qué resultado; no se infiere |

### 14.2 Riesgos residuales medibles (ninguno es garantía)

| Riesgo | Naturaleza | Mitigación propuesta | SLO medible, no garantía |
|---|---|---|---|
| Rechazo del proveedor por causas ajenas al plan (cuota, incidente, cambio de contrato de API) | Externa | Clasificación B5 + mensaje accionable | **Objetivo:** 100 % de fallos con clase asignada y mensaje accionable. **No** se promete tasa de éxito del proveedor |
| Truncación por subestimación de tokens | Estimación local, declarada no tokenizer (`engine/org_design.py:509-511`) | A1 + A2 + holgura verificable | **Objetivo:** 0 lotes planificados sin holgura. Falsificable por test |
| Facturación desconocida en fallo | Del proveedor: no expone usage en error | `billing_outcome = unknown` nunca `known` (`engine/generation_pipeline.py:52`; `LEEME_V8.txt:57`) | **Objetivo:** 100 % de fallos con billing `unknown` o `not_applicable`, jamás `0` implícito |
| Pérdida de recibos por cierre abrupto | Local, hoy real (`LEEME_V8.txt:53-56`) | Ledger B3 | **Objetivo:** 0 recibos perdidos tras muerte forzada. Hoy sería 100 % perdido |
| Latencia/red/TLS | Externa | Sin reintento automático (`engine/providers.py:301-305`) | **Objetivo:** fallo clasificado, no silencioso |
| Credencial inválida | Externa | 401/403 ⇒ marca de credencial inválida, sin rotación (`engine/org_design.py:110-111`) | **Objetivo:** 0 rotaciones automáticas de clave |
| Cobertura parcial presentada como total | Documental | `whole_repository_content_complete: False` forzado (`engine/providers.py:976`) | **Objetivo:** 0 pantallas que afirmen cobertura total |
| Huecos de > 40 KB | Técnico, hoy real | C1, con autorización previa (Anexo A-2) | **Objetivo:** 100 % de archivos grandes con hueco **o** fragmento etiquetado |
| Un `TaskSpec` se lea como autorización de ejecución | Semántico | `state: PROPOSED_NOT_EXECUTED`, `granted: false` | **Objetivo:** 0 documentos exportados sin marca de no ejecutado |

### 14.3 SLOs propuestos (medibles, revisables, no garantías)

- **S1.** 100 % de envíos con manifest sellado y consentimiento exacto consumido una sola vez.
- **S2.** 100 % de fallos con `result_outcome` y `retry_class` asignados.
- **S3.** 100 % de campos de `usage` ausentes en `null` (nunca `0`).
- **S4.** 0 recibos perdidos por cierre abrupto (tras B3).
- **S5.** 0 lotes planificados sin holgura declarada (tras A1/A2).
- **S6.** 100 % de archivos > 40 KB con hueco explícito o fragmento etiquetado (tras C1).
- **S7.** 100 % de diagnósticos sin claves, cabeceras ni cuerpos remotos.

**Separación de éxitos exigida por el encargo:** *éxito de request* (HTTP 2xx) ≠ *éxito de esquema* (N perfiles conformes) ≠ *éxito útil* (artefacto descargable + recibo + contrato por perfil). Sólo el tercero cuenta como resultado entregable, y **ningún SLO de este documento se expresa en términos de "garantizado", "perfecto" o "sin fallos".**

---

## Anexo A — Dependencias nuevas no autorizadas

Registradas, **no incorporadas** al plan. Cada una exige decisión explícita del operador antes de tocar código.

| # | Descripción | Evidencia / impacto | Alternativa sin cambio | Decisión requerida |
|---|---|---|---|---|
| **A-1** | Crear un almacén durable nuevo en `data/` para el ledger de recibos (p. ej. `data/ledger/*.jsonl`) | P0-B lo exige; hoy no existe (`LEEME_V8.txt:53-56`). Superficie nueva de disco y de privacidad | Mantener recibos en memoria y sólo persistir al guardar proyecto o descargar diagnóstico (estado actual) | ¿Autoriza un archivo de ledger append-only fuera de `data/projects/`? |
| **A-2** | Lectura fragmentada de archivos > 40 KB y cambio de semántica de `MAX_FILE_BYTES` | `engine/providers.py:32,911-912,955-956`; cambia `coverage` y el presupuesto de red | Mantener el hueco explícito que ya se reporta | ¿Autoriza ampliar el presupuesto de lectura dirigida a blobs grandes por fragmentos? |
| **A-3** | Grafo de dependencias/AST con centralidad real | `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:29,40-41`. Exigiría parsers por lenguaje y probablemente dependencia externa, **prohibida** por el encargo | `repo_map` heurístico declarado como tal (C2) + `_FAMILY_ORDER` (`engine/providers.py:538`) | ¿Se acepta la heurística declarada como techo de P1-A? |
| **A-4** | Registro de `Retry-After` y cabeceras de rate limit del proveedor | El encargo pide respetar `Retry-After`; hoy `_request` **descarta** las cabeceras de respuesta (`engine/providers.py:297-298` sólo usa `status, headers, data` internamente) | Registrar sólo `http_status` y clase `rate_limit` (B5) | ¿Autoriza conservar un subconjunto allowlisteado de cabeceras de rate limit? |
| **A-5** | Conservar el identificador de request del proveedor | El encargo pide `provider request id`; hoy sólo se conserva `response_id_sha256` (hash, `engine/generation_pipeline.py:56`) | Mantener sólo el hash, o hash + prefijo truncado | ¿Se autoriza guardar el ID en claro, o se mantiene hasheado? |
| **A-6** | Campos nuevos en la UI (`catalog_source`, `expires_at`, `attempt`, `retry_class`) | Requiere tocar `web/index.html`, que **no** figura en la lista de módulos autorizados del encargo (sólo cita `web/app.js`) | Exponerlos únicamente en el diagnóstico JSON descargable | ¿Se autoriza `web/index.html` como archivo de alcance ampliado? |
| **A-7** | Reintentos con backoff y circuit breaker | El encargo los enumera (429, 5xx); la suite los excluyó deliberadamente (`LEEME_V8.txt:50-51`) | Clasificación sin envío (B5) y decisión humana por plan nuevo | ¿Se autoriza reintento automático acotado, o se mantiene la prohibición? |

---

## Anexo B — Artefactos exactos que deben inspeccionarse

No se inventa su contenido; se indica la ruta y el motivo.

| # | Artefacto | Ruta / cómo obtenerlo | Qué resolvería |
|---|---|---|---|
| **B-1** | Diagnóstico del intento fallido | Botón **Descargar diagnóstico JSON** en la UI (`web/app.js:538`), servido como `/download/generation-diagnostic.json` y nombrado `orgdna-generation-diagnostic-<job_id>.json` (`engine/bridge.py:1410-1412`). Contiene `error.code`, `error.finish_reason`, `error.http_status`, `error.provider_error_code`, `request_receipts` y `usage_summary` (`engine/bridge.py:673-702`) | **Decide entre [H1] y la premisa [O]:** si aparece `output_truncated` + `finish_reason: "length"` ⇒ [H1]; si aparece `provider_http_error` + `http_status: 400` + `invalid_request_error` ⇒ premisa del encargo |
| **B-2** | Versión de proyecto asociada a ese job | `data/projects/<project_id>/versions/<version_id>.json` — el historial va en `generation_history` (`engine/bridge.py:850`) y cada versión tiene su `.sha256` (`engine/project_store.py:134-135`) | Correlacionar el job con su plan, `request_hashes` y su catálogo guardado (`models`, `engine/bridge.py:847`) |
| **B-3** | Plan sellado del intento | Dentro de B-2, campo del job con `payload_sha256`, `request_hashes`, `max_output_tokens`, `profiles_per_request`, `effective_profiles_per_request` (`engine/generation_pipeline.py:501-508`) | Comprobar el dimensionado real de lote que produjo la truncación |
| **B-4** | Respuesta cruda del proveedor | **No existe y no debe existir**: `raw_response_included: False` por diseño (`engine/bridge.py:700-701`) | Nada. La causa del HTTP 400, si existió, **sólo** puede confirmarse en el panel de consumo del proveedor |
| **B-5** | Inventario del repositorio del intento | Campo `repo_inventory` del proyecto (`engine/bridge.py:848`) con `coverage.gaps`, `families`, `modules`, `oversized_relevant_files` (`engine/providers.py:970-987`) | Contrastar las cifras 254/18/236/4/86/2 del encargo |
| **B-6** | Catálogo de modelos con el que se preparó | Campo `models` del proyecto (`engine/bridge.py:847`) | Determinar si había límites reportados (`max_output_tokens`) en el momento del plan |

---

## Anexo C — Tabla de verificación aritmética (reproducible)

| Comprobación | Fórmula | Resultado | Uso |
|---|---|---|---|
| Perfiles por lote con tope 16384 | `(16384 − 1024) // 2400` | `6` | Dimensión típica de lote |
| Perfiles por lote con tope 15424 | `(15424 − 1024) // 2400` | `6` | Consistente con `LEEME_V8.txt:73` |
| Salida máxima agregada | `15424 × 5` | `77120` | **Coincide exactamente** con los 77.120 tokens citados en `LEEME_V8.txt:73` |
| Tope sin holgura (ruta automática) | `1024 + 2400 × 6` | `15424` | Igual al presupuesto ⇒ **cero margen** para error de estimación |
| Tope con holgura (ruta explícita, hoy) | `effective_cap` | `15424` | El único camino con margen es fijar `profiles_per_request` explícito (`engine/org_design.py:491`) |

**Lectura:** la aritmética del motor reproduce la cifra publicada en el material V8, lo que refuerza [H1] como hipótesis **consistente**, y refuerza también que el camino automático es el que carece de holgura. **No es prueba:** el plan exacto de aquel intento no está en el paquete (Anexo B-3).

---

## Cierre

El plan queda **bloqueado a cuatro paquetes** y ordenado P0-A → P0-B → P1-A → P1-B. Ninguna sección propone Docker, Kubernetes, reinstalación de DSH, reescritura, cambio de formato de exportación, envío a proveedores, consumo de claves ni instalación de dependencias.

**La única corrección de dirección que este documento introduce respecto del encargo es de hechos, no de alcance:** la evidencia local del fallo apunta a truncación por dimensionado de lote (`output_truncated`, `engine/org_design.py:46,648`) y no a un rechazo por identificador de modelo. El identificador no verificado sigue siendo relevante, pero por la vía de la ausencia de límites, no por un HTTP 400. Ambos desenlaces están previstos y el falsificador que los separa es un solo artefacto: el diagnóstico del Anexo B-1.

Mientras ese artefacto no exista, cualquier afirmación de causa raíz —incluida la de este documento— permanece como hipótesis.
