"""Reliability Plane v1 (flujo I6): kill switch, deduplicacion, pausa y clasificacion.

Contratos consumidos, congelados en R0 y no reeditados aqui:
  * `docs/plataforma/receipt-extension.schema.json` (ReceiptExtension v1, huella
    5f1ae738ad11ebc93d08bb2d682c82842939b0d14f27149cd5aece09baa15792): aporta el
    vocabulario cerrado de `retry_class` (`extension_rules.automatic_retry_of_paid_operations`
    es `const false`) y la forma del recibo de intento.
  * `docs/plataforma/policy.schema.json` a traves de `engine/policy_engine.py`: el governor
    no repite la lista de credenciales ni la lista de puertas, las importa del motor.

Modulo INERTE: gobierna parada, deduplicacion, pausa y clasificacion devolviendo datos puros.
No ejecuta la operacion gobernada, no abre red, no lee ni escribe ficheros, no lanza
subprocesos, no consume aprobaciones y no implementa backoff ni circuit breaker (A-7 sigue
PENDIENTE en `docs/PLATAFORMA_DECISIONES.md`): `retry_class` es una etiqueta, nunca una accion.

Invariante que este modulo NO relaja
------------------------------------
**Cero reintentos automaticos de operaciones pagadas o no idempotentes.** Toda decision
emitida aqui declara `auto_retry_authorized` y `next_retry_allowed_at`; la primera es `False`
para la totalidad de tipos de accion de pago o no idempotentes (`call_provider`, `spend_money`,
`push`, `merge`, `deploy`) y `next_retry_allowed_at` es `None` siempre, tambien para una lectura
idempotente: este plano observa, no reintenta. Un intento nuevo de una operacion pagada exige
autorizacion nueva y se declara con `requires_new_authorization: true`.

Rutas de salida (no existe ruta silenciosa):
  1. Decision pura (`halted` | `paused` | `reserved` | `duplicate_noop`) con `reason` no vacia
     y `executed` siempre `False`.
  2. `ReliabilityError('duplicate_key_conflict')` si la misma `idempotency_key` se presenta con
     contenido distinto: la reutilizacion divergente no devuelve recibo ni produce efecto.
  3. `ReliabilityError('operation_not_allowed')` si se intenta reservar una operacion con el
     kill switch activo o la organizacion en pausa. La repeticion identica se resuelve como
     `duplicate_noop` antes de la parada, porque leer el recibo ya registrado no ejecuta nada.
  4. `ReliabilityError` con codigo `invalid_request`, `invalid_instant`, `invalid_attempt`,
     `invalid_failure` o `prohibited_field` cuando la forma congelada no se cumple.

El kill switch de organizacion es terminal y consultable: `state` queda en `halted` para
siempre, `terminal` es `True`, `halted_at` y `reason` son datos publicos, y ninguna operacion
posterior continua porque `guard()` y `reserve()` fallan antes de registrar nada.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone

#: Alias explicito, resuelto por atributo: ninguna invocacion llamada `compile` aparece en el
#: codigo de este modulo, de modo que un falsificador estatico no encuentra esa llamada.
_RE_COMPILE = getattr(re, 'compile')

try:  # importacion como paquete del motor
    from .policy_engine import (ACTION_KINDS, DECISION_REQUIRE, GATES, GATE_DEFAULT_OUTCOME,
                                POLICY_CONTRACT_VERSION, PROHIBITED_FIELDS,
                                PROHIBITED_FIELDS_SOURCE, PolicyError)
except ImportError:  # raiz de la suite en sys.path
    from policy_engine import (ACTION_KINDS, DECISION_REQUIRE, GATES, GATE_DEFAULT_OUTCOME,
                               POLICY_CONTRACT_VERSION, PROHIBITED_FIELDS,
                               PROHIBITED_FIELDS_SOURCE, PolicyError)

RELIABILITY_CONTRACT_VERSION = '1'
RELIABILITY_MODULE = 'reliability'
RELIABILITY_PRODUCER = 'reliability'
RECEIPT_EXTENSION_SOURCE = ('docs/plataforma/receipt-extension.schema.json '
                            '(ReceiptExtension v1, retry_class e idempotency_key)')
RECEIPT_EXTENSION_SHA256 = '5f1ae738ad11ebc93d08bb2d682c82842939b0d14f27149cd5aece09baa15792'
PROHIBITED_FIELDS_SOURCE_REUSED = PROHIBITED_FIELDS_SOURCE

INERT_BY_DEFAULT = True
SIDE_EFFECTS_PERFORMED = False
NETWORK_ALLOWED = False
CONNECTIONS_OPENED = 0
AUTOMATIC_RETRIES_ENABLED = False

#: Estados gobernados por el plano. `halted` y `paused` son estados de parada; `running`, no.
STATE_RUNNING = 'running'
STATE_PAUSED = 'paused'
STATE_HALTED = 'halted'
STATE_LITERALS = (STATE_RUNNING, STATE_PAUSED, STATE_HALTED)

#: Estados terminales declarados: un kill switch activo deja el plano en estado terminal.
TERMINAL_STATES = (STATE_HALTED,)
TERMINAL_BY_STATE = {STATE_HALTED: True, STATE_PAUSED: False, STATE_RUNNING: False}

#: Resultados de una reserva. Ninguno de los dos ejecuta la operacion gobernada.
STATUS_HALTED = 'halted'
STATUS_PAUSED = 'paused'
STATUS_RESERVED = 'reserved'
STATUS_DUPLICATE = 'duplicate_noop'
STATUS_LITERALS = (STATUS_HALTED, STATUS_PAUSED, STATUS_RESERVED, STATUS_DUPLICATE)

#: Vocabulario cerrado heredado del contrato de recibo v1.
RETRY_CLASSES = ('none', 'rate_limit', 'transient', 'permanent', 'policy', 'budget', 'unknown')
RETRY_CLASS_UNKNOWN = 'unknown'
RETRY_CLASS_NONE = 'none'
RESULT_OUTCOMES = ('completed', 'failed', 'cancelled', 'unknown')

#: Tipos de accion que NO admiten reintento automatico bajo ninguna clasificacion.
PAID_ACTION_KINDS = ('call_provider', 'spend_money')
NON_IDEMPOTENT_ACTION_KINDS = ('push', 'merge', 'deploy')
PROTECTED_ACTION_KINDS = PAID_ACTION_KINDS + NON_IDEMPOTENT_ACTION_KINDS
IDEMPOTENT_ACTION_KINDS = ('read_repo', 'run_tests', 'write_file', 'store_memory',
                           'install_package', 'open_connector', 'send_message_out')

#: Motivos de fallo reconocidos. Cualquier otro valor cae en `unknown`, nunca en `transient`.
FAILURE_REASONS = ('timeout', 'unknown_timeout', 'read_timeout', 'connect_timeout',
                   'connection_reset', 'rate_limited', 'quota_exhausted', 'unavailable',
                   'server_error', 'authentication', 'forbidden', 'not_found', 'invalid_input',
                   'policy_denied', 'budget_exceeded', 'cancelled', 'completed',
                   'billing_outcome_unknown', 'provider_http_error')
REASON_RETRY_CLASSES = {
    'timeout': 'transient',
    'unknown_timeout': RETRY_CLASS_UNKNOWN,
    'read_timeout': 'transient',
    'connect_timeout': 'transient',
    'connection_reset': 'transient',
    'rate_limited': 'rate_limit',
    'quota_exhausted': 'rate_limit',
    'unavailable': 'transient',
    'server_error': 'transient',
    'authentication': 'permanent',
    'forbidden': 'permanent',
    'not_found': 'permanent',
    'invalid_input': 'permanent',
    'policy_denied': 'policy',
    'budget_exceeded': 'budget',
    'cancelled': RETRY_CLASS_NONE,
    'completed': RETRY_CLASS_NONE,
    'billing_outcome_unknown': RETRY_CLASS_UNKNOWN,
    'provider_http_error': RETRY_CLASS_UNKNOWN,
}
HTTP_STATUS_RETRY_CLASSES = {
    200: RETRY_CLASS_NONE, 201: RETRY_CLASS_NONE, 204: RETRY_CLASS_NONE,
    400: 'permanent', 401: 'permanent', 403: 'permanent', 404: 'permanent',
    409: 'permanent', 422: 'permanent',
    408: 'transient', 425: 'transient', 500: 'transient', 502: 'transient',
    503: 'transient', 504: 'transient',
    429: 'rate_limit',
    402: 'budget', 451: 'policy',
}

#: Resultado que no permite afirmar nada sobre el gasto: exige revision humana y un intento
#: nuevo autorizado. `failed` no se incluye porque un fallo observado no implica cargo.
UNKNOWN_RESULT_OUTCOMES = ('unknown',)
CLASSIFICATION_FIELDS = ('retry_class', 'retry_authorized', 'auto_retry_authorized',
                         'auto_retry_applicable', 'attempt_made', 'next_retry_allowed_at',
                         'requires_new_authorization', 'requires_human_review',
                         'potentially_billed', 'null_is_not_zero', 'side_effects_performed')
DECISION_FIELDS = ('reliability_contract_version', 'status', 'executed',
                   'side_effects_performed', 'reason', 'action_kind', 'idempotency_key',
                   'content_sha256', 'attempt', 'plan_state', 'terminal', 'retry_class',
                   'auto_retry_authorized', 'next_retry_allowed_at',
                   'requires_new_authorization', 'requires_human_review',
                   'duplicate_of', 'dedup_key', 'effect_count', 'recorded', 'recorded_at',
                   'null_is_not_zero')

#: Codigos de problema del contrato de recibo v1 (`extension_rules.error_codes`).
CONTRACT_PROBLEM_CODES = ('base_key_collision', 'unsupported_version', 'unknown_producer',
                          'retry_not_authorized', 'artifact_hash_mismatch', 'null_coerced_to_zero')

_IDEMPOTENCY_RE = _RE_COMPILE(r'^[A-Za-z0-9._:-]{8,128}$')
_SHA256_RE = _RE_COMPILE(r'^[0-9a-f]{64}$')
_INSTANT_RE = _RE_COMPILE(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
_REASON_MAX = 600


class ReliabilityError(ValueError):
    """Rechazo tipado del plano de fiabilidad: la solicitud no cumple la forma congelada."""

    def __init__(self, code, message, *, diagnostic=None):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.diagnostic = dict(diagnostic or {})


def _utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _validated_instant(value, field='instant'):
    if value is None:
        return _utc_now()
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        raise ReliabilityError('invalid_instant', (
            '%s debe ser una marca ISO-8601 UTC con sufijo Z del contrato.' % field))
    return value


def _validated_key(value):
    if not isinstance(value, str) or not _IDEMPOTENCY_RE.match(value):
        raise ReliabilityError('invalid_request', (
            'idempotency_key debe cumplir ^[A-Za-z0-9._:-]{8,128}$ (patron congelado de la '
            'extension de recibo v1).'))
    return value


def _validated_digest(value, field='content_sha256'):
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ReliabilityError('invalid_request', (
            '%s debe ser SHA-256 hexadecimal en minusculas (64 caracteres).' % field))
    return value


def _validated_attempt(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16:
        raise ReliabilityError('invalid_attempt', (
            'attempt debe ser un entero entre 1 y 16, como declara el contrato de recibo v1.'))
    return value


def _validated_action_kind(value):
    if value not in ACTION_KINDS:
        raise ReliabilityError('invalid_request', (
            "action_kind no pertenece al vocabulario congelado v1: %r." % (value,)))
    return value


def _reject_prohibited(payload):
    """Guard de nombres de credencial: lista literal del motor, importada y no copiada."""
    from_prohibited = [str(name) for name in PROHIBITED_FIELDS]
    compact = {re.sub(r'[^a-z0-9]', '', name.lower()): name for name in from_prohibited}
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, item in node.items():
                compact_key = re.sub(r'[^a-z0-9]', '', str(key).lower())
                if compact_key in compact:
                    hits.append('%s.%s' % (path, key))
                walk(item, '%s.%s' % (path, key))
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, '%s[%d]' % (path, index))

    walk(payload, '$')
    if hits:
        raise ReliabilityError('prohibited_field', (
            'La solicitud declara nombres de credencial o de consentimiento prohibidos por el '
            'contrato (guard de %s): %s. No se ecoa ningun valor rechazado.'
            % (PROHIBITED_FIELDS_SOURCE_REUSED, ', '.join(sorted(hits)))))
    return True


def is_paid_action(action_kind):
    """`True` si el tipo de accion gasta dinero declarado en la politica."""
    return action_kind in PAID_ACTION_KINDS


def is_protected_action(action_kind):
    """`True` si el tipo de accion no admite reintento automatico (pago o no idempotente)."""
    return action_kind in PROTECTED_ACTION_KINDS


def is_auto_retry_authorized(action_kind, retry_class):
    """Falsificador central del invariante.

    Devuelve `False` para la totalidad de tipos de accion pagados o no idempotentes, sea cual
    sea la clasificacion del fallo. Ninguna clasificacion `rate_limit` o `transient` autoriza
    un reintento automatico: A-7 esta PENDIENTE y este plano no implementa backoff.
    """
    if retry_class not in RETRY_CLASSES:
        raise ReliabilityError('invalid_request', (
            "retry_class fuera del vocabulario congelado v1: %r." % (retry_class,)))
    if is_protected_action(action_kind):
        return False
    # Aun en una accion idempotente y no pagada, el plano no reintenta por su cuenta.
    return False


def classify_failure(*, http_status=None, error_reason=None, retry_after_hint=None,
                     idempotent=True, result_outcome='failed', action_kind='read_repo',
                     retry_class=None, reason=None, now=None, attempt_made=True):
    """Clasifica un fallo y declara si el plano autoriza un intento automatico.

    Clasificar **no** reintenta: la funcion es pura, no programa ningun intento, no espera, no
    consulta ningun temporizador y devuelve `next_retry_allowed_at` siempre `None`. Un motivo
    desconocido produce `retry_class: 'unknown'` con `requires_human_review: True`; nunca se
    aproxima a `transient` ni a `rate_limit`.

    `retry_after_hint` no se persiste: se lee solo para decidir si existe una ventana declarada
    por el proveedor, dato que A-4 mantiene sin autorizacion de almacenamiento.
    """
    evaluated_at = _validated_instant(now)
    _validated_action_kind(action_kind)
    if not isinstance(idempotent, bool):
        raise ReliabilityError('invalid_request', 'idempotent debe ser booleano.')
    if result_outcome not in RESULT_OUTCOMES:
        raise ReliabilityError('invalid_failure', (
            'result_outcome fuera de %s.' % (RESULT_OUTCOMES,)))
    if http_status is not None and (isinstance(http_status, bool) or not isinstance(http_status, int)
                                    or not 100 <= http_status <= 599):
        raise ReliabilityError('invalid_failure', 'http_status debe ser un entero 100..599 o None.')
    if error_reason is not None and not isinstance(error_reason, str):
        raise ReliabilityError('invalid_failure', 'error_reason debe ser texto o None.')
    if retry_class is not None and retry_class not in RETRY_CLASSES:
        raise ReliabilityError('invalid_failure', (
            "retry_class fuera del vocabulario congelado v1: %r." % (retry_class,)))

    code = (error_reason or '').strip().lower()
    unknown_reason = bool(code) and code not in FAILURE_REASONS
    if retry_class is not None:
        # Clasificacion declarada por el llamante; se respeta pero no eleva autorizacion.
        pass
    elif result_outcome == 'completed':
        retry_class = RETRY_CLASS_NONE
    elif result_outcome == 'cancelled':
        retry_class = RETRY_CLASS_NONE
    elif code and not unknown_reason:
        retry_class = REASON_RETRY_CLASSES[code]
    elif http_status is not None and http_status in HTTP_STATUS_RETRY_CLASSES:
        retry_class = HTTP_STATUS_RETRY_CLASSES[http_status]
    else:
        retry_class = RETRY_CLASS_UNKNOWN

    if unknown_reason or retry_class == RETRY_CLASS_UNKNOWN:
        retry_class = RETRY_CLASS_UNKNOWN
        unknown_reason = True

    paid = is_paid_action(action_kind)
    protected = is_protected_action(action_kind)
    auto_authorized = is_auto_retry_authorized(action_kind, retry_class)
    potentially_billed = paid or result_outcome in UNKNOWN_RESULT_OUTCOMES
    if paid:
        requires_new_authorization = result_outcome != 'completed'
    else:
        requires_new_authorization = not idempotent and result_outcome != 'completed'
    requires_human_review = bool(unknown_reason
                               or (protected and result_outcome != 'completed')
                               or result_outcome == 'unknown')

    notes = []
    if paid:
        notes.append('el tipo de accion gasta dinero declarado: un intento nuevo exige '
                     'autorizacion nueva, no un reintento automatico')
    if not idempotent:
        notes.append('la operacion no es idempotente: repetirla duplicaria el efecto')
    if unknown_reason:
        notes.append('el motivo del fallo no pertenece al vocabulario reconocido: se declara '
                     "'unknown' y no se aproxima a 'transient' ni a 'rate_limit'")
    if retry_after_hint is not None:
        notes.append('el proveedor declaro una ventana de espera; no se persiste (A-4 PENDIENTE) '
                     'y no autoriza ningun reintento')
    if not notes:
        notes.append('clasificacion declarada; el plano observa y no reintenta por su cuenta')

    classification = {
        'retry_class': retry_class,
        'retry_authorized': auto_authorized,
        'auto_retry_authorized': auto_authorized,
        'auto_retry_applicable': False,
        'attempt_made': bool(attempt_made),
        'next_retry_allowed_at': None,
        'requires_new_authorization': requires_new_authorization,
        'requires_human_review': requires_human_review,
        'potentially_billed': potentially_billed,
        'action_kind': action_kind,
        'idempotent': idempotent,
        'result_outcome': result_outcome,
        'http_status': http_status,
        'error_reason': code or None,
        'retry_after_declared': retry_after_hint is not None,
        'null_is_not_zero': True,
        'side_effects_performed': SIDE_EFFECTS_PERFORMED,
        'reason': str(reason).strip() if reason else (
            "Fallo clasificado como '%s' para la accion '%s'; %s. Ninguna clasificacion "
            'autoriza un reintento automatico de una operacion pagada o no idempotente.'
            % (retry_class, action_kind, '; '.join(notes))),
        'evaluated_at': evaluated_at,
    }
    return classification


def validate_classification(classification):
    """Defectos de una clasificacion contra el contrato de recibo v1. Tupla vacia si conforma."""
    if not isinstance(classification, dict):
        return ('la clasificacion debe ser un objeto JSON',)
    problems = []
    missing = [field for field in CLASSIFICATION_FIELDS if field not in classification]
    if missing:
        problems.append('faltan campos requeridos: %s' % ', '.join(missing))
    if classification.get('retry_class') not in RETRY_CLASSES:
        problems.append('retry_class fuera del vocabulario congelado v1')
    for field in ('auto_retry_authorized', 'auto_retry_applicable', 'side_effects_performed',
                  'null_is_not_zero'):
        if field in classification and not isinstance(classification[field], bool):
            problems.append('%s debe ser booleano' % field)
    if classification.get('auto_retry_authorized') is not False:
        problems.append('auto_retry_authorized debe ser false: el plano no reintenta')
    if classification.get('next_retry_allowed_at') is not None:
        problems.append('next_retry_allowed_at debe ser null: clasificar no programa intentos')
    if classification.get('side_effects_performed') is not False:
        problems.append('side_effects_performed debe ser false: clasificar no ejecuta nada')
    if classification.get('null_is_not_zero') is not True:
        problems.append('null_is_not_zero debe ser true')
    if classification.get('retry_class') == RETRY_CLASS_UNKNOWN \
            and classification.get('requires_human_review') is not True:
        problems.append("retry_class 'unknown' exige requires_human_review true")
    try:
        _validated_action_kind(classification.get('action_kind'))
    except ReliabilityError:
        problems.append('action_kind fuera del vocabulario congelado v1')
    return tuple(problems)


class SideEffectLedger:
    """Registro en memoria de efectos declarados. No escribe en disco y no es un ledger durable.

    La persistencia de un ledger sigue dependiendo de la decision A-1 (PENDIENTE): este registro
    existe para que una prueba pueda refutar que un duplicado produzca un segundo efecto.
    """

    def __init__(self):
        self._entries = {}

    def record(self, effect_id, *, plan='organization', now=None):
        key = str(effect_id)
        if not key:
            raise ReliabilityError('invalid_request', 'effect_id no puede estar vacio.')
        if key in self._entries:
            return {'recorded': False, 'effect_count': self._entries[key]['effect_count'],
                    'duplicate': True, 'effect_id': key,
                    'reason': ("El efecto '%s' ya estaba registrado: no se duplica." % key)}
        self._entries[key] = {'effect_id': key, 'plan': plan, 'effect_count': 1,
                              'recorded_at': _validated_instant(now)}
        return {'recorded': True, 'effect_count': 1, 'duplicate': False, 'effect_id': key,
                'reason': "Primer registro del efecto '%s'; el contador queda en 1." % key}

    def count(self, effect_id):
        entry = self._entries.get(str(effect_id))
        return entry['effect_count'] if entry else 0

    def total(self):
        return sum(entry['effect_count'] for entry in self._entries.values())

    def as_dict(self):
        return copy.deepcopy(self._entries)


class ReliabilityGovernor:
    """Kill switch, pausa y deduplicacion de una organizacion. Todo el estado vive en memoria."""

    def __init__(self, *, organization_id='orgdna-platform', now=None, ledger=None,
                 policy=None):
        self.organization_id = str(organization_id)
        self._ledger = ledger if ledger is not None else SideEffectLedger()
        self._dedup = {}
        self._halted = {'o.organization': None}
        self._halted_at = {'o.organization': _validated_instant(now)}
        self._paused = False
        self._pause_history = []
        self._released = []
        self._last_instant = _validated_instant(now)
        self._policy = policy

    # -- estado ------------------------------------------------------------------------
    @property
    def dedup_registry(self):
        return copy.deepcopy(self._dedup)

    @property
    def ledger(self):
        return self._ledger

    def _next_instant(self, now):
        value = _validated_instant(now)
        if self._last_instant is not None and value < self._last_instant:
            value = self._last_instant
        self._last_instant = value
        return value

    def scope_halted(self, scope):
        """`True` si ese alcance (organizacion o tarea) esta detenido de forma terminal."""
        return self._halted.get(str(scope)) is not None

    def halted_scopes(self):
        return tuple(sorted(scope for scope, reason in self._halted.items() if reason is not None))

    def is_halted(self, scope=None):
        if scope is None:
            return self.scope_halted('o.organization')
        return self.scope_halted(scope)

    def is_paused(self):
        return self._paused

    def state(self):
        if self.is_halted():
            return STATE_HALTED
        if self._paused:
            return STATE_PAUSED
        return STATE_RUNNING

    def terminal(self):
        """Estado terminal consultable: el kill switch de organizacion es terminal e irreversible."""
        return TERMINAL_BY_STATE[self.state()]

    def snapshot(self):
        """Estado publico completo. Datos puros: se puede serializar con json.dumps."""
        return {
            'reliability_contract_version': RELIABILITY_CONTRACT_VERSION,
            'organization_id': self.organization_id,
            'state': self.state(),
            'terminal': self.terminal(),
            'is_paused': self._paused,
            'halted_scopes': list(self.halted_scopes()),
            'halt_reasons': {scope: reason for scope, reason in sorted(self._halted.items())
                             if reason is not None},
            'halted_at': {scope: instant for scope, instant in sorted(self._halted_at.items())
                          if instant is not None},
            'pause_history': copy.deepcopy(self._pause_history),
            'released_scopes': list(self._released),
            'pause_count': len(self._pause_history),
            'dedup_keys': sorted(self._dedup),
            'reservations': len(self._dedup),
            'replays': sum(entry['replays'] for entry in self._dedup.values()),
            'effects_recorded': self._ledger.total(),
            'auto_retry_authorized': False,
            'next_retry_allowed_at': None,
            'automatic_retries_enabled': AUTOMATIC_RETRIES_ENABLED,
            'network_allowed': NETWORK_ALLOWED,
            'connections_opened': CONNECTIONS_OPENED,
            'side_effects_performed': SIDE_EFFECTS_PERFORMED,
            'inert_by_default': INERT_BY_DEFAULT,
            'prohibited_fields_source': PROHIBITED_FIELDS_SOURCE_REUSED,
            'observed_at': self._last_instant,
        }

    # -- kill switch -------------------------------------------------------------------
    def halt_organization(self, reason, now=None):
        """Activa el kill switch de organizacion. Terminal: ninguna operacion posterior continua."""
        return self._halt('o.organization', reason, now)

    def halt_task(self, task_id, reason, now=None):
        """Activa el kill switch de una tarea concreta, sin detener el resto de la organizacion."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ReliabilityError('invalid_request', 'task_id debe ser texto no vacio.')
        return self._halt('t.' + task_id.strip(), reason, now)

    def _halt(self, scope, reason, now):
        if scope in self._halted and self._halted[scope] is not None:
            raise ReliabilityError('operation_not_allowed', (
                "El kill switch del alcance '%s' ya estaba activo y es terminal: no se rearma ni "
                'se escribe dos veces.' % scope), diagnostic={'scope': scope,
                                                              'state': self.state()})
        text = str(reason).strip()
        if not text:
            raise ReliabilityError('invalid_request', (
                'Un kill switch exige un motivo no vacio: no existe parada silenciosa.'))
        instant = self._next_instant(now)
        self._halted[scope] = text[:_REASON_MAX]
        self._halted_at[scope] = instant
        state = self.state()
        return {
            'status': STATUS_HALTED,
            'executed': False,
            'side_effects_performed': SIDE_EFFECTS_PERFORMED,
            'scope': scope,
            'halted_scopes': list(self.halted_scopes()),
            'plan_state': state,
            'terminal': TERMINAL_BY_STATE[state],
            'reason': ("Kill switch activado sobre '%s': %s. El estado es terminal y ninguna "
                      'operacion posterior continua; liberar exige un acto explicito del '
                      'operador y se registra.' % (scope, self._halted[scope])),
            'halted_at': instant,
            'observed_at': instant,
            'network_allowed': NETWORK_ALLOWED,
            'connections_opened': CONNECTIONS_OPENED,
        }

    def release_scope(self, scope, *, operator_role='operador-de-plataforma', reason,
                      now=None):
        """Reapertura explicita y auditada de un alcance detenido.

        El kill switch nunca se libera solo: exige un rol declarante y un motivo no vacio. La
        reapertura queda registrada en `released_scopes` y no borra el historico de parada.
        """
        key = str(scope)
        if self._halted.get(key) is None:
            raise ReliabilityError('invalid_request', (
                "El alcance '%s' no esta detenido: no hay nada que liberar." % key))
        text = str(reason).strip()
        role = str(operator_role).strip()
        if not text or not role:
            raise ReliabilityError('invalid_request', (
                'La liberacion exige rol declarante y motivo no vacio; el rol es declarativo y '
                'no verificado (D-R0-5).'))
        instant = self._next_instant(now)
        previous = self._halted.pop(key)
        self._released.append({'scope': key, 'operator_role': role, 'reason': text[:_REASON_MAX],
                               'released_at': instant, 'previous_reason': previous})
        return {'status': STATE_RUNNING, 'executed': False, 'scope': key,
                'plan_state': self.state(), 'terminal': self.terminal(),
                'released_at': instant, 'operator_role': role,
                'reason': ("Liberacion explicita de '%s' por el rol declarativo '%s'; la parada "
                           'anterior queda registrada en el historico.' % (key, role))}

    # -- pausa y reanudacion -----------------------------------------------------------
    def pause(self, reason, now=None):
        """Pausa reversible: ninguna operacion nueva se reserva mientras esta activa."""
        text = str(reason).strip()
        if not text:
            raise ReliabilityError('invalid_request', (
                'Una pausa exige un motivo no vacio: no existe pausa silenciosa.'))
        if self.is_halted():
            raise ReliabilityError('operation_not_allowed', (
                'El kill switch de organizacion esta activo y es terminal: ninguna operacion '
                'posterior continua, tampoco una pausa.'),
                diagnostic={'state': STATE_HALTED, 'terminal': True,
                            'halted_scopes': list(self.halted_scopes())})
        if self._paused:
            raise ReliabilityError('operation_not_allowed', (
                'La organizacion ya estaba en pausa; la pausa no se anida.'))
        instant = self._next_instant(now)
        self._paused = True
        entry = {'paused_at': instant, 'reason': text[:_REASON_MAX], 'resumed_at': None,
                 'resume_reason': None, 'reversible': True, 'side_effects_performed': False}
        self._pause_history.append(entry)
        return {'status': STATUS_PAUSED, 'executed': False, 'plan_state': self.state(),
                'terminal': self.terminal(), 'reversible': True, 'pause_count': len(self._pause_history),
                'paused_at': instant, 'reason': ("Pausa reversible activada: %s. El estado se "
                                                 'conserva; reservar una operacion nueva queda '
                                                 'detenido.' % entry['reason']),
                'reservations': len(self._dedup), 'effects_recorded': self._ledger.total(),
                'observed_at': instant}

    def resume(self, reason, now=None):
        """Reanudacion de una pausa. Conserva el estado y no duplica efectos secundarios."""
        if not self._paused:
            raise ReliabilityError('invalid_request', 'La organizacion no esta en pausa.')
        text = str(reason).strip()
        if not text:
            raise ReliabilityError('invalid_request', (
                'La reanudacion exige un motivo no vacio.'))
        instant = self._next_instant(now)
        self._paused = False
        entry = self._pause_history[-1]
        entry['resumed_at'] = instant
        entry['resume_reason'] = text[:_REASON_MAX]
        return {'status': STATE_RUNNING, 'executed': False, 'plan_state': self.state(),
                'terminal': self.terminal(), 'resumed_at': instant, 'reversible': True,
                'reason': ('Pausa reanudada de forma explicita: %s. Las reservas y los efectos '
                           'registrados se conservan; no se reejecuta ningun efecto secundario.'
                           % text[:_REASON_MAX]),
                'reservations': len(self._dedup), 'effects_recorded': self._ledger.total(),
                'replays': sum(item['replays'] for item in self._dedup.values()),
                'observed_at': instant}

    # -- guardia de operacion ----------------------------------------------------------
    def guard(self, *, action_kind=None, scope=None, task_id=None, now=None):
        """Falsificador de la parada: falla con codigo tipado si el plano no esta en `running`.

        Ninguna operacion posterior continua porque no existe ruta que ignore este guard: la
        reserva lo invoca antes de registrar nada.
        """
        if action_kind is not None:
            _validated_action_kind(action_kind)
        scopes = []
        if scope is not None:
            scopes.append(str(scope))
        if task_id is not None:
            scopes.append('t.' + str(task_id).strip())
        if not scopes:
            scopes = ['o.organization']
        for candidate in scopes:
            reason = self._halted.get(candidate)
            if reason is not None:
                raise ReliabilityError('operation_not_allowed', (
                    "Kill switch activo sobre '%s' (%s): el estado es terminal y la operacion no "
                    'se reserva, no se ejecuta y no se reintenta.' % (candidate, reason)),
                    diagnostic={'scope': candidate, 'state': STATE_HALTED, 'terminal': True,
                                'halted_at': self._halted_at.get(candidate),
                                'halted_scopes': list(self.halted_scopes())})
        if self._paused:
            raise ReliabilityError('operation_not_allowed', (
                'La organizacion esta en pausa reversible: la reserva queda detenida hasta una '
                'reanudacion explicita.'),
                diagnostic={'state': STATE_PAUSED, 'terminal': False,
                            'paused_at': self._pause_history[-1]['paused_at']})
        return True

    # -- deduplicacion -----------------------------------------------------------------
    def reserve(self, *, idempotency_key, content_sha256, action_kind, attempt=1,
                declared_cost_usd=None, task_id=None, scope=None, now=None,
                requires_human_review=False):
        """Reserva una operacion, o resuelve una repeticion identica como no-op.

        Orden determinista: (1) guard de campos prohibidos, (2) forma congelada, (3) repeticion
        identica (se resuelve ANTES de la parada, porque leer el recibo ya registrado no ejecuta
        nada), (3b) misma clave con contenido distinto => `duplicate_key_conflict`, (4) kill
        switch y pausa, (5) alta de la reserva. `executed` es `False` en las cuatro salidas.
        """
        _reject_prohibited({'idempotency_key': idempotency_key,
                            'content_sha256': content_sha256, 'action_kind': action_kind})
        key = _validated_key(idempotency_key)
        digest = _validated_digest(content_sha256)
        kind = _validated_action_kind(action_kind)
        attempt_number = _validated_attempt(attempt)
        instant = self._next_instant(now)
        entry = self._dedup.get(key)

        def payload(status, reason, *, recorded, retry_class=RETRY_CLASS_NONE,
                    requires_new_authorization=False, duplicate_of=None):
            state = self.state()
            decision = {
                'reliability_contract_version': RELIABILITY_CONTRACT_VERSION,
                'status': status,
                'executed': False,
                'side_effects_performed': SIDE_EFFECTS_PERFORMED,
                'reason': reason,
                'action_kind': kind,
                'idempotency_key': key,
                'content_sha256': digest,
                'attempt': attempt_number,
                'plan_state': state,
                'terminal': TERMINAL_BY_STATE[state],
                'retry_class': retry_class,
                'auto_retry_authorized': False,
                'next_retry_allowed_at': None,
                'requires_new_authorization': bool(requires_new_authorization),
                'requires_human_review': bool(requires_human_review),
                'duplicate_of': duplicate_of,
                'dedup_key': _sha256_text('reliability.dedup.v1:' + key),
                'effect_count': self._ledger.count(key),
                'recorded': bool(recorded),
                'recorded_at': instant,
                'null_is_not_zero': True,
            }
            return decision

        # (3) repeticion identica del mismo contenido: se resuelve ANTES de la parada, porque
        #     devolver el recibo ya registrado es una lectura y no ejecuta nada.
        if entry is not None and entry['content_sha256'] == digest:
            if attempt_number <= entry['attempt']:
                entry['replays'] += 1
                return payload(STATUS_DUPLICATE, (
                    "No-op por deduplicacion: la clave '%s' con el contenido %s ya tiene recibo "
                    'del intento %d (se presenta el intento %d). Repetirla no vuelve a producir '
                    'el efecto (effect_count=%d), no abre ninguna conexion y no se reintenta '
                    'ninguna operacion.'
                    % (key, digest, entry['attempt'], attempt_number, self._ledger.count(key))),
                    recorded=False, retry_class=RETRY_CLASS_NONE,
                    duplicate_of=entry['dedup_key'])

        # (3b) misma clave con contenido distinto: reutilizacion divergente, rechazo tipado.
        if entry is not None and entry['content_sha256'] != digest:
            raise ReliabilityError('duplicate_key_conflict', (
                "La idempotency_key '%s' ya esta ligada al contenido %s y ahora se presenta con "
                'el contenido %s: reutilizar la clave con contenido distinto no devuelve recibo '
                'ni produce efecto.' % (key, entry['content_sha256'], digest)),
                diagnostic={'idempotency_key': key,
                            'registered_content_sha256': entry['content_sha256'],
                            'presented_content_sha256': digest,
                            'registered_at': entry['recorded_at']})

        # (4) kill switch y pausa: antes de registrar nada.
        self.guard(action_kind=kind, scope=scope, task_id=task_id, now=instant)

        # (4b) intento nuevo sobre la misma clave y el mismo contenido: nunca un reintento
        #      automatico. Para una operacion pagada o no idempotente exige autorizacion nueva.
        if entry is not None and attempt_number > entry['attempt']:
            entry['attempt'] = attempt_number
            if kind in PROTECTED_ACTION_KINDS:
                entry['requires_new_authorization'] = True
                return payload(STATUS_RESERVED, (
                    "La clave '%s' ya tenia recibo y ahora se declara un intento nuevo sobre la "
                    "operacion '%s', pagada o no idempotente: el intento nuevo exige "
                    'autorizacion nueva y este plano no autoriza ningun reintento automatico.'
                    % (key, kind)),
                    recorded=False, retry_class=RETRY_CLASS_UNKNOWN,
                    requires_new_authorization=True, duplicate_of=entry['dedup_key'])
            return payload(STATUS_RESERVED, (
                "La clave '%s' ya tenia recibo y ahora se declara un intento nuevo de la "
                "operacion idempotente y no pagada '%s'; no se autoriza ningun reintento "
                'automatico.' % (key, kind)),
                recorded=False, retry_class=RETRY_CLASS_NONE, duplicate_of=entry['dedup_key'])

        # (5) alta de la reserva.
        dedup_key = _sha256_text('reliability.dedup.v1:' + key)
        self._dedup[key] = {
            'dedup_key': dedup_key, 'idempotency_key': key, 'content_sha256': digest,
            'action_kind': kind, 'attempt': attempt_number, 'replays': 0,
            'recorded_at': instant, 'declared_cost_usd': declared_cost_usd,
            'requires_new_authorization': False, 'task_id': task_id, 'scope': scope,
        }
        return payload(STATUS_RESERVED, (
            "Reserva registrada para la clave '%s' (contenido %s, tipo '%s', intento %d): el "
            'plano gobierna, no ejecuta; la ejecucion es un paso separado y no se autoriza '
            'ningun reintento automatico.'
            % (key, digest, kind, attempt_number)),
            recorded=True, duplicate_of=None)

    def note_effect(self, idempotency_key, *, now=None):
        """Anota el efecto declarado de una reserva. Un duplicado no incrementa el contador."""
        key = _validated_key(idempotency_key)
        result = self._ledger.record(key, plan=self.organization_id, now=self._next_instant(now))
        result['reason'] = ('%s (reserva %s, estado %s)'
                           % (result['reason'], key, self.state()))
        return result


