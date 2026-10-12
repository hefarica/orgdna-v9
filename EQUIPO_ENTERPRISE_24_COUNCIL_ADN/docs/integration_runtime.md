# Integración de OrgDNA, Teams, AgentTeams y Cordis

## Responsabilidades

- **OrgDNA local:** analiza el repositorio, propone una organización, valida perfiles y genera artefactos. La generación por API requiere una clave introducida localmente y consentimiento sobre contenido, destino y presupuesto. La plantilla offline se identifica como tal.
- **Teams (`dsh-agent-team-gui`):** biblioteca de definiciones de perfiles y formatos Recipe v1 / Definitions v2. No se confunde una definición con una sesión en ejecución.
- **AgentTeams (`@nanmicoder/dsh-agent-teams`):** motor nativo de tareas, miembros y Captain cuando se selecciona ese backend y sus interfaces necesarias se han verificado.
- **Cordis:** aloja las herramientas y el adaptador adicional. El addon utiliza un espacio de nombres propio y conserva los identificadores de la organización.
- **Plugin Shop:** descubrimiento y comparación de extensiones. Un resultado del catálogo no acredita seguridad, compatibilidad ni instalación.

## Un equipo y un ejecutor

El número solicitado incluye al líder. Un diseño de 24 perfiles no se convierte en un Captain más 24 integrantes. Los identificadores de definición, los identificadores de sesión y los identificadores de tarea son distintos y su correspondencia debe tener procedencia comprobable.

En el modo `teams_gui`, los squads de implementación y Council son dos fases que comparten perfiles. En el modo `agentteams_native`, Teams sirve como catálogo y sus squads quedan pasivos para evitar un segundo despacho paralelo. La autonomía de la organización no justifica ejecutar ambos motores a la vez.

El addon no crea ni reanuda silenciosamente una ejecución existente. Una ejecución detenida continúa detenida hasta una acción nativa explícita permitida. Las capacidades no verificadas aparecen como pendientes o no disponibles.

## Qué hace una importación

Los dos JSON nativos contienen perfiles, CV ficticios de capacidades objetivo, mando, instrucciones, permisos y contratos dentro de campos que admite DSH. No incluyen propiedades nuevas en la raíz para fingir compatibilidad. Importar esos JSON **no instala código ejecutable** ni activa automáticamente el addon.

La aplicación puede preparar un paquete Cordis y una variante extendida de las definiciones con los mismos IDs. Antes de usar los nuevos nombres de herramientas en una allowlist, el addon correspondiente debe estar disponible en la sesión. Se revisan versiones, servicios, colisiones y permisos; se conserva una ruta de reversión. No se deben sobrescribir perfiles o archivos de configuración completos para añadir la extensión.

## Enlace local

El puente utiliza emparejamiento explícito y temporal, destinos loopback limitados y comprobación de identidad, protocolo, versiones y capacidades. No reutiliza cookies del navegador ni incluye credenciales en los artefactos. Cargar la aplicación, un proyecto o un ZIP no equivale a conectarse a DSH.

Las lecturas y vistas previas no prueban que existan capacidades de escritura o despacho. El cliente sólo debe mostrar una capacidad operativa cuando el adaptador la anuncie y compruebe; una llamada no soportada debe producir un resultado explícito. Consultar el estado no debe activar un scheduler ni consumir mensajes por accidente.

## Coordinación y latencia

El Council admite deliberación de los participantes del diseño y las reservas de edición limitan a tres los escritores coordinados. Una reserva cooperativa no impide que un editor externo la ignore. El buzón durable del addon tampoco equivale, por sí solo, a despertar sesiones nativas de AgentTeams.

Se distinguen latencia de transporte, espera en cola, ejecución de herramientas, respuesta del modelo y confirmación del resultado. Las mediciones Python/Node de loopback con dobles de servicios sólo describen ese ensayo; no certifican DSH, el equipo Windows del usuario ni el tiempo de inferencia de un proveedor. Véase el informe de validación entregado y, cuando esté incluido, `docs/dsh_loopback_benchmark.json`.

