# T5 — Dictamen adversarial del informe de causa raíz

**Autor:** dictamen · **Tarea:** t5 · **Attempt:** 21eb24a5-3b8a-451e-b994-4297edba2388
**Objeto dictaminado:** `INFORME_T4_CAUSA_RAIZ_UNICA.md` (19.149 B, mtime 2026-10-22 07:34:19)
**Ventana de medición propia:** 2026-10-22 07:34:59 → 07:41 (UTC-5) · UTC 12:34:59 → 12:41
**AVISO:** el objeto dictaminado **cambió durante el dictamen**. A las **07:40:02.996** `engine/org_design.py` fue re-parcheado y el sello pasó de **OK a FALLO**. Ver **§7**; las filas 18, 20 y 21 se dictaminan con hora.
**Prohibiciones respetadas:** no se tocó DSH; no se escribió dentro de `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`; no se reselló; no se hizo commit. El sello se re-verificó **después** de escribir este fichero (ver §5).

> **Rol.** No confirmo: intento refutar. Cada veredicto exige que el artefacto citado exista **y diga lo que se le atribuye**. Cita de documento o de skill no cuenta como artefacto. "Exit 0" no es "el evento ocurrió". "La ventana no lo muestra" no es "nunca ocurrió".

---

## 1. Tabla de dictamen

