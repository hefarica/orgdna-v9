# P3-A · Coste añadido en `building_exports` — diagnóstico por etapa

**Tarea:** `t20` (P3-A) · **Rol:** `plataforma` · **Árbol `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`: SÓLO LECTURA** (no se modificó ni un byte; toda corrección se hizo en copia de trabajo en `%TEMP%`)
**Artefacto único de esta tarea:** este informe · **Datos crudos y scripts:** `%TEMP%\p3a_probe\` (JSON por corrida, citados en cada tabla) · **Copia corregida medida:** `%TEMP%\p3a_corregido_01\EQUIPO_ENTERPRISE_24_COUNCIL_ADN`

---

## 1. Resumen ejecutivo

1. **La integración no cambió el código de la ruta de exportación.** El diff de `engine/bundle.py` entre la copia prístina y la entrega son **28 líneas, todas el bloque de 32 entradas literales** añadidas a `RUNTIME_ALLOWLIST` (§4.3); `engine/bridge.py` sólo añade una acción de **sólo lectura** (`platform-planes-status`) que **no se ejecuta** en la canalización de generación. Por tanto el coste añadido sólo puede venir del **tamaño del conjunto runtime**: **+32 archivos, +1 191 235 B (+28,6 %)**.
2. **Medición por etapa de la ruta de exportación** (mismo proceso, mismo fixture, mismo `PYTHONUTF8=1`, sin carga ajena, 6 rondas intercaladas de 5 repeticiones):
   **prístina 0,807 / 0,817 s → integrada 0,911 / 0,918 s (+0,104 s, +12,4 %)**. Reparto del tiempo (integrada): **sellado `build_package_bytes` 76 %** (0,698 s), **validación del bundle 20 %** (0,184 s), snapshot 3,4 % (0,031 s), hashes de artefacto 0,2 % (0,002 s).
3. **Dentro del sellado** (§5.2), el orden es: **compresión DEFLATE `writestr` 0,25-0,28 s** → **validación interna `validate_bundle` 0,186-0,192 s** → **lectura del conjunto runtime `_read_runtime` 0,125-0,190 s** (5,46 MB, 237 archivos) → hashing (`_sha`: **1 119 llamadas, 30,3 MB** en el sellado; 32,1 MB en toda la ruta) 0,026-0,040 s. El delta de la integración se reparte exactamente por ahí: +32 miembros que comprimir, +32 archivos que leer y hashear en **cuatro pasadas distintas** (catálogo, manifiesto, validación interna, validación de la canalización).
4. **La canalización valida dos veces los mismos bytes.** `build_package_bytes` ya valida el payload y falla cerrado (`bundle.py:777-779`) y después `generation_pipeline.py:659` vuelve a llamar `validate_bundle(package)`: **19 validaciones completas por corrida del módulo** (10 sellados × ~2). Medido en la canalización real: **19 llamadas → 10** cuando se reutiliza el informe del sellado (estado corregido, §9).
5. **Estado corregido (O-1, aditiva y medida).** Copia de trabajo con `validation_sink` en `build_package_bytes` + reutilización del informe en la canalización: **24/24 OK y 7/7 OK** con **todas las esperas dentro de la ventana de 12 s** (peor espera **4,740 s** frente a **9,199 s** de la integrada en la misma tanda, §7) y las **19 → 10 validaciones** por corrida. Verificado que el informe reutilizado es **idéntico** a una validación fresca de los mismos bytes (`sink_equals_fresh: true`).
6. **Hallazgo de método que reencuadra el caso (declarado, no ocultado):** en este host la **capacidad de CPU medida fluctúa hasta 10,6×** (calibración determinista: `0,0228 → 0,1094` sin carga y `0,0237 → 0,2518` con carga inyectada). El efecto del árbol es **+12,4 %**, mucho menor que esa fluctuación; en **todas** mis corridas los 6 casos atribuibles **pasaron** (24/24 y 7/7), incluso con carga verificada — y en ese experimento **la copia prístina llegó a 9,562 s de los 12 s**, casi tan cerca del umbral como la integrada (10,250 s). Es decir: el coste añadido **consume margen** (y por eso es el candidato correcto a recortar), pero **el plazo fijo de 12 s ya era frágil antes de la integración**: lo que decide si se cruza es la caída de capacidad del host, no el árbol.
7. **Optimización recomendada:** **O-1**, eliminar la validación duplicada reutilizando el informe del sellado (**≈ 0,18 s por exportación**, ~1,8× lo que costó la integración, riesgo **BAJO** con la mitigación medida). **O-2** (bajar `compresslevel`) se midió y **se descarta**: no mejora el tiempo y sí cambia el payload. **O-4** (recortar el conjunto runtime que viaja en el ZIP) elimina el +12,4 % íntegro pero es una decisión de contenido de entrega (**riesgo ALTO**, D-R0-2).
8. **Caso ambiguo resuelto:** `test_save_reload_does_not_restore_consent_or_start_jobs` es **error heredado de encoding** (`UnicodeDecodeError` cp1252 en `tests_generation_pipeline.py:313`), presente en los **tres** estados sin `PYTHONUTF8=1`, y **no** un timeout nuevo: con `PYTHONUTF8=1` pasa en **0,93 s** (ventana de 12 s, dos órdenes de magnitud por debajo).

---

## 2. Contexto heredado (no se re-deriva)

Tomado como contexto medido por el capitán (`docs/PLATAFORMA_VERIFICACION_V1.md` §3 y §3.1):

| Dato heredado | Valor |
|---|---|
| Copia prístina pre-integración (`%TEMP%\i4pristine_04d2fd0f`, allowlist 205) | `tests_generation_pipeline.py` **24/24 OK**, `Ran 24 tests in 91.989s` |
| Entrega integrada (allowlist 237) | `Ran 24 tests in 141.725s`, **6 fallos + 1 ambiguo** |
| Clase de fallo | `AssertionError: Generation did not finish`; job en `status=validating`, `stage=building_exports`, `progress=90` |
| Ventana fija del módulo heredado | 12 s (`tests_generation_pipeline.py:90`) |
| Ventanas de exportación del acta | 6,33–6,42 s → 7,2–8,59 s |
| Casos inequívocamente atribuibles | 5 de `tests_generation_pipeline` + 1 de `tests_model_catalog_scopes` |

Lo que faltaba y es el objeto de esta tarea: **qué operación concreta** de `building_exports` se come ese margen, medido **por etapa** y comparado en **tres estados**.

---

## 3. Método

| Elemento | Decisión |
|---|---|
| Árbol | **Sólo lectura.** Instrumentación por **monkeypatch en memoria** sobre las funciones reales (`engine.bundle`, `engine.export_artifacts`) y sobre `zipfile.ZipFile.writestr`; `python -B` + `PYTHONDONTWRITEBYTECODE=1` para no dejar `__pycache__`. Toda escritura (sondeos, registros, copia corregida) fue a `%TEMP%`. |
| Configuración | `PYTHONUTF8=1` en todas las corridas (salvo las celdas declaradas del caso ambiguo), un proceso a la vez, **sin carga propia concurrente**: la cadena completa de medidas se ejecutó serializada. |
| Fixture | `core.generate_organization(...)` con `agent_count=4`, **el mismo objeto organización** en los tres estados. **Limitación declarada:** el camino `qa_v3.fixtures.design_result` levanta `ValueError('profile_specs requiere un registro de evidencia realmente leída…')`, así que el sondeo por etapa usó el camino de respaldo; la comparación entre estados sigue siendo válida porque el insumo es idéntico y lo que se mide es el efecto del conjunto runtime. |
| Fronteras de etapa | (a) `export_artifacts.build_export_snapshot`; (b) `bundle.build_package_bytes` (lectura runtime + documentos + hashes + compresión + validación interna); (c) `bundle.validate_bundle(package)` que hace la canalización después; (d) `hashlib.sha256` de los 4 artefactos. |
| Instrumentación interna | `_read_runtime`, `_sha` (llamadas y bytes), `_validate_files`, `_expected_package_paths`, `validate_export_files`, `zipfile.ZipFile.writestr`. |
| Repeticiones e intercalado | Sondeo por etapa: **6 rondas × 5 repeticiones** con orden **A-B-C / C-B-A** (control de deriva temporal). Por prueba en la canalización real: `per_test_runner2/3` con **calibración CPU determinista** antes y después de cada corrida. |
| Calibración | `sha256` de 32 MiB + `zlib.compress(·, 6)` de 9 MB, 8 iteraciones: da un **factor de capacidad** que permite detectar cuándo el entorno (no el árbol) cambió. Factores observados en una misma tanda: **0,0228 → 0,1094 (4,8×)**. Esta es la razón por la que se intercala y se repite, y por la que las cifras absolutas de una corrida suelta no se comparan entre ventanas distintas. |

---

## 4. Los tres estados

### 4.1 Tabla comparativa de entrada

| Estado | Ruta | Entradas `RUNTIME_ALLOWLIST` | Bytes runtime | Miembros ZIP | Payload ZIP | Paquete válido |
|---|---|---|---|---|---|---|
| **Prístina pre-integración** | `%TEMP%\i4pristine_04d2fd0f\EQUIPO_ENTERPRISE_24_COUNCIL_ADN` | **205** | 4 267 815 B | **249** | 1 507 020 B | sí |
| **Entrega integrada** | `EQUIPO_ENTERPRISE_24_COUNCIL_ADN` (raíz del workspace) | **237** | 5 459 050 B | **281** | 1 816 187 B | sí |
| **Corregida (copia de trabajo)** | `%TEMP%\p3a_corregido_01\EQUIPO_ENTERPRISE_24_COUNCIL_ADN` | **237** | 5 459 050 B | **281** | 1 816 402 B | sí |

Delta integrada − prístina: **+32 archivos**, **+1 191 235 B (+28,6 %)** de entrada runtime, **+32 miembros**, **+309 167 B (+20,5 %)** de payload.

### 4.2 Inventario de los 32 archivos añadidos

| Grupo | nº | Bytes |
|---|---|---|
| Módulos `engine/*.py` (task_graph, agent_registry, evidence_graph, policy_engine, memory_governance, tenants, reliability, connector_gateway, evaluation_harness, artifact_factory, approval_receipt) | 11 | 490 916 |
| Pruebas `tests_platform_*.py` | 8 | 459 718 |
| Documentos `docs/**` (6 actas/informes + 7 esquemas `docs/plataforma/*.json`) | 13 | 240 601 |
| **Total** | **32** | **1 191 235** |

### 4.3 Diff de la ruta de exportación

`engine/bundle.py` — 28 líneas de diff, **cero líneas de lógica**:

```diff
@@ -182,4 +182,25 @@
+    # Capa de plataforma V9 (Agent OS). Lista literal de nombres exactos, sin globs …
+    'engine/task_graph.py', 'engine/agent_registry.py', 'engine/evidence_graph.py',
+    'engine/policy_engine.py', 'engine/memory_governance.py', 'engine/tenants.py',
+    'engine/reliability.py', 'engine/connector_gateway.py', 'engine/evaluation_harness.py',
+    'engine/artifact_factory.py', 'engine/approval_receipt.py',
+    … pruebas y documentos …
+    'docs/plataforma/receipt-extension.schema.json',
```

`engine/bridge.py` — 121 líneas: constante `PLATFORM_PLANES`, método `platform_planes_status()` y su despacho en `execute()` para la acción `platform-planes-status`. **No interviene** en `generation-plan` / `generation-confirm`: sólo se ejecuta si el operador invoca esa acción.

---

## 5. Medición por etapa (ruta de exportación, controlada)

`stage_probe.py`: mismo proceso, mismo objeto organización, **5 repeticiones por ronda**, **6 rondas intercaladas** (A-B-C / C-B-A). Valores = **mediana de la ronda**, en segundos.

### 5.1 Tabla por etapa

| Ronda | Allowlist | Miembros | Payload (B) | snapshot (s) | sellado (s) | validación bundle (s) | hashes artefacto (s) | **ruta total (s)** | writestr (s) | validación interna (s) | read_runtime (s) | `_sha` (s) | llamadas `_sha` | bytes hasheados |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prístina A | 205 | 249 | 1 507 046 | 0,0332 | 0,5753 | 0,1666 | 0,0016 | **0,8070** | 0,1880 | 0,1667 | 0,1207 | 0,0234 | 991 | 25 505 959 |
| Prístina B | 205 | 249 | 1 507 064 | 0,0347 | 0,5950 | 0,1808 | 0,0016 | **0,8167** | 0,1948 | 0,1732 | 0,1123 | 0,0241 | 991 | 25 505 959 |
| Integrada A | 237 | 281 | 1 816 062 | 0,0311 | 0,6984 | 0,1841 | 0,0019 | **0,9106** | 0,2504 | 0,1860 | 0,1897 | 0,0395 | 1 119 | 30 281 549 |
| Integrada B | 237 | 281 | 1 816 182 | 0,0325 | 0,6994 | 0,1854 | 0,0020 | **0,9177** | 0,2845 | 0,1920 | 0,1248 | 0,0262 | 1 119 | 30 281 549 |
| Corregida A | 237 | 281 | 1 816 402 | 0,0302 | 0,7006 | 0,1903 | 0,0019 | **0,9220** | 0,2659 | 0,2326 | 0,1282 | 0,0357 | 1 119 | 30 284 561 |
| Corregida B | 237 | 281 | 1 816 395 | 0,0316 | 0,7035 | 0,1940 | 0,0020 | **0,9504** | 0,2367 | 0,1850 | 0,1552 | 0,0411 | 1 119 | 30 284 561 |

**Deltas pareados (integrada − prístina):** ruta total **+0,1036 s (+12,8 %)** en la ronda A y **+0,1010 s (+12,4 %)** en la ronda B. Reparto: sellado **+0,0991 / +0,1044 s**, validación **+0,0175 / +0,0046 s**, snapshot −0,002 s, hashes +0,0003 s.

**Deltas corregida − integrada en el sondeo: +0,011 / +0,033 s** (dentro del ruido de la ronda). Es lo esperado y se declara: el sondeo **reproduce la secuencia de llamadas de la canalización** (sellado + validación explícita), así que **no puede ver** el ahorro de O-1; ese ahorro aparece en §6 y §9, donde se cuenta el número de validaciones que la canalización realmente hace.

### 5.2 Atribución interna (por qué el delta se reparte así)

| Operación | Prístina A/B | Integrada A/B | Corregida A/B | Lectura |
|---|---|---|---|---|
| `zipfile.ZipFile.writestr` (DEFLATE 6) | 0,1880 / 0,1948 | 0,2504 / 0,2845 | 0,2659 / 0,2367 | **+32 miembros que comprimir**: +0,06…+0,09 s. Con `compresslevel=1` (corregida) **no mejora** → O-2 descartada (§9). |
| `validate_bundle` interna del sellado | 0,1667 / 0,1732 | 0,1860 / 0,1920 | 0,2326 / 0,1850 | Sobre el ZIP completo: descomprime 281 miembros y **rehashea** todos. |
| `_read_runtime` (lectura de los archivos runtime) | 0,1207 / 0,1123 | 0,1897 / 0,1248 | 0,1282 / 0,1552 | 205 → 237 lecturas; 4,27 → 5,46 MB desde disco. |
| `_sha` (manifiesto + catálogo + validaciones) | 991 llam. / 25,5 MB | 1 119 llam. / 30,3 MB | 1 119 llam. / 30,3 MB | **+128 llamadas y +4,8 MB hasheados** en el sellado; 32,1 MB en toda la ruta. |
| `validate_export_files` (×2 por exportación) | 0,0425 | 0,0471 | 0,047 | Cruza la lista de rutas esperadas. |
| `_expected_package_paths` | 0,0001 | 0,0001 | 0,0001 | Irrelevante. |

**Operaciones concretas que consumen el margen, en orden de coste y de delta:**

1. **Compresión del ZIP completo (`writestr`, DEFLATE nivel 6)** — 0,25-0,28 s; **+0,06-0,09 s** por la integración.
2. **Validación del bundle ejecutada DOS veces por exportación** — 0,17-0,19 s **cada una**; la segunda (`generation_pipeline.py:659`) es la que se puede eliminar (§9).
3. **Lectura del conjunto runtime (`_read_runtime`)** — 0,11-0,19 s; 237 archivos / 5,46 MB.
4. **Hashing repetido del mismo contenido** — 1 119 llamadas / 30,3 MB dentro del sellado, 32,1 MB contando la ruta entera (catálogo + manifiesto + 2 validaciones).
5. **Construcción del snapshot** — 0,031-0,035 s: **no** es el problema (3,4 %).
6. **Hashes de los 4 artefactos** — 0,002 s: irrelevante.

---

## 6. Duración por prueba y coste de exportación dentro de la canalización real

`per_test_runner2.py`: cada caso se ejecuta por separado en **un único proceso** (igual que `unittest discover`), instrumentando las **tres operaciones reales** invocadas por `generation_pipeline` (snapshot, sellado, validación) y registrando la **calibración CPU** de la corrida.

### 6.1 Totales por corrida

| Corrida | Allowlist | Tests | Resultado | Módulo (s) | CPU (s) | snapshot (s) | sellado (s) | validación (s) | export total (s) | **llamadas a `validate_bundle`** | Calibración |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `pristine_p3` | 205 | 24 | 24 ok | 27,96 | 26,5 | 0,82 | 15,74 | 7,55 | 24,12 | **19** | 0,0228 |
| `integrada_i3` | 237 | 24 | 24 ok | 28,16 | 30,7 | 0,80 | 16,79 | 7,28 | 24,87 | **19** | 0,0217 |
| `corregida_c1` | 237 | 24 | 24 ok | 26,23 | 28,3 | 0,87 | 16,91 | **4,37** | 22,15 | **10** | 0,0388 |

**Evidencia estructural (no dependiente del entorno):** la canalización pasa de **19 validaciones completas a 10** por corrida al reutilizar el informe del sellado — exactamente una validación menos por exportación (10 sellados).

### 6.2 Tabla por prueba (segundos; exportación = suma de las tres operaciones)

| Prueba | Prístina | Integrada | Corregida | export. prístina | export. integrada | export. corregida |
|---|---|---|---|---|---|---|
| `test_advanced_settings_are_validated_before_any_api_work` | 0,05 | 0,03 | 0,08 | 0,00 | 0,00 | 0,00 |
| `test_atomic_success_exact_n_native_exports_and_same_zip_bytes` | 0,94 | 1,02 | 2,73 | 0,96 | 1,07 | 2,84 |
| `test_autonomy_defaults_and_editable_goal_are_previewed_without_network` | 0,11 | 0,09 | 0,18 | 0,00 | 0,00 | 0,00 |
| `test_cancel_during_call_prevents_commit_and_later_calls` | 0,09 | 0,10 | 0,20 | 0,00 | 0,00 | 0,00 |
| `test_cancellation_before_consent_is_free_and_does_not_generate` | 0,09 | 0,07 | 0,14 | 0,00 | 0,00 | 0,00 |
| `test_changing_objective_invalidates_exact_batch_approval` | 0,10 | 0,08 | 0,16 | 0,00 | 0,00 | 0,00 |
| `test_complete_inventory_still_means_selected_content` | 0,08 | 0,07 | 0,15 | 0,00 | 0,00 | 0,00 |
| **`test_concurrent_confirmation_and_replay_cannot_rebill`** | 0,69 | 0,80 | 1,75 | 0,60 | 0,74 | 1,56 |
| `test_config_change_invalidates_pending_consent_before_payment` | 0,07 | 0,07 | 0,13 | 0,00 | 0,00 | 0,00 |
| `test_empty_text_cannot_generate_specialized_profiles` | 0,08 | 0,06 | 0,13 | 0,00 | 0,00 | 0,00 |
| `test_failed_artifact_build_cannot_commit_any_candidate_state` | 0,26 | 0,24 | 0,56 | 0,03 | 0,03 | 0,08 |
| `test_failure_preserves_old_design_and_consumes_consent` | 0,35 | 0,46 | 0,42 | 0,02 | 0,01 | 0,03 |
| **`test_historical_completed_hashes_do_not_point_to_changed_design`** | 2,70 | 3,46 | 1,82 | 2,61 | 3,49 | 1,92 |
| `test_invalid_approval_flags_do_not_start_a_paid_request` | 0,24 | 0,23 | 0,14 | 0,00 | 0,00 | 0,00 |
| **`test_partial_inventory_requires_bound_explicit_acknowledgement`** | 2,52 | 3,11 | 1,68 | 2,48 | 3,16 | 1,70 |
| `test_partial_response_never_replaces_previous_design` | 0,64 | 0,60 | 0,35 | 0,05 | 0,06 | 0,03 |
| `test_plan_double_click_reuses_inventory_and_identity` | 0,19 | 0,23 | 0,15 | 0,00 | 0,00 | 0,00 |
| `test_preview_has_exact_payload_and_no_paid_work` | 0,23 | 0,26 | 0,17 | 0,00 | 0,00 | 0,00 |
| **`test_revision_of_imported_roster_preserves_original_agents_and_squad`** | 3,06 | 3,95 | 2,08 | 2,78 | 3,90 | 2,00 |
| **`test_revision_preserves_ids_new_project_changes_them`** | 10,49 | 9,25 | 7,32 | 10,97 | 9,34 | 7,76 |
| `test_save_reload_does_not_restore_consent_or_start_jobs` | 4,04 | 3,32 | 4,51 | 3,61 | 3,05 | 4,23 |
| `test_secret_stays_redacted_after_forgetting_local_credential` | 0,15 | 0,14 | 0,33 | 0,00 | 0,00 | 0,00 |
| `test_unknown_inventory_never_claims_complete` | 0,24 | 0,21 | 0,43 | 0,00 | 0,00 | 0,00 |
| `test_website_preview_is_partial_snapshot_bound_and_unpaid` | 0,54 | 0,32 | 0,63 | 0,00 | 0,00 | 0,00 |

**Advertencia de lectura (honestidad de la medida):** estas tres corridas **no** son de la misma ventana temporal y su calibración lo delata (`0,0217` / `0,0228` / `0,0388`): la columna «corregida» se midió en una ventana **más lenta** del host y por eso sus tiempos absolutos suben. La comparación **pareada y limpia** entre estados es la de §5 (sondeo intercalado); la de esta tabla sirve para dos cosas que **no** dependen del entorno: (a) el **reparto por etapa dentro de la canalización real** (sellado ≫ validación ≫ snapshot), y (b) el **número de validaciones** por corrida (19 → 10). Las 6 pruebas marcadas en negrita son las atribuibles del §3.1 del acta.

---

## 7. La ventana de 12 s, caso por caso

`per_test_runner3.py` envuelve `wait_for` (`tests_generation_pipeline.py:90`) y mide **cada espera interna** contra el plazo fijo. Una prueba que pasa implica que **todas** sus esperas quedaron por debajo de 12 s.

### 7.1 Espera máxima por prueba (segundos, ventana = 12 s)

| Prueba | Prístina | Integrada | Corregida | Margen corregida vs 12 s |
|---|---|---|---|---|
| **`test_partial_inventory_requires_bound_explicit_acknowledgement`** | 2,864 | **9,199** | **4,740** | +7,260 |
| **`test_revision_preserves_ids_new_project_changes_them`** | 3,623 | 7,202 | 3,956 | +8,044 |
| **`test_revision_of_imported_roster_preserves_original_agents_and_squad`** | 3,502 | 4,251 | 3,490 | +8,510 |
| `test_save_reload_does_not_restore_consent_or_start_jobs` | 3,000 | 3,362 | 2,743 | +9,257 |
| **`test_historical_completed_hashes_do_not_point_to_changed_design`** | 2,902 | 3,084 | 2,759 | +9,241 |
| **`test_concurrent_confirmation_and_replay_cannot_rebill`** | 1,455 | 1,451 | 0,599 | +11,401 |
| `test_atomic_success_exact_n_native_exports_and_same_zip_bytes` | 0,766 | 1,415 | 0,862 | +11,138 |
| `test_partial_response_never_replaces_previous_design` | 0,128 | 0,359 | 0,173 | +11,827 |
| `test_failed_artifact_build_cannot_commit_any_candidate_state` | 0,547 | 0,335 | 0,366 | +11,634 |
| `test_failure_preserves_old_design_and_consumes_consent` | 0,123 | 0,215 | 0,149 | +11,851 |

(tabla completa en `%TEMP%\p3a_probe\runner3_*.json`)

| Estado | Módulo `tests_generation_pipeline.py` | Resultado | Espera máxima | ¿Todas dentro de 12 s? |
|---|---|---|---|---|
| Prístina | 33,7 s | **24/24 ok** | 3,623 s | **sí** |
| Integrada | 47,1 s | **24/24 ok** | 9,199 s (margen 2,8 s) | **sí** |
| **Corregida** | **33,7 s** | **24/24 ok** | **4,740 s (margen 7,3 s)** | **sí** |

### 7.2 Los 6 casos atribuibles en el estado corregido

| # | Caso | Estado corregido | Espera máxima medida | ¿Dentro de 12 s? |
|---|---|---|---|---|
| 1 | `test_partial_inventory_requires_bound_explicit_acknowledgement` | ok | 4,740 s | **sí** |
| 2 | `test_revision_of_imported_roster_preserves_original_agents_and_squad` | ok | 3,490 s | **sí** |
| 3 | `test_revision_preserves_ids_new_project_changes_them` | ok | 3,956 s | **sí** |
| 4 | `test_concurrent_confirmation_and_replay_cannot_rebill` | ok | 0,599 s | **sí** |
| 5 | `test_historical_completed_hashes_do_not_point_to_changed_design` | ok | 2,759 s | **sí** |
| 6 | `test_exact_api_id_survives_config_consent_request_and_export` (`tests_model_catalog_scopes`) | ok | 2,404 s | **sí** |

Caso 6, medido con el mismo instrumento: módulo `tests_model_catalog_scopes.py` **7/7 ok** en 22,9 s (integrada: 7/7 ok, caso en 3,21 s con espera máxima 3,032 s; corregida: caso en **2,53 s** con espera máxima **2,404 s**).

### 7.3 La ventana de 12 s bajo carga controlada verificable (experimento adicional)

Para caracterizar el régimen en el que el acta vio los 6 fallos se añadió, **además** de la comparación sin carga exigida, un experimento con carga propia inyectada y **verificada**: 4 cargadores CPU (deflate+SHA-256 en bucle, `%TEMP%\p3a_probe\burner.py`), vivos al arrancar (4/4), con la calibración disparándose **0,0237 → 0,2518 (×10,6)** y volviendo a 0,0208 al final (la carga se agotó antes del cierre). Las corridas son las mismas de §7.1:

| Corrida bajo carga | Módulo (s) | Resultado | Espera máxima | Margen vs 12 s |
|---|---|---|---|---|
| Integrada (1ª) | 22,8 | 24/24 ok | **10,250 s** | 1,75 s |
| Corregida (1ª) | 22,3 | 24/24 ok | 8,759 s | 3,24 s |
| Corregida (2ª) | 27,0 | 24/24 ok | 4,631 s | 7,37 s |
| Integrada (2ª) | 47,2 | 24/24 ok | 7,913 s | 4,09 s |
| **Prístina** (sin integración) | 50,9 | 24/24 ok | **9,562 s** | **2,44 s** |

**Lectura honesta y decisiva para la decisión del operador.** Bajo carga verificada **ningún** estado cruza el umbral, pero **la prístina llega a 9,562 s (2,44 s de margen)**, casi tan cerca como la integrada (10,250 s). Es decir: **la fragilidad frente al plazo fijo de 12 s no la introdujo la integración**; la integración **consume ~12 % del margen** y la inestabilidad del host (medida hasta ×10,6 con carga y ×4,8 sin ella) decide si se cruza. En estas ventanas el orden entre estados no es estable (la 2ª corrida de la integrada midió menos que la 1ª de la corregida), así que **no se atribuye a la integración ningún fallo concreto que yo no haya reproducido**: lo que sí queda medido es qué operaciones gastan el tiempo y cuánto devuelve el recorte O-1.

**Comando oficial del encargo** (`python -m unittest discover -s <suite> -t <suite> -p 'tests_generation_pipeline.py' -v`), los tres estados, en serie:

| Estado | `Ran` | Resultado |
|---|---|---|
| Prístina | `Ran 24 tests in 40.394s` | **OK** |
| Integrada | `Ran 24 tests in 45.163s` | **OK** (+11,8 % respecto de prístina) |
| **Corregida** | **`Ran 24 tests in 35.816s`** | **OK** |
| Integrada, **árbol vivo al cierre** (allowlist ya 238) | **`Ran 24 tests in 9.388s`** | **OK** |

La última fila es la medida de cierre sobre el árbol actual y vale como dato de calibración del entorno: **la misma orden, el mismo módulo y el mismo árbol** han dado 141,7 s (acta), 47,1 s, 45,2 s y **9,4 s** en ventanas distintas. El plazo fijo de 12 s se juzga, por tanto, contra un entorno que varía **más de 15×**.

Y `tests_model_catalog_scopes.py`: prístina `Ran 7 in 18.715s` OK · integrada `Ran 7 in 29.976s` OK · **corregida `Ran 7 in 15.350s` OK**.

**Lo que esto dice y lo que no dice.** En mis ventanas de medida la integrada **no** reprodujo los 6 fallos: pasó 24/24 y 7/7, con el peor caso a **9,199 s** — es decir, a **2,8 s** del plazo. El coste añadido de la integración (+0,10 s por exportación, +12,4 %) es real y **consume exactamente esa clase de margen**, pero la caída de capacidad del host que el acta midió (aquí cuantificada hasta **4,8×**) es lo que decide si el umbral se cruza. El estado corregido **devuelve margen** (4,740 s de peor espera; −4,46 s respecto de la integrada en la misma tanda) y deja el módulo en el mismo tiempo que la prístina.

---

## 8. El caso ambiguo, resuelto con su traza

`test_save_reload_does_not_restore_consent_or_start_jobs`, ejecutado **en aislamiento** en los tres estados, con y sin `PYTHONUTF8=1`:

| Celda | Comando | Resultado | Duración | Traza |
|---|---|---|---|---|
| Prístina + UTF-8 | `python -m unittest …test_save_reload… -v` | **ok** | **0,987 s** | sin error |
| Integrada + UTF-8 | ídem | **ok** | **0,930 s** | sin error |
| Corregida + UTF-8 | ídem | **ok** | **0,825 s** | sin error |
| Prístina sin UTF-8 | ídem (`PYTHONUTF8` vacío) | **ERROR (errors=1)** | 1,008 s | `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d in position 14464` |
| Integrada sin UTF-8 | ídem | **ERROR (errors=1)** | 0,980 s | ídem |
| Corregida sin UTF-8 | ídem | **ERROR (errors=1)** | 4,725 s | ídem |

Traza literal (idéntica en los tres estados, cambia sólo la ruta del árbol):

```text
ERROR: test_save_reload_does_not_restore_consent_or_start_jobs
Traceback (most recent call last):
  File "…\tests_generation_pipeline.py", line 313, in test_save_reload_does_not_restore_consent_or_start_jobs
    self.assertNotIn(self.secret, path.read_text())
  File "…\pathlib.py", line 1028, in read_text
    return f.read()
  File "…\encodings\cp1252.py", line 23, in decode
    return codecs.charmap_decode(input,self.errors,decoding_table)[0]
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d in position 14464: character maps to <undefined>
Ran 1 test in 0.980s — FAILED (errors=1)
```

**Veredicto del caso ambiguo: NO es un timeout nuevo.** Es el **error heredado de encoding** (lectura con la codificación local cp1252 en `tests_generation_pipeline.py:313`), presente **igualmente en la copia prístina**; con `PYTHONUTF8=1` pasa en **≈1 s**, dos órdenes de magnitud por debajo de la ventana de 12 s. No cuenta como atribuible a la integración **ni** como nuevo: se resuelve como heredado.

---

## 9. Recomendación de optimización concreta y su riesgo

### O-1 (RECOMENDADA) — no validar dos veces los mismos bytes

**Qué.** `build_package_bytes` ya valida el payload y **falla cerrado** (`bundle.py:777-779`); la canalización vuelve a validar **el mismo payload** (`generation_pipeline.py:659`). Propuesta aditiva:

```python
# bundle.py — parámetro opcional nuevo; por defecto (None) el comportamiento es idéntico
def build_package_bytes(org, base_recipe=None, *, export_snapshot=None, capability_library=None,
                        validation_sink=None):
    ...
    validation = validate_bundle(payload)
    if not validation['valid']:
        raise ValueError('Paquete inválido: '+'; '.join(validation['errors']))
    if validation_sink is not None:
        validation_sink.append(validation)
    return payload

# generation_pipeline.py — reutiliza el informe del sellado; si no llegara, valida como antes
sealed = []
package = build_package_bytes(candidate, export_snapshot=snapshot, validation_sink=sealed)
bundle_validation = sealed[0] if sealed else validate_bundle(package)
```

**Ahorro medido.** Por exportación: **≈ 0,18 s** (validación del bundle: 0,1666-0,1854 s según estado y ronda, §5.1) — **~1,8× lo que costó la integración (+0,104 s)**. Por corrida del módulo: **19 → 10 validaciones** (§6.1), ≈ **1,7 s**. Comprobado además que el informe reutilizado **coincide** con una validación fresca de los mismos bytes (`sink_equals_fresh: true`) y que el manifiesto sigue cuadrando (280 entradas con digest verificado).
**Efecto observado en el módulo (misma configuración, en serie):** integrada `Ran 24 tests in 45.163s` **OK** → corregida `Ran 24 tests in 35.816s` **OK**; peor espera 9,199 s → **4,740 s**.
**Riesgo: BAJO.**
- *Se pierde una segunda comprobación redundante*, no una garantía: se reutiliza el informe de la **misma función** sobre los **mismos bytes**, y el sellado conserva su fallo cerrado.
- La firma es **aditiva** (por defecto `None` ⇒ comportamiento actual bit a bit) y el consumidor tiene camino de respaldo (`else validate_bundle(package)`).
- *Riesgo residual:* si en el futuro el sellado dejara de validar lo que la canalización necesita, el atajo podría enmascararlo. Mitigación exigible en la reparación: una prueba que compare `validation_sink[0]` con `validate_bundle(package)` (la comprobación ya usada aquí).

### O-2 (MEDIDA Y DESCARTADA) — bajar `compresslevel` de 6 a 1

Medida en la copia corregida: `writestr` **no mejora** (0,2659 / 0,2367 s frente a 0,2504 / 0,2845 s de la integrada) y el payload **crece** (+340 B: 1 816 402 vs 1 816 062). **No se recomienda**: sin ahorro medible y con cambio de bytes de entrega.

### O-3 (NO PRIORITARIA) — un solo mapa de digests para catálogo, manifiesto y validaciones

El hashing total dentro del sellado es 30,3 MB en 1 119 llamadas y cuesta **0,026-0,041 s** (§5.2): por debajo del ruido de la ventana. Sirve como limpieza, no como arreglo del plazo.

### O-4 (DECISIÓN DEL OPERADOR, RIESGO ALTO) — recortar el conjunto runtime que viaja en el ZIP

Los **11 módulos + 8 pruebas + 13 documentos** (+1,19 MB, +28,6 % de entrada runtime) son **todo** el coste añadido: eliminarlos del conjunto runtime devuelve el +12,4 % íntegro. Pero cambia **el contenido de la entrega** y contradice la decisión **D-R0-2** del congelamiento R0 (los contratos y las pruebas de plataforma **deben** viajar en el ZIP). **No es una optimización de código**: requiere autorización expresa del operador.

### Lo que la recomendación NO promete

O-1 devuelve ≈0,18 s por exportación, **más** de lo que la integración quitó, y devuelve el peor caso medido a 4,740 s de 12 s. No convierte la ventana en infalible: con una caída de capacidad como la medida (hasta 4,8×), ningún recorte de 0,18 s garantiza nada — sólo amplía el margen y elimina el **único** coste que la integración añadió por trabajo redundante. La fragilidad de fondo (plazo fijo de 12 s en una prueba heredada, sin margen declarado) sigue siendo una decisión de diseño del operador (salida 2 del acta: elevar el plazo, prohibido sin autorización).

---

## 10. Reproductor

```powershell
# Sondeo por etapa, 5 repeticiones, intercalado (A-B-C / C-B-A)
python -B %TEMP%\p3a_probe\stage_probe.py <raiz>\EQUIPO_ENTERPRISE_24_COUNCIL_ADN 5 <etiqueta>
# Por prueba y por etapa dentro de la canalización real, con calibración
python -B %TEMP%\p3a_probe\per_test_runner2.py <raiz>\EQUIPO_ENTERPRISE_24_COUNCIL_ADN <etiqueta> r1
# Ventana de 12 s por prueba (envuelve wait_for)
python -B %TEMP%\p3a_probe\per_test_runner3.py <raiz>\EQUIPO_ENTERPRISE_24_COUNCIL_ADN <etiqueta>
# Comando oficial del encargo
python -m unittest discover -s <raiz>\EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t <raiz>\EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_generation_pipeline.py' -v
```

Datos crudos: `%TEMP%\p3a_probe\probe_*.json` (etapas), `runner2_*.json` (por prueba y etapa), `runner3_*.json` (ventana de 12 s), `verify_*.out` (comando oficial), `amb_*.out` (caso ambiguo), `chain_log.txt`.

---

## 11. Limitaciones declaradas

1. **Ruido del host.** La capacidad de CPU medida varía hasta **4,8×** entre ventanas (`0,0228 → 0,1094` en la calibración determinista). Por eso el sondeo por etapa se **intercala y repite** (§5) y las tablas por prueba (§6) se presentan **con su calibración** y con la advertencia de no comparar sus absolutos entre columnas. Las conclusiones que dependen de la estructura (**reparto por etapa**, **19 → 10 validaciones**) no dependen del entorno.
2. **Fixture de respaldo en el sondeo por etapa.** El camino con evidencia real de `qa_v3.fixtures` exige un registro de evidencia leída que el sondeo no fabrica; se usó `generate_organization(agent_count=4)`, idéntico en los tres estados. El efecto medido es el del **conjunto runtime**; no se extrapola a documentos que escalan con el tamaño de la organización (las pruebas reales generan organizaciones más grandes y sus sellados cuestan 1,6-3,3 s frente a 0,70 s del sondeo).
3. **El árbol estaba vivo durante la medición.** La «entrega integrada» medida es el **estado con `RUNTIME_ALLOWLIST` = 237** (ventana 17:06-17:18). A las **17:18:33**, con mis corridas ya hechas, otro miembro modificó `engine/bundle.py` y añadió una entrada más (`tests_platform_packaging_cache.py`, 7 698 B) → 238 entradas, y regeneró `MANIFIESTO_SHA256.txt` (301 entradas). El efecto de esa entrada sobre esta diagnosis es proporcional a su tamaño (**+0,6 %** del conjunto runtime ⇒ décimas de milisegundo por exportación); no invalida ninguna comparación de este informe, pero se declara para que nadie compare cifras tomadas en árboles distintos.
4. **El experimento de carga controlada (primer intento) no produjo evidencia utilizable** y se descartó; el **segundo intento sí fue verificable** (calibración ×10,6 con 4 cargadores vivos) y es el que se reporta en §7.3. Aun así, su carga decayó antes del cierre (calibración final 0,0208), por lo que sus cifras absolutas tampoco se comparan fila a fila.
5. **No se reparó el árbol.** Todo el trabajo de corrección y medición del estado corregido se hizo sobre `%TEMP%\p3a_corregido_01` (copia). El árbol `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/` no se modificó **por mi parte**: instrumentación en memoria, `python -B` + `PYTHONDONTWRITEBYTECODE=1` y 0 archivos `.pyc` escritos en la ventana de mi tarea (comprobado por marca de tiempo). Los cambios que hoy muestra el árbol (`engine/bundle.py`, `MANIFIESTO_SHA256.txt`, `03_CATALOGO_DOCUMENTAL.json`, `tests_platform_packaging_cache.py`, `docs/PLATAFORMA_VERIFICACION_V1.md`) tienen marcas de tiempo de **otro** miembro y son posteriores a mis lecturas.
6. Sin red, sin claves, sin proveedores, sin dependencias nuevas y sin tocar DSH: los scripts usan sólo la biblioteca estándar y leen el árbol.
