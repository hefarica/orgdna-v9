# REVISION_AGILIDAD_V1 — Verificación independiente y adversarial de la misión de agilidad

**Tarea:** `t28` (V) · **Verificador:** `evidencia` (no implementó `t22`–`t27`)
**Fecha de la verificación:** 2026-10-22, 01:25 → 07:20 (hora local, UTC−5).
**Árbol verificado:** HEAD `db6ec2e` + los cambios sin commitear de la misión de agilidad
(`git status`: **21 rutas modificadas** — 8 de código/pruebas del paquete, 8 de sello/documentos,
5 de estado del equipo en `.agent-teams/` — y **19 rutas nuevas**, más este informe).
**Baseline de comparación:** copia limpia de `db6ec2e` obtenida con
`git archive db6ec2e` → `%TEMP%\t28_base` (no se tocó el árbol de trabajo para crearla).

**Declaración de independencia:** no implementé ninguno de los módulos auditados; no reparé
código, no toqué DSH y no re-sellé. Todo número de este informe lo produje yo con los comandos
de §10; cuando no pude reproducir una cifra de la misión, queda dicho con su medida.

**Aviso de tiempos.** El host se suspendió entre dos turnos de esta sesión (salto de reloj
observado: 01:39:20 → 07:04:42). Por eso **los tiempos de pared de una corrida contaminada por
esa pausa no valen como medida de velocidad**; solo cito como tiempo el que mide el propio
`unittest` (643,519 s canónico) y marco explícitamente el otro.

---

## 1. Veredicto

# PASS

La misión está entregada y es reproducible, con **cuatro hallazgos (uno medio, tres bajos)** y
**dos observaciones informativas**, ninguno de los cuales invalida lo entregado. El PASS es
**condicionado a un acto documental** (H-2): registrar en el acta el re-sello del paquete
posterior al cierre de `t27`, con hash anterior y nuevo. No hay código que reparar por mi parte
(prohibido), y ninguna aserción de guard quedó relajada.

| Criterio de aceptación | Resultado | Evidencia |
| --- | --- | --- |
| Guards no debilitados (diffs vs `db6ec2e`) | **Cumple** | §2: 5 ficheros-guard byte-idénticos; 2 con solo `encoding='utf-8'` (refuerzan); 1 re-basado declarado (pin 70→72); 0 aserciones relajadas |
| Re-ejecución propia: sello, suite, validador, DSH | **Cumple** | §3: sello 377/377; suite 1517 pruebas, 0 fallos, 5 errores; validador 2201 checks/378 ficheros; DSH 4/4 |
| Agilidad real y no nominal | **Cumple, con límite declarado** | §5: follow-ups persigue (evento `reminder`), sandbox sin aprobación NO ejecuta (marcador ausente) y con aprobación SÍ (control positivo), `team_loop` avanza el proceso, `lease_held`, reanudación |
| Evidencia Chromium real y sin trampa | **Cumple** | §6: PNG existen, 6/6 digests coinciden, 57 aserciones, 6/6 pasos, arnés auditado (aborta al fallar, no fabrica DOM) |
| Diferencial contra baseline con medición | **Cumple** | §4: los 5 errores de la suite se reproducen igual en `db6ec2e`; 0 fallos nuevos sin atribuir |
| Informe con veredicto, severidades y no verificado | **Cumple** | este documento (§7) |

**Nota sobre el sello y este informe:** cuando lo escribí, el sello pasó de «OK, 0 sobrantes» a
«1 sobrante = `docs/REVISION_AGILIDAD_V1.md`» (0 divergentes y 0 faltantes en ambos casos). Es el
guard haciendo su trabajo con un fichero nuevo no declarado; la tarea de integración debe
re-sellar (§3.1, §9).

---

## 2. Guards: comparación por diffs contra `db6ec2e`

Método: `git diff db6ec2e -- <fichero>` y lectura de la aserción citada en cada uno.

