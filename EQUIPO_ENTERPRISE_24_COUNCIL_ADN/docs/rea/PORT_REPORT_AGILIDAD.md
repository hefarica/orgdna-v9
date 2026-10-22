# RE-B — Informe de port: gate Tier 2 de agilidad (adopción verbatim)

**Estado: GATE TIER 2 CERRADO.** Autorizados **2 fragmentos verbatim de 2 fuentes** (Apache-2.0 y
MIT, licencia leída en el sha), con rango, blob SHA, `sha256` del fragmento y vectores de paridad.
**Cinco fuentes más quedan resueltas con veredicto explícito de no copia** (una por licencia, tres por
razón técnica declarada, dos por port ya existente). **En esta tarea no se ha copiado ninguna línea de
código ajeno**: la copia es de `t30`.

- Autoriza: `docs/security/FUSILE_SOURCE_POLICY.md` §«ENMIENDA PERMANENTE — código verbatim»
  (marca literal del operador, 2026-10-21), con la condición única de no-código-malicioso y las 5
  exclusiones. Las obligaciones Tier 2 (a)–(f) siguen vigentes.
- Licencias y método: `docs/rea/license_audit.md` (Tabla A, 7 fuentes, huellas de cada licencia).
- Catálogo de mecanismos y vectores de comportamiento: `docs/rea/agile_agents_survey.md` (M1–M8) y
  `docs/rea/agile_vectors.json` (AV-01…AV-26).
- Contrato congelado que gobierna el destino: `docs/rea/TEAM_API_CONTRACT_v1.md` (C-1…C-5 y el
  vocabulario de §1).

---

## 1. Decisión ejecutiva

| Fuente | Licencia al sha | Veredicto de adopción |
|---|---|---|
| `ag2ai/ag2@0938ebd` | Apache-2.0 (SPDX en el propio fichero) | **SE COPIA VERBATIM**: `ag2/events/conditions.py` (144 líneas) → M2 |
| `FoundationAgents/MetaGPT@11cdf46` | MIT | **SE COPIA VERBATIM** (con adaptación): `metagpt/team.py` líneas 87–100 → M5 |
| `langchain-ai/langgraph@3cd57c0` | MIT | **NO SE COPIA**: M1 ya congelado e implementado; almacén y `uuid6` rechazados por razón técnica (pickle / `random`) |
| `agentscope-ai/agentscope@8a2aef4` (y `@26ec620`) | Apache-2.0 | **NO REQUIERE COPIA**: port ya validado con vectores |
| `OpenBMB/ChatDev@a2ea4a2` | Apache-2.0 | **NO REQUIERE COPIA**: port ya validado bajo puertas |
| `microsoft/autogen@004749e` | CC-BY-4.0 | **NO COMPATIBLE**: se reimplementa |
| `Significant-Gravitas/AutoGPT@8d4a965` | PolyForm Shield + MIT (split) | **NO COMPATIBLE** en `autogpt_platform/**`; nada adoptado |

Regla que se aplicó: *no se copia lo que ya está congelado o ya está portado; se copia lo que ahorra
semanas y no colisiona con un contrato congelado*. Esa regla deja el valor real en **M2** y **M5**,
que es justo lo que falta en el destino.

---

## 2. Por qué el valor real ya no está en M1 (checkpoint)

`t21` propuso M1 (checkpoint durable + reanudación) como el mecanismo de mayor valor, y langgraph como
su fuente natural. Al abrir el gate, el estado del destino cambió la conclusión:

1. **`TEAM_API_CONTRACT_v1` ya congeló el checkpoint** (`docs/rea/TEAM_API_CONTRACT_v1.md`): regla
   **C-2** — «El checkpoint v1 de §4 es el **único** formato de estado durable. Añadir, quitar o
   re-tipar una clave exige `checkpoint_version = 2`»; `CHECKPOINT_VERSION = 1`,
   `CHECKPOINT_SCHEMA = 'orgdna.team_process.checkpoint/1'`, `CHECKPOINT_KEY =
   'orgdna.team_process.checkpoint'`.
2. **`engine/team_process.py` ya lo implementa** (tarea t22; existe en el árbol) con superficie
   congelada (`export_checkpoint`, `import_checkpoint`, `from_checkpoint`, `checkpoint_digest`) y
   `tests_team_process.py` (43 020 B) contra los 26 vectores `AV-01…AV-26` de
   `docs/rea/agile_vectors.json`.
3. Copiar el contrato de checkpoint de langgraph **forkearía** un formato ya congelado: violaría C-2
   y duplicaría estado. Por eso los fragmentos LG-F1/F2/F3 quedan **verificados y no copiados**.

