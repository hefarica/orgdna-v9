# PLATAFORMA_ENTREGA_V9 — Integración y empaquetado de la capa de plataforma (Agent OS)

**Tarea:** `t9` (INT-A), miembro `contratos`. **Ronda:** integración y empaquetado sobre el cierre de R0,
`I1`–`I6` y `O1`. **Naturaleza:** acta de entrega y de alcance. **No es** ejecución de la plataforma.
**Convención de rutas:** relativas al *workspace* (la suite vive en `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`);
las listas máquina-legibles del anexo usan esa misma forma.
**Convención de citas:** `archivo:línea` sobre el código leído en esta ronda.

> **Advertencia de alcance, por delante:** esta entrega integra y empaqueta la capa de plataforma; **no
> ejecuta** ningún plano. Presencia, hash y coherencia de un artefacto **no acreditan ejecución**, conexión,
> identidad autenticada, disponibilidad de un proveedor ni rentabilidad. Lo que queda en `NOT_RUN` está
> enumerado en la sección 8 y no se ha convertido en un resultado por conveniencia de redacción.

---

## 1. Qué se integra

Toda la capa se integra por las dos vías que exige el paquete: la lista **literal** `RUNTIME_ALLOWLIST`
(`engine/bundle.py`) y `MANIFIESTO_SHA256.txt`. Añadir a una sin la otra **falla** la validación
(`engine/bundle.py:808`, `:810-820`), de modo que la coherencia es comprobable, no declarativa.

| Grupo | Artefactos | Estado en t9 |
| --- | --- | --- |
| Módulos de plano (`engine/`) | 11 | Integrados; **ninguno modificado** en esta ronda |
| Pruebas de plataforma (raíz) | 9 (7 preexistentes + `tests_platform_integration.py` + `tests_platform_packaging_cache.py`) | Las 7 preexistentes **no se tocan**; las dos nuevas son de esta ronda y de la reparación P3‑A |
| Contratos y actas (`docs/`) | 13 (6 esquemas de R0 + `policy.v2` + 5 documentos + este acta) | Integrados; 2 documentos modificados por esta ronda |
| Allowlist literal | 238 entradas exactas | 33 entradas nuevas, sin globs ni patrones |
| Manifiesto | 301 entradas + el propio manifiesto | Regenerado por diseño (D‑R0‑2) y de nuevo por la reparación P3‑A |
| Índice documental | `03_CATALOGO_DOCUMENTAL.json` (300 entradas) | Regenerado con la misma regla del empaquetador (`engine/bundle.py`), porque el validador exige que enumere **todos** los archivos entregados salvo él mismo y el manifiesto |

Los 11 módulos son `engine/task_graph.py`, `agent_registry.py`, `evidence_graph.py`, `policy_engine.py`,
`memory_governance.py`, `tenants.py`, `reliability.py`, `connector_gateway.py`, `evaluation_harness.py`,
`artifact_factory.py` y `approval_receipt.py`. Se integran **sin reescribir una sola línea**: sus huellas
quedan fijadas por el manifiesto y sus propias suites siguen siendo la autoridad sobre su comportamiento.

### 1.1 La allowlist sigue siendo literal

`RUNTIME_ALLOWLIST` conserva la propiedad que el propio archivo declara («Deliberately literal. Never add
glob…», `engine/bundle.py:29-30`): es una **tupla de nombres exactos**, sin `glob`, `rglob`, `fnmatch` ni
patrones. `tests_platform_integration.py` lo comprueba sobre el AST (la asignación debe ser una tupla de
literales, sin concatenación ni llamadas), verifica que no hay duplicados, que **toda** entrada existe en
disco —condición de `_read_runtime`, `engine/bundle.py:379`— y que los **47** módulos `engine/*.py` de la
entrega están dentro.

---

## 2. Manifiesto regenerado

El manifiesto cubre todos los archivos de la entrega salvo él mismo (`engine/bundle.py:798`) y su formato es
`<sha256><dos espacios><ruta>` por línea, ordenado por ruta (`engine/bundle.py:766`, `:927`).