| Fichero-guard | Estado vs `db6ec2e` | Qué cambió | ¿Se debilita? |
| --- | --- | --- | --- |
| `tests_bridge.py` (líneas 187 y 217) | **byte-idéntico** | nada | **No.** L187: rechaza 6 configuraciones inválidas (`agent_count 41`, `max_direct_reports 0`, `api_key`, `repo_url` a 127.0.0.1, `repo_url` con `token=`, `implementation_concurrency 4`). L217: exige que no se filtren `__CSRF_TOKEN__`/`__MAX_AGENTS__` y que `X-Frame-Options == DENY` |
| `tests_model_catalog_scopes.py` (43 y 62) | **byte-idéntico** | nada | **No.** L43: nombre/alias de API rechazado incluso si hay preferencia manual. L62: el alias de proveedor no salta el catálogo exacto |
| `tests_org_design.py` (178) | **byte-idéntico** | nada | **No.** Exige `availability_verified == False`: los límites desconocidos no se inventan |
| `qa_v7/test_generation_failures_independent.py` (274) | **byte-idéntico** | nada | **No.** Exige `ConsentRequired` con marcador privado y `fixture.calls == []` |
| `qa_v7/dsh_baseline.json` | **byte-idéntico** | nada | **No.** No se añadió ninguna enmienda. El fichero contiene **8 enmiendas históricas**, todas con `file` + `previous_sha256` + `new_sha256` + `reason` + `evidence` (verificado campo a campo): cumplen el estándar exigido |
| `tests_v8_ui_contract.py` | +3/−3 líneas | `read_text(encoding='utf-8')` en `setUpClass` (js/html/css) | **No: refuerza.** Antes el `setUpClass` moría con `cp1252` en Windows y los 15 contratos de UI **no llegaban a ejecutarse**; ahora sí |
| `qa_v7/test_dsh_preservation_independent.py` | +6/−4 líneas | `read_text(encoding='utf-8')` en baseline, `app.js` y `bridge.py` | **No: refuerza.** Las cuatro aserciones (`assertEqual(actual, BASELINE[...])`, hashes de handlers, bytes pineados) están intactas |
| `tests_platform_integration.py` | +3/−1 líneas | pin `len(modules) == 70` → `== 72` con comentario que declara la revisión (`team_process.py`, `team_loop.py`) | **No: re-base declarado.** La aserción sigue siendo exacta (`assertEqual(len(modules), 72, ...)`) y sigue detectando altas no documentadas |

Anclas del baseline DSH, medidas por mí sobre los bytes en disco:

- **41/41** ficheros pineados coinciden con su SHA-256 declarado.
- **14** funciones JavaScript pineadas y **3** ramas de dispatch del bridge: presentes y sin cambios
  (`qa_v7.test_dsh_preservation_independent`: **4/4 OK**, §3).
- `javascript_handler_lines_sha256` = `260fbd8fbcb1415b921a918f…`, `baseline_zip_sha256` =
  `76046fa7dc96b4c3…` (sin cambios en el fichero).
- **DSH no se tocó:** 0 ficheros bajo `C:\Users\HFRC\.dsh-vscode` con fecha de modificación dentro
  de la ventana de la misión (2026-10-21 23:30 → 2026-10-22 01:30).

Ruido detectado y clasificado (no es un guard): `verifica_manifiesto.py` (+4) y
`resella_paquete.py` (+5/−1) **añaden** a `EXENTOS` la ruta `docs/rea/evidence/chromium/`, y
`engine/bundle.py` (+17) amplía `RUNTIME_ALLOWLIST` con 17 nombres **literales** (sin globs). La
exención es el hallazgo **H-1**.

---

## 3. Reproducibilidad: los números que obtengo yo

### 3.1 Sello

Medido **antes** de que yo escribiera este informe:

```
python verifica_manifiesto.py            (desde la raíz del workspace)
entradas manifiesto: 377
hashes coincidentes: 377
hashes divergentes : 0
faltantes          : 0
exentos declarados : 380
sobrantes reales   : 0
RESULTADO: OK - integridad del sello verificada sobre bytes en disco      [exit 0]
```

Desglose propio de los 380 exentos: `data/` **372**, `docs/PLATAFORMA_VERIFICACION_V1.md` **1**,
`docs/rea/evidence/chromium/` **7**. Manifiesto vigente: **377 líneas, 35 906 B, sha256
`3cb13e911b92c05c9c59bc2135f7ee7523357fd7717191a3feec468237a6f57a`, mtime 2026-10-22 01:27:27**.

Medido **después** de escribir este informe (mismo comando, mismo árbol):

```
entradas manifiesto: 377 | hashes coincidentes: 377 | hashes divergentes: 0 | faltantes: 0
exentos declarados : 453
sobrantes reales   : 1
  SOBRANTE  docs/REVISION_AGILIDAD_V1.md
RESULTADO: FALLO
```

**Esto es el comportamiento correcto del guard, no una regresión:** el sello marca como sobrante
cualquier fichero nuevo no declarado, y este informe lo es. Los exentos pasan de 380 a 453 porque
`data/` creció de 372 a **445** ficheros: son proyectos locales escritos por las corridas de la
suite y por mis sondas en la ruta de estado declarada exenta. Lo correcto es que la tarea de
integración vuelva a sellar al final (yo no puedo: me lo prohíbe el encargo). Divergentes y
faltantes siguen en 0, que es lo que mide la integridad de lo ya sellado.

**No coincide con el que declaró `t27` (`56cd7063…`)**: el sello se regeneró **después** de su
informe (H-2). El sello actual **sí** cubre los bytes actuales, incluidos `web/app.js`
(`3e9563c0…`), `web/index.html` (`3e068785…`), `engine/bridge.py` (`706d6789…`),
`engine/team_loop.py` (`22311fdb…`), `engine/team_process.py` (`1586c9d0…`),
`tests_v8_ui_contract.py` (`3ad9c9ed…`) y `qa_v7/dsh_baseline.json` (`b5444d7a…`).

### 3.2 Suite completa canónica (comando literal del contrato, sin `PYTHONUTF8`)

```
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN \
       -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'test*.py'          [exit 1]
Ran 1517 tests in 643.519s
FAILED (errors=5, skipped=1)        ← 0 failures
```

Errores (5), todos ya conocidos y **reproducidos en baseline** (§4):

1. `setUpClass (tests_frontend_contract.FrontendContracts)` — `UnicodeDecodeError` cp1252.
2. `tests_generation_pipeline...test_save_reload_does_not_restore_consent_or_start_jobs` — cp1252.
3. `qa_v6.test_http_multisource...test_both_sources_real_http_and_three_downloads_30_agents` — `TimeoutError`.
4. `tests_bridge.BridgeStateTests.test_workbook_stale_blocks_export` — Excel COM (`excel_bridge.ps1`).
5. `tests_bridge.HTTPTests.test_bad_host_origin_csrf_cookie_blocked` — `ConnectionAbortedError [WinError 10053]`.

**Corrida de control con `PYTHONUTF8=1`** (para separar la clase `encoding` del resto):

```
python -m unittest discover ... -p 'test*.py'   (PYTHONUTF8=1)      [exit 1]
Ran 1532 tests in 19926.276s     ← tiempo NO válido: incluye una suspensión del host de ~5,5 h
FAILED (errors=3, skipped=1)     ← 0 failures
```

Con UTF-8 los 15 contratos de `tests_frontend_contract` se ejecutan (**15/15 OK**, §4) y quedan
solo los 3 errores de entorno (multisource, workbook, bad_host).

**Delta con lo declarado por `t27` (1517 / 710,7 s / 0 fallos / 4 errores / 1 skip):** mismo
número de pruebas y 0 fallos; **una prueba de diferencia en errores** (`bad_host_origin`, que es
intermitente y también falla en baseline: H-6) y **67 s menos** de tiempo de suite.

