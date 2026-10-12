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
| `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/` | El producto. 302 archivos, **sellado por SHA-256** (301 entradas). |
| `verifica_manifiesto.py` | Verificador independiente del sello. Solo stdlib. Código 0 = sello íntegro. |
| `OBSERVACIONES_CAPITAN_PLATAFORMA.md` | Registro del capitán: decisiones abiertas O-1…O-23, cada una con su estado. |
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
python verifica_manifiesto.py          # sello SHA-256: 301/301 hashes sobre bytes en disco
python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py
```

Resultado medido en el árbol congelado que originó este repositorio:

```
verifica_manifiesto.py
  entradas manifiesto : 301
  hashes coincidentes : 301
  hashes divergentes  : 0
  faltantes           : 0
  exentos declarados  : 14     (data/ y el expediente de verificación, por diseño)
  sobrantes reales    : 0
  RESULTADO           : OK

validate_imports_portable.py
  valid: true | errors: [] | checks: 1796 | file_count: 302
  agent_count: 24 | tool_catalog_count: 271 | export_hashes_valid: true
```

`MANIFIESTO_SHA256.txt` → `bde630927326bafeddb1d45e26808d98a3ffc68a0139d248241a190c21a3f585`

El sello cubre **301** archivos; el archivo 302 es el propio manifiesto. `data/` y
`docs/PLATAFORMA_VERIFICACION_V1.md` quedan fuera del sello **deliberadamente**: el primero es estado
de ejecución que el producto reescribe al usarse, el segundo un expediente que debe poder revisarse
sin re-sellar el paquete.

---

## 3. ⚠️ Aviso crítico sobre Git y los finales de línea

**No cambies `.gitattributes`.** El paquete está sellado sobre **bytes exactos**, y los archivos de
este árbol son **LF puro**.

Este host trae `core.autocrlf=true` en el gitconfig de sistema (`C:/Program Files/Git/etc/gitconfig`).
Sin la regla `* -text` de [`.gitattributes`](.gitattributes), Git convertiría LF → CRLF al hacer
checkout y **los 301 hashes dejarían de verificar en un clon limpio**. La regla viaja con el repo, así
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
  -p 'tests*.py' -v
```

**Define `PYTHONUTF8=1` en Windows.** Tres módulos heredan la página de códigos cp1252 y fallan sin
esa variable; con ella pasan. Está medido y documentado en el expediente de verificación (§3.2).

---

## 5. Defectos conocidos y atribución honesta

La comparación controlada línea base → con plataforma (mismo árbol congelado, misma huella de
medición) dio:

- **Regresión atribuible a la integración: 6 → 0.** Cerrada por reparación, con falsificación
  ejecutada: revertir las dos reparaciones hace fallar 4 de los 9 casos nuevos.
- **Quedan 11 fallos de línea base/entorno, no atribuibles**: 1 por *Mark-of-the-Web* +
  `RemoteSigned` bloqueando el `.ps1` sin firma (y el puente Excel lanzando cuando el libro no está
  abierto), 4 de entorno, 1 de symlinks (`WinError 1314`, con `core.symlinks=false`), 3 de cp1252.
- **2 skips legítimos.**

Post-reparación, la suite completa reportó `Ran 782 tests — FAILED (failures=1, errors=10,
skipped=2)`, y la suite de plataforma **391 OK (skipped=1)**. Cifras del expediente registrado en
`verificacion_v2_suite.txt` con su huella de medición en `verificacion_v2_huella.json`.

**Independencia de la verificación: degradada.** La verificación V1 la firmó el propio capitán, que no
implementó ninguno de los 11 módulos de plataforma, pero tampoco es un tercero independiente. Las
capacidades operativas siguen en `NOT_RUN`.

---

## 6. Lo que este repositorio NO afirma

- No afirma que las capacidades operativas funcionen: **no se han ejecutado**.
- No afirma seguridad ni corrección criptográfica de nada que dependa de red o de claves.
- No afirma certificación de producción. La ruta a producción pasa por
  [`GUIA_PRODUCCION_ORGDNA_V9.md`](GUIA_PRODUCCION_ORGDNA_V9.md) y por las decisiones abiertas
  O-1, A-1, O-3, O-5, D-R0-5 y O-4, cada una con su coste y su reversibilidad.
