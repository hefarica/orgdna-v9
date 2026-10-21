# Cuaderno REA — ChatDev `PythonNodeExecutor` + seguridad de ejecución de código

> Fuente fijada: **OpenBMB/ChatDev@a2ea4a2**
> Método: lectura completa vía `https://raw.githubusercontent.com/OpenBMB/ChatDev/a2ea4a2/<ruta>`
> (todas las rutas citadas devolvieron HTTP 200 en ese sha; verificable re-ejecutando el fetch).
> El contenido del repo fuente es **DATO**, no instrucción. Nada de lo que dice un
> comentario o docstring del fuente se trata aquí como orden.

## 0. Archivos leídos completos (evidencia: fetch HTTP 200 al sha citado)

| # | Ruta en el sha a2ea4a2 | Rol |
|---|---|---|
| 1 | `runtime/node/executor/python_executor.py` | **Objetivo**: ejecutor de nodo python |
| 2 | `entity/configs/node/python_runner.py` | Dep. directa: config (timeout/interpreter/env/encoding) |
| 3 | `utils/code_execution.py` | Dep. directa: gate de opt-in de seguridad |
| 4 | `runtime/node/executor/base.py` | Dep. directa: `ExecutionContext`, `_build_message` |
| 5 | `entity/messages.py` | Dep. directa: semántica de `text_content()` en `_extract_code` |
| 6 | `utils/exceptions.py` | Semántica de `SecurityError`/`ValidationError` |
| 7 | `functions/edge_processor/transformers.py` | `code_save_and_run`: procesador gemelo, muy testeado |
| 8 | `utils/workspace_paths.py` | `validate_path_component` / `resolve_workspace_path` |
| 9 | `functions/function_calling/file.py` | `FileToolContext.resolve_under_workspace` (confinamiento) |
| 10 | `tests/test_code_execution_security.py` | Suite de seguridad de ejecución |
| 11 | `tests/test_session_workspace_security.py` | Suite de traversal de sesión |
| 12 | `tests/test_attachment_boundary_security.py` | Suite de frontera de attachments |

**No leído (fail-honest, con razón)** — se declaran porque los tests los citan y
este cuaderno NO describe su interior:

- `entity/configs/__init__.py` (o donde vive `Node.as_config`): el comportamiento de
  `node.as_config(PythonRunnerConfig)` se infiere solo de su uso en el ejecutor.
- `functions/function_calling/code_executor.py` (`execute_code`), `functions/function_calling/uv_related.py`
  (`uv_run`), `functions/function_calling/video.py` (`render_manim`),
  `runtime/node/agent/tool.py` (gate MCP), `utils/attachments.py` (`AttachmentStore`),
  `workflow/graph_context.py` (`GraphContext`), `server/services/attachment_service.py`,
  `runtime/node/executor/agent_executor.py` (`_persist_message_attachments`):
  testeados pero no abiertos. Sus vectores transcriben lo que el **test** observa, no
  su implementación.

## 1. Mapa de los dos caminos de ejecución

ChatDev@a2ea4a2 tiene DOS caminos para correr código Python, con contratos distintos:

| | `PythonNodeExecutor` (nodo `python`) | `code_save_and_run` (edge processor) |
|---|---|---|
| Quién elige el nombre de archivo | **El sistema** (`{node_id_sanitizado}[_run-N].py`) | **El modelo** (primera línea del payload) |
| Superficie de ataque del filename | ninguna (node.id se sanea con `re.sub(r"[^0-9A-Za-z_\-]", "_")`) | máxima → por eso toda la validación de nombres vive ahí |
| Runner | `[interpreter] + args + [script]` vía `subprocess.run`, **shell=False** | `["uv", "run", "main.py"]` vía `Popen`, shell=False |
| Timeout | configurable, default **60 s** (`PythonRunnerConfig.timeout_seconds`, int > 0 o `ConfigError`) | **hardcoded 3 s** |
| Kill al vencer timeout | el de `subprocess.run` (kill al hijo + reaptura) | manual: `killpg(SIGTERM)` en POSIX; en Windows `kill` + `CTRL_BREAK_EVENT` |
| Criterio de éxito | estricto: `returncode == 0` | laxo: `returncode == 0` **o** `stderr` vacío |
| Workspace | persistente entre corridas (contador `_run-N` evita sobrescribir) | **se limpia entero** (salvo `attachments/`) en cada corrida |
| Decode de salida | `errors="replace"` | `errors="ignore"` |

