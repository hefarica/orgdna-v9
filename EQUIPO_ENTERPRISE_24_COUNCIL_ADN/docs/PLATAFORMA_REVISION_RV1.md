# RV1 · Revisión adversarial del contrato del Task Graph Engine (I1 / t2)

**Tarea revisora:** `t8` (miembro `verificador`) · attempt `f35e699a-eed0-4c9e-a77a-60d38e05563e` · ronda RV1
**Implementación revisada:** `t2` → `engine/task_graph.py` + `tests_platform_task_graph.py` (autores distintos del revisor: no hay auto-revisión)
**Fecha:** 2026-10-10 · **Entorno:** Windows, Python 3.12.10 y Python 3.14.2, sin red, sin claves, sin dependencias nuevas
**Veredicto:** `needs_revision` — 1 hallazgo de severidad **alta** (`RV1-01`) + 3 de severidad **baja** (`RV1-02`, `RV1-03`, `RV1-04`); 0 falsos aceptados y 0 falsos rechazados en 66 048 grafos enumerados exhaustivamente.

Este informe sólo lee, ejecuta pruebas y emite veredicto. No se modificó ningún archivo de código: las únicas escrituras atribuibles a RV1 son este informe y la caché de bytecode del intérprete (`engine/__pycache__/task_graph.cpython-312.pyc`, no listada en el manifiesto). El manifiesto V8 se recomputó completo: **268/268 entradas verificadas, 0 alteradas** (sección 7).

## 0. Artefactos revisados y huellas

| Archivo | SHA-256 | Bytes |
|---|---|---|
| `engine/task_graph.py` | `223b3105d62a6c3551d19850a7fe589699bb4aed4ab0cb0d3b5783dc0b5e1438` | 36 257 |
| `tests_platform_task_graph.py` | `a99534a6c43efb0de877b4998cb24907fec4fca78e328441077007309dbcd206` | 47 374 |
| `docs/plataforma/taskspec.schema.json` (contrato congelado R0, sólo lectura) | `34d775431312df97487ceaf277150235508d92eac8095e2199c89b547edf1715` | 10 656 |
| `MANIFIESTO_SHA256.txt` (huella del archivo) | `f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96` | — |

Las huellas de `task_graph.py` y de la suite se registraron antes (`p04`) y después (`p05`) de toda la batería de sondas y son idénticas: la revisión no tocó el código.