### 3.3 Validador portable

```
python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py     [exit 0]
"valid": true, "errors": [], "checks": 2201, "file_count": 378,
"agent_count": 24, "export_hashes_valid": true
```

Coincide con `t27` (2201 comprobaciones / 378 ficheros).

### 3.4 Preservación DSH

```
python -m unittest qa_v7.test_dsh_preservation_independent -v          [exit 0]
Ran 4 tests — OK
```

Coincide con `t27` (4/4 en modo normal). Añado la comprobación independiente de §2: 41/41 hashes
pineados correctos y 0 ficheros de DSH tocados en la ventana.

### 3.5 Módulos de la misión (pruebas propias de cada flujo)

```
python -m unittest tests_team_process tests_team_loop                  [exit 0]
Ran 94 tests — OK
```

---

## 4. Diferencial contra baseline: ningún fallo nuevo sin atribuir

Método: copia limpia de `db6ec2e` (`git archive`, sin tocar el árbol de trabajo) y **la misma
invocación** de cada caso, sin `PYTHONUTF8`, en la copia y en el árbol actual.

| Caso | Baseline `db6ec2e` | Árbol actual | Atribución |
| --- | --- | --- | --- |
| `tests_frontend_contract` | FAILED (errors=1), `Ran 0 tests` | FAILED (errors=1), `Ran 0 tests` | **Pre-existente** (cp1252) |
| `tests_generation_pipeline…save_reload…` | FAILED (errors=1) | FAILED (errors=1) | **Pre-existente** (cp1252) |
| `tests_bridge…test_workbook_stale_blocks_export` | FAILED (errors=1) | FAILED (errors=1) | **Pre-existente** (Excel COM) |
| `tests_bridge.HTTPTests.test_bad_host_origin_csrf_cookie_blocked` | FAILED (errors=1) | FAILED (errors=1) | **Pre-existente** + intermitente (coincide con `t19`/O-3) |
| `qa_v6.test_http_multisource` | FAILED (errors=1), `TimeoutError`, 21,65 s | ERROR (mismo `TimeoutError`) | **Pre-existente** (intento de red real) |

Con esto, **los 5 errores de la corrida canónica quedan atribuidos con medición**; no queda ningún
fallo nuevo etiquetado como «no atribuible».

**Observación informativa (H-5):** el hallazgo `F1` que declaró `t27` («con `PYTHONUTF8=1` el
contrato de frontend revela `test_unique_referenced_ids` fallando: `#sandbox-isolation`
referenciado 2 veces en `web/app.js` y ausente en `web/index.html`, 0 de 18 ids `sandbox-*`») **no
lo puedo reproducir**. Medido por mí:

- `python -m unittest tests_frontend_contract -v` con `PYTHONUTF8=1` → **15/15 OK** (incluido
  `test_unique_referenced_ids`), también por descubrimiento canónico.
- `web/index.html` tiene **19** ids `sandbox-*` (no 18), todos únicos; `#sandbox-isolation` está
  **presente** y en `web/app.js` se referencia **una** vez; 0 ids duplicados y **0 referencias
  colgantes**.
- `web/app.js` (mtime 01:26:59) y `web/index.html` (01:26:40) cambiaron **después** del informe de
  `t27`; el `F1` describe un estado anterior del árbol. No es un defecto vigente; sí es una
  inconsistencia del acta.

---

## 5. Agilidad real, medida (no nominal)

Sonda propia, fuera del repo (`%TEMP%\t28_probe.py`): panel de producción `engine.bridge.LocalServer`
sobre `127.0.0.1:59216` (puerto efímero), 24 agentes generados, peticiones HTTP reales con cookie y
CSRF del propio panel.

