# Preparar, reutilizar o relanzar DSH desde OrgDNA

El panel está en Exportaciones → Preparar el relanzamiento DSH. Conserva el flujo existente de preparación Cordis y conexión local del addon.

## Qué está integrado en el panel

- **Usar relanzador incluido** selecciona `relanzador_dsh/DSH_REINICIAR.exe`, variante `fuente` de la entrega 1.1.1. Su SHA-256 es `c149d0bf8b7d7a14ce81f7008a6c8b98dc02aa78aecb708342138093eeeb3fd0`. Esa variante embebe el core y evita la caché del bootstrap exterior. El adaptador rechaza binarios diferentes. La revisión estática de fuente no sustituye pruebas reales en Windows.
- **Leer configuración local existente** lee `%LOCALAPPDATA%\DSH_LAUNCHER\launcher.json` sin ejecutarlo, conserva su SHA y muestra sólo `home`, `runtime`, `profile` y `port`. El formulario se llena con las rutas/puerto encontrados; no copia secretos ni el JSON completo a proyectos o exportaciones.
- Si falta esa configuración, no se ejecuta el relanzador con defaults. El puerto 3080 y perfil web de la fuente se muestran sólo como propuestas no verificadas.
- El BAT es opcional y sólo una referencia: puede leerse e identificarse por hash, pero nunca se ejecuta. El contenido crudo no se muestra, persiste ni exporta.

## Dos modos y una excepción

1. **Reutilizar**, modo inicial: `--headless --no-open --reuse`. Evita detener un DSH existente; si está apagado puede iniciarlo. No significa una lectura pura: el EXE puede escribir su estado/config y utilizar la autenticación existente.
2. **Reiniciar**, selección explícita: `--headless --no-open --restart`. El código revisado comprueba identidad/actividad antes del cierre y no fuerza automáticamente un DSH legacy. Importante: un reinicio puede perder un `--patch` previo y limpia `NODE_OPTIONS`/`NODE_PATH`. No garantiza conservar toda la configuración efectiva del proceso anterior.
3. **Legacy**, sólo después del error específico de una operación de reinicio: un marcador fijo del stdout del mismo proceso y su salida fallida habilitan preparar una operación nueva para la misma configuración y EXE. Requiere copia nueva y otra confirmación expresa, ahora con `--allow-legacy-stop`. Puede terminar el DSH identificado mediante `Process.Kill` y perder datos en memoria o tareas externas. Nunca se reintenta automáticamente ni se habilita por un `last-result.json` ajeno.

El panel no ejecuta `--check-only` como si fuera una lectura: la fuente revela que también escribe archivos y autentica.

## Copia previa y confirmación

1. Revisa la configuración detectada, rutas y puertos originales. Añade cualquier otra ruta real de datos que deba respaldarse. No se asignan puertos nuevos.
2. Cierra DSH manualmente antes de copiar si necesitas reducir cambios concurrentes. La app no mata procesos por nombre.
3. Inspecciona el plan: operación, argumentos, rutas, SHA del EXE/config/BAT y riesgos. Autoriza una copia de las rutas revisadas. Se comprueban lista de archivos y hashes, incluyendo otra comprobación inmediatamente antes de iniciar el EXE. Límite: 512 MiB y 20.000 archivos. Si no cabe, se bloquea sin excluir archivos silenciosamente.
4. La copia se guarda en `%LOCALAPPDATA%\OrgDNA\dsh-backups`. Puede contener credenciales y debe protegerse como los originales. No tiene ruta HTTP de descarga ni se incorpora a exportaciones. Es una **copia verificada de archivos, no un snapshot coherente de una base de datos activa ni prueba de cobertura completa**.
5. Confirma la operación exacta. El EXE se invoca por ruta absoluta, con argumentos del contrato y `shell=False`. Un handle de lectura Windows impide escritura/eliminación del EXE durante la última comprobación de hash y el inicio. No se aceptan comandos ni argumentos libres.
6. Actualiza el resultado. Un plan sólo se ejecuta una vez; dobles clics/reintentos no repiten el proceso. Una inspección nueva crea otra operación y exige nueva copia/confirmación. El estado sobrevive a recargar el navegador, no a reiniciar OrgDNA.

## Resultado no equivale a integración

La salida 0 no demuestra salud DSH. Un `last-result.json` sólo se muestra si cambió y sus tiempos corresponden a esta ventana de ejecución; sigue etiquetado como informe del launcher sin identidad runtime verificada. Un mutex `ALREADY_RESTARTING` descarta ese resultado. No hay un ID de operación autenticado en el protocolo original.

La salida del proceso se drena en líneas acotadas y sólo conserva identificadores fijos de fallo/estado. Nunca se guarda, muestra o exporta stdout/stderr crudo, URLs de autenticación, rutas de diagnóstico emitidas ni cuerpos de informe. No se termina el proceso por timeout.

Para integrar realmente el equipo:

1. Preparar paquete Cordis y revisar su preflight.
2. Instalar/activar un addon compatible y revisar backup/efectos antes de importar en DSH. Este panel no lo automatiza ni sobrescribe configuraciones del perfil.
3. Reutilizar o relanzar la instalación cuando proceda, con los límites anteriores.
4. Emparejar el addon de sólo lectura y comprobar capacidades/perfiles. Escucha TCP, paquete preparado, addon conectado e importación verificada son estados diferentes.

## Verificación

`python -m unittest tests_dsh_launcher tests_bridge tests_frontend_contract tests_frontend_integrations -v`

Las pruebas offline usan fixtures y Popen simulado. No demuestran WinAPI/ACL reales, arranque del EXE en tu equipo, preservación del historial, importación ni funcionamiento real del addon.

## Siguiente comprobación para completar la integración

El ZIP fuente del relanzador ya está incorporado y revisado; no está pendiente de recibirse. Lo que falta es diagnosticar **la instalación runtime concreta**: comprobar la versión real de DSH, el parser/configuración que esa versión admite y qué overlay o `--patch` está cargado en el proceso vigente. El panel ya conserva el hash de launcher.json y comprueba la existencia del entry local configurado, pero no demuestra el comando/entorno efectivo del proceso ni que Cordis esté cargado. Hace falta acceso o un diagnóstico de esa instalación para adaptar/verificar el overlay sin sobrescribir el perfil. Hasta entonces, preparar el paquete y revisar su preflight no equivale a tener todo integrado.