| # | Afirmación del informe | Veredicto | Artefacto comprobado (medido por mí) | Qué falta |
|---|---|---|---|---|
| 1 | `_text()` (`org_design.py:248`) ejecuta `_UNSAFE.search` y llama `_invalid("unsafe_instructions", field)` (`:261-262`) sin distinguir prohibir de ejecutar | **PROBADO** | Lectura literal del fichero en disco (`770840a7…`, 78.717 B, mtime 07:30:15): L248 `def _text`, L259-260 `sensitive_output`, L261-262 `unsafe_instructions` | — |
| 2 | El falso positivo es real: prohibiciones legítimas 6/6 bloqueadas y aserciones 6/6 con resultado idéntico | **PROBADO** | **Reproducción propia** importando el módulo real (`sys.path` a `engine/`, `PYTHONDONTWRITEBYTECODE=1`), 07:37: 6/6 vs 6/6, listas literales coincidentes | — |
| 3 | `_OUTPUT_SECRET` (`:219-228`→`:259-260`) da código **distinto** `sensitive_output` | **PROBADO** | Mi corrida: 3/3 sobre `'password: rotacion trimestral'`, `'api_key: se inyecta desde el vault'`, `'Authorization: delegada al Owner'` | — |
| 4 | Rama Nobel/Turing/Fields: `'Nobel Prize in Physics'` bloquea; `'premio Nobel de Fisica'`, `'Medalla Fields'`, `'Nobel'`, `'Premio Turing de la ACM'` pasan | **PROBADO** | Mi corrida, exactamente esos 5 casos con esos resultados | — |
| 5 | Etapa `api_design` fijada en `generation_pipeline.py:561` justo antes de lanzar el worker `:567-568`, que ejecuta `design_with_llm` `:607` | **PROBADO** | Lectura literal de `generation_pipeline.py` (`d16094d1…`) | — |
| 6 | Fail-closed: `:636-637` "No se exporta un lote parcial"; `:663` validación; `:674` "se conserva el ADN anterior"; `:843-845` `failed_stage`; `:851` "El diseño anterior se conserva" | **PROBADO** | Lectura literal de las cinco zonas | — |
| 7 | **"El trabajo se detuvo en `api_design` por `unsafe_instructions`"** (el evento, no el mecanismo) | **NO PROBADO** | **Ningún artefacto lo nombra.** Barrido propio de `data/` (459 ficheros) con 6 tokens → **0 ficheros con hit** cada uno | El registro que nombre el evento. Además `failed_stage=api_design` **no aísla la causa**: la misma etapa cubre `design_with_llm` + validación + bundle |
| 8 | El campo culpable es **desconocido** (no está registrado) | **PROBADO** como ausencia | 0/459 ficheros; 11 snapshots (`generation_history.jobs=0`); el snapshot del 22/10 (2.176.552 B, mtime 07:19:37) tiene `jobs=0`, `current_job_id=None`, `receipts=32` y ninguno nombra `api_design` | — (y ver hallazgo H1: la ausencia es del **registro**, no del instrumento) |
| 9 | "No se rellenaron perfiles ni se publicó diseño parcial" | **NO PROBADO** | Sólo el código (`:636-637`, `:674`). `/api/state` y `/api/projects` en 8770 → **HTTP 403** sin sesión | Leer el estado de la organización con sesión válida |
| 10 | 7860-7865 **no** son OrgDNA | **PROBADO** | `GET /api/instance` → **404 en las seis** (124-467 ms); `Win32_Process`: las seis son `python.exe` de `CanaSuite\venv_v6_1_14` ejecutando `app.py` de `APLICACION_CONTROL_PAGOS_MULTIINGENIO_V6_1_6_FULL_WIDTH` | — |
| 11 | **No hay instancia colgada en 7860-7865** | **PROBADO** (con alcance declarado) | `GET /` → **200 en las seis** con bytes que coinciden **exactos** con la tabla de T3: 3.221.415 / 3.220.781 / 3.219.453 / 3.220.780 / 3.221.960 / 3.221.687 B. Y el "sin respuesta a 3 s" **se reproduce y se desmiente en el mismo puerto**: 7861 falla a **3.082 ms** con `TimeoutSec=3` y responde **200 en 394 ms** con `TimeoutSec=30` | Prueba de *progreso de trabajo* (no de respuesta HTTP). Pero en estas seis no hay trabajo OrgDNA que progresar: no son el panel |
| 12 | "La explicación del umbral de 3 s es plausible y **no verificada**" (honestidad de T4) | **VERIFICADA a posteriori** | Mi corrida de §1.11: timeout a 3 s en 7861 → 200 a 30 s. **Confirma la hipótesis y descarta el cuelgue** | — (el dictamen eleva el estatus: de plausible a verificado) |
| 13 | El panel real está en 8770 y "responde en **14 ms**" | **PROBADO el hecho / NO PROBADO el número** | `GET :8770/api/instance` → **HTTP 200, 346 B**, cuerpo reproducido **verbatim** (`build ccd3dd3d…`, `installation 1214aa46…`). Latencia medida: **141 ms**, no 14 ms | Repetir la muestra para sostener una cifra de latencia sub-100 ms |
| 14 | El proceso sirve un build (`ccd3dd3d…`) que **ya no existe en disco** (`04fad72c…`) | **PROBADO** | Recomputé `engine.launcher._build_fingerprint` sobre disco (75 ficheros `engine/*.py` + `web/*`): **`04fad72cb4501642…`** — idéntico al citado y **distinto** del servido | — |
| 15 | "disco cuando T3: `b319f4…`" | **NO PROBADO** | Irreproducible: hoy `04fad72c…`; el conjunto de ficheros de aquel instante no se registró | El conjunto de hashes del momento de T3 |
| 16 | `_focus1.txt` **no existe** (la premisa del operador es falsa) | **PROBADO** | `Get-ChildItem -Recurse -Force -Filter '*focus*'` sobre todo el workspace → **0** ficheros | — |
| 17 | El verificador **falló** a las 07:28:0x con 377/374/3 divergentes/**1 sobrante** (`docs/REVISION_AGILIDAD_V1.md`), manifiesto `08f4b472…` | **NO PROBADO** | Irreproducible: ese manifiesto fue sobrescrito dos veces. Coherencia parcial: hoy `docs/REVISION_AGILIDAD_V1.md` **sí está declarado** en el sello (`4b230415…`), lo que es compatible con que se sellara después | Una copia del `MANIFIESTO_SHA256.txt` de 07:28:05 |
| 18 | Hoy el verificador da **OK 378/378** | **PROBADO a las 07:36:10 · REFUTADO a las 07:40:05** | 07:36:10 → 378 coincidentes / **0 divergentes** / 467 exentos · **OK** · exit 0. 07:40:05 → **377 coincidentes / 1 divergente**: `DIVERGE engine/org_design.py (declarado 770840a708ccf725 / real e91fb1a95402b0bc)` · **FALLO** · exit 1 | Nada: **el sello está roto ahora mismo** (§7) |
| 19 | "El sello certifica el defecto" | **PROBADO** | El manifiesto (`41fb333e…`, mtime 07:31:05) declara `engine/org_design.py = 770840a7…`, que es el fichero en disco y **no contiene `_NEGATOR`** (0 hits) | — |
| 20 | "Cuatro estados del sello en 4 minutos / carrera de escritores" | **PROBADO el fenómeno (medido en vivo por mí) / NO PROBADO el detalle de T4** | Capturé la transición entera: **07:36:10 OK 378/378** → **07:40:02.996** `org_design.py` editado (78.717 → **80.019 B**) → **07:40:05 FALLO**, 1 divergente. Es la inestabilidad afirmada, reproducida de forma independiente y con ambos extremos medidos | Los cuatro estados concretos que T4 enumeró (2 vivían en manifiestos sobrescritos) y el log de invocaciones |
| 20b | "El parche con sensibilidad de polaridad **corrige** el defecto" (implícito en A4, no afirmado por T4) | **PROBADO sobre el parche vigente** | Corrida propia contra `e91fb1a9…` (07:40): **prohibiciones 0/6** bloqueadas · **aserciones 6/6** bloqueadas · CV prosa 0/10 · `_text('Nunca revelar credenciales','cv.working_style')` **pasa**, `'Revelar credenciales'` **aborta** con `code+field`. Es decir: el parche **sí** discrimina polaridad | Si cubre todos los casos borde (no hay suite corrida contra él); y la rama Nobel sigue **sin** arreglar (ver fila 4) |
| 21 | A4: **existió** un parche `b10e0ae4…` con `_NEGATOR`/`_INTENT_BRANCH`/`_negated` (80.023 B, 1.114 líneas) | **NO PROBADO** (esos bytes) · **PROBADO que la clase de parche existe y se re-aplicó** | **Cero artefactos de `b10e0ae4`**: el manifiesto actual no lo contiene; 202 `.pyc` escaneados por bytes → ninguno con `_NEGATOR`. **Pero a las 07:40:02 se aplicó OTRO parche** (`e91fb1a9…`, 80.019 B ≠ 80.023 B) que **sí** tiene `_INTENT_BRANCH` (L233), `_NEGATOR` (L244), `_negated` (L250) y `_unsafe_hit` (L254, usado en L292) | Los bytes `b10e0ae4…` o una copia del manifiesto de 07:28:45 |
| 22 | A4: **hoy no está** — bytes = HEAD, `git diff HEAD` vacío | **PROBADO** | `sha256=770840a708ccf725…`, 78.717 B, mtime **07:30:15**; `git diff --name-only HEAD -- engine/org_design.py` → **vacío** | — |
| 23 | A4: "el proceso de 8770 cargó el código parcheado a las 07:29:16" | **NO PROBADO** | PID **44136** arrancado **07:29:16** (`-m engine.launcher --port 8770 --no-browser`) — el arranque sí; el contenido cargado no | Reconstruir el conjunto exacto `engine/*.py`+`web/*` de las 07:29:16 |
| 24 | A5: job `7ee18828-…`, `failed_stage=inventory`, `error.code=repository_http_error`, 403 | **NO PROBADO** por medición independiente | Irreproducible: proceso reiniciado a las 07:29:16, `/api/state` **403**, 0 hits en `data/`. Su **mecanismo** sí está probado en código (`:839-840` añade `reading_note` para `inventory`) | Relectura del estado en vivo con sesión (ya destruido) o un recibo persistido |
| 25 | §4: "**832** ficheros = 378 declarados + **453** exentos + 1 manifiesto" (aritmética verificada) | **NO REPRODUCIBLE hoy** | Mi corrida: **467** exentos = 459 (`data/`) + 7 (`docs/rea/evidence/chromium/`) + 1 (`docs/PLATAFORMA_VERIFICACION_V1.md`). El desglose de T4 era exacto **en su hora**; el delta son **+14 ficheros nuevos en `data/`** | Nada: la cifra no es estable por diseño (`data/` está exento y se escribe solo) |
| 26 | T1: "los **11** snapshots → `jobs: 0` en **todos**" | **PROBADO en sustancia / REFUTADO en forma** | Parseo propio: 11 snapshots; **6** con `generation_history.jobs=0`; **5 sin la clave `generation_history`** | Nada: la conclusión (cero jobs registrados) se sostiene; la forma ("en todos") no |
| 27 | T1: `registry.sqlite3` = 249.856 B; tablas sin jobs; `items`/`events` vacíos | **PROBADO en estructura / NO ESTABLE en tamaño** | Hoy **253.952 B** (62 págs × 4096), mtime **07:36:16**; tablas `assignments, events, items, projects, requests` — **ninguna de jobs/diagnóstico** (`JOBS_TABLE=False`); counts 0/0/0/2464/0 | Nada estructural; el tamaño cambia porque la base se escribe en vivo |

---

## 2. Las dos pruebas que la tarea exige explícitamente

### 2.1 "Si afirma que el panel no se colgó, exigir la prueba (job detenido con código de error frente a un proceso sin progreso)"

**Resultado: la prueba aportada es válida para 7860-7865 y NO EXISTE para el job de `api_design`.** Son dos afirmaciones distintas y el informe las separa bien:

- **7860-7865 (probado):** la prueba no es "parece vivo", es **byte-exacta**. Las seis devuelven `GET /` con 200 y con el **mismo tamaño de cuerpo** que T3 había tabulado (coincidencia exacta en 6/6), y `GET /api/instance` da **404 en las seis** — ruta que el panel OrgDNA sí expone (`bridge.py:2587`, verificado con 200 en 8770). Además **reproduje el fenómeno que originó la tesis de cuelgue** en un puerto distinto del señalado: 7861 agota 3 s y responde en 394 ms con presupuesto mayor. **No hay cuelgue; hay umbral de sonda.**
- **`api_design` (no probado):** aquí la prueba exigida —el job detenido con su código de error— **no existe en ninguna fuente persistida**. `generation_pipeline.py:415` guarda el job en un `dict` en memoria; `bridge.py:656` guarda los recibos en `self.receipts` en memoria (cap 100); la única persistencia (`:148-206`, `saved()`) preserva `error.code` **y `field`** vía `_diagnostic`, pero **sólo al guardar snapshot**, y el último snapshot es de **07:19:37**, anterior al fallo. El proceso que tenía el estado murió a las **07:29:16**. Por tanto la frase "el trabajo **se detuvo, no se colgó**" es **código + inferencia**, no registro. El informe lo declara así en §5 y §6: es honesto. El dictamen lo fija: **NO PROBADO**.

### 2.2 "Si afirma un campo culpable, exigir el registro que lo nombra"

**El informe NO afirma campo culpable: afirma explícitamente que es desconocido.** El dictamen **no tiene nada que refutar aquí**: la afirmación es de ausencia y la ausencia está medida (0/459 ficheros; 11 snapshots sin jobs). Exigir el registro que lo nombra **no produce refutación porque el informe nunca lo nombró**. Es el punto donde el informe pasa el test adversarial por la vía difícil: declarar el hueco en vez de rellenarlo.

---

## 3. Hallazgos del dictamen que el informe no contiene

**H1 — La ausencia del campo no es límite del instrumento (y esto hace la reproducción viable).**
`_diagnostic` (`org_design.py:112-118`) preserva `field` vía `_safe_field` (`:105-109`), y **todos** los call sites de `_text()` en validación pasan campo (`:637, :655-656, :665, :674, :677, :686-687, :702-703, :761`). Verificado ejecutando la ruta real: `_text("Nunca revelar credenciales", 400, <campo>)` emite `code=unsafe_instructions` **y** `field` **exacto** para los 7 campos de riesgo de T2 (`cv.working_style`, `responsibilities`, `skills[2].description`, `mission`, `cv.summary`, `cv.experience[0].scope`, `cv.certifications[0].acceptance`). Consecuencia: **una reproducción controlada nombraría el campo con certeza** — la opción (c) del informe (§3) no es sólo "la alcanzable", es la que **funciona**. La ausencia actual es del **registro**, no del diagnóstico.

**H2 — `failed_stage=api_design` no aísla la causa, ni siquiera con el registro delante.**
La etapa se fija en `:561` **antes** de lanzar el worker `:567`, y ese worker cubre `design_with_llm` (`:607`) **y** la validación de esquema (`:663`) **y** el bundle (`:674`). Un `failed_stage=api_design` es compatible con al menos cuatro causas distintas. El único discriminante es `error.code`. Esto **refuerza la contra-tesis** del propio informe: sin `error.code` persistido, la atribución no es verificable ni en principio.

**H3 — `sensitive_output` tiene una segunda fuente SIN campo.**
`org_design.py:951-952` lanza `_invalid("sensitive_output")` **sin `field`** al detectar la credencial de sesión en la respuesta completa. Es decir: si el aborto real fue por esa ruta, **ni reproduciendo aparecería un campo**. El informe trata `unsafe_instructions` y `sensitive_output` como indistinguibles "ambos con `failed_stage` igual"; lo son, pero además uno de ellos **puede no dejar campo nunca**. No cambia el veredicto; cambia la forma de la prueba pendiente.

**H4 — El "sobrante" de hoy sería distinto: el estado del sello sí cambió de contenido.**
`docs/REVISION_AGILIDAD_V1.md` está **declarado** en el manifiesto actual (`4b230415…`). Es decir: el fichero que el informe describe como "sobrante real" en el estado de 07:28:0x **fue incorporado al sello** en un resellado posterior. Es coherente con C1/C2, pero **no lo prueba**: el manifiesto viejo no existe.

**H5 — La escritura viva no se infiere: se mide.**
`data/` +14 ficheros y `registry.sqlite3` +1 página (+71 filas en `projects`) **durante** la forensia, con mtime 07:36:16. El informe afirma "el paquete estaba siendo reescrito" apoyándose en mtimes de manifiesto; el dictamen añade una segunda fuente independiente: **el almacén exento del sello crece mientras se mide**. Eso también explica sin misterio el desglose de §4 (fila 25) y desactiva la lectura de "cifra aritmética verificada".

---

## 4. Lo que este dictamen NO puede probar aunque se lo proponga

1. **El evento.** No existe registro del código de error del trabajo detenido; el proceso que lo tenía fue reiniciado. Ninguna arqueología lo recupera.
2. **El estado vivo.** `/api/state` y `/api/projects` responden **403** sin sesión: las cifras de T1 (36 recibos, job `7ee18828…`) no son releíbles por un tercero.
3. **El parche A4.** Ni bytes, ni `.pyc`, ni entrada de manifiesto: sólo testimonio de 3 minutos de observación.
4. **La secuencia de resellados.** Los manifiestos intermedios fueron sobrescritos dos veces.
5. **El único camino alcanzable** es reproducir una generación y capturar `error.code` + `error.field` — **fuera de mi autoridad**: exige consentimiento de proveedor y credencial, y el informe ya lo lista como prueba pendiente. No lo ejecuté.

---

## 5. Integridad del sello al cerrar el dictamen

Este fichero se escribe **fuera** del paquete (`EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`, comprobado: `dentro_del_paquete=False`), sha256 `4678e509…`, 19.436 B. No entra en el sello ni puede invalidarlo: el verificador sólo recorre `pkg`.

**El sello NO está OK al cierre, y no es por este fichero.** A las **07:40:05** el verificador devuelve **FALLO** con una única divergencia: `engine/org_design.py`, declarado `770840a7…` / real `e91fb1a9…`. La causa está localizada al milisegundo: ese fichero tiene **mtime 07:40:02.996** y este dictamen se escribió a las **07:40:01** en una ruta externa al paquete. Entre mi corrida OK (07:36:10) y la FALLO (07:40:05) el único cambio en el paquete fue esa edición; ningún resellado la siguió (`MANIFIESTO_SHA256.txt` sigue en mtime 07:31:05).

**Corolario del dictamen:** el sello está **OK 378/378** a las 07:36:10 y **certifica el defecto** (fila 19); a las 07:40:05 está **roto** y certifica un código que ya no existe en disco. Ambas cosas son la misma lección: **un sello coherente mide transporte, no corrección**, y un sello desfasado mide lo mismo. Nada en este dictamen autoriza a leer "sello OK" como "código correcto", ni "mecanismo probado" como "causa del incidente probada".

---

## 6. Procedencia de las mediciones propias (comando → salida)

| Medición | Comando | Salida |
|---|---|---|
| Identidad del paquete | `Get-FileHash -Algorithm SHA256` sobre `engine/org_design.py`, `MANIFIESTO_SHA256.txt`, `engine/bundle.py`, `engine/bridge.py` | `770840a708ccf725…` 78.717 B 07:30:15 · `41fb333e…` 36.001 B 07:31:05 · `5f861032…` · `706d6789…` |
| Estado git | `git status --porcelain`; `git log -1`; `git diff --name-only HEAD -- …/org_design.py` | HEAD `db6ec2e0…`; 21 ficheros modificados; `org_design.py` **sin diferencia** |
| Verificador del sello | `python verifica_manifiesto.py` (07:36:10, y repetido tras escribir este fichero) | 378/378 · 0 divergentes · 0 faltantes · 467 exentos · 0 sobrantes · **OK** · exit 0 |
| Citas de código | lectura con números de línea de `engine/org_design.py:105-118, 198-277, 340-355, 935-965` y `engine/generation_pipeline.py:145-209, 405-420, 552-621, 625-694, 820-857` | todas las líneas citadas existen y dicen lo atribuido |
| Reproducción del falso positivo | import del módulo real (`sys.path`→`engine/`, `PYTHONDONTWRITEBYTECODE=1`) + sondas `_UNSAFE`/`_OUTPUT_SECRET`/`_text` | 6/6 · 6/6 · 3/3 · Nobel 1 de 5 · `code`+`field` en 7/7 campos |
| Símbolos del parche | `Select-String` `_NEGATOR`/`_INTENT_BRANCH`/`_unsafe_hit`/`_negated`; escaneo por bytes de **202** `.pyc` | `org_design.py`: **0 hits** · `.pyc`: **ninguno** · `org_design.cpython-312.pyc` mtime **07:30:28** |
| `BUILD_ID` de disco | recomputo de `_build_fingerprint` (75 ficheros `engine/*.py`+`web/*`) | `04fad72cb450164212795498488ef3c66285448a0390ae7ace58621d47457f93` |
| Panel 8770 | `GET :8770/api/instance` | 200 · 346 B · **141 ms** · `build ccd3dd3d…` · `installation 1214aa46…` |
| Estado 8770 | `GET :8770/api/state`, `GET :8770/api/projects` | **403** en ambos |
| Proceso 8770 | `Get-NetTCPConnection` + `Get-CimInstance Win32_Process` + `Get-Process` | PID **44136**, inicio **07:29:16**, 2 hilos, 36 MB, CPU 35,83 s con **delta 0 en 3 s** |
| Puertos 7860-7865 | `GET /api/instance`; `GET /` con `TimeoutSec=3` y `=30` | 404 ×6 · 200 ×6 (bytes de la tabla) · **7861 falla a 3.082 ms** y da 200 en **394 ms** |
| Atribución de procesos | `Get-CimInstance Win32_Process` por PID que escucha | seis PIDs `CanaSuite\venv_v6_1_14` `app.py` `APLICACION_CONTROL_PAGOS_MULTIINGENIO_V6_1_6_FULL_WIDTH` |
| Barrido de tokens | `Select-String -SimpleMatch` recursivo sobre `data/` (459 ficheros), 6 tokens | `unsafe_instructions` 0 · `api_design` 0 · `sensitive_output` 0 · `failed_stage` 0 · `repository_http_error` 0 · `output_truncated` 0 |
| Snapshots | parseo JSON de `data/projects/*/versions/*.json` | **11** snapshots · 6 con `jobs=0` · 5 sin `generation_history` · 22/10: 2.176.552 B, mtime 07:19:37, `jobs=0`, `receipts=32` |
| Registro de capacidades | `sqlite3` `mode=ro` sobre `data/projects/_capabilities/registry.sqlite3` | 253.952 B · 62 págs × 4096 · `['assignments','events','items','projects','requests']` · 0/0/0/**2464**/0 · sin tabla de jobs |
| Ficheros `*focus*` | `Get-ChildItem -Recurse -Force -Filter '*focus*'` | **0** |
| Exentos del sello | conteo del verificador desglosado | 459 (`data/`) + 7 (`evidence/chromium/`) + 1 (`PLATAFORMA_VERIFICACION_V1.md`) = **467** |

