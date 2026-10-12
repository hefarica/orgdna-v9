# Hallazgos de línea base — NO atribuibles a la ola de plataforma

**Fecha de medición:** 10 de octubre de 2026
**Artefacto medido:** paquete `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/` **sin ningún cambio** (V8 tal como se entregó)
**Log completo:** `linea_base_regresion_v8.txt` (raíz de este workspace)

## Comando de reproducción

```
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'tests_*.py' -v
```

## Resultado

```
Ran 391 tests in 168.517s
FAILED (failures=1, errors=8, skipped=1)
```

**El paquete entregado no pasa su propia suite de pruebas en un host Windows limpio.** Nueve defectos, cuatro causas raíz. **Refinamiento verificado:** tres de esos nueve son inducidos por el locale y **desaparecen por completo con `PYTHONUTF8=1`**, así que el número de defectos deterministas es **seis** (Causa B: 1; Causa C: 4; Causa D: 1). La medición está en «Causa A» más abajo.

## Defectos por causa raíz

### Causa A — Encoding por defecto `cp1252` al leer archivos sin `encoding='utf-8'` (3 errores)

| Test | Excepción | Posición |
|---|---|---|
| `tests_v8_ui_contract.V8UIContracts` (setUpClass) | `UnicodeDecodeError: 'charmap' codec can't decode byte 0x81` | 149255 |
| `tests_frontend_contract.FrontendContracts` (setUpClass) | `UnicodeDecodeError: 'charmap' codec can't decode byte 0x81` | 1468 |
| `tests_generation_pipeline.GenerationPipelineTests.test_save_reload_does_not_restore_consent_or_start_jobs` | `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d` | 14464 |

`tests_v8_ui_contract.py:19` ejecuta `(ROOT / 'web/app.js').read_text()` sin `encoding`. En un Python cuya codificación por defecto es `cp1252`, cualquier archivo con caracteres no ASCII (todo el código en español) rompe la prueba. **El defecto es de portabilidad, no de lógica.**

**MITIGACIÓN VERIFICADA POR EL CAPITÁN (10 de octubre).** Los tres módulos pasan a verde con `PYTHONUTF8=1`, medido uno a uno:

| Módulo | Sin `PYTHONUTF8` | Con `PYTHONUTF8=1` |
|---|---|---|
| `tests_v8_ui_contract.py` | FAILED (errors=1) | **OK** |
| `tests_frontend_contract.py` | FAILED (errors=1) | **OK** |
| `tests_generation_pipeline.py` | FAILED (errors=1) | **OK** |

**Consecuencia práctica:** ejecutar la suite con `PYTHONUTF8=1` reduce los defectos de línea base de nueve a **seis**. La corrección de fondo —añadir `encoding='utf-8'` explícito en las pruebas que leen archivos— sigue pendiente y pertenece a la ola P2, pero la mitigación operativa ya está disponible y no requiere tocar el paquete.

### Causa B — El puente Excel no puede ejecutarse desde el estado en que se distribuye (1 error)

| Test | Excepción |
|---|---|
| `tests_bridge.BridgeStateTests.test_workbook_stale_blocks_export` | `engine.bridge.BridgeError: Excel no pudo completar la acción… Detalle: No se puede cargar el archivo C:\Users\HFRC\Downloads\EQUIPO_ENTERPRISE_24_COUNCIL_ADN ` |

**CORRECCIÓN DE UNA HIPÓTESIS PROPIA.** En la primera versión de este registro atribuí el fallo al comillado de la ruta con paréntesis (`…ADN (7)`). Esa hipótesis queda **refutada**. El diagnóstico corregido, aportado por el miembro `gobernanza` durante la ola de plataforma y **verificado por el capitán leyendo el código**, identifica dos mecanismos reales:

1. **Mark-of-the-Web + `RemoteSigned`.** El ZIP se descargó de Internet, así que `engine/excel_bridge.ps1` arrastra un flujo alternativo `Zone.Identifier` (103 bytes). Con `LocalMachine=RemoteSigned`, PowerShell se niega a cargar el script no firmado. El detalle truncado que capturé (`No se puede cargar el archivo C:\…\EQUIPO_ENTERPRISE_24_COUNCIL_ADN `) es exactamente el mensaje de ese rechazo: se corta justo donde empieza la ruta, no por los paréntesis. Al desbloquear el archivo en una copia, el script **sí arranca** con Excel COM 16.0 — lo que descarta definitivamente la hipótesis de la ruta.
2. **`engine/excel_bridge.ps1:82` — `throw` para `-Action Read`.** **Precisión verificada:** NO lanza incondicionalmente. Está dentro de `if ($null -eq $book)` (línea 81), de modo que lanza sólo cuando el libro designado **no está abierto** en la instancia activa de Excel. Como `tests_bridge.py:163` crea un fixture temporal que nunca se abre en Excel, el `throw` se alcanza siempre en esa prueba.

