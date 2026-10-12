# Plugin Shop: descubrir, inspeccionar y preparar una instalación

La app incorpora un buscador de candidatos del catálogo público de dsh-plugin-shop. Puedes buscar cualquier entrada que exista en ese catálogo, comparar su origen y versión, vincularla con capacidades del equipo e imprimir un plan de instalación versionado. No se instala DSH ni ningún plugin, no se llama al gestor nativo y no se modifica el perfil actual.

## Flujo en la app

1. Actualiza el catálogo cuando quieras consultar su edición actual. Abrir la app, generar perfiles o exportar el paquete no dispara esta consulta.
2. Busca por nombre, tecnología o capacidad. El orden depende de coincidencias descriptivas; no convierte estrellas o popularidad en confianza.
3. Inspecciona el candidato. Para npm se consulta el manifiesto de la versión exacta. Para GitHub se consulta el manifiesto en el commit exacto y se verifica su blob. Para una entrega tarball se contrasta la entrega y su asset; su manifiesto y los bytes del archivo siguen pendientes de revisión nativa. Nunca se sustituye la entrega por la rama actual.
4. Prepara el plan para un perfil aislado. El predeterminado es `orgdna-isolated`: es un destino propuesto, no un perfil creado o comprobado. Revisa manifiesto, scripts, dependencias, compatibilidad, conflictos, copias y recuperación.
5. Si decides instalar más adelante, conserva el plan y usa el gestor nativo autorizado sobre el perfil exacto. Debes verificar el esquema y la versión del DSH que realmente tienes.
6. Puedes registrar aprobación y resultados del operador. Son reportes locales, no certificación de que el runtime realizó esas acciones.

La aplicación no contiene un ejecutor de instalación ni un botón para activar plugins. Las consultas públicas no requieren API keys ni envían el repositorio o los perfiles al catálogo.

## Catálogo real y proveniencia

La fuente implementada es GitHub Pages:

- Índice: <https://livxue.github.io/dsh-plugin-shop/v1/index.json>
- Proyecto y otros canales de distribución: <https://github.com/LivXue/dsh-plugin-shop>
- Esquema revisado: <https://github.com/LivXue/dsh-plugin-shop/blob/9700bebb638f490b0ab70689bb8fc1249b1274e8/docs/schema.md>

El upstream también distribuye `dsh-plugin-shop-catalog` mediante npm. Esta integración utiliza el JSON estático de GitHub Pages, no descarga ni ejecuta el paquete npm del catálogo. Las versiones de plugins npm se inspeccionan en el registro público oficial.

El índice consultado durante la validación tenía 13.950 entradas, fecha `2026-10-06T17:06:40.911Z` y SHA-256 `58c8672fc03c76240314cf13230a844331e19529635c52f4be539ed29387eb6f`. Se comprobaron los 12.882.783 bytes y se normalizaron las 13.950 entradas. Esto es una observación histórica, no un recuento fijado en el código. El catálogo completo no se incluye en el paquete.

Cada candidato conserva fuente, repositorio/subdirectorio, versión, integridad declarada del paquete, hash de la entrada y hash/fecha del catálogo. Un nombre igual en dos forks no implica identidad igual. Una edición nueva no hereda los reportes de otra versión. Que los bytes coincidan con el hash del índice no demuestra autoría criptográfica, seguridad del código ni integridad de un tarball que todavía no se descargó.

## Límites de red y datos no confiables

El módulo acepta únicamente la fuente enumerada `github_pages`, sin URLs configurables. Exige un nombre exacto `plugins.<sha256>.json`, limita tamaños y recuentos, comprueba índice y contenido, rechaza claves JSON duplicadas/números no finitos y no sigue redirecciones. Las inspecciones construyen URLs públicas a partir de identidades validadas. Los enlaces contenidos en la metadata no conceden permiso para hacer nuevas consultas.

El transporte de producción reutiliza la conexión TLS de `engine/providers.py`: comprueba IPs públicas y conecta a la IP validada sin segunda resolución, sin proxy implícito y sin enviar credenciales. En este entorno cloud la prueba de ese transporte informó `No se pudo resolver el endpoint.` Se verificó el contenido público mediante la vía de investigación y se probó el módulo sin red con fixtures. No se debilitó la protección para ocultar el bloqueo. Una actualización fallida debe mostrarse como fallida; conservar una copia anterior no la vuelve actual.

La app no interpreta texto del catálogo como instrucciones, no ejecuta JavaScript/JSON, no hace `eval`, no lanza subprocesses y no escribe archivos desde este módulo. La metadata se muestra como texto no confiable. Las capacidades son declaraciones del autor, no permisos efectivos ni una barrera de seguridad.

## Compatibilidad y confianza

`compatibility.status` y `trust.status` permanecen en `UNVERIFIED`. Se conserva por separado la categoría de revisión que publica el catálogo (`community`, `verified` o `verified-stale`). Esa categoría no es una auditoría de OrgDNA. La comparación SemVer definitiva, las dependencias reales, el funcionamiento del bundle y los permisos deben comprobarse en la versión y el perfil del runtime.

