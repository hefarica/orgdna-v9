# RV2 · Revisión adversarial de la reparación de I1 (Task Graph Engine) — ronda 2

**Tarea revisora:** `t12` (miembro `verificador`) · attempt `46665488-c56b-4c72-a1f7-a58228fbf4f0` · ronda RV2
**Reparación revisada:** `t11` → `engine/task_graph.py` + `tests_platform_task_graph.py` (autor `nucleo`, distinto del revisor: no hay auto-revisión)
**Antecedente:** RV1 (`docs/PLATAFORMA_REVISION_RV1.md`, t8) emitió `needs_revision` con 1 hallazgo alto (RV1-01) + 3 bajos (RV1-02/03/04). Este informe verifica **de forma independiente** si la reparación cierra esos cuatro hallazgos y si introduce regresiones.
**Fecha:** 2026-10-10 · **Entorno:** Windows, Python 3.12.10 (y 3.14.2 en la ronda 1), sin red, sin claves, sin dependencias nuevas
**Veredicto:** `pass` — los cuatro hallazgos están cerrados con regresión **no vacua**, sin regresiones detectadas y con el contrato congelado intacto (hash del fixture retrocompatible).

## 0. Artefactos revisados y huellas

| Archivo | SHA-256 (RV2) | Bytes / líneas | SHA-256 (RV1, antes de reparar) |
|---|---|---|---|
| `engine/task_graph.py` | `369a734f3b10e449e76d4e4ca78d2784a04b6ab73b5dfb43512bdbf4a9ff8424` | 42 597 / 866 | `223b3105d62a6c3551d19850a7fe589699bb4aed4ab0cb0d3b5783dc0b5e1438` (36 257 / 757) |
| `tests_platform_task_graph.py` | `e493d321f50786654232b5beca848f478bd76250b04e8b77b4eca81d094129c3` | 61 364 / 999 | `a99534a6c43efb0de877b4998cb24907fec4fca78e328441077007309dbcd206` (47 374 / 738) |
| `docs/plataforma/taskspec.schema.json` (contrato congelado, sólo lectura) | `34d775431312df97487ceaf277150235508d92eac8095e2199c89b547edf1715` | 10 656 | idéntico |
| `MANIFIESTO_SHA256.txt` | `f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96` | 268 entradas | idéntico (huella base de R0) |

Sólo cambian los dos artefactos que `t11` declaró. La caché `engine/__pycache__/task_graph.cpython-312.pyc` se refrescó al ejecutar las pruebas (efecto del intérprete, no listada en el manifiesto).

**Método (ronda 2).** No se dio por buena la afirmación de la reparación: se repitieron las sondas de RV1 contra el código nuevo, se añadieron ataques específicos a las rutas nuevas (centinela `_MISSING`, `_read_values`, `_declared_value`, `MAX_DECLARATION_DEPTH`) y se ejecutó un experimento de **falsificación de la prueba**: se reintrodujo el defecto RV1-01 en una copia temporal del árbol para comprobar que la regresión nueva lo detecta.

---

## 1. Estado de los cuatro hallazgos de RV1 (verificación independiente)

### RV1-01 (alto) · CERRADO

**Corrección aplicada.** `_cycle_path` avanza ahora sólo hacia dependencias no resueltas (`engine/task_graph.py:717-718`), con el invariante documentado en el propio docstring (`:704-710`):

```python
717:        candidates = sorted(dependency for dependency in index[node].depends_on if dependency in unresolved)
718:        node = candidates[0]
```

**Verificación 1 — las cinco formas de la sonda p01 que rompían el módulo** (`p01_cycle_path.py`, salida literal):

```
--- A ciclo puro (control)          inspect_graph -> False cycle_detected | build_graph -> codigo tipado cycle_detected
--- B ciclo con raiz resuelta       inspect_graph -> False cycle_detected | build_graph -> codigo tipado cycle_detected
--- C cadena larga hasta hoja       inspect_graph -> False cycle_detected | build_graph -> codigo tipado cycle_detected
--- D hoja resuelta en medio        inspect_graph -> False cycle_detected | build_graph -> codigo tipado cycle_detected
ESCAPES NO TIPADOS: 0
```

El mensaje del ciclo se queda dentro de los nodos no resueltos (traza real de `p02`): `cycle_detected: ciclo de dependencias en el grafo: qqq -> zzz -> qqq.`

