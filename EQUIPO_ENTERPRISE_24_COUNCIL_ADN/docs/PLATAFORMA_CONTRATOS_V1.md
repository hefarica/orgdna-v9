# PLATAFORMA_CONTRATOS_V1 — Contratos congelados de la capa de plataforma (Agent OS) sobre OrgDNA V8

**Ronda:** R0 (congelamiento de contratos previo a los flujos I1–I6).
**Naturaleza del entregable:** documento de diseño y contratos declarativos. **No es el código aplicado.**
**Modo:** `freeze` (lectura y diseño). En esta ronda no se escribió código de runtime, no se modificó
`engine/`, no se envió ninguna solicitud a ningún proveedor, no se consumieron claves, no se instalaron
dependencias, no se modificó DSH y no se abrió ninguna conexión de red.
**Convención de rutas:** todas las rutas son relativas a `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`, raíz de la suite.
**Convención de citas:** `archivo:línea` o `archivo:línea-línea` sobre el código leído en esta sesión. Ninguna
afirmación técnica de este documento se apoya en memoria: cada una cita el artefacto o declara su estatuto.

---

## 1. Qué fija este congelamiento y qué no

Se congelan seis contratos declarativos que los seis flujos de implementación (`I1`–`I6`) deben consumir sin
reinterpretarlos. Un contrato aquí es:

- una **forma** (JSON Schema `draft 2020-12` parseable con `json.load`, biblioteca estándar);
- un **campo de versión obligatorio** con valor `"1"` y rechazo explícito de cualquier otro valor;
- una lista de **campos requeridos** no vacía;
- una sección **`prohibited_fields`** que reutiliza la lista literal de `engine/project_store.py:19`;
- una marca **`inert_by_default: true`**;
- y una serie de **invariantes** expresadas como `const` que ninguna implementación puede relajar sin subir de versión.

Lo que este documento **no** es: no es el motor, no es una prueba de que el motor exista, no acredita ninguna
ejecución de agente, no autoriza ninguna acción de las que los contratos describen, y no sustituye la revisión
independiente del flujo `t8` ni la validación de empaquetado de `t9`.

Los seis artefactos congelados:

| Contrato | Archivo | `version_field` | Consumidor primario |
| --- | --- | --- | --- |
| TaskSpec / Task Graph v1 | `docs/plataforma/taskspec.schema.json` | `taskspec_version` | `I1` → `engine/task_graph.py` |
| EvidenceNode v1 | `docs/plataforma/evidence-node.schema.json` | `evidence_node_version` | `I2` → `engine/evidence_graph.py` |
| PolicyDecision v1 | `docs/plataforma/policy.schema.json` | `policy_contract_version` | `I3` → `engine/policy_engine.py` |
| MemoryRecord v1 | `docs/plataforma/memory-record.schema.json` | `memory_record_version` | `I4` → `engine/memory_governance.py` |
| TenantBoundary v1 | `docs/plataforma/tenant-boundary.schema.json` | `tenant_boundary_version` | `I4` → `engine/tenants.py` |
| ReceiptExtension v1 | `docs/plataforma/receipt-extension.schema.json` | `receipt_version` | `I5` → `engine/artifact_factory.py`, `I6` → `engine/reliability.py`, `engine/connector_gateway.py` |

**Revisión 2 del contrato de política (emitida en `t9`, aditiva).** `t9` cerró el hallazgo F‑T4‑2 emitiendo
`docs/plataforma/policy.v2.schema.json` como **archivo nuevo**, conforme a la regla de cambio de la sección 10.
Los bytes de `policy.schema.json` (v1) **no se tocan**: dos consumidores congelados los fijan byte a byte
(`tests_platform_policy.py:39,145-162` y `tests_platform_eval_artifacts.py:1194-1196`; ver
`docs/PLATAFORMA_ENTREGA_V9.md`, sección 4, para la medición completa). El payload no cambia de versión
(`policy_contract_version` sigue siendo `"1"`); lo que cambia es la revisión del contrato, declarada en su
campo `schema_revision = "2"`.

El registro de `Agent Registry` (`I2` → `engine/agent_registry.py`) no recibe un séptimo artefacto propio: reutiliza
`taskspec.schema.json` en su campo `agent_ref` y la forma de evidencia de `evidence-node.schema.json`. Se documenta
así para no inventar un contrato que el encargo no pidió.

---

## 2. Restricciones duras que heredan los seis contratos

| Restricción | Traducción contractual |
| --- | --- |
| Sin red | `limits.network_allowed` y `declared_limits.network_allowed` son `const false`; `extension_rules` de la extensión de recibo prohíbe persistencia de cabeceras de proveedor. |
| Sin claves | `prohibited_fields` literal + guard `propertyNames` negativo + `additionalProperties: false` en cada objeto. |
| Sin envíos a proveedores | Ningún contrato tiene un campo de envío; `call_provider` solo aparece como `action_kind` **evaluado** por la política, nunca ejecutado (`side_effects_performed` es `const false`). |
| Sin cambios en DSH | Ningún contrato nombra rutas de DSH, ni formatos DSH, ni configuración de DSH. La única mención es la prohibición. |
| Sin dependencias nuevas | Los seis contratos son JSON puro; el verificador de la sección 8 usa solo `json`, `re`, `pathlib` y `glob`. |
| Formatos de exportación retrocompatibles | Sección 6: `orgdna-local-project` v1 y `orgdna/export-manifest` v1 quedan intactos; la extensión de recibo es aditiva y tiene 0 colisiones con las 11 claves base. |

