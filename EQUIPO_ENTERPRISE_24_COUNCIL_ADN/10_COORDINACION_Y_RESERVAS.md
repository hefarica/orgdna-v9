# Coordinación de escritura y Council

Los 24 perfiles son el mismo equipo en ambas fases. Council usa all, maxConcurrency=24, parallel/fork/stop y activationMode=manual: todos pueden opinar sobre el mismo snapshot, sin editar ni ejecutar el proyecto. Implementación usa adaptive, maxConcurrency=3 y activationMode=manual. El límite de tres editores no reduce el Council a tres personas. La consolidación del CEO se realiza después en una tarea individual; no relanza al Council-all.

## Reservas cooperativas

El registro local admite como máximo 3 tickets de escritura activos en total, entre todos los proyectos y workspaces que comparten ese almacén. No es un límite global entre equipos, instalaciones o almacenes separados. Cada ticket identifica agente, tarea, workspace absoluto, rutas relativas, SHA base completo, vencimiento y versión esperada.

Las rutas se normalizan antes de comprobar colisiones: la misma ruta y su relación padre/hijo se solapan, incluso si se declaran workspaces anidados. Se rechazan traversal y rutas fuera del workspace. Rutas distintas no resuelven por sí solas conflictos semánticos: requieren DAG, contratos de productor/consumidor y revisión de integración.

TTL predeterminado: 900 segundos; rango admitido: 60–3600. Sólo el mismo agente y tarea pueden renovar o liberar su ticket. No se reactivan tickets expirados/liberados. Las escrituras comprueban expected_version; una versión obsoleta obliga a recargar. La idempotencia repite únicamente la misma adquisición todavía activa, sin transferir propietario ni revivir un ticket.

## Límites reales

El bloqueo interno serializa el archivo del registro para evitar carreras entre clientes cooperativos; no bloquea archivos del repositorio, editores externos, shells, navegador ni llamadas DSH. El SHA se registra, no se verifica contra Git por registrar el ticket. Identidad declarada, reserva y autorización efectiva son comprobaciones distintas.

Un handoff debe incluir SHA base y SHA candidato, worktree aislado, dueño, rutas reservadas, dependencias, productor/consumidor, contrato de datos, pruebas y limitaciones. Aislar también puertos y contextos de navegador. La integración debe comprobar que el consumidor usa la versión acordada y que nadie modificó el mismo archivo fuera del protocolo. No se promete que los agentes jamás se pisen por el mero texto de un prompt o por registrar una reserva.

No se han lanzado agentes, Council o pruebas del proyecto por crear una reserva. Antes de escribir se requiere permiso real, tarea y superficie aislada; después se libera la reserva y se entrega SHA y evidencia. Un programa externo puede ignorar este protocolo. La UI y los exports no deben afirmar un hardlock de filesystem ni un scheduler DSH conectado.

Guardar un proyecto conserva un snapshot histórico local. Cargarlo no reactiva sus tickets; se consulta el registro durable vigente. El ZIP entrega sólo política, sin ledger operativo ni rutas/leases personales. Las descargas no crean, renuevan o liberan reservas.

## Política exacta

```json
{
  "version": 1,
  "max_writers": 3,
  "council_participants": 24,
  "council_read_only": true,
  "implementation_max_concurrency": 3,
  "global_scope": "all_projects_and_workspaces_in_this_local_store",
  "lease_fields": [
    "owner_agent_id",
    "task_id",
    "workspace",
    "paths",
    "base_sha",
    "ttl_seconds",
    "expected_version"
  ],
  "ttl_seconds": {
    "default": 900,
    "minimum": 60,
    "maximum": 3600
  },
  "path_conflicts": "same_path_or_parent_child_in_normalized_workspace",
  "renewal_and_release": "same_owner_and_task_only",
  "historical_snapshot_reactivates_leases": false,
  "filesystem_lock_enforced": false,
  "dsh_enforced": false,
  "base_sha_verified_by_app": false,
  "live_leases_included": false
}
```