Lo que **sí** falta en el destino es `engine/team_loop.py` (t23), y su contrato ya define el
vocabulario exacto donde encajan los dos fragmentos adoptados:

```
CYCLE_STATES      = ('not_run', 'running', 'incomplete', 'completed', 'budget_exhausted')
STOP_REASONS      = ('stop_requested', 'stopped_before_start', 'time_exhausted',
                     'budget_exhausted', 'lease_held', 'cycles_completed')
RECEIPT_MOTIVES   = ('completed', 'incomplete', 'budget_exhausted', 'time_exhausted',
                     'stop_requested', 'checkpoint_write_failed')
BUDGET_DIMENSIONS = ('steps', 'seconds', 'delegations', 'tokens')
EXHAUSTION_REASONS= ('steps', 'seconds', 'delegations', 'tokens')
LOOP_SCHEMA       = 'orgdna.team_loop/1'
```

Los dos fragmentos aportan la **lógica de decisión** que el contrato deja abierta: *cuándo* un
predicado pide parada (M2) y *cómo* se compara el consumo con el techo (M5). Ninguno de los dos
inventa códigos: emiten el vocabulario congelado de arriba.

---

## 3. Tabla B — fragmentos evaluados (veredicto y trazabilidad completa)

Rangos 1-based inclusive. `sha256 del fragmento` = líneas unidas con `\n`, UTF-8 sin BOM, sin salto
final. `blob` = `git hash-object` del fichero completo en ese sha.

### 3.1 Adoptados (verbatim autorizado)

| ID | Fuente@sha | Ruta | Blob SHA | Rango | Tamaño | `sha256` del fragmento | Licencia | Veredicto | Destino | Vectores | Qué se adapta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **AG-F1** | `ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e` | `ag2/events/conditions.py` | `67b72fc7fd84ad43394df75e515ac05bc73287fc` | 1–144 (144 líneas) | 4 151 B | `01647ee672e18da5a663d42aa022f0c2715c3c5bdf0f2a92316e33ecbb0b22e3` | **Apache-2.0** (SPDX en cabecera, L1–3) | **SE COPIA** | `engine/team_loop.py` (M2) | `test/events/test_conditions.py` (blob `d7108a3f8d8d2336144ee2f1310b2e2ac4a392e6`, 250 líneas, 27 casos) | `ag2.types.ClassInfo` → alias local `type \| tuple[type, ...]`; eventos propios por clave en vez de atributos; los predicados se mapean a `STOP_REASONS` congelados |
| **MG-F1** | `FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f` | `metagpt/team.py` | `5a9838885070add38a7cdd3ddf034ea40768d4b2` | 87–100 (14 líneas) | 598 B | `d13e885a69080987ea0d5d541cecb2e1a60ce1c57165eca9a505dbc24083b192` | **MIT** | **SE COPIA** (con adaptación) | `engine/team_loop.py` + `engine/team_process.py` (M5) | derivados del predicado (el fuente **no** trae test de `_check_balance`) + forma de acumulación de `tests/metagpt/utils/test_cost_manager.py` (blob `9508c778f45191c035d4ef018c69d8a7cffc3e2a`, 32 líneas) | `NoMoneyException` → código congelado `budget_exhausted`; contadores → `BUDGET_DIMENSIONS`; **sin** tablas de precios (FUSILE regla 4) |

### 3.2 Evaluados y **no** copiados (con razón explícita)

