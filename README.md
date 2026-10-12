# OrgDNA V9 — Release Candidate verificable (offline)

Suite de diseño organizacional **OrgDNA V9** más el expediente completo de verificación que la
acompaña: línea base medida, hallazgos no atribuibles, especificación de la plataforma integrada y
los informes de verificación V1/V2.

> **Estado real, sin adornos.** Estamos ante un **release candidate verificado offline**, no ante un
> producto certificado para producción. La suite no ha ejecutado **ninguna** capacidad operativa
> (red, modelo, Excel en vivo, lanzador DSH): esas capacidades están en estado `NOT_RUN` por diseño
> —el producto es inerte y *fail-closed*—. La independencia de la verificación está **degradada**
> (ver abajo). No existe todavía certificación operativa.

---

## 1. Qué hay aquí

| Ruta | Qué es |
|---|---|
| `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/` | El producto. 303 archivos, **sellado por SHA-256** (302 entradas). |
| `verifica_manifiesto.py` | Verificador independiente del sello. Solo stdlib. Código 0 = sello íntegro. |
| `resella_paquete.py` | Re-sella el paquete (catálogo + manifiesto + huella publicada) y se autoverifica. Idempotente. |
| `OBSERVACIONES_CAPITAN_PLATAFORMA.md` | Registro del capitán: decisiones abiertas O-1…O-24, cada una con su estado. |
| `HALLAZGOS_LINEA_BASE_NO_ATRIBUBLES.md` | Defectos de línea base que **no** son atribuibles a la integración. |
| `PLAN_CORRECCION_FOCALIZADO_V8_P0A_P0B_P1A_P1B.md` | Plan focalizado P0-A/P0-B/P1-A/P1-B. |
| `linea_base_regresion_v8.txt` | Línea base de la suite **antes** de la plataforma (árbol congelado). |
| `regresion_con_plataforma.txt` | Misma suite **después** de la integración. Comparación controlada. |
| `verificacion_v1_suite.txt` / `_huella.json` | Verificación V1: resultados por test + huella de medición. |
| `verificacion_v2_suite.txt` / `_huella.json` | Verificación V2: repetición con huella de medición. |
| `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_VERIFICACION_V1.md` | Expediente de verificación (fuera del sello, a propósito). |
| `P3A_COSTE_EXPORT_INFORME.md` + `p3a_*.py` | Sondeo, desglose y verificación del coste de la ruta de exportación. |
| `.agent-teams/` | Estado de coordinación del equipo que produjo la integración. |

---

## 2. Verificación reproducible

```bash
python verifica_manifiesto.py          # sello SHA-256: 302/302 hashes sobre bytes en disco
python resella_paquete.py              # solo si tocas un archivo sellado
python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py
```

Resultado medido en el árbol congelado que originó este repositorio:

```
verifica_manifiesto.py
  entradas manifiesto : 316
  hashes coincidentes : 316
  hashes divergentes  : 0
  faltantes           : 0
  exentos declarados  : 14     (data/ y el expediente de verificación, por diseño)
  sobrantes reales    : 0
  RESULTADO           : OK

validate_imports_portable.py
  valid: true | errors: [] | checks: 1881 | file_count: 317
  agent_count: 24 | tool_catalog_count: 271 | export_hashes_valid: true
```

`MANIFIESTO_SHA256.txt` → `d71e311612ae43bdfd5dae143169c5abbc0b683acc9bc0c8c9410f452530b66b`

El sello cubre **316** archivos; el archivo 317 es el propio manifiesto. `data/` y
`docs/PLATAFORMA_VERIFICACION_V1.md` quedan fuera del sello **deliberadamente**: el primero es estado
de ejecución que el producto reescribe al usarse —verificado: la suite completa lo modifica y los 302
hashes siguen coincidiendo—, el segundo un expediente que debe poder revisarse sin re-sellar el paquete.

---

## 3. ⚠️ Aviso crítico sobre Git y los finales de línea

**No cambies `.gitattributes`.** El paquete está sellado sobre **bytes exactos**, y los archivos de
este árbol son **LF puro**.

