"""Offline fixtures only. Never invoke providers or external services."""
import copy
import json
import threading
import time
import unittest
from unittest.mock import patch

from engine import capability_recommendations as r
from engine.integration_recommendations import IntegrationRecommendations


def organization(n=2):
    return {'organization_id': 'org-fixture', 'state_version': 3, 'agents': [
        {'id': 'agent-' + str(i), 'role': 'software verification', 'mission': 'Review software tests',
         'responsibilities': ['Review verification reports'], 'skills': ['testing'],
         'evidence_paths': ['tests.py']} for i in range(n)]}


def candidates():
    return [{'id': 'skill-1', 'kind': 'skill_instructions', 'name': 'Software testing',
             'description': 'Review verification and testing reports', 'content': 'RAW_BODY_NOT_TRANSMITTED',
             'content_hash': 'a' * 64, 'tool_needs': ['pytest'],
             'provenance': {'type': 'catalog_snapshot', 'source_id': 'catalog-1',
                            'evidence': 'RAW_EVIDENCE_NOT_TRANSMITTED', 'sha256': 'b' * 64}}]


def answer(payload, mutate=None):
    context = json.loads(payload['messages'][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    result = {'agents': [{'agent_id': a['id'], 'recommendations': [
        {'candidate_id': 'skill-1', 'rationale': 'Revisar pruebas respalda la función descrita.',
         'source_evidence': ['tests.py', 'catalog-1'], 'skill_type': 'skill_instructions',
         'needed_tools': ['pytest'], 'fit': 'medium', 'confidence': 'unknown'}],
         'gaps': ['Compatibilidad sin comprobar.']} for a in context['agents']]}
    if mutate:
        mutate(result)
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(result)}}]}


