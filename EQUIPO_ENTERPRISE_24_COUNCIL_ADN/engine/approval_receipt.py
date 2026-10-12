"""ApprovalReceipt v1 (O1) — recibo declarativo de aprobacion enlazado al hash del TaskGraph.

Reparacion aditiva de auditabilidad `O1-APPROVAL-RECEIPT-LINK-01`. Este modulo NO ejecuta
nada: no abre red, no abre ficheros, no usa claves, no autentica a nadie y no escribe en
ningun almacen. Convierte una aprobacion humana **declarativa** en evidencia reconstruible.

REGLA DE ORO
------------
`TaskGraphHash != ProofOfApproval`, pero
`ApprovalReceipt.graph_sha256 == compute_graph_sha256(TaskGraph)`.
El hash sigue identificando SOLO el contenido determinista; el recibo prueba que un rol
declarativo aprobo ese contenido exacto, en un momento dado, bajo una politica y un alcance
concretos. Este modulo **no toca** `engine/task_graph.py`: recalcula el hash llamando a
`task_graph.compute_graph_sha256()` y describe el esquema del grafo con su `graph_version`.

SEMANTICA DE LAS CINCO PREGUNTAS (el sistema debe diferenciarlas)
----------------------------------------------------------------
1. ¿el grafo es integro?           solo si `compute_graph_sha256` coincide con el recibo;
2. ¿fue aprobado?                  solo si existe un `ApprovalReceipt` con `graph_sha256`
                                   coincidente y `decision == "approved"`;
3. ¿sigue vigente?                 solo si no esta expirado ni revocado;
4. ¿el alcance de la tarea cabe?   solo si `task_id`, autonomia, herramientas/conectores y
                                   presupuesto estan cubiertos por `approval_scope`;
5. ¿quien aprobo?                  en local/offline unicamente un ROL DECLARATIVO:
                                   `approver.authenticated` es siempre `False` y NO se
                                   afirma identidad autenticada.

`answer_security_questions()` responde esas cinco preguntas por separado y `can_execute()`
devuelve `False` ante cualquier duda: la AUSENCIA de recibo NUNCA se interpreta como
aprobacion.

Lo que este modulo NO hace, por diseno y por contrato
-----------------------------------------------------
  * no modifica `compute_graph_sha256()`, el `TaskGraph` serializado, `MANIFIESTO_SHA256.txt`,
    los permisos efectivos, los defaults de autonomia ni la politica de persistencia efimera;
  * no introduce autenticacion ficticia: rechaza cualquier recibo que declare firma,
    autenticacion, identidad verificada o firma criptografica, reutilizando en modo lectura el
    criterio del Policy Engine (`policy_engine.find_authentication_claims`). La unica exencion
    es el campo que el propio contrato exige, `approver.authenticated`, y solo con valor
    `False`: la forma de declarar que NO hay autenticacion;
  * no persiste nada: entrega el payload canonico y su contrato de incrustacion para los cinco
    canales (`CHANNELS`). El cableado fisico no esta autorizado en esta tarea: la persistencia
    local, cuando exista, sera opcional y explicita.

Dominio de entrada: `Mapping` coherente (el que produce `json.loads`) o `TaskSpec`/`TaskGraph`
ya construidos; cualquier otro tipo se rechaza con `InvalidFieldError`. Las lecturas usan el
centinela `_MISSING` (`data.get(name, _MISSING)`), de modo que dentro del dominio nunca se
propaga `KeyError` ni `AttributeError`. Solo biblioteca estandar mas `engine/task_graph.py` y
`engine/policy_engine.py` en modo lectura. Python 3.10+.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re

try:  # Paquete: mismo patron de importacion local que engine/project_store.py:12-15.
    from . import policy_engine, task_graph
except ImportError:  # Modulo suelto en sys.path.
    import policy_engine
    import task_graph

RECEIPT_SCHEMA = 'orgdna-approval-receipt-v1'
RECEIPT_SCHEMA_VERSION = '1'
RECEIPT_KIND = 'task_graph_approval'

#: Esquema del grafo aprobado, derivado del `graph_version` del contrato congelado de I1.
GRAPH_SCHEMA_PREFIX = 'orgdna-task-graph-v'
GRAPH_SCHEMAS = (GRAPH_SCHEMA_PREFIX + task_graph.GRAPH_VERSION,)

DECISION_APPROVED = 'approved'
DECISION_DENIED = 'denied'
DECISION_REVOKED = 'revoked'
DECISION_EXPIRED = 'expired'
DECISIONS = (DECISION_APPROVED, DECISION_DENIED, DECISION_REVOKED, DECISION_EXPIRED)
ACTIVE_DECISIONS = (DECISION_APPROVED,)

#: El aprobador es un ROL declarativo, nunca una identidad autenticada (D-R0-5).
APPROVER_MODE = 'declarative_role'
APPROVER_AUTHENTICATED = False
APPROVER_AUTHENTICATION = policy_engine.APPROVER_AUTHENTICATION
APPROVAL_IDENTITY_CLAIM = policy_engine.APPROVAL_AUTHENTICATION_CLAIM
AUTHENTICATION_EXEMPT_FIELDS = (('approver', 'authenticated'),)

APPROVAL_SCOPE_FIELDS = ('task_ids', 'max_autonomy', 'allowed_write_scopes', 'allowed_connectors',
                         'max_requests', 'max_output_tokens', 'max_estimated_cost_usd')
APPROVER_FIELDS = ('mode', 'role', 'authenticated')
POLICY_REFERENCE_FIELDS = ('policy_version', 'policy_hash', 'approval_required')
REVOCATION_FIELDS = ('revoked_at', 'revoked_by_role', 'reason', 'supersedes')
RECEIPT_REQUIRED_FIELDS = ('receipt_id', 'kind', 'graph_sha256', 'graph_schema', 'approval_scope',
                           'approver', 'policy', 'decision', 'created_at', 'expires_at',
                           'revocation', 'notes')
#: Campos adicionales declarados por O1: el contrato exige "TODOS los campos obligatorios" y no
#: prohibe que el recibo identifique su propio esquema y selle su contenido.
RECEIPT_EXTRA_FIELDS = ('receipt_schema', 'receipt_version', 'receipt_sha256')
RECEIPT_FIELDS = ('receipt_schema', 'receipt_version') + RECEIPT_REQUIRED_FIELDS + ('receipt_sha256',)

CHANNEL_SAVED_PROJECT = 'saved_project'
CHANNEL_EXPORTED_BUNDLE = 'exported_bundle'
CHANNEL_DOWNLOADED_DIAGNOSTIC = 'downloaded_diagnostic'
CHANNEL_GENERATION_RESULT = 'generation_result'
CHANNEL_APPROVAL_ARTIFACT = 'approval_artifact'
CHANNELS = (CHANNEL_SAVED_PROJECT, CHANNEL_EXPORTED_BUNDLE, CHANNEL_DOWNLOADED_DIAGNOSTIC,
            CHANNEL_GENERATION_RESULT, CHANNEL_APPROVAL_ARTIFACT)
#: Contrato de incrustacion: canal -> (clave del payload, modelo minimo previsto). Tupla de
#: tuplas para no exponer ningun contenedor mutable a nivel de modulo.
CHANNEL_CONTRACT = (
    (CHANNEL_SAVED_PROJECT, 'approval_receipts', 'project/approval_receipts.jsonl'),
    (CHANNEL_EXPORTED_BUNDLE, 'approval_receipts', 'bundle/approval_receipts.jsonl'),
    (CHANNEL_DOWNLOADED_DIAGNOSTIC, 'approval_receipts', 'project/generation_diagnostics.json'),
    (CHANNEL_GENERATION_RESULT, 'approval_receipt', 'project/task_graph.json'),
    (CHANNEL_APPROVAL_ARTIFACT, 'approval_receipt', 'project/artifacts/'),
)

BLOCKER_CODES = ('receipt_missing', 'receipt_invalid', 'graph_invalid', 'graph_hash_mismatch',
                 'graph_schema_mismatch', 'receipt_not_approved', 'receipt_expired', 'receipt_revoked',
                 'task_unknown', 'task_out_of_scope', 'autonomy_not_covered',
                 'write_scope_not_covered', 'connector_not_covered', 'requests_exceeded',
                 'tokens_exceeded', 'cost_exceeded', 'policy_hash_not_supplied',
                 'policy_hash_mismatch')
VERIFICATION_PROBLEMS = ('receipt_invalid', 'receipt_hash_mismatch', 'graph_invalid',
                         'graph_hash_mismatch', 'graph_schema_mismatch', 'receipt_not_approved',
                         'receipt_expired', 'receipt_revoked', 'policy_hash_mismatch')

RECEIPT_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$')
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')

#: Centinela de lectura: distingue "clave ausente" de "clave presente con valor null".
_MISSING = object()
_SCOPE_TEXT_MAX = 400
_NOTES_MAX = 1000


class ApprovalReceiptError(ValueError):
    """Base tipada del recibo de aprobacion: cada rechazo usa una subclase con `code`."""

    code = 'invalid_approval_receipt'


class MissingFieldError(ApprovalReceiptError):
    """Falta un campo obligatorio del recibo. La presencia se decide con el valor leido."""

    code = 'missing_required_field'


class InvalidFieldError(ApprovalReceiptError):
    """Forma o tipo invalido para el recibo v1."""

    code = 'invalid_field'


class ProhibitedFieldError(ApprovalReceiptError):
    """Nombre de campo con forma de credencial o consentimiento (guard del Policy Engine)."""

    code = 'prohibited_field'


class AuthenticationClaimError(ApprovalReceiptError):
    """El recibo declara autenticacion, firma o identidad verificada: no se admite."""

    code = 'authentication_claim'


class GraphHashMismatchError(ApprovalReceiptError):
    """El hash declarado no coincide con `compute_graph_sha256` del grafo aprobado."""

    code = 'graph_hash_mismatch'


class GraphSchemaMismatchError(ApprovalReceiptError):
    """El esquema declarado no es el del grafo (contrato v1 congelado)."""

    code = 'graph_schema_mismatch'


class ReceiptIntegrityError(ApprovalReceiptError):
    """El sello del recibo (`receipt_sha256`) no coincide con su contenido."""

    code = 'receipt_hash_mismatch'


class UnknownChannelError(ApprovalReceiptError):
    """Canal de incrustacion fuera de los cinco declarados."""

    code = 'channel_unknown'


ERROR_CLASSES = (MissingFieldError, InvalidFieldError, ProhibitedFieldError,
                 AuthenticationClaimError, GraphHashMismatchError, GraphSchemaMismatchError,
                 ReceiptIntegrityError, UnknownChannelError)
ERROR_CODES = tuple(error.code for error in ERROR_CLASSES)


def _describe(value):
    """Descripcion corta y segura de un valor para el mensaje. Nunca copia el valor crudo."""
    if isinstance(value, str):
        return json.dumps(value[:24], ensure_ascii=True)
    return type(value).__name__


def _is_sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _require_mapping(value, field_name):
    if not isinstance(value, Mapping):
        raise InvalidFieldError(f'{field_name}: se requiere un objeto JSON; recibido {_describe(value)}.')
    return value


def _require_sequence(value, field_name):
    if not _is_sequence(value):
        raise InvalidFieldError(f'{field_name}: se requiere una lista; recibido {_describe(value)}.')
    return value


def _check_text(value, field_name, minimum=1, maximum=None):
    if not isinstance(value, str):
        raise InvalidFieldError(f'{field_name}: se requiere texto; recibido {_describe(value)}.')
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise InvalidFieldError(f'{field_name}: longitud fuera de {minimum}..{maximum} caracteres.')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise InvalidFieldError(f'{field_name}: el texto no es codificable en UTF-8; la forma canonica '
                                'no seria determinista.') from None
    return value


def _check_counter(value, field_name):
    if type(value) is not int:
        raise InvalidFieldError(f'{field_name}: se requiere un entero; recibido {_describe(value)}.')
    if value < 0:
        raise InvalidFieldError(f'{field_name}: no admite valores negativos.')
    return value


def _check_cost(value, field_name):
    if isinstance(value, bool) or type(value) not in (int, float):
        raise InvalidFieldError(f'{field_name}: se requiere un numero; recibido {_describe(value)}.')
    if not math.isfinite(value):
        raise InvalidFieldError(f'{field_name}: se requiere un numero finito; un coste desconocido no se '
                                'aproxima a cero.')
    if value < 0:
        raise InvalidFieldError(f'{field_name}: no admite valores negativos.')
    return float(value)


def _check_instant(value, field_name):
    if not isinstance(value, str) or not task_graph.TIMESTAMP_PATTERN.fullmatch(value):
        raise InvalidFieldError(f'{field_name}: se requiere una marca UTC tipo 2026-10-10T00:00:00Z; '
                                f'recibido {_describe(value)}.')
    return value


def _check_hash(value, field_name):
    if not isinstance(value, str) or not HASH_PATTERN.fullmatch(value):
        raise InvalidFieldError(f'{field_name}: se requiere SHA-256 hexadecimal en minuscula (64 caracteres).')
    return value


def _check_text_list(value, field_name):
    items = _require_sequence(value, field_name)
    result = []
    for item in items:
        text = _check_text(item, field_name, 1, _SCOPE_TEXT_MAX)
        if text in result:
            raise InvalidFieldError(f'{field_name}: "{text}" esta declarado mas de una vez.')
        result.append(text)
    return tuple(result)


def _read_values(data, names, field_name, required=True):
    """Lee `names` con centinela y decide con el valor leido: nunca `in` seguido de `data[name]`."""
    values = {}
    for name in names:
        value = data.get(name, _MISSING)
        if value is _MISSING and required:
            raise MissingFieldError(f'{field_name}: falta el campo obligatorio "{name}".')
        values[name] = value
    return values


def _unknown_names(data, declared, field_name):
    unknown = sorted(str(name) for name in data if name not in declared)
    if unknown:
        raise InvalidFieldError(f'{field_name}: campo no declarado en el recibo v1: ' + ', '.join(unknown) + '.')
    return data


def _guard_view(payload):
    """Copia del payload con la unica exencion declarada: `approver.authenticated == False`.

    El contrato v1 exige ese campo y `False` es la forma de declarar que NO hay autenticacion.
    Cualquier otro nombre que reclame autenticacion, firma o verificacion —incluido
    `approver.authenticated` con un valor distinto de `False`— no se exime y se rechaza.
    """
    view = dict(payload)
    approver = view.get('approver', _MISSING)
    if isinstance(approver, Mapping) and approver.get('authenticated', _MISSING) is False:
        view['approver'] = {key: value for key, value in approver.items() if key != 'authenticated'}
    return view


def _reject_prohibited_and_claims(payload, field_name):
    """Blindaje en lectura: reutiliza los guards del Policy Engine sin modificar policy_engine.py."""
    prohibited = policy_engine.find_prohibited_fields(payload)
    if prohibited:
        raise ProhibitedFieldError('prohibited_field: el recibo declara nombres con forma de credencial o '
                                   f'consentimiento ({", ".join(sorted(prohibited))}); no se admiten. Guard '
                                   'reutilizado de engine/project_store.py:19.')
    claims = policy_engine.find_authentication_claims(_guard_view(payload))
    if claims:
        raise AuthenticationClaimError('authentication_claim: el recibo declara autenticacion, firma o identidad '
                                       f'verificada ({", ".join(sorted(claims))}); en local/offline solo se admite '
                                       'un rol declarativo y no se afirma identidad autenticada (D-R0-5).')


def _canonical_bytes(value):
    """JSON canonico determinista. Falla en vez de aproximar."""
    try:
        text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        return text.encode('utf-8')
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise InvalidFieldError('invalid_field: el recibo no se puede canonicalizar como JSON UTF-8 (' +
                                type(error).__name__ + ').') from None


def _sha256_json(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _instant_epoch(value):
    try:
        text = value[:-1] if isinstance(value, str) and value.endswith('Z') else value
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%f').replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def _resolve_now(now):
    if now is None:
        return _utc_now()
    return _check_instant(now, 'now')


def _autonomy_rank(level):
    return policy_engine.AUTONOMY_LEVELS.index(level)


@dataclass(frozen=True)
class ApprovalScope:
    """Alcance declarado de la aprobacion. Un alcance no es un permiso efectivo."""

    task_ids: tuple = ()
    max_autonomy: str = policy_engine.AUTONOMY_CEILING_DEFAULT
    allowed_write_scopes: tuple = ()
    allowed_connectors: tuple = ()
    max_requests: int = 0
    max_output_tokens: int = 0
    max_estimated_cost_usd: float = 0.0

    def __post_init__(self):
        identifiers = []
        for task_id in _require_sequence(self.task_ids, 'approval_scope.task_ids'):
            if not isinstance(task_id, str) or not task_graph.TASK_ID_PATTERN.fullmatch(task_id):
                raise InvalidFieldError('approval_scope.task_ids: cada identificador debe cumplir '
                                        '^[a-z0-9][a-z0-9_-]{1,63}$.')
            if task_id in identifiers:
                raise InvalidFieldError(f'approval_scope.task_ids: "{task_id}" esta declarada mas de una vez.')
            identifiers.append(task_id)
        if not identifiers:
            raise InvalidFieldError('approval_scope.task_ids: la aprobacion debe declarar al menos una tarea '
                                    '(sin tareas no hay alcance que cubrir).')
        if self.max_autonomy not in policy_engine.AUTONOMY_LEVELS:
            raise InvalidFieldError('approval_scope.max_autonomy: se requiere uno de ' +
                                    ', '.join(policy_engine.AUTONOMY_LEVELS) + '.')
        object.__setattr__(self, 'task_ids', tuple(identifiers))
        object.__setattr__(self, 'allowed_write_scopes',
                           _check_text_list(self.allowed_write_scopes, 'approval_scope.allowed_write_scopes'))
        object.__setattr__(self, 'allowed_connectors',
                           _check_text_list(self.allowed_connectors, 'approval_scope.allowed_connectors'))
        object.__setattr__(self, 'max_requests', _check_counter(self.max_requests, 'approval_scope.max_requests'))
        object.__setattr__(self, 'max_output_tokens',
                           _check_counter(self.max_output_tokens, 'approval_scope.max_output_tokens'))
        object.__setattr__(self, 'max_estimated_cost_usd',
                           _check_cost(self.max_estimated_cost_usd, 'approval_scope.max_estimated_cost_usd'))

    def to_dict(self):
        return {'task_ids': list(self.task_ids), 'max_autonomy': self.max_autonomy,
                'allowed_write_scopes': list(self.allowed_write_scopes),
                'allowed_connectors': list(self.allowed_connectors),
                'max_requests': self.max_requests, 'max_output_tokens': self.max_output_tokens,
                'max_estimated_cost_usd': self.max_estimated_cost_usd}


@dataclass(frozen=True)
class Approver:
    """Aprobador DECLARATIVO. `authenticated` es siempre `False`: no hay autenticacion."""

    role: str
    mode: str = APPROVER_MODE
    authenticated: bool = APPROVER_AUTHENTICATED

    def __post_init__(self):
        if self.mode != APPROVER_MODE:
            raise AuthenticationClaimError('approver.mode: el unico modo admitido es "declarative_role"; '
                                           f'recibido {_describe(self.mode)}.')
        if self.authenticated is not False:
            raise AuthenticationClaimError('approver.authenticated: debe ser false; este sistema no autentica al '
                                           'aprobador (D-R0-5) y un recibo no puede presentarse como identidad '
                                           'verificada.')
        _check_text(self.role, 'approver.role', 1, 120)

    def to_dict(self):
        return {'mode': self.mode, 'role': self.role, 'authenticated': self.authenticated}


@dataclass(frozen=True)
class PolicyReference:
    """Politica bajo la que se aprobo: version y hash exacto, sin copiar la politica."""

    policy_version: str
    policy_hash: str
    approval_required: bool = True

    def __post_init__(self):
        _check_text(self.policy_version, 'policy.policy_version', 1, 120)
        _check_hash(self.policy_hash, 'policy.policy_hash')
        if not isinstance(self.approval_required, bool):
            raise InvalidFieldError('policy.approval_required: se requiere booleano.')

    def to_dict(self):
        return {'policy_version': self.policy_version, 'policy_hash': self.policy_hash,
                'approval_required': self.approval_required}


@dataclass(frozen=True)
class Revocation:
    """Revocacion declarativa de una aprobacion anterior. No borra el recibo previo."""

    revoked_at: str
    revoked_by_role: str
    reason: str
    supersedes: str | None = None

    def __post_init__(self):
        _check_instant(self.revoked_at, 'revocation.revoked_at')
        _check_text(self.revoked_by_role, 'revocation.revoked_by_role', 1, 120)
        _check_text(self.reason, 'revocation.reason', 1, 600)
        if self.supersedes is not None:
            if not isinstance(self.supersedes, str) or not RECEIPT_ID_PATTERN.fullmatch(self.supersedes):
                raise InvalidFieldError('revocation.supersedes: se requiere el receipt_id del recibo superado.')

    def to_dict(self):
        return {'revoked_at': self.revoked_at, 'revoked_by_role': self.revoked_by_role,
                'reason': self.reason, 'supersedes': self.supersedes}


@dataclass(frozen=True)
class ApprovalReceipt:
    """Recibo inmutable de aprobacion (o denegacion) enlazado al hash exacto del TaskGraph.

    `receipt_id` y `receipt_sha256` se derivan del contenido cuando no se aportan, de modo que
    el mismo contenido produce el mismo sello y el mismo identificador. Un `receipt_sha256`
    aportado que no coincida con el contenido se rechaza: es la deteccion de alteracion.
    """

    graph_sha256: str
    graph_schema: str
    approval_scope: ApprovalScope
    approver: Approver
    policy: PolicyReference
    created_at: str
    decision: str = DECISION_APPROVED
    expires_at: str | None = None
    revocation: Revocation | None = None
    notes: str = ''
    receipt_id: str = ''
    kind: str = RECEIPT_KIND
    receipt_schema: str = RECEIPT_SCHEMA
    receipt_version: str = RECEIPT_SCHEMA_VERSION
    receipt_sha256: str = ''

    def __post_init__(self):
        if self.receipt_schema != RECEIPT_SCHEMA:
            raise InvalidFieldError('receipt_schema: se requiere "%s"; recibido %s.'
                                    % (RECEIPT_SCHEMA, _describe(self.receipt_schema)))
        if self.receipt_version != RECEIPT_SCHEMA_VERSION:
            raise InvalidFieldError('receipt_version: se requiere "%s" (un contrato no se degrada).'
                                    % RECEIPT_SCHEMA_VERSION)
        if self.kind != RECEIPT_KIND:
            raise InvalidFieldError('kind: se requiere "%s"; recibido %s.' % (RECEIPT_KIND, _describe(self.kind)))
        _check_hash(self.graph_sha256, 'graph_sha256')
        if self.graph_schema not in GRAPH_SCHEMAS:
            raise GraphSchemaMismatchError('graph_schema: se requiere uno de ' + ', '.join(GRAPH_SCHEMAS) +
                                           f'; recibido {_describe(self.graph_schema)}. El recibo no se construye '
                                           'sobre un esquema de grafo desconocido.')
        if not isinstance(self.approval_scope, ApprovalScope):
            raise InvalidFieldError('approval_scope: se requiere un ApprovalScope ya validado.')
        if not isinstance(self.approver, Approver):
            raise InvalidFieldError('approver: se requiere un Approver declarativo.')
        if not isinstance(self.policy, PolicyReference):
            raise InvalidFieldError('policy: se requiere una PolicyReference.')
        _check_text(self.approver.role, 'approver.role', 1, 120)
        if self.decision not in DECISIONS:
            raise InvalidFieldError('decision: se requiere uno de ' + ', '.join(DECISIONS) + '.')
        _check_instant(self.created_at, 'created_at')
        if self.expires_at is not None:
            _check_instant(self.expires_at, 'expires_at')
            if (_instant_epoch(self.expires_at) or 0.0) < (_instant_epoch(self.created_at) or 0.0):
                raise InvalidFieldError('expires_at: no puede ser anterior a created_at.')
        if self.revocation is not None and not isinstance(self.revocation, Revocation):
            raise InvalidFieldError('revocation: se requiere una Revocation o null.')
        if self.revocation is not None and self.decision != DECISION_REVOKED:
            raise InvalidFieldError('revocation: solo un recibo con decision "revoked" declara una revocacion.')
        if self.decision == DECISION_REVOKED and self.revocation is None:
            raise MissingFieldError('revocation: un recibo revocado debe declarar la revocacion (quien, cuando y '
                                    'por que).')
        _check_text(self.notes, 'notes', 0, _NOTES_MAX)
        if self.receipt_id and (not isinstance(self.receipt_id, str)
                                or not RECEIPT_ID_PATTERN.fullmatch(self.receipt_id)):
            raise InvalidFieldError('receipt_id: se requiere texto de 8..128 caracteres del patron '
                                    '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$.')
        object.__setattr__(self, 'receipt_id', self.receipt_id or _derived_receipt_id(self))
        digest = _sha256_json(self._payload())
        if self.receipt_sha256 and self.receipt_sha256 != digest:
            raise ReceiptIntegrityError('receipt_hash_mismatch: el sello declarado no coincide con el contenido '
                                        'del recibo; el recibo fue alterado y no se admite.')
        object.__setattr__(self, 'receipt_sha256', digest)

    def _payload(self):
        """Payload canonico sin el sello: el sello cubre exactamente este contenido."""
        revocation = None if self.revocation is None else self.revocation.to_dict()
        return {'receipt_schema': self.receipt_schema, 'receipt_version': self.receipt_version,
                'receipt_id': self.receipt_id, 'kind': self.kind, 'graph_sha256': self.graph_sha256,
                'graph_schema': self.graph_schema, 'approval_scope': self.approval_scope.to_dict(),
                'approver': self.approver.to_dict(), 'policy': self.policy.to_dict(),
                'decision': self.decision, 'created_at': self.created_at, 'expires_at': self.expires_at,
                'revocation': revocation, 'notes': self.notes}

    def to_dict(self):
        """Declaracion completa del recibo, incluido su sello."""
        payload = self._payload()
        payload['receipt_sha256'] = self.receipt_sha256
        return payload

    def is_expired(self, now=None):
        if self.expires_at is None:
            return False
        reference = _instant_epoch(_resolve_now(now))
        expiry = _instant_epoch(self.expires_at)
        return reference is not None and expiry is not None and reference > expiry

    def is_active(self, now=None):
        """Vigente = aprobado, sin revocacion declarada y no expirado a `now`."""
        if self.decision not in ACTIVE_DECISIONS or self.revocation is not None:
            return False
        return not self.is_expired(now=now)


def _derived_receipt_id(receipt):
    """Identificador determinista derivado del contenido (mismo contenido, mismo id)."""
    payload = receipt._payload()
    payload['receipt_id'] = ''
    return 'rcpt-' + _sha256_json(payload)[:24]


def graph_hash_of(graph):
    """Recalcula el hash del grafo con la funcion congelada de I1 (no se anade campo alguno)."""
    if not isinstance(graph, task_graph.TaskGraph):
        raise InvalidFieldError('graph: se requiere un TaskGraph ya construido y autoverificado; recibido '
                                f'{_describe(graph)}.')
    return task_graph.compute_graph_sha256(graph.tasks)


def graph_schema_of(graph):
    """Esquema del grafo declarado por su propio contrato (`graph_version` congelado)."""
    if not isinstance(graph, task_graph.TaskGraph):
        raise InvalidFieldError('graph: se requiere un TaskGraph ya construido y autoverificado; recibido '
                                f'{_describe(graph)}.')
    return GRAPH_SCHEMA_PREFIX + str(graph.graph_version)


def policy_reference(policy):
    """Referencia de solo lectura a una politica del Policy Engine (version + hash)."""
    revision = getattr(policy, 'policy_revision', None)
    policy_hash = getattr(policy, 'policy_hash', None)
    if revision is None or not isinstance(policy_hash, str):
        raise InvalidFieldError('policy: se requiere una politica del Policy Engine con revision y hash '
                                '(p. ej. policy_engine.Policy.default()).')
    return PolicyReference(policy_version='%s.%s' % (policy_engine.POLICY_CONTRACT_VERSION, revision),
                           policy_hash=_check_hash(policy_hash, 'policy.policy_hash'),
                           approval_required=True)


def issue_receipt(graph, *, role, policy, scope, decision=DECISION_APPROVED, expires_at=None, notes='',
                  now=None, receipt_id=None, graph_sha256=None, graph_schema=None):
    """Emision explicita del recibo: aprobar o denegar produce evidencia inmutable.

    El recibo se NIEGA a construirse si `graph_sha256` o `graph_schema` no coinciden con el
    grafo aprobado. Esta funcion no ejecuta nada, no concede permisos y no escribe nada.
    """
    actual_hash = graph_hash_of(graph)
    actual_schema = graph_schema_of(graph)
    if graph_sha256 is not None and graph_sha256 != actual_hash:
        raise GraphHashMismatchError('graph_hash_mismatch: el hash declarado no corresponde al grafo aprobado; '
                                     'el recibo no se construye sobre un grafo distinto.')
    if graph_schema is not None and graph_schema != actual_schema:
        raise GraphSchemaMismatchError('graph_schema_mismatch: el esquema declarado no corresponde al grafo '
                                       f'aprobado ({actual_schema}).')
    if not isinstance(role, str):
        raise InvalidFieldError('role: el aprobador es un ROL declarativo (texto), no una identidad autenticada.')
    if isinstance(scope, Mapping):
        scope = ApprovalScope(**_read_values(scope, APPROVAL_SCOPE_FIELDS, 'scope'))
    if not isinstance(scope, ApprovalScope):
        raise InvalidFieldError('scope: se requiere un ApprovalScope o un Mapping con su forma.')
    reference = policy if isinstance(policy, PolicyReference) else policy_reference(policy)
    return ApprovalReceipt(graph_sha256=actual_hash, graph_schema=actual_schema, approval_scope=scope,
                           approver=Approver(role=role), policy=reference,
                           created_at=_resolve_now(now), decision=decision, expires_at=expires_at,
                           notes=notes, receipt_id=receipt_id or '')


def approve(graph, **options):
    """Atajo: emite el recibo de aprobacion (`decision='approved'`)."""
    return issue_receipt(graph, decision=DECISION_APPROVED, **options)


def deny(graph, **options):
    """Atajo: emite el recibo de denegacion (`decision='denied'`) para dejar constancia."""
    return issue_receipt(graph, decision=DECISION_DENIED, **options)


def revoke_receipt(receipt, *, role, reason, now=None):
    """Emite un recibo de revocacion que supera a `receipt` sin borrarlo.

    El recibo previo sigue existiendo y sigue siendo verificable; la vigencia la decide
    `active_receipt()`/`evaluate_execution()` con la cadena de revocaciones.
    """
    if not isinstance(receipt, ApprovalReceipt):
        raise InvalidFieldError('receipt: se requiere un ApprovalReceipt.')
    moment = _resolve_now(now)
    return ApprovalReceipt(graph_sha256=receipt.graph_sha256, graph_schema=receipt.graph_schema,
                           approval_scope=receipt.approval_scope, approver=Approver(role=role),
                           policy=receipt.policy, created_at=moment, decision=DECISION_REVOKED,
                           expires_at=receipt.expires_at,
                           revocation=Revocation(revoked_at=moment, revoked_by_role=role, reason=reason,
                                                 supersedes=receipt.receipt_id),
                           notes=receipt.notes)


def receipt_payload(receipt):
    """Copia del payload canonico (el llamador no puede alterar el recibo)."""
    if not isinstance(receipt, ApprovalReceipt):
        raise InvalidFieldError('receipt: se requiere un ApprovalReceipt.')
    return receipt.to_dict()


def canonical_receipt_json(receipt):
    """JSON canonico determinista del recibo: el mismo contenido produce el mismo texto."""
    return _canonical_bytes(receipt_payload(receipt)).decode('utf-8')


def receipt_fingerprint(receipt):
    """Sello recalculado desde el payload (no se confia en el campo declarado).

    Acepta un `ApprovalReceipt` o el payload crudo: en ese caso recalcula el sello sobre los
    campos del recibo y falla con error tipado si falta alguno.
    """
    if isinstance(receipt, ApprovalReceipt):
        return _sha256_json(receipt._payload())
    data = _require_mapping(receipt, 'receipt')
    payload = {}
    for name in RECEIPT_FIELDS:
        if name == 'receipt_sha256':
            continue
        value = data.get(name, _MISSING)
        if value is _MISSING:
            raise MissingFieldError(f'receipt: falta el campo obligatorio "{name}" para recalcular el sello.')
        payload[name] = value
    return _sha256_json(payload)


def parse_receipt(value):
    """Reconstruye un recibo desde su payload canonico (`Mapping` o texto JSON).

    Detecta alteracion: si el contenido no coincide con `receipt_sha256`, rechaza. Si declara
    credenciales, autenticacion o campos no declarados, rechaza. Nunca abre ficheros.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise InvalidFieldError('receipt: el texto no es JSON valido.') from None
    data = _require_mapping(value, 'receipt')
    # El blindaje de lectura va PRIMERO: un nombre con forma de credencial o una declaracion de
    # autenticacion se rechazan con su propio codigo, no como "campo no declarado".
    _reject_prohibited_and_claims(data, 'receipt')
    data = _unknown_names(data, RECEIPT_FIELDS, 'receipt')
    values = _read_values(data, RECEIPT_REQUIRED_FIELDS + RECEIPT_EXTRA_FIELDS, 'receipt', required=False)
    missing = tuple(name for name in RECEIPT_REQUIRED_FIELDS if values[name] is _MISSING)
    if missing:
        raise MissingFieldError('receipt: faltan campos obligatorios del recibo v1: ' + ', '.join(missing) + '.')
    scope_data = _unknown_names(_require_mapping(values['approval_scope'], 'approval_scope'),
                                APPROVAL_SCOPE_FIELDS, 'approval_scope')
    approver_data = _unknown_names(_require_mapping(values['approver'], 'approver'),
                                   APPROVER_FIELDS, 'approver')
    policy_data = _unknown_names(_require_mapping(values['policy'], 'policy'),
                                 POLICY_REFERENCE_FIELDS, 'policy')
    scope = ApprovalScope(**_read_values(scope_data, APPROVAL_SCOPE_FIELDS, 'approval_scope'))
    approver_values = _read_values(approver_data, APPROVER_FIELDS, 'approver')
    approver = Approver(role=approver_values['role'], mode=approver_values['mode'],
                        authenticated=approver_values['authenticated'])
    policy = PolicyReference(**_read_values(policy_data, POLICY_REFERENCE_FIELDS, 'policy'))
    revocation = values['revocation']
    if revocation is not None:
        revocation_data = _unknown_names(_require_mapping(revocation, 'revocation'),
                                        REVOCATION_FIELDS, 'revocation')
        revocation_values = _read_values(revocation_data, REVOCATION_FIELDS, 'revocation', required=False)
        revocation = Revocation(revoked_at=revocation_values['revoked_at'],
                                revoked_by_role=revocation_values['revoked_by_role'],
                                reason=revocation_values['reason'],
                                supersedes=(None if revocation_values['supersedes'] is _MISSING
                                            else revocation_values['supersedes']))
    return ApprovalReceipt(graph_sha256=values['graph_sha256'], graph_schema=values['graph_schema'],
                           approval_scope=scope, approver=approver, policy=policy,
                           created_at=values['created_at'], decision=values['decision'],
                           expires_at=values['expires_at'], revocation=revocation, notes=values['notes'],
                           receipt_id=('' if values['receipt_id'] is _MISSING else values['receipt_id']),
                           kind=values['kind'],
                           receipt_schema=(RECEIPT_SCHEMA if values['receipt_schema'] is _MISSING
                                           else values['receipt_schema']),
                           receipt_version=(RECEIPT_SCHEMA_VERSION if values['receipt_version'] is _MISSING
                                            else values['receipt_version']),
                           receipt_sha256=('' if values['receipt_sha256'] is _MISSING
                                           else values['receipt_sha256']))


