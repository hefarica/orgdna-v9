# PLATAFORMA V9 — VERIFICACIÓN INDEPENDIENTE (V1)

> **AVISO DE COBERTURA.** Este informe se genera **después** del manifiesto del paquete; por eso el acta
> `PLATAFORMA_ENTREGA_V9.md` lo declara **fuera del paquete por diseño**. Se deposita aquí por estar en el `inScope`
> de `t10`, pero **NO está cubierto por `MANIFIESTO_SHA256.txt`** y no debe añadirse a él sin un nuevo empaquetado.

## 0. Degradación de la propiedad «verificación independiente» — declarada

Esta verificación la firma **el capitán**, no un miembro independiente, y eso **degrada la propiedad de independencia**.
Motivo: **cinco intentos consecutivos** de ejecutarla por miembros murieron con el mismo error de infraestructura
(`SSE stream ended without [DONE]`, code `STREAM_CLOSED`) en **tres sesiones distintas** (`verificador` ×2, `auditor` ×2,
`contratos` ×1), más un fallo de harness en `contratos` (`turn/end carries non-JSON-serializable data`). Ninguno fue un
fallo de criterio: el mismo rol había cerrado `RV2` con veredicto **PASS**.
**Atenuante:** el capitán **no implementó ninguno de los 11 módulos** de plataforma (los hicieron `nucleo`, `evidencia`,
`gobernanza`, `fiabilidad` y `plataforma`). Toda evidencia de este informe es **reproducible por el operador** con los
comandos citados. Si la infraestructura se recupera, el operador puede pedir una reejecución por un miembro
independiente: este informe queda entonces como **insumo**, no como sustituto.

## 1. Huella de medición

| Campo | Valor |
|---|---|
| `runner_id` | capitán / `pwsh` / Python 3.12.10 |
| `host` | windows |
| `python_utf8` | `unset` en la corrida diferencial; `1` en los diferenciales aislados |
| `thread_count` | 1 (sin paralelismo) |
| `suite_scope` | full · patrón `tests_*.py` |
| `tree_digest` | `MANIFIESTO_SHA256.txt` = `3f74e6269be4de5b89aa0d07280969f203d6103fab40fbe247a79a72ae1cd2b8` |
| `started_at` | registrado en `verificacion_v1_huella.json` |
| `stdout_capture` | `verificacion_v1_suite.txt` |

## 2. Matriz PASS / FAIL / NOT_RUN

| # | Objeto verificado | Resultado | Evidencia |
|---|---|---|---|
| 1 | Validación del paquete | **PASS** | `valid=true`, 1791 comprobaciones, 301 archivos, exit 0 |
| 2 | Suite de plataforma (11 módulos) | **PASS** | `Ran 382 tests — OK (skipped=1)` |
| 3 | Cadena del manifiesto | **PASS** | 300 entradas, **0 discrepancias**, 0 enmascaradas; cada digest coincide con los bytes reales |
| 4 | Allowlist (diferencia literal) | **PASS** | 205 → 237: **+32**, −0, orden preservado = 11 módulos + 8 pruebas + 13 documentos |
| 5 | Política v2 aditiva | **PASS** | v1 intacto `c6026c70…`; v2 nuevo `b273d096…`; 14/14 rutas; dos validadores coincidentes |
| 6 | Pins previos intactos | **PASS** | `tests_platform_policy.py:145-162` y `tests_platform_eval_artifacts.py:1194-1196` en verde **sin modificar** |
| 7 | Recibo de aprobación (O-1) | **PASS** | `Ran 38 tests — OK`; 14 falsificadores ejecutados |
| 8 | No intrusión de `t9` en `F-T9-1` | **PASS** | Copia fechada `i4pristine_04d2fd0f` (12:40:11) = bytes entregados, anterior a la primera escritura de `t9` |
| 9 | **Diferencial de regresión completa** | **FAIL — ver §3** | 773 pruebas, **5 fallos + 8 errores**, 7 de ellos **nuevos y atribuibles a la ola** |
| 10 | SLO del encargo | **PASS parcial / NOT_RUN** | Ver §4 |
| 11 | Análisis estático (AST) | **PASS** | Ningún módulo nuevo importa `socket`/`urllib`/`http`/`subprocess`; binding de `_RE_COMPILE` verificado |
| 12 | Conectores vivos, operación 24/7, proveedor real, Chromium, DSH | **NOT_RUN** | Fuera de alcance por diseño; declarado en el acta |

