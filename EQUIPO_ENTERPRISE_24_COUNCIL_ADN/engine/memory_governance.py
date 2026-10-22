"""Memory Governance v1 (flujo I4): cuatro planos separados, caducidad efectiva y promocion explicita.

Contrato consumido: `docs/plataforma/memory-record.schema.json` (MemoryRecord v1, congelado en
R0, huella f678780d1735c7a1570dc54a188b02e78c04e22d46db24d47e938c0c48923d41). Modulo
INERTE: gobierna alcance, caducidad y aislamiento en memoria. No ejecuta agentes, no escribe
ficheros, no abre red y no materializa ningun almacen.

Reglas congeladas que este modulo implementa:
  * cuatro planos separados (`execution`, `project`, `organizational`, `personal`) sin
    almacen ni indice compartido;
  * cada fragmento declara `origin`, `recorded_at`, `scope`, `confidence`, `integrity.sha256`,
    `ttl_seconds` explicito, `read_permissions`, `update_policy` y `tenant_id`; si falta
    cualquiera, el alta se rechaza con error tipado;
  * lectura permitida solo si coinciden `plane` **y** `tenant_id` **y** existe una entrada de
    `read_permissions`; `cross_plane_reads`, `cross_tenant_reads` y `contaminates` son `false`;
  * un fragmento caducado no se devuelve nunca: se marca expirado y la marca es permanente
    (una lectura con un reloj anterior no lo revive);
  * `execution_lifetime`: el plano de ejecucion es efimero y expira al cerrar su tarea;
  * `project_inheritance`: un proyecto no hereda memoria organizacional ni personal;
  * `personal_exclusion`: el plano personal nunca se exporta, ni en el paquete ni por
    hand-off externo, y es terminal: no se promueve ni se mezcla con otro inquilino.

Reutiliza el modelo de politica de I3 (`engine/policy_engine.py`): las escrituras, las
promociones y los hand-offs externos pasan por `evaluate` con las puertas humanas del
contrato (`store_memory` -> `write`; `send_message_out` -> `connectors`) y la lectura de
contenido se autoriza con la unica accion de lectura del vocabulario congelado (`read_repo`),
que por defecto no levanta puerta y que una organizacion puede cerrar declarando la puerta
que corresponda en su politica. Ninguna ruta eleva autonomia ni inventa una aprobacion: sin
aprobacion declarativa valida, la operacion queda en `require_human_approval`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

try:  # importacion como paquete del motor
    from .policy_engine import (DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE, Policy, PolicyError,
                                PROHIBITED_FIELDS, PROHIBITED_FIELDS_SOURCE, evaluate,
                                find_prohibited_fields)
    from .tenants import (DOMAINS, TenantRegistry, require_path_belongs_to, resolve_path)
except ImportError:  # raiz de la suite en sys.path
    from policy_engine import (DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE, Policy, PolicyError,
                               PROHIBITED_FIELDS, PROHIBITED_FIELDS_SOURCE, evaluate,
                               find_prohibited_fields)
    from tenants import DOMAINS, TenantRegistry, require_path_belongs_to, resolve_path

MEMORY_RECORD_VERSION = '1'
MEMORY_VERSION_FIELD = 'memory_record_version'

PLANES = ('execution', 'project', 'organizational', 'personal')
EXECUTION_PLANE = 'execution'
PROJECT_PLANE = 'project'
ORGANIZATIONAL_PLANE = 'organizational'
PERSONAL_PLANE = 'personal'

SOURCE_KINDS = ('manual_entry', 'run_output', 'tool_result', 'human_record', 'imported_file')
CONTENT_KINDS = ('inline_text', 'file_ref')
SCOPE_KINDS = ('task', 'project', 'organization', 'personal')
UPDATE_POLICIES = ('append_only', 'supersede', 'manual_review', 'expire_on_ttl')
HASH_ALGORITHM = 'SHA-256'

#: Cada plano exige un scope coherente; una promocion obliga a declarar el scope del destino.
PLANE_SCOPES = {EXECUTION_PLANE: 'task', PROJECT_PLANE: 'project',
                ORGANIZATIONAL_PLANE: 'organization', PERSONAL_PLANE: 'personal'}

#: Rutas de promocion permitidas. `personal` es terminal y nada se promueve hacia el.
PROMOTION_ROUTES = ((EXECUTION_PLANE, PROJECT_PLANE), (EXECUTION_PLANE, ORGANIZATIONAL_PLANE),
                    (PROJECT_PLANE, ORGANIZATIONAL_PLANE))

EXPORT_DESTINATIONS = ('package', 'external_handoff')

EXECUTION_LIFETIME = 'efimero: vive en el proceso; sin persistencia autorizada no sobrevive'
PROJECT_INHERITANCE = 'un proyecto no hereda memoria organizacional ni personal'
PERSONAL_EXCLUSION = 'el plano personal nunca se exporta en el paquete ni en el ZIP'
READ_RULE = ('lectura permitida solo si coincide plane AND tenant_id AND existe una entrada de '
             'read_permissions')
CONTAMINATES = False
CROSS_PLANE_READS = False
CROSS_TENANT_READS = False
MAX_CONTENT_CHARS = 8000

RECORD_FIELDS = ('memory_record_version', 'memory_id', 'plane', 'origin', 'content_ref',
                 'recorded_at', 'scope', 'confidence', 'integrity', 'ttl_seconds', 'expires_at',
                 'read_permissions', 'update_policy', 'tenant_id', 'cross_plane_reads',
                 'cross_tenant_reads', 'contaminates')
ORIGIN_REQUIRED_FIELDS = ('source_kind', 'ref', 'captured_at')
ORIGIN_FIELDS = ORIGIN_REQUIRED_FIELDS + ('author',)
CONTENT_REQUIRED_FIELDS = ('kind', 'value')
CONTENT_FIELDS = CONTENT_REQUIRED_FIELDS + ('sha256',)
SCOPE_REQUIRED_FIELDS = ('scope_kind',)
SCOPE_FIELDS = SCOPE_REQUIRED_FIELDS + ('project_id', 'task_id', 'agent_ref')
INTEGRITY_REQUIRED_FIELDS = ('hash_algorithm', 'sha256', 'bytes')
PERMISSION_REQUIRED_FIELDS = ('role_ref', 'tenant_id', 'plane')

MEMORY_ERROR_CODES = ('unsupported_version', 'invalid_record', 'invalid_request',
                      'prohibited_field', 'memory_expired', 'task_closed', 'record_not_found',
                      'record_exists', 'cross_tenant_denied', 'cross_plane_denied',
                      'read_not_permitted', 'human_approval_required', 'policy_denied',
                      'personal_plane_not_exportable', 'domain_not_exportable',
                      'promotion_not_allowed', 'unknown_tenant', 'domain_not_declared',
                      'sensitive_domain_not_materializable')

_MEMORY_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,63}$')
#: Patron publico del identificador de fragmento (contrato v1). Lo consume
#: engine/bridge.py para rechazar en el borde con el MISMO criterio que el governor,
#: en vez de repetir una copia que se desincroniza (paso: el borde aceptaba puntos).
MEMORY_ID_PATTERN = r'[a-z0-9][a-z0-9_-]{1,63}'
_TENANT_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,63}$')
_INSTANT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
_HASH_RE = re.compile(r'^[0-9a-f]{64}$')


class MemoryGovernanceError(ValueError):
    """Rechazo tipado de la capa de memoria. `code` pertenece al vocabulario declarado."""

    def __init__(self, code, message, decision=None):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message
        #: Decision de politica asociada (datos puros del contrato I3), cuando corresponde.
        self.decision = decision


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def memory_hash(record):
    """Huella canonica del fragmento validado (trazabilidad y deduplicacion determinista)."""
    return sha256_text(canonical(validate_record(record)))


def parse_instant(text, field='instante'):
    if not isinstance(text, str) or not _INSTANT_RE.match(text):
        raise MemoryGovernanceError('invalid_record', (
            '%s debe ser un instante ISO-8601 UTC terminado en Z.' % field))
    base, _, fraction = text[:-1].partition('.')
    moment = datetime.strptime(base, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    if fraction:
        moment = moment.replace(microsecond=int(fraction.ljust(6, '0')[:6]))
    return moment


def format_instant(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def add_seconds(instant, seconds):
    return format_instant(parse_instant(instant) + timedelta(seconds=seconds))


def _now(now):
    return now if now is not None else utc_now()


def _reject_prohibited(payload, where):
    hits = find_prohibited_fields(payload)
    if hits:
        raise MemoryGovernanceError('prohibited_field', (
            'El %s contiene campos con forma de credencial o consentimiento (%s); la capa de '
            'memoria no los admite ni los registra. Guard reutilizado de %s.'
            % (where, ', '.join(sorted(hits)), PROHIBITED_FIELDS_SOURCE)))


def _require_text(value, field, minimum=1, maximum=400):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise MemoryGovernanceError('invalid_record', (
            '%s debe ser texto legible de %d a %d caracteres.' % (field, minimum, maximum)))
    return value


def _require_hash(value, field):
    if not isinstance(value, str) or not _HASH_RE.match(value):
        raise MemoryGovernanceError('invalid_record', (
            '%s debe ser 64 caracteres hexadecimales en minuscula.' % field))
    return value


def validate_record(record):
    """Valida un MemoryRecord contra el contrato congelado y devuelve una copia normalizada."""
    if not isinstance(record, dict):
        raise MemoryGovernanceError('invalid_record', 'El fragmento de memoria debe ser un '
                                      'objeto JSON del contrato MemoryRecord v1.')
    version = record.get(MEMORY_VERSION_FIELD)
    if version != MEMORY_RECORD_VERSION:
        raise MemoryGovernanceError('unsupported_version', (
            'El fragmento declara %s=%r; esta capa solo soporta %r y no degrada a otra '
            'interpretacion.' % (MEMORY_VERSION_FIELD, version, MEMORY_RECORD_VERSION)))
    unknown = sorted(str(key) for key in record if key not in RECORD_FIELDS)
    _reject_prohibited(record, 'fragmento')
    if unknown:
        raise MemoryGovernanceError('invalid_record', 'Campos no admitidos en el fragmento: %s.'
                                    % ', '.join(unknown))
    missing = [field for field in RECORD_FIELDS if field not in record]
    if missing:
        raise MemoryGovernanceError('invalid_record', (
            'El fragmento no declara campos obligatorios del contrato v1: %s. Sin origen, scope, '
            'TTL, confianza o hash no hay memoria gobernada.' % ', '.join(missing)))
    memory_id = record['memory_id']
    if not isinstance(memory_id, str) or not _MEMORY_ID_RE.match(memory_id):
        raise MemoryGovernanceError('invalid_record', 'memory_id no cumple el patron del contrato '
                                      'v1 (2..64 de [a-z0-9_-]).')
    plane = record['plane']
    if plane not in PLANES:
        raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.' % (PLANES,))
    origin = record['origin']
    if not isinstance(origin, dict) or set(origin) - set(ORIGIN_FIELDS) or any(
            field not in origin for field in ORIGIN_REQUIRED_FIELDS):
        raise MemoryGovernanceError('invalid_record', (
            'origin debe declarar %s (y opcionalmente author).' % (ORIGIN_REQUIRED_FIELDS,)))
    if origin['source_kind'] not in SOURCE_KINDS:
        raise MemoryGovernanceError('invalid_record', 'origin.source_kind debe pertenecer a %s.'
                                      % (SOURCE_KINDS,))
    _require_text(origin['ref'], 'origin.ref', maximum=400)
    parse_instant(origin['captured_at'], 'origin.captured_at')
    if 'author' in origin:
        _require_text(origin['author'], 'origin.author', maximum=120)
    content_ref = record['content_ref']
    if not isinstance(content_ref, dict) or set(content_ref) - set(CONTENT_FIELDS) or any(
            field not in content_ref for field in CONTENT_REQUIRED_FIELDS):
        raise MemoryGovernanceError('invalid_record', (
            'content_ref debe declarar %s (y opcionalmente sha256).' % (CONTENT_REQUIRED_FIELDS,)))
    if content_ref['kind'] not in CONTENT_KINDS:
        raise MemoryGovernanceError('invalid_record', 'content_ref.kind debe pertenecer a %s.'
                                      % (CONTENT_KINDS,))
    _require_text(content_ref['value'], 'content_ref.value', maximum=MAX_CONTENT_CHARS)
    if 'sha256' in content_ref:
        _require_hash(content_ref['sha256'], 'content_ref.sha256')
    parse_instant(record['recorded_at'], 'recorded_at')
    scope = record['scope']
    if not isinstance(scope, dict) or set(scope) - set(SCOPE_FIELDS) or any(
            field not in scope for field in SCOPE_REQUIRED_FIELDS):
        raise MemoryGovernanceError('invalid_record', (
            'scope debe declarar scope_kind (y opcionalmente project_id, task_id, agent_ref).'))
    if scope['scope_kind'] not in SCOPE_KINDS:
        raise MemoryGovernanceError('invalid_record', 'scope.scope_kind debe pertenecer a %s.'
                                      % (SCOPE_KINDS,))
    expected_scope = PLANE_SCOPES[plane]
    if scope['scope_kind'] != expected_scope:
        raise MemoryGovernanceError('invalid_record', (
            "El plano '%s' exige scope_kind '%s'; un fragmento no se lee ni se promueve con un "
            'alcance de otro plano.' % (plane, expected_scope)))
    for field in ('project_id', 'task_id', 'agent_ref'):
        value = scope.get(field)
        if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 120
                                  or any(ord(c) < 32 for c in value)):
            raise MemoryGovernanceError('invalid_record', 'scope.%s debe ser texto de 1 a 120 '
                                          'caracteres o null.' % field)
    if plane == EXECUTION_PLANE and not scope.get('task_id'):
        raise MemoryGovernanceError('invalid_record', (
            'El plano de ejecucion exige scope.task_id: sin tarea no hay cierre que lo caduque.'))
    if plane == PROJECT_PLANE and not scope.get('project_id'):
        raise MemoryGovernanceError('invalid_record', 'El plano de proyecto exige scope.project_id.')
    confidence = record['confidence']
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise MemoryGovernanceError('invalid_record', (
            'confidence debe ser un numero entre 0 y 1; su ausencia no se aproxima a 1.'))
    integrity = record['integrity']
    if not isinstance(integrity, dict) or set(integrity) != set(INTEGRITY_REQUIRED_FIELDS):
        raise MemoryGovernanceError('invalid_record', 'integrity debe declarar exactamente %s.'
                                      % (INTEGRITY_REQUIRED_FIELDS,))
    if integrity['hash_algorithm'] != HASH_ALGORITHM:
        raise MemoryGovernanceError('invalid_record', "integrity.hash_algorithm debe ser 'SHA-256'.")
    _require_hash(integrity['sha256'], 'integrity.sha256')
    if isinstance(integrity['bytes'], bool) or not isinstance(integrity['bytes'], int) or integrity['bytes'] < 0:
        raise MemoryGovernanceError('invalid_record', 'integrity.bytes debe ser un entero no '
                                      'negativo.')
    if content_ref['kind'] == 'inline_text':
        if integrity['sha256'] != sha256_text(content_ref['value']):
            raise MemoryGovernanceError('invalid_record', (
                'integrity.sha256 no corresponde al contenido declarado: la integridad se '
                'recomprueba en el alta.'))
        if integrity['bytes'] != len(content_ref['value'].encode('utf-8')):
            raise MemoryGovernanceError('invalid_record', (
                'integrity.bytes no corresponde al contenido declarado.'))
    ttl = record['ttl_seconds']
    if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 0):
        raise MemoryGovernanceError('invalid_record', 'ttl_seconds debe ser un entero no negativo '
                                      'o null explicito.')
    expires_at = record['expires_at']
    if expires_at is not None:
        parse_instant(expires_at, 'expires_at')
        if ttl is not None and expires_at != add_seconds(record['recorded_at'], ttl):
            raise MemoryGovernanceError('invalid_record', (
                'expires_at y ttl_seconds se contradicen; declara solo uno o hazlos coincidir.'))
    elif ttl is not None:
        expires_at = add_seconds(record['recorded_at'], ttl)
    permissions = record['read_permissions']
    if not isinstance(permissions, list) or not permissions:
        raise MemoryGovernanceError('invalid_record', (
            'read_permissions exige al menos una entrada {role_ref, tenant_id, plane}.'))
    tenant_id = record['tenant_id']
    if not isinstance(tenant_id, str) or not _TENANT_ID_RE.match(tenant_id):
        raise MemoryGovernanceError('invalid_record', 'tenant_id no cumple el patron del contrato '
                                      'v1.')
    normalized_permissions = []
    for entry in permissions:
        if not isinstance(entry, dict) or set(entry) != set(PERMISSION_REQUIRED_FIELDS):
            raise MemoryGovernanceError('invalid_record', (
                'Cada entrada de read_permissions declara exactamente %s.'
                % (PERMISSION_REQUIRED_FIELDS,)))
        _require_text(entry['role_ref'], 'read_permissions[].role_ref', maximum=120)
        if not isinstance(entry['tenant_id'], str) or not _TENANT_ID_RE.match(entry['tenant_id']):
            raise MemoryGovernanceError('invalid_record', 'read_permissions[].tenant_id no cumple '
                                          'el patron del contrato v1.')
        if entry['plane'] not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'read_permissions[].plane debe '
                                          'pertenecer a %s.' % (PLANES,))
        if entry['tenant_id'] != tenant_id:
            raise MemoryGovernanceError('cross_tenant_denied', (
                'Una entrada de read_permissions nombra al inquilino %s y el fragmento pertenece a '
                '%s: una entrada no puede autorizar otro inquilino.' % (entry['tenant_id'], tenant_id)))
        normalized_permissions.append(dict(entry))
    if not any(entry['plane'] == plane and entry['tenant_id'] == tenant_id
               for entry in normalized_permissions):
        raise MemoryGovernanceError('read_not_permitted', (
            "Ninguna entrada de read_permissions autoriza el plano '%s' del inquilino %s: el "
            'fragmento seria ilegible y no se admite.' % (plane, tenant_id)))
    if record['update_policy'] not in UPDATE_POLICIES:
        raise MemoryGovernanceError('invalid_record', 'update_policy debe pertenecer a %s.'
                                      % (UPDATE_POLICIES,))
    for field, expected in (('cross_plane_reads', CROSS_PLANE_READS),
                            ('cross_tenant_reads', CROSS_TENANT_READS),
                            ('contaminates', CONTAMINATES)):
        if record[field] is not expected:
            raise MemoryGovernanceError('invalid_record', (
                '%s es const %r en el contrato v1; este fragmento intenta abrir una via de '
                'contaminacion.' % (field, expected)))
    normalized = {field: copy.deepcopy(record[field]) for field in RECORD_FIELDS}
    normalized['expires_at'] = expires_at
    normalized['read_permissions'] = normalized_permissions
    return normalized


def build_record(memory_id, plane, *, tenant_id, origin, content, recorded_at, scope, confidence,
                 ttl_seconds, read_permissions, update_policy='append_only', expires_at=None,
                 content_kind='inline_text', content_ref_sha256=None, declared_bytes=None):
    """Construye un MemoryRecord v1 validado. Determinista y sin acceso a disco.

    Con `content_kind='inline_text'` el hash y el tamano se calculan del propio texto. Con
    `content_kind='file_ref'` este modulo NO lee el fichero: el autor debe declarar
    `content_ref_sha256` y `declared_bytes`, y la integridad se limita a registrarlos.
    """
    if content_kind not in CONTENT_KINDS:
        raise MemoryGovernanceError('invalid_record', 'content_ref.kind debe pertenecer a %s.'
                                      % (CONTENT_KINDS,))
    if content_kind == 'inline_text':
        content_hash = sha256_text(content)
        size = len(content.encode('utf-8'))
    else:
        if not content_ref_sha256:
            raise MemoryGovernanceError('invalid_request', (
                'Una referencia a fichero exige el sha256 declarado: este modulo no lee ficheros.'))
        _require_hash(content_ref_sha256, 'content_ref_sha256')
        content_hash = content_ref_sha256
        size = 0 if declared_bytes is None else declared_bytes
    record = {
        MEMORY_VERSION_FIELD: MEMORY_RECORD_VERSION,
        'memory_id': memory_id,
        'plane': plane,
        'origin': dict(origin),
        'content_ref': {'kind': content_kind, 'value': content, 'sha256': content_hash},
        'recorded_at': recorded_at,
        'scope': dict(scope),
        'confidence': confidence,
        'integrity': {'hash_algorithm': HASH_ALGORITHM, 'sha256': content_hash, 'bytes': size},
        'ttl_seconds': ttl_seconds,
        'expires_at': expires_at,
        'read_permissions': [dict(entry) for entry in read_permissions],
        'update_policy': update_policy,
        'tenant_id': tenant_id,
        'cross_plane_reads': CROSS_PLANE_READS,
        'cross_tenant_reads': CROSS_TENANT_READS,
        'contaminates': CONTAMINATES,
    }
    return validate_record(record)


def _policy_decision(policy, action, *, approval, now):
    if not isinstance(policy, Policy):
        raise MemoryGovernanceError('invalid_request', 'Se esperaba una politica v1 de I3.')
    try:
        decision = evaluate(policy, action, approval=approval, now=now)
    except PolicyError as exc:
        raise MemoryGovernanceError('invalid_request', (
            'La politica rechazo la accion propuesta: %s' % exc)) from None
    return decision


def _require_allow(decision, what):
    if decision['decision'] == DECISION_ALLOW:
        return decision
    if decision['decision'] == DECISION_REQUIRE:
        raise MemoryGovernanceError('human_approval_required', (
            '%s exige aprobacion humana (puerta %r): %s' % (what, decision['gate'],
                                                            decision['reason'])), decision)
    raise MemoryGovernanceError('policy_denied', (
        '%s fue denegada por la politica %s@%s: %s'
        % (what, decision['policy_id'], decision['policy_revision'], decision['reason'])), decision)


class MemoryStore:
    """Almacen de memoria en proceso, ligado a un inquilino. Cero escritura en disco.

    Aplica el contrato del fragmento (planos, alcance, TTL, permisos, integridad) y las reglas
    de caducidad y aislamiento. Las operaciones gobernadas por politica (`store_with_policy`,
    `read_with_policy`, `promote`, `export_records`) consultan I3 y no ejecutan nada: devuelven
    datos o lanzan un error tipado.
    """

    def __init__(self, registry, tenant_id):
        if not isinstance(registry, TenantRegistry):
            raise MemoryGovernanceError('invalid_request', 'Se esperaba un TenantRegistry.')
        self._registry = registry
        self._boundary = registry.boundary(tenant_id)
        self._records = {}
        self._expired = {}
        self._closed_tasks = set()

    @property
    def tenant_id(self):
        return self._boundary.tenant_id

    @property
    def boundary(self):
        return self._boundary

    @property
    def closed_tasks(self):
        return frozenset(self._closed_tasks)

    def record_path(self, memory_id, plane):
        """Ruta logica donde se materializaria el fragmento. Nunca sale del inquilino."""
        if plane not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.' % (PLANES,))
        if not isinstance(memory_id, str) or not _MEMORY_ID_RE.match(memory_id):
            raise MemoryGovernanceError('invalid_record', (
                'memory_id no cumple el patron del contrato v1 (2..64 de [a-z0-9_-]): una ruta de '
                'materializacion no admite un identificador libre.'))
        return resolve_path(self.tenant_id, 'memories/%s/%s' % (plane, memory_id))

    def assert_path_in_tenant(self, path):
        return require_path_belongs_to(self.tenant_id, path)

    def _key(self, plane, memory_id):
        return (plane, memory_id)

    def _find_other_plane(self, memory_id, plane):
        for other in PLANES:
            if other != plane and (other, memory_id) in self._records:
                return other
        return None

    def _is_expired(self, record, now):
        expires_at = record['expires_at']
        if expires_at is None:
            return False
        return parse_instant(expires_at) <= parse_instant(_now(now))

    def _latch(self, plane, memory_id, reason):
        self._expired.setdefault((plane, memory_id), reason)

    def _ensure_alive(self, plane, memory_id, now):
        reason = self._expired.get((plane, memory_id))
        if reason is not None:
            if reason == 'task_closed':
                raise MemoryGovernanceError('task_closed', (
                    'El fragmento %s del plano %s pertenece a una tarea ya cerrada y no se '
                    'devuelve.' % (memory_id, plane)))
            raise MemoryGovernanceError('memory_expired', (
                'El fragmento %s del plano %s esta caducado y no se revive por ninguna ruta.'
                % (memory_id, plane)))
        record = self._records.get((plane, memory_id))
        if record is not None and self._is_expired(record, now):
            self._latch(plane, memory_id, 'ttl')
            raise MemoryGovernanceError('memory_expired', (
                'El fragmento %s del plano %s esta caducado (expires_at %s); se marca expirado y '
                'no se devuelve.' % (memory_id, plane, record['expires_at'])))

    def expired_ids(self, plane=None):
        return tuple(sorted(memory_id for (item_plane, memory_id) in self._expired
                            if plane is None or item_plane == plane))

    def expired_reason(self, plane, memory_id):
        return self._expired.get((plane, memory_id))

    def accept(self, record, *, now=None):
        """Alta en memoria: valida el contrato y aplica aislamiento. No escribe en disco."""
        validated = validate_record(record)
        if validated['tenant_id'] != self.tenant_id:
            raise MemoryGovernanceError('cross_tenant_denied', (
                'El fragmento %s pertenece al inquilino %s y este almacen gobierna %s.'
                % (validated['memory_id'], validated['tenant_id'], self.tenant_id)))
        plane = validated['plane']
        memory_id = validated['memory_id']
        if plane == EXECUTION_PLANE and validated['scope'].get('task_id') in self._closed_tasks:
            raise MemoryGovernanceError('task_closed', (
                "La tarea '%s' ya esta cerrada: su plano de ejecucion no admite fragmentos nuevos."
                % validated['scope']['task_id']))
        key = self._key(plane, memory_id)
        existing = self._records.get(key)
        if existing is not None:
            if canonical(existing) == canonical(validated):
                return copy.deepcopy(existing)
            raise MemoryGovernanceError('record_exists', (
                'El fragmento %s ya existe en el plano %s con otro contenido; el contrato prohibe '
                'sobreescribirlo en silencio (usa update_policy declarada).' % (memory_id, plane)))
        self._records[key] = copy.deepcopy(validated)
        if self._is_expired(validated, now):
            self._latch(plane, memory_id, 'ttl')
        return copy.deepcopy(validated)

    def describe(self, memory_id, *, plane, role_ref, now=None):
        """Vista sin contenido: metadatos y estado. Respeta permisos y caducidad."""
        record = self.read(memory_id, plane=plane, role_ref=role_ref, now=now)
        view = {field: copy.deepcopy(record[field]) for field in RECORD_FIELDS}
        view['content_ref'] = {key: value for key, value in record['content_ref'].items()
                               if key != 'value'}
        view['content_ref']['value_withheld'] = True
        view['status'] = 'live'
        return view

    def read(self, memory_id, *, plane, role_ref, now=None):
        """Lectura gobernada por la regla congelada: plane, tenant_id y read_permissions."""
        if plane not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.' % (PLANES,))
        key = self._key(plane, memory_id)
        record = self._records.get(key)
        if record is None:
            other = self._find_other_plane(memory_id, plane)
            if other is not None:
                raise MemoryGovernanceError('cross_plane_denied', (
                    'El fragmento %s vive en el plano %s y se intento leer desde %s: los planos no '
                    'comparten indice de lectura.' % (memory_id, other, plane)))
            raise MemoryGovernanceError('record_not_found', (
                'El inquilino %s no tiene el fragmento %s en el plano %s.'
                % (self.tenant_id, memory_id, plane)))
        permitted = any(entry['plane'] == plane and entry['tenant_id'] == self.tenant_id
                        and entry['role_ref'] == role_ref
                        for entry in record['read_permissions'])
        if not permitted:
            raise MemoryGovernanceError('read_not_permitted', (
                "El rol '%s' no tiene entrada de read_permissions para el fragmento %s del plano %s "
                'del inquilino %s.' % (role_ref, memory_id, plane, self.tenant_id)))
        self._ensure_alive(plane, memory_id, now)
        return copy.deepcopy(record)

    def list_plane(self, plane, *, role_ref, now=None):
        """Vista de los fragmentos vivos del plano. Los caducados no se devuelven nunca."""
        if plane not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.' % (PLANES,))
        views = []
        for (item_plane, memory_id), record in sorted(self._records.items()):
            if item_plane != plane:
                continue
            permitted = any(entry['plane'] == plane and entry['tenant_id'] == self.tenant_id
                            and entry['role_ref'] == role_ref
                            for entry in record['read_permissions'])
            if not permitted:
                continue
            if (plane, memory_id) in self._expired:
                continue
            if self._is_expired(record, now):
                self._latch(plane, memory_id, 'ttl')
                continue
            views.append(self.describe(memory_id, plane=plane, role_ref=role_ref, now=now))
        return tuple(views)

    def sweep(self, *, now=None):
        """Marca expirados los fragmentos vencidos. Devuelve los identificadores marcados."""
        marked = []
        for (plane, memory_id), record in sorted(self._records.items()):
            if (plane, memory_id) in self._expired:
                continue
            if self._is_expired(record, now):
                self._latch(plane, memory_id, 'ttl')
                marked.append(memory_id)
        return tuple(sorted(marked))

    def close_task(self, task_id, *, now=None):
        """Cierra la tarea: su plano de ejecucion caduca y no se reabre."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise MemoryGovernanceError('invalid_request', 'close_task exige un task_id.')
        self._closed_tasks.add(task_id)
        closed = []
        for (plane, memory_id), record in sorted(self._records.items()):
            if plane == EXECUTION_PLANE and record['scope'].get('task_id') == task_id:
                self._latch(plane, memory_id, 'task_closed')
                closed.append(memory_id)
        return tuple(sorted(closed))

    def action_for(self, policy, action_kind, plane, memory_id=None):
        """Accion exacta que esta capa somete a la politica, con su `scope_hash` vigente.

        El alcance lo deriva I3 del binomio (politica vigente, accion): una aprobacion humana
        concedida sobre este hash solo autoriza esta accion concreta, y cualquier cambio de la
        politica lo cambia. Es la unica forma de atar una aprobacion declarativa a una operacion
        de memoria.
        """
        if not isinstance(policy, Policy):
            raise MemoryGovernanceError('invalid_request', 'Se esperaba una politica v1 de I3.')
        action = {'action_kind': action_kind,
                  'target': 'memory://%s/%s/%s' % (self.tenant_id, plane,
                                                   memory_id if memory_id is not None else plane)}
        action['scope_hash'] = policy.scope_hash(action)
        return action

    def store_with_policy(self, policy, record, *, approval=None, now=None):
        """Alta gobernada: la puerta humana de escritura decide antes de almacenar."""
        validated = validate_record(record)
        decision = _policy_decision(policy, self.action_for(policy, 'store_memory',
                                                            validated['plane'],
                                                            validated['memory_id']),
                                    approval=approval, now=now)
        _require_allow(decision, 'El alta del fragmento %s' % validated['memory_id'])
        stored = self.accept(validated, now=now)
        return stored, dict(decision)

    def read_with_policy(self, policy, memory_id, *, plane, role_ref, approval=None, now=None):
        """Lectura de contenido: primero el aislamiento congelado y despues la autorizacion.

        El aislamiento entre planos e inquilinos se aplica antes que la politica: ninguna
        decision, ni siquiera `allow`, puede abrir una lectura que el contrato prohibe. La
        politica solo puede exigir ademas una aprobacion humana declarativa.
        """
        record = self.read(memory_id, plane=plane, role_ref=role_ref, now=now)
        decision = _policy_decision(policy, self.action_for(policy, 'read_repo', plane, memory_id),
                                    approval=approval, now=now)
        _require_allow(decision, 'La lectura del fragmento %s' % memory_id)
        return record, decision

    def promote(self, policy, memory_id, *, from_plane, to_plane, scope, role_ref,
                read_permissions=None, update_policy=None, ttl_seconds=None, approval=None,
                recorded_at=None, now=None):
        """Promocion explicita entre planos. Sin decision allow no hay copia en el destino."""
        if from_plane == PERSONAL_PLANE:
            raise MemoryGovernanceError('personal_plane_not_exportable', (
                'El plano personal es terminal: no se promueve a otro plano (regla de exclusion '
                'personal del contrato v1).'))
        if to_plane == PERSONAL_PLANE:
            raise MemoryGovernanceError('promotion_not_allowed', (
                'Nada se promueve hacia el plano personal: seria contaminarlo con otro contexto.'))
        if (from_plane, to_plane) not in PROMOTION_ROUTES:
            raise MemoryGovernanceError('promotion_not_allowed', (
                'Ruta de promocion no declarada: %s -> %s. Rutas admitidas: %s.'
                % (from_plane, to_plane, PROMOTION_ROUTES)))
        source = self.read(memory_id, plane=from_plane, role_ref=role_ref, now=now)
        moment = _now(now)
        promoted_id = 'mem-' + sha256_text('%s:%s' % (memory_id, to_plane))[:16]
        decision = _policy_decision(policy, self.action_for(policy, 'store_memory', to_plane,
                                                            promoted_id),
                                    approval=approval, now=now)
        _require_allow(decision, 'La promocion de %s hacia el plano %s' % (memory_id, to_plane))
        if read_permissions is None:
            read_permissions = [entry for entry in source['read_permissions']
                                if entry['plane'] == to_plane and entry['tenant_id'] == self.tenant_id]
            if not read_permissions:
                raise MemoryGovernanceError('read_not_permitted', (
                    'El plano destino %s no tiene entradas de read_permissions declaradas para la '
                    'promocion; no se heredan en silencio.' % to_plane))
        promoted = {
            MEMORY_VERSION_FIELD: MEMORY_RECORD_VERSION,
            'memory_id': promoted_id,
            'plane': to_plane,
            'origin': copy.deepcopy(source['origin']),
            'content_ref': copy.deepcopy(source['content_ref']),
            'recorded_at': recorded_at if recorded_at is not None else moment,
            'scope': dict(scope),
            'confidence': source['confidence'],
            'integrity': copy.deepcopy(source['integrity']),
            'ttl_seconds': source['ttl_seconds'] if ttl_seconds is None else ttl_seconds,
            'expires_at': None,
            'read_permissions': [dict(entry) for entry in read_permissions],
            'update_policy': update_policy or source['update_policy'],
            'tenant_id': self.tenant_id,
            'cross_plane_reads': CROSS_PLANE_READS,
            'cross_tenant_reads': CROSS_TENANT_READS,
            'contaminates': CONTAMINATES,
        }
        stored = self.accept(promoted, now=now)
        return stored, decision

    def export_records(self, policy, *, plane, role_ref, destination='external_handoff',
                       approval=None, now=None):
        """Exportacion gobernada. El plano personal nunca sale, en ningun destino."""
        if destination not in EXPORT_DESTINATIONS:
            raise MemoryGovernanceError('invalid_request', 'destination debe pertenecer a %s.'
                                        % (EXPORT_DESTINATIONS,))
        if plane not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.' % (PLANES,))
        if plane == PERSONAL_PLANE:
            raise MemoryGovernanceError('personal_plane_not_exportable', (
                'El plano personal no se exporta nunca: ni en el paquete ni por hand-off externo '
                '(regla de exclusion personal del contrato v1).'))
        if 'memories' in self._boundary.never_exported_domains() and destination == 'package':
            raise MemoryGovernanceError('domain_not_exportable', (
                "El dominio 'memories' del inquilino %s nunca viaja en el paquete ni en el ZIP del "
                'export DSH.' % self.tenant_id))
        decision = _policy_decision(policy, self.action_for(policy, 'send_message_out', plane,
                                                            '%s-export' % plane),
                                    approval=approval, now=now)
        _require_allow(decision, 'La exportacion de memoria del plano %s' % plane)
        exported = []
        for view in self.list_plane(plane, role_ref=role_ref, now=now):
            exported.append(self.read(view['memory_id'], plane=plane, role_ref=role_ref, now=now))
        return tuple(exported), decision


__all__ = ['MEMORY_RECORD_VERSION', 'MEMORY_VERSION_FIELD', 'PLANES', 'EXECUTION_PLANE',
           'PROJECT_PLANE', 'ORGANIZATIONAL_PLANE', 'PERSONAL_PLANE', 'SOURCE_KINDS',
           'CONTENT_KINDS', 'SCOPE_KINDS', 'UPDATE_POLICIES', 'HASH_ALGORITHM', 'PLANE_SCOPES',
           'PROMOTION_ROUTES', 'EXPORT_DESTINATIONS', 'EXECUTION_LIFETIME', 'PROJECT_INHERITANCE',
           'PERSONAL_EXCLUSION', 'READ_RULE', 'CONTAMINATES', 'CROSS_PLANE_READS',
           'CROSS_TENANT_READS', 'MAX_CONTENT_CHARS', 'RECORD_FIELDS', 'MEMORY_ERROR_CODES',
           'PROHIBITED_FIELDS', 'PROHIBITED_FIELDS_SOURCE', 'DOMAINS', 'MemoryGovernanceError',
           'MemoryStore', 'validate_record', 'build_record', 'memory_hash', 'parse_instant',
           'format_instant', 'add_seconds', 'utc_now', 'canonical', 'sha256_text']