| ID | Fuente@sha | Ruta | Blob SHA | Rango(s) | Tamaño | `sha256` del fragmento | Licencia | Veredicto / razón |
|---|---|---|---|---|---|---|---|---|
| LG-F1 | `langchain-ai/langgraph@3cd57c0` | `libs/checkpoint/langgraph/checkpoint/base/__init__.py` | `c7cacc7bfd703f298427e870bd6d07b4aa395812` | 31–148 (118 líneas) | 4 202 B | `fad65b12713647ebe8a17fab6c942006a93b5c4f5cace2cb1210939f2288452c` | MIT | **NO** — M1 congelado (C-2) e implementado; copiar forkearía el formato |
| LG-F2 | idem | idem | idem | 185–196 (12 líneas) | 506 B | `736347d2593be7a807c110b4fde8e0f16c3ae9540912c549f9cb29478c0a9d24` | MIT | **NO** — el orden determinista de escrituras ya vive en el checkpoint v1; `writes_sort_key` queda citado como **dato** |
| LG-F3 | idem | idem | idem | 781–836 (56 líneas) | 1 919 B | `1fabe7395687b057772f6e6cc39912071f505ba4b9a71b04422ca553a0a209c6` | MIT | **NO** — `WRITES_IDX_MAP = {ERROR:-1, SCHEDULED:-2, INTERRUPT:-3, RESUME:-4}` y `EXCLUDED_METADATA_KEYS` son valores del formato ajeno; el v1 propio no los usa |
| LG-R1 | idem | `libs/checkpoint/langgraph/checkpoint/memory/__init__.py` | `ff6f7b1caaab88f01363dc8d6b249d5ad0c338e8` | 34–124, 430–520, 622–633 (evaluados) | 707 líneas | — | MIT | **NO** — `pickle` (L5, L688, L698), `shutil`/`os` (L7, L669/673/675) y `random.random()` en `get_next_version` (L630): deserialización insegura + no determinismo. Se **reimplementa** con sus vectores |
| LG-R2 | idem | `libs/checkpoint/langgraph/checkpoint/base/id.py` | `30abc48a509601216fe7ddee3be55ceaa6cd93bd` | 1–109 | 3 647 B | — | MIT | **NO** — `random.getrandbits` (L100, L102) y `time.time_ns()` (L96); además linaje de terceros («Adapted from oittaa/uuid6-python»). Ids propios = digest determinista |
| MG-R1 | `FoundationAgents/MetaGPT@11cdf46` | `metagpt/team.py` | `5a9838885070add38a7cdd3ddf034ea40768d4b2` | 32–86 y 101–138 | 138 líneas (total) | — | MIT | **NO** — `serialize`/`deserialize`/`hire`/`run_project` arrastran pydantic + `Environment`/`Context`/`Role`: no es fragmento mínimo |
| AS-NOTE | `agentscope-ai/agentscope@8a2aef4` (y `@26ec620`) | `_team_pipeline.py`, `_in_memory_message_bus.py`, `_middleware.py` | — | — | — | — | Apache-2.0 | **NO REQUIERE COPIA** — port validado con vectores (`engine/team_channel.py`, `engine/team_memory.py`; `PORT_REPORT.md:25-26`; `docs/rea/agentscope_vectors.json`) |
| CD-NOTE | `OpenBMB/ChatDev@a2ea4a2` | `runtime/node/executor/python_executor.py` | — | — | — | — | Apache-2.0 | **NO REQUIERE COPIA** — port validado bajo puertas (`engine/sandbox_executor.py`, 3 suites; `PORT_REPORT.md:27`); su fragmento natural (subproceso) queda del lado seguro de la exclusión 4 |
| AU-NO | `microsoft/autogen@004749e` | — | — | — | — | — | **CC-BY-4.0** | **NO COMPATIBLE** — no es licencia de software: M2/M5 se reimplementan |
| AGPT-NO | `Significant-Gravitas/AutoGPT@8d4a965` | — | — | — | — | — | **PolyForm Shield + MIT (split)** | **NO COMPATIBLE** en `autogpt_platform/**`; nada seleccionado (t21 la usó solo como referencia) |

---

## 4. Vectores de paridad

### 4.1 AG-F1 (adoptado) — casos del fuente, con valores

Fuente: `test/events/test_conditions.py` en `ag2ai/ag2@0938ebd` (blob
`d7108a3f8d8d2336144ee2f1310b2e2ac4a392e6`; 250 líneas; clase `TestEventConditions`). El evento de
prueba es `TestEvent(field: int | str | None)`; el valor esperado es el booleano del predicado.

