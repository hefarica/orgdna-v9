"""Agent Registry versionado e INERTE (flujo I2, capa de plataforma Agent OS).

Registra, versiona y valida perfiles de agente -- perfil, instrucciones, skills,
permisos declarados y modelos permitidos -- y detecta deriva respecto de un
snapshot versionado. Este modulo NO instala skills, NO concede permisos, NO
muta `toolScope`, NO ejecuta ninguna accion, NO abre red, NO escribe en disco y
NO envia nada a ningun proveedor: toda funcion devuelve datos.

Contratos consumidos (R0, congelados en `docs/PLATAFORMA_CONTRATOS_V1.md`):
  * `docs/plataforma/taskspec.schema.json` -> `agent_ref` (referencia declarativa,
    cadena de hasta 120 caracteres; su presencia no prueba que el agente exista).
  * `docs/plataforma/evidence-node.schema.json` -> forma de evidencia referenciada
    (los perfiles se citan como referencias tipadas, no como bytes).

Reglas heredadas de R0:
  * R-1 version explicita: el contrato de entrada es siempre `"1"`; cualquier otro
    valor falla con `unsupported_version`, nunca se interpreta con tolerancia.
  * R-3 guard de credenciales: se reutiliza la lista literal de
    `engine/project_store.py:19` y la normalizacion de `engine/project_store.py:38-46`
    llamando al guard del motor, mas un patron estricto de nombres de credencial.
  * R-2 nada desconocido se convierte en cero: falta de version, de hash o de
    procedencia es un error tipado, nunca un valor por defecto silencioso.
  * R-10 todo es local: ningun campo admite un endpoint remoto ni una URL con
    credenciales embebidas.

Un registro **declara**; no autoriza. `permissions` enumera nombres de herramienta
propuestos y `allowed_models` enumera modelos declarados: ambos son datos de solo
lectura para quien los consuma y ninguno cambia el `toolScope` de la organizacion.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

try:  # importado como `engine.agent_registry`
    from .project_store import FORBIDDEN_FIELDS, ProjectStoreError, _reject_secret_fields
except ImportError:  # ejecucion directa del archivo
    from project_store import FORBIDDEN_FIELDS, ProjectStoreError, _reject_secret_fields

REGISTRY_VERSION = '1'
CONTRACT_VERSION_FIELD = 'registry_entry_version'
ENTRY_KINDS = ('profile', 'instructions', 'skills', 'permissions', 'models')
ENTRY_STATES = ('declared', 'superseded')
SKILL_STATUS = ('PROPOSED', 'NOT_INSTALLED', 'PROPOSED_NOT_INSTALLED', 'DECLARED')
INSTALL_ASSERTION_KEYS = frozenset({
    'installed', 'granted', 'applied', 'active', 'enabled', 'installation_verified',
    'promoted', 'write_scope', 'scope_applied', 'tool_scope', 'toolscope',
})
MAX_ENTRIES = 512
MAX_LIST_ITEMS = 256

SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
SEMVER_RE = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
ISO_Z_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$')
REMOTE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://')
# Una URL con userinfo (`esquema://usuario:secreto@host`) es una credencial embebida.
USERINFO_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+@')
CREDENTIAL_NAME_RE = re.compile(
    r'(?i)(credential|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer[_-]?token|'
    r'client[_-]?secret|private[_-]?key|password|cookie|csrf|pending[_-]?consent|authorization)')
# `tokens` es una magnitud de presupuesto, no un token de acceso: la excepcion se
# declara auditada (misma nota que la seccion 8.3 de `docs/PLATAFORMA_CONTRATOS_V1.md`).
AUDITED_NON_CREDENTIAL = frozenset({'tokens'})

# Estado declarado del modulo. Se expone para que una prueba pueda refutarlo.
INERT_FLAGS = {
    'installs_skills': False,
    'grants_permissions': False,
    'mutates_tool_scope': False,
    'executes_actions': False,
    'network_allowed': False,
    'writes_to_disk': False,
    'sends_to_providers': False,
}

SUITE_ROOT = Path(__file__).resolve().parent.parent


class RegistryError(ValueError):
    """Error tipado del registro. `code` es el vocabulario estable de I2."""

    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------- #
# Determinismo y guard de credenciales
# --------------------------------------------------------------------------- #
def canonical_json(value):
    """JSON canonico de R-6: sort_keys, separadores compactos, sin escapes ASCII."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def sha256_of(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def sha256_of_bytes(data):
    return hashlib.sha256(data).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def normalized_names(name):
    """Replica literal de `engine/project_store.py:38-46`."""
    camel = re.sub(r'(?<!^)(?=[A-Z])', '_', str(name)).lower().replace('-', '_')
    return camel, re.sub(r'[^a-z0-9]', '', str(name).lower())


