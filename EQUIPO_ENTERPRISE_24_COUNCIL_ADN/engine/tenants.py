"""Tenant Isolation v1 (flujo I4): fronteras por inquilino con seis dominios aislados.

Contrato consumido: `docs/plataforma/tenant-boundary.schema.json` (TenantBoundary v1,
congelado en R0, huella 7e5fcf46946977d1e4137761409595bdd68e46d8b313798ea5b1a9b47374718a).
Modulo INERTE: declara fronteras y resuelve lecturas y rutas en memoria. No materializa
almacenes, no abre conexiones, no escribe ficheros y no ejecuta agentes.

Reglas congeladas que este modulo implementa:
  * seis dominios aislados obligatorios: `organizations`, `projects`, `sensitive_material`,
    `budgets`, `memories`, `artifacts`;
  * `sensitive_values_stored` y `cross_tenant_read` son `false`; `shared_tenants` es `[]`;
  * toda lectura lleva `tenant_id` explicito y sin coincidencia exacta se deniega con error
    tipado, nunca con una lista vacia silenciosa;
  * `sensitive_material` designa el dominio y nunca su valor: guardar un valor ahi se
    rechaza con `sensitive_domain_not_materializable`;
  * `memories` y `sensitive_material` nunca se exportan en el paquete; `organizations`,
    `projects` y `artifacts` si.

Codigos de error: los cinco del vocabulario congelado
(`unknown_tenant`, `cross_tenant_denied`, `boundary_version_unsupported`,
`domain_not_declared`, `sensitive_domain_not_materializable`) mas dos propios de I4,
declarados y probados: `invalid_entry` para entradas de forma no valida y
`record_not_found` para una clave ausente dentro del mismo inquilino (la regla congelada
solo prescribe el error tipado para el desajuste de inquilino).

Rutas: `tenant_root()` y `resolve_path()` son aritmetica lexica de cadenas. Este modulo no
importa `os` ni `pathlib` ni toca el disco: garantiza por construccion que toda ruta
resuelta queda dentro del directorio del inquilino y rechaza rutas absolutas, unidades de
disco, UNC, URL, caracteres de control, dos puntos (unidad o flujo alternativo) y cualquier
segmento `..`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone

try:  # importacion como paquete del motor
    from .policy_engine import (PROHIBITED_FIELDS, PROHIBITED_FIELDS_SOURCE,
                                find_prohibited_fields)
except ImportError:  # raiz de la suite en sys.path
    from policy_engine import (PROHIBITED_FIELDS, PROHIBITED_FIELDS_SOURCE,
                               find_prohibited_fields)

TENANT_BOUNDARY_VERSION = '1'
BOUNDARY_VERSION_FIELD = 'tenant_boundary_version'

DOMAINS = ('organizations', 'projects', 'sensitive_material', 'budgets', 'memories', 'artifacts')
STORE_KINDS = ('none', 'local_directory', 'in_memory')
ERROR_CODES = ('unknown_tenant', 'cross_tenant_denied', 'boundary_version_unsupported',
               'domain_not_declared', 'sensitive_domain_not_materializable')
I4_ERROR_CODES = ('invalid_entry', 'record_not_found', 'prohibited_field')

DEFAULT_EXPORTED_DOMAINS = ('organizations', 'projects', 'artifacts')
NEVER_EXPORTED_DOMAINS = ('sensitive_material', 'memories')
SENSITIVE_VALUES_STORED = False
CROSS_TENANT_READ = False
SHARED_TENANTS = ()
OPEN_CONNECTIONS = False
READ_RULE = ('toda lectura lleva tenant_id explicito; sin coincidencia exacta se deniega con '
             'error tipado, nunca con una lista vacia silenciosa')

#: Reglas por defecto: `sensitive_material` no se materializa y `memories` no se exporta.
#: Los dominios exportados por defecto son los tres de `$defs.isolation_rules
#: .default_exported_domains` (`organizations`, `projects`, `artifacts`); `budgets` queda fuera
#: de la lista exportada por defecto porque la anotacion del contrato solo enumera tres.
DEFAULT_DOMAIN_RULES = {
    'organizations': {'store_kind': 'in_memory', 'cross_tenant_read': False,
                      'shared_between_tenants': False, 'exported_in_package': True},
    'projects': {'store_kind': 'in_memory', 'cross_tenant_read': False,
                 'shared_between_tenants': False, 'exported_in_package': True},
    'sensitive_material': {'store_kind': 'none', 'cross_tenant_read': False,
                           'shared_between_tenants': False, 'exported_in_package': False},
    'budgets': {'store_kind': 'in_memory', 'cross_tenant_read': False,
                'shared_between_tenants': False, 'exported_in_package': False},
    'memories': {'store_kind': 'in_memory', 'cross_tenant_read': False,
                 'shared_between_tenants': False, 'exported_in_package': False},
    'artifacts': {'store_kind': 'in_memory', 'cross_tenant_read': False,
                  'shared_between_tenants': False, 'exported_in_package': True},
}

BOUNDARY_FIELDS = ('tenant_boundary_version', 'tenant_id', 'organization_id', 'display_name',
                   'isolated_domains', 'domain_rules', 'sensitive_values_stored',
                   'cross_tenant_read', 'shared_tenants', 'project_ids', 'declared_limits',
                   'created_at')
BOUNDARY_REQUIRED_FIELDS = ('tenant_boundary_version', 'tenant_id', 'organization_id',
                            'isolated_domains', 'domain_rules', 'sensitive_values_stored',
                            'cross_tenant_read', 'shared_tenants', 'created_at')
DOMAIN_RULE_FIELDS = ('store_kind', 'cross_tenant_read', 'shared_between_tenants',
                      'exported_in_package')
LIMIT_FIELDS = ('money_usd_max', 'tokens_max', 'network_allowed')

_TENANT_ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,63}$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_INSTANT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
_DRIVE_RE = re.compile(r'^[A-Za-z]:')
TENANT_ROOT_PREFIX = 'tenants'


class TenantError(ValueError):
    """Rechazo tipado de la capa de aislamiento. `code` pertenece al vocabulario declarado."""

    def __init__(self, code, message):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate_tenant_id(value, field='tenant_id'):
    if not isinstance(value, str) or not _TENANT_ID_RE.match(value):
        raise TenantError('invalid_entry', (
            '%s debe cumplir el patron del contrato v1 (2..64 de [a-z0-9._-], primer caracter '
            'alfanumerico).' % field))
    return value


def validate_instant(value, field):
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        raise TenantError('invalid_entry', (
            '%s debe ser un instante ISO-8601 UTC terminado en Z.' % field))
    return value


def validate_uuid(value, field):
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise TenantError('invalid_entry', (
            '%s debe ser un UUID en minusculas (contrato v1).' % field))
    return value


def _reject_prohibited(payload, where):
    hits = find_prohibited_fields(payload)
    if hits:
        raise TenantError('prohibited_field', (
            'La %s contiene campos con forma de credencial o consentimiento (%s); la capa no los '
            'admite ni los registra. Guard reutilizado de %s.'
            % (where, ', '.join(sorted(hits)), PROHIBITED_FIELDS_SOURCE)))


def tenant_root(tenant_id):
    """Raiz logica del inquilino. No es una ruta fisica y no se toca el disco."""
    validate_tenant_id(tenant_id)
    return '%s/%s' % (TENANT_ROOT_PREFIX, tenant_id)


def resolve_path(tenant_id, relative):
    """Ruta logica dentro de la raiz del inquilino, o `outside_tenant_root` tipado.

    Aritmetica lexica pura: sin `os`, sin `pathlib` y sin acceso a disco. Se rechazan rutas
    absolutas, unidades de disco, UNC, URL, caracteres de control y cualquier segmento `..`.
    """
    root = tenant_root(tenant_id)
    if not isinstance(relative, str) or not relative.strip():
        raise TenantError('outside_tenant_root', (
            'La ruta relativa del inquilino %s no puede estar vacia.' % tenant_id))
    text = relative.strip().replace('\\', '/')
    if any(ord(character) < 32 for character in text):
        raise TenantError('outside_tenant_root', 'La ruta contiene caracteres de control.')
    if text.startswith('/') or text.startswith('//') or _DRIVE_RE.match(text) or '://' in text:
        raise TenantError('outside_tenant_root', (
            "La ruta '%s' es absoluta, UNC o una URL y sale del directorio del inquilino %s."
            % (relative, tenant_id)))
    segments = [segment for segment in text.split('/') if segment not in ('', '.')]
    if not segments or any(segment == '..' for segment in segments):
        raise TenantError('outside_tenant_root', (
            "La ruta '%s' contiene un recorrido de directorio y sale del inquilino %s."
            % (relative, tenant_id)))
    if any(':' in segment for segment in segments):
        raise TenantError('outside_tenant_root', (
            "La ruta '%s' usa dos puntos (unidad de disco o flujo alternativo) y no se admite "
            'dentro del inquilino %s.' % (relative, tenant_id)))
    return '%s/%s' % (root, '/'.join(segments))


def path_belongs_to(tenant_id, path):
    """True solo si la ruta resuelta esta dentro de la raiz de ese inquilino."""
    root = tenant_root(tenant_id)
    if not isinstance(path, str):
        return False
    normalized = path.replace('\\', '/')
    return normalized == root or normalized.startswith(root + '/')


def require_path_belongs_to(tenant_id, path):
    if not path_belongs_to(tenant_id, path):
        raise TenantError('outside_tenant_root', (
            "La ruta '%s' no pertenece al directorio del inquilino %s." % (path, tenant_id)))
    return path


def _validated_domain_rules(rules):
    if not isinstance(rules, dict) or set(rules) != set(DOMAINS):
        raise TenantError('domain_not_declared', (
            'domain_rules debe declarar exactamente los seis dominios aislados.'))
    normalized = {}
    for domain in DOMAINS:
        rule = rules[domain]
        if not isinstance(rule, dict) or set(rule) != set(DOMAIN_RULE_FIELDS):
            raise TenantError('invalid_entry', (
                'domain_rules[%s] debe declarar exactamente %s.' % (domain, DOMAIN_RULE_FIELDS)))
        if rule['store_kind'] not in STORE_KINDS:
            raise TenantError('invalid_entry', 'domain_rules[%s].store_kind no admite %r.'
                              % (domain, rule['store_kind']))
        if rule['cross_tenant_read'] is not False or rule['shared_between_tenants'] is not False:
            raise TenantError('cross_tenant_denied', (
                'domain_rules[%s] intenta abrir lectura o uso compartido entre inquilinos; el '
                'contrato v1 lo fija en false.' % domain))
        if not isinstance(rule['exported_in_package'], bool):
            raise TenantError('invalid_entry', 'domain_rules[%s].exported_in_package debe ser '
                              'booleano.' % domain)
        if domain in NEVER_EXPORTED_DOMAINS and rule['exported_in_package']:
            raise TenantError('invalid_entry', (
                "domain_rules[%s].exported_in_package no puede ser true: '%s' nunca viaja en el "
                'paquete.' % (domain, domain)))
        normalized[domain] = dict(rule)
    if normalized['sensitive_material']['store_kind'] != 'none':
        raise TenantError('sensitive_domain_not_materializable', (
            "domain_rules[sensitive_material].store_kind debe ser 'none': el contrato declara el "
            'dominio y nunca el valor.'))
    return normalized


class TenantBoundary:
    """Frontera declarada de un inquilino: datos versionados con hash reproducible."""

    def __init__(self, data):
        if not isinstance(data, dict):
            raise TenantError('invalid_entry', 'La frontera debe ser un objeto JSON.')
        version = data.get(BOUNDARY_VERSION_FIELD)
        if version != TENANT_BOUNDARY_VERSION:
            raise TenantError('boundary_version_unsupported', (
                'La frontera declara %s=%r; esta capa solo soporta %r y no degrada a otra '
                'interpretacion.' % (BOUNDARY_VERSION_FIELD, version, TENANT_BOUNDARY_VERSION)))
        unknown = sorted(str(key) for key in data if key not in BOUNDARY_FIELDS)
        _reject_prohibited(data, 'frontera')
        if unknown:
            raise TenantError('invalid_entry', 'Campos no admitidos en la frontera: %s.'
                              % ', '.join(unknown))
        missing = [field for field in BOUNDARY_REQUIRED_FIELDS if field not in data]
        if missing:
            raise TenantError('invalid_entry', 'Faltan campos requeridos en la frontera: %s.'
                              % ', '.join(missing))
        self._tenant_id = validate_tenant_id(data['tenant_id'])
        self._organization_id = validate_uuid(data['organization_id'], 'organization_id')
        display_name = data.get('display_name')
        if display_name is not None and (not isinstance(display_name, str)
                                         or not 1 <= len(display_name) <= 160):
            raise TenantError('invalid_entry', 'display_name debe ser texto de 1 a 160 caracteres.')
        isolated = data['isolated_domains']
        if (not isinstance(isolated, list) or len(set(isolated)) != len(isolated)
                or set(isolated) != set(DOMAINS)):
            raise TenantError('domain_not_declared', (
                'isolated_domains debe declarar exactamente los seis dominios aislados.'))
        self._domain_rules = _validated_domain_rules(data['domain_rules'])
        if data['sensitive_values_stored'] is not False:
            raise TenantError('sensitive_domain_not_materializable', (
                'sensitive_values_stored es const false en el contrato v1.'))
        if data['cross_tenant_read'] is not False:
            raise TenantError('cross_tenant_denied', 'cross_tenant_read es const false en el '
                              'contrato v1.')
        if list(data['shared_tenants']) != list(SHARED_TENANTS):
            raise TenantError('cross_tenant_denied', (
                'shared_tenants debe ser [] en el contrato v1; compartir exigiria otra version.'))
        project_ids = data.get('project_ids', [])
        if not isinstance(project_ids, list) or len(set(project_ids)) != len(project_ids):
            raise TenantError('invalid_entry', 'project_ids debe ser una lista sin repetidos.')
        for project_id in project_ids:
            validate_uuid(project_id, 'project_ids[]')
        limits = data.get('declared_limits', {'network_allowed': False})
        if not isinstance(limits, dict) or set(limits) - set(LIMIT_FIELDS):
            raise TenantError('invalid_entry', 'declared_limits solo admite %s.' % (LIMIT_FIELDS,))
        if limits.get('network_allowed') is not False:
            raise TenantError('invalid_entry', 'declared_limits.network_allowed es const false.')
        for field in ('money_usd_max', 'tokens_max'):
            value = limits.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or value < 0):
                raise TenantError('invalid_entry', 'declared_limits.%s debe ser no negativo o '
                                  'null.' % field)
        self._created_at = validate_instant(data['created_at'], 'created_at')
        self._data = {
            BOUNDARY_VERSION_FIELD: TENANT_BOUNDARY_VERSION,
            'tenant_id': self._tenant_id,
            'organization_id': self._organization_id,
            'isolated_domains': list(DOMAINS),
            'domain_rules': self._domain_rules,
            'sensitive_values_stored': False,
            'cross_tenant_read': False,
            'shared_tenants': [],
            'project_ids': list(project_ids),
            'declared_limits': dict(limits),
            'created_at': self._created_at,
        }
        if display_name is not None:
            self._data['display_name'] = display_name

    @classmethod
    def default(cls, tenant_id, organization_id, *, display_name=None, created_at=None,
                project_ids=None, declared_limits=None, overrides=None):
        """Frontera v1 por defecto: seis dominios aislados, sin material sensible, sin compartir."""
        data = {
            BOUNDARY_VERSION_FIELD: TENANT_BOUNDARY_VERSION,
            'tenant_id': tenant_id,
            'organization_id': organization_id,
            'isolated_domains': list(DOMAINS),
            'domain_rules': copy.deepcopy(DEFAULT_DOMAIN_RULES),
            'sensitive_values_stored': False,
            'cross_tenant_read': False,
            'shared_tenants': [],
            'project_ids': list(project_ids or []),
            'declared_limits': dict(declared_limits or {'network_allowed': False}),
            'created_at': created_at if created_at is not None else utc_now(),
        }
        if display_name is not None:
            data['display_name'] = display_name
        if overrides:
            if not isinstance(overrides, dict) or not overrides:
                raise TenantError('invalid_entry', 'overrides exige un objeto de cambios no vacio.')
            for key, value in overrides.items():
                if key == 'domain_rules' and isinstance(value, dict):
                    merged = copy.deepcopy(data['domain_rules'])
                    for domain, rule in value.items():
                        if domain not in merged:
                            raise TenantError('domain_not_declared',
                                              'Dominio desconocido en overrides: %r.' % (domain,))
                        merged[domain].update(rule)
                    data['domain_rules'] = merged
                else:
                    data[key] = copy.deepcopy(value)
        return cls(data)

    @classmethod
    def from_dict(cls, data):
        return cls(data)

    def as_dict(self):
        return copy.deepcopy(self._data)

    @property
    def boundary_hash(self):
        return sha256_text(canonical(self._data))

    @property
    def tenant_id(self):
        return self._tenant_id

    @property
    def organization_id(self):
        return self._organization_id

    @property
    def isolated_domains(self):
        return tuple(self._data['isolated_domains'])

    @property
    def domain_rules(self):
        return copy.deepcopy(self._domain_rules)

    @property
    def declared_limits(self):
        return copy.deepcopy(self._data['declared_limits'])

    @property
    def project_ids(self):
        return tuple(self._data['project_ids'])

    @property
    def created_at(self):
        return self._created_at

    @property
    def root(self):
        return tenant_root(self._tenant_id)

    def rule(self, domain):
        if domain not in DOMAINS:
            raise TenantError('domain_not_declared', (
                "El dominio %r no pertenece a los seis dominios aislados del contrato v1; la "
                'lectura no se resuelve con una lista vacia.' % (domain,)))
        return dict(self._domain_rules[domain])

    def exported_domains(self):
        return tuple(domain for domain in DOMAINS if self._domain_rules[domain]['exported_in_package'])

    def never_exported_domains(self):
        return tuple(domain for domain in DOMAINS
                     if not self._domain_rules[domain]['exported_in_package'])

    def resolve(self, relative):
        return resolve_path(self._tenant_id, relative)

    def __repr__(self):
        return 'TenantBoundary(%s org=%s hash=%s)' % (self._tenant_id, self._organization_id,
                                                      self.boundary_hash[:12])


class TenantRegistry:
    """Registro en memoria de fronteras y entradas por dominio. Cero escritura en disco.

    Toda lectura exige `requester_tenant` explicito y se resuelve solo con coincidencia exacta.
    Una discrepancia lanza `cross_tenant_denied`; nunca devuelve una lista vacia silenciosa.
    """

    def __init__(self):
        self._boundaries = {}
        self._entries = {domain: {} for domain in DOMAINS}

    def register(self, boundary):
        if not isinstance(boundary, TenantBoundary):
            raise TenantError('invalid_entry', 'register exige una TenantBoundary v1.')
        existing = self._boundaries.get(boundary.tenant_id)
        if existing is not None and existing.boundary_hash != boundary.boundary_hash:
            raise TenantError('invalid_entry', (
                'La frontera de %s ya esta registrada con otra huella; registrar una version '
                'distinta exige sustituirla explicitamente.' % boundary.tenant_id))
        self._boundaries[boundary.tenant_id] = boundary
        return boundary

    def boundary(self, tenant_id):
        if not isinstance(tenant_id, str) or tenant_id not in self._boundaries:
            raise TenantError('unknown_tenant', (
                'El inquilino %r no esta registrado; no se resuelve con una lista vacia.'
                % (tenant_id,)))
        return self._boundaries[tenant_id]

    def tenants(self):
        return tuple(sorted(self._boundaries))

    def _rule(self, boundary, domain):
        return boundary.rule(domain)

    def _key(self, tenant_id, domain, key):
        if not isinstance(key, str) or not key.strip() or len(key) > 120 or any(ord(c) < 32 for c in key):
            raise TenantError('invalid_entry', (
                'La clave debe ser texto legible de 1 a 120 caracteres.'))
        return '%s:%s:%s' % (tenant_id, domain, key)

    def store(self, tenant_id, domain, key, value):
        """Guarda una entrada en el dominio del inquilino. Material sensible: nunca."""
        boundary = self.boundary(tenant_id)
        rule = self._rule(boundary, domain)
        if domain == 'sensitive_material' or rule['store_kind'] == 'none':
            raise TenantError('sensitive_domain_not_materializable', (
                "El dominio '%s' del inquilino %s no materializa valores: el contrato declara el "
                'dominio y nunca el valor.' % (domain, tenant_id)))
        _reject_prohibited({'value': value}, 'entrada')
        qualified = self._key(tenant_id, domain, key)
        self._entries[domain][qualified] = {'tenant_id': tenant_id, 'domain': domain,
                                            'key': key, 'value': copy.deepcopy(value)}
        return qualified

    def read(self, requester_tenant, owner_tenant, domain, key=None):
        """Lectura con inquilino explicito. Sin coincidencia exacta: error tipado.

        Orden determinista: se validan ambos inquilinos (`unknown_tenant`) y despues la
        coincidencia (`cross_tenant_denied`). Nunca devuelve una lista vacia por desajuste.
        """
        self.boundary(requester_tenant)
        boundary = self.boundary(owner_tenant)
        if requester_tenant != owner_tenant:
            raise TenantError('cross_tenant_denied', (
                'El inquilino %s no puede leer el dominio %s del inquilino %s; la lectura entre '
                'inquilinos se deniega con error tipado.'
                % (requester_tenant, domain, owner_tenant)))
        self._rule(boundary, domain)
        if key is None:
            return self.ids(owner_tenant, domain)
        qualified = self._key(owner_tenant, domain, key)
        entry = self._entries[domain].get(qualified)
        if entry is None:
            raise TenantError('record_not_found', (
                "El inquilino %s no tiene la clave %r en el dominio '%s'."
                % (owner_tenant, key, domain)))
        return copy.deepcopy(entry['value'])

    def ids(self, tenant_id, domain):
        boundary = self.boundary(tenant_id)
        self._rule(boundary, domain)
        prefix = '%s:%s:' % (tenant_id, domain)
        return tuple(sorted(entry['key'] for qualified, entry in self._entries[domain].items()
                            if qualified.startswith(prefix)))

    def qualified_ids(self, tenant_id, domain):
        """Identificadores calificados con el inquilino: el espacio de nombres es del inquilino."""
        boundary = self.boundary(tenant_id)
        self._rule(boundary, domain)
        prefix = '%s:%s:' % (tenant_id, domain)
        return tuple(sorted(qualified for qualified in self._entries[domain]
                            if qualified.startswith(prefix)))

    def qualified_ids_across_tenants(self, domain):
        return {tenant_id: self.qualified_ids(tenant_id, domain) for tenant_id in self.tenants()}

    def ids_across_tenants(self, domain):
        """Identificadores por inquilino: permite comprobar que la interseccion es vacia."""
        for tenant_id in self.tenants():
            self._rule(self.boundary(tenant_id), domain)
        return {tenant_id: self.ids(tenant_id, domain) for tenant_id in self.tenants()}

    def read_budget(self, requester_tenant, owner_tenant):
        self.boundary(requester_tenant)
        boundary = self.boundary(owner_tenant)
        if requester_tenant != owner_tenant:
            raise TenantError('cross_tenant_denied', (
                'El inquilino %s no puede leer el presupuesto del inquilino %s.'
                % (requester_tenant, owner_tenant)))
        self._rule(boundary, 'budgets')
        return boundary.declared_limits

    def read_artifact(self, requester_tenant, owner_tenant, artifact_key):
        return self.read(requester_tenant, owner_tenant, 'artifacts', artifact_key)

    def export_plan(self, tenant_id):
        """Dominios que pueden viajar en el paquete y dominios que nunca lo hacen."""
        boundary = self.boundary(tenant_id)
        return {'tenant_id': tenant_id,
                'exported_in_package': list(boundary.exported_domains()),
                'never_exported_in_package': list(boundary.never_exported_domains())}

    def entry_count(self, tenant_id, domain):
        boundary = self.boundary(tenant_id)
        self._rule(boundary, domain)
        prefix = '%s:%s:' % (tenant_id, domain)
        return sum(1 for qualified in self._entries[domain] if qualified.startswith(prefix))


__all__ = ['TENANT_BOUNDARY_VERSION', 'BOUNDARY_VERSION_FIELD', 'DOMAINS', 'STORE_KINDS',
           'ERROR_CODES', 'I4_ERROR_CODES', 'DEFAULT_EXPORTED_DOMAINS', 'NEVER_EXPORTED_DOMAINS',
           'SENSITIVE_VALUES_STORED', 'CROSS_TENANT_READ', 'SHARED_TENANTS', 'OPEN_CONNECTIONS',
           'READ_RULE', 'DEFAULT_DOMAIN_RULES', 'BOUNDARY_FIELDS', 'BOUNDARY_REQUIRED_FIELDS',
           'DOMAIN_RULE_FIELDS', 'LIMIT_FIELDS', 'PROHIBITED_FIELDS', 'PROHIBITED_FIELDS_SOURCE',
           'TenantError', 'TenantBoundary', 'TenantRegistry', 'tenant_root', 'resolve_path',
           'path_belongs_to', 'require_path_belongs_to', 'validate_tenant_id', 'validate_instant',
           'validate_uuid', 'canonical', 'sha256_text', 'utc_now']
