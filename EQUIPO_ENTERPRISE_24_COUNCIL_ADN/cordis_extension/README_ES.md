# Cordis: ampliación aditiva del mismo equipo

Este cartucho conserva el UUID de organización, los UUID de todos los perfiles y
los UUID de los squads. No crea otra plantilla ni un segundo motor de agentes.
La aplicación genera el cartucho; descargarlo no lo instala ni lo activa.

## Qué está implementado

- Plugin nativo Cordis `apply(ctx, config)`, dependencia `tools`, definiciones
  reales con `defineTool` de `@deepseek-ai/dsh-tools` y limpieza `ctx.effect`.
- Seis herramientas con prefijo único de UUID completo: consulta, mensajes,
  tareas de coordinación, evidencia, memoria y aprendizaje compartido.
- Almacén JSON local aislado por organización, escritura atómica, versión CAS,
  idempotencia, auditoría y bloqueo de doble proceso. No contiene claves API.
- Los mensajes se consultan en el bus. El bus no despierta sesiones ni inicia
  solicitudes a modelos. El estado de tareas es un registro de coordinación;
  el scheduler de DSH/AgentTeams sigue siendo el único ejecutor.
- La evidencia registra localizador y SHA-256 declarado. El plugin no lee el
  artefacto ni acredita que la prueba haya ocurrido. Las propuestas de aprendizaje
  pasan revisión independiente y nunca instalan código o entrenan modelos.
- Variantes JSON nativas en `extended-native/` añaden los seis nombres a las
  allowlists explícitas, respetan todos los deny y el máximo de 256. Los JSON
  originales permanecen iguales. Los perfiles con herencia conservan esa política.

Es coordinación y conocimiento compartido, no consciencia ni garantía de ausencia
de fallos. El contenido de otros agentes es dato no confiable, nunca una instrucción
capaz de elevar permisos o autorizar acciones externas.

## Compatibilidad real y límites

La interfaz nativa está revisada contra DSH Tools 0.2.1-alpha.1, commit oficial
5badb15009ae1756c3afe0ae0cef1faafc290ccc. Esto no certifica la versión instalada.
La pantalla antigua `Cordis plugins`/`ready to activate` corresponde a otro flujo;
este cartucho NO se pega en `cordis_define` ni usa sus APIs legacy.

Se probaron además composiciones reales y sin claves con Cordis 4.0.5-alpha.1,
Tools/SystemPrompt 0.2.1-alpha.1; y por separado Cordis 4.0.4, Tools 0.0.1-rc.1
y SystemPrompt 0.0.1-rc.5. Pasaron registro, validación, 24 mensajes de identidades
de prueba y limpieza conservando otra herramienta. Son pruebas de bibliotecas,
no 24 modelos en ejecución ni verificación del DSH del usuario. Una versión de
paquete SDK no debe presentarse automáticamente como versión del host completo.
También pasó el registro completo de coordinación con Tools/SystemPrompt
0.2.0-rc.2 y Cordis 4.0.4, la combinación del staging nativo revisado.

AgentTeams de NanmiCoder es distinto de `agent-team-gui`, cuyos JSON contienen los
perfiles. AgentTeams 0.1.22 declara como recomendado DSH 0.2.0-rc.2; su matriz
revisada no incluye 0.2.1-alpha.1. No actualizar, reinstalar ni migrar una instalación
que funciona para forzar este addon. El preflight debe identificar el par real y
adaptar/verificar los APIs antes de activarlo.

El `id` de `exec.agent` es un UUID de SESIÓN, no el UUID del perfil. La activación
requiere que el propietario verifique la relación sesión → miembro existente y
la incluya en `session_bindings`. Un nombre o rol remitido por un modelo no prueba
identidad. Las sesiones no vinculadas fallan sin cambios.

