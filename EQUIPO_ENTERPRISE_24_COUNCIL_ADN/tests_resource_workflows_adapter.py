"""Offline workflow bridge and atomic per-role assignment regression tests."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from engine.bridge import BridgeState
from engine.project_store import ProjectStore
from engine.capability_library import CapabilityLibrary
from tests_bridge import NullStore
from tests.test_resource_workflows import answer


class WorkflowAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = BridgeState(credential_store=NullStore(), project_store=ProjectStore(Path(self.tmp.name) / 'projects'))
        self.s.execute('config', {'config': {'agent_count': 3, 'council_concurrency': 3}})
        self.s.execute('generate', {})
        self.s.execute('resource-workflow-example', {})

    def body(self, **kw):
        return {'expected_state_version': self.s.organization['state_version'],
                'reference_hash': self.s.capabilities_hub.reference['source_hash'],
                'selection': {'mode': 'all'}, 'idempotency_key': 'fixture-plan', **kw}

    def baseline(self):
        return self.s.execute('resource-workflow-baseline', self.body())['resource_workflows']['job']

    def preview(self, job, **kw):
        return self.s.execute('resource-workflow-preview', self.body(job_id=job['job_id'],
             expected_revision=self.s.capabilities_hub.library.status()['revision'], **kw))['resource_workflows']['preview']

    def apply(self, preview, **kw):
        return self.s.execute('resource-workflow-apply', self.body(preview_hash=preview['preview_hash'],
                        confirmed=True, idempotency_key='fixture-apply', **kw))

    def test_example_is_inert_and_explicit_research_snapshot(self):
        self.assertEqual(self.s.capabilities_hub.reference['source_kind'], 'research_snapshot')
        self.assertFalse(self.s.capabilities_hub.reference['live_fetch_performed'])
        self.assertEqual(self.s.capabilities_hub.library.status()['item_count'], 0)

    def test_preview_readonly_apply_exact_per_role_and_replay(self):
        job = self.baseline(); preview = self.preview(job)
        self.assertEqual(self.s.capabilities_hub.library.status()['item_count'], 0)
        self.assertEqual(preview['changed_count'], 3)
        self.apply(preview)
        status = self.s.capabilities_hub.library.status()
        self.assertEqual(status['assigned_count'], 3)
        self.assertEqual(status['active_count'], 0)
        rows = self.s.capabilities_hub.library.manifest_page()['items']
        for row in rows:
            self.assertIn(row['item_id'], job['result']['agent_item_ids'][row['agent_id']])
        self.apply(preview)
        self.assertEqual(status, self.s.capabilities_hub.library.status())

    def test_subset_activation_only_selected_agent(self):
        job = self.baseline(); aid = job['result']['agents'][0]['agent_id']
        preview = self.preview(job, workflow_agent_ids=[aid], action='activate')
        self.apply(preview)
        rows = self.s.capabilities_hub.library.manifest_page()['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['agent_id'], aid)
        self.assertTrue(rows[0]['active'])
        exported = self.s._exports()['snapshot']
        self.assertIsNotNone(exported.capability_library)

    def test_source_role_library_changes_block_apply(self):
        job = self.baseline(); preview = self.preview(job)
        self.s.capabilities_hub.reference['source_hash'] = 'b' * 64
        with self.assertRaises(ValueError): self.apply(preview)
        self.assertEqual(self.s.capabilities_hub.library.status()['item_count'], 0)

    def test_failed_late_assignment_rolls_back_all_imports(self):
        job = self.baseline(); preview = self.preview(job)
        original = CapabilityLibrary.apply; calls = 0
        def fail_second(instance, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2: raise ValueError('fixture error')
            return original(instance, *args, **kwargs)
        with patch.object(CapabilityLibrary, 'apply', fail_second):
            with self.assertRaises(ValueError): self.apply(preview)
        status = self.s.capabilities_hub.library.status()
        self.assertEqual(status['item_count'], 0)
        self.assertEqual(status['assigned_count'], 0)
        self.assertEqual(status['revision'], 0)

    def test_invalid_subset_never_crossassigns(self):
        job = self.baseline()
        for ids in ([], ['missing'], [job['result']['agents'][0]['agent_id']] * 2):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.preview(job, workflow_agent_ids=ids)

    def test_ai_async_exact_consent_no_replay_or_import(self):
        from engine import resource_workflows as w
        self.s.config.update(provider='deepseek-official', model='deepseek-flash')
        self.s.credentials['deepseek-official'] = 'fixture-session-secret'
        catalog = {'source': 'live_api', 'verified_at': 'OFFLINE_FIXTURE_ONLY',
            'models': [{'id': 'deepseek-flash', 'source': 'live_api',
                        'availability_verified': True, 'synthetic_fixture': True}]}
        with patch.object(self.s._provider(), 'discover_models', return_value=catalog):
            self.s.execute('discover-models', {'confirmed': True})
        with patch.object(w.p, '_request', side_effect=lambda *a, **kw: answer(kw['payload'])) as call:
            result = self.s.execute('resource-workflow-plan', self.body())
            call.assert_not_called()
            job = result['resource_workflows']['job']; consent = job['consent']
            body = {'job_id': job['job_id'], 'confirmed': True, 'data_reviewed': True,
                    'budget_acknowledged': True, 'approval_id': consent['approval_id'],
                    'payload_sha256': consent['payload_sha256']}
            self.s.execute('resource-workflow-confirm', body)
            for _ in range(200):
                if self.s.resource_workflows.public()['job']['status'] != 'running': break
                time.sleep(.01)
            self.assertEqual(self.s.resource_workflows.public()['job']['status'], 'completed')
            self.s.execute('resource-workflow-confirm', body)
            self.assertEqual(call.call_count, 1)
        self.assertEqual(self.s.capabilities_hub.library.status()['item_count'], 0)
        self.assertNotIn('fixture-session-secret', str(self.s.resource_workflows.public()))

    def test_selected_provider_cannot_be_overridden(self):
        with self.assertRaises(ValueError):
            self.s.execute('resource-workflow-plan', self.body(provider='unknown', model='unknown'))

    def test_unreviewed_apply_fails(self):
        job = self.baseline(); preview = self.preview(job)
        body = self.body(preview_hash=preview['preview_hash'], idempotency_key='apply-no', confirmed=False)
        with self.assertRaises(ValueError): self.s.execute('resource-workflow-apply', body)
        self.assertEqual(self.s.capabilities_hub.library.status()['item_count'], 0)

    def test_secrets_never_exported(self):
        self.s.credentials['deepseek'] = 'fixture-session-secret'
        job = self.baseline(); self.apply(self.preview(job))
        self.assertNotIn('fixture-session-secret', str(self.s.capabilities_hub.library.manifest_page()))
        self.assertNotIn('fixture-session-secret', str(job))


if __name__ == '__main__': unittest.main()
