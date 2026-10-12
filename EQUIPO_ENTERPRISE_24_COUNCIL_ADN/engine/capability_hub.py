"""Explicit UI adapter for project-local capability references and CAS assignments."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import uuid
try:
    from .capability_library import CapabilityLibrary
except ImportError:
    from capability_library import CapabilityLibrary

ACTIONS = frozenset({'capability-search', 'capability-import', 'capability-save', 'capability-preview',
                     'capability-apply', 'capability-discard', 'capability-recommend', 'capability-assignments', 'capability-source-read', 'capability-deployment-plan', 'capability-deployment-discard', 'capability-audit'})

class CapabilityHub:
    def __init__(self, state, library_id=None, saved_revision=None):
        self.state = state
        self.library_id = library_id or uuid.uuid4().hex
        if not isinstance(self.library_id, str) or not re.fullmatch(r'[a-f0-9]{32}', self.library_id):
            raise ValueError('Identidad local de biblioteca inválida.')
        self.library = CapabilityLibrary(state.project_store.root / '_capabilities' / 'registry.sqlite3', self.library_id)
        if saved_revision is not None and (type(saved_revision) is not int or saved_revision < 0):
            raise ValueError('Revisión guardada de biblioteca inválida.')
        if saved_revision and self.library.status()['revision'] == 0:
            raise ValueError('La biblioteca guardada no está disponible. Recupera la carpeta data/projects completa antes de abrir este proyecto.')
        self.saved_revision = saved_revision
        self.query = ''; self.offset = 0; self.assignment_offset = 0; self.audit_offset = 0
        self.plan = None; self.recommendations = None; self.last_import = None; self.reference = None; self.deployment = None; self.deployment_identity = None

    def saved(self):
        return {'library_id': self.library_id, 'library_revision': self.library.status()['revision']}

    def public(self):
        ids = [a['id'] for a in (self.state.organization or {}).get('agents', [])]
        assignments = self.library.manifest_page(offset=self.assignment_offset, limit=50, agent_ids=ids)
        names = {iid: self.library.read_items([iid])[0]['name'] for iid in dict.fromkeys(a['item_id'] for a in assignments['items'])}
        for assignment in assignments['items']:
            assignment['name'] = names[assignment['item_id']]
        return {'saved_revision': self.saved_revision, 'saved_revision_status': 'unknown' if self.saved_revision is None else ('current' if self.saved_revision == self.library.status()['revision'] else 'changed'), 'saved_revision_differs': self.saved_revision is not None and self.saved_revision != self.library.status()['revision'], 'status': self.library.status(), 'page': self.library.search(self.query, offset=self.offset, limit=50),
                'audit_page': self.library.audit_page(self.audit_offset, limit=50), 'assignment_page': assignments, 'plan': copy.deepcopy(self.plan), 'deployment': self.public_deployment(),
                'reference': copy.deepcopy(self.reference), 'recommendations': copy.deepcopy(self.recommendations), 'last_import': copy.deepcopy(self.last_import)}

    def _deployment_current(self):
        if not self.deployment or self.state.generation_stale or self.state.organization is None:
            return False
        return self.deployment_identity == [hashlib.sha256(json.dumps(self.state.organization, sort_keys=True).encode()).hexdigest(), self.library.status()['revision']]

    def public_deployment(self):
        if not self.deployment:
            return None
        result = {k: copy.deepcopy(v) for k, v in self.deployment.items() if k not in ('base_snapshot', 'target_snapshot')}
        result.update(stale=not self._deployment_current(), applied=False, runtime_verified=False,
                      download_url='/download/capability-update.json' if self._deployment_current() else None)
        return result

    def deployment_download(self):
        if not self._deployment_current():
            raise ValueError('El plan de actualización cambió o no existe. Prepara uno nuevo.')
        return (json.dumps(self.deployment, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()

    def selection(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('Selecciona los destinatarios.')
        if raw.get('mode') == 'subteams':
            teams = (self.state.organization or {}).get('functional_subteams', []) + self.state.records.get('subteams', [])
            requested = raw.get('subteam_ids')
            if not isinstance(requested, list) or not requested:
                raise ValueError('Selecciona al menos un subequipo actual.')
            indexed = {team['id']: team for team in teams}
            if any(key not in indexed for key in requested):
                raise ValueError('Un subequipo ya no existe. Vuelve a seleccionar.')
            ids = list(dict.fromkeys(a for key in requested for a in indexed[key].get('member_ids', [])))
            return {'mode': 'selected', 'agent_ids': ids}
        return copy.deepcopy(raw)

    def catalog_identity(self):
        catalog = self.state.integrations.catalog
        if catalog is None:
            return None
        return catalog.get('catalog_sha256') or hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()

    def catalog_items(self, body):
        if body.get('catalog_identity') != self.catalog_identity() or self.catalog_identity() is None:
            raise ValueError('El catálogo cambió. Actualiza los resultados y vuelve a seleccionar.')
        ids = body.get('candidate_ids')
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise ValueError('Selecciona IDs únicos del catálogo actual.')
        result = []
        for cid in ids:
            candidate = self.state.integrations._candidate(cid)
            provenance = candidate.get('provenance', {})
            source_id = candidate['id']
            identity = hashlib.sha256(json.dumps([source_id, candidate.get('version'), provenance.get('entry_sha256')], sort_keys=True).encode()).hexdigest()
            result.append({'id': 'catalog-'+identity, 'kind': 'plugin_package', 'name': candidate.get('name', source_id),
                'description': candidate.get('description', ''), 'content': '', 'tags': candidate.get('capabilities', [])[:128],
                'tool_needs': [], 'role_evidence': [], 'provenance': {'type': 'catalog_snapshot',
                    'source_id': source_id, 'sha256': provenance.get('entry_sha256') or self.catalog_identity(),
                    'evidence': 'Catálogo público consultado '+str(self.catalog_identity())+'; versión '+str(candidate.get('version'))+'; metadatos declarados, sin ejecución verificada.'}})
        return result

    def reference_items(self, body):
        keys = body.get('reference_ids') or []
        if not keys:
            return []
        if not self.reference or body.get('reference_hash') != self.reference.get('source_hash'):
            raise ValueError('La referencia cambió; vuelve a revisar su contenido.')
        indexed = {item['id']: item for item in self.reference.get('item_proposals', [])}
        if not isinstance(keys, list) or any(key not in indexed for key in keys):
            raise ValueError('Selecciona capacidades de la referencia actual.')
        return [copy.deepcopy(indexed[key]) for key in dict.fromkeys(keys)]

    def apply(self, action, body):
        state = self.state
        if state.generation._active():
            raise ValueError('Termina o cancela la generación pendiente antes de cambiar capacidades.')
        if state.redact(body) != body:
            raise ValueError('No guardes credenciales en capacidades, referencias ni instrucciones.')
        if action == 'capability-deployment-plan':
            state.require_version(body)
            if __package__:
                from .capability_deployment import build_skillhub_delta, export_skillhub_library
            else:
                from capability_deployment import build_skillhub_delta, export_skillhub_library
            baseline = body.get('baseline')
            target = export_skillhub_library(self.library, state.organization)
            deployment = build_skillhub_delta(baseline, target, state.organization)
            self.deployment = deployment
            self.deployment_identity = [hashlib.sha256(json.dumps(state.organization, sort_keys=True).encode()).hexdigest(), self.library.status()['revision']]
            state.receipt(action, 'success', 'Actualización DSH comparada localmente. Pendiente de aplicar, recargar y verificar; ningún archivo del runtime fue modificado.')
        elif action == 'capability-deployment-discard':
            self.deployment = None; self.deployment_identity = None
        elif action == 'capability-source-read':
            if __package__:
                from .capability_sources import read_reference
            else:
                from capability_sources import read_reference
            reference = read_reference(body.get('url'), item_kind=body.get('item_kind', 'skill_instructions'))
            if state.redact(reference) != reference:
                raise ValueError('La referencia contiene credenciales de sesión; no se guardó.')
            self.reference = reference
            self.plan = None
            state.receipt(action, 'success', 'Referencia pública leída sin cambiar la fuente de la organización, importar ni ejecutar contenido.')
        elif action == 'capability-search':
            self.library.search(body.get('query', ''), offset=body.get('offset', 0), limit=50)
            self.query, self.offset = body.get('query', ''), body.get('offset', 0)
        elif action == 'capability-audit':
            self.library.audit_page(body.get('offset', 0), limit=50)
            self.audit_offset = body.get('offset', 0)
        elif action == 'capability-assignments':
            self.library.manifest_page(body.get('offset', 0), limit=50)
            self.assignment_offset = body.get('offset', 0)
        elif action == 'capability-discard':
            self.plan = None
        elif action in ('capability-import', 'capability-save'):
            if action == 'capability-import':
                items = (self.catalog_items(body) if body.get('candidate_ids') else []) + self.reference_items(body)
            else:
                raw = body.get('item')
                if not isinstance(raw, dict):
                    raise ValueError('Skill manual inválida.')
                items = [raw]
                if raw.get('provenance', {}).get('type') != 'user_authored':
                    raise ValueError('La entrada manual debe declarar autoría local, no evidencia web no consultada.')
            result = self.library.import_items(items, body.get('expected_revision'), body.get('idempotency_key'))
            self.last_import = dict(result, item_ids=[item.get('id') for item in items])
            if all(item.get('id') for item in items):
                self.last_import['items'] = self.library.read_items([item['id'] for item in items])
            self.plan = None; self.offset = 0; self.query = ''; state.project['dirty'] = True
            state.receipt(action, 'success', 'Referencias guardadas en la biblioteca local; sin asignar, instalar ni activar.', **result)
        else:
            state.require_version(body)
            selection = self.selection(body.get('selection', {'mode': 'all'}))
            if action == 'capability-preview':
                items = self.catalog_items(body) if body.get('candidate_ids') else []
                items += self.reference_items(body)
                preview = self.library.preview_import_items(state.organization, items, body.get('item_ids') or [], selection,
                    action=body.get('assignment_action', 'assign'), expected_revision=body.get('expected_revision'))
                self.plan = {'id': uuid.uuid4().hex, 'preview': preview, 'catalog_identity': self.catalog_identity(), 'reference_hash': (self.reference or {}).get('source_hash')}
            elif action == 'capability-recommend':
                self.recommendations = self.library.recommend(state.organization, selection, offset=body.get('offset', 0), limit=50)
            elif action == 'capability-apply':
                if body.get('confirmed') is not True or not self.plan or body.get('plan_id') != self.plan['id'] or body.get('preview_hash') != self.plan['preview']['preview_hash']:
                    raise ValueError('Revisa y confirma el plan exacto de capacidades.')
                if self.plan['catalog_identity'] != self.catalog_identity():
                    raise ValueError('El catálogo cambió después de la revisión. Prepara otro plan.')
                if self.plan.get('reference_hash') != (self.reference or {}).get('source_hash'):
                    raise ValueError('La referencia cambió después del plan. Vuelve a revisar.')
                result = self.library.apply_import_preview(state.organization, self.plan['preview'], body.get('idempotency_key'))
                self.plan = None; state.project['dirty'] = True
                state.receipt(action, 'success', 'Asignaciones locales guardadas. Sin instalación, concesión de herramientas ni ejecución verificada.', **result)
            else:
                raise ValueError('Acción de capacidades desconocida.')
        return state.public()