El helper `agentteams-adapter.mjs` revisa una correspondencia uno a uno de snapshot
sin leer ni escribir `.agent-teams`. El capitán cuenta dentro de N: para N=24 son
un capitán y 23 compañeros, nunca 24 más uno. Un snapshot manual no demuestra una
conexión viva ni autentica la procedencia. No reanuda equipos detenidos.

Importante: el código fuente revisado de `agent_teams_status` despierta el scheduler
cuando lo invoca el capitán y marca mensajes como leídos. No se utiliza como
sondeo estrictamente de lectura. Tampoco expone UUID de sesiones de miembros.
La conexión local opcional exige un adaptador host real con capacidades verificadas;
si el host no ofrece lectura segura de perfiles y pertenencia, queda bloqueada.

## Activación manual, reversible y aditiva

1. Revisar `addon-manifest.json`, `dry-run-report.json`, `scope-diff.json` y hashes.
   Mantener intactos el perfil DSH, proveedores, plugins y ajustes existentes.
2. Situar la carpeta del addon donde pueda resolver las dependencias del DSH
   revisado, por ejemplo dentro de un checkout del host. No ejecutar `npm install`
   a ciegas: puede instalar un segundo core incompatible. Este paquete no lleva
   scripts de instalación ni intenta instalar dependencias.
3. En el addon plano, ejecutar `node preflight.mjs`; en una distribución que
   conserva la subcarpeta, ejecutar `node cordis_extension/preflight.mjs` desde
   su raíz. Encuentra el manifiesto junto al script o en la raíz superior de
   ese layout; las dependencias siempre se resuelven desde la carpeta real del
   plugin. Sólo lee metadatos. Un resultado BLOCKED_ACTIVATION/código 2 significa
   que falta verificar el runtime vivo, no que la comprobación haya activado nada.
   Versión ausente o distinta bloquea activación.
4. Crear una copia de `addon-config.example.json` DENTRO de la carpeta del addon.
   Elegir un directorio absoluto exclusivo para datos del addon. Añadir los UUID
   reales de sesiones verificadas como claves de `session_bindings` y los UUID de
   perfiles existentes como valores si se usa activación manual. Una sesión por
   miembro; no inventar sesiones. Con el panel nativo se permite comenzar con
   `session_bindings:{}`: seguir el orden de arranque descrito abajo.
5. Tras revisión humana de permisos y alcance, poner `enabled: true` y
   `confirm_activation: "ACTIVATE_EXISTING_ROSTER_ONLY"` sólo en esa copia.
6. Ejecutar `node prepare-overlay.mjs addon-config.reviewed.json addon-overlay.yml`.
   Crea un archivo nuevo o falla si ya existe. No modifica `cordis.yml`, perfiles,
   settings, providers ni otros plugins. La ruta del plugin será absoluta.
7. Sólo tras comprobar compatibilidad, usar el mecanismo aditivo documentado del
   host: `pnpm dsh web --patch /ruta/absoluta/addon-overlay.yml` en el checkout
   revisado. Es un ejemplo del host oficial, no una orden ejecutada por la app.
   No iniciar otra instancia sobre el mismo perfil/puerto. En Desktop, usar su
   flujo documentado de plugins sólo tras autorización y diagnóstico exactos.
8. Confirmar que las herramientas están realmente registradas antes de revisar
   una importación de los JSON extendidos. Actualizar por los mismos UUID;
   nunca importar como copia ni reemplazar toda la biblioteca DSH. Si el importador
   no muestra merge/update por identidad, detenerse y conservar la configuración.
9. Probar primero `..._state` con una sesión vinculada. Estado `MOUNTED` acredita
   sólo este plugin; no implica que perfiles, orquestador o automatización hayan
   quedado conectados. No conceder herramientas ausentes a los miembros.

La conexión HTTP local, si se habilita expresamente mediante el adaptador incluido,
debe usar el emparejamiento efímero documentado por ese adaptador. Nunca copiar
cookies de DSH, claves de proveedores ni tokens a este ZIP. Desconectar debe
revocar la sesión local y cerrar el listener. Las operaciones no admitidas por un
seam verificado permanecen bloqueadas; no hay fallback de escritura a archivos.