**Verificación 2 — enumeración exhaustiva del espacio de dependencias de 3 y 4 nodos** (`p06_differential.py`, 512 + 65 536 = 66 048 grafos, contra un oráculo de validez escrito por el revisor):

```
resumen: {'acuerdo': 66048, 'precedencia': 0, 'falso-acepta': 0, 'falso-rechaza': 0, 'escape': 0}
codigos observados: {'cycle_detected': 3592, 'self_dependency': 61888, 'valid': 568}
```

Antes de la reparación este mismo experimento daba `escape: 550` y `cycle_detected: 3042`; ahora no hay ni un escape y el total de ciclos detectados es exactamente 3 592 = 3 042 + 550.

**Verificación 3 — el contrato de `inspect_graph` sobre el espacio completo de 3 nodos** (`p11_inspect_space.py`, 512 grafos): `escapes no tipados: 0`; `discrepancias inspect_graph vs build_graph: 0`; códigos `{'cycle_detected': 39, 'self_dependency': 448, 'valid': 25}`.

**Verificación 4 — grafos grandes aleatorios** (`p12_fuzz_big.py`, 20 000 grafos de 3 a 10 tareas con ciclos, auto-dependencias y repetidas): `escapes no tipados: ninguno`, `discrepancias con el oraculo: 0`, códigos `{'cycle_detected': 1284, 'self_dependency': 18160, 'valid': 556}`.

**Verificación 5 — la regresión nueva es no vacua** (`p10_test_the_tests.py`). Se copió `engine/` + la suite a un árbol temporal, se reintrodujo la línea antigua `node = sorted(index[node].depends_on)[0]` **en la copia** y se ejecutó la suite:

```
--- copia limpia:                                        exit=0   Ran 62 tests in 1.148s | OK (skipped=4)
--- copia con el defecto RV1-01 reintroducido:           exit=1   Ran 62 tests in 1.184s | FAILED (errors=16, skipped=4)
    ERROR: ProbeP01CycleRegressionTests.test_build_graph_raises_the_typed_code_and_names_the_cycle (shape='entrada minima de p01 ...')
    ERROR: ... (shape='B ciclo con raiz resuelta de por medio') | (shape='C cadena larga hasta hoja resuelta') | (shape='D hoja resuelta en medio del ciclo')
    ERROR: ProbeP01CycleRegressionTests.test_cycle_message_stays_inside_the_unresolved_nodes
    ERROR: test_exhaustive_three_node_space_matches_an_independent_oracle (function='n0>;n1>n2;n2>n0,n1')
    ... y 8 mas
VEREDICTO DE LA PRUEBA: NO VACUA (detecta el defecto)
```

La clase nueva (`tests_platform_task_graph.py:506-598`) llama a `inspect_graph` **sin `try/except`** (un escape falla por sí mismo), incluye las formas A/mínima/B/C/D, comprueba que el camino reportado es un ciclo real dentro de `unresolved` (`:546-554`) y contrapone el espacio completo de 3 nodos (512) y una muestra determinista del de 4 (≥300) contra `reference_verdict`, un oráculo independiente definido en la propia suite.

### RV1-02 (bajo) · CERRADO

`duplicate_idempotency_keys` acepta ahora `TaskSpec` y declaraciones JSON por igual a través de `_declared_value` (`engine/task_graph.py:732-747`, `:841-850`), con docstrings que declaran el tipo admitido. Sonda `p09_repair_attacks.py` sección D:

```
    dicts                 -> ('idem-ta-0001',)
    specs                 -> ('idem-ta-0001',)
    mixto                 -> ('idem-ta-0001',)
    dict sin la clave     -> TYPED:missing_required_field
    tipo ajeno (entero)   -> TYPED:invalid_field
    None                  -> TYPED:invalid_field
```

Las tres formas dan el mismo informe (se esperaba `('idem-ta-0001',)`) y ningún caso produce `AttributeError`. Cobertura en la suite: `AdmittedInputDomainTests.test_list_helpers_accept_task_specs_and_declarations_uniformly` (`:745-755`) y `test_list_helpers_reject_missing_keys_and_foreign_types` (`:768-778`), que además afirman explícitamente `assertNotIsInstance(error, AttributeError)`.

### RV1-03 (bajo) · CERRADO

