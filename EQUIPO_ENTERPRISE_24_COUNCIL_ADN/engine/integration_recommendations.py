"""Session-only, asynchronous UI adapter for reviewable capability suggestions.

No recommendation changes selected capabilities, library assignments, runtime
permissions or agent profiles. Paid consent/idempotency never enters exports.
"""
from __future__ import annotations
import copy
import re
import threading
import uuid

if __package__:
    from . import capability_recommendations as rec
    from .capability_library import select_agents
else:
    import capability_recommendations as rec
    from capability_library import select_agents

ACTIONS = frozenset({'capability-ai-plan', 'capability-ai-confirm', 'capability-ai-cancel', 'capability-ai-baseline'})
ROUTES = {'openai': 'openai', 'deepseek': 'deepseek', 'deepseek-official': 'deepseek', 'zai': 'zai', 'zai-official': 'zai'}
TERMINAL = {'completed', 'failed', 'cancelled', 'stale'}


class IntegrationRecommendations:
    def __init__(self, state):
        self.state = state
        self.jobs = {}
        self.contexts = {}
        self.keys = {}
        self.current_id = None

    def public(self):
        job = copy.deepcopy(self.jobs.get(self.current_id))
        if job:
            ctx = self.contexts[self.current_id]
            job['stale'] = not self._current(ctx)
            if job['stale']:
                job['result'] = None
                job['consent'] = None
        return {'job': job, 'advisory_only': True, 'automatic_installation': False,
                'max_agents': rec.MAX_AGENTS, 'max_candidates': rec.MAX_CANDIDATES,
                'mode_notice': 'Baseline local sin API; IA sólo tras revisar y confirmar el plan exacto.'}

    def _current(self, ctx):
        s = self.state
        try:
            return (not s.generation_stale and s.organization is not None and
                    rec._digest(s.organization) == ctx['target_sha256'] and
                    s.config_version == ctx['config_version'] and
                    s.capabilities_hub.library.project_id == ctx['project_id'] and
                    s.capabilities_hub.library.status()['revision'] == ctx['library_revision'] and
                    rec._digest(self._candidate_snapshot(ctx)) == ctx['candidate_sha256'])
        except (ValueError, KeyError, AttributeError):
            return False

    def _candidate_snapshot(self, ctx):
        hub = self.state.capabilities_hub
        items = hub.library.read_items(ctx['library_candidate_ids']) if ctx['library_candidate_ids'] else []
        if ctx['catalog_candidate_ids']:
            items.extend(hub.catalog_items({'candidate_ids': ctx['catalog_candidate_ids'],
                                            'catalog_identity': ctx['catalog_identity']}))
        return items

    def _catalog_shortlist(self, selected, remaining):
        """Read only the already-loaded catalog; never refresh/fetch implicitly."""
        s = self.state
        integrations = getattr(s, 'integrations', None)
        if not remaining or integrations is None or integrations.catalog is None:
            return []
        module = integrations._shop()
        per_agent = []
        for agent in s.organization['agents']:
            if agent['id'] not in selected:
                continue
            parts = [str(agent.get(k, '')) for k in ('role', 'title', 'mission')]
            for skill in agent.get('proposed_skills', []) + agent.get('skills', []):
                parts.append(skill.get('name', '') if isinstance(skill, dict) else str(skill))
            query = ' '.join(dict.fromkeys(re.findall(r'[\w-]{3,}', ' '.join(parts))))[:500]
            if query:
                per_agent.append([c['id'] for c in module.search_catalog(integrations.catalog, query, limit=8)['results']])
        # Round robin keeps a specialized agent from losing every slot to the CEO.
        chosen = []
        for i in range(8):
            for matches in per_agent:
                if i < len(matches) and matches[i] not in chosen:
                    chosen.append(matches[i])
                    if len(chosen) == remaining:
                        return chosen
        return chosen

    def _prepare_inputs(self, body):
        s = self.state
        s.require_version(body)
        if s.organization is None or s.generation_stale:
            raise ValueError('Genera una organización actual antes de sugerir capacidades.')
        selection = s.capabilities_hub.selection(body.get('selection', {'mode': 'all'}))
        ids = select_agents(s.organization, selection)
        if len(ids) > rec.MAX_AGENTS:
            raise ValueError('Selecciona un lote de hasta 32 agentes.')
        library = s.capabilities_hub.library
        explicit_shortlist = 'candidate_ids' in body or 'catalog_candidate_ids' in body
        candidate_ids = body.get('candidate_ids', [] if explicit_shortlist else None)
        catalog_ids = body.get('catalog_candidate_ids', [])
        if not isinstance(catalog_ids, list) or any(not isinstance(i, str) for i in catalog_ids) or len(set(catalog_ids)) != len(catalog_ids):
            raise ValueError('La selección de catálogo debe contener IDs únicos.')
        if explicit_shortlist and catalog_ids and body.get('catalog_identity') != s.capabilities_hub.catalog_identity():
            raise ValueError('El catálogo cambió; vuelve a seleccionar las capacidades de la recomendación.')
        if not explicit_shortlist:
            candidate_ids = [row['item_id'] for row in library.recommend(s.organization, selection, limit=32)['items']]
            catalog_ids = self._catalog_shortlist(ids, rec.MAX_CANDIDATES - len(candidate_ids))
        if (not isinstance(candidate_ids, list) or len(candidate_ids) + len(catalog_ids) > rec.MAX_CANDIDATES or
                not candidate_ids and not catalog_ids or
                any(not isinstance(i, str) for i in candidate_ids) or len(set(candidate_ids)) != len(candidate_ids)):
            raise ValueError('No hay shortlist válido. Consulta SkillShop o importa capacidades relacionadas.')
        catalog_identity = s.capabilities_hub.catalog_identity() if catalog_ids else None
        candidates = library.read_items(candidate_ids) if candidate_ids else []
        if catalog_ids:
            converted = s.capabilities_hub.catalog_items({'candidate_ids': catalog_ids, 'catalog_identity': catalog_identity})
            existing = set(candidate_ids)
            pairs = [(source_id, item) for source_id, item in zip(catalog_ids, converted) if item['id'] not in existing]
            catalog_ids = [source_id for source_id, _ in pairs]
            candidates.extend(item for _, item in pairs)
        kwargs = {'agent_ids': ids, 'max_output_tokens': body.get('max_output_tokens', 4096),
                  'batch_size': body.get('batch_size', 8), 'max_requests': body.get('max_requests', 4)}
        ctx = {'organization': copy.deepcopy(s.organization), 'candidates': candidates, 'candidate_ids': [c['id'] for c in candidates],
               'library_candidate_ids': candidate_ids, 'catalog_candidate_ids': catalog_ids, 'catalog_identity': catalog_identity,
               'target_sha256': rec._digest(s.organization), 'config_version': s.config_version,
               'project_id': library.project_id, 'library_revision': library.status()['revision'],
               'candidate_sha256': rec._digest(candidates), 'selection': copy.deepcopy(selection), 'kwargs': kwargs,
               'cancel': threading.Event()}
        return ctx

    def apply(self, action, body):
        if action not in ACTIONS:
            raise ValueError('Acción de recomendaciones no admitida.')
        with self.state.lock:
            if action in ('capability-ai-plan', 'capability-ai-baseline'):
                self.plan(body, baseline=action.endswith('baseline'))
            elif action == 'capability-ai-confirm':
                self.confirm(body)
            else:
                self.cancel(body)
        return self.state.public()

    def plan(self, body, baseline=False):
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError('Se requiere una clave idempotente para el plan.')
        request_hash = rec._digest(body)
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
            result = rec.baseline_recommendations(ctx['organization'], ctx['candidates'], ctx['kwargs']['agent_ids'])
        else:
            provider = body.get('provider', s.config['provider'])
            model = body.get('model', s.config['model'])
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
            consent = rec.prepare_recommendation_consent(ctx['organization'], ctx['candidates'], route, model, **ctx['kwargs'])
            if any(secret and secret in rec.p._dump(consent) for secret in s.credentials.values()):
                raise ValueError('El contexto contiene una credencial de sesión; no se transmitió.')
            ctx['consent'] = copy.deepcopy(consent)
        identifier = str(uuid.uuid4())
        self.jobs[identifier] = {'job_id': identifier, 'status': 'completed' if baseline else 'awaiting_consent',
                                 'mode': 'deterministic' if baseline else 'ai', 'selection': ctx['selection'],
                                 'catalog_candidate_ids': ctx['catalog_candidate_ids'], 'catalog_identity': ctx['catalog_identity'],
                                 'consent': consent, 'result': result, 'error': None,
                                 'confirmation_consumed': False, 'requests': 0}
        self.contexts[identifier] = ctx
        self.keys[key] = (identifier, request_hash)
        self.current_id = identifier
        s.receipt('capability-ai-baseline' if baseline else 'capability-ai-plan', 'success',
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
            result = rec.recommend_with_llm(ctx['organization'], ctx['candidates'], ctx['route'], ctx['model'], key,
                ctx['consent'], cancel_check=cancelled, current_organization=organization, **ctx['kwargs'])
            with self.state.lock:
                if cancelled():
                    self.jobs[identifier].update(status='cancelled' if ctx['cancel'].is_set() else 'stale', result=None)
                    return
                if any(secret and secret in rec.p._dump(result) for secret in self.state.credentials.values()):
                    raise ValueError('La respuesta contiene una credencial.')
                self.jobs[identifier].update(status='completed', result=result, requests=result['audit']['requests'])
                self.state.receipt('capability-ai-confirm', 'success', 'Propuesta completa recibida; revisa qué capacidades asignar. No se instaló ni activó ninguna.')
        except Exception as exc:
            with self.state.lock:
                job = self.jobs[identifier]
                if job['status'] != 'cancelled':
                    job.update(status='stale' if not self._current(ctx) else 'failed', result=None,
                               error='La propuesta no se completó. No hubo reintento automático ni cambios de capacidades.')
                job['requests'] = getattr(exc, 'audit', {}).get('requests', 0)