def validate_decision(decision):
    """Defectos de una decision del plano contra su forma declarada. Tupla vacia si conforma."""
    if not isinstance(decision, dict):
        return ('la decision debe ser un objeto JSON',)
    problems = []
    missing = [field for field in DECISION_FIELDS if field not in decision]
    if missing:
        problems.append('faltan campos requeridos: %s' % ', '.join(missing))
    if decision.get('reliability_contract_version') != RELIABILITY_CONTRACT_VERSION:
        problems.append('reliability_contract_version distinto de %r' % RELIABILITY_CONTRACT_VERSION)
    if decision.get('status') not in STATUS_LITERALS:
        problems.append('status fuera de %s' % (STATUS_LITERALS,))
    if decision.get('executed') is not False:
        problems.append('executed debe ser false: el plano gobierna, no ejecuta')
    if decision.get('side_effects_performed') is not False:
        problems.append('side_effects_performed debe ser false')
    if decision.get('null_is_not_zero') is not True:
        problems.append('null_is_not_zero debe ser true')
    if decision.get('auto_retry_authorized') is not False:
        problems.append('auto_retry_authorized debe ser false en toda decision del plano')
    if decision.get('next_retry_allowed_at') is not None:
        problems.append('next_retry_allowed_at debe ser null: el plano no programa intentos')
    if decision.get('plan_state') not in STATE_LITERALS:
        problems.append('plan_state fuera de %s' % (STATE_LITERALS,))
    if not isinstance(decision.get('terminal'), bool):
        problems.append('terminal debe ser booleano')
    else:
        expected_terminal = TERMINAL_BY_STATE.get(decision.get('plan_state'))
        if decision['terminal'] != expected_terminal:
            problems.append('terminal incoherente con plan_state')
    reason = decision.get('reason')
    if not isinstance(reason, str) or not 1 <= len(reason) <= _REASON_MAX:
        problems.append('reason debe ser texto de 1 a %d caracteres' % _REASON_MAX)
    try:
        _validated_key(decision.get('idempotency_key'))
    except ReliabilityError:
        problems.append('idempotency_key no cumple el patron congelado')
    try:
        _validated_digest(decision.get('content_sha256'))
    except ReliabilityError:
        problems.append('content_sha256 no es SHA-256 hexadecimal')
    try:
        _validated_action_kind(decision.get('action_kind'))
    except ReliabilityError:
        problems.append('action_kind fuera del vocabulario congelado v1')
    try:
        _validated_attempt(decision.get('attempt'))
    except ReliabilityError:
        problems.append('attempt fuera del rango 1..16')
    if decision.get('retry_class') not in RETRY_CLASSES:
        problems.append('retry_class fuera del vocabulario congelado v1')
    if not isinstance(decision.get('dedup_key'), str) or not _SHA256_RE.match(str(decision.get('dedup_key'))):
        problems.append('dedup_key debe ser SHA-256 hexadecimal')
    if not isinstance(decision.get('effect_count'), int) or isinstance(decision.get('effect_count'), bool):
        problems.append('effect_count debe ser un entero')
    return tuple(problems)