**Método.** Para cada garantía se construyó primero el caso que la rompería y se ejecutó; sólo después se aceptó lo que sobrevivió. Se usaron oráculos independientes (no aserciones de la suite): recomputación del JSON canónico con un `canonicalizador` propio, un validador de validez estructural propio (Kahn + ids + auto-dependencia + dependencias inexistentes), un verificador de la regla de orden por cadenas más largas, enumeración exhaustiva del espacio de dependencias y parches de E/S (`builtins.open`, `socket.*`) para probar inercia. Todas las sondas se guardaron fuera del repositorio (`%TEMP%\orgdna_rv1\`) y su código esencial se reproduce en el Anexo A.

---

## 1. Resultado sobre las cinco garantías

Las cinco garantías son la agrupación natural de los siete criterios de aceptación de `t2` (`team.json`, tarea `t2`). Se revisó cada una con al menos un intento de refutación.

| # | Garantía (criterios de `t2`) | Intento de refutación (lo que la rompería) | Resultado |
|---|---|---|---|
| **G1** | `taskspec_version` y todos los obligatorios; construir sin un obligatorio falla con error tipado, **nunca KeyError** (crit. 1) | Ausencia de cada obligatorio (raíz y anidados), tipos basura, `Mapping` hostil cuyo `__contains__` miente, estructuras auto-referentes | **Refutada parcialmente**: 2 000 mutaciones aleatorias sin ningún escape tipado, pero un `Mapping` con `__contains__` inconsistente produce **KeyError crudo** (`RV1-03`) y una estructura cíclica produce `RecursionError` (`RV1-04`) |
| **G2** | Hash determinista entre construcciones y entre procesos; **cambia ante cualquier mutación de campo** (crit. 2) | Mutar todos los campos del contrato (raíz, presupuesto, criterios y falsificadores) uno a uno, permutar claves anidadas, permutar el orden de la lista, normalización numérica, NFC→NFD, 3 semillas de `PYTHONHASHSEED` × 2 órdenes en 6 procesos | **Sostenida** para todos los campos del contrato (31 mutaciones ejecutadas: 28 hashes distintos, 3 exenciones) y para los 6 procesos; acotada por las exenciones documentadas en O-1, O-3 y O-4 |
| **G3** | Rechazo con error explícito de ciclos, ids duplicados, dependencias inexistentes y auto-dependencias; todo grafo inválido rechazado con el vocabulario congelado (crit. 3) | Enumeración **exhaustiva** de las 66 048 funciones de dependencia sobre 3 y 4 nodos + grafos aleatorios con duplicados/dependencias inexistentes + formas de ciclo no cubiertas por la suite | **Refutada**: **550/66 048 grafos (0,83 %)** —todos cíclicos— levantan `IndexError` crudo en lugar de `cycle_detected` (`RV1-01`). Ningún grafo inválido fue **aceptado** (0 falsos aceptados) |
| **G4** | `autonomy_state` por defecto `observe`; todo estado con capacidad de escritura exige flag explícito y **falla sin él** (crit. 4) | Matriz nivel × aprobación (sin flag, `False`, `1`, `True`), construcción directa, `dataclasses.replace`, `deepcopy`, `pickle`, aprobación por tarea, contenedores no declarados, intento de elevar el nivel con la aprobación | **Sostenida**: `prepare` y `execute-approved` fallan con `approval_required` por todas las rutas; la aprobación no eleva el nivel; `replace` no puede añadir ni quitar el flag. Reutilización del flag entre niveles declarada como O-2 |
| **G5** | Sólo stdlib y `engine/`; no abre red ni ficheros; ninguna función concede permisos, instala ni muta estado global (crit. 5 y 7) | Auditoría AST independiente, batería completa con `open`/`socket`/DNS parcheados para levantar, escaneo de contenedores mutables (incluidos anidados), estabilidad de `vars()`, 1 600 construcciones concurrentes en 8 hilos | **Sostenida**: 0 intentos de E/S, 0 contenedores mutables de módulo, 7 importaciones absolutas de stdlib (incluido `__future__`) + el respaldo `project_store`, un solo hash en las 1 600 construcciones concurrentes |

Criterio 6 de `t2` (≥12 casos): verificado, la suite tiene **48 casos** (`p05`/sección 6). El comando de verificación del contrato pasa en verde en dos versiones de Python: `Ran 48 tests ... OK` (exit 0) con 3.12.10 y con 3.14.2.

---

## 2. Comprobaciones explícitas exigidas por el encargo de RV1

### 2.1 Un estado de escritura sin flag de aprobación falla

Sonda `p05_autonomy.py`, sección A (salida literal):

```
    nivel                | sin flag        | approved=False  | approved=1(int) | approved=True
    observe              | OK:'observe'    | OK:'observe'    | TYPED:invalid_field | OK:'observe'
    propose              | OK:'propose'    | OK:'propose'    | TYPED:invalid_field | OK:'propose'
    prepare              | TYPED:approval_required | TYPED:approval_required | TYPED:invalid_field | OK:'prepare'
    execute-approved     | TYPED:approval_required | TYPED:approval_required | TYPED:invalid_field | OK:'execute-approved'
```

Rutas alternativas (sección B): `TaskSpec(autonomy_level='prepare', ...)` directo → `approval_required`; `TaskSpec(autonomy_level='execute-approved', ...)` → `approval_required`; `dataclasses.replace(spec_observe, autonomy_level='prepare')` → `approval_required`; `dataclasses.replace(spec_aprobado, autonomy_approved=False)` → `approval_required` (no se puede quitar el flag de un nivel de escritura). En grafos (sección C): `approved={'t2': True}` sobre un grafo cuya tarea de escritura es `t1` → `approval_required`; `approved={'t1': 1}` (entero, no `True` estricto) → `approval_required`; `approved=[True]` → `approval_required`; `approved={'t1'}` (set) y `approved='si'` → `invalid_field`. `approved=True` y `approved=['t1']`/`{'t1': True}` → se construye, y el nivel declarado no se eleva (`observe` con `approved=True` sigue siendo `observe`).

**Conclusión:** la garantía G4 se sostiene; el flag es estricto (`is True`) y ninguna ruta de construcción lo elude. La única matización no bloqueante es O-2.

### 2.2 El hash cambia ante cualquier mutación de campo

Sonda `p03b_parity.py`, sección C, con el fixture exacto de la suite y el hash base `c0690c65c91bc5b55be60136f3f4f9b7453eb04708794286e0a54027998d8b53`:

- 31 mutaciones ejecutadas: **28 producen hash distinto** — `task_id`, `title`, `intent`, `agent_ref` (cambiar/quitar), `autonomy_level`, `depends_on` (agregar/quitar), las cuatro magnitudes de `budget` (más `0.0 → -0.0`), `criterion`, `verify`, `status`, criterio agregado, `falsifier_id`, `statement`, `how_detected`, `idempotency_key`, `evidence_refs` (cambiar/quitar), `created_at` (cambiar/quitar), NFC→NFD en `title`, tarea agregada, tarea quitada.
- 2 exenciones **por diseño** verificadas aparte: permutar el orden de la lista de tareas o permutar claves (incluso anidadas) **no** cambia el hash ni el orden (el hash es sobre la lista ya ordenada con claves ordenadas); `policy_ref`/`created_at` del grafo son metadatos y no entran en el hash.
- 2 exenciones **declaradas** (no bloqueantes, ver sección 4): `autonomy_approved` (campo no-contrato, `compare=False`) no entra en `to_dict()` ni en el hash; `money_usd: 0` y `0.0` normalizan al mismo `0.0` y comparten hash.

Sensibilidad adicional verificada: `depends_on` participa en el hash **en el orden declarado** (misma arista `t3→{t1,t2}` declarada como `['t1','t2']` y `['t2','t1']` produce `a80805f0…` y `65c8bb0c…` respectivamente, con el mismo orden topológico) — observación O-3.

---

## 3. Hallazgos que requieren corrección

### RV1-01 · Severidad **alta** · `IndexError` crudo en lugar de `cycle_detected` en ciclos con una raíz ya resuelta

**Problema.** `_cycle_path()` documenta que recorre «los nodos no resueltos» (`engine/task_graph.py:637`), pero en la línea **`engine/task_graph.py:644`** avanza a la dependencia lexicográficamente menor **sin filtrar por `unresolved`**:

```python
644:        node = sorted(index[node].depends_on)[0]
```

Si esa dependencia es un nodo **ya resuelto** que no tiene dependencias propias (una raíz), `sorted(())` devuelve `[]` y `[0]` levanta `IndexError`. Como `IndexError` **no** es `TaskGraphError`, escapa de `build_graph` (`:731`) y de `inspect_graph` (`:750-754`, que sólo captura `TaskGraphError`), rompiendo dos cosas a la vez: el vocabulario congelado de rechazo (`$defs.graph_rules.error_codes` → `cycle_detected`) y el contrato de «veredicto sin excepción» de `inspect_graph` (`:745`).

**Evidencia (comando y salida).** Sonda `p01_cycle_path.py` (3 formas construidas a propósito para romperlo, más el ciclo puro de control):

```
--- A ciclo puro (control, cubierto por la suite)
inspect_graph -> False cycle_detected
build_graph -> codigo tipado cycle_detected
--- B ciclo con raiz resuelta de por medio
inspect_graph ESCAPED -> IndexError IndexError('list index out of range')
build_graph ESCAPED -> IndexError IndexError('list index out of range')
--- C cadena larga hasta hoja resuelta
inspect_graph ESCAPED -> IndexError IndexError('list index out of range')
--- D hoja resuelta en medio del ciclo
inspect_graph ESCAPED -> IndexError IndexError('list index out of range')
ESCAPES NO TIPADOS: 6
```

Traceback con la línea exacta:

```
File "...\engine\task_graph.py", line 628, in _topological_order
    ' -> '.join(_cycle_path(index, unresolved)) + '.')