### Conectar primero en sólo lectura

La lectura de la biblioteca Teams no requiere activar aún el ledger ni asignar
sesiones. En una copia del config dejar `enabled:false` y cambiar únicamente
`live_connection.enabled:true`; preparar el overlay nuevo como arriba. Así se
registra `/api/orgdna-local-connect` dentro de la Connection autenticada de DSH,
sin abrir todavía un puerto. Abrir esa ruta en el DSH local ya autenticado.

Pulsar allí “Autorizar lectura local durante 30 minutos”. Sólo entonces nace un
listener aleatorio en 127.0.0.1 y un código de emparejamiento de un solo uso y
120 segundos. Introducir puerto y código exclusivamente en el panel local de la
app; no pegarlos en chats, JSON de Teams ni repositorios. La sesión expira en
30 minutos como máximo. Revocar cierra el listener; no guarda credenciales.

Las capacidades son separadas: lectura de perfiles Teams, previsualización sin
importación, catálogo Cordis y estado AgentTeams cuando la lectura específica
esté verificada. `agentteams_state_root`, si se necesita, es una ruta absoluta
elegida explícitamente por el propietario dentro de `live_connection`. No se
buscan carpetas o cookies automáticamente. El adaptador lee el snapshot sin
editar `.agent-teams` ni invocar el status que despierta al scheduler.

Conectar en lectura no concede ejecución: envío de planes, importación efectiva,
mensajes con wake y eventos realtime permanecen no disponibles hasta disponer de
un adaptador nativo verificado y autorización específica. Los indicadores de
la app deben reflejar esa disponibilidad parcial, no “24 conectados” por inferencia.

### Orquestación nativa única y permisos por perfil

`native_orchestration.mjs` implementa la preparación y el staging por los APIs
reales `agent_teams_create` con `approval:required` y `agent_teams_edit_plan`.
El capitán ocupa uno de los N perfiles; para N=24 se preparan 23 compañeros,
con alias estables derivados de los UUID y su `execution_prompt` completo.
No se truncan prompts. No se admiten tareas de capitán en el plan inline porque
esa forma nativa sólo acepta nombres de compañeros como assignee.

El modo `agentteams_native` exige squads de Teams pasivos/manuales. La UI nativa
debe mostrar y ligar la aprobación a un hash del plan exacto, identidad de capitán,
snapshot actual de Teams, permisos añadidos y pruebas de que no hay ejecución
GUI activa ni otro equipo nativo. Crear el borrador no autoriza Approve & Run.
El helper no llama approve/resume y no cambia los archivos de configuración.
Si el enriquecimiento falla después de crear, el equipo queda staged: reparar
ese mismo borrador, sin crear otro. Los recibos no afirman agentes ejecutados.

El hook `agent/created` es serial y previo a la primera petición del host revisado.
Lee exclusivamente el descriptor nativo oculto al modelo, su parentSession, alias,
provider/model y presencia del prompt completo. Registra `agent.ctx.tools.restrict`
y `guard` en el ámbito del compañero, nunca globalmente. Así preserva los allow/deny
de Teams como restricciones monotónicas junto con las políticas nativas. Los cuatro
tools de gestión de miembros y los tools de capitán añadidos figuran explícitamente
en el plan; un deny manual incompatible bloquea en vez de quitarse.

El capitán también tiene su contrato: debe ser la sesión existente revisada, usar
exactamente la ruta provider/model de su perfil y recibir el prompt y las restricciones
en su propio ámbito. La app no cambia el modelo para forzar coincidencia. Sin esa
validación, el staging falla y no declara N perfiles aplicados.

El hook requiere un plan íntegro aprobado fuera de los argumentos del modelo.
`native_orchestration.enabled` permanece false en el cartucho generado. La interfaz
nativa registra aprobación temporal, no una concesión permanente de acceso.
Detener el trabajo nativo antes de descargar el hook de permisos; retirar un plugin
retira sus efectos temporales. Un tool genérico de shell puede realizar muchos
tipos de escritura: la allowlist no es un bloqueo de rutas del filesystem ni una
prueba de que todas las modificaciones estén aisladas.

