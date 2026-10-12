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
  entradas manifiesto : 302
  hashes coincidentes : 302
  hashes divergentes  : 0
  faltantes           : 0
  exentos declarados  : 14     (data/ y el expediente de verificación, por diseño)
  sobrantes reales    : 0
  RESULTADO           : OK

validate_imports_portable.py
  valid: true | errors: [] | checks: 1801 | file_count: 303
  agent_count: 24 | tool_catalog_count: 271 | export_hashes_valid: true
```

`MANIFIESTO_SHA256.txt` → `a29ec9e2e4a39a5a7f4c5d3dd4790abd7787b92db34b953905820b841ba5d867`

El sello cubre **302** archivos; el archivo 303 es el propio manifiesto. `data/` y
`docs/PLATAFORMA_VERIFICACION_V1.md` quedan fuera del sello **deliberadamente**: el primero es estado
de ejecución que el producto reescribe al usarse —verificado: la suite completa lo modifica y los 302
hashes siguen coincidiendo—, el segundo un expediente que debe poder revisarse sin re-sellar el paquete.

---

## 3. ⚠️ Aviso crítico sobre Git y los finales de línea

**No cambies `.gitattributes`.** El paquete está sellado sobre **bytes exactos**, y los archivos de
este árbol son **LF puro**.

Este host trae `core.autocrlf=true` en el gitconfig de sistema (`C:/Program Files/Git/etc/gitconfig`).
Sin la regla `* -text` de [`.gitattributes`](.gitattributes), Git convertiría LF → CRLF al hacer
checkout y **los 302 hashes dejarían de verificar en un clon limpio**. La regla viaja con el repo, así
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

Descubrimiento completo (`test*.py`, 44 módulos), `PYTHONUTF8=1`, sin paralelismo, huella del árbol
`a29ec9e2e4a39a5a7f4c5d3dd4790abd7787b92db34b953905820b841ba5d867`:

```
Ran 1035 tests in 240.995s
FAILED (errors=3, skipped=3)          ← failures=0
```

Los **3 errores restantes son de entorno puro**, verificado uno a uno por su traza:

| Caso | Causa raíz | Naturaleza |
|---|---|---|
| `qa_v6.test_evaluation_independent.test_symlink_in_test_tree_rejected` | `OSError WinError 1314` — sin privilegio para crear enlaces simbólicos | entorno |
| `tests_capability_deployment.test_namespace_traversal_symlink` | `OSError WinError 1314` — ídem | entorno |
| `tests_bridge.test_workbook_stale_blocks_export` | *Mark-of-the-Web* + `RemoteSigned` bloquean el `.ps1` sin firma; el puente Excel lanza si el libro no está abierto | línea base V8 |

Los **3 skips son declarados**, no silenciosos: dos por capacidad de plataforma (grupo de procesos
POSIX; symlinks) y uno por el privilegio de symlink anterior. **Cero fallos atribuibles al producto.**

Comparación controlada de las tres mediciones (misma huella de medición, mismo host):

| Medición | Resultado |
|---|---|
| Clon limpio, antes de la reparación P3‑B (1026 casos) | `failures=1, errors=9, skipped=2` |
| Árbol re-sellado, primera pasada (1035) | `failures=1, errors=5, skipped=3` |
| **Árbol final (1035)** | **`failures=0, errors=3, skipped=3`** |

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

### 5.3 Independencia de la verificación: degradada

La verificación V1 la firmó el propio capitán, que no implementó ninguno de los 11 módulos de
plataforma, pero tampoco es un tercero independiente. Las capacidades operativas siguen en `NOT_RUN`.

---

## 6. Lo que este repositorio NO afirma

- No afirma que las capacidades operativas funcionen: **no se han ejecutado**.
- No afirma seguridad ni corrección criptográfica de nada que dependa de red o de claves.
- No afirma certificación de producción. La ruta a producción pasa por
  [`GUIA_PRODUCCION_ORGDNA_V9.md`](GUIA_PRODUCCION_ORGDNA_V9.md) y por las decisiones abiertas
  O-1, A-1, O-3, O-5, D-R0-5 y O-4, cada una con su coste y su reversibilidad.
