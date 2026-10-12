# Contrato de la app web local 1.0

## Inicio y límites reales

- Windows: extraer todo el paquete y ejecutar `launch.cmd`. La app web es la interfaz principal. Excel es un complemento opcional; abrir el libro en Excel de escritorio sólo si deseas sincronizarlo.
- Python 3.10+ instalado previamente. Sólo biblioteca estándar; no instala paquetes ni ejecuta contenido del repositorio.
- Alternativa portable desde la carpeta del paquete: `python -m engine.bridge --no-browser`.
- URL: `http://127.0.0.1:8765/`. Los hipervínculos del libro necesitan este proceso abierto. El libro `.xlsx` por sí solo no ejecuta Python, scripts ni APIs.
- `Ctrl+C` cierra el servidor y vacía sus claves de memoria. No inicia ningún agente DSH, Council, implementación ni trading. Un servidor HTTP vivo no equivale a operación 24/7 de agentes.
- La interfaz debe quedar en loopback. No publicar, tunelizar ni cambiar el bind a `0.0.0.0`.

## Libro y sincronización

El contrato de rangos es `workbook/sheet_ranges.json`. `Configuracion` B6:B15/B21:B22 contiene entradas. `Asignacion_modelos` D/E permite proveedor/modelo por ID estable. D/E con fórmula heredan la selección automática J/K o el valor global; una celda reemplazada por texto fija sólo ese campo como override manual. I identifica la fuente de selección. Los IDs/cargos se sincronizan al aplicar perfiles.

1. `Leer archivo guardado` usa ZIP/XML stdlib de sólo lectura. No ve cambios sin guardar.
2. `Sincronizar Excel abierto` usa COM en Windows y lee el libro exacto en la instancia activa de Excel. Si no lo encuentra abierto, bloquea; no finge haber leído cambios en vivo.
3. `Generar organización offline` usa `core.generate_organization` y las asignaciones manuales leídas. No hace llamadas de red.
4. `Aplicar datos a Excel y guardar` requiere confirmación; crea primero una copia de recuperación junto al libro, aplica configuración/datos y guarda. Una interrupción puede dejar cambios parciales en el libro abierto; la copia `*.before-apply.*.xlsx` permite recuperarse sin sobrescribir otras ediciones a ciegas.
5. Una descarga GET nunca genera, llama proveedores ni escribe Excel. Lee la organización existente. Si existe un libro asociado, compara su configuración y sus asignaciones con la última sincronización. En Windows requiere que el libro esté abierto para leer también cambios sin guardar. Si cambió, bloquea la descarga hasta sincronizar y regenerar.
6. `Trabajar sólo en el panel` desvincula el libro; permite generar/exportar desde los campos visibles del panel sin Excel. La desvinculación exige regenerar.

Al aplicar se escriben sólo Perfiles, CV, Competencias, Council, Subequipos, Modelos y Asignacion_modelos A:E/I:K. Se conservan Organigrama, Council E, Subequipos D, la disponibilidad calculada y las notas/prioridades de asignaciones y los registros de Pruebas/Aprendizaje. Las nueve celdas de enlace declaradas se convierten a hipervínculos nativos de loopback. Se mantiene `CatalogoModelos` y sus validaciones, con advertencia que permite una selección manual no verificada.

CV usa una fila por entrada aspiracional. Máximo 32 perfiles, 400 entradas CV, 400 competencias y 200 filas de modelos en Excel. Si se excede una capacidad, se bloquea sin truncar. El estado completo sigue disponible en la descarga de ADN.

Todos los textos externos se escriben con formato de texto antes de `Value2`; nunca mediante `Formula`/`Formula2`. Los prefijos `=`, `+`, `-` y `@` no se interpretan como fórmulas. Las fórmulas ejecutables provienen de la plantilla controlada, no del repositorio ni del LLM.

## Proveedores, rutas y disponibilidad