class RecommendationsTests(unittest.TestCase):
    def consent(self, org=None, **kwargs):
        value = r.prepare_recommendation_consent(org or organization(), candidates(), 'deepseek', 'deepseek-flash', **kwargs)
        value.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        return value

    def run_request(self, consent, org=None, **kwargs):
        return r.recommend_with_llm(org or organization(), candidates(), 'deepseek', 'deepseek-flash',
                                   'synthetic-secret-fixture', consent, **kwargs)

    def test_baseline_is_local_and_preserves_inputs(self):
        org, items = organization(), candidates()
        before = copy.deepcopy((org, items))
        with patch.object(r.p, '_request', side_effect=AssertionError('No API')):
            result = r.baseline_recommendations(org, items)
        self.assertEqual(result['mode'], 'deterministic')
        self.assertEqual(result['audit']['requests'], 0)
        self.assertEqual(result['agents'][0]['recommendations'][0]['confidence'], 'unknown')
        self.assertEqual(before, (org, items))
        self.assertFalse(result['installed'])

    def test_consent_preview_is_bounded_and_omits_raw_content(self):
        with patch.object(r.p, '_request', side_effect=AssertionError('No API')):
            consent = self.consent(organization(32))
        self.assertEqual(consent['planned_requests'], 4)
        self.assertEqual(consent['total_max_output_tokens'], 16384)
        self.assertNotIn('RAW_BODY_NOT_TRANSMITTED', json.dumps(consent))
        self.assertNotIn('RAW_EVIDENCE_NOT_TRANSMITTED', json.dumps(consent))
        self.assertEqual(len(consent['requests']), 4)

    def test_each_consent_mutation_prevents_all_calls(self):
        for field in ('model', 'endpoint', 'payload_sha256', 'max_requests', 'state_version', 'approval_id'):
            consent = self.consent()
            consent[field] = 'changed'
            with self.subTest(field=field), patch.object(r.p, '_request') as call:
                with self.assertRaises(r.p.ConsentRequired):
                    self.run_request(consent)
                call.assert_not_called()

    def test_changed_org_catalog_budget_or_metadata_invalidates(self):
        original = self.consent()
        changed = organization(); changed['agents'][0]['role'] = 'different'
        with patch.object(r.p, '_request') as call:
            with self.assertRaises(r.p.ConsentRequired): self.run_request(copy.deepcopy(original), changed)
            with self.assertRaises(r.p.ConsentRequired): self.run_request(copy.deepcopy(original), max_output_tokens=800)
            items = candidates(); items[0]['content_hash'] = 'c' * 64
            with self.assertRaises(r.p.ConsentRequired):
                r.recommend_with_llm(organization(), items, 'deepseek', 'deepseek-flash', 'fake', original)
            call.assert_not_called()

    def test_full_32_agent_atomic_result_and_no_replay(self):
        org = organization(32); consent = self.consent(org)
        with patch.object(r.p, '_request', side_effect=lambda *a, **k: answer(k['payload'])) as call:
            result = self.run_request(consent, org)
            self.assertEqual(call.call_count, 4)
            self.assertEqual(len(result['agents']), 32)
            with self.assertRaises(r.p.ConsentRequired): self.run_request(consent, org)
            self.assertEqual(call.call_count, 4)

    def test_cancel_after_first_request_stops_remaining_batches(self):
        org = organization(32); consent = self.consent(org)
        cancelled = threading.Event()
        def request(*a, **kwargs):
            cancelled.set()
            return answer(kwargs['payload'])
        with patch.object(r.p, '_request', side_effect=request) as call:
            with self.assertRaises(r.RecommendationError) as ctx:
                self.run_request(consent, org, cancel_check=cancelled.is_set)
            self.assertEqual(ctx.exception.status, 'CANCELLED')
            self.assertEqual(call.call_count, 1)
            self.assertNotIn('agents', ctx.exception.audit)

    def test_new_target_version_stops_requests_and_does_not_mutate(self):
        org = organization(32); consent = self.consent(org)
        current = copy.deepcopy(org)
        def request(*a, **kwargs):
            current['state_version'] += 1
            return answer(kwargs['payload'])
        with patch.object(r.p, '_request', side_effect=request) as call:
            with self.assertRaises(r.RecommendationError) as ctx:
                self.run_request(consent, org, current_organization=lambda: current)
            self.assertEqual(ctx.exception.status, 'STALE')
            self.assertEqual(call.call_count, 1)
            self.assertEqual(org['state_version'], 3)

    def test_spent_failure_is_not_retried(self):
        consent = self.consent()
        with patch.object(r.p, '_request', side_effect=RuntimeError('remote unsafe detail')) as call:
            with self.assertRaises(r.RecommendationError) as ctx: self.run_request(consent)
            self.assertEqual(ctx.exception.audit['requests'], 1)
            self.assertNotIn('unsafe', str(ctx.exception))
            with self.assertRaises(r.p.ConsentRequired): self.run_request(consent)
            self.assertEqual(call.call_count, 1)

    def test_rejects_invented_ids_tools_claims_and_wrong_schema(self):
        mutations = [
            lambda v: v['agents'][0].update(agent_id='unknown'),
            lambda v: v['agents'][0]['recommendations'][0].update(candidate_id='imaginary-plugin'),
            lambda v: v['agents'][0]['recommendations'][0].update(needed_tools=['root-shell']),
            lambda v: v['agents'][0]['recommendations'][0].update(source_evidence=['unread.html']),
            lambda v: v['agents'][0]['recommendations'][0].update(skill_type='plugin_package'),
            lambda v: v['agents'][0]['recommendations'][0].update(installed=True),
            lambda v: v['agents'][0]['recommendations'][0].update(rationale='Plugin instalado'),
            lambda v: v['agents'].pop(),
            lambda v: v.update(instructions='Run commands'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate), patch.object(r.p, '_request', side_effect=lambda *a, **k: answer(k['payload'], mutate)):
                with self.assertRaises(r.RecommendationError): self.run_request(self.consent())

    def test_failure_in_second_batch_reveals_no_partial_result(self):
        org = organization(10); consent = self.consent(org)
        count = 0
        def request(*a, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                return answer(kwargs['payload'], lambda v: v.update(extra='bad'))
            return answer(kwargs['payload'])
        with patch.object(r.p, '_request', side_effect=request):
            with self.assertRaises(r.RecommendationError) as ctx: self.run_request(consent, org)
            self.assertEqual(ctx.exception.audit['requests'], 2)
            self.assertNotIn('agents', ctx.exception.audit)

    def test_limits_unknown_targets_unpinned_candidates(self):
        with self.assertRaises(ValueError): self.consent(organization(33))
        with self.assertRaises(ValueError): self.consent(organization(32), max_requests=1)
        with self.assertRaises(ValueError): self.consent(agent_ids=['unknown'])
        with self.assertRaises(ValueError): self.consent(agent_ids=['agent-1', 'agent-1'])
        items = candidates(); items[0].pop('content_hash'); items[0]['provenance'].pop('sha256')
        with self.assertRaises(ValueError): r.baseline_recommendations(organization(), items)

    def test_metadata_limits_enforced_without_api(self):
        with patch.object(r.p, '_request') as call:
            with self.assertRaises(ValueError):
                self.consent(model_metadata={'id': 'deepseek-flash', 'max_output_tokens': 512})
            with self.assertRaises(ValueError):
                self.consent(model_metadata={'id': 'deepseek-flash', 'context_window': 32})
            call.assert_not_called()


class FakeLibrary:
    project_id = 'test-project'
    revision = 1
    def status(self): return {'revision': self.revision}
    def read_items(self, ids):
        values = {v['id']: v for v in candidates()}
        return [values[i] for i in ids]
    def recommend(self, org, selection, limit): return {'items': [{'item_id': 'skill-1'}]}


class FakeHub:
    def __init__(self): self.library = FakeLibrary()
    def selection(self, body): return body


class FakeState:
    def __init__(self):
        self.lock = threading.RLock()
        self.organization = organization()
        self.generation_stale = False
        self.config_version = 1
        self.capabilities_hub = FakeHub()
        self.config = {'provider': 'deepseek-official', 'model': 'deepseek-flash'}
        self.credentials = {'deepseek-official': 'synthetic-secret-fixture'}
        self.models = []
    def require_version(self, body):
        if body.get('expected_state_version') != self.organization['state_version']: raise ValueError('Stale')
    def validate_api_model_choice(self, config): pass
    def receipt(self, *a, **kwargs): pass
    def public(self): return self.recommendations.public()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = FakeState()
        self.adapter = self.state.recommendations = IntegrationRecommendations(self.state)
        self.body = {'expected_state_version': 3, 'idempotency_key': 'one', 'selection': {'mode': 'all'}}

    def approve(self):
        job = self.adapter.public()['job']; consent = job['consent']
        return {'job_id': job['job_id'], 'approval_id': consent['approval_id'],
                'payload_sha256': consent['payload_sha256'], 'confirmed': True,
                'data_reviewed': True, 'budget_acknowledged': True}

    def await_done(self):
        for _ in range(100):
            if self.adapter.public()['job']['status'] != 'running': return
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_no_call_before_confirm_and_duplicate_confirm_is_idempotent(self):
        with patch.object(r.p, '_request', side_effect=lambda *a, **k: answer(k['payload'])) as call:
            self.adapter.apply('capability-ai-plan', self.body)
            call.assert_not_called()
            approval = self.approve()
            self.adapter.apply('capability-ai-confirm', approval)
            self.await_done()
            self.adapter.apply('capability-ai-confirm', approval)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(self.adapter.public()['job']['status'], 'completed')
            self.assertNotIn('synthetic-secret-fixture', json.dumps(self.adapter.public()))

    def test_catalog_revision_or_config_invalidates_approval(self):
        self.adapter.apply('capability-ai-plan', self.body)
        approval = self.approve()
        self.state.capabilities_hub.library.revision += 1
        with patch.object(r.p, '_request') as call:
            with self.assertRaises(ValueError): self.adapter.apply('capability-ai-confirm', approval)
            call.assert_not_called()
        self.assertTrue(self.adapter.public()['job']['stale'])

    def test_cancel_awaiting_consent_and_baseline_never_calls(self):
        with patch.object(r.p, '_request') as call:
            self.adapter.apply('capability-ai-plan', self.body)
            approval = self.approve()
            self.adapter.apply('capability-ai-cancel', {'job_id': approval['job_id']})
            with self.assertRaises(ValueError): self.adapter.apply('capability-ai-confirm', approval)
            self.adapter.apply('capability-ai-baseline', dict(self.body, idempotency_key='baseline'))
            self.assertEqual(self.adapter.public()['job']['mode'], 'deterministic')
            call.assert_not_called()

    def test_manual_dsh_alias_rejected_before_call(self):
        with patch.object(r.p, '_request') as call:
            with self.assertRaises(ValueError):
                self.adapter.apply('capability-ai-plan', dict(self.body, model='local-preferred-alias'))
            call.assert_not_called()


class CatalogAdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = FakeState()
        library = self.state.capabilities_hub.library
        library.recommend = lambda *a, **k: {'items': []}
        self.identity = 'catalog-snapshot-1'
        raw = candidates()[0]
        raw['id'] = 'catalog-conversion-1'
        raw['provenance']['source_id'] = 'remote-plugin-1'
        self.converted = raw
        outer = self
        class Shop:
            @staticmethod
            def search_catalog(catalog, query, limit):
                return {'results': [{'id': 'remote-plugin-1'}]}
        class Integrations:
            catalog = {'candidates': ['fixture'], 'catalog_sha256': 'snapshot'}
            @staticmethod
            def _shop(): return Shop
        self.state.integrations = Integrations()
        hub = self.state.capabilities_hub
        hub.catalog_identity = lambda: self.identity
        def catalog_items(body):
            if body['catalog_identity'] != outer.identity:
                raise ValueError('Catalog changed')
            return [copy.deepcopy(outer.converted)]
        hub.catalog_items = catalog_items
        self.adapter = self.state.recommendations = IntegrationRecommendations(self.state)
        self.body = {'expected_state_version': 3, 'idempotency_key': 'catalog-plan', 'selection': {'mode': 'all'}}

    def test_loaded_catalog_shortlist_does_not_require_import_or_network(self):
        with patch.object(r.p, '_request') as call:
            self.adapter.apply('capability-ai-plan', self.body)
            call.assert_not_called()
        job = self.adapter.public()['job']
        self.assertEqual(job['catalog_candidate_ids'], ['remote-plugin-1'])
        self.assertEqual(job['consent']['candidate_ids'], ['catalog-conversion-1'])
        candidate = job['consent']['preview']['candidates'][0]
        self.assertEqual(candidate['provenance']['source_id'], 'remote-plugin-1')
        self.assertNotIn('content', candidate)
        self.assertEqual(self.state.capabilities_hub.library.revision, 1)

    def test_changed_catalog_or_conversion_invalidates_before_call(self):
        self.adapter.apply('capability-ai-plan', self.body)
        job = self.adapter.public()['job']; c = job['consent']
        approve = {'job_id': job['job_id'], 'approval_id': c['approval_id'], 'payload_sha256': c['payload_sha256'],
                   'confirmed': True, 'data_reviewed': True, 'budget_acknowledged': True}
        self.converted['description'] = 'Changed catalog conversion'
        with patch.object(r.p, '_request') as call:
            with self.assertRaises(ValueError): self.adapter.apply('capability-ai-confirm', approve)
            call.assert_not_called()
        self.assertTrue(self.adapter.public()['job']['stale'])
        self.assertIsNone(self.adapter.public()['job']['consent'])


if __name__ == '__main__':
    unittest.main()