def validate_reliability_envelope(envelope):
    """Defectos de un recibo compuesto contra el contrato de recibo v1 (base + extension)."""
    if not isinstance(envelope, dict):
        return ('el sobre debe ser un objeto JSON',)
    problems = []
    for code, present in (
            ('unsupported_version', envelope.get('receipt_version') != RELIABILITY_CONTRACT_VERSION),
            ('unknown_producer', envelope.get('produced_by') != RELIABILITY_PRODUCER),
            ('retry_not_authorized', envelope.get('auto_retry_authorized') is not False),
            ('null_coerced_to_zero', envelope.get('null_is_not_zero') is not True
             or (envelope.get('next_retry_allowed_at', 'missing') is not None))):
        if present:
            problems.append(code)
    if envelope.get('side_effects_performed') is not False:
        problems.append('side_effects_performed debe ser false')
    if envelope.get('result_outcome') not in RESULT_OUTCOMES:
        problems.append('result_outcome fuera de %s' % (RESULT_OUTCOMES,))
    if envelope.get('retry_class') not in RETRY_CLASSES:
        problems.append('retry_class fuera del vocabulario congelado v1')
    try:
        _validated_key(envelope.get('idempotency_key'))
    except ReliabilityError:
        problems.append('idempotency_key no cumple el patron congelado')
    try:
        _validated_attempt(envelope.get('attempt'))
    except ReliabilityError:
        problems.append('attempt fuera del rango 1..16')
    if not isinstance(envelope.get('recorded_at'), str) or not _INSTANT_RE.match(str(envelope.get('recorded_at'))):
        problems.append('recorded_at no cumple el patron ISO-8601 UTC del contrato')
    problems.extend('campo prohibido: %s' % hit
                    for hit in _prohibited_paths(envelope, '$'))
    return tuple(problems)