Todas las lecturas de entrada usan el centinela `_MISSING = object()` (`:113-115`) y deciden con el valor leído: `_read_values` (`:346-358`), `_declared_value` (`:732-747`), `_reject_credential_names` (`:336-340`), `build_taskspec` (`:775-798`). Auditoría AST (`p09b_ast.py`): **0 subíndices de lectura sobre la entrada**; lecturas con centinela sobre `data`, `record`, `spec`, `value`, `approved`; 4 manejadores `except` y ninguno ciego (`ImportError`, `UnicodeEncodeError`, `(TypeError, ValueError, UnicodeEncodeError)`, `TaskGraphError`). Ataques de la sonda `p09` sección E:

```
    build_taskspec(Liar())                  -> TYPED:missing_required_field
    budget=Liar()                           -> TYPED:missing_required_field
    acceptance_criteria=[Liar()]            -> TYPED:missing_required_field
    build_graph([Liar()])                   -> TYPED:missing_required_field
```

El segundo filo —un mapeo cuyo `in` niega claves que `get` sí devuelve— se construye idéntico al `dict` coherente (declaración documentada del dominio en `:25-43`), y la suite lo cubre con `InverseLiar` (`:722-729`, `:739-743`).

### RV1-04 (bajo) · CERRADO

El docstring del módulo declara el dominio admitido (`:25-43`, incluida la profundidad y la ausencia de ciclos) y `MAX_DECLARATION_DEPTH = 32` (`:116-118`) acota el recorrido con error tipado (`:325-329`). Frontera verificada en `p09` sección B:

```
    nido de  31 -> OK:NoneType      nido de  32 -> OK:NoneType
    nido de  33 -> TYPED:invalid_field      nido de 400 -> TYPED:invalid_field
    _reject_credential_names(ciclico)       -> TYPED:invalid_field
    _reject_credential_names(lista ciclica) -> TYPED:invalid_field
     registro con anidamiento 64            -> TYPED:invalid_field (vía build_taskspec)
     canonical_task_list(declaracion ciclica) -> TYPED:invalid_field (json.dumps, :648-655)
```

El máximo legítimo del contrato v1 son 3-4 niveles, así que el tope no restringe el contrato (verificado: el fixture y las declaraciones mínima/completa siguen construyéndose).

---

## 2. Las cinco garantías, re-atacadas

| # | Garantía | Intento de refutación en RV2 | Resultado |
|---|---|---|---|
| **G1** | Versión + obligatorios; error tipado, nunca `KeyError` | 2 000 mutaciones aleatorias del registro (`p02`), `Mapping` hostil en raíz/presupuesto/criterio/grafo, `null` explícito vs ausente en los 3 opcionales (`p09b`) | **Sostenida**: 0 escapes; `null` → `invalid_field`, ausente → default del contrato (`evidence_refs` → `[]`, `agent_ref`/`created_at` fuera del `to_dict`) |
| **G2** | Hash determinista y sensible a cada campo | 31 mutaciones de campo (`p03b`), 6 procesos con `PYTHONHASHSEED` 0/1/42 × 2 órdenes de claves, 1 600 construcciones en 8 hilos (`p04`), recomputación del fixture con oráculo canónico propio | **Sostenida e inalterada**: 28 hashes distintos, 3 exenciones ya declaradas; `FIXTURE_GRAPH_SHA256` sigue siendo `c0690c65…` y coincide con el oráculo propio → **retrocompatible** |
| **G3** | Rechazo tipado de ciclos, duplicados, dependencias inexistentes y auto-dependencias | 66 048 grafos exhaustivos + 20 000 aleatorios de 3–10 tareas + 512 vía `inspect_graph` + reintroducción del defecto en copia temporal | **Sostenida y reforzada**: 0 escapes, 0 falsos aceptados, 0 falsos rechazados; el código sale siempre del vocabulario congelado |
| **G4** | `observe` por defecto; escritura exige flag y falla sin él | Matriz nivel × aprobación y rutas alternativas (`p05`), `replace`/`deepcopy`/`pickle`, aprobación por tarea, contenedores no declarados | **Sostenida** (idéntica a RV1): `prepare`/`execute-approved` sin flag → `approval_required` por todas las rutas; `approved=1`/`'si'`/`[True]` → rechazo tipado; la aprobación no eleva el nivel |
| **G5** | Sólo stdlib y `engine/`; sin E/S; sin permisos, instalación ni estado global | AST (imports, llamadas, `except`), batería con `open`/`socket`/DNS parcheados (`p04`/`p04b`), contenedores mutables (incluidos anidados), `vars()` estable, 1 600 construcciones concurrentes | **Sostenida**: 0 intentos de E/S, 0 contenedores mutables de módulo, 8 funciones públicas sin nombres que concedan permisos, imports = stdlib + respaldo `project_store`, un solo hash concurrente |

