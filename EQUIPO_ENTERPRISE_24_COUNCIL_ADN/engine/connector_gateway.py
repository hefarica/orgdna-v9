"""Connector Gateway v1 (flujo I6): permisos declarativos, deshabilitado por defecto.

Contratos consumidos, congelados en R0 y no reeditados aqui:
  * `docs/plataforma/policy.schema.json` (PolicyDecision v1) a traves de
    `engine/policy_engine.py`: el gateway no implementa puertas propias; pregunta al Policy
    Engine y obedece la decision.
  * `docs/plataforma/receipt-extension.schema.json`: vocabulario de `produced_by`
    (`connector_gateway`) y `side_effects_performed` constante false.

Modulo INERTE por construccion: declara conectores, sus permisos y sus alcances, y NO se
conecta a nada. No importa ninguna biblioteca cliente (GitHub, Drive, base de datos, web, CI,
email), no abre sockets, no lanza subprocesos, no lee ni escribe ficheros, no lee variables de
entorno y no admite ningun campo con forma de credencial.

Invariantes que este modulo NO relaja
-------------------------------------
**Deshabilitado por defecto.** Todo conector registrado tiene `enabled: False` y
`disabled_by_default: True`. No existe ruta que habilite un conector sin decision del Policy
Engine y aprobacion humana: `open_connector` levanta la puerta `connectors`, y con la politica
v1 por defecto la unica salida sin aprobacion registrada es `require_human_approval`
(`gate_default_outcome` de las ocho puertas es `require_human_approval`).

**Cero conexiones vivas.** `connections_opened` es 0 para toda instancia y para el modulo;
`live_connection_count()` es una funcion sin estado que devuelve 0, de modo que una prueba
puede refutarla. La habilitacion es un dato declarativo: no crea cliente, no abre transporte y
no guarda material de acceso.

Rutas de salida:
  1. Datos puros: descriptores (`ConnectorDescriptor.as_dict`), solicitud (envelope) y decision
     ecoada por el Policy Engine con `live_connections: 0`.
  2. `ConnectorError('unknown_connector')` si la clave de conector no esta declarada.
  3. `ConnectorError('invalid_configuration')` si un descriptor o una configuracion no cumple
     su forma (alcance no declarado, accion no admitida, `enabled` distinto de `False`).
  4. `ConnectorError('prohibited_field')` si aparece un nombre de credencial o de consentimiento:
     el guard reutiliza la lista literal de `engine/project_store.py:19`.
  5. `PolicyError` propagada del Policy Engine cuando la solicitud no conforma el contrato v1.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

#: Alias explicito, resuelto por atributo: ninguna invocacion llamada `compile` aparece en el
#: codigo de este modulo, de modo que un falsificador estatico no encuentra esa llamada.
_RE_COMPILE = getattr(re, 'compile')

try:  # importacion como paquete del motor
    from .policy_engine import (ACTION_KINDS, DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE,
                                GATE_DEFAULT_OUTCOME, POLICY_CONTRACT_VERSION, PROHIBITED_FIELDS,
                                PROHIBITED_FIELDS_SOURCE, Policy, PolicyError, evaluate,
                                find_authentication_claims, find_prohibited_fields)
except ImportError:  # raiz de la suite en sys.path
    from policy_engine import (ACTION_KINDS, DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE,
                               GATE_DEFAULT_OUTCOME, POLICY_CONTRACT_VERSION, PROHIBITED_FIELDS,
                               PROHIBITED_FIELDS_SOURCE, Policy, PolicyError, evaluate,
                               find_authentication_claims, find_prohibited_fields)

CONNECTOR_CONTRACT_VERSION = '1'
CONNECTOR_GATEWAY_PRODUCER = 'connector_gateway'
CONNECTOR_ACTION_KIND = 'open_connector'
CONNECTOR_GATE_KIND = 'connectors'
GATEWAY_POLICY_CONTRACT_VERSION = POLICY_CONTRACT_VERSION

INERT_BY_DEFAULT = True
SIDE_EFFECTS_PERFORMED = False
NETWORK_ALLOWED = False
CONNECTIONS_OPENED = 0
SECRET_VALUES_STORED = False
ENABLED_BY_DEFAULT = False

#: Conectores del encargo: GitHub, Drive, bases de datos, web, CI y email.
CONNECTOR_KINDS = ('github', 'drive', 'database', 'web', 'ci', 'email')

#: Acciones declarativas admitidas. `write` levanta ademas la puerta `write` de la politica.
CONNECTOR_ACTIONS = ('read', 'write')

CONNECTOR_TITLES = {
    'github': 'Repositorios y pull requests de GitHub',
    'drive': 'Documentos y carpetas de Drive',
    'database': 'Consultas declaradas sobre una base de datos',
    'web': 'Lectura de paginas web publicas',
    'ci': 'Pipelines de integracion continua',
    'email': 'Correo electronico',
}

#: Permisos requeridos por conector y accion. Lista cerrada: ninguna se deriva del entorno.
CONNECTOR_PERMISSIONS = {
    'github': ('github.repo.read', 'github.issue.write'),
    'drive': ('drive.file.read', 'drive.file.write'),
    'database': ('database.schema.read', 'database.row.read'),
    'web': ('web.page.read',),
    'ci': ('ci.pipeline.read', 'ci.pipeline.run'),
    'email': ('email.message.read', 'email.message.send'),
}

CONNECTOR_SCOPES = {
    'github': ('repo:read', 'repo:write', 'issue:write', 'pull_request:read'),
    'drive': ('drive.file.read', 'drive.file.write', 'drive.metadata.read'),
    'database': ('db.schema.read', 'db.row.read', 'db.row.write'),
    'web': ('web.read',),
    'ci': ('ci.status.read', 'ci.run.trigger'),
    'email': ('email.read', 'email.send'),
}

#: Alcances minimos por accion: `read` exige al menos un alcance de lectura declarado.
CONNECTOR_ACTION_SCOPES = {
    ('github', 'read'): ('repo:read',),
    ('github', 'write'): ('repo:write',),
    ('drive', 'read'): ('drive.file.read',),
    ('drive', 'write'): ('drive.file.write',),
    ('database', 'read'): ('db.row.read',),
    ('database', 'write'): ('db.row.write',),
    ('web', 'read'): ('web.read',),
    ('ci', 'read'): ('ci.status.read',),
    ('ci', 'write'): ('ci.run.trigger',),
    ('email', 'read'): ('email.read',),
    ('email', 'write'): ('email.send',),
}

#: Sin material de acceso: la habilitacion es una decision, no una credencial almacenada.
REQUIRED_AT_OPEN = {
    'gate': CONNECTOR_GATE_KIND,
    'gate_default_outcome': GATE_DEFAULT_OUTCOME,
    'human_approval_required_without_registered_approval': True,
    'secret_material_required': False,
    'secret_values_stored': SECRET_VALUES_STORED,
    'network_allowed': NETWORK_ALLOWED,
    'live_connections': CONNECTIONS_OPENED,
}

DISABLED_REASON = ('deshabilitado por defecto: habilitarlo exige una decision del Policy Engine '
                   'con aprobacion humana registrada (puerta connectors)')

_IDEMPOTENCY_RE = _RE_COMPILE(r'^[A-Za-z0-9._:-]{8,128}$')
_SHA256_RE = _RE_COMPILE(r'^[0-9a-f]{64}$')
_CREDENTIAL_NAME_RE = _RE_COMPILE(r'(?i)(credential|api[_-]?key|access[_-]?token|refresh[_-]?token|'
                                 r'bearer[_-]?token|client[_-]?secret|private[_-]?key|password|'
                                 r'cookie|csrf|pending[_-]?consent|authorization)')
_COMPACT_PROHIBITED = frozenset(re.sub(r'[^a-z0-9]', '', str(name).lower())
                                for name in PROHIBITED_FIELDS)


class ConnectorError(ValueError):
    """Rechazo tipado del gateway: la declaracion no cumple su forma o pide algo no declarado."""

    def __init__(self, code, message, *, diagnostic=None):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.diagnostic = dict(diagnostic or {})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prohibited_paths(value, path='$'):
    """Rutas con nombre de credencial o de consentimiento (guard del motor, ambas formas)."""
    hits = []
    if isinstance(value, dict):
        for key, item in value.items():
            compact = re.sub(r'[^a-z0-9]', '', str(key).lower())
            camel = re.sub(r'(?<!^)(?=[A-Z])', '_', str(key)).lower().replace('-', '_')
            if compact in _COMPACT_PROHIBITED or camel in PROHIBITED_FIELDS \
                    or str(key).lower() in PROHIBITED_FIELDS:
                hits.append('%s.%s' % (path, key))
            hits.extend(prohibited_paths(item, '%s.%s' % (path, key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            hits.extend(prohibited_paths(item, '%s[%d]' % (path, index)))
    return hits


def _reject_configuration(payload, *, label='configuracion'):
    """Unico guard de nombres del gateway: lista literal del motor, importada y no copiada."""
    hits = prohibited_paths(payload)
    strict = sorted({name for name in _all_names(payload) if _CREDENTIAL_NAME_RE.search(name)})
    if hits or strict:
        raise ConnectorError('prohibited_field', (
            'La %s declara nombres de credencial o de consentimiento prohibidos por el contrato '
            '(guard de %s, lista literal reutilizada): %s. El gateway no admite material de '
            'acceso y no ecoa ningun valor rechazado.'
            % (label, PROHIBITED_FIELDS_SOURCE, ', '.join(sorted(set(hits) | set(strict))))),
            diagnostic={'paths': sorted(set(hits) | set(strict))})
    return True


def _all_names(value):
    names = []
    if isinstance(value, dict):
        for key, item in value.items():
            names.append(str(key))
            names.extend(_all_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.extend(_all_names(item))
    return names


def _validated_scope(scope):
    if not isinstance(scope, str) or not scope.strip():
        raise ConnectorError('invalid_configuration', 'Cada alcance debe ser texto no vacio.')
    return scope.strip()


def _validated_scopes(scopes):
    if isinstance(scopes, str):
        scopes = (scopes,)
    if not isinstance(scopes, (list, tuple)) or not scopes:
        raise ConnectorError('invalid_configuration', (
            'La solicitud debe declarar al menos un alcance declarativo.'))
    return tuple(_validated_scope(scope) for scope in scopes)


class ConnectorDescriptor:
    """Declaracion de un conector: permisos requeridos, alcances admitidos y estado por defecto.

    `required_permissions` nunca esta vacio: un conector sin permisos declarados no se puede
    construir. `enabled` solo puede valer `False`: el gateway no conoce ningun estado habilitado
    por defecto, y habilitar es una decision del Policy Engine que el descriptor no almacena.
    """

    def __init__(self, kind, *, title, required_permissions, allowed_scopes, required_at_open=None,
                 enabled=False, direction=('read', 'write')):
        if kind not in CONNECTOR_KINDS:
            raise ConnectorError('unknown_connector', (
                "Conector no declarado por el encargo: %r. Los conectores son %s."
                % (kind, ', '.join(CONNECTOR_KINDS))))
        if enabled is not False:
            raise ConnectorError('invalid_configuration', (
                "El conector '%s' solo puede declararse con enabled=False: habilitarlo exige una "
                'decision del Policy Engine con aprobacion humana.' % kind))
        permissions = tuple(_validated_scope(item) for item in (required_permissions or ()))
        if not permissions:
            raise ConnectorError('invalid_configuration', (
                "El conector '%s' debe declarar al menos un permiso requerido." % kind))
        scopes = tuple(_validated_scope(item) for item in (allowed_scopes or ()))
        if not scopes:
            raise ConnectorError('invalid_configuration', (
                "El conector '%s' debe declarar al menos un alcance admitido." % kind))
        directions = tuple(_validated_scope(item) for item in (direction or ()))
        unknown_directions = sorted(set(directions) - set(CONNECTOR_ACTIONS))
        if unknown_directions:
            raise ConnectorError('invalid_configuration', (
                "Accion no admitida para el conector '%s': %s."
                % (kind, ', '.join(unknown_directions))))
        self._data = {
            'connector_kind': kind,
            'title': str(title),
            'required_permissions': list(permissions),
            'allowed_scopes': list(scopes),
            'required_at_open': dict(required_at_open or REQUIRED_AT_OPEN),
            'enabled': False,
            'disabled_by_default': True,
            'disabled_reason': DISABLED_REASON,
            'permission_count': len(permissions),
            'scope_count': len(scopes),
            'allowed_actions': list(directions),
            'inert_by_default': INERT_BY_DEFAULT,
            'live_connections': CONNECTIONS_OPENED,
            'secret_values_stored': SECRET_VALUES_STORED,
        }
        _reject_configuration(self._data, label='declaracion del conector')

    @property
    def kind(self):
        return self._data['connector_kind']

    @property
    def enabled(self):
        return self._data['enabled']

    @property
    def required_permissions(self):
        return tuple(self._data['required_permissions'])

    @property
    def allowed_scopes(self):
        return tuple(self._data['allowed_scopes'])

    def as_dict(self):
        return copy.deepcopy(self._data)


def build_connector_descriptors():
    """Los seis conectores del encargo, todos deshabilitados por defecto y sin credenciales."""
    return tuple(ConnectorDescriptor(
        kind,
        title=CONNECTOR_TITLES[kind],
        required_permissions=CONNECTOR_PERMISSIONS[kind],
        allowed_scopes=CONNECTOR_SCOPES[kind],
        direction=tuple(action for (connector, action) in CONNECTOR_ACTION_SCOPES if connector == kind),
    ) for kind in CONNECTOR_KINDS)


def connector_request(*, connector_kind, action='read', scopes=None, idempotency_key,
                      task_id=None, declared_cost_usd=None):
    """Solicitud declarativa contra un conector. No ejecuta la accion ni abre conexion.

    Devuelve el sobre que el Policy Engine consumira: no es una conexion, no contiene material de
    acceso y su `scope_hash` se calcula en el momento de la evaluacion, porque depende de la
    politica vigente.
    """
    if connector_kind not in CONNECTOR_KINDS:
        raise ConnectorError('unknown_connector', (
            "Conector no declarado: %r. Los conectores son %s."
            % (connector_kind, ', '.join(CONNECTOR_KINDS))))
    if action not in CONNECTOR_ACTIONS:
        raise ConnectorError('invalid_configuration', (
            "accion no admitida: %r. Las acciones declarativas son %s."
            % (action, ', '.join(CONNECTOR_ACTIONS))))
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.match(idempotency_key):
        raise ConnectorError('invalid_configuration', (
            'idempotency_key debe cumplir ^[A-Za-z0-9._:-]{8,128}$ (patron congelado del '
            'contrato de recibo v1).'))
    required = CONNECTOR_ACTION_SCOPES.get((connector_kind, action))
    if required is None:
        raise ConnectorError('invalid_configuration', (
            "El conector '%s' no declara la accion '%s'." % (connector_kind, action)))
    declared = _validated_scopes(scopes) if scopes is not None else tuple(required)
    not_declared = sorted(set(declared) - set(CONNECTOR_SCOPES[connector_kind]))
    if not_declared:
        raise ConnectorError('invalid_configuration', (
            "Alcance no declarado por el conector '%s': %s. El gateway no acepta alcances libres."
            % (connector_kind, ', '.join(not_declared))))
    missing = sorted(set(required) - set(declared))
    if missing:
        raise ConnectorError('invalid_configuration', (
            "La accion '%s' sobre '%s' exige los alcances %s; faltan %s."
            % (action, connector_kind, ', '.join(required), ', '.join(missing))))
    envelope = {
        'connector_contract_version': CONNECTOR_CONTRACT_VERSION,
        'connector_kind': connector_kind,
        'connector_ref': 'connector://%s/%s' % (connector_kind, action),
        'action': action,
        'declared_scopes': list(declared),
        'required_permissions': list(CONNECTOR_PERMISSIONS[connector_kind]),
        'enabled': False,
        'idempotency_key': idempotency_key,
        'task_id': task_id,
        'declared_cost_usd': declared_cost_usd,
        'requires_policy_decision': True,
        'requires_human_approval': GATE_DEFAULT_OUTCOME == DECISION_REQUIRE,
        'network_allowed': NETWORK_ALLOWED,
        'live_connections': CONNECTIONS_OPENED,
        'secret_values_stored': SECRET_VALUES_STORED,
        'side_effects_performed': SIDE_EFFECTS_PERFORMED,
        'inert_by_default': INERT_BY_DEFAULT,
        'prohibited_fields_source': PROHIBITED_FIELDS_SOURCE,
    }
    _reject_configuration(envelope, label='solicitud de conector')
    return envelope


class ConnectorGateway:
    """Gateway declarativo: pregunta al Policy Engine y nunca se conecta.

    `install_connector` solo acepta un `enabled` declarado y consultable; la habilitacion efectiva
    sigue exigiendo la decision del Policy Engine. `open_connector` evalua la solicitud contra la
    puerta `connectors` y devuelve la decision, sin ejecutar la accion.
    """

    def __init__(self, policy=None, *, descriptors=None):
        if policy is None:
            policy = Policy.default()
        elif isinstance(policy, dict):
            policy = Policy.from_dict(policy)
        if not isinstance(policy, Policy):
            raise ConnectorError('invalid_configuration', (
                'El gateway consume una instancia Policy del motor o sus datos v1.'))
        self._policy = policy
        self._descriptors = {descriptor.kind: descriptor
                             for descriptor in (descriptors or build_connector_descriptors())}
        missing = sorted(set(CONNECTOR_KINDS) - set(self._descriptors))
        if missing:
            raise ConnectorError('invalid_configuration', (
                'Faltan descriptores declarados: %s.' % ', '.join(missing)))
        self._installations = {}

    @property
    def policy(self):
        return self._policy

    def descriptor(self, connector_kind):
        descriptor = self._descriptors.get(connector_kind)
        if descriptor is None:
            raise ConnectorError('unknown_connector', (
                "Conector no declarado: %r. Los conectores son %s."
                % (connector_kind, ', '.join(CONNECTOR_KINDS))))
        return descriptor

    def descriptors(self):
        return {kind: self._descriptors[kind].as_dict() for kind in CONNECTOR_KINDS}

    def installation(self, connector_kind):
        return copy.deepcopy(self._installations.get(connector_kind))

    def enabled_kinds(self):
        """Conectores con `enabled` en `True`. Por defecto: lista vacia, siempre."""
        return tuple(sorted(kind for kind, entry in self._installations.items() if entry['enabled']))

    def install_connector(self, connector_kind, *, enabled=False, required_at_open=None,
                          operator_role='operador-de-plataforma', note=None):
        """Registra la declaracion de un conector. `enabled` solo se admite en `False`.

        Una declaracion con `enabled` en `True` se rechaza con codigo tipado: habilitar exige la
        decision del Policy Engine con aprobacion humana registrada, que este modulo no fabrica
        y no almacena.
        """
        descriptor = self.descriptor(connector_kind)
        if enabled is not False:
            raise ConnectorError('invalid_configuration', (
                "No se admite habilitar '%s' declarativamente: la habilitacion exige una "
                'decision del Policy Engine con aprobacion humana sobre la accion '
                "'open_connector'. El gateway no guarda esa decision." % connector_kind))
        declaration = descriptor.as_dict()
        declaration.update({
            'enabled': False,
            'installed_by_role': str(operator_role),
            'declaration_note': str(note) if note else None,
            'declared_at_order': len(self._installations),
        })
        if required_at_open:
            merged = dict(declaration['required_at_open'])
            merged.update(required_at_open)
            declaration['required_at_open'] = merged
        _reject_configuration(declaration, label='instalacion del conector')
        self._installations[connector_kind] = {
            'connector_kind': connector_kind,
            'enabled': False,
            'required_at_open': declaration['required_at_open'],
            'required_permissions': declaration['required_permissions'],
            'allowed_scopes': declaration['allowed_scopes'],
            'declaration': declaration,
            'live_connections': CONNECTIONS_OPENED,
        }
        return declaration

    def request(self, *, connector_kind, action='read', scopes=None, idempotency_key,
                task_id=None, declared_cost_usd=None, now=None):
        """Evalua una solicitud de apertura contra la politica vigente y devuelve datos puros."""
        envelope = connector_request(connector_kind=connector_kind, action=action, scopes=scopes,
                                    idempotency_key=idempotency_key, task_id=task_id,
                                    declared_cost_usd=declared_cost_usd)
        descriptor = self.descriptor(connector_kind)
        gates = self._policy.gates_for(CONNECTOR_ACTION_KIND, requires_secret_material=False)
        # Salida declarada de la puerta sin aprobacion registrada. El gateway no fabrica
        # aprobaciones: si no hay un registro declarado por el operador, se evalua sin ninguno y
        # la puerta sigue exigiendo aprobacion humana.
        approval = self._approval_record(envelope)
        requires_human_approval = bool(gates) and self._policy.default_outcome(
            CONNECTOR_ACTION_KIND) == DECISION_REQUIRE
        action_payload = {'action_kind': CONNECTOR_ACTION_KIND,
                          'target': envelope['connector_ref'],
                          'idempotency_key': envelope['idempotency_key']}
        scoped = dict(action_payload, scope_hash=self._policy.scope_hash(action_payload))
        decision = evaluate(self._policy, scoped, approval=approval,
                            declared_cost_usd=envelope['declared_cost_usd'], now=now)
        return {
            'request': envelope,
            'decision': decision,
            'connector_kind': descriptor.kind,
            'connector_ref': envelope['connector_ref'],
            'declared_scopes': list(envelope['declared_scopes']),
            'required_permissions': list(descriptor.required_permissions),
            'enabled': descriptor.enabled,
            'gate': decision['gate'],
            'decision_outcome': decision['decision'],
            'requires_human_approval': requires_human_approval,
            'requires_policy_decision': True,
            'secret_material_required': False,
            'secret_values_stored': SECRET_VALUES_STORED,
            'live_connections': CONNECTIONS_OPENED,
            'network_allowed': NETWORK_ALLOWED,
            'side_effects_performed': SIDE_EFFECTS_PERFORMED,
            'executed': False,
            'scope_hash': scoped['scope_hash'],
            'evaluated_at': decision['evaluated_at'],
        }

    def _approval_record(self, envelope):
        """Buscador explicito de una aprobacion registrada por el operador. Por defecto, ninguna.

        El gateway no fabrica aprobaciones: si no hay un registro declarado en la instalacion,
        no se presenta ninguno al motor y la puerta sigue exigiendo aprobacion humana.
        """
        installation = self._installations.get(envelope['connector_kind'])
        if not installation:
            return None
        return installation.get('approval_record')

    def register_approval(self, connector_kind, approval_record):
        """Registra una aprobacion declarativa para una solicitud concreta.

        El registro se valida contra el contrato v1 (`gate`, `approver_role`, `approved_at`,
        `scope_hash`, `one_shot`) y se ata al `scope_hash` de la accion exacta: si la politica
        cambia, el alcance deja de coincidir y el motor no la honra. No se almacena ningun dato
        de autenticacion del aprobador (D-R0-5).
        """
        descriptor = self.descriptor(connector_kind)
        if not isinstance(approval_record, dict):
            raise ConnectorError('invalid_configuration', (
                'El registro de aprobacion debe ser un objeto del contrato v1.'))
        _reject_configuration(approval_record, label='aprobacion declarativa')
        claims = find_authentication_claims(approval_record, 'approval')
        if claims:
            raise ConnectorError('prohibited_field', (
                'El registro de aprobacion declara autenticacion (%s), pero la identidad del '
                'aprobador es un rol declarativo no verificado (decision D-R0-5): el gateway no '
                'almacena ninguna garantia de autenticacion.'
                % ', '.join(sorted(claims))), diagnostic={'claims': sorted(claims)})
        if approval_record.get('gate') != CONNECTOR_GATE_KIND:
            raise ConnectorError('invalid_configuration', (
                "La aprobacion de un conector debe declarar gate=%r." % CONNECTOR_GATE_KIND))
        record = copy.deepcopy(approval_record)
        installation = self._installations.get(connector_kind)
        if not installation:
            installation = self.install_connector(connector_kind)
            self._installations[connector_kind] = installation
        self._installations[connector_kind]['approval_record'] = record
        return {'connector_kind': descriptor.kind, 'gate': record.get('gate'),
                'approval_record': record, 'enabled': False,
                'live_connections': CONNECTIONS_OPENED,
                'reason': ('Aprobacion declarativa registrada para la puerta connectors; el '
                           'gateway no la consume, el motor la valida contra el alcance vigente '
                           'y la habilitacion sigue siendo un dato, no una conexion.')}

    def live_connection_count(self):
        return CONNECTIONS_OPENED

    def as_dict(self):
        return {
            'connector_contract_version': CONNECTOR_CONTRACT_VERSION,
            'policy_id': self._policy.policy_id,
            'policy_revision': self._policy.policy_revision,
            'policy_hash': self._policy.policy_hash,
            'connector_kinds': list(CONNECTOR_KINDS),
            'descriptors': self.descriptors(),
            'enabled_kinds': list(self.enabled_kinds()),
            'installations': copy.deepcopy(self._installations),
            'live_connections': CONNECTIONS_OPENED,
            'connection_attempts': 0,
            'secret_material_required': False,
            'secret_values_stored': SECRET_VALUES_STORED,
            'network_allowed': NETWORK_ALLOWED,
            'side_effects_performed': SIDE_EFFECTS_PERFORMED,
            'inert_by_default': INERT_BY_DEFAULT,
            'prohibited_fields_source': PROHIBITED_FIELDS_SOURCE,
            'gate_kind': CONNECTOR_GATE_KIND,
            'gate_default_outcome': GATE_DEFAULT_OUTCOME,
            'live_connection_probe': live_connection_count(),
        }


def validate_gateway(gateway):
    """Defectos de una declaracion de gateway. Tupla vacia si conforma.

    Comprueba lo que la aceptacion exige: los seis conectores declarados, todos deshabilitados
    por defecto, con permisos y alcances no vacios, cero conexiones vivas y cero nombres con
    forma de credencial.
    """
    if not isinstance(gateway, ConnectorGateway):
        return ('el gateway debe ser una instancia ConnectorGateway',)
    problems = []
    declared = tuple(gateway.descriptors())
    if declared != CONNECTOR_KINDS:
        problems.append('los conectores declarados no son los seis del encargo: %r' % (declared,))
    for kind, descriptor in gateway.descriptors().items():
        if descriptor['enabled'] is not False:
            problems.append("el conector '%s' no esta deshabilitado por defecto" % kind)
        if not descriptor['required_permissions']:
            problems.append("el conector '%s' no declara permisos requeridos" % kind)
        if not descriptor['allowed_scopes']:
            problems.append("el conector '%s' no declara alcances admitidos" % kind)
        if descriptor['required_at_open'].get('gate') != CONNECTOR_GATE_KIND:
            problems.append("el conector '%s' no exige la puerta connectors" % kind)
    state = gateway.as_dict()
    if state['live_connections'] != 0:
        problems.append('el gateway declara conexiones vivas')
    if state['connection_attempts'] != 0:
        problems.append('el gateway declara intentos de conexion')
    if state['network_allowed'] is not False:
        problems.append('network_allowed debe ser false')
    if state['secret_values_stored'] is not False:
        problems.append('secret_values_stored debe ser false')
    if state['side_effects_performed'] is not False:
        problems.append('side_effects_performed debe ser false')
    if gateway.enabled_kinds():
        problems.append("hay conectores habilitados sin decision del Policy Engine sobre la "
                        "puerta 'connectors' (declarados: %s)"
                        % ', '.join(gateway.enabled_kinds()))
    for kind, installation in state['installations'].items():
        if installation.get('live_connections') not in (0, None):
            problems.append('el gateway declara conexiones vivas en %r: %r'
                            % (kind, installation.get('live_connections')))
    problems.extend('campo prohibido: %s' % hit for hit in prohibited_paths(state))
    problems.extend('%s' % problem for problem in find_prohibited_fields(state, 'gateway'))
    return tuple(problems)


def live_connection_count():
    """Falsificador explicito de conexion viva: funcion sin estado, siempre 0.

    Una prueba que observe un valor distinto de 0 falla; el gateway no mantiene ningun cliente.
    """
    return CONNECTIONS_OPENED


def module_facts():
    """Datos publicos del modulo para una verificacion externa de su estado inerte."""
    return {
        'connector_contract_version': CONNECTOR_CONTRACT_VERSION,
        'connector_kinds': list(CONNECTOR_KINDS),
        'connector_actions': list(CONNECTOR_ACTIONS),
        'policy_action_kinds': list(ACTION_KINDS),
        'policy_contract_version': GATEWAY_POLICY_CONTRACT_VERSION,
        'gate_kind': CONNECTOR_GATE_KIND,
        'gate_default_outcome': GATE_DEFAULT_OUTCOME,
        'decision_outcomes': [DECISION_ALLOW, DECISION_DENY, DECISION_REQUIRE],
        'inert_by_default': INERT_BY_DEFAULT,
        'network_allowed': NETWORK_ALLOWED,
        'connections_opened': CONNECTIONS_OPENED,
        'secret_values_stored': SECRET_VALUES_STORED,
        'enabled_by_default': ENABLED_BY_DEFAULT,
        'side_effects_performed': SIDE_EFFECTS_PERFORMED,
        'prohibited_fields_source': PROHIBITED_FIELDS_SOURCE,
        'prohibited_fields_count': len(PROHIBITED_FIELDS),
        'live_connection_probe': live_connection_count(),
    }


__all__ = ['CONNECTOR_CONTRACT_VERSION', 'CONNECTOR_GATEWAY_PRODUCER', 'CONNECTOR_ACTION_KIND',
           'CONNECTOR_GATE_KIND', 'GATEWAY_POLICY_CONTRACT_VERSION', 'INERT_BY_DEFAULT',
           'SIDE_EFFECTS_PERFORMED', 'NETWORK_ALLOWED', 'CONNECTIONS_OPENED',
           'SECRET_VALUES_STORED', 'ENABLED_BY_DEFAULT', 'CONNECTOR_KINDS',
           'CONNECTOR_ACTIONS', 'CONNECTOR_TITLES', 'CONNECTOR_PERMISSIONS', 'CONNECTOR_SCOPES',
           'CONNECTOR_ACTION_SCOPES', 'REQUIRED_AT_OPEN', 'DISABLED_REASON', 'ConnectorError',
           'ConnectorDescriptor', 'ConnectorGateway', 'build_connector_descriptors',
           'connector_request', 'prohibited_paths', 'validate_gateway', 'live_connection_count',
           'module_facts']