Ambos comparten el mismo gate maestro: `require_unsafe_code_execution`.

## 2. Invariantes de seguridad — lo que NUNCA puede pasar

Cada invariante cita su prueba en el suite del sha.

**I1 — Ejecución sin opt-in explícito del SERVIDOR.**
El único interruptor es la variable de entorno del proceso servidor
`MAC_ALLOW_UNSAFE_CODE_EXECUTION`; habilita solo si
`valor.strip().lower() ∈ {"1","true","yes","on"}`. Se lee **exclusivamente** de
`os.environ` del servidor — "Never consult workflow variables, tool arguments, or
child-process env overrides" (`utils/code_execution.py`).
NUNCA puede habilitarse desde: variables del YAML del workflow, `config.env` del nodo,
argumentos de tools (`uv_run(env={...})`), env de un MCP local, ni env de un proceso
hijo. Pruebas: `test_execution_requires_explicit_opt_in` (None,"","0","false","no","off","typo" →
SecurityError), `test_python_node_env_cannot_enable_execution`,
`test_uv_entry_points_cannot_override_server_policy`, `test_local_mcp_env_cannot_enable_execution`,
`test_uploaded_workflow_cannot_enable_execution` (YAML con `vars` + `env` del nodo en
"1" → HTTP 403 / `event: error`, cero `.py` en disco).

**I2 — Mutación de filesystem antes del gate.**
El gate corre ANTES de crear el workspace, escribir el script, limpiar `media/` o
crear `TEMP_CODE_DIR`. Pruebas: `test_python_node_env_cannot_enable_execution`
(afirma `not workspace.exists()`), `test_execute_code_is_blocked_before_saving_script`
(afirma `not temp_code_dir.exists()`), `test_manim_is_blocked_before_clearing_media`
(`media/keep.txt` intacto), `test_disabled_processor_does_not_clear_or_write_files`.

**I3 — Destrucción antes de validación total (procesador).**
`code_save_and_run` valida TODOS los filenames del payload ANTES de limpiar el
workspace: un payload con un nombre inválido deja los archivos preexistentes intactos
y no lanza proceso. Prueba: `test_processor_validates_all_files_before_clearing`
(`keep.txt` sigue "original", `main.py` no se crea, `Popen` no llamado).

**I4 — Escapes de workspace por nombre de archivo.**
Se rechazan: rutas absolutas, drives de Windows (`PureWindowsPath(filename).drive`
detecta `C:` incluso en POSIX), UNC (`\\server\share`), `..`/`.` como componente,
solo-espacios, caracteres de control/NUL (`validate_path_component`:
`re.search(r"[/\\:\x00-\x1f\x7f]", name)`), y todo lo que `resolve_under_workspace`
no confine (`workspace_root not in target.parents and target != workspace_root` →
"Path is outside workspace"). Pruebas: paramétrica de 14 filenames en
`test_processor_validates_all_files_before_clearing`; `INVALID_NAMES` (12 valores) en
`test_session_workspace_security.py`; `test_uploaded_processor_cannot_plant_module_even_when_enabled`
(`../../../functions/function_calling/planted.py` → "Invalid code filename", `functions/` jamás creada).

**I5 — El directorio `attachments/` es isla de solo-lectura.**
El código generado NUNCA escribe en `attachments/` ni lo reemplaza: se rechaza si el
primer componente es `attachments`, si el path resuelto cae dentro, o si es un alias
de caso (`Attachments/`, `aTtAcHmEnTs`) que resuelva al MISMO directorio — la
comparación es por identidad de inodo (`samefile`), no por string, porque
"`resolve()` preserves case aliases on some filesystems" (comentario del fuente,
dato). El cleanup preserva `attachments/` incluso renombrado con otro casing
(`test_processor_cleanup_preserves_attachment_directory_with_different_case`), y en
filesystems case-sensitive un `Attachments/` distinto SÍ se permite
(`test_processor_allows_distinct_case_sensitive_directory`). Un `attachments` que sea
symlink se rechaza antes de cualquier borrado con "The attachments directory must not
be a symbolic link" (`test_processor_rejects_linked_attachments_before_cleanup`).