| Caso (test del fuente) | Línea | Predicado | Entrada → esperado |
|---|---|---|---|
| `test_equality_condition_string` | 23 | `field == "1"` | `field="1"`→**True**; `field="2"`→**False**; `field=2`→**False** (igualdad **estricta de tipo**) |
| `test_equality_condition_integer` | 30 | `field == 42` | `42`→**True**; `41`→**False**; `"42"`→**False** |
| `test_inequality_condition` | 37 | `field != "1"` | `"1"`→**False**; `"2"`→**True**; `2`→**True** |
| `test_less_than_condition` | 44 | `field < 10` | `5`→**True**; `9`→**True**; `10`→**False**; `15`→**False** |
| `test_less_than_or_equal_condition` | 52 | `field <= 10` | `5`→**True**; `10`→**True**; `11`→**False** |
| `test_greater_than_condition` | 59 | `field > 10` | `10`→**False**; `11`→**True**; `20`→**True** |
| `test_greater_than_or_equal_condition` | 66 | `field >= 10` | `9`→**False**; `10`→**True**; `20`→**True** |
| `test_and_condition` | 73 | `(field > 0) & (field < 10)` | `5`,`1`,`9`→**True**; `0`,`10`→**False** |
| `test_or_condition` / `..._with_class` / `..._with_class_first` / `..._with_class_or_method` / `..._with_union_classes` | 84, 93, 101, 108, 115 | `or` de valores y de clases/uniones | **True** si el evento satisface cualquiera; **True** si es instancia de la clase de la condición |
| `test_and_method` / `test_or_method` / `test_not_method` | 121, 132, 148 | `and_()` / `or_()` / `not_()` | mismos resultados que los operadores `&`, `\|`, `~` |
| `test_not_condition` | 141 | `~(field == "1")` | `"1"`→**False**; `"2"`→**True** |
| `test_complex_condition` / `test_chained_conditions` | 155, 194 | composiciones anidadas | sin excepción; resultado booleano determinista |
| `test_condition_matches_subclass` | 203 | condición sobre clase base | evento de la subclase →**True** |
| `test_child_condition_does_not_match_parent` | 209 | condición sobre subclase | evento de la base →**False** |
| `test_reading_an_inherited_field_elsewhere_does_not_retarget_a_condition` | 215 | campo heredado | el predicado no se redirige a otra clase |
| `test_event_with_multiple_fields` / `test_condition_with_none_value` / `test_condition_with_is_none_value` / `test_condition_with_boolean` | 166, 173, 180, 187 | campos múltiples, `None`, `is None`, booleanos | valores esperados del fuente, uno por caso |

Dos detalles del fragmento que **son parte del contrato de paridad** y no se pueden «simplificar»:
`check_eq(x, y)` exige `isinstance(x, type(y))` (por eso `field=2` no satisface `== "1"`), y
`OpCondition.__repr__` usa el mapa `op_names` (L136–144) para imprimir el operador.

### 4.2 MG-F1 (adoptado) — vectores **derivados** del predicado del fuente

El fuente **no trae test de `_check_balance`** (verificado: `tests/metagpt/test_team.py` solo contrata
un rol; `tests/metagpt/serialize_deserialize/test_team.py` usa `max_budget` pero no prueba el corte).
El vector se deriva del predicado literal del fragmento (línea 99: `if self.cost_manager.total_cost >=
self.cost_manager.max_budget: raise NoMoneyException(...)`) y **se declara como derivado**:

| Vector | Entrada | Salida esperada |
|---|---|---|
| `invest` fija el techo | `invest(3.0)` | `cost_manager.max_budget == 3.0` |
| por debajo del techo | `total_cost = 2.999`, `max_budget = 3.0` | `_check_balance()` **no** lanza |
| **borde exacto** | `total_cost = 3.0`, `max_budget = 3.0` | **lanza** (el predicado es `>=`, no `>`) |
| por encima | `total_cost = 3.001`, `max_budget = 3.0` | **lanza** |
| sin `invest` previo | `max_budget` del cost manager inyectado | se usa tal cual; **la cifra no se copia** (configuración, FUSILE regla 4) |

Forma de acumulación (del test del fuente `test_cost_manager.py`, L14–31, blob `9508c778…`): tras dos
`update_cost(...)` los totales son **monótonos no decrecientes** y `get_costs().total_cost ==
get_total_cost()`; se adopta **la forma de la aserción**, no las cifras (los precios por modelo son
configuración del fuente y la regla 4 prohíbe copiarlos como literal).

### 4.3 LG-* (no copiados) — vectores disponibles si el operador abre `checkpoint_version = 2`

`libs/checkpoint/tests/test_memory.py` (blob `7c350ab96209706e4540f3887afdd0097d766629`, 722 líneas)
contiene los casos que servirían: `test_combined_metadata` (L81: `metadata` del resultado = metadata
del checkpoint **más** `config["metadata"]`, p. ej. `{'run_id': 'my_run_id'}`), la semántica de
`CheckpointTuple` (5 campos), los valores de `WRITES_IDX_MAP` y `get_checkpoint_id(config)` desde
`configurable`. No se copian hoy: C-2 congela el formato v1 propio y ese contrato no los necesita.

---

## 5. Cumplimiento de la enmienda (5 exclusiones) y de las obligaciones Tier 2

### 5.1 Exclusiones — verificación sobre los dos fragmentos adoptados

Escaneo de los fragmentos (AG-F1 completo, MG-F1 87–100) por `socket`, `urllib`, `requests`, `http`,
`subprocess`, `os.system`, `eval(`, `exec(`, `__import__`, `open(`, `pickle`, `random`, `time.` →
**0 hallazgos** (los dos fragmentos son lógica pura; MG-F1 no tiene ni un import).