---

## 3. Reglas transversales (R-1 … R-10)

Cada regla se enuncia con su comprobación. Todas se aplican a los seis contratos.

| Regla | Enunciado | Comprobación |
| --- | --- | --- |
| **R-1** | Versión explícita: el campo de versión es obligatorio y vale `"1"`; cualquier otro valor es un error tipado `unsupported_version`, nunca una interpretación tolerante. | `version_field` ∈ `required` y `properties[version_field].const == "1"` (sección 8). |
| **R-2** | Nada desconocido se convierte en cero: un valor ausente se representa `null` y una ausencia de evidencia se representa con un veredicto explícito (`unevidenced`, `insufficient`, `unknown`). | `null_is_not_zero` (`const true`) en la extensión de recibo; unión `["integer","null"]` en `ttl_seconds`; `verdict` obligatorio en el nodo de evidencia. |
| **R-3** | Sin campos de credencial: la lista `prohibited_fields` es la de `engine/project_store.py:19` sin alteración, y el guard de nombres de `engine/project_store.py:38-46` (normalización camelCase→snake_case, `-`→`_`, y variante sin caracteres no alfanuméricos) no debe coincidir con ningún nombre declarado. | La verificación de la sección 8 recorre los nombres de propiedad de cada objeto y aplica ambas comparaciones; además aplica un patrón estricto de nombres de credencial. |
| **R-4** | `inert_by_default: true`: el artefacto es declarativo. Cargarlo, parsearlo o validarlo no importa módulos con efectos, no abre red, no escribe en disco, no consume credenciales, no envía nada a proveedores y no altera DSH. | Marca presente en los seis (`inert_by_default is True`); criterio de cierre de cada flujo: 0 importaciones de red en el módulo nuevo. |
| **R-5** | Retrocompatibilidad: los formatos vigentes no cambian. Proyecto `orgdna-local-project` v1 (`engine/project_store.py:126,163`), manifiesto de exportación `orgdna/export-manifest` v1 (`engine/export_artifacts.py:124`) y recibo base de solicitud (`engine/generation_pipeline.py:24-57`) quedan intactos. Las extensiones son aditivas. | `base_receipt_compatibility.redefinition_forbidden == true` y 0 colisiones entre las propiedades de la extensión y las 11 claves base + 3 claves de `usage` (sección 8). |
| **R-6** | Determinismo: todo hash de contrato es SHA-256 hexadecimal sobre JSON canónico (`sort_keys=True`, `separators=(',',':')`, `ensure_ascii=False`), como ya hace `engine/evaluation_runs.py:30`. | `graph_sha256` y `scope_hash` con patrón `^[0-9a-f]{64}$`; regla congelada en `$defs.graph_rules.hash_rule`. |
| **R-7** | Fallo honesto: ningún contrato expresa garantías, porcentajes de éxito ni "sin fallos". Un resultado parcial se declara parcial. | Enumeraciones cerradas con valor explícito para lo desconocido: `verdict`, `result_outcome`, `retry_class`, `status` (`engine/generation_pipeline.py:18,21`). |
| **R-8** | Ninguna decisión ejecuta: evaluar política, registrar evidencia o emitir recibo son operaciones de datos. | `side_effects_performed` es `const false` en política y en la extensión de recibo. |
| **R-9** | Frontera obligatoria: todo registro de memoria y de evidencia lleva `tenant_id`; ninguna lectura cruza plano ni inquilino. | `tenant_id` ∈ `required`; `cross_plane_reads`, `cross_tenant_reads` y `cross_tenant_read` son `const false`. |
| **R-10** | Todo es local: no hay campo que designe un endpoint remoto, un token, una cabecera de autorización ni una credencial; el almacenamiento declarado es local y explícito. | Guard de nombres (R-3) + revisión de que ningún `ref` admita URL con credenciales embebidas (`evidence-node` `$defs.evidence_ref.ref`). |

---

## 4. Los seis contratos

### 4.1 `taskspec.schema.json` — TaskSpec y TaskGraph v1

- **Raíz:** un `TaskSpec`. `$defs.task_graph` describe la envolvente del DAG.
- **Requeridos (10):** `taskspec_version`, `task_id`, `title`, `intent`, `autonomy_level`, `depends_on`, `budget`,
  `acceptance_criteria`, `falsifiers`, `idempotency_key`.
- **Invariantes:** `autonomy_level ∈ {observe, propose, prepare, execute-approved}` con `default: "observe"`;
  `acceptance_criteria` y `falsifiers` con `minItems: 1`; el estado de un criterio es
  `{pending, passed, failed, not_run}` (mismo vocabulario PASS/FAIL/NOT_RUN de la suite, `LEEME_V8.txt:82-83`, y
  `not_run` nunca se aproxima a `passed`); presupuesto con las cuatro magnitudes obligatorias
  (`tokens`, `money_usd`, `time_seconds`, `requests`); identificadores con patrón estable.
- **Congelado para `I1`:** orden topológico determinista — nivel = longitud de la cadena de dependencias más larga
  desde una raíz y, dentro del nivel, orden lexicográfico ascendente por `task_id` (`$defs.graph_rules.deterministic_order_rule`);
  los diez códigos de error de `$defs.graph_rules.error_codes` son el vocabulario cerrado del validador de grafo.
