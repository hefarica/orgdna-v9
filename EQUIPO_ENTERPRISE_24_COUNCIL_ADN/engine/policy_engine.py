"""Policy Engine v1 (flujo I3): politica central por organizacion, versionada y con hash.

Contrato consumido: `docs/plataforma/policy.schema.json` (PolicyDecision v1, congelado en
R0, huella c6026c70690115c7e37ac0d080510f6f19b36cabc76c89701e7d5443bf54118e).
Modulo INERTE: evalua una accion propuesta y devuelve datos puros
(`allow` | `deny` | `require_human_approval`). Nunca ejecuta la accion evaluada, nunca
consume una aprobacion, no abre red, no lee ni escribe ficheros y no lanza subprocesos.

Rutas de salida (no existe ruta silenciosa):
  1. Decision (`allow` | `deny` | `require_human_approval`) para toda accion conforme al
     contrato v1, siempre con `reason` no vacia.
  2. `PolicyError('prohibited_field')` si la accion, la aprobacion o la politica contienen
     un nombre de credencial o de consentimiento: el guard reutiliza la lista literal de
     `engine/project_store.py:19` y el contenido rechazado no se ecoa en ninguna decision.
  3. `PolicyError` con codigo `unsupported_version`, `invalid_policy`, `invalid_action` o
     `invalid_request` cuando la forma congelada del contrato no se cumple.

Lecturas del contrato congelado que este modulo implementa:
  * `decision` es total y `gate` es obligatorio y no nulo cuando la decision es
    `require_human_approval`;
  * las ocho puertas humanas (`secrets`, `spend`, `connectors`, `write`, `install`, `push`,
    `merge`, `deploy`) tienen salida por defecto `require_human_approval`;
  * `limits.network_allowed` nunca es `true` y `side_effects_performed` siempre es `false`;
  * una accion que levanta una puerta solo llega a `allow` con un registro de aprobacion
    cuyo `scope_hash` coincida con `action.scope_hash`;
  * una aprobacion de un solo uso ya consumida se deniega; el motor la detecta, no la
    consume: recibe los alcances consumidos como dato de entrada.

Una accion que no levanta ninguna puerta del conjunto obligatorio (por ejemplo `read_repo`
o `run_tests`) se autoriza sin aprobacion: `gate: null` y `approval: null`.

  * La anotacion `$defs.mandatory_gates` del contrato limita la exigencia de aprobacion
    humana a esas ocho puertas. `allow` sin aprobacion solo se emite para tipos de accion que
    no levantan ninguna puerta y que ademas pasan los limites de acceso, coste y autonomia.
  * El segundo `allOf` del esquema (`if decision == allow then approval: object`), leido al pie
    de la letra, exigiria una aprobacion registrada en toda decision `allow`. Combinado con la
    regla `gate` obligatorio en `require_human_approval`, una accion de solo lectura no tendria
    salida valida: ni `allow` sin aprobacion, ni `require_human_approval` sin puerta, dejando
    solo `deny`, que el contrato no declara para lectura. Este modulo implementa la lectura de
    `mandatory_gates` y la hace verificable: el 100 % de las decisiones `allow` de las ocho
    puertas llevan `gate` no nulo y `approval` con el mismo `scope_hash` de la accion.
  * Un operador que prefiera la lectura literal cierra esos tipos con `denied_action_kinds`:
    la decision pasa a `deny`, que es la unica salida conforme al pie de la letra.
  * Resolver la ambiguedad exige una version nueva del contrato (seccion 10 de
    `docs/PLATAFORMA_CONTRATOS_V1.md`): un contrato v1 no se edita en caliente.

Verificacion independiente contra el esquema congelado (subconjunto de JSON Schema escrito
aparte de `validate_decision`): 12/14 rutas conformes, y las 2 no conformes son exactamente
los `allow` sin puerta descritos arriba.

Aprobaciones declarativas (decision D-R0-5): `approver_role` es un rol declarado por el
operador. Este motor NO afirma identidad autenticada, firma ni verificacion criptografica,
y deniega cualquier registro que declare autenticacion.

Techo de autonomia (decision D-R0-4): por defecto `observe`; ninguna ruta de este modulo lo
eleva ni lo infiere del objetivo declarado del proyecto.

Binding politica <-> aprobacion: `Policy.scope_hash()` deriva el alcance exacto del binomio
(politica vigente, accion). Modificar cualquier valor de la politica cambia `policy_hash`,
cambia el alcance esperado y deja sin valor la aprobacion anterior.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone

try:  # importacion como paquete del motor
    from .project_store import FORBIDDEN_FIELDS as ENGINE_FORBIDDEN_FIELDS
except ImportError:  # raiz de la suite en sys.path
    from project_store import FORBIDDEN_FIELDS as ENGINE_FORBIDDEN_FIELDS

POLICY_CONTRACT_VERSION = '1'
PROHIBITED_FIELDS_SOURCE = 'engine/project_store.py:19'
PROHIBITED_FIELDS = tuple(sorted(ENGINE_FORBIDDEN_FIELDS))
INERT_BY_DEFAULT = True
SIDE_EFFECTS_PERFORMED = False

DECISION_ALLOW = 'allow'
DECISION_DENY = 'deny'
DECISION_REQUIRE = 'require_human_approval'
DECISION_OUTCOMES = (DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE)

GATES = ('secrets', 'spend', 'connectors', 'write', 'install', 'push', 'merge', 'deploy')
GATE_DEFAULT_OUTCOME = DECISION_REQUIRE

ACTION_KINDS = ('read_repo', 'write_file', 'run_tests', 'call_provider', 'install_package',
                'open_connector', 'spend_money', 'store_memory', 'push', 'merge', 'deploy',
                'send_message_out')

AUTONOMY_LEVELS = ('observe', 'propose', 'prepare', 'execute-approved')
AUTONOMY_CEILING_DEFAULT = 'observe'

APPROVAL_IDENTITY_KIND = 'declarative_role'
APPROVER_AUTHENTICATION = 'not_verified'
APPROVAL_AUTHENTICATION_CLAIM = 'ninguna; el rol del aprobador es declarativo y no verificado'
APPROVAL_FIELDS = ('gate', 'approver_role', 'approved_at', 'scope_hash', 'one_shot')

DECISION_FIELDS = ('policy_contract_version', 'policy_id', 'policy_revision', 'action',
                   'decision', 'reason', 'gate', 'matched_rules', 'limits',
                   'side_effects_performed', 'evaluated_at')
DECISION_OPTIONAL_FIELDS = ('approval',)
LIMIT_FIELDS = ('write_allowed', 'network_allowed', 'spend_usd_max', 'autonomy_ceiling',
                'approvals_required')
ACTION_FIELDS = ('action_kind', 'target', 'scope_hash', 'idempotency_key')

POLICY_DATA_FIELDS = ('policy_contract_version', 'policy_id', 'policy_revision',
                      'organization_id', 'created_at', 'inert_by_default', 'limits',
                      'gate_defaults', 'action_gates', 'denied_action_kinds',
                      'target_deny_patterns')

#: Puertas que levanta cada tipo de accion del vocabulario congelado.
DEFAULT_ACTION_GATES = {
    'read_repo': (),
    'run_tests': (),
    'write_file': ('write',),
    'store_memory': ('write',),
    'install_package': ('install',),
    'call_provider': ('secrets', 'spend', 'connectors'),
    'open_connector': ('connectors',),
    'spend_money': ('spend',),
    'send_message_out': ('connectors',),
    'push': ('push',),
    'merge': ('merge',),
    'deploy': ('deploy',),
}

#: Limites de acceso por defecto: rutas fuera del alcance declarado del proyecto.
DEFAULT_TARGET_DENY_PATTERNS = (
    {'rule_id': 'access.parent_traversal', 'pattern': r'(^|[\\/])\.\.([\\/]|$)'},
    {'rule_id': 'access.drive_absolute', 'pattern': r'^[A-Za-z]:[\\/]'},
    {'rule_id': 'access.system_absolute', 'pattern': r'^/(etc|proc|sys|dev|root|boot)(/|$)'},
)

#: Nombres que declaran autenticacion, firma o verificacion del aprobador (D-R0-5).
AUTHENTICATION_CLAIM_KEYS = ('authenticated', 'authentication', 'attestation', 'certificate',
                             'cert', 'hmac', 'jwt', 'nonce', 'notarized', 'proof', 'seal',
                             'signature', 'signed', 'signatureverified', 'verified',
                             'verification', 'verificationstatus', 'identityverified',
                             'publickey', 'keyid', 'fingerprint', 'token')

_POLICY_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,63}$')
_RULE_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,63}$')
_ORG_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,40}$')
_SCOPE_HASH_RE = re.compile(r'^[0-9a-f]{64}$')
_INSTANT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
_IDEMPOTENCY_RE = re.compile(r'^[A-Za-z0-9._:-]{8,128}$')
_CAMEL_RE = re.compile(r'(?<!^)(?=[A-Z])')
_NON_ALNUM_RE = re.compile(r'[^a-z0-9]')
_FORBIDDEN_COMPACT = frozenset(_NON_ALNUM_RE.sub('', name) for name in ENGINE_FORBIDDEN_FIELDS)
_CLAIM_COMPACT = frozenset(AUTHENTICATION_CLAIM_KEYS)
_REASON_MAX = 600


class PolicyError(ValueError):
    """Rechazo tipado: la solicitud no cumple la forma congelada del contrato v1."""

    def __init__(self, code, message):
        super().__init__('%s: %s' % (code, message))
        self.code = code


def _utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _deep_merge(base, extra):
    result = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _rule(rule_id, outcome, limit_ref=None):
    return {'rule_id': rule_id, 'outcome': outcome, 'limit_ref': limit_ref}


def _compact_key(key):
    return _NON_ALNUM_RE.sub('', str(key).lower())


def _normalized_key(key):
    return _CAMEL_RE.sub('_', str(key)).lower().replace('-', '_')


def find_prohibited_fields(value, path='$'):
    """Rutas con nombre de credencial o consentimiento (guard de engine/project_store.py:19).

    Reutiliza la lista literal del motor y las dos comparaciones de su guard: nombre
    normalizado (camelCase->snake_case, '-'->'_') y variante sin caracteres no alfanumericos.
    """
    hits = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = '%s.%s' % (path, key)
            if _normalized_key(key) in ENGINE_FORBIDDEN_FIELDS or _compact_key(key) in _FORBIDDEN_COMPACT:
                hits.append(child)
            hits.extend(find_prohibited_fields(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(find_prohibited_fields(item, '%s[%d]' % (path, index)))
    return hits


def find_authentication_claims(value, path='$'):
    """Rutas que declaran autenticacion, firma o verificacion del aprobador (D-R0-5)."""
    hits = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = '%s.%s' % (path, key)
            if _compact_key(key) in _CLAIM_COMPACT:
                hits.append(child)
            hits.extend(find_authentication_claims(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(find_authentication_claims(item, '%s[%d]' % (path, index)))
    return hits


def _reject_prohibited(payload):
    hits = find_prohibited_fields(payload)
    if hits:
        raise PolicyError('prohibited_field', (
            'La solicitud contiene campos con forma de credencial o consentimiento (%s); '
            'el motor no los admite ni los registra. Guard reutilizado de %s.'
            % (', '.join(sorted(hits)), PROHIBITED_FIELDS_SOURCE)))


def _validated_action(action):
    if not isinstance(action, dict):
        raise PolicyError('invalid_action', (
            'La accion propuesta debe ser un objeto JSON conforme a $defs.action del '
            'contrato v1.'))
    unknown = sorted(str(key) for key in action if key not in ACTION_FIELDS)
    if unknown:
        raise PolicyError('invalid_action', (
            'Campos no admitidos en la accion: %s. El contrato v1 no admite campos '
            'adicionales.' % ', '.join(unknown)))
    kind = action.get('action_kind')
    if kind not in ACTION_KINDS:
        raise PolicyError('invalid_action', (
            "action_kind no pertenece al vocabulario congelado v1: %r." % (kind,)))
    target = action.get('target')
    if not isinstance(target, str) or not 1 <= len(target) <= 400:
        raise PolicyError('invalid_action', (
            'target debe ser texto de 1 a 400 caracteres (contrato v1).'))
    scope_hash = action.get('scope_hash')
    if scope_hash is not None and (not isinstance(scope_hash, str) or not _SCOPE_HASH_RE.match(scope_hash)):
        raise PolicyError('invalid_action', (
            'scope_hash debe ser 64 caracteres hexadecimales en minuscula (contrato v1).'))
    idempotency_key = action.get('idempotency_key')
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.match(idempotency_key)):
        raise PolicyError('invalid_action', (
            'idempotency_key no cumple el patron del contrato v1 (8..128 de [A-Za-z0-9._:-]).'))
    return copy.deepcopy(action)


def _validated_instant(value):
    if value is None:
        return _utc_now()
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        raise PolicyError('invalid_request', (
            'now debe ser un instante ISO-8601 UTC terminado en Z (patron del contrato v1).'))
    return value


def _validated_cost(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PolicyError('invalid_request', (
            'declared_cost_usd debe ser un numero no negativo o None.'))
    return float(value)


def _validated_autonomy_level(value):
    if value is None:
        return None
    if value not in AUTONOMY_LEVELS:
        raise PolicyError('invalid_request', (
            'autonomy_level debe pertenecer a %s.' % (AUTONOMY_LEVELS,)))
    return value


def _validated_consumed(value):
    if value is None:
        return frozenset()
    if isinstance(value, str):
        value = (value,)
    hashes = set()
    for item in value:
        if not isinstance(item, str) or not _SCOPE_HASH_RE.match(item):
            raise PolicyError('invalid_request', (
                'consumed_scope_hashes solo admite alcances de 64 hex en minuscula.'))
        hashes.add(item)
    return frozenset(hashes)


def _approval_problems(approval):
    """Defectos de forma de un registro de aprobacion (contrato $defs.approval_record)."""
    problems = []
    if not isinstance(approval, dict):
        return ['el registro de aprobacion no es un objeto JSON']
    unknown = sorted(str(key) for key in approval if key not in APPROVAL_FIELDS)
    if unknown:
        problems.append('campos no admitidos en la aprobacion: %s' % ', '.join(unknown))
    if approval.get('gate') not in GATES:
        problems.append('gate ausente o fuera de las ocho puertas obligatorias')
    role = approval.get('approver_role')
    if not isinstance(role, str) or not role.strip() or len(role) > 120 or any(ord(c) < 32 for c in role):
        problems.append('approver_role debe ser un rol declarativo de 1 a 120 caracteres legibles')
    approved_at = approval.get('approved_at')
    if not isinstance(approved_at, str) or not _INSTANT_RE.match(approved_at):
        problems.append('approved_at debe ser un instante ISO-8601 UTC terminado en Z')
    scope_hash = approval.get('scope_hash')
    if not isinstance(scope_hash, str) or not _SCOPE_HASH_RE.match(scope_hash):
        problems.append('scope_hash debe ser 64 caracteres hexadecimales en minuscula')
    if approval.get('one_shot') is not True:
        problems.append('one_shot debe ser true: la aprobacion es de un solo uso')
    return problems


def _validated_policy_data(data):
    if not isinstance(data, dict):
        raise PolicyError('invalid_policy', 'La politica debe ser un objeto JSON.')
    version = data.get('policy_contract_version')
    if version != POLICY_CONTRACT_VERSION:
        raise PolicyError('unsupported_version', (
            'La politica declara policy_contract_version=%r; este motor solo soporta %r y no '
            'degrada a otra interpretacion.' % (version, POLICY_CONTRACT_VERSION)))
    unknown = sorted(str(key) for key in data if key not in POLICY_DATA_FIELDS)
    _reject_prohibited(data)
    if unknown:
        raise PolicyError('invalid_policy', (
            'Campos no admitidos en los datos de la politica: %s.' % ', '.join(unknown)))
    problems = []
    policy_id = data.get('policy_id')
    if not isinstance(policy_id, str) or not _POLICY_ID_RE.match(policy_id):
        problems.append('policy_id no cumple el patron del contrato v1')
    revision = data.get('policy_revision')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        problems.append('policy_revision debe ser un entero positivo')
    organization_id = data.get('organization_id')
    if not isinstance(organization_id, str) or not _ORG_ID_RE.match(organization_id):
        problems.append('organization_id debe ser 2..41 caracteres [a-z0-9._-]')
    created_at = data.get('created_at')
    if not isinstance(created_at, str) or not _INSTANT_RE.match(created_at):
        problems.append('created_at debe ser un instante ISO-8601 UTC terminado en Z')
    if data.get('inert_by_default') is not True:
        problems.append('la politica debe declarar inert_by_default=true')
    limits = data.get('limits')
    if not isinstance(limits, dict):
        problems.append('limits debe ser un objeto del contrato v1')
    else:
        unknown_limits = sorted(str(key) for key in limits if key not in LIMIT_FIELDS)
        if unknown_limits:
            problems.append('campos no admitidos en limits: %s' % ', '.join(unknown_limits))
        if not isinstance(limits.get('write_allowed'), bool):
            problems.append('limits.write_allowed debe ser booleano')
        if limits.get('network_allowed') is not False:
            problems.append('limits.network_allowed es const false en el contrato v1')
        spend = limits.get('spend_usd_max')
        if spend is not None and (isinstance(spend, bool) or not isinstance(spend, (int, float)) or spend < 0):
            problems.append('limits.spend_usd_max debe ser un numero no negativo')
        if limits.get('autonomy_ceiling') not in AUTONOMY_LEVELS:
            problems.append('limits.autonomy_ceiling debe pertenecer a %s' % (AUTONOMY_LEVELS,))
        approvals = limits.get('approvals_required')
        if not isinstance(approvals, list) or any(gate not in GATES for gate in approvals) or len(set(approvals)) != len(approvals):
            problems.append('limits.approvals_required debe ser una lista sin repetidos de las ocho puertas')
    gate_defaults = data.get('gate_defaults')
    if not isinstance(gate_defaults, dict) or set(gate_defaults) != set(GATES):
        problems.append('gate_defaults debe declarar exactamente las ocho puertas')
    elif any(gate_defaults[gate] not in DECISION_OUTCOMES for gate in GATES):
        problems.append('gate_defaults solo admite %s' % (DECISION_OUTCOMES,))
    action_gates = data.get('action_gates')
    if not isinstance(action_gates, dict) or set(action_gates) != set(ACTION_KINDS):
        problems.append('action_gates debe declarar exactamente los %d tipos de accion v1' % len(ACTION_KINDS))
    else:
        for kind in ACTION_KINDS:
            gates = action_gates[kind]
            if not isinstance(gates, list) or any(gate not in GATES for gate in gates) or len(set(gates)) != len(gates):
                problems.append('action_gates[%s] debe ser una lista sin repetidos de las ocho puertas' % kind)
    denied = data.get('denied_action_kinds')
    if not isinstance(denied, list) or any(kind not in ACTION_KINDS for kind in denied) or len(set(denied)) != len(denied):
        problems.append('denied_action_kinds debe ser una lista sin repetidos del vocabulario v1')
    patterns = data.get('target_deny_patterns')
    if not isinstance(patterns, list):
        problems.append('target_deny_patterns debe ser una lista')
    else:
        for entry in patterns:
            if not isinstance(entry, dict) or set(entry) != {'rule_id', 'pattern'}:
                problems.append('cada patron de acceso requiere exactamente rule_id y pattern')
                continue
            if not isinstance(entry['rule_id'], str) or not _RULE_ID_RE.match(entry['rule_id']):
                problems.append('rule_id de acceso no cumple el patron de matched_rules')
            try:
                re.compile(entry['pattern'])
            except (re.error, TypeError):
                problems.append('patron de acceso no compilable: %r' % (entry['pattern'],))
    if problems:
        raise PolicyError('invalid_policy', ' '.join(problems))
    return copy.deepcopy({key: data[key] for key in POLICY_DATA_FIELDS})


def _normalized_organization_id(value):
    if not isinstance(value, str):
        raise PolicyError('invalid_policy', 'organization_id debe ser texto.')
    normalized = value.strip().lower()
    if not _ORG_ID_RE.match(normalized):
        raise PolicyError('invalid_policy', (
            'organization_id no admisible: %r. Use de 2 a 41 caracteres [a-z0-9._-].' % (value,)))
    return normalized


def _coerce_policy(policy):
    if isinstance(policy, Policy):
        return policy
    if isinstance(policy, dict):
        return Policy.from_dict(policy)
    raise PolicyError('invalid_policy', (
        'Se esperaba una instancia Policy o los datos de una politica v1.'))


class Policy:
    """Politica central por organizacion: datos versionados con hash reproducible.

    El objeto es inmutable en la practica: los datos se copian en la construccion y
    `as_dict()` devuelve una copia. Cualquier cambio exige una instancia nueva
    (`with_overrides`), que sube la revision y cambia el hash.
    """

    def __init__(self, data):
        self._data = _validated_policy_data(data)
        self._target_patterns = tuple(
            (entry['rule_id'], re.compile(entry['pattern']))
            for entry in self._data['target_deny_patterns'])

    @classmethod
    def default(cls, organization_id='orgdna-platform', *, revision=1, created_at=None,
                overrides=None, policy_id=None):
        """Politica v1 por defecto para una organizacion: todo cerrado y con ocho puertas."""
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise PolicyError('invalid_policy', 'policy_revision debe ser un entero positivo.')
        organization = _normalized_organization_id(organization_id)
        data = {
            'policy_contract_version': POLICY_CONTRACT_VERSION,
            'policy_id': policy_id if policy_id is not None else 'orgdna.platform.' + organization,
            'policy_revision': revision,
            'organization_id': organization,
            'created_at': created_at if created_at is not None else _utc_now(),
            'inert_by_default': True,
            'limits': {
                'write_allowed': False,
                'network_allowed': False,
                'spend_usd_max': 0.0,
                'autonomy_ceiling': AUTONOMY_CEILING_DEFAULT,
                'approvals_required': list(GATES),
            },
            'gate_defaults': {gate: GATE_DEFAULT_OUTCOME for gate in GATES},
            'action_gates': {kind: list(gates) for kind, gates in DEFAULT_ACTION_GATES.items()},
            'denied_action_kinds': [],
            'target_deny_patterns': [dict(entry) for entry in DEFAULT_TARGET_DENY_PATTERNS],
        }
        if overrides:
            data = _deep_merge(data, overrides)
        return cls(data)

    @classmethod
    def from_dict(cls, data):
        return cls(data)

    def as_dict(self):
        return copy.deepcopy(self._data)

    @property
    def policy_hash(self):
        return _sha256_text(_canonical(self._data))

    @property
    def policy_id(self):
        return self._data['policy_id']

    @property
    def policy_revision(self):
        return self._data['policy_revision']

    @property
    def organization_id(self):
        return self._data['organization_id']

    @property
    def created_at(self):
        return self._data['created_at']

    @property
    def limits(self):
        limits = self._data['limits']
        result = {
            'write_allowed': limits['write_allowed'],
            'network_allowed': False,
            'autonomy_ceiling': limits['autonomy_ceiling'],
            'approvals_required': list(limits['approvals_required']),
        }
        if 'spend_usd_max' in limits:
            result['spend_usd_max'] = limits['spend_usd_max']
        return result

    @property
    def gate_defaults(self):
        return dict(self._data['gate_defaults'])

    @property
    def denied_action_kinds(self):
        return tuple(self._data['denied_action_kinds'])

    @property
    def spend_usd_max(self):
        """Maximo declarado por la politica. Su ausencia equivale a 0: no hay gasto autorizado."""
        return self._data['limits'].get('spend_usd_max', 0.0)

    @property
    def autonomy_ceiling(self):
        return self._data['limits']['autonomy_ceiling']

    def gate_default_outcome(self, gate):
        if gate not in GATES:
            raise PolicyError('invalid_policy', 'Puerta desconocida: %r.' % (gate,))
        return self._data['gate_defaults'][gate]

    def gates_for(self, action_kind, requires_secret_material=False):
        """Puertas efectivamente levantadas, en el orden congelado de `GATES`.

        Una puerta candidata se levanta si esta en `limits.approvals_required` o si su limite
        duro esta cerrado (`write_allowed` en false para `write`; `network_allowed` en false
        para `connectors`, valor que el contrato fija como constante).
        """
        if action_kind not in ACTION_KINDS:
            raise PolicyError('invalid_action', (
                "action_kind no pertenece al vocabulario congelado v1: %r." % (action_kind,)))
        candidates = list(self._data['action_gates'][action_kind])
        if requires_secret_material and 'secrets' not in candidates:
            candidates.append('secrets')
        levied = []
        for gate in GATES:
            if gate not in candidates:
                continue
            if gate in self._data['limits']['approvals_required'] or self._gate_forced_closed(gate):
                levied.append(gate)
        return tuple(levied)

    def _gate_forced_closed(self, gate):
        if gate == 'write':
            return self._data['limits']['write_allowed'] is False
        if gate == 'connectors':
            return self._data['limits']['network_allowed'] is False
        return False

    def default_outcome(self, action_kind, requires_secret_material=False):
        """Salida declarada por la politica para ese tipo de accion, sin aprobacion."""
        gates = self.gates_for(action_kind, requires_secret_material=requires_secret_material)
        if not gates:
            return DECISION_ALLOW
        return self.gate_default_outcome(gates[0])

    def scope_hash(self, action):
        """Alcance exacto del binomio (politica vigente, accion), 64 hex en minuscula."""
        validated = _validated_action(action)
        payload = {
            'policy_id': self.policy_id,
            'policy_revision': self.policy_revision,
            'policy_hash': self.policy_hash,
            'action': {
                'action_kind': validated['action_kind'],
                'target': validated['target'],
                'idempotency_key': validated.get('idempotency_key'),
            },
        }
        return _sha256_text(_canonical(payload))

    def with_overrides(self, overrides, *, revision=None):
        """Politica nueva: sube la revision, cambia el hash e invalida aprobaciones previas."""
        if not isinstance(overrides, dict) or not overrides:
            raise PolicyError('invalid_policy', 'with_overrides exige un objeto de cambios no vacio.')
        data = _deep_merge(self._data, overrides)
        if revision is None:
            data['policy_revision'] = self.policy_revision + 1
        else:
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise PolicyError('invalid_policy', 'revision debe ser un entero positivo.')
            data['policy_revision'] = revision
        return Policy(data)

    def __repr__(self):
        return 'Policy(%s@%s hash=%s)' % (self.policy_id, self.policy_revision, self.policy_hash[:12])


def default_policy(organization_id='orgdna-platform', *, revision=1, created_at=None,
                   overrides=None, policy_id=None):
    """Atajo de `Policy.default` para consumidores del motor."""
    return Policy.default(organization_id, revision=revision, created_at=created_at,
                          overrides=overrides, policy_id=policy_id)


def _decision(policy, action, decision, reason, gate, matched_rules, approval, evaluated_at):
    text = str(reason).strip() or 'Sin razon especifica: una decision no puede emitirse sin motivo.'
    return {
        'policy_contract_version': POLICY_CONTRACT_VERSION,
        'policy_id': policy.policy_id,
        'policy_revision': policy.policy_revision,
        'action': copy.deepcopy(action),
        'decision': decision,
        'reason': text[:_REASON_MAX],
        'gate': gate,
        'matched_rules': [dict(rule) for rule in matched_rules],
        'limits': policy.limits,
        'approval': copy.deepcopy(approval) if approval is not None else None,
        'side_effects_performed': SIDE_EFFECTS_PERFORMED,
        'evaluated_at': evaluated_at,
    }


def evaluate(policy, action, *, approval=None, consumed_scope_hashes=(), declared_cost_usd=None,
             requires_secret_material=False, autonomy_level=None, now=None):
    """Evalua una accion propuesta y devuelve la decision del contrato PolicyDecision v1.

    Orden de evaluacion, determinista: (1) tipos denegados por la politica, (2) limites de
    acceso sobre el destino, (3) alcance declarado no vigente, (4) coste sobre el maximo,
    (5) autonomia declarada sobre el techo, (6) puertas humanas.

    `approval` es un registro declarativo ya concedido por una persona; el motor lo valida y,
    si procede, lo ecoa, pero nunca lo consume. `consumed_scope_hashes` declara los alcances
    ya consumidos por el runtime: si el registro presentado figura ahi, la decision es `deny`.

    La funcion no ejecuta la accion ni produce ningun efecto: no hay red, ficheros ni
    subprocesos, y `side_effects_performed` es siempre `false`.
    """
    policy = _coerce_policy(policy)
    _reject_prohibited({'action': action, 'approval': approval})
    validated_action = _validated_action(action)
    provided_approval = copy.deepcopy(approval)
    evaluated_at = _validated_instant(now)
    consumed = _validated_consumed(consumed_scope_hashes)
    cost = _validated_cost(declared_cost_usd)
    if not isinstance(requires_secret_material, bool):
        raise PolicyError('invalid_request', 'requires_secret_material debe ser booleano.')
    level = _validated_autonomy_level(autonomy_level)

    kind = validated_action['action_kind']
    target = validated_action['target']
    head = 'politica %s@%s' % (policy.policy_id, policy.policy_revision)
    expected_scope = policy.scope_hash(validated_action)
    declared_scope = validated_action.get('scope_hash')

    # (1) limites duros: cierran la puerta antes de cualquier aprobacion
    if kind in policy.denied_action_kinds:
        rules = [_rule('deny.kind.' + kind, DECISION_DENY, 'policy.denied_action_kinds')]
        reason = ("El tipo de accion '%s' figura en la lista denegada de la %s: no admite "
                  'aprobacion en esta revision.' % (kind, head))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    # (2) limites de acceso sobre el destino
    for rule_id, pattern in policy._target_patterns:
        if pattern.search(target):
            rules = [_rule(rule_id, DECISION_DENY, 'policy.target_deny_patterns')]
            reason = ("El destino '%s' queda fuera de los limites de acceso de la %s: coincide "
                      'con el patron de acceso %s.' % (target, head, rule_id))
            return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    # (3) el alcance declarado pertenece al binding politica <-> aprobacion
    if declared_scope is not None and declared_scope != expected_scope:
        rules = [_rule('deny.scope.stale', DECISION_DENY, 'policy.policy_hash')]
        reason = ('El scope_hash declarado (%s) no corresponde al alcance de esta accion bajo la '
                  '%s, cuyo alcance vigente es %s: una aprobacion de un alcance anterior no es '
                  'reutilizable.' % (declared_scope, head, expected_scope))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    # (4) coste declarado sobre el maximo de la politica
    if cost is not None and cost > policy.spend_usd_max:
        rules = [_rule('deny.cost.over_cap', DECISION_DENY, 'limits.spend_usd_max')]
        reason = ('El coste declarado (%s USD) supera el maximo de la %s (%s USD); una aprobacion '
                  'no eleva ese limite.' % (cost, head, policy.spend_usd_max))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    # (5) autonomia declarada sobre el techo (D-R0-4): el motor nunca eleva la autonomia
    if level is not None and AUTONOMY_LEVELS.index(level) > AUTONOMY_LEVELS.index(policy.autonomy_ceiling):
        rules = [_rule('deny.autonomy.above_ceiling', DECISION_DENY, 'limits.autonomy_ceiling')]
        reason = ("El nivel de autonomia declarado ('%s') supera el techo de la %s ('%s'); este "
                  'motor no eleva el techo ni lo infiere del objetivo del proyecto.'
                  % (level, head, policy.autonomy_ceiling))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    # (6) puertas humanas
    gates = policy.gates_for(kind, requires_secret_material=requires_secret_material)
    if not gates:
        rules = [_rule('default.open', DECISION_ALLOW, 'policy.action_gates')]
        reason = ("La %s no levanta ninguna puerta humana para '%s': la accion no esta prohibida y "
                  'no hay aprobacion que registrar. El motor no ejecuta nada: la ejecucion es un '
                  'paso separado (side_effects_performed=false).' % (head, kind))
        return _decision(policy, validated_action, DECISION_ALLOW, reason, None, rules, None, evaluated_at)

    primary = gates[0]
    gate_outcome = policy.gate_default_outcome(primary)
    rules = [_rule('gate.' + primary, gate_outcome, 'policy.gate_defaults.' + primary)]

    if gate_outcome == DECISION_DENY:
        reason = ("La puerta '%s' de la %s esta cerrada por la politica: la accion '%s' se deniega "
                  'sin opcion de aprobacion en esta revision.' % (primary, head, kind))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    if gate_outcome == DECISION_ALLOW:
        reason = ("La %s declara salida por defecto 'allow' para la puerta '%s': no se registra "
                  'ninguna aprobacion y el motor no ejecuta nada.' % (head, primary))
        return _decision(policy, validated_action, DECISION_ALLOW, reason, None, rules, None, evaluated_at)

    if provided_approval is None:
        rules.append(_rule('approval.missing', DECISION_REQUIRE, 'policy.approvals_required'))
        reason = ("La accion '%s' sobre '%s' levanta la puerta humana '%s' (%s) y no hay aprobacion "
                  'registrada para el alcance vigente %s.'
                  % (kind, target, primary, ', '.join(gates), expected_scope))
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    if not isinstance(provided_approval, dict):
        rules.append(_rule('approval.invalid', DECISION_REQUIRE, None))
        reason = ("El registro de aprobacion presentado para la puerta '%s' no es un objeto JSON del "
                  'contrato v1, asi que no se honra y la puerta sigue exigiendo aprobacion humana.'
                  % primary)
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    claims = find_authentication_claims(provided_approval, 'approval')
    if claims:
        rules.append(_rule('deny.approval.authentication_claim', DECISION_DENY, None))
        reason = ('El registro de aprobacion declara autenticacion (%s), pero la identidad del '
                  'aprobador es un rol declarativo no verificado (decision D-R0-5): el motor no '
                  'admite garantias de autenticacion y deniega la solicitud.'
                  % ', '.join(sorted(claims)))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    problems = _approval_problems(provided_approval)
    if problems:
        rules.append(_rule('approval.invalid', DECISION_REQUIRE, None))
        reason = ('El registro de aprobacion no cumple el contrato v1 (%s): no se honra y la puerta '
                  "'%s' sigue exigiendo aprobacion humana." % ('; '.join(problems), primary))
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    if provided_approval['scope_hash'] in consumed:
        rules.append(_rule('deny.approval.consumed', DECISION_DENY, None))
        reason = ("La aprobacion de la puerta '%s' para el alcance %s ya fue consumida (one_shot=true); "
                  'el motor no reutiliza aprobaciones y no la consume por su cuenta.'
                  % (provided_approval['gate'], provided_approval['scope_hash']))
        return _decision(policy, validated_action, DECISION_DENY, reason, None, rules, None, evaluated_at)

    if provided_approval['gate'] != primary:
        rules.append(_rule('approval.gate_mismatch', DECISION_REQUIRE, None))
        reason = ("La aprobacion corresponde a la puerta '%s' y la accion levanta '%s': la puerta "
                  "'%s' sigue exigiendo aprobacion humana para el alcance vigente %s."
                  % (provided_approval['gate'], primary, primary, expected_scope))
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    if declared_scope is None:
        rules.append(_rule('approval.scope_missing', DECISION_REQUIRE, None))
        reason = ('La accion no declara scope_hash, asi que la aprobacion presentada no puede atarse a '
                  'ella: declara el alcance vigente %s y la puerta %s lo revisara de nuevo.'
                  % (expected_scope, primary))
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    if provided_approval['scope_hash'] != expected_scope:
        rules.append(_rule('approval.scope_mismatch', DECISION_REQUIRE, None))
        reason = ('El scope_hash de la aprobacion (%s) no coincide con el alcance vigente de la accion '
                  '(%s) bajo la %s: una aprobacion de otro alcance no autoriza esta accion.'
                  % (provided_approval['scope_hash'], expected_scope, head))
        return _decision(policy, validated_action, DECISION_REQUIRE, reason, primary, rules, None, evaluated_at)

    rules.append(_rule('approval.valid', DECISION_ALLOW, 'policy.approvals_required'))
    reason = ("Aprobacion declarativa valida (rol '%s', sin autenticacion verificada) para la puerta "
              "'%s' y el alcance %s: la accion '%s' no esta prohibida por la %s. El motor no ejecuta "
              'nada (side_effects_performed=false).'
              % (provided_approval['approver_role'], primary, expected_scope, kind, head))
    return _decision(policy, validated_action, DECISION_ALLOW, reason, primary, rules, provided_approval,
                     evaluated_at)


def validate_decision(decision):
    """Comprueba una decision contra el contrato PolicyDecision v1. Devuelve los defectos.

    Verifica la forma congelada (campos requeridos, enumeraciones, patrones, limites) y las
    invariantes de las puertas: `require_human_approval` exige `gate` no nulo; `allow` con
    `gate` no nulo exige el registro de aprobacion con el mismo `scope_hash` de la accion; y
    un registro de aprobacion nunca puede declarar autenticacion.

    Lectura aplicada del segundo `allOf` (`if decision == allow then approval: object`): la
    exigencia de aprobacion se evalua sobre `allow` con puerta, conforme a `$defs
    .mandatory_gates`. Los `allow` sin puerta de tipos de accion que no levantan ninguna de
    las ocho puertas se aceptan con `gate: null` y `approval: null`; la nota de modulo
    documenta esta lectura y su alternativa literal.
    """
    problems = []
    if not isinstance(decision, dict):
        return ('la decision debe ser un objeto JSON',)
    missing = [field for field in DECISION_FIELDS if field not in decision]
    unknown = sorted(str(key) for key in decision if key not in DECISION_FIELDS + DECISION_OPTIONAL_FIELDS)
    if missing:
        problems.append('faltan campos requeridos: %s' % ', '.join(missing))
    if unknown:
        problems.append('campos no admitidos: %s' % ', '.join(unknown))
    problems.extend(find_prohibited_fields(decision, 'decision'))
    if decision.get('policy_contract_version') != POLICY_CONTRACT_VERSION:
        problems.append('policy_contract_version distinto de %r' % POLICY_CONTRACT_VERSION)
    if not isinstance(decision.get('policy_id'), str) or not _POLICY_ID_RE.match(str(decision.get('policy_id'))):
        problems.append('policy_id no cumple el patron del contrato')
    revision = decision.get('policy_revision')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        problems.append('policy_revision debe ser un entero positivo')
    action = decision.get('action')
    if not isinstance(action, dict):
        problems.append('action debe ser un objeto')
    else:
        try:
            _validated_action(action)
        except PolicyError as exc:
            problems.append('action no conforme: %s' % exc)
    outcome = decision.get('decision')
    if outcome not in DECISION_OUTCOMES:
        problems.append('decision fuera de %s' % (DECISION_OUTCOMES,))
    reason = decision.get('reason')
    if not isinstance(reason, str) or not 1 <= len(reason) <= _REASON_MAX:
        problems.append('reason debe ser texto de 1 a %d caracteres' % _REASON_MAX)
    gate = decision.get('gate')
    if gate is not None and gate not in GATES:
        problems.append('gate fuera de las ocho puertas')
    if outcome == DECISION_REQUIRE and gate is None:
        problems.append('require_human_approval exige gate no nulo')
    rules = decision.get('matched_rules')
    if not isinstance(rules, list):
        problems.append('matched_rules debe ser una lista')
    else:
        for rule in rules:
            if not isinstance(rule, dict):
                problems.append('cada regla coincidente debe ser un objeto')
                continue
            rule_missing = [field for field in ('rule_id', 'outcome') if field not in rule]
            rule_unknown = sorted(str(key) for key in rule if key not in ('rule_id', 'outcome', 'limit_ref'))
            if rule_missing or rule_unknown:
                problems.append('regla coincidente no conforme: %r' % (rule,))
            elif not isinstance(rule['rule_id'], str) or not _RULE_ID_RE.match(rule['rule_id']):
                problems.append('rule_id no cumple el patron de matched_rules: %r' % (rule['rule_id'],))
            elif rule['outcome'] not in DECISION_OUTCOMES:
                problems.append('outcome de regla fuera de %s' % (DECISION_OUTCOMES,))
        if not rules and outcome != DECISION_DENY:
            problems.append('una decision sin regla coincidente solo es valida como deny por defecto cerrado')
    limits = decision.get('limits')
    if not isinstance(limits, dict):
        problems.append('limits debe ser un objeto')
    else:
        limit_missing = [field for field in ('write_allowed', 'network_allowed', 'autonomy_ceiling', 'approvals_required') if field not in limits]
        limit_unknown = sorted(str(key) for key in limits if key not in LIMIT_FIELDS)
        if limit_missing:
            problems.append('limits sin campos requeridos: %s' % ', '.join(limit_missing))
        if limit_unknown:
            problems.append('limits con campos no admitidos: %s' % ', '.join(limit_unknown))
        if not isinstance(limits.get('write_allowed'), bool):
            problems.append('limits.write_allowed debe ser booleano')
        if limits.get('network_allowed') is not False:
            problems.append('limits.network_allowed es const false en el contrato v1')
        if limits.get('autonomy_ceiling') not in AUTONOMY_LEVELS:
            problems.append('limits.autonomy_ceiling fuera del vocabulario del TaskSpec')
        approvals = limits.get('approvals_required')
        if not isinstance(approvals, list) or any(g not in GATES for g in approvals):
            problems.append('limits.approvals_required debe listar puertas del contrato')
    if decision.get('side_effects_performed') is not False:
        problems.append('side_effects_performed debe ser false: evaluar no ejecuta la accion')
    if not isinstance(decision.get('evaluated_at'), str) or not _INSTANT_RE.match(str(decision.get('evaluated_at'))):
        problems.append('evaluated_at no cumple el patron ISO-8601 UTC del contrato')
    approval = decision.get('approval')
    if approval is not None:
        claims = find_authentication_claims(approval, 'approval')
        if claims:
            problems.append('la aprobacion declara autenticacion no verificada: %s' % ', '.join(sorted(claims)))
        problems.extend('aprobacion: %s' % problem for problem in _approval_problems(approval))
        if isinstance(approval, dict) and isinstance(action, dict):
            if approval.get('scope_hash') != action.get('scope_hash'):
                problems.append('approval.scope_hash debe coincidir con action.scope_hash')
        if gate is None:
            problems.append('una decision allow con aprobacion debe declarar la puerta que autoriza')
    elif outcome == DECISION_ALLOW and gate is not None:
        problems.append('allow en una puerta obligatoria exige el registro de aprobacion')
    if outcome == DECISION_ALLOW and gate is None and approval is None:
        rule_ids = {rule.get('rule_id') for rule in rules} if isinstance(rules, list) else set()
        if not rule_ids & {'default.open'} and not any(str(rule_id).startswith('gate.') for rule_id in rule_ids):
            problems.append('allow sin puerta debe trazar la regla que lo autoriza')
    return tuple(problems)


__all__ = ['POLICY_CONTRACT_VERSION', 'PROHIBITED_FIELDS', 'PROHIBITED_FIELDS_SOURCE',
           'INERT_BY_DEFAULT', 'SIDE_EFFECTS_PERFORMED', 'DECISION_ALLOW', 'DECISION_DENY',
           'DECISION_REQUIRE', 'DECISION_OUTCOMES', 'GATES', 'GATE_DEFAULT_OUTCOME',
           'ACTION_KINDS', 'AUTONOMY_LEVELS', 'AUTONOMY_CEILING_DEFAULT',
           'APPROVAL_IDENTITY_KIND', 'APPROVER_AUTHENTICATION', 'APPROVAL_AUTHENTICATION_CLAIM',
           'APPROVAL_FIELDS', 'DECISION_FIELDS', 'DECISION_OPTIONAL_FIELDS', 'LIMIT_FIELDS',
           'ACTION_FIELDS',
           'DEFAULT_ACTION_GATES', 'DEFAULT_TARGET_DENY_PATTERNS', 'AUTHENTICATION_CLAIM_KEYS',
           'PolicyError', 'Policy', 'default_policy', 'evaluate', 'validate_decision',
           'find_prohibited_fields', 'find_authentication_claims']
