# OrgDNA V7: diagnóstico y recuperación de generación

Actualización acotada sobre el ZIP V6 entregado. Conserva los 62 archivos históricos protegidos: organización de 24 agentes, IDs, ADN, prompts, importables, plantilla Excel y documentos de ese snapshot. Los hashes y el catálogo documental se recalculan para reflejar el runtime actualizado. El manual V6 permanece histórico; la guía nueva es `USO_RECUPERACION_V7.md`.

## Generación y diagnóstico

- Configuración explícita del tamaño de lote, límite de salida y formato de respuesta antes de preparar el plan.
- Diagnóstico estructurado y acotado de fallos de proveedor/transporte, formato y validación. Las categorías conocidas no sustituyen la evidencia del fallo concreto.
- Un único envoltorio externo de bloque JSON puede retirarse sin alterar su contenido, dejando una señal de auditoría; las referencias de evidencia siguen validándose contra lo leído.
- Informe local de diagnóstico sin claves ni cuerpos crudos del proveedor.
- Reintentos manuales mediante un plan nuevo y una autorización nueva; sin reintentos de pago ni cambio de proveedor/modelo silenciosos.

## Recuperación y autorización

- Un cambio de configuración conserva el diseño válido disponible y permite restaurar su configuración tras una acción explícita.
- El borrador de configuración pendiente puede retomarse después; los exports permanecen bloqueados mientras el diseño no corresponda a la configuración activa.
- Guardar una configuración idéntica no invalida el diseño.
- Una sola aprobación revisable cubre el plan de generación exacto y sus solicitudes acotadas. Cambiar el plan invalida esa aprobación.

## Preservación de DSH

Los módulos de conexión DSH, harness, launcher, relanzador y Cordis se conservan byte a byte frente a V6. Los cambios en `bridge.py` y `app.js` se limitan a generación/recuperación y se verifican las funciones, handlers y rutas protegidas de DSH. Este trabajo no ha operado sobre el PC del usuario, reiniciado DSH, cambiado puertos ni instalado o activado addons.

Las pruebas realizadas, sus recuentos y los límites figuran en `qa_recuperacion_v7.md`. Un PASS local con fixtures no acredita la causa del error visto por el usuario, inferencia real del proveedor ni ejecución del DSH instalado.
