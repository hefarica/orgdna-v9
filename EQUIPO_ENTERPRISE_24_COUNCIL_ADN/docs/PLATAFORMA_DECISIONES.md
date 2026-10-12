# PLATAFORMA_DECISIONES — Registro de decisiones de la capa de plataforma (Agent OS) V9

**Ronda:** R0. **Naturaleza:** registro. **Este documento no decide nada por sí mismo.**
**Convención de rutas:** relativas a `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`.
**Convención de citas:** `archivo:línea` sobre el código leído en esta sesión.

---

## 1. Cómo leer este registro

| Estado | Significado |
| --- | --- |
| **PENDIENTE** | La decisión es del operador. No hay autorización. R0 aplica el **default seguro** indicado y ningún flujo puede adoptar la variante ampliada. |
| **APLICADA (R0)** | Decisión de diseño tomada dentro del alcance de R0, reversible y sin efecto de runtime. Se registra para que sea auditable y revocable. |
| **INFORMATIVA** | Distinción registrada porque un revisor podría confundirla; no requiere acción del operador. |

Regla de interpretación: mientras una decisión figure **PENDIENTE**, la variante ampliada está **prohibida** y la
ausencia de respuesta no autoriza nada. Autorizar una variante exige una decisión explícita del operador y, cuando
cambie la forma de un contrato, la creación de una versión nueva (`docs/PLATAFORMA_CONTRATOS_V1.md`, sección 10).

---

## 2. Las siete decisiones heredadas (Anexo A del plan previo)

Fuente: `PLAN_CORRECCION_FOCALIZADO_V8_P0A_P0B_P1A_P1B.md:746-758`, anexo "Dependencias nuevas no autorizadas".
Las siete se arrastran sin resolver. Ninguna fue adoptada en R0.

### A-1 — Almacén durable nuevo para el ledger de recibos

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Autoriza un archivo de ledger append-only fuera de `data/projects/`? (p. ej. `data/ledger/*.jsonl`) |
| **Evidencia** | No existe hoy: los recibos viven en memoria hasta Guardar proyecto o descargar el diagnóstico (`LEEME_V8.txt:53-56`). El plan lo declaró exigido por P0-B. |
| **Default seguro aplicado en R0** | `receipt-extension.schema.json` no persiste nada por sí mismo y `extension_rules.ledger_persistence` remite a esta decisión. Los recibos conservan el régimen V8. |
| **Flujos afectados** | `I5` (`engine/artifact_factory.py`, recibos de artefacto) y `I6` (`engine/reliability.py`, deduplicación por `idempotency_key`). |
| **Impacto si se autoriza** | Superficie nueva de disco y de privacidad; exige política de retención, recuperación y búsqueda de secretos, además de pruebas de supervivencia a cierre abrupto. |
| **Estado** | **PENDIENTE** |

### A-2 — Lectura fragmentada de archivos mayores de 40 KB

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Autoriza ampliar el presupuesto de lectura dirigida a blobs grandes por fragmentos? |
| **Evidencia** | `engine/providers.py:32` (`MAX_FILE_BYTES`), declarado no implementado en `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:30`; cambia la semántica de `coverage` y el presupuesto de red. |
| **Default seguro aplicado en R0** | Ninguno de los seis contratos la requiere ni la habilita. El hueco explícito actual permanece. |
| **Flujos afectados** | Ninguno de `I1`–`I6`. Si se autoriza, pertenece a una corrección de V8, no a la capa de plataforma. |
| **Impacto si se autoriza** | Cambio de semántica en pruebas existentes (`tests_v8_evidence.py:124`), red y presupuesto de bytes. |
| **Estado** | **PENDIENTE** |

### A-3 — Grafo de dependencias/AST con centralidad real

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Se acepta la heurística declarada como techo de P1-A (y de la capa de plataforma)? |
| **Evidencia** | `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:29,40-41`; exigiría parsers por lenguaje y probablemente una dependencia externa, prohibida por el encargo. |
| **Default seguro aplicado en R0** | El Evidence Graph de `I2` usa referencias declaradas y hashes recomprobados; **no** infiere centralidad ni construye AST. |
| **Flujos afectados** | `I2` (`engine/evidence_graph.py`, `engine/agent_registry.py`). |
| **Impacto si se autoriza** | Dependencias nuevas (prohibidas hoy), presupuesto de cómputo y riesgo de afirmar análisis estructural donde hay heurística. |
| **Estado** | **PENDIENTE** |

