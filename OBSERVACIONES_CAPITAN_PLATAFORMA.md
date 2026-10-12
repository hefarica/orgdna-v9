# Observaciones del capitán — ola de plataforma `orgdna-plataforma-v9`

Registro de hallazgos que **no se incorporan silenciosamente** al alcance aprobado.
Artefacto del capitán, fuera del paquete entregado (no altera `MANIFIESTO_SHA256.txt`).

---

## O-1 · La aprobación de un TaskSpec no queda ligada a un recibo

**Origen:** informe de `nucleo` sobre `t2` (I1), punto AUTONOMIA: *«Aprobación por tarea (True | lista de task_id | {task_id: True}); no concede permisos, **no se serializa y no cambia el hash**»*.

**Descripción.** El Task Graph Engine exige `approved=True` para construir un grafo con niveles de escritura (`prepare`, `execute-approved`), y eso está verificado y probado. Pero la aprobación es una **puerta transitoria en tiempo de construcción**: no forma parte del contenido serializado ni del `compute_graph_sha256`. Consecuencia: del hash del grafo **no se puede deducir que fue aprobado**, ni quién lo aprobó, ni cuándo.

**Evidencia.** `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/engine/task_graph.py` (757 líneas, 48 pruebas OK); hash determinista fijado en `c0690c65c91bc5b55be60136f3f4f9b7453eb04708794286e0a54027998d8b53` sobre un grafo conocido.

**Impacto.** Medio y diferido. No rompe nada hoy. Sí debilita la cadena de auditoría que el propio encargo exige («cada acción tenga: objetivo, evidencia, alcance, permiso, costo, **receipt**, prueba y reversión»): sin un recibo ligado al hash del grafo, la aprobación no es reconstruible desde el artefacto. Un lector futuro podría además **sobreafirmar** que un hash aprobado prueba aprobación, cuando no lo hace.

**Alternativa sin cambio.** El hash identifica **contenido**, no consentimiento. Es una separación defendible y ya está implementada. Dejar constancia explícita de que la aprobación es un evento, no un campo, evita la sobreafirmación.

**Trabajo relacionado ya existente.** R0 entregó `docs/plataforma/receipt-extension.schema.json` (huella `5f1ae738ad11ebc93d08bb2d682c82842939b0d14f27149cd5…`) precisamente como extensión aditiva de recibo. `t6` (I5) exige recibo con hash por artefacto; `t4`/`t5` producen las decisiones de aprobación. **Pero ninguna tarea del DAG aprobado tiene asignado explícitamente el enlace «aprobación de TaskGraph → recibo con hash del grafo + aprobador declarativo + sello de tiempo».**

**RESUELTA — AUTORIZADA POR EL OPERADOR** como reparación aditiva de auditabilidad `O1-APPROVAL-RECEIPT-LINK-01`, materializada como tarea `t13` (implementación, `nucleo`).

**Alcance autorizado (6 elementos aditivos):** schema de `ApprovalReceipt`, emisión explícita del recibo al aprobar y al denegar, enlace `graph_sha256 → approval receipt`, verificador de consistencia `can_execute()`, pruebas positivas y negativas con 14 falsificadores, y documentación de semántica.

**Regla de oro impuesta al contrato:** `TaskGraphHash ≠ ProofOfApproval`, pero `ApprovalReceipt.graph_sha256 == compute_graph_sha256(TaskGraph)`.

**Prohibiciones explícitas verificables:** no se modifica `compute_graph_sha256()`, ni el `TaskGraph` serializado, ni `MANIFIESTO_SHA256.txt`, ni permisos efectivos, ni defaults de autonomía, ni la política de persistencia efímera, ni la identidad/autenticación de usuario. Se comprueba con dos pruebas: el fixture dorado `c0690c65…` sigue intacto y el manifiesto conserva `f7dc6586…` al cerrar la tarea.

**LÍMITE QUE APLICO Y DECLARO.** El operador describió además que el recibo debe sobrevivir dentro de proyecto guardado, bundle exportado, diagnóstico descargado, resultado de generación y artefacto de aprobación, con el modelo `project/{task_graph.json, approval_receipts.jsonl, generation_diagnostics.json, artifacts/}` y dos reglas (persistencia opcional y explícita; la ausencia de recibo **no** es aprobación).

En `t13` se entrega eso como **semántica y contrato de incrustación** (payload canónico + round-trip + las dos reglas probadas), **no como cableado físico**. El cableado tocaría `engine/export_artifacts.py`, `engine/bundle.py` y `engine/bridge.py`, y añadir un documento nuevo al bundle altera el conjunto exacto de archivos que exige `engine/bundle.py:787`, es decir el formato de exportación congelado y la validación de 1620 comprobaciones. Eso excede lo autorizado y colisionaría con `t9`, que ya tiene `bridge.py` y `bundle.py` en su alcance.

**Decisión requerida (paso 2, NO autorizado, NO ejecutado):** ¿se autoriza una tarea separada de integración de persistencia que cablee el recibo en proyecto, bundle y diagnóstico, asumiendo el cambio de formato de exportación (versión nueva, lectura de la anterior) y la actualización del manifiesto?


---

## Decisiones pendientes que requieren al operador

| Id | Asunto | Estado | Default seguro aplicado |
|---|---|---|---|
| A-1 | Almacén durable de recibos en `data/` | **Pendiente** | No se crea: recibos en memoria y persistidos sólo al guardar proyecto/descargar diagnóstico |
| D-R0-5 | Identidad del aprobador humano | **Pendiente** | Rol declarativo, sin datos de autenticación. Una app local offline no puede autenticar al aprobador |
| D-R0-3 | Persistencia de planos de memoria | Ratificada con default seguro | Ejecución efímera; personal nunca exportado; sin superficies de disco nuevas |
| D-R0-4 | Techo de autonomía por defecto | Ratificada con default seguro | `observe`; no inferible del objetivo declarado |
| D-R0-2 | Distribución de contratos en el ZIP V9 | **Resuelta por contrato** | Ampliada la descripción de `t9` con la lista literal de archivos a integrar |