**Alcance real del defecto:** `engine/bridge.py:1444` decide por plataforma — en Windows `download()` pasa por `excel_call('Read', …)`; en POSIX usa `read_xlsx_snapshot(...)` y no toca Excel. Por tanto **en Windows toda descarga de exportación exige una instancia viva de Excel con el libro abierto y el script desbloqueado**; en POSIX no. La prueba `tests_bridge.py:161-168` está escrita contra el camino POSIX y no puede pasar en Windows.

**Impacto práctico alto y superior al que declaré primero:** no es un problema de la carpeta del usuario, es que la exportación en Windows depende de Excel en ejecución y de que el usuario desbloquee manualmente un script descargado. Eso afecta a cualquier instalación desde ZIP, no sólo a la de este host.

### Causa C — Respaldo del relanzador DSH no verificable (4 errores)

| Test | Excepción |
|---|---|
| `tests_dsh_launcher.LauncherTests.test_backup_hashes_and_original_unchanged` | `engine.dsh_launcher.LauncherError: No se completó un respaldo verificable…` |
| `tests_dsh_launcher.LauncherTests.test_execute_exact_argv_idempotent_and_separate_status` | idem |
| `tests_dsh_launcher.LauncherTests.test_execute_rejects_changed_backup_inventory` | idem |
| `tests_dsh_launcher.LauncherTests.test_unknown_binary_cannot_execute_even_if_state_tampered` | idem |

Los cuatro comparten el mismo punto de fallo: el paso de respaldo del relanzador. **Causa NO DETERMINADA.** No hereda la explicación del comillado de rutas —esa hipótesis está **refutada** en «Causa B»— y la posible raíz compartida con B es una **conjetura sin evidencia**, no un hallazgo. Su diagnóstico aislado corresponde a P2-C.

### Causa D — El relanzador inyecta el puerto 3080 cuando la prueba exige ninguno (1 failure)

| Test | Excepción |
|---|---|
| `tests_dsh_launcher.LauncherTests.test_no_script_assumption_no_guessed_port` | `AssertionError: Lists differ: [3080] != []` |

La prueba exige que un plan con `ports: []` no invente puertos; la implementación devuelve `[3080]`. **3080 es exactamente el puerto del panel Web de DSH en este host.** Discrepancia real entre contrato y comportamiento: o el código adivina un puerto por defecto (lo que la prueba prohíbe expresamente) o la prueba está desactualizada.

### Skip legítimo (no es defecto)

`tests_evaluation_runs.Evaluations.test_timeout_terminates_child_process_group ... skipped 'POSIX process group check'` — correcto en Windows.

## Impacto sobre los entregables

| Efecto | Consecuencia |
|---|---|
| La suite no acredita el paquete al 100 % | Cualquier informe que declare "todas las pruebas pasan" sobre este ZIP sería **falso** |
| Tres pruebas no pueden ejecutarse en locale `cp1252` | La cobertura de UI y de generación está **infravalorada** en el informe de validación del ZIP |
| Excel/COM en Windows exige libro abierto y script desbloqueado (causa medida, **no** la ruta) | Afecta a la exportación real del usuario en Windows; POSIX no usa Excel |
| `[3080]` | El contrato de "no adivinar puertos" no se cumple en el código |

## Decisión requerida (no autorizada, no ejecutada)

1. **¿Se autoriza una ola de corrección P2** posterior a la plataforma, con estos cuatro frentes: encoding explícito en pruebas, desbloqueo y ejecución del puente Excel en Windows (Mark-of-the-Web + `excel_bridge.ps1:81-82`), diagnóstico del respaldo del relanzador, y resolución de la discrepancia del puerto 3080?
2. **¿O se congela como línea base conocida** y se limita a declararse en los informes, que es lo que hace la tarea V1?

**Mientras no haya decisión, estos defectos NO se tocan.** La tarea V1 tiene instrucción explícita de registrarlos como no atribuibles a la ola y de no exigir verde absoluto; la tarea INT-A tiene prohibido modificar pruebas previas para que pasen. Ninguna tarea de la ola aprobada puede absorberlos ni silenciarlos.
