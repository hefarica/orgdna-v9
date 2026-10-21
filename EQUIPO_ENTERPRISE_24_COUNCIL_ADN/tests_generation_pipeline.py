"""Local asynchronous integration tests. Provider responses are synthetic fixtures.

No live API keys, network, DSH import, workbook mutation or paid calls occur.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from engine.bridge import BridgeState, BridgeError
from engine.project_store import ProjectStore
from engine import org_design
from qa_v3.fixtures import inventory_fixture, design_result
from tests_bridge import NullStore


class MockDesignProvider:
    def __init__(self):
        self.inventory_calls = 0
        self.design_calls = 0
        self.fail = False
        self.partial = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def analyze_repository(self, repo_url, ref=None, **kwargs):
        self.inventory_calls += 1
        value = inventory_fixture()
        value['repository']['url'] = repo_url
        return value

    def prepare_design_consent(self, *args, **kwargs):
        return org_design.prepare_design_consent(*args, **kwargs)

    def design_with_llm(self, summary, provider, model, config, api_key, consent, **kwargs):
        self.design_calls += 1
        self.entered.set()
        self.release.wait(5)
        if self.fail:
            raise RuntimeError('Unsafe upstream body contains ' + api_key)
        result = design_result(config['agent_count'])
        result['provenance']['provider'] = provider
        result['provenance']['model'] = model
        if self.partial:
            result['profile_specs'].pop()
        kwargs['progress_callback']({'completed_requests': 1, 'total_requests': 1})
        return result


class GenerationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = MockDesignProvider()
        self.state = BridgeState(credential_store=NullStore(), provider_module=self.provider,
            project_store=ProjectStore(Path(self.temp.name) / 'projects'))
        self.secret = 'SYNTHETIC_ONLY_NOT_A_REAL_CREDENTIAL'
        self.state.execute('credentials', {'provider': 'deepseek-official', 'api_key': self.secret})
        self.state.execute('config', {'config': {'repo_url': 'https://github.com/example/qa-fixture',
            'repo_name': 'Synthetic API pipeline fixture', 'template': 'generic', 'agent_count': 4,
            'council_concurrency': 4, 'model': 'fixture-model'}})
        # Synthetic catalog evidence for the offline adapter, never a real GET.
        self.state.models = [{'provider': 'deepseek-official', 'model': 'fixture-model',
            'source': 'live_api', 'available': True, 'availability_verified': True,
            'catalog_scope': 'provider_api', 'synthetic_fixture': True}]
        self.state._record_model_account(self.state.config)
        self.exceptions = []
        original = self.state.generation._fail
        def capture(job_id, exc):
            self.exceptions.append(exc)
            return original(job_id, exc)
        self.state.generation._fail = capture

    def tearDown(self):
        self.provider.release.set()
        active = self.state.generation._active()
        if active:
            self.state.execute('generation-cancel', {'job_id': active['job_id']})
        self.temp.cleanup()

    def wait_for(self, *statuses):
        # 12 -> 45: los exports GenTeam (addon con 2 tools nuevas x 24 perfiles en 3
        # variantes) estiraron building_exports; medido 27-32s bajo la suite completa
        # (saturacion del proceso) y <1s aislado. Frontera movida con la medicion
        # declarada, patron P3-K. Optimizar el builder queda como pendiente.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            job = self.state.public()['generation_job']
            if job and job['status'] in statuses:
                return job
            if job and job['status'] == 'failed':
                self.fail('Generation unexpectedly failed: ' + repr(self.exceptions))
            time.sleep(.01)
        self.fail('Generation did not finish: ' + repr(self.state.generation.public()))

    def plan(self, **options):
        body = {'idempotency_key': str(uuid.uuid4()), 'new_project': True, **options}
        self.state.execute('generation-plan', body)
        self.wait_for('awaiting_consent')
        return body

    def approval(self):
        pending = self.state.pending_consent
        return {'job_id': pending['job_id'], 'config_version': pending['config_version'],
            'consent_id': pending['approval_id'], 'payload_sha256': pending['payload_sha256'],
            'confirmed': True, 'data_reviewed': True, 'budget_acknowledged': True}

    def complete(self, **options):
        self.plan(**options)
        self.state.execute('generation-confirm', self.approval())
        return self.wait_for('completed')

    def test_website_preview_is_partial_snapshot_bound_and_unpaid(self):
        from engine.web_sources import analyze_website
        from qa_v6.test_independent_multisource import WebFixture, ROOT
        inventory = analyze_website(ROOT, transport=WebFixture())
        self.state.execute('config', {'config': {'source_kind': 'website', 'repo_url': ROOT}})
        with patch('engine.web_sources.analyze_website', return_value=inventory):
            self.plan()
        pending = self.state.pending_consent
        self.assertEqual(self.provider.inventory_calls, 0)
        self.assertEqual(self.provider.design_calls, 0)
        self.assertTrue(pending['partial_inventory_required'])
        self.assertEqual(pending['coverage_review']['source_kind'], 'website')
        self.assertEqual(pending['coverage_review']['source_hash'], inventory['source_hash'])
        self.assertNotIn('repository', pending['preview'])
        self.assertNotIn('repository_sha', pending['source_provenance'])
        self.assertIsNone(pending['coverage_review']['total_repository_files'])
        with self.assertRaises(BridgeError):
            self.state.execute('generation-confirm', self.approval())
        self.assertEqual(self.provider.design_calls, 0)

    def test_partial_inventory_requires_bound_explicit_acknowledgement(self):
        inventory = inventory_fixture()
        inventory['coverage'].update(inventory_complete=False, safe_files_seen=4100,
            gaps=['No se pudo observar todo el árbol'], inventory={'method': 'bounded_subtrees'})
        self.state.repo_inventory = inventory
        self.plan()
        pending = self.state.pending_consent
        self.assertEqual(pending['coverage_review']['known_safe_files'], 4100)
        self.assertIsNone(pending['coverage_review']['total_repository_files'])
        self.assertEqual(pending['coverage_review']['read_files'], 3)
        self.assertTrue(pending['partial_inventory_required'])
        approval = self.approval()
        with self.assertRaisesRegex(BridgeError, 'inventario es parcial'):
            self.state.execute('generation-confirm', approval)
        with self.assertRaises(BridgeError):
            self.state.execute('generation-confirm', dict(approval,
                partial_inventory_acknowledged=True, coverage_sha256='0'*64))
        self.assertEqual(self.provider.design_calls, 0)
        self.state.execute('generation-confirm', dict(approval,
            partial_inventory_acknowledged=True, coverage_sha256=pending['coverage_sha256']))
        self.wait_for('completed')
        self.assertEqual(self.provider.design_calls, 1)

    def test_unknown_inventory_never_claims_complete(self):
        inventory = inventory_fixture()
        inventory['coverage'] = {}
        self.state.repo_inventory = inventory
        self.plan()
        pending = self.state.pending_consent
        self.assertTrue(pending['partial_inventory_required'])
        self.assertIsNone(pending['coverage_review']['total_repository_files'])
        self.assertFalse(pending['coverage_review']['whole_repository_content_complete'])

    def test_empty_text_cannot_generate_specialized_profiles(self):
        inventory = inventory_fixture()
        for item in inventory['files']:
            item['snippet'] = '   '
        self.state.repo_inventory = inventory
        self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4())})
        job = self.wait_for('failed')
        self.assertIn('no hay contenido útil', job['error']['message'])
        self.assertEqual(self.provider.design_calls, 0)
        self.assertIsNone(self.state.pending_consent)

    def test_complete_inventory_still_means_selected_content(self):
        inventory = inventory_fixture()
        inventory['coverage'].update(inventory_complete=True, safe_files_seen=150000)
        self.state.repo_inventory = inventory
        self.plan()
        review = self.state.pending_consent['coverage_review']
        self.assertEqual(review['total_repository_files'], 150000)
        self.assertEqual(review['read_files'], 3)
        self.assertFalse(review['whole_repository_content_complete'])
        self.assertFalse(self.state.pending_consent['partial_inventory_required'])

    def test_preview_has_exact_payload_and_no_paid_work(self):
        self.plan()
        self.assertEqual(self.provider.inventory_calls, 1)
        self.assertEqual(self.provider.design_calls, 0)
        pending = self.state.pending_consent
        self.assertEqual(pending['agent_count'], 4)
        self.assertEqual(pending['max_requests'], len(pending['requests']))
        self.assertTrue(pending['requests'][0]['payload'])
        self.assertNotIn(self.secret, json.dumps(self.state.public()))

    def test_plan_double_click_reuses_inventory_and_identity(self):
        body = self.plan()
        first = self.state.generation.public()
        self.state.execute('generation-plan', body)
        self.assertEqual(first, self.state.generation.public())
        self.assertEqual(self.provider.inventory_calls, 1)
        with self.assertRaises(BridgeError):
            self.state.execute('generation-plan', dict(body, config={'agent_count': 3, 'council_concurrency': 3}))

    def test_atomic_success_exact_n_native_exports_and_same_zip_bytes(self):
        job = self.complete()
        org = self.state.organization
        self.assertEqual(len(org['agents']), 4)
        self.assertEqual(org['organization_id'], self.state.project['id'])
        self.assertEqual(org['provenance']['generation_mode'], 'api_generated')
        self.assertEqual(self.provider.design_calls, 1)
        archive = zipfile.ZipFile(io.BytesIO(self.state.download('package.zip')))
        for kind, alias in [('definitions', 'definitions.json'), ('implementation', 'implementation.json')]:
            artifact = job['artifacts'][kind]
            data = self.state.download(alias)
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact['sha256'])
            self.assertEqual(data, archive.read(next(n for n in archive.namelist() if n.endswith('/' + artifact['filename']))))
        a = json.loads(self.state.download('definitions.json'))
        b = json.loads(self.state.download('implementation.json'))
        self.assertEqual(a['exportedAt'], b['exportedAt'])
        self.assertEqual(self.state.download('package.zip'), self.state.download('package.zip'))

    def test_concurrent_confirmation_and_replay_cannot_rebill(self):
        self.plan()
        approval = self.approval()
        threads = [threading.Thread(target=self.state.execute, args=('generation-confirm', approval)) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.wait_for('completed')
        self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 1)

    def test_failure_preserves_old_design_and_consumes_consent(self):
        self.state.execute('generate', {})
        old = copy.deepcopy(self.state.organization)
        self.provider.fail = True
        self.plan()
        approval = self.approval()
        self.state.execute('generation-confirm', approval)
        self.wait_for('failed')
        self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 1)
        self.assertEqual(old, self.state.organization)
        self.assertNotIn(self.secret, json.dumps(self.state.public()))
        self.assertNotIn('Unsafe upstream', json.dumps(self.state.public()))

    def test_partial_response_never_replaces_previous_design(self):
        self.state.execute('generate', {})
        old = copy.deepcopy(self.state.organization)
        self.provider.partial = True
        self.plan()
        self.state.execute('generation-confirm', self.approval())
        self.wait_for('failed')
        self.assertEqual(old, self.state.organization)
        self.assertIsNone(self.state.generation.public()['artifacts'])

    def test_cancel_during_call_prevents_commit_and_later_calls(self):
        self.provider.release.clear()
        self.plan()
        approval = self.approval()
        self.state.execute('generation-confirm', approval)
        self.assertTrue(self.provider.entered.wait(2))
        self.state.execute('generation-cancel', {'job_id': approval['job_id']})
        self.provider.release.set()
        job = self.wait_for('cancelled')
        self.assertTrue(job['potentially_billed'])
        self.assertIsNone(self.state.organization)
        self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 1)

    def test_config_change_invalidates_pending_consent_before_payment(self):
        self.plan()
        approval = self.approval()
        self.state.execute('config', {'config': {'model': 'another-fixture-model'}})
        with self.assertRaises(BridgeError):
            self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 0)
        self.assertEqual(self.state.generation.public()['status'], 'cancelled')

    def test_revision_preserves_ids_new_project_changes_them(self):
        self.complete()
        first = copy.deepcopy(self.state.organization)
        self.complete(new_project=False)
        revised = copy.deepcopy(self.state.organization)
        self.assertEqual(first['organization_id'], revised['organization_id'])
        self.assertEqual([a['id'] for a in first['agents']], [a['id'] for a in revised['agents']])
        self.assertEqual(revised['dna_revision'], first['dna_revision'] + 1)
        self.complete(new_project=True)
        self.assertNotEqual(revised['organization_id'], self.state.organization['organization_id'])
        self.assertEqual(self.provider.inventory_calls, 1)

    def test_save_reload_does_not_restore_consent_or_start_jobs(self):
        self.complete()
        self.state.execute('project-save', {'name': 'Synthetic saved organization'})
        project_id = self.state.project['id']
        envelope = self.state.project_store.load(project_id)
        self.assertEqual(envelope['metadata']['organization_id'], self.state.organization['organization_id'])
        other = BridgeState(credential_store=NullStore(), provider_module=self.provider, project_store=self.state.project_store)
        other.execute('project-load', {'project_id': project_id})
        self.assertIsNone(other.pending_consent)
        self.assertEqual(other.generation.public()['status'], 'completed')
        self.assertTrue(other.generation.public()['restored_from_project'])
        self.assertIsNone(other.generation._active())
        self.assertEqual(other.generation._contexts, {})
        self.assertEqual(self.provider.design_calls, 1)
        for path in self.state.project_store.root.rglob('*.json'):
            self.assertNotIn(self.secret, path.read_text())
            self.assertNotIn('pending_consent', path.read_text())

    def test_revision_of_imported_roster_preserves_original_agents_and_squad(self):
        from engine import core
        base = core.export_recipe(core.generate_organization(self.state.config))
        imported = core.generate_organization(dict(self.state.config, identity_mode='import_legacy',
            organization_id=str(uuid.uuid4()), dna_revision=1), base_recipe=base)
        self.state.organization = imported
        self.state.generation_stale = False
        self.state.project['id'] = imported['organization_id']
        self.complete(new_project=False)
        result = self.state.organization
        self.assertEqual(result['organization_id'], imported['organization_id'])
        self.assertEqual(result['dna_revision'], 2)
        self.assertEqual([a['id'] for a in result['agents']], [a['id'] for a in imported['agents']])
        recipe = json.loads(self.state.download('implementation.json'))
        self.assertEqual(recipe['squad']['id'], base['squad']['id'])

    def test_autonomy_defaults_and_editable_goal_are_previewed_without_network(self):
        preview = self.state.public()['autonomy_preview']
        self.assertEqual(preview['preset'], 'autonomous')
        self.assertIn('plan_preview', preview)
        self.assertEqual(self.provider.design_calls, 0)
        self.state.execute('config', {'config': {'autonomy_preset': 'smart', 'planning_context': 'recent',
            'response_mode': 'background', 'planner_max_tokens': 6000, 'member_timeout_ms': 60000,
            'handoff_summary_max_chars': 8000, 'runtime_token_budget': 48000,
            'quality_gate_rounds': 1, 'objective': 'Validar contratos del servicio con evidencia reproducible.'}})
        self.assertEqual(self.state.public()['autonomy_preview']['preset'], 'smart')
        self.plan()
        consent = self.state.pending_consent
        self.assertIn('Validar contratos', json.dumps(consent, ensure_ascii=False))
        self.assertEqual(self.provider.design_calls, 0)

    def test_advanced_settings_are_validated_before_any_api_work(self):
        for field, value in [('autonomy_preset', 'unknown'), ('planning_context', 'unlimited'),
            ('response_mode', 'unknown'), ('planner_max_tokens', 8193), ('member_timeout_ms', 0),
            ('handoff_summary_max_chars', 32001), ('runtime_token_budget', 0),
            ('quality_gate_rounds', 3), ('objective', 'x' * 5001)]:
            with self.subTest(field=field), self.assertRaises((ValueError, BridgeError)):
                self.state.execute('config', {'config': {field: value}})
        self.assertEqual(self.provider.design_calls, 0)
        self.assertEqual(self.provider.inventory_calls, 0)

    def test_changing_objective_invalidates_exact_batch_approval(self):
        self.plan()
        approval = self.approval()
        self.state.execute('config', {'config': {'objective': 'Un alcance nuevo requiere autorización nueva.'}})
        with self.assertRaises(BridgeError):
            self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 0)

    def test_historical_completed_hashes_do_not_point_to_changed_design(self):
        self.complete()
        self.assertTrue(self.state.generation.public()['artifacts_current'])
        self.state.execute('config', {'config': {'repo_name': 'Changed name'}})
        job = self.state.generation.public()
        self.assertFalse(job['artifacts_current'])
        self.assertIsNone(job['artifacts'])
        self.assertIsNone(self.state.public()['export_artifacts'])

    def test_failed_artifact_build_cannot_commit_any_candidate_state(self):
        self.state.execute('generate', {})
        previous = copy.deepcopy(self.state.organization)
        previous_models = copy.deepcopy(self.state.models)
        previous_project = copy.deepcopy(self.state.project)
        self.plan()
        with patch('engine.bundle.build_package_bytes', side_effect=ValueError('Synthetic export failure')):
            self.state.execute('generation-confirm', self.approval())
            self.wait_for('failed')
        self.assertEqual(self.state.organization, previous)
        self.assertEqual(self.state.models, previous_models)
        self.assertEqual(self.state.project, previous_project)
        self.assertIsNone(self.state.generation.public()['artifacts'])

    def test_secret_stays_redacted_after_forgetting_local_credential(self):
        self.state.receipt('test', 'warning', 'Synthetic message ' + self.secret)
        self.state.execute('forget-credentials', {})
        self.assertEqual(self.state.credentials, {})
        self.assertEqual(self.state.redact(self.secret), '[REDACTED]')
        self.assertNotIn(self.secret, json.dumps(self.state.public()))

    def test_invalid_approval_flags_do_not_start_a_paid_request(self):
        self.plan()
        valid = self.approval()
        for key in ('confirmed', 'data_reviewed', 'budget_acknowledged'):
            with self.subTest(flag=key), self.assertRaises(BridgeError):
                self.state.execute('generation-confirm', dict(valid, **{key: False}))
        for key, value in [('config_version', -1), ('payload_sha256', 'changed'), ('consent_id', 'changed')]:
            with self.subTest(field=key), self.assertRaises(BridgeError):
                self.state.execute('generation-confirm', dict(valid, **{key: value}))
        self.assertEqual(self.provider.design_calls, 0)
        self.assertEqual(self.state.generation.public()['status'], 'awaiting_consent')

    def test_cancellation_before_consent_is_free_and_does_not_generate(self):
        self.plan()
        job = self.state.generation.public()
        self.state.execute('generation-cancel', {'job_id': job['job_id']})
        self.assertEqual(self.provider.design_calls, 0)
        self.assertFalse(self.state.generation.public()['potentially_billed'])
        self.assertIsNone(self.state.organization)


if __name__ == '__main__':
    unittest.main()