---

## Verificaciones del capitán (independientes de los informes de los miembros)

### R0 (`t1`, contratos) — verificado
- 8 entregables existen; tamaños reales coinciden con los publicados.
- 6/6 schemas parsean; `prohibited_fields` idéntico al conjunto de 13 de `engine/project_store.py:19`; `inert_by_default=True`; `version_field` presente en los 6.
- **6/6 huellas SHA-256 publicadas en §8.2 coinciden** con el archivo real.
- `MANIFIESTO_SHA256.txt` = `f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96`, 25.664 B, 268 líneas (intacto).

### I1 (`t2`, nucleo) — verificado
- 48 pruebas OK en 0,277 s (contrato exigía ≥12).
- Análisis AST independiente: imports = `__future__`, `collections`, `dataclasses`, `hashlib`, `json`, `math`, `re` + `project_store` intra-paquete con la convención dual `__package__` (líneas 57/59). **Cero contenedores mutables de módulo.**
- Sin `open(`, `socket`, `urllib`, `subprocess`, `os.system`, `eval`, `exec`.
- **Falso positivo propio, declarado:** mi escáner marcó `requests`; es vocabulario del presupuesto (`budget.requests`), no la librería HTTP. El listado de imports lo confirma.
- Manifiesto sin cambios y `validate_imports_portable.py` con `valid=true`, 1620 comprobaciones, 269 archivos.

**Nota de vigencia:** tras RV1, `engine/task_graph.py` fue reescrito por `t11` (757 → 861 → 692 líneas durante la sesión). El recuento de 48 pruebas y el hash `c0690c65…` corresponden al cierre original de I1, **no** al estado actual. La verificación definitiva es de `t12`.

---

## O-1b · Limitaciones declaradas por el implementador de I1 (sin cambio de código)

`nucleo` declaró, y no corrigió por no estar en su contrato, cuatro precisiones que un lector futuro **no debe sobreinterpretar**. Se registran aquí para que la documentación de entrega no las presente como garantías:

| # | Limitación declarada | Por qué importa |
|---|---|---|
| O-1b.1 | El hash **no atestigua la aprobación** | Ya cubierta como O-1. Del hash no se deduce que el grafo fue aprobado |
| O-1b.2 | El flag `approved` **no está ligado al nivel** de autonomía | `approved=True` aprueba por tarea, pero no distingue `prepare` de `execute-approved`; una aprobación amplia es una aprobación amplia |
| O-1b.3 | El hash es sobre la **declaración**, no sobre el DAG resultante | El hash cubre la lista canónica de declaraciones; no cubre por sí mismo el orden topológico ni la estructura derivada |
| O-1b.4 | Normalización `0` / `0.0` | Dos declaraciones numéricamente iguales pueden diferir en su forma JSON; conviene saber si comparten hash |

**Estado:** ninguna bloquea ni cambia el alcance aprobado. `t12` (re-revisión) y `t10` (verificación) deben confirmar que siguen siendo ciertas tras la reparación, o declararlas resueltas. **No se ha autorizado ningún cambio de código por ellas.**

---

## O-2 · Dos «defectos nuevos» que resultaron ser artefactos de medición

**Origen:** mi propia corrida diferencial completa sobre el árbol vivo (533 pruebas, 386 s, `regresion_con_plataforma.txt`) produjo **2 failures + 9 errores** frente a la línea base de **1 failure + 8 errores**. Los dos no presentes en la línea base:

| Defecto | Síntoma medido | Atribución tras reejecución aislada |
|---|---|---|
| `tests_bridge.HTTPTests.test_body_bound` (ERROR) | `http.client` → `_read_status` → reset de conexión al enviar 140 KB esperando 413 (`tests_bridge.py:232`) | **Flakiness.** Ver O-3 |
| `tests_model_catalog_scopes.…test_exact_api_id_survives…` (FAIL) | `Generation did not finish`: el job estaba en `status=validating`, `stage=building_exports`, `progress=90` al expirar la espera | **Timeout por contención.** En aislamiento: `Ran 7 tests — OK`. La canalización estaba avanzando, no rota |

**Prueba de no-regresión por bytes:** `MANIFIESTO_SHA256.txt` confirma `INTACTO` para `engine/bridge.py`, `engine/generation_pipeline.py`, `tests_bridge.py`, `tests_model_catalog_scopes.py` y `tests_generation_pipeline.py`. Mismo código, distinto resultado ⇒ contenido ambiental, no regresión.

**Error mío que corrijo:** mi corrida se ejecutó **sobre el árbol vivo, con escritores concurrentes** (`t11` reescribiendo `engine/task_graph.py`) y compitiendo con las suites de otros miembros (386 s frente a 168 s de la línea base: 2,3× más lenta). Esa medición **no es concluyente**. La atribución exigida a V1 es, por eso, con árbol congelado o copia temporal.

## O-3 · `tests_bridge.HTTPTests` es una clase de pruebas inestable en este host

Dos corridas **aisladas y consecutivas** del mismo módulo, sin ningún otro escritor:

| Corrida | Duración | Errores |
|---|---|---|
| 1.ª | 26,76 s | `test_workbook_stale_blocks_export` (Causa B) + `test_body_bound` |
| 2.ª | 19,28 s | `test_workbook_stale_blocks_export` (Causa B) + `test_bad_host_origin_csrf_cookie_blocked` |