## 3. HALLAZGO PRINCIPAL — regresión atribuible a la integración

**El acta clasifica F‑T9‑2 como «frágil al plazo, no atribuible a `t9`». Esa clasificación NO está sostenida por la
medición.** Diferencial controlado, mismo host, minutos de diferencia, mismo `PYTHONUTF8=1`, mismo módulo de prueba y
misma ventana fija de 12 s (`tests_generation_pipeline.py:90`):

| Árbol | Allowlist | `tests_generation_pipeline.py` | Resultado |
|---|---|---|---|
| **Copia prístina pre-integración** (`%TEMP%\i4pristine_04d2fd0f`) | 205 | `Ran 24 tests in 91.989s` | **OK — 24/24** |
| **Entrega integrada** | 237 | `Ran 24 tests in 141.725s` | **FAILED — 6 fallos** |

Y en aislamiento sobre la entrega, **sin carga concurrente**: `tests_generation_pipeline.py` **6 fallos/24** (141,7 s) y
`tests_model_catalog_scopes.py` **1 fallo/7** (88,6 s).

**Causa medida, no supuesta.** Los siete fallos son de la misma clase: `AssertionError: Generation did not finish`, con el
job detenido en `status=validating`, `stage=building_exports`, `progress=90` al expirar la espera. **Ninguna aserción
funcional falla**: la canalización está avanzando, simplemente ya no le alcanza el plazo. La integración **no rompió
comportamiento; consumió el margen de un plazo fijo**, y eso convierte en fallo lo que antes pasaba.

### 3.1 Tabla por test, por corrida y por clasificación (exigida antes de usar V1 como evidencia)

| Test | Módulo | Pristina pre-integración | Entrega, aislado | Entrega, suite completa | Clasificación |
|---|---|---|---|---|---|
| `test_partial_inventory_requires_bound_explicit_acknowledgement` | `tests_generation_pipeline` | **OK** | FAIL | FAIL | **Atribuible** · plazo local agotado |
| `test_revision_of_imported_roster_preserves_original_agents_and_squad` | `tests_generation_pipeline` | **OK** | FAIL | FAIL | **Atribuible** · plazo local agotado |
| `test_revision_preserves_ids_new_project_changes_them` | `tests_generation_pipeline` | **OK** | FAIL | FAIL | **Atribuible** · plazo local agotado (F‑T9‑2) |
| `test_concurrent_confirmation_and_replay_cannot_rebill` | `tests_generation_pipeline` | **OK** | FAIL | no aparece | **Atribuible** · plazo local agotado |
| `test_historical_completed_hashes_do_not_point_to_changed_design` | `tests_generation_pipeline` | **OK** | FAIL | no aparece | **Atribuible** · plazo local agotado |
| `test_exact_api_id_survives_config_consent_request_and_export` | `tests_model_catalog_scopes` | **OK** | FAIL | FAIL | **Atribuible** · plazo local agotado |
| `test_save_reload_does_not_restore_consent_or_start_jobs` | `tests_generation_pipeline` | **ERROR** | FAIL | ERROR | **AMBIGUO — ver 3.2** |

**Cifras y su relación, sin mezclarlas:** la corrida diferencial completa da **5 fallos + 8 errores** sobre 773 pruebas
(391 de línea base + 382 de plataforma); el módulo `tests_generation_pipeline` aislado da **6 fallos sobre 24**; y el
conjunto **atribuible a la integración es de 6 casos inequívocos** más uno ambiguo. El módulo aislado da 6 porque incluye
`test_concurrent_confirmation_and_replay_cannot_rebill` y `test_historical_completed_hashes_do_not_point_to_changed_design`,
que no llegaron a ejecutarse en la corrida completa (el módulo murió antes). Las tres cifras son correctas y describen
poblaciones distintas: **no deben promediarse ni compararse directamente.**

