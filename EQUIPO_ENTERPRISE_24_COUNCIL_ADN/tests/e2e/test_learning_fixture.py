"""Learning fixture schema checks only; no HTTP server or browser is started.

Passing these direct Python checks does not execute the authored UI cases.
Outbound sockets and child processes are explicitly refused throughout each test.
"""
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fixture_server import FixtureState, bridge, denied


class LearningFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orgdna-learning-fixture-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for target, name in [(bridge, 'ROOT'), (socket.socket, 'connect'),
                             (socket, 'create_connection'), (subprocess, 'Popen'), (subprocess, 'run')]:
            self.guards.enter_context(patch.object(target, name, self.root if target is bridge else denied))
        self.guards.enter_context(patch.dict(os.environ, {
            key: str(self.root) for key in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME')
        }))
        self.state = FixtureState(self.root)
        self.addCleanup(self.state.fixture_provider.release.set)
        self.ids = [agent['id'] for agent in self.state.organization['agents']]

    def tearDown(self):
        public = self.state.public()
        self.assertEqual(public['e2e_fixture']['live_provider_calls'], 0)
        self.assertEqual(public['e2e_fixture']['synthetic_design_calls'], 0)
        self.assertEqual(public['e2e_fixture']['synthetic_inventory_calls'], 0)
        self.assertEqual(public['e2e_fixture']['blocked_actions'], [])
        self.assertEqual(public['evaluations']['runs'], [])

    def profile_evidence(self):
        rows = []
        for agent in self.state.organization['agents']:
            self.assertTrue({'id', 'display_name', 'reports_to', 'tool_policy', 'skills'} <= agent.keys())
            self.assertIsInstance(agent['skills'], list)
            self.assertGreater(len(agent['skills']), 0)
            skills = []
            for skill in agent['skills']:
                self.assertTrue({'id', 'verified_level', 'evidence'} <= skill.keys())
                skills.append({key: skill[key] for key in ('id', 'verified_level', 'evidence')})
            rows.append({key: agent[key] for key in ('id', 'display_name', 'reports_to', 'tool_policy')} | {'skills': skills})
        return copy.deepcopy(rows)

    def save_project(self, name):
        self.state.execute('project-save', {'name': name})
        return copy.deepcopy(self.state.project)

    def load_project(self, project):
        return self.state.execute('project-load', {
            'project_id': project['id'], 'version_id': project['version_id'], 'confirmed': True
        })

    def save_capability(self, content='Original synthetic instructions.'):
        item = {'kind': 'skill_instructions', 'name': 'E2E immutable local instruction',
                'description': 'Locally authored capability for isolated acceptance checks.',
                'content': content, 'provenance': {'type': 'user_authored',
                    'evidence': 'Instrucciones redactadas y revisadas localmente. Referencias no consultadas: ninguna'}}
        revision = self.state.capabilities_hub.library.status()['revision']
        public = self.state.execute('capability-save', {
            'item': item, 'expected_revision': revision, 'idempotency_key': 'save-' + str(revision)
        })
        return next(row for row in public['capability_library']['page']['items'] if row['content'] == content)

    def preview(self, item, selection, expected_ids):
        before = self.state.public()
        result = self.state.execute('capability-preview', {
            'expected_state_version': self.state.organization['state_version'],
            'expected_revision': self.state.capabilities_hub.library.status()['revision'],
            'item_ids': [item['id']], 'candidate_ids': [], 'reference_ids': [],
            'catalog_identity': None, 'selection': selection, 'assignment_action': 'assign'
        })
        plan = result['capability_library']['plan']
        preview = plan['preview']['assignment_preview']
        self.assertEqual(preview['agent_ids'], expected_ids)
        self.assertEqual(preview['item_ids'], [item['id']])
        self.assertEqual(preview['effects'], [
            {'agent_id': aid, 'item_id': item['id'], 'before': None, 'after': False} for aid in expected_ids
        ])
        self.assertEqual(preview['changed_count'], len(expected_ids))
        self.assertEqual(preview['unchanged_count'], 0)
        self.assertEqual(preview['installs'], [])
        self.assertEqual(preview['permission_changes'], [])
        self.assertEqual(preview['tool_availability'], 'unverified')
        self.assertEqual(result['capability_library']['status']['revision'], before['capability_library']['status']['revision'])
        self.assertEqual(result['capability_library']['assignment_page']['items'], before['capability_library']['assignment_page']['items'])
        return plan

    def apply_plan(self, plan, item, expected_ids):
        result = self.state.execute('capability-apply', {
            'expected_state_version': self.state.organization['state_version'], 'plan_id': plan['id'],
            'preview_hash': plan['preview']['preview_hash'], 'idempotency_key': 'apply-' + plan['id'], 'confirmed': True
        })
        assignments = result['capability_library']['assignment_page']['items']
        self.assertIsNone(result['capability_library']['plan'])
        self.assertEqual(sorted(row['agent_id'] for row in assignments), sorted(expected_ids))
        for row in assignments:
            self.assertEqual(row['item_id'], item['id'])
            self.assertFalse(row['active'])
            self.assertTrue(row['assigned'])
            self.assertFalse(row['installed'])
            self.assertFalse(row['runtime_verified'])
        self.assertEqual(result['capability_library']['assignment_page']['permission_grants'], [])
        return copy.deepcopy(assignments)

    def test_seeded_profile_evidence_fields_survive_project_reload(self):
        before = self.profile_evidence()
        self.load_project(self.save_project('Profile evidence schema'))
        self.assertEqual(self.profile_evidence(), before)

    def test_skill_feedback_versions_and_historical_records_persist(self):
        profiles = self.profile_evidence()
        self.state.execute('skill-register', {
            'name': 'E2E versioned manual learning', 'description': 'Manual proposal only.',
            'owner_agent_id': self.ids[1], 'evidence': ['fixture://skill/registration', 'fixture://skill/source']
        })
        skill = copy.deepcopy(self.state.records['skill_registry'][0])
        self.assertEqual(skill['version'], 1)
        self.assertEqual(skill['status'], 'proposed')
        self.assertFalse(skill['installed'])
        self.assertFalse(skill['verified'])
        first = self.save_project('E2E manual learning versions')
        for index, aid in enumerate(self.ids[2:], 1):
            self.state.execute('skill-feedback', {
                'skill_id': skill['id'], 'agent_id': aid, 'failure': 'Synthetic failure ' + str(index),
                'proposed_change': 'Manual checklist revision ' + str(index),
                'retest_result': 'Manual retest only; no command executed.',
                'evidence': ['fixture://feedback/' + str(index)],
                'expected_state_version': self.state.organization['state_version']
            })
            current = self.state.records['skill_registry'][0]
            self.assertEqual(current['version'], index + 1)
            self.assertEqual(len(current['feedback']), index)
            self.assertFalse(current['installed'])
            self.assertFalse(current['verified'])
            self.assertEqual(current['status'], 'proposed')
            self.assertEqual(current['feedback'][-1]['origin'], 'manual_entry')
            self.assertFalse(current['feedback'][-1]['runtime_identity_verified'])
            self.assertFalse(current['feedback'][-1]['verified'])
        final_record = copy.deepcopy(self.state.records['skill_registry'][0])
        latest = self.save_project('E2E manual learning versions')
        self.assertEqual(first['id'], latest['id'])
        self.assertNotEqual(first['version_id'], latest['version_id'])
        self.load_project(first)
        self.assertEqual(self.state.records['skill_registry'], [skill])
        self.load_project(latest)
        self.assertEqual(self.state.records['skill_registry'], [final_record])
        self.assertEqual(self.profile_evidence(), profiles)

    def test_remediation_order_rejection_and_manual_fields_survive_reload(self):
        profiles = self.profile_evidence()
        self.state.execute('remediation-create', {
            'agent_id': self.ids[1], 'failure': 'E2E ordered remediation',
            'expected': 'Synthetic expected result A', 'actual': 'Synthetic observed result B',
            'evidence': ['fixture://remediation/observed']
        })
        record = copy.deepcopy(self.state.records['remediation_records'][0])
        version = self.state.organization['state_version']
        with self.assertRaisesRegex(ValueError, 'transición requiere avanzar'):
            self.state.execute('remediation-update', {
                'remediation_id': record['id'], 'status': 'testing', 'note': 'Attempt to skip the proposal',
                'evidence': ['fixture://remediation/skip']
            })
        self.assertEqual(self.state.records['remediation_records'], [record])
        self.assertEqual(self.state.organization['state_version'], version)
        for status in ('proposed', 'testing'):
            self.state.execute('remediation-update', {
                'remediation_id': record['id'], 'status': status, 'note': 'Manual declaration ' + status,
                'evidence': ['fixture://remediation/' + status]
            })
        result = copy.deepcopy(self.state.records['remediation_records'][0])
        self.assertEqual(result['status'], 'testing')
        self.assertEqual([event['status'] for event in result['events']], ['proposed', 'testing'])
        self.assertEqual(result['evidence'], ['fixture://remediation/observed', 'fixture://remediation/proposed', 'fixture://remediation/testing'])
        for event in result['events']:
            self.assertEqual(event['origin'], 'manual_entry')
            self.assertIsNone(event['reviewer_id'])
        self.assertFalse(result['tests_executed_by_app'])
        self.assertFalse(result['effectiveness_verified'])
        self.load_project(self.save_project('E2E remediation declarations'))
        self.assertEqual(self.state.records['remediation_records'], [result])
        self.assertEqual(self.profile_evidence(), profiles)

    def test_selected_capability_effects_discard_apply_and_persistence(self):
        item = self.save_capability()
        ids = [self.ids[1], self.ids[3]]
        selection = {'mode': 'selected', 'agent_ids': ids, 'subteam_ids': []}
        before = self.state.public()
        self.preview(item, selection, ids)
        self.state.execute('capability-discard', {})
        self.assertIsNone(self.state.capabilities_hub.plan)
        self.assertEqual(self.state.public()['capability_library']['assignment_page']['items'], [])
        self.assertEqual(self.state.capabilities_hub.library.status()['revision'], before['capability_library']['status']['revision'])
        assignments = self.apply_plan(self.preview(item, selection, ids), item, ids)
        restored = self.load_project(self.save_project('E2E selected assignments'))
        self.assertEqual(restored['capability_library']['assignment_page']['items'], assignments)
        self.assertEqual(restored['capability_library']['status']['active_count'], 0)

    def test_subteam_preview_deduplicates_union_from_real_subteam_actions(self):
        teams = []
        for index, members in enumerate([self.ids[:2], self.ids[1:3]]):
            result = self.state.execute('subteam-save', {
                'name': 'E2E overlapping team ' + str(index), 'type': 'consulting', 'member_ids': members,
                'facilitator_id': members[0], 'scope': 'Synthetic overlapping-member target checks only.',
                'expected_state_version': self.state.organization['state_version']
            })
            teams.append(result['subteams'][-1])
        agents = copy.deepcopy(self.state.organization['agents'])
        item = self.save_capability()
        selection = {'mode': 'subteams', 'agent_ids': [], 'subteam_ids': [team['id'] for team in teams]}
        plan = self.preview(item, selection, self.ids[:3])
        self.assertEqual(plan['preview']['assignment_preview']['selection'], {'mode': 'selected', 'agent_ids': self.ids[:3]})
        self.apply_plan(plan, item, self.ids[:3])
        self.assertEqual(self.state.capabilities_hub.library.status()['assigned_count'], 3)
        self.assertEqual(self.state.capabilities_hub.library.status()['assigned_agent_count'], 3)
        self.assertEqual(self.state.organization['agents'], agents)

    def test_edited_capability_is_a_new_immutable_copy_without_automatic_assignment(self):
        original = self.save_capability()
        plan = self.preview(original, {'mode': 'selected', 'agent_ids': [self.ids[1]], 'subteam_ids': []}, [self.ids[1]])
        assignments = self.apply_plan(plan, original, [self.ids[1]])
        revised = self.save_capability('Revised synthetic instructions with an explicit evidence checklist.')
        self.assertNotEqual(revised['id'], original['id'])
        self.assertNotEqual(revised['content_hash'], original['content_hash'])
        items = self.state.public()['capability_library']['page']['items']
        self.assertEqual(len(items), 2)
        self.assertEqual(next(row for row in items if row['id'] == original['id']), original)
        for item in items:
            self.assertFalse(item['installed'])
            self.assertFalse(item['runtime_verified'])
            self.assertFalse(item['permission_grant'])
        self.assertEqual(self.state.public()['capability_library']['assignment_page']['items'], assignments)
        self.assertEqual(self.state.capabilities_hub.library.status()['active_count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
