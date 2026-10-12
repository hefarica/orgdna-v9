# V5: diagnóstico, catálogo y descargas

Fecha: 7 de octubre de 2026. Base: entrega V4, sin regenerar la organización entregada.

## Problema identificado

El error mostrado por el usuario rechaza los 24 perfiles por «Modelo no disponible: deepseek-official/DeepSeek-V41-Flash». La comprobación mezclaba el catálogo de modelos para diseñar mediante API con las rutas o alias del equipo en DSH. La ausencia de un alias DSH en un catálogo API no acredita que esa ruta sea inutilizable en DSH. Esto tampoco demuestra que el alias funcione: su disponibilidad real sigue pendiente de verificación en el runtime del usuario.

## Cambios

- Se distingue la elección exacta del modelo de diseño API de las referencias de modelos del equipo DSH. No se sustituye silenciosamente un modelo ni se elude una indisponibilidad explícita del runtime.
- Al cargar un proyecto anterior se revisan las afirmaciones heredadas de disponibilidad. Las rutas, identidades y perfiles se conservan; una referencia no comprobada permanece sin verificar.
- El aviso de preparación o generación termina al llegar a revisión o a un estado terminal, sin sobrescribir mensajes posteriores ajenos.
- Un fallo conserva etapa, código y estado HTTP cuando corresponde. El resultado y el registro muestran texto seguro; los detalles arbitrarios de excepciones o transportes no se publican.
- El recibo inicial indica que la preparación comenzó, sin afirmar que el inventario ya terminó. No se añaden reintentos automáticos ni se evita la autorización existente.

La comprobación final de Recipe, Backup y ZIP, incluyendo proyecto V4 guardado y ejecución del paquete extraído, se describe en `qa_generacion_v5.md`. No se atribuye éxito a una descarga antes de esa evidencia.

## Recuperar tus proyectos al cambiar de carpeta

Los proyectos locales están dentro de `data/projects` en la carpeta de OrgDNA. Una carpeta recién extraída no contiene los proyectos que guardaste en otra instalación.

1. Cierra sólo el panel/servidor OrgDNA anterior. Conserva íntegra la carpeta V4; no borres ni reemplaces tu instalación DSH.
2. Extrae V5 en una carpeta nueva. Copia la carpeta `data/projects` de tu OrgDNA V4 a `data/projects` de V5, conservando el original. Si el destino ya contiene proyectos, no sobrescribas archivos en conflicto: guarda ambas carpetas y revisa antes de mezclarlas.
3. No copies `state`, claves, credenciales, configuración de sesión ni carpetas DSH. Esta transferencia se limita a los proyectos guardados.
4. Inicia OrgDNA V5. Ve a Inicio → Proyectos y versiones → Actualizar lista → Cargar última y selecciona el proyecto correspondiente.
5. Comprueba que están los 24 perfiles y sus rutas antes de descargar Recipe, Backup o ZIP. Recuperar y exportar un proyecto existente no requiere regenerarlo ni llamar a una API.

## Límites

Se conserva byte por byte el contenido previo de V4 salvo los archivos de código, pruebas y documentación enumerados en la validación V5 y los manifiestos actualizados. No se regeneraron los 24 agentes entregados, sus identificadores, ADN, recetas, libro Excel ni el relanzador. No hubo llamadas reales a proveedores ni cambios en el ordenador del usuario.

Esta entrega no acredita una inferencia real, importación o activación en DSH, disponibilidad del alias en el runtime, ni compatibilidad comprobada en Windows. Los informes V4 se conservan como evidencia histórica de V4, no como validación nueva de V5.
