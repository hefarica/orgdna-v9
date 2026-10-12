# V8 y el prompt de planificación aportado el 10 de octubre

La V8 implementa el parche aprobado en la conversación. El prompt posterior es
una referencia de evaluación y planificación, no una ampliación automática del
alcance ni autorización para inferencias pagadas, cambios en DSH o dependencias.

## Implementado en esta actualización

- ID de API comprobado y separado del nombre visible y de referencias DSH.
- Verificación ligada a la credencial actual; rechazo de aprobación obsoleta.
- Límites del catálogo preservados al usar alias del mismo proveedor.
- Recibos seguros por solicitud, con usage nullable, incluso al fallar o cancelar.
- Descarga diagnóstica y conservación de historial al guardar el proyecto.
- Prioridad de subsistemas, sustitución acotada de archivos descartados y paquetes
  comunes/específicos; validación de referencias contra el contenido del lote.
- Presentación separada de estimaciones, límites y uso real observado.
- Formatos de exportación existentes y configuración/conectividad DSH conservados.

El informe de validación externo determina qué verificaciones PASS, FAIL o
NOT_RUN acompañan al ZIP exacto. La presencia de una prueba no acredita su ejecución.

## Parcial o fuera del parche actual

| Propuesta | Estado de V8 |
| --- | --- |
| Catálogo offline persistente con TTL y expiración | No implementado. No debe atribuirse a la caché de repositorio. |
| Ledger inmutable y durable antes de cada envío | No implementado. Los recibos están en memoria y se conservan al guardar el proyecto o descargar diagnóstico. |
| Preservar body de error sanitizado | Se conservan campos tipados/reconocidos; no se guarda cuerpo remoto arbitrario. La causa histórica del HTTP 400 continúa sin confirmación. |
| Grafo AST/dependencias y centralidad real | No implementado. La selección de rutas/familias es heurística. |
| Fragmentos de archivos mayores de 40 KB | No implementado; permanecen como huecos explícitos. |
| Backoff, circuito y reintentos pagados automáticos | No añadidos. Los intentos nuevos siguen requiriendo autorización exacta. |
| Cambio de niveles de autonomía o restricciones de todo el equipo | No incorporado. Este parche no reescribe la política ni configuración DSH existente. |
| Garantía económica o límite duro USD | No ofrecido. Presupuestos de referencia, tokens máximos y costes reales son conceptos distintos. |
| Prueba pagada contra DeepSeek | NOT_RUN. |
| Chromium real e importación en DSH del usuario | NOT_RUN. |

## Criterios para una fase posterior, si se solicita

Una ampliación requeriría definir retención y recuperación del ledger, caducidad y
procedencia del catálogo, límites de lectura fragmentada, y adaptadores por lenguaje
para el mapa de dependencias. Debe preservar el consentimiento por envío y los
formatos de importación. No requiere introducir Docker ni reinstalar DSH.

El piloto con un número menor de agentes es opcional y separable de la configuración
N=30. Las pruebas sintéticas de N=30 verifican estructura/exportaciones, no calidad
semántica de treinta perfiles producidos por un proveedor real.