### 3.2 El caso de encoding quedó RESUELTO: es error heredado, no timeout nuevo

`test_save_reload_does_not_restore_consent_or_start_jobs` **es** uno de los 3 casos condicionados por encoding de la línea
base. Medido en los tres estados (prístina / integrada / corregida) por `t20`:

| Modo | Prístina | Integrada | Corregida |
|---|---|---|---|
| Con `PYTHONUTF8=1` | pasa (0,987 s) | pasa (0,930 s) | pasa (0,825 s) |
| **Sin** `PYTHONUTF8=1` | **ERROR** | **ERROR** | **ERROR** |

La traza es **idéntica en los tres estados**: `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d` en
`tests_generation_pipeline.py:313` (`path.read_text()` sin `encoding`). **No hay timeout nuevo**: el fallo es el defecto
heredado de portabilidad, y por eso se clasifica como **heredado**, no como atribuible a la integración.

### 3.3 Advertencia de capacidad del host — el plazo de 12 s ya era frágil antes de la ola

`t20` midió la capacidad de esta máquina de forma controlada y **fluctúa hasta 10,6×** (calibración 0,0228→0,1094 sin
carga; 0,0237→0,2518 con 4 cargadores verificados). La **misma orden sobre el mismo árbol** dio 141,7 s (acta de `t9`),
47,1 s, 45,2 s y 9,388 s. Y con carga verificada, la copia **prístina** llegó a **9,562 s de los 12 s**, casi tan cerca
como la integrada (10,250 s).

**Consecuencia para la atribución, y corrección de este informe.** La ola consume **~12,4 %** de la ruta de exportación
(+0,104 s medidos sobre 0,807 s prístinos), y eso es lo correcto a recortar. Pero **el plazo fijo de 12 s ya era frágil
antes de la integración**: cruzarlo lo decide la caída de capacidad del host, no sólo el delta de la ola. Mi §3 decía
«la integración cruza el umbral»; la formulación precisa es: **la integración redujo el margen en ~12 % sobre una línea
base que ya estaba cerca del límite**. Conservar los 12 s es conservar una **fragilidad declarada**, no un margen seguro
— y esa es exactamente la decisión que el operador tomó al elegir la salida 1.

**Causa única del delta, medida por `t20`:** el conjunto runtime creció **+32 archivos / +1 191 235 B (+28,6 %)**. El diff
de `engine/bundle.py` prístina→integrada son 28 líneas **sin lógica** (el bloque literal de la allowlist) y `bridge.py`
sólo añade la acción de sólo lectura, que no interviene en la canalización.

**Duplicación, y por qué la memoización la cubre.** `t20` localizó **19 `validate_bundle` por corrida** sobre los mismos
bytes y propuso O‑1 (`validation_sink` aditivo) para bajarlas a 10. **Verificado por el capitán que la corrección ya
aplicada las absorbe**: instrumentando una corrida real, `validate_bundle` recibe 2 llamadas y ejecuta **1 solo cálculo**
(2 → 1 por memoización por contenido). O‑1 **no es necesaria**: el mismo ahorro se obtiene sin tocar la canalización.

**Reproducción exacta del diferencial:**

```
python -m unittest discover -s %TEMP%\i4pristine_04d2fd0f\EQUIPO_ENTERPRISE_24_COUNCIL_ADN \
       -t %TEMP%\i4pristine_04d2fd0f\EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_generation_pipeline.py'   # OK  24/24, 92.0s
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN \
       -p 'tests_generation_pipeline.py'                                                                  # FAILED 6/24, 141.7s
```

**Consecuencia honesta:** un operador que ejecute la suite sobre la entrega ve **5 fallos y 8 errores** donde la línea base
veía **1 fallo y 8 errores**. La ola **no puede declararse «sin regresión»**. No se atribuye a un cambio funcional ni a un
defecto de lógica: se atribuye al **coste añadido del empaquetado**, que el propio acta midió (ventanas de exportación de
6,3–6,4 s → 7,2–8,6 s) y que en la entrega cruza el umbral fijo.