| Magnitud | Valor |
| --- | --- |
| Entradas del manifiesto | `301` |
| `file_count` que reportará `validate_imports_portable.py` | `302` (incluye el propio manifiesto) |
| Allowlist | `238` entradas |

### 2.1 Por qué el acta no puede publicar la huella del manifiesto que la cubre

El paquete tiene una **dependencia circular real** de tres saltos: el acta publica una huella del manifiesto;
el manifiesto cubre `03_CATALOGO_DOCUMENTAL.json`; y el catálogo documental cubre al acta. Publicar aquí la
huella del manifiesto *tal cual* exigiría un punto fijo de SHA‑256. Es la misma razón por la que el manifiesto
se excluye a sí mismo (`engine/bundle.py:766`, `:798`) y el ZIP no incluye su propio hash
(`docs/export_artifacts.md:27`).

Se rompe publicando la huella del manifiesto con **dos líneas enmascaradas**. De las 301 entradas, solo los
digest de esas dos dependen del valor publicado; las otras **299** no. La huella se calcula, por tanto, antes
de escribirla, y se verifica después por recomputación:

```text
MANIFIESTO_FILE_COUNT 301
MANIFIESTO_SHA256_SIN_ESPEJO bce851b27a7d368f5a997bc6def3712fad6bad73c84d938e9659b17d5b5f4e28
MANIFIESTO_MARCADOR PENDIENTE_DE_MANIFIESTO
MANIFIESTO_LINEAS_ENMASCARADAS 03_CATALOGO_DOCUMENTAL.json docs/PLATAFORMA_ENTREGA_V9.md
```

- **Regla exacta.** Tomar `MANIFIESTO_SHA256.txt` entregado, sustituir el digest de las dos líneas declaradas
  en `MANIFIESTO_LINEAS_ENMASCARADAS` por el marcador literal `PENDIENTE_DE_MANIFIESTO` (conservando el orden,
  el separador de **dos espacios** y el salto de línea final), y calcular el SHA‑256 de esos bytes. El
  resultado debe ser igual a la huella publicada.
- **Quién lo comprueba.** `tests_platform_integration.py`,
  prueba `test_published_manifest_hash_is_reconstructible_with_masked_lines`, con el mismo procedimiento.
- La huella del manifiesto entregado **sin enmascarar** no se publica dentro del paquete (sería el punto fijo
  prohibido): se recalcula o se consulta en vivo con la acción de la sección 3, que la devuelve calculada
  sobre los bytes en disco.

---

## 3. Acción nueva de `engine/bridge.py`: `platform-planes-status`

**Es la única acción nueva de esta ronda** y es **estrictamente de solo lectura**. Devuelve el estado
declarativo de los siete grupos de artefactos (G1…G6, O1): por cada módulo y contrato, presencia, tamaño y
SHA‑256, más la coherencia con la allowlist literal y con el manifiesto.

| Garantía | Cómo se comprueba |
| --- | --- |
| No muta estado | No añade recibos (`receipts_added = 0`), no cambia `project`, ni `organization`, ni `pending_consent`, ni marca el proyecto como sucio |
| No escribe en disco | Huellas de los artefactos vigilados idénticas antes y después de invocar la acción |
| No abre red | `socket.socket` y `socket.create_connection` parcheados para fallar: la acción responde igual y `network_used = false` |
| No lanza procesos | El handler no importa `subprocess`, `shutil` ni usa `os.system` (comprobado sobre el AST) |
| No consume consentimiento ni presupuesto | `consent_consumed = false`, `spend_performed = false`, sin tocar `pending_consent` |
| No ejecuta ningún plano | El handler solo importa `engine.bundle` para leer la allowlist; ningún módulo de plano se importa ni se invoca; `planes_executed = false` |

La acción se invoca como cualquier otra del puente local (`POST /api/platform-planes-status` con cuerpo `{}`).
Su propio payload declara el límite: `runtime_verified = false` y `executed_by_this_action = false` por plano.

---

## 4. F‑T4‑2 cerrado: revisión 2 del contrato de política

