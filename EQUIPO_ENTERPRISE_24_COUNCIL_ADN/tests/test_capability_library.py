"""Offline capability registry/CAS/activation tests; no external tools."""
import copy
import tempfile
import unittest
from pathlib import Path
from engine.capability_library import CapabilityLibrary, CapabilityLibraryError, MAX_CONTEXT_BYTES


def organization(n=30):
    return {'organization_id': 'organization-current', 'state_version': 1,
            'agents': [{'id': f'current-{i}', 'role': 'Python developer', 'tools': {'shell': 'deny'}, 'manual_override': True} for i in range(n)],
            'functional_subteams': [{'id': 'audit', 'member_ids': ['current-3', 'current-9']}],
            'competency_gaps': [{'name': 'Python testing', 'agent_id': 'current-3'}]}


def item(i=0, kind='skill_instructions', **extras):
    return dict({'id': f'capability-{i}', 'kind': kind, 'name': f'Python testing {i}', 'content': 'Review evidence before acting.', 'tags': ['Python'],
                 'tool_needs': ['filesystem.read'], 'provenance': {'type': 'user_authored', 'evidence': 'User supplied instructions'}}, **extras)


class CapabilityLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'state.sqlite'
        self.lib = CapabilityLibrary(self.path, 'project-one')
        self.org = organization()
        self.lib.import_items([item()], 0, 'import')

    def tearDown(self):
        self.temp.cleanup()

    def test_no_arbitrary_500_limit_and_persistent_pagination(self):
        self.lib.import_items([item(i) for i in range(1, 1601)], 1, 'large')
        reopened = CapabilityLibrary(self.path, 'project-one')
        self.assertEqual(reopened.status()['item_count'], 1601)
        ids, offset = set(), 0
        while offset is not None:
            page = reopened.search('Python', offset=offset, limit=200)
            ids.update(x['id'] for x in page['items'])
            offset = page['next_offset']
        self.assertEqual(len(ids), 1601)
        self.assertEqual(reopened.search(query='%', limit=1)['total'], 0)
        self.assertEqual(CapabilityLibrary(self.path, 'other').status()['item_count'], 0)

    def test_all_30_ids_assignment_never_grants_or_installs(self):
        original = copy.deepcopy(self.org)
        plan = self.lib.preview(self.org, ['capability-0']*2, {'mode': 'all'})
        self.assertEqual(plan['changed_count'], 30)
        self.assertEqual(plan['installs'], [])
        result = self.lib.apply(self.org, plan, 'assign')
        self.assertEqual(self.org, original)
        self.assertEqual(result['revision'], 2)
        self.assertFalse(result['installed'])
        self.assertEqual(self.lib.status()['active_count'], 0)
        self.assertEqual(self.lib.apply(self.org, plan, 'assign'), result)
        repeat = self.lib.preview(self.org, ['capability-0'], {'mode': 'all'})
        self.assertEqual(repeat['changed_count'], 0)
        self.assertEqual(self.lib.manifest_page(limit=20)['next_offset'], 20)

    def test_stale_org_revision_and_tamper_rejected_atomically(self):
        plan = self.lib.preview(self.org, ['capability-0'], {'mode': 'all'})
        changed = copy.deepcopy(self.org); changed['state_version'] += 1
        with self.assertRaises(CapabilityLibraryError):
            self.lib.apply(changed, plan, 'stale')
        tampered = copy.deepcopy(plan); tampered['effects'][0]['after'] = True
        with self.assertRaises(CapabilityLibraryError):
            self.lib.apply(self.org, tampered, 'tamper')
        self.assertEqual(self.lib.status()['assigned_count'], 0)
        self.lib.import_items([item(1)], 1, 'another')
        with self.assertRaises(CapabilityLibraryError):
            self.lib.apply(self.org, plan, 'stale-library')

    def test_selection_validates_real_ids_and_subteams(self):
        for selection in ({'mode':'selected','agent_ids':['fake']}, {'mode':'subteam','subteam_id':'fake'}, {'mode':'selected','agent_ids':[]}):
            with self.assertRaises(CapabilityLibraryError):
                self.lib.preview(self.org, ['capability-0'], selection)
        plan = self.lib.preview(self.org, ['capability-0'], {'mode':'subteam','subteam_id':'audit'})
        self.assertEqual(plan['agent_ids'], ['current-3','current-9'])

    def test_atomic_import_idempotency_immutable_provenance(self):
        with self.assertRaises(CapabilityLibraryError):
            self.lib.import_items([item(1), item(0, content='changed')], 1, 'bad')
        self.assertEqual(self.lib.status()['item_count'], 1)
        self.assertEqual(self.lib.status()['revision'], 1)
        self.lib.import_items([item(1)], 1, 'good')
        with self.assertRaises(CapabilityLibraryError):
            self.lib.import_items([item(2)], 2, 'good')
        for bad in (item(4, provenance={}), item(4, provenance={'type':'unknown','evidence':'x'}), item(4, provenance={'type':'page_evidence','evidence':'x','url':'https://example.com/?token=x'}), item(4, content='Bearer abcdefghijklmnopqrstuvwxyz')):
            with self.assertRaises(CapabilityLibraryError):
                self.lib.import_items([bad], 2, 'bad-source')

    def test_activation_bounded_no_truncation_and_undo(self):
        plan = self.lib.preview(self.org, ['capability-0'], {'mode':'selected','agent_ids':['current-3']}, 'activate')
        result = self.lib.apply(self.org, plan, 'activate')
        self.assertEqual(self.lib.active_context(self.org, 'current-3', 3)['text'], '')
        context = self.lib.active_context(self.org, 'current-3')
        self.assertIn('Review evidence', context['text'])
        self.assertLessEqual(context['bytes'], 12000)
        self.assertFalse(context['training_weights_changed'])
        undone = self.lib.undo(self.org, result['revision'], result['revision'], 'undo')
        self.assertEqual(self.lib.status()['assigned_count'], 0)
        self.assertEqual(undone['revision'], 3)
        self.assertEqual(self.lib.undo(self.org, 2, 2, 'undo'), undone)
        with self.assertRaises(CapabilityLibraryError):
            self.lib.active_context(self.org, 'current-3', MAX_CONTEXT_BYTES+1)

    def test_plugin_and_connector_assigned_not_activated(self):
        self.lib.import_items([item(1,'plugin_package'),item(2,'connector')], 1, 'plugins')
        for i in (1,2):
            with self.assertRaises(CapabilityLibraryError):
                self.lib.preview(self.org,[f'capability-{i}'],{'mode':'all'},'activate')
        plan = self.lib.preview(self.org,['capability-1','capability-2'],{'mode':'all'})
        self.lib.apply(self.org,plan,'assign-plugins')
        self.assertEqual(self.lib.status()['assigned_count'],60)
        self.assertEqual(self.lib.status()['active_count'],0)

    def test_combined_preview_has_no_writes_and_atomic_apply(self):
        before = self.lib.status()
        raw = item(12); raw.pop('id')
        plan = self.lib.preview_import_items(self.org, [raw, item(13)], ['capability-0'], {'mode':'all'}, 1)
        self.assertEqual(self.lib.status(), before)
        self.assertEqual(plan['assignment_preview']['changed_count'], 90)
        result = self.lib.apply_import_preview(self.org, plan, 'combined')
        self.assertEqual(result['revision'], 3)
        self.assertEqual(self.lib.status()['item_count'], 3)
        self.assertEqual(self.lib.status()['assigned_count'], 90)
        self.assertEqual(self.lib.apply_import_preview(self.org, plan, 'combined'), result)

    def test_combined_failure_rolls_back_import(self):
        plan = self.lib.preview_import_items(self.org, [item(7)], [], {'mode':'all'}, 1)
        plan['assignment_preview']['effects'][0]['after'] = True
        from engine.capability_library import _hash
        unsigned = dict(plan); unsigned.pop('preview_hash')
        plan['preview_hash'] = _hash(unsigned)
        with self.assertRaises(CapabilityLibraryError):
            self.lib.apply_import_preview(self.org, plan, 'combined-bad')
        self.assertEqual(self.lib.status()['item_count'], 1)
        self.assertEqual(self.lib.status()['revision'], 1)
        self.assertEqual(self.lib.status()['assigned_count'], 0)

    def test_save_as_fork_isolated_content_assignments_and_replay(self):
        import uuid
        plan = self.lib.preview(self.org, ['capability-0'], {'mode':'all'})
        self.lib.apply(self.org, plan, 'assign-source')
        source_status = self.lib.status()
        target_id = uuid.uuid4().hex
        target = self.lib.fork(target_id, expected_revision=source_status['revision'])
        self.assertNotEqual(target.project_id, self.lib.project_id)
        self.assertEqual(target.status()['assigned_count'], 30)
        self.assertEqual(target.status()['revision'], source_status['revision']+1)
        self.assertEqual(target.audit_page()['items'][0]['action'], 'fork')
        target_plan = target.preview(self.org, ['capability-0'], {'mode':'all'}, 'unassign')
        target.apply(self.org, target_plan, 'assign-source')  # replay keys not copied
        target.import_items([item(123)], target.status()['revision'], 'target-import')
        self.assertEqual(target.status()['assigned_count'], 0)
        self.assertEqual(target.status()['item_count'], 2)
        self.assertEqual(self.lib.status(), source_status)
        self.assertEqual(self.lib.search()['total'], 1)
        self.assertEqual(self.lib.manifest_page()['total'], 30)
        with self.assertRaises(CapabilityLibraryError):
            self.lib.fork(target_id)
        with self.assertRaises(CapabilityLibraryError):
            self.lib.fork('../escape')
        with self.assertRaises(CapabilityLibraryError):
            self.lib.fork(uuid.uuid4().hex, expected_revision=0)

    def test_manifest_filters_before_pagination_and_counts(self):
        self.lib.apply(self.org, self.lib.preview(self.org, ['capability-0'], {'mode':'all'}), 'all')
        page = self.lib.manifest_page(limit=1, agent_ids=['current-3','current-9'])
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['next_offset'], 1)
        second = self.lib.manifest_page(offset=1, limit=1, agent_ids=['current-3','current-9'])
        self.assertNotEqual(page['items'][0]['agent_id'], second['items'][0]['agent_id'])
        self.assertIsNone(second['next_offset'])
        self.assertEqual(self.lib.manifest_page(agent_ids=[])['total'], 0)

    def test_recommendation_deterministic_advisory(self):
        a = self.lib.recommend(self.org, {'mode':'all'})
        self.assertEqual(a,self.lib.recommend(self.org,{'mode':'all'}))
        self.assertEqual(a['items'][0]['status'],'candidate_unverified')
        self.assertFalse(a['llm_advisory_contract']['may_install'])
        self.assertEqual(self.lib.status()['assigned_count'],0)

if __name__ == '__main__':
    unittest.main()
