"""V8 offline model gate and durable, typed per-request audit regression tests."""
import copy
import json
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from engine import org_design, providers
from engine.bridge import BridgeState, BridgeError
from engine.generation_pipeline import safe_request_receipts, usage_summary
from tests_bridge import NullStore
from tests_generation_pipeline import GenerationPipelineTests
from tests_org_design import Fixture, fixture_summary


class TypedReceiptsTests(unittest.TestCase):
    def test_untrusted_values_are_typed_and_never_copied(self):
        for malformed_status in ([], {}, True, 9, 'REMOTE_SECRET'):
            raw = {'index': 1, 'status': malformed_status, 'usage': {'prompt_tokens': 0,
                'completion_tokens': True, 'total_tokens': 'PRIVATE'}, 'latency_ms': -1,
                'payload_sha256': 'a' * 64, 'http_status': True, 'error_code': ['SECRET'],
                'endpoint': 'https://private.invalid/?key=SECRET', 'headers': {'Authorization': 'SECRET'},
                'body': 'PRIVATE_BODY', 'provider': 'PRIVATE', 'model': 'SECRET'}
            rows = safe_request_receipts([raw], 'deepseek-official', 'fixture-model')
            row = rows[0]
            self.assertEqual(row['usage'], {'prompt_tokens': 0, 'completion_tokens': None, 'total_tokens': None})
            self.assertEqual(row['status'], 'billing_outcome_unknown')
            self.assertIsNone(row['http_status'])
            self.assertIsNone(row['error_code'])
            self.assertIsNone(row['latency_ms'])
            self.assertNotIn('SECRET', json.dumps(rows))
            self.assertNotIn('PRIVATE', json.dumps(rows))
            self.assertNotIn('endpoint', row)

    def test_usage_never_converts_unknown_to_zero(self):
        def receipt(index, usage):
            return safe_request_receipts([{'index': index, 'usage': usage}], 'deepseek', 'fixture')[0]
        zero = receipt(1, {key: 0 for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
        absent = receipt(2, {})
        self.assertEqual(usage_summary([zero], 1)['total_tokens'], 0)
        combined = usage_summary([zero, absent], 2)
        self.assertIsNone(combined['total_tokens'])
        self.assertEqual((combined['known_requests'], combined['unknown_requests']), (1, 1))
        self.assertIsNone(usage_summary([], 0)['total_tokens'])
        self.assertEqual(usage_summary([], None, True)['unknown_requests'], 1)


class ModelGateV8(unittest.TestCase):
    setUp = GenerationPipelineTests.setUp
    tearDown = GenerationPipelineTests.tearDown

    def test_manual_id_cannot_bypass_unconsulted_catalog(self):
        self.state.models = []
        for model in ('DeepSeek-V41-Flash', 'deepseek-flash'):
            with self.assertRaisesRegex(BridgeError, 'ID elegido para la API'):
                self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4()), 'config': {'model': model}})
        self.assertEqual(self.provider.design_calls, 0)
        self.assertEqual(self.provider.inventory_calls, 0)
        self.assertIsNone(self.state.pending_consent)

    def test_dsh_alias_or_negative_runtime_row_does_not_verify_api(self):
        self.state.models = [{'provider': 'deepseek-official', 'model': 'fixture-model',
            'source': 'live_api', 'available': True, 'catalog_scope': 'dsh_runtime'}]
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(self.state.config)
        self.state.models.append({'provider': 'deepseek-official', 'model': 'fixture-model',
            'source': 'live_api', 'available': True, 'catalog_scope': 'provider_api'})
        self.state.models[0]['available'] = False
        self.assertEqual(self.state.validate_api_model_choice(self.state.config)['status'], 'catalog_verified')

    def test_zai_documented_manual_id_requires_explicit_ack_and_no_models_endpoint(self):
        config = dict(self.state.config, provider='zai-official', model='glm-5.3')
        result = providers.discover_models('zai', 'SYNTHETIC_ONLY', transport=lambda *a: self.fail('Z.AI must not GET undocumented /models'))
        self.state.models = [dict(row, provider='zai-official', model=row['id'], available=None) for row in result['models']]
        with self.assertRaisesRegex(BridgeError, 'Confirma explícitamente'):
            self.state.validate_api_model_choice(config)
        verified = self.state.validate_api_model_choice(config, manual_confirmed=True)
        self.assertEqual(verified['status'], 'manual_documented')
        self.assertFalse(verified['account_verified'])
        self.assertFalse(verified['capabilities_verified'])
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(dict(config, model='INVENTED'), manual_confirmed=True)

    def test_manual_or_saved_references_never_verify_discovery_provider(self):
        for source in ('official_docs_snapshot', 'saved_project_reference', 'manual_not_verified'):
            self.state.models = [{'provider': 'deepseek-official', 'model': 'fixture-model', 'source': source, 'available': None}]
            with self.assertRaises(BridgeError):
                self.state.validate_api_model_choice(self.state.config, manual_confirmed=True)

    def test_catalog_from_another_key_or_alias_account_cannot_verify_current_account(self):
        self.state.execute('credentials', {'provider': 'deepseek-official', 'api_key': 'OTHER_SYNTHETIC_ACCOUNT'})
        self.assertIsNone(self.state.public()['models'][0]['available'])
        self.assertEqual(self.state.public()['models'][0]['status'], 'ACCOUNT_RECHECK_REQUIRED')
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(self.state.config)
        self.state.credentials['deepseek'] = 'DIFFERENT_SYNTHETIC_ACCOUNT'
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(dict(self.state.config, provider='deepseek'))

    def test_forgetting_credentials_cannot_reuse_catalog(self):
        self.state.execute('forget-credentials', {})
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(self.state.config)

    def test_two_alias_accounts_cannot_mix_models_or_limits(self):
        def catalog(model, limit):
            return {'source': 'live_api', 'models': [{'id': model, 'source': 'live_api',
                'availability_verified': True, 'max_output_tokens': limit}], 'verified_at': 'FIXTURE_ONLY'}
        with patch.object(self.provider, 'discover_models', return_value=catalog('only-A', 32768), create=True):
            self.state.execute('discover-models', {'confirmed': True})
        self.state.credentials['deepseek'] = 'ACCOUNT_B_SYNTHETIC'
        self.state.execute('config', {'config': {'provider': 'deepseek', 'model': 'only-B'}})
        with patch.object(self.provider, 'discover_models', return_value=catalog('only-B', 8192), create=True):
            self.state.execute('discover-models', {'confirmed': True})
        self.assertEqual(self.state.api_model_metadata(self.state.config)['max_output_tokens'], 8192)
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(dict(self.state.config, model='only-A'))
        self.assertIsNone(self.state.api_model_metadata(dict(self.state.config, model='only-A')))

    def test_verifying_one_model_does_not_rebind_other_old_models(self):
        old = dict(self.state.models[0], model='old-account-only')
        self.state.models.append(old)
        self.state._record_model_account(dict(self.state.config, model='old-account-only'))
        self.state.execute('credentials', {'provider': 'deepseek-official', 'api_key': 'ACCOUNT_B_SYNTHETIC'})
        self.state._record_model_account(self.state.config)
        self.state.validate_api_model_choice(self.state.config)
        with self.assertRaises(BridgeError):
            self.state.validate_api_model_choice(dict(self.state.config, model='old-account-only'))


