# RELEVO V1 — datos ya medidos por el capitán (leer una vez, no re-derivar)

Verificación final de la ola `orgdna-plataforma-v9`. El paquete está en `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`.
Informes previos del propio rol verificador: `docs/PLATAFORMA_REVISION_RV1.md` (`b72d8f8f…`, needs_revision sobre I1) y
`docs/PLATAFORMA_REVISION_RV2.md` (`67b54746…`, **PASS** sobre la reparación `t11`).

## Estado de la ola

`t1`–`t7`, `t11`, `t12`, `t13`, `t9` cerradas. Entrega integrada y validable. **El paquete completo NO está verde** y no
se te pide que lo esté: arrastra deuda de línea base V8 documentada en `HALLAZGOS_LINEA_BASE_NO_ATRIBUBLES.md`.

## Datos medidos, no re-derivar

1. **F-T9-1 resuelto.** `tests_platform_reliability_connectors.py` fue declarado por `t7` como `ed42d004…` (54075 B) y se
   entrega como `51a6c845…` (54030 B). Copias fechadas en `%TEMP%`: `i4full_7d62fe53` (12:31:00) tiene exactamente
   `ed42d004…`; `i4pristine_04d2fd0f` (12:40:11) tiene exactamente `51a6c845…`, **anterior en ~15 min a la primera
   escritura de `t9`**, lo que **prueba la no-intrusión de `t9`**. Quién escribió a las 12:31:10 es **inferencia fuerte,
   no probada** (cae en la secuencia de `t7`: 12:28:30 / 12:30:02 / 12:31:10). Los tamaños DIFERÍAN, así que "mismo
   tamaño" no era argumento válido en ninguna dirección.

2. **Allowlist, diferencia literal ya calculada.** Previa 205 entradas (`bundle.py` `98a58d9c…`, en dos copias
   independientes que coinciden) → final **237**: nuevas **32**, eliminadas **0**, orden preservado. Composición:
   11 `engine/` + 8 `tests_platform_*` + 13 `docs`. La cifra "32" del acta es correcta y está medida por conjuntos.

3. **Manifiesto.** El entregado es completo y **sin enmascarar**: 300 entradas, 0 marcadores, 0 discrepancias contra los
   bytes reales, incluidos el acta y `03_CATALOGO_DOCUMENTAL.json`. Dos conceptos distintos que no deben confundirse:
   `MANIFIESTO_SHA256_SIN_ESPEJO` (huella con dos digest enmascarados, publicada en el acta) y el SHA-256 del manifiesto
   real = `3f74e6269be4de5b89aa0d07280969f203d6103fab40fbe247a79a72ae1cd2b8`.

4. **Contradicción interna del acta que debes conciliar.** `docs/PLATAFORMA_ENTREGA_V9.md` §9.2 (línea 278) dice que
   `test_revision_preserves_ids_new_project_changes_them` **falló** en "la corrida completa de esta ronda (993 pruebas)";
   §9.4 (línea 321) dice que **no falló** en esta corrida. Pueden ser dos corridas distintas, pero el acta no las
   distingue: identifícalas por huella y log. Datos de margen en §9.2 líneas 283-286: pre-integración 6,33–6,42 s frente
   a 7,2–8,59 s de la entrega, contra plazo fijo de 12 s.

5. **Regla de poblaciones.** Los 6 defectos deterministas + 3 condicionados por encoding pertenecen a la línea base
   **acotada de 391 pruebas**; los 1 fallo + 14 errores pertenecen a la colección de **993**. **No se comparan
   directamente.** No reduzcas a "solo entorno" la combinación de fragilidad de plazo + trabajo del empaquetado + carga
   del host.

6. **Dos hechos operativos.** El validador del paquete es de **sólo lectura** (hashes, tamaños y mtimes idénticos antes y
   después, medido). Y la suite completa **no puede devolver exit 0** por la deuda de línea base (medido: 391 pruebas →
   1 fallo y 8 errores; 993 → 1 fallo y 14 errores), así que se retiró de la compuerta mecánica; el diferencial completo
   **sigue siendo criterio de aceptación**.

## Protocolo de supervivencia (obligatorio: tres intentos murieron por stream cortado)

- Lanza los comandos pesados con `run_in_background: true` y recógelos con `job_output`. **No relances a ciegas**: lee el
  job por su id.
- **Escribe `docs/PLATAFORMA_VERIFICACION_V1.md` a medida**, sección a sección, en cuanto tengas cada resultado. Si el
  stream se corta, el trabajo debe sobrevivir y el reintento **continúa**, no empieza de cero.
- Turnos cortos y encadenados mejor que uno que lo haga todo.
- Al reactivarte, lo primero es leer lo que ya escribiste y seguir desde ahí.

## Límite de alcance

Tu único artefacto de escritura es `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/docs/PLATAFORMA_VERIFICACION_V1.md`. `engine/`,
`web/`, `MANIFIESTO_SHA256.txt` y las pruebas heredadas son de **sólo lectura** para ti: no corrijas nada, ni siquiera un
defecto evidente. Sin red, sin claves, sin dependencias nuevas, sin tocar DSH.