## Objetivo y evidencia

Para ArbitrageX, el objetivo incluye despliegue mainnet, operación con capital real y beneficio neto realizado en USD después de costes. Es un objetivo que debe demostrarse, no una ganancia certificada por generar perfiles. Un saludo solicita presentación y propuestas; no constituye una orden de transferencia de fondos.

Toda afirmación distingue configuración propuesta, pruebas locales, observaciones de una sesión conectada y resultados de ejecución. Memoria compartida, revisión y aprendizaje registrado son mecanismos de ingeniería; no demuestran conciencia ni ausencia absoluta de fallos.

## Referencias de las interfaces

- [DSH: plugins Cordis](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/index.md)
- [DSH: inspección Cordis](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/tool-cordis/README.md)
- [DSH: Plugin Manager](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md)
- [AgentTeams](https://github.com/NanmiCoder/dsh-agent-teams)
- [Teams GUI](https://github.com/toolclub/dsh-agent-team-gui)
- [Plugin Shop](https://github.com/LivXue/dsh-plugin-shop)

Estas referencias explican las interfaces estudiadas. No sustituyen la inspección de la versión instalada. Instalar plugins puede modificar el perfil y ejecutar código Host; deben conservarse las aprobaciones nativas y la revisión de scripts de dependencias.


## Integridad y reproducción desde el paquete

`agent-team-export-manifest.json` comprueba los bytes exactos de las descargas base y de sus copias dentro del ZIP. El archivo del addon `base-native-normalized-sha256.json` tiene un alcance distinto: hashes de objetos reconstruidos y serializados por el builder, no de los bytes originales subidos. Preparar el addon no altera las dos descargas principales. Sus variantes `extended-native/` son opt-in, conservan IDs y deny, y nunca deben truncar una allowlist para cumplir el límite de 256.

El runtime principal incluye únicamente archivos enumerados de código, guías, fuentes citadas y pruebas. No incluye los paquetes instalados para pruebas SDK, `node_modules`, configuraciones del usuario, ledger, bindings vivos, códigos, tokens ni la caché completa del catálogo remoto. El builder se comprueba contra esa lista explícita para que no falten dependencias al extraer el paquete.

Pruebas reproducibles desde la carpeta principal extraída:

- `python validate_imports_portable.py`
- `node --test cordis_extension/tests/*.test.mjs`
- `python -m unittest discover -s cordis_extension/tests -p 'test_*.py' -v`
- `python -m unittest discover -s tests -p 'test_dsh_connection.py' -v`
- `python tests/benchmark_dsh_loopback.py benchmark-local-result.json`

El destino separado del benchmark conserva la medición distribuida y su hash. Los fixtures identificados como tales no contactan a DSH ni a proveedores. Las pruebas SDK adicionales requieren una ruta explícita a dependencias oficiales previamente revisadas; el paquete no las instala. Para el recorrido de emparejamiento y activación, consultar `docs/dsh_connection.md` y `cordis_extension/README_ES.md`.


### Evidencia adicional con paquetes oficiales

`docs/dsh_native_connection_sdk_smoke.json` registra composición real del SDK de Connection/Cordis con almacenamiento y registro de herramientas de prueba; no una aplicación DSH completa. `docs/native_agentteams_stage_smoke.json` separa el staging real de los paquetes oficiales AgentTeams/DSH de los perfiles, sesiones y consentimiento inertes utilizados como fixtures. Comprueba preservación de prompts completos, rutas y restricciones antes de ejecutar modelos; no acredita llamadas a proveedores, aprobación nativa del usuario ni spawn real de subagentes.

Los scripts de reproducción están incluidos y requieren dependencias oficiales exactas ya revisadas en un directorio aislado. No utilice la instalación o el estado de producción para estos ensayos. Sus etiquetas, campos `actual_*` y lista de aspectos no verificados forman parte de la evidencia; no deben omitirse al resumir los resultados.