**Falla un test distinto cada vez.** La clase abre sockets reales y prueba cuerpos de 140 KB; bajo carga, miembros distintos de la clase fallan de forma no determinista. Es un **defecto de robustez de la suite de pruebas, no del producto**, y es relevante para V1: un veredicto diferencial que lo ignore puede declarar «fallo nuevo» falso con la misma facilidad con que puede declarar «sin fallos nuevos» falso si el test pasa por casualidad.

**Decisión requerida (no autorizada, no ejecutada):** ¿se autoriza, en una futura ola P2, hacer determinista `tests_bridge.HTTPTests` (puerto efímero verificado, servidor con espera explícita de cierre, reintento acotado sólo en la prueba)?

**Clasificación corregida por indicación del operador, y adoptada:** esto es una **inestabilidad observada con causa raíz NO atribuida**, y debe tratarse como **investigación específica y separada**. **No se imputa a concurrencia general.** Son dos fenómenos distintos: el claim de contención (O-7) y esta inestabilidad. Protocolo de investigación propuesto para O-3: puertos reproducibles o 0, reintentos desactivados inicialmente, logs de bind/accept/respond, corrida de **un test** en lugar del módulo entero, y comparación de orden aleatorio frente a orden fijo.

---

## O-7 · Instancias solapadas de la suite: mecanismo plausible, reproducción PARCIAL

`gobernanza`, al cerrar `t5`, reportó un hallazgo preexistente y no atribuible a su trabajo: `test_success_receipts_survive_save_load_and_diagnostic` falla de forma determinista cuando **2–3 procesos ejecutan la suite completa simultáneamente sobre el mismo árbol** (contención sobre el almacén de fixture), reproducido en copia prístina sin sus archivos, y 19/19 verde en 5 corridas secuenciales.

**Mi intento de reproducción, y su resultado honesto:** lancé **dos procesos en paralelo del mismo módulo** (`tests_v8_models_receipts.py`) sobre el mismo árbol. **Ambos devolvieron OK.** No reproduje el fallo.

**Lo que esto significa, sin exagerar en ninguna dirección:** no refuta el hallazgo, porque mis condiciones fueron más suaves que las descritas (un módulo × 2 procesos, frente a la suite completa × 2–3 procesos). Sí acota el mecanismo: la contención **no** se dispara con dos instancias de un módulo aislado. Queda como **plausible y no confirmado por el capitán**.

**Corroboración independiente de que existe una capa ambiental:** mi propia medición de `tests_bridge.HTTPTests` (O-3) mostró dos corridas aisladas consecutivas fallando **tests distintos**, con `bridge.py` byte-idéntico al manifiesto. Eso es flakiness medida, con independencia de la causa exacta.

**Recomendación operativa (no autorizada, no ejecutada):** serializar las verificaciones mientras haya varios flujos activos. Con siete miembros capaces de correr suites a la vez, una medición paralela sobre el mismo árbol no es evidencia fiable — ni para declarar un fallo ni para declararlo ausente.

## O-8 · El conjunto de plataforma está verde: 310/310

Medido por el capitán al cerrar `t5`, `t6` y `t12`, en una sola corrida:

| Comprobación | Resultado |
|---|---|
| `tests_platform_*.py` (I1 62 + I2 53 + I3 41 + I4 50 + I5 70 + I6 34) | **310 OK** |
| `docs/PLATAFORMA_REVISION_RV1.md` | 31.484 B · `b72d8f8f…` (coincide con lo declarado) |
| `docs/PLATAFORMA_REVISION_RV2.md` | 22.866 B · `67b54746…` (coincide con lo declarado) |
| Manifiesto · validador | `f7dc6586…` intacto · `valid=true`, 1620 comprobaciones |

`t12` (RV2) cerró con veredicto **pass** sobre la reparación de I1: 0 escapes en 66.048 grafos exhaustivos de 3–4 nodos (antes 550), y la prueba de falsificación de la propia prueba —reintroducir la línea antigua hace fallar la suite nueva con 16 errores— demuestra que la regresión no es vacua. Ese es exactamente el estándar que el programa exige.

## O-9 · Nueva observación del revisor: las funciones canónicas aceptan declaraciones crudas sin normalizar

`t12` documenta (O-RV2-4) que las funciones canónicas de `task_graph` aceptan declaraciones crudas **sin normalizar**, de modo que hay que construir con `build_taskspec`/`build_graph` antes de hashear. Es coherente con el diseño declarado —`canonical_task_list` se documenta como canonicalizador, no como validador— pero es una trampa para un consumidor futuro: hashear una declaración cruda puede dar un hash que no corresponde a ningún grafo construido.

**No se autoriza cambio de código.** Se registra para que `t9` y `t10` lo declaren y para que la documentación de entrega no presente el hash de una declaración cruda como hash de un grafo válido.

---

## O-10 · Bloque canónico del invariante de aprobación — publicado VERBATIM por el capitán

**Defecto del capitán que esto corrige.** La aceptación de `t13` exigía que `docs/PLATAFORMA_APROBACION_V1.md` contuviera «LITERALMENTE el bloque INVARIANTE DE APROBACIÓN aportado por el operador», pero **yo nunca publiqué ese bloque en ningún artefacto accesible al equipo**. El miembro hizo lo único honesto posible: transcribió el texto disponible —el de la descripción de `t13`, escrito por mí— y dejó constancia de su procedencia real. El documento quedó etiquetado como «(bloque literal del operador)», lo cual es **inexacto**: el bloque del operador es el siguiente, y es este el que debe aparecer literal.