| Exclusión de la enmienda | AG-F1 | MG-F1 | Nota |
|---|---|---|---|
| 1. Exfiltración de datos/credenciales/telemetría | limpio | limpio | sin I/O ni red |
| 2. Red/sockets/URLs/proveedores | limpio | limpio | no se importa nada de red |
| 3. Evasión de las 8 puertas / gobernanza de memoria / aislamiento | limpio | limpio | no tocan `policy_engine`, `memory_governance` ni `tenants`; el bucle sigue bajo puertas |
| 4. Comandos de sistema fuera del sandbox gobernado | limpio | limpio | sin `subprocess`; el ejecutor sigue siendo `engine/sandbox_executor.py` bajo puertas |
| 5. Tocar DSH | limpio | limpio | ninguna ruta ni import de DSH |

### 5.2 Obligaciones Tier 2 (a)–(f) — estado

| Obligación | Estado |
|---|---|
| (a) Citar `owner/name@<sha>` en el docstring y en el mensaje de cambio | **Pendiente de `t30`** (aquí queda el sha exacto y la cita lista) |
| (b) Resolver la licencia **leída en ese sha** y declararla | **CUMPLIDA** — `docs/rea/license_audit.md` §2 (Tabla A, 7 fuentes con `sha256` del texto) |
| (c) Traer los **vectores de prueba del fuente** y demostrar paridad en el destino | **Preparada** — §4 (AG-F1: 27 casos con valores; MG-F1: 5 vectores derivados + 1 hueco declarado). La demostración se ejecuta en `t30` |
| (d) Dejar la suite del destino en verde antes de aceptar el port | **Pendiente de `t30`** (prohibido correr la suite completa en esta tarea) |
| (e) No copiar addresses/keys/tokens/endpoints/configuración de despliegue | **CUMPLIDA** — los fragmentos no contienen ninguno; las cifras de coste del fuente **no** se copian (§4.2) |
| (f) Registrar la entrada en `docs/rea/PORT_REPORT.md` con sha, licencia y vectores | **Pendiente de `t30`** — `PORT_REPORT.md` está fuera de mi inScope; este informe es el contenido listo para esa entrada |

---

## 6. Instrucciones de ejecución para `t30` (checklist cerrado)

**AG-F1 — `engine/team_loop.py` (M2)**

1. Copiar `ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e:ag2/events/conditions.py`
   **líneas 1–144 tal cual**, **incluida la cabecera de copyright y `SPDX-License-Identifier:
   Apache-2.0`** (L1–3). Verificar tras copiar: `sha256` del bloque = `01647ee6…0b22e3` y blob del
   fichero original = `67b72fc7…`.
2. Docstring de cabecera del módulo con: cita `ag2ai/ag2@0938ebd`, mención literal
   «ENMIENDA PERMANENTE — código verbatim», licencia Apache-2.0 y **declaración de cambios**
   (obligación Apache-2.0 §4(b)): `ClassInfo` → alias local; acceso a campo por clave de evento;
   mapeo de predicados al vocabulario `STOP_REASONS` congelado.
3. **Prohibido** inventar códigos de parada: los únicos válidos son `CYCLE_STATES`/`STOP_REASONS`/
   `RECEIPT_MOTIVES` de `TEAM_API_CONTRACT_v1` §1. La condición decide **entre ciclos**, nunca a mitad
   de una escritura de checkpoint (C-4/C-5).
4. Conservar la atribución Apache-2.0 del repo (aviso de copyright + nota de cambios). Si el repo no
   tiene aún un fichero de avisos de terceros, incluirlo es decisión del operador (crear ficheros
   nuevos no estaba en mi inScope).

**MG-F1 — `engine/team_loop.py` + `engine/team_process.py` (M5)**

5. Copiar `FoundationAgents/MetaGPT@11cdf46:metagpt/team.py` **líneas 87–100** adaptando:
   `NoMoneyException` → error tipado con el código congelado `budget_exhausted`; `cost_manager` →
   los contadores de `BUDGET_DIMENSIONS`; **no** copiar la tabla de precios ni los defaults del fuente.
6. Incluir el texto MIT del fuente (`LICENSE` 1 072 B, `sha256 74945da6…`) en el bloque de avisos de
   terceros del repo, como exige MIT, junto a la cita `FoundationAgents/MetaGPT@11cdf46`.
7. Paridad: implementar los 5 vectores de §4.2 en la suite del destino (incluido el **borde exacto**
   `total_cost == max_budget → corte`).

**Verificación y registro**

