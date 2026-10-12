# Contrato de las herramientas

Prefijo: `orgdna_<32hexUUIDorganizacion>_`. `member_id` significa el UUID estable del
perfil. El actor lo determina `exec.agent.id` más el binding aprobado localmente;
no existe argumento `actor`, `from`, `session_id` ni cambio de permisos.

`state`: `{section?,offset?,limit?}`; secciones summary, roster, messages, tasks,
evidence, memory, learning, audit. limit 1..100. Retorna version y paginación.
Los mensajes directos son visibles al emisor/destinatario; `to: all` al equipo.

Los otros métodos reciben `{idempotency_key,expected_version,payload}`. Una clave
repetida con igual operación/contenido devuelve el recibo sin escribir; otro
contenido falla. Una versión obsoleta falla sin cambios: leer y reconciliar.

- `message`: `{to: member_id|"all", text, topic?}`. Registro compartido; no wake.
- `evidence`: `{locator,sha256,summary}`. SHA-256 hex minúsculo64; no abre URLs,
  archivos ni comandos. `artifact_read_by_plugin=false`, `content_verified=false`.
- `memory`: `{title,text,evidence_ids:[id],supersedes?:memory_id}`. Evidencia debe
  existir. Revisiones append-only; nadie reemplaza la historia.
- `task` create: `{action:"create",title,owner_member_id,depends_on?:[task_id]}`.
  Dependencias existentes evitan ciclos por inserción; no son ejecución de tareas.
  Otras: `{action:"claim"|"block"|"submit"|"accept"|"reject",task_id,note,evidence_ids?}`.
  Sólo propietario claim/block/submit. claim requiere dependencias aceptadas.
  submit necesita evidencia. accept/reject requieren evidencia y otro revisor
  ajeno a la cadena de mando. Estado accepted es juicio registrado, no prueba real.
- `learning` propose: `{action:"propose",title,failure,proposed_change,retest_result,evidence_ids:[id]}`.
  Revisión: `{action:"accept"|"reject",learning_id,note,evidence_ids:[id]}`.
  Prohibida auto-revisión y conflicto jerárquico. Aceptar conserva `installed=false`,
  `trained=false`, `effectiveness_verified=false`. No permite código ejecutable.

Límites: hasta32 miembros, 10.000 eventos, 8MiB por ledger, 6.000 caracteres por
texto general,20 evidencias por referencia. Al alcanzar límite, falla; no elimina
ni resume datos automáticamente. Cancelación antes del commit no escribe; una
respuesta interrumpida tras commit puede consultarse/repetirse con idempotencia.

Los registros son compartidos dentro de la organización; no escribir secretos ni
datos personales innecesarios. La independencia reduce conflictos, no certifica
competencia o veracidad. El plugin no impone locks sobre archivos del proyecto,
no autoriza operaciones financieras ni despliegues y no salta las políticas DSH.
