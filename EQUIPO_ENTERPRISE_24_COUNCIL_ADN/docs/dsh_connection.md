# Conexión local OrgDNA ↔ DSH

## Qué está implementado

El adaptador es código ejecutable: cliente Python, servidor local Node y una pantalla de emparejamiento servida por el registro nativo autenticado de DSH. No se ha conectado al DSH ni al ordenador del usuario. Las pruebas de transporte usan procesos Python y Node reales con dobles explícitos de los servicios de Teams.

El addon no abre un puerto por cargarse. Si el operador habilita `live_connection.enabled`, registra únicamente `/api/orgdna-local-connect` dentro del servicio nativo `connection.fetch`. El usuario abre esa ruta en el mismo origen de su DSH, tras iniciar sesión normalmente. Un clic en «Autorizar lectura local durante 30 minutos» abre un puerto aleatorio en `127.0.0.1` y muestra un código de un solo uso válido durante 120 segundos. Se introduce ese puerto y código en OrgDNA. No se piden claves de proveedor ni credenciales en chat.

El cliente comprueba protocolo, nonce, identidad de instancia UUID, versiones, permisos aprobados, capacidades y vencimiento. Después verifica el token recibido mediante un segundo handshake. «Conectado» se refiere a esa instancia emparejada del addon, no demuestra por sí solo la identidad de sesiones de agentes ni que toda la organización pueda ejecutarse.

## Capacidades y límites

- `Teams / agentTeamGui`: lectura real de `readDefinitionSnapshot()`. Los IDs son identificadores de definición; nunca se convierten automáticamente en IDs de sesiones.
- Importación: vista previa de `previewDefinitionsImport(document, 'merge', signal)` o `previewRecipe(document, {}, signal)`. No aplica importaciones, no llama `previewPlan()`, no ejecuta un plan y no solicita inferencia a un modelo.
- Cordis: lectura de nombres de herramientas mediante `tools.schemas()`. Un nombre registrado no implica permiso para ejecutarlo.
- AgentTeams: lectura opcional de `team.json` desde una ruta absoluta seleccionada expresamente por el operador. Es observación del estado almacenado con contrato de esquema fijado; no autentica sesiones vivas. No se busca automáticamente el directorio `.agent-teams`, no se escribe en él, no se leen ni reconocen mensajes de buzones, no se invoca `agent_teams_status`.
- Envío de planes y mensajes desde la app, y eventos en tiempo real: capacidades no disponibles en este adaptador de lectura. AgentTeams sí dispone de su mensajería nativa; el registro compartido del addon no equivale a esa entrega. La preparación autorizada se ofrece en una pantalla nativa separada, descrita abajo.
- Una preparación de plan devuelve `BLOCKED_CAPABILITY` y un hash; una confirmación de ese hash no habilita una función inexistente.
- El lector no crea equipos, recrea miembros ni reinicia trabajos. La pantalla nativa separada puede preparar un plan expresamente aprobado sólo si el capitán no participa ya en un equipo.

Los controles del backend que emparejan o consultan son acciones explícitas. Las lecturas reutilizan HTTP/1.1 keep-alive y el estado público usa una copia local fechada cuando no se solicita actualización. No hay sondeo periódico oculto. Un fallo de verificación invalida la conexión; revocar elimina la autoridad efímera.

## Compatibilidad verificada por código

Se permiten pares coincidentes de `@deepseek-ai/dsh-tools` y `@deepseek-ai/dsh-client-connection` en `0.2.0-rc.2` o `0.2.1-alpha.1`; versiones desconocidas se rechazan. La lectura de Teams requiere `dsh-agent-team-gui` 1.3.0 y los métodos públicos comprobados. La observación de archivos requiere `@nanmicoder/dsh-agent-teams` 0.1.22 y una ruta explícita.