Este host trae `core.autocrlf=true` en el gitconfig de sistema (`C:/Program Files/Git/etc/gitconfig`).
Sin la regla `* -text` de [`.gitattributes`](.gitattributes), Git convertiría LF → CRLF al hacer
checkout y **los 316 hashes dejarían de verificar en un clon limpio**. La regla viaja con el repo, así
que cualquier clon queda protegido. `* -text` desactiva solo la conversión de fin de línea: el atributo
`diff` sigue activo y los diffs de texto funcionan con normalidad.

Si tocas cualquier archivo sellado, `verifica_manifiesto.py` lo dirá de inmediato.

---

## 4. Requisitos y ejecución

- **Python 3.10+**. Medido y verificado con **3.12.10** (y 3.14.2 vía `py -3`).
- **Solo biblioteca estándar.** Sin dependencias, sin red, sin claves, sin escritura fuera del árbol.
- **Windows** para las rutas nativas (puente Excel vía COM, lanzador DSH). El núcleo es portable.

Arrancar la aplicación (el lanzador elige `py -3` o `python`, exige 3.10+ y no instala nada):

```bat
EQUIPO_ENTERPRISE_24_COUNCIL_ADN\launch.cmd
```

Equivalente directo, desde dentro del paquete:

```bash
cd EQUIPO_ENTERPRISE_24_COUNCIL_ADN
python -m engine.launcher
```

Ejecutar la suite de tests, con descubrimiento explícito y desde la raíz del workspace:

```bash
python -m unittest discover \
  -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN \
  -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN \
  -p 'test*.py' -v
```

El patrón debe ser `test*.py`, no `tests*.py`: cubre los 36 módulos `tests_*.py` de la raíz **y**
los 8 `test_*.py` de `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests/`, que es un paquete con `__init__.py` y
por tanto se recorre recursivamente. Con `tests*.py` se perderían esos 8 módulos en silencio.

**Define `PYTHONUTF8=1` en Windows.** Tres módulos heredan la página de códigos cp1252 y fallan sin
esa variable; con ella pasan. Está medido y documentado en el expediente de verificación (§3.2).

---

## 5. Defectos conocidos y atribución honesta

### 5.1 Medición final sobre el árbol congelado

Descubrimiento completo (`test*.py`, 55 módulos), `PYTHONUTF8=1`, sin paralelismo, huella del árbol
`d71e311612ae43bdfd5dae143169c5abbc0b683acc9bc0c8c9410f452530b66b`:

```
Ran 1119 tests in 216.981s
FAILED (errors=3, skipped=3)          ← failures=0
```

Los **4 errores restantes son de entorno**, verificado uno a uno por su traza:

| Caso | Causa raíz | Naturaleza |
|---|---|---|
| `qa_v6.test_evaluation_independent.test_symlink_in_test_tree_rejected` | `OSError WinError 1314` — sin privilegio para crear enlaces simbólicos | entorno |
| `tests_capability_deployment.test_namespace_traversal_symlink` | `OSError WinError 1314` — ídem | entorno |
| `tests_bridge.test_workbook_stale_blocks_export` | *Mark-of-the-Web* + `RemoteSigned` bloquean el `.ps1` sin firma; el puente Excel lanza si el libro no está abierto | línea base V8 |
| `qa_v7.test_design_recovery_independent.RecoveryHttpIndependent` | `ConnectionAbortedError WinError 10053` — carrera de socket local | **inestabilidad preexistente (O‑3)** |

El cuarto es **intermitente y preexistente**, y está medido, no supuesto: repetido en aislamiento falla
**1/12 en el árbol anterior a P3‑C y 3/12 en el actual**. Ambos árboles fallan, así que el mecanismo no es de
P3‑C; la diferencia de tasa **no queda establecida** (prueba exacta de Fisher, p ≈ 0,59 con n=12) y se declara
como cuestión abierta, no como «sin diferencia».

Los **3 skips son declarados**, no silenciosos: dos por capacidad de plataforma (grupo de procesos
POSIX; symlinks) y uno por el privilegio de symlink anterior. **Cero fallos atribuibles al producto.**

