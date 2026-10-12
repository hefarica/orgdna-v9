# QA multifuente V6

Estado: PASS del código final congelado y del candidato completo extraído. La entrega final debe ser idéntica funcionalmente al candidato, salvo este informe derivado y los manifiestos recalculados.

Se prueban fuentes GitHub y HTML público con fixtures deterministas sin APIs pagadas, credenciales reales, lectura de un repositorio real ni ejecución de contenido obtenido. El smoke HTTP usa únicamente loopback Linux y no demuestra funcionamiento visual en un navegador ni ejecución Windows/DSH.

Agregado final estable (2026-10-08 01:52:14–01:56:32 UTC): 948 pruebas históricas, 27 de regresión V4, 87 independientes V6 y 64 contratos Node pasan, además de cinco fixtures DOM. Sin fallos ni skips en esos grupos. Se conservaron los IDs históricos. No cambió ningún archivo fuente durante la ejecución.

## Límites de lectura

GitHub: resolución de commit mediante representación SHA (máximo 100 bytes), metadatos de commit Git sin diff y árbol de revisión inmutable. Inventario: 24 solicitudes de árboles, 12.000.000 bytes contabilizados conservadoramente, profundidad 16, 5.000 entradas y ventana de programación de 120 segundos. HTTP por árbol máximo 3.000.000 bytes. Solo tamaño/truncamiento permiten subdivisión; errores de acceso, cuota y red no permiten inventar evidencia. Lectura equilibrada: 20 archivos/250.000 bytes; profunda: 60/750.000; ampliar exige confirmación. Topes: 100 archivos, 1.000.000 bytes, 40.000 por archivo, concurrencia máxima 4.

Web: valores predeterminados 12 páginas, 600.000 bytes, profundidad 2, 30 solicitudes, 30 segundos y concurrencia 4. Solo HTTPS público del mismo origen, TLS/DNS fijados, robots verificado, HTML estático sin ejecutar JavaScript, formularios ni botones. Máximo configurable 100 páginas, 4.000.000 bytes, profundidad 5, 300 solicitudes, 120 segundos, concurrencia 8; máximo por página 150.000 bytes, hasta 4 iteraciones de redirección y 3 variantes por ruta. Caché local de HTML: TTL predeterminado 300 segundos, máximo 3.600, hasta 100 entradas/8.000.000 bytes de cuerpos. Se vuelve a consultar robots. La cobertura siempre es parcial y las peticiones en vuelo/DNS pueden superar la ventana de programación; no es un timeout duro de pared.

## Comprobaciones ampliadas en curso

- Diseño organizacional: pruebas independientes de revisión con árbol manual, política allow/deny y UUID conservados; importación legacy mantiene squad e identidades; cambio de membresía exige edición explícita.
- Jerarquía: comprobación de raíz CEO/Owner, ausencia de ciclos y límites de span en equipos de 1, 28, 30 y 32 agentes.
- Herramientas: recomendaciones ligadas a UUID actuales y catálogo; disponibles en runtime permanece UNKNOWN, no se conceden permisos por una propuesta.
- Diferenciación: coincidencias de misión, competencias y evidencias se señalan para revisión; no se declara unicidad mundial ni acreditación profesional.
- Evaluación dinámica y ciclo de mejora: pruebas cruzadas sobre fixtures locales y LLM simulado; verificación global final superada. Ningún resultado de este informe autoriza ejecución externa, llamadas pagadas ni afirmar skills acreditadas.

## Evaluación local: límites verificados y de confianza

El runner usa perfiles cerrados `python_unittest_v1`, `python_pytest_v1` y `node_test_v1`. Un runner ausente bloquea la acción; no se instala nada. Preparar no ejecuta pruebas. La ejecución exige el hash del plan, el diseño actual y confirmación explícita; una repetición del mismo plan reutiliza el resultado y no vuelve a ejecutar.

