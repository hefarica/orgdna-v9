# OrgDNA: actualización de arranque y panel DSH

Esta entrega actualiza la aplicación del paquete anterior. Conserva sin regenerar las identidades, la organización, los prompts, los JSON importables, sus fechas de exportación y la plantilla Excel. El catálogo documental y el manifiesto SHA-256 se recalculan porque cambian archivos de aplicación.

## Cambios de aplicación

- Arranque local que comprueba la identidad de la instancia y el puerto antes de abrir el navegador. Recuperación ante un puerto ocupado o denegado; el enlace usa el puerto efectivo. Detalles y límites en local_startup.md.
- Panel para elegir un ejecutable de relanzamiento DSH local, revisar su huella SHA-256 y solicitar su ejecución manual. La operación requiere consentimiento explícito, confirmación de backup y control frente a solicitudes repetidas.
- El argumento de permiso de parada heredada es fijo y visible; elegir el archivo no lo ejecuta automáticamente. El panel no integra ni activa agentes por sí mismo.
- Se incluye una sola variante del relanzador recibido: fuente/DSH_REINICIAR.exe, situada en relanzador_dsh/DSH_REINICIAR.exe, con sus fuentes y procedencia. Se excluyen logs, receipts y el ejecutable raíz alternativo. La revisión estática está en dsh_launcher_source_audit.md; no se recompiló ni se ejecutó el binario en Windows.
- Un hash identifica los bytes elegidos: no acredita que un ejecutable desconocido sea seguro ni garantiza su comportamiento. La ejecución del archivo elegido depende de la aprobación del usuario y de su entorno local.
- Las pruebas de entrega y sus límites figuran en qa_arranque_v4.md. No se ejecutaron acciones en el equipo del usuario.

## Preservación

El ZIP conserva su snapshot base. Las variantes JSON integradas Cordis entregadas por separado y su add-on se conservan sin cambios; no deben confundirse con ese snapshot base. Ningún ID, prompt, permiso, modelo ni ajuste de los equipos entregados se regenera para esta corrección.

Descomprimir el paquete completo en una carpeta y ejecutar launch.cmd con Python 3.10 o posterior instalado. Revisar la guía de arranque antes de configurar una aplicación externa.