AgentTeams limita los compañeros mediante su configuración existente `maxMembers`.
Su valor por defecto es 8. Un equipo de N=24 necesita que esa instalación permita
al menos 23 compañeros, además del capitán. El cartucho no aumenta ese límite ni
reescribe la configuración: si no alcanza, la preparación nativa falla y exige
una decisión explícita del propietario. La prueba nativa aislada usó un host de
pruebas con límite 23; no acredita el límite del equipo del usuario.
El preflight lee el valor validado del plugin ACTIVO mediante el registro público
Cordis y bloquea como CAPACITY_LIMIT o CAPACITY_UNVERIFIED. No deduce la capacidad
de una captura de pantalla ni toma el valor por defecto como prueba del valor real.

### Panel de revisión nativa de la app

Para habilitar el panel, usar `native_stage_ui.enabled:true` en la copia del
config del addon y proporcionar `native_stage_ui.agentteams_state_root` como
directorio absoluto explícito. Mantener `native_orchestration.enabled:false`:
el panel administra los hooks revisados y no se debe montar una segunda copia.
La lectura emparejada conserva sus permisos de sólo lectura.

La app recibe el enlace del panel únicamente si DSH ha confirmado su registro.
El panel consulta los perfiles SSOT y capitanes realmente vivos, limita el roster
al UUID de organización y miembros del cartucho, comprueba el modo pasivo de todos
los squads relacionados y exige el capitán inactivo. No vacía ni cancela su trabajo
para forzar disponibilidad. La aprobación de staging es de un solo uso y caduca
en 120 segundos. Cambiar perfiles o plan invalida la revisión.

Tras “Autorizar preparación nativa”, el servidor nativo ejecuta create/edit a través
del registro real de herramientas con su pipeline, sin fabricar tokens de llamadas
de modelo. Se utiliza la barrera pública de mantenimiento de la sesión capitán.
El plan queda pendiente de una aprobación DISTINTA para ejecutarlo en AgentTeams.
La petición de lectura desde la app no puede aprobar, reanudar ni enviar mensajes.
Los tools de modelo approve/resume quedan denegados por el hook de staging.

#### Orden de arranque sin bindings previos

1. Generar las variantes integradas en modo `agentteams_native` y revisar sus
   mismos UUID. En la copia local del config elegir un directorio absoluto para
   datos del addon y dejar `session_bindings:{}`. Poner `enabled:true`,
   `confirm_activation:"ACTIVATE_EXISTING_ROSTER_ONLY"`,
   `native_stage_ui.enabled:true` y su directorio AgentTeams explícito.
   Habilitar `live_connection.enabled:true` si se usará la app conectada.
2. Preparar el overlay nuevo y cargarlo una sola vez. Se registran las seis
   herramientas antes de restringir perfiles. Con cero bindings, cualquier llamada
   de agente a ellas falla con UNBOUND_SESSION; no se concede identidad provisional.
3. Verificar las herramientas registradas. Revisar/importar las variantes
   integradas mediante actualización de los mismos UUID, con Teams en modo pasivo.
   La conexión de lectura y la consulta de perfiles/capitanes del panel nativo
   funcionan sin binding de coordinación. No ejecutar los squads de Teams.
4. Elegir en el panel el Captain existente, su perfil y el roster exacto. Revisar
   el plan completo y autorizar únicamente su preparación. Esa acción autenticada
   verifica la sesión, vincula el Captain al ledger e instala los hooks y límites.
   Un error de capacidad, identidad o permiso bloquea; no se aumenta maxMembers.
5. El borrador sigue sin miembros ejecutados. Sólo una aprobación posterior en
   AgentTeams autoriza su ejecución. Cuando nazca cada sesión, el hook nativo
   verifica descriptor/padre/alias y la vincula al mismo perfil del ledger.

