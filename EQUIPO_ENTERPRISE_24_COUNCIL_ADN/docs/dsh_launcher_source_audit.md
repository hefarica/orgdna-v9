# Revisión estática del relanzador DSH 1.1.1

Fecha: 2026-10-07. Alcance: lectura del ZIP aportado, código fuente, recursos incrustados y hashes. No se ejecutó ningún EXE, script de la entrega, DSH ni operación en el ordenador del usuario. Los resultados Windows incluidos en el ZIP son evidencia del remitente, no una validación independiente actual.

## Resultado ejecutivo

El contrato permite reutilizar o reiniciar el perfil configurado y verificar su disponibilidad. No permite añadir el overlay OrgDNA por argumentos. Tampoco garantiza conservar argumentos de arranque adicionales de un DSH previo: en particular, un `--patch` previo no se propaga. El modo `--check-only` evita iniciar y cerrar DSH, pero escribe estado/configuración propia y realiza autenticación/API; no es una inspección estrictamente de solo lectura.

Hay dos ejecutables distintos. El de la raíz es un bootstrap que compila una fuente C# incrustada y utiliza una caché local. El de `fuente/` es el ensamblado .NET con `core.gz` incrustado directamente; su fuente revisada no utiliza esa caché de compilación. No se ha reconstruido ni comparado el IL del ensamblado con la fuente, ni auditado completamente el stub nativo del bootstrap.

## Integridad y contenido

ZIP SHA-256: `92efe1844ac87e69df24c9fcc1898e79c7e3777775d02f442e0e0bd66c2d1e8f`.

52 entradas, 297573 bytes descomprimidos. No se detectaron rutas absolutas, traversal, nombres con colon ni entradas symlink. Se leyeron entradas explícitas, sin extracción general ni ejecución.

Rutas relativas a `DSH_REINICIAR_ENTREGA_1_1_1/`:

- `DSH_REINICIAR.exe`: 41097 bytes; SHA-256 `a83195b0bc7d74587ca2b69f83123f81b441c0b80962077c63c1c8abcf27e1c2`.
- `fuente/DSH_REINICIAR.exe`: 52224 bytes; SHA-256 `c149d0bf8b7d7a14ce81f7008a6c8b98dc02aa78aecb708342138093eeeb3fd0`.
- `fuente/core.cjs`: SHA-256 `1384b5b46376f5f2ef53f7320fc1604dce4d099ac33a5166f9476765f6d0065a`.
- `fuente/Launcher.cs`: SHA-256 `4b3eb5d4a933f81773289f0418f91514c0d1df199668f7b62201d18674750253`.
- `fuente/app.manifest`: SHA-256 `5a6967b47b95486273ce6525058e9cf8dc2e443de67ad6572f944a33f230f956`.

El `core.gz` incrustado en el EXE de `fuente/`, localizado en offset 12612, coincide byte a byte con el recurso del ZIP, y su descompresión coincide con `core.cjs`. El SHA de core coincide con la constante de integridad C#.

Los últimos 31881 bytes del EXE raíz son el bootstrap JavaScript; SHA-256 `91c90e1b89cd96cfd96bb4f8d735ceed14dc8b5c9021d1b1fd92298ed34a601a`, igual al hash declarado por el cargador visible. El objeto comprimido de fuentes incrustadas tiene SHA-256 `4301f53c94638aad47b40ab89cabb41955bd0a8c48f254c58ffe22da3185aabd`. Su core y manifiesto coinciden con los del ZIP. Su C# tiene SHA-256 `d7882e621deda68e6b350a31a51d8d5ca9f963e3ca9d1d807dc2bb8b58d34b81`; difiere del C# externo exclusivamente porque este último añade la copia portable de respaldo en `InstallShortcut`. No hay diferencia en el contrato CLI ni motor.

Los hashes de C# externo y EXE .NET coinciden con `windows-validation.json` de la entrega. Esto demuestra consistencia del paquete, no una compilación reproducible o firma de confianza.

## Contrato de ejecución

Argumentos públicos aceptados: `--headless`, `--no-open`, `--check-only`, `--self-test`, `--reuse`, `--restart`, `--allow-legacy-stop`, `--elevated`. No hay argumento de config, perfil, home, puerto ni patch. `--probe <base64>` es un canal interno que admite también operaciones de cierre; no exponerlo al usuario ni tratarlo como un diagnóstico inocuo.