### A-4 — Conservar cabeceras de rate limit del proveedor

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Autoriza conservar un subconjunto allowlisteado de cabeceras de rate limit? |
| **Evidencia** | `engine/providers.py:297-298` descarta hoy las cabeceras de respuesta; `Retry-After` no se registra. |
| **Default seguro aplicado en R0** | `receipt-extension` clasifica con `retry_class` y **no** persiste ninguna cabecera (`extension_rules.provider_headers_storage`). |
| **Flujos afectados** | `I6` (`engine/reliability.py`). |
| **Impacto si se autoriza** | Superficie nueva de datos remotos en un recibo que la suite diseñó explícitamente sin cuerpo, URL ni cabeceras (`engine/generation_pipeline.py:25`). |
| **Estado** | **PENDIENTE** |

### A-5 — Conservar el identificador de solicitud del proveedor

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Se autoriza guardar el ID en claro, o se mantiene hasheado? |
| **Evidencia** | Hoy solo se conserva `response_id_sha256` (`engine/generation_pipeline.py:56`). |
| **Default seguro aplicado en R0** | El contrato mantiene el hash: `receipt-extension` no reabre el campo ni admite el identificador en claro (`extension_rules.provider_request_id_storage`). |
| **Flujos afectados** | `I5` y `I6` (recibos de artefacto y de intento). |
| **Impacto si se autoriza** | Mayor trazabilidad frente al proveedor a cambio de un identificador de terceros en claro dentro del paquete local. |
| **Estado** | **PENDIENTE** |

### A-6 — Campos nuevos en la interfaz (`web/index.html`)

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Se autoriza `web/index.html` como archivo de alcance ampliado? |
| **Evidencia** | El plan lo registró como no autorizado: la lista de módulos del encargo cita `web/app.js`, no `web/index.html`. |
| **Default seguro aplicado en R0** | `I1`–`I6` no tocan `web/`. La exposición de los estados nuevos es JSON local y la acción de solo lectura de `t9` en `engine/bridge.py`. |
| **Flujos afectados** | Superficie de lectura de los seis flujos y el empaquetado (`t9`). |
| **Impacto si se autoriza** | Ampliación de alcance de archivos y de contrato de interfaz; exige pruebas de DOM y revisión de compatibilidad visual. |
| **Estado** | **PENDIENTE** |

### A-7 — Reintentos con backoff y circuit breaker

| Campo | Contenido |
| --- | --- |
| **Decisión requerida** | ¿Se autoriza reintento automático acotado, o se mantiene la prohibición? |
| **Evidencia** | La suite los excluyó deliberadamente (`LEEME_V8.txt:50-51`); un 429 puede ser cuota de cuenta. |
| **Default seguro aplicado en R0** | `I6` clasifica y pausa; **0** reintentos automáticos de operaciones pagadas o no idempotentes. `retry_class` es una etiqueta, no una acción. |
| **Flujos afectados** | `I6` (`engine/reliability.py`). |
| **Impacto si se autoriza** | Riesgo de cargos repetidos y de duplicar efectos no idempotentes; exige autorización por intento y control de presupuesto. |
| **Estado** | **PENDIENTE** |

---

## 3. Decisiones nuevas detectadas en R0

### D-R0-1 — `budget.tokens` no es una credencial

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿Se mantiene el nombre `tokens` para la magnitud de presupuesto, sabiendo que existe `access_token`/`bearer_token` en la lista de campos prohibidos? |
| **Evidencia** | Guard del motor: `engine/project_store.py:38-46` compara el nombre normalizado contra `FORBIDDEN_FIELDS` (`:19`). `tokens` no coincide con `access_token` ni con `bearer_token`. |
| **Default seguro aplicado en R0** | Se mantiene `budget.tokens` (entero ≥ 0) y el verificador de la sección 8 de `docs/PLATAFORMA_CONTRATOS_V1.md` aplica **ambas** comparaciones más un patrón estricto de nombres de credencial. Resultado ejecutado: 0 coincidencias en los seis contratos. |
| **Estado** | **INFORMATIVA** (comprobada) |