Comprobaciones explícitas exigidas por el encargo, repetidas en RV2:

- **Estado de escritura sin flag** (`p05` sección A/C): `prepare` y `execute-approved` → `TYPED:approval_required` con «sin flag», `approved=False`, `approved={'t2':True}` (tarea equivocada), `approved={'t1':1}`, `approved=[True]`; se construyen sólo con `True`/`['t1']`/`{'t1':True}`.
- **El hash cambia ante cualquier mutación de campo** (`p03b` sección C): 28 de 31 mutaciones cambian el hash; las 3 exenciones son el orden de la lista de entrada (×2) y la normalización `0`/`0.0`, no campos del contrato.

---

## 3. Ausencia de regresiones (verificada, no supuesta)

| Comprobación | Comando / sonda | Resultado |
|---|---|---|
| Suite del contrato | `python -m unittest discover … -p 'tests_platform_task_graph.py' -v` | `Ran 62 tests in 0.823s` · `OK` · exit 0 (antes 48) |
| No regresión V8 | `… -p 'tests_org_design.py'` | `Ran 24 tests` · `OK` · exit 0 |
| Paridad literal con el schema | `p03`/`p03b` | 17/17 estáticas + 9/9 de límites (acepta máx., rechaza máx.+1) + 5/5 de fixture/oráculo |
| Orden y hash contra oráculos propios | `p03b` sección A, `p04` | 2 000 DAGs: 0 discrepancias; 6 procesos idénticos |
| Inercia | `p04`/`p04b`/`p09b` | 0 E/S con parches; sin contenedores mutables (ni anidados); `vars()` estable en identidad y representación |
| Surface pública | `p09b` | 8 funciones exactas; 21 clases = 14 de `ERROR_CLASSES` + 2 bases no lanzables + 5 declaraciones (`TaskSpec`, `Budget`, `AcceptanceCriterion`, `Falsifier`, `TaskGraph`) |
| Sin `except` ciego | `p09b` | 4 manejadores, todos específicos; ninguno nuevo que enmascare errores |
| Alcance de la reparación | manifiesto + huellas | Sólo cambian los 2 archivos declarados por `t11`; **268/268 entradas del manifiesto verificadas** (incluye 48 de `engine/`, entre ellas `bundle.py`, `project_store.py`, `bridge.py`, `org_design.py`, `generation_pipeline.py`, los out-of-scope declarados por `t11`) y `web/*` con las mismas huellas que en RV1 |
| Retrocompatibilidad del hash | `p03b` | `FIXTURE_GRAPH_SHA256` intacto y recomputado con oráculo propio; `depends_on`, `autonomy_level`, etc. siguen entrando en el hash igual que en RV1 |

La caché `__pycache__` de los archivos tocados y de los módulos de otros flujos aparece en la ventana temporal de trabajo (los flujos I2–I6 se están implementando en paralelo), pero ninguna entrada del manifiesto cambió.

---

## 4. Observaciones para la integración (no bloquean; constancia, no cambio de código)