| Propiedad | Cómo la medí | Resultado exacto |
| --- | --- | --- |
| El panel arranca y expone estado | `GET /api/state` | 200; `team_followups.available=true`; sobre del bucle con claves `available, driver, module, reason, state, tests, wired` |
| **Un tick de follow-ups persigue un compromiso** | `POST /api/channel-publish` («luego subo el informe del puerto») → `POST /api/followups-tick` → `GET /api/state` | publish 200 (1 mensaje); tick 200; `active=1`, `chasing=1`, `tasks=1`, `events=1` (`commitment`), tarea `fu=1` en estado `chasing` |
| …y **vuelve a perseguir al vencer** | reloj de la sonda +3601 s → segundo `tick` | tick 200; `events=2`, último evento **`reminder`**, `reminders_sent=1`; `stats` sigue `active=1, chasing=1` |
| **Sandbox SIN aprobación NO ejecuta** | `POST /api/sandbox-request` con código que **crearía** un fichero marcador → comprobar disco → `POST /api/sandbox-exec` sin aprobar | request 200 (`blocked_reason=human_approval_required`, `decision=require_human_approval`, `gate=write`, `scope_hash` de 64 hex); **marcador ausente**; exec **HTTP 400** («gate 'write': requiere aprobacion humana en dos pasos…, no se ejecuto nada»); `executions=0`; **marcador ausente**; `approved=false` |
| **Control positivo** (la ruta de ejecución funciona) | request → `sandbox-approve` → `sandbox-exec` con el mismo código | approve 200 (`approved=true`); exec 200; **marcador creado** con contenido `EJECUTADO`; `executions=1`, estado `completed`, artefacto firmado `sha256=2fda3d0ddd750555…` |
| **Un ciclo de `team_loop` avanza el proceso** | `TeamProcess(roster de 3, worker inyectado)` + `TeamLoop(process, store={})` → `run(cycles=2)` | `cycles=2`, `stop_reason='cycles_completed'`, `receipts=2`, `checkpoint_written=true`, `step 0 → 3`, `cycle=2`, `cycle_state='completed'`; checkpoint en el store (`cycle=2`, `step=3`); `history()==2` |
| **Exclusividad** | mismo proceso con un `lease` cuyo `acquire` devuelve `acquired=False` | `cycles=0`, `stop_reason='lease_held'`, `receipts=0` (AV-23) |
| **Reanudación** | `process3.import_checkpoint(process.export_checkpoint())` | `resumptions=1`, `step=3`, `cycle=2` (AV-01/AV-02) |

**Límite declarado, no defecto (H-3):** el panel publica
`loop = {available:false, wired:false, reason:"…cada paso necesita un trabajador (worker=) que
ejecute el trabajo del slot. Ese trabajador es el runtime de agentes, que no esta disponible en
esta app (envio a DSH: CAPABILITY_UNAVAILABLE). No se simula: un ciclo sin trabajador real no es
trabajo, es teatro."}`. Es decir: el bucle **no se puede accionar desde la UI** y no hay daemon
24/7; la continuidad existe como módulo verificado + contrato + vectores y como `run(cycles=N)`
desde el llamador. Coincide con lo que declara `t23` y con las restricciones del encargo (sin DSH,
sin proveedores); lo mido con un `worker` inyectado y lo digo.

---

## 6. Evidencia Chromium: qué comprobé y qué revisé del arnés

### 6.1 Evidencia pre-existente (antes de mi corrida)

- 6 PNG (`step_00_app_load` … `step_05_sandbox_block`) + `report.json`; **6/6 digests** del informe
  coinciden con los ficheros reales (bytes y SHA-256), y `screenshot_digests` es coherente con
  `steps[].screenshot`.
- **57 aserciones**, todas `ok`; `uncaught_errors` vacío en los 6 pasos; `ok:true`;
  `failed_steps: []`; `all_steps_present: true`.

### 6.2 Mi corrida independiente