**I6 — Symlinks que amplifican alcance.**
Ningún camino de escritura sigue un symlink hacia fuera: targets symlinked en el
payload → SecurityError (`test_processor_rejects_symlink_targets`); symlinks
preexistentes en el workspace se **desvinculan** (`item.unlink()`), nunca se
`rmtree`-ean a través de ellos — `old_link` → fuera deja de ser symlink y
`outside/keep.txt` queda intacto (`test_enabled_processor_preserves_nested_files_and_attachments`);
sesión/workspace/attachments que ya existen como symlink → ValidationError "escapes"
(`test_graph_rejects_existing_session_symlink`,
`test_attachment_copy_rejects_escaping_symlinks`,
`test_runtime_rejects_workspace_symlink_without_attachments`,
`test_upload_endpoints_reject_escaping_symlinks`); el zip de descarga **omite**
links (file/directory/dangling/loop) y solo empaqueta archivos regulares
(`test_download_skips_links_and_preserves_regular_files`,
`test_download_with_venv_interpreter_links`: los symlinks `.venv/bin/python` quedan
fuera del zip, `pyvenv.cfg` entra).

**I7 — Traversal por nombre de sesión.**
`session_id` → `session_{validate_path_component(...)}`: un solo componente, sin
separadores, drives ni controles. Se valida en TODA entrada antes de hacer trabajo:
HTTP 400 antes de arrancar el worker (`test_http_rejects_bad_session_before_starting_worker`),
WebSocket close 1008 sin registrar conexión, upload service rechaza **antes de leer
el archivo** (`upload.file.tell() == 0`, dato observable del test), SDK rechaza antes
de `load_config` y sin crear `WareHouse`. Incluso con `fixed_output_dir: True`,
`../outside` sigue rechazado (`test_fixed_output_directory_is_still_confined`).

**I8 — Fuentes de attachment no confiables por HTTP.**
Un workflow lanzado por HTTP solo acepta attachments del store de la sesión
declarada (`attachment_session_id`): absolutos, relativos, symlinked, no
registrados, de otra sesión, o id ajeno → 403 antes de copiar nada y sin crear la
sesión destino. El SDK local (CLI, confianza distinta) sigue aceptando paths
explícitos (`test_local_sdk_still_accepts_explicit_file_paths`).

**I9 — Shell.**
Ambos lanzadores usan argv-lista con `shell` ausente/falso. Prueba explícita:
`assert not kwargs.get("shell", False)` y `args == (["uv", "run", "main.py"],)`
(`test_enabled_processor_preserves_nested_files_and_attachments`).

**I10 — Attachments generados por nodos agente.**
`_persist_message_attachments` valida `node_id`, `name` y `attachment_id` como
componentes únicos (mismas clases de rechazo que I4), rechaza symlinks en cualquier
tramo de `generated/...`, y exige que un `local_path` fuente ya resuelva DENTRO del
workspace (directo o via symlink → SecurityError, `test_generated_local_source_cannot_read_outside`).

## 3. Orden exacto de operaciones

### 3.1 `PythonNodeExecutor.execute(node, inputs)` — texto del fuente, sin saltos