| Id | Observación | Evidencia | Acción sugerida |
|---|---|---|---|
| **O-RV2-1** | El hash **no atestigua la aprobación**: `autonomy_approved` no se serializa, no entra en el hash y `compare=False` lo excluye de la igualdad (`engine/task_graph.py:551` campo, `:533` docstring, `:51-55` decision declarada) | `p07` sección B: `autonomy_approved cambia el hash: False`, `specs iguales: True` | `t9` no debe usar `graph_sha256` como evidencia de escritura aprobada; si un recibo declara aprobación, debe llevar campo propio |
| **O-RV2-2** | El flag de aprobación sigue **sin estar ligado al nivel**: `replace(spec_aprobado_para_prepare, autonomy_level='execute-approved')` se construye reutilizando el flag | `p05` sección B: `OK:'execute-approved'` | Debe quedar escrito en `docs/PLATAFORMA_DECISIONES.md` para que I3/I6 no lo lean como aprobación específica de nivel |
| **O-RV2-3** | El hash es **sobre la declaración, no sobre el DAG**: el orden de `depends_on` participa | `p07` sección A: misma arista, `a80805f0…` vs `65c8bb0c…`, con idéntico `topological_order` | `t10` debe comparar declaraciones canonicalizadas, no JSON crudo |
| **O-RV2-4** | **Nuevo, documentado y probado por la reparación:** las funciones canónicas aceptan declaraciones crudas *sin normalizarlas*, así que `compute_graph_sha256([crudo])` ≠ `compute_graph_sha256([build_taskspec(crudo)])` cuando faltan opcionales (`status`, `evidence_refs`…) | Suite `:757-764` (`test_canonical_helpers_dump_raw_declarations_as_is`) y `p09` sección D | `t9`/`t10` deben **construir** (`build_taskspec`/`build_graph`) antes de hashear una declaración cruda; el hash de referencia del paquete debe calcularse siempre sobre la declaración normalizada |
| **O-RV2-5** | Un `Mapping` fuera del dominio declarado cuyo `get` levanta una excepción no tipada (p. ej. `TypeError`) todavía escapa de `inspect_graph`, que sólo captura `TaskGraphError` (`:859-866`). El dominio admitido está declarado y este caso queda fuera de él («mapeos coherentes»), pero la promesa «veredicto sin excepción» no cubre mapeos hostiles | `p12` sección final: `build_taskspec -> ESCAPE fuera de dominio: TypeError get hostil`; `inspect_graph -> ESCAPE fuera de dominio: TypeError get hostil` | Opcional: degradar el contrato de `inspect_graph` a «sin excepción para el dominio admitido» de forma explícita en el docstring, o envolver la lectura del mapeo en un error tipado. Ninguna de las dos altera el contrato congelado |
| **O-RV2-6** | La suite sigue omitiendo 4 de 62 casos si `docs/plataforma/` no viaja en el paquete (`@unittest.skipUnless`, `:919`) | Árbol temporal sin `docs/`: `Ran 62 tests … OK (skipped=4)` | `t9` debe permitir el schema en `RUNTIME_ALLOWLIST` (D-R0-2) y `t10` exigir `skipped=0` sobre el paquete final |
| **O-RV2-7** | Un `Mapping` que **oculta claves a la iteración** puede esquivar el escaneo de nombres prohibidos, pero los valores ocultos no llegan a la declaración ni al hash | `p09` sección E: con `hidden['password']` oculto, `'password' in to_dict(): False` y el hash no cambia | Ninguna; se declara para que la auditoría de nombres no se lea como una defensa contra mapeos hostiles (el módulo es inerte y sólo lee los 13 nombres del contrato) |

---

## 5. Lo que NO se pudo verificar (declarado, no asumido)

1. **Python 3.10 y 3.11.** El módulo declara «Python 3.10+» pero sólo hay 3.12.10 y 3.14.2 en este entorno (en RV1 la suite y las sondas pasaron en ambas). La reparación se verificó íntegramente en 3.12.10; en 3.14.2 se verificó la ronda 1.
2. **Empaquetado real.** No existen todavía `RUNTIME_ALLOWLIST` ni el ZIP de V9: la ausencia de `docs/plataforma/` se simuló con una copia temporal (O-RV2-6). **Este informe (`docs/PLATAFORMA_REVISION_RV2.md`) es un artefacto nuevo que `t9` debe añadir a la allowlist y al manifiesto**, igual que `RV1`, `engine/task_graph.py` y la suite.
3. **Consumo aguas abajo.** No se verificó cómo I2–I6 ni `t9` usarán `graph_sha256`, `autonomy_approved` o el informe de idempotencia; las observaciones O-RV2-1..O-RV2-4 son precisamente los puntos que esa integración debe respetar.
4. **Ausencia de red «de verdad».** Probada con auditoría AST y parches de `open`/`socket`/DNS, no con cortafuegos ni traza de syscalls.
5. **Fix del ciclo más allá de lo enumerado.** La cobertura es exhaustiva para 3 y 4 nodos (66 048 grafos) y aleatoria hasta 10 tareas (20 000 grafos), más el argumento estructural del docstring (`:704-710`): un nodo no resuelto tiene al menos una dependencia fuera de `levels` (si no, habría sido `ready`), de modo que `candidates` nunca está vacío. No se enumeró exhaustivamente ningún espacio mayor.
6. **`tests_platform_task_graph.py` como oráculo.** Su `reference_verdict` es independiente del módulo, pero escrito por el mismo autor que la reparación; la contrastación con **mi** oráculo (RV1 §A.3, reutilizado en `p06`/`p12`) es la que da la garantía de independencia, y coincide en el 100 % de los 86 048 grafos probados.
7. **Semántica de los códigos de campo.** La asignación de `invalid_field` a casos como `depends_on` repetido sigue sin estar fijada por el contrato congelado (extensión declarada de I1).