No hace falta inventar ni copiar por adelantado los UUID de futuras sesiones.
Fuera del panel nativo, la activación de coordinación sigue exigiendo al menos
un binding manual revisado. Este arranque no abre otra ruta de aprobación ni
permite llamadas de coordinación sin una identidad verificada.

## Desactivación y recuperación

- Descargar el plugin mediante el mecanismo del host o reiniciar sin ESTE `--patch`.
  Los disposers retiran sólo las seis herramientas propias; no tocan las ajenas.
- Conservar los datos para inspección. El cartucho no borra el historial al salir.
- Restaurar la variante base de toolScope por los mismos UUID si se aplicó la
  variante extendida. No eliminar nombres desconocidos de otros plugins.
- Un cierre abrupto puede dejar `active.lock`. Nunca se roba automáticamente.
  Comprobar que no hay proceso vivo usando ese almacén, respaldar la carpeta y
  revisar el PID antes de retirar exclusivamente ese lock. No tocar locks de DSH.
- Un ledger corrupto o perteneciente a otro roster bloquea. No lo sobrescribe ni
  migra silenciosamente. Guardar copia y reconciliar los miembros explícitamente.
- Los hashes detectan modificaciones accidentales; no son una firma de confianza
  frente a quien puede reemplazar tanto código como manifiesto.

## Pruebas y alcance de verificación

`node --test cordis_extension/tests/*.test.mjs` desde el proyecto comprueba el
ledger, aislamiento, permisos de identidad y ciclo de vida con registro simulado.
Dentro del ZIP extraído, usar `node --test tests/*.test.mjs`; no instala dependencias.
`python -m unittest discover -s cordis_extension/tests -p 'test_*.py' -v` prueba
generación/identidad/allowlists/ZIP. No son una ejecución del DSH instalado ni de
Excel/Windows. No se realizaron instalación de plugins, inferencias pagadas,
reanudar equipos, importaciones ni cambios del equipo del usuario.

## SkillHub: publicación local/VPS y carga real son pasos distintos

1. `node skillhub-package.mjs --preview DESTINO VERSION` verifica los hashes del cartucho y muestra un directorio NUEVO `DESTINO/orgdna_UUID/VERSION`. No escribe nada.
2. Tras revisión, `--publish-reviewed` con los mismos argumentos copia exclusivamente ese directorio y verifica los bytes. Nunca reemplaza una versión, configuración, perfiles, historial u otros plugins. Conserva versiones previas como respaldo; devuelve `PUBLISHED_BYTES_VERIFIED_NOT_ACTIVATED`, jamás «instalado».
3. En el directorio publicado, ejecutar `skillhub-preflight.cmd "RUNTIME_ABSOLUTO"` en Windows o `sh skillhub-preflight.sh /runtime/absoluto` en Linux/VPS. Lee metadatos locales de DSH/SDK/AgentTeams, hash de entry y hashes del addon. No instala dependencias, no inicia procesos y devuelve pendiente (exit 2) aunque el inventario sea legible.
4. La carga real del addon es la composición Cordis del host con `entry.mjs` y config revisada, mediante el mecanismo de overlay que admita ESA versión de CLI, o la revisión/activación nativa soportada. Es imprescindible comprobarlo localmente antes de generar un comando. El relanzador original no reenvía `--patch`; no añadirle flags. `prepare-overlay.mjs` sólo prepara un archivo, no valida que el host pueda consumirlo ni lo carga.
5. Vincular los UUID existentes, habilitar explícitamente y usar una ruta absoluta + SHA256 para `skillhub-library.json`. Leer en el runtime el tool `orgdna_UUID_state` con `section=summary`: debe devolver la organización, el namespace y `skillhub.manifest_sha256` esperado; comprobar también el registro real de los seis tools y los perfiles actuales. `section=skills` devuelve asignaciones paginadas; `section=skill_context` devuelve únicamente referencias activas del miembro autenticado, con presupuesto UTF-8 (máximo 12000 bytes). Ninguno concede permisos.
6. Los conectores de correo, mensajes y voz siguen en `BLOCKED_AUTH_AND_HEALTH`: requieren paquete revisado, scopes explícitos, health readback y autorización separada para comunicaciones. Una skill, README, código de salida cero o declaración del modelo no prueba instalación, activación ni capacidad. NativePluginManager requiere revisión nativa separada; el cartucho no lo invoca silenciosamente.
7. Para revertir archivos, desconectar antes el addon activo en el runtime nativo. `node skillhub-package.mjs --rollback-preview DIRECTORIO_DE_VERSION` verifica el recibo y todos sus hashes. `--rollback-reviewed` elimina sólo esa versión si permanece intacta; si hay archivos ajenos o modificados se niega. No desactiva plugins ni restaura configuración porque nunca la modificó.

