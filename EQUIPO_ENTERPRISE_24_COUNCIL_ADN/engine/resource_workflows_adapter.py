"""Session-only workflow planning and explicit atomic per-role activation.

Planning is inert. Reviewed application changes local instruction assignments
only, never runtime permissions or external resources. Paid consent stays local.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
else:
    from limits import MAX_AGENTS

import copy
import threading
import uuid
import sqlite3

if __package__:
    from . import resource_workflows as rec
    from .capability_library import select_agents
else:
    import resource_workflows as rec
    from capability_library import select_agents

ACTIONS = frozenset({'resource-workflow-plan', 'resource-workflow-confirm', 'resource-workflow-cancel', 'resource-workflow-baseline', 'resource-workflow-example', 'resource-workflow-preview', 'resource-workflow-apply'})
ROUTES = {'openai': 'openai', 'deepseek': 'deepseek', 'deepseek-official': 'deepseek', 'zai': 'zai', 'zai-official': 'zai'}
TERMINAL = {'completed', 'failed', 'cancelled', 'stale'}


class ResourceWorkflows:
    def __init__(self, state):
        self.state = state
        self.jobs = {}
        self.contexts = {}
        self.keys = {}
        self.current_id = None
        self.preview = None

    def public(self):
        job = copy.deepcopy(self.jobs.get(self.current_id))
        if job:
            ctx = self.contexts[self.current_id]
            job['stale'] = not self._current(ctx)
            if job['stale']:
                job['result'] = None
                job['consent'] = None
        return {'job': job, 'advisory_only': True, 'automatic_installation': False,
                'max_agents': MAX_AGENTS, 'preview': copy.deepcopy(self.preview),
                'mode_notice': 'Baseline local sin API; IA sólo tras revisar y confirmar el plan exacto.'}

    def _current(self, ctx):
        s = self.state
        try:
            return (not s.generation_stale and s.organization is not None and
                    rec.rec._digest(s.organization) == ctx['target_sha256'] and
                    s.config_version == ctx['config_version'] and
                    s.capabilities_hub.library.project_id == ctx['project_id'] and
                    s.capabilities_hub.library.status()['revision'] == ctx['library_revision'] and
                    rec.rec._digest(s.capabilities_hub.reference) == ctx['reference_sha256'])
        except (ValueError, KeyError, AttributeError):
            return False

    def _prepare_inputs(self, body):
        s = self.state
        s.require_version(body)
        if s.organization is None or s.generation_stale:
            raise ValueError('Genera una organización actual antes de preparar workflows.')
        selection = s.capabilities_hub.selection(body.get('selection', {'mode': 'all'}))
        ids = select_agents(s.organization, selection)
        if len(ids) > 32:
            raise ValueError('Selecciona hasta %d agentes actuales.' % MAX_AGENTS)
        reference = copy.deepcopy(s.capabilities_hub.reference)
        if not reference or body.get('reference_hash') != reference.get('source_hash'):
            raise ValueError('Consulta y revisa una referencia o el ejemplo antes de preparar workflows.')
        kwargs = {'agent_ids': ids, 'max_output_tokens': body.get('max_output_tokens', 4096),
                  'batch_size': body.get('batch_size', 4), 'max_requests': body.get('max_requests', 8)}
        return {'organization': copy.deepcopy(s.organization), 'reference': reference,
                'target_sha256': rec.rec._digest(s.organization), 'config_version': s.config_version,
                'project_id': s.capabilities_hub.library.project_id,
                'library_revision': s.capabilities_hub.library.status()['revision'],
                'reference_sha256': rec.rec._digest(reference), 'selection': selection,
                'kwargs': kwargs, 'cancel': threading.Event()}

    def apply(self, action, body):
        if action not in ACTIONS:
            raise ValueError('Acción de workflow no admitida.')
        with self.state.lock:
            if self.state.generation._active():
                raise ValueError('Termina o cancela la generación pendiente antes de preparar workflows.')
            if self.state.redact(body) != body:
                raise ValueError('No incluir secretos en propuestas de workflow.')
            if action == 'resource-workflow-example':
                self.state.capabilities_hub.reference = rec.datainventor_research_reference()
                self.preview = None
                self.state.receipt(action, 'success', 'Snapshot de investigación revisada; no se consultó la URL en vivo.')
            elif action in ('resource-workflow-plan', 'resource-workflow-baseline'):
                self.plan(body, baseline=action.endswith('baseline'))
                self.preview = None
            elif action == 'resource-workflow-confirm':
                self.confirm(body)
            elif action == 'resource-workflow-preview':
                self.prepare_assignment(body)
            elif action == 'resource-workflow-apply':
                self.apply_assignment(body)
            else:
                self.cancel(body)
        return self.state.public()

    def plan(self, body, baseline=False):
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 140:
            raise ValueError('Se requiere una clave idempotente para el plan.')
        request_hash = rec.rec._digest(body)
        if key in self.keys:
            identifier, prior_hash = self.keys[key]
            if prior_hash != request_hash:
                raise ValueError('La clave idempotente ya identifica otro plan.')
            self.current_id = identifier
            return
        if any(job['status'] == 'running' for job in self.jobs.values()):
            raise ValueError('Espera o cancela la recomendación en curso.')
        if len(self.jobs) >= 1000:
            raise ValueError('La sesión alcanzó su límite de planes; abre otra sesión.')
        ctx = self._prepare_inputs(body)
        s = self.state
        consent = None
        result = None
        if baseline:
            result = rec.baseline_resource_workflows(ctx['organization'], ctx['reference'], ctx['kwargs']['agent_ids'])
        else:
            provider = body.get('provider', s.config['provider'])
            model = body.get('model', s.config['model'])
            if provider != s.config['provider'] or model != s.config['model']:
                raise ValueError('Usa el mismo proveedor y modelo API seleccionado en la organización.')
            if provider not in ROUTES or not s.credentials.get(provider):
                raise ValueError('Prepara la clave del proveedor seleccionado antes de recomendar con IA.')
            s.validate_api_model_choice({'provider': provider, 'model': model})
            route = ROUTES[provider]
            # A runtime alias/display name does not prove an API identifier exists.
            models = [m for m in s.models if ROUTES.get(m.get('provider')) == route and m.get('model', m.get('id')) == model
                      and m.get('catalog_scope') not in ('dsh_runtime', 'dsh_runtime_reference')
                      and (m.get('source') in ('live_api', 'official_docs_snapshot') or m.get('status') == 'VERIFIED_INFERENCE')]
            docs = [m for m in rec.p.DOC_CATALOG.get(route, []) if m['id'] == model]
            if not models and not docs:
                raise ValueError('Elige un ID de API del catálogo de Modelos; un alias local DSH no sirve para estas llamadas.')
            meta = dict((models or docs)[0], id=model, provider=route)
            ctx['kwargs']['model_metadata'] = meta
            ctx.update(provider=provider, route=route, model=model)
            consent = rec.prepare_workflow_consent(ctx['organization'], ctx['reference'], route, model, **ctx['kwargs'])
            if any(secret and secret in rec.p._dump(consent) for secret in s.credentials.values()):
                raise ValueError('El contexto contiene una credencial de sesión; no se transmitió.')
            ctx['consent'] = copy.deepcopy(consent)
        identifier = str(uuid.uuid4())
        self.jobs[identifier] = {'job_id': identifier, 'status': 'completed' if baseline else 'awaiting_consent',
                                 'mode': 'deterministic' if baseline else 'ai', 'selection': ctx['selection'],
                                 'source_hash': ctx['reference']['source_hash'],
                                 'consent': consent, 'result': result, 'error': None,
                                 'confirmation_consumed': False, 'requests': 0}
        self.contexts[identifier] = ctx
        self.keys[key] = (identifier, request_hash)
        self.current_id = identifier
        s.receipt('resource-workflow-baseline' if baseline else 'resource-workflow-plan', 'success',
                  'Propuesta local preparada.' if baseline else 'Plan revisable preparado sin llamadas de pago.')

    def confirm(self, body):
        identifier = body.get('job_id')
        if identifier not in self.jobs:
            raise ValueError('No existe este plan de recomendaciones.')
        job, ctx = self.jobs[identifier], self.contexts[identifier]
        if job['confirmation_consumed']:
            self.current_id = identifier
            return  # Includes failed/cancelled runs: never re-spend a consent.
        if job['status'] != 'awaiting_consent' or not self._current(ctx):
            raise ValueError('El plan está obsoleto o no espera autorización; prepara uno nuevo.')
        pending = ctx['consent']
        if (any(body.get(k) is not True for k in ('confirmed', 'data_reviewed', 'budget_acknowledged')) or
                body.get('approval_id') != pending['approval_id'] or body.get('payload_sha256') != pending['payload_sha256']):
            raise ValueError('Confirma el contenido exacto, modelo y presupuesto del plan revisado.')
        key = self.state.credentials.get(ctx['provider'])
        if not key:
            raise ValueError('Falta la clave del proveedor elegido.')
        ctx['consent'].update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        job.update(status='running', confirmation_consumed=True, consent=None)
        threading.Thread(target=self._run, args=(identifier, key), daemon=True,
                         name='orgdna-capability-' + identifier[:8]).start()

    def cancel(self, body):
        identifier = body.get('job_id', self.current_id)
        if identifier not in self.jobs:
            raise ValueError('No existe este plan de recomendaciones.')
        job, ctx = self.jobs[identifier], self.contexts[identifier]
        if job['status'] in TERMINAL:
            return
        ctx['cancel'].set()
        job.update(status='cancelled', result=None, consent=None,
                   error='Cancelado. Una llamada ya enviada puede tener coste; no se enviarán los siguientes lotes.')

    def _run(self, identifier, key):
        ctx = self.contexts[identifier]
        def cancelled():
            with self.state.lock:
                return ctx['cancel'].is_set() or not self._current(ctx)
        def organization():
            with self.state.lock:
                return copy.deepcopy(self.state.organization)
        try:
            result = rec.workflows_with_llm(ctx['organization'], ctx['reference'], ctx['route'], ctx['model'], key,
                ctx['consent'], cancel_check=cancelled, current_organization=organization, **ctx['kwargs'])
            with self.state.lock:
                if cancelled():
                    self.jobs[identifier].update(status='cancelled' if ctx['cancel'].is_set() else 'stale', result=None)
                    return
                if any(secret and secret in rec.p._dump(result) for secret in self.state.credentials.values()):
                    raise ValueError('La respuesta contiene una credencial.')
                self.jobs[identifier].update(status='completed', result=result, requests=result['audit']['requests'])
                self.state.receipt('resource-workflow-confirm', 'success', 'Propuesta completa recibida; revisa qué capacidades asignar. No se instaló ni activó ninguna.')
        except Exception as exc:
            with self.state.lock:
                job = self.jobs[identifier]
                if job['status'] != 'cancelled':
                    job.update(status='stale' if not self._current(ctx) else 'failed', result=None,
                               error='La propuesta no se completó. No hubo reintento automático ni cambios de capacidades.')
                job['requests'] = getattr(exc, 'audit', {}).get('requests', 0)

    def prepare_assignment(self, body):
        """Preview all per-agent imports/assignments in a private memory DB."""
        s = self.state
        s.require_version(body)
        identifier = body.get('job_id', self.current_id)
        if identifier not in self.jobs:
            raise ValueError('No existe esta propuesta de workflow.')
        job, ctx = self.jobs[identifier], self.contexts[identifier]
        if job['status'] != 'completed' or not self._current(ctx):
            raise ValueError('La propuesta cambió o no está completa.')
        action = body.get('action', 'assign')
        if action not in ('assign', 'activate'):
            raise ValueError('Elige asignar o activar instrucciones tras revisión.')
        library = s.capabilities_hub.library
        revision = library.status()['revision']
        if body.get('expected_revision') != revision:
            raise ValueError('La biblioteca cambió; vuelve a revisar.')
        result = job['result']
        chosen = body.get('workflow_agent_ids', list(result['agent_item_ids']))
        if (not isinstance(chosen, list) or not chosen or any(not isinstance(a, str) for a in chosen) or
                len(set(chosen)) != len(chosen) or not set(chosen) <= set(result['agent_item_ids'])):
            raise ValueError('Selecciona IDs de agentes de esta propuesta.')
        mapping = {a: ids for a, ids in result['agent_item_ids'].items() if a in chosen}
        selected_items = {iid for ids in mapping.values() for iid in ids}
        items = copy.deepcopy([item for item in result['item_proposals'] if item['id'] in selected_items])
        memory = sqlite3.connect(':memory:')
        memory.row_factory = sqlite3.Row
        try:
            with library._connection() as db:
                db.backup(memory)
            view = library._transaction_view(memory)
            view.import_items(items, revision, 'workflow-preview-import')
            assignments = []
            for agent_id, ids in mapping.items():
                preview = view.preview(s.organization, ids, {'mode': 'selected', 'agent_ids': [agent_id]}, action)
                view.apply(s.organization, preview, 'workflow-preview-' + agent_id)
                assignments.append(preview)
            value = {'job_id': identifier, 'project_id': library.project_id, 'revision': revision,
                     'target_sha256': ctx['target_sha256'], 'reference_sha256': ctx['reference_sha256'],
                     'items': items, 'assignments': assignments, 'action': action,
                     'agent_item_ids': copy.deepcopy(mapping),
                     'changed_count': sum(p['changed_count'] for p in assignments),
                     'installed': False, 'runtime_verified': False, 'permission_changes': []}
            self.preview = dict(value, preview_hash=rec.rec._digest(value))
        finally:
            memory.close()

    def apply_assignment(self, body):
        s = self.state
        s.require_version(body)
        preview = self.preview
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 140:
            raise ValueError('Se necesita una clave idempotente.')
        if not preview or body.get('preview_hash') != preview['preview_hash'] or body.get('confirmed') is not True:
            raise ValueError('Confirma el plan exacto de instrucciones por agente.')
        identifier = preview['job_id']
        library = s.capabilities_hub.library
        request = {'workflow_preview': preview}
        # Replay can return a prior committed operation, never repeat its effects.
        with library._connection(True) as db:
            cached = library._cached(db, key, request)
            if cached is not None:
                return
            if not self._current(self.contexts[identifier]):
                raise ValueError('Cambió la fuente, organización o biblioteca; prepara otro plan.')
            library._cas(db, preview['revision'])
            unsigned = dict(preview); unsigned.pop('preview_hash')
            if rec.rec._digest(unsigned) != preview['preview_hash']:
                raise ValueError('La previsualización cambió.')
            view = library._transaction_view(db)
            view.import_items(preview['items'], preview['revision'], 'workflow-import:' + key)
            for index, assignment in enumerate(preview['assignments']):
                view.apply(s.organization, assignment, 'workflow-assign:' + key + ':' + str(index))
            result = {'changed_count': preview['changed_count'], 'installed': False, 'runtime_verified': False}
            if __package__:
                from .capability_library import _hash, _dump
            else:
                from capability_library import _hash, _dump
            db.execute('INSERT INTO requests VALUES (?,?,?,?)', (library.project_id, key, _hash(request), _dump(result)))
            library._check_quota(db)
        s.receipt('resource-workflow-apply', 'success',
                  'Instrucciones por agente guardadas' + (' y activadas en contexto.' if preview['action'] == 'activate' else '; activación pendiente.') + ' Sin instalación ni ejecución del recurso.')