```text
INVARIANTE DE APROBACIÓN

compute_graph_sha256 identifica el contenido canónico de un TaskGraph.
No acredita aprobación, identidad humana, autorización de herramientas,
presupuesto, consentimiento vigente ni permiso de ejecución.

Una aprobación solo es válida si existe un ApprovalReceipt vigente cuyo
graph_sha256, policy_hash, scope y nivel de autonomía coinciden con el
TaskGraph y la tarea que se pretende ejecutar.

En modo local/offline, approver.role es declarativo y
approver.authenticated=false. La plataforma no debe presentar esa
declaración como una identidad autenticada.
```

**Fuente de autoridad:** mensaje del operador que autoriza `O1-APPROVAL-RECEIPT-LINK-01`, sección «Redacción que debe entrar al documento». Este registro pasa a ser la fuente canónica para la alineación.

## O-11 · Corrección de un método de medición propio, declarada

Durante toda la sesión reporté recuentos de líneas obtenidos con `Get-Content | Measure-Object -Line`. **Ese método es defectuoso en este entorno y ha producido cifras falsas.** Contrastado contra `len(src.splitlines())`:

| Archivo | `Measure-Object -Line` (lo que reporté) | `splitlines()` (correcto) | Afirmado por el miembro |
|---|---|---|---|
| `engine/approval_receipt.py` | 836 | **1006** | 1006 ✔ |
| `tests_platform_approval_receipt.py` | 663 | **743** | 743 ✔ |
| `docs/PLATAFORMA_APROBACION_V1.md` | 188 | **245** | 245 ✔ |
| `engine/task_graph.py` | 697 | **866** | 866 ✔ |

**Consecuencias que asumo:**
1. Los recuentos que reporté al operador para `task_graph.py` (757 → 861 → 692) eran poco fiables. El cambio de contenido **sí fue real** —el hash pasó de `be7dc89b…` a `369a734f…` mientras `t11` reparaba—, pero la trayectoria de líneas que presenté como prueba de esa reescritura no lo era.
2. La conclusión de que mi corrida diferencial estaba contaminada **se mantiene**, porque se apoya en el cambio de hash y en la contención medida, no en los recuentos.
3. Los hashes siempre fueron correctos (coinciden con lo declarado por los miembros), así que ninguna verificación de identidad de archivo queda invalidada. Solo el conteo de líneas estaba mal.
4. **Regla adoptada:** a partir de aquí, cualquier recuento de líneas se mide con `len(src.splitlines())` en Python, nunca con `Measure-Object`.

---

## O-12 · Política de medición adoptada (aportada por el operador)

Esta sesión produjo **tres mediciones no comparables del mismo árbol** (528, 531 y 533 pruebas, con recuentos de fallo distintos) porque cada una corrió con distinto paralelismo, distinto subconjunto y el árbol cambiando. El operador propuso una regla de huella, y la adopto como obligatoria:

```text
measurement_epoch = timestamp + runner + árbol_por_digest + PYTHONUTF8 explícito
                  + paralelismo + hash de la captura de stdout
```

**Dos mediciones sin huella comparable no se comparan entre sí.**

| Tipo de medición | Protocolo obligatorio |
|---|---|
| Defectos de código | Serializada · `PYTHONUTF8` anotado · árbol congelado por digest · resultados **por clase y por test**, no sólo el resumen |
| Concurrencia | Escalar deliberadamente los mismos procesos que el claim · aislamiento de trabajos · sin lectura/escritura compartida de artefactos · registrar orden y timing de cada fallo |
| `HTTPTests` | Puertos reproducibles o 0 · reintentos desactivados inicialmente · logs de bind/accept/respond · un test, no el módulo entero · orden aleatorio vs fijo |

**Adoptado en el contrato de `t10`** (tercera revisión, registrada): la huella de medición, los resultados por test, la corrida en ambos modos de encoding y la separación explícita entre contención e inestabilidad de `HTTPTests` son ahora criterios de aceptación, no recomendaciones.

## O-13 · Línea base operativa, cifra definitiva de este corte

```text
Defectos baseline reportados inicialmente:   9
Defectos deterministas confirmados:          6
Casos condicionados por encoding:            3
Mitigación operativa medida:                 PYTHONUTF8=1
Reparación definitiva:                       pendiente en P2
```

**Matiz que el operador aporta y que suscribo:** `PYTHONUTF8=1` **no cierra el defecto**; demuestra que el paquete no debería depender del encoding predeterminado del entorno. La reparación definitiva es forzar `utf-8` explícito en lectura/escritura donde corresponda, **con pruebas que se ejecuten explícitamente bajo ambos modos** — no basta con que pasen en el modo cómodo.

## O-14 · Huella canónica de medición — formato ampliado del operador

Sustituye al esquema resumido de O-12 como formato de referencia. Cualquier afirmación de defecto debe poder acompañarse de esto:

```json
{
  "measurement": {
    "runner_id": "…",
    "host": "windows|wsl|linux|ci",
    "cwd_digest": "sha256",
    "python_utf8": true,
    "thread_count": 1,
    "suite_scope": "module|full",
    "module": "tests_dsh_launcher.py",
    "git_state": "…",
    "file_digests": {"engine/…": "…"},
    "environment_forwarded": ["PYTHONUTF8", "TERM", "CI"],
    "started_at": "…",
    "finished_at": "…"
  }
}
```

**Regla:** si dos corridas difieren en esta huella, sus resultados son **evidencia contextual, no refutación automática**. El contrato de `t10` ya obliga a la huella, a resultados por test y a declarar `PYTHONUTF8`; este formato es el de referencia para cumplirlo.

## O-15 · P2 autorizado como DIAGNÓSTICO, no como reparación — y por qué se encadenó a `t10`

El operador autorizó cuatro paquetes P2 estrechos, con los defectos por separado y **sin absorber deuda histórica dentro de la ola de plataforma**. Materializados como cinco tareas de diagnóstico, todas **dependientes de `t10`**:

| Tarea | Paquete | Dueño | Entregable (fuera del paquete entregado) |
|---|---|---|---|
| `t15` | P2-A encoding | `evidencia` | `P2A_ENCODING_INFORME.md` |
| `t16` | P2-B Excel/COM en Windows | `fiabilidad` | `P2B_EXCEL_INFORME.md` |
| `t17` | P2-C respaldo del relanzador DSH | `plataforma` | `P2C_LAUNCHER_INFORME.md` |
| `t18` | P2-D puerto 3080 | `contratos` | `P2D_PUERTO_INFORME.md` |
| `t19` | P2-E / O-3 inestabilidad de `HTTPTests` | `verificador` | `P2E_HTTPTESTS_INFORME.md` |

**Dos decisiones de diseño que aplico y declaro:**

1. **Dependencia de `t10`, no arranque inmediato.** El operador pidió «P2 pendiente hasta cerrar t13/t9/t10». Encadenarlas a `t10` garantiza además algo que casi me costó caro con `t14`: una reparación P2 que escriba dentro del paquete **desplazaría los hashes que `t9` está calculando ahora**, dejando el manifiesto obsoleto. El diagnóstico no debe competir con el empaquetado.
2. **`inScope` = un solo informe en la raíz del workspace; `outOfScope` = todo `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`.** El árbol entregado es de **sólo lectura** para las cinco tareas. Así el diagnóstico es compatible con `t9`/`t10` aunque llegara a solaparse en el tiempo, y la deuda V8 no se cuela en el ZIP V9.

**Sin autorización en esta ronda:** ejecución física o desbloqueo de scripts, apertura de Excel, reinicio del relanzador DSH, y cualquier edición dentro del paquete por motivos P2. Cada reparación se decide después, **por defecto y con su propia medición**.

## O-16 · Congelación vigente hasta `t10`, verificada contra los contratos

El operador fijó siete congelaciones. **Ninguna es una promesa verbal: todas están ya escritas en un contrato con `outOfScope` o en un criterio de aceptación.**

| Congelación | Dónde está escrita |
|---|---|
| No desbloquear scripts descargados | `t16` (P2-B): prohibido «desbloquear archivos del paquete» |
| No abrir Excel como acción de reparación | `t16`: prohibido «abrir Excel»; la ejecución física exige consentimiento separado |
| No iniciar ni reiniciar DSH | `t17` (P2-C): prohibido «reiniciar ni relanzar nada del entorno del usuario» |
| No cambiar el puerto 3080 | `t18` (P2-D): sólo informe; la decisión es del operador |
| No editar `bridge.py`, `bundle.py` ni `export_artifacts.py` por persistencia física del recibo | `engine/export_artifacts.py` está en `outOfScope` de `t9`; la persistencia física es el paso 2 **no autorizado** (O-1) |
| No modificar tests heredados para verde artificial | `t9` criterio 6 y criterios 11 (pins en verde **sin modificar**) |
| No escribir dentro del árbol entregado por motivos P2 | `t15`–`t19`: `outOfScope` = `EQUIPO_ENTERPRISE_24_COUNCIL_ADN` completo |

## O-17 · Línea base: los recuentos antiguos quedan marcados como históricos

Por indicación del operador, que suscribo: **todo recuento obtenido con `Measure-Object -Line` queda clasificado como histórico y NO confiable.** Los hashes no se ven afectados, porque nunca dependieron de ese método. La formulación canónica de la línea base es la de O-13, y su lectura correcta es:

```text
PYTHONUTF8=1 mitiga el entorno.
No repara el código.
La corrección final exige encoding='utf-8' explícito
en cada lectura/escritura relevante,
más pruebas ejecutadas bajo ambos modos.
```

## O-18 · O-9 exigido en la documentación de cierre

El operador exige que el acta de entrega declare O-9 —que no se debe hashear una declaración cruda y presentarla como TaskGraph válido, sino construir o canonicalizar antes con `build_taskspec`/`build_graph`— como **limitación vigente, no como algo corregido**. Incorporado como criterio 14 del contrato de `t9`, que es quien escribe `docs/PLATAFORMA_ENTREGA_V9.md` y está en ejecución: era la única ventana donde podía aterrizar sin crear una tarea nueva ni reabrir el paquete.

---

## O-19 · `f7dc6586…` es referencia HISTÓRICA, no hash final de la entrega

Corrección de lectura que el operador señala y que suscribo, porque un lector futuro podría equivocarse:

```text
f7dc6586be40bf69d78abfc767f98a2e5778cac54dec6d2fe81c3ba0eb7dcd96
  = huella del manifiesto V8 al cierre de R0…t13, con 268 entradas y 269 archivos.
  = PRUEBA DE NO-INTRUSIÓN de esas tareas, no estado final exigible.
```

**`t9` regenera legítimamente el manifiesto**: añade los 11 módulos de plataforma, las pruebas `tests_platform_*`, los contratos de R0, los informes de revisión y el acta. Por tanto la huella **cambiará** y el `file_count` **crecerá**. Exigir `f7dc6586…` como hash final sería exigir que la integración no ocurriera.

**Lo que sí debe verificarse, y es lo que ya exige el contrato de `t10`:** que la huella y el `file_count` **declarados en `docs/PLATAFORMA_ENTREGA_V9.md`** coincidan con los bytes reales del árbol final. La referencia histórica sirve para comparar qué entró, no para congelar el resultado.

## O-20 · Distinciones que deben permanecer en el cierre

Fijadas por el operador para que el acta final no las difumine:

```text
Implementación lógica del recibo:        cerrada.
Persistencia física del recibo:          no autorizada.
Limitación O-9:                          documentada, no reparada.
Política v2:                             extensión aditiva (v1 intacto).
Defectos V8:                             separados de la ola V9.
Verificación del capitán:                directa, ejecutada en este host.
Verificación del asistente del operador: no ejecutada sobre ese paquete.
```