- **Nota de nombres:** `budget.tokens` es una magnitud entera de presupuesto, no un token de acceso. La distinción se
  registra en `docs/PLATAFORMA_DECISIONES.md` (D-R0-1) y se comprueba en la sección 8.

### 4.2 `evidence-node.schema.json` — EvidenceNode v1

- **Requeridos (9):** `evidence_node_version`, `node_id`, `node_kind`, `statement`, `verdict`, `evidence_refs`, `edges`,
  `tenant_id`, `created_at`.
- **Invariantes:** `verdict ∈ {supported, unevidenced, insufficient, contradicted}`; una referencia de tipo `file` exige
  `sha256`; una referencia de tipo `test` exige `observed_at`; `superseded_by` permite superar un nodo sin editarlo.
- **Regla de veredicto congelada (`$defs.verdict_rules`), evaluada en orden:** una arista `contradicts` ⇒ `contradicted`;
  sin referencias ⇒ `unevidenced`; con referencias pero ninguna `verified: true` con hash recomprobado ⇒ `insufficient`;
  con al menos una verificada y ninguna contradicción ⇒ `supported`. La ausencia de evidencia nunca se convierte en `supported`.
- **Prohibición explícita:** una referencia de evidencia es ruta, hash o etiqueta; nunca un valor de credencial ni una
  cabecera de autorización (el guard de nombres lo hace estructural).

### 4.3 `policy.schema.json` — PolicyDecision v1 y puertas humanas

- **Requeridos (11):** `policy_contract_version`, `policy_id`, `policy_revision`, `action`, `decision`, `reason`, `gate`,
  `matched_rules`, `limits`, `side_effects_performed`, `evaluated_at`.
- **Invariantes:** `decision ∈ {allow, deny, require_human_approval}`; `reason` con `minLength: 1` (una decisión sin razón
  no valida); si `decision == "require_human_approval"` entonces `gate` es obligatorio y no nulo; si `decision == "allow"`
  entonces `approval` es obligatorio.
- **Puertas humanas obligatorias (`$defs.mandatory_gates`):** `secrets`, `spend`, `connectors`, `write`, `install`, `push`,
  `merge`, `deploy`. Salida por defecto de esas ocho puertas: `require_human_approval`.
- **Aprobación (`$defs.approval_record`):** `gate`, `approver_role`, `approved_at`, `scope_hash` y `one_shot: true`.
  El `scope_hash` debe coincidir con `action.scope_hash`: una aprobación de otro alcance no autoriza esta acción.
  No se almacena ningún dato de autenticación del aprobador.
- **`limits`:** `network_allowed` es `const false`; `autonomy_ceiling` replica el vocabulario del TaskSpec.
- **Revisión 2 (t9):** `policy.v2.schema.json` limita la exigencia de aprobación a los tipos de acción sujetos
  a puerta obligatoria (una lectura puede devolver `allow` con `gate: null` y `approval: null`) y convierte
  `$defs.mandatory_gates` en una restricción `enum` referenciada por `$ref` desde `gate`, desde los `allOf` y
  desde los registros de aprobación. El motor de `I3` no se modifica.

### 4.4 `memory-record.schema.json` — MemoryRecord v1

- **Requeridos (17):** versión, `memory_id`, `plane`, `origin`, `content_ref`, `recorded_at`, `scope`, `confidence`,
  `integrity`, `ttl_seconds`, `expires_at`, `read_permissions`, `update_policy`, `tenant_id`, `cross_plane_reads`,
  `cross_tenant_reads`, `contaminates`.
- **Invariantes:** `plane ∈ {execution, project, organizational, personal}`; `confidence` entre 0 y 1; `integrity` con
  `hash_algorithm: "SHA-256"` y 64 hex; `ttl_seconds` y `expires_at` admiten `null` y ese `null` es explícito (no 0);
  `read_permissions` exige al menos una entrada con `role_ref`, `tenant_id` y `plane`; `cross_plane_reads`,
  `cross_tenant_reads` y `contaminates` son `const false`.
- **Regla de lectura congelada (`$defs.plane_rules.read_rule`):** se permite solo si coinciden `plane` **y** `tenant_id`
  **y** existe una entrada de `read_permissions`. Un fragmento caducado no se devuelve aunque siga en disco.
- **Regla de exportación congelada:** el plano `personal` nunca entra en el paquete ni en el ZIP.

### 4.5 `tenant-boundary.schema.json` — TenantBoundary v1

- **Requeridos (9):** versión, `tenant_id`, `organization_id`, `isolated_domains`, `domain_rules`,
  `sensitive_values_stored`, `cross_tenant_read`, `shared_tenants`, `created_at`.
- **Invariantes:** seis dominios aislados obligatorios — `organizations`, `projects`, `sensitive_material`, `budgets`,
  `memories`, `artifacts`; `sensitive_values_stored` es `const false`; `cross_tenant_read` es `const false`;
  `shared_tenants` es `const []` (compartir exigiría otra versión de contrato).
- **Precisión deliberada:** el dominio `sensitive_material` designa el **dominio** de material sensible. El contrato
  declara el dominio y no admite su valor: la regla `$defs.domain_rule` exige `store_kind`, y las reglas congeladas
  marcan `sensitive_material` y `memories` como nunca exportados.

### 4.6 `receipt-extension.schema.json` — ReceiptExtension v1

- **Requeridos (9):** `receipt_version`, `idempotency_key`, `attempt`, `result_outcome`, `retry_class`, `produced_by`,
  `null_is_not_zero`, `side_effects_performed`, `recorded_at`.