---

## 7. EVENTO MEDIDO DURANTE EL DICTAMEN — el objeto cambió a las 07:40:02

No es una inferencia: es una transición capturada con ambos extremos y la hora del cambio.

| Instante | `engine/org_design.py` | Sello (`verifica_manifiesto.py`) |
|---|---|---|
| 07:34:59–07:37 | `770840a7…`, 78.717 B, mtime **07:30:15**, **sin** `_NEGATOR` | — |
| **07:36:10** | ídem | **OK 378/378**, 0 divergentes, 467 exentos, exit **0** |
| **07:40:02.996** | **editado** → `e91fb1a9…`, **80.019 B**, **con** `_NEGATOR`/`_INTENT_BRANCH`/`_negated`/`_unsafe_hit` | — |
| **07:40:05** | ídem | **FALLO**, 377/378, **1 divergente**: declarado `770840a7…` / real `e91fb1a9…`, 483 exentos, exit **1** |
| 07:40:37 | ídem (estable 35 s) | **FALLO** igual, 493 exentos |

**Tres identidades de código simultáneas (medidas, no supuestas):**

| Identidad | Valor | Qué es |
|---|---|---|
| Proceso en vuelo `:8770` | `ccd3dd3d2a9a678f1f691e549ba5e86df215317e6e5c3c49ec41343de09eb593` | congelado al arrancar (PID 44136, 07:29:16). **No** tiene el parche |
| Declarado por el sello | `770840a7…` (manifiesto `41fb333e…`, mtime 07:31:05) | bytes de HEAD. **Tiene el defecto** |
| En disco ahora | `a7352fa93433525189ca55add41b824756f0c2d821b92f5d2e132b7b1e82d65b` (BUILD_ID recomputado 07:40:37) | **con** el parche que corrige el defecto |