8. Ejecutar la suite del destino del flujo (`tests_team_loop.py` / `tests_team_process.py`) y dejarla
   en verde; luego `python -m unittest discover … -p 'tests_team_*.py'` (prohibido correr la suite
   completa aquí; en `t30` aplica la política de verificación que fije el capitán).
9. Registrar la entrada en `docs/rea/PORT_REPORT.md` (obligación (f)) con: fragmento, `fuente@sha`,
   blob SHA, rango, `sha256` del fragmento, licencia, vectores y destino.

---

## 7. Límites de este informe (fail-honest)

1. **No hay test del fuente para `_check_balance`**: el vector de MG-F1 es **derivado** del predicado
   (línea 99) y se declara como tal. No se presenta como si fuera un test copiado.
2. **No verifiqué la ruta de `NoMoneyException`** en el paquete MetaGPT (`metagpt/utils/custom_exception.py`
   y `custom_exceptions.py` dieron 404). No hace falta: la adaptación usa el código congelado
   `budget_exhausted`, que es más estricto que la excepción del fuente.
3. **Los fragmentos LG-*** quedan con evidencia completa (blob, rango, `sha256`) por si el operador
   abre `checkpoint_version = 2`, pero **no están autorizados a copiar hoy**. El motivo no es la
   licencia (MIT, compatible) sino el congelamiento C-2 y la higiene: `pickle` en el almacén y
   `random` en el versionado e ids.
4. **No se copió ni una línea de código ajeno** en esta tarea: los dos archivos que escribí son
   documentos (`docs/rea/license_audit.md`, `docs/rea/PORT_REPORT_AGILIDAD.md`). La única cita literal
   de las fuentes es la cabecera de copyright/SPDX de AG2 (3 líneas de comentario) usada como prueba
   de licencia en `license_audit.md` §3.5; control automático: ninguna otra línea de más de 40
   caracteres de los ficheros fuente aparece en los dos documentos.
5. **El registro en `docs/rea/PORT_REPORT.md`** y la copia efectiva son de `t30`; el gate deja la
   decisión cerrada, la licencia probada y los vectores listos, que es exactamente lo que faltaba
   para que nadie copie «de memoria».

---

## 8. Adopción verbatim ejecutada (`t30`) — tabla final

> Sección escrita por `t30`, que es quien copia. Cierra el gate de `t29`: cada fila tiene fragmento,
> `fuente@sha`, licencia SPDX, líneas, test de paridad y veredicto. Los dos bloques llevan la nota
> `ENMIENDA PERMANENTE - codigo verbatim`, la cita `owner/name@sha` y la declaración de cambios en su
> cabecera; la **superficie pública del contrato no cambió** (`TeamProcess`/`TeamLoop`, §1 y §3
> intactos) y `tests_team_process.py` / `tests_team_loop.py` siguen **sin editar**:

| Test congelado | `sha256` en `t22`/`t23` | `sha256` tras `t30` | ¿Editado? |
|---|---|---|---|
| `tests_team_process.py` (50 casos) | `cf9a81dac0884924f14999adb2660fc6ab0839268f43f5c4cc882e6908eb4f25` | idéntico | **no** |
| `tests_team_loop.py` (44 casos) | `d147d7fe466a2c2e0cba48fd0b44c3048d4fbb05d1e212675e0b999d5f321221` | idéntico | **no** |

### 8.1 Tabla final de adopción

| Fragmento | Fuente@sha | Ruta:líneas | Blob | `sha256` del fragmento | Licencia SPDX | Destino (bloque) | Test de paridad | Veredicto final |
|---|---|---|---|---|---|---|---|---|
| **AG-F1** | `ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e` | `ag2/events/conditions.py` L1–144 (144) | `67b72fc7fd84ad43394df75e515ac05bc73287fc` | `01647ee672e18da5a663d42aa022f0c2715c3c5bdf0f2a92316e33ecbb0b22e3` | **Apache-2.0** (SPDX en el fichero, L1–3) | `engine/team_loop.py` L151–349 — predicados de `stop_decision` (M2) | `tests_team_verbatim_parity.py`: `ProvenanceTests` (4), `CopyTests` (5), `AgF1SourceCaseParityTests` (32) | **ADOPTADO** |
| **MG-F1** | `FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f` | `metagpt/team.py` L87–100 (14) | `5a9838885070add38a7cdd3ddf034ea40768d4b2` | `d13e885a69080987ea0d5d541cecb2e1a60ce1c57165eca9a505dbc24083b192` | **MIT** | `engine/team_process.py` L111–191 — `_BudgetBalance` (M5) | `tests_team_verbatim_parity.py`: `MgF1VectorParityTests` (8) | **ADOPTADO con adaptación** |
| LG-F1/F2/F3 | `langchain-ai/langgraph@3cd57c0` | `…/checkpoint/base/__init__.py` | `c7cacc7b…` | `fad65b12…` | MIT | — | — | **NO COPIADO**: C-2 congela el checkpoint v1; copiarlo lo forkearía (razón de `t29`) |
| LG-R1/R2 | idem | `…/checkpoint/memory/__init__.py`, `…/base/id.py` | — | — | MIT | — | — | **NO COPIADO**: `pickle`/`shutil`/`random` (higiene) |
| autogen · AutoGPT | `microsoft/autogen`, `Significant-Gravitas/AutoGPT` | — | — | — | CC-BY-4.0 · PolyForm Shield | — | — | **NO COMPATIBLE**: se reimplementa (M2/M5 propios) |
| ChatDev · AgentScope | — | — | — | — | Apache-2.0 | ya portados (`PORT_REPORT.md`) | — | **NO REQUIERE verbatim** |