**Instrucción de continuidad recibida:** continuar con el contrato vigente de `t9`, sin sexta revisión, sin criterios nuevos y sin cambios de alcance. El siguiente hito es el cierre de `t9` y la verificación independiente de `t10`; P2 va después, sin contaminar la entrega ni su atribución causal. **Acatada: no se ha añadido ninguna revisión más.**

---

## O-21 · `t9` cerrada — verificación del capitán y disciplina de hashes en el cierre

### Lo que verifiqué, con números

| Comprobación | Declarado por `t9` | Medido por mí | Veredicto |
|---|---|---|---|
| `validate_imports_portable.py` | valid=true, 1791 checks, 301 archivos | idéntico | ✅ |
| `tests_platform_*.py` | 382/382 OK | **382 OK** | ✅ |
| `MANIFIESTO_SHA256.txt` | `3f74e6269be4de5b…` , 300 entradas | idéntico | ✅ |
| `RUNTIME_ALLOWLIST` | 205 → 237, literal | **237 entradas, sin globs** | ✅ |
| `engine/bundle.py` | `323d1eaf…` | idéntico | ✅ |
| `engine/bridge.py` | `70ab7f3d…` | idéntico | ✅ |
| `docs/plataforma/policy.schema.json` (v1) | intacto en `c6026c70…` | **`c6026c70…`** | ✅ **la vía aditiva funcionó** |
| `docs/plataforma/policy.v2.schema.json` (v2) | nuevo `b273d096…` | idéntico | ✅ |
| `PLATAFORMA_CONTRATOS_V1.md` §8.2 | dos filas (v1 + v2) | líneas 292 y 296, ambas presentes | ✅ |
| `PLATAFORMA_APROBACION_V1.md` | `4773dd89…` | idéntico | ✅ |
| Acta §9.2 (F-T9-2) | declarada | líneas 276/278/321 | ✅ |

**Cadena del manifiesto: 300 entradas, 0 enmascaradas, 0 discrepancias.** El manifiesto entregado es **completo y sin máscaras**, y cada entrada coincide con los bytes reales. El enmascaramiento fue un estado intermedio para romper la circularidad (acta → huella → catálogo → acta), no el estado final.

**El validador es de sólo lectura, medido:** ejecuté `validate_imports_portable.py` comparando hashes, tamaños y mtimes antes y después — idénticos. **Mi verificación no alteró la entrega.**

### F-T9-1 — CONFIRMADO, y es una declaración obsoleta, no una manipulación

| | Declarado por `t7` | Bytes reales |
|---|---|---|
| `tests_platform_reliability_connectors.py` | 914 líneas · `ed42d004…` | **912 líneas · `51a6c845…` · 54.030 B** |
| `engine/reliability.py` | `a183f058…` | `a183f058…` ✅ |
| `engine/connector_gateway.py` | `5918369e…` | `5918369e…` ✅ |

**Los dos módulos coinciden exactamente; sólo el archivo de pruebas difiere.** Los tres mtimes caen en la misma ventana de escritura (12:28:30 / 12:30:02 / 12:31:10), anterior al inicio de `t9`, y las 34 pruebas del módulo siguen en verde. Conclusión: **`t7` declaró antes de su última edición**; nadie tocó el archivo después. Impacto **bajo para el producto** (código y pruebas intactos) y **medio para la auditabilidad** (un hash declarado que nunca correspondió a los bytes entregados es exactamente lo que este programa existe para impedir). **Ningún artefacto entregado porta el hash equivocado**, así que no requiere reparación dentro del paquete.

### Tres hashes de cierre obsoletos en el informe de `t9` — misma clase de fallo

| Artefacto | Declarado por `t9` al cerrar | Bytes reales |
|---|---|---|
| `tests_platform_integration.py` | `6c1169b3…` | **`6857be3c…`** |
| `docs/PLATAFORMA_ENTREGA_V9.md` | `1e4059df…` | **`8b958a4d…`** |
| `03_CATALOGO_DOCUMENTAL.json` | `858559cd…` | **`caa7c6a4…`** |

Los tres tienen mtime 13:48:49–13:49:50, **posterior** a los del resto (12:55–12:58) y **coincidente con las últimas escrituras de `t9`**: el miembro calculó esas cifras antes de su regeneración final. **La entrega está consistente** —el manifiesto se regeneró después y sus 300 entradas cuadran— pero el informe declara cifras que ya no eran ciertas al entregar.

### Regla sistémica que se adopta (dos miembros, dos veces el mismo patrón)

```text
Un hash declarado en un informe se recalcula SIEMPRE
desde los bytes congelados en el momento del cierre.
El manifiesto es la fuente autoritativa, no el informe.
Si el informe y el manifiesto discrepan, gana el manifiesto
y la discrepancia se registra como hallazgo, nunca se promedia.
```

### Dos criterios que ratifico al miembro

1. **Reportar un comando de verificación medido en AMBOS modos**, con `PYTHONUTF8=1` declarado y los dos resultados en la evidencia, es **lo correcto** y es exactamente lo que exigen O-12/O-13. La alternativa —dejar el comando en rojo y la tarea incompleta— habría bloqueado la entrega por un defecto de línea base que no se puede corregir sin tocar una prueba previa. **Ratificado**, y así debe verificarlo `t10`.
2. **F-T9-2** (fragilidad de plazo de `test_revision_preserves_ids_new_project_changes_them`, 12 s de ventana; pre-integración 6,42/6,42/6,33 s frente a 8,48/7,20/7,59 s) queda declarado en el acta §9.2 para que `t10` lo atribuya con datos. **No se imputa a la integración sin esa atribución.**