class ReceiptPipelineV8(unittest.TestCase):
    setUp = GenerationPipelineTests.setUp
    tearDown = GenerationPipelineTests.tearDown
    wait_for = GenerationPipelineTests.wait_for
    plan = GenerationPipelineTests.plan
    approval = GenerationPipelineTests.approval

    def test_provider_alias_preserves_reported_model_limits(self):
        self.state.models[0].update(max_output_tokens=8192, context_window=131072)
        self.state.credentials['deepseek'] = self.secret
        self.plan(config={'provider': 'deepseek'}, profiles_per_request=2, max_output_tokens=32768)
        self.assertEqual(self.state.pending_consent['max_output_tokens'], 8192)
        self.assertEqual(self.state.pending_consent['model_limits']['context_window'], 131072)

    def test_account_changed_after_plan_requires_new_plan_without_paid_send(self):
        self.plan()
        approval = self.approval()
        self.state.execute('credentials', {'provider': 'deepseek-official', 'api_key': 'NEW_SYNTHETIC_ACCOUNT'})
        with self.assertRaisesRegex(BridgeError, 'cuenta del proveedor cambió'):
            self.state.execute('generation-confirm', approval)
        self.assertEqual(self.provider.design_calls, 0)
        self.assertFalse(self.state.generation.public().get('confirmation_consumed', False))
        serialized = json.dumps(self.state.public()) + json.dumps(self.state.project_snapshot())
        self.assertNotIn('credential_stamp', serialized)
        self.assertNotIn('account_stamp', serialized)

    def execute_fixture(self, fixture, **options):
        self.state.repo_inventory = fixture_summary()
        self.plan(**options)
        def design(*args, **kwargs):
            return org_design.design_with_llm(*args, transport=fixture, **kwargs)
        with patch.object(self.provider, 'design_with_llm', side_effect=design):
            self.state.execute('generation-confirm', self.approval())
            job = self.wait_for('completed', 'failed')
        return job

    def wait_receipts(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            job = self.state.generation.public()
            if not job.get('receipts_pending'):
                return job
            time.sleep(.01)
        self.fail('Late receipt did not settle')

    def reload(self):
        self.state.execute('project-save', {'name': 'Offline V8 receipts'})
        other = BridgeState(credential_store=NullStore(), provider_module=self.provider, project_store=self.state.project_store)
        other.execute('project-load', {'project_id': self.state.project['id']})
        self.assertIsNone(other.pending_consent)
        self.assertIsNone(other.generation._active())
        self.assertEqual(other.generation._contexts, {})
        return other

    def test_success_receipts_survive_save_load_and_diagnostic(self):
        job = self.execute_fixture(Fixture(), profiles_per_request=2)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(len(job['request_receipts']), 2)
        self.assertEqual(job['usage_summary'], {'prompt_tokens': 1000, 'completion_tokens': 2000,
            'total_tokens': 3000, 'known_requests': 2, 'unknown_requests': 0})
        self.assertTrue(all(row['status'] == 'validated' and type(row['latency_ms']) is int for row in job['request_receipts']))
        other = self.reload()
        report = other.generation_diagnostic()
        self.assertEqual(report['request_receipts'], job['request_receipts'])
        self.assertEqual(report['usage_summary'], job['usage_summary'])
        self.assertNotIn(self.secret, json.dumps(report))
        self.assertNotIn('endpoint', json.dumps(report))
        self.assertTrue(other.generation.public()['restored_from_project'])

    def test_invalid_schema_retains_actual_usage_and_failure_code(self):
        fixture = Fixture(mutate=lambda value, response, index: value['profile_specs'][0].pop('cv'))
        job = self.execute_fixture(fixture, profiles_per_request=2)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(fixture.calls), 1)
        row = job['request_receipts'][0]
        self.assertEqual(row['usage']['total_tokens'], 1500)
        self.assertEqual(row['error_code'], 'schema_fields')
        self.assertEqual(row['status'], 'response_received_not_yet_validated')
        self.assertEqual(self.reload().generation.public()['request_receipts'], job['request_receipts'])

    def test_http_failure_retains_safe_metadata_without_unknown_body_or_retry(self):
        calls = []
        def fail(*args):
            calls.append(1)
            return 400, {}, b'{"error":{"code":"model_not_found","message":"PRIVATE_RAW_BODY"}}'
        job = self.execute_fixture(fail)
        row = job['request_receipts'][0]
        self.assertEqual((row['http_status'], row['error_code']), (400, 'model_not_found'))
        self.assertIsNone(row['usage']['total_tokens'])
        self.assertEqual(job['usage_summary']['unknown_requests'], 1)
        self.assertNotIn('PRIVATE_RAW_BODY', json.dumps(self.state.public()))
        self.state.execute('generation-confirm', {'job_id': job['job_id']})
        self.assertEqual(len(calls), 1)

    def test_second_request_timeout_keeps_first_usage_and_unknown_aggregate(self):
        fixture = Fixture(fail_at=2)
        job = self.execute_fixture(fixture, profiles_per_request=2)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(job['request_receipts']), 2)
        self.assertEqual(job['request_receipts'][0]['usage']['total_tokens'], 1500)
        self.assertIsNone(job['request_receipts'][1]['usage']['total_tokens'])
        self.assertEqual((job['usage_summary']['known_requests'], job['usage_summary']['unknown_requests']), (1, 1))
        self.assertIsNone(job['usage_summary']['total_tokens'])
        self.assertEqual(len(fixture.calls), 2)

    def test_cancel_during_transport_keeps_late_usage_without_applying_design(self):
        entered, release = threading.Event(), threading.Event()
        fixture = Fixture()
        def transport(*args):
            entered.set()
            release.wait(5)
            return fixture(*args)
        self.addCleanup(release.set)
        self.state.repo_inventory = fixture_summary()
        self.plan(profiles_per_request=2)
        def design(*args, **kwargs):
            return org_design.design_with_llm(*args, transport=transport, **kwargs)
        with patch.object(self.provider, 'design_with_llm', side_effect=design):
            self.state.execute('generation-confirm', self.approval())
            self.assertTrue(entered.wait(3))
            before = copy.deepcopy(self.state.organization)
            job_id = self.state.generation.current_id
            self.state.execute('generation-cancel', {'job_id': job_id})
            self.assertTrue(self.state.generation.public()['receipts_pending'])
            release.set()
            job = self.wait_receipts()
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(len(fixture.calls), 1)
        self.assertEqual(job['request_receipts'][0]['usage']['total_tokens'], 1500)
        self.assertEqual(self.state.organization, before)
        self.assertEqual(self.reload().generation.public()['request_receipts'], job['request_receipts'])

    def test_cancel_before_worker_starts_does_not_leave_receipt_polling_forever(self):
        self.plan()
        with patch('engine.generation_pipeline.threading.Thread') as thread:
            self.state.execute('generation-confirm', self.approval())
            thread.return_value.start.assert_called_once()
        job_id = self.state.generation.current_id
        self.state.execute('generation-cancel', {'job_id': job_id})
        self.state.generation._run(job_id, self.secret)
        job = self.state.generation.public()
        self.assertFalse(job['receipts_pending'])
        self.assertFalse(job['potentially_billed'])
        self.assertEqual(job['sent_requests'], 0)
        self.assertEqual(self.provider.design_calls, 0)

    def test_old_project_without_generation_history_still_loads(self):
        self.state.execute('generate', {})
        snapshot = self.state.project_snapshot()
        snapshot.pop('generation_history')
        metadata = self.state.project_store.save(snapshot, 'V7 project')
        self.state.execute('project-load', {'project_id': metadata['project_id'], 'confirmed': True})
        self.assertIsNone(self.state.generation.public())


del GenerationPipelineTests
if __name__ == '__main__':
    unittest.main()