- Invocación recomendada para reinicio solicitado: EXE absoluto + `--headless --no-open --restart`, sin shell.
- `--restart` explicita la intención, pero no crea un modo distinto del valor predeterminado.
- `--reuse` reutiliza DSH si existe; si no existe, puede iniciarlo. No es de solo lectura.
- `--check-only` no inicia ni detiene DSH y falla con `DSH_OFFLINE` si está apagado. Crea estado propio si falta, puede crear config default, y escribe resultados.
- `--allow-legacy-stop` habilita una terminación forzada `Process.Kill()` de un único proceso identificado cuando no hay canal de cierre ordenado. Nunca incorporarlo por defecto; exigir decisión explícita con advertencia de datos en memoria y trabajos externos.
- `--headless` evita diálogo UI, elevación automática e instalación de acceso directo. `--no-open` evita apertura del navegador.

Root fijo: `%LOCALAPPDATA%\DSH_LAUNCHER`. Config: `launcher.json` directamente bajo root. Campos permitidos: `schema=1`, `home`, `profile`, `runtime`, `port`, `startupTimeoutSeconds`, `stabilitySeconds`, `openBrowser`, `shutdownTimeoutSeconds`, `idleWaitSeconds`, `restartDebounceSeconds`. Defaults: home `%USERPROFILE%\.dsh`; runtime `%USERPROFILE%\.dsh-vscode\server`; profile `web`; port 3080; timeouts 240/5/45/120/15 segundos respectivamente; openBrowser true. No sobrescribir un archivo existente ni presentar estos defaults como configuración real ya comprobada.

El motor establece `DSH_HOME`, inyecta un control de ciclo de vida con `--import`, elimina `NODE_OPTIONS` y `NODE_PATH`, y lanza en cwd runtime:

`node --import <preload propio> <runtime>/node_modules/@deepseek-ai/dsh/lib/bin.js --profile <profile> --host 127.0.0.1 --port <port> --no-open`

El Node se descubre en Program Files/PATH; no se garantiza preservar el Node ni todo el entorno del proceso anterior. La identificación bloquea por diferencias de executable Node, entry, perfil o puerto.

## Preflight, cierre, copias y verificación

Antes del cierre valida propietario de puerto, PID y fecha de creación, dependencias/bundles, espacio libre mínimo 256 MiB, autenticación existente, lista de sesiones con running booleano y dos lecturas idle, inventario dinámico persistente, inventario de archivos, fingerprint de configuración y nueva verificación de identidad. Nunca cancela turnos activos en esta fuente.

Cierre preferido: canal propio autenticado que invoca el handler SIGINT del CLI. Alternativa: CTRL_C sólo en consola privada. Última alternativa, únicamente con consentimiento legacy: Kill del PID verificado. Timeout de cierre conserva el proceso y no lanza un duplicado. El programa vuelve a comprobar si un supervisor inició reemplazo.

El checkpoint NO es una copia íntegra del historial: guarda lista de IDs/metadatos de archivos, copia `profile/package.json` y, si es menor de 16 MiB, estado de plugins dinámicos. No copia conversaciones, no dispara backups y no restaura automáticamente. Una comprobación posterior de presencia de archivos no prueba igualdad de su contenido.

Verifica auth 303→200, APIs de modelos/presets/sesiones/plugins, retención de IDs, inventario de archivos y estabilidad. Un fallo posterior al stop puede dejar el servicio apagado o iniciado parcialmente; no hay rollback automático. `automaticTaskResumption=false` no asegura que plugins particulares carezcan de efectos al arrancar.

## Resultado para el adaptador

Archivo fijo `state/last-result.json`, schema `hfrc.dsh.launcher.result.v2`, launcher `1.1.1`, `at` inicio ISO, `completedAt` fin ISO, status `CHECKING`, `READY` o `FAILED`. Campos condicionales: `errorCode`, `error`, `requestedAction` (`restart`, `check`, `open`), `action` (`restarted`, `started`, `reused`, `checked`), `pid`, `createdUtc`, `home`, `profile`, `port`, `entry`, `profileFingerprint`, `shutdownMethod`, `checkpoint`, contadores de sesiones/archivos.

