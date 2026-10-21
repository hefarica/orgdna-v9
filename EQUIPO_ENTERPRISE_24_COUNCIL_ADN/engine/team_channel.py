"""Canal dirigido de la organizacion: publicacion por miembro, @mencion y asignacion.

Port REA de agentscope-ai/agentscope@26ec620 (Apache-2.0): semantica de
_TeamAssign/_team_pipeline.py y routing de _in_memory_message_bus.py, reescrita en
las convenciones de este engine. Vectores: tests de pipeline_team_test.py e
in_memory_message_bus_test.py (transcriptos como casos del destino en
tests_team_channel.py; cuaderno de lectura en docs/rea/agentscope_notebook.md).

Que hace este modulo (todo en memoria, stdlib puro, offline, sin efectos al importar):

  * valida un roster (ids y nombres unicos; nombre/id sin espacios ni "@" y distinto
    del destino reservado "all"): invariante de construccion portada de TeamPipeline
    (_team_pipeline.py:152, "Member names must be unique...") + techo de 32 miembros
    del roster de cordis (runtime.mjs validateConfig) + jefes existentes
    (engine/gang_assembly.py:123);
  * publish(sender, to=member_id|"all", text, ...) publica dirigido o a todos con
    inbox POR MIEMBRO y orden preservado — Mode A del bus (ack-on-read destructivo,
    FIFO, max_count con el resto persistente, purga de expirados ANTES del append,
    ttl_secs=0 expira ya): _in_memory_message_bus.py:130-199;
  * una @mencion inicial ("@Nombre prompt") produce una tarea dirigida al miembro
    nombrado, validado contra el roster: semantica _TeamAssign ({member: enum de
    nombres, prompt: string}, permiso always-allow para asignar,
    _team_pipeline.py:51-99); "@Desconocido ..." rechaza la publicacion entera;
  * assign(sender, member, task, ...) crea la asignacion directa (solo roster).
    Dentro de un miembro las asignaciones avanzan en ORDEN DE LLAMADA y una sola
    claimed a la vez (run_group secuencial, _team_pipeline.py:305-337); entre
    miembros no hay orden (corren concurrentes, run_all :339-352);
  * claim/block/submit/accept/reject con los mismos campos que el ledger de
    cordis_extension/runtime.mjs:190-215 (owner_member_id, status
    open->claimed->submitted->accepted/rejected, history[{actor, action, at, note,
    evidence_ids}]) y revision independiente por cadena de mando (runtime.mjs:240-251);
  * ledger_view() serializa mensajes/tareas/evidencia/audit con los mismos nombres
    de campo que el ledger, devolviendo COPIAS (disciplina de copia del
    registry_getall, _in_memory_message_bus.py:509).

Que NO hace, por diseno (y se declara):

  * no ejecuta agentes ni modelos ni corre la delegacion (eso es P1/P3): el canal
    crea y enruta la asignacion, no la ejecuta. Por eso los vectores de pipeline que
    exigen stream de eventos, HITL por reply_id, cancelacion y join de siblings
    (pipeline_team_test.py:271, :507, :932, :1018; pipeline_team_cleanup_test.py:51)
    se declaran NO PORTABLES en tests_team_channel.py;
  * no persiste en disco, no abre red, no instala nada, no define contenedores
    mutables de nivel de modulo;
  * no porta idempotency-receipts ni session_bindings de runtime.mjs (no hay
    sesiones aqui): la compatibilidad con el ledger es de CAMPOS (to/text/topic,
    claim/submit, base id/actor/created_at/provenance/content_verified), no de bytes
    cargables. Divergencias declaradas: los row id usan el formato monotono "<seq>-0"
    del bus (comparables por prefijo numerico, preserva orden de llamada) en vez del
    UUID del ledger; provenance vale "engine.team_channel"; las filas de tarea creadas
    con prompt llevan el campo adicional "prompt" (superconjunto aditivo).

Decisiones documentadas del port:

  * ttl_secs vive en la ENTREGA de inbox (Mode A), no en la fila del mensaje: el log
    de mensajes es append-only como messages[] del ledger;
  * "all" entrega una entrada de inbox POR destinatario (doctrina _base.py:33-40:
    el fan-out se hace escribiendo una entrada por destinatario sobre Mode A);
  * submit sin salida usa la constante portada FINISHED_WITHOUT_REPLY
    (_team_pipeline.py:332, "The member finished without a reply.");
  * la fila del mensaje conserva el texto crudo (recortado solo en los extremos,
    como text() de runtime.mjs): la normalizacion es solo para rutear — port del
    vector "input reparable" (pipeline_team_test.py:550);
  * las operaciones dirigidas a un miembro validan roster y rechazan a desconocidos
    ("Target outside roster", runtime.mjs:169). Divergencia consciente con el bus de
    claves opacas (drain de clave inexistente -> []): aqui el drain de un miembro del
    roster con inbox vacia devuelve [], y el miembro fuera del roster se rechaza.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import time

SCHEMA_VERSION = 'engine.team_channel/1'
LEDGER_PROTOCOL = 'orgdna-cordis/1'   # espejo declarativo; NO es un estado cargable
PROVENANCE = 'engine.team_channel'

# Constante portada de _team_pipeline.py:332.
FINISHED_WITHOUT_REPLY = 'The member finished without a reply.'
DEFAULT_TOPIC = 'coordination'        # runtime.mjs:177
BROADCAST_TO = 'all'

MAX_MEMBERS = 32                      # runtime.mjs validateConfig: roster 1..32
MAX_TEXT = 6000                       # runtime.mjs text() default
MAX_TOPIC = 160                       # runtime.mjs:177 topic
MAX_TITLE = 300                       # runtime.mjs:195 title
MAX_LOCATOR = 2000                    # runtime.mjs:182 locator
MAX_DEPENDENCIES = 32                 # runtime.mjs:194
MAX_EVIDENCE_REFS = 20                # runtime.mjs:171
DEFAULT_DRAIN = 100                   # _in_memory_message_bus.py queue_drain default

TASK_STATUSES = ('open', 'claimed', 'blocked', 'submitted', 'accepted', 'rejected')
CLAIMABLE_FROM = ('open', 'blocked', 'rejected')   # runtime.mjs:202
# Orden de llamada dentro de un miembro (run_group secuencial, _team_pipeline.py:305-337):
# una tarea puede reclamarse cuando todas las ANTERIORES del mismo dueno terminaron.
_FINISHED_FOR_ORDER = ('submitted', 'accepted')

_MENTION_RE = re.compile(r'^@(\S+)(?:[ \t]+(.*))?$')
_SHA256_RE = re.compile(r'^[a-f0-9]{64}$')


class ChannelError(ValueError):
    """Error tipado del canal: todo rechazo lleva codigo y motivo deterministas."""


def _text(value, field, limit):
    """text() de runtime.mjs: no vacio, recortado en extremos, tope de largo, sin control."""
    if not isinstance(value, str):
        raise ChannelError(f'{field}: se requiere texto.')
    trimmed = value.strip()
    if not trimmed:
        raise ChannelError(f'{field}: texto vacio o solo espacios.')
    if len(trimmed) > limit:
        raise ChannelError(f'{field}: supera {limit} caracteres.')
    if any(ord(char) < 32 and char != '\t' for char in trimmed):
        raise ChannelError(f'{field}: caracteres de control no admitidos.')
    return trimmed


def entry_seq(entry_id):
    """Prefijo numerico de un id "<seq>-0" (bus _next_id): la unica forma de compararlos.

    Los ids "<seq>-0" NO son ordenables lexicograficamente (seq > 9): toda comparacion
    de orden parsea el prefijo (log_read:267, log_trim:298 del bus).
    """
    try:
        return int(str(entry_id).split('-', 1)[0])
    except ValueError:
        raise ChannelError(f'entry_id: formato "<seq>-0" requerido, se recibio {entry_id!r}.') from None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False)
                          .encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ChannelMember:
    """Miembro del roster. Port de TeamMember {agent, description} (_team_pipeline.py:37-48):
    la identidad por la que se lo referencia es member_id (para publicar/asignar) y
    name (para @mencion); role hace de descripcion del miembro."""
    member_id: str
    name: str
    role: str = ''
    reports_to: str | None = None


class _InboxQueue:
    """Mode A del bus: cola ack-on-read, at-most-once (destructiva), por clave.

    Port de _in_memory_message_bus.py:130-199. Los ids monotonos "<seq>-0" viven en el
    canal (contador global); la cola guarda (payload, expire_at) y purga expirados
    ANTES de cada append (:158) para que una clave jamas drenada quede acotada.
    """

    def __init__(self, clock):
        self._clock = clock
        self._queues = {}

    def push(self, key, payload, ttl_secs=None):
        queue = self._queues.setdefault(key, [])
        now = self._clock()
        queue[:] = [entry for entry in queue if entry[1] is None or entry[1] > now]
        expire_at = None if ttl_secs is None else now + ttl_secs
        queue.append((payload, expire_at))

    def drain(self, key, max_count):
        queue = self._queues.get(key, [])
        alive = [entry for entry in queue if entry[1] is None or entry[1] > self._clock()]
        self._queues[key] = alive[max_count:]          # destructivo: el resto persiste
        return [copy.deepcopy(entry[0]) for entry in alive[:max_count]]

    def delete(self, key):
        self._queues.pop(key, None)                    # idempotente (:191-199)


class TeamChannel:
    """Canal de la organizacion: publicacion dirigida, @mencion y asignacion tipo colega."""

    def __init__(self, members, clock=None):
        self._clock = clock if clock is not None else time.time
        self._members = self._build_roster(members)
        self._by_id = {member.member_id: member for member in self._members}
        self._by_name = {member.name: member for member in self._members}
        self._queues = _InboxQueue(self._clock)
        self._subscribers = {member.member_id: [] for member in self._members}
        self._messages = []   # orden de publicacion (append-only)
        self._tasks = []      # orden de llamada (append-only)
        self._evidence = []
        self._audit = []
        self._version = 0
        self._seq = 0

    # ------------------------------------------------------------------ roster

    @staticmethod
    def _build_roster(members):
        if not isinstance(members, (list, tuple)):
            raise ChannelError('members: se requiere una lista de declaraciones de miembro.')
        if not 1 <= len(members) <= MAX_MEMBERS:
            raise ChannelError(f'members: el roster admite de 1 a {MAX_MEMBERS} miembros.')
        built, seen_ids, seen_names = [], set(), set()
        for index, raw in enumerate(members):
            if not isinstance(raw, dict):
                raise ChannelError(f'members[{index}]: se requiere objeto.')
            member_id = _text(raw.get('member_id'), f'members[{index}].member_id', 120)
            name = _text(raw.get('name'), f'members[{index}].name', 120)
            for token, field in ((member_id, 'member_id'), (name, 'name')):
                if any(char.isspace() for char in token) or '@' in token:
                    raise ChannelError(f"members[{index}].{field}: sin espacios ni '@' "
                                       '(la mencion y el rutero exigen tokens).')
                if token == BROADCAST_TO:
                    raise ChannelError(f"members[{index}].{field}: 'all' es un destino reservado.")
            if member_id in seen_ids:
                raise ChannelError(f'duplicate_member: member_id repetido en el roster: {member_id}.')
            if name in seen_names:
                # Port de _team_pipeline.py:152 (nombres unicos y distintos del leader):
                # aqui no hay leader, pero el nombre es la clave de la @mencion.
                raise ChannelError(f'duplicate_member: nombre repetido en el roster: {name} '
                                   '(los nombres de miembro deben ser unicos).')
            seen_ids.add(member_id)
            seen_names.add(name)
            role = raw.get('role') or ''
            role = _text(role, f'members[{index}].role', 200) if role else ''
            reports_to = raw.get('reports_to')
            if reports_to is not None:
                reports_to = _text(reports_to, f'members[{index}].reports_to', 120)
            built.append(ChannelMember(member_id=member_id, name=name, role=role,
                                       reports_to=reports_to))
        known = {member.member_id for member in built}
        for member in built:
            if member.reports_to is not None and member.reports_to not in known:
                raise ChannelError(f'unknown_member: {member.member_id} reporta a '
                                   f'{member.reports_to}, que no esta en el roster.')
        return tuple(built)

    def resolve(self, ref):
        """Resuelve member_id exacto primero, luego name exacto; desconocido rechaza."""
        member = self._by_id.get(ref) if isinstance(ref, str) else None
        if member is None and isinstance(ref, str):
            member = self._by_name.get(ref)
        if member is None:
            raise ChannelError(f'unknown_member: {ref!r} no esta en el roster (target outside roster).')
        return member

    @property
    def members(self):
        return self._members

    @property
    def member_ids(self):
        return tuple(member.member_id for member in self._members)

    @property
    def names(self):
        return tuple(member.name for member in self._members)

    # ------------------------------------------------------------- internos

    def _next_id(self):
        self._seq += 1
        return f'{self._seq}-0'          # formato "<seq>-0" del bus (_next_id :113-124)

    def _stamp(self):
        return datetime.fromtimestamp(self._clock(), timezone.utc).isoformat().replace('+00:00', 'Z')

    def _record(self, operation, actor_id, record_id, payload):
        self._version += 1
        self._audit.append({'seq': self._version, 'actor': actor_id, 'operation': operation,
                            'record_id': record_id, 'at': self._stamp(),
                            'request_digest': _digest([operation, payload])})

    def _notify(self, member_id, row):
        for handler in list(self._subscribers.get(member_id, ())):
            handler(copy.deepcopy(row))

    # ------------------------------------------------------------- mensajes

    @staticmethod
    def parse_mention(text):
        """Parse puro de "@Nombre prompt" inicial: (nombre, prompt) o None.

        Tolerante a espacios (equivalente del parse con repair del fuente: un input
        que solo parsea tras reparar igualmente se enruta, pipeline_team_test.py:550).
        NO valida roster: la validacion del destinatario ocurre al publicar.
        """
        if not isinstance(text, str):
            return None
        match = _MENTION_RE.match(text.strip())
        if match is None:
            return None
        return match.group(1), (match.group(2) or '').strip()

    def publish(self, sender, to=BROADCAST_TO, text='', topic=DEFAULT_TOPIC,
                ttl_secs=None, task_title=None, task_depends_on=()):
        """Publica un mensaje dirigido (to=member_id|'all') y enruta la @mencion inicial.

        Devuelve {'message': fila, 'task': fila | None}. El texto crudo se conserva en
        la fila (recortado solo en extremos); la normalizacion es solo para rutear.
        """
        actor = self.resolve(sender)
        if to == BROADCAST_TO:
            target = BROADCAST_TO
        else:
            target = self.resolve(to).member_id
        body = _text(text, 'text', MAX_TEXT)
        topic_value = _text(topic, 'topic', MAX_TOPIC)
        if ttl_secs is not None and (isinstance(ttl_secs, bool) or
                                     not isinstance(ttl_secs, (int, float)) or ttl_secs < 0):
            raise ChannelError('ttl_secs: se requiere numero >= 0 o None.')
        # Validacion completa ANTES de mutar (fail-closed): mencion y tarea preparada.
        mention = self.parse_mention(body)
        prepared = None
        if mention is not None:
            name, prompt = mention
            member = self._by_name.get(name)
            if member is None:
                raise ChannelError(f'unknown_member: la mencion @{name} no existe en el roster '
                                   '(el enum de _TeamAssign solo admite miembros existentes).')
            # Asignar a un miembro del roster siempre esta permitido (_team_pipeline.py:89-99);
            # el prompt viaja autocontenido en el mensaje.
            prepared = self._prepare_task(actor, member, prompt, task_title, task_depends_on)
        row = {'id': self._next_id(), 'actor': actor.member_id, 'created_at': self._stamp(),
               'provenance': PROVENANCE, 'content_verified': False,
               'to': target, 'text': body, 'topic': topic_value}
        self._messages.append(row)
        if prepared is not None:
            assignment = self._commit_task(prepared)
        else:
            assignment = None
        recipients = self.member_ids if target == BROADCAST_TO else (target,)
        for member_id in recipients:
            self._queues.push(member_id, copy.deepcopy(row), ttl_secs)
            self._notify(member_id, row)
        self._record('message', actor.member_id, row['id'],
                     {'to': target, 'text': body, 'topic': topic_value})
        return {'message': copy.deepcopy(row),
                'task': copy.deepcopy(assignment) if assignment is not None else None}

    def visible_messages(self, member):
        """Vista no destructiva: filtro exacto de runtime.mjs:151
        (to == 'all' || to == miembro || actor == miembro), en orden de publicacion."""
        member = self.resolve(member)
        return copy.deepcopy([row for row in self._messages
                              if row['to'] == BROADCAST_TO or row['to'] == member.member_id
                              or row['actor'] == member.member_id])

    def inbox(self, member, max_count=DEFAULT_DRAIN):
        """Drain del inbox del miembro: FIFO, destructivo, respeta max_count (Mode A)."""
        member = self.resolve(member)
        if isinstance(max_count, bool) or not isinstance(max_count, int) or max_count < 1:
            raise ChannelError('max_count: se requiere entero >= 1.')
        return self._queues.drain(member.member_id, max_count)

    def inbox_delete(self, member):
        """Vacia el inbox del miembro; idempotente (queue_delete, :191-199)."""
        member = self.resolve(member)
        self._queues.delete(member.member_id)

    def subscribe(self, member, handler, on_ready=None):
        """Suscribe un handler al inbox-del-miembro (Mode D). Devuelve el desuscriptor.

        on_ready se invoca UNA vez inmediatamente despues del registro y ANTES de
        cualquier entrega posterior (:346-347): cierra la carrera
        publicar-inmediatamente-despues-de-suscribir. Publicar sin suscriptores es
        no-op (:307-320).
        """
        member = self.resolve(member)
        if not callable(handler):
            raise ChannelError('handler: se requiere callable.')
        if on_ready is not None and not callable(on_ready):
            raise ChannelError('on_ready: se requiere callable.')
        entries = self._subscribers[member.member_id]
        entries.append(handler)
        if on_ready is not None:
            on_ready()

        def _dispose():
            if handler in entries:
                entries.remove(handler)
        return _dispose

    # ------------------------------------------------------------- tareas

    def _find_task(self, task_id):
        for row in self._tasks:
            if row['id'] == task_id:
                return row
        raise ChannelError(f'unknown_task: no existe la tarea {task_id!r}.')

    def _check_evidence_ids(self, value):
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_EVIDENCE_REFS:
            raise ChannelError(f'invalid_evidence: se requieren de 1 a {MAX_EVIDENCE_REFS} '
                               'referencias de evidencia existentes.')
        known = {row['id'] for row in self._evidence}
        if len(set(value)) != len(value) or any(ident not in known for ident in value):
            raise ChannelError('invalid_evidence: las referencias deben ser unicas y existentes.')

    def _check_dependencies(self, value):
        if not isinstance(value, (list, tuple)) or len(value) > MAX_DEPENDENCIES:
            raise ChannelError(f'invalid_dependency: depends_on admite hasta {MAX_DEPENDENCIES} '
                               'tareas existentes.')
        known = {row['id'] for row in self._tasks}
        if len(set(value)) != len(value) or any(ident not in known for ident in value):
            raise ChannelError('invalid_dependency: las dependencias deben ser tareas '
                               'existentes y unicas.')
        return list(value)

    def _prepare_task(self, actor, member, task, title, depends_on):
        """Valida la asignacion sin mutar nada (fail-closed antes de publicar/asignar)."""
        prompt = ''
        if task not in (None, ''):
            prompt = _text(task, 'task', MAX_TEXT)
        if title in (None, ''):
            if not prompt:
                raise ChannelError('title: requerido cuando el prompt esta vacio.')
            title_value = prompt[:MAX_TITLE]           # derivado determinista
        else:
            title_value = _text(title, 'title', MAX_TITLE)
        dependencies = self._check_dependencies(depends_on or ())
        return {'actor': actor.member_id, 'owner': member.member_id, 'title': title_value,
                'prompt': prompt, 'depends_on': dependencies}

    def _commit_task(self, prepared):
        row = {'id': self._next_id(), 'actor': prepared['actor'],
               'created_at': self._stamp(), 'provenance': PROVENANCE,
               'content_verified': False, 'title': prepared['title'],
               'owner_member_id': prepared['owner'], 'depends_on': prepared['depends_on'],
               'status': 'open', 'evidence_ids': [], 'history': []}
        if prepared['prompt']:
            row['prompt'] = prepared['prompt']         # superconjunto aditivo (docstring)
        self._tasks.append(row)
        self._record('task', prepared['actor'], row['id'],
                     {'action': 'create', 'title': prepared['title'],
                      'owner_member_id': prepared['owner'],
                      'depends_on': prepared['depends_on']})
        return row

    def assign(self, sender, member, task, title=None, depends_on=()):
        """Asignacion directa: valida member contra el roster y rechaza a desconocidos.

        Semantica _TeamAssign: llamada explicita del emisor -> tarea con destinatario
        validado; asignar a un miembro del roster siempre esta permitido (:89-99).
        """
        actor = self.resolve(sender)
        owner = self.resolve(member)
        prepared = self._prepare_task(actor, owner, task, title, depends_on)
        return copy.deepcopy(self._commit_task(prepared))

    def _owner_only(self, actor, row):
        if actor.member_id != row['owner_member_id']:
            raise ChannelError('not_task_owner: solo el dueno asignado puede actuar '
                               '(Only assigned owner may act).')

    def _transition(self, row, actor, action, note, evidence_ids):
        note_value = _text(note if note is not None else action, 'note', MAX_TEXT)
        row['history'].append({'actor': actor.member_id, 'action': action,
                               'at': self._stamp(), 'note': note_value,
                               'evidence_ids': list(evidence_ids)})
        row['updated_at'] = self._stamp()
        self._record('task', actor.member_id, row['id'],
                     {'action': action, 'task_id': row['id'], 'note': note_value,
                      'evidence_ids': list(evidence_ids)})

    def claim(self, actor, task_id, note=None):
        """open/blocked/rejected -> claimed. Solo el dueno; dependencias aceptadas
        (runtime.mjs:202-204); orden de llamada dentro del miembro (run_group)."""
        member = self.resolve(actor)
        row = self._find_task(task_id)
        self._owner_only(member, row)
        if row['status'] not in CLAIMABLE_FROM:
            raise ChannelError(f"invalid_transition: claim no aplica desde '{row['status']}'.")
        for dependency in row['depends_on']:
            dep = self._find_task(dependency)
            if dep['status'] != 'accepted':
                raise ChannelError(f"dependencies_not_accepted: {dependency} esta en "
                                   f"status '{dep['status']}'.")
        for other in self._tasks:
            if other['id'] == row['id'] or other['owner_member_id'] != row['owner_member_id']:
                continue
            if other['status'] == 'claimed':
                raise ChannelError('invalid_transition: el miembro ya tiene una tarea claimed; '
                                   'sus asignaciones avanzan en orden de llamada.')
            if entry_seq(other['id']) < entry_seq(row['id']) and other['status'] not in _FINISHED_FOR_ORDER:
                raise ChannelError(f'invalid_transition: la asignacion {other["id"]} es anterior '
                                   'en orden de llamada y aun no termina.')
        row['status'] = 'claimed'
        self._transition(row, member, 'claim', note, [])
        return copy.deepcopy(row)

    def block(self, actor, task_id, note=None):
        """claimed -> blocked (parqueo del dueno; re-claimable despues)."""
        member = self.resolve(actor)
        row = self._find_task(task_id)
        self._owner_only(member, row)
        if row['status'] != 'claimed':
            raise ChannelError(f"invalid_transition: block no aplica desde '{row['status']}'.")
        row['status'] = 'blocked'
        self._transition(row, member, 'block', note, [])
        return copy.deepcopy(row)

    def submit(self, actor, task_id, evidence_ids, output='', note=None):
        """claimed -> submitted con evidencia. Sin salida, el resultado portado es
        FINISHED_WITHOUT_REPLY (_team_pipeline.py:332)."""
        member = self.resolve(actor)
        row = self._find_task(task_id)
        self._owner_only(member, row)
        if row['status'] != 'claimed':
            raise ChannelError(f"invalid_transition: submit no aplica desde '{row['status']}'.")
        self._check_evidence_ids(evidence_ids)
        if note is None:
            note = output if isinstance(output, str) and output.strip() else FINISHED_WITHOUT_REPLY
        row['evidence_ids'] = list(evidence_ids)
        row['status'] = 'submitted'
        self._transition(row, member, 'submit', note, evidence_ids)
        return copy.deepcopy(row)

    def _ancestors(self, member_id):
        chain, current, seen = set(), member_id, set()
        roster = self._by_id
        while current in roster:
            parent = roster[current].reports_to
            if parent is None:
                break
            if parent in seen:
                raise ChannelError('invalid_management_cycle: ciclo en la cadena de mando.')
            seen.add(parent)
            chain.add(parent)
            current = parent
        return chain

    def accept(self, reviewer, task_id, note=None, evidence_ids=()):
        """submitted -> accepted por revisor independiente (runtime.mjs:207-212, 240-251)."""
        return self._review(reviewer, task_id, 'accept', note, evidence_ids)

    def reject(self, reviewer, task_id, note=None, evidence_ids=()):
        return self._review(reviewer, task_id, 'reject', note, evidence_ids)

    def _review(self, reviewer, task_id, action, note, evidence_ids):
        member = self.resolve(reviewer)
        row = self._find_task(task_id)
        if row['status'] != 'submitted':
            raise ChannelError(f"invalid_transition: {action} no aplica desde '{row['status']}'.")
        owner = row['owner_member_id']
        if member.member_id == owner or member.member_id in self._ancestors(owner) \
                or owner in self._ancestors(member.member_id):
            raise ChannelError('dependent_reviewer: se exige un revisor independiente fuera '
                               'de la cadena de mando del autor.')
        self._check_evidence_ids(evidence_ids)
        row['review_evidence_ids'] = list(evidence_ids)
        row['status'] = 'accepted' if action == 'accept' else 'rejected'
        row['reviewer_member_id'] = member.member_id
        self._transition(row, member, action, note, evidence_ids)
        return copy.deepcopy(row)

    def record_evidence(self, actor, locator, sha256, summary):
        """Evidencia con SHA-256 hexadecimal (runtime.mjs:180-183)."""
        member = self.resolve(actor)
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            raise ChannelError('sha256: se requiere un digest SHA-256 hexadecimal de 64.')
        row = {'id': self._next_id(), 'actor': member.member_id, 'created_at': self._stamp(),
               'provenance': PROVENANCE, 'content_verified': False,
               'locator': _text(locator, 'locator', MAX_LOCATOR), 'sha256': sha256,
               'summary': _text(summary, 'summary', MAX_TEXT), 'artifact_read_by_plugin': False}
        self._evidence.append(row)
        self._record('evidence', member.member_id, row['id'],
                     {'locator': row['locator'], 'sha256': sha256})
        return copy.deepcopy(row)

    # ------------------------------------------------------------- serializacion

    def ledger_view(self):
        """Vista serializable con los nombres de campo del ledger de cordis.

        Devuelve COPIAS profundas: mutar la salida no toca el estado del canal
        (disciplina de registry_getall, _in_memory_message_bus.py:509). No es un
        estado cargable por SharedLedger (sin receipts/member_ids): la compatibilidad
        es de campos (to/text/topic, claim/submit), ver docstring del modulo.
        """
        return {
            'schema_version': SCHEMA_VERSION,
            'ledger_protocol': LEDGER_PROTOCOL,
            'version': self._version,
            'members': [{'member_id': member.member_id, 'name': member.name,
                         'role': member.role, 'reports_to': member.reports_to}
                        for member in self._members],
            'messages': copy.deepcopy(self._messages),
            'tasks': copy.deepcopy(self._tasks),
            'evidence': copy.deepcopy(self._evidence),
            'audit': copy.deepcopy(self._audit),
        }
