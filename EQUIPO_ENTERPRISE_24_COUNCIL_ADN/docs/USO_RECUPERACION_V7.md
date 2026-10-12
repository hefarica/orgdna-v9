# Estado e instalación de la candidata V7

**CANDIDATA V7. Chromium real: NOT_RUN. Aceptación E2E pendiente.**
Se entrega para inspección con sus comprobaciones offline y sus límites explícitos.

## Actualización segura

1. Guarda el proyecto y detén sólo OrgDNA. No reinicies DSH ni cambies su configuración.
2. Respalda la carpeta anterior completa y extrae este ZIP en una carpeta nueva.
3. Con OrgDNA cerrado, copia `data/projects` completa al mismo lugar de la carpeta nueva, incluyendo `_capabilities`, bases SQLite y auxiliares presentes. Si ya existen proyectos en destino, respalda ambos lados y evita sobrescribirlos.
4. No copies claves API, credenciales, tokens o sesiones. Ejecuta `launch.cmd` con Python 3.10 o posterior.
5. Comprueba nombre, número de perfiles y diseño del proyecto; guarda y vuelve a abrir. Conserva el respaldo hasta verificarlo en tu equipo.

La ampliación de pruebas ya está incorporada: 92 casos Chromium escritos, todos NOT_RUN, y matriz de 403 filas (179 con comprobaciones escritas; 224 de verificación manual específica). No acredita cobertura completa ni ejecución real. El informe externo `VALIDACION_ORGDNA.txt` distingue la evidencia anterior y la comprobación de este ZIP. El resto de esta guía mantiene las instrucciones funcionales V7.

# OrgDNA V7: generar, reintentar y recuperar

Esta guía complementa el material V6. El manual V6 conserva su contenido histórico y no se presenta como actualizado.

## Antes de generar

1. Abre el proyecto y comprueba la fuente, el número de perfiles, el proveedor y el ID exacto del modelo. Una etiqueta de DSH puede diferir del ID que acepta una API.
2. Guarda tu trabajo. En la configuración de generación puedes ajustar **Tokens máximos de salida por solicitud**, **Perfiles por solicitud** y **Formato de respuesta**. El modo **Texto con JSON · compatibilidad** omite `response_format`, pero exige JSON válido y los mismos controles del diseño.
3. Pulsa **1. Preparar ADN con IA**. Preparar muestra la cobertura observada, el contenido, el proveedor/modelo, las solicitudes y los límites efectivos antes de transmitir el contenido al proveedor.
4. Revisa el plan completo. Marca la única casilla de autorización del plan y pulsa **Autorizar este plan y generar**. Esta aprobación sólo sirve una vez para ese contenido y presupuesto. Los límites de tokens no garantizan un tope de dinero.

Reducir los perfiles por solicitud puede aumentar la cantidad de solicitudes y el coste. Aumentar tokens no garantiza que el modelo pueda aceptarlos. Revisa siempre los valores efectivos del plan; no se sustituye automáticamente el proveedor ni el modelo elegido.

Límites de estos controles: salida solicitada entre 4.096 y 131.072 tokens, con 16.384 por defecto; perfiles por solicitud entre 1 y 32 o automático. El plan aplica los límites declarados del modelo y como máximo 16 solicitudes. Un plan que no cabe se rechaza antes del envío. Estos valores son límites de la aplicación, no una garantía de capacidad o precio del proveedor.

## Si la generación falla

- Lee la etapa y el código del diagnóstico. El mensaje distingue errores del transporte/proveedor, respuestas incompletas o malformadas y fallos de validación cuando existe evidencia para hacerlo. No atribuyas una causa concreta a un mensaje genérico.
- Usa **Descargar diagnóstico JSON** si necesitas revisar el informe local. No incluye la API key ni la respuesta cruda del proveedor.
- Corrige lo que indique el diagnóstico y pulsa **Preparar otro intento · sin cargo de IA**. Este paso prepara un plan nuevo; un reintento requiere revisar y autorizar nuevamente las solicitudes. No hay reintentos de pago ni cambios de modelo automáticos.
- Un plan nuevo vuelve a generar el diseño completo; no reanuda silenciosamente los lotes parciales del intento fallido. El diagnóstico separa las solicitudes iniciadas de las completadas y validadas; un intento iniciado puede facturarse aunque no produzca perfiles válidos.
- Cancelar evita nuevas solicitudes y descarta resultados pendientes. Una solicitud que ya se envió puede tener coste aunque después falle o se cancele.

## Recuperar el diseño conservado

Si una configuración pendiente impide exportar y hay un diseño anterior recuperable, el panel **Tu diseño conservado** muestra qué configuración se recuperará. Revisa sus efectos y pulsa **Restaurar configuración y diseño**. La configuración que estabas probando queda como borrador pendiente; el diseño válido y sus ediciones manuales se conservan.

Tras restaurar, revisa el diseño antes de descargarlo. **Retomar configuración pendiente** vuelve al borrador y puede bloquear las exportaciones hasta completar una nueva generación válida o volver a recuperar el diseño anterior. Guardar la misma configuración no debe invalidar un diseño vigente.

La recuperación depende del estado disponible en el proyecto o sesión; no reconstruye un diseño privado perdido desde el ZIP histórico. El contexto del último diseño válido se conserva entre sesiones sólo cuando se guarda explícitamente el proyecto; un diseño sin guardar sigue dependiendo de la sesión abierta. Guarda el proyecto después de comprobar el resultado.

## Conexión DSH y alcance

Este parche se concentra en generación, diagnóstico y recuperación. No incluye cambios de puertos, emparejamiento, addons, arranque DSH, credenciales ni configuración DSH. La entrega conserva los archivos de conexión, harness, launcher y Cordis, y comprueba por separado las secciones DSH de los archivos compartidos. Recuperar un diseño dentro de la sesión conserva el enlace DSH de esa sesión; esto no promete trasladar una conexión efímera al cerrar o sustituir la aplicación.

El snapshot incluido sigue siendo el equipo histórico de 24 agentes, con sus mismos JSON, IDs, prompts y Excel. No sustituye los proyectos privados guardados. Las pruebas del paquete usan fixtures locales; no demuestran inferencia real con tu proveedor ni la salud de tu DSH instalado.

Consulta `qa_recuperacion_v7.md` para las pruebas y límites de esta entrega. Para repetir la comprobación estructural del ZIP: `python validate_imports_portable.py` desde la carpeta extraída. Para la regresión autocontenida V7: `python -m unittest discover -s qa_v7 -p 'test_*.py' -v`, `node qa_v7/recovery_dom.cjs` y `node qa_v7/frontend_recovery_dom.cjs`. Los dos últimos usan DOM simulado, sin Chromium.

La suite preparada para Chromium se documenta en `CHROMIUM_E2E.md`. Su presencia no equivale a haberla ejecutado: el estado comprobado figura en el informe QA. Un candidato con Chromium pendiente no es una entrega con E2E real validado.