```
python qa_v7/chromium_e2e.py            (desde la carpeta del paquete)      [exit 0]
6/6 pasos · 57 aserciones · 0 con error no capturado · 14,75 s
Chrome/155.0.8059.85 · panel 127.0.0.1:49859 (efímero) · cleanup exit 0
orphans: {checked:true, pids:[], tree_cleared:true, profile_removed:true}
```

Tras la corrida: los 6 digests del informe **fresco** coinciden con los PNG en disco; 5 PNG son
byte-idénticos a los anteriores y `step_01_generate.png` cambia (es una captura nueva del mismo
panel: la evidencia gráfica es volátil por diseño). No queda ningún `chrome.exe` con el perfil
`orgdna-chromium-*` ni ningún directorio de perfil en `%TEMP%`.

### 6.3 ¿Hace trampa el arnés? Revisión del código, no solo de la salida

- **Una aserción falsa aborta el paso y la corrida.** `Recorder.check/equal/contains` lanzan
  `StepFailure` cuando la condición es falsa; `run_step` solo marca `ok=True` si la función
  termina sin excepción. `report['ok']` exige `all_steps_present` (lista exacta de 6 pasos),
  `failed_steps==[]`, `error is None`, `orphans.checked` y `orphans.pids==[]`; `main()` devuelve
  `0` solo si `ok`. Es decir: **no puede «pasar» saltándose un paso** ni con una aserción vacía.
- **No fabrica el DOM.** No hay `innerHTML=`/`textContent=` en el arnés; para interactuar solo
  asigna `.value` y despacha eventos reales (`input`, `change`, `submit`) o llama `el.click()`.
- **Contrasta DOM contra backend por un canal independiente**: `recorder.equal(name, dom, backend)`
  compara lo que pinta la página con `GET /api/state` leído desde Python (`http.client` con cookie
  y CSRF), no con el estado interno del proceso.
- **Sin red externa:** todas las URL del arnés y de `qa_v7/chromium_cdp.py` son `127.0.0.1`
  (panel y endpoint CDP); `chromium_cdp.py` usa solo biblioteca estándar (`socket`, `struct`,
  `hashlib`, `subprocess` para lanzar el navegador).
- **El caso de seguridad se prueba sobre el backend**: en `sandbox_block` exige
  `executions==0`, `approved is False`, `consumed_at is None`, `blocked_reason` de la política y
  que el panel **no** afirme ejecución (`'ejecutad' not in verdict.lower()`).

### 6.4 Fragilidades del arnés (H-4, baja)

- Si **no encuentra navegador**, devuelve **exit 0** con `chromium_unavailable` (un entorno sin
  Chrome «pasaría» el comando de verificación). En esta máquina sí hay Chrome, y `browser_info`
  lo demuestra (`Chrome/155.0.8059.85`, `protocol 1.3`), así que la prueba fue real.
- `steps[].name` y `steps[].seconds` se serializan como `null` (el nombre útil está en
  `steps[].step` y la duración en `steps[].duration_s`).
- `cleanup.killed_tree` incluye el texto de un `taskkill rc=128` («no hay ninguna instancia
  activa»): inofensivo, pero es ruido dentro de la evidencia.

---

## 7. Hallazgos