- **Composición congelada:** `recibo_compuesto = recibo_base ∪ extensión`, con claves disjuntas. La extensión **no
  redefine** ninguno de los 11 campos base ni de las 3 claves de `usage`
  (`base_receipt_compatibility.base_top_level_keys`, `:base_usage_keys`, fuente `engine/generation_pipeline.py:24-57`).
- **Invariantes:** `retry_class ∈ {none, rate_limit, transient, permanent, policy, budget, unknown}`; `result_outcome`
  incluye `unknown` como valor legítimo; `attempt ≥ 1` (un intento nuevo de una operación pagada exige autorización nueva);
  `null_is_not_zero` y `side_effects_performed` son `const`; `artifact.path` no admite rutas absolutas, `..` ni unidad de disco.
- **Bloqueos heredados:** `extension_rules` deja escrito que la persistencia de ledger depende de la decisión A-1,
  que el identificador de solicitud del proveedor se guarda solo como hash (decisión A-5) y que las cabeceras de
  proveedor no se persisten (decisión A-4). Ver sección 7.

---

## 5. Mapa de las 11 capacidades del encargo → I1–I6

Las once capacidades del encargo se agrupan en seis flujos offline e inertes. `I1`–`I6` son las tareas `t2`–`t7`
de la lista compartida; el paquete de integración es `t9`.

### 5.1 Tabla de mapeo (una fila por capacidad)

| # | Capacidad del encargo | Flujo | Módulo destino exacto | Contrato | Criterio de aceptación medible |
| --- | --- | --- | --- | --- | --- |
| 1 | Task Graph Engine | **I1** (`t2`) | `engine/task_graph.py` | `taskspec.schema.json` | En `tests_platform_task_graph.py`: 100 % de los grafos con ciclo, id duplicado, dependencia inexistente o auto-dependencia devuelven uno de los 10 códigos de `$defs.graph_rules.error_codes`; el mismo JSON produce el mismo `topological_order` y el mismo `graph_sha256` en dos procesos distintos; `autonomy_level` ausente ⇒ `"observe"`. |
| 2 | Agent Registry | **I2** (`t3`) | `engine/agent_registry.py` | `taskspec.schema.json` (`agent_ref`) | Deriva de un snapshot sin cambios ⇒ `drift == []`; mutar exactamente un campo (instrucción, skill, permiso o modelo permitido) ⇒ `drift` nombra ese campo y ningún otro; 0 modelos permitidos fuera del conjunto declarado. |
| 3 | Evidence Graph | **I2** (`t3`) | `engine/evidence_graph.py` | `evidence-node.schema.json` | Se cumplen los cuatro casos de `$defs.verdict_rules`: sin referencias ⇒ `unevidenced`; referencias sin `verified: true` ⇒ `insufficient`; una arista `contradicts` ⇒ `contradicted` (aunque haya soporte); ≥ 1 verificada con hash de 64 hex recomprobado y sin contradicción ⇒ `supported`; 0 nodos `supported` sin hash recomprobado. |
| 4 | Policy Engine | **I3** (`t4`) | `engine/policy_engine.py` | `policy.schema.json` | Las 8 puertas de `$defs.mandatory_gates` sin aprobación ⇒ `require_human_approval` con `gate` no nulo y `reason` no vacío; `network_allowed` nunca `true`; 0 decisiones con `side_effects_performed != false`; el módulo no importa `socket`, `urllib`, `http`, `subprocess` ni ningún cliente de red. |
| 5 | Puertas de aprobación humana | **I3** (`t4`) | `engine/policy_engine.py` | `policy.schema.json` (`$defs.approval_record`) | 0 `allow` en puerta obligatoria sin `approval` cuyo `scope_hash` sea igual a `action.scope_hash`; una aprobación con otro `scope_hash` ⇒ `require_human_approval`; una aprobación ya consumida (`one_shot: true`) ⇒ `deny`. |
| 6 | Memory Governance | **I4** (`t5`) | `engine/memory_governance.py` | `memory-record.schema.json` | 100 % de los fragmentos aceptados declaran `plane`, `origin`, `recorded_at`, `scope`, `confidence`, `integrity.sha256`, `ttl_seconds` explícito, `read_permissions` y `update_policy`; un fragmento con `expires_at` vencido no se devuelve en lectura; 0 lecturas fuera del mismo `plane` y `tenant_id`. |
| 7 | Tenant Isolation | **I4** (`t5`) | `engine/tenants.py` | `tenant-boundary.schema.json` | Leer con un `tenant_id` distinto ⇒ error tipado `cross_tenant_denied`, nunca una lista vacía silenciosa; la intersección de identificadores entre N inquilinos es ∅; `sensitive_values_stored == false` en todos los límites declarados; 0 valores de material sensible materializados. |
| 8 | Evaluation Harness | **I5** (`t6`) | `engine/evaluation_harness.py` | `taskspec.schema.json` (`acceptance_criteria`) | Cada caso declara el criterio del `TaskSpec` que comprueba; el hash de las instrucciones de producción antes y después de la corrida es idéntico byte a byte; todo resultado por caso ∈ `{passed, failed, not_run}` y ninguno se etiqueta "garantizado". |
| 9 | Artifact Factory | **I5** (`t6`) | `engine/artifact_factory.py` | `receipt-extension.schema.json` | Cada artefacto escrito en disco tiene `sha256` y recibo con los campos requeridos de la extensión; releer el archivo y recomprobar el hash coincide; 0 artefactos escritos fuera de la ruta declarada; 0 claves base redefinidas. |
| 10 | Reliability Plane | **I6** (`t7`) | `engine/reliability.py` | `receipt-extension.schema.json` (`retry_class`, `idempotency_key`) | Kill switch activo ⇒ 0 tareas nuevas despachadas; la misma `idempotency_key` devuelve el mismo recibo y 0 efectos duplicados; 0 reintentos automáticos para `call_provider`, `spend_money`, `push`, `merge` y `deploy` (la clasificación se declara, no se ejecuta). |
| 11 | Connector Gateway | **I6** (`t7`) | `engine/connector_gateway.py` | `policy.schema.json` (`action_kind: open_connector`) | 100 % de los conectores declarados con `enabled: false` por defecto; 0 conexiones vivas y 0 llamadas de red; `open_connector` ⇒ `require_human_approval` con `gate: "connectors"`; el módulo no importa ninguna biblioteca cliente (GitHub, Drive, base de datos, email) y no admite campos con forma de credencial. |