### 8.2 Adaptaciones declaradas (obligación Apache-2.0 §4(b))

**AG-F1** (cabecera del bloque en `engine/team_loop.py`):

| Id | Adaptación | Motivo |
|---|---|---|
| B1 | `import operator` → `_OperatorShim` con `ne/lt/le/gt/ge/is_` | El allowlist de imports de `team_loop.py` está congelado por `tests_team_loop.py:46-51`; `t30` no puede reescribir pruebas. `op_names` sigue apuntando a los mismos objetos, así que `__repr__` imprime igual. |
| B2 | `from abc import ABC, abstractmethod` → `abstractmethod` identidad + `ABC` nominal | Idem. El cuerpo del fuente ya declara `raise NotImplementedError`; lo único que no se reproduce es el guard de instanciación de `ABCMeta` (ningún vector lo ejercita). |
| B3 | `from collections.abc import Callable` / `from typing import Any` → sin importar | Solo aparecen en anotaciones y el módulo las difiere (`from __future__ import annotations`): ninguna ruta de ejecución las evalúa. |
| B4 | `from ag2.types import ClassInfo` → sin importar | Igual que B3 (anotación de `TypeCondition.__init__`). |

**MG-F1** (cabecera del bloque en `engine/team_process.py`):

| Id | Adaptación | Motivo |
|---|---|---|
| A1 | `self.env.context.cost_manager` → `self._cost` | Aquí el cost manager se inyecta; sus campos son los contadores de `BUDGET_DIMENSIONS`. |
| A2 | `logger.info(f"Investment: ${investment}.")` eliminado | El módulo no tiene logger, no hace E/S y no escribe nada (contrato C-5). El resto de `invest` es literal. |
| A3 | `NoMoneyException(...)` → `_BudgetExhausted(...)` | Código congelado `budget_exhausted` (contrato §1); mensaje del fuente idéntico. |
| A4 | Constructor añadido (`max_budget`, `total_cost`) | En el fuente el cost manager viene del contexto del equipo; aquí se inyecta para que el predicado sea puro y testeable. |

### 8.3 Vectores de paridad demostrados

- **AG-F1 — 30/30 casos del test del fuente** (`test/events/test_conditions.py`, 30 métodos; la tabla
  de §4.1 los agrupó en 27 filas) reproducidos uno a uno: igualdad estricta de tipo, `!=`, `<`, `<=`,
  `>`, `>=`, `&`, `|`, `~`, `and_()`, `or_()`, `not_()`, composición anidada, `None`, `is None`,
  booleanos (con `check_eq(1, True) is False`), campos múltiples, subclase/clase base, no-redirección
  del descriptor heredado, invertir clase y composición con `~`. Más dos vectores del contrato de
  paridad de `t29`: `check_eq` estricto y `__repr__` vía `op_names`
  (`Is(TestEvent.field < 10)`, `And(...)` aplanado, `~Is(...)`, `IsType(TestEvent)`).
- **MG-F1 — 5/5 vectores derivados** de §4.2: `invest` fija el techo; `2.999 < 3.0` no corta;
  **borde exacto `3.0 >= 3.0` corta**; `3.001` corta; sin `invest` previo se usa el techo inyectado
  (la cifra no se copia). Más la **forma de acumulación** del test del fuente (dos `update_cost`
  monótonos no decrecientes).
- **No decorativo**: `MgF1VectorParityTests.test_the_process_uses_the_adopted_predicate_at_the_boundary`
  demuestra que el corte del borde exacto del proceso (`budget={'steps': 2}` → `budget_exhausted`,
  `reason='steps'`, 2 pasos) sale del predicado adoptado (`_balance_exhausted` → `_BudgetBalance`).