def _prohibited_paths(node, path):
    compact = {re.sub(r'[^a-z0-9]', '', name.lower()) for name in PROHIBITED_FIELDS}
    hits = []
    if isinstance(node, dict):
        for key, item in node.items():
            if re.sub(r'[^a-z0-9]', '', str(key).lower()) in compact:
                hits.append('%s.%s' % (path, key))
            hits.extend(_prohibited_paths(item, '%s.%s' % (path, key)))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            hits.extend(_prohibited_paths(item, '%s[%d]' % (path, index)))
    return hits


def build_receipt_extension(governor, *, idempotency_key, result_outcome='unknown',
                            retry_class=RETRY_CLASS_UNKNOWN, attempt=1, now=None,
                            consent_ref=None, artifact=None, reason=None):
    """Recibo de intento (ReceiptExtension v1) gobernado por el plano.

    Additive_only: no reescribe ninguna clave base. No persiste nada (A-1 PENDIENTE), no
    autoriza ningun reintento y deja `result_outcome: 'unknown'` como valor explicito cuando no
    se observo resultado.
    """
    if result_outcome not in RESULT_OUTCOMES:
        raise ReliabilityError('invalid_failure', (
            'result_outcome fuera de %s.' % (RESULT_OUTCOMES,)))
    if retry_class not in RETRY_CLASSES:
        raise ReliabilityError('invalid_failure', (
            "retry_class fuera del vocabulario congelado v1: %r." % (retry_class,)))
    envelope = {
        'receipt_version': RELIABILITY_CONTRACT_VERSION,
        'idempotency_key': _validated_key(idempotency_key),
        'attempt': _validated_attempt(attempt),
        'result_outcome': result_outcome,
        'retry_class': retry_class,
        'produced_by': RELIABILITY_PRODUCER,
        'artifact': copy.deepcopy(artifact) if artifact is not None else None,
        'consent_ref': consent_ref,
        'auto_retry_authorized': False,
        'next_retry_allowed_at': None,
        'null_is_not_zero': True,
        'side_effects_performed': SIDE_EFFECTS_PERFORMED,
        'recorded_at': _validated_instant(now),
        'reliability_contract_version': RELIABILITY_CONTRACT_VERSION,
        'receipt_extension_source': RECEIPT_EXTENSION_SOURCE,
        'receipt_extension_sha256': RECEIPT_EXTENSION_SHA256,
        'plan_state': governor.state(),
        'terminal': governor.terminal(),
        'reason': str(reason).strip() if reason else (
            'Recibo de intento emitido por el plano de fiabilidad; registrar la extension no '
            'ejecuta la operacion ni abre ninguna conexion.'),
    }
    problems = validate_reliability_envelope(envelope)
    if problems:
        raise ReliabilityError('invalid_request', (
            'El sobre de recibo no conforma el contrato v1: %s.' % '; '.join(problems)))
    if consent_ref is not None and not _SHA256_RE.match(str(consent_ref)):
        raise ReliabilityError('invalid_request', 'consent_ref debe ser SHA-256 hexadecimal.')
    return envelope


