# Actualizar la aplicación y conservar proyectos

1. Guarda el proyecto desde la aplicación anterior y cierra su servidor local.
2. Conserva una copia de seguridad de la carpeta anterior. Descomprime el ZIP nuevo completo en una carpeta nueva; no mezcles archivos de motor entre versiones.
3. Para recuperar proyectos guardados, copia únicamente la carpeta `data/projects` de la instalación anterior a `data/projects` de la nueva. Haz la copia con OrgDNA completamente cerrado. Mantén la estructura, los nombres y los archivos auxiliares SQLite del proyecto; copia también la subcarpeta `_capabilities` y sus archivos auxiliares presentes. Copiar sólo un JSON o una carpeta de proyecto aislada puede perder la biblioteca y sus asignaciones. Si ya hay proyectos en el destino, evita sobrescribirlos: respalda ambas carpetas y resuelve los nombres antes de copiar.
4. No copies archivos de API keys, credenciales, tokens, sesiones ni otros datos de configuración. Configura las credenciales necesarias de nuevo en la sesión de la aplicación. No las pongas en documentos o URLs de fuentes.
5. Ejecuta `launch.cmd` con Python 3.10 o posterior instalado. Abre el proyecto guardado y verifica su nombre y número de agentes antes de hacer cambios. Guarda cualquier trabajo nuevo antes de cerrar.

El ZIP incluye el snapshot histórico de 24 agentes. Sus JSON, IDs, ADN y prompts no se regeneran en esta actualización. Los JSON adjuntos de otros equipos tampoco sustituyen ese snapshot. La aplicación permite trabajar con proyectos de 30 agentes al cargar sus datos guardados desde `data/projects` o generar un diseño AI con ese tamaño; requiere las fuentes y autorizaciones correspondientes. No se reconstruyen proyectos privados a partir de sus exports durante esta entrega.

Los cambios de fuente, cobertura o diseño pueden requerir una nueva preparación y autorización. Una cobertura parcial debe revisarse como parcial: una lectura de repositorio o de sitio no garantiza haber leído todo el sistema. Conserva el backup hasta comprobar que el proyecto abre y guarda correctamente en tu equipo.
