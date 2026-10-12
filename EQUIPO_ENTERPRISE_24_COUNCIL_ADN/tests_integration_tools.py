"""Backend addon/catalog boundaries with synthetic, offline helper modules."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from engine.bridge import BridgeState, BridgeError
from engine.project_store import ProjectStore
from tests_bridge import NullStore


class MockShop:
    def __init__(self): self.fetches = 0
    def fetch_catalog(self, source='github_pages'):
        self.fetches += 1
        return {'source': source, 'candidates': [self.candidate(i) for i in range(100)]}
    @staticmethod
    def candidate(i):
        return {'id': 'candidate-' + str(i), 'name': 'Synthetic Plugin ' + str(i),
                'version': '1.0.0', 'status': 'proposal', 'runtime_verified': False}
    def search_catalog(self, catalog, query='', capabilities=None, limit=30, offset=0, category=None, sort='source'):
        return {'results': copy.deepcopy(catalog['candidates'][offset:offset+limit]), 'total': len(catalog['candidates']), 'query': query}
    def capability_wishlist(self, organization, catalog, tool_catalog=None, limit=20):
        return {'gaps': [], 'suggestions': [], 'runtime_verified': False}
    def inspect_candidate(self, catalog, candidate_id):
        candidate = next(copy.deepcopy(c) for c in catalog['candidates'] if c['id'] == candidate_id)
        candidate['status'] = 'inspected'
        return candidate
    def create_installation_plan(self, candidate, profile='orgdna-isolated', runtime=None, request_id=None):
        if candidate['status'] != 'inspected': raise ValueError('Inspect first')
        return {'plan_id': 'plan-' + candidate['id'], 'candidate': candidate,
                'profile': profile, 'status': 'PLAN_ONLY', 'runtime_verified': False,
                'approvals_required': ['Review exact version and permissions']}
    def transition_candidate(self, candidate, status, evidence=None):
        candidate['status'] = status
        candidate['evidence'] = evidence
        candidate['runtime_verified'] = False
        return candidate


def mock_addon(org, teams_config=None, capabilities=None, skillhub_manifest=None):
    assert set(a['id'] for a in org['agents']) == set(a['id'] for a in teams_config['agents'])
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('fixture.txt', 'Synthetic Cordis package only, no runtime code.')
    return {'manifest': {'version': '0.0.0-fixture', 'activation': {'enabled': False}},
            'dry_run': {'status': 'BLOCKED_RUNTIME_NOT_VERIFIED', 'same_roster': True,
                        'member_count': len(org['agents'])},
            'filename': 'orgdna-cordis-fixture.zip', 'zip_bytes': payload.getvalue(), 'files': {}}


class IntegrationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = BridgeState(credential_store=NullStore(), project_store=ProjectStore(Path(self.temp.name) / 'projects'))
        self.state.execute('config', {'config': {'agent_count': 3, 'council_concurrency': 3}})
        self.state.execute('generate', {})
        self.shop = MockShop()
        self.module_patch = patch('engine.cordis_extension.build_cordis_addon', side_effect=mock_addon)
        self.module_patch.start()
        self.factory_patch = patch.object(self.state.integrations, '_shop', return_value=self.shop)
        self.factory_patch.start()

    def tearDown(self):
        self.factory_patch.stop(); self.module_patch.stop(); self.temp.cleanup()

    def prepare(self):
        return self.state.execute('cordis-prepare', {'expected_state_version': self.state.organization['state_version']})

    def test_addon_preparation_returns_matching_roster_without_activating(self):
        state = self.prepare()
        addon = state['cordis_addon']
        self.assertEqual(addon['status'], 'ready')
        self.assertEqual(addon['dry_run']['member_count'], 3)
        self.assertFalse(addon['enabled']); self.assertFalse(addon['installed'])
        data = self.state.download('cordis-addon.zip')
        self.assertEqual(hashlib.sha256(data).hexdigest(), addon['artifact']['sha256'])
        self.assertEqual(self.state.download_filename('cordis-addon.zip'), addon['artifact']['filename'])

    def test_stale_addon_download_fails_without_reusing_old_ids(self):
        self.prepare()
        self.state.execute('config', {'config': {'repo_name': 'Changed organization'}})
        self.assertEqual(self.state.public()['cordis_addon']['status'], 'stale')
        with self.assertRaises(ValueError): self.state.download('cordis-addon.zip')

    def test_addon_rejects_other_team_and_secret_arguments(self):
        for extra in ({'teams_config': {}}, {'api_key': 'forbidden'}, {'enabled': True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.state.execute('cordis-prepare', {'expected_state_version': self.state.organization['state_version'], **extra})

    def test_catalog_is_not_returned_in_full_state_or_saved(self):
        self.state.execute('plugin-shop-refresh', {})
        public = self.state.public()['plugin_shop']
        self.assertNotIn('candidates', public['catalog'])
        self.assertEqual(public['catalog']['candidate_count'], 100)
        self.state.execute('plugin-shop-search', {'query': '', 'limit': 8})
        self.assertEqual(len(self.state.public()['plugin_shop']['search']['results']), 8)
        self.state.execute('project-save', {'name': 'Plugin preferences'})
        snapshot = self.state.project_store.load(self.state.project['id'])['snapshot']
        self.assertNotIn('catalog', snapshot['integrations'])
        self.assertNotIn('search', snapshot['integrations'])
        self.assertNotIn('inspected', snapshot['integrations'])

    def test_inspect_plan_and_operator_status_do_not_install(self):
        self.state.execute('plugin-shop-refresh', {})
        with self.assertRaises(ValueError):
            self.state.execute('plugin-shop-plan', {'candidate_id': 'candidate-1'})
        self.state.execute('plugin-shop-inspect', {'candidate_id': 'candidate-1'})
        self.state.execute('plugin-shop-plan', {'candidate_id': 'candidate-1'})
        self.state.execute('plugin-shop-status', {'candidate_id': 'candidate-1', 'status': 'active_reported', 'evidence': {'note': 'Synthetic operator report only'}})
        public = self.state.public()['plugin_shop']
        self.assertEqual(public['plans'][0]['status'], 'PLAN_ONLY')
        self.assertFalse(public['installation_performed'])
        self.assertFalse(public['reported_candidates']['candidate-1']['runtime_verified'])

    def test_reload_does_not_revive_cache_or_activation(self):
        self.prepare()
        self.state.execute('plugin-shop-refresh', {})
        self.state.execute('plugin-shop-inspect', {'candidate_id': 'candidate-1'})
        self.state.execute('plugin-shop-plan', {'candidate_id': 'candidate-1'})
        self.state.execute('project-save', {'name': 'Prepared integrations'})
        other = BridgeState(credential_store=NullStore(), project_store=self.state.project_store)
        other.execute('project-load', {'project_id': self.state.project['id']})
        self.assertEqual(other.public()['cordis_addon']['status'], 'unprepared')
        self.assertEqual(other.public()['plugin_shop']['status'], 'not_loaded')
        self.assertEqual(len(other.public()['plugin_shop']['plans']), 1)
        self.assertFalse(other.public()['plugin_shop']['plans'][0]['runtime_verified'])

    def test_real_catalog_upgrade_cannot_be_shadowed_by_old_operator_report(self):
        from engine import plugin_shop as module
        from tests_plugin_shop import catalog, npm_entry, inspected, manifest, Fixture, evidence
        old_catalog = catalog()
        old = inspected()
        self.state.integrations.catalog = old_catalog
        self.state.integrations.inspected[old['id']] = old
        with patch.object(self.state.integrations, '_shop', return_value=module):
            self.state.execute('plugin-shop-status', {'candidate_id': old['id'], 'status': 'approved_by_operator',
                                                      'evidence': evidence(old)})
            new_catalog = catalog([npm_entry(version='2.0.0')])
            with patch.object(module, 'fetch_catalog', return_value=new_catalog):
                self.state.execute('plugin-shop-refresh', {})
            current = new_catalog['candidates'][0]
            self.assertEqual(old['id'], current['id'])
            self.assertTrue(self.state.integrations.reported[old['id']]['stale_against_catalog'])
            self.state.execute('plugin-shop-plan', {'candidate_id': current['id']})
            plan = self.state.integrations.plans[-1]
            self.assertEqual(plan['pin']['version'], '2.0.0')
            self.assertEqual(plan['pin']['entry_sha256'], current['provenance']['entry_sha256'])
            self.assertIn('exact_manifest_not_inspected', plan['blockers'])

    def test_imported_report_cannot_supply_a_forged_install_spec(self):
        self.state.execute('plugin-shop-refresh', {})
        raw = self.state.integrations.saved()
        raw['reported_candidates']['candidate-1'] = {'id': 'candidate-1', 'version': '1.0.0',
            'status': 'active_reported', 'install_spec': 'untrusted-install-command', 'installed': True,
            'runtime_verified': True, 'inspection': {'manifest_inspected': True, 'active': True},
            'execution_available': True, 'native_action_performed': True, 'enabled': True}
        self.state.integrations.load_saved(raw)
        row = self.state.integrations.reported['candidate-1']
        for key in ('runtime_verified', 'installed', 'execution_available', 'native_action_performed', 'enabled'):
            self.assertFalse(row[key])
        self.assertFalse(row['inspection']['active'])
        self.state.execute('plugin-shop-refresh', {})
        candidate = self.state.integrations._candidate('candidate-1')
        self.assertNotIn('install_spec', candidate)
        self.assertEqual(candidate['status'], 'proposal')

    def test_persisted_activation_cannot_be_loaded(self):
        raw = self.state.integrations.saved()
        raw['settings']['cordis']['enabled'] = True
        with self.assertRaises(ValueError): self.state.integrations.load_saved(raw)


class MockConnection:
    def __init__(self):
        self.calls = []
        self.connected = False
    def cached_status(self):
        return {'status': 'CONNECTED' if self.connected else 'DISCONNECTED',
                'live_connection': self.connected, 'identity_verified': self.connected,
                'read_only': True, 'cached': True, 'capabilities': {}}
    def status(self):
        self.calls.append('refresh'); return self.cached_status()
    def connect(self, port, pairing_code):
        self.calls.append('connect'); self.connected = True; return self.cached_status()
    def disconnect(self):
        self.calls.append('disconnect'); self.connected = False; return self.cached_status()
    def read_profiles(self):
        self.calls.append('profiles'); return {'source': 'fixture_not_live', 'agents': [], 'squads': [], 'live_connection': True}
    def read_team(self, team_name=''):
        self.calls.append('team'); return {'source': 'fixture_not_live', 'teams': [], 'live_connection': True}
    def preview_import(self, document):
        self.calls.append('preview'); return {'format': document['format'], 'valid': True, 'fixture': True}
    def prepare_task_plan(self, plan):
        return {'status': 'BLOCKED_CAPABILITY', 'dispatch_supported': False}


class LocalConnectionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = BridgeState(credential_store=NullStore(), project_store=ProjectStore(Path(self.temp.name) / 'projects'))
        self.state.execute('config', {'config': {'agent_count': 3, 'council_concurrency': 3}})
        self.state.execute('generate', {})
        self.manager = MockConnection()
        self.state.integrations.dsh_manager = self.manager
        self.code = 'A' * 43
    def tearDown(self): self.temp.cleanup()
    def connect(self):
        return self.state.execute('dsh-connect', {'port': 42001, 'pairing_code': self.code, 'confirmed': True})
    def test_connect_is_explicit_and_state_poll_does_not_send_requests(self):
        with self.assertRaises(ValueError):
            self.state.execute('dsh-connect', {'port': 42001, 'pairing_code': self.code})
        self.assertFalse(self.manager.calls)
        self.connect()
        for _ in range(5): self.state.public()
        self.assertEqual(self.manager.calls, ['connect'])
        self.assertNotIn(self.code, json.dumps(self.state.public()))
        self.state.execute('dsh-status', {})
        self.assertEqual(self.manager.calls, ['connect', 'refresh'])
    def test_pairing_and_read_data_are_never_saved_in_project(self):
        self.connect()
        self.state.execute('dsh-read-profiles', {})
        self.state.execute('project-save', {'name': 'Connected fixture project'})
        snapshot = self.state.project_store.load(self.state.project['id'])['snapshot']
        self.assertNotIn('dsh_connection', snapshot)
        self.assertNotIn('dsh_profiles', json.dumps(snapshot))
        self.assertNotIn(self.code, json.dumps(snapshot))
        self.assertFalse(self.state.public()['dsh_connection']['runtime_write_supported'])
    def test_import_preview_becomes_stale_after_org_changes(self):
        self.connect()
        self.state.execute('dsh-preview-import', {'document_kind': 'definitions',
            'expected_state_version': self.state.organization['state_version']})
        self.assertIsNotNone(self.state.public()['dsh_connection']['import_preview'])
        self.state.execute('config', {'config': {'repo_name': 'Different project name'}})
        value = self.state.public()['dsh_connection']
        self.assertIsNone(value['import_preview'])
        self.assertTrue(value['import_preview_stale'])
    def test_dispatch_is_unavailable_even_after_pairing(self):
        self.connect()
        self.state.execute('dsh-prepare-task-plan', {'plan': {'goal': 'Synthetic read-only diagnostic'}})
        self.assertEqual(self.state.public()['dsh_connection']['task_plan']['status'], 'BLOCKED_CAPABILITY')
        with self.assertRaises(BridgeError):
            self.state.execute('dsh-submit-task-plan', {'confirmed': True})
        self.assertNotIn('dispatch', self.manager.calls)
    def test_disconnect_clears_read_snapshots(self):
        self.connect(); self.state.execute('dsh-read-profiles', {})
        self.state.execute('dsh-disconnect', {})
        value = self.state.public()['dsh_connection']
        self.assertFalse(value['status']['live_connection'])
        self.assertIsNone(value['profiles'])


if __name__ == '__main__': unittest.main()
