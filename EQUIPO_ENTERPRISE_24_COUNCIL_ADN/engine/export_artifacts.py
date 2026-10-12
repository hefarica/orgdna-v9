"""Frozen, native-named DSH export artifacts and exact-byte SHA-256 metadata.

The two DSH envelopes remain recipe v1 and definitions v2. Integrity metadata
lives in a separate OrgDNA JSON document; UUID identifiers are not file hashes.
No network, provider call, import, or agent execution occurs here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from types import MappingProxyType
import uuid

if __package__:
    from . import core
else:
    import core

MANIFEST_FILENAME = 'agent-team-export-manifest.json'
CAPABILITY_FILENAME = 'skillhub-library.json'
BACKUP_PATTERN = re.compile(r'agent-team-backup-\d{4}-\d{2}-\d{2}\.json\Z')
RECIPE_PATTERN = re.compile(r'agent-team-recipe-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json\Z')
PRIVATE_RUNTIME_KEYS = frozenset({
    'records', 'local_records', 'scoreboard', 'coordination_snapshot',
    'council_sessions', 'skill_registry', 'remediation_records',
    'performance_records', 'promotion_records', 'governance_events',
    'leases', 'coordination_ledger',
    'integrations', 'integration_runtime', 'integration_settings', 'integration_state',
    'plugin_shop', 'plugin_shop_catalog', 'plugin_catalog', 'plugin_inspections',
    'plugin_installation_plans', 'plugin_operator_reports',
    'cordis_cache', 'cordis_runtime_state', 'dsh_connection', 'dsh_profiles',
    'dsh_team', 'dsh_preview', 'dsh_plan', 'dsh_status', 'dsh_preview_identity',
    'connection_session', 'session_bindings',
})


def json_bytes(value):
    """One UTF-8 representation, with LF terminator and without a BOM."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')