**El defecto.** El segundo `allOf` de `docs/plataforma/policy.schema.json` (v1) exigía `approval` objeto en
**toda** decisión `allow`; combinado con `gate` obligatorio en `require_human_approval`, una acción de solo
lectura no tenía salida válida salvo `deny`. El motor `engine/policy_engine.py` ya implementaba la lectura
correcta (limitada a las ocho puertas) y su docstring documentaba que resolver la ambigüedad exigía una
**versión nueva** del contrato, no una edición en caliente (`engine/policy_engine.py:32-45`).

**La decisión.** La revisión 2 se emite como archivo **nuevo**: `docs/plataforma/policy.v2.schema.json`.
**v1 no se toca: sus bytes siguen siendo los de R0** (`c6026c70…`), porque dos consumidores congelados los
fijan byte a byte y no se modifican:

| Consumidor congelado | Qué fija | Estado |
| --- | --- | --- |
| `tests_platform_policy.py:39,145-162` | `FROZEN_SCHEMA_SHA256`, `required`, y `$defs.mandatory_gates` con la forma de anotación de v1 (`:159`) | **INTACTO y verde** |
| `tests_platform_eval_artifacts.py:1194-1196` | `$defs.mandatory_gates.properties.gates.const` | **INTACTO y verde** |

Esa es la prueba positiva de que la evolución es aditiva: los dos consumidores que exigían v1 literal siguen
pasando **sin que se les toque una línea**.

### 4.1 Qué cambia en v2

1. **`allow` implica aprobación solo donde hay puerta obligatoria.** Para los 10 tipos de acción que levantan
   alguna de las ocho puertas, `allow` exige registro de aprobación y una puerta levantada por **ese** tipo de
   acción. Para los 2 tipos sin puerta (`read_repo`, `run_tests`), `allow` exige `gate: null` y
   `approval: null`: una lectura no se disfraza de autorización humana.
2. **`$defs.mandatory_gates` deja de ser una anotación no referenciada** y pasa a ser
   `{"enum": [ocho puertas]}` **referenciado** desde `properties.gate` (`oneOf`), desde el `allOf` de
   `require_human_approval`, desde el de aprobación registrada, desde `$defs.approval_record.gate` y desde
   `limits.approvals_required`. Las ocho puertas son ahora una **puerta de máquina**, no un comentario.
3. **Payload sin cambios.** `policy_contract_version` sigue siendo `"1"` porque el motor no se modifica y sus
   decisiones siguen siendo las correctas; lo que cambia es la **revisión del contrato** (`schema_revision = 2`),
   declarada con `supersedes.sha256` apuntando a los bytes exactos de v1.

### 4.2 Medición (validador independiente + contraste)

Validador propio del subconjunto de JSON Schema que usan los contratos (implementación stdlib, independiente
del motor) y contraste con la librería de terceros `jsonschema` (instalada en este host):

| Conjunto de rutas | v1 | v2 | `jsonschema` v1 | `jsonschema` v2 |
| --- | --- | --- | --- | --- |
| 12 tipos de acción (`$defs.action.action_kind`) + 2 rutas de `allow` sin puerta = **14** | **12/14** (fallan exactamente `read_repo` y `run_tests`) | **14/14** | 12/14 (mismas dos) | 14/14 |
| Batería etiquetada del propietario de I3 (13 rutas) | 12/13 (falla `accion sin puertas`) | **13/13** | 12/13 (misma) | 13/13 |

Ambos validadores **coinciden exactamente** en los dos esquemas y en las **27 evaluaciones etiquetadas** (25
decisiones distintas, porque las dos rutas de `allow` sin puerta se miden dentro de los dos conjuntos); no hay
ninguna discrepancia que ocultar. Comando exacto y resultado, en la sección 9.

### 4.3 Límites declarados de v2

La igualdad `approval.gate == gate` y la trazabilidad de `matched_rules` para un `allow` sin puerta **no son
expresables** en JSON Schema; las verifica el motor (`engine/policy_engine.py:886-902`) y se cubren en su
suite. El esquema no pretende sustituir a `validate_decision`, sino dejar de contradecirlo.