**Salidas posibles (no ejecutadas, requieren decisión):** (a) reducir el coste añadido por la integración en la ruta de
exportación; (b) elevar el plazo del módulo heredado —tocar una prueba previa queda **prohibido** por el contrato vigente y
exigiría autorización expresa—; (c) declarar la fragilidad como limitación conocida y no presentar la suite como verde.

## 4. SLO del encargo

| SLO | Estado | Base |
|---|---|---|
| Requests inválidos bloqueados antes de envío: 100 % | **PASS** | `validate_api_model_choice` en plan y confirmación; 19 pruebas V8 |
| Receipts persistidos por intento: 100 % | **PASS** | frontera tipada + `_capture_receipts`; 19 pruebas |
| Claves expuestas: 0 | **PASS** | `FORBIDDEN_FIELDS` × 6 contratos; guard en módulos; `project_store.py:19` |
| Reintentos duplicados ante timeout: 0 automáticos | **PASS** | `is_auto_retry_authorized` → 84/84 combinaciones sin autorización |
| Tareas idempotentes repetidas sin efecto: 100 % | **PASS** | dedup por `idempotency_key`; `duplicate_noop` con `effect_count=0` |
| Outputs con evidencia requerida completa ≥95 % | **NOT_RUN** | Requiere corpus de salidas reales; no existe offline y no se inventa |
| Hallazgos críticos con falsificador ≥95 % | **NOT_RUN** | No hay corpus de hallazgos críticos; no se infiere |
| Bundles con hash válido antes de instalación: 100 % | **PASS** | `validate_bundle` + sellado; 5 pruebas de exportación |
| Instalación repetida mismo hash: no-op 100 % | **PASS** | CAS de publicación + 5 pruebas |
| Autonomía de escritura sin aprobación: 0 | **PASS** | 8 puertas con `require_human_approval` por defecto; 41 pruebas |

## 5. Falsificadores ejecutados

- **Recibo de aprobación:** 38 casos (`Ran 38 tests — OK`), incluidos los 14 exigidos como aserciones de **bloqueo** y el
  caso de que **la ausencia de recibo nunca se interpreta como aprobación**.
- **Governanza y memoria:** 41 (I3) + 50 (I4) OK; memoria personal nunca exportada ni cruzada de tenant.
- **Task Graph:** 62 OK, incluida la entrada mínima `[aaa, qqq->zzz, zzz->{aaa,qqq}]` → `cycle_detected` sin `IndexError`
  (verificado además por el capitán con su propia reproducción).
- **Fiabilidad:** 34 OK; `is_auto_retry_authorized` sin autorización en 84/84 combinaciones medidas por el capitán.

## 6. Limitaciones declaradas — comprobadas, no corregidas

| Id | Estado tras la verificación |
|---|---|
| O-1b (el hash no atestigua aprobación; el flag no está ligado al nivel; el hash es sobre la declaración; normalización 0/0.0) | **Vigentes** |
| O-5 (tablas de clasificación mutables a nivel de módulo) | **Vigente**; sin mutación interna medida |
| O-9 (las funciones canónicas aceptan declaraciones crudas sin normalizar) | **Vigente**; declarado en el acta |
| Persistencia física del recibo | **NO AUTORIZADA**; sigue pendiente el paso 2 |

## 6-bis. Desviación de un criterio propio, declarada

El criterio 14 del contrato exigía `skipped=0` en las pruebas de plataforma. La medición arroja **`skipped=1`**:
`tests_platform_eval_artifacts.FactoryWriteTests.test_symlinked_directories_inside_the_root_are_not_followed`, omitida con
la razón *«El sistema no permite crear enlaces simbólicos: OSError»*.