No hay ID de operación. El mutex ocupado devuelve exit 0 y la línea `{"status":"ALREADY_RESTARTING","noDuplicate":true}`. Por ello rc0 no prueba éxito. Exigir un resultado nuevo y una ventana temporal coherente; tratarlo como informe del launcher, no prueba independiente ni vinculación causal fuerte. Otro proceso concurrente podría escribir el resultado fijo. No mostrar logs completos, URLs autenticadas ni estado de control con tokens. Renderizar exclusivamente campos allowlist sanitizados.

`LEGACY_RESTART_CONFIRMATION` exige un intento posterior con nueva confirmación; `SESSIONS_BUSY`, `PORT_FOREIGN`, `IDENTITY_PERMISSION`, `MULTIPLE_DSH`, `CONFIG_CHANGED_DURING_CHECK`, `SHUTDOWN_TIMEOUT`, `READINESS_TIMEOUT`, `HISTORY_NOT_RECONFIRMED`, `DYNAMIC_RESTORE_UNCONFIRMED` y `FILES_NOT_RECONFIRMED` deben permanecer fallos/bloqueos explícitos, sin kill/retry ciego.

## Límites del bootstrap raíz

Compila con el compilador .NET Framework local y requiere Node >=22. Utiliza `code/<sourceDigest>/DSH.Core.exe`; acepta el binario cacheado si `build.json` declara ese sourceDigest y el SHA coincide. Cambiar conjuntamente EXE cacheado y stamp puede satisfacer esta comprobación. El pin del EXE exterior no autentica por sí solo toda la caché. No borrar o reconstruir una caché desconocida automáticamente. El EXE .NET de `fuente/` no presenta esta ruta de caché en la fuente revisada, aunque sigue dependiendo de Node y paquetes DSH locales.

## Overlay aditivo OrgDNA: propuesta, no implementada

`cordis_extension/prepare-overlay.mjs` ya puede crear un nuevo YAML/JSON addon-only con creación exclusiva y configuración revisada. Esto no lo activa. El launcher original no añade `--patch` y rechaza un campo patch extra en launcher.json. Por tanto no afirmar que reiniciar con este EXE carga OrgDNA.

Para integración completa sin editar perfiles:

1. Verificar el parser CLI y la semántica de patch del runtime instalado: composición aditiva, orden, resolución y comportamiento con patches previos; contrastar entry/version reales, no sólo documentación de otra versión.
2. Crear un launcher DERIVADO separado, con nombre/version/hash propios, conservando intacta la entrega original y el launcher.json existente. Mantener configuración suplementaria propia.
3. Añadir argumento explícito de overlay de ruta absoluta y hash aprobado. Validar un overlay exclusivamente aditivo y el namespace/roster esperado; resolver entry del addon y sus dependencias antes de detener DSH.
4. Incluir overlay, contenido de config y archivos relevantes del addon en fingerprint. Copiar el overlay revisado a ubicación inmutable por operación y comprobar identidad/hash inmediatamente antes del spawn.
5. Incorporar el argumento `--patch` al spawn únicamente tras comprobar soporte; preservar o bloquear ante argumentos previos no representados, especialmente otros patches, en vez de descartarlos. Extender la identidad y reporte con hashes de overlay/runtime y ID de operación propio.
6. Verificar después la disponibilidad del namespace y APIs OrgDNA además de los checks DSH; readiness general no prueba addon cargado. Mostrar discrepancias y no modificar/restaurar perfiles automáticamente.

Esta derivación requiere implementación, pruebas unitarias/integración y validación local autorizada. No está realizada por esta auditoría.

## Empaquetado mínimo

Permitir los dos EXE identificados sólo como artefactos aportados con revisión estática limitada, el C# externo, core y app.manifest, más este informe y manifiesto de hashes. Identificar claramente que el C# externo no es idéntico al incluido en el bootstrap raíz. Para mayor transparencia puede incluirse la fuente C# extraída del bootstrap bajo un nombre inequívoco y su SHA, sin ejecutarla. Excluir logs, maintenance-pause, receipts, scripts de mantenimiento y fragmentos base64 no necesarios. No distribuir dichos datos como evidencia pública.