def embed_receipt(receipt, channel):
    """Contrato de incrustacion: envuelve el payload canonico para uno de los cinco canales."""
    if channel not in CHANNELS:
        raise UnknownChannelError('channel_unknown: canal fuera de los cinco declarados (' +
                                  ', '.join(CHANNELS) + f'); recibido {_describe(channel)}.')
    key = next(entry[1] for entry in CHANNEL_CONTRACT if entry[0] == channel)
    return {'channel': channel, 'receipt_schema': RECEIPT_SCHEMA,
            'receipt_version': RECEIPT_SCHEMA_VERSION, 'key': key,
            'payload': receipt_payload(receipt), 'receipt_sha256': receipt.receipt_sha256}


def verify_receipt(value, *, graph=None, policy_hash=None, now=None):
    """Verificador de consistencia del recibo: declara problemas, nunca autoriza.

    `valid` es True solo si no hay ningun problema. Un recibo alterado, un hash que no
    corresponde al grafo, un esquema distinto, un recibo no aprobado, expirado o revocado, y
    una politica distinta se declaran de forma explicita.
    """
    try:
        receipt = value if isinstance(value, ApprovalReceipt) else parse_receipt(value)
    except ReceiptIntegrityError as error:
        return {'valid': False, 'receipt_id': None, 'decision': None, 'active': False,
                'problems': ('receipt_hash_mismatch',), 'detail': str(error),
                'graph_hash_matches': None, 'policy_hash_matches': None}
    except ApprovalReceiptError as error:
        return {'valid': False, 'receipt_id': None, 'decision': None, 'active': False,
                'problems': ('receipt_invalid',), 'detail': str(error),
                'graph_hash_matches': None, 'policy_hash_matches': None}
    problems = []
    graph_hash_matches = None
    if graph is not None:
        try:
            graph_hash_matches = graph_hash_of(graph) == receipt.graph_sha256
            if not graph_hash_matches:
                problems.append('graph_hash_mismatch')
            if graph_schema_of(graph) != receipt.graph_schema:
                problems.append('graph_schema_mismatch')
        except ApprovalReceiptError:
            problems.append('graph_invalid')
            graph_hash_matches = False
    if receipt_fingerprint(receipt) != receipt.receipt_sha256:
        problems.append('receipt_hash_mismatch')
    if receipt.decision != DECISION_APPROVED:
        problems.append('receipt_not_approved')
    if receipt.decision == DECISION_REVOKED or receipt.revocation is not None:
        problems.append('receipt_revoked')
    if receipt.is_expired(now=now):
        problems.append('receipt_expired')
    if policy_hash is not None and policy_hash != receipt.policy.policy_hash:
        problems.append('policy_hash_mismatch')
    ordered = tuple(problem for problem in VERIFICATION_PROBLEMS if problem in problems)
    return {'valid': not ordered, 'receipt_id': receipt.receipt_id, 'decision': receipt.decision,
            'active': receipt.is_active(now=now), 'problems': ordered, 'detail': '',
            'graph_hash_matches': graph_hash_matches,
            'policy_hash_matches': (None if policy_hash is None
                                    else policy_hash == receipt.policy.policy_hash)}