Comparación controlada de las mediciones (mismo host, misma huella de medición en cada par):

| Medición | Resultado |
|---|---|
| Clon limpio, antes de la reparación P3‑B (1026 casos) | `failures=1, errors=9, skipped=2` |
| Árbol final de P3‑B (1035) | `failures=0, errors=3, skipped=3` |
| P3‑C primera pasada (1035) — las 4 guardas lo detectan | `failures=4, errors=3, skipped=3` |
| P3‑C con las guardas cerradas (1035) | `failures=0, errors=4, skipped=3` |
| **P3‑D: +27 casos de A y B (1062)** | **`failures=0, errors=3, skipped=3`** |

Las 4 guardas de la tercera fila no son un defecto del cambio: son tests que **fijaban las fronteras viejas** y
que se movieron de forma declarada. Dos de ellas eran hashes pinneados que nadie había listado.

Además: la suite de plataforma **391 OK (skipped=1)**, y `tests_dsh_launcher.py` pasó de
`FAILED (failures=1, errors=5)` a **`OK (skipped=1)`**.

> Las cifras `Ran 782 tests` de los expedientes `verificacion_v1_suite.txt` y `verificacion_v2_suite.txt`
> son **históricas y correctas para su patrón**: se obtuvieron con descubrimiento `tests*.py`, que no
> entra en `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/tests/`. No se reescriben; la medición de arriba usa
> descubrimiento completo y por eso da 1035.

### 5.2 Defecto de producto encontrado y reparado (P3‑B): el respaldo del lanzador DSH

Al verificar el clon limpio aparecieron **6** no-pasantes en `tests_dsh_launcher`, no 1. Instrumentando
una copia desechable —nunca el paquete sellado— salió la causa, que estaba **enmascarada** por un
`except Exception ... from None`:

```
KeyError: "There is no item named '0\\history.json' in the archive"
```