Límites: timeout configurable de 1 a 120 segundos, salida total de 1.024 a 262.144 bytes, plan válido durante 900 segundos y máximo 100 planes por sesión. El manifiesto local admite hasta 10.000 archivos, 20.000.000 bytes por archivo y 100.000.000 bytes totales. El árbol completo seleccionado de pruebas entra en el hash, incluidos sus subdirectorios; exclusiones de dependencias/cachés sólo se aplican fuera de ese árbol. No se admiten symlinks. Los resultados deben guardarse fuera del árbol evaluado para no alterar su propio manifiesto.

Se comprueban fuente e intérprete antes y después, y la fuente actual antes de reutilizar un resultado en feedback. El harness unittest también queda ligado por hash. Se retienen métricas acotadas y referencias/digests, no stdout/stderr crudos. No se heredan claves API del entorno. Los procesos tienen acceso real del usuario: esto NO es un sandbox, entorno hermético ni garantía de impedir red o modificaciones externas.

Los contadores/éxitos del runner proceden de un proceso no confiable. Un resultado PASS demuestra el cumplimiento observado de condiciones del runner sobre esa copia y ejecución; no acredita honestidad de pruebas adversariales, calidad global, competencia de un agente ni equivalencia entre la copia local y el GitSHA remoto. La revisión independiente sigue pendiente. `skills_verified`, `skills_installed` y entrenamiento de pesos no se activan por un PASS.

Timeout/cancelación se han ejercitado en Linux con procesos fixture y grupos de procesos. El código Windows de proceso suspendido, Job Object y limpieza de handles sólo se ha revisado estáticamente; no está probado en Windows.

## Correcciones descubiertas por QA independiente

- Las respuestas web demasiado grandes ya consumen su reserva conservadora de bytes, en lugar de liberar incorrectamente todo el presupuesto.
- Labels anteriores a sus controles se asocian correctamente.
- El flujo manual web conserva procedencia URL/snapshot sin acceder a campos exclusivos de GitHub.
- La generación local web produce 30 agentes y las tres descargas mediante HTTP loopback con fixtures.
- Un directorio de pruebas excluido y un subpaquete excluido anidado ya no permiten ejecutar contenido fuera del hash aprobado.
- Cambios de fuente posteriores al run invalidan el resultado para mejora.

Estos hallazgos no se interpretan como pruebas sobre sitios reales, APIs pagadas ni el runtime DSH instalado.

## Primer agregado congelado (2026-10-08 00:55–00:58 UTC)

El manifiesto permaneció estable. Se ejecutaron 836 casos históricos, más los grupos V4/V6, DOM simulado y contratos Node. Los seis grupos adicionales pasaron. El grupo histórico falló en tres casos preexistentes: 225 subcasos exigían todavía el árbol BFS sustituido deliberadamente por el diseño funcional; otro ciclo se construía con posiciones BFS que ya no eran descendientes; un setup intentaba crear una carpeta ya creada por el almacén de evaluación. No se cambió producción para satisfacer esos oráculos. Se conservaron los tres IDs y se adaptaron a invariantes de grafo, un descendiente real y preparación idempotente. Los tres casos adaptados pasan, incluyendo las 256 combinaciones N/span. El resultado fallido original se conserva y queda superado por el agregado final estable. Un pase intermedio también se conservó: todas las pruebas Python pasaron, pero una edición tardía de UI invalidó su congelación y un selector DOM antiguo confundía «Comparar» con «Añadir al equipo». Se cambió únicamente ese selector del test y se repitió el agregado completo.

## SkillHub y recomendaciones

La biblioteca persistente y privada usa SQLite, separado de los ZIP. Tipos: instrucciones de skill, paquete plugin, conector y política de memoria. La cuota predeterminada es 256 MiB de carga lógica contabilizada, no una garantía sobre el tamaño físico de SQLite/índices. Solicitud máxima 2 MiB, ítem máximo 128 KiB, paginación de 1–200 registros. Se han probado 1.601 ítems persistidos, sin límite arbitrario de 500. Asignaciones por equipo, subconjunto o subequipo usan UUID actuales; importación y asignación combinadas se confirman en una sola transacción. Replays no duplican, y conflictos de revisión o undo no pisan cambios posteriores.

