# Exportaciones nativas, identidad e integridad

Los ejemplos proporcionados definen los formatos de archivo. Sus 21 o 3 agentes no sustituyen el equipo actualizado ni sus dos fases. La entrega mantiene el roster actual y sus perfiles completos dentro de `agents[].systemPrompt`; los permisos declarados están en `agents[].toolScope`. Los sidecars añaden inspección y trazabilidad, sin convertirse en claves inventadas del JSON DSH.

## Archivos principales

- `agent-team-backup-YYYY-MM-DD.json`: `agent-team-gui/definitions`, versión 2. La fecha es la fecha UTC del instante `exportedAt`. Contiene una sola lista compartida de agentes y los squads de implementación y Council.
- `agent-team-recipe-<UUID-del-squad>.json`: `agent-team-gui/recipe`, versión 1. Contiene el squad de implementación y los mismos agentes.
- `extras/agent-team-recipe-<UUID-del-Council>.json`: recipe adicional opcional del Council. No es otro formato principal. El backup ya contiene esta fase.

Los sufijos `(1)` y `(2)` que aparecen en los ejemplos son nombres de copias locales del navegador. El exportador usa el nombre nativo sin esos sufijos. El UUID de una recipe identifica su squad; **no es un hash SHA-256**. El nombre histórico `AGENT_TEAM_*_N.json` se conserva en el mapa de preservación como origen, pero no se duplica como un segundo export principal.

La plantilla offline actual conserva sus identidades heredadas cuando se genera en modo compatible. Una organización nueva generada por API utiliza su identidad nueva. La elección de roster e identidad es del generador; el exportador no copia agentes de los archivos de referencia ni convierte una plantilla offline en un resultado de IA.

## Un snapshot para todas las descargas

`engine.export_artifacts.build_export_snapshot(org, base_recipe=None, exported_at=None)` captura un único `exportedAt` en milisegundos UTC. Devuelve bytes congelados de los dos JSON principales, la recipe Council y el manifiesto. Reutilizar ese snapshot asegura que descargas separadas y archivos dentro del ZIP son idénticos byte por byte, incluso si el usuario los descarga en momentos diferentes.

El caché se vincula a `organization_fingerprint(org)`, un SHA-256 de la revisión estructural del sidecar. Los registros privados de ejecución, evaluaciones y reservas no forman parte del export. Una edición de la organización invalida el snapshot anterior. Reconstruir con la misma organización, ancla base e instante explícito produce los mismos bytes JSON; el ZIP también depende de los archivos runtime y de la plantilla Excel incluidos. El motor conserva los bytes del ZIP final junto al snapshot, sin recalcular sus hashes contra otro build.

Las rutas HTTP de compatibilidad `implementation.json`, `definitions.json` y `council.json` pueden conservarse para enlaces existentes, incluidos los de Excel. El nombre de descarga que indica `Content-Disposition` es siempre el nombre nativo del snapshot actual.

## Qué comprueban los hashes

`agent-team-export-manifest.json` es un documento separado de OrgDNA. Enumera nombre, ruta dentro del ZIP, formato, versión, longitud en bytes y SHA-256 exacto de cada JSON DSH. No añade campos `sha256`, `dna`, `provenance` ni otros metadatos a los esquemas estrictos de DSH. El ADN esencial se expresa en el prompt de cada perfil.

Los hashes se calculan sobre los bytes UTF-8 finales, sin BOM y con salto de línea LF final. El manifiesto no incluye su propio hash ni el hash del ZIP: hacerlo crearía una dependencia circular. `MANIFIESTO_SHA256.txt`, dentro del ZIP, cubre los archivos del paquete salvo ese propio manifiesto. El hash del ZIP, si se muestra o entrega por separado, se calcula después de cerrar el archivo.

SHA-256 permite detectar diferencias de bytes. No es una firma de autor, ni prueba que un proveedor respondió, que los agentes se importaron, que un skill está instalado o que el software del proyecto funciona.

## Verificación portable

Ejecutar `python validate_imports_portable.py` desde la carpeta extraída, o pasar la ruta de un ZIP. El validador detecta exactamente un backup y una recipe principal por sus patrones nativos, comprueba sus nombres contra `exportedAt` y los UUID reales, revisa la recipe Council, los hashes de los bytes y la coincidencia del equipo compartido. También verifica el catálogo documental, la allowlist runtime, los prompts, el visor y el mapa de los 42 archivos históricos. No ejecuta el repositorio ni llama a proveedores.

El libro Excel distribuido es una plantilla. La descarga no guarda ni sincroniza implícitamente un libro abierto. El estado declarado de generación distingue una plantilla offline de un diseño obtenido por API; las pruebas con proveedores simulados no demuestran una llamada real.

## Autonomía y Plan Preview

El esquema permanece compatible con los ejemplos aportados, pero sus valores de comportamiento pueden cambiar por la configuración más reciente. Con el backend `teams_gui`, el preset autónomo usa `activationMode=always`, `triggerMode=guaranteed` y `planningContext=full`; implementación mantiene `adaptive`, `parallel`, `fork` y un máximo de tres miembros simultáneos. Council selecciona todos los miembros del equipo para deliberación de sólo lectura. Los modos manual o smart siguen siendo elecciones explícitas. Con `agentteams_native`, los squads GUI permanecen pasivos (`manual`/`model-tool`, sin quality gate GUI) para que AgentTeams sea el único orquestador; cambiar de backend conserva perfiles e IDs y actualiza la revisión del diseño. Un proyecto heredado puede conservar valores anteriores; `IMPORTAR_LEEME.txt` muestra los valores exactos realmente presentes en ambos squads del snapshot.

Los límites `tokenBudget`, `memberTimeoutMs`, `handoffSummaryMaxChars` y `qualityGate`, cuando se configuran y están soportados, ocupan únicamente sus campos nativos reconocidos. Su presencia no prueba que el host los haya aplicado. `plannerMaxTokens=8192` limita esa planificación, no garantiza un coste máximo en USD ni disponibilidad de saldo. Según el host y el modo elegido, cada mensaje puede consumir tokens, incluido un saludo.

`PLAN_PREVIEW_TAREA.txt` es una tarea específica del repositorio para copiar en Plan Preview. No se inventa una clave JSON `previewTask`; el contexto operativo esencial también queda en `systemPrompt` y `collabNote`. Importar un archivo guarda las definiciones: todavía se necesita seleccionar el equipo, una sesión compatible y acceso real al repositorio/modelos/herramientas.

El saludo inicial presenta el equipo y sus capacidades declaradas y propone un plan verificable. Para ArbitrageX, la meta económica en mainnet y beneficio neto real en USD se tratan como objetivo sujeto a evidencia, costes y riesgos, sin promesa de rentabilidad. Un saludo, el nombre de un preset o la importación de un archivo no autorizan movimientos de capital, firmas, transacciones ni publicación. La autorización necesaria para cada acción sigue siendo independiente de la configuración de autonomía.