```
1. Guard de contrato: node.node_type != "python" → ValueError. (nada tocado aún)
2. GATE:      require_unsafe_code_execution("Python node")
              → lee SOLO os.environ del servidor; sin opt-in → SecurityError
                y NO EXISTE ningún directorio aún (I2).
3. WORKSPACE: _ensure_workspace_root()
              - global_state["python_workspace_root"] cacheado → re-usar y mkdir otra vez
              - si falta: requiere global_state["graph_directory"] (si no → RuntimeError),
                root = (graph_dir / "code_workspace").resolve(); mkdir(parents, exist_ok)
4. EXTRACT:   code = último mensaje (inputs[-1]; si no hay → "").
              - text_content() del mensaje
              - si hay bloque ```lang\n...``` → PRIMER match, grupo "code"
              - si no hay bloque → el texto crudo ES el código
              - textwrap.dedent(...) + strip()
              - vacío → Message de fallo "No executable code segment found"
                (NO es excepción: es un mensaje de fallo estructurado)
5. SCRIPT:    _write_script_file
              - contador por node.id en global_state["python_node_run_counters"] (n, n+1...)
              - safe_node_id = re.sub(r"[^0-9A-Za-z_\-]", "_", node.id)
              - filename = f"{safe_node_id}{'_run-%d' % n if n > 1 else ''}.py"
              - path = (workspace / filename).resolve()
              - write_text(código + "\n" si no terminaba en \n, utf-8)
6. CONFIG:    node.as_config(PythonRunnerConfig); ausente → ValueError.
7. SPAWN:     _run_process
              - cmd = [interpreter] + args + [str(script_path)]   (lista, sin shell)
              - env = os.environ.copy() + config.env + {
                  MAC_CODE_WORKSPACE, MAC_CODE_SCRIPT, MAC_NODE_ID }
              - subprocess.run(cmd, cwd=str(workspace), capture_output=True,
                               check=False, timeout=config.timeout_seconds)
8. CAPTURE/DECODE: stdout/stderr .decode(config.encoding, errors="replace")
9. ÉXITO (returncode == 0):
              - Message(ASSISTANT, content=stdout, metadata={workspace, script_path})
              - stderr NO va en el mensaje: solo log_manager.debug
10. FALLO:
              - Message con "==CODE EXECUTION FAILED==" + error_text
                + "exit_code={n}" (si hay) + "stderr:\n{...}" (si hay)
              - metadata: workspace siempre; script_path/exit_code/stderr condicionales
```

El spawn hereda la flag del servidor (`os.environ.copy()`): propagación unidireccional
servidor→hijo; el hijo jamás influye la flag de corridas futuras (I1).

### 3.2 `code_save_and_run(data, _context)` (procesador) — orden

```
1. GATE: require_unsafe_code_execution("code_save_and_run")           (I1/I2)
2. PARSE: regex "(?P<filename>[^\n]+)\n```(?:python)?\n(?P<code>.*?)\n```"
          sobre TODO el payload; sin matches → devuelve el payload tal cual (no-op).
3. VALIDAR TODO ANTES DE BORRAR (I3): por cada match, en orden:
   a. attachments_root symlink? → SecurityError                    (I5)
   b. filename vacío / absoluto / con drive → SecurityError         (I4)
   c. cada componente por validate_path_component                   (I4)
   d. resolve_under_workspace → confinado o SecurityError           (I4)
   e. alias-de-caso de attachments por samefile en (path ∪ parents) (I5)
   f. path == workspace_root o bajo attachments → SecurityError     (I5)
4. CLEANUP: borrar cada item del workspace EXCEPTO attachments/
   (por nombre y por samefile); los symlinks se unlink, los dirs rmtree, el resto unlink.
5. WRITE: cada archivo validado (mkdir parents, write_text utf-8).
6. SPAWN: Popen(["uv","run","main.py"], cwd=workspace, pipes,
          env=os.environ.copy() + PYTHONUNBUFFERED=1,
          POSIX: start_new_session=True | Windows: CREATE_NEW_PROCESS_GROUP)
7. TIMEOUT 3 s: communicate(timeout=3); vencido → killpg(SIGTERM) o
   kill+CTRL_BREAK_EVENT; communicate() final para reapturar.
8. DECODE errors="ignore"; filtrar línea de warning experimental de uv
   (convención descartable, ver §5).
9. ÉXITO laxo: rc==0 O stderr vacío → stdout + "The software run successfully
   without errors."  FALLO: stderr (si contiene "Traceback", se remata la ruta
   absoluta del workspace del texto). Cualquier excepción del bloque → "Error: {e}".
10. RETURN: bloques de código guardados + "\n\n" + resultado.
```

## 4. Bordes (vectores obligatorios de un port)