Los nombres de entrada del ZIP se construían con `Path(...) / relativo`, que usa `os.sep` (`\` en
Windows), mientras `zipfile` **normaliza a `/` al escribir**. El respaldo se escribía bien y no podía
leer su propia lista de entradas: **`dsh-launch-backup` era inoperante en Windows**. En POSIX `os.sep`
es `/` y el defecto es invisible.

- **Reparado** con `_entry_name()` → `'%d/%s' % (index, relative.as_posix())` (APPNOTE 4.4.17.1 exige
  barra inclinada), y el `except` pasa a `from cause` conservando mensaje y tipo.
- **Falsificado**: con el código original en una copia, `Ran 25 tests — FAILED (failures=4, errors=8,
  skipped=1)`; las aserciones señalan el defecto (`'\\' unexpectedly found in '0\\sub\\deep\\leaf.txt'`;
  `None is not an instance of <class 'RuntimeError'>`).
- **Regresión nueva**: `tests_platform_launcher_zip_names.py` (9 casos) comprueba el **formato** del
  nombre, no solo el resultado, precisamente porque en POSIX el fallo no se manifestaría.
- **Segundo defecto corregido**: `test_no_script_assumption_no_guessed_port` leía el
  `%LOCALAPPDATA%\DSH_LAUNCHER\launcher.json` **real del operador**. El producto lee la configuración
  correctamente; el test no la aislaba. Lo habría visto en rojo cualquier operador con el lanzador
  configurado.
- **Hash pinneado actualizado y DECLARADO**: `qa_v7/dsh_baseline.json` fijaba `engine/dsh_launcher.py`;
  la enmienda queda registrada dentro del propio archivo (`amendments`) con hash anterior, nuevo,
  motivo y evidencia.

**Esto significa que BUG 5 no estaba cerrado.** Lo que sigue en `NOT_RUN` es el lanzamiento real de
DSH: la suite es offline y no ejecuta ningún proceso de Windows.

### 5.3 Cambio P3‑C — techo de agentes: de un literal duplicado a una fuente única

El techo de N era un literal `32` **repetido**, no una frontera de orquestación, y por eso estaba desincronizado
entre capas: subirlo por partes fallaba. Ahora hay **una sola definición** —`engine/limits.py`, `MAX_AGENTS = 40`—
y todas las capas la importan. Verificado que `core.MAX_AGENTS is limits.MAX_AGENTS` → **`True`**: es el mismo
objeto.

**Alcance real medido: 13 archivos, 51 reglas, 54 sustituciones** — no 4 archivos y 5 puntos.

**Por qué un barrido de literales no bastaba.** `autonomy.py:43` pasa la cota **como argumento**
(`_integer(n,'agent_count',1,32)`) y el mensaje se compone en `:20`. El literal no está junto al mensaje, así que
un grep no lo ve. Comprobado: un parche de **30 sitios** que no incluía `autonomy.py` seguía fallando con
`agent_count: entero 1..32 requerido.`

**La UI pierde los literales.** Los tres `max="32"` pasan a `max="__MAX_AGENTS__"`, que `bridge.py:1644` rellena
al servir junto al `__CSRF_TOKEN__`. Un test afirma ahora que **ningún** marcador sobrevive en el cuerpo servido.

**Un mensaje que habría pasado a mentir, corregido.** `core.py:112` decía «>32 requiere diseño multi-squad». Con
el techo en 40 eso sería falso: `multi-squad` aquí son los dos escuadrones fijos —implementación y Council—
(`bundle.py:837`), no N escuadrones encadenados. Ahora dice la verdad: escuadrón plano de N, encadenado **no
implementado**.

**Tres fronteras movidas declaradamente** (`33`→`41` en `tests_bridge.py`, `tests_org_design.py` y
`qa_v7/test_generation_failures_independent.py`), **una de conteo** (`47`→`48` módulos de `engine/`) y **dos
hashes pinneados con enmienda registrada** dentro de `qa_v7/dsh_baseline.json`. Más un positivo **N=40** que
antes no existía: sin él, subir el techo quedaría declarado pero no probado.

| Medición | Resultado |
|---|---|
| N=41 | `Más de 40 agentes no está soportado: … no se trunca el equipo.` |
| `autonomy` con 41 (la cota-argumento) | `agent_count: entero 1..40 requerido.` |
| **Positivo N=40, modo API** | **`OK`** — 40 perfiles, `len(agents)==40`, organización válida |
| Prompt del proveedor | `Use 1-40 professions` |
| Cotas `32` supervivientes | **0** |

**Limitación declarada, no resuelta:** el modo **plantilla sin IA** sigue en 32, porque `ROLE_SEEDS` y `PERSONAS`
son 32 y `core.py:947` rechaza N=40 por ahí. Falla cerrado, no trunca en silencio. Ampliarlo exige 8 semillas
nuevas: contenido de producto, decisión separada.

**Lo que sigue sin verificar:** AgentTeams tendría que admitir **1 Captain + 39 teammates**. Este repositorio
genera el diseño y los artefactos; **no ejecuta** AgentTeams ni DSH. `RUNTIME_UNVERIFIED`.

### 5.4 Módulos A y B — compilador de contexto y bucle de mejora (P3‑D)

Dos módulos nuevos, stdlib puro, deterministas y fail-closed: `engine/context_compiler.py` (contexto acotado por
presupuesto) y `engine/improvement_loop.py` (ejecutor de los siete estados de remediación).

**Se escribieron, se ejecutaron y se falsificaron.** Ejecutarlos encontró **tres defectos reales en B y una
inconsistencia en A** — ninguno de ellos visible por lectura, y todos con falsificación ejecutada.

| # | Defecto | Evidencia medida |
|---|---|---|
| B1 | `publish()` exigía `skill_diff`, que **nadie asigna nunca** → el camino feliz era **inalcanzable** | `evidencia incompleta para publicar: skill_diff` |
| B1b | Ese fallo **enmascaraba** el guardián de permisos, que quedaba inejercitable | el caso 5 original no podía recorrerse |
| B2 | El digest **plegaba el anterior** y `verify_case` devolvía **True con el contenido alterado** | `case_digest(c) != c["digest"]` |
| A1 | Campos desconocidos **dentro de un elemento** se ignoraban en silencio, contra el contrato de A | un `extra` en una evidencia no lanzaba nada |

**Dos casos de la lista de falsificación original eran inejercitables**, y se declara: el caso 3 de A (el fixture
no desbordaba el presupuesto —caben 638 bytes en 1024—) y el caso 7 de B (**inexpresable**: `_SKILL_KEYS` rechaza
el campo que el test pretendía inyectar). Ambos sustituidos por lo que sí es verificable.

| Medición | Resultado |
|---|---|
| `tests_context_compiler.py` (13 casos) | **13/13 OK** |
| `tests_improvement_loop.py` (14 casos) | **14/14 OK** |
| Falsificación de B (arreglos revertidos en copia desechable) | **`FAILED (failures=2, errors=2)`** de 14 |

**Lo que estos módulos NO son.** No tocan pesos: la política vive en las skills y la recompensa en la revisión
independiente. `context_compiler` **no es recuperación semántica** —lo declara en su propio `selection.method`—.
Y la señal de recompensa y la propagación **no están cableadas**: son del llamador.

### 5.5 Capa de agentes, contrato de instrucción y cableado (P3‑E)

Nueve archivos nuevos (7 módulos + 2 suites): `agent_kinds`, `operational_gate`, `readiness_gate`,
`playbooks`, `agent_dossier`, `instruction_contract`, `remediation_wiring`.

**Se escribieron, se ejecutaron y se falsificaron.** La ejecución encontró **cinco defectos reales** que la
lectura no daba:

| # | Defecto | Evidencia |
|---|---|---|
| D1 | `readiness_gate`: el switch era un **dict literal**, evaluado ENTERO antes de indexar — `item["gap"]` reventaba con `KeyError` en el primer bloqueo de herramienta | la puerta fallaba **justo cuando tenía que bloquear** |
| D2 | `instruction_contract`: `reconcile` sólo reparaba `got` de tipo `str`, así que un `2` número JSON frente al `2.0` fijado se declaraba irreparable | el caso 5 de la lista original no podía pasar |
| D3 | `agent_kinds`: catálogo vacío → preset vacía y **silenciosa** | el caso 2 («nunca lista vacía») era falso; lo correcto es que sea visible |
| D4 | `agent_dossier`: `to_context_items(limit=64)` daba **66** ítems y `context_compiler` los **rechazaba** | la llamada por defecto no podía alimentar a su consumidor |
| D5 | `remediation_wiring`: clave de idempotencia estable con `expected_revision` **leída en vivo** | el reintento lanzaba `Clave idempotente reutilizada` — justo el caso para el que existe |

**Verificado contra los componentes reales**, no simulado: `import_items(**plan)` sobre SQLite real → OK
(revisión 0→1); reimportar el mismo caso → `item_count` sigue 1; cambiar instrucciones sin subir versión →
`Los registros son inmutables; importar una nueva versión con otro ID.`

| Medición | Resultado |
|---|---|
| `tests_agent_layer_contracts.py` | **32/32 OK** |
| `tests_instruction_and_wiring.py` | **25/25 OK** |
| Los 5 arreglos revertidos en copia desechable | **`FAILED (failures=2, errors=8)`** de 57 |

**Lo que sigue sin estar cableado:** el llamador que dispara el bucle en producción **no existe**, y la señal
de recompensa sigue fuera. Nada de esto toca pesos, instala, activa ni ejecuta un agente.

### 5.6 Independencia de la verificación: degradada

La verificación V1 la firmó el propio capitán, que no implementó ninguno de los 11 módulos de
plataforma, pero tampoco es un tercero independiente. Las capacidades operativas siguen en `NOT_RUN`.

---

## 6. Lo que este repositorio NO afirma

- No afirma que las capacidades operativas funcionen: **no se han ejecutado**.
- No afirma seguridad ni corrección criptográfica de nada que dependa de red o de claves.
- No afirma certificación de producción. La ruta a producción pasa por
  [`GUIA_PRODUCCION_ORGDNA_V9.md`](GUIA_PRODUCCION_ORGDNA_V9.md) y por las decisiones abiertas
  O-1, A-1, O-3, O-5, D-R0-5 y O-4, cada una con su coste y su reversibilidad.