**Sigue siendo una DESVIACIÓN NO SALDADA del criterio literal.** Una razón legítima **no modifica unilateralmente el
contrato**: el capitán no puede aceptar su propia excepción. Queda **pendiente de aceptación expresa del operador** o de
ejecución en un host capaz de crear enlaces simbólicos. Mismo estatuto que el skip POSIX legítimo de `tests_evaluation_runs`,
que tampoco está aceptado por nadie: simplemente se declara.

## 5-bis. Error de `api_design` (respuesta truncada) — requisito de gestión demostrado

El aviso de la imagen corresponde al código `output_truncated` (`engine/org_design.py:46`), emitido en un único punto
(`:648`) cuando `finish_reason == "length"`. Se demuestra cada exigencia con evidencia **ejecutada**, no leída.

### Las cuatro condiciones están separadas en el código

| Condición | Código | Categoría |
|---|---|---|
| Límite de salida confirmado por el proveedor | `output_truncated` | `output_limit` |
| Stream interrumpido sin terminación esperada | `response_incomplete` | `invalid_response` |
| Fallo de transporte / plazo del proveedor | `transport_failure`, `request_timeout` | `transport` |
| Plazo local de generación agotado | `progress_failure` | `state` |

**No se infiere límite de tokens de una interrupción genérica**: `response_incomplete` y `output_truncated` son códigos
distintos y una prueba dedicada lo fija (`test_truncated_output_and_empty_reasoning_have_distinct_codes`, **OK**).
El fallo de harness por datos no serializables es un **error de orquestación** del equipo, **no** un resultado del
producto, y no aparece en esa tabla porque no es del producto.

### Comportamiento obligatorio — verificado por ejecución

| Exigencia | Evidencia | Estado |
|---|---|---|
| Detener la aceptación del resultado incompleto; no convertir JSON parcial en artefacto | `test_tool_calls_refusal_and_truncation_fail_closed` **OK** | **PASS** |
| No publicar subconjuntos: ningún perfil parcial | `test_partial_failure_has_audit_but_no_partial_profiles` **OK** | **PASS** |
| Lo desconocido permanece desconocido | `test_usage_never_converts_unknown_to_zero` **OK** | **PASS** |
| Separar solicitud iniciada, recepción y facturación | `test_invalid_schema_retains_actual_usage_and_failure_code`, `test_second_request_timeout_keeps_first_usage_and_unknown_aggregate` **OK** | **PASS** |
| Sin reintento ni continuación automática | `test_same_consent_consumed_even_after_uncertain_timeout`, `test_failed_request_consumes_consent` **OK** | **PASS** |
| Confirmación repetida no duplica efectos | `test_cancel_during_transport_keeps_late_usage_without_applying_design` **OK** | **PASS** |
| El aviso describe fielmente el estado observado | `org_design.py:46` + `:648`; mensaje y `next_action` coinciden con la condición real | **PASS** |
| Reproducir con **proveedor real** | — | **NOT_RUN** |

**Lo que esta evidencia NO acredita:** el comportamiento contra un proveedor real sigue en `NOT_RUN`. Los dobles de
prueba acreditan la lógica offline; no acreditan recepción, cuotas ni facturación. La reconciliación de facturación del
intento truncado **no se deduce** del número de perfiles completados: pertenece al proveedor.

**Alcance:** esto **no autoriza** la persistencia física del Approval Receipt (O‑1 paso 2) ni un ledger durable nuevo (A‑1).

## 5-ter. Cobertura de los SIETE casos de prueba exigidos por el operador

El operador fijó siete casos necesarios para cerrar la gestión del límite de salida. **Mapear comportamientos no es mapear
casos**: esta tabla dice, caso por caso, qué existe como **prueba ejecutada** y qué no.

