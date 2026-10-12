"""Evidence Graph INERTE con contradicciones explicitas (flujo I2, Agent OS).

Conecta nodos `claim | file | api | test | tool_output | decision` mediante
aristas de soporte (`supports`), contradiccion (`contradicts`) y dependencia
(`depends_on`), y evalua cada claim con la regla de veredicto congelada en
`docs/plataforma/evidence-node.schema.json` (`$defs.verdict_rules`).

Vocabulario de aceptacion del flujo I2, por orden de evaluacion (el primero que
aplica gana) y proyectado al vocabulario del contrato:

  1. arista `contradicts` (o referencia divergente, ver mas abajo) -> `contradicted`
  2. sin `evidence_refs`                                          -> `unsupported`
  3. con referencias pero ninguna con hash SHA-256 recomprobado   -> `insufficient`
  4. >=1 referencia recomprobada y ninguna contradiccion          -> `supported`

`verdict` (campo del nodo) usa el vocabulario del contrato congelado
(`supported | unevidenced | insufficient | contradicted`); la proyeccion es
`unsupported -> unevidenced`. El estado del grafo se lee con `claim_state()`.

Reglas duras de este modulo:
  * Una contradiccion NUNCA se resuelve por mayoria ni por confianza: no existe
    campo `confidence` (el contrato lo rechaza) y `Resolution` no compara
    cantidades de evidencia. Una arista `contradicts` basta, aunque haya veinte
    referencias verificadas en sentido contrario.
  * `supported` exige un hash SHA-256 declarado de 64 hex recomprobado en esta
    misma ejecucion (archivo local o artefacto local registrado). La ausencia de
    evidencia no se eleva nunca a `supported`.
  * Solo biblioteca estandar; sin red, sin claves, sin proveedores, sin escribir
    en disco, sin instalar nada y sin ejecutar nada. Todo es datos en memoria.
  * Guard de credenciales: lista literal de `engine/project_store.py:19` y
    normalizacion de `engine/project_store.py:38-46`, reutilizados sin alteracion.

Procedencia: el contrato congelado cierra el nodo (`additionalProperties: false`),
asi que la **fecha** viaja en el nodo (`created_at`) y el **origen** en el libro
de procedencia del grafo (`provenance(node_id)`); `origin` es obligatorio al
insertar cualquier nodo.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

try:  # importado como `engine.evidence_graph`
    from .project_store import FORBIDDEN_FIELDS, ProjectStoreError, _reject_secret_fields
except ImportError:  # ejecucion directa del archivo
    from project_store import FORBIDDEN_FIELDS, ProjectStoreError, _reject_secret_fields

GRAPH_VERSION = '1'
FROZEN_SCHEMA_REF = 'docs/plataforma/evidence-node.schema.json'
FROZEN_SCHEMA_SHA256 = '19c364da482b2bfd7f72a3ec33a2be73615e06557b72dd152eb157a4b5e09d8c'
FROZEN_PROHIBITED_FIELDS = ('credentials', 'api_key', 'api_keys', 'pending_consent', 'csrf', 'cookie',
                            'password', 'access_token', 'refresh_token', 'client_secret', 'private_key',
                            'authorization', 'bearer_token')
FROZEN_VERSION_FIELD = 'evidence_node_version'
FROZEN_NODE_KINDS = ('claim', 'evidence', 'decision')
FROZEN_REF_KINDS = ('file', 'api_result', 'tool_result', 'test', 'decision', 'human_record')
FROZEN_RELATIONS = ('supports', 'contradicts', 'depends_on')
FROZEN_VERDICTS = ('supported', 'unevidenced', 'insufficient', 'contradicted')

# Vocabulario de aceptacion del encargo I2 (nodo -> forma del contrato).
NODE_ALIASES = {'claim': 'claim', 'file': 'evidence', 'api': 'evidence', 'test': 'evidence',
                'tool_output': 'evidence', 'decision': 'decision'}
ALIAS_REF_KIND = {'file': 'file', 'api': 'api_result', 'test': 'test',
                  'tool_output': 'tool_result', 'decision': 'decision'}
CLAIM_STATES = ('supported', 'contradicted', 'insufficient', 'unsupported')
SCHEMA_VERDICT = {'supported': 'supported', 'contradicted': 'contradicted',
                  'insufficient': 'insufficient', 'unsupported': 'unevidenced'}
ACCEPTANCE_STATE = {'supported': 'supported', 'contradicted': 'contradicted',
                    'insufficient': 'insufficient', 'unevidenced': 'unsupported'}
# `verified` NO es un estado del grafo: solo existe como bandera booleana de una
# referencia recomprobada. Se declara aqui para que una prueba pueda refutarlo.
STATES_THAT_ARE_NOT_VERDICTS = ('verified',)

SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
ISO_Z_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
NODE_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,63}$')
USERINFO_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+@')
REMOTE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*://')
CREDENTIAL_NAME_RE = re.compile(
    r'(?i)(credential|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer[_-]?token|'
    r'client[_-]?secret|private[_-]?key|password|cookie|csrf|pending[_-]?consent|authorization)')
AUDITED_NON_CREDENTIAL = frozenset({'tokens'})

# Palabras clave de JSON Schema que este validador aplica de verdad. Cualquier
# otra palabra clave en un esquema consumido se reporta como no soportada en
# lugar de ignorarse en silencio (fallo honesto, R-7).
SUPPORTED_KEYWORDS = frozenset({'$ref', 'type', 'enum', 'const', 'required', 'properties',
                                'additionalProperties', 'pattern', 'minLength', 'maxLength',
                                'minItems', 'maxItems', 'uniqueItems', 'items', 'allOf', 'if', 'then',
                                'not', 'propertyNames', 'oneOf', 'minProperties'})
SCHEMA_METADATA_KEYWORDS = frozenset({'$schema', '$id', '$defs', 'title', 'description', 'default',
                                      'version_field', 'prohibited_fields', 'prohibited_fields_source',
                                      'prohibited_fields_rule', 'name_guard', 'inert_by_default',
                                      'inert_by_default_note', 'frozen_by', 'frozen_in_round', 'frozen_at'})
JSON_TYPE_CHECKS = {
    'object': lambda value: isinstance(value, dict),
    'array': lambda value: isinstance(value, (list, tuple)),
    'string': lambda value: isinstance(value, str),
    'integer': lambda value: isinstance(value, int) and not isinstance(value, bool),
    'number': lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    'boolean': lambda value: isinstance(value, bool),
    'null': lambda value: value is None,
}

INERT_FLAGS = {
    'reads_files_for_hashing': True,
    'writes_to_disk': False,
    'network_allowed': False,
    'executes_actions': False,
    'sends_to_providers': False,
    'installs_skills': False,
    'grants_permissions': False,
    'resolves_by_majority': False,
    'resolves_by_confidence': False,
}

SUITE_ROOT = Path(__file__).resolve().parent.parent


class EvidenceGraphError(ValueError):
    """Error tipado del grafo. `code` es el vocabulario estable de I2."""

    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------- #
# Utilidades deterministas y guard de credenciales
# --------------------------------------------------------------------------- #
def canonical_json(value):
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
    if str(name) in AUDITED_NON_CREDENTIAL:
        return False
    camel, stripped = normalized_names(name)
    if camel in FORBIDDEN_FIELDS or stripped in {re.sub(r'[^a-z0-9]', '', item) for item in FORBIDDEN_FIELDS}:
        return True
    return bool(CREDENTIAL_NAME_RE.search(str(name)))


def reject_credentials(value, where='<raiz>'):
    """Rechaza claves con forma de credencial reutilizando el guard del motor."""
    try:
        _reject_secret_fields(value)
    except ProjectStoreError:
        raise EvidenceGraphError('prohibited_field',
                                 'El grafo contiene un campo de credencial o consentimiento.',
                                 {'where': where, 'guard': 'engine/project_store.py:38-46'}) from None
    if isinstance(value, dict):
        for key, item in value.items():
            if credential_like(key):
                raise EvidenceGraphError('prohibited_field',
                                         'Nombre de campo con forma de credencial: %r.' % (key,),
                                         {'where': where, 'field': str(key)})
            reject_credentials(item, '%s.%s' % (where, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_credentials(item, '%s[%d]' % (where, index))
    return True


# --------------------------------------------------------------------------- #
# Validador de subconjunto de JSON Schema (biblioteca estandar)
# --------------------------------------------------------------------------- #
def resolve_ref(ref, root):
    if not isinstance(ref, str) or not ref.startswith('#/'):
        raise EvidenceGraphError('unsupported_schema', 'Solo se admiten referencias locales `#/...`.',
                                 {'$ref': ref})
    node = root
    for part in ref[2:].split('/'):
        if not isinstance(node, dict) or part not in node:
            raise EvidenceGraphError('unsupported_schema', 'Referencia local no resoluble: %s.' % ref,
                                     {'$ref': ref})
        node = node[part]
    return node


def _validate(instance, schema, path, errors, root):
    if not isinstance(schema, dict):
        errors.append('%s: esquema no valido.' % path)
        return
    for keyword in schema:
        if keyword in SCHEMA_METADATA_KEYWORDS or keyword == 'definition':
            continue
        if keyword not in SUPPORTED_KEYWORDS:
            errors.append('%s: palabra clave no soportada por el validador: %s' % (path, keyword))
    if '$ref' in schema:
        _validate(instance, resolve_ref(schema['$ref'], root), path, errors, root)
    if 'type' in schema:
        types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(JSON_TYPE_CHECKS.get(name, lambda _: False)(instance) for name in types):
            errors.append('%s: tipo %s esperado, recibido %s.' % (path, '/'.join(map(str, types)),
                                                                 type(instance).__name__))
            return
    if 'const' in schema and instance != schema['const']:
        errors.append('%s: valor constante %r esperado, recibido %r.' % (path, schema['const'], instance))
    if 'enum' in schema and instance not in schema['enum']:
        errors.append('%s: valor fuera de la enumeracion %r: %r.' % (path, schema['enum'], instance))
    if 'allOf' in schema:
        for sub in schema['allOf']:
            _validate(instance, sub, path, errors, root)
    if 'oneOf' in schema:
        matched = sum(1 for sub in schema['oneOf'] if not _silent_errors(instance, sub, root))
        if matched != 1:
            errors.append('%s: oneOf esperaba exactamente un esquema valido, coincidencias=%d.' % (path, matched))
    if 'if' in schema:
        if not _silent_errors(instance, schema['if'], root):
            if 'then' in schema:
                _validate(instance, schema['then'], path, errors, root)
    if 'not' in schema and not _silent_errors(instance, schema['not'], root):
        errors.append('%s: el valor no puede satisfacer el esquema `not`.' % path)
    if isinstance(instance, str):
        if 'pattern' in schema and not re.search(schema['pattern'], instance):
            errors.append('%s: el valor no casa con el patron %s.' % (path, schema['pattern']))
        if 'minLength' in schema and len(instance) < schema['minLength']:
            errors.append('%s: longitud %d < minLength %d.' % (path, len(instance), schema['minLength']))
        if 'maxLength' in schema and len(instance) > schema['maxLength']:
            errors.append('%s: longitud %d > maxLength %d.' % (path, len(instance), schema['maxLength']))
    if isinstance(instance, (list, tuple)):
        if 'minItems' in schema and len(instance) < schema['minItems']:
            errors.append('%s: %d elementos < minItems %d.' % (path, len(instance), schema['minItems']))
        if 'maxItems' in schema and len(instance) > schema['maxItems']:
            errors.append('%s: %d elementos > maxItems %d.' % (path, len(instance), schema['maxItems']))
        if schema.get('uniqueItems') and len({canonical_json(item) for item in instance}) != len(instance):
            errors.append('%s: elementos duplicados con uniqueItems.' % path)
        if 'items' in schema:
            for index, item in enumerate(instance):
                _validate(item, schema['items'], '%s[%d]' % (path, index), errors, root)
    if isinstance(instance, dict):
        if 'minProperties' in schema and len(instance) < schema['minProperties']:
            errors.append('%s: %d propiedades < minProperties %d.' % (path, len(instance), schema['minProperties']))
        if 'required' in schema:
            for name in schema['required']:
                if name not in instance:
                    errors.append('%s: falta el campo obligatorio %r.' % (path, name))
        if 'propertyNames' in schema:
            for name in instance:
                _validate(name, schema['propertyNames'], '%s<%s>' % (path, name), errors, root)
        properties = schema.get('properties') or {}
        for name, value in instance.items():
            if name in properties:
                _validate(value, properties[name], '%s.%s' % (path, name), errors, root)
                continue
            additional = schema.get('additionalProperties', True)
            if additional is False:
                errors.append('%s: campo no declarado en el contrato congelado: %r.' % (path, name))
            elif isinstance(additional, dict):
                _validate(value, additional, '%s.%s' % (path, name), errors, root)


def _silent_errors(instance, schema, root):
    errors = []
    _validate(instance, schema, '<test>', errors, root)
    return errors


def validate_instance(instance, schema):
    """Valida una instancia contra el subconjunto declarado. Devuelve lista de errores."""
    errors = []
    _validate(instance, schema, '<raiz>', errors, schema)
    return errors


def load_frozen_schema(schema_path=None, strict=True, expected_sha256=None):
    """Carga el contrato congelado y verifica su identidad antes de usarlo."""
    path = Path(schema_path) if schema_path is not None else SUITE_ROOT / FROZEN_SCHEMA_REF
    if not path.is_file():
        raise EvidenceGraphError('missing_schema', 'No se encuentra el contrato congelado.',
                                 {'path': str(path), 'expected': FROZEN_SCHEMA_REF})
    raw = path.read_bytes()
    digest = sha256_of_bytes(raw)
    expected = expected_sha256 or (FROZEN_SCHEMA_SHA256 if strict else None)
    if expected is not None and digest != expected:
        raise EvidenceGraphError('unsupported_schema',
                                 'El contrato en disco no es la version congelada v1; un cambio exige v2.',
                                 {'path': str(path), 'expected_sha256': expected, 'observed_sha256': digest})
    try:
        schema = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise EvidenceGraphError('invalid_schema', 'El contrato no es JSON valido: %r.' % (exc,),
                                 {'path': str(path)}) from None
    if schema.get('version_field') != FROZEN_VERSION_FIELD:
        raise EvidenceGraphError('unsupported_schema', 'Campo de version distinto del congelado.',
                                 {'version_field': schema.get('version_field')})
    if tuple(schema.get('prohibited_fields') or ()) != FROZEN_PROHIBITED_FIELDS:
        raise EvidenceGraphError('unsupported_schema',
                                 'La lista de campos prohibidos no es la literal de engine/project_store.py:19.',
                                 {'prohibited_fields': schema.get('prohibited_fields')})
    if schema.get('inert_by_default') is not True:
        raise EvidenceGraphError('unsupported_schema', 'El contrato no declara inert_by_default.',
                                 {'inert_by_default': schema.get('inert_by_default')})
    declared_kinds = tuple((schema.get('properties') or {}).get('node_kind', {}).get('enum') or ())
    if declared_kinds and declared_kinds != FROZEN_NODE_KINDS:
        raise EvidenceGraphError('unsupported_schema', 'La enumeracion de node_kind cambio.',
                                 {'node_kind': list(declared_kinds)})
    declared_verdicts = tuple((schema.get('properties') or {}).get('verdict', {}).get('enum') or ())
    if declared_verdicts and declared_verdicts != FROZEN_VERDICTS:
        raise EvidenceGraphError('unsupported_schema', 'La enumeracion de verdict cambio.',
                                 {'verdict': list(declared_verdicts)})
    return {'schema': schema, 'sha256': digest, 'path': str(path), 'ref': FROZEN_SCHEMA_REF}


# --------------------------------------------------------------------------- #
# Grafo
# --------------------------------------------------------------------------- #
class EvidenceGraph:
    """Grafo de evidencia en memoria: registra, verifica y contradice. No ejecuta."""

    def __init__(self, root=None, schema_path=None, strict_schema=True):
        self.root = Path(root).expanduser().resolve() if root is not None else SUITE_ROOT
        loaded = load_frozen_schema(schema_path, strict=strict_schema)
        self.schema = loaded['schema']
        self.schema_sha256 = loaded['sha256']
        self.schema_path = loaded['path']
        self._nodes = {}
        self._provenance = {}
        self._artifacts = {}
        self._counters = {'write_operations': 0, 'network_calls': 0, 'executed_actions': 0,
                          'permission_grants': 0, 'tool_scope_mutations': 0}

    # -- alta de nodos ----------------------------------------------------- #
    def _local_path(self, relative):
        if not isinstance(relative, str) or not relative:
            return None
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            return None
        return candidate

    def _coerce_ref(self, ref):
        if isinstance(ref, dict):
            return copy.deepcopy(ref)
        if isinstance(ref, (tuple, list)):
            if len(ref) == 2:
                return {'kind': ref[0], 'ref': ref[1]}
            if len(ref) == 3:
                return {'kind': ref[0], 'ref': ref[1], 'sha256': ref[2]}
            if len(ref) == 4:
                return {'kind': ref[0], 'ref': ref[1], 'sha256': ref[2], 'locator': ref[3]}
            raise EvidenceGraphError('invalid_reference', 'Una referencia admite 2 a 4 elementos.',
                                     {'reference': list(ref)})
        raise EvidenceGraphError('invalid_reference', 'Formato de referencia no admitido.',
                                 {'reference': repr(ref)})

    def _provenance_entry(self, origin, recorded_at, provenance):
        if provenance is not None:
            if not isinstance(provenance, dict):
                raise EvidenceGraphError('missing_provenance', 'provenance debe ser un objeto.')
            origin = provenance.get('origin', origin)
            recorded_at = provenance.get('recorded_at', recorded_at)
        if not isinstance(origin, str) or not origin.strip():
            raise EvidenceGraphError('missing_provenance',
                                     'Cada nodo exige procedencia: `origin` no vacio.',
                                     {'guard': 'docs/plataforma/evidence-node.schema.json'})
        recorded_at = recorded_at or now_iso()
        if not isinstance(recorded_at, str) or not ISO_Z_RE.match(recorded_at):
            raise EvidenceGraphError('missing_provenance', 'La procedencia exige fecha ISO-8601 UTC.',
                                     {'recorded_at': recorded_at})
        if USERINFO_RE.match(origin):
            raise EvidenceGraphError('embedded_credential', 'El origen contiene credenciales embebidas.',
                                     {'origin': origin})
        return {'origin': origin.strip(), 'recorded_at': recorded_at}

    def add_node(self, node_id, node_kind, statement, tenant_id, evidence_refs=(), edges=(),
                 plane=None, created_at=None, superseded_by=None, origin=None, recorded_at=None,
                 provenance=None):
        """Inserta un nodo con la forma del contrato congelado. Nunca lo ejecuta."""
        if not isinstance(node_id, str) or not NODE_ID_RE.match(node_id):
            raise EvidenceGraphError('invalid_node', 'node_id debe casar con el patron del contrato.',
                                     {'node_id': node_id})
        if node_id in self._nodes:
            raise EvidenceGraphError('duplicate_node', 'Un nodo no se reescribe; se supera.',
                                     {'node_id': node_id})
        if node_kind not in FROZEN_NODE_KINDS:
            raise EvidenceGraphError('invalid_node', 'node_kind fuera del contrato.', {'node_kind': node_kind})
        if not isinstance(statement, str) or not statement.strip():
            raise EvidenceGraphError('invalid_node', 'statement no puede estar vacio.', {'node_id': node_id})
        if not isinstance(tenant_id, str) or not re.match(r'^[a-z0-9][a-z0-9._-]{2,63}$', tenant_id):
            raise EvidenceGraphError('invalid_node', 'tenant_id es obligatorio y debe casar el patron.',
                                     {'node_id': node_id, 'tenant_id': tenant_id})
        ledger = self._provenance_entry(origin, recorded_at, provenance)
        refs = [self._coerce_ref(ref) for ref in evidence_refs]
        node = {
            FROZEN_VERSION_FIELD: GRAPH_VERSION,
            'node_id': node_id,
            'node_kind': node_kind,
            'statement': statement,
            'verdict': 'unevidenced',
            'evidence_refs': refs,
            'edges': [],
            'tenant_id': tenant_id,
            'created_at': created_at or now_iso(),
        }
        if plane is not None:
            node['plane'] = plane
        if superseded_by is not None:
            node['superseded_by'] = superseded_by
        for edge in edges:
            node['edges'].append(self._coerce_edge(edge))
        reject_credentials(node, where='node:%s' % node_id)
        errors = validate_instance(node, self.schema)
        if errors:
            raise EvidenceGraphError('invalid_node', 'El nodo no cumple el contrato congelado.',
                                     {'node_id': node_id, 'errors': errors})
        self._assert_edges_resolvable(node)
        self._nodes[node_id] = node
        self._provenance[node_id] = ledger
        # Insertar un nodo puede cambiar la topologia de contradicciones de los claims
        # ya registrados, asi que los derivados se recomponen de forma determinista.
        self._refresh_affected(extra=(node_id,))
        return copy.deepcopy(node)

    def refresh(self, node_id):
        """Actualiza SOLO los campos derivados: la bandera `verified` y el `verdict`.

        Nunca toca `statement`, `node_kind`, la identidad de cada referencia
        (`kind`, `ref`, `sha256`, `locator`), las aristas ni la procedencia: un nodo
        no se edita, se supera. La recomprobacion es la de esta ejecucion, asi que
        `verified` nunca se eleva por una declaracion previa.
        """
        node = self._node(node_id)
        for ref in node['evidence_refs']:
            ref['verified'] = bool(self._recompute_ref(ref)['verified_flag'])
        node['verdict'] = self._derived_verdict(node_id)
        errors = validate_instance(node, self.schema)
        if errors:
            raise EvidenceGraphError('invalid_node', 'El nodo derivado sale del contrato congelado.',
                                     {'node_id': node_id, 'errors': errors})
        return copy.deepcopy(node)

    def _derived_verdict(self, node_id):
        """Regla congelada de `$defs.verdict_rules`, en el mismo orden.

        En un claim: sin referencias ⇒ `unevidenced`; con referencias y ningun hash
        recomprobado ⇒ `insufficient`; con al menos uno recomprobado y sin
        contradiccion ⇒ `supported`; con contradiccion ⇒ `contradicted`. En un nodo
        de evidencia o de decision la misma regla se lee sobre su propia referencia:
        `supported` significa que su hash declarado se recomprobo en esta ejecucion,
        no que la accion ocurriera.
        """
        node = self._node(node_id)
        if node_id in self.contradicted_nodes():
            return 'contradicted'
        if not node['evidence_refs']:
            return 'unevidenced'
        if not any(self._recompute_ref(ref)['verified_flag'] for ref in node['evidence_refs']):
            return 'insufficient'
        return 'supported'

    def _refresh_affected(self, extra=(), evidence_ref=None):
        """Recompone los derivados de los claims y de los nodos citados."""
        targets = {node_id for node_id, node in self._nodes.items() if node['node_kind'] == 'claim'}
        targets.update(node_id for node_id in extra if node_id in self._nodes)
        if evidence_ref is not None:
            kind, label = evidence_ref
            targets.update(node_id for node_id, node in self._nodes.items()
                           if any(ref['kind'] == kind and ref['ref'] == label for ref in node['evidence_refs']))
        for node_id in sorted(targets):
            self.refresh(node_id)
        return True

    def _coerce_edge(self, edge):
        if not isinstance(edge, dict):
            raise EvidenceGraphError('invalid_edge', 'Cada arista debe ser un objeto.', {'edge': repr(edge)})
        if edge.get('relation') not in FROZEN_RELATIONS:
            raise EvidenceGraphError('invalid_edge', 'Relacion fuera del contrato.',
                                     {'relation': edge.get('relation')})
        result = {'target_node_id': edge.get('target_node_id'), 'relation': edge['relation']}
        if edge.get('note') is not None:
            result['note'] = edge['note']
        return result

    def _assert_edges_resolvable(self, node):
        for edge in node['edges']:
            target = edge['target_node_id']
            if target == node['node_id']:
                raise EvidenceGraphError('invalid_edge', 'Auto-arista no admitida.',
                                         {'node_id': node['node_id']})
            if not isinstance(target, str) or not NODE_ID_RE.match(target):
                raise EvidenceGraphError('invalid_edge', 'target_node_id debe casar el patron del contrato.',
                                         {'target_node_id': target})
        return True

    def _dup_edge(self, node, edge):
        return any(existing['target_node_id'] == edge['target_node_id']
                   and existing['relation'] == edge['relation'] for existing in node['edges'])

    def _recompute_ref(self, ref):
        """Recomprobacion honesta: sin bytes locales no hay verificacion."""
        kind = ref.get('kind')
        label = ref.get('ref')
        declared = ref.get('sha256')
        if kind == 'file':
            path = self._local_path(label)
            if path is None:
                return {'recompute_basis': 'file_unavailable', 'recomputed': False,
                        'verified_flag': False, 'observed_sha256': None}
            observed = sha256_of_bytes(path.read_bytes())
            return {'recompute_basis': 'file_sha256', 'recomputed': True,
                    'verified_flag': bool(declared) and declared == observed,
                    'observed_sha256': observed}
        artifact = self._artifacts.get((kind, label)) or self._artifacts.get((None, label))
        if artifact is not None:
            path = self._local_path(artifact)
            if path is not None:
                observed = sha256_of_bytes(path.read_bytes())
                matched = bool(declared) and declared == observed
                return {'recompute_basis': 'local_artifact_sha256', 'recomputed': True,
                        'verified_flag': matched, 'observed_sha256': observed,
                        'artifact_ref': artifact}
        return {'recompute_basis': 'not_recomputable', 'recomputed': False,
                'verified_flag': False, 'observed_sha256': None}

    def attach_artifact(self, ref_kind, ref, relative_path):
        """Registra (solo lectura) el artefacto local que respalda una referencia."""
        if relative_path is None:
            return None
        path = self._local_path(relative_path)
        if path is None:
            raise EvidenceGraphError('artifact_unavailable',
                                     'El artefacto local no existe o sale del arbol autorizado.',
                                     {'artifact_ref': relative_path})
        self._artifacts[(ref_kind, ref)] = relative_path
        digest = sha256_of_bytes(path.read_bytes())
        self._refresh_affected(evidence_ref=(ref_kind, ref))
        return {'artifact_ref': relative_path, 'sha256': digest}

    # -- constructores por alias (claim | file | api | test | tool_output | decision) - #
    def _evidence_node(self, alias, node_id, statement, tenant_id, ref, **kwargs):
        ref_kind = ALIAS_REF_KIND.get(alias)
        if ref_kind is None:
            raise EvidenceGraphError('invalid_node', 'Alias de nodo no admitido.',
                                     {'alias': alias, 'admitted': sorted(NODE_ALIASES) + ['evidence']})
        artifact = kwargs.pop('artifact', None)
        declared = kwargs.pop('sha256', None)
        locator = kwargs.pop('locator', None)
        observed_at = kwargs.pop('observed_at', None)
        if artifact is not None:
            self.attach_artifact(ref_kind, ref, artifact)
        if alias == 'file' and declared is None:
            path = self._local_path(ref)
            if path is None:
                raise EvidenceGraphError('file_unavailable',
                                         'Una referencia de tipo file exige hash y el archivo local no existe.',
                                         {'ref': ref})
            declared = sha256_of_bytes(path.read_bytes())
        ref_dict = {'kind': ref_kind, 'ref': ref}
        if declared is not None:
            if not isinstance(declared, str) or not SHA256_RE.match(declared):
                raise EvidenceGraphError('invalid_hash',
                                         'sha256 debe ser SHA-256 hexadecimal de 64 caracteres.',
                                         {'sha256': declared})
            ref_dict['sha256'] = declared
        if locator is not None:
            ref_dict['locator'] = locator
        if ref_kind in ('test', 'tool_result', 'api_result', 'human_record'):
            # El contrato exige `observed_at` para una referencia de tipo test. Cuando
            # el llamante no aporta otra fecha se inscribe la del registro de la
            # referencia: acredita cuando la inscribio el grafo, no que la prueba se
            # haya ejecutado ni que la salida de la herramienta sea correcta.
            ref_dict['observed_at'] = observed_at or now_iso()
        return self.add_node(node_id, 'evidence', statement, tenant_id,
                             evidence_refs=[ref_dict], **kwargs)

    def add_claim(self, node_id, statement, tenant_id, refs=(), edges=(), **kwargs):
        return self.add_node(node_id, 'claim', statement, tenant_id, evidence_refs=refs,
                             edges=edges, **kwargs)

    def add_decision(self, node_id, statement, tenant_id, decision_ref, **kwargs):
        return self._evidence_node('decision', node_id, statement, tenant_id, decision_ref, **kwargs)

    def add_file_evidence(self, node_id, relative_path, statement, tenant_id, **kwargs):
        return self._evidence_node('file', node_id, statement, tenant_id, relative_path, **kwargs)

    def add_test_evidence(self, node_id, test_ref, statement, tenant_id, **kwargs):
        return self._evidence_node('test', node_id, statement, tenant_id, test_ref, **kwargs)

    def add_tool_output_evidence(self, node_id, tool_ref, statement, tenant_id, **kwargs):
        return self._evidence_node('tool_output', node_id, statement, tenant_id, tool_ref, **kwargs)

    def add_api_result_evidence(self, node_id, result_ref, statement, tenant_id, **kwargs):
        return self._evidence_node('api', node_id, statement, tenant_id, result_ref, **kwargs)

    def add_evidence(self, alias, node_id, statement, tenant_id, ref, **kwargs):
        return self._evidence_node(alias, node_id, statement, tenant_id, ref, **kwargs)

    # -- aristas ----------------------------------------------------------- #
    def add_edge(self, source_id, target_id, relation, note=None):
        source = self._node(source_id)
        self._node(target_id)
        if relation not in FROZEN_RELATIONS:
            raise EvidenceGraphError('invalid_edge', 'Relacion fuera del contrato.',
                                     {'relation': relation, 'admitted': list(FROZEN_RELATIONS)})
        if source_id == target_id:
            raise EvidenceGraphError('invalid_edge', 'Auto-arista no admitida.', {'node_id': source_id})
        edge = {'target_node_id': target_id, 'relation': relation}
        if note is not None:
            if not isinstance(note, str) or not note.strip() or len(note) > 600:
                raise EvidenceGraphError('invalid_edge', 'La nota debe tener entre 1 y 600 caracteres.')
            edge['note'] = note
        if self._dup_edge(source, edge):
            return copy.deepcopy(edge)
        source['edges'].append(edge)
        errors = validate_instance(source, self.schema)
        if errors:
            source['edges'].pop()
            raise EvidenceGraphError('invalid_edge', 'La arista deja el nodo fuera del contrato.',
                                     {'node_id': source_id, 'errors': errors})
        self._refresh_affected(extra=(source_id, target_id))
        return copy.deepcopy(edge)

    def _node(self, node_id):
        if node_id not in self._nodes:
            raise EvidenceGraphError('unknown_node', 'Nodo no registrado.', {'node_id': node_id})
        return self._nodes[node_id]

    def node(self, node_id):
        return copy.deepcopy(self._node(node_id))

    def node_ids(self):
        return sorted(self._nodes)

    def provenance(self, node_id):
        self._node(node_id)
        return copy.deepcopy(self._provenance[node_id])

    def kind_alias(self, node_id):
        node = self._node(node_id)
        if node['node_kind'] == 'claim':
            return 'claim'
        if node['node_kind'] == 'decision':
            return 'decision'
        kinds = {ref['kind'] for ref in node['evidence_refs']}
        for alias, ref_kind in ALIAS_REF_KIND.items():
            if kinds == {ref_kind}:
                return alias
        return 'evidence'

    def edges(self):
        result = []
        for source_id in sorted(self._nodes):
            for edge in self._nodes[source_id]['edges']:
                result.append({'source_node_id': source_id, 'target_node_id': edge['target_node_id'],
                               'relation': edge['relation'], 'note': edge.get('note')})
        return result

    # -- contradicciones --------------------------------------------------- #
    def dangling_edges(self):
        """Aristas declaradas hacia nodos no registrados: se reportan, no se ocultan."""
        return [{'source_node_id': source_id, 'target_node_id': edge['target_node_id'],
                 'relation': edge['relation']}
                for source_id in sorted(self._nodes)
                for edge in self._nodes[source_id]['edges']
                if edge['target_node_id'] not in self._nodes]

    def contradictions(self):
        """Contradicciones explicitas. No hay recuento de mayoria en ningun caso."""
        records = []
        for source_id in sorted(self._nodes):
            for edge in self._nodes[source_id]['edges']:
                if edge['relation'] == 'contradicts':
                    records.append({'kind': 'explicit_edge', 'source_node_id': source_id,
                                    'target_node_id': edge['target_node_id'], 'note': edge.get('note')})
        index = {}
        for node_id in sorted(self._nodes):
            for ref in self._nodes[node_id]['evidence_refs']:
                if ref.get('sha256'):
                    index.setdefault((ref['kind'], ref['ref']), {}).setdefault(node_id, set()).add(ref['sha256'])
        for (ref_kind, ref_label), per_node in sorted(index.items()):
            digests = sorted({digest for values in per_node.values() for digest in values})
            if len(digests) > 1:
                records.append({'kind': 'divergent_evidence',
                                'evidence_ref': {'kind': ref_kind, 'ref': ref_label},
                                'nodes': sorted(per_node), 'sha256_values': digests})
        return records

    def _related(self, node_id):
        related = set()
        for source_id in sorted(self._nodes):
            for edge in self._nodes[source_id]['edges']:
                if edge['relation'] == 'contradicts':
                    continue
                if source_id == node_id:
                    related.add(edge['target_node_id'])
                if edge['target_node_id'] == node_id:
                    related.add(source_id)
        return related

    def contradicted_nodes(self):
        contradicted = set()
        for record in self.contradictions():
            if record['kind'] == 'explicit_edge':
                contradicted.update({record['source_node_id'], record['target_node_id']} & set(self._nodes))
            else:
                contradicted.update(set(record['nodes']) & set(self._nodes))
        changed = True
        while changed:
            changed = False
            for node_id, node in sorted(self._nodes.items()):
                if node['node_kind'] != 'claim' or node_id in contradicted:
                    continue
                if self._related(node_id) & contradicted:
                    contradicted.add(node_id)
                    changed = True
        return contradicted

    def contradiction_report(self):
        records = self.contradictions()
        return {'contradictions': records,
                'contradiction_count': len(records),
                'contradicted_nodes': sorted(self.contradicted_nodes()),
                'resolution': 'explicit_only',
                'resolved_by_majority': False,
                'resolved_by_confidence': False,
                'support_counts_compared': False}

    # -- evaluacion de claims ---------------------------------------------- #
    def claim_state(self, node_id):
        """Estado en el vocabulario de aceptacion de I2 (nunca 'verified')."""
        node = self._node(node_id)
        if node['node_kind'] != 'claim':
            raise EvidenceGraphError('not_a_claim', 'Solo un claim tiene estado de claim.',
                                     {'node_id': node_id, 'node_kind': node['node_kind']})
        return ACCEPTANCE_STATE[self._derived_verdict(node_id)]

    def schema_verdict(self, node_id):
        return SCHEMA_VERDICT[self.claim_state(node_id)]

    def claim_status(self, node_id):
        node = self._node(node_id)
        state = self.claim_state(node_id)
        recomputations = [self._recompute_ref(ref) for ref in node['evidence_refs']]
        recomputed = [row for row in recomputations if row['recomputed']]
        verified = [row for row in recomputations if row['verified_flag']]
        touching = [record for record in self.contradictions()
                    if node_id in {record.get('source_node_id'), record.get('target_node_id')}
                    or node_id in (record.get('nodes') or [])]
        return {
            'node_id': node_id,
            'claim_state': state,
            'schema_verdict': SCHEMA_VERDICT[state],
            'stored_verdict': node['verdict'],
            'verified': state == 'supported',
            'evidence_refs': len(node['evidence_refs']),
            'recomputed_refs': len(recomputed),
            'verified_refs': len(verified),
            'not_recomputable_refs': len(recomputations) - len(recomputed),
            'contradiction_count': len(touching),
            'supporting_edges': sum(1 for edge in node['edges'] if edge['relation'] == 'supports'),
            'dependency_edges': sum(1 for edge in node['edges'] if edge['relation'] == 'depends_on'),
            'recompute_basis': sorted({row['recompute_basis'] for row in recomputations}),
            'decided_by': 'frozen_verdict_rules_v1',
            'resolution': 'explicit_contradiction' if state == 'contradicted' else 'no_contradiction',
            'resolved_by_majority': False,
            'resolved_by_confidence': False,
            'support_counts_compared': False,
        }

    def claims_by_state(self, state):
        if state not in CLAIM_STATES:
            raise EvidenceGraphError('invalid_state', 'Estado fuera del vocabulario de I2.',
                                     {'state': state, 'admitted': list(CLAIM_STATES)})
        return sorted(node_id for node_id, node in self._nodes.items()
                      if node['node_kind'] == 'claim' and self.claim_state(node_id) == state)

    def unsupported_claims(self):
        return self.claims_by_state('unsupported')

    def contradicted_claims(self):
        return self.claims_by_state('contradicted')

    def supported_claims(self):
        return self.claims_by_state('supported')

    def insufficient_claims(self):
        return self.claims_by_state('insufficient')

    # -- auditoria --------------------------------------------------------- #
    def validate_nodes(self):
        return {node_id: validate_instance(self._nodes[node_id], self.schema)
                for node_id in sorted(self._nodes)}

    def audit(self):
        """Recomprueba todo y reporta lo que no se sostiene. Cero supuestos."""
        states = {node_id: self.claim_state(node_id) for node_id in sorted(self._nodes)
                  if self._nodes[node_id]['node_kind'] == 'claim'}
        unsupported_with_hash = []
        supported_without_hash = []
        stale_flags = []
        unavailable_refs = []
        for node_id in sorted(self._nodes):
            node = self._nodes[node_id]
            for index, ref in enumerate(node['evidence_refs']):
                row = self._recompute_ref(ref)
                if bool(ref.get('verified', False)) != bool(row['verified_flag']):
                    stale_flags.append({'node_id': node_id, 'ref_index': index, 'ref': ref['ref'],
                                        'stored_verified': bool(ref.get('verified', False)),
                                        'recomputed_verified': bool(row['verified_flag']),
                                        'recompute_basis': row['recompute_basis']})
                if not row['recomputed']:
                    unavailable_refs.append({'node_id': node_id, 'ref': ref['ref'],
                                             'kind': ref['kind'], 'basis': row['recompute_basis']})
                if states.get(node_id) == 'unsupported' and row['verified_flag']:
                    unsupported_with_hash.append(node_id)
        for node_id, state in states.items():
            if state != 'supported':
                continue
            refs = self._nodes[node_id]['evidence_refs']
            if not any(SHA256_RE.match(ref.get('sha256') or '') and self._recompute_ref(ref)['verified_flag']
                       for ref in refs):
                supported_without_hash.append(node_id)
        return {
            'graph_version': GRAPH_VERSION,
            'schema_ref': FROZEN_SCHEMA_REF,
            'schema_sha256': self.schema_sha256,
            'nodes': len(self._nodes),
            'claims': len(states),
            'states': states,
            'state_counts': {state: sum(1 for value in states.values() if value == state)
                             for state in CLAIM_STATES},
            'supported_without_recomputed_hash': sorted(set(supported_without_hash)),
            'unsupported_with_verified_ref': sorted(set(unsupported_with_hash)),
            'stale_verified_flags': stale_flags,
            'unavailable_refs': unavailable_refs,
            'dangling_edges': self.dangling_edges(),
            'contradictions': self.contradiction_report(),
            'node_errors': {node_id: errors for node_id, errors in self.validate_nodes().items() if errors},
            'inert': dict(INERT_FLAGS),
            'counters': dict(self._counters),
            'note': 'La verificacion no prueba que la accion ocurriera; prueba que los bytes citados coinciden.',
        }

    def assert_no_unverified_supported(self):
        report = self.audit()
        bad = report['supported_without_recomputed_hash']
        if bad:
            raise EvidenceGraphError('unverified_supported',
                                     'Hay claims supported sin hash recomprobado.',
                                     {'claims': bad, 'schema_sha256': self.schema_sha256})
        return {'claims_supported': report['state_counts']['supported'],
                'supported_without_recomputed_hash': 0}

    def to_dict(self):
        return {
            'graph_version': GRAPH_VERSION,
            'schema': {'ref': FROZEN_SCHEMA_REF, 'sha256': self.schema_sha256},
            'nodes': [copy.deepcopy(self._nodes[node_id]) for node_id in sorted(self._nodes)],
            'provenance': {node_id: copy.deepcopy(self._provenance[node_id]) for node_id in sorted(self._nodes)},
            'kind_aliases': {node_id: self.kind_alias(node_id) for node_id in sorted(self._nodes)},
            'edges': self.edges(),
            'assessment': {node_id: self.claim_status(node_id) for node_id in sorted(self._nodes)
                           if self._nodes[node_id]['node_kind'] == 'claim'},
            'contradictions': self.contradiction_report(),
            'inert': dict(INERT_FLAGS),
        }

    def to_json(self):
        return canonical_json(self.to_dict())


def graph_capabilities():
    """Vocabulario estable de I2 para consumidores y pruebas de inertitud."""
    return {
        'graph_version': GRAPH_VERSION,
        'schema_ref': FROZEN_SCHEMA_REF,
        'schema_sha256': FROZEN_SCHEMA_SHA256,
        'node_aliases': sorted(NODE_ALIASES) + ['evidence'],
        'node_kinds': list(FROZEN_NODE_KINDS),
        'ref_kinds': list(FROZEN_REF_KINDS),
        'relations': list(FROZEN_RELATIONS),
        'claim_states': list(CLAIM_STATES),
        'schema_verdicts': list(FROZEN_VERDICTS),
        'states_that_are_not_verdicts': list(STATES_THAT_ARE_NOT_VERDICTS),
        'error_codes': sorted({'missing_schema', 'invalid_schema', 'unsupported_schema', 'invalid_node',
                               'duplicate_node', 'invalid_edge', 'invalid_reference', 'invalid_hash',
                               'unknown_node', 'not_a_claim', 'invalid_state', 'missing_provenance',
                               'prohibited_field', 'embedded_credential', 'file_unavailable',
                               'artifact_unavailable', 'unverified_supported'}),
        'flags': dict(INERT_FLAGS),
    }


__all__ = ['EvidenceGraph', 'EvidenceGraphError', 'GRAPH_VERSION', 'FROZEN_SCHEMA_REF',
           'FROZEN_SCHEMA_SHA256', 'NODE_ALIASES', 'CLAIM_STATES', 'SCHEMA_VERDICT', 'INERT_FLAGS',
           'canonical_json', 'sha256_of', 'sha256_of_bytes', 'now_iso', 'credential_like',
           'reject_credentials', 'validate_instance', 'load_frozen_schema', 'graph_capabilities']
