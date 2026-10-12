"""Adversarial local transports. Every value and credential is synthetic."""
import copy
import json
import threading
from engine import org_design
from tests_org_design import fixture_profile, fixture_summary

PRIVATE_MARKER = 'QA_V7_PRIVATE_SENTINEL_ONLY'
RAW_MARKER = 'RAW_PROVIDER_BODY_MUST_NOT_APPEAR'

class DesignTransport:
    def __init__(self, mutate=None, fault=None):
        self.calls = []
        self.mutate, self.fault = mutate, fault
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        payload = json.loads(body)
        control = json.loads(payload['messages'][1]['content'].split('DESIGN_CONTROL\n', 1)[1].split('\nEND_DESIGN_CONTROL', 1)[0])
        # Deliberately never retain authorization headers in fixture evidence.
        self.calls.append({'method': method, 'url': url, 'payload': payload, 'timeout': timeout, 'max_bytes': max_bytes})
        self.entered.set()
        self.release.wait(5)
        if self.fault is not None:
            if isinstance(self.fault, Exception):
                raise self.fault
            return self.fault
        value = {'profile_specs': [fixture_profile(slot) for slot in control['requested_slots']],
                 'model_selection': {'provider': control['selected_provider'], 'model': control['selected_model'],
                                     'rationale': 'Selección exacta y pendiente de revisión.'},
                 'warnings': ['Evidencia estática parcial; no acredita ejecución.']}
        response = {'id': 'fixture-' + str(len(self.calls)), 'choices': [{'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False)}}],
                    'usage': {'prompt_tokens': 12, 'completion_tokens': 34, 'total_tokens': 46}}
        if self.mutate:
            self.mutate(value, response, len(self.calls))
        # Mutations can alter the raw message explicitly for broken-JSON cases.
        if not response.pop('_preserve_content', False):
            response['choices'][0]['message']['content'] = json.dumps(value, ensure_ascii=False)
        return 200, {}, json.dumps(response, ensure_ascii=False).encode()

class PipelineProvider:
    def __init__(self, transport=None):
        self.transport = transport or DesignTransport()
        self.inventory_calls, self.design_calls = 0, 0

    def discover_models(self, provider, api_key):
        # Synthetic observation through the production discovery boundary.
        # This method never enters DesignTransport or any network transport.
        assert provider == 'deepseek' and api_key == PRIVATE_MARKER
        return {'source': 'live_api', 'status': 'synthetic_fixture_only', 'verified_at': 'QA_V7_OFFLINE',
                'models': [{'id': 'fixture-model', 'source': 'live_api',
                            'availability_verified': True, 'synthetic_fixture': True}]}

    def analyze_repository(self, repo_url, ref=None, **kwargs):
        self.inventory_calls += 1
        result = fixture_summary()
        result['repository']['url'] = repo_url
        return result

    prepare_design_consent = staticmethod(org_design.prepare_design_consent)

    def design_with_llm(self, *args, **kwargs):
        self.design_calls += 1
        return org_design.design_with_llm(*args, transport=self.transport, **kwargs)
