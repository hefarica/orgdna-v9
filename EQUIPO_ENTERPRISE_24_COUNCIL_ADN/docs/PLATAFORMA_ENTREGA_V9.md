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
| Pruebas de plataforma (raíz) | 18 (7 preexistentes + `tests_platform_integration.py` + `tests_platform_packaging_cache.py` + `tests_platform_launcher_zip_names.py`) | Las 7 preexistentes **no se tocan**; las dos nuevas son de esta ronda y de la reparación P3‑A |
| Contratos y actas (`docs/`) | 13 (6 esquemas de R0 + `policy.v2` + 5 documentos + este acta) | Integrados; 2 documentos modificados por esta ronda |
| Allowlist literal | 272 entradas exactas | 33 entradas nuevas, sin globs ni patrones |
| Manifiesto | 423 entradas + el propio manifiesto | Regenerado por diseño (D‑R0‑2), por las reparaciones P3‑A, P3‑B y P3‑C, y por la integración GenTeam P1‑P4 (ronda 9‑quattuordecies) |
| Índice documental | `03_CATALOGO_DOCUMENTAL.json` (422 entradas) | Regenerado con la misma regla del empaquetador (`engine/bundle.py`), porque el validador exige que enumere **todos** los archivos entregados salvo él mismo y el manifiesto |

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
| Entradas del manifiesto | `423` |
| `file_count` que reportará `validate_imports_portable.py` | `343` (incluye el propio manifiesto) |
| Allowlist | `360` entradas |

### 2.1 Por qué el acta no puede publicar la huella del manifiesto que la cubre

El paquete tiene una **dependencia circular real** de tres saltos: el acta publica una huella del manifiesto;
el manifiesto cubre `03_CATALOGO_DOCUMENTAL.json`; y el catálogo documental cubre al acta. Publicar aquí la
huella del manifiesto *tal cual* exigiría un punto fijo de SHA‑256. Es la misma razón por la que el manifiesto
se excluye a sí mismo (`engine/bundle.py:766`, `:798`) y el ZIP no incluye su propio hash
(`docs/export_artifacts.md:27`).

Se rompe publicando la huella del manifiesto con **dos líneas enmascaradas**. De las 423 entradas, solo los
digest de esas dos dependen del valor publicado; las otras **340** no. La huella se calcula, por tanto, antes
de escribirla, y se verifica después por recomputación:

