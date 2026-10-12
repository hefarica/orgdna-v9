"""Synthetic diagnostic failures; no provider network or paid inference."""
import json
import unittest
import uuid
from unittest.mock import patch
from engine.providers import ProviderError, HTTPFailure
from engine.bridge import BridgeError
from tests_generation_pipeline import GenerationPipelineTests


class GenerationDiagnostics(unittest.TestCase):
    setUp = GenerationPipelineTests.setUp
    tearDown = GenerationPipelineTests.tearDown
    wait_for = GenerationPipelineTests.wait_for

    def fail_inventory(self, exc):
        with patch.object(self.provider, 'analyze_repository', side_effect=exc):
            self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4()), 'new_project': True})
            job = self.wait_for('failed')
        self.assertEqual(self.provider.design_calls, 0)
        self.assertFalse(job['potentially_billed'])
        self.assertEqual(job['failed_stage'], 'inventory')
        receipt = self.state.public()['receipts'][-1]
        self.assertEqual(receipt['job_id'], job['job_id'])
        self.assertEqual(receipt['error'], job['error'])
        self.assertIn(job['error']['message'], receipt['message'])
        return job

    def test_known_repository_error_visible_and_correlated(self):
        job = self.fail_inventory(ProviderError('No se pudo resolver el endpoint.'))
        self.assertEqual(job['error']['message'], 'No se pudo resolver el endpoint.')
        self.assertEqual(job['error']['code'], 'repository_read_failed')
        self.assertEqual(job['error']['stage'], 'inventory')

    def test_http_error_has_safe_status_and_correct_source(self):
        exc = HTTPFailure(403)
        exc.args = ('RAW BODY https://secret.example/?token=unknown-secret',)
        job = self.fail_inventory(exc)
        self.assertEqual(job['error']['http_status'], 403)
        self.assertEqual(job['error']['code'], 'repository_http_error')
        self.assertIn('GitHub', job['error']['message'])
        self.assertNotIn('RAW BODY', json.dumps(self.state.public()))

    def test_unknown_provider_error_never_leaks_raw_text(self):
        self.fail_inventory(ProviderError('RAW BODY https://private.example/?token=unknown-secret ' + self.secret))
        serialized = json.dumps(self.state.public())
        for value in ('RAW BODY', 'private.example', 'unknown-secret', self.secret):
            self.assertNotIn(value, serialized)

    def test_repository_failure_preserves_only_allowlisted_adapter_stage_and_code(self):
        exc = ProviderError('Respuesta HTTP supera el límite de bytes.')
        exc.endpoint_stage, exc.code = 'tree_inventory', 'response_too_large'
        job = self.fail_inventory(exc)
        self.assertEqual(job['error']['source_stage'], 'tree_inventory')
        self.assertEqual(job['error']['adapter_code'], 'response_too_large')
        self.assertIn('no al límite de tokens', job['error']['reading_note'])

    def test_arbitrary_adapter_attributes_are_not_exposed(self):
        exc = ProviderError('Respuesta HTTP supera el límite de bytes.')
        exc.endpoint_stage = 'SECRET_ENDPOINT_https://private.example'
        exc.code = 'SECRET_ADAPTER_CODE'
        job = self.fail_inventory(exc)
        self.assertIsNone(job['error']['source_stage'])
        self.assertIsNone(job['error']['adapter_code'])
        self.assertNotIn('SECRET_', json.dumps(self.state.public()))

    def test_unknown_exception_never_leaks_raw_text(self):
        self.fail_inventory(RuntimeError('PRIVATE TRACE ' + self.secret))
        serialized = json.dumps(self.state.public())
        self.assertNotIn('PRIVATE TRACE', serialized)
        self.assertNotIn(self.secret, serialized)

    def test_bridge_validation_error_never_leaks_arbitrary_detail(self):
        self.fail_inventory(BridgeError('El ADN no superó validación: https://private.example/?token=untracked SECRET BODY'))
        serialized = json.dumps(self.state.public())
        self.assertNotIn('private.example', serialized)
        self.assertNotIn('SECRET BODY', serialized)

    def test_preparation_stage_preserved_without_inference(self):
        with patch.object(self.provider, 'prepare_design_consent', side_effect=ProviderError('No hay contenido revisable para analizar.')):
            self.state.execute('generation-plan', {'idempotency_key': str(uuid.uuid4()), 'new_project': True})
            job = self.wait_for('failed')
        self.assertEqual(job['error']['stage'], 'preparing_consent')
        self.assertEqual(job['error']['code'], 'generation_validation_failed')
        self.assertEqual(self.provider.design_calls, 0)
        self.assertIsNone(self.state.pending_consent)


del GenerationPipelineTests

if __name__ == '__main__':
    unittest.main()
