# Estado actual de la candidata V7

**CANDIDATA disponible para inspección. Chromium real: NOT_RUN. Aceptación E2E pendiente.**
El código funcional coincide con la ejecución offline descrita abajo. La única excepción de empaquetado amplía la lista literal RUNTIME_ALLOWLIST de engine/bundle.py para distribuir siete archivos nuevos. Su AST restante es idéntico.
Esta distribución incorpora además 92 casos de navegador escritos y una matriz de 403 filas (179 vinculadas a comprobaciones escritas; 224 de revisión manual específica), sin afirmar ejecución Chromium.
El informe externo `VALIDACION_ORGDNA.txt` identifica el hash del ZIP entregado y las comprobaciones posteriores a su extracción. Para instalar, consulta `USO_RECUPERACION_V7.md` y `../LEEME_V7_CANDIDATA.txt`.

## Registro histórico intacto de la congelación inicial V7

Los recuentos de 73 casos y 397 filas, y las expresiones sobre entrega bloqueada que siguen, describen aquella congelación anterior. Se conservan como historial; no impiden inspeccionar la candidata actual. Su aceptación E2E sigue pendiente.

# QA V7: diagnóstico y recuperación de generación

Estado: **PASS offline sobre fuentes congeladas. Chromium real: NOT_RUN. Entrega final bloqueada por E2E pendiente.** Este informe no certifica que toda la aplicación haya sido probada en un navegador.

## Ejecución congelada

Ventana: 2026-10-08 05:56:38–06:01:38 UTC. Los 20 grupos terminaron con código 0 y no cambió ningún archivo del manifiesto de fuentes durante la ejecución. SHA-256 del manifiesto de fuentes probado: `a061d90467316c20e5e9f654ac82143b03d484645391da351066d052c0c6d27a`. Este informe es el único documento derivado excluido de esa congelación; no cambia código funcional.

- 963 ejecuciones de pruebas Python históricas, conservando sus identificadores.
- 27 pruebas de regresión V4.
- 87 pruebas independientes V6.
- 35 pruebas independientes V7.
- 6 autocomprobaciones Python del fixture E2E.
- Total: 1.118 ejecuciones de pruebas Python; el recuento no implica que todos sus escenarios sean únicos.
- 64 pruebas de contratos Node, sin fallos, cancelaciones ni skips.
- Siete suites con DOM simulado: legacy, generación, launcher, capacidades, recursos/harness, recuperación independiente y recuperación del frontend.
- Seis comprobaciones sintácticas Node de archivos CJS E2E y enumeración de declaraciones de los casos preparados, sin importar Playwright ni ejecutar sus cuerpos.

## Cobertura comprobada de generación y recuperación

Las pruebas usan transporte y contenidos sintéticos controlados. Cubren diagnóstico acotado de respuestas del proveedor y errores de formato/validación; registro de solicitudes iniciadas frente a completadas; consentimiento exacto ligado a contenido, cobertura, modelo, límites, lotes y formato; prevención de replays obsoletos y dobles envíos; cancelación y respuestas tardías; reintento sólo mediante un nuevo plan aprobado; conservación del diseño válido; recuperación explícita y versionada; borrador pendiente y persistencia mediante guardado de proyecto.

El límite de salida solicitado es 4.096–131.072 tokens y el valor por defecto 16.384. El tamaño de lote se puede dejar automático o pedir entre 1 y 32 perfiles; el plan ajusta los valores efectivos a los límites declarados del modelo y no permite más de 16 solicitudes. Un valor declarado no demuestra disponibilidad o capacidad real de un proveedor. No se introducen reintentos de pago automáticos, cambio silencioso de proveedor/modelo/N ni publicación parcial de lotes fallidos.

Las pruebas HTTP reales se limitan a loopback Linux con servicios fixture. Verifican sesión, descarga de diagnóstico ligada a un único job_id, cabeceras de no-caché, disposición de descarga y protección CSRF de restauración. La recuperación conserva los bytes de las definiciones del diseño retenido. El diagnóstico no incluye claves ni el cuerpo crudo del proveedor.

Los dos fixtures DOM V7 comprueban, entre otros casos, una sola aprobación del plan, invalidación al cambiar opciones, bloqueo mientras hay una operación, reintento que prepara sin confirmar, descarga del job mostrado, restauración única ante dobles clics, reanudación del borrador y rechazo de respuestas de polling atrasadas. No comprueban píxeles, layout ni comportamiento del navegador real.

## Frontera DSH preservada

El guard independiente contra V6 pasa sobre 41 archivos completos de conexión, harness, launcher, relanzador, integración y Cordis. Compara además 14 secciones exactas de funciones JavaScript, 24 líneas de handlers DSH y tres ramas de dispatch del bridge. La comprobación del frontend también conserva su región HTML DSH. Los cambios del bundle son únicamente la lista explícita de archivos incluidos.

El empaquetado parte del ZIP V6 SHA-256 `76046fa7dc96b4c38589012b7ca2bc90ea87d41227f7e3890a2f60db44ccdb6d` y exige preservar sus 62 archivos históricos protegidos: organización de 24 agentes, identidades, ADN, prompts, importables, Excel y documentación histórica. No regenera ese equipo ni copia proyectos privados, SQLite de usuario, credenciales o conexiones vivas. Catálogo documental y manifiesto se recalculan. El informe externo que acompaña al candidato registra el hash del ZIP, su validación portable y la verificación independiente después de extraerlo, sin introducir autorreferencia en el archivo.

No se operó el PC del usuario, no se cambió la configuración DSH, no se reinició un proceso DSH ni se realizó un emparejamiento, importación o activación real. Conservar código y exports no acredita la salud actual de una instalación externa ni la continuidad de una conexión efímera al cerrar la aplicación.

## Chromium: preparado y aún no ejecutado

Se incluye una suite Playwright autocontenida con 73 casos escritos. Su matriz registra 397 filas de controles: 91 vinculadas a un caso de comportamiento escrito y 306 que requieren verificación manual específica. Todas las comprobaciones de navegador permanecen NOT_RUN. Las filas no son 397 funcionalidades independientes y su presencia estática no implica cobertura funcional.

Las seis autocomprobaciones del fixture, las comprobaciones de sintaxis y la enumeración de declaraciones no han iniciado Chromium. No existen capturas, trazas o resultados visuales que demuestren aceptación. Incluso pasar los 73 casos preparados no cubriría por sí solo todas las interacciones de la aplicación; `CHROMIUM_E2E.md` enumera los huecos y el procedimiento para una ejecución autorizada y aislada.

El bloqueo del navegador no se ha eludido. La entrega final sigue pendiente de pruebas reales de Chromium y de resolver los casos funcionales/visuales que correspondan. No se presenta este candidato como E2E completo.

## Límites de la conclusión

No se llamó a una API pagada o real, no se leyó un repositorio externo real durante esta QA, no se verificó Windows/Excel COM ni se instaló o ejecutó DSH del usuario. No se acredita la causa concreta del fallo que el usuario observó ni compatibilidad efectiva del modelo de su cuenta. Los fixtures verifican manejo local de escenarios representativos y mejor trazabilidad; no sustituyen evidencia del intento real.

El manual V6 se conserva como material histórico. Las instrucciones nuevas están en `USO_RECUPERACION_V7.md` y los cambios en `changelog_recuperacion_v7.md`.