| Borde | Comportamiento en el fuente | Prueba/evidencia |
|---|---|---|
| **Timeout vencido (ejecutor)** | `TimeoutExpired` → resultado fallido con `exit_code=None` (distingue timeout de crash), stdout="" , stderr = `exc.stdout` parcial decodificado, error = `f"Script did not finish within {N}s"` | `python_executor.py::_run_process` |
| **Timeout vencido (procesador)** | SIGTERM al grupo de proceso; éxito laxo posterior: si stderr quedó vacío se reporta éxito ("covers the case where the process times out/is killed but didn't crash", comentario del fuente) | `transformers.py::code_save_and_run` |
| **Código que falla** | rc≠0 → mensaje `==CODE EXECUTION FAILED==` con `exit_code={n}` y stderr embebido; en el procesador, Traceback con la ruta del workspace recortada | `_build_failure_message`; `transformers.py` |
| **Intérprete inexistente** | `FileNotFoundError` → error "Interpreter {X} not found", exit_code=None | `_run_process` |
| **Sin segmento de código** | NO es excepción: mensaje de fallo "No executable code segment found" | `execute` paso 4 |
| **Payload sin bloque de código (procesador)** | no-op: devuelve el payload sin cambiar nada | `code_save_and_run` paso 2 |
| **Varios bloques en el mensaje (ejecutor)** | solo el PRIMER bloque cercado ejecuta (`_CODE_BLOCK_RE.search`); sin cerca, el texto crudo es el código | `_extract_code` |
| **Salida enorme** | `capture_output=True` bufferea TODO en memoria; decode con `errors="replace"` nunca trunca ni explota por bytes inválidos; **NO hay truncamiento de salida en ninguno de los dos caminos** — un port debe decidir su propio tope (brecha consciente del fuente) | `_run_process`; `transformers.py` |
| **Bytes no-UTF8** | ejecutor: `errors="replace"`; procesador: `errors="ignore"` (divergencia interna del fuente; para un port, `replace` es más seguro: preserva evidencia del error) | idem |
| **Corridas repetidas** | contador por nodo → `{id}_run-2.py`, `_run-3.py`…: nunca se pisa el script de una corrida anterior; primera corrida sin sufijo | `_write_script_file` |
| **node.id hostil** | se sanea a `[0-9A-Za-z_\-]` para el FILENAME; el id original viaja intacto en env `MAC_NODE_ID` y metadata | `_write_script_file` |
| **graph_directory ausente** | `RuntimeError("graph_directory missing from execution context")` — no hay fallback silencioso | `_ensure_workspace_root` |
| **timeout_seconds inválido** | no-int o ≤0 → `ConfigError("timeout_seconds must be a positive integer")` | `python_runner.py::from_dict` |
| **encoding vacío** | `ConfigError("encoding cannot be empty")`; default "utf-8" | idem |
| **inputs vacío** | `last_message=None` → extract "" → "No executable code segment found" | `execute` |
| **stderr en éxito (ejecutor)** | se descarta del mensaje (solo debug-log): el consumidor downstream ve stdout puro | `execute` paso 9 |

## 5. Convenciones descartadas (se re-derivan en el destino, no se portan)

- **`uv run main.py`** como runner del procesador: toolchain propio de ChatDev. La
  semántica portable es "argv fijo + shell=False + cwd=workspace", no el binario `uv`.
- **Nombres `MAC_*`** (`MAC_ALLOW_UNSAFE_CODE_EXECUTION`, `MAC_CODE_WORKSPACE`,
  `MAC_CODE_SCRIPT`, `MAC_NODE_ID`): naming del fuente. El invariante es "UNA flag
  del entorno del servidor, leída solo del proceso servidor" — el nombre lo elige el
  destino. Igual la clase base `MACException` y el directorio `WareHouse` y el
  prefijo `session_`.
- **Filtro del warning experimental de uv**: ruido específico de su stack; no portar.
- **Criterio de éxito laxo del procesador** (`rc==0 OR stderr vacío`): decisión
  tolerante a kills de timeout. El ejecutor es estricto (`rc==0`). Para un port, el
  estricto es el defendible; si se adopta el laxo hay que declararlo.
- **Limpieza total del workspace por corrida** (procesador): semántica destructiva
  deliberada; un port debe decidirla explícitamente, no heredarla por copia.