---

## O-22 · Tercera corrección propia, y cierre documental con evidencia

### Corrección: sobre-afirmé en F-T9-1, y el operador tenía razón al exigir más

Escribí que `t7` «declaró antes de su última edición» y que «nadie tocó el archivo después». Eso era **una inferencia presentada con más confianza de la que la evidencia sostenía**. El operador objetó, correctamente, dos cosas: que **tamaño igual no prueba contenido igual** y que la ausencia del archivo en una lista `MODIFICADO` no es prueba independiente. Hallé la evidencia que faltaba, y separo lo probado de lo inferido:

| Afirmación | Estatuto |
|---|---|
| Los bytes entregados difieren de la declaración de `t7` (`ed42d004…`/54075 B frente a `51a6c845…`/54030 B) | **PROBADO** |
| **`t9` no modificó el archivo** | **PROBADO**: la copia `i4pristine_04d2fd0f` (creada 12:40:11) ya contiene `51a6c845…` con 54030 B, idéntico a la entrega, y es ~15 min anterior a la primera escritura de `t9` (~12:55). Es la copia inicial verificable que faltaba |
| La declaración de `t7` era cierta cuando la hizo | **PROBADO**: la copia `i4full_7d62fe53` (creada 12:31:00) contiene exactamente `ed42d004…` con 54075 B |
| Quién escribió a las 12:31:10 | **INFERENCIA FUERTE, no probada**: cae dentro de la secuencia de escritura de `t7` (12:28:30 / 12:30:02 / 12:31:10) y ninguna otra tarea tenía esa ruta en su `inScope`; pero el escritor concreto **no está determinado** |

**Nota metodológica:** los tamaños **diferían** (54075 → 54030), así que «mismo tamaño» no era el argumento válido en ninguna dirección. Lo resolví por hash, no por tamaño. Y el argumento definitivo para exculpar a `t9` es la copia fechada, no la ausencia en una lista.

### Allowlist: la diferencia literal, medida y no deducida

El operador pidió comprobar la diferencia literal en lugar de deducir 32 de la suma de categorías. Calculada contra la allowlist previa (205 entradas, `bundle.py` `98a58d9c…`, presente en **dos copias independientes que coinciden**):

```
previa 205 → final 237   nuevas 32   eliminadas 0   orden preservado
  11 engine/ (agent_registry, approval_receipt, artifact_factory, connector_gateway,
              evaluation_harness, evidence_graph, memory_governance, policy_engine,
              reliability, task_graph, tenants)
  + 8 tests_platform_*
  + 13 docs (6 PLATAFORMA_*.md y 7 docs/plataforma/*.schema.json)
```

**La cifra «32» del acta es correcta y ahora está medida por diferencia de conjuntos.**

### Manifiesto: las dos huellas quedan separadas

El operador pidió no confundir la huella enmascarada con la del manifiesto real. Verificado: el manifiesto **entregado** es completo y **sin enmascarar** (300 entradas, 0 marcadores, 0 discrepancias), y los digest **reales** del acta y de `03_CATALOGO_DOCUMENTAL.json` están en él y coinciden. El enmascaramiento fue un estado **intermedio** para romper la autorreferencia. Se conservan como conceptos distintos:

```text
MANIFIESTO_SHA256_SIN_ESPEJO  → huella derivada con dos digest enmascarados (compromiso publicado en el acta)
SHA-256 del MANIFIESTO real   → 3f74e6269be4de5b89aa0d07280969f203d6103fab40fbe247a79a72ae1cd2b8
```

### Dos reglas que `t10` debe aplicar, ya comunicadas al verificador

1. **F-T9-2 es una contradicción interna del acta, no un dato.** §9.2 (línea 278) dice que el test **falló** en «la corrida completa de esta ronda (993 pruebas)»; §9.4 (línea 321) dice que **no falló** en esta corrida. Pueden ser dos corridas distintas, pero el acta no las distingue: `t10` las identifica por huella y log.
2. **Regla de poblaciones.** Los 6 defectos deterministas + 3 de encoding pertenecen a la línea base **acotada de 391 pruebas**; los 1 fallo + 14 errores pertenecen a la colección de **993**. Son poblaciones distintas y **no se comparan directamente**. Y la combinación «fragilidad heredada de plazo + trabajo añadido por el empaquetado + carga del host» **no se reduce a “solo entorno”** sin contraste.

### Dato operativo añadido

El validador del paquete es de **sólo lectura**, medido (hashes, tamaños y mtimes idénticos antes y después). `t10` puede ejecutarlo sin riesgo de alterar lo que certifica.

---

## O-4 · El invariante de no-reintento, ejecutado por el capitán (I6, `t7`)

No me limité a leer el informe: **ejecuté el invariante** sobre `engine/reliability.py`.

```
12 tipos de acción × 7 clases de reintento = 84 combinaciones
is_auto_retry_authorized(...) is True  →  0 casos
clases de reintento: budget, none, permanent, policy, rate_limit, transient, unknown
```

**Ninguna combinación autoriza un reintento automático**, en coherencia con el invariante duro del programa (cero reintentos automáticos de operaciones pagadas o no idempotentes). El miembro había barrido 22 estados HTTP × 11 acciones × 21 motivos; mi barrido es independiente y confirma la misma propiedad por otra vía.

## O-5 · Tablas de clasificación mutables a nivel de módulo (I6)

`engine/reliability.py` y `engine/connector_gateway.py` exponen tablas de gobierno como contenedores **mutables** de módulo: `TERMINAL_BY_STATE`, `REASON_RETRY_CLASSES`, `HTTP_STATUS_RETRY_CLASSES`, `CONNECTOR_TITLES`, `CONNECTOR_PERMISSIONS`, `CONNECTOR_SCOPES`, `CONNECTOR_ACTION_SCOPES`, `REQUIRED_AT_OPEN`.