| # | Caso exigido | Evidencia existente | Estado | Qué falta |
|---|---|---|---|---|
| 1 | Límite de salida **antes del primer perfil** | `_response` comprueba `finish_reason` **antes** de extraer y parsear contenido (`org_design.py:646-648`); `test_tool_calls_refusal_and_truncation_fail_closed` inyecta `finish_reason="length"` y exige `DesignError` | **PARCIAL** | **No hay aserción de «cero perfiles aceptados»** en ese caso: la prueba sólo exige que se lance error, no que el lote quede vacío |
| 2 | Límite **entre perfiles y dentro de un perfil/bloque** | `test_partial_failure_has_audit_but_no_partial_profiles` (auditoría sí, perfiles parciales no) + el mismo corte por `finish_reason` previo al parseo | **PARCIAL** | **No hay caso de JSON cortado a mitad de objeto/bloque** que verifique el rechazo por `invalid_json` con aserción de cero perfiles |
| 3 | Stream cortado, **con y sin** información de uso | `test_second_request_timeout_keeps_first_usage_and_unknown_aggregate`; `test_cancel_during_transport_keeps_late_usage_without_applying_design`; `test_receipts_hash_response_ids_and_missing_usage_is_null` | **CUBIERTO** | — |
| 4 | Confirmación repetida y recarga de estado: **ningún reintento automático** | `test_consent_requires_all_flags_and_no_replay`, `test_concurrent_confirmation_and_replay_cannot_rebill`, `test_doubleclick_idempotent`, `test_repeating_the_idempotency_key_does_not_duplicate_the_effect`, `test_paid_and_non_idempotent_operations_can_never_be_retried_automatically` | **CUBIERTO** | — |
| 5 | Replanificación: **aprobación anterior no reutilizada** para parámetros distintos | `test_config_change_invalidates_consent`, `test_config_change_invalidates_pending_consent_before_payment`, `test_changed_payload_endpoint_model_cap_rejects_consent`, `test_real_facade_accepts_generation_options_and_idempotency_binds_them` | **CUBIERTO** | — |
| 6 | Solicitud **compatible con los límites reales** del modelo | `test_reported_model_output_cap_changes_fixed_plan`, `test_context_and_small_cap_fail_before_network`, `test_unknown_limits_are_not_invented`, `test_output_cap_is_reported_limit_and_request_budget_remains_bounded` | **CUBIERTO** | — |
| 7 | Evidencia de que **el aviso describe fielmente** el estado observado | Lectura de `org_design.py:46` y `:648`, verificada por el capitán | **PARCIAL** | **No existe prueba ejecutada** que compare el mensaje emitido con la condición real; hoy descansa en inspección |

**Conclusión del mapeo: 4 de 7 cubiertos por pruebas ejecutadas; 3 parciales.** Los tres parciales son **requisitos de
prueba para la ola de reparación**, no hallazgos de comportamiento incorrecto: en los casos 1, 2 y 7 el comportamiento
parece correcto **por estructura del código**, pero la garantía descansa en lectura, no en aserción. Un requisito del
operador que se satisface «porque se lee en el código» no está satisfecho.

**Reproducción del mapeo:**

```
# nombres de prueba por caso
Get-ChildItem EQUIPO_ENTERPRISE_24_COUNCIL_ADN\tests_*.py | Select-String 'def (test_\w*(?:truncat|finish_reason|usage|replay|idempot|consent|limit|cap|context)\w*)'
# el truncamiento se detecta antes del parseo
engine/org_design.py:646-648   # finish_reason != stop  ->  _invalid(...)
```

## 7. Veredicto

**La capa de plataforma está integrada, empaquetada y es estructuralmente correcta; su comportamiento está probado offline.
NO puede declararse «sin regresión» ni «verde»: introduce una regresión medible y atribuible en 7 pruebas previamente
verdes por consumo del margen de un plazo fijo, y sus capacidades operativas siguen en NOT_RUN.**
El paquete no debe presentarse como «Agent OS funcionando en producción» en ninguna parte.

**Recomendación:** tratar el §3 como el hallazgo abierto de la entrega y decidir entre reducirlo, autorizar el ajuste del
plazo heredado, o declararlo limitación conocida. Mientras no se decida, la formulación correcta es la del párrafo anterior.

---

# Anexo V1-B — Reejecución independiente (`contratos`, `t10`, intento 9) sobre el árbol posterior a `t9`

**Alcance.** Este anexo **no sustituye** las secciones §0–§7: es una **reejecución independiente** sobre el árbol
**actual**, que ya no es el de 300 entradas que midió el capitán. Se conserva íntegro todo lo anterior.