Activar instrucciones locales tiene presupuesto de contexto predeterminado de 12.000 bytes (tope 24.000). Un ítem que no cabe se difiere entero; no se corta silenciosamente. Activar instrucciones no instala plugins ni concede herramientas. Plugins/conectores sólo pueden asignarse como referencias en esta biblioteca. Ninguna asignación acredita competencia, entrenamiento ni acceso real.

Las recomendaciones IA preparan el contenido y costes desconocidos antes de autorizar: hasta 32 perfiles, shortlist de 1–64 candidatos con procedencia fijada; predeterminado 8 perfiles por lote, máximo 4 llamadas configuradas y 4.096 tokens de salida por llamada. Los límites configurables alcanzan 32 llamadas y 32.768 tokens de salida; máximo 600.000 bytes de entrada/respuesta por llamada y timeout 120 segundos. No son un límite monetario. El catálogo, identidades, modelo API, contexto y presupuesto quedan ligados al consentimiento. Un error o cancelación no publica un lote parcial ni reintenta. Los intentos enviados se contabilizan también cuando falla la validación del resultado. El modo local determinista no llama APIs.

El lector de referencias es independiente de la fuente principal del proyecto. Por defecto lee 1 página, 300.000 bytes, profundidad 0, 8 solicitudes, ventana 20 segundos y excerpt de 6.000 caracteres. Sólo produce referencias revisables, sin importar ni ejecutar instrucciones remotas. README/SKILL.md de GitHub se ligan a commit y blob verificados; HTML utiliza el lector público protegido. Una referencia no demuestra que exista un plugin instalable o un conector autenticado.

## Exportación y frontera DSH

Registrar referencias o asignarlas inactivas conserva los bytes de los tres JSON nativos DSH. La activación explícita de instrucciones modifica únicamente los prompts derivados correspondientes, junto con el companion y sus hashes; no modifica UUID, perfiles estructurales ni toolScope. El manifiesto exportable admite hasta 10.000 ítems, 320.000 asignaciones y 16 MiB; una prueba independiente recorre 12.000 asignaciones (400 ítems por 30 UUID). Conserva el equipo existente; no crea agentes nuevos.

La publicación local es exclusiva por namespace de organización y versión: hasta 1.000 archivos, 8 MiB por archivo y 64 MiB total. Vista previa no escribe. Rechaza sobreescritura y paths inseguros, lee de vuelta los bytes y distingue publicación de activación. Rollback sólo elimina su versión intacta; rechaza archivos ajenos o modificados. El delta conserva backup y compara hash base/objetivo. Su lock coordina escritores cooperantes, no impide a un proceso externo hostil ignorarlo.

Las pruebas de addon/SDK son fixtures Node y contratos, no una instalación DSH real del usuario. El preflight no instala, ejecuta CLI ni cambia configuración. Activación/reload sólo pueden acreditarse después de aprobación nativa y lectura real de namespace, roster, hash y salud. Email, mensajería y voz permanecen bloqueados hasta configurar autenticación/permisos, comprobar salud y autorizar separadamente cada comunicación pertinente.

## UI no visual

DOM simulado independiente: selección de catálogo entre páginas, persistencia de pestaña, preview sin escritura, descarte, invalidación tras cambio de catálogo y respuesta tardía de polling después de cancelación. Se corrigió el polling para impedir que un GET antiguo vuelva a mostrar como activa una recomendación cancelada. Estas pruebas no validan layout, accesibilidad visual ni comportamiento de un navegador real.


## Identidad y contexto operacional

