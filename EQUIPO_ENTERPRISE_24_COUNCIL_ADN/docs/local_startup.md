# Arranque local en Windows

Ejecuta `launch.cmd` en la carpeta extraída. Python 3.10 o posterior debe estar instalado. El panel sólo escucha en `127.0.0.1`.

- Si ya está abierta una instancia compatible de esta misma copia, se abre su enlace sin iniciar otro servidor. Se comprueban aplicación, versión, protocolo, huella del código cargado, instalación y libro opcional mediante `/api/instance`.
- Si el puerto 8765 pertenece a otro servicio, otra copia o una versión anterior, o el sistema deniega ese puerto, OrgDNA imprime el error real (`errno` y `winerror`) y pide al sistema un puerto libre para su propio panel.
- El navegador recibe el enlace con ese puerto efectivo. El siguiente arranque puede recuperarlo de un pequeño registro temporal, pero siempre vuelve a comprobar la identidad HTTP antes de reutilizarlo.
- Dos aperturas simultáneas de la misma copia, puerto preferido y libro se coordinan mediante un bloqueo del sistema operativo. La segunda espera hasta que el panel esté sirviendo su identidad antes de reutilizarlo. El bloqueo se libera también si el proceso termina; un archivo de bloqueo que quede en disco no significa que siga ocupado.
- No se cierran procesos, no se cambian puertos de DSH y no se elevan permisos ni se modifican reservas, firewall o seguridad de Windows.
- Enlaces de Excel creados previamente conservan su puerto original. Usa las descargas del panel abierto o actualiza esos enlaces expresamente. Los archivos Excel no se modifican al arrancar.

Opciones:

- `launch.cmd --port 0`: pide directamente un puerto libre.
- `launch.cmd --port 9000`: prefiere el puerto 9000; conserva recuperación automática.
- `launch.cmd --port 9000 --strict-port`: exige ese puerto; termina con diagnóstico si no puede abrirlo ni reutilizar una instancia compatible en él.
- `launch.cmd --no-browser`: muestra el enlace sin abrir el navegador.

Un `winerror=10048` indica dirección en uso. `winerror=10013` indica acceso denegado, que puede corresponder a un puerto reservado o restringido; no demuestra por sí solo que exista otra instancia. Otros errores, por ejemplo agotamiento de recursos, se muestran y no se ocultan tras un cambio de puerto.

La identidad pública evita confundir servicios normales y versiones distintas. No es una autenticación contra un proceso local malicioso capaz de imitar la aplicación bajo el mismo usuario. El endpoint no contiene credenciales, tokens de sesión, tokens CSRF ni rutas privadas.