## B.1 Huella de medición (política O-12)

| Campo | Valor observado |
|---|---|
| `timestamp_utc` (reloj del runner) | `2026-10-22T04:40:22Z` |
| `runner` | Python `3.12.10`, Windows-11 |
| `PYTHONUTF8` | **no definido** (`None`) |
| `paralelismo` | 1 (serial); ningún otro proceso de la suite activo durante la corrida |
| `tree_digest` | `MANIFIESTO_SHA256.txt` = `b3761de9e65321ca0f99989d9e56a0c5d584629ca7ca6907500ff60dbeb253cf` |
| `manifiesto_filas` | **360** (el informe del capitán midió 300) |
| `allowlist_entradas` | **297** (el informe del capitán midió 237) |
| `engine_py` | **70** módulos |
| `stdout_capture` | `%TEMP%\orgdna_v1b\{val.json, plat.txt}` |

**No comparable con §1.** El árbol cambió entre ambas mediciones (300 → 360 filas; 237 → 297 entradas de allowlist). Por la
política adoptada en O-12, estas dos mediciones **no se comparan entre sí**; la de este anexo describe únicamente el estado
medido.

## B.2 Matriz de esta reejecución

| # | Objeto verificado | Resultado | Evidencia ejecutada |
|---|---|---|---|
| B-1 | Validación del paquete (`validate_imports_portable.py`) | **FAIL** | `valid=False`, 2114 comprobaciones, `file_count=361`, **exit 1**; 2 errores literales: `SHA-256 no coincide: docs/security/FUSILE_SOURCE_POLICY.md` y `Catálogo documental no coincide con los archivos y sus hashes.` |
| B-2 | Suite de plataforma (`tests_platform_*.py -v`) | **FAIL (2/400)** | `Ran 400 tests` · `FAILED (failures=2)` · exit 1. Fallos con nombre completo en B.3 |
| B-3 | Cadena del manifiesto (`verifica_manifiesto.py`, herramienta del capitán) | **FAIL** | 360 entradas, **359 coinciden**, **1 diverge**, 0 faltantes, 141 exentos, **5 sobrantes reales**; `RESULTADO: FALLO` (exit 1) |
| B-4 | Comportamiento de los flujos de plataforma | **PASS (398/400)** | Las 398 pruebas restantes en verde en la misma corrida; los 2 fallos son aserciones de **integridad del manifiesto**, no de comportamiento |
| B-5 | Inventario de `t27` en disco | **PARCIAL (8/19)** | Detalle en B.4 |
| B-6 | Diferencial completo `tests_*.py` en ambos modos | **NOT_RUN** | Razón en B.5 |
| B-7 | 10 SLO del encargo y 14 falsificadores del recibo | **NOT_RUN en esta reejecución** | Razón en B.5; evidencia vigente = §2–§4 de este mismo informe |

## B.3 Causa raíz única de B-1 y B-2 (misma divergencia, cuatro manifestaciones)

Los dos fallos de la suite tienen nombre completo y la **misma** causa:

```
FAIL: test_falsifier_14_manifest_remains_intact
      (tests_platform_approval_receipt.FalsifierTests.test_falsifier_14_manifest_remains_intact)
      -> ['docs/security/FUSILE_SOURCE_POLICY.md'] != []
FAIL: test_every_manifest_entry_matches_the_file_bytes
      (tests_platform_integration.ManifestTests.test_every_manifest_entry_matches_the_file_bytes)
verifica_manifiesto.py: DIVERGE docs/security/FUSILE_SOURCE_POLICY.md
      (declarado fa23fd47abd44340 / real cf335bd5ddc7a232)
```

Es **una sola** causa: `docs/security/FUSILE_SOURCE_POLICY.md` fue editado después del sellado (la enmienda verbatim del
capitán), de modo que el manifiesto y el catálogo documental quedaron obsoletos. **No hay ninguna aserción de
comportamiento de los flujos de plataforma en rojo**, y ninguna de las 400 pruebas falla por lógica de los módulos.