### 5.2 Criterios de cierre por flujo

| Flujo | Tarea | Módulos de implementación | Prueba exigida | Cierre del flujo (medible) |
| --- | --- | --- | --- | --- |
| **I1** Task Graph Engine | `t2` | `engine/task_graph.py` | `tests_platform_task_graph.py` | Suite del flujo en verde + 0 importaciones de red + todo grafo inválido rechazado con código del vocabulario congelado. |
| **I2** Agent Registry + Evidence Graph | `t3` | `engine/agent_registry.py`, `engine/evidence_graph.py` | `tests_platform_registry_evidence.py` | Suite en verde + 0 nodos `supported` sin hash recomprobado + drift reportado con el campo exacto. |
| **I3** Policy Engine + puertas humanas | `t4` | `engine/policy_engine.py` | `tests_platform_policy.py` | Suite en verde + 8/8 puertas obligatorias devuelven `require_human_approval` sin aprobación + 0 efectos de la evaluación. |
| **I4** Memory Governance + Tenant Isolation | `t5` | `engine/memory_governance.py`, `engine/tenants.py` | `tests_platform_memory_tenants.py` | Suite en verde + 0 fugas entre inquilinos y planos + caducidad efectiva comprobada. |
| **I5** Evaluation Harness + Artifact Factory | `t6` | `engine/evaluation_harness.py`, `engine/artifact_factory.py` | `tests_platform_eval_artifacts.py` | Suite en verde + hash de instrucciones de producción sin cambios + todo artefacto con hash y recibo. |
| **I6** Reliability Plane + Connector Gateway | `t7` | `engine/reliability.py`, `engine/connector_gateway.py` | `tests_platform_reliability_connectors.py` | Suite en verde + 0 reintentos automáticos de operaciones pagadas + 0 conectores habilitados por defecto. |
| **Entrega** (integración y empaquetado) | `t9` | `engine/bundle.py` (`RUNTIME_ALLOWLIST`), `MANIFIESTO_SHA256.txt`, una acción de lectura en `engine/bridge.py` | `tests_platform_integration.py` | `python validate_imports_portable.py` sigue devolviendo `valid=true`; el ZIP V9 distribuye los 10 módulos y los 6 contratos; ninguna ruta prohibida modificada. |

**Nota de integración para `t9` (CERRADA en `t9`).** `RUNTIME_ALLOWLIST` es deliberadamente literal y sin globs
(`engine/bundle.py:29-31`, `:808-820`), y `MANIFIESTO_SHA256.txt` debe cubrir todos los archivos menos él mismo
(`engine/bundle.py:798`). `t9` añadió explícitamente los 11 módulos, las 8 pruebas de plataforma y los 13
documentos a la lista literal, regeneró el manifiesto (300 entradas; `file_count = 301`) y expuso una acción
de solo lectura en `engine/bridge.py`. El detalle, la huella base reconstruible y lo que queda en `NOT_RUN`
están en `docs/PLATAFORMA_ENTREGA_V9.md`. Decisión D‑R0‑2: **cumplida**.
**Nota de citas:** la ampliación de la allowlist desplazó 21 líneas el resto de `engine/bundle.py`; las citas de
esta sección y de la 8.4 ya apuntan a la numeración posterior a `t9`.

---

## 6. Retrocompatibilidad de formatos

| Formato vigente | Evidencia | Efecto de R0 |
| --- | --- | --- |
| Proyecto local `orgdna-local-project` v1 | `engine/project_store.py:126,163` | Intacto. Los contratos nuevos no añaden claves al sobre ni al `snapshot`; quien los guarde dentro de un proyecto sigue sujeto al guard de `engine/project_store.py:101` y `:170`. |
| Manifiesto de exportación `orgdna/export-manifest` v1 | `engine/export_artifacts.py:124` | Intacto. `exportedAt`, `organization_sha256`, `state_version`, `artifacts` y los indicadores de auto-hash no cambian. |
| Recibo de solicitud (base v1) | `engine/generation_pipeline.py:24-57` | Intacto y **no redefinido**: la extensión es aditiva con 0 colisiones (verificado, sección 8). |
| Recetas y backups DSH (`agent-team-gui/recipe` v1, `agent-team-gui/definitions` v2) | `docs/export_artifacts.md:7-9` | Intactos. Ningún contrato de plataforma añade claves a esos esquemas. |
| Estados terminales y de recibo | `engine/generation_pipeline.py:18,21` | Reutilizados literalmente: `completed/failed/cancelled` y los tres estados de recibo. La extensión añade `unknown` como valor explícito para lo no observado, sin reemplazar ninguno. |

