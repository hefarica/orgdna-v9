"""Offline API ID vs DSH route tests; no live provider or runtime."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch
from engine import core
from engine.bridge import BridgeError
from tests_generation_pipeline import GenerationPipelineTests


class ModelCatalogScopes(unittest.TestCase):
    setUp = GenerationPipelineTests.setUp
    tearDown = GenerationPipelineTests.tearDown
    wait_for = GenerationPipelineTests.wait_for
    plan = GenerationPipelineTests.plan
    approval = GenerationPipelineTests.approval
    complete = GenerationPipelineTests.complete

    def catalog(self):
        return {'models': [{'id': 'deepseek-flash', 'name': 'DeepSeek-V4.1-Flash', 'source': 'live_api', 'availability_verified': True}], 'source': 'live_api', 'verified_at': 'FIXTURE'}

    def discover(self):
        with patch.object(self.provider, 'discover_models', return_value=self.catalog(), create=True):
            self.state.execute('discover-models', {'confirmed': True})

    def test_all_24_legacy_aliases_recover_exports_without_renaming(self):
        self.state.execute('config', {'config': {'agent_count': 24, 'council_concurrency': 24, 'model': 'DeepSeek-V41-Flash'}})
        self.state.execute('generate', {})
        before = [(a['id'], a['name'], a['provider'], a['model']) for a in self.state.organization['agents']]
        # Reproduce pre-fix API absence incorrectly applied to runtime routes.
        self.state.organization = core.refresh_model_catalog(self.state.organization, [{'provider': 'deepseek-official', 'model': 'deepseek-flash', 'available': True}])
        self.assertTrue(all(a['model_status'] == 'unavailable' for a in self.state.organization['agents']))
        self.discover()
        self.assertEqual(before, [(a['id'], a['name'], a['provider'], a['model']) for a in self.state.organization['agents']])
        self.assertTrue(all(a['model_status'] == 'unverified' and a['model_verification']['runtime_status'] == 'UNKNOWN' for a in self.state.organization['agents']))
        for filename in ('definitions.json', 'implementation.json', 'council.json'):
            payload = json.loads(self.state.download(filename))
            self.assertEqual(before, [(a['id'], a['name'], a['provider'], a['model']) for a in payload['agents']])
        self.assertTrue(self.state.download('package.zip').startswith(b'PK'))
        self.assertEqual(self.provider.design_calls, 0)

    def test_api_display_name_or_alias_rejected_even_if_manual_preference_exists(self):
        self.discover()
        for bad in ('DeepSeek-V4.1-Flash', 'DeepSeek-V41-Flash'):
            self.state.merge_preferences([{'provider': 'deepseek-official', 'model': bad}])
            with self.assertRaisesRegex(BridgeError, 'ID elegido para la API'):
                self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4()), 'config': {'model': bad}, 'new_project': True})
        self.assertEqual(self.provider.inventory_calls, 0)
        self.assertEqual(self.provider.design_calls, 0)
        self.assertIsNone(self.state.generation.public())

    def test_exact_api_id_survives_config_consent_request_and_export(self):
        self.discover()
        with patch.object(self.provider, 'design_with_llm', wraps=self.provider.design_with_llm) as call:
            self.complete(config={'model': 'deepseek-flash'})
        self.assertEqual(self.state.config['model'], 'deepseek-flash')
        self.assertEqual(call.call_args.args[1:3], ('deepseek', 'deepseek-flash'))
        exported = json.loads(self.state.download('definitions.json'))
        self.assertTrue(all(a['provider'] == 'deepseek-official' and a['model'] == 'deepseek-flash' for a in exported['agents']))

    def test_provider_alias_does_not_bypass_exact_api_catalog(self):
        self.discover()
        self.state.credentials['deepseek'] = self.secret
        with self.assertRaises(BridgeError):
            self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4()), 'new_project': True, 'config': {'provider': 'deepseek', 'model': 'DeepSeek-V41-Flash'}})
        self.state.validate_api_model_choice(dict(self.state.config, provider='deepseek', model='deepseek-flash'))

    def test_explicit_unavailable_runtime_remains_blocked(self):
        self.state.execute('generate', {})
        self.state.organization = core.refresh_model_catalog(self.state.organization, [{'provider': 'deepseek-official', 'model': 'fixture-model', 'available': False, 'catalog_scope': 'dsh_runtime'}])
        self.discover()
        self.assertTrue(all(a['model_status'] == 'unavailable' for a in self.state.organization['agents']))
        with self.assertRaises(ValueError):
            self.state.download('definitions.json')
        self.state.execute('project-save', {'name': 'Blocked runtime fixture'})
        project = copy.deepcopy(self.state.project)
        self.state.execute('project-load', {'project_id': project['id'], 'version_id': project['version_id'], 'confirmed': True})
        self.assertTrue(all(a['model_status'] == 'unavailable' for a in self.state.organization['agents']))
        with self.assertRaises(ValueError):
            self.state.download('definitions.json')

    def test_v4_saved_unavailable_alias_recovers_without_api_or_regeneration(self):
        self.state.execute('config', {'config': {'agent_count': 24, 'council_concurrency': 24, 'model': 'DeepSeek-V41-Flash'}})
        self.state.execute('generate', {})
        first = self.state.organization['agents'][0]
        self.state.execute('edit-organization', {'edits': {'expected_state_version': self.state.organization['state_version'], 'agents': [{'id': first['id'], 'display_name': 'Edición manual preservada'}]}})
        self.state.organization = core.refresh_model_catalog(self.state.organization, [{'provider': 'deepseek-official', 'model': 'deepseek-flash', 'available': True}])
        # Older saved metadata has no scope/runtime_status.
        for a in self.state.organization['agents']:
            a['model_verification'].pop('catalog_scope', None)
            a['model_verification'].pop('runtime_status', None)
        before = [(a['id'], a['name'], a['display_name'], a['provider'], a['model']) for a in self.state.organization['agents']]
        self.state.execute('project-save', {'name': 'Saved V4 failure fixture'})
        project = copy.deepcopy(self.state.project)
        with patch.object(self.provider, 'analyze_repository', side_effect=AssertionError('No network allowed')):
            self.state.execute('project-load', {'project_id': project['id'], 'version_id': project['version_id'], 'confirmed': True})
            self.assertEqual(before, [(a['id'], a['name'], a['display_name'], a['provider'], a['model']) for a in self.state.organization['agents']])
            self.assertTrue(self.state.has_manual_edits)
            for filename in ('definitions.json', 'implementation.json', 'council.json'):
                self.assertEqual(len(json.loads(self.state.download(filename))['agents']), 24)
            self.assertTrue(self.state.download('package.zip').startswith(b'PK'))
        self.assertEqual(self.provider.design_calls, 0)

    def test_saved_manual_alias_remains_unverified_after_load(self):
        self.state.execute('config', {'config': {'model': 'DeepSeek-V41-Flash'}})
        self.state.execute('generate', {})
        self.discover()
        before = [(a['id'], a['model']) for a in self.state.organization['agents']]
        self.state.execute('project-save', {'name': 'Alias fixture'})
        project = copy.deepcopy(self.state.project)
        self.state.execute('project-load', {'project_id': project['id'], 'version_id': project['version_id'], 'confirmed': True})
        self.assertEqual(before, [(a['id'], a['model']) for a in self.state.organization['agents']])
        self.assertTrue(all(a['model_status'] == 'unverified' for a in self.state.organization['agents']))
        self.assertIsNotNone(self.state.export_artifacts())


del GenerationPipelineTests
if __name__ == '__main__':
    unittest.main()
