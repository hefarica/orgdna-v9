# Validación independiente V5

Fecha: 2026-10-07. Suite ejecutada 20:15:04–20:17:26 UTC.

## Resultado de fuentes: PASS

- 756 pruebas Python: 722 de regresión histórica y funcional, 27 independientes V4 y 7 independientes de diagnóstico/HTTP V5; 0 fallos, 0 errores y 0 omitidas.
- 58 contratos Node pasan.
- Tres fixtures DOM completos pasan: interfaz histórica, generación y lanzador. Otros 10 checks independientes pasan para el banner terminal, propiedad del aviso, mensajes posteriores, job distinto y texto inerte.
- Los hashes de código, pruebas y documentación permanecieron iguales durante toda la suite. Este informe se deriva después de finalizar; su actualización no modifica el código probado.
- Se preservan todos los identificadores de pruebas históricas incluidos por el runner.

## Reproducción y corrección verificadas

La captura mostraba 24 rutas `deepseek-official/DeepSeek-V41-Flash` rechazadas como no disponibles y las descargas fallaban con un error local genérico. La prueba recrea ese estado histórico, aplica una edición manual, guarda el proyecto, abre una sesión nueva y lo carga desde disco sin consultar proveedores ni regenerar el equipo.

Mediante HTTP real de loopback, Recipe DSH (`implementation.json`), Backup DSH (`definitions.json`) y `package.zip` devuelven 200 con cabecera de descarga y longitud correcta. Ambos JSON contienen los 24 agentes originales, conservando IDs, nombres y rutas de modelo. La edición manual permanece en la organización. El ZIP es válido y contiene exactamente los bytes de los dos JSON descargados.

Las referencias históricas cuya disponibilidad no estaba acreditada pasan a no verificadas. La corrección no afirma que el alias exista o funcione en DSH. Una indisponibilidad explícita de runtime sigue bloqueada, incluso después de guardar/cargar. El ID exacto de diseño API se conserva en configuración, consentimiento, solicitud simulada y exportación; los nombres visibles o alias ausentes del catálogo API comprobado se rechazan antes de iniciar trabajo.

Las excepciones sintéticas en cinco etapas verifican diagnóstico y recibo correlacionados sin filtrar credenciales, URLs ni cuerpos externos. Se comprueban códigos HTTP acotados, cancelación/idempotencia, ausencia de reintentos pagados y conservación de artefactos previos. Errores de validación de exportación devuelven HTTP 400 seguro sin cabecera de descarga; el cliente comprueba el estado antes de guardar un archivo.

## Paquete extraído

PASS: se repitieron las dos pruebas HTTP independientes sobre el código del ZIP candidato extraído (SHA-256 `df1df674e961f5514176aca9fbf07951a0e7c0f99e1f330581bc5edd6b877309`), desde su propio directorio. Las tres descargas devuelven bytes nativos válidos tras cargar el proyecto histórico, y la respuesta de error permanece segura. No se usó el motor del árbol de desarrollo. Este informe se incorpora después como documentación derivada, sin cambiar código ni pruebas. El paquete final se somete nuevamente a integridad y al mismo caso HTTP antes de entregarlo; su hash y resultado quedan en la evidencia externa de entrega.

## Límites

No se realizaron llamadas reales a proveedores ni inferencias pagadas. No se ejecutaron Windows, EXE, DPAPI, Excel COM, importación/activación DSH ni pruebas de disponibilidad real de modelos. Los fixtures DOM no son un navegador ni validan renderizado visual o el gestor de descargas del usuario. La comprobación HTTP se ejecutó en Linux mediante loopback con datos sintéticos; no leyó ni modificó proyectos personales.

Evidencia de desarrollo: `qa_generation_diagnostics/final-results.json`, logs `*-final.txt` y `qa_v3/generation-v5-final_results.json`.