Regla de interpretación para el consumidor: **una clave nueva nunca cambia el significado de una clave existente**.
Si un flujo necesita cambiar el significado de un campo base, debe proponer una versión nueva del contrato y
detenerse (sección 10).

---

## 7. Interacción con las decisiones pendientes del Anexo A

El plan previo registró siete dependencias nuevas no autorizadas
(`PLAN_CORRECCION_FOCALIZADO_V8_P0A_P0B_P1A_P1B.md:746-758`). R0 **no las resuelve**: las mantiene bloqueadas y fija
el comportamiento seguro por defecto que los contratos ya codifican. El detalle de cada decisión, con la pregunta
exacta al operador, está en `docs/PLATAFORMA_DECISIONES.md`.

| Decisión | Efecto sobre la capa de plataforma en R0 |
| --- | --- |
| A-1 ledger durable | **No autorizado.** `receipt-extension` no persiste nada por sí mismo; los recibos siguen el régimen V8 en memoria (`LEEME_V8.txt:53-56`). |
| A-2 lectura fragmentada > 40 KB | Fuera del alcance de los seis flujos. Ningún contrato la requiere y ninguno la habilita. |
| A-3 grafo AST/dependencias | **No autorizado.** El Evidence Graph de I2 usa referencias declaradas y verificadas por hash; no infiere centralidad ni construye AST. |
| A-4 cabeceras de rate limit | **No autorizado.** `retry_class` clasifica; no se persiste ninguna cabecera del proveedor. |
| A-5 identificador de solicitud en claro | **No autorizado.** Se conserva `response_id_sha256` (hash); el contrato no admite el identificador en claro. |
| A-6 campos nuevos en la UI (`web/index.html`) | **No autorizado.** `I1`–`I6` no tocan `web/`; la exposición es JSON local y la acción de lectura de `t9` en `engine/bridge.py`. |
| A-7 backoff y circuit breaker | **No autorizado.** El Reliability Plane clasifica y pausa; no reintenta operaciones pagadas ni no idempotentes. |

---

## 8. Verificación ejecutada en R0

### 8.1 Comandos y resultado

```text
python check_r0_schemas.py docs/plataforma
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_v8_models_receipts.py" -v
python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py
```

Salida literal del verificador de contratos, ejecutada sobre los seis archivos con Python 3.12.10 en Windows (el
separador de ruta lo imprime el sistema operativo; en otro sistema aparecerá el separador nativo):

```text
directorio: docs\plataforma
schemas encontrados: 6
OK   evidence-node.schema.json        props=27   version=evidence_node_version    required=9   prohibited=13  inert=True excepcion=no usada
OK   memory-record.schema.json        props=39   version=memory_record_version    required=17  prohibited=13  inert=True excepcion=no usada
OK   policy.schema.json               props=36   version=policy_contract_version  required=11  prohibited=13  inert=True excepcion=no usada
     extension aditiva: base_keys=11 usage_keys=3 colisiones=0 redefinition_forbidden=True existing_formats=2
OK   receipt-extension.schema.json    props=22   version=receipt_version          required=9   prohibited=13  inert=True excepcion=no usada
OK   taskspec.schema.json             props=38   version=taskspec_version         required=10  prohibited=13  inert=True excepcion=no usada
OK   tenant-boundary.schema.json      props=30   version=tenant_boundary_version  required=9   prohibited=13  inert=True excepcion=no usada
resultado: valid=true | comprobaciones=236 | schemas=6
```

Lectura del resultado: los seis `*.schema.json` parsean con `json.load` sin excepción; los seis declaran su campo de
versión, lo incluyen en `required` y lo fijan a `"1"`; los seis reutilizan las 13 entradas literales de
`engine/project_store.py:19`; los seis marcan `inert_by_default`; **0 nombres de propiedad** tienen forma de credencial,
sea por el guard del motor o por el patrón estricto de la sección 8.3; y la extensión de recibo tiene **0 colisiones**
con las 11 claves base y las 3 claves de `usage`.

### 8.2 Huellas de los artefactos congelados

| Archivo | Bytes | SHA-256 |
| --- | --- | --- |
| `docs/plataforma/taskspec.schema.json` | 10656 | `34d775431312df97487ceaf277150235508d92eac8095e2199c89b547edf1715` |
| `docs/plataforma/evidence-node.schema.json` | 7712 | `19c364da482b2bfd7f72a3ec33a2be73615e06557b72dd152eb157a4b5e09d8c` |
| `docs/plataforma/policy.schema.json` | 10069 | `c6026c70690115c7e37ac0d080510f6f19b36cabc76c89701e7d5443bf54118e` |
| `docs/plataforma/memory-record.schema.json` | 9496 | `f678780d1735c7a1570dc54a188b02e78c04e22d46db24d47e938c0c48923d41` |
| `docs/plataforma/tenant-boundary.schema.json` | 7545 | `7e5fcf46946977d1e4137761409595bdd68e46d8b313798ea5b1a9b47374718a` |
| `docs/plataforma/receipt-extension.schema.json` | 8297 | `5f1ae738ad11ebc93d08bb2d682c82842939b0d14f27149cd5aece09baa15792` |
| `docs/plataforma/policy.v2.schema.json` (revisión 2, **nueva** en `t9`) | 22978 | `b273d09668c3fba84350ef1786530c932f26afabf3b83372f049912a3d776b95` |