Los nuevos perfiles contienen identidad operativa derivada de nombre, rol, misión, superior y miembros actuales. Cambiar el nombre o estilo manual mantiene los UUID y actualiza el contrato. Son agentes de IA con estilo definido, no seres humanos, conciencia, títulos reales ni experiencia acreditada. La memoria de trabajo refleja registros explícitos; un registro no otorga autorización, acceso a datos ni almacenamiento persistente verificado.

La exportación compila desde cero las instrucciones activadas de cada UUID. Referencias asignadas pero inactivas no alteran el prompt. Activar un ítem sólo lo incluye para sus destinatarios; desactivarlo recompila sin residuos. Contenido serializado y delimitado permanece subordinado a reglas, permisos y gates. Se cumplen el presupuesto UTF-8 de contexto y el tope estricto de menos de 50.000 unidades UTF-16 por prompt. Ítems completos que no caben quedan diferidos, y plugins/conectores no pueden convertirse en contexto de instrucciones. Perfiles históricos sin el marcador de identidad mantienen su composición anterior.


## Cierre del código congelado

Resultado agregado: PASS, nueve grupos sobre el mismo manifiesto, sin cambios fuente entre inicio y fin. Huella SHA-256 del mapa de fuentes probado: `15dddaf7127b7bca8211041cfbeceb624a946b8a31b90f7bd645d9ae67b2d064`. La actualización posterior de este informe es derivada; no es una modificación funcional. El candidato correspondiente se verificó por separado después de extraerlo, como se detalla a continuación.

GitHub, Hugging Face o Hermes pueden aparecer como nombres/enlaces de referencias del usuario. Esta QA no demuestra descarga ni ejecución nativa de modelos Hugging Face/Hermes, compatibilidad de sus paquetes, autenticación de cuentas ni una instalación de esos runtimes. La lectura de una página o documento público no equivale a instalar o ejecutar su contenido.


## Candidato extraído verificado del baseline anterior

Archivo candidato: EQUIPO_ENTERPRISE_24_COUNCIL_ADN.zip. SHA-256: `a2f0ca2a69d36203d0136d42a2c0e671b1e18957c315c8b40672a08f5bd52201`. CRC limpio; 215 archivos y 10.994.771 bytes sin comprimir. La extracción independiente rechazó rutas absolutas, recorridos ascendentes y symlinks antes de materializar.

Ejecutado desde el propio árbol extraído, sin importar el checkout mutable:
- Validador portable: válido, 1.346 checks, hashes de exportación válidos y sin historia privada de runtime.
- 73 pruebas independientes V6: PASS.
- 122 pruebas focalizadas de regresión V5, evaluación, mejora, fuentes, SkillHub, contexto y exports: PASS.
- Seis pruebas Node del contrato SkillHub: PASS.
- DOM independiente SkillHub: PASS.

Incluye HTTP loopback real con ambas fuentes sintéticas, 30 agentes, tres descargas y preservación exacta de JSON DSH tras registro/asignación inactiva de capacidades. Incluye subprocesos de prueba locales reales y respuestas LLM simuladas. No acredita un repositorio real, API pagada, DataInventor ejecutado, navegador visual o DSH del usuario. Este hash identifica un candidato probado; cualquier ZIP posterior debe comprobar sus diferencias y repetir los checks de entrega.


## Workflows por recurso y prerequisito de arranque

Se verificaron planes por rol y su asignación atómica individual: cada perfil recibe su propio workflow, sin producto cruzado entre agentes. El modo determinista no llama un LLM. El modo IA requiere consentimiento exacto ligado a fuente, roles, proveedor, modelo y presupuesto; usa por defecto lotes de cuatro agentes, hasta ocho llamadas y 4.096 tokens de salida por llamada. Rechaza agentes/fuentes/endpoints inventados y conserva los requisitos de seguridad aunque el modelo intente omitirlos. Errores y cancelaciones consumen los intentos ya enviados y no publican parciales.

