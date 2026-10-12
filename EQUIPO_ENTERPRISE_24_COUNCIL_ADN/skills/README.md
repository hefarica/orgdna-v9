# Skills portables propuestas

Incluye `webapp-testing` y `systematic-debugging`, versión 1.0.0. Son guías nuevas
de este paquete. No son skills oficiales, no fueron instaladas en DSH y no
acreditan pruebas de navegador ni aprendizaje ejecutado. `skill-registry.json`
es un índice local del paquete; no debe importarse como recipe.

## Carga en DSH: compatibilidad conocida y límite real

Se revisó el esquema público de `toolclub/dsh-agent-team-gui` 1.3.0, commit
`14ea11960b20b1f93c33541ba9df7746ed16d08a`. El recipe admite `systemPrompt` por
agente y `collabNote` por squad. No contiene un campo nativo `skills`, rutas de
skills, instalador ni tool key que permita registrar automáticamente estos
archivos. Esto no identifica la versión instalada del host del usuario.

- Si tu DSH ofrece un gestor de skills, usa su documentación y mecanismo reales.
  Antes de afirmar instalación, comprueba versión, ruta admitida, carga completa
  del contenido y una tarea inocua. Este paquete no presupone esa integración.
- Como adaptación textual al plugin de equipos inspeccionado, puede incorporarse
  el contenido relevante al `systemPrompt` de los roles mediante una edición
  revisada del recipe. Incluye también el contrato remedial y de evidencia
  necesario, controla el límite editable de 50.000 unidades UTF-16 y no añadas
  nuevas claves al JSON. Un nombre o ruta en el prompt no carga un archivo.
- Valida el candidato, exporta respaldo, abre preview, revisa UUID, modelos y
  `affectedSquads` antes de aplicar el merge autorizado. `copy` remapea UUID
  estructurales pero puede dejar UUID textuales antiguos. Importar definiciones
  no instala Chromium/Playwright/RDC ni otorga permisos a herramientas.

No se entrega un comando DSH inventado. Si no hay un mecanismo de carga probado,
el estado correcto es «guías disponibles, integración DSH pendiente».

El definitions backup v2 generado contiene sólo esta organización y sus dos
squads. No equivale al respaldo completo de una instalación DSH ni autoriza
reemplazar sus otras definiciones.

## Host Codex con carga de skills compatible

En un host Codex cuyo cargador esté habilitado, las carpetas con `SKILL.md` se
descubren en `${CODEX_HOME}/skills`, o `~/.codex/skills` si CODEX_HOME no está
definido. Copia cada carpeta conservando sus referencias; los archivos comunes
de este paquete deben quedar un nivel por encima de ambas carpetas. Comprueba
el catálogo del host y ejecuta un ensayo de lectura/planificación sin efectos
externos. No se ha copiado nada a esos destinos en esta entrega.

## Validación y fuentes

`qa_independent/` contiene la revisión del paquete y, cuando estén disponibles,
pruebas offline de contratos. Una validación del Markdown no prueba que la skill
mejore el comportamiento. Los ensayos/remediales requieren resultados y revisión
independiente reales antes de promoción.

Fuente del esquema inspeccionado:
https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/spec.ts

Fuente de importación y preview:
https://github.com/toolclub/dsh-agent-team-gui/blob/14ea11960b20b1f93c33541ba9df7746ed16d08a/src/tools/application/definition-service.ts
