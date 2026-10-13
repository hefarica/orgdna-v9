"""Consent-bound asynchronous organization generation.

Only an explicit confirmation starts paid work. Jobs stage results privately and
commit the organization and its verified exports together. No retry or fallback
is performed after a provider request, including on cancellation or timeout.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
    from .org_design import MAX_REQUESTS
else:
    from limits import MAX_AGENTS
    from org_design import MAX_REQUESTS


import copy
import hashlib
import json
import re
import secrets
import threading
import time
import uuid

TERMINAL = frozenset({'completed', 'failed', 'cancelled'})
ACTIONS = frozenset({'generation-plan', 'generation-confirm', 'generation-cancel'})
USAGE_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens')
RECEIPT_STATUSES = frozenset({'billing_outcome_unknown', 'response_received_not_yet_validated', 'validated'})


def safe_request_receipts(values, provider, model, request_hashes=None):
    """A typed boundary, not redaction of remote text. No body/URL/key survives."""
    if __package__:
        from .providers import HTTP_ERROR_CODES
        from .org_design import _FAILURES
    else:
        from providers import HTTP_ERROR_CODES
        from org_design import _FAILURES
    def integer(value, maximum, minimum=0):
        return value if type(value) is int and minimum <= value <= maximum else None
    def sha(value):
        return value if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) else None
    rows = {}
    for raw in values[:16] if isinstance(values, list) else []:
        if not isinstance(raw, dict):
            continue
        index = integer(raw.get('index'), 16, 1)
        if index is None:
            continue
        usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
        payload_hash = sha(raw.get('payload_sha256'))
        if isinstance(request_hashes, list) and index <= len(request_hashes):
            payload_hash = sha(request_hashes[index - 1])
        code = raw.get('error_code')
        rows[index] = {'index': index, 'provider': provider, 'model': model,
            'payload_sha256': payload_hash,
            'max_output_tokens': integer(raw.get('max_output_tokens'), 131072, 1),
            'status': raw.get('status') if isinstance(raw.get('status'), str) and raw['status'] in RECEIPT_STATUSES else 'billing_outcome_unknown',
            'usage': {key: integer(usage.get(key), 99_999_999) for key in USAGE_FIELDS},
            'latency_ms': integer(raw.get('latency_ms'), 86_400_000),
            'http_status': integer(raw.get('http_status'), 599, 100),
            'error_code': code if isinstance(code, str) and (code in HTTP_ERROR_CODES or code in _FAILURES) else None,
            'response_id_sha256': sha(raw.get('response_id_sha256'))}
    return [rows[index] for index in sorted(rows)]


def usage_summary(receipts, sent_requests=None, potentially_billed=False):
    observed = max(len(receipts), sent_requests if type(sent_requests) is int and 0 <= sent_requests <= 16 else
                   (1 if potentially_billed else 0))
    known = sum(all(row['usage'][key] is not None for key in USAGE_FIELDS) for row in receipts)
    return {**{key: sum(row['usage'][key] for row in receipts)
               if receipts and len(receipts) == observed and all(row['usage'][key] is not None for row in receipts) else None
               for key in USAGE_FIELDS}, 'known_requests': known, 'unknown_requests': max(0, observed - known)}


# Exact static messages only: never serialize arbitrary adapter/transport text.
SAFE_FAILURE_MESSAGES = frozenset({
    'No hay evidencia HTML utilizable para analizar.',
    'El modelo no propuso una corrección funcional para el agente afectado; no basta cambiar advertencias.',
    'La evidencia de fuente no corresponde al diseño evaluado; vuelve a generar y evaluar antes de mejorarlo.',
    'La mejora cambió las identidades de la organización.',
    'Snapshot sin evidencia utilizable.',
    'Etapa de lectura del repositorio: no hay contenido útil de archivos para fundamentar un ADN especializado. No se llamó al modelo. Revisa la referencia o prepara un inventario con archivos legibles.',
    'Generación cancelada. No se ha reemplazado el diseño anterior.',
    'La configuración o el diseño cambió. El resultado no se aplicó; prepara una nueva autorización.',
    'El contenido revisable contiene una credencial de sesión. No se transmitió.',
    'La respuesta incluye una credencial de sesión; se descartó sin guardar.',
    'El proveedor no devolvió exactamente N perfiles completos. No se exporta un lote parcial.',
    'Una ruta de modelo difiere de la elección autorizada; el ADN no se aplicó.',
    'El paquete no superó la validación final; se conserva el ADN anterior.',
    'Una credencial aparece en el ADN final. No se guardó ni exportó.',
    'Cancelado. Una solicitud ya transmitida puede tener coste; no se aplicarán resultados ni se enviarán los lotes siguientes.',
    'Rama o SHA no válido.',
    'GitHub no devolvió un SHA de commit válido.',
    'GitHub no devolvió un SHA de árbol válido.',
    'Árbol de repositorio inválido.',
    'Repositorio inválido.',
    'Se necesita la URL raíz del repositorio; rama o SHA se indican por separado.',
    'No se pudo resolver el endpoint.',
    'DNS resolvió una dirección privada o no pública; conexión bloqueada.',
    'Fallo de red/TLS. No hubo reintento automático; resultado de la solicitud desconocido.',
    'El transporte falló; no se reintentó ni se mostró información sensible.',
    'Respuesta HTTP inválida o demasiado grande.',
    'Respuesta HTTP supera el límite de bytes.',
    'Respuesta JSON inválida.',
    'No hay contenido revisable para analizar.',
    'Falta SHA fijado para transmitir el repositorio.',
    'El resumen supera 1.2 MB; reduce los archivos o documentos antes de continuar.',
    'El contenido no coincide con su SHA de Git; análisis detenido.',
    'Tamaño de archivo inesperado; análisis detenido.',
    'Identificador de modelo inválido; usa uno descubierto o confirmado manualmente.',
})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def timestamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class GenerationPipeline:
    def __init__(self, state):
        self.state = state
        self.jobs = {}
        self.keys = {}
        self.current_id = None
        self._contexts = {}
        self._project_job_ids = []

    def _capture_receipts(self, job, values=None, detail=None):
        rows = {row['index']: row for row in job.get('request_receipts', [])}
        for row in safe_request_receipts(values, job['provider'], job['model'], job.get('request_hashes')):
            rows[row['index']] = row
        receipts = [rows[index] for index in sorted(rows)]
        if receipts and isinstance(detail, dict):
            raw = dict(receipts[-1])
            raw['http_status'] = detail.get('http_status', raw.get('http_status'))
            raw['error_code'] = detail.get('provider_error_code') or detail.get('code') or raw.get('error_code')
            receipts[-1] = safe_request_receipts([raw], job['provider'], job['model'], job.get('request_hashes'))[0]
        job['request_receipts'] = receipts
        job['usage_summary'] = usage_summary(receipts, job.get('sent_requests'), job.get('potentially_billed', False))

    def saved(self):
        """Historical safe receipts only; pending consent is never restorable."""
        history = []
        for job_id in self._project_job_ids[-100:]:
            job = self.jobs.get(job_id)
            if job:
                history.append(self._saved_job(job))
        return {'version': 1, 'jobs': history, 'current_job_id': self.current_id}

    @staticmethod
    def _saved_job(source):
        job = {}
        patterns = {'job_id': r'[A-Za-z0-9_-]{8,128}', 'organization_id': r'[A-Za-z0-9_-]{1,128}',
            'provider': r'[a-z][a-z0-9-]{0,63}', 'model': r'[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,159}',
            'organization_state_sha256': r'[0-9a-f]{64}', 'payload_sha256': r'[0-9a-f]{64}'}
        for key, pattern in patterns.items():
            value = source.get(key)
            if isinstance(value, str) and re.fullmatch(pattern, value):
                job[key] = value
        stages = {'inventory', 'preparing_consent', 'review', 'api_design', 'validating_profiles', 'building_exports', 'ready', 'failed', 'cancelled'}
        for key, allowed in (('status', TERMINAL), ('stage', stages), ('failed_stage', stages), ('response_mode', {'json_object', 'text'})):
            value = source.get(key)
            if isinstance(value, str) and value in allowed:
                job[key] = value
        for key in ('created_at', 'updated_at', 'finished_at'):
            value = source.get(key)
            if isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
                job[key] = value
        limits = {'agent_count': MAX_AGENTS, 'progress': 100, 'max_requests': MAX_REQUESTS, 'sent_requests': MAX_REQUESTS,
            'completed_requests': 16, 'completed_profiles': MAX_AGENTS, 'max_output_tokens': 131072,
            'total_max_output_tokens': 16 * 131072, 'max_total_output_tokens': 16 * 131072,
            'profiles_per_request': MAX_AGENTS, 'read_files': 10000000, 'known_safe_files': 10000000}
        for key, maximum in limits.items():
            value = source.get(key)
            if key in source and (value is None or type(value) is int and 0 <= value <= maximum):
                job[key] = value
        for key in ('potentially_billed', 'confirmation_consumed', 'interrupted_snapshot'):
            if type(source.get(key)) is bool:
                job[key] = source[key]
        # A saved running attempt cannot resume or restore spending permission.
        if job.get('status') not in TERMINAL:
            job.update(status='cancelled', stage='cancelled', interrupted_snapshot=True)
        if source.get('receipts_pending') is True:
            job['interrupted_snapshot'] = True
        job['receipts_pending'] = False
        job['artifacts'] = None
        job['restored_from_project'] = True
        job['request_receipts'] = safe_request_receipts(source.get('request_receipts'), job.get('provider'), job.get('model'))
        job['usage_summary'] = usage_summary(job['request_receipts'], job.get('sent_requests'), job.get('potentially_billed', False))
        # Error details are already local allowlisted diagnostics; preserve only
        # protocol labels/counters, never provider or adapter prose from a file.
        raw_error = source.get('error')
        job['error'] = None
        if isinstance(raw_error, dict):
            if __package__:
                from .org_design import _diagnostic
            else:
                from org_design import _diagnostic
            job['error'] = _diagnostic(raw_error.get('code'), **{key: value for key, value in raw_error.items() if key != 'code'})
            local_codes = {'generation_stage_failed', 'generation_state_error', 'repository_http_error',
                'repository_read_failed', 'generation_validation_failed', 'improvement_evidence_invalid'}
            if isinstance(raw_error.get('code'), str) and raw_error['code'] in local_codes:
                job['error']['code'] = raw_error['code']
                if isinstance(raw_error.get('message'), str) and raw_error['message'] in SAFE_FAILURE_MESSAGES:
                    job['error']['message'] = raw_error['message']
            for key, allowed in (('stage', stages), ('request_status', RECEIPT_STATUSES),
                    ('source_kind', {'github_repository', 'website'}),
                    ('source_stage', {'repository_metadata', 'commit_resolution', 'commit_metadata', 'tree_recursive', 'tree_subtree', 'tree_inventory'}),
                    ('adapter_code', {'response_too_large', 'http_error', 'repository_read_error', 'inventory_unavailable'})):
                value = raw_error.get(key)
                if isinstance(value, str) and value in allowed:
                    job['error'][key] = value
            for key in ('sent_requests', 'completed_requests', 'max_requests', 'completed_profiles'):
                value = raw_error.get(key)
                if value is None or type(value) is int and 0 <= value <= limits[key]:
                    job['error'][key] = value
            job['error']['retry_requires_new_consent'] = True
        return job

    def load_saved(self, value):
        if value is None:
            value = {'version': 1, 'jobs': []}
        if (not isinstance(value, dict) or value.get('version') != 1 or
                not isinstance(value.get('jobs'), list) or len(value['jobs']) > 100):
            raise self._error('Historial de generación guardado no válido.')
        loaded = []
        for raw in value['jobs']:
            if (not isinstance(raw, dict) or not isinstance(raw.get('job_id'), str) or
                    not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', raw['job_id']) or
                    not isinstance(raw.get('provider'), str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', raw['provider']) or
                    not isinstance(raw.get('model'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,159}', raw['model'])):
                raise self._error('Historial de generación guardado no válido.')
            loaded.append(self._saved_job(raw))
        self._project_job_ids = [job['job_id'] for job in loaded]
        for job in loaded:
            # Do not downgrade a current session's more complete late receipt.
            if job['job_id'] not in self.jobs:
                self.jobs[job['job_id']] = job
        selected = value.get('current_job_id')
        self.current_id = selected if selected in self._project_job_ids else (self._project_job_ids[-1] if loaded else None)

    def public(self):
        result = copy.deepcopy(self.jobs.get(self.current_id))
        if result and result['status'] == 'completed':
            current = not self.state.generation_stale and result.get('organization_state_sha256') == digest(self.state.organization)
            result['artifacts_current'] = current
            if not current:
                result['artifacts'] = None
        return result

    def _api(self):
        # Injectable adapters make the complete flow testable without paid calls.
        provider = self.state._provider()
        if hasattr(provider, 'prepare_design_consent') and hasattr(provider, 'design_with_llm'):
            return provider
        if __package__:
            from . import org_design
        else:
            import org_design
        return org_design

    def _error(self, message):
        if __package__:
            from .bridge import BridgeError
        else:
            from bridge import BridgeError
        return BridgeError(message)

    def _active(self):
        return next((j for j in self.jobs.values() if j['status'] not in TERMINAL), None)

    def apply(self, action, body):
        if action == 'generation-plan':
            self.plan(body)
        elif action == 'generation-confirm':
            self.confirm(body)
        else:
            self.cancel(body)
        return self.state.public()

    def _still_current(self, ctx):
        state = self.state
        return (state.config_version == ctx['config_version'] and
                digest(state.config) == ctx['config_sha256'] and
                digest(state.organization) == ctx['previous_organization_sha256'] and
                state.records_version == ctx['records_version'] and
                state.project.get('id') == ctx['previous_project_id'])

    def _check_current(self, ctx):
        if ctx['cancel'].is_set():
            raise self._error('Generación cancelada. No se ha reemplazado el diseño anterior.')
        if not self._still_current(ctx):
            raise self._error('La configuración o el diseño cambió. El resultado no se aplicó; prepara una nueva autorización.')

    def plan(self, body):
        if __package__:
            from .bridge import normalize_config, PROVIDER_ROUTES
        else:
            from bridge import normalize_config, PROVIDER_ROUTES
        state = self.state
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', key):
            raise self._error('Incluye un idempotency_key único para esta generación (8–128 caracteres).')
        config = normalize_config(body.get('config', {}), state.config)
        # The guided flow derives Council membership directly from N.
        config['council_concurrency'] = config['agent_count']
        if not config['repo_url'] or not config['model']:
            raise self._error('Indica el repositorio y el identificador exacto del modelo elegido.')
        if state.redact(config) != config:
            raise self._error('Una credencial aparece en la configuración. Retírala antes de transmitir datos.')
        maximum = body.get('max_output_tokens', 16384)
        if type(maximum) is not int or not 4096 <= maximum <= 131072:
            raise self._error('max_output_tokens debe ser un entero entre 4096 y 131072 por solicitud.')
        profiles_per_request = body.get('profiles_per_request')
        if profiles_per_request is not None and (type(profiles_per_request) is not int or not 1 <= profiles_per_request <= MAX_AGENTS):
            raise self._error('profiles_per_request debe ser un entero entre 1 y %d, o dejarse automático.' % MAX_AGENTS)
        response_mode = body.get('response_mode', 'json_object')
        if response_mode not in ('json_object', 'text'):
            raise self._error('response_mode debe ser json_object o text.')
        new_project = body.get('new_project', False)
        if type(new_project) is not bool:
            raise self._error('new_project debe ser verdadero o falso.')
        improvement_ids = body.get('improvement_run_ids', [])
        if not isinstance(improvement_ids, list) or len(improvement_ids) > 16 or any(not isinstance(x, str) for x in improvement_ids):
            raise self._error('Selecciona como máximo 16 identificadores de evaluación.')
        revision_context = None
        if improvement_ids:
            if new_project or not state.organization or config['agent_count'] != len(state.organization.get('agents', [])):
                raise self._error('Mejorar requiere el diseño actual y conserva N e identidades.')
            if config != state.config:
                raise self._error('Mejorar conserva la configuración, fuente, proveedor y modelo seleccionado; evalúa de nuevo tras cambiar el diseño.')
            if __package__:
                from .improvement import build_feedback_package
            else:
                from improvement import build_feedback_package
            try:
                runs = [state.evaluations.verified_result(run_id, state.organization) for run_id in improvement_ids]
                feedback = build_feedback_package(runs, state.organization)
            except ValueError as exc:
                raise self._error(str(exc)) from None
            revision_context = {'organization': copy.deepcopy(state.organization), 'feedback': feedback}
        parameters = {'config': config, 'new_project': new_project, 'max_output_tokens': maximum,
                      'profiles_per_request': profiles_per_request, 'response_mode': response_mode,
                      'improvement_run_ids': improvement_ids,
                      'feedback_sha256': revision_context['feedback']['feedback_sha256'] if revision_context else None}
        request_hash = digest(parameters)
        if key in self.keys:
            prior = self.jobs[self.keys[key]]
            if prior['request_sha256'] != request_hash:
                raise self._error('La clave de idempotencia ya corresponde a otra configuración. No se ha repetido ninguna solicitud.')
            active = self._active()
            if active is None or active['job_id'] == prior['job_id']:
                self.current_id = prior['job_id']
            return
        if self._active():
            raise self._error('Ya hay una generación pendiente. Termínala o cancélala antes de preparar otra.')
        if state.has_manual_edits and body.get('confirmed_discard_edits') is not True:
            raise self._error('Hay ediciones manuales. Guarda una versión o confirma su reemplazo para generar un ADN nuevo.')
        if not state.credentials.get(config['provider']):
            raise self._error('Prepara primero la clave del proveedor elegido en el panel local.')
        # Keep consumed idempotency tokens for this whole session, including failures.
        # A repeated old token must never become a fresh paid operation.
        if len(self.jobs) >= 2000:
            raise self._error('La sesión alcanzó el límite de trabajos. Guarda el proyecto y abre una nueva sesión.')
        verification = state.validate_api_model_choice(config, manual_confirmed=body.get('manual_model_confirmed') is True)
        previous_repository = (state.config.get('source_kind', 'github_repository'), state.config['repo_url'], state.config['repo_ref'])
        state.remember_current_design()
        if config != state.config:
            state.config = config
            state.config_version += 1
            state.generation_stale = True
            state.project['dirty'] = True
        if previous_repository != (config.get('source_kind', 'github_repository'), config['repo_url'], config['repo_ref']):
            state.repo_inventory = None
            state.analysis = None
        state.pending_consent = None
        old_org = state.organization or {}
        old_id = old_org.get('organization_id')
        organization_id = str(uuid.uuid4()) if new_project or not old_id else old_id
        generation_config = dict(config, organization_id=organization_id, generation_mode='automatic',
                                 identity_mode='new' if new_project or not old_id else 'revision',
                                 dna_revision=1 if new_project or not old_id else old_org.get('dna_revision', 1) + 1)
        job_id = str(uuid.uuid4())
        job = {'job_id': job_id, 'idempotency_key': key, 'request_sha256': request_hash,
               'status': 'planned', 'stage': 'inventory', 'progress': 5,
               'created_at': timestamp(), 'updated_at': timestamp(),
               'config_version': state.config_version, 'organization_id': organization_id,
               'new_project': new_project, 'provider': config['provider'], 'model': config['model'],
               'agent_count': config['agent_count'], 'completed_requests': 0, 'sent_requests': 0,
               'completed_profiles': 0, 'max_output_tokens': maximum,
               'profiles_per_request': profiles_per_request, 'response_mode': response_mode,
               'potentially_billed': False, 'error': None, 'artifacts': None,
               'receipts_pending': False,
               'model_verification': verification, 'request_receipts': [], 'usage_summary': usage_summary([])}
        model_metadata = state.api_model_metadata(config)
        if model_metadata is not None:
            model_metadata['provider'] = PROVIDER_ROUTES[config['provider']]
        ctx = {'cancel': threading.Event(), 'config': copy.deepcopy(config),
               'credential_stamp': state._api_account_stamp(config), 'model_verification': verification,
               'generation_config': generation_config, 'config_version': state.config_version,
               'config_sha256': digest(config), 'previous_organization_sha256': digest(state.organization),
               'records_version': state.records_version, 'previous_project_id': state.project.get('id'),
               'previous_project': copy.deepcopy(state.project), 'previous_organization': copy.deepcopy(state.organization), 'provider_route': PROVIDER_ROUTES[config['provider']],
               'max_output_tokens': maximum, 'model_metadata': model_metadata,
               'profiles_per_request': profiles_per_request, 'response_mode': response_mode,
               'inventory': copy.deepcopy(state.repo_inventory), 'consent': None,
               'revision_context': revision_context}
        self.jobs[job_id] = job
        self._project_job_ids.append(job_id)
        self.keys[key] = job_id
        self._contexts[job_id] = ctx
        self.current_id = job_id
        state.receipt('generation-plan', 'started', 'Preparación del inventario local iniciada. Ningún contenido se envía al proveedor sin autorización.', job_id=job_id)
        self._launch(self._prepare, job_id)

    @staticmethod
    def _launch(function, job_id):
        threading.Thread(target=function, args=(job_id,), daemon=True,
                         name='orgdna-generation-' + job_id[:8]).start()

    def _update(self, job, **values):
        job.update(values, updated_at=timestamp())

    def _prepare(self, job_id):
        state = self.state
        with state.lock:
            ctx = self._contexts.get(job_id)
            if ctx is None:
                return
            job = self.jobs[job_id]
        try:
            module = state._provider()
            inventory = ctx['inventory']
            if inventory is None:
                options = {}
                with state.lock:
                    self._check_current(ctx)
                    if hasattr(module, 'RepositoryCache'):
                        if state.repo_cache is None:
                            state.repo_cache = module.RepositoryCache()
                        options['cache'] = state.repo_cache
                if ctx['config'].get('source_kind') == 'website':
                    if __package__:
                        from .web_sources import analyze_website
                    else:
                        from web_sources import analyze_website
                    inventory = analyze_website(ctx['config']['repo_url'])
                else:
                    inventory = module.analyze_repository(ctx['config']['repo_url'],
                        ref=ctx['config'].get('repo_ref') or None, **options)
            with state.lock:
                self._check_current(ctx)
                inventory = state.redact(copy.deepcopy(inventory))
                ctx['inventory'] = inventory
                self._update(job, stage='preparing_consent', progress=20)
            if ctx.get('revision_context'):
                if __package__:
                    from .improvement import validate_source_baseline
                else:
                    from improvement import validate_source_baseline
                validate_source_baseline(inventory, ctx['previous_organization'])
            revision_options = {'revision_context': ctx['revision_context']} if ctx.get('revision_context') else {}
            consent = self._api().prepare_design_consent(inventory, ctx['provider_route'],
                ctx['config']['model'], ctx['generation_config'], max_output_tokens=ctx['max_output_tokens'],
                model_metadata=ctx['model_metadata'], max_requests=MAX_REQUESTS,
                profiles_per_request=ctx['profiles_per_request'], response_mode=ctx['response_mode'], **revision_options)
            # Names or a tree alone cannot support repository-specialized profiles.
            readable = [item for item in consent.get('preview', {}).get('files', [])
                        if isinstance(item, dict) and isinstance(item.get('snippet'), str)
                        and item['snippet'].strip()]
            website = inventory.get('source_kind') == 'website'
            if website:
                readable = [page for page in consent.get('preview', {}).get('snapshots', [])
                            if isinstance(page, dict) and page.get('content_status') == 'usable_static_html'
                            and (page.get('text_excerpt', '').strip() or any(page.get(k) for k in ('headings', 'forms', 'buttons', 'inputs')))]
            if not readable:
                raise self._error('Etapa de lectura del repositorio: no hay contenido útil de archivos para fundamentar un ADN especializado. No se llamó al modelo. Revisa la referencia o prepara un inventario con archivos legibles.')
            coverage = copy.deepcopy(inventory.get('coverage') or {})
            inventory_complete = coverage.get('inventory_complete') is True
            review = {'source_kind': ctx['config'].get('source_kind', 'github_repository'),
                      'source_url': ctx['config']['repo_url'], 'source_hash': inventory.get('source_hash'),
                      'inventory_complete': inventory_complete,
                      'inventory_status': 'complete' if inventory_complete else 'partial_or_unknown',
                      'known_safe_files': coverage.get('pages_fetched', 0) if website else coverage.get('safe_files_seen', len(inventory.get('tree', []))),
                      'total_repository_files': coverage.get('safe_files_seen', len(inventory.get('tree', []))) if inventory_complete else None,
                      'read_files': len(readable), 'coverage': coverage,
                      'whole_repository_content_complete': False,
                      'note': 'Lectura selectiva de evidencia; no equivale a leer todo el repositorio. Los archivos no observados y sus capacidades no se presuponen.'}
            coverage_hash = digest({'job_id': job_id, 'config_sha256': ctx['config_sha256'],
                                    'payload_sha256': consent['payload_sha256'], 'coverage_review': review})
            with state.lock:
                self._check_current(ctx)
                consent = dict(consent, coverage_review=review, coverage_sha256=coverage_hash,
                               partial_inventory_required=not inventory_complete,
                               approval_id=secrets.token_urlsafe(24), job_id=job_id,
                               config_version=ctx['config_version'], config_sha256=ctx['config_sha256'],
                               agent_count=ctx['config']['agent_count'], organization_id=job['organization_id'])
                if state.redact(consent) != consent:
                    raise self._error('El contenido revisable contiene una credencial de sesión. No se transmitió.')
                ctx['consent'] = copy.deepcopy(consent)
                state.repo_inventory = copy.deepcopy(inventory)
                state.pending_consent = consent
                self._update(job, status='awaiting_consent', stage='review', progress=25,
                             payload_sha256=consent['payload_sha256'], request_hashes=copy.deepcopy(consent.get('request_hashes', [])),
                             max_requests=consent.get('max_requests'), read_files=review['read_files'],
                             known_safe_files=review['known_safe_files'],
                             effective_profiles_per_request=consent.get('effective_profiles_per_request'),
                             effective_max_output_tokens=consent.get('max_output_tokens'),
                             total_max_output_tokens=consent.get('max_total_output_tokens'),
                             max_total_output_tokens=consent.get('max_total_output_tokens'))
                state.receipt('generation-plan', 'pending', 'Revisa el contenido, modelo, N y límites del lote antes de autorizar los cargos posibles.', job_id=job_id)
        except Exception as exc:
            self._fail(job_id, exc)

    def confirm(self, body):
        state = self.state
        job_id = body.get('job_id')
        if job_id not in self.jobs:
            raise self._error('No existe esa generación en esta sesión.')
        job = self.jobs[job_id]
        # Duplicate confirmations do not re-enter provider code, including failures.
        if job['status'] != 'awaiting_consent':
            if job.get('confirmation_consumed'):
                active = self._active()
                if active is None or active['job_id'] == job_id:
                    self.current_id = job_id
                return
            raise self._error('Esta generación no tiene una autorización pendiente.')
        ctx = self._contexts[job_id]
        self._check_current(ctx)
        pending = ctx['consent']
        if (any(body.get(k) is not True for k in ('confirmed', 'data_reviewed', 'budget_acknowledged')) or
                body.get('consent_id') != pending['approval_id'] or
                body.get('payload_sha256') != pending['payload_sha256'] or
                type(body.get('config_version')) is not int or body['config_version'] != ctx['config_version']):
            raise self._error('Confirma el contenido exacto, N, modelo y los posibles cargos del lote revisado.')
        if pending.get('partial_inventory_required') and (
                body.get('partial_inventory_acknowledged') is not True or
                body.get('coverage_sha256') != pending.get('coverage_sha256')):
            raise self._error('El inventario es parcial o desconocido. Revisa sus huecos y autoriza explícitamente esta cobertura para este trabajo antes de enviar al modelo.')
        key = state.credentials.get(ctx['config']['provider'])
        if not key:
            raise self._error('Falta la clave local del proveedor elegido.')
        if state._api_account_stamp(ctx['config']) != ctx['credential_stamp']:
            raise self._error('La cuenta del proveedor cambió desde la preparación. Consulta su catálogo y prepara una autorización nueva antes de enviar.')
        state.validate_api_model_choice(ctx['config'], manual_confirmed=ctx['model_verification']['status'] == 'manual_documented')
        ctx['consent'] = dict(pending, confirmed=True, data_reviewed=True, budget_acknowledged=True,
                              partial_inventory_acknowledged=body.get('partial_inventory_acknowledged') is True)
        state.pending_consent = None
        self._update(job, status='running', stage='api_design', progress=30,
                     confirmation_consumed=True, potentially_billed=True, sent_requests=None, receipts_pending=True)
        self._capture_receipts(job)
        state.receipt('generation-confirm', 'started', 'Autorización consumida para el lote exacto. Un fallo no autoriza reintentos automáticos.', job_id=job_id, payload_sha256=pending['payload_sha256'])
        # Credential passed only on this ephemeral worker's stack; never in job,
        # consent, receipt, project snapshots or export cache.
        threading.Thread(target=self._run, args=(job_id, key), daemon=True,
                         name='orgdna-design-' + job_id[:8]).start()

    def _progress(self, job_id, update):
        if not isinstance(update, dict):
            return
        with self.state.lock:
            job = self.jobs[job_id]
            self._capture_receipts(job, update.get('request_receipts'))
            if job['status'] in TERMINAL:
                raise self._error('La generación ya terminó o fue cancelada.')
            ctx = self._contexts[job_id]
            self._check_current(ctx)
            allowed = {k: v for k, v in update.items() if k in
                       ('completed_requests', 'max_requests', 'completed_profiles', 'total_profiles', 'total_requests', 'sent_requests', 'batch_index') and
                       type(v) is int and 0 <= v <= (MAX_AGENTS if k in ('completed_profiles', 'total_profiles') else 16)}
            maximum = allowed.get('total_requests', allowed.get('max_requests', job.get('max_requests'))) or 1
            completed = allowed.get('completed_requests', job.get('completed_requests', 0))
            self._update(job, **allowed, progress=min(78, 30 + int(48 * completed / maximum)))
            self._capture_receipts(job)

    def _run(self, job_id, api_key):
        state = self.state
        with state.lock:
            ctx = self._contexts.get(job_id)
            if ctx is None:
                # Cancellation can win the race before this worker even starts.
                # No transport was entered, so there is no late receipt to await.
                job = self.jobs.get(job_id)
                if job is not None:
                    self._update(job, receipts_pending=False, sent_requests=0, potentially_billed=False)
                    self._capture_receipts(job)
                    if isinstance(job.get('error'), dict):
                        job['error']['sent_requests'] = 0
                return
            job = self.jobs[job_id]
        try:
            with state.lock:
                self._check_current(ctx)
            revision_options = {'revision_context': ctx['revision_context']} if ctx.get('revision_context') else {}
            result = self._api().design_with_llm(ctx['inventory'], ctx['provider_route'],
                ctx['config']['model'], ctx['generation_config'], api_key, ctx['consent'],
                max_output_tokens=ctx['max_output_tokens'], model_metadata=ctx['model_metadata'],
                max_requests=MAX_REQUESTS, cancel_event=ctx['cancel'],
                profiles_per_request=ctx['profiles_per_request'], response_mode=ctx['response_mode'],
                progress_callback=lambda update: self._progress(job_id, update), **revision_options)
            api_key = None
            with state.lock:
                audit = result.get('audit') if isinstance(result, dict) and isinstance(result.get('audit'), dict) else {}
                for field, source in (('sent_requests', 'requests'), ('completed_requests', 'completed_requests')):
                    value = audit.get(source)
                    if type(value) is int and 0 <= value <= MAX_REQUESTS:
                        job[field] = value
                self._capture_receipts(job, audit.get('receipts'))
                self._check_current(ctx)
                if state.redact(result) != result:
                    raise self._error('La respuesta incluye una credencial de sesión; se descartó sin guardar.')
                self._update(job, status='validating', stage='validating_profiles', progress=82)
            if __package__:
                from . import core
                from .governance import ensure_governance
                from .export_artifacts import build_export_snapshot, organization_fingerprint
                from .bundle import build_package_bytes, validate_bundle, package_filename
            else:
                import core
                from governance import ensure_governance
                from export_artifacts import build_export_snapshot, organization_fingerprint
                from bundle import build_package_bytes, validate_bundle, package_filename
            specs = result.get('profile_specs')
            if not isinstance(specs, list) or len(specs) != ctx['config']['agent_count']:
                raise self._error('El proveedor no devolvió exactamente N perfiles completos. No se exporta un lote parcial.')
            if ctx.get('revision_context'):
                if __package__:
                    from .improvement import preserve_revision_identity, validate_target_changes
                else:
                    from improvement import preserve_revision_identity, validate_target_changes
                specs = preserve_revision_identity(specs, ctx['previous_organization'])
                validate_target_changes(specs, ctx['previous_organization'], ctx['revision_context']['feedback'])
            # All profiles use the explicitly chosen model. No prior overrides,
            # cross-provider preference or static fallback enters automatic DNA.
            catalog = [{'provider': ctx['config']['provider'], 'model': ctx['config']['model'],
                        'available': True, 'availability_verified': True, 'source': 'live_inference'}]
            candidate = core.generate_organization(ctx['generation_config'],
                analysis=result.get('analysis'), model_catalog=catalog,
                profile_specs=specs, provenance=result.get('provenance'),
                previous_organization=ctx['previous_organization'] if ctx['generation_config']['identity_mode'] == 'revision' else None)
            if ctx.get('revision_context'):
                if __package__:
                    from .improvement import finalize_proposal
                else:
                    from improvement import finalize_proposal
                proposal = finalize_proposal(ctx['previous_organization'], candidate, ctx['revision_context']['feedback'])
                job['improvement_proposal'] = copy.deepcopy(proposal)
            candidate = ensure_governance(candidate)
            validation = core.validate_organization(candidate)
            if not validation.get('valid'):
                raise self._error('El ADN no superó validación: ' + '; '.join(validation.get('errors', [])))
            if any(a.get('provider') != ctx['config']['provider'] or a.get('model') != ctx['config']['model']
                   for a in candidate['agents']):
                raise self._error('Una ruta de modelo difiere de la elección autorizada; el ADN no se aplicó.')
            with state.lock:
                self._check_current(ctx)
                self._update(job, stage='building_exports', progress=90)
            snapshot = build_export_snapshot(candidate)
            package = build_package_bytes(candidate, export_snapshot=snapshot)
            bundle_validation = validate_bundle(package)
            if not bundle_validation.get('valid'):
                raise self._error('El paquete no superó la validación final; se conserva el ADN anterior.')
            artifacts = {}
            for kind, alias in (('definitions', 'definitions.json'), ('implementation', 'implementation.json'),
                                ('manifest', 'export-manifest.json')):
                data = snapshot.file_for(alias)
                artifacts[kind] = {'filename': snapshot.filename_for(alias), 'url': '/download/' + alias,
                                   'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            artifacts['package'] = {'filename': package_filename(candidate), 'url': '/download/package.zip',
                                    'sha256': hashlib.sha256(package).hexdigest(), 'bytes': len(package)}
            next_integrations = type(state.integrations)(state) if ctx['generation_config']['identity_mode'] == 'new' else state.integrations
            if next_integrations is not state.integrations:
                next_integrations.adopt_connection(state.integrations)
            candidate_fingerprint = organization_fingerprint(candidate)
            candidate_state_hash = digest(candidate)
            with state.lock:
                self._check_current(ctx)
                if state.redact(candidate) != candidate:
                    raise self._error('Una credencial aparece en el ADN final. No se guardó ni exportó.')
                # Single locked commit after BOTH native JSONs and package validate.
                state.organization = candidate
                state.analysis = copy.deepcopy(result.get('analysis'))
                state.repo_inventory = copy.deepcopy(ctx['inventory'])
                state.model_overrides = {}
                state.models = [m for m in state.models if not (m.get('provider') == ctx['config']['provider'] and
                    m.get('model', m.get('id')) == ctx['config']['model'])] + catalog
                state._record_model_account(ctx['config'])
                state.generation_stale = False
                state.has_manual_edits = False
                state._export_cache = {'organization_sha256': candidate_fingerprint, 'snapshot': snapshot, 'package': package}
                if ctx['generation_config']['identity_mode'] == 'new':
                    state.project = {'id': job['organization_id'], 'name': ctx['config']['repo_name'],
                                     'version_id': None, 'dirty': True}
                    state.records = {key: [] for key in state.records}
                    state.records_version += 1
                    state.integrations = next_integrations
                else:
                    state.project['dirty'] = True
                self._update(job, status='completed', stage='ready', progress=100,
                             artifacts=artifacts, finished_at=timestamp(), organization_state_sha256=candidate_state_hash,
                             dna_hash=candidate.get('dna_hash'), dna_revision=candidate.get('dna_revision'))
                state.remember_current_design()
                state.receipt('generation-complete', 'success', 'ADN completo y dos formatos DSH validados y listos. No se importó ni ejecutó nada en DSH.',
                              job_id=job_id, organization_id=candidate.get('organization_id'),
                              agent_count=len(candidate['agents']), source='api_generated',
                              request_receipts=copy.deepcopy(job['request_receipts']), usage_summary=copy.deepcopy(job['usage_summary']))
                self._contexts.pop(job_id, None)
        except Exception as exc:
            self._fail(job_id, exc)
        finally:
            api_key = None
            with state.lock:
                job['receipts_pending'] = False
                job['updated_at'] = timestamp()

    def _fail(self, job_id, exc):
        state = self.state
        with state.lock:
            job = self.jobs[job_id]
            if __package__:
                from .org_design import DesignError, safe_design_failure
            else:
                from org_design import DesignError, safe_design_failure
            audit = exc.audit if isinstance(exc, DesignError) and isinstance(exc.audit, dict) else {}
            if job['status'] in TERMINAL:
                # A cancelled in-flight request may return usage later. Retain
                # its safe receipt without reviving the job or applying DNA.
                sent = audit.get('requests')
                if type(sent) is int and 0 <= sent <= MAX_REQUESTS:
                    job['sent_requests'] = sent
                self._capture_receipts(job, audit.get('receipts'), safe_design_failure(exc) if audit else None)
                job['updated_at'] = timestamp()
                if job_id == self.current_id:
                    state.project['dirty'] = True
                return
            ctx = self._contexts[job_id]
            cancelled = ctx['cancel'].is_set()
            # Provider errors can contain request credentials or arbitrary raw data.
            # Keep a useful bounded message but never serialize the exception object.
            if __package__:
                from .providers import ProviderError, HTTPFailure
            else:
                from providers import ProviderError, HTTPFailure
            failed_stage = job.get('stage', 'unknown')
            code = 'generation_stage_failed'
            http_status = None
            if isinstance(exc, HTTPFailure) and type(exc.status) is int and 100 <= exc.status <= 599:
                http_status = exc.status
                code = 'repository_http_error' if failed_stage == 'inventory' else 'provider_http_error'
                source = 'GitHub' if failed_stage == 'inventory' else 'El proveedor'
                message = f'{source} devolvió HTTP {http_status}. Comprueba acceso y disponibilidad; no se reintentó automáticamente.'
            elif type(exc).__name__ == 'ImprovementError' and str(exc) in SAFE_FAILURE_MESSAGES:
                code = 'improvement_evidence_invalid'
                message = str(exc)
            elif isinstance(exc, ProviderError):
                code = 'repository_read_failed' if failed_stage == 'inventory' else 'generation_validation_failed'
                message = str(exc) if str(exc) in SAFE_FAILURE_MESSAGES else 'La etapa no pudo completarse. El detalle del adaptador se omitió por seguridad.'
            elif isinstance(exc, type(self._error(''))):
                code = 'generation_state_error'
                message = str(exc) if str(exc) in SAFE_FAILURE_MESSAGES else 'El estado o la validación del diseño impidió completar la etapa. El detalle interno se omitió por seguridad.'
            else:
                message = 'La etapa no pudo completarse. El detalle interno se omitió por seguridad.'
            source_stage = getattr(exc, 'endpoint_stage', None)
            if source_stage not in ('repository_metadata', 'commit_resolution', 'commit_metadata', 'tree_recursive', 'tree_subtree', 'tree_inventory'):
                source_stage = None
            adapter_code = getattr(exc, 'code', None)
            if adapter_code not in ('response_too_large', 'http_error', 'repository_read_error', 'inventory_unavailable'):
                adapter_code = None
            if failed_stage == 'inventory':
                if ctx['config'].get('source_kind') == 'website':
                    message = message.replace('GitHub', 'El sitio web')
            if __package__:
                from .org_design import DesignError, safe_design_failure
            else:
                from org_design import DesignError, safe_design_failure
            detail = safe_design_failure(exc) if failed_stage != 'inventory' else None
            if detail and detail['code'] != 'unknown_design_failure':
                code, message = detail['code'], detail['message']
            elif detail and isinstance(exc, DesignError):
                code, message = detail['code'], detail['message']
            else:
                detail = None
            # The real adapter's audit is internal. Only bounded counters and a
            # small request-state enum are public; no payloads, profiles, body,
            # endpoint, headers or arbitrary exception attributes are retained.
            audit = exc.audit if isinstance(exc, DesignError) and isinstance(exc.audit, dict) else {}
            maximum = job.get('max_requests')
            maximum = maximum if type(maximum) is int and 1 <= maximum <= MAX_REQUESTS else MAX_REQUESTS
            def count(key, cap, fallback=None):
                value = audit.get(key)
                if type(value) is int and 0 <= value <= cap:
                    return value
                return fallback if type(fallback) is int and 0 <= fallback <= cap else None
            sent = count('requests', maximum, job.get('sent_requests'))
            completed = count('completed_requests', sent if type(sent) is int else maximum, job.get('completed_requests', 0))
            profiles = count('completed_profiles', job['agent_count'], job.get('completed_profiles', 0))
            request_status = None
            receipts = audit.get('receipts')
            if isinstance(receipts, list) and receipts and isinstance(receipts[-1], dict):
                value = receipts[-1].get('status')
                if value in ('billing_outcome_unknown', 'response_received_not_yet_validated', 'validated'):
                    request_status = value
            if type(sent) is int and sent == 0:
                job['potentially_billed'] = False
            message = state.redact(message)
            error = {'message': message, 'code': code, 'stage': failed_stage,
                     'source_stage': source_stage, 'adapter_code': adapter_code,
                     'source_kind': ctx['config'].get('source_kind', 'github_repository'), 'retry_requires_new_consent': bool(job.get('confirmation_consumed'))}
            if detail:
                error.update(detail)
            error.update(provider=job['provider'], model=job['model'], sent_requests=sent,
                         completed_requests=completed, max_requests=job.get('max_requests'),
                         completed_profiles=profiles, request_status=request_status)
            if 'category' not in error:
                error['category'] = 'state' if code == 'generation_state_error' else 'unknown'
                error['next_action'] = 'Revisa la etapa y descarga el diagnóstico antes de preparar un plan nuevo. No se reintenta automáticamente.'
            if failed_stage == 'inventory':
                error['reading_note'] = 'No se llamó al modelo; este fallo corresponde a la lectura HTTP de la fuente, no al límite de tokens del LLM.'
            if http_status is not None:
                error['http_status'] = http_status
            self._update(job, status='cancelled' if cancelled else 'failed', stage='cancelled' if cancelled else 'failed',
                         error=error, failed_stage=failed_stage, finished_at=timestamp(),
                         sent_requests=sent, completed_requests=completed, completed_profiles=profiles)
            self._capture_receipts(job, audit.get('receipts'), detail or {'code': code, 'http_status': http_status})
            state.project['dirty'] = True
            if (state.pending_consent or {}).get('job_id') == job_id:
                state.pending_consent = None
            state.receipt('generation-cancel' if cancelled else 'generation-failed', 'warning' if cancelled else 'failed',
                          'Etapa: ' + failed_stage + '. ' + message + ' El diseño anterior se conserva. ' + ('El lote pudo generar cargos; no se reintenta automáticamente.' if job['potentially_billed'] else 'No se inició ningún cargo de diseño.'),
                          job_id=job_id, error=copy.deepcopy(error),
                          request_receipts=copy.deepcopy(job['request_receipts']), usage_summary=copy.deepcopy(job['usage_summary']))
            self._contexts.pop(job_id, None)

    def cancel(self, body):
        job_id = body.get('job_id')
        if job_id not in self.jobs:
            raise self._error('No existe esa generación en esta sesión.')
        job = self.jobs[job_id]
        if job['status'] in TERMINAL:
            return
        ctx = self._contexts[job_id]
        ctx['cancel'].set()
        self._fail(job_id, self._error('Cancelado. Una solicitud ya transmitida puede tener coste; no se aplicarán resultados ni se enviarán los lotes siguientes.'))

    def invalidate(self, reason):
        active = self._active()
        if active:
            self._contexts[active['job_id']]['cancel'].set()
            self._fail(active['job_id'], self._error(reason))