### 8.4 Divergencias declaradas (fail-honest)

1. **Azúcar de metaclase de AG2** (`TestEvent.field == "1"`, `AnotherEvent | TestEvent`,
   `TestEvent.not_()`): no se reproduce porque vive en `ag2.events` (fuera del fragmento L1–144). Los
   30 casos se expresan con `OpCondition`/`TypeCondition` del fragmento y se prueban igual.
2. **`ABCMeta`** (B2): no se reproduce el guard de instanciación de la clase abstracta; ningún vector
   del fuente instancia `Condition()` directamente.
3. **Vista dual `get_costs().total_cost == get_total_cost()`** (test de `cost_manager.py`): no se
   reproduce; ese fichero **no** está adoptado. Se conserva la monotonía no decreciente, que es la
   forma de la aserción.
4. **MG-F1 no trae test de `_check_balance`** en el fuente: sus vectores son **derivados** del
   predicado (ya declarado en §7.2), no copiados.
5. **Destino efectivo de MG-F1**: se aplica en `engine/team_process.py`; el bucle hereda el corte vía
   `cycle_state='budget_exhausted'` (no se duplica el predicado en `team_loop.py`: una sola fuente de
   verdad). El plan de `t29` citaba ambos módulos; la diferencia se declara aquí.

### 8.5 Exclusiones de la enmienda (5 supuestos)

Escaneo automático de los dos bloques (`tests_team_verbatim_parity.ExclusionTests`) por `socket`,
`urllib`, `requests`, `http`, `subprocess`, `os.system`, `eval(`, `exec(`, `__import__`, `open(`,
`pickle`, `random`, `time.`, `getenv`, `environ`, `dsh`, `DSH`, `.dsh-vscode` → **0 hallazgos**; y por
`policy_engine`, `approval`, `sandbox`, `can_execute`, `gate` → **0 hallazgos**. Los dos fragmentos son
lógica pura: no exfiltran datos, no abren red, no tocan las puertas de `policy_engine`, no ejecutan
fuera del sandbox gobernado y no mencionan DSH. **No hubo que recortar nada.**

### 8.6 Verificación ejecutada

```
cd EQUIPO_ENTERPRISE_24_COUNCIL_ADN && python -m unittest tests_team_verbatim_parity tests_team_process tests_team_loop -v
→ Ran 146 tests in 0.412s — OK  (52 paridad + 50 proceso + 44 bucle; exit 0, sin editar los tests congelados)

cd EQUIPO_ENTERPRISE_24_COUNCIL_ADN && python -c "from engine import team_process, team_loop; print(sorted(...)); print(sorted(...))"
→ exit 0; team_process no gana nombres públicos (el fragmento es privado: `_BudgetBalance`),
  team_loop gana los nombres verbatim de AG-F1 (`Condition`, `TypeCondition`, `AndCondition`,
  `OrCondition`, `NotCondition`, `OpCondition`, `check_eq`, `op_names`) y ningún nombre congelado cambia.
```

### 8.7 Avisos de terceros (MIT/Apache) — estado y pendiente declarado

- **Apache-2.0 (AG2)**: se conserva la cabecera de copyright + `SPDX-License-Identifier` del fuente
  (L1–3) dentro del bloque adoptado, y la declaración de cambios está en su cabecera (§8.2) —
  obligación §4(b) cumplida.
- **MIT (MetaGPT)**: copyright del fuente `Copyright (c) 2024 Chenglin Wu`; `LICENSE` del repo al sha
  = 1 072 B, `sha256 74945da6216c3f6498159a55cd25c0564acc684b791c169f869117a095808b00`. La atribución
  está en el docstring del módulo, en el docstring de `_BudgetBalance` y en esta tabla.
- **Pendiente declarado**: crear un fichero de avisos de terceros (`THIRD_PARTY_NOTICES.md` o
  equivalente) con el texto MIT completo **no estaba en el inScope de `t30`** (4 rutas). Queda como
  decisión de empaquetado del operador / `t27`, con la atribución ya íntegra en este informe y en el
  código.

### 8.8 Límites de esta sección

1. No re-verifica las fuentes **no** copiadas (langgraph, autogen, AutoGPT, ChatScope/ChatDev): sus
   razones están en §3.2 y en `license_audit.md`.
2. La paridad es de **comportamiento** contra los vectores del fuente, no una equivalencia bit a bit
   del módulo destino completo.
3. `tests_team_verbatim_parity.py` guarda el texto de los fragmentos como prueba **offline** (sin
   red): su `sha256` se comprueba contra el auditado en cada corrida.