---

## 6. Comandos y resultados de referencia

| Comando | Resultado |
|---|---|
| `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_platform_task_graph.py' -v` | `Ran 62 tests in 0.823s` · `OK` · `EXITCODE=0` (3.12.10) |
| `python -m unittest discover … -p 'tests_org_design.py'` | `Ran 24 tests in 0.897s` · `OK` · `EXITCODE=0` |
| `python %TEMP%\orgdna_rv1\p01_cycle_path.py` | 4 formas de ciclo (A/mínima/B/C/D) con `cycle_detected` por ambas rutas; `ESCAPES NO TIPADOS: 0` |
| `python %TEMP%\orgdna_rv1\p02_escapes.py` | `Liar` → tipado; `duplicate_idempotency_keys(dicts)` → OK; estructura cíclica → `invalid_field`; 2 000 mutaciones y 1 000 grafos sin escapes |
| `python %TEMP%\orgdna_rv1\p03b_parity.py` | Paridad y límites OK; `FIXTURE_GRAPH_SHA256` recomputado con oráculo propio; 28/31 mutaciones cambian el hash |
| `python %TEMP%\orgdna_rv1\p04_inertness.py` + `p04b_inertness.py` | 6 procesos idénticos; 0 E/S con parches; 0 contenedores mutables; 1 600 construcciones concurrentes con 1 hash |
| `python %TEMP%\orgdna_rv1\p05_autonomy.py` | Matriz de autonomía × aprobación completa; manifiesto 268/268 |
| `python %TEMP%\orgdna_rv1\p06_differential.py` | 66 048 grafos: `escape: 0`, `falso-acepta: 0`, `falso-rechaza: 0` |
| `python %TEMP%\orgdna_rv1\p09_repair_attacks.py` / `p09b_ast.py` | Frontera de profundidad (32 OK / 33+ tipado), ciclos tipados, API uniforme, 0 subíndices de entrada, 4 `except` específicos, 8 funciones públicas, `null` vs ausente |
| `python %TEMP%\orgdna_rv1\p10_test_the_tests.py` | Copia limpia: 62 tests OK; copia con RV1-01 reintroducido: `FAILED (errors=16)` en `ProbeP01CycleRegressionTests` → regresión **no vacua** |
| `python %TEMP%\orgdna_rv1\p11_inspect_space.py` | 512 grafos por `inspect_graph`: 0 escapes, 0 discrepancias con `build_graph` |
| `python %TEMP%\orgdna_rv1\p12_fuzz_big.py` | 20 000 grafos de 3–10 tareas: 0 escapes, 0 discrepancias con el oráculo; mapeo fuera de dominio documentado como O-RV2-5 |

---

## 7. Veredicto

**`pass`.** Los cuatro hallazgos de RV1 están cerrados y verificados por vías independientes de la afirmación del autor:

- **RV1-01** (el único bloqueante): el recorrido del ciclo se restringe a los nodos no resueltos (`engine/task_graph.py:717-718`); no queda ni un escape en 66 048 grafos exhaustivos de 3–4 nodos, en 512 grafos vía `inspect_graph` ni en 20 000 grafos aleatorios de 3–10 tareas, y la regresión nueva **falla** (16 errores) cuando se reintroduce el defecto en una copia temporal, lo que demuestra que protege de verdad.
- **RV1-02/03/04** (bajos): API uniforme con errores tipados para las tres funciones de lista, lectura por centinela en todas las rutas con auditoría AST sin subíndices de entrada, y tope de profundidad explícito con frontera verificada, más dominio de entrada declarado en el docstring.

Sin regresiones: el hash del fixture sigue siendo el mismo (`c0690c65…`, recomputado con oráculo propio), la paridad literal con el contrato congelado se mantiene, la determinación entre procesos y la inercia siguen intactas, las 24 pruebas V8 pasan y el manifiesto V8 sigue 268/268. La única matización es O-RV2-5 (mapeos fuera del dominio declarado, sin cambio requerido) y las observaciones O-RV2-1..O-RV2-4, que `t9`/`t10` deben respetar al integrar. I1 queda apto para la integración de V9.