### D-R0-2 — Distribución de los contratos en el ZIP V9

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿Se añaden `docs/plataforma/*.schema.json`, `docs/PLATAFORMA_CONTRATOS_V1.md` y `docs/PLATAFORMA_DECISIONES.md` a `RUNTIME_ALLOWLIST` y se regenera `MANIFIESTO_SHA256.txt` en `t9`? |
| **Evidencia** | `RUNTIME_ALLOWLIST` es literal y sin globs (`engine/bundle.py:29-31`, `:789-799`); la cobertura del manifiesto se exige en `engine/bundle.py:777`; `validate_directory` solo lee archivos listados (`engine/bundle.py:898-926`). |
| **Default seguro aplicado en R0** | R0 no toca `engine/bundle.py` ni `MANIFIESTO_SHA256.txt` (fuera de su alcance y expresamente prohibido). Los contratos existen en el árbol pero **no viajan en el ZIP** hasta que `t9` lo haga. Comprobado: `validate_imports_portable.py` sigue devolviendo `valid=true` (1620 comprobaciones, 269 archivos). |
| **Flujos afectados** | `t9` (integración y empaquetado). |
| **Impacto si no se autoriza** | El paquete entregable no incluiría los contratos congelados; la entrega sería autoconsistente pero incompleta respecto del encargo. |
| **Estado** | **PENDIENTE** |

### D-R0-3 — Persistencia de los planos de memoria y de los artefactos

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿Los planos `execution` y `personal`, y los artefactos de `I5`, se persisten en disco o quedan efímeros por defecto? |
| **Evidencia** | El encargo pide gobierno de memoria y una fábrica de artefactos "escritos a disco local"; el plan previo no autorizó un almacén nuevo (A-1). |
| **Default seguro aplicado en R0** | `memory-record` declara `plane` obligatorio y `update_policy`, pero no autoriza escritura; `plane_rules.execution_lifetime` fija el plano de ejecución como efímero y `personal` como nunca exportado. La escritura de artefactos de `I5` es local y declarada por su módulo, con hash y recibo. |
| **Flujos afectados** | `I4` (`engine/memory_governance.py`) e `I5` (`engine/artifact_factory.py`). |
| **Estado** | **PENDIENTE** |

### D-R0-4 — Techo de autonomía por defecto

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿El techo por defecto de una tarea sigue siendo `observe` cuando la organización usa el preset autónomo de DSH (`engine/autonomy.py:36` admite `autonomous`, `smart` y `manual`)? |
| **Evidencia** | El encargo pide estado de autonomía por tarea con `observe` por defecto; el preset de DSH configura el host, no la capa de plataforma. |
| **Default seguro aplicado en R0** | `autonomy_level` con `default: "observe"` y `execute-approved` como nivel más alto; elevar una tarea exige un acto explícito, no la configuración de DSH. La capa de plataforma no reescribe política ni configuración de DSH (`docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:32`). |
| **Flujos afectados** | `I1` (`engine/task_graph.py`) e `I3` (`engine/policy_engine.py`). |
| **Estado** | **PENDIENTE** |

### D-R0-5 — Identidad del aprobador humano

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿Basta el rol declarado del aprobador (`approver_role`) o se exige identidad nominal verificable? |
| **Evidencia** | El encargo exige puertas de aprobación humana; cualquier identidad nominal exigiría almacenar datos de autenticación, prohibidos por la lista de campos y contrarios al diseño de la suite (`engine/generation_pipeline.py:25` descarta cuerpo, URL y cabeceras). |
| **Default seguro aplicado en R0** | `approval_record` exige `gate`, `approver_role`, `approved_at`, `scope_hash` y `one_shot: true`, y **no admite** ningún dato de credencial del aprobador. La aprobación se ata al `scope_hash` exacto de la acción. |
| **Flujos afectados** | `I3` (`engine/policy_engine.py`). |
| **Estado** | **PENDIENTE** |