Esto verifica interfaces concretas, no certifica una combinación completa de plugins. La matriz de AgentTeams 0.1.22 incluye DSH 0.2.0-rc.2, pero no el posterior 0.2.1-alpha.1. Teams 1.3.0 tiene sus propias dependencias de versión. La aplicación conserva `SOURCE_SEAMS_CHECKED_FULL_PLUGIN_COMBINATION_UNVERIFIED` hasta una validación real independiente. El `latest` de npm puede apuntar a 0.0.1-rc.1; esa versión antigua de Connection usa otra interfaz y no es equivalente a 0.2.0.

## Preparación nativa separada, con revisión explícita

Cuando el addon tiene habilitada `native_stage_ui`, la pantalla `/api/orgdna-native-stage` se registra dentro de Connection autenticado. La app muestra su enlace únicamente cuando el handshake de esa instancia publica la URL verificada. Emparejar el lector no concede autoridad de escritura: revisar y autorizar la preparación ocurre en DSH.

La pantalla toma una instantánea coherente de Teams. La organización y el conjunto exacto de IDs deben coincidir con el manifiesto del addon. El usuario elige un squad, un perfil de capitán y una sesión nativa existente, y revisa el objetivo, tareas, prompts completos y permisos. Los squads relacionados tienen que estar en modo manual. No se crea otra fuente de perfiles.

La autorización se vincula al hash exacto del plan y a un nonce de un uso que vence en dos minutos. Cambiar el formulario invalida la revisión; respuestas tardías no sustituyen el plan revisado. Antes de preparar se vuelven a comprobar perfiles, identidad del capitán, ausencia de otro equipo, estado de Teams y capacidad real de AgentTeams. Un historial de 200 filas, estados desconocidos o una ejecución activa impiden declarar inactividad.

La capacidad se lee del registro público de Cordis y de la configuración validada de la única instancia activa de AgentTeams. No se infiere por un valor predeterminado ni por el formulario. Una organización de 24 incluye al capitán y requiere 23 compañeros; el valor predeterminado de AgentTeams es 8. Si faltan capacidad o evidencia, se muestran `CAPACITY_LIMIT` o `CAPACITY_UNVERIFIED`; no se modifica la configuración.

La sesión capitán debe estar realmente inactiva y conservar el proveedor/modelo revisados. Su `runMaintenance()` nativo mantiene esa frontera mientras `ToolRuntime.execute()` ejecuta únicamente:

1. `agent_teams_create` con `approval: 'required'`, para dejar un plan preparado sin sesiones de miembros.
2. `agent_teams_edit_plan`, para incorporar los prompts completos de Teams.

Los permisos se restringen en el contexto nativo del capitán y, para futuros miembros, mediante el evento nativo y descriptores de sesión verificados. El plan muestra las herramientas de coordinación añadidas. Los rechazos explícitos se respetan. No se fabrica un token padre, no se llama directamente a la implementación de una herramienta y no se elude el pipeline de aprobación. Un modo PTC que rechace el llamado permanece bloqueado.

La pantalla nunca llama approve, run o resume. El helper impide aprobación/reanudación automática desde las herramientas del capitán. El usuario conserva la aprobación posterior de ejecución en la interfaz nativa de AgentTeams. Mantenga el addon cargado mientras sus agentes estén activos.

Si ya existe un equipo para el capitán, se conserva y se rechaza la creación; la pantalla no migra, reemplaza ni reinicia ese equipo. Un error después de crear el plan exige inspeccionar y reparar ese mismo plan preparado, nunca recrearlo automáticamente. El lector no demuestra por sí solo que la organización completa ya haya ejecutado un trabajo.

Esta pantalla admite las bibliotecas nativas exactas 0.2.0-rc.2, Teams 1.3.0 y AgentTeams 0.1.22, con interfaces públicas presentes. La combinación del usuario sigue pendiente de verificación local. `native_agentteams_stage_smoke.json` documenta por separado la prueba del helper con AgentTeams real; no constituye una prueba de ejecución de modelos ni del ordenador del usuario.

## Seguridad