def active_receipt(receipts, *, graph_sha256, now=None):
    """Localiza el recibo vigente de un grafo en el instante `now`.

    Devuelve el recibo aprobado mas reciente de ese grafo que no haya sido superado por una
    revocacion ya efectiva ni este expirado; `None` si no hay ninguno vigente (y `None` NO es
    aprobacion). Una revocacion surte efecto desde su `revoked_at`: una consulta anterior a ese
    instante sigue viendo el recibo aprobado, porque la auditoria es punto a punto.
    """
    ledger = _require_sequence(receipts, 'receipts')
    moment = _resolve_now(now)
    reference = _instant_epoch(moment) or 0.0
    superseded = set()
    for entry in ledger:
        if not isinstance(entry, ApprovalReceipt) or entry.revocation is None:
            continue
        if entry.revocation.supersedes and (_instant_epoch(entry.revocation.revoked_at) or 0.0) <= reference:
            superseded.add(entry.revocation.supersedes)
    candidates = [entry for entry in ledger
                  if isinstance(entry, ApprovalReceipt) and entry.graph_sha256 == graph_sha256
                  and entry.receipt_id not in superseded and entry.is_active(now=moment)]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: (_instant_epoch(entry.created_at) or 0.0, entry.receipt_id))


def append_receipt(receipts, receipt):
    """Registra un recibo sin mutar la entrada y SIN duplicar efecto.

    La misma aprobacion enviada dos veces no se registra dos veces: `appended` es False y el
    duplicado se declara de forma explicita (`duplicate_of`), en vez de multiplicar el efecto.
    """
    ledger = tuple(_require_sequence(receipts, 'receipts'))
    if not isinstance(receipt, ApprovalReceipt):
        raise InvalidFieldError('receipt: se requiere un ApprovalReceipt.')
    for existing in ledger:
        if not isinstance(existing, ApprovalReceipt):
            raise InvalidFieldError('receipts: el registro solo admite ApprovalReceipt.')
        if existing.receipt_id == receipt.receipt_id or existing.receipt_sha256 == receipt.receipt_sha256:
            return {'receipts': ledger, 'appended': False, 'duplicate_of': existing.receipt_id,
                    'duplicates': tuple(sorted({existing.receipt_id, receipt.receipt_id})),
                    'receipt_count': len(ledger)}
    updated = ledger + (receipt,)
    return {'receipts': updated, 'appended': True, 'duplicate_of': None, 'duplicates': (),
            'receipt_count': len(updated)}