El wishlist cruza perfiles y señales del proyecto con grupos de capacidades y nombres/descripciones del catálogo de herramientas. Expone quién necesita cada capacidad, herramientas declaradas relacionadas y candidatos concretos con su motivo. `DECLARATION_GAP` significa que no se identificó una herramienta declarada por esta heurística; no prueba que falte en el runtime. `RUNTIME_COVERAGE_UNVERIFIED` tampoco prueba cobertura. Las sugerencias están siempre en `PROPOSED_NOT_TESTED`.

## Plan de instalación y cambios persistentes

El plan incluye un `request_id`, pines exactos, una lista de comprobaciones, bloqueos pendientes, aprobaciones necesarias y posibles cambios persistentes. Sus comprobaciones utilizan `NOT_RUN`, `UNVERIFIED` o estados equivalentes, nunca un PASS inventado.

La copia previa debe incluir `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `cordis.patch.yml` y `compatibility.json`, registrar cuáles no existían y verificar hashes/lectura. Después de cualquier fallo se debe comprobar la restauración del estado y de las dependencias, la recomposición o reinicio y el funcionamiento anterior. Restaurar manifiesto y lockfile no revierte por sí solo efectos arbitrarios de scripts o cambios externos.

Fuente oficial de comportamiento: <https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md>. El Host del plugin no queda contenido por el sandbox de workspace. Un cambio de perfil puede afectar todas sus sesiones. La autorización de scripts es separada y puede persistir incluso si una instalación falla. `enabled:false` expresa una intención de no seleccionar inicialmente el bundle; no evita por sí mismo scripts de instalación ni sus efectos.

Esquema del tool revisado: <https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/src/tools.ts>. El tool usa `target`, no `spec`. Sus acciones incluyen `list_bundles` e `install_bundle`; no expone una acción `inspect` ni un argumento `requestId`. Las operaciones `inspect`, `installBundle`, `waitForInstall` y `cancelInstall` son APIs del servicio. El plan distingue ambos contratos; no utiliza el servicio para eludir la aprobación del tool. No solicita cambiar el modo global de permisos ni crea exenciones de compatibilidad.

## Estados de evidencia

`proposal → inspected → approved_by_operator → test_reported → active_reported`

- `proposal`: entrada real del catálogo.
- `inspected`: metadata pública exacta contrastada; el tipo de inspección señala si falta el manifiesto del tarball.
- `approved_by_operator`: el operador registró aprobación para identidad y versión concretas. Esto no sustituye la aprobación nativa ni activa permisos.
- `test_reported`: el operador adjuntó referencia de evidencia y resultado `passed`, `failed` o `blocked`, con request, perfil y versión del runtime.
- `active_reported`: sólo se registra tras un test reportado `passed`, con el mismo request, perfil y runtime. Sigue siendo un reporte no verificado por la app.

En todos los estados, `runtime_verified`, `installed` y `active` permanecen en false. No se permiten saltos de estados ni convertir un resultado fallido en activación. Un nuevo intento o una nueva versión necesita una propuesta/revisión nueva.

## API de módulo

- `empty_catalog()` no accede a red.
- `fetch_catalog(source='github_pages', *, transport=None)` consulta y verifica el catálogo.
- `parse_catalog(index, payload, *, source='github_pages', fetched_at=None)` valida bytes sin red; seam para pruebas offline.
- `get_candidate(catalog, candidate_id)` devuelve una copia por identidad exacta.
- `search_catalog(catalog, query='', *, capabilities=None, limit=30)` devuelve resultados acotados, motivo y total.
- `inspect_candidate(catalog, candidate_id, *, transport=None)` consulta metadata pública exacta.
- `create_installation_plan(candidate, *, profile='orgdna-isolated', runtime=None, request_id=None)` genera el plan sin ejecutar.
- `transition_candidate(candidate, status, *, evidence=None)` valida y registra un reporte.
- `capability_wishlist(organization, catalog, *, tool_catalog=None, limit=20)` propone capacidades y candidatos.

`transport` es exclusivamente una inyección de código confiable para pruebas, con la firma de `engine/providers.py`. No es una opción recibida por HTTP ni una URL de usuario. El bridge debe conservar el catálogo completo sólo en memoria; la respuesta pública debe ofrecer metadata, resultados acotados y el candidato seleccionado. Guardar el proyecto no debe copiar el catálogo remoto ni secretos. La restauración de un proyecto nunca debe convertir reportes en permisos activos.

Validación offline: `python -m unittest tests_plugin_shop -v`. Los fixtures sintéticos se identifican por `@fixture/` y no forman un catálogo ofrecido al usuario. Las pruebas locales no certifican el navegador, una instalación nativa DSH ni compatibilidad con el equipo real.