File "...\engine\task_graph.py", line 644, in _cycle_path
    node = sorted(index[node].depends_on)[0]
IndexError: list index out of range
```

Entrada mínima reproducible (una raíz `aaa` resuelta en la primera pasada y un ciclo `qqq↔zzz` que la alcanza por orden alfabético `sorted(('aaa','qqq'))[0] == 'aaa'`):

```python
tg.build_graph([D('aaa'), D('qqq', ('zzz',)), D('zzz', ('aaa', 'qqq'))])   # -> IndexError, no cycle_detected
tg.inspect_graph([D('aaa'), D('qqq', ('zzz',)), D('zzz', ('aaa', 'qqq'))])  # -> IndexError, no dict con code
```

**Magnitud exacta (enumeración exhaustiva).** Sonda `p06_differential.py`: se enumeraron **todas** las funciones de dependencia `d: V → P(V)` con ids únicos y declaraciones por lo demás válidas — 512 grafos con n=3 y 65 536 con n=4, total 66 048 — comparando el veredicto del módulo contra el oráculo propio:

```
resumen: {'acuerdo': 65498, 'precedencia': 0, 'falso-acepta': 0, 'falso-rechaza': 0, 'escape': 550}
codigos observados: {'ESCAPE:IndexError': 550, 'cycle_detected': 3042, 'self_dependency': 61888, 'valid': 568}
```

Es decir: **550 grafos (0,83 % del espacio) son cíclicos según el oráculo y el módulo no los rechaza con `cycle_detected`, sino que revienta con `IndexError`**; 0 falsos aceptados y 0 falsos rechazados. La reproducción del fallo también ocurre en Python 3.14.2 (los 6 escapes idénticos), así que no es dependiente de la versión.

**Por qué la suite no lo detecta.** Los tres ciclos de `test_cycle_is_rejected_with_its_own_code` (`tests_platform_task_graph.py:374-382`) tienen todos sus nodos dentro del ciclo, de modo que `sorted(deps)[0]` nunca abandona `unresolved`. La suite pasa en verde (48/48) con el defecto presente.

**Por qué obliga a `needs_revision`.** El criterio de aceptación 3 de `t2` («se rechazan con error explícito: ciclos…») y la garantía del encargo («100 % de los grafos con ciclo… devuelven uno de los 10 códigos») no se cumplen para esa clase de grafos. No es un falso aceptado (la rama termina en excepción, no en grafo válido), así que no impide seguir con `t9`; lo que impide es certificar I1 como completo.

**Corrección requerida.** Restringir el recorrido a los nodos no resueltos (que es lo que el propio docstring declara). En `_cycle_path`, sustituir la línea 644 por un avance que sólo considere dependencias de `unresolved` —no vacío por construcción, porque un nodo no resuelto tiene al menos una dependencia fuera de `levels`—:

```python
candidates = sorted(dep for dep in index[node].depends_on if dep in unresolved)
node = candidates[0]      # siempre no vacío: si no, el nodo habría sido 'ready'
```

y **añadir a `tests_platform_task_graph.py`** un caso de regresión con las tres formas B/C/D de `p01` más la entrada mínima, comprobando `inspect_graph(...)['code'] == 'cycle_detected'` sin excepción. No se acepta como corrección envolver la llamada en `except Exception`: eso ocultaría la causa (`cycle_detected` dejaría de ser el código devuelto) en vez de arreglar el recorrido.

### RV1-02 · Severidad **baja** · `duplicate_idempotency_keys()` levanta `AttributeError` con declaraciones crudas (API no uniforme)

**Problema.** Las tres funciones de lista del módulo deberían aceptar lo mismo, pero no lo hacen: `canonical_task_list` (`:606-609`) y `compute_graph_sha256` (`:612-615`) normalizan vía `_declaration_of` (`:602-603`) y aceptan tanto `TaskSpec` como declaraciones; `duplicate_idempotency_keys` (`:738-741`) accede directamente a `spec.idempotency_key` y con un `dict` levanta `AttributeError` crudo (no tipado).

**Evidencia.** Sonda `p02_escapes.py`, sección 2:

```
canonical_task_list(dicts)        -> ('OK', '')
compute_graph_sha256(dicts)       -> ('OK', '')
duplicate_idempotency_keys(dicts) -> ('ESCAPED:AttributeError', "'dict' object has no attribute 'idempotency_key'")
duplicate_idempotency_keys(specs) -> ('OK', '')
```

**Corrección requerida.** En `duplicate_idempotency_keys`, aceptar declaraciones con `_declared_task_id` / `_declaration_of` (o rechazar lo que no sea `TaskSpec` con `InvalidFieldError` y documentarlo en el docstring). Si se aceptan, la clave ausente debe producir `MissingFieldError`, nunca `AttributeError`.

### RV1-03 · Severidad **baja** · Un `Mapping` cuyo `__contains__` no coincide con `__getitem__` propaga `KeyError`

**Problema.** `MissingFieldError` documenta «Nunca se propaga un KeyError» (`engine/task_graph.py:131`), pero la comprobación de presencia y la lectura se hacen en dos pasos: `name not in data` (`:309-311`, `:681-682`) y después `data[name]` (`:377-380`, `:686-699`). Con un `Mapping` que responde `True` a `in` y levanta en `__getitem__`, el `KeyError` escapa.

**Evidencia.** Sonda `p02_escapes.py`, sección 1 (un `dict` con `__contains__` que devuelve `True` y `__getitem__` que levanta):

```
build_taskspec(Liar()) -> ('ESCAPED:KeyError', "'agent_ref'")
build_taskspec(Liar con budget Liar) -> ('ESCAPED:KeyError', "'agent_ref'")
```

**Alcance real (declarado, no exagerado).** No es alcanzable con la salida de `json.loads` (que siempre produce `dict` coherentes) ni con `dict`/`Mapping` estándar; sólo con un mapeo hostil o con un error de consistencia en un mapeo de terceros. Se registra porque contradice una afirmación absoluta del propio módulo y porque la sonda de aceptación de `t2` («nunca KeyError») se apoya en ese docstring.

**Corrección requerida.** Leer con centinela (`data.get(name, _MISSING)`) y decidir con ese valor, o acotar la afirmación del docstring al dominio real («no se propaga KeyError para mapeos coherentes, como los producidos por `json.loads`»).

### RV1-04 · Severidad **baja** · `_reject_credential_names` no acota profundidad ni ciclos

**Problema.** El recorrido recursivo de nombres (`:_reject_credential_names`, `:287-298`) no limita profundidad ni detecta referencias circulares, por lo que una estructura de Python cíclica produce `RecursionError` y no un error tipado; tampoco hay documentada una profundidad máxima admitida.

**Evidencia.** Sonda `p02_escapes.py`, sección 3:

```
build_taskspec(ciclico) -> ('ESCAPED:RecursionError', 'maximum recursion depth exceeded')
```

**Alcance real:** no representable en un documento JSON (mismo límite que el propio `json.loads`), por lo que no rompe el dominio declarado — de ahí la severidad baja.

**Corrección requerida.** Declarar el dominio de entrada en el docstring del módulo («documento JSON sin ciclos, profundidad acotada») o añadir un tope de profundidad explícito. Ninguna de las dos opciones altera el contrato.

---

## 4. Observaciones declaradas (no bloquean; requieren constancia, no cambio de código)

| Id | Observación | Evidencia | Acción sugerida |
|---|---|---|---|
| **O-1** | El hash **no atestigua la aprobación**: `autonomy_approved` no se serializa, no entra en el hash y `compare=False` lo excluye de la igualdad (`:478-480`, `:495`). Dos declaraciones idénticas con distinto estado de aprobación son iguales y comparten hash | `p03b` sección D y `p07` sección B: `autonomy_approved` cambia el hash: `False`; `to_dict` iguales: `True`; `specs iguales: True` | Declarado por el autor (`:31-35`). `t9` no debe usar `graph_sha256` como evidencia de tarea de escritura aprobada; si un recibo declara aprobación, debe llevar campo propio |
| **O-2** | El flag de aprobación es **booleano y no está ligado al nivel**: `dataclasses.replace(spec_aprobado_para_prepare, autonomy_level='execute-approved')` se construye reutilizando el flag previo | `p05` sección B: `replace(aprobado prepare -> execute-approved) -> OK:'execute-approved'` | La afirmación del docstring («ninguna ruta… puede elevar el nivel sin el flag») se cumple literalmente, pero el flag no distingue niveles. Debe quedar escrito en `docs/PLATAFORMA_DECISIONES.md` para que I3/I6 no lo interpreten como aprobación específica de nivel |
| **O-3** | El hash es **sobre la declaración, no sobre el DAG**: el orden de `depends_on` participa (`:520-534`, `:606-615`). Mismo conjunto de aristas con orden distinto ⇒ hash distinto y `to_dict` distinto, con idéntico `topological_order` | `p07` sección A: `hash A: a80805f0…` vs `hash B: 65c8bb0c…`, `orden topologico igual: True` | Conforme a la `hash_rule` congelada. `t10` debe comparar declaraciones canonicalizadas (o normalizar el orden de `depends_on` al exportar), no el JSON crudo |
| **O-4** | Normalización numérica: `money_usd: 0` y `0.0` producen la misma declaración (`0.0` flotante) y el mismo hash; `json.dumps` normaliza `-0.0` a `-0.0` (hash distinto) | `p03b` sección C (`budget.money_usd: 0.0 -> 0` → MISMO HASH) y `p07` sección C | El hash atestigua la declaración **normalizada**, no los bytes de entrada; declararlo si `t9`/`t10` comparan hashes entre árboles con literales numéricos distintos |
| **O-5** | Sin `docs/plataforma/` en el árbol (situación del ZIP antes de `t9`), **4 de los 48 casos se omiten** (`FrozenContractCrossCheckTests`, `:662-664`): las comprobaciones contra el contrato congelado desaparecen de forma visible pero silenciosa para el recuento de «OK» | Árbol copiado sin `docs/`: `Ran 48 tests in 0.754s` / `OK (skipped=4)` | `t9` debe permitir el schema en `RUNTIME_ALLOWLIST` (ya previsto en D-R0-2) y `t10` debe exigir `skipped=0` sobre el paquete final |
| **O-6** | Ejecutar el comando de verificación crea/refresca la caché de bytecode `engine/__pycache__/task_graph.cpython-312.pyc` (no es un artefacto del manifiesto) | `p05` sección E: `__pycache__ dentro de engine/: ['task_graph.cpython-312.pyc']`; manifiesto 268/268 intacto | Ninguna; se declara para que `t9` no confunda la caché con una entrada nueva del paquete |

---

## 5. Lo que NO se pudo verificar (declarado, no asumido)

1. **Python 3.10 y 3.11.** El módulo declara «Python 3.10+» (`:23`), pero en este entorno sólo hay 3.12.10 y 3.14.2 (`py -0p`). Se ejecutó la suite y las sondas en ambas (verde y mismo defecto); la compatibilidad con 3.10/3.11 queda **sin verificar**.
2. **Comportamiento dentro del ZIP empaquetado.** Sólo se simuló la ausencia de `docs/plataforma/` copiando `engine/` + la suite a un árbol temporal (O-5). No se verificó el empaquetado real, ni `RUNTIME_ALLOWLIST`, ni `MANIFIESTO_SHA256.txt` regenerados: son de `t9` y aquí no existen todavía.
3. **Consumo aguas abajo.** No se verificó cómo I2–I6 (`t3`–`t7`) ni la integración (`t9`) consumirán `graph_sha256`, `autonomy_approved` o `duplicate_idempotency_keys`; el estado de escritura sin flag se verificó **en la construcción del contrato**, no en ninguna ejecución (el módulo no ejecuta nada, y no existe aún capa de policy que lo consuma).
4. **Ausencia de red «de verdad».** La inercia se probó con auditoría AST (imports y llamadas) y parcheando `builtins.open`, `socket.socket`, `socket.create_connection` y `socket.getaddrinfo` para que levanten; no se usó un cortafuegos ni un monitor de syscalls, así que un acceso por un camino no cubierto por esos parches no quedaría descartado por esta evidencia.
5. **Semántica de los códigos de campo.** `FIELD_ERROR_CODES = ('missing_required_field', 'invalid_field', 'forbidden_field', 'approval_required')` es una extensión declarada por I1 (`:108-110`); el contrato congelado no fija códigos para errores de campo. Verifiqué que la extensión está declarada y que los 10 códigos estructurales coinciden literalmente con el schema, pero **no** que la asignación de código a cada caso de campo sea la única razonable (p. ej. `depends_on` repetido se rechaza como `invalid_field` por `uniqueItems`, y no existe código congelado para ello).
6. **`tests_platform_task_graph.py` como prueba independiente.** Sus tres ciclos no cubren la forma que rompe `_cycle_path`; la suite pasa en verde con el defecto presente. No se auditó línea a línea la calidad de cada aserción (sí su recuento, su vocabulario de errores y la coherencia de sus constantes contra el schema, recomputadas por oráculos propios).

---

## 6. Comandos y resultados de referencia

| Comando | Resultado |
|---|---|
| `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_platform_task_graph.py' -v` | `Ran 48 tests in 0.213s` · `OK` · `EXITCODE=0` (Python 3.12.10) |
| `& "…\Python314\python.exe" -B -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_platform_task_graph.py'` | `Ran 48 tests in 0.532s` · `OK` · `EXITCODE=0` (Python 3.14.2) |
| `python -m unittest discover … -p 'tests_org_design.py'` (no regresión V8, verify #2 de `t2`) | `Ran 24 tests in 1.064s` · `OK` · `EXITCODE=0` |
| `python "%TEMP%\orgdna_rv1\p01_cycle_path.py"` | Ciclo puro de control → `cycle_detected` por ambas rutas; 6 escapes `IndexError` en las formas B/C/D (incluye `inspect_graph`) |
| `python "%TEMP%\orgdna_rv1\p02_escapes.py"` | KeyError con `Mapping` hostil; `AttributeError` en `duplicate_idempotency_keys(dicts)`; `RecursionError` en estructura cíclica; 2 000 mutaciones de registro y 1 000 grafos aleatorios sin otros escapes |
| `python "%TEMP%\orgdna_rv1\p03b_parity.py"` | `FIXTURE_GRAPH_SHA256` recomputado con oráculo canónico propio; límites de longitud aceptados en el máximo y rechazados en máximo+1; 28 hashes distintos en 31 mutaciones de campo |
| `python "%TEMP%\orgdna_rv1\p04_inertness.py` y `p04b_inertness.py` | 6 procesos (semillas 0/1/42 × 2 órdenes) con hash y orden idénticos; 0 intentos de E/S con `open`/`socket` parcheados; 0 contenedores mutables; `vars()` estable; 1 600 construcciones concurrentes con 1 solo hash |
| `python "%TEMP%\orgdna_rv1\p05_autonomy.py"` | Matriz de autonomía × aprobación completa; manifiesto 268/268 verificado; artefactos de plataforma ausentes del manifiesto |
| `python "%TEMP%\orgdna_rv1\p06_differential.py"` | 66 048 grafos enumerados: 0 falsos aceptados, 0 falsos rechazados, 550 escapes `IndexError` |
| `python "%TEMP%\orgdna_rv1\p07_shape.py"` | Orden de `depends_on` participa en el hash; `autonomy_approved` y metadatos del grafo no; normalización `0`/`0.0` |
| Suite sobre árbol sin `docs/plataforma/` | `Ran 48 tests … OK (skipped=4)` |

Verificación independiente del contrato congelado (sondas `p03`/`p03b`, recomputada desde el JSON y no desde las aserciones de la suite): **17/17 comprobaciones de paridad OK** — `GRAPH_ERROR_CODES` idéntico y en el mismo orden, `ORDER_RULE`/`HASH_RULE` byte-idénticas, conjuntos de propiedades/obligatorios de raíz, `budget`, criterios y falsificadores iguales, los cuatro patrones (`task_id`, `idempotency_key`, `created_at`, credenciales) idénticos, enums y defaults idénticos, 13 campos prohibidos = `engine/project_store.py:19`, versiones `"1"`; más **5/5** comprobaciones del fixture y del oráculo canónico propio, y **9/9** de los límites de longitud, que se reejecutaron correctamente en `p03b` sección B (aceptación en el máximo, rechazo en máximo+1) porque la primera redacción de esa comprobación en `p03` era defectuosa. Orden y hash comparados con oráculos propios en 2 000 DAGs aleatorios: 0 discrepancias.

---

## 7. No intromisión y efecto colateral declarado

- Manifiesto V8 recomputado entrada por entrada: **268 entradas, 0 ausentes, 0 alteradas**; huella del archivo `MANIFIESTO_SHA256.txt` = `f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96`, la misma base declarada por R0.
- `web/app.js`, `web/index.html`, `web/style.css`, `engine/*` y `tests_platform_task_graph.py`: sin cambios atribuibles a RV1 (huellas idénticas antes/después de la batería; `web/index.html` y `web/style.css` coinciden además con sus entradas del manifiesto).
- Los artefactos de la capa de plataforma (contratos R0, `engine/task_graph.py`, la suite y **este informe**) **no** están en el manifiesto: `t9` debe añadirlos a `RUNTIME_ALLOWLIST` y regenerar `MANIFIESTO_SHA256.txt` (D-R0-2), incluyendo `docs/PLATAFORMA_REVISION_RV1.md`.
- Efecto colateral del intérprete: la caché `engine/__pycache__/task_graph.cpython-312.pyc` se refrescó al ejecutar el comando de verificación exigido por el contrato de `t8`. No es un artefacto del paquete ni una entrada del manifiesto (O-6). Las corridas con 3.14 se hicieron con `-B` para no crear caché nueva.
- Sin red, sin claves, sin llamadas a proveedores, sin instalación de dependencias y sin tocar DSH durante toda la revisión.

---

## 8. Veredicto

**`needs_revision`.** El núcleo del contrato está sólido: paridad literal con el schema congelado, orden y hash deterministas y sensibles a todos los campos del contrato (0 discrepancias en 2 000 DAGs y en 6 procesos), rechazo correcto de duplicados/dependencias inexistentes/auto-dependencias, DAG siempre acíclico cuando se acepta (0 falsos aceptados en 66 048 grafos), aprobación explícita infranqueable por todas las rutas de construcción, e inercia verificada (sin E/S, sin estado mutable, sin permisos).

No puede declararse `pass` mientras `RV1-01` esté abierto: una clase de grafos cíclicos (550/66 048 = 0,83 % del espacio exhaustivo de 3–4 nodos, con la entrada mínima de tres tareas documentada arriba) escapa del vocabulario congelado con un `IndexError` crudo en `engine/task_graph.py:644`, y `inspect_graph` propaga la excepción en vez de devolver `cycle_detected`. La corrección es quirúrgica (filtrar el avance por `unresolved` en `_cycle_path`) y debe ir acompañada del caso de regresión en `tests_platform_task_graph.py`; `RV1-02`, `RV1-03` y `RV1-04` son de severidad baja y pueden resolverse en el mismo lote de reparación o dejarse documentados con justificación explícita.

---

## Anexo A. Código esencial de las sondas

Entrada reutilizada por todas las sondas (sustituible por `tests_platform_task_graph.declaration`):

```python
import sys
sys.path.insert(0, 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN')
from engine import task_graph as tg

def D(i, d=()):
    return {'taskspec_version': '1', 'task_id': i, 'title': 'Tarea ' + i,
            'intent': 'Declarar sin ejecutar.', 'autonomy_level': 'observe', 'depends_on': list(d),
            'budget': {'tokens': 1, 'money_usd': 0.0, 'time_seconds': 1, 'requests': 1},
            'acceptance_criteria': [{'criterion': 'c', 'verify': 'v'}],
            'falsifiers': [{'falsifier_id': 'fr01', 'statement': 's', 'how_detected': 'h'}],
            'idempotency_key': 'idem-' + i + '-0001'}
```

**A.1 Reproducción de `RV1-01`** (`_cycle_path` abandona `unresolved`):

```python
tg.inspect_graph([D('aaa'), D('qqq', ('zzz',)), D('zzz', ('aaa', 'qqq'))])   # IndexError
tg.inspect_graph([D('a0'), D('c1', ('c2',)), D('c2', ('c3',)), D('c3', ('a0', 'c1'))])  # IndexError
tg.inspect_graph([D('m0'), D('p1', ('p2', 'm0')), D('p2', ('p1',))])          # IndexError
tg.inspect_graph([D('ta', ('tb',)), D('tb', ('ta',))])                       # control: cycle_detected
```

**A.2 `Mapping` hostil de `RV1-03`:**

```python
class Liar(dict):
    def __contains__(self, key): return True
    def __getitem__(self, key): raise KeyError(key)
    def __iter__(self): return iter(())

tg.build_taskspec(Liar())     # KeyError: 'agent_ref'
```

**A.3 Oráculo de validez de `RV1-01` (usado en la enumeración exhaustiva):**

```python
def reference_verdict(records):
    ids = [r['task_id'] for r in records]
    if not records: return 'empty_graph'
    if len(ids) != len(set(ids)): return 'duplicate_task_id'
    for r in records:
        for d in r['depends_on']:
            if d == r['task_id']: return 'self_dependency'
            if d not in set(ids): return 'unknown_dependency'
    remaining = {r['task_id']: set(r['depends_on']) for r in records}
    while remaining:
        ready = [n for n, deps in remaining.items() if not deps]
        if not ready: return 'cycle_detected'
        for n in ready: remaining.pop(n)
        for deps in remaining.values(): deps.difference_update(ready)
    return 'valid'
```

**A.4 Inercia con E/S bloqueada (`RV1` garantía G5):** cargar `engine.task_graph`, después sustituir `builtins.open`, `socket.socket`, `socket.create_connection` y `socket.getaddrinfo` por funciones que levantan `AssertionError`, recorrer todas las funciones públicas (válidas e inválidas) y restaurar los originales en un `finally`. Resultado: 0 intentos de E/S, 0 excepciones inesperadas fuera de las tipadas.