def credential_like(name):
    """`True` si el nombre coincide con el guard del motor o con un patron estricto."""
    if str(name) in AUDITED_NON_CREDENTIAL:
        return False
    camel, stripped = normalized_names(name)
    if camel in FORBIDDEN_FIELDS or stripped in {re.sub(r'[^a-z0-9]', '', item) for item in FORBIDDEN_FIELDS}:
        return True
    return bool(CREDENTIAL_NAME_RE.search(str(name)))


def reject_credentials(value, where='<raiz>'):
    """Rechaza claves con forma de credencial. Reutiliza el guard del motor."""
    try:
        _reject_secret_fields(value)
    except ProjectStoreError:
        raise RegistryError('prohibited_field',
                            'El registro contiene un campo de credencial o consentimiento.',
                            {'where': where, 'guard': 'engine/project_store.py:38-46'}) from None
    if isinstance(value, dict):
        for key, item in value.items():
            if credential_like(key):
                raise RegistryError('prohibited_field',
                                    'Nombre de campo con forma de credencial: %r.' % (key,),
                                    {'where': where, 'field': str(key)})
            reject_credentials(item, '%s.%s' % (where, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_credentials(item, '%s[%d]' % (where, index))
    return True


def reject_install_assertions(value, where='<raiz>'):
    """Ninguna declaracion puede afirmar instalacion ni concesion de permisos."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace('-', '_') in INSTALL_ASSERTION_KEYS:
                if item not in (False, None, 0, '', 'false', 'False', 'none'):
                    raise RegistryError('install_forbidden',
                                        'El registro declara instalacion o concesion; esta prohibido: %r.' % (key,),
                                        {'where': where, 'field': str(key)})
            reject_install_assertions(item, '%s.%s' % (where, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_install_assertions(item, '%s[%d]' % (where, index))
    return True


def check_local_reference(value, field, allow_relative_path=True):
    """R-10: una referencia no admite endpoint remoto ni credencial embebida."""
    if not isinstance(value, str) or not value.strip():
        raise RegistryError('invalid_reference', '%s debe ser una referencia local no vacia.' % field, {'field': field})
    if USERINFO_RE.match(value):
        raise RegistryError('embedded_credential', '%s contiene una URL con credenciales embebidas.' % field,
                            {'field': field})
    if REMOTE_RE.match(value):
        raise RegistryError('remote_reference_forbidden', '%s designa un endpoint remoto; solo se admite local.' % field,
                            {'field': field})
    if allow_relative_path and (value.startswith('/') or value.startswith('\\') or '..' in Path(value).parts
                                or re.match(r'^[A-Za-z]:', value)):
        raise RegistryError('path_out_of_scope', '%s sale del arbol local autorizado.' % field, {'field': field})
    return value


# --------------------------------------------------------------------------- #
# Huellas y deriva
# --------------------------------------------------------------------------- #
LIST_IDENTITY_KEYS = ('name', 'model_id', 'skill_id', 'entry_id', 'profile_id', 'ref', 'path', 'id', 'role')


def _identity_label(item, index):
    if isinstance(item, dict):
        for key in LIST_IDENTITY_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value:
                return '%s=%s' % (key, value)
    return str(index)


def flatten_fields(value, prefix=''):
    """Aplana a `{ruta: valor_canonico}`. Una lista de escalares es una sola hoja."""
    fields = {}
    if isinstance(value, dict):
        if not value:
            fields[prefix or '<raiz>'] = '{}'
        for key in sorted(value):
            child = '%s.%s' % (prefix, key) if prefix else str(key)
            fields.update(flatten_fields(value[key], child))
    elif isinstance(value, (list, tuple)):
        if not value:
            fields[prefix or '<raiz>'] = '[]'
        elif all(not isinstance(item, (dict, list, tuple)) for item in value):
            fields[prefix or '<raiz>'] = canonical_json(list(value))
        else:
            used = {}
            for index, item in enumerate(value):
                label = _identity_label(item, index)
                used[label] = used.get(label, 0) + 1
                if used[label] > 1:
                    label = '%s#%d' % (label, index)
                child = '%s[%s]' % (prefix, label) if prefix else '[%s]' % (label,)
                fields.update(flatten_fields(item, child))
    else:
        fields[prefix or '<raiz>'] = canonical_json(value)
    return fields


def diff_fields(expected, observed):
    """Deriva campo a campo: devuelve la ruta exacta que cambio, ni una mas."""
    records = []
    for path in sorted(set(expected) | set(observed)):
        if path not in observed:
            records.append({'field': path, 'change': 'removed', 'expected': expected[path], 'observed': None})
        elif path not in expected:
            records.append({'field': path, 'change': 'added', 'expected': None, 'observed': observed[path]})
        elif expected[path] != observed[path]:
            records.append({'field': path, 'change': 'changed',
                            'expected': expected[path], 'observed': observed[path]})
    return records


def entry_hash(entry_kind, entry_id, version, content):
    """Huella SHA-256 canonica de una entrada (R-6)."""
    return sha256_of({'entry_kind': entry_kind, 'entry_id': entry_id,
                      'entry_version': version, 'content': content})


# --------------------------------------------------------------------------- #
# Validadores de contenido
# --------------------------------------------------------------------------- #
def _require(condition, code, message, detail=None):
    if not condition:
        raise RegistryError(code, message, detail)


def _version_tuple(value):
    _require(isinstance(value, str) and SEMVER_RE.match(value), 'invalid_version',
             'La version debe ser semver `MAYOR.MENOR.PARCHE`.', {'version': value})
    return tuple(int(part) for part in value.split('.'))


def _name_list(values, field, require=False):
    _require(isinstance(values, list) and (values or not require), 'invalid_content',
             '%s debe ser una lista%s.' % (field, ' no vacia' if require else ''), {'field': field})
    _require(len(values) <= MAX_LIST_ITEMS, 'invalid_content', '%s supera %d elementos.' % (field, MAX_LIST_ITEMS))
    result = []
    for value in values:
        _require(isinstance(value, str) and value and len(value) <= 120 and value == value.strip(),
                 'invalid_content', '%s admite nombres exactos no vacios.' % field, {'field': field, 'value': value})
        _require('*' not in value and ',' not in value and not any(ord(c) < 32 for c in value),
                 'invalid_content', '%s no admite comodines, CSV ni controles.' % field, {'value': value})
        result.append(value)
    _require(len(result) == len(set(result)), 'invalid_content', '%s tiene duplicados.' % field)
    return result


def _validate_instructions(content):
    _require(isinstance(content, dict), 'invalid_content', 'instructions debe ser un objeto.')
    text = content.get('text')
    text_ref = content.get('text_ref')
    _require(bool(text) != bool(text_ref), 'invalid_content',
             'instructions exige exactamente uno de `text` o `text_ref`.')
    if text_ref is not None:
        check_local_reference(text_ref, 'instructions.text_ref')
    if content.get('sha256') is not None:
        _require(isinstance(content['sha256'], str) and SHA256_RE.match(content['sha256']),
                 'invalid_hash', 'instructions.sha256 debe ser SHA-256 hexadecimal de 64 caracteres.')
    return True


def _validate_skills(content):
    """Un skill se declara con hash; jamas se instala desde aqui.

    Admite una declaracion suelta (`{name, version, sha256}`), una lista de
    declaraciones o el contenedor `{'declared': [ ... ]}` que usa la suite.
    """
    if isinstance(content, list):
        _require(bool(content), 'invalid_content', 'skills no puede ser una lista vacia.')
        for item in content:
            _validate_skills(item)
        return True
    _require(isinstance(content, dict), 'invalid_content', 'skills debe ser un objeto o una lista.')
    if 'declared' in content:
        declared = content['declared']
        _require(isinstance(declared, list) and declared, 'invalid_content',
                 'skills.declared debe ser una lista no vacia de declaraciones.')
        for item in declared:
            _validate_skills(item)
        return True
    name = content.get('name')
    _require(isinstance(name, str) and IDENTIFIER_RE.match(name), 'invalid_content',
             'skills.name debe ser un identificador estable.', {'name': name})
    _version_tuple(content.get('version'))
    declared = content.get('sha256')
    _require(isinstance(declared, str) and SHA256_RE.match(declared), 'invalid_hash',
             'skills.sha256 es obligatorio y debe ser SHA-256 hexadecimal de 64 caracteres.',
             {'skill': name, 'sha256': declared})
    if content.get('status') is not None:
        _require(content['status'] in SKILL_STATUS, 'install_forbidden',
                 'skills.status declara un estado de instalacion no admitido.',
                 {'skill': name, 'status': content['status']})
    _require(content.get('installation_verified') in (None, False), 'install_forbidden',
             'skills.installation_verified debe ser falso o ausente.', {'skill': name})
    if content.get('entrypoint') is not None:
        check_local_reference(content['entrypoint'], 'skills.entrypoint')
    return True


def _validate_permissions(content):
    """Permisos declarados: nombres propuestos, nunca una concesion aplicada."""
    _require(isinstance(content, dict), 'invalid_content', 'permissions debe ser un objeto.')
    _require(bool(set(content) & {'allow', 'deny'}), 'invalid_content',
             'permissions exige al menos `allow` o `deny`.')
    for field in ('allow', 'deny'):
        if field in content:
            _name_list(content[field], 'permissions.%s' % field, require=True)
    overlap = set(content.get('allow') or []) & set(content.get('deny') or [])
    _require(not overlap, 'invalid_content', 'permissions.allow y deny no pueden solaparse.',
             {'overlap': sorted(overlap)})
    _require(content.get('applied') in (None, False), 'install_forbidden',
             'permissions.applied debe ser falso o ausente: el registro no aplica politicas.')
    return True


def _validate_models(content, known_models=None):
    payload = content
    if isinstance(content, list):
        payload = {'allowed_models': content}
    _require(isinstance(payload, dict), 'invalid_content', 'models debe ser un objeto o una lista.')
    models = payload.get('allowed_models')
    _require(isinstance(models, list), 'invalid_content', 'models.allowed_models debe ser una lista.')
    seen = set()
    for item in models:
        _require(isinstance(item, dict), 'invalid_content', 'Cada modelo permitido debe ser un objeto.')
        model_id = item.get('model_id')
        _require(isinstance(model_id, str) and MODEL_ID_RE.match(model_id), 'invalid_content',
                 'Cada modelo permitido exige `model_id`.', {'model_id': model_id})
        _require(model_id not in seen, 'duplicate_model', 'Modelo permitido duplicado.', {'model_id': model_id})
        seen.add(model_id)
        check_local_reference(item.get('provider_ref') or '', 'allowed_models.provider_ref',
                              allow_relative_path=False)
        capabilities = item.get('capabilities')
        _require(isinstance(capabilities, list) and capabilities, 'invalid_content',
                 'Cada modelo permitido declara `capabilities` no vacias.', {'model_id': model_id})
        _name_list(capabilities, 'allowed_models.capabilities', require=True)
        if item.get('enabled') not in (None, False):
            raise RegistryError('install_forbidden',
                                'Un modelo permitido no se habilita desde el registro.', {'model_id': model_id})
        if known_models is not None and model_id not in known_models:
            raise RegistryError('unknown_model',
                                'Modelo permitido fuera del conjunto declarado.',
                                {'model_id': model_id, 'declared': sorted(known_models)[:32]})
    return True


def _validate_profile_content(content, known_models=None):
    _require(isinstance(content, dict), 'invalid_content', 'profile debe ser un objeto.')
    _require('profile_id' in content and 'profile_version' in content, 'invalid_content',
             'profile exige `profile_id` y `profile_version`.')
    _version_tuple(content['profile_version'])
    for section, validator in (('instructions', _validate_instructions),
                               ('skills', _validate_skills),
                               ('permissions', _validate_permissions)):
        if section in content:
            validator(content[section])
    if 'allowed_models' in content:
        _validate_models(content['allowed_models'], known_models)
    return True


class AgentRegistry:
    """Registro versionado en memoria. Sin escritura, sin red, sin concesiones."""

    def __init__(self, root=None, known_models=None):
        self.root = Path(root).expanduser().resolve() if root is not None else SUITE_ROOT
        self._entries = {}
        self._latest = {}
        self._snapshots = {}
        self._known_models = frozenset(known_models) if known_models is not None else None
        self._counters = {'write_operations': 0, 'granted_permissions': 0, 'installed_skills': 0,
                          'tool_scope_mutations': 0, 'network_calls': 0, 'executed_actions': 0}

    # -- registro ---------------------------------------------------------- #
    def register(self, kind, entry_id, version, content, sha256=None, origin=None,
                 recorded_at=None, provenance=None, state='declared', derived_from=None):
        """Registra una entrada versionada. Sin hash o con hash invalido se rechaza."""
        _require(kind in ENTRY_KINDS, 'unsupported_entry_kind',
                 'Tipo de entrada no admitido por el contrato v1.', {'entry_kind': kind, 'admitted': list(ENTRY_KINDS)})
        _require(isinstance(entry_id, str) and IDENTIFIER_RE.match(entry_id), 'invalid_content',
                 'entry_id debe ser un identificador estable.', {'entry_id': entry_id})
        _version_tuple(version)
        _require(state in ENTRY_STATES, 'install_forbidden',
                 'El registro solo admite estado declarado o superado.', {'state': state})
        _require(isinstance(content, dict) and content, 'invalid_content', 'content debe ser un objeto no vacio.')
        reject_credentials({'content': content})
        reject_install_assertions(content)
        if kind == 'profile':
            _validate_profile_content(content, self._known_models)
            _require(content.get('profile_id') == entry_id, 'profile_mismatch',
                     'profile_id no coincide con entry_id.', {'profile_id': content.get('profile_id')})
            _require(content.get('profile_version') == version, 'profile_mismatch',
                     'profile_version no coincide con la version de la entrada.',
                     {'profile_version': content.get('profile_version'), 'entry_version': version})
        elif kind == 'instructions':
            _validate_instructions(content)
        elif kind == 'skills':
            _validate_skills(content)
        elif kind == 'permissions':
            _validate_permissions(content)
        else:
            _validate_models(content, self._known_models)
        expected = entry_hash(kind, entry_id, version, content)
        if sha256 is None:
            raise RegistryError('missing_hash',
                                'Cada entrada exige su hash SHA-256; no se calcula en silencio.',
                                {'entry_kind': kind, 'entry_id': entry_id, 'entry_version': version})
        _require(isinstance(sha256, str) and SHA256_RE.match(sha256), 'invalid_hash',
                 'sha256 debe ser SHA-256 hexadecimal de 64 caracteres en minusculas.', {'sha256': sha256})
        _require(sha256 == expected, 'hash_mismatch',
                 'La entrada no coincide con el hash declarado.', {'declared': sha256, 'observed': expected})
        provenance = self._provenance(origin, recorded_at, provenance)
        key = (kind, entry_id, version)
        _require(key not in self._entries, 'duplicate_entry',
                 'Una version registrada no se sobrescribe.', {'entry_kind': kind, 'entry_id': entry_id,
                                                               'entry_version': version})
        _require(len(self._entries) < MAX_ENTRIES, 'capacity_exceeded', 'Registro lleno.')
        entry = {
            CONTRACT_VERSION_FIELD: REGISTRY_VERSION,
            'entry_kind': kind,
            'entry_id': entry_id,
            'entry_version': version,
            'content_sha256': sha256,
            'provenance': provenance,
            'state': state,
            'content': copy.deepcopy(content),
        }
        if derived_from is not None:
            entry['derived_from'] = copy.deepcopy(derived_from)
        reject_credentials(entry)
        current = self._latest.get((kind, entry_id))
        if current is not None:
            _require(_version_tuple(version) > _version_tuple(current), 'version_regression',
                     'La version nueva debe superar a la vigente.', {'current': current, 'declared': version})
        self._entries[key] = entry
        self._latest[(kind, entry_id)] = version
        return copy.deepcopy(entry)

    def _provenance(self, origin, recorded_at, provenance):
        if provenance is not None:
            _require(isinstance(provenance, dict), 'missing_provenance', 'provenance debe ser un objeto.')
            origin = provenance.get('origin')
            recorded_at = provenance.get('recorded_at')
        _require(isinstance(origin, str) and origin.strip(), 'missing_provenance',
                 'Cada entrada exige procedencia: `origin` no vacio.')
        recorded_at = recorded_at or now_iso()
        _require(isinstance(recorded_at, str) and ISO_Z_RE.match(recorded_at), 'missing_provenance',
                 'Cada entrada exige fecha `recorded_at` en ISO-8601 UTC.', {'recorded_at': recorded_at})
        return {'origin': origin.strip(), 'recorded_at': recorded_at}

    def register_profile(self, profile, sha256=None, origin=None, recorded_at=None, provenance=None):
        """Registra un perfil y, de forma derivada, sus secciones ya verificadas.

        Es atomico: si una seccion derivada no se puede registrar, se retiran la
        entrada del perfil y las secciones ya creadas, y el registro queda como
        estaba. Nunca deja un perfil a medias.
        """
        _require(isinstance(profile, dict), 'invalid_content', 'profile debe ser un objeto.')
        entry_id = profile.get('profile_id')
        version = profile.get('profile_version')
        key = ('profile', entry_id, version)
        previous = self._latest.get(('profile', entry_id))
        entry = self.register('profile', entry_id, version, profile, sha256=sha256, origin=origin,
                              recorded_at=recorded_at, provenance=provenance)
        derived = {'entry_id': entry_id, 'entry_version': version, 'content_sha256': entry['content_sha256']}
        created = [key]
        sections = {'instructions': 'instructions', 'skills': 'skills', 'permissions': 'permissions'}
        try:
            for section, kind in sections.items():
                if section in profile:
                    created.append(self._register_derived(kind, '%s.%s' % (entry_id, section), version,
                                                          profile[section], origin,
                                                          entry['provenance']['recorded_at'], derived))
            if 'allowed_models' in profile:
                created.append(self._register_derived('models', '%s.models' % entry_id, version,
                                                      profile['allowed_models'], origin,
                                                      entry['provenance']['recorded_at'], derived))
        except RegistryError:
            for created_key in [item for item in created if item is not None]:
                self._entries.pop(created_key, None)
                self._latest.pop((created_key[0], created_key[1]), None)
            if previous is None:
                self._latest.pop(('profile', entry_id), None)
            else:
                self._latest[('profile', entry_id)] = previous
            raise
        return {'entry': entry, 'derived_entries': self.section_entries(entry_id)}

    def _register_derived(self, kind, entry_id, version, content, origin, recorded_at, derived):
        """Devuelve la clave creada, o None si la seccion ya estaba registrada."""
        if isinstance(content, list):
            if kind == 'skills':
                content = {'declared': content}
            elif kind == 'models':
                content = {'allowed_models': content}
            else:
                raise RegistryError('invalid_content', 'La seccion derivada debe ser un objeto.',
                                    {'entry_kind': kind, 'entry_id': entry_id})
        digest = entry_hash(kind, entry_id, version, content)
        try:
            self.register(kind, entry_id, version, content, sha256=digest, origin=origin,
                          recorded_at=recorded_at, derived_from=derived)
        except RegistryError as exc:
            if exc.code != 'duplicate_entry':
                raise
            return None
        return (kind, entry_id, version)

    # -- consulta ---------------------------------------------------------- #
    def get(self, kind, entry_id, version=None):
        _require(kind in ENTRY_KINDS, 'unsupported_entry_kind', 'Tipo de entrada no admitido.',
                 {'entry_kind': kind})
        version = version or self._latest.get((kind, entry_id))
        key = (kind, entry_id, version)
        _require(key in self._entries, 'unknown_entry', 'Entrada no registrada.',
                 {'entry_kind': kind, 'entry_id': entry_id, 'entry_version': version})
        return copy.deepcopy(self._entries[key])

    def versions(self, kind, entry_id):
        return sorted((version for (k, i, version) in self._entries if k == kind and i == entry_id),
                      key=_version_tuple)

    def list_entries(self, kind=None):
        return [{'entry_kind': key[0], 'entry_id': key[1], 'entry_version': key[2]}
                for key in sorted(self._entries) if kind is None or key[0] == kind]

    def section_entries(self, profile_id):
        return [row for row in self.list_entries()
                if row['entry_id'] == profile_id or row['entry_id'].startswith(profile_id + '.')]

    def profile_ref(self, profile_id, version=None):
        """Referencia declarativa para `taskspec.agent_ref` (cadena <= 120)."""
        entry = self.get('profile', profile_id, version)
        return 'agent-registry:profile:%s@%s#%s' % (entry['entry_id'], entry['entry_version'],
                                                    entry['content_sha256'][:12])

    def profile_ref_record(self, profile_id, version=None):
        entry = self.get('profile', profile_id, version)
        return {'agent_ref': self.profile_ref(profile_id, version), 'profile_id': entry['entry_id'],
                'entry_version': entry['entry_version'], 'content_sha256': entry['content_sha256'],
                'executable': False, 'source': 'engine/agent_registry.py'}

    def verify_entry_hash(self, kind, entry_id, version=None, sha256=None):
        entry = self.get(kind, entry_id, version)
        expected = entry_hash(entry['entry_kind'], entry['entry_id'], entry['entry_version'], entry['content'])
        result = {'entry_kind': kind, 'entry_id': entry_id, 'entry_version': entry['entry_version'],
                  'stored': entry['content_sha256'], 'recomputed': expected,
                  'valid': expected == entry['content_sha256']}
        if sha256 is not None:
            result['declared'] = sha256
            result['matches_declared'] = expected == sha256
            result['valid'] = result['valid'] and result['matches_declared']
        return result

    def verify_instructions(self, profile_id, version=None):
        """Recomprueba (solo lectura) las instrucciones respaldadas por un archivo."""
        entry = self.get('profile', profile_id, version)
        instructions = entry['content'].get('instructions') or {}
        text_ref = instructions.get('text_ref')
        declared = instructions.get('sha256')
        if text_ref is None:
            return {'profile_id': profile_id, 'basis': 'inline_text', 'recomputed': False,
                    'verified': False, 'note': 'Texto en linea: no hay bytes locales que recomprobar.'}
        path = (self.root / text_ref).resolve()
        if not path.is_file() or not path.resolve().is_relative_to(self.root):
            return {'profile_id': profile_id, 'basis': 'file_sha256', 'recomputed': False,
                    'verified': False, 'ref': text_ref, 'note': 'Archivo local no disponible.'}
        observed = sha256_of_bytes(path.read_bytes())
        return {'profile_id': profile_id, 'basis': 'file_sha256', 'ref': text_ref, 'declared': declared,
                'observed': observed, 'recomputed': True,
                'verified': bool(declared) and declared == observed}

    # -- snapshot y deriva ------------------------------------------------- #
    def snapshot(self, profile_id, origin, recorded_at=None, version=None):
        """Congela el estado vigente del perfil. Un snapshot no se edita."""
        entry = self.get('profile', profile_id, version)
        fields = self._profile_fields(entry['entry_version'], entry['content'])
        history = self._snapshots.setdefault(profile_id, [])
        snapshot = {
            'snapshot_version': len(history) + 1,
            'profile_id': profile_id,
            'entry_version': entry['entry_version'],
            'content_sha256': entry['content_sha256'],
            'fields': fields,
            'field_count': len(fields),
            'snapshot_sha256': sha256_of(fields),
            'provenance': self._provenance(origin, recorded_at, None),
        }
        history.append(snapshot)
        return copy.deepcopy(snapshot)

    def snapshots(self, profile_id):
        return [_public_snapshot(row) for row in self._snapshots.get(profile_id, [])]

    def latest_snapshot(self, profile_id):
        history = self._snapshots.get(profile_id) or []
        _require(bool(history), 'unknown_snapshot', 'No hay snapshot versionado para este perfil.',
                 {'profile_id': profile_id})
        return history[-1]

    def verify_snapshot(self, profile_id, snapshot_version=None):
        history = self._snapshots.get(profile_id) or []
        _require(bool(history), 'unknown_snapshot', 'No hay snapshot versionado para este perfil.',
                 {'profile_id': profile_id})
        snapshot = history[-1] if snapshot_version is None else next(
            (row for row in history if row['snapshot_version'] == snapshot_version), None)
        _require(snapshot is not None, 'unknown_snapshot', 'Snapshot inexistente.',
                 {'profile_id': profile_id, 'snapshot_version': snapshot_version})
        observed = sha256_of(snapshot['fields'])
        return {'profile_id': profile_id, 'snapshot_version': snapshot['snapshot_version'],
                'stored': snapshot['snapshot_sha256'], 'recomputed': observed,
                'valid': observed == snapshot['snapshot_sha256']}

    @staticmethod
    def _profile_fields(entry_version, content):
        view = {key: value for key, value in content.items() if key not in ('profile_version', 'entry_version')}
        return flatten_fields({'entry_version': entry_version, **view})

    def _current_fields(self, profile_id, current):
        _require(isinstance(current, dict), 'invalid_content',
                 'El perfil vigente debe ser un objeto de perfil.', {'profile_id': profile_id})
        if (isinstance(current.get('content'), dict)
                and ('entry_version' in current or 'profile_id' in current or 'entry_kind' in current)):
            content = current['content']
            version = current.get('entry_version') or content.get('profile_version')
            _require(isinstance(version, str), 'invalid_version',
                     'La entrada vigente no declara version.', {'profile_id': profile_id})
            return version, self._profile_fields(version, content)
        version = current.get('profile_version') or current.get('entry_version')
        _require(isinstance(version, str), 'invalid_version', 'El perfil vigente no declara version.',
                 {'profile_id': profile_id})
        return version, self._profile_fields(version, current)

    def detect_drift_against_registered(self, profile_id, other_entry_id):
        """Compara el snapshot de un perfil contra otra entrada registrada."""
        other = self.get('profile', other_entry_id)
        return self.detect_drift(profile_id, {'entry_version': other['entry_version'], 'content': other['content']})

    def detect_drift(self, profile_id, current):
        """Deriva respecto del ultimo snapshot. Nombra el campo exacto que cambio."""
        snapshot = self.latest_snapshot(profile_id)
        version, fields = self._current_fields(profile_id, current)
        drift = diff_fields(snapshot['fields'], fields)
        return {
            'profile_id': profile_id,
            'drifted': bool(drift),
            'field_count': len(drift),
            'changed_fields': [row['field'] for row in drift],
            'drift': drift,
            'compared_against': {'snapshot_version': snapshot['snapshot_version'],
                                 'entry_version': snapshot['entry_version'],
                                 'snapshot_sha256': snapshot['snapshot_sha256']},
            'declared_entry_version': version,
            'resolution': 'exact_field_diff',
        }

    def is_drifted(self, profile_id, current):
        return self.detect_drift(profile_id, current)['drifted']

    # -- modelos permitidos ------------------------------------------------ #
    def allowed_models(self, profile_id, version=None):
        entry = self.get('profile', profile_id, version)
        payload = entry['content'].get('allowed_models') or []
        if isinstance(payload, dict):
            payload = payload.get('allowed_models') or []
        return copy.deepcopy(payload)

    def model_report(self, profile_id, requested=(), version=None):
        declared = self.allowed_models(profile_id, version)
        known = {item['model_id'] for item in declared}
        requested = list(requested)
        outside = sorted(item for item in requested if item not in known)
        return {
            'profile_id': profile_id,
            'declared_models': sorted(known),
            'declared_count': len(known),
            'requested': requested,
            'outside_declared_set': outside,
            'outside_declared_set_count': len(outside),
            'enabled_models': [],
            'network_calls': 0,
            'resolution': 'declared_set_only',
        }

    def check_model(self, profile_id, model_id, required_capabilities=(), version=None):
        """Compatibilidad declarativa. No habilita nada ni contacta a nadie."""
        declared = self.allowed_models(profile_id, version)
        known = {item['model_id']: item for item in declared}
        if model_id not in known:
            return {'profile_id': profile_id, 'model_id': model_id, 'allowed': False,
                    'reason': 'not_in_allowed_models', 'missing_capabilities': [],
                    'declared_models': sorted(known), 'enabled': False, 'network_calls': 0}
        capabilities = set(known[model_id].get('capabilities') or [])
        missing = sorted(set(required_capabilities) - capabilities)
        return {'profile_id': profile_id, 'model_id': model_id, 'allowed': not missing,
                'reason': 'declared_and_capable' if not missing else 'missing_capability',
                'missing_capabilities': missing, 'declared_capabilities': sorted(capabilities),
                'enabled': False, 'network_calls': 0}

    def compatible_models(self, profile_id, required_capabilities=(), version=None):
        return sorted(item['model_id'] for item in self.allowed_models(profile_id, version)
                      if self.check_model(profile_id, item['model_id'], required_capabilities, version)['allowed'])

    def common_models(self, profile_ids, required_capabilities=()):
        _require(isinstance(profile_ids, list) and len(profile_ids) >= 1, 'invalid_content',
                 'common_models exige al menos un perfil.')
        sets = [set(self.compatible_models(pid, required_capabilities)) for pid in profile_ids]
        shared = set.intersection(*sets) if sets else set()
        return {'profiles': list(profile_ids), 'common_models': sorted(shared),
                'outside_declared_set_count': 0}

    # -- estado inerte ----------------------------------------------------- #
    def inert_report(self):
        counts = dict(self._counters)
        return {
            'registry_version': REGISTRY_VERSION,
            'registry_entry_version': REGISTRY_VERSION,
            'entries': len(self._entries),
            'entry_kinds': {kind: sum(1 for key in self._entries if key[0] == kind) for kind in ENTRY_KINDS},
            'flags': dict(INERT_FLAGS),
            'counters': counts,
            'install_capability': False,
            'grant_capability': False,
            'tool_scope_mutated': False,
            'skills_written': 0,
            'inert_by_default': True,
            'note': 'Registrar, versionar y validar son operaciones de datos; no instalan ni autorizan.',
        }

    def to_dict(self):
        return {
            'registry_version': REGISTRY_VERSION,
            'entries': [copy.deepcopy(self._entries[key]) for key in sorted(self._entries)],
            'snapshots': {profile_id: [_public_snapshot(row) for row in history]
                          for profile_id, history in sorted(self._snapshots.items())},
            'inert': self.inert_report(),
        }

    def to_json(self):
        return canonical_json(self.to_dict())


def _public_snapshot(snapshot):
    return {key: copy.deepcopy(value) for key, value in snapshot.items() if key != 'fields'}


def registry_capabilities():
    """Vocabulario estable de I2 para consumidores y pruebas de inertitud."""
    return {
        'registry_version': REGISTRY_VERSION,
        'entry_kinds': list(ENTRY_KINDS),
        'contract_version_field': CONTRACT_VERSION_FIELD,
        'error_codes': sorted({'unsupported_version', 'unsupported_entry_kind', 'invalid_version',
                               'missing_hash', 'invalid_hash', 'hash_mismatch', 'duplicate_entry',
                               'duplicate_model', 'unknown_model', 'unknown_entry', 'unknown_snapshot',
                               'missing_provenance', 'prohibited_field', 'install_forbidden',
                               'remote_reference_forbidden', 'embedded_credential', 'path_out_of_scope',
                               'profile_mismatch', 'version_regression', 'invalid_content',
                               'capacity_exceeded'}),
        'flags': dict(INERT_FLAGS),
    }


__all__ = ['AgentRegistry', 'RegistryError', 'REGISTRY_VERSION', 'CONTRACT_VERSION_FIELD',
           'ENTRY_KINDS', 'INERT_FLAGS', 'canonical_json', 'sha256_of', 'sha256_of_bytes', 'now_iso',
           'entry_hash', 'flatten_fields', 'diff_fields', 'credential_like', 'reject_credentials',
           'reject_install_assertions', 'check_local_reference', 'registry_capabilities']