| ID | Severidad | Hallazgo | Evidencia (medida) | RequiredFix |
| --- | --- | --- | --- | --- |
| **H-1** | baja | **La misión añadió una exención al sello**: `docs/rea/evidence/chromium/` queda fuera de `MANIFIESTO_SHA256.txt` en `verifica_manifiesto.py` y `resella_paquete.py`. Cualquier fichero futuro en esa carpeta no estará sellado | `git diff db6ec2e -- verifica_manifiesto.py resella_paquete.py`; 7 ficheros exentos hoy; sello 377/377 en el resto | Declararlo en el acta (ya está comentado en ambos scripts) y, si se quiere cobertura total, sellar la evidencia de forma inmutable (p. ej. un `EVIDENCIA_SHA256.txt` propio dentro de una ruta sellada) en la tarea de integración |
| **H-2** | **media** | **Re-sello posterior al cierre de la misión**: el manifiesto vigente (mtime 01:27:27, sha256 `3cb13e91…`) no es el que declaró `t27` (`56cd7063…`), y `web/app.js` (01:26:59) e `web/index.html` (01:26:40) cambiaron después de su informe. La evidencia de `t27` corresponde a otro árbol | `verifica_manifiesto.py` (377/377 OK) + `Get-FileHash` del manifiesto + mtimes; los hashes sellados de los dos ficheros web coinciden con los bytes actuales | Registrar el re-sello en el acta con **hash anterior, hash nuevo, motivo y evidencia** (mismo estándar que las enmiendas del baseline DSH); no hace falta tocar código |
| **H-3** | baja (declarado por el producto) | El bucle continuo **no es accionable desde el panel** (`available:false, wired:false`): no hay acción HTTP de ciclo y falta el `worker` real (runtime de agentes → `CAPABILITY_UNAVAILABLE`). No hay daemon 24/7 | `GET /api/state` → `team_followups.loop`; sonda de §5 con `worker` inyectado | Ninguno si el operador acepta el límite (está declarado en la UI y en el contrato). Si quiere continuidad desde la app: cablear un `worker` real o un `run(cycles=N)` explícito con recibo |
| **H-4** | baja | Fragilidades del arnés Chromium: exit 0 sin navegador; `steps[].name`/`seconds` nulos; ruido de `taskkill rc=128` | §6.4 (código y salida) | Endurecer en la tarea de integración: exit ≠ 0 o `SKIP` declarado cuando falte navegador; rellenar `name`/`seconds` |
| **H-5** | informativa | El hallazgo `F1` de `t27` **no es reproducible**: `tests_frontend_contract` da 15/15 OK con UTF-8; hay 19 ids `sandbox-*`, `#sandbox-isolation` presente y 1 referencia | §4 (medición propia) | Corregir el acta: `F1` describe un estado anterior del árbol; no hay defecto vigente |
| **H-6** | informativa | `test_bad_host_origin_csrf_cookie_blocked` es **intermitente** y falla también en `db6ec2e`; explica el 5.º error que yo obtengo frente a los 4 de `t27` | §4 (reproducido en baseline, con y sin UTF-8) | Ninguno (ya investigado como O-3/`t19`); no mover la frontera del test sin medición |

---

## 8. Lo que NO queda verificado por diseño (fail-honest)

1. **Proveedores vivos.** No se llamó a ningún proveedor y esta verificación no lo intentó: el
   encargo lo prohíbe. Todo lo relativo a disponibilidad de modelos es declarativo.
2. **24/7 y demonio.** No existe servicio ni temporizador: la continuidad es `run(cycles=N)` desde
   el llamador (§5, H-3). No verifiqué nada que no exista.
3. **DSH en ejecución.** No ejecuté DSH. Solo comprobé bytes pineados (41/41), las anclas de JS y
   dispatch, y que ningún fichero de `C:\Users\HFRC\.dsh-vscode` cambió en la ventana.
4. **Excel COM.** `test_workbook_stale_blocks_export` no puede pasar en este host (sin Excel); lo
   clasifico como entorno porque falla igual en baseline.
5. **Red externa.** No se probó ninguna conexión externa (prohibido); los tests que la intentan
   fallan por timeout, que es el comportamiento esperado en un host sin salida.
6. **«Trabajo real» de cada slot del bucle.** El `worker` que inyecté es un doble de prueba: prueba
   que el bucle avanza, sella checkpoint y reanuda, **no** que un agente haga trabajo real.
7. **Rendimiento.** Los tiempos de pared están contaminados por una suspensión del host
   (01:39:20 → 07:04:42). Solo doy por bueno el tiempo medido por `unittest` en la corrida
   canónica: **643,519 s**.