Los scripts no usan sudo, npm install, servicios, credenciales ni llamadas pagadas. La versión real, el mecanismo de carga y el readback del runtime local permanecen pendientes hasta obtener el diagnóstico del equipo destino.

### Actualizar una biblioteca activa sin recrear agentes

La aplicación Python expone `build_skillhub_delta(base,target,organization)` (preview), `apply_skillhub_delta(path,delta,organization,approve=True)` (publicación explícita) y `request_skillhub_reload(path,delta,organization,approve=True)` (solicitud de recarga explícita y separada). El delta conserva todos los UUID e incluye add/remove/update, destinos, base_hash, target_hash, requisitos y reversión. Los hashes del delta usan JSON UTF-8 con claves ordenadas, indentación 2 y newline final; no comparar contra otra serialización.

La primera operación usa lock exclusivo y compara el hash antes del reemplazo atómico; conserva backup por hash. Esto coordina escritores que respetan el lock, no proporciona CAS de sistema operativo contra un editor externo que lo ignore. La segunda sólo escribe `skillhub-reload.json` junto al manifiesto dentro de `orgdna_UUID`. Configurar previamente `skillhub.reload_receipt_path` como opt-in local a esa ruta exacta.

El addon ya cargado consulta el recibo al leer state, verifica base/target, scope, identidad y contenido, y cambia únicamente su snapshot en memoria. Publicar bytes sin recibo no autoriza recarga; una consulta no crea recibos ni archivos. Confirmar en state.summary el nuevo `manifest_sha256` y `reload_request_id`. Es recarga de biblioteca/contexto, nunca instalación de plugins, cambio de toolScope, autenticación ni modificación global. Un recibo adulterado/stale falla cerrado.

Para reversión, preparar el delta inverso, publicar el snapshot anterior por el mismo CAS y solicitar su recarga explícitamente. La configuración inicial hash-pinned se actualiza aparte mediante revisión nativa antes de reiniciar el host; el addon no reescribe configuración de DSH. Recarga en vivo no implica recuperación automática tras restart. El recibo es una instrucción del operador local con acceso al directorio; no es una firma criptográfica ni una defensa contra un host comprometido.

Desde la raíz de la aplicación local o VPS (Python instalado), los comandos ejecutables son:

- Preview: `python -m engine.capability_deployment preview-delta --base base.json --target target.json --organization organizacion.json`
- Publicar tras revisar: `python -m engine.capability_deployment publish-delta --base base.json --target target.json --organization organizacion.json --manifest RUTA_ABSOLUTA/orgdna_UUID/VERSION/skillhub-library.json --reviewed`
- Solicitar recarga explícita: mismo comando sustituyendo `publish-delta` por `request-reload`. Sin `--reviewed`, ambos sólo muestran preview.

No se ha ejecutado ninguno sobre tu DSH. `request-reload` termina en `RELOAD_REQUESTED_READBACK_PENDING`, no en activado. El estado vivo y su hash los debe confirmar el addon ya cargado.