**Cambio de versión del contrato de política (t9, aditivo).** La fila de `policy.schema.json` **no se
re-pinnea a otros bytes**: v1 sigue vigente e intacto en `c6026c70…` porque dos consumidores congelados lo
fijan byte a byte. La revisión 2 se emite como archivo nuevo y se pinea en su propia fila. La tabla vuelve a
coincidir con los bytes reales de los siete esquemas, y el verificador de la sección 8.3 —que descubre los
esquemas por `glob`— pasa a encontrar **7** archivos: los siete deben pasar.

Estas huellas permiten comprobar que un flujo consumió exactamente la versión congelada.
`MANIFIESTO_SHA256.txt` ya las cubre desde `t9` (ver `docs/PLATAFORMA_ENTREGA_V9.md`, sección 2).

### 8.3 Verificador reproducible

Guardar este bloque como un archivo temporal **fuera** del paquete (por ejemplo `%TEMP%\check_r0_schemas.py`) y
ejecutar `python check_r0_schemas.py docs/plataforma` desde la raíz de la suite. Python 3.10+, solo biblioteca
estándar, sin red, sin escritura en disco y sin ejecutar el repositorio. No se distribuye como archivo del paquete.

```python
"""Verificacion R0 de los 6 contratos congelados. Solo biblioteca estandar.

Uso: python check_r0_schemas.py [directorio docs/plataforma]
Comprueba, para cada *.schema.json:
  1. json.load sin excepcion;
  2. campo de version declarado, requerido y con const "1";
  3. required no vacio;
  4. prohibited_fields igual a la lista literal de engine/project_store.py:19;
  5. inert_by_default marcado explicitamente como true;
  6. ningun nombre de propiedad admite forma de credencial (guard del motor
     y patron estricto de nombres de credencial).
No ejecuta el repositorio, no usa red y no escribe archivos.
"""
import glob
import json
import re
import sys
from pathlib import Path

BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('docs/plataforma')
FILES = sorted(glob.glob(str(BASE / '*.schema.json')))

FORBIDDEN = {'credentials', 'api_key', 'api_keys', 'pending_consent', 'csrf', 'cookie',
             'password', 'access_token', 'refresh_token', 'client_secret', 'private_key',
             'authorization', 'bearer_token'}
STRIPPED = {re.sub(r'[^a-z0-9]', '', name) for name in FORBIDDEN}
CRED = re.compile(r'(?i)(credential|api[_-]?key|access[_-]?token|refresh[_-]?token|'
                  r'bearer[_-]?token|client[_-]?secret|private[_-]?key|password|cookie|csrf|'
                  r'pending[_-]?consent|authorization)')
# 'tokens' es la magnitud entera del presupuesto, no un token de acceso. Se declara
# la excepcion para que quede auditada; el patron solo coincide con nombres completos
# de credencial, asi que en la practica la excepcion no se usa.
ALLOWED_NON_CREDENTIAL = {'tokens'}


def property_names(node, found=None):
    """Nombres de propiedad declarados: claves de todo objeto valor de 'properties'."""
    if found is None:
        found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'properties' and isinstance(value, dict):
                found.extend(str(name) for name in value)
            property_names(value, found)
    elif isinstance(node, list):
        for item in node:
            property_names(item, found)
    return found


def normalized(name):
    camel = re.sub(r'(?<!^)(?=[A-Z])', '_', str(name)).lower().replace('-', '_')
    return camel, re.sub(r'[^a-z0-9]', '', str(name).lower())


def main():
    ok = True
    checks = 0
    print('directorio: %s' % BASE)
    print('schemas encontrados: %d' % len(FILES))
    for path in FILES:
        name = Path(path).name
        try:
            doc = json.loads(Path(path).read_text('utf-8'))
        except Exception as exc:  # noqa: BLE001 - se reporta, no se oculta
            print('FAIL %s: json.load -> %r' % (name, exc))
            ok = False
            continue
        props = property_names(doc)
        version_field = doc.get('version_field')
        required = doc.get('required') or []
        declared = (doc.get('properties') or {}).get(version_field, {})
        version_ok = bool(version_field) and version_field in required and declared.get('const') == '1'
        required_ok = isinstance(required, list) and len(required) > 0
        prohibited = doc.get('prohibited_fields') or []
        prohibited_ok = set(prohibited) == FORBIDDEN and len(prohibited) == len(FORBIDDEN)
        inert_ok = doc.get('inert_by_default') is True
        engine_hits = sorted({n for n in props
                              if normalized(n)[0] in FORBIDDEN or normalized(n)[1] in STRIPPED})
        cred_hits = sorted({n for n in props
                            if CRED.search(n) and n not in ALLOWED_NON_CREDENTIAL})
        used_exception = sorted({n for n in props
                                 if CRED.search(n) and n in ALLOWED_NON_CREDENTIAL})
        guard_count = len(re.findall(r'"propertyNames"', Path(path).read_text('utf-8')))
        checks += 7 + len(props)
        problems = []
        if not version_ok:
            problems.append('version_field invalido')
        if not required_ok:
            problems.append('required vacio')
        if not prohibited_ok:
            problems.append('prohibited_fields distinto de la lista literal')
        if not inert_ok:
            problems.append('inert_by_default ausente')
        if engine_hits:
            problems.append('campos con guard del motor: %s' % engine_hits)
        if cred_hits:
            problems.append('campos con forma de credencial: %s' % cred_hits)
        if guard_count < 1:
            problems.append('sin guard propertyNames')
        if name == 'receipt-extension.schema.json':
            compat = doc.get('base_receipt_compatibility') or {}
            base_keys = set(compat.get('base_top_level_keys') or [])
            usage_keys = set(compat.get('base_usage_keys') or [])
            collision = sorted(set(props) & (base_keys | usage_keys))
            checks += 2
            if collision:
                problems.append('colision con campos base: %s' % collision)
            print('     extension aditiva: base_keys=%d usage_keys=%d colisiones=%d '
                  'redefinition_forbidden=%s existing_formats=%d'
                  % (len(base_keys), len(usage_keys), len(collision),
                     compat.get('redefinition_forbidden'),
                     len(compat.get('existing_formats_unchanged') or [])))
        status = 'OK  ' if not problems else 'FAIL'
        if problems:
            ok = False
        print('%s %-32s props=%-4d version=%-24s required=%-3d prohibited=%-3d inert=%s excepcion=%s %s'
              % (status, name, len(props), version_field, len(required), len(prohibited),
                 inert_ok, used_exception or 'no usada', '; '.join(problems)))
    print('resultado: %s | comprobaciones=%d | schemas=%d' % ('valid=true' if ok else 'valid=false', checks, len(FILES)))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
```