8. **Comparación con el árbol exacto que selló `t27`.** El árbol cambió después de su informe
   (H-2); no puedo reconstruir ese estado sin los bytes, y no los tengo.

---

## 9. Efectos de esta verificación sobre el repositorio

- **Escrito por mí:** `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/REVISION_AGILIDAD_V1.md` (este
  informe, 24 797 B). Nada más dentro del repo.
- **Regenerado por un comando del contrato** (`python qa_v7/chromium_e2e.py`): los 7 ficheros de
  `docs/rea/evidence/chromium/` (6 PNG + `report.json`). Esa carpeta está declarada exenta del
  sello (H-1), por lo que los bytes sellados no cambian: lo recomprobé **después** de la corrida
  (377/377 coincidentes, 0 divergentes, 0 faltantes).
- **Estado local bajo `data/projects/`:** las corridas de la suite y mis sondas ejercitaron el
  panel y su almacén local, que escribió proyectos en `data/` (hoy **445** ficheros; 48 con mtime
  de las últimas 3 h). Es la ruta declarada exenta (`data/` = estado que el producto reescribe), y
  no altera ningún byte sellado.
- **Este informe deja 1 sobrante en el sello** hasta que la integración vuelva a sellar (§3.1).
  Es el guard funcionando: un fichero nuevo no declarado debe romper el sello.
- **Fuera del repo:** `%TEMP%\t28_probe.py`, `%TEMP%\t28_base*` (copia del baseline), `%TEMP%\t28_*`
  (salidas de las corridas). Nada de eso entra en el paquete.
- **No ejecuté** `resella_paquete.py`, no toqué `engine/`, `web/`, `qa_v7/dsh_baseline.json` ni
  `MANIFIESTO_SHA256.txt`, y no modifiqué DSH.

---

## 10. Comandos ejecutados (reproducibles)

| # | Comando | Resultado |
| --- | --- | --- |
| 1 | `git diff db6ec2e -- <cada guard>` | 5 guards byte-idénticos; 3 cambios de encoding; 1 pin re-basado; exención del sello |
| 2 | `python verifica_manifiesto.py` | 377/377, 0 divergentes/faltantes/sobrantes, exit 0 |
| 3 | `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'test*.py'` | 1517 pruebas, 643,519 s, 0 fallos, 5 errores, 1 skip, exit 1 |
| 4 | ídem con `PYTHONUTF8=1` (control) | 1532 pruebas, 0 fallos, 3 errores, 1 skip, exit 1 |
| 5 | `python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py` | valid=true, 2201 checks, 378 ficheros, exit 0 |
| 6 | `python -m unittest qa_v7.test_dsh_preservation_independent -v` | 4/4 OK, exit 0 |
| 7 | `python -m unittest tests_team_process tests_team_loop` | 94 pruebas OK, exit 0 |
| 8 | `python qa_v7/chromium_e2e.py` | 6/6 pasos, 57 aserciones, 14,75 s, exit 0 |
| 9 | Sonda propia `%TEMP%\t28_probe.py` (panel + HTTP + bucle + sandbox) | §5 completo |
| 10 | Control positivo del sandbox (request→approve→exec) | marcador `EJECUTADO`, 1 ejecución firmada |
| 11 | `git archive db6ec2e` → `%TEMP%\t28_base` + 5 casos de atribución | los 5 reproducen el fallo en baseline |
| 12 | Recuento de enmiendas del baseline DSH y hashes pineados | 8 enmiendas completas; 41/41 ficheros |
| 13 | Barrido de mtimes de `C:\Users\HFRC\.dsh-vscode` en la ventana | 0 ficheros tocados |
| 14 | `python verifica_manifiesto.py` **después** de las corridas y del informe | 377/377 coincidentes, 0 divergentes, 0 faltantes; 1 sobrante = este informe (esperado hasta el re-sello de integración) |

*Fin del informe.*
