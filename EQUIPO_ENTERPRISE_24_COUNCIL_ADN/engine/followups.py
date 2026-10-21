"""Brecha P3 — follow-ups de compromisos: detectar -> perseguir -> reportar, acotado.

DECLARACION DE ORIGEN: implementacion composicional PROPIA, SIN FUENTE EXTERNA.
El barrido REA de la mision no encontro candidato con este mecanismo (perseguir
compromisos conversacionales con backoff fijo acotado sobre un canal de equipo);
por eso este modulo NO es un port y NO cita owner/name@sha: no hay upstream. No
se adapto codigo, configuracion, endpoint ni valor ajeno de ningun repo. Sus dos
puntos de composicion son modulos LOCALES de este repositorio:

  * engine/team_channel.py (el port P2, que cita agentscope-ai/agentscope@26ec620
    en su propio docstring): el canal es la fuente de mensajes a escanear
    (ledger_view()['messages'], append-only en orden de publicacion) y el medio de
    entrega de recordatorios y escalaciones (publish() escribe el inbox por
    miembro, Modo A del bus). El roster se valida con channel.resolve().

  * engine/scheduler.py, SOLO LECTURA (no se modifica): se importan RUN_STATES y
    TERMINAL_STATES unicamente para FIJAR por contrato que el vocabulario de
    follow-ups ('chasing'/'escalated'/'reported') es DISJUNTO del vocabulario del
    scheduler. La brecha que este modulo cubre vive documentada ahi: hoy un nodo
    'failed'/'blocked' jamas vuelve a estar listo (scheduler.py:298-303) y solo
    una decision explicita lo reabre (:436-444). Este modulo NO reintenta nodos
    del scheduler ni toca sus runs: persigue, FUERA DE BANDA, los compromisos que
    los miembros expresan en el canal. El scheduler decide; el follow-up insiste.

  * engine/gang_supervisor.py:19-21 (doctrina de tick manual, citada): igual que
    el supervisor, aqui NO hay demonio — el tick es EXPLICITO y lo dispara quien
    orquesta (panel, launcher, cron o test).

Semantica (la que prescribe la brecha P3):

  1. DETECCION (determinista, sin LLM): un mensaje del canal cuyo texto contiene
     un compromiso accionable — marcador textual ('hare/hare', 'pendiente(s)',
     'cuando', 'luego', 'despues/después', 'voy a', 'me encargo', 'haremos';
     superconjunto del minimo prescrito) SEGUIDO de una palabra (la aproximacion
     de "verbo/sustantivo" es 'cualquier palabra': sin diccionario ni POS, para
     mantenerla determinista) — genera UNA tarea de follow-up dirigida al EMISOR
     comprometido, en estado nuevo 'chasing'. Una tarea por mensaje (primer match).
     El motor ignora sus propios mensajes (actor == agente del motor): el texto
     del recordatorio contiene 'pendiente' a proposito para que el salto sea
     observable en los tests. Falsos positivos/negativos son aceptados y
     declarados: el costo de un falso positivo queda ACOTADO por el tope de
     recordatorios.

  2. PERSECUCION (backoff fijo, acotado): en cada tick, una tarea 'chasing' sin
     reporte cuyo recordatorio esta vencido emite UN recordatorio al inbox del
     comprometido y programa el proximo a now + reminder_interval (intervalo
     FIJO; el primero vence a creacion + intervalo: el compromiso tiene su
     ventana de gracia). Tras max_reminders (default 3, el prescrito) la tarea
     queda 'escalated': UNA escalacion al inbox del supervisor y NUNCA mas
     recordatorios — reintento infinito prohibido por diseno. La escalacion
     vence en el tick en que VENCIERIA el siguiente recordatorio (el ultimo
     recordatorio tiene su ventana completa para ser respondido).

  3. REPORTE (determinista, sin LLM): cuando el comprometido publica un mensaje
     con artefacto/resultado — frase de cierre ('ya esta/ya está', 'entregado/a',
     'entregue/entregué', 'subido/a', 'subi/subí', 'hecho' (salvo 'de hecho'),
     'completado/a', 'complete/completé', 'finalizado/a', 'listo[:!.]') o marca
     de artefacto (sha256 de 64 hex, URL http(s), ruta con extension, archivo
     .py/.md/.../.pdf) — TODAS sus tareas 'chasing' abiertas pasan a 'reported' y
     se ARCHIVAN. El reporte se procesa ANTES que la persecucion dentro del
     tick: un reporte entregado cierra la tarea sin que ese tick recuerde. Un
     reporte tardio DESPUES de la escalacion NO reescribe historia: 'escalated'
     es terminal para el motor y el registro queda a la vista del supervisor.
     Un mismo mensaje puede cerrar chases viejos y abrir uno nuevo (reporta X y
     se compromete a Y): primero se cierra, luego se abre.

Determinismo integral: reloj inyectable, dedup por id de mensaje, orden de
publicacion para el escaneo, orden de creacion para la persecucion, y el tick en
dos fases fijas (escanear -> perseguir). Sin red, sin disco, sin hilos, sin
contenedores mutables de modulo, sin efectos al importar, stdlib pura.

Que NO hace (declarado): no ejecuta nada ni a nadie (no es P1), no reabre nodos
del scheduler, no juzga la CALIDAD del artefacto reportado (solo detecta la
senal), no hay NLP/LLM (regex documentada), y el tope MAX_ACTIVE_TASKS rechaza
nuevos compromisos con un evento 'commitment_skipped' VISIBLE — nunca silencioso.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import re
import time

try:
    from . import scheduler, team_channel
except ImportError:  # importacion suelta (validador de portabilidad)
    import scheduler, team_channel

SCHEMA_VERSION = 'engine.followups/1'
PROVENANCE = 'engine.followups'
FOLLOWUP_TOPIC = 'followups'          # topico de recordatorios y escalaciones

# Estados propios, DISJUNTOS de scheduler.RUN_STATES por contrato (ver docstring).
CHASING = 'chasing'
ESCALATED = 'escalated'
REPORTED = 'reported'
FOLLOWUP_STATES = (CHASING, ESCALATED, REPORTED)

# Consumo de SOLO LECTURA del scheduler: fija la disjuncion de vocabularios sin
# tocar una sola linea de scheduler.py.
SCHEDULER_RUN_STATES = frozenset(scheduler.RUN_STATES)
SCHEDULER_TERMINAL_STATES = frozenset(scheduler.TERMINAL_STATES)
VOCABULARY_OVERLAP = frozenset(FOLLOWUP_STATES) & SCHEDULER_RUN_STATES   # == set()

DEFAULT_REMINDER_INTERVAL_SECS = 3600.0   # backoff FIJO por defecto: 1 hora
MAX_REMINDERS_DEFAULT = 3                 # "3 recordatorios maximo" (brecha P3)
MAX_REMINDERS_CAP = 10                    # nunca reintento infinito
MAX_ACTIVE_TASKS = 512                    # techo del persecutor; skip visible
MAX_SNIPPET = 200                         # recorte del compromiso citado

# --- Deteccion de compromiso: marcador + UNA palabra despues (verbo/sustantivo
# --- aproximado por 'cualquier palabra'; sin diccionario, sin LLM).
_COMMITMENT_RE = re.compile(
    r'\b(?:har[eé]s?|har[eé]mos|pendientes?|cuando|luego|despu[eé]s|voy\s+a|me\s+encargo)'
    r'[ \t]+(\w+)',
    re.IGNORECASE,
)

# --- Deteccion de reporte: frase de cierre o marca de artefacto. 'de hecho'
# --- (marcador de discurso) se excluye con lookbehind; presente ('subo') NO
# --- cuenta: una promesa no es un reporte.
_REPORT_RE = re.compile(
    r'\bya\s+est[aá]\b'
    r'|\bentregad[oa]s?\b'
    r'|\bentregu[eé]\b'
    r'|\bsubid[oa]s?\b'
    r'|\bsub[ií]\b'
    r'|(?<![Dd]e )\bhecho\b'
    r'|\bcompletad[oa]s?\b'
    r'|\bcomplet[eé]\b'
    r'|\bfinalizad[oa]s?\b'
    r'|\blisto\s*[:!.]',
    re.IGNORECASE,
)
_ARTIFACT_RE = re.compile(
    r'\b[0-9a-f]{64}\b'                                              # sha256
    r'|https?://\S+'                                                  # URL
    r'|(?:[A-Za-z0-9_@.\-]+/)+[A-Za-z0-9_.\-]+\.[A-Za-z0-9]{1,8}\b'   # ruta/ext
    r'|\b[A-Za-z0-9_\-]+\.(?:py|md|txt|json|csv|log|pdf|rs|ts|js|toml|yaml|yml|zip)\b',
    re.IGNORECASE,
)


class FollowupsError(ValueError):
    """Error tipado del motor: todo rechazo lleva motivo determinista."""


def detect_commitment(text):
    """Pureza comprobable: devuelve el compromiso citado ('luego subo') o None."""
    if not isinstance(text, str):
        return None
    match = _COMMITMENT_RE.search(text)
    return None if match is None else match.group(0)[:MAX_SNIPPET]


def detect_report(text):
    """Pureza comprobable: True si el texto trae cierre o artefacto."""
    if not isinstance(text, str):
        return False
    return bool(_REPORT_RE.search(text) or _ARTIFACT_RE.search(text))


class FollowupsEngine:
    """El persecutor: tick() = escanear mensajes nuevos -> perseguir vencidos."""

    def __init__(self, channel, agent, supervisor, *, clock=None,
                 reminder_interval=DEFAULT_REMINDER_INTERVAL_SECS,
                 max_reminders=MAX_REMINDERS_DEFAULT):
        if not isinstance(channel, team_channel.TeamChannel):
            raise FollowupsError('channel: se requiere engine.team_channel.TeamChannel '
                                 '(composicion P3 sobre el canal P2).')
        if clock is not None and not callable(clock):
            raise FollowupsError('clock: se requiere un callable de tiempo.')
        try:
            self._agent_id = channel.resolve(agent).member_id
            self._supervisor_id = channel.resolve(supervisor).member_id
        except team_channel.ChannelError as exc:
            raise FollowupsError('roster: %s' % exc) from None
        if isinstance(reminder_interval, bool) or not isinstance(reminder_interval, (int, float)) \
                or reminder_interval < 0:
            raise FollowupsError('reminder_interval: se requiere numero >= 0 (segundos).')
        if isinstance(max_reminders, bool) or not isinstance(max_reminders, int) \
                or not 1 <= max_reminders <= MAX_REMINDERS_CAP:
            raise FollowupsError('max_reminders: entero 1..%d.' % MAX_REMINDERS_CAP)
        self._channel = channel
        self._clock = clock if clock is not None else time.time
        self._interval = float(reminder_interval)
        self._max_reminders = int(max_reminders)
        self._tasks = []            # activas (chasing + escalated), orden de creacion
        self._archive = []          # reportadas y archivadas
        self._processed = set()     # ids de mensaje ya escaneados (dedup)
        self._processed_order = []  # mismo conjunto, en orden de escaneo (vista)
        self._events = []           # log append-only
        self._seq = 0

    # ------------------------------------------------------------- internos

    def _stamp(self, now):
        return datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')

    def _event(self, kind, now, **fields):
        row = {'event': kind, 'at': self._stamp(now)}
        row.update(fields)
        return row

    def _history(self, task, kind, now, detail):
        task['history'].append({'event': kind, 'at': self._stamp(now), 'detail': detail})

    # ------------------------------------------------------------- fase 1: escaneo

    def _scan(self, now):
        """Mensajes NUEVOS del canal, en orden de publicacion: reportes cierran,
        compromisos abren. Los mensajes del propio motor nunca se procesan."""
        events = []
        for row in self._channel.ledger_view().get('messages', ()):
            message_id = row.get('id')
            if message_id in self._processed:
                continue
            self._processed.add(message_id)      # un mensaje se procesa UNA vez
            self._processed_order.append(message_id)
            actor = row.get('actor')
            if not isinstance(actor, str) or actor == self._agent_id:
                continue
            text = row.get('text') if isinstance(row.get('text'), str) else ''
            # 1) El reporte del comprometido cierra TODAS sus chases abiertas.
            if detect_report(text):
                for task in [t for t in self._tasks
                             if t['state'] == CHASING and t['owner_member_id'] == actor]:
                    self._close(task, message_id, now)
                    events.append(self._event('reported', now, task_id=task['id'],
                                              owner_member_id=actor, message_id=message_id))
            # 2) El compromiso del emisor abre UNA nueva chase dirigida a el.
            snippet = detect_commitment(text)
            if snippet is not None:
                if len(self._tasks) >= MAX_ACTIVE_TASKS:
                    events.append(self._event('commitment_skipped', now, message_id=message_id,
                                              owner_member_id=actor, reason='capacity',
                                              snippet=snippet))
                    continue
                task = self._create(actor, message_id, snippet, now)
                events.append(self._event('commitment', now, task_id=task['id'],
                                          owner_member_id=actor, message_id=message_id,
                                          snippet=task['snippet']))
        return events

    def _create(self, actor, message_id, snippet, now):
        self._seq += 1
        task = {'id': 'fu-%d' % self._seq, 'message_id': message_id,
                'owner_member_id': actor, 'snippet': snippet[:MAX_SNIPPET],
                'state': CHASING, 'reminders_sent': 0,
                'next_reminder_at': now + self._interval,   # gracia de un intervalo
                'created_at': self._stamp(now), 'updated_at': self._stamp(now),
                'escalated_at': None, 'reported_message_id': None, 'reported_at': None,
                'history': []}
        self._history(task, 'commitment', now, 'compromiso detectado en el mensaje %s' % message_id)
        self._tasks.append(task)
        return task

    def _close(self, task, message_id, now):
        task['state'] = REPORTED
        task['reported_message_id'] = message_id
        task['reported_at'] = self._stamp(now)
        task['updated_at'] = self._stamp(now)
        task['next_reminder_at'] = None
        self._history(task, 'reported', now, 'reporte en el mensaje %s' % message_id)
        self._tasks.remove(task)
        self._archive.append(task)

    # ------------------------------------------------------------- fase 2: persecucion

    def _fire(self, now):
        """Chases vencidas en orden de creacion: recordatorio o escalacion."""
        events = []
        for task in self._tasks:
            if task['state'] != CHASING:
                continue
            if task['next_reminder_at'] is None or task['next_reminder_at'] > now:
                continue
            if task['reminders_sent'] < self._max_reminders:
                count = task['reminders_sent'] + 1
                # El texto lleva 'pendiente' A PROPOSITO: el motor debe saltarse sus
                # propios mensajes (actor == agente) y los tests lo demuestran.
                self._channel.publish(
                    self._agent_id, to=task['owner_member_id'], topic=FOLLOWUP_TOPIC,
                    text='follow-up %d/%d: %s tiene un compromiso pendiente de entrega: "%s" '
                         '(tarea %s).' % (count, self._max_reminders, task['owner_member_id'],
                                          task['snippet'], task['id']))
                task['reminders_sent'] = count
                task['next_reminder_at'] = now + self._interval   # backoff FIJO
                task['updated_at'] = self._stamp(now)
                self._history(task, 'reminder', now, 'recordatorio %d/%d' % (count, self._max_reminders))
                events.append(self._event('reminder', now, task_id=task['id'],
                                          owner_member_id=task['owner_member_id'],
                                          count=count, max=self._max_reminders))
            else:
                task['state'] = ESCALATED
                task['escalated_at'] = self._stamp(now)
                task['updated_at'] = self._stamp(now)
                task['next_reminder_at'] = None                  # terminal: sin reintento
                self._channel.publish(
                    self._agent_id, to=self._supervisor_id, topic=FOLLOWUP_TOPIC,
                    text='follow-up escalado a supervision: %s no reporto tras %d recordatorios '
                         '(tarea %s: "%s").' % (task['owner_member_id'], self._max_reminders,
                                                task['id'], task['snippet']))
                self._history(task, 'escalated', now,
                              'sin reporte tras %d recordatorios' % self._max_reminders)
                events.append(self._event('escalated', now, task_id=task['id'],
                                          owner_member_id=task['owner_member_id'],
                                          reminders_sent=task['reminders_sent']))
        return events

    # ------------------------------------------------------------- tick

    def tick(self):
        """Un tick EXPLICITO (doctrina gang_supervisor.py:19-21): escanear y luego
        perseguir, contra UN solo now. Devuelve la tupla de eventos del tick."""
        now = self._clock()
        events = self._scan(now) + self._fire(now)
        self._events.extend(events)
        return tuple(copy.deepcopy(events))

    # ------------------------------------------------------------- vistas

    def tasks(self):
        """Activas ('chasing' + 'escalated') en orden de creacion. Copias."""
        return tuple(copy.deepcopy(self._tasks))

    def archive(self):
        """Reportadas y archivadas, en orden de cierre. Copias."""
        return tuple(copy.deepcopy(self._archive))

    def find(self, task_id):
        for task in list(self._tasks) + list(self._archive):
            if task['id'] == task_id:
                return copy.deepcopy(task)
        raise FollowupsError('unknown_task: no existe la tarea de follow-up %r.' % (task_id,))

    def stats(self):
        counts = {state: 0 for state in FOLLOWUP_STATES}
        for task in self._tasks:
            counts[task['state']] += 1
        for task in self._archive:
            counts[task['state']] += 1
        counts['active'] = len(self._tasks)
        counts['archived'] = len(self._archive)
        counts['total'] = len(self._tasks) + len(self._archive)
        return counts

    def events_log(self):
        """Log append-only completo. Copias."""
        return tuple(copy.deepcopy(self._events))

    def ledger_view(self):
        """Snapshot serializable (disciplina de copia del canal). No cargable."""
        return {
            'schema_version': SCHEMA_VERSION,
            'provenance': PROVENANCE,
            'agent_member_id': self._agent_id,
            'supervisor_member_id': self._supervisor_id,
            'reminder_interval_secs': self._interval,
            'max_reminders': self._max_reminders,
            'processed_message_ids': list(self._processed_order),
            'tasks': copy.deepcopy(self._tasks),
            'archive': copy.deepcopy(self._archive),
            'events': copy.deepcopy(self._events),
            'stats': self.stats(),
        }