```text
MANIFIESTO_FILE_COUNT 423
MANIFIESTO_SHA256_SIN_ESPEJO c0780e58a3b1467540d62983f866f4795e3827031787e1bd6abebb2bf164ec0b
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

> **Reclasificados por la reparación P3‑B (§9‑ter).** Dos filas de la tabla anterior dejan de estar sin determinar:
> la «Causa C» es un **defecto de producto en Windows** y la «Causa D» un **defecto de aislamiento del test**. La
> medición histórica de arriba **no se reescribe**; la corrección se declara en §9‑ter.

---

## 9-ter. Reparación P3‑B — el respaldo del relanzador DSH no podía completarse en Windows

**Defecto medido, no inferido.** Los nombres de entrada del ZIP de respaldo se construían con
`Path(str(index)) / relativo` (`engine/dsh_launcher.py:345` y `:373`), y `Path.__truediv__` usa `os.sep`, que en
Windows es `\`. El nombre quedaba `0\history.json`, mientras `zipfile` **normaliza `os.sep` al escribir**
(`ZipInfo.__init__`), de modo que el archivo guardaba `0/history.json` y el manifiesto interno conservaba el nombre
sin normalizar. La copia se escribía correctamente y después no podía leer su propia lista de entradas:

```text
KeyError: "There is no item named '0\\history.json' in the archive"
```

**Consecuencia:** `dsh-launch-backup` no podía completarse **nunca** en Windows. Y el `except Exception` de la línea
421 relanzaba con `from None`, de modo que el operador veía «revisa las rutas» apuntando al sitio equivocado.

**Corrección aplicada** (`engine/dsh_launcher.py`):

1. Helper `_entry_name(index, relative)` que devuelve `'%d/%s' % (index, relative.as_posix())`, conforme a
   APPNOTE 4.4.17.1 (**barra inclinada obligatoria**). Se aplica en `_inventory` y en `backup`, de modo que lo que se
   escribe y lo que se busca son la misma cadena. En POSIX el resultado es idéntico al anterior.
2. El `except` conserva mensaje y tipo —el contrato visible no cambia— pero **encadena la causa** (`from cause`).

**Lo que NO se ha hecho:** no se ha relajado ninguna validación, no se ha modificado ninguna otra prueba previa, y el
alcance del respaldo (rutas, límites de 512 MiB / 20 000 archivos, rechazo de reparse points) queda intacto.

**Evidencia**

| Medición | Antes | Después |
|---|---|---|
| `tests_dsh_launcher.py` (16 casos) | **FAILED (failures=1, errors=5)** | **OK (skipped=1)** |
| `tests_platform_launcher_zip_names.py` (9 casos, nuevo) | no existía | **9/9 OK** |

**Falsificación ejecutada.** Restaurado el código original en una copia desechable del árbol (helper ausente, los dos
sitios de llamada con `os.sep`, `from None`), la ejecución conjunta da **`Ran 25 tests — FAILED (failures=4, errors=8,
skipped=1)`**. Las aserciones señalan el defecto de forma directa:

```text
AssertionError: '\' unexpectedly found in '0\sub\deep\leaf.txt' : nombre no conforme a APPNOTE 4.4.17.1
AssertionError: None is not an instance of <class 'RuntimeError'>
```

En POSIX `os.sep` es `/` y el defecto es **invisible**: el respaldo funciona. Por eso el módulo nuevo comprueba el
**formato** del nombre y no solo el resultado; sin esa aserción la regresión volvería sin ser detectada en Linux o macOS.

**Reclasificación de las dos filas** (la medición histórica no se reescribe):

| Fila histórica | Clasificación anterior | Clasificación corregida |
|---|---|---|
| Causa C — 4 casos en `tests_dsh_launcher` | «línea base V8, causa no determinada» | **defecto de producto en Windows**, localizado y reparado aquí |
| Causa D — `test_no_script_assumption_no_guessed_port` | «puerto 3080 inyectado» | **defecto de aislamiento del test**: leía el `%LOCALAPPDATA%\DSH_LAUNCHER\launcher.json` real del operador. El producto lee la configuración correctamente. Comprobado: con `LOCALAPPDATA` aislado el caso pasa |

**Actualización DECLARADA de un hash pinneado.** `qa_v7/dsh_baseline.json` es un contrato de preservación por
bytes sobre la superficie de integración DSH (42 archivos: extensión Cordis, `engine/dsh_*.py`, el relanzador) y
pinnaba `engine/dsh_launcher.py` en `9998fe928f8307a081b1f5eaf0ba8157444a071cc1acf0a6dd1822625665866b`. La
reparación cambia ese archivo, así que la entrada se actualiza a
`651274749334518afd66f9b757525017ba03bfa886ef0c29d67df8447505f939`. Reescribirla en silencio sería exactamente lo
que ese contrato existe para impedir: la enmienda queda registrada **dentro del propio archivo**, en la clave
`amendments`, con el hash anterior, el nuevo, el motivo y la evidencia. `baseline_zip_sha256` **no se toca**: es
procedencia del ZIP de origen y ningún test lo consume. Verificado tras la enmienda:
`qa_v7.test_dsh_preservation_independent` → **4/4 OK**.

**Riesgo residual declarado (NO VERIFICADO AQUÍ).** `test_symlink_destination_rejected` requiere
`SeCreateSymbolicLinkPrivilege` (o Modo desarrollador) para montar su propio escenario; sin ese privilegio lanza
`WinError 1314` antes de ejercitar nada. Se declara **skip con motivo explícito** en lugar de quedar en rojo, de modo
que la carencia de cobertura sea visible y no un fallo aparente del producto. **La ruta de rechazo de reparse points
queda NO VERIFICADA en este host**; `no_links()` sí contempla junctions vía `st_file_attributes & 0x400`.

---

## 9-quater. Cambio P3‑C — techo de agentes de 32 a 40 (decisión del propietario)

**Qué cambia y por qué.** El techo de N era un literal `32` **duplicado**. No era una frontera de orquestación: era
una constante repetida, y por eso estaba **desincronizada entre capas**. Se sustituye por una **fuente única**,
`engine/limits.py`, del que todas las capas importan `MAX_AGENTS`. Ninguna capa lo redefine.

**El alcance no eran cuatro archivos.** Inventario medido: **13 archivos**, 51 reglas de sustitución, 54
sustituciones. Incluye `core.py` (el gate que salta primero, `_normalize_config:111`), `autonomy.py` (dos sitios
donde la cota viaja **como argumento**), `bridge.py:156` (validación en servidor), `dna.py`, `org_design.py`,
`providers.py`, `capability_deployment.py`, `capability_recommendations.py`, `integration_recommendations.py`,
`resource_workflows_adapter.py`, `resource_workflows.py`, `cordis_extension.py`, `generation_pipeline.py` y la UI.

**Por qué un barrido de literales no bastaba.** `autonomy.py:43` pasa `1,32` como **argumento** a `_integer`, y el
mensaje se compone en `:20` (`f'{field}: entero {minimum}..{maximum} requerido.'`). El literal no aparece junto al
mensaje, así que un grep no lo encuentra. Comprobado: un parche de **30 sitios** que no incluía `autonomy.py`
seguía fallando con `agent_count: entero 1..32 requerido.`

**La UI deja de tener literales.** Los tres `max="32"` pasan a `max="__MAX_AGENTS__"` y `bridge.py:1644` los
rellena al servir, junto al `__CSRF_TOKEN__` que ya se sustituía. `tests_bridge.py` afirma ahora que **ninguno** de
los dos marcadores sobrevive en el cuerpo servido.

**El mensaje que habría mentido, corregido.** `core.py:112` decía «Más de 32 agentes requiere diseño multi-squad».
Con el techo en 40 eso sería **falso**: `multi-squad` en este producto significa los dos escuadrones fijos
—implementación y Council— (`bundle.py:837`), no N escuadrones encadenados. El mensaje dice ahora la verdad: un
escuadrón plano de N perfiles, con el encadenado **no implementado**.

**Los dos tests de frontera, movidos de forma declarada y no silenciada:** `tests_bridge.py:187` (`33`→`41`) y
`tests_org_design.test_invalid_n_and_budgets_are_not_coerced` (`33`→`41`). Y se **añade un positivo N=40**: sin él,
subir el techo quedaría declarado pero no probado.

**Evidencia**

| Medición | Resultado |
|---|---|
| N=41 rechazado | `Más de 40 agentes no está soportado: … no se trunca el equipo.` |
| `autonomy` con 41 (la cota-argumento) | `agent_count: entero 1..40 requerido.` |
| `autonomy` con 40 | aceptado |
| **Positivo N=40, modo API** (`tests_org_design`) | **`OK`** — 40 perfiles, `len(agents)==40`, organización válida |
| Prompt del proveedor | `Use 1-40 professions` — deja de instruir al modelo con el techo viejo |
| Cotas `32` supervivientes | **0** (el único resto es el docstring de `limits.py` que explica el patrón) |

### 9-quater.1 Limitación declarada: el modo plantilla sigue en 32

`core.py:947` (`check(config.get('agent_count')==n, 'agent_count no coincide con agents.')`) rechaza N=40 en el
modo **plantilla sin IA**, porque `ROLE_SEEDS` y `PERSONAS` son **32** y el generador offline produce 32 perfiles.
Falla **cerrado** —no trunca en silencio—, que es la conducta correcta, pero el mensaje no explica la causa real.

- **Modo API: N=40 funciona**, probado (tabla anterior).
- **Modo plantilla: sigue en 32.** Ampliarlo exige **8 semillas nuevas** en `ROLE_SEEDS`/`PERSONAS`, que son
  contenido de producto y no una reparación. **Decisión pendiente y separada**, no incluida en P3‑C.

### 9-quater.2 `RUNTIME_UNVERIFIED` que este cambio NO resuelve

AgentTeams tendría que admitir **1 Captain + 39 teammates**. Este repositorio **genera** el diseño y los
artefactos; **no ejecuta** AgentTeams ni DSH. Esa frontera queda declarada como `RUNTIME_UNVERIFIED`, igual que el
resto de capacidades operativas: `NOT_RUN`.

---

## 9-quinquies. Módulos A y B — compilador de contexto y bucle de mejora (P3‑D)

**Dos módulos nuevos**, stdlib puro, sin estado mutable de módulo, con digest determinista y fail-closed:
`engine/context_compiler.py` (contexto acotado por presupuesto) y `engine/improvement_loop.py` (ejecutor de los
siete estados de remediación).

**Se escribieron, se ejecutaron y se falsificaron.** No se aceptaron por lectura. La ejecución encontró **tres
defectos reales en B y una inconsistencia en A**, todos reparados con falsificación ejecutada.

| # | Defecto medido | Evidencia | Reparación |
|---|---|---|---|
| B1 | `_REQUIRED_AT_PUBLISH` exigía `skill_diff`, que **nadie asigna nunca** (el diff vive en `case["skill"]["diff"]`) → `publish()` **inalcanzable**, el camino feliz siempre fallaba | `case: evidencia incompleta para publicar: skill_diff` | la puerta comprueba `skill`, cuyas siete claves ya valida `draft_skill` |
| B1b | Ese fallo **enmascaraba** el guardián de permisos, que era inejercitable | el caso 5 de la lista original no podía recorrerse | queda ejercitable y verificado |
| B2 | `case_digest` **plegaba el digest anterior** dentro del nuevo y `verify_case` devolvía **True con el contenido alterado**: B calculaba digests que nadie podía comprobar | `case_digest(c) != c["digest"]`; alterar `expected` no se detectaba | el digest se excluye a sí mismo y `verify_case` lo recomprueba |
| A1 | Los campos desconocidos **dentro de un elemento** se ignoraban en silencio, contra el propio contrato de A («campo desconocido → ValueError con ruta de campo») y contra `_SKILL_KEYS` de B | un `extra` en una fila de evidencia no lanzaba nada | `_ITEM_KEYS` por tipo, con ruta de campo |

**Dos casos de la lista de falsificación original eran inejercitables, y se declara:**

1. **A, caso 3** («budget diminuto»): con `budget_bytes=1024` y un fixture pequeño caben 638 bytes, así que no se
   omitía nada. El módulo era correcto; el fixture no recorría la ruta de omisión. Se redimensiona para desbordar.
2. **B, caso 7** («reintroducir el borrador viejo sin `preserved_failure_id`»): **inexpresable**, porque
   `draft_skill` construye el dict de la skill y `_SKILL_KEYS` rechaza el campo ajeno. Se sustituye por lo que sí
   es verificable: que el borrador **siempre** conserve el caso fallido, y que alterar el caso se detecte.

**Evidencia**

| Medición | Resultado |
|---|---|
| `tests_context_compiler.py` (13 casos) | **13/13 OK** |
| `tests_improvement_loop.py` (14 casos) | **14/14 OK** |
| Falsificación de B (arreglos revertidos en copia desechable) | **`FAILED (failures=2, errors=2)`** de 14 — camino feliz, fail-closed, digest y permisos |
| `verify_case` con `expected` alterado | lanza `caso alterado` |

**Lo que estos módulos NO son.** No tocan pesos: la política vive en las skills y la recompensa en la revisión
independiente. No llaman al proveedor, no ejecutan agentes y no conceden permisos. `context_compiler` **no es
recuperación semántica**: es selección por solape de términos con presupuesto, y lo declara en su propio
`selection.method`. La señal de recompensa y la propagación son del llamador: **no están cableadas**.

---

## 9-sexies. Capa de agentes, contrato de instrucción y cableado (P3‑E)

**Nueve archivos** (7 módulos + 2 suites), stdlib puro, deterministas y fail-closed: `agent_kinds`,
`operational_gate`, `readiness_gate`, `playbooks`, `agent_dossier`, `instruction_contract` y
`remediation_wiring`.

**Se escribieron, se ejecutaron y se falsificaron.** La ejecución encontró **cinco defectos reales** que la
lectura no daba, y **uno de ellos era un crash en el peor sitio posible**.

| # | Defecto medido | Evidencia | Reparación |
|---|---|---|---|
| D1 | `readiness_gate`: el switch era un **dict literal**, que se evalúa ENTERO antes de indexar, así que `item["gap"]` reventaba con `KeyError` en el **primer bloqueo de herramienta** | la puerta fallaba **exactamente cuando tenía que bloquear** | `if/elif` con `raise` en código desconocido |
| D2 | `instruction_contract`: `reconcile` sólo reparaba `got` de tipo `str`, así que un `2` **número JSON** frente al `2.0` fijado se declaraba **irreparable** | el caso 5 de la lista original no podía pasar | la rama numérica acepta `int`/`float`/`str`, con guarda de `bool` |
| D3 | `agent_kinds`: con el catálogo vacío la preset salía **vacía y en silencio** | el caso 2 («nunca lista vacía») era falso; lo correcto es que sea **visible** | la lista vacía se declara en `capability_gaps` |
| D4 | `agent_dossier`: `to_context_items(limit=64)` producía **66** elementos de memoria (64 + relaciones + omitidos) y `context_compiler` los **rechazaba** | la llamada por defecto **no podía alimentar a su consumidor** | `MAX_ENTRIES_IN_CONTEXT = 64 − 2`, y el default cabe exacto |
| D5 | `remediation_wiring`: clave de idempotencia **estable** con `expected_revision` leída **en vivo** | el reintento del mismo caso lanzaba `Clave idempotente reutilizada para otra solicitud` — **justo el escenario para el que existe la idempotencia** | `replay_key()` incluye la revisión; la idempotencia real la da el `item_id` determinista |

**Corrección de una predicción:** los seis `tool_needs` del playbook **sí existen** en el catálogo real (271
herramientas), así que `unknown_in_catalog` es `[]` y el preflight **no** sale bloqueado por nombres.

**Evidencia**

| Medición | Resultado |
|---|---|
| `tests_agent_layer_contracts.py` (32 casos) | **32/32 OK** |
| `tests_instruction_and_wiring.py` (25 casos) | **25/25 OK** |
| Falsificación: los 5 arreglos revertidos en copia desechable | **`FAILED (failures=2, errors=8)`** de 57 — los cinco defectos, delatados por su caso nombrado |
| `import_items(**plan)` contra **SQLite real** | **OK**, revisión 0→1; reimportar el mismo caso → **item_count sigue 1** |
| Inmutabilidad contra la **biblioteca real** | lanza `Los registros son inmutables; importar una nueva versión con otro ID.` |

**Lo que sigue sin estar cableado.** `publish() → biblioteca → contexto` está **verificado contra los
componentes reales**, pero el llamador que lo invoca en producción **no existe**: no hay punto de entrada que
dispare el bucle. La señal de recompensa sigue fuera. Nada de esto toca pesos, instala, activa ni ejecuta un
agente: `RUNTIME_UNVERIFIED` y `NOT_RUN` no se mueven.

---

## 9-septies. Diagnostico de notacion de modelos (P3‑F)

**El caso real.** La configuracion guardada tenia `model = 'DeepSeek-V41-Flash'`, que es el **nombre visible**,
mientras el ID de API es `deepseek-flash`. El producto fallaba cerrado -correctamente- con «El ID elegido para la
API no esta verificado», y el operador quedaba en un callejon sin salida: el mensaje no decia cual era el ID.

**`engine/model_resolver.py`** resuelve la notacion para **DIAGNOSTICAR, nunca para aceptar**. La forma canonica
(casefold + solo alfanumericos) hace coincidir la MISMA notacion escrita distinto:

    'DeepSeek-V41-Flash' -> 'deepseekv41flash' -> nombre 'DeepSeek-V4.1-Flash' -> ID 'deepseek-flash'

No hay parecido, ni subcadena, ni eleccion entre varios: `DeepSeek-V41`, `deepseek`, `flash` y `gpt-4` dan
`unknown`; un caso ambiguo devuelve `ambiguous` y **no elige**.

### Lo que NO se hizo, y por que

**La primera version AUTO-ADOPTABA el ID resuelto. Se retiro.** El arbol tiene **dos** guardianes deliberados
que lo prohiben, y uno de ellos no se habia leido antes:

  tests_model_catalog_scopes.py:43  test_api_display_name_or_alias_rejected_even_if_manual_preference_exists
  tests_model_catalog_scopes.py:62  test_provider_alias_does_not_bypass_exact_api_catalog

El fixture de esos tests lleva `'name': 'DeepSeek-V4.1-Flash'` **a proposito**, para que el nombre exista y
**aun asi no se use**. La regla del producto —«never reinterpret a display name... never silently pick another
model»— es una propiedad de seguridad, no una limitacion: un nombre visible puede ser ambiguo o cambiar.

**Lo que si cambia:** el error deja de ser un callejon sin salida y **nombra el ID exacto**. Eso es lo que se
cablea. La regla de aceptacion **no se mueve**.

### El segundo muro, que este modulo NO tumba

Para `deepseek` el proveedor tiene `discovery=True`, de modo que la rama manual es inalcanzable: **solo una fila
`live_api`** —el catalogo real de la cuenta— satisface la verificacion. Las filas guardadas son
`saved_project_reference` y **nunca cuentan**. Resolver la notacion elimina el primer muro; el segundo exige
**una consulta real del catalogo con la clave**, y eso no lo hace este modulo.

| Medicion | Resultado |
|---|---|
| `tests_model_resolver.py` (15 casos) | **15/15 OK** |
| `tests_model_catalog_scopes.py` (los 2 guardianes) | **2/2 OK** — la regla de aceptacion intacta |
| `tests_v8_models_receipts.py` (19 casos) | **19/19 OK** |
| `DeepSeek-V41-Flash` | **rechazado**, y el error nombra `deepseek-flash` |
| `DeepSeek-V41`, `deepseek`, `gpt-4`, `INVENTED` | `unknown` — no se inventa coincidencia |

**Automatico al guardar la clave (pedido explicito del propietario, ejecutado).** Guardar la clave dispara ahora
la consulta del catalogo **en el acto** para proveedores con `discovery=True`: la llamada es de **metadatos**
(listar modelos, no diseno ni inferencia), queda declarada en el recibo ("Consulta AUTOMATICA al guardar la
clave..."), y si falla, la clave **sigue guardada** y queda el boton manual. Sin este cableado, el operador tenia
el ID delante y aun asi no podia avanzar sin un segundo clic. La UI envia `auto_discover:true` en el formulario
de clave, y `tests_bridge` + `tests_v8_models_receipts` + `tests_model_catalog_scopes` siguen en verde en la
pasada de verificacion.

---

## 9-octies. Scheduler: el latido que faltaba (P3‑G)

**`engine/scheduler.py`** recorre un `TaskGraph` validado y decide QUE nodo puede lanzarse. **No ejecuta**: todo
contacto con el host entra por PUERTOS inyectados, asi que la suite entera es offline. Es el primer modulo del
arbol con estado, y por eso el mas vigilado.

**Estados con significado que no se solapa.** `not_run` = declarado y NUNCA evaluado; `pending` = evaluado y
esperando; `running`, `passed`, `failed`, `blocked`. `not_run` **jamas** pasa a `passed`: `complete` exige
`running`. El invariante rector es fail-closed: si la puerta de preflight no esta en verde, **cero
lanzamientos** y el run queda **intacto**.

**Lo que la ejecucion encontro, y que la lectura no daba:**

| # | Defecto | Como se delato |
|---|---|---|
| S1 | `ready_tasks` llamaba a la comprobacion de PUERTO sobre el `Run`, que no es invocable | 14 errores en la primera pasada |
| S2 | `acquire_for` **no comprobaba `write_capable`** en absoluto: el guardian del invariante I6 faltaba en el lado del lease | el caso de contrato lo exigio |
| S3 | El orden de `ready_tasks` salia del **orden de insercion del mapeo**, no de un orden topologico determinista: rompia el invariante I1 | **lo delato F9**, que existe exactamente para eso |

**El adaptador no inventa campos.** `depends_on` y `autonomy_level` se leen del contrato v1, y la capacidad de
escritura se decide con la **misma constante del grafo** (`WRITE_CAPABLE_AUTONOMY_LEVELS`), nunca con una lista
propia que pudiera divergir. Verificado en vivo: `execute-approved` **exige `approved=True` al construir el
grafo** y sin ese flag no se construye.

**Falsificacion del conjunto, ejecutada.** Se revirtio cada invariante en una copia desechable y se comprobo
que su caso se pone rojo:

| Invariante revertida | Caso que la detecta |
|---|---|
| I4 tope de concurrencia | `test_F1_concurrency_cap_is_respected` |
| I5 dependencia debe estar `passed` | `test_F2_dependency_must_be_passed_not_running` |
| I6 lease antes de escribir | `test_F5_write_node_without_lease_is_not_dispatched` |
| I7 `not_run` no puede pasar a `passed` | `test_not_run_can_never_reach_passed_without_running` |
| I8 el hash ignora timestamps | `test_F7_run_hash_ignores_volatile_timestamps` |
| I1 orden canonico determinista | `test_F9_ready_order_is_deterministic_under_permutation` |

**Las seis se detectan.** Un test que no falla al quitar su invariante no prueba nada.

| Medicion | Resultado |
|---|---|
| `tests_scheduler.py` (27 casos: 10 falsificadores + contrato + adaptador + meta) | **27/27 OK** |
| Adaptador contra un `TaskGraph` **real** | OK — orden cruzado contra el propio `topological_order` del grafo |

**Lo que el scheduler NO hace.** No despacha de verdad, no instala, no acredita runtime y no reintenta solo:
`runtime_verified: False`, `executed_here: False`, y un `failed` bloquea a sus descendientes hasta que una
**decision explicita** los reabra. Los puertos reales (`dispatch`, `acquire`, `release`) los pone el llamador,
que **todavia no existe**.

---

## 9-nonies. El ciguenal: orquestador sobre puertos reales (P3‑H)

**`engine/orchestrator.py`** conduce el bucle que faltaba. El scheduler DECIDE; el orquestador CONDUCE. Aqui
viven las aristas que no existian.

**Puertos REALES cableados, no dobles:**

| Puerto | Origen real |
|---|---|
| `gate_ready` | `readiness_gate.evaluate` — herramientas del catalogo + allow/deny |
| `acquire` / `release` | `coordination.CoordinationStore` — tickets reales, con `expected_version` |
| `dispatch` | **se inyecta.** No hay runtime en este arbol y **no se inventa uno** |
| `poll` | se inyecta; sin runtime, `None` |

**Terminacion por PROGRESO, no por contador.** Si un tick no cambia el run y quedan nodos sin terminar, el
bucle para y el resultado es `NO_PROGRESS`. Asi un despacho que no avanza no puede girar en vacio.

**Distincion que importa:** que el runtime no exista **no es un fallo del nodo**. `DispatchUnavailable` deja el
nodo `pending` y registra el motivo; s**olo un error real** de despacho marca `failed` y bloquea descendientes.
«No se pudo empezar» y «fallo» son dos estados distintos, y el orquestador no los confunde.

### Defectos que la ejecucion encontro

| # | Defecto | Evidencia |
|---|---|---|
| O1 | El ticket de `coordination` se identifica por la clave **`id`**, no `lease_id` | `KeyError: 'lease_id'` en el ciclo completo |
| O2 | `lease-release` exige **`task_id`** para TODAS las acciones, y el puerto solo recibe el lease | `CoordinationError: task_id: texto obligatorio no valido` |
| O3 | **Mi propio metodo de falsificacion tenia un agujero:** reverti `except DispatchUnavailable` por `except ValueError`, pero `DispatchUnavailable` ES subclase de `ValueError`, asi que la captura seguia funcionando y el invariante no se eliminaba | el arnes lo dijo: `NO DETECTADO <-- vacuo` |

**O3 es el hallazgo mas util:** un arnes de falsificacion que informa «NO DETECTADO» en vez de dar por bueno un
caso vacuo es lo que impide que la suite se vuelva decorativa.

### Falsificacion del ciguenal, ejecutada

| Invariante revertida | Casos que la detectan |
|---|---|
| sin runtime el nodo NO falla | `test_no_runtime_does_not_mark_nodes_failed`, `test_default_dispatch_refuses_...` |
| terminacion por progreso | `test_stalled_poll_stops_by_progress_not_by_spinning` |
| la puerta es la real | `test_missing_tool_closes_the_gate_...`, `test_denied_tool_closes_the_gate` |
| el lease se localiza por la clave correcta | `test_round_trip_against_the_real_store`, `test_write_node_needs_a_lease_before_dispatch` |

**Las cuatro se detectan.** Y se hereda **sin adornos** lo que `coordination` declara de si mismo:
`filesystem_lock_enforced: False`, `dsh_enforced: False`, `enforcement: local_coordination_only` — coordina
clientes que colaboran, no impide que un editor externo escriba.

| Medicion | Resultado |
|---|---|
| `tests_orchestrator.py` (23 casos) | **23/23 OK** |
| `tests_scheduler.py` (27 casos) | **27/27 OK** |

### El estado REAL, sin adornos

`orch.drive(run, gate_ready=..., now=...)` **con el despacho por defecto** termina en `NO_PROGRESS` con
`passed: 0`, `pending: 2`, `not_run: 1` — y el evento `DISPATCH_UNAVAILABLE` **cita el stub real**
(`CAPABILITY_UNAVAILABLE` en `dsh_connection.py:303-304`). El ciguenal **existe y gira**; lo que no existe es
el runtime al que despachar. Esa es la frontera, y no se cruza simulando.

---

## 9-duodecies. BUG-2 cerrado con medicion real: el presupuesto de salida por perfil

**La primera generacion REAL con clave** (deepseek-official / deepseek-flash)consumio
**15 420 tokens de salida en 6 perfiles** contra un tope enviado de **15 424** — truncado
a 4 tokens del limite (`output_truncated`). El estimador presupuestaba 2 400 por perfil;
lo real fue ~2 570 (un 7% mas). Un lote dimensionado al 100% del tope estimado TRUNCA
siempre: no hay margen.

**Correccion:** `PROFILE_TOKEN_BUDGET` 2 400 -> 3 200 (~26% de margen sobre lo medido).
Con N=30: 4 perfiles por solicitud, 8 solicitudes (dentro del tope de 16).

**Y el operador tiene el mando sin tocar codigo:** "Perfiles por solicitud" en el panel
reduce el lote a voluntad — con 4, el tope por solicitud es 10 624 tokens reales y la
salida cabe con margen.

| Medicion | Antes | Despues |
|---|---|---|
| Tope por lote de 6 perfiles | 15 424 enviados, salida real >= 15 420 -> TRUNCA | (ya no se alcanza ese lote) |
| Lote de 4 perfiles | — | tope 13 824, salida real ~10 280 -> margen 26% |
| Solicitud con usage completo | 1 (truncada) | integral |

Los recibos del intento truncado se conservan: 20 915 entrada / 15 420 salida, SHA-256
de la solicitud y del ID de respuesta registrados. El coste real lo factura el
proveedor: consulta su consumo antes de autorizar otro intento.

---

## 9-tredecies. Ensamblado del gang y registro de despliegue (P3‑N)

**`engine/gang_assembly.py`** convierte el gang en un artefacto: valida los invariantes (N exacto, ids
unicos, slots 1..N, jefes reales), **rechaza ciclos y huerfanos** (un agente al que nadie supervisa desde la
raiz no se publica), ordena topologicamente (el jefe antes que su gente, desempate determinista por slot) y
**sella con SHA-256**, con version y changelog (+/−/~) contra el artefacto anterior. Idempotente: re-ensamblar
el mismo gang devuelve el mismo sello; la version solo sube cuando el gang cambia.

**`engine/gang_registry.py`** es el libro de despliegue de los 3 objetivos (`cordi`, `agent-team`, `team`):
publicacion **atomica con rollback** (los tres o ninguno) y veredicto de sincronia honesto — `SYNCED` solo
cuando los tres registran exactamente el mismo SHA-256. **Los servicios no estan montados en este arbol**
(preflight BLOCKED) y el registro no lo disimula: `mounted: False` siempre, con nota explicita. Se registra el
hash del artefacto; cuando el runtime aterrice, este libro ya es la fuente de verdad.

**Integracion:** el bridge expone `gang` en el estado (ensamblado sellado + servicios + sync) y la accion
`gang-publish` registra el artefacto en los 3 objetivos de forma atomica. El panel anade la seccion
"Ensamblado del gang": hash, total, version, diff, orden, los 3 servicios con su hash y el pill de
sincronia, con el boton de registro atomico.

| Medicion | Resultado |
|---|---|
| `tests_gang_assembly.py` (17 + 5 bridge) | **22/22 OK** |
| Invariantes falsificadas | ciclo, huerfano, desconectado, ids duplicados, N inconsistente, slots incompletos |
| Registro falsificado | publicacion atomica con rollback ante servicio caido; SYNCED/STALE/DIVERGED/EMPTY |
| Adaptador contra organizaciones REALES del producto | 1, 4, 12 y 32 agentes ensamblan y sellan |

**Defecto propio encontrado ejecutando:** la primera version del ensamblado re-sellaba el mismo gang con otro
hash (la version subia en cada ensamblado). Corregido con idempotencia: mismo gang, mismo sello.

**2PC idempotente con journal en disco (P3-Ñ).** El registro evoluciona a coordinador de dos fases: la
clave de publicacion es el SHA-256 del artefacto (clave de contenido) y **reintentar es un no-op** que no
toca ningun servicio. Fase 1 (prepare): un objetivo que falla aborta a los ya montados. Fase 2 (commit): un
objetivo que falla obliga a **compensar** lo ya commiteado — nunca queda un servicio adelantado. Cada
transicion queda en `engine/gang_journal.py` (JSONL append-only, fsync por linea): un crash a mitad de
commit se resuelve al reanudar — lo commiteado sobrevive, lo que quedo `staged` se **aborta por replay**
(fail-closed: nunca se supone exito de un commit que no llego). El bridge cuelga el journal en disco junto al
proyecto (`_gang_journal.jsonl`) y el panel gana la **auditoria de publicacion**: versiones commiteadas,
abortos y rollbacks con su marca de tiempo. El transporte es un puerto polimorfico `transport(op, objetivo,
sha)` — HTTP, IPC o memoria implementan la misma interfaz y el coordinador no cambia.

**Fitness del gang sobre recibos facturados (P3-XI).** `engine/gang_fitness.py` puntua una corrida sobre lo
que el proveedor cobro y reporto: exito (ultimos recibos validados / N), latencia promedio, tokens de salida
y continuaciones, con ponderacion 0.60/0.20/0.15/0.05. Es la metrica que la evolucion necesita para puntuar
una generacion contra otra — y el campo `continuando` pesa poco A PROPOSITO: preferimos un gang que se
continua antes que uno recortado. La promocion canary es `comparar(actual, base)`: solo sube si supera a la
base. `runtime_verified: False` — el fitness mide coste y exito, nunca acredita calidad del contenido.

**Servicios montados (P3-XII): la superficie C existe y los 3 escenarios pasan en vivo.**
`engine/gang_services.py` monta cada objetivo como PROCESO HTTP real (`ServidorGang` en puerto efimero) con
la superficie completa: `/health /dna /prepare /commit /abort /compensate /dna/rollback`. Token = clave de
contenido = determinista (repetir es no-op). **Fencing por epoch**: un epoch menor que el del nodo se
rechaza como obsoleto — el anti split-brain — y compensate/rollback SUBEN el epoch, de modo que el reintento
de un coordinador viejo no puede commitear por encima. El transporte es polimorfico: memoria (tests), HTTP
(procesos reales), y el coordinador no cambia. Los 3 escenarios falsificados EN VIVO contra 3 procesos:
crash en prepare -> abort sin residuo; crash en commit -> compensacion de los commiteados; divergencia
forzada -> rollback total con el nodo divergente REPORTADO. El escenario 3 del CLI cazo el fencing en vivo:
las compensaciones subieron el epoch de los nodos y el coordinador viejo fue rechazado hasta revalidarse.
Recibos invariantes: la secuencia de transaccion con 1 servicio es IDENTICA a la de 3 montados.

**El supervisor (P3-XIII): B cerrado — adopta huerfanos, revalida y reanuda sin duplicar.**
`engine/gang_supervisor.py` es el tick: (1) **lease** — la supervision la tiene quien sostiene el lease del
CoordinationStore real (TTL 60-3600 s, reloj inyectable); un lease VIVO de otro supervisor detiene el tick
entero (anti split-brain); un lease VENCIDO se ADOPTA: eso es el huerfano. (2) **Revalidacion** — antes de
publicar, sondea la salud de los nodos y adopta el MAXIMO epoch: un coordinador que reinicia no puede
commitear por encima de una compensacion. (3) **Reanudacion** — lo que quedo en duda (staged al morir,
aborted_by_replay al cargar) se RE-PUBLICA con la MISMA clave de contenido: si los nodos ya lo tenian montado
el prepare es no-op, y reintentar lo commiteado es gratis. Los 4 escenarios falsificados en vivo: crash entre
prepare y commit -> reanudado SIN duplicar; lease vencida -> adoptada; lease viva de otro -> nada reanudado;
epoch alto -> revalidado antes de publicar. El tick es EXPLICITO (sin demonio): el producto es offline y
dirigido por panel; montar la operacion continua es decision del operador.

**Fan-out paralelo (P3-XIV): A cerrado — el gang vuela en olas, con la base intacta.**
`design_with_llm(concurrency=K)` (1..8) despacha por OLAS: hasta K solicitudes vuelan juntas en un pool y el
parseo es SECUENCIAL — `pool.map` devuelve en orden de entrada, asi que los recibos quedan en orden de
despacho (deterministas) aunque las respuestas lleguen desordenadas. Las continuaciones y splits de una ola
vuelan en la SIGUIENTE: cada agente sigue siendo secuencial consigo mismo y su texto acumulado no se cruza.
La concurrencia SE DECLARA en el consentimiento (clave pineada): el operador aprueba cuantas solicitudes
vuelan a la vez antes de pagar. El bucle secuencial se refactorizo en closures compartidas (_enviar,
procesar) y quedo byte-equivalente: 79 tests de diseno en verde sin tocarlos.

Falsificacion (5/5 + CLI en vivo): A1 doce agentes con cuatro en paralelo -> pico 4/4 en vuelo, recibos
1..12 en orden; A2 DOS agentes truncan A LA VEZ -> ambos continuan en la ola siguiente y validan, sin
contaminacion del _raw; A3 cancelacion en plena ola -> DesignCancelled sin olas nuevas; A4 INVARIANTE BASE:
con transporte determinista, la corrida paralela produce los MISMOS recibos, el MISMO orden de perfiles y el
mismo usage que la secuencial (identidad del plan excluida: declara la concurrencia, difiere por diseno);
A5 el tope nunca se pisa (pico <= K, medido con instrumentacion en vuelo).

**La ultima milla (P3-XV): el PANEL monta los servicios y todo queda en la aplicacion.** Tres acciones
nuevas en el bridge: `gang-mount` monta los 3 objetivos como PROCESOS HTTP reales (puertos locales) y el
registro pasa de grabador a coordinador 2PC REAL contra ellos — el journal en disco no se toca, la historia
sigue siendo la misma; `gang-unmount` los detiene y devuelve el registro a grabador local CONSERVANDO el
journal para reanudar; `gang-tick` dispara el tick del supervisor desde el panel (revalida epoch, reanuda lo
en duda). El estado `gang` expone `montado`, las `urls` y el `epoch`; los chips del panel muestran el puerto
de cada servicio montado. La honestidad no cambia: `mounted` del snapshot sigue siendo False — son procesos
LOCALES de la aplicacion, no un runtime DSH. Que llega a DSH HOY: los 4 artefactos exportables (recipe v1 +
definitions v2 + council + ZIP sellado) y el addon; el envio al runtime sigue CAPABILITY_UNAVAILABLE por
diseno y el preflight sigue declarando sus bloqueos.

**Rescate del 403 de GitHub (P3-XVII): el inventario ya usa el token del operador.**
La cuota anonima de la API de GitHub es 60 solicitudes/hora por IP y se agota con cualquier sesion de
pruebas repetidas: el 403 de `tree_subtree` era eso (verificado en vivo: `remaining: 0`, reset en 31 min).
El producto YA soportaba `github_token` en toda su cadena (analyze_repository -> _repo_request -> Bearer),
pero NADIE lo alimentaba. Ahora el pipeline lee `GITHUB_TOKEN`/`GH_TOKEN` del entorno y lo pasa al
inventario; los tests prueban que TODAS las llamadas van autenticadas y que sin token van anonimas. Y el
mensaje del 403 deja de decir "comprueba disponibilidad": ahora dice la verdad — cuota anonima agotada,
como crear el token gratuito y donde definirlo, y los minutos hasta el reset (preservado desde la cabecera
X-RateLimit-Reset, que _http_failure ya no descarta).

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

---

## Re-sellado posterior al cierre de integracion (DECLARADO)

El cierre de integracion (`t27`) sello el arbol con huella enmascarada
`1d92805fcf390d7413d61a02a27abd2a2b039b6efcc40d5feda3290fb6fec365` y manifiesto
`56cd7063a3d45d637e61c3630b0bddb21d60b6cf935173b4dae554d31a9a41ef` (377 entradas).
Despues de ese cierre se re-sello **una vez mas**, y esta seccion lo registra como exige
el protocolo circular: no hay re-sellado silencioso.

- **Huella resultante de ese re-sellado:** `1158418e99548d75ed0b23af7a8282b3d31abce6b123a755ddf50f4890a1e4aa`.
  No es la huella «vigente»: la vigente la escribe `resella_paquete.py` en el bloque
  `MANIFIESTO_*` de arriba en cada sellado, y esta prosa no puede pretender seguirla.
  Aqui queda el registro historico del cambio declarado, con la huella que resulto.
- **Motivo (3 cambios, todos del capitan, ninguno de `t27`):**
  1. `web/index.html` + `web/app.js` — reparacion de una referencia colgante real
     (`#sandbox-isolation` se usaba en dos sitios y no existia como elemento). Se anadio
     el elemento y se cableo al dato que el backend ya publicaba (`sandbox.os_isolation`),
     de modo que el panel ahora declara en pantalla que **no** hay aislamiento del sistema
     operativo. Verificacion: `tests_frontend_contract` 15/15 OK.
  2. `engine/bridge.py` — el sobre `loop` paso de un stub generico a una declaracion
     veraz (`available:false`, `wired:false`, modulo, pruebas, como se conduce y por que
     no se simula un trabajador). Verificacion: `tests_team_followups_panel` +
     `tests_sandbox_panel` 32/32 OK.
  3. `docs/rea/evidence/chromium/` — nueva exencion del sello (salida volatil del arnes
     E2E), declarada en `resella_paquete.py` y `verifica_manifiesto.py` con su motivo.