def _load_json(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Clave JSON duplicada: ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('Constante JSON no finita: ' + value)
    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def export_organization(org):
    """Structural state only; private runtime history never changes exports."""
    result = copy.deepcopy(org)
    for key in PRIVATE_RUNTIME_KEYS:
        result.pop(key, None)
    for agent in result.get('agents', []):
        for key in PRIVATE_RUNTIME_KEYS:
            agent.pop(key, None)
    return result


def organization_fingerprint(org):
    """Stable cache/revision key, independent of dictionary insertion order."""
    data = json.dumps(export_organization(org), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _date(exported_at):
    if type(exported_at) is not int or exported_at < 0:
        raise ValueError('exported_at debe ser un entero de milisegundos UTC no negativo.')
    try:
        return datetime.fromtimestamp(exported_at / 1000, timezone.utc).strftime('%Y-%m-%d')
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError('exported_at está fuera del calendario admitido.') from exc


def native_filenames(implementation, council, definitions):
    """Native filenames derive from the frozen export date and actual squad IDs."""
    exported_at = implementation['exportedAt']
    if council['exportedAt'] != exported_at or definitions['exportedAt'] != exported_at:
        raise ValueError('Los formatos y fases deben compartir exactamente exportedAt.')
    implementation_id = str(uuid.UUID(implementation['squad']['id']))
    council_id = str(uuid.UUID(council['squad']['id']))
    if implementation_id == council_id:
        raise ValueError('Implementación y Council deben tener UUID distintos.')
    return {
        'implementation.json': f'agent-team-recipe-{implementation_id}.json',
        'definitions.json': f'agent-team-backup-{_date(exported_at)}.json',
        'council.json': f'agent-team-recipe-{council_id}.json',
        'export-manifest.json': MANIFEST_FILENAME,
    }


def package_paths(filenames):
    return {alias: ('extras/' if alias == 'council.json' else '') + name
            for alias, name in filenames.items()}


def _manifest(org_sha, state_version, exported_at, documents, payloads, filenames, capability_bytes=None, context_receipt=None):
    paths = package_paths(filenames)
    artifacts = []
    for role in ('definitions', 'implementation', 'council'):
        alias = role + '.json'
        document = documents[alias]
        data = payloads[filenames[alias]]
        squads = document['squads'] if role == 'definitions' else [document['squad']]
        artifacts.append({
            'role': role, 'filename': filenames[alias], 'package_path': paths[alias],
            'format': document['format'], 'version': document['version'],
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'squad_ids': [squad['id'] for squad in squads],
        })
    result = {
        'format': 'orgdna/export-manifest', 'version': 1,
        'exportedAt': exported_at, 'organization_sha256': org_sha,
        'state_version': state_version, 'hash_algorithm': 'SHA-256',
        'hash_scope': 'exact_file_bytes_utf8',
        'artifacts': artifacts,
        'manifest_self_hash_included': False, 'zip_hash_included': False,
        'identifier_note': 'Los UUID identifican squads; no son hashes SHA-256. Los sufijos (1)/(2) son copias locales del navegador, no parte del nombre nativo.',
    }


    if capability_bytes is not None:
        companion = _load_json(capability_bytes)
        result['companions'] = [{'role': 'capability_library', 'filename': CAPABILITY_FILENAME,
                                 'package_path': CAPABILITY_FILENAME, 'protocol': companion['protocol'],
                                 'revision': companion['revision'], 'bytes': len(capability_bytes),
                                 'sha256': hashlib.sha256(capability_bytes).hexdigest(),
                                 'organization_id': companion['organization_id']}]
    if context_receipt is not None:
        result['context_compilation'] = context_receipt
    return result


def _validate_capability_library(value, org):
    if __package__:
        from .capability_deployment import validate_skillhub_manifest
    else:
        from capability_deployment import validate_skillhub_manifest
    validate_skillhub_manifest(value, org)
    return value


def _compile_export_context(org, capability_library=None):
    if capability_library is None:
        return None, None
    if __package__:
        from .agent_context import compile_agent_context
    else:
        from agent_context import compile_agent_context
    result = compile_agent_context(org, capability_library)
    active = any(row['included_item_ids'] or row['deferred_item_ids'] for row in result['agents'].values())
    if not active:
        return result['agents'], None
    fields = ('budget_bytes', 'bytes', 'included_item_ids', 'deferred_item_ids', 'items')
    receipt = {'manifest_sha256': result['manifest_sha256'],
               'agents': {identifier: {**{key: copy.deepcopy(row[key]) for key in fields},
                                       'system_prompt_sha256': hashlib.sha256(row['systemPrompt'].encode('utf-8')).hexdigest()}
                          for identifier, row in result['agents'].items()},
               'permission_changes': [], 'runtime_verified': False}
    return result['agents'], receipt


def expected_export_agents(org, capability_library=None, *, base_recipe=None):
    agents = core.export_recipe(org, base_recipe)['agents']
    compiled, _ = _compile_export_context(org, capability_library)
    if compiled is not None:
        if set(compiled) != {agent['id'] for agent in agents}:
            raise ValueError('El contexto compilado no coincide con los IDs actuales.')
        for agent in agents:
            agent['systemPrompt'] = compiled[agent['id']]['systemPrompt']
    return agents


@dataclass(frozen=True)
class ExportSnapshot:
    """Immutable byte payloads; returned document properties are independent copies."""
    exported_at: int
    organization_sha256: str
    state_version: int
    _filenames: tuple
    _files: tuple

    @property
    def filenames(self):
        return MappingProxyType(dict(self._filenames))

    @property
    def files(self):
        return MappingProxyType(dict(self._files))

    @property
    def package_files(self):
        paths = package_paths(self.filenames)
        return MappingProxyType({paths[alias]: self.file_for(alias) for alias in paths})

    def filename_for(self, alias):
        if alias in self.filenames:
            return self.filenames[alias]
        if alias in self.files:
            return alias
        raise ValueError('Export desconocido: ' + str(alias))

    def file_for(self, alias):
        return self.files[self.filename_for(alias)]

    @property
    def implementation(self):
        return json.loads(self.file_for('implementation.json'))

    @property
    def council(self):
        return json.loads(self.file_for('council.json'))

    @property
    def definitions(self):
        return json.loads(self.file_for('definitions.json'))

    @property
    def manifest(self):
        return json.loads(self.file_for('export-manifest.json'))

    @property
    def capability_library(self):
        if CAPABILITY_FILENAME not in self.files:
            return None
        return _load_json(self.files[CAPABILITY_FILENAME])

    def assert_matches(self, org):
        if organization_fingerprint(org) != self.organization_sha256:
            raise ValueError('El snapshot de exportación pertenece a otra revisión de la organización.')
        report = validate_export_files(self.package_files, org)
        if not report['valid']:
            raise ValueError('Snapshot de exportación inválido: ' + '; '.join(report['errors']))


def build_export_snapshot(org, base_recipe=None, exported_at=None, *, capability_library=None):
    """Capture one export instant and reuse exactly these bytes for every route.

    Rebuilding with the same organization, base anchor, and exported_at produces
    identical JSON and manifest bytes. Callers cache this object per structural
    organization revision and pass it to the ZIP builder.
    """
    clean = export_organization(org)
    exported_at = int(time.time() * 1000) if exported_at is None else exported_at
    _date(exported_at)
    implementation = core.export_recipe(clean, base_recipe, phase='implementation')
    council = core.export_recipe(clean, base_recipe, phase='council')
    if capability_library is not None:
        frozen_agents = expected_export_agents(clean, capability_library, base_recipe=base_recipe)
        implementation['agents'] = copy.deepcopy(frozen_agents)
        council['agents'] = copy.deepcopy(frozen_agents)
    implementation['exportedAt'] = council['exportedAt'] = exported_at
    if implementation['agents'] != council['agents']:
        raise ValueError('Las fases deben compartir exactamente las definiciones de agente.')
    # The definitions sample's root envelope and key order are preserved. No hash
    # or provenance fields are inserted into either strict DSH schema.
    definitions = {'format': 'agent-team-gui/definitions', 'exportedAt': exported_at,
                   'agents': copy.deepcopy(implementation['agents']),
                   'squads': [copy.deepcopy(implementation['squad']), copy.deepcopy(council['squad'])],
                   'version': 2}
    for report in (core.validate_recipe(implementation), core.validate_recipe(council),
                   core.validate_definitions(definitions)):
        if not report['valid']:
            raise ValueError('Export DSH inválido: ' + '; '.join(report['errors']))
    filenames = native_filenames(implementation, council, definitions)
    documents = {'implementation.json': implementation, 'council.json': council,
                 'definitions.json': definitions}
    payloads = {filenames[alias]: json_bytes(document) for alias, document in documents.items()}
    org_sha = organization_fingerprint(clean)
    state_version = clean.get('state_version', 1)
    capability_bytes = None
    if capability_library is not None:
        companion = _validate_capability_library(copy.deepcopy(capability_library), clean)
        if __package__:
            from .capability_deployment import skillhub_manifest_bytes
        else:
            from capability_deployment import skillhub_manifest_bytes
        capability_bytes = skillhub_manifest_bytes(companion)
        filenames[CAPABILITY_FILENAME] = CAPABILITY_FILENAME
        payloads[CAPABILITY_FILENAME] = capability_bytes
    _, context_receipt = _compile_export_context(clean, capability_library)
    manifest = _manifest(org_sha, state_version, exported_at, documents, payloads, filenames, capability_bytes, context_receipt)
    payloads[MANIFEST_FILENAME] = json_bytes(manifest)
    return ExportSnapshot(exported_at, org_sha, state_version,
                          tuple(filenames.items()), tuple(payloads.items()))


def validate_export_files(files, org=None):
    """Detect exactly the native principal pair plus the optional-path Council.

    Used by the package validator and API snapshot consistency checks. File bytes
    are checked as received, without re-serializing before hashing.
    """
    errors = []
    try:
        backups = [name for name in files if BACKUP_PATTERN.fullmatch(name)]
        recipes = [name for name in files if RECIPE_PATTERN.fullmatch(name)]
        councils = [name for name in files if name.startswith('extras/') and RECIPE_PATTERN.fullmatch(name[7:])]
        if len(backups) != 1 or len(recipes) != 1 or len(councils) != 1:
            raise ValueError('Se requieren exactamente un backup nativo, una recipe principal y una recipe Council en extras/.')
        definitions = _load_json(files[backups[0]])
        implementation = _load_json(files[recipes[0]])
        council = _load_json(files[councils[0]])
        for label, report in [('recipe', core.validate_recipe(implementation)),
                              ('definitions', core.validate_definitions(definitions)),
                              ('Council', core.validate_recipe(council))]:
            errors.extend(label + ': ' + error for error in report['errors'])
        filenames = native_filenames(implementation, council, definitions)
        paths = package_paths(filenames)
        if (backups[0], recipes[0], councils[0]) != (paths['definitions.json'], paths['implementation.json'], paths['council.json']):
            errors.append('Los nombres nativos no corresponden a exportedAt UTC y UUID de los squads.')
        if not implementation['agents'] == definitions['agents'] == council['agents']:
            errors.append('Los formatos y fases no comparten exactamente los mismos agentes.')
        if definitions['squads'] != [implementation['squad'], council['squad']]:
            errors.append('Los squads del backup difieren de las recipes.')
        manifest = _load_json(files[MANIFEST_FILENAME])
        documents = {'implementation.json': implementation, 'council.json': council,
                     'definitions.json': definitions}
        payloads = {filenames[alias]: files[paths[alias]] for alias in documents}
        org_sha = organization_fingerprint(org) if org is not None else manifest['organization_sha256']
        state_version = org.get('state_version', 1) if org is not None else manifest['state_version']
        capability_bytes = files.get(CAPABILITY_FILENAME)
        if capability_bytes is not None:
            companion = _load_json(capability_bytes)
            identity = org if org is not None else {'organization_id': companion.get('organization_id'), 'agents': implementation['agents']}
            _validate_capability_library(companion, identity)
            filenames[CAPABILITY_FILENAME] = CAPABILITY_FILENAME
            paths = package_paths(filenames)
        context_receipt = None
        if org is not None:
            companion = _load_json(capability_bytes) if capability_bytes is not None else None
            if implementation['agents'] != expected_export_agents(org, companion):
                errors.append('Los agentes exportados no corresponden al contexto y organización actuales.')
            _, context_receipt = _compile_export_context(org, companion)
        elif manifest.get('context_compilation') is not None:
            context_receipt = manifest['context_compilation']
            if capability_bytes is None or context_receipt.get('manifest_sha256') != hashlib.sha256(capability_bytes).hexdigest():
                errors.append('El recibo de contexto no corresponde al companion.')
            rows = context_receipt.get('agents', {})
            if set(rows) != {a['id'] for a in implementation['agents']} or any(rows.get(a['id'], {}).get('system_prompt_sha256') != hashlib.sha256(a['systemPrompt'].encode('utf-8')).hexdigest() for a in implementation['agents']):
                errors.append('El recibo de contexto no corresponde a los prompts exportados.')
        expected = _manifest(org_sha, state_version, implementation['exportedAt'], documents, payloads, filenames, capability_bytes, context_receipt)
        if json.dumps(manifest, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            errors.append('El manifiesto de exportación no coincide con los nombres, bytes, hashes o revisión actual.')
        if not re.fullmatch(r'[0-9a-f]{64}', org_sha):
            errors.append('organization_sha256 no es SHA-256 válido.')
        return {'valid': not errors, 'errors': errors, 'filenames': filenames,
                'package_paths': paths, 'exported_at': implementation['exportedAt'],
                'organization_sha256': org_sha}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        return {'valid': False, 'errors': errors + ['Exports no válidos: ' + str(exc)]}