def _resolve_task(graph, task):
    """Resuelve la tarea contra el grafo: el hash cubre el contenido que se va a ejecutar.

    Un `TaskSpec` ajeno debe coincidir exactamente con la declaracion del grafo; una cadena o
    un `Mapping` solo aportan `task_id` y el contenido autoritativo es el del grafo.
    """
    if not isinstance(graph, task_graph.TaskGraph):
        return None
    candidate = None
    if isinstance(task, task_graph.TaskSpec):
        candidate = task
    elif isinstance(task, str):
        candidate = None
        for spec in graph.tasks:
            if spec.task_id == task:
                candidate = spec
        return candidate
    elif isinstance(task, Mapping):
        declared = task.get('task_id', _MISSING)
        for spec in graph.tasks:
            if spec.task_id == declared:
                return spec
        return None
    else:
        return None
    for spec in graph.tasks:
        if spec.task_id == candidate.task_id:
            return spec if spec.to_dict() == candidate.to_dict() else None
    return None


def _verdict(graph, receipt, spec, blockers, moment, detail=''):
    return {'allowed': not blockers, 'blockers': tuple(blockers),
            'receipt_id': None if receipt is None else receipt.receipt_id,
            'decision': None if receipt is None else receipt.decision,
            'graph_sha256': graph_hash_of(graph) if isinstance(graph, task_graph.TaskGraph) else None,
            'task_id': None if spec is None else spec.task_id,
            'policy_hash': None if receipt is None else receipt.policy.policy_hash,
            'evaluated_at': moment, 'detail': detail}