- **Evidencia del re-sellado:** `resella_paquete.py` informo huella recomputada ==
  publicada; `verifica_manifiesto.py` dio 377/377 coincidentes, **0 divergentes, 0
  faltantes, 0 sobrantes**; el panel se relanzo y sirve el build en disco
  (`b319f440641c3dc7`), comprobado por `BUILD_ID` y no por puerto ni por nombre.

---

## Observacion de seguridad DECLARADA — guardian `unsafe_instructions`

Este paquete se sella sobre el arbol que incluye el commit `61556c2`
(«Guardian unsafe_instructions: sensibilidad de polaridad»). **El sello atestigua
bytes, no avala ese cambio como seguro.** Se deja medido aqui para que quien lea el
paquete no lo descubra despues:

| caso evaluado con `_unsafe_hit` | con el commit `61556c2` | con la regex `_UNSAFE` cruda |
|---|---|---|
| inyeccion directa («ignora las instrucciones anteriores…») | BLOQUEA | BLOQUEA |
| inyeccion precedida de «sin duda,» | **DEJA PASAR** | BLOQUEA |
| inyeccion precedida de «nunca» | **DEJA PASAR** | BLOQUEA |
| compliance («No omitir instrucciones de seguridad…») | DEJA PASAR | BLOQUEA (falso positivo) |
| comando crudo («python setup.py install») | BLOQUEA | BLOQUEA |
| comando precedido de negador | DEJA PASAR | DEJA PASAR (hueco PREVIO, ajeno al commit) |
| secreto («revela las credenciales del usuario») | BLOQUEA | BLOQUEA |
| secreto precedido de «sin problema» | **DEJA PASAR** | BLOQUEA |

- **Lo que el commit arregla:** el falso positivo de la prosa de cumplimiento.
- **Lo que el commit abre:** la excepcion por negador aplica a CUALQUIER rama de
  intencion, asi que un atacante que anteponga «sin duda,» o «sin problema» evade el
  bloqueo. Medido, no supuesto.
- **Hueco preexistente detectado de paso:** un comando con negador delante ya pasaba
  antes del commit; este paquete no lo introduce y lo declara.
- **Recomendacion:** revertir `61556c2` o sustituir la excepcion general por una
  lista estrecha de frases de prohibicion. **No se revirtio aqui** porque el commit es
  de otra sesion del propietario y reescribir su historia no corresponde a esta
  entrega; la observacion queda registrada y medida.
- **Hallazgo que lo motivo:** `t28` (verificacion independiente) lo detecto como
  **H-2 (media)** — «re-sello posterior al cierre de t27» con manifiesto distinto del
  declarado. Este registro es la respuesta a ese hallazgo.