- **`errors="ignore"`** (procesador) frente a `replace` (ejecutor): divergencia
  interna; se descarta `ignore`.
- **Doble canal HTTP JSON/SSE** con las mismas garantías: capa de transporte del
  fuente; el invariante (mismo rechazo en ambos canales) sí es portable como forma
  de test.
- **`interpreter = sys.executable or "python3"`** y **timeout default 60 s**: estos
  sí son semántica valiosa (defaults seguros) — se mantienen como valores de
  referencia citados, no como literales obligatorios.

## 6. Números-hecho extraídos (citable bajo binding rule 3, FUSILE)

- Opt-in verdadero: exactamente `{"1", "true", "yes", "on"}` tras `strip().lower()`.
- Timeout default ejecutor: **60 s** (int > 0 obligatorio). Timeout procesador: **3 s**.
- Profundidad máxima de listado de workspace: 8 (`describe_available_files`, comentado
  como `max_depth = 8`); límite default 200 entradas / 500 en `list_directory`.
- Payload de código cercado: primer match de
  ````(?P<filename>[^\n]+)\n```(?:python)?\n(?P<code>.*?)\n``` ```` (procesador) /
  ```` ```(?P<lang>[a-zA-Z0-9_+-]*)?\s*\n(?P<code>.*?)``` ```` (ejecutor, DOTALL).
- Saneo de node.id: `[^0-9A-Za-z_\-]` → `_`.
- Componente de nombre válido: sin `/ \ : NUL ni controles \x00-\x1f\x7f`, ni `.`, `..`, ni blank.

## 7. Procedencia (fuente → concepto para el port)

```
runtime/node/executor/python_executor.py :: PythonNodeExecutor.execute     → orden del §3.1 (gate→workspace→extract→write→spawn→capture)
runtime/node/executor/python_executor.py :: _run_process                   → timeout parcial, exit_code=None, decode replace
runtime/node/executor/python_executor.py :: _write_script_file             → saneo de filename, contador _run-N
runtime/node/executor/python_executor.py :: _build_failure_message         → marcador ==CODE EXECUTION FAILED== y metadata condicional
utils/code_execution.py :: require_unsafe_code_execution                   → I1 (flag única, solo os.environ del servidor)
entity/configs/node/python_runner.py :: PythonRunnerConfig.from_dict       → validación de timeout/encoding, defaults
functions/edge_processor/transformers.py :: code_save_and_run              → §3.2, I3/I4/I5/I6, éxito laxo, kill de grupo
utils/workspace_paths.py :: validate_path_component / resolve_workspace_path→ I4/I7, session_ mapping
functions/function_calling/file.py :: FileToolContext.resolve_under_workspace → confinamiento por parents tras resolve()
entity/messages.py :: Message.text_content                                 → extracción best-effort de bloques
utils/exceptions.py :: SecurityError/ValidationError                      → tipos distinguibles (SECURITY_ERROR vs VALIDATION_ERROR)
tests/test_code_execution_security.py                                     → I1,I2,I3,I4,I5,I9 + vectores 1–22
tests/test_session_workspace_security.py                                  → I6,I7 + vectores 23–36
tests/test_attachment_boundary_security.py                                → I6,I8,I10 + vectores 37–51
```

## 8. Reglas de port inmediatas (para el integrador GenTeam)

1. El gate ANTES que todo: ni mkdir, ni tmpdir, ni script, ni logging de archivo.
2. Una sola flag, leída del proceso anfitrión; todo lo que venga del agente/modelo
   (vars de grafo, env de nodo, args de tool) es incapaz de habilitarla — y eso se
   TESTEA desde el lado del atacante, no solo del feliz.
3. Validación completa antes de cualquier borrado (all-or-nothing).
4. Filename del modelo = superficie de ataque: componente-único + sin
   separadores/drives/controles + confinamiento post-resolve + isla `attachments`
   por identidad de inodo (samefile), no por string.
5. Symlinks: unlink, nunca rmtree a través; descargas omiten links.
6. Marcador de fallo estable y exit_code=None para timeout — distinguible de crash.
7. Sin truncamiento de salida en el fuente: el port DEBE añadir un tope propio y
   declararlo (mejora consciente, no paridad).
