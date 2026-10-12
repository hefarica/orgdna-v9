# Validación del arranque y panel DSH

Fecha: 7 de octubre de 2026. Resultado: **PASS en el entorno de pruebas Linux**, con los límites indicados abajo.

## Pasó

- 709 pruebas Python de regresión, conservando las 351 identidades de pruebas históricas; 0 fallos, errores u omisiones.
- 27 pruebas independientes adicionales: HTTP local real, arranque concurrente en procesos Python, copia de archivos sintéticos y ejecución del relanzador simulada.
- Tres recorridos DOM mínimos y 58 pruebas Node; 0 fallos.
- Fuentes, documentación y bytes del relanzador permanecieron iguales durante la pasada final. Después sólo se añadió este informe derivado.

## Cobertura relevante

- Puerto ocupado por un servicio ajeno: el panel obtiene otro puerto y deja intacto el servicio existente. Dos arranques simultáneos reutilizan un solo panel compatible. Los errores no relacionados con ocupación/permisos no se ocultan con un cambio de puerto.
- Identidad del panel, rechazo de Host ajeno y protección de operaciones mediante sesión, Origin y CSRF. La identidad pública distingue servicios normales; no autentica contra un proceso malicioso del mismo usuario.
- Consentimiento ligado a operación, configuración, rutas y hashes; argumentos cerrados, sin shell ni ejecución del BAT. Doble clic/reintento no repite la operación. Una preparación explícita nueva sí crea otra operación.
- EXE/configuración/copia alterados, archivos añadidos, enlaces simbólicos y destinos inseguros bloquean los recorridos probados. Se comprueban límites y hashes; no se expone la copia por HTTP ni se incluye en la exportación.
- Fallo de inicio, proceso aún vivo y salida no cero no acreditan salud DSH. El resultado fijo del relanzador no se atribuye a la operación cuando hay mutex `ALREADY_RESTARTING`; un informe nuevo sigue marcado sin identidad runtime ni preservación verificadas.
- Cancelar confirmación, editar rutas durante una inspección, actualizar estado y repetir clics mantienen los bloqueos en el DOM de prueba.
- Los bytes del EXE seleccionado y de las tres fuentes incluidas coinciden con sus miembros del ZIP aportado y con su procedencia documentada. Esto no demuestra una compilación reproducible ni correspondencia completa entre el ensamblado y la fuente.

## No ejecutado y límites

No se ejecutó el EXE ni DSH en Windows, ni se probó el ordenador del usuario, un navegador real, diseño visual, ACL Windows, bloqueo Windows de archivos, importación/activación Cordis, restauración de historial o llamadas reales a proveedores. Los recorridos Windows de ejecución se probaron con dobles controlados, no con procesos DSH reales.

La copia es de los archivos seleccionados: **no es un snapshot coherente de una base de datos activa ni garantiza cobertura completa**. Puede contener credenciales y requiere protección local. La preservación efectiva depende del runtime y de la operación elegida.

Reutilizar no equivale a integrar. Reiniciar puede perder argumentos `--patch` anteriores y limpia `NODE_OPTIONS`/`NODE_PATH`; legacy puede perder estado en memoria. La integración automática y conservación real del historial no quedan acreditadas por estas pruebas. Véanse `DSH_RELANZAMIENTO_LOCAL.md` y `dsh_launcher_source_audit.md`.