def evaluate_execution(graph, receipt, task, *, now=None, policy=None, policy_hash=None,
                       requested_write_scopes=(), requested_connectors=(), requested_requests=None,
                       requested_output_tokens=None, requested_cost_usd=None):
    """Veredicto estructurado: `allowed` es True solo si TODAS las condiciones se cumplen.

    Declara bloqueos explicitos en vez de aproximar. La ausencia de recibo es un bloqueo
    (`receipt_missing`) y una duda tambien. La tarea se resuelve contra el propio grafo (cuyo
    hash cubre el contenido), no contra una copia ajena.
    """
    blockers = []
    moment = _resolve_now(now)
    spec = None
    if receipt is None:
        blockers.append('receipt_missing')
        return _verdict(graph, None, None, blockers, moment)
    if not isinstance(receipt, ApprovalReceipt):
        try:
            receipt = parse_receipt(receipt)
        except ApprovalReceiptError as error:
            blockers.append('receipt_invalid')
            return _verdict(graph, None, None, blockers, moment, detail=str(error))
    if not isinstance(graph, task_graph.TaskGraph):
        blockers.append('graph_invalid')
    else:
        try:
            if graph_hash_of(graph) != receipt.graph_sha256:
                blockers.append('graph_hash_mismatch')
            if graph_schema_of(graph) != receipt.graph_schema:
                blockers.append('graph_schema_mismatch')
        except ApprovalReceiptError:
            blockers.append('graph_invalid')
    if receipt.decision != DECISION_APPROVED:
        blockers.append('receipt_not_approved')
    if receipt.decision == DECISION_REVOKED or receipt.revocation is not None:
        blockers.append('receipt_revoked')
    if receipt.is_expired(now=moment):
        blockers.append('receipt_expired')
    supplied = policy_hash
    if supplied is None and policy is not None:
        supplied = getattr(policy, 'policy_hash', None)
    if supplied is None:
        blockers.append('policy_hash_not_supplied')
    elif supplied != receipt.policy.policy_hash:
        blockers.append('policy_hash_mismatch')
    spec = _resolve_task(graph, task)
    if spec is None:
        blockers.append('task_unknown')
    else:
        scope = receipt.approval_scope
        if spec.task_id not in scope.task_ids:
            blockers.append('task_out_of_scope')
        if _autonomy_rank(spec.autonomy_level) > _autonomy_rank(scope.max_autonomy):
            blockers.append('autonomy_not_covered')
        if task_graph.is_write_capable_level(spec.autonomy_level):
            requested = _check_text_list(requested_write_scopes, 'requested_write_scopes') \
                if requested_write_scopes else ()
            if not scope.allowed_write_scopes or any(name not in scope.allowed_write_scopes
                                                     for name in requested):
                blockers.append('write_scope_not_covered')
        connectors = _check_text_list(requested_connectors, 'requested_connectors') \
            if requested_connectors else ()
        if any(connector not in scope.allowed_connectors for connector in connectors):
            blockers.append('connector_not_covered')
        requests_needed = spec.budget.requests if requested_requests is None else requested_requests
        tokens_needed = spec.budget.tokens if requested_output_tokens is None else requested_output_tokens
        cost_needed = spec.budget.money_usd if requested_cost_usd is None else requested_cost_usd
        if _check_counter(requests_needed, 'requested_requests') > scope.max_requests:
            blockers.append('requests_exceeded')
        if _check_counter(tokens_needed, 'requested_output_tokens') > scope.max_output_tokens:
            blockers.append('tokens_exceeded')
        if _check_cost(cost_needed, 'requested_cost_usd') > scope.max_estimated_cost_usd:
            blockers.append('cost_exceeded')
    ordered = tuple(code for code in BLOCKER_CODES if code in blockers)
    return _verdict(graph, receipt, spec, ordered, moment)