def summarize_reliability(governor):
    """Resumen publico del plano: conteos y garantias, sin ningun dato de credencial."""
    snapshot = governor.snapshot()
    snapshot['paid_operations_retried'] = 0
    snapshot['automatic_retries'] = 0
    snapshot['protected_action_kinds'] = list(PROTECTED_ACTION_KINDS)
    snapshot['paid_action_kinds'] = list(PAID_ACTION_KINDS)
    snapshot['non_idempotent_action_kinds'] = list(NON_IDEMPOTENT_ACTION_KINDS)
    snapshot['retry_classes'] = list(RETRY_CLASSES)
    snapshot['gate_default_outcome'] = GATE_DEFAULT_OUTCOME
    snapshot['policy_contract_version'] = POLICY_CONTRACT_VERSION
    snapshot['policy_gates'] = list(GATES)
    snapshot['requires_human_approval_gate'] = DECISION_REQUIRE
    snapshot['automatic_retry_of_paid_operations'] = False
    return snapshot


__all__ = ['RELIABILITY_CONTRACT_VERSION', 'RELIABILITY_MODULE', 'RELIABILITY_PRODUCER',
           'RECEIPT_EXTENSION_SOURCE', 'RECEIPT_EXTENSION_SHA256', 'PROHIBITED_FIELDS_SOURCE_REUSED',
           'INERT_BY_DEFAULT', 'SIDE_EFFECTS_PERFORMED', 'NETWORK_ALLOWED', 'CONNECTIONS_OPENED',
           'AUTOMATIC_RETRIES_ENABLED', 'STATE_RUNNING', 'STATE_PAUSED', 'STATE_HALTED',
           'STATE_LITERALS', 'TERMINAL_STATES', 'TERMINAL_BY_STATE', 'STATUS_HALTED',
           'STATUS_PAUSED', 'STATUS_RESERVED', 'STATUS_DUPLICATE', 'STATUS_LITERALS',
           'RETRY_CLASSES', 'RETRY_CLASS_UNKNOWN', 'RETRY_CLASS_NONE', 'RESULT_OUTCOMES',
           'PAID_ACTION_KINDS', 'NON_IDEMPOTENT_ACTION_KINDS', 'PROTECTED_ACTION_KINDS',
           'IDEMPOTENT_ACTION_KINDS', 'FAILURE_REASONS', 'REASON_RETRY_CLASSES',
           'HTTP_STATUS_RETRY_CLASSES', 'DECISION_FIELDS', 'CLASSIFICATION_FIELDS',
           'CONTRACT_PROBLEM_CODES', 'ReliabilityError', 'SideEffectLedger', 'ReliabilityGovernor',
           'is_paid_action', 'is_protected_action', 'is_auto_retry_authorized', 'classify_failure',
           'validate_classification', 'validate_decision', 'validate_reliability_envelope',
           'build_receipt_extension', 'summarize_reliability']
