"""Manual website analysis through preview/approval; offline transports only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import providers as p
from engine.bridge import BridgeState, BridgeError
from engine.project_store import ProjectStore
from tests_bridge import NullStore
from tests_org_design_website import fixture_website


def response_value(url):
    return {'professions': [{'id': 'review', 'title': 'Revisión de interacción',
                            'expertise': ['Diseño de interacción'], 'methods': ['Contrastar el botón observado con el objetivo de revisión'],
                            'evidence_paths': [url], 'confidence': 'low'}],
            'skills': [{'id': 'flow', 'name': 'Inspección de navegación',
                        'description': 'Comparar etiquetas visibles y secuencia de revisión propuesta', 'evidence_paths': [url]}],
            'model_selection': {'provider': 'deepseek', 'model': 'deepseek-flash', 'rationale': 'Modelo seleccionado por el usuario.'},
            'warnings': ['Observación parcial pendiente de contraste.']}


def response_body(value):
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(value)}}]}


class ManualWebsiteAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch('socket.create_connection', side_effect=AssertionError('No network allowed'))
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.summary = fixture_website()
        self.calls = []

    def transport(self, method, url, headers, body, timeout, max_bytes):
        self.calls.append(json.loads(body))
        return 200, {}, json.dumps(response_body(response_value(self.summary['source_url']))).encode()

    def consent(self):
        result = p.prepare_llm_consent(self.summary, 'deepseek', 'deepseek-flash', 8192)
        result.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        return result

    def test_manual_preview_confirm_result_keeps_web_ledger_and_one_request(self):
        consent = self.consent()
        self.assertEqual(self.calls, [])
        self.assertEqual(consent['source_kind'], 'website')
        self.assertEqual(consent['coverage']['scope']['max_pages'], 12)
        self.assertIsNone(consent['repository'])
        result = p.analyze_with_llm(self.summary, 'deepseek', 'deepseek-flash', 'OFFLINE_FIXTURE_KEY', consent,
                                    max_output_tokens=8192, transport=self.transport)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result['evidence_urls'], [self.summary['source_url']])
        self.assertEqual(result['snapshots'], consent['source_provenance']['snapshots'])
        self.assertEqual(result['coverage']['limitations'], consent['coverage']['limitations'])
        self.assertNotIn('repository', result)
        self.assertNotIn('repository_sha', result)
        self.assertEqual(result['audit']['requests'], 1)
        with self.assertRaises(p.ConsentRequired):
            p.analyze_with_llm(self.summary, 'deepseek', 'deepseek-flash', 'OFFLINE_FIXTURE_KEY', consent,
                               max_output_tokens=8192, transport=self.transport)
        self.assertEqual(len(self.calls), 1)

    def test_manual_mutated_visible_preview_is_rejected_before_network(self):
        for field in ('preview', 'source_provenance', 'coverage'):
            consent = self.consent()
            consent[field]['forged'] = True
            with self.subTest(field=field), self.assertRaises(p.ConsentRequired):
                p.analyze_with_llm(self.summary, 'deepseek', 'deepseek-flash', 'OFFLINE_FIXTURE_KEY', consent,
                                   max_output_tokens=8192, transport=self.transport)
        self.assertEqual(self.calls, [])

    def test_manual_unobserved_urls_and_fake_file_paths_rejected(self):
        for reference in ('README.md', 'https://evil.example/steal', self.summary['source_url'] + '#unobserved'):
            value = response_value(self.summary['source_url'])
            value['professions'][0]['evidence_paths'] = [reference]
            with self.subTest(reference=reference), self.assertRaises(p.ProviderError):
                p.validate_analysis(value, p.prepare_summary(self.summary), 'deepseek', 'deepseek-flash')

    def test_bridge_manual_website_prepare_partial_approval_confirm_generate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = BridgeState(credential_store=NullStore(), project_store=ProjectStore(Path(directory)/'projects'))
            state.execute('config', {'config': {'source_kind': 'website', 'repo_url': self.summary['source_url'],
                           'repo_name': 'Website fixture', 'model': 'deepseek-flash', 'analysis_model': 'deepseek-flash',
                           'agent_count': 3, 'council_concurrency': 3, 'provider': 'deepseek-official'}})
            state.repo_inventory = copy.deepcopy(self.summary)
            state.credentials['deepseek-official'] = 'OFFLINE_FIXTURE_KEY'
            state.models = [{'provider': 'deepseek-official', 'model': 'deepseek-flash',
                'source': 'live_api', 'available': True, 'availability_verified': True,
                'synthetic_fixture': True}]
            state._record_model_account(state.config)
            with patch('engine.providers._request', return_value=response_body(response_value(self.summary['source_url']))) as call:
                state.execute('prepare-analysis', {'max_output_tokens': 8192})
                self.assertEqual(call.call_count, 0)
                pending = state.pending_consent
                approval = {'confirmed': True, 'consent_id': pending['approval_id'],
                            'payload_sha256': pending['payload_sha256'], 'data_reviewed': True, 'budget_acknowledged': True}
                with self.assertRaises(BridgeError):
                    state.execute('confirm-analysis', approval)
                self.assertEqual(call.call_count, 0)
                approval.update(partial_inventory_acknowledged=True, coverage_sha256=pending['coverage_sha256'])
                state.execute('confirm-analysis', approval)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(state.analysis['source_kind'], 'website')
                state.execute('generate', {})
                self.assertEqual(len(state.organization['agents']), 3)
                self.assertEqual(state.organization['provenance']['snapshots'], state.analysis['snapshots'])
                self.assertNotIn('repository_sha', state.organization['provenance'])


if __name__ == '__main__': unittest.main()
