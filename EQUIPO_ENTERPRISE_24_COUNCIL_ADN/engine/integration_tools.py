"""Local, explicit addon/catalog preparation; never installs or activates plugins.

Catalog reads are read-only. Installation documents and operator-reported states
are not runtime verification. Secrets, API authority and live bridge grants are
not part of saved integration settings or generated addon downloads.
"""
from __future__ import annotations
import copy
import hashlib
import io
import json
import re
import zipfile

ACTIONS = frozenset({'cordis-prepare', 'plugin-shop-refresh', 'plugin-shop-search',
                     'plugin-shop-inspect', 'plugin-shop-plan', 'plugin-shop-status',
                     'plugin-shop-wishlist', 'dsh-connect', 'dsh-disconnect', 'dsh-status',
                     'dsh-read-profiles', 'dsh-read-team', 'dsh-preview-import', 'dsh-prepare-task-plan'})
DSH_ACTIONS = frozenset(action for action in ACTIONS if action.startswith('dsh-'))
CORDIS_JSON_DOWNLOADS = {
    'cordis-implementation.json': ('recipe', 'extended-native/implementation.json'),
    'cordis-definitions.json': ('definitions', 'extended-native/definitions.json'),
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class IntegrationTools:
    def __init__(self, state):
        self.state = state
        self.cordis_cache = None
        self.catalog = None
        self.search = None
        self.wishlist = None
        self.inspected = {}
        self.settings = {'cordis': {'enabled': False, 'requested_version': None}, 'plugin_shop': {'source': 'github_pages'}}
        self.plans = []
        self.reported = {}
        self.dsh_manager = None
        self.dsh_status = {'status': 'disconnected', 'connected': False, 'identity_verified': False,
                           'dispatch_supported': False}
        self.dsh_profiles = self.dsh_team = self.dsh_preview = self.dsh_plan = None
        self.dsh_preview_identity = None

    @staticmethod
    def _shop():
        if __package__:
            from . import plugin_shop
        else:
            import plugin_shop
        return plugin_shop

    def public_cordis(self):
        if self.cordis_cache is None:
            return {'status': 'unprepared', 'settings': copy.deepcopy(self.settings['cordis']), 'integrated_exports': None,
                    'runtime_verified': False, 'installed': False, 'enabled': False}
        current = self.state.organization is not None and not self.state.generation_stale and self.cordis_cache['fingerprint'] == fingerprint(self.state.organization) and self.cordis_cache.get('library_revision') == self.state.capabilities_hub.library.status()['revision']
        return {'status': 'ready' if current else 'stale', 'settings': copy.deepcopy(self.settings['cordis']),
                'manifest': copy.deepcopy(self.cordis_cache['manifest']), 'dry_run': copy.deepcopy(self.cordis_cache['dry_run']),
                'artifact': copy.deepcopy(self.cordis_cache['artifact']) if current else None,
                'integrated_exports': copy.deepcopy(self.cordis_cache.get('integrated_exports', {})) if current else None,
                'runtime_verified': False, 'installed': False, 'enabled': False}

    def _freeze_integrated_downloads(self, result):
        """Expose only the two named, validated members of the prepared ZIP."""
        declared = result['manifest'].get('integrated_exports')
        if declared is None:
            return {}, {}  # Older addon caches remain downloadable as ZIP only.
        if not isinstance(declared, dict):
            raise ValueError('El manifiesto de exportaciones integradas no es válido.')
        if __package__:
            from . import core
        else:
            import core
        expected_ids = [agent['id'] for agent in self.state.organization['agents']]
        metadata, payloads = {}, {}
        try:
            with zipfile.ZipFile(io.BytesIO(result['zip_bytes'])) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ValueError('El addon contiene nombres ZIP duplicados.')
                archived_manifest = json.loads(archive.read('addon-manifest.json'))
                for alias, (role, path) in CORDIS_JSON_DOWNLOADS.items():
                    entry = declared.get(role)
                    if (not isinstance(entry, dict) or entry.get('path') != path or
                            archived_manifest.get('integrated_exports', {}).get(role) != entry or
                            entry.get('requires_addon_activation') is not True):
                        raise ValueError('La descarga integrada no coincide con el miembro fijo del manifiesto del addon.')
                    filename = entry.get('filename')
                    if (not isinstance(filename, str) or len(filename) > 255 or
                            re.fullmatch(r'[A-Za-z0-9_.-]+\.json', filename) is None):
                        raise ValueError('Nombre de descarga integrada no válido.')
                    info = archive.getinfo(path)
                    if not 0 < info.file_size <= 4 * 1024 * 1024:
                        raise ValueError('El JSON integrado supera el límite de tamaño seguro.')
                    payload = archive.read(path)
                    if (type(entry.get('bytes')) is not int or entry['bytes'] != len(payload) or
                            entry.get('sha256') != hashlib.sha256(payload).hexdigest()):
                        raise ValueError('Los bytes del JSON integrado no coinciden con el hash de su manifiesto.')
                    document = json.loads(payload)
                    validator = core.validate_recipe if role == 'recipe' else core.validate_definitions
                    if not validator(document)['valid'] or [agent['id'] for agent in document.get('agents', [])] != expected_ids:
                        raise ValueError('El JSON integrado no conserva exactamente los miembros del ADN actual.')
                    metadata[role] = dict(copy.deepcopy(entry), url='/download/' + alias)
                    payloads[alias] = payload
        except (KeyError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('El addon no contiene los dos JSON integrados verificables esperados.') from exc
        return metadata, payloads

    def public_shop(self):
        metadata = None
        if self.catalog is not None:
            metadata = {k: v for k, v in self.catalog.items() if k != 'candidates'}
            metadata['candidate_count'] = len(self.catalog.get('candidates', []))
            if isinstance(metadata.get('denied'), list):
                metadata['denied_count'] = len(metadata['denied'])
                metadata['denied'] = metadata['denied'][:100]
        return copy.deepcopy({'status': 'loaded' if self.catalog is not None else 'not_loaded',
            'catalog': metadata, 'search': self.search, 'wishlist': self.wishlist,
            'inspected': self.inspected, 'plans': self.plans, 'settings': self.settings['plugin_shop'],
            'reported_candidates': self.reported, 'runtime_verified': False,
            'installation_performed': False})

    def public_dsh(self):
        # cached_status checks expiry locally, with no HTTP or renewed authority.
        if self.dsh_manager is not None:
            self.dsh_status = self.dsh_manager.cached_status()
        current_preview = bool(self.dsh_preview is not None and not self.state.generation_stale and
            self.dsh_preview_identity and self.dsh_preview_identity['fingerprint'] == fingerprint(self.state.organization))
        result = copy.deepcopy({'status': self.dsh_status, 'profiles': self.dsh_profiles,
            'team': self.dsh_team, 'import_preview': self.dsh_preview if current_preview else None,
            'import_preview_stale': self.dsh_preview is not None and not current_preview,
            'import_preview_identity': self.dsh_preview_identity,
            'task_plan': self.dsh_plan, 'runtime_write_supported': False,
            'status_is_last_explicit_check': True})
        if not self.dsh_status.get('live_connection'):
            for key in ('profiles', 'team', 'import_preview'):
                if isinstance(result[key], dict):
                    result[key]['live_connection'] = False
                    result[key]['historical_snapshot'] = True
        return result

    def adopt_connection(self, previous):
        """A user-paired read-only DSH session belongs to the app, not a project."""
        self.dsh_manager = previous.dsh_manager
        self.dsh_status = copy.deepcopy(previous.dsh_status)
        self.dsh_profiles = copy.deepcopy(previous.dsh_profiles)
        self.dsh_team = copy.deepcopy(previous.dsh_team)
        # Import previews and task plans are tied to the previously selected ADN.
        self.dsh_preview = self.dsh_plan = None
        self.dsh_preview_identity = None

    def _connection(self):
        if self.dsh_manager is None:
            if __package__:
                from .dsh_connection import DSHConnectionManager
            else:
                from dsh_connection import DSHConnectionManager
            self.dsh_manager = DSHConnectionManager()
        return self.dsh_manager

    def _apply_dsh(self, action, body):
        state = self.state
        if action == 'dsh-disconnect':
            if self.dsh_manager is not None:
                self.dsh_status = self.dsh_manager.disconnect()
            self.dsh_manager = None
            self.dsh_profiles = self.dsh_team = self.dsh_preview = self.dsh_plan = None
            self.dsh_preview_identity = None
        elif action == 'dsh-connect':
            if body.get('confirmed') is not True:
                raise ValueError('Confirma el emparejamiento local de sólo lectura con el código mostrado por DSH.')
            code = body.get('pairing_code')
            port = body.get('port')
            if not isinstance(code, str) or re.fullmatch(r'[A-Za-z0-9_-]{43}', code) is None:
                raise ValueError('Introduce el código de emparejamiento local de DSH, sin espacios.')
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError('Puerto local inválido.')
            state._sensitive_values.add(code)
            self.dsh_status = self._connection().connect(port, code)
            self.dsh_profiles = self.dsh_team = self.dsh_preview = self.dsh_plan = None
            self.dsh_preview_identity = None
        elif action == 'dsh-status':
            if self.dsh_manager is not None:
                self.dsh_status = self.dsh_manager.status()
        else:
            manager = self._connection()
            if action == 'dsh-read-profiles':
                result = manager.read_profiles()
                self.dsh_status = manager.cached_status()
                self.dsh_profiles = result
            elif action == 'dsh-read-team':
                result = manager.read_team(body.get('team_name', ''))
                self.dsh_status = manager.cached_status()
                self.dsh_team = result
            elif action == 'dsh-preview-import':
                state.require_version(body)
                kind = body.get('document_kind', 'definitions')
                if kind not in ('definitions', 'implementation', 'council'):
                    raise ValueError('Selecciona definitions, implementation o council para una vista previa sin importación.')
                snapshot = state._exports()['snapshot']
                document = getattr(snapshot, kind)
                self.dsh_preview = manager.preview_import(document)
                self.dsh_preview_identity = {'organization_id': state.organization.get('organization_id'),
                    'state_version': state.organization.get('state_version'),
                    'fingerprint': fingerprint(state.organization), 'document_kind': kind}
                self.dsh_status = manager.cached_status()
            elif action == 'dsh-prepare-task-plan':
                plan = body.get('plan')
                if not isinstance(plan, dict):
                    raise ValueError('El plan debe ser un objeto para revisión; este conector no despacha tareas.')
                self.dsh_plan = manager.prepare_task_plan(plan)
            else:
                raise ValueError('Acción de conexión DSH no admitida.')
        state.receipt(action, 'success', 'Estado de conexión local actualizado. Sólo lectura; no se importaron perfiles, instalaron plugins ni despacharon tareas.')
        return state.public()

    def saved(self):
        # No cache, source content, network credentials, addon bytes or activation.
        return copy.deepcopy({'version': 1, 'settings': self.settings,
                              'plans': self.plans, 'reported_candidates': self.reported})

    def load_saved(self, raw=None):
        raw = copy.deepcopy(raw or {})
        if not isinstance(raw, dict) or set(raw) - {'version', 'settings', 'plans', 'reported_candidates'} or raw.get('version', 1) != 1:
            raise ValueError('Formato de integraciones guardadas no válido.')
        settings = raw.get('settings', {'cordis': {'enabled': False, 'requested_version': None}, 'plugin_shop': {'source': 'github_pages'}})
        if (not isinstance(settings, dict) or set(settings) != {'cordis', 'plugin_shop'} or
                not isinstance(settings.get('cordis'), dict) or set(settings['cordis']) - {'enabled', 'requested_version'} or
                settings['cordis'].get('enabled') is not False or
                (settings['cordis'].get('requested_version') is not None and (not isinstance(settings['cordis']['requested_version'], str) or len(settings['cordis']['requested_version']) > 64)) or
                not isinstance(settings.get('plugin_shop'), dict) or
                set(settings['plugin_shop']) != {'source'} or settings['plugin_shop']['source'] != 'github_pages'):
            raise ValueError('Los ajustes guardados no pueden activar extensiones ni conceder acceso.')
        plans = raw.get('plans', [])
        reported = raw.get('reported_candidates', {})
        if (not isinstance(plans, list) or len(plans) > 100 or any(not isinstance(p, dict) for p in plans) or
                not isinstance(reported, dict) or len(reported) > 200 or any(not isinstance(p, dict) for p in reported.values())):
            raise ValueError('Registros de plugins inválidos o excesivos.')
        # Never revive a declaration as a verified installation after restart.
        def unverify(value):
            if isinstance(value, dict):
                for flag in ('runtime_verified', 'installed', 'active', 'execution_available',
                             'native_action_performed', 'enabled', 'connected', 'identity_verified', 'live_connection'):
                    if flag in value:
                        value[flag] = False
                for child in value.values():
                    unverify(child)
            elif isinstance(value, list):
                for child in value:
                    unverify(child)
        for row in list(plans) + list(reported.values()):
            row['runtime_verified'] = False
            unverify(row)
        for row in reported.values():
            row['historical_reference'] = True
        self.settings, self.plans, self.reported = settings, plans, reported
        self.catalog = self.search = self.wishlist = self.cordis_cache = None
        self.inspected = {}

    def _candidate(self, candidate_id):
        if not isinstance(candidate_id, str) or not candidate_id or len(candidate_id) > 300:
            raise ValueError('Selecciona un candidato del catálogo consultado.')
        if self.catalog is None:
            raise ValueError('Consulta el catálogo actual y vuelve a inspeccionar el candidato; los reportes guardados son históricos.')
        rows = self.catalog.get('candidates', [])
        current = next((copy.deepcopy(row) for row in rows if row.get('id') == candidate_id), None)
        if current is None:
            raise ValueError('El candidato no está en el catálogo actual. Selecciona su identidad exacta.')
        def matches(row):
            return (row.get('id') == current.get('id') and row.get('version') == current.get('version') and
                    row.get('provenance', {}).get('entry_sha256') == current.get('provenance', {}).get('entry_sha256'))
        report = self.reported.get(candidate_id)
        if report and not report.get('historical_reference') and matches(report):
            return copy.deepcopy(report)
        inspected = self.inspected.get(candidate_id)
        if inspected and matches(inspected):
            return copy.deepcopy(inspected)
        return current

    def apply(self, action, body):
        state = self.state
        if state.generation._active() and action not in DSH_ACTIONS:
            raise ValueError('Termina o cancela la generación pendiente antes de preparar integraciones.')
        if state.redact(body) != body:
            raise ValueError('Una credencial aparece en los datos de integración. No se puede guardar ni transmitir.')
        if action in DSH_ACTIONS:
            try:
                return self._apply_dsh(action, body)
            finally:
                if self.dsh_manager is not None:
                    self.dsh_status = self.dsh_manager.cached_status()
        if action == 'cordis-prepare':
            state.require_version(body)
            if set(body) - {'expected_state_version'}:
                raise ValueError('La preparación Cordis usa sólo el ADN actual; no acepta claves ni configuración de otro equipo.')
            if __package__:
                from .cordis_extension import build_cordis_addon
                from .capability_deployment import export_skillhub_library
            else:
                from cordis_extension import build_cordis_addon
                from capability_deployment import export_skillhub_library
            result = build_cordis_addon(state.organization, teams_config=state._exports()['snapshot'].definitions,
                skillhub_manifest=export_skillhub_library(state.capabilities_hub.library, state.organization))
            required = {'manifest', 'dry_run', 'zip_bytes', 'filename'}
            if not isinstance(result, dict) or not required <= set(result) or not isinstance(result['zip_bytes'], bytes):
                raise ValueError('La extensión no devolvió un paquete local verificable.')
            safe = {k: result[k] for k in ('manifest', 'dry_run', 'filename')}
            if state.redact(safe) != safe:
                raise ValueError('La extensión contiene una credencial; no se ha preparado para descarga.')
            if not result['filename'].endswith('.zip') or any(c in result['filename'] for c in ('/', '\\', '\n', '\r', '"')):
                raise ValueError('Nombre de paquete Cordis no válido.')
            artifact = {'filename': result['filename'], 'url': '/download/cordis-addon.zip',
                        'sha256': hashlib.sha256(result['zip_bytes']).hexdigest(), 'bytes': len(result['zip_bytes'])}
            integrated_exports, integrated_payloads = self._freeze_integrated_downloads(result)
            self.settings['cordis'] = {'enabled': False, 'requested_version': str(result['manifest'].get('version', ''))[:64]}
            self.cordis_cache = {**safe, 'artifact': artifact, 'payload': result['zip_bytes'],
                                 'integrated_exports': integrated_exports, 'integrated_payloads': integrated_payloads,
                                 'fingerprint': fingerprint(state.organization), 'library_revision': state.capabilities_hub.library.status()['revision']}
            state.receipt(action, 'success', 'Extensión Cordis preparada para los mismos miembros. No instalada ni activada; runtime pendiente de verificar.')
        else:
            module = self._shop()
            if action == 'plugin-shop-refresh':
                source = body.get('source', self.settings['plugin_shop']['source'])
                candidate_catalog = module.fetch_catalog(source=source)
                if state.redact(candidate_catalog) != candidate_catalog:
                    raise ValueError('El catálogo contiene una credencial de sesión; se descartó.')
                self.catalog = candidate_catalog
                self.settings['plugin_shop']['source'] = source
                self.search = self.wishlist = None
                self.inspected = {}
                current = {row['id']: row for row in self.catalog.get('candidates', [])}
                def stale(candidate):
                    if not isinstance(candidate, dict):
                        return True
                    row = current.get(candidate.get('id'))
                    return not row or row.get('version') != candidate.get('version') or row.get('provenance', {}).get('entry_sha256') != candidate.get('provenance', {}).get('entry_sha256')
                for report in self.reported.values():
                    report['stale_against_catalog'] = bool(stale(report))
                for saved_plan in self.plans:
                    saved_plan['stale_against_catalog'] = bool(stale(saved_plan.get('candidate', {})))
            elif action == 'plugin-shop-search':
                if self.catalog is None:
                    raise ValueError('Consulta primero el catálogo Plugin Shop.')
                self.search = module.search_catalog(self.catalog, body.get('query', ''),
                    capabilities=body.get('capabilities'), limit=body.get('limit', 30), offset=body.get('offset', 0),
                    category=body.get('category'), sort=body.get('sort', 'source'))
            elif action == 'plugin-shop-wishlist':
                state.require_version(body)
                if self.catalog is None:
                    raise ValueError('Consulta primero el catálogo para buscar capacidades faltantes.')
                self.wishlist = module.capability_wishlist(state.organization, self.catalog,
                    tool_catalog=state.tool_catalog(), limit=body.get('limit', 20))
            elif action == 'plugin-shop-inspect':
                if self.catalog is None:
                    raise ValueError('Consulta primero el catálogo Plugin Shop.')
                candidate = module.inspect_candidate(self.catalog, body.get('candidate_id'))
                if len(self.inspected) >= 200 and candidate['id'] not in self.inspected:
                    raise ValueError('Máximo de 200 inspecciones locales por consulta de catálogo.')
                self.inspected[candidate['id']] = candidate
            elif action == 'plugin-shop-plan':
                candidate = self._candidate(body.get('candidate_id'))
                plan = module.create_installation_plan(candidate, profile=body.get('profile', 'orgdna-isolated'),
                    runtime=None, request_id=body.get('request_id'))
                if state.redact(plan) != plan:
                    raise ValueError('El plan contiene una credencial; no se puede guardar.')
                if not any(p.get('plan_id') == plan.get('plan_id') for p in self.plans):
                    if len(self.plans) >= 100:
                        raise ValueError('Máximo de 100 planes locales. Conserva los existentes antes de ampliar el registro.')
                    self.plans.append(plan)
            elif action == 'plugin-shop-status':
                candidate = self._candidate(body.get('candidate_id'))
                updated = module.transition_candidate(candidate, body.get('status'), evidence=body.get('evidence'))
                if state.redact(updated) != updated:
                    raise ValueError('El reporte contiene una credencial; no se puede guardar.')
                if len(self.reported) >= 200 and candidate['id'] not in self.reported:
                    raise ValueError('Máximo de 200 reportes locales de candidatos.')
                self.reported[candidate['id']] = updated
            else:
                raise ValueError('Acción de integración desconocida.')
            state.receipt(action, 'success', 'Operación local de catálogo o plan completada. No se instaló ni activó ningún plugin; los estados operativos son declaraciones sin verificación del runtime.')
        if action in ('cordis-prepare', 'plugin-shop-refresh', 'plugin-shop-plan', 'plugin-shop-status'):
            state.project['dirty'] = True
        return state.public()

    def download(self, filename='cordis-addon.zip'):
        if self.public_cordis()['status'] != 'ready':
            raise ValueError('Prepara de nuevo la extensión Cordis para el ADN actual antes de descargar.')
        if filename == 'cordis-addon.zip':
            return self.cordis_cache['payload'], self.cordis_cache['filename']
        if filename not in CORDIS_JSON_DOWNLOADS or filename not in self.cordis_cache.get('integrated_payloads', {}):
            raise ValueError('No hay una descarga integrada preparada para ese archivo; vuelve a preparar el addon.')
        role = CORDIS_JSON_DOWNLOADS[filename][0]
        return self.cordis_cache['integrated_payloads'][filename], self.cordis_cache['integrated_exports'][role]['filename']