def can_execute(task, graph, receipt, **options):
    """Predicado estricto: True SOLO si todas las comprobaciones se cumplen.

    Devuelve `False` ante cualquier duda, incluida la ausencia de recibo y cualquier excepcion
    inesperada durante la comprobacion: el fallo nunca autoriza. La firma es la del contrato
    (`task`, `graph`, `receipt`); las opciones (`now`, `policy`, `policy_hash`, `requested_*`)
    estan documentadas en `evaluate_execution()`.
    """
    try:
        verdict = evaluate_execution(graph, receipt, task, **options)
    except Exception:  # noqa: BLE001 - fail-safe deliberado: una duda bloquea, nunca autoriza.
        return False
    return verdict['allowed'] is True


def answer_security_questions(graph, task=None, receipt=None, **options):
    """Responde por separado las cinco preguntas de seguridad del invariante de aprobacion.

    Ninguna respuesta se aproxima: con un grafo invalido o sin recibo, `graph_intact`,
    `approved`, `active` y `scope_covers` son `False` y se declaran los bloqueos.
    """
    verdict = evaluate_execution(graph, receipt, task, **options)
    hash_now = graph_hash_of(graph) if isinstance(graph, task_graph.TaskGraph) else None
    known_receipt = receipt if isinstance(receipt, ApprovalReceipt) else None
    intact = hash_now is not None and (known_receipt is None or hash_now == known_receipt.graph_sha256)
    approver = None if known_receipt is None else known_receipt.approver
    return {'graph_intact': intact,
            'graph_sha256': hash_now,
            'approved': bool(known_receipt is not None and known_receipt.decision == DECISION_APPROVED
                             and intact),
            'active': bool(known_receipt is not None and known_receipt.is_active(now=options.get('now'))),
            'scope_covers': bool(verdict['allowed']),
            'approver': {'mode': None if approver is None else approver.mode,
                         'role': None if approver is None else approver.role,
                         'authenticated': None if approver is None else approver.authenticated,
                         'identity_verified': False},
            'blockers': verdict['blockers']}