El ejemplo DataInventor es un snapshot de investigación explícito, no una consulta en vivo ni un backend comprobado. La licencia, API y versión del backend permanecen desconocidas. Las propuestas de dataset.jsonl, manifest.json y quality-report.json son entregables futuros; esta QA no generó datasets mediante DataInventor.

El startup_gate compilado exige comprobar instalación compatible, contrato/licencia, autorización y presupuesto, configuración no secreta en namespace por agente/recurso, readback y aceptación independiente PASS antes de tareas dependientes. Su estado inicial es pending_integration, configuración not_persisted y aceptación not_run; permite investigación de sólo lectura y preparar un plan para resolver esos pendientes. La prueba independiente confirma que esos campos invariantes sobreviven a la IA y llegan completos al contexto activado. Es un contrato de instrucciones para el agente; esta entrega no contiene un instalador DataInventor verificado ni acredita su ejecución o configuración efectiva en DSH.

## Harness de conexión DSH

El plan liga hash de launcher, operación reuse, puerto de emparejamiento cuando se especifica, roster esperado y espera de 1–120 segundos. Preparar no arranca. Inicio y respaldo requieren revisión y aprobación; emparejamiento es separado. No mata listeners, reinicia procesos, instala addons ni inventa soporte de overlay. Se probó que seis llamadas concurrentes al mismo plan sólo intentan un inicio, y que timeout/error no autoriza otro. Una excepción inesperada queda consumida y marcada como fallo visible sin exponer detalle privado.

TCP abierto, exit 0, identidad autenticada, doble lectura de roster, hash esperado y hash SkillHub son estados separados. La lectura autenticada se comprobó con un servidor Node fixture local. No acredita dispatch, identidad de sesiones de agentes ni tareas nativas ejecutadas. Desconexión/caducidad invalida la evidencia visible. La UI limpia el código de emparejamiento y bloquea un plan si cambian sus rutas.

El relanzador original puede perder --patch al arrancar; la conservación completa del entorno no está verificada. La instalación real de addons, integración compatible y permisos de PluginManager siguen requiriendo su mecanismo nativo y verificación en la instalación del usuario. No se ejecutó ningún EXE Windows, DSH del usuario o instalador remoto durante esta QA.


## Candidato completo con recursos y harness: PASS

SHA-256 del candidato completo probado: `059927966beb462dcf44505f2fa699be0732c96f78e98a64cd02438ca96e73ad`. CRC limpio; 227 archivos y 11.149.566 bytes sin comprimir. Sin entradas duplicadas, rutas absolutas/ascendentes, separadores inseguros ni symlinks en la extracción independiente.

Ejecutado desde este ZIP:
- Validador portable: PASS, 1.410 checks.
- QA independiente: 87 pruebas PASS.
- Regresión e integración focalizadas: 162 pruebas PASS.
- Contrato Node SkillHub: seis pruebas PASS.
- DOM independientes SkillHub y recurso/harness: ambos PASS.

Las pruebas incluyen HTTP de ambas fuentes con fixtures, descargas de 30 agentes, igualdad de bytes de exports nativos cuando sólo se guardan/asignan referencias, activación/desactivación de contexto, evaluación local real, feedback con LLM simulado, asignación de workflows individual por rol, startup_gate pendiente e inmutable y pairing/readback contra un bridge Node fixture local.

No se han verificado Windows/EXE, la instalación DSH del usuario, ejecución real de DataInventor, conectores de email/voz ni modelos Hugging Face/Hermes. Estos pendientes permanecen explícitos y no se convierten en READY por generación de instrucciones, puerto TCP, exit 0 o un reporte manual.

El empaquetado final posterior sólo puede cambiar este informe y metadatos/hash derivados. La equivalencia de todos los demás miembros, CRC, validador portable y smoke HTTP/QA se comprueban otra vez antes de entrega; el SHA del archivo final se publica fuera del propio ZIP para evitar autorreferencia.