### 8.4 Regresión de la suite V8

Ejecutadas en esta ronda para confirmar que R0 es solo aditivo en documentación:

| Comando | Resultado |
| --- | --- |
| `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_v8_models_receipts.py" -v` | 19 pruebas, OK. |
| `python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py` | `valid=true`, 1620 comprobaciones sobre 269 archivos, salida 0. |
| Recomprobación de las **268 entradas** de `MANIFIESTO_SHA256.txt` (script temporal, solo biblioteca estándar) | 0 archivos ausentes, **0 archivos alterados**: `engine/bundle.py`, `engine/project_store.py`, `web/app.js` y `LEEME_V8.txt` conservan exactamente el hash del manifiesto. |

`MANIFIESTO_SHA256.txt` no se lista a sí mismo (`engine/bundle.py:798`), así que su propia huella se registra aquí para
que `t9` pueda comprobar que lo regenera desde el estado de R0: `f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96`
(26 564 bytes, idéntico al del paquete recibido en esta ronda).

**Actualización de `t9` (posterior a esta sección, que queda como acta de R0).** El manifiesto se regeneró a
**300 entradas** (`file_count = 301`), la allowlist pasó a **237** entradas exactas sin globs y se expuso la
acción de solo lectura `platform-planes-status`. Huella base reconstruible, procedimiento y `NOT_RUN` están en
`docs/PLATAFORMA_ENTREGA_V9.md`.

`validate_directory` lee **solo** los archivos listados en `MANIFIESTO_SHA256.txt`
(`engine/bundle.py:919-947`), por lo que añadir documentos no listados no altera el resultado del validador
portable; sí impediría que viajaran en el ZIP, condición que `t9` resolvió añadiéndolos a la lista literal y
regenerando el manifiesto (sección 5.2 y `docs/PLATAFORMA_ENTREGA_V9.md`).

---

## 9. Qué no queda demostrado por este congelamiento

- **No** demuestra que `I1`–`I6` estén implementados: los módulos destino no existen todavía en el árbol.
- **No** demuestra aislamiento real de inquilinos, caducidad real de memoria ni deduplicación real en runtime:
  los contratos fijan la regla que las pruebas de cada flujo deben poder refutar.
- **No** acredita ninguna ejecución de agente, ninguna prueba pagada contra un proveedor, ninguna importación en DSH
  y ninguna rentabilidad.
- **No** sustituye la revisión independiente (`t8`) ni la validación de empaquetado (`t9`).
- **No** resuelve las siete decisiones del Anexo A: las registra bloqueadas y fija el comportamiento seguro por defecto.
- Los seis `$schema` son identificadores de dialecto y los `$id` son URN: **no se resuelve ni se descarga ninguno**.
  La verificación usa `json.load`, no un validador con red.

---

## 10. Regla de cambio de un contrato congelado

1. Un contrato v1 **no se edita en caliente**. Un cambio de forma, de enumeración, de regla de veredicto o de
   composición exige un archivo nuevo (`*.v2.schema.json`) con `version_field` apuntando a `"2"`.
2. La versión anterior se conserva. Un consumidor que reciba `"2"` sin soportarla debe fallar con `unsupported_version`,
   nunca degradar a la interpretación v1.
3. Todo cambio de contrato se registra en `docs/PLATAFORMA_DECISIONES.md` con su motivo y su impacto de compatibilidad.
4. Cambiar la lista `prohibited_fields` es una decisión del operador, no del implementador: hoy es la lista literal de
   `engine/project_store.py:19` y solo puede crecer por decisión explícita.
5. **Primera aplicación de esta regla (`t9`, F‑T4‑2):** `docs/plataforma/policy.v2.schema.json`. Se emitió archivo
   nuevo en lugar de editar v1; el `version_field` del **payload** no sube porque el motor no cambia y sus
   decisiones siguen siendo conformes, y la revisión del contrato se declara en `schema_revision`. La justificación
   completa, los dos consumidores que fijan v1 byte a byte y la medición 14/14 están en
   `docs/PLATAFORMA_ENTREGA_V9.md`, sección 4.