- Solo dirección numérica `127.0.0.1`; puertos de usuario entre 1024 y 65535. No URLs arbitrarias, redirecciones, DNS, proxies o descubrimiento de puertos.
- El servidor valida Host y dirección remota; rechaza Origin, Fetch Metadata y cabeceras de reenvío en su API local. La pantalla nativa queda dentro de la autenticación y protección de origen de DSH.
- Código aleatorio de 256 bits, un uso y cinco intentos máximos. Sesión aleatoria de 256 bits, solo memoria y duración máxima de 30 minutos.
- Tokens y código no se guardan en proyecto, estado público, historial, manifiesto ni exportaciones. Respuestas públicas filtran campos sensibles, secretos con patrones reconocibles y el token/código activos. No existe un registro de cuerpos de solicitudes.
- Tamaños acotados, tiempos de espera, comprobación de archivo normal y rechazo de enlaces simbólicos en la lectura de estado. Esquema desconocido se rechaza.
- Revocar, descargar el addon, caducidad y fallos de verificación eliminan la autoridad local. La conexión no cambia las políticas de aprobación de DSH.

## Verificación reproducible

Desde la raíz del paquete:

- `node --test cordis_extension/tests/live_bridge.test.mjs cordis_extension/tests/native_stage_ui.test.mjs`
- `python -m unittest discover -s tests -p test_dsh_connection.py -v`
- `python tests/benchmark_dsh_loopback.py benchmark-local-result.json`

En el entorno de desarrollo también se ejecutó `python -m unittest discover -s qa_v3 -p test_dsh_connection_adversarial.py -v`; ese directorio de auditoría no forma parte del paquete portátil.

`dsh_loopback_benchmark.json` contiene percentiles medidos, entorno y alcance. Sus milisegundos corresponden al transporte local y a servicios simulados. No miden DSH completo, generación de modelos, entrega de mensajes, trabajo de agentes ni el ordenador del usuario.

## Fuentes fijadas

- DeepSeek Harness, `5badb15009ae1756c3afe0ae0cef1faafc290ccc`: [Connection nativo](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/client/connection/src/index.ts).
- Paquete oficial publicado `@deepseek-ai/dsh-client-connection@0.2.0-rc.2`: tipos `HostConnectionFetch`, `ConnectionFetchRoute`, `HostConnectionService`; autenticación `admit()` y `requestRejection()`.
- Teams, `14ea11960b20b1f93c33541ba9df7746ed16d08a`: [servicio de definiciones](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/tools/application/definition-service.ts) y [registro RPC](https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/rpc.ts).
- AgentTeams, `98aac03f46fc0aa19522c6f23a2b5bd08f9b1abd`: [herramientas](https://github.com/NanmiCoder/dsh-agent-teams/blob/98aac03f46fc0aa19522c6f23a2b5bd08f9b1abd/src/tools.ts), [estado](https://github.com/NanmiCoder/dsh-agent-teams/blob/98aac03f46fc0aa19522c6f23a2b5bd08f9b1abd/src/state.ts) y [tipos](https://github.com/NanmiCoder/dsh-agent-teams/blob/98aac03f46fc0aa19522c6f23a2b5bd08f9b1abd/src/types.ts).

## Prueba adicional con SDK oficial

`dsh_native_connection_sdk_smoke.json` registra una prueba de composición con los paquetes oficiales exactos Cordis 4.0.4 y Connection/Tools 0.2.0-rc.2. Se ejecutaron la firma y validación nativas de cookies, el filtro Host/Origin, el registro Fetch nativo, la pantalla de permiso, el arranque de producción del puente, su emparejamiento por loopback y la revocación. El almacenamiento de credenciales fue exclusivamente un doble en memoria y el catálogo de herramientas fue de prueba. No arrancó una aplicación DSH completa, Teams, AgentTeams ni un proveedor.

Para repetirla, instale usted previamente esos paquetes oficiales exactos en un entorno aislado y ejecute `node cordis_extension/tests/native_connection_sdk_smoke.mjs /ruta/al/sdk-aislado resultado-sdk-local.json`. La prueba no instala dependencias y no escribe credenciales en disco. No utilice el perfil o directorio de estado de una ejecución de producción para esta prueba.