- Rutas admitidas: `deepseek-official`/`deepseek` → API DeepSeek; `zai-official`/`zai` → API Z.ai; `openai` → API OpenAI.
- La ruta runtime se conserva en el JSON. Un alias de transporte no cambia el proveedor de los agentes exportados.
- Consulta de catálogo: confirmación explícita, sin completions. Un catálogo API real acredita el listado observado para la cuenta; no acredita calidad, latencia, precio ni ejecución de tareas.
- Z.ai sin endpoint de catálogo documentado: referencia manual marcada no verificada. No se inventa `/models` ni disponibilidad de cuenta.
- Prueba mínima opcional: una sola inferencia con 32 tokens de salida máximos, tras preparación y confirmación separadas. Un 429 o fallo de red mantiene `UNVERIFIED`; no convierte el modelo en inexistente. No hay sondeos masivos.
- Un modelo desconocido permanece advertido como no verificado y necesita preflight de runtime. Uno confirmado no disponible bloquea exportación. No hay sustitución automática por otro modelo.

## Repo y consentimiento LLM

`analyze-repository` obtiene inventario de GitHub en lectura, con límites y SHA; no ejecuta código ni manda contenido a un LLM. `prepare-analysis` construye un resumen depurado y muestra contenido exacto, endpoint, modelo, hash, tokens aproximados y límite de salida. La confirmación exige revisar datos, autorizar su transmisión y reconocer posibles cargos.

No se afirma un límite monetario duro: el precio puede ser desconocido. `llm_budget_usd` es una referencia editable y no autoriza gasto por sí sola. La barrera aplicada es una solicitud con máximo de salida elegido entre 256 y 16384 tokens para análisis (8192 por defecto), o 32 para prueba mínima. El consentimiento se consume antes de I/O. Si hay timeout/fallo incierto, hace falta preparar y confirmar uno nuevo; no se reintenta automáticamente.

La propuesta del LLM es entrada no confiable: el motor valida un esquema declarativo. No puede introducir comandos, permisos, nuevas URLs de servicio ni fórmulas. El análisis no acredita las competencias de los agentes.

## Claves

Las claves se introducen únicamente en un campo de contraseña del panel. No están en Excel, URLs, historial de shell, repositorios ni recibos. Se mantienen en memoria por defecto. El guardado opcional usa DPAPI CurrentUser en Windows (`LOCALAPPDATA/OrgDNA/keys.dpapi`); no crea un archivo de claves en claro. `Olvidar claves` elimina memoria y el almacén de este panel. DPAPI sólo permite reutilizarlas con el mismo usuario de Windows; no es un almacén portable.

DPAPI y COM requieren verificación en Windows; no se presentan como probados por los tests de Linux. El launcher no cambia ExecutionPolicy, no usa Bypass, no habilita macros ni VBOM. Si la política bloquea el script, el usuario debe revisarlo y seguir el proceso de firma/confianza de su organización; no rebajar su seguridad.

## HTTP y API interna

Servidor `127.0.0.1` exclusivamente. Comprobación exacta de Host; Origin loopback obligatorio en POST; cookie HttpOnly/SameSite=Strict y token CSRF por proceso; Fetch-Site cross-site bloqueado; sin CORS; CSP sólo self; sin frames; sin caché; cuerpo JSON máximo 128 KiB. Los consentimientos se confirman por ID/hash, no reenviando una vista previa grande. No se imprimen URLs, cuerpos ni claves en el log HTTP.

Los principales formatos descargables son `implementation.json` (recipe DSH) y `definitions.json` (backup de definiciones con agentes compartidos y squads). `package.zip` reúne el paquete actual; `council.json` es un recipe opcional independiente. Generar un ZIP tampoco inicia agentes.

GET: `/`, `/app.js`, `/style.css`, `/api/state`, `/api/projects`, `/download/{organization,implementation,definitions,council,evidence}.json`, `/download/package.zip`.