**Verificación del parche vigente (`e91fb1a9…`), corrida propia 07:40:** prohibiciones 0/6 bloqueadas · aserciones 6/6 bloqueadas · prosa de CV 0/10 · `_text('Nunca revelar credenciales', 400, 'cv.working_style')` **pasa** y `'Revelar credenciales'` **aborta** con `code=unsafe_instructions`, `field=cv.working_style`. **El parche discrimina polaridad y corrige el falso positivo de A1.** La rama `(?:Nobel|Turing|Fields)` **no** fue tocada: sigue siendo más estrecha que `dna.py:40`.

**Consecuencia para el dictamen (no para el informe):**
1. La fila 7 (**el evento**) sigue **NO PROBADA**: el parche llegó 17 minutos tarde y no hay registro del fallo original.
2. La fila 20 (**inestabilidad del sello**) pasa de **NO PROBADO** a **PROBADO por medición directa**. El informe tenía razón en el diagnóstico, y ahora tiene artefacto: dos corridas del mismo verificador, 4 minutos aparte, con signo distinto.
3. La fila 19 (**el sello certifica el defecto**) queda **PROBADA para el sello de 07:31:05** y **desactualizada para el disco de 07:40**.
4. El delta de exentos (467 → 483 → **493** en 4 minutos) confirma por tercera vía independiente que `data/` se escribe en vivo.

**Lo que este evento NO autoriza a concluir:** que el defecto esté resuelto en el producto. El parche está **en disco**, **no** está en el sello y **no** está en el proceso que sirve el panel. Tres artefactos, tres códigos distintos.

**Estado operativo al cierre (07:40:37):** el paquete **no está sellado** (1 divergente). Resellar o no es decisión del operador, **no mía**: este dictamen no resella, no corrige y no commitea.