### D-R0-6 — `not_run` como estado de criterio de aceptación

| Campo | Contenido |
| --- | --- |
| **Pregunta** | ¿Se mantiene `not_run` como estado explícito de un criterio, distinto de `failed` y nunca aproximado a `passed`? |
| **Evidencia** | La suite ya distingue PASS, FAIL y NOT_RUN (`LEEME_V8.txt:82-83`; `docs/ALCANCE_V8_Y_PROPUESTA_POSTERIOR.md:19-20`). |
| **Default seguro aplicado en R0** | `taskspec.schema.json` incluye `not_run` en el enum de estado del criterio y documenta que no se aproxima a `passed`. |
| **Flujos afectados** | `I1` (`engine/task_graph.py`) e `I5` (`engine/evaluation_harness.py`). |
| **Estado** | **APLICADA (R0)**, reversible: eliminar el valor exige subir la versión del contrato. |

---

## 4. Congelamiento R0: artefactos y huellas

| Artefacto | SHA-256 |
| --- | --- |
| `docs/plataforma/taskspec.schema.json` | `34d775431312df97487ceaf277150235508d92eac8095e2199c89b547edf1715` |
| `docs/plataforma/evidence-node.schema.json` | `19c364da482b2bfd7f72a3ec33a2be73615e06557b72dd152eb157a4b5e09d8c` |
| `docs/plataforma/policy.schema.json` | `c6026c70690115c7e37ac0d080510f6f19b36cabc76c89701e7d5443bf54118e` |
| `docs/plataforma/memory-record.schema.json` | `f678780d1735c7a1570dc54a188b02e78c04e22d46db24d47e938c0c48923d41` |
| `docs/plataforma/tenant-boundary.schema.json` | `7e5fcf46946977d1e4137761409595bdd68e46d8b313798ea5b1a9b47374718a` |
| `docs/plataforma/receipt-extension.schema.json` | `5f1ae738ad11ebc93d08bb2d682c82842939b0d14f27149cd5aece09baa15792` |

Los documentos (`PLATAFORMA_CONTRATOS_V1.md`, `PLATAFORMA_DECISIONES.md`) no incluyen su propia huella: hacerlo
crearía una dependencia circular, igual que el manifiesto de exportación que documenta `docs/export_artifacts.md:27`.
La huella vigente de los contratos es la publicada en `docs/PLATAFORMA_CONTRATOS_V1.md`, sección 8.2.

---

## 5. Resumen de estados

| Decisión | Estado | Efecto inmediato |
| --- | --- | --- |
| A-1 ledger durable | PENDIENTE | Sin persistencia nueva; recibos en el régimen V8. |
| A-2 lectura fragmentada > 40 KB | PENDIENTE | Fuera de los seis flujos. |
| A-3 grafo AST | PENDIENTE | El Evidence Graph no infiere estructura. |
| A-4 cabeceras de rate limit | PENDIENTE | No se persiste ninguna cabecera. |
| A-5 ID de solicitud en claro | PENDIENTE | Solo `response_id_sha256`. |
| A-6 `web/index.html` | PENDIENTE | `I1`–`I6` no tocan `web/`. |
| A-7 backoff / circuit breaker | PENDIENTE | 0 reintentos automáticos de operaciones pagadas. |
| D-R0-1 `tokens` vs credencial | INFORMATIVA | 0 coincidencias en los seis contratos. |
| D-R0-2 distribución en el ZIP | PENDIENTE | `t9` debe ampliar la allowlist y regenerar el manifiesto. |
| D-R0-3 persistencia de planos | PENDIENTE | Ejecución efímera, `personal` nunca exportado. |
| D-R0-4 techo de autonomía | PENDIENTE | `observe` por defecto. |
| D-R0-5 identidad del aprobador | PENDIENTE | Rol declarativo, sin datos de autenticación. |
| D-R0-6 `not_run` | APLICADA (R0) | Estado explícito, distinto de `passed`. |

**Ninguna decisión PENDIENTE se resuelve por silencio, por omisión de respuesta ni por conveniencia de implementación.**