POST: `/api/project-save`, `/api/project-load`, `/api/edit-organization`, `/api/subteam-save`, `/api/council-create`, `/api/council-add-entry`, `/api/council-close`, `/api/skill-register`, `/api/skill-update`, `/api/remediation-create`, `/api/remediation-update`, `/api/config`, `credentials`, `forget-credentials`, `import-workbook`, `read-excel`, `detach-workbook`, `reset-model-overrides`, `generate`, `discover-models`, `analyze-repository`, `prepare-analysis`, `prepare-verification`, `confirm-analysis`, `apply-excel`.

El estado público no incluye claves. Los recibos redactan recursivamente claves incluso con comillas o barras invertidas. Las llamadas de test usan exclusivamente fixtures explícitas; `source=live_api` dentro de una fixture no equivale a una llamada real aprobada.

## Verificación

Ejecutar desde la carpeta del paquete:

```
python -m unittest tests_bridge -v
python -m unittest discover -s tests -v
python -m unittest tests_providers -v
python -m unittest qa_independent.test_contracts -v
```

Tests del puente cubren generación/export offline, invalidación por cambios, overrides por ID, comparación de libro guardado, límites de tablas, no replay del consentimiento, fallo incierto, aliases, redacción de secretos y HTTP Host/Origin/CSRF/cookie/GET sin mutación. La inspección estática de PowerShell no certifica COM: falta ejecutar lectura/escritura/hyperlinks/validación/recuperación en Windows Excel real. Tampoco se han afirmado inferencias reales de proveedor ni ejecución DSH.

## Modelos automáticos y preferencias

Las prioridades de Modelos (menor número = preferencia mayor) y sus capacidades descriptivas se combinan con disponibilidad verificada de la sesión. Una celda AVAILABLE guardada en Excel no acredita por sí sola una consulta API reciente. Sin una alternativa disponible con motivos suficientes, el motor conserva el modelo global y declara benchmark pendiente. Las recomendaciones no son mediciones de inteligencia ni rentabilidad.

Al aplicar, una recomendación automática se guarda como texto en J/K y conserva D/E como fórmulas. Un override manual se conserva sólo en el campo editado. Restablecer herencia vacía los overrides en el panel; requiere generar y aplicar para restaurar las fórmulas del libro. Los perfiles y auxiliares inactivos fuera de N se conservan como semillas; el aviso STALE exige regenerar antes de exportar tras cambiar N.

## Proyectos locales y versiones

`project-save` recibe `{name, as_new?}`. Cada guardado crea una versión inmutable y actualiza un puntero atómico a la última versión en `data/projects/<UUID>/`. No existe endpoint de borrado. `project-load` recibe `{project_id, version_id?, confirmed?}`; si hay cambios no guardados, exige confirmación. GET `/api/projects` devuelve `{projects:[{project_id,name,version_id,saved_at,agent_count,versions,version_count,sha256}]}`.

Los proyectos guardan configuración, perfiles, árbol, preferencias de modelos, análisis y registros manuales. No incluyen claves, cookies, tokens de sesión, consentimientos de gasto, caché de repositorio ni rutas de Excel del equipo original. Las rutas se validan contra el directorio autorizado y se rechazan symlinks. Cada versión tiene SHA256 para detectar corrupción; no es una firma de autenticidad frente a quien pueda editar todos los archivos del usuario.

Cargar no sobrescribe ni borra versiones anteriores. La disponibilidad histórica de modelos baja a no verificada, preservando perfiles y relaciones. Abrir la app no ejecuta agentes ni recupera autorizaciones para llamadas pagadas.

`state.project` contiene `{id,name,version_id,dirty}`. `generation_stale` conserva visible el diseño anterior cuando cambia la configuración, pero bloquea exportarlo como actual. `has_manual_edits` obliga a confirmar `generate {confirmed_discard_edits:true}` antes de reemplazar esas ediciones. Es recomendable guardar una versión antes de regenerar.

## Edición y jerarquía