---

## 5. Alineación O‑10 de `docs/PLATAFORMA_APROBACION_V1.md`

El documento de `O1` titulaba «(bloque literal del operador)» un texto que procedía de la descripción de `t13`
—escrita por el capitán— y no de una publicación del operador. Se ha alineado **antes** de recalcular su
huella, según el orden exigido:

- El epígrafe 1 contiene ahora el **bloque canónico del operador publicado en `OBSERVACIONES_CAPITAN_PLATAFORMA.md`,
  sección O‑10**, reproducido **verbatim** (13 líneas, `sha256 = 91810f2d8980508a2a4428d6ff613f6eefb5b302ad76addbe8f8d529ac0f6970`),
  con la atribución corregida y la fuente de autoridad citada.
- La transcripción previa **se conserva íntegra** en el epígrafe 1.1, relabelada como lo que es, porque las
  pruebas de documentación de `tests_platform_approval_receipt.py:697-714` verifican sus fragmentos y esas
  pruebas no se tocan.
- La comparación es programática, no visual: se extrae el bloque entre las marcas ```` ```text ```` de O‑10 y
  el del epígrafe 1, y se comparan **bytes** (no solo texto normalizado).

---

## 6. Formatos de exportación: sin cambios de versión

| Formato | Versión | Comprobación |
| --- | --- | --- |
| `agent-team-gui/recipe` | 1 | Leído del archivo entregado y de `engine/export_artifacts.py` |
| `agent-team-gui/definitions` | 2 | Ídem |
| `orgdna/export-manifest` | 1 | Leído del manifiesto de exportación entregado |
| `orgdna-local-project` | 1 | `engine/project_store.py` conserva `{'format':'orgdna-local-project','version':1,` |

Ninguna prueba previa de exportación se ha modificado para que pase; la lista máquina-legible del anexo
declara qué archivos tocó esta ronda.

---

## 7. Lo que esta entrega **no** hace

> La presencia y el hash de un artefacto **no acredita ejecución**, conexión, identidad autenticada ni
> disponibilidad de un proveedor. Esta acta declara qué se integró y qué se comprobó offline; nada más.

### 7.1 Limitación VIGENTE: hashear una declaración cruda no es hashear un `TaskGraph` (O‑9)

`t12` documentó en RV2 (O‑RV2‑4) que las funciones canónicas de `engine/task_graph.py` aceptan
**declaraciones crudas sin normalizar**: `canonical_task_list` está documentado como *canonicalizador*, no
como *validador*. Es coherente con el diseño declarado, pero es una trampa para un consumidor futuro:
**hashear una declaración cruda puede producir un hash que no corresponde a ningún grafo construido**.

- **Regla para consumidores:** primero se construye —`build_taskspec` / `build_graph`— y **después** se
  calcula `compute_graph_sha256` sobre el objeto resultante.
- **Estatuto:** limitación **vigente**, no una corrección. El flujo de contenido de `I1` no se modifica en
  esta ronda y **no se autoriza cambio de código**; esta acta **no promete ninguna comprobación que el
  código no realice hoy**. Nada de lo aquí entregado convierte el hash de una declaración cruda en la
  acreditación de un `TaskGraph` válido.
- **Alcance en esta ronda:** se declara, no se arregla. Su reparación, si el operador la quiere, es una
  decisión de otra ola (P2), no de `t9`.

- No ejecuta ningún plano, ni conecta con proveedores, ni abre conectores, ni gasta presupuesto.
- No modifica `engine/task_graph.py`, `agent_registry.py`, `evidence_graph.py`, `policy_engine.py`,
  `memory_governance.py`, `tenants.py`, `reliability.py`, `connector_gateway.py`, `evaluation_harness.py`,
  `artifact_factory.py`, `approval_receipt.py`, ni `web/`, ni `data/`, ni `MANIFIESTO_SHA256.txt` de R0
  (reemplazado por el nuevo, que es el objeto de esta ronda), ni `docs/plataforma/policy.schema.json`.
- No corrige pruebas previas ni cambia la semántica de ninguna que ya existía.
- No distribuye `docs/PLATAFORMA_VERIFICACION_V1.md`: lo produce `t10` **después** de esta ronda y por tanto
  no puede estar en este manifiesto. Se declara como ausencia esperada, no como omisión.

---

## 8. `NOT_RUN` explícito

| Elemento | Estado | Motivo |
| --- | --- | --- |
| Conectores vivos | **NOT_RUN** | El Connector Gateway es declarativo y está deshabilitado por defecto; no hay conexiones ni credenciales |
| Operación continua 24/7 | **NOT_RUN** | Ningún componente se ha dejado corriendo; las pruebas son offline y de un solo proceso |
| Chromium real | **NOT_RUN** | No se ha abierto un navegador; la interfaz no se toca en esta ronda |
| Proveedor real | **NOT_RUN** | Sin red, sin claves y sin envíos a ningún proveedor |
| Instalación DSH | **NOT_RUN** | No se modifica ni se instala nada de DSH |
| Ejecución de los planos | **NOT_RUN** | La capa se integra y se empaqueta; ninguna acción la ejecuta |
| Aislamiento real de inquilinos en runtime | **NOT_RUN** | El contrato y sus pruebas fijan la regla; el aislamiento efectivo no se ha ejercido fuera de las pruebas |
| Rentabilidad | **NOT_RUN** | Fuera del alcance de esta entrega y no derivable de ninguna prueba local |

---

## 9. Verificación ejecutada en esta ronda

| Comando | Resultado observado |
| --- | --- |
| `python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py` | `valid=true`, `checks=1791`, `file_count=301`, salida 0 |
| `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_*.py" -v` | **382** pruebas, OK, salida 0 (eran 348 antes de esta ronda; +34 de `tests_platform_integration.py`) |
| `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_frontend_contract.py" -v` | Línea base roja por `cp1252` (ver §9.3): `Ran 0 tests`, `FAILED (errors=1)`, salida 5 |
| `python -X utf8 -m unittest discover … -p "tests_frontend_contract.py"` (control) | **15** pruebas, OK, salida 0: la ronda no rompe el contrato de interfaz |
| Doble modo de lectura (política de medición O‑12/O‑13): `tests_platform_*.py` con `-X utf8` **y** con `PYTHONUTF8=1` | **382** pruebas, OK, salida 0 en los dos modos |
| Verificador de contratos de R0 sobre `docs/plataforma` (script de `PLATAFORMA_CONTRATOS_V1.md`, §8.3) | `valid=true`, `comprobaciones=337`, **7** esquemas (los 6 de R0 + `policy.v2`) |
| Comparación O‑10 verbatim (script temporal, stdlib) | bloque canónico = bloque documentado, `sha256 91810f2d…`, 13 líneas |
| Validador independiente de política + `jsonschema` sobre 27 rutas | v1: 25/27 conformes; v2: 27/27; coincidencia exacta entre ambos validadores |
| Contraste de no intromisión contra las huellas declaradas por los propietarios (`t6`, `t7`, `t12`, `t13`) | 6 de 7 coinciden byte a byte; la séptima es la discrepancia heredada F‑T9‑1 (§9.1) |
| Regresión completa sin patrón: `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN` | **993** pruebas en 454 s: 1 fallo y 14 errores, **ninguno atribuible a `t9`**; clasificación en §9.4 |

### 9.1 Discrepancia heredada, no atribuible a esta ronda (F‑T9‑1)

`tests_platform_reliability_connectors.py` tiene hoy
`sha256 = 51a6c845f37194003f3768e1e923c3f9f9889777499b1dddc230f35d4f6e4c0a` (912 líneas, 54 030 bytes), mientras que su
propietario declaró en `t7` `ed42d004ab43967eb8b04e5fb402a528c1f7104f614f6a3054e99a372ed163c9` (914 líneas).
**No lo introdujo `t9`**: el archivo ya tenía 54 030 bytes en el inventario con el que empezó esta ronda y conserva
exactamente 54 030 bytes al cerrarla, y no aparece en la lista `MODIFICADO` del anexo. Los otros seis artefactos
contrastados (`engine/reliability.py`, `engine/connector_gateway.py`, `engine/task_graph.py`,
`engine/approval_receipt.py`, `docs/PLATAFORMA_REVISION_RV1.md`, `docs/PLATAFORMA_REVISION_RV2.md`) coinciden
**byte a byte** con lo declarado por sus propietarios, así que la integración no tocó ningún plano.

- **Efecto funcional:** ninguno medido. Su suite pasa dentro de las 382 pruebas en verde.
- **Causa:** no determinada desde aquí. Ninguna tarea ni informe disponible documenta un cambio de ese archivo tras `t7`.
- **Qué hace esta ronda:** lo integra con sus bytes actuales y los fija en el manifiesto, de modo que a partir de ahora
  cualquier cambio sea detectable. **No se edita**: corregir pruebas ajenas está fuera de alcance.
- **Recomendación:** que el capitán o `t10` contrasten con el propietario de `t7` si su cifra declarada era anterior a su
  última edición; si lo es, los bytes actuales quedan como línea base de V1 y la declaración de `t7` debe corregirse.

### 9.2 Inestabilidad de plazo con margen reducido (F‑T9‑2)

En la corrida completa de esta ronda (993 pruebas) falló `test_revision_preserves_ids_new_project_changes_them`
(`tests_generation_pipeline`), con `Generation did not finish` y la etapa `building_exports` al 90 %; volvió a fallar
una vez en aislamiento. Su fixture da **12 s por ventana de espera** (`tests_generation_pipeline.py:90`). Medición
diferencial con el mismo test y el mismo plazo, 3 corridas en cada estado, sin modificar ningún archivo de la entrega:

| Estado | Ventanas medidas (segundos) | Resultado |
| --- | --- | --- |
| Copia pre‑integración reconstruida (allowlist 205, manifiesto 268, catálogo 267) | `[0.05, 1.41, 0.08, 2.92, 0.17, 6.42]` · `[0.14, 5.26, 0.16, 6.2, 0.2, 6.42]` · `[0.11, 5.28, 0.16, 6.0, 0.2, 6.33]` | 3/3 OK |
| Entrega de `t9` **antes de la reparación P3‑A** (allowlist 237, manifiesto 300, catálogo 299) — medición histórica, no se reescribe | `[0.03, 2.23, 0.06, 8.25, 0.22, 8.48]` · `[0.09, 5.92, 0.17, 7.25, 0.17, 7.2]` · `[0.09, 6.55, 0.2, 7.45, 0.17, 7.59]` | 3/3 OK |

Lectura honesta: la integración **no determina** el fallo —los dos estados pasan en aislamiento, 3/3— pero **reduce el
margen**: la última ventana sube de ~6,3‑6,4 s a ~7,2‑8,5 s contra un plazo fijo de 12 s. El fallo aparece cuando el host
está cargado (corrida completa). Con la política de medición de O‑12 esta prueba es **frágil al plazo y sensible a la
carga**, no un fallo nuevo atribuible a `t9`; se declara medida su ventana en ambos estados para que `t10` pueda
atribuirla con datos y no por impresión.
Método: `medir_ventanas.py` (script temporal, solo biblioteca estándar) que envuelve `wait_for` en memoria sin tocar
archivos; la copia pre‑integración se reconstruyó **sobre una copia del árbol**, nunca sobre la entrega.

### 9.3 Nota honesta sobre `tests_frontend_contract.py`

Este host usa `cp1252` como encoding por defecto. `tests_frontend_contract.py:24` lee `web/index.html`,
`web/app.js` y `web/style.css` **sin** `encoding='utf-8'` y falla con `UnicodeDecodeError` **antes** de
ejecutar ninguna prueba: `Ran 0 tests`, `FAILED (errors=1)`, salida 5. Es una condición de la **línea base**
de este host, reproducible sobre el árbol sin tocar, y no la introduce esta ronda: es uno de los **3 casos
condicionados por encoding** de la línea base (O‑13). No se corrige aquí: el contrato prohíbe modificar pruebas
previas y `web/` está fuera del alcance. Se mide en **los dos modos**: con `python -X utf8` (equivale a
`PYTHONUTF8=1`) pasa con **15 pruebas, OK, salida 0**, y eso es lo que se declara como control; `PYTHONUTF8=1`
**no cierra el defecto**, solo lo hace visible como lo que es: una dependencia del encoding del entorno.
Las pruebas de esta ronda (`tests_platform_integration.py`) leen **siempre** con bytes/`utf-8` explícito y pasan
en ambos modos.

### 9.4 Regresión completa: clasificación de lo que falla (y de lo que no es de esta ronda)

`python -m unittest discover …` sin patrón, sobre el árbol entregado: **993 pruebas en 454 s**, con **1 fallo y 14
errores**. Ninguno es atribuible a `t9`; cada uno cae en una clase ya documentada:

| Clase | Casos | Evidencia |
| --- | --- | --- |
| Encoding por defecto del host (`cp1252`) | 5 | `UnicodeDecodeError` en `tests_frontend_contract` (setUpClass), `tests_v8_ui_contract` (setUpClass), `tests_generation_pipeline.test_save_reload…` y `qa_v7.test_dsh_preservation_independent` (×2). El de la pipeline figura como ERROR en **las dos** líneas base del *workspace* |
| Inestabilidad de fixtures HTTP (O‑3, medida por el capitán) | 4 | `TimeoutError` en `qa_v6.test_http_multisource` (×2); `ConnectionAbortedError` en `qa_v7.RecoveryHttpIndependent` y en `tests_bridge.HTTPTests.test_body_bound` (esta última ya en `regresion_con_plataforma.txt`) |
| `tests_dsh_launcher` (puerto 3080 ocupado por el propio arnés / backup) | 5 | 4 errores + `test_no_script_assumption_no_guessed_port`; los 5 figuran en **las dos** líneas base |
| `tests_bridge.BridgeStateTests.test_workbook_stale_blocks_export` | 1 | `SecurityError` de PowerShell (COM/Excel); figura en **las dos** líneas base |

`test_revision_preserves_ids_new_project_changes_them` **no** falló en esta corrida: coherente con F‑T9‑2 (frágil al
plazo, aparece con el host cargado). El resumen de la corrida y los trazados completos quedan en el registro de la
ronda, no dentro del paquete.

---

## 9-bis. Reparación P3‑A — coste de la ruta de exportación (posterior a `t9`)

**Defecto medido, no inferido.** `validate_bundle` es una función **pura** de sus bytes y la canalización la invocaba
**dos veces sobre el MISMO payload**: una dentro de `build_package_bytes` y otra en `generation_pipeline._run`. Medido
en esta máquina: **0,38–0,43 s por validación**, es decir ~0,4 s desperdiciados en cada generación. Además, cada archivo
se hasheaba **dos veces** por generación (catálogo y manifiesto): 1199 llamadas para ~600 archivos.

**Corrección aplicada** (`engine/bundle.py`):

1. `validate_bundle` memoriza su veredicto **por sha256 del contenido**, con caché acotada y cerrojo. Unos bytes
   distintos **nunca** reutilizan el veredicto; se devuelve una copia para que el llamante no pueda corromper la caché.
   La caché **no contiene datos de ninguna organización, proyecto ni tenant**: solo el resultado de validar un paquete
   ya construido.
2. Un **único cálculo de digest por archivo**, compartido entre el catálogo y el manifiesto.

**Lo que NO se ha hecho:** no se ha ampliado la ventana heredada de 12 s, no se ha modificado ninguna prueba previa y
no se ha debilitado ninguna validación.

**Evidencia de la reparación**

| Medición | Antes | Después |
|---|---|---|
| `tests_generation_pipeline.py` | **6 fallos / 24 en 141,725 s** | **24/24 OK en 20,920 s** |
| Digests por empaquetado (1 agente, 278 archivos) | 554 | **≤ 282** |
| Validaciones sobre bytes idénticos | 2 | **1** |

**Prueba de regresión nueva:** `tests_platform_packaging_cache.py` (9 casos). **Falsificada**: al revertir las dos
correcciones en una copia temporal del árbol, **4 de los 9 casos fallan** con números exactos (`2 != 1` en validación
repetida; `554 digests para 278 archivos`). Un test que no falla sin el arreglo no prueba nada.

**Riesgo residual declarado:** la medición por etapa prístina-vs-integrada **no es resoluble con 3 repeticiones en este
host** (se observaron valores atípicos de 3–4 s por contención). Los mínimos fueron 1,215 s y 1,161 s, indistinguibles.
La cifra que sí es estable y reproducible es la de la tabla superior.

**Reconciliación de la suite completa, por test y causa raíz** (782 pruebas, 60,371 s, `failures=1, errors=10, skipped=2`):

| Causa raíz | Casos | Atribución |
|---|---|---|
| **Regresión de la integración (plazo de exportación)** | **0** | **ELIMINADA** por esta reparación (antes: 6) |
| Causa B heredada — Excel/COM + Mark‑of‑the‑Web | 1 (`tests_bridge.test_workbook_stale_blocks_export`) | línea base V8, no atribuible a la ola |
| Causa C heredada — respaldo del relanzador DSH | 4 (`tests_dsh_launcher`) | línea base V8, causa no determinada |
| Causa D heredada — puerto 3080 inyectado | 1 (`test_no_script_assumption_no_guessed_port`) | línea base V8 |
| Capacidad de Windows — symlink (`WinError 1314`, privilegio no disponible) | 2 (`test_namespace_traversal_symlink`, `test_symlink_destination_rejected`) | entorno; falla igual en aislamiento y no toca los módulos modificados |
| Encoding cp1252 del host | 3 (2 `setUpClass` + `test_save_reload…`) | condicionado por entorno; desaparece con `PYTHONUTF8=1` |
| Skips legítimos | 2 (POSIX process group; symlink no soportado) | capacidad de plataforma |

**Ninguno de los 11 fallos restantes es atribuible a la ola de plataforma ni a esta reparación.**

---

## 10. Anexo máquina-legible (lo lee `tests_platform_integration.py`)

Las líneas siguientes tienen formato fijo `PREFIJO <dato>`; el anexo evita que la lista de alcance dependa de
la prosa. Los cuatro valores `MANIFIESTO_*` (`MANIFIESTO_FILE_COUNT`, `MANIFIESTO_SHA256_SIN_ESPEJO`,
`MANIFIESTO_MARCADOR`, `MANIFIESTO_LINEAS_ENMASCARADAS`) se declaran **una sola vez** en la sección 2.1, que es
donde se explican; no se repiten aquí precisamente para que sigan siendo únicos y la reconstrucción de la huella
sea determinista.

```text
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/03_CATALOGO_DOCUMENTAL.json
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/bundle.py
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/bridge.py
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/MANIFIESTO_SHA256.txt
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_CONTRATOS_V1.md
MODIFICADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_APROBACION_V1.md
NUEVO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/policy.v2.schema.json
NUEVO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_ENTREGA_V9.md
NUEVO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_integration.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/task_graph.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/agent_registry.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/evidence_graph.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/policy_engine.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/memory_governance.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/tenants.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/reliability.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/connector_gateway.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/evaluation_harness.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/artifact_factory.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/approval_receipt.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_task_graph.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_registry_evidence.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_policy.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_memory_tenants.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_eval_artifacts.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_reliability_connectors.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests_platform_approval_receipt.py
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_DECISIONES.md
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_REVISION_RV1.md
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_REVISION_RV2.md
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/taskspec.schema.json
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/evidence-node.schema.json
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/policy.schema.json
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/memory-record.schema.json
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/tenant-boundary.schema.json
INTEGRADO EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/plataforma/receipt-extension.schema.json
```
