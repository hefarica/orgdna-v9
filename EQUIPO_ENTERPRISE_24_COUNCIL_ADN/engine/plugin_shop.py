"""Read-only Plugin Shop discovery, evidence review and installation proposals.

No subprocesses, installation, environment reads, filesystem writes or import-time
network. Public GETs reuse providers' DNS/IP-pinned TLS transport. A catalog hash
verifies bytes against its publisher's index, not the publisher's trustworthiness.
Fixtures may inject the same trusted transport seam as engine.providers.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

try:
    from . import providers
except ImportError:
    import providers

SOURCES = {'github_pages': 'https://livxue.github.io/dsh-plugin-shop/v1/'}
SOURCE_REPOSITORY = 'https://github.com/LivXue/dsh-plugin-shop'
SOURCE_COMMIT = '9700bebb638f490b0ab70689bb8fc1249b1274e8'
MANAGER_DOCS = 'https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md'
MAX_CATALOG_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 50000
MAX_METADATA_BYTES = 2 * 1024 * 1024
SCHEMA_MAX = 6
STATES = ('proposal', 'inspected', 'approved_by_operator', 'test_reported', 'active_reported')
HASH = re.compile(r'^[a-f0-9]{64}$')
COMMIT = re.compile(r'^[a-f0-9]{40}$')
NAME = re.compile(r'^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$')
REPO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$')
VERSION = re.compile(r'^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][A-Za-z0-9-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][A-Za-z0-9-]*))*)?(?:\+[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)?$')
SRI = re.compile(r'^(sha256|sha384|sha512)-([A-Za-z0-9+/]+={0,2})$')
LIFECYCLE_SCRIPTS = {'preinstall', 'install', 'postinstall', 'prepare', 'prepublish', 'prepack'}
HOST_RISK = ('El código Host se ejecuta fuera del sandbox del workspace y puede acceder a archivos, shell, red y solicitudes al modelo. Las capacidades declaradas no limitan esos permisos.')


class PluginShopError(ValueError):
    """Bounded, displayable error without remote response bodies or secrets."""


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise PluginShopError('Datos de Plugin Shop no serializables.') from None


def _hash(value):
    return hashlib.sha256(_dump(value).encode('utf-8')).hexdigest()


def _text(value, limit=2000, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise PluginShopError('Texto de catálogo ausente, demasiado largo o con controles.')
    return value


def _strings(value, limit=128, length=256):
    if not isinstance(value, list) or len(value) > limit:
        raise PluginShopError('Lista de catálogo inválida o demasiado grande.')
    return [_text(x, length) for x in value]


def _mapping(value, limit=512, value_length=512):
    if not isinstance(value, dict) or len(value) > limit:
        raise PluginShopError('Mapa de manifiesto inválido o demasiado grande.')
    return {_text(k, 214): _text(v, value_length, empty=True) for k, v in value.items()}


def _name(value):
    value = _text(value, 214)
    if not NAME.fullmatch(value):
        raise PluginShopError('Nombre exacto de paquete inválido; no se admiten comandos ni alias.')
    return value


def _version(value):
    value = _text(value, 128)
    if not VERSION.fullmatch(value):
        raise PluginShopError('Se requiere una versión SemVer exacta; no latest, rangos ni comandos.')
    return value


def _sri(value):
    if value is None:
        return None
    value = _text(value, 256)
    matched = SRI.fullmatch(value)
    if not matched:
        raise PluginShopError('Integridad npm inválida.')
    try:
        raw = base64.b64decode(matched.group(2), validate=True)
    except ValueError:
        raise PluginShopError('Integridad npm mal codificada.') from None
    if len(raw) != {'sha256': 32, 'sha384': 48, 'sha512': 64}[matched.group(1)]:
        raise PluginShopError('Longitud de integridad npm incorrecta.')
    return value


def _display_url(value):
    """Metadata links are never fetch permissions; unsafe links are omitted."""
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 1024:
        raise PluginShopError('Enlace de catálogo inválido.')
    clean = value[4:] if value.startswith('git+https://') else value
    try:
        parsed = providers._url(clean)
        if parsed.query:
            return None
        return clean
    except providers.ProviderError:
        return None


def _json(raw, max_bytes):
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise PluginShopError('El cuerpo JSON supera el límite permitido.')
    try:
        value = providers._loads(raw.decode('utf-8'))
    except (UnicodeError, providers.ProviderError):
        raise PluginShopError('JSON de catálogo inválido, duplicado o no UTF-8.') from None
    if not isinstance(value, dict):
        raise PluginShopError('La respuesta debe ser un objeto JSON.')
    return value


def _get(url, *, transport=None, max_bytes=MAX_METADATA_BYTES):
    # URL is constructed only from a fixed catalog root or validated identity.
    parsed = providers._url(url)
    if parsed.hostname not in {'livxue.github.io', 'registry.npmjs.org', 'api.github.com'}:
        raise PluginShopError('Origen fuera de la lista de fuentes públicas permitidas.')
    headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'OrgDNA-PluginDiscovery/1.0'}
    if parsed.hostname == 'api.github.com':
        headers['X-GitHub-Api-Version'] = '2022-11-28'
    try:
        status, _, raw = (transport or providers._https_transport)('GET', url, headers, None, 20, max_bytes)
    except providers.ProviderError as exc:
        raise PluginShopError(str(exc)) from None
    except Exception:
        raise PluginShopError('No se pudo consultar la fuente pública; no hubo instalación ni reintento automático.') from None
    if type(status) is not int or not 200 <= status < 300:
        raise PluginShopError(f'Fuente pública respondió HTTP {status if type(status) is int else 0}; no se siguen redirecciones.')
    return raw, _json(raw, max_bytes)


def empty_catalog():
    return {'format': 'orgdna/plugin-catalog', 'version': 1, 'status': 'NOT_FETCHED', 'candidates': [],
            'count': 0, 'denied': [], 'built_at': None, 'fetched_at': None, 'source': None,
            'catalog_url': SOURCES['github_pages'] + 'index.json', 'catalog_sha256': None,
            'runtime_verified': False, 'network_performed': False, 'sources': copy.deepcopy(SOURCES),
            'warnings': ['Actualizar consulta sólo metadatos públicos. No instala plugins ni cambia perfiles DSH.']}


def _index(index):
    if not isinstance(index, dict) or type(index.get('schemaVersion')) is not int or not 1 <= index['schemaVersion'] <= SCHEMA_MAX:
        raise PluginShopError('Versión del esquema de catálogo no compatible.')
    _text(index.get('builtAt'), 64)
    if type(index.get('count')) is not int or not 0 <= index['count'] <= MAX_ENTRIES:
        raise PluginShopError('Recuento de catálogo inválido.')
    pointer = index.get('plugins')
    if not isinstance(pointer, dict) or not isinstance(pointer.get('sha256'), str) or not HASH.fullmatch(pointer['sha256']):
        raise PluginShopError('Falta el SHA-256 exacto del catálogo.')
    expected = 'plugins.' + pointer['sha256'] + '.json'
    if pointer.get('url') != expected:
        raise PluginShopError('El índice debe nombrar exactamente plugins.<sha256>.json, sin rutas ni URLs arbitrarias.')
    return pointer


def _candidate(entry, provenance):
    if not isinstance(entry, dict) or len(_dump(entry).encode()) > 16384:
        raise PluginShopError('Entrada de catálogo inválida o demasiado grande.')
    name = _name(entry.get('name'))
    source = entry.get('source', 'npm')
    if source not in ('npm', 'github'):
        raise PluginShopError('Canal de plugin no soportado.')
    version = _text(entry.get('version'), 256)
    repo, subdir, tarball, install_spec, blockers = None, None, None, None, []
    if source == 'npm':
        if name != name.lower():
            raise PluginShopError('Nombre npm debe estar en minúsculas.')
        _version(version)
        integrity = _sri(entry.get('integrity'))
        install_spec = name + '@' + version
    else:
        repo = _text(entry.get('repo'), 214)
        if not REPO.fullmatch(repo) or any(x in ('.', '..') for x in repo.split('/')):
            raise PluginShopError('Repositorio GitHub inválido.')
        subdir = entry.get('subdir')
        if subdir is not None:
            _text(subdir, 200)
            if not re.fullmatch(r'[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*', subdir) or any(x in ('.', '..') for x in subdir.split('/')):
                raise PluginShopError('Subdirectorio de plugin inválido.')
        integrity = entry.get('integrity')
        if integrity is not None:
            _text(integrity, 256)
        if entry.get('tarball') is not None:
            item = entry['tarball']
            if not isinstance(item, dict) or not isinstance(item.get('sha256'), str) or not HASH.fullmatch(item['sha256']):
                raise PluginShopError('Tarball sin hash exacto.')
            url = _text(item.get('url'), 1024)
            try:
                parsed = providers._url(url)
            except providers.ProviderError:
                raise PluginShopError('Tarball GitHub inválido.') from None
            if parsed.hostname != 'github.com' or parsed.query or '%' in parsed.path or not parsed.path.lower().startswith('/' + repo.lower() + '/releases/download/'):
                raise PluginShopError('Tarball no pertenece al repositorio indicado.')
            if integrity != item['sha256']:
                raise PluginShopError('Integridad del tarball no coincide con la entrada.')
            tarball = {'url': url, 'sha256': item['sha256']}
            install_spec = url
            blockers.append('release_archive_requires_native_inspection')
        elif COMMIT.fullmatch(version):
            if integrity != version:
                raise PluginShopError('El commit y la integridad del plugin GitHub no coinciden.')
            install_spec = f'github:{repo}#{version}' + (f'&path:/{subdir}' if subdir else '')
        else:
            blockers.append('immutable_source_pin_missing')
    cat = entry.get('catalog') or {}
    if not isinstance(cat, dict):
        raise PluginShopError('Descripción de plugin inválida.')
    summary = cat.get('summary') or {}
    if not isinstance(summary, dict):
        raise PluginShopError('Resumen de plugin inválido.')
    description = _text(summary.get('en') or summary.get('zh') or name, 2000)
    capabilities = _strings(cat.get('capabilities', []), 20, 64)
    category = cat.get('category', 'other')
    if category not in ('tool', 'provider', 'ui', 'workflow', 'integration', 'theme', 'other'):
        raise PluginShopError('Categoría de catálogo no admitida.')
    peers = _strings(entry.get('peers', []), 128, 128)
    compatibility = entry.get('compatibility') or {}
    if not isinstance(compatibility, dict):
        raise PluginShopError('Declaración de compatibilidad inválida.')
    declared_dsh = compatibility.get('dsh')
    if declared_dsh is not None:
        _text(declared_dsh, 256, empty=True)
    declared_profiles = _strings(compatibility.get('profiles', []), 16, 64)
    dsh_peers = _mapping(entry.get('dshPeers', {}), 128, 256)
    tier = entry.get('tier', 'community')
    if tier not in ('community', 'verified', 'verified-stale'):
        raise PluginShopError('Nivel de revisión de catálogo no válido.')
    review = entry.get('review') or {}
    if not isinstance(review, dict) or len(_dump(review)) > 8000:
        raise PluginShopError('Metadata de revisión inválida.')
    review = {k: _text(review[k], 4000, empty=True) for k in ('reviewedVersion', 'reviewedCommit', 'reviewedSha256', 'repo', 'reviewer', 'reviewCommit', 'notes') if k in review}
    identity = {'source': source, 'name': name, 'repo': repo, 'subdir': subdir}
    result = {'id': 'plugin-' + _hash(identity)[:24], 'name': name, 'version': version, 'source': source,
              'repo': repo, 'subdir': subdir, 'repository': _display_url(entry.get('repository')),
              'license': _text(entry['license'], 128) if entry.get('license') else None,
              'category': category, 'description': description, 'capabilities': capabilities,
              'capability_evidence': 'SELF_DECLARED_NOT_ENFORCED', 'required_peers': peers,
              'dsh_peers': dsh_peers,
              'compatibility': {'status': 'UNVERIFIED', 'declared_dsh': declared_dsh, 'declared_profiles': declared_profiles,
                                'reason': 'Falta contrastar el manifiesto y el runtime real; no se infiere compatibilidad de estrellas o nombres.'},
              'trust': {'status': 'UNVERIFIED', 'catalog_tier': tier, 'review': review,
                        'warning': 'La revisión declarada por el catálogo no es una auditoría de OrgDNA. Popularidad no acredita confianza.'},
              'provenance': dict(provenance, entry_sha256=_hash(entry), source_integrity=integrity),
              'install_spec': install_spec, 'tarball': tarball, 'blockers': blockers,
              'status': 'proposal', 'runtime_verified': False, 'installed': False, 'active': False,
              'history': [], 'risks': [HOST_RISK], 'inspection': None}
    size = entry.get('installSize', entry.get('unpackedSize'))
    if size is not None:
        if type(size) is not int or not 0 <= size <= 2**53 - 1:
            raise PluginShopError('Tamaño de instalación inválido.')
        result['install_size'] = size
    return result


def parse_catalog(index, payload, *, source='github_pages', fetched_at=None):
    """Pure validation seam; payload must be the exact data-file bytes."""
    if source not in SOURCES:
        raise PluginShopError('Fuente no permitida. Selecciona github_pages; no se aceptan URLs arbitrarias.')
    pointer = _index(index)
    if not isinstance(payload, bytes) or len(payload) > MAX_CATALOG_BYTES:
        raise PluginShopError('Catálogo demasiado grande.')
    if hashlib.sha256(payload).hexdigest() != pointer['sha256']:
        raise PluginShopError('SHA-256 del catálogo no coincide; no se usarán estos candidatos.')
    value = _json(payload, MAX_CATALOG_BYTES)
    if type(value.get('schemaVersion')) is not int or value['schemaVersion'] != index['schemaVersion']:
        raise PluginShopError('El esquema del índice y de los datos no coincide.')
    entries = value.get('plugins')
    if not isinstance(entries, list) or len(entries) != index['count']:
        raise PluginShopError('El recuento del índice y de los candidatos no coincide.')
    denied = value.get('denied', [])
    if not isinstance(denied, list) or len(denied) > MAX_ENTRIES:
        raise PluginShopError('Lista de denegaciones inválida.')
    denied_rows = []
    for row in denied:
        if not isinstance(row, dict):
            raise PluginShopError('Denegación de catálogo inválida.')
        denied_rows.append({'name': _name(row.get('name')), 'detail': _text(row.get('detail'), 4000),
                            'replacement': _name(row['replacement']) if row.get('replacement') else None})
    provenance = {'catalog_url': SOURCES[source] + pointer['url'], 'catalog_built_at': index['builtAt'],
                  'catalog_sha256': pointer['sha256'], 'source_repository': SOURCE_REPOSITORY,
                  'validation': 'SHA256_MATCHES_PUBLISHER_INDEX_NOT_SIGNATURE'}
    candidates = [_candidate(e, provenance) for e in entries]
    ids = [c['id'] for c in candidates]
    if len(set(ids)) != len(ids):
        raise PluginShopError('El catálogo contiene identidades duplicadas; no se mezclan versiones o repositorios.')
    denials = {row['name']: row['detail'] for row in denied_rows}
    for candidate in candidates:
        if candidate['name'] in denials:
            candidate['blockers'].append('catalog_denied')
            candidate['denial_reason'] = denials[candidate['name']]
    return {'format': 'orgdna/plugin-catalog', 'version': 1, 'status': 'CATALOG_INTEGRITY_CHECKED',
            'schema_version': index['schemaVersion'], 'source': source, 'catalog_url': SOURCES[source] + 'index.json',
            'catalog_sha256': pointer['sha256'], 'built_at': index['builtAt'], 'fetched_at': fetched_at,
            'count': len(candidates), 'candidates': candidates, 'denied': denied_rows,
            'runtime_verified': False, 'network_performed': False, 'sources': copy.deepcopy(SOURCES),
            'warnings': ['Integridad del catálogo comprobada; código, compatibilidad y entorno aún no verificados.', HOST_RISK]}


def fetch_catalog(source='github_pages', *, transport=None):
    if source not in SOURCES:
        raise PluginShopError('Fuente no permitida. Selecciona github_pages; no se aceptan URLs arbitrarias.')
    _, index = _get(SOURCES[source] + 'index.json', transport=transport, max_bytes=65536)
    pointer = _index(index)  # Reject a hostile data URL before any second request.
    raw, _ = _get(SOURCES[source] + pointer['url'], transport=transport, max_bytes=MAX_CATALOG_BYTES)
    result = parse_catalog(index, raw, source=source, fetched_at=_now())
    result['network_performed'] = True
    return result


def get_candidate(catalog, candidate_id):
    _text(candidate_id, 64)
    if not isinstance(catalog, dict) or not isinstance(catalog.get('candidates'), list):
        raise PluginShopError('Primero consulta un catálogo válido.')
    matches = [c for c in catalog['candidates'] if c.get('id') == candidate_id]
    if len(matches) != 1:
        raise PluginShopError('Candidato no encontrado en este catálogo; actualiza y selecciona su identidad exacta.')
    return copy.deepcopy(matches[0])


def _tokens(text):
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))
    return set(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+', folded))


SEARCH_ALIASES = {
    'pruebas': 'test testing quality', 'calidad': 'quality test', 'navegador': 'browser playwright',
    'seguridad': 'security audit vulnerability', 'dependencias': 'dependency dependencies',
    'memoria': 'memory', 'documentacion': 'documentation docs', 'equipo': 'team squad',
    'coordinacion': 'coordination workflow', 'herramientas': 'tools', 'busqueda': 'search retrieval',
    'datos': 'data database', 'rendimiento': 'performance', 'observabilidad': 'observability monitoring',
    'proveedor': 'provider', 'interfaz': 'ui frontend', 'accesibilidad': 'accessibility',
}


def search_catalog(catalog, query='', *, capabilities=None, limit=30, offset=0, category=None, sort='source'):
    query = _text(query, 500, empty=True).strip()
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PluginShopError('El límite de resultados debe estar entre 1 y 100.')
    if type(offset) is not int or offset < 0 or (category is not None and not isinstance(category, str)) or sort not in ('source', 'name'):
        raise PluginShopError('Paginación, categoría u orden inválidos.')
    requested = _strings(capabilities or [], 30, 80)
    terms = _tokens(query + ' ' + ' '.join(requested))
    terms |= _tokens(' '.join(SEARCH_ALIASES.get(t, '') for t in list(terms)))
    if not isinstance(catalog, dict) or not isinstance(catalog.get('candidates'), list):
        raise PluginShopError('Catálogo inválido.')
    ranked = []
    for candidate in catalog['candidates']:
        if category and candidate.get('category') != category:
            continue
        text = ' '.join([candidate['name'], candidate['description'], candidate['category'], *candidate['capabilities']])
        matched = sorted(terms & _tokens(text))
        substring_match = bool(query and query.casefold() in text.casefold())
        if terms and not matched and not substring_match:
            continue
        score = len(matched) * 10 + (10 if substring_match else 0)
        if query and query.lower() in candidate['name'].lower():
            score += 25
        explicit = sorted(set(requested) & set(candidate['capabilities']))
        score += 15 * len(explicit)
        match = {'score': score, 'terms': matched, 'explicit_capabilities': explicit,
                 'reason': 'Coincidencia descriptiva en catálogo; requiere inspección y pruebas.' if terms else 'Entrada del catálogo sin ranking por popularidad.',
                 'coverage': 'PROPOSED_NOT_TESTED'}
        ranked.append((candidate, match))
    ranked.sort(key=lambda item: (-item[1]['score'], item[0]['name'].lower(), item[0]['id']))
    if sort == 'name':
        ranked.sort(key=lambda item: (item[0]['name'].lower(), item[0]['id']))
    results = [dict(copy.deepcopy(candidate), match=match) for candidate, match in ranked[offset:offset+limit]]
    return {'query': query, 'capabilities': requested, 'results': results, 'total': len(ranked),
            'limit': limit, 'offset': offset, 'next_offset': offset+len(results) if offset+len(results)<len(ranked) else None,
            'category': category, 'sort': sort, 'categories': sorted({c.get('category', '') for c in catalog['candidates']}), 'catalog_count': catalog.get('count', 0), 'catalog_built_at': catalog.get('built_at'),
            'status': catalog.get('status', 'NOT_FETCHED'), 'runtime_verified': False}


def _manifest(candidate, *, transport):
    if candidate['source'] == 'npm':
        url = 'https://registry.npmjs.org/' + quote(candidate['name'], safe='') + '/' + quote(_version(candidate['version']), safe='')
        raw, manifest = _get(url, transport=transport)
        if manifest.get('name') != candidate['name'] or manifest.get('version') != candidate['version']:
            raise PluginShopError('El registro respondió otro paquete o versión; no se acepta el cambio.')
        dist = manifest.get('dist') or {}
        if not isinstance(dist, dict):
            raise PluginShopError('Metadata dist inválida.')
        integrity = _sri(dist.get('integrity'))
        expected = candidate['provenance'].get('source_integrity')
        if expected and integrity != expected:
            raise PluginShopError('La integridad del registro ya no coincide con el catálogo; revisar antes de continuar.')
        return url, raw, manifest, integrity
    if candidate.get('tarball') or not COMMIT.fullmatch(candidate['version']):
        raise PluginShopError('Esta entrega necesita inspección nativa del archivo publicado y su hash; no se sustituye por la rama actual.')
    repo = candidate['repo']
    path = (candidate['subdir'] + '/' if candidate.get('subdir') else '') + 'package.json'
    url = 'https://api.github.com/repos/' + repo + '/contents/' + path + '?ref=' + candidate['version']
    _, wrapper = _get(url, transport=transport)
    if wrapper.get('encoding') != 'base64' or not isinstance(wrapper.get('content'), str):
        raise PluginShopError('GitHub no devolvió un manifiesto de archivo base64.')
    try:
        raw = base64.b64decode(''.join(wrapper['content'].split()), validate=True)
    except ValueError:
        raise PluginShopError('Manifiesto GitHub base64 inválido.') from None
    if wrapper.get('sha') != hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest():
        raise PluginShopError('El manifiesto GitHub no coincide con su blob hash.')
    manifest = _json(raw, 1048576)
    if manifest.get('name') != candidate['name']:
        raise PluginShopError('La identidad del manifiesto GitHub no coincide con el candidato.')
    return url, raw, manifest, candidate['version']


def _inspect_release(candidate, *, transport):
    # Inspect the release carrying the pinned artifact, never replace it with
    # the repository's mutable default-branch package.json.
    url = 'https://api.github.com/repos/' + candidate['repo'] + '/releases/tags/' + quote(candidate['version'], safe='')
    raw, release = _get(url, transport=transport)
    if release.get('tag_name') != candidate['version'] or not isinstance(release.get('assets'), list):
        raise PluginShopError('La entrega GitHub no corresponde a la versión exacta del catálogo.')
    assets = [a for a in release['assets'] if isinstance(a, dict) and a.get('browser_download_url') == candidate['tarball']['url']]
    if len(assets) != 1:
        raise PluginShopError('La entrega ya no contiene el archivo exacto del catálogo; no se sustituye por otro.')
    digest = assets[0].get('digest')
    if digest is not None and digest != 'sha256:' + candidate['tarball']['sha256']:
        raise PluginShopError('El hash declarado de la entrega no coincide con el catálogo.')
    candidate['inspection'] = {'status': 'RELEASE_METADATA_ONLY_MANIFEST_NOT_INSPECTED',
        'metadata_url': url, 'metadata_sha256': hashlib.sha256(raw).hexdigest(), 'inspected_at': _now(),
        'name': candidate['name'], 'version': candidate['version'], 'manifest_inspected': False,
        'scripts': {}, 'build_script_names': [], 'scripts_status': 'UNKNOWN_NOT_INSPECTED',
        'dependencies': {}, 'optional_dependencies': {}, 'peer_dependencies': {}, 'engines': {},
        'bundle_declared': None, 'source_integrity': candidate['tarball']['sha256'],
        'artifact_integrity_verified': False, 'transitive_dependencies_inspected': False, 'code_audited': False,
        'risks': [HOST_RISK, 'Sólo se contrastó la entrega y la URL del asset. Falta leer el manifiesto dentro del tarball y verificar sus bytes; scripts y dependencias desconocidos.']}
    candidate['status'] = 'inspected'
    candidate['risks'] = candidate['inspection']['risks']
    candidate['history'] = [{'status': 'inspected', 'at': _now(), 'evidence_kind': 'public_release_metadata',
                             'metadata_sha256': candidate['inspection']['metadata_sha256']}]
    return candidate


def inspect_candidate(catalog, candidate_id, *, transport=None):
    candidate = get_candidate(catalog, candidate_id)
    if 'catalog_denied' in candidate['blockers']:
        raise PluginShopError('El catálogo deniega este paquete; no se preparará su instalación.')
    if candidate.get('tarball'):
        return _inspect_release(candidate, transport=transport)
    url, raw, manifest, integrity = _manifest(candidate, transport=transport)
    dsh = manifest.get('dsh') or {}
    if not isinstance(dsh, dict):
        raise PluginShopError('Campo dsh de manifiesto inválido.')
    scripts = _mapping(manifest.get('scripts', {}), 100, 4096)
    dependencies = _mapping(manifest.get('dependencies', {}))
    optional_dependencies = _mapping(manifest.get('optionalDependencies', {}))
    peer_dependencies = _mapping(manifest.get('peerDependencies', {}))
    engines = _mapping(manifest.get('engines', {}), 30, 256)
    build_scripts = sorted(set(scripts) & LIFECYCLE_SCRIPTS)
    risks = [HOST_RISK, 'No se descargó ni auditó el código del plugin ni sus dependencias transitivas.']
    if build_scripts:
        risks.append('Scripts de ciclo de vida declarados: ' + ', '.join(build_scripts) + '; autorización separada por nombre de paquete antes de ejecutarlos.')
    if any(v.startswith(('file:', 'link:', 'workspace:', 'git', 'http:', 'https:')) for v in [*dependencies.values(), *optional_dependencies.values()]):
        risks.append('Hay dependencias por ruta, workspace, Git o URL; inspeccionar destino y fijar versiones transitivas.')
    if not dsh.get('bundle'):
        candidate['blockers'].append('manifest_has_no_dsh_bundle')
    candidate['inspection'] = {'status': 'METADATA_INSPECTED_CODE_NOT_AUDITED', 'metadata_url': url,
                               'metadata_sha256': hashlib.sha256(raw).hexdigest(), 'inspected_at': _now(),
                               'name': candidate['name'], 'version': candidate['version'], 'manifest_inspected': True,
                               'scripts': scripts, 'build_script_names': build_scripts,
                               'dependencies': dependencies, 'optional_dependencies': optional_dependencies,
                               'peer_dependencies': peer_dependencies, 'engines': engines,
                               'bundle_declared': bool(dsh.get('bundle')), 'source_integrity': integrity,
                               'artifact_integrity_verified': False, 'transitive_dependencies_inspected': False,
                               'code_audited': False, 'risks': risks}
    candidate['status'] = 'inspected'
    candidate['risks'] = risks
    candidate['history'] = [{'status': 'inspected', 'at': _now(), 'evidence_kind': 'public_manifest_metadata',
                             'metadata_sha256': candidate['inspection']['metadata_sha256']}]
    return candidate


def create_installation_plan(candidate, *, profile='orgdna-isolated', runtime=None, request_id=None):
    """A dry-run checklist, never a native runtime call or an access grant."""
    if not isinstance(candidate, dict) or candidate.get('status') not in STATES:
        raise PluginShopError('Candidato o estado inválido.')
    _name(candidate.get('name'))
    if not isinstance(candidate.get('provenance'), dict) or not HASH.fullmatch(str(candidate['provenance'].get('entry_sha256', ''))):
        raise PluginShopError('Falta la proveniencia exacta del candidato.')
    profile = _text(profile, 64)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', profile):
        raise PluginShopError('Nombre de perfil inválido; no rutas, espacios ni comandos.')
    runtime = {} if runtime is None else runtime
    if not isinstance(runtime, dict) or set(runtime) - {'dsh_version', 'node_version', 'profile_template', 'installed_packages', 'available_peers'}:
        raise PluginShopError('Contexto runtime contiene campos desconocidos; no se aceptan permisos o credenciales.')
    runtime_copy = {}
    for key in ('dsh_version', 'node_version', 'profile_template'):
        if key in runtime:
            runtime_copy[key] = _text(runtime[key], 128)
    installed = _mapping(runtime.get('installed_packages', {}))
    peers = _strings(runtime.get('available_peers', []), 512, 214)
    request_id = str(uuid.uuid4()) if request_id is None else _text(request_id, 100)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', request_id):
        raise PluginShopError('request_id inválido.')
    inspection = candidate.get('inspection') or {}
    blockers = list(candidate.get('blockers', []))
    if not inspection.get('manifest_inspected'):
        blockers.append('exact_manifest_not_inspected')
    if not candidate.get('install_spec'):
        blockers.append('immutable_install_spec_missing')
    if not candidate['provenance'].get('source_integrity'):
        blockers.append('artifact_integrity_missing')
    if candidate['name'] in installed:
        blockers.append('existing_package_requires_explicit_update_review')
    missing_peers = sorted(set(candidate.get('required_peers', [])) - set(peers) - set(installed)) if peers or installed else []
    checks = [
        {'id': 'source_pin', 'status': 'RECORDED' if candidate.get('install_spec') else 'MISSING', 'detail': 'Recomprobar identidad, versión y hash del artefacto antes de instalar; metadata no verifica los bytes del paquete.'},
        {'id': 'manifest', 'status': 'INSPECTED_METADATA' if inspection.get('manifest_inspected') else 'NOT_RUN', 'detail': 'Manifiesto exacto, bundle y scripts de ciclo de vida.'},
        {'id': 'permissions', 'status': 'REQUIRES_RUNTIME_APPROVAL', 'detail': 'Cada acción plugin_manager exige aprobación del runtime o su modo ya configurado; este plan no cambia ni solicita danger-full-access.'},
        {'id': 'build_scripts', 'status': 'REVIEW_REQUIRED', 'detail': 'Inspeccionar scripts directos y transitivos. approvedBuilds requiere consentimiento separado y persiste por nombre en pnpm-workspace.yaml.'},
        {'id': 'dependencies', 'status': 'NOT_RESOLVED', 'detail': 'Resolver y revisar árbol transitivo, licencias, origen e integridad; no se ejecutó pnpm.'},
        {'id': 'compatibility', 'status': 'UNVERIFIED', 'detail': 'Usar validación SemVer/peers del DSH real. No hay exenciones automáticas ni inferencia a partir de un perfil llamado web.'},
        {'id': 'conflicts', 'status': 'CONFLICT_REPORTED' if candidate['name'] in installed else 'UNVERIFIED', 'detail': 'Comparar bundles, entradas Cordis, precedencia, puertos, servicios y sesiones del perfil; evitar sobrescribir la configuración existente.'},
        {'id': 'backup', 'status': 'NOT_RUN', 'detail': 'Guardar y hashear manifiesto, lockfile, workspace, patch y compatibilidad; registrar archivos inexistentes y verificar lectura de la copia.'},
        {'id': 'rollback', 'status': 'NOT_RUN', 'detail': 'Verificar restauración y recomposición; los efectos de scripts externos pueden permanecer.'},
        {'id': 'runtime_test', 'status': 'NOT_RUN', 'detail': 'Instalado/seleccionado no demuestra cargado o funcional; prueba aislada y confirmación de versión efectiva.'},
    ]
    backup_files = ['package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'cordis.patch.yml', 'compatibility.json']
    pin = {'candidate_id': candidate['id'], 'name': candidate['name'], 'version': candidate['version'],
           'source': candidate['source'], 'repo': candidate.get('repo'), 'subdir': candidate.get('subdir'),
           'install_spec': candidate.get('install_spec'), 'integrity': candidate['provenance'].get('source_integrity'),
           'entry_sha256': candidate['provenance']['entry_sha256'],
           'metadata_sha256': inspection.get('metadata_sha256'), 'catalog_sha256': candidate['provenance'].get('catalog_sha256')}
    result = {'format': 'orgdna/plugin-installation-plan', 'version': 1, 'status': 'PLAN_ONLY',
              'plan_id': 'plugin-plan-' + _hash({'pin': pin, 'profile': profile, 'request_id': request_id})[:24],
              'request_id': request_id, 'created_at': _now(), 'candidate': copy.deepcopy(candidate), 'pin': pin,
              'profile': profile, 'target_scope': 'ALL_SESSIONS_USING_TARGET_PROFILE',
              'recommended_target': 'Nuevo perfil aislado, explícitamente creado y verificado antes de cualquier instalación.',
              'dry_run': True, 'execution_available': False, 'runtime_verified': False, 'native_action_performed': False,
              'checks': checks, 'blockers': sorted(set(blockers)), 'runtime_reported': runtime_copy,
              'missing_peers_reported': missing_peers,
              'backup': {'status': 'NOT_RUN', 'files': backup_files, 'include_absent_files': True,
                         'verify_sha256_and_readability': True, 'never_overwrite_backup': True},
              'rollback': {'status': 'NOT_RUN', 'verify': ['cancel_or_wait_for_exact_request_id', 'restore_each_changed_file_and_hash', 'restore_dependency_tree', 'recompose_or_restart_then_check_errors', 'retest_original_workflow'],
                           'warning': 'Restaurar package.json y lockfile no revierte efectos arbitrarios de scripts, accesos externos ni permisos persistidos.'},
              'approvals_required': ['exact_source_version_and_target_profile', 'native_plugin_manager_runtime_approval_each_call', 'dependency_build_scripts_if_any', 'activation_after_isolated_tests'],
              'runtime_actions': [{'stage': 'inventory_before_change', 'tool': 'plugin_manager', 'action': 'list_bundles', 'approval': 'native_runtime'},
                                  {'stage': 'install_if_approved', 'tool': 'plugin_manager', 'action': 'install_bundle', 'target': candidate.get('install_spec'), 'enabled': False, 'approval': 'native_runtime'},
                                  {'stage': 'verify_saved_and_loaded_state', 'tool': 'plugin_manager', 'action': 'list_bundles', 'approval': 'native_runtime'}],
              'runtime_action_notice': 'Plantillas informativas: el tool oficial usa target y no expone inspect ni requestId. El perfil es el actual del runtime; verificar antes de llamar.',
              'service_tracking': {'status': 'NOT_CALLED', 'request_id': request_id,
                                   'note': 'El identificador puede usarse en la API de servicio installBundle/waitForInstall/cancelInstall si el cliente autorizado la soporta; no es un argumento del tool.'},
              'expected_persistent_changes': backup_files + ['node_modules and package-manager caches'],
              'risks': list(candidate.get('risks', [HOST_RISK])) + ['La instalación y selección alteran el perfil y pueden afectar a todas sus sesiones. enabled:false no contiene scripts ni el código Host.'],
              'documentation': [SOURCE_REPOSITORY, MANAGER_DOCS]}
    return result


def transition_candidate(candidate, status, *, evidence=None):
    """Store an operator report, never translate a report into installed=true."""
    if not isinstance(candidate, dict) or candidate.get('status') not in STATES or status not in STATES:
        raise PluginShopError('Estado del candidato inválido.')
    current = STATES.index(candidate['status'])
    if current + 1 >= len(STATES) or STATES[current + 1] != status or status == 'inspected':
        raise PluginShopError('Transición inválida. Inspeccionar metadata primero y conservar la secuencia de reportes.')
    if not isinstance(evidence, dict) or set(evidence) - {'candidate_id', 'version', 'entry_sha256', 'operator', 'note', 'request_id', 'profile', 'runtime_version', 'result', 'evidence_ref', 'acknowledged'}:
        raise PluginShopError('Se requiere evidencia acotada; no credenciales ni permisos del runtime.')
    if evidence.get('candidate_id') != candidate.get('id') or evidence.get('version') != candidate.get('version') or evidence.get('entry_sha256') != candidate.get('provenance', {}).get('entry_sha256'):
        raise PluginShopError('La evidencia no corresponde a esta identidad y versión exactas.')
    for field in ('operator', 'note', 'request_id'):
        _text(evidence.get(field), 2000 if field == 'note' else 128)
    if evidence.get('acknowledged') is not True:
        raise PluginShopError('Falta la confirmación explícita del operador para este reporte.')
    if status != 'approved_by_operator':
        previous_request = candidate.get('history', [{}])[-1].get('evidence', {}).get('request_id')
        if previous_request != evidence.get('request_id'):
            raise PluginShopError('El reporte debe mantener el request_id aprobado; un plan nuevo requiere revisión nueva.')
        for field in ('profile', 'runtime_version', 'evidence_ref'):
            _text(evidence.get(field), 512)
        if evidence.get('result') not in ('passed', 'failed', 'blocked'):
            raise PluginShopError('El reporte necesita un resultado passed, failed o blocked.')
    if status == 'active_reported':
        previous = candidate.get('history', [])[-1] if candidate.get('history') else {}
        if previous.get('evidence', {}).get('result') != 'passed' or evidence.get('result') != 'passed':
            raise PluginShopError('La activación reportada necesita pruebas reportadas como passed; un fallo no se convierte en éxito.')
        prior = previous['evidence']
        if any(evidence.get(k) != prior.get(k) for k in ('request_id', 'profile', 'runtime_version')):
            raise PluginShopError('La activación reportada debe referirse al mismo request, perfil y runtime probado.')
    result = copy.deepcopy(candidate)
    result.update(status=status, runtime_verified=False, installed=False, active=False)
    result.setdefault('history', []).append({'status': status, 'at': _now(), 'evidence_kind': 'OPERATOR_REPORT_UNVERIFIED', 'evidence': copy.deepcopy(evidence)})
    result['status_notice'] = 'Reporte local del operador; no verifica ni ejecuta instalación o activación en DSH.'
    return result


CAPABILITY_GROUPS = {
    'browser_testing': {'label': 'Pruebas de navegador e interfaz', 'signals': 'frontend web browser navegador interfaz e2e playwright accesibilidad react ux mobile', 'search': 'browser playwright e2e accessibility', 'tools': 'browser playwright screenshot'},
    'dependency_security': {'label': 'Seguridad y dependencias', 'signals': 'security seguridad privacidad privacy build dependencias auditoria audit', 'search': 'security dependency audit vulnerability', 'tools': 'security audit dependency'},
    'repository_analysis': {'label': 'Análisis y navegación de repositorio', 'signals': 'backend frontend architecture arquitectura python typescript rust implementer codigo', 'search': 'code repository search analysis', 'tools': 'code repo search'},
    'testing_quality': {'label': 'Pruebas y calidad', 'signals': 'qa pruebas testing calidad evidence assurance', 'search': 'test quality coverage validation', 'tools': 'test validate coverage'},
    'coordination': {'label': 'Coordinación y tareas de equipo', 'signals': 'ceo planner equipo jerarquia squad collaboration coordination', 'search': 'agent team workflow task coordination', 'tools': 'ops_plan dispatch task'},
    'observability': {'label': 'Observabilidad y diagnóstico', 'signals': 'sre performance rendimiento metrics metricas observabilidad incident release', 'search': 'metrics observability monitoring log', 'tools': 'metrics monitor diagnose'},
    'knowledge': {'label': 'Documentación y recuperación de conocimiento', 'signals': 'docs documentacion memoria memory retrieval search datos data', 'search': 'memory knowledge documentation retrieval', 'tools': 'memory docs search'},
    'data_tools': {'label': 'Datos, bases de datos y migraciones', 'signals': 'data datos sql postgres redis migraciones database quant', 'search': 'database sql data migration', 'tools': 'sql database data'},
}


def capability_wishlist(organization, catalog, *, tool_catalog=None, limit=20):
    if not isinstance(organization, dict) or type(limit) is not int or not 1 <= limit <= 50:
        raise PluginShopError('Organización o límite de capacidades inválido.')
    agents = organization.get('agents', [])
    if not isinstance(agents, list) or len(agents) > 1000:
        raise PluginShopError('Lista de perfiles inválida.')
    tools = (tool_catalog or {}).get('tools', []) if isinstance(tool_catalog, dict) else []
    if not isinstance(tools, list):
        raise PluginShopError('Catálogo de herramientas inválido.')
    gaps, suggestions = [], []
    for key, rule in CAPABILITY_GROUPS.items():
        signals = _tokens(rule['signals'])
        roles = []
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            # Only descriptive fields; prompts and external instructions never become actions.
            context = _dump({k: agent[k] for k in ('role', 'name', 'title', 'skills', 'responsibilities', 'proposed_skills') if k in agent})
            if signals & _tokens(context):
                roles.append(str(agent.get('id') or agent.get('name') or agent.get('role', 'profile')))
        analysis_context = _dump({k: organization[k] for k in ('repository', 'analysis', 'competency_gaps') if k in organization})
        if not roles and not (signals & _tokens(analysis_context)):
            continue
        tool_terms = _tokens(rule['tools'])
        declared_tools = [t['name'] for t in tools if isinstance(t, dict) and isinstance(t.get('name'), str) and tool_terms & _tokens(t['name'] + ' ' + str(t.get('description', '')))]
        matched = search_catalog(catalog, rule['search'], limit=min(3, limit))['results']
        gap = {'id': key, 'capability': rule['label'], 'required_by_profiles': roles,
               'status': 'RUNTIME_COVERAGE_UNVERIFIED' if declared_tools else 'DECLARATION_GAP',
               'declared_tools': declared_tools[:20], 'tool_runtime_verified': False,
               'reason': 'Capacidad relevante a perfiles/señales del proyecto. Las herramientas declaradas no demuestran disponibilidad o cobertura real.',
               'candidates': [c['id'] for c in matched], 'candidate_count': len(matched), 'coverage': 'PROPOSED_NOT_TESTED'}
        gaps.append(gap)
        for candidate in matched:
            suggestions.append({'capability_id': key, 'candidate_id': candidate['id'], 'name': candidate['name'],
                                'version': candidate['version'], 'source': candidate['source'],
                                'reason': candidate['match']['reason'] + ' Términos: ' + ', '.join(candidate['match']['terms']),
                                'risk': HOST_RISK, 'coverage': 'PROPOSED_NOT_TESTED', 'provenance': candidate['provenance']})
    return {'status': 'PROPOSED_NOT_TESTED', 'gaps': gaps[:limit], 'suggestions': suggestions[:limit],
            'runtime_verified': False, 'catalog_count': catalog.get('count', 0),
            'warning': 'El wishlist facilita descubrir e inspeccionar candidatos. No instala, concede permisos ni garantiza cobertura universal.'}