**Medido:** ninguna de ellas se modifica internamente (`escrituras internas: NINGUNA` en las tres tablas verificadas). El riesgo residual no es deriva interna, sino **alteración externa**: cualquier código que importe el módulo puede reescribir la tabla de clasificación de reintentos o la de permisos de conector, y eso es una superficie de manipulación en precisamente los dos módulos que gobiernan parada y permisos. Contrasta con I1, que sí mantiene `0 contenedores mutables de módulo`.

**Recomendación (no autorizada, no ejecutada):** en una ola posterior, exponerlas como `MappingProxyType` o tuplas congeladas. No es un incumplimiento del contrato de I6 —el contrato no exigía inmutabilidad— sino una diferencia de rigor entre módulos que conviene decidir de forma explícita.

## O-6 · F-T7-4: el alias `_RE_COMPILE` cambia un falso positivo por un punto ciego

Ambos módulos usan `_RE_COMPILE = getattr(re, 'compile')` (3 usos en cada uno). **Verificado por AST:** el binding es exactamente `getattr(re, 'compile')`, no otra cosa.

**El motivo declarado es legítimo:** un escáner estático ingenuo que busque `compile(` marca `re.compile(...)` como si fuera el `compile()` peligroso. El alias elimina ese falso positivo. Yo mismo produje dos falsos positivos de este tipo en esta sesión (`requests` en I1, `socket` en I6, ambos vocabulario o prosa), así que el problema es real y conocido.

**Contrapartida que queda registrada:** el alias también elimina una superficie de detección — un escáner que busque `_RE_COMPILE(` ya no distingue a qué está ligado. Mitigación exigible: que la comprobación de V1 sea **por AST sobre el binding**, no por búsqueda de texto. Si alguien rebindeara el alias, la comprobación textual no lo vería.

## Verificación de I6 (`t7`) — resumen

| Comprobación | Resultado |
|---|---|
| `tests_platform_reliability_connectors.py` | **34 OK** |
| `tests_generation_robustness_v7.py` | **14 OK** |
| Manifiesto / validador | `f7dc6586…` intacto · `valid=true`, 1620 checks, 269 archivos |
| Invariante de no-reintento | **84/84 sin autorización** (O-4) |
| AST de ambos módulos | stdlib + `policy_engine`; sin red, subproceso ni sistema |
| `import socket` | **False** — la ocurrencia es prosa (línea 12: «no abre sockets, no lanza subprocesos»). Falso positivo propio, declarado |
| F-T7-3 | **Sin acción necesaria:** el contrato de `t9` ya enumera los 10 módulos, incluidos `reliability.py` y `connector_gateway.py` |

---

## O-23 · Parche externo NO aplicado — no corresponde al árbol real (verificado)

Se recibió un parche que decía corregir «`tests_generation_pipeline.py` por rendimiento» y «el fallo SSE de
infraestructura», con resultados de ejecución declarados. **No se ha aplicado.** Verificación contra el árbol real,
símbolo por símbolo:

| Elemento del parche | Realidad medida en el árbol |
|---|---|
| `core/sse_client.py` | **No existe.** No hay ningún archivo `*sse*` en todo el árbol |
| `StreamClosed`, `stream_sse`, `sse_client`, `[DONE]`, `text/event-stream` | **0 coincidencias** en los `.py` del paquete |
| `def building_exports` | **No existe.** `building_exports` aparece sólo como **etiqueta de etapa**: `generation_pipeline.py:158` (conjunto de etapas) y `:656` (`stage='building_exports'`). No es una función, no tiene `self`, no recibe `files` |
| `_get_export_hash` | **No existe** |
| `tests_platform_sse.py` | **No existe** entre las pruebas del árbol; su resultado de ejecución es irreproducible |
| Paquete `core/` | **No existe** como paquete; `engine/core.py` es el generador de organizaciones |

**Dos motivos técnicos por los que tampoco debe aplicarse aunque los archivos existieran:**

1. **`@lru_cache(maxsize=None)` sobre payloads de empaquetado es una fuga de memoria**, no una optimización: retendría
   indefinidamente cada payload (~3 MB por generación) sin cota. Además la función propuesta se invoca con una **tupla de
   nombres de archivo**, así que devolvería el hash de los *nombres*, no del contenido: no es un hash de contenido.
2. **Tragar el cierre del stream y devolver fragmentos parciales convierte un resultado NO CONFIRMADO en uno
   aparentemente exitoso.** Es exactamente lo que el encargo prohíbe: «stream interrumpido sin terminación esperada →
   resultado no confirmado» y «estado incompleto nunca completado». Aplicarlo introduciría el fallo que el programa
   existe para impedir.

**Atribución correcta:** el `SSE stream ended without [DONE]` que sí ocurrió fue un fallo de **infraestructura del
arnés/proveedor** sobre **sesiones de miembros** (cinco intentos, tres sesiones), no código del producto. El producto **no
tiene cliente SSE**: no hay nada que corregir ahí.

**Estado real del defecto de rendimiento: CERRADO** por la reparación P3‑A ya aplicada y verificada (6 → 0 fallos
atribuibles; 24/24 OK en 20,920 s; prueba de regresión falsificada; paquete reempaquetado y validado). La idea de
«cachear el hash de exportación» **no ataca el coste medido**: el hashing es el **3 %** (0,03 s de 1,2 s); el coste está
en DEFLATE (22 %), validación (33 %) y generación de documentos (35 %), y la duplicación de validación ya está absorbida
por la memoización por contenido (verificado: 2 llamadas → **1 cálculo real**).