`edit-organization` recibe `edits` con `expected_state_version`, `hierarchy_mode` opcional y una lista `agents` de cambios por ID. Campos permitidos: nombre visible, cargo, departamento, misión, personalidad, responsabilidades, entregables, competencias/propuestas, CV y superior. IDs, permisos, nombres runtime legacy y prompts no son campos editables directamente. Las competencias manuales siguen siendo objetivos no acreditados. Las ediciones son atómicas; el motor recalcula subordinados, profundidad, auditorías, prompts y validación de ciclos/máximo de reportes.

La jerarquía manual se conserva al guardar/cargar y al refrescar disponibilidad de modelos. Aplicarla al libro BFS se bloquea expresamente; puedes exportarla desde la app o restablecer jerarquía automática mediante una acción explícita. No se cambia silenciosamente su superior para encajar en Excel.

## Subequipos, Council y mejora

`subteam-save` crea/edita por ID grupos `audit` o `consulting`, con nombre, alcance, miembros y facilitador. Máximo 16 por diseño. El facilitador es un vínculo funcional, no otro supervisor. Todos los miembros cuentan dentro de N. La afiliación se incorpora a los prompts exportados, sin otorgar independencia de auditoría ni permisos automáticos. Las versiones anteriores del grupo se conservan en history.

Council crea actas manuales mediante `council-create`, añade hechos/riesgos/objeciones/propuestas/decisiones mediante `council-add-entry`, y cierra con `council-close`. Cada entrada está marcada `origin=manual_entry`, `recorded_by=user`, `verified_agent_run=false`. Cerrar no acredita que N agentes deliberaran; se muestran las contribuciones faltantes y `runtime_council_complete=false`.

`skill-register` y `skill-update` mantienen propuestas versionadas con evidencia declarada. Incluso `approved_manual` conserva `installed=false` y `verified=false`. `remediation-create` y `remediation-update` exigen secuencia de propuesta, pruebas declaradas, supervisor y revisor independiente antes del cierre registrado. Se rechaza autoría propia/conflicto jerárquico para independencia. Esto documenta la revisión del usuario; nunca simula tests ejecutados ni eficacia comprobada por un harness.

## Cobertura del repositorio

Inventario `balanced`: 20 archivos/250000 bytes por defecto. Perfil `deep`: 60/750000; máximos100/1000000. Cualquier ampliación requiere `budget_confirmed=true` como confirmación de alcance de lectura. Hay concurrencia acotada (3, máximo4), selección diversa determinista y caché en memoria por repo/commit/blob. `coverage` distingue inventario observado, truncado, archivos leídos/no leídos, módulos/familias y huecos. Ninguna lectura parcial se presenta como auditoría completa. El consentimiento LLM posterior muestra el resumen exacto y no autoriza a ejecutar el código del repositorio.

## Pruebas de la aplicación

`python -m unittest tests_app_backend -v` cubre versiones, no guardado de claves, confirmación para cargar cambios sin guardar, integridad, symlinks, edición manual, jerarquía conservada, frontera Excel, referencias manuales, subequipos y bloqueo de ZIP si una clave de la sesión aparece en el contenido. Esas pruebas son offline y no reemplazan prueba visual RDC ni Windows COM.

## Selección de modelos desde la web

`model-overrides` recibe `{assignments:{agent_id:{provider?,model?}},expected_state_version?}`. Sustituye el mapa completo de overrides; un campo omitido hereda, y quitar la entrada devuelve ese agente a selección automática. Sólo acepta agentes actuales y rutas de proveedor mapeadas. Actualiza modelos/prompts/versiones sin regenerar los CV ni alterar el árbol manual.

`model-preferences` recibe `{preferences:[{provider,model,user_rank?,capabilities?}],expected_state_version?}`. Actualiza las preferencias declaradas del catálogo y recalcula únicamente rutas automáticas; una preferencia no convierte un modelo desconocido en disponible. Los overrides manuales siempre prevalecen. Las capacidades son descriptores, no benchmarks. Las versiones obsoletas se rechazan sin cambios parciales.