## B.4 Checklist exacto de sellado para `t27` (verificado en disco ahora)

**Presentes y pendientes de sellar** (`verifica_manifiesto.py` los reporta como sobrantes reales):
`docs/rea/agile_agents_survey.md`, `docs/rea/agile_vectors.json`, `docs/rea/PANEL_SEGUIMIENTO_SPEC.md`,
`docs/rea/TEAM_API_CONTRACT_v1.md`, `qa_v7/chromium_cdp.py`.
Además, `docs/security/FUSILE_SOURCE_POLICY.md` **existe y diverge**: el resellado lo re-digiere sin más (así lo indicó el capitán).

**Presentes y ya cubiertos** (en la primera pasada no aparecían como sobrantes): `docs/PLATAFORMA_VERIFICACION_V1.md`
(exento por diseño).

**El conjunto de sobrantes NO es estable (árbol en movimiento).** Dos pasadas de `verifica_manifiesto.py` separadas por
minutos dieron **5** y luego **6** sobrantes: en la segunda apareció `engine/team_process.py`. Es la prueba de que el
árbol se está integrando mientras se verifica; `t27` debe medir sobre el árbol final, no sobre una foto intermedia.

**Todavía NO existen en disco — no pueden sellarse aún** (`t27` los añadirá a la allowlist sólo cuando existan):
`engine/team_loop.py`; `tests_team_process.py`, `tests_team_loop.py`, `tests_team_verbatim_parity.py`,
`tests_team_followups_panel.py`, `tests_sandbox_panel.py`; `docs/rea/license_audit.md`, `docs/rea/PORT_REPORT_AGILIDAD.md`;
`qa_v7/chromium_smoke.py`, `qa_v7/chromium_e2e.py`; y el directorio `docs/rea/evidence/chromium/` (no existe todavía).

**No deben entrar (respetado literalmente):** `docs/REVISION_AGILIDAD_V1.md` (lo escribe `t28` después de `t27`; hoy no
existe) y `docs/PLATAFORMA_VERIFICACION_V1.md` (exento por diseño, ver aviso de cobertura).

## B.5 Lo que esta reejecución NO pudo verificar (declarado, no asumido)

1. **Diferencial completo `tests_*.py` en ambos modos de encoding**: NOT_RUN. El árbol está **a mitad de integración de
   `t27`** y cambió durante la propia sesión de verificación (300 → 360 filas de manifiesto, 237 → 297 entradas de
   allowlist); una foto diferencial tomada ahora caduca con el sello y produciría una comparación no admisible bajo O-12.
   Debe reejecutarse **después** de `t27` (sello) y `t28` (revisión).
2. **Los 10 SLO y los 14 falsificadores del recibo**: no reejecutados por mí en este intento. La evidencia vigente es la
   de §2–§4 de este informe (árbol de 300 entradas) y las sondas de los intentos previos; **no la reatribuyo** al árbol actual.
3. **`qa_v7 dsh_baseline`**: no reejecutado; su precondición (archivos pineados sin cambios) no se cumple en un árbol que
   está siendo integrado.

## B.6 Veredicto de la reejecución

**FAIL — BLOCKED por integración pendiente.** En el instante medido el paquete **no es válido**:
`validate_imports_portable.py` devuelve `valid=False` (exit 1) y `verifica_manifiesto.py` devuelve `FALLO` con
1 divergencia y 5 sobrantes. **No es una regresión de los seis flujos de plataforma** —398 de 400 pruebas en verde, y los
2 fallos son aserciones de integridad del manifiesto— sino la consecuencia esperada de que `t27` (allowlist + resellado)
todavía no se ha ejecutado y de la edición del capitán en `FUSILE_SOURCE_POLICY.md`.

**Condición de desbloqueo:** `t27` debe cerrar `0 divergencias / 0 faltantes / 0 sobrantes` y, sobre el árbol final,
reejecutarse esta verificación (ambos modos de encoding) antes de cualquier entrega o sellado. Hasta entonces **no debe
presentarse el paquete como válido ni como entregable**.
