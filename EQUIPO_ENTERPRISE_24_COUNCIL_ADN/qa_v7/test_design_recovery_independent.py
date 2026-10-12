"""Snapshot recovery, replay/cancel safety, and byte-preserving export checks."""
import copy
import hashlib
import io
import json
import time
from unittest.mock import patch
import zipfile

from engine.bridge import BridgeError, BridgeState
from engine.project_store import ProjectStore
from tests_bridge import NullStore
from qa_v7.fixtures import DesignTransport, PRIVATE_MARKER, RAW_MARKER
from qa_v7.test_generation_failures_independent import PipelineCase


class DesignRecoveryIndependent(PipelineCase):
    def offline_baseline(self):
        self.state.execute('generate', {})
        self.state.public()  # materialize the available validated context
        names = ('definitions.json', 'implementation.json', 'council.json', 'export-manifest.json', 'package.zip')
        exports = {name: self.state.download(name) for name in names}
        return {'organization': copy.deepcopy(self.state.organization), 'config': copy.deepcopy(self.state.config),
                'records': copy.deepcopy(self.state.records), 'exports': exports,
                'integrations': self.state.integrations, 'launcher': self.state.dsh_launcher,
                'harness': self.state.dsh_harness, 'connection': self.state.dsh_harness.connection}

    def restore_body(self):
        recovery = self.state.public()['design_recovery']
        return {'confirmed': True, 'snapshot_id': recovery['snapshot_id'],
                'expected_config_version': recovery['expected_config_version']}

    def change_config(self):
        self.state.execute('config', {'config': {'repo_name': 'Pending next attempt', 'agent_count': 6,
                                                'council_concurrency': 6}})
        return copy.deepcopy(self.state.config)

    def test_restore_previous_design_and_exact_exports_after_failed_changed_config(self):
        prior = self.offline_baseline()
        draft = self.change_config()
        self.provider.transport = DesignTransport(fault=TimeoutError(RAW_MARKER + PRIVATE_MARKER))
        self.plan()
        self.state.execute('generation-confirm', self.approval())
        self.wait('failed')
        self.assertEqual(self.state.organization, prior['organization'])
        with self.assertRaises(BridgeError):
            self.state.download('definitions.json')
        result = self.state.public()['design_recovery']
        self.assertTrue(result['can_restore'])
        body = self.restore_body()
        self.state.execute('design-restore', body)
        version = self.state.config_version
        self.state.execute('design-restore', body)
        self.assertEqual(self.state.config_version, version, 'Repeat click is idempotent')
        self.assertFalse(self.state.generation_stale)
        self.assertEqual(self.state.config, prior['config'])
        self.assertEqual(self.state.organization, prior['organization'])
        self.assertEqual(self.state.public()['design_recovery']['draft_config'], draft)
        self.assertEqual(self.state.records, prior['records'])
        self.assertEqual(len(self.provider.transport.calls), 1)
        for name, expected in prior['exports'].items():
            with self.subTest(export=name):
                self.assertEqual(self.state.download(name), expected)
        for name in ('integrations', 'launcher', 'harness'):
            self.assertIs(getattr(self.state, {'launcher': 'dsh_launcher', 'harness': 'dsh_harness'}.get(name, name)), prior[name])
        self.assertIs(self.state.dsh_harness.connection, prior['connection'])
        self.assert_no_secrets()

    def test_restore_requires_exact_snapshot_version_and_approval(self):
        self.offline_baseline()
        self.change_config()
        body = self.restore_body()
        for mutation in ({'confirmed': False}, {'snapshot_id': 'wrong'}, {'expected_config_version': body['expected_config_version'] - 1}, {'expected_config_version': True}):
            with self.subTest(mutation=mutation), self.assertRaises(BridgeError):
                self.state.execute('design-restore', dict(body, **mutation))
        self.assertTrue(self.state.generation_stale)
        self.assertEqual(self.provider.design_calls, 0)

    def test_restore_blocked_during_review_and_running_then_allowed_after_cancel(self):
        prior = self.offline_baseline()
        self.change_config()
        self.plan(max_output_tokens=4224)
        with self.assertRaises(BridgeError):
            self.state.execute('design-restore', self.restore_body())
        self.provider.transport.release.clear()
        self.state.execute('generation-confirm', self.approval())
        self.assertTrue(self.provider.transport.entered.wait(3))
        with self.assertRaises(BridgeError):
            self.state.execute('design-restore', self.restore_body())
        self.state.execute('generation-cancel', {'job_id': self.state.generation.current_id})
        self.state.execute('design-restore', self.restore_body())
        self.provider.transport.release.set()
        time.sleep(.05)
        self.assertEqual(self.state.organization, prior['organization'])
        self.assertFalse(self.state.generation_stale)
        self.assertEqual(len(self.provider.transport.calls), 1)

    def test_restore_never_bypasses_invalid_existing_design(self):
        self.offline_baseline()
        self.change_config()
        self.state.organization['agents'][0]['id'] = 'not-a-valid-uuid'
        self.assertFalse(self.state.public()['design_recovery']['can_restore'])
        with self.assertRaises(BridgeError):
            self.state.execute('design-restore', self.restore_body())
        self.assertTrue(self.state.generation_stale)

    def test_recovery_cannot_unblock_explicit_unavailable_runtime(self):
        self.offline_baseline()
        self.change_config()
        agent = self.state.organization['agents'][0]
        agent['model_status'] = 'unavailable'
        agent['model_verification'].update(status='unavailable', runtime_status='UNAVAILABLE', runtime_verified=False)
        self.assertFalse(self.state.public()['design_recovery']['can_restore'])
        with self.assertRaises(BridgeError):
            self.state.execute('design-restore', self.restore_body())
        with self.assertRaises(BridgeError):
            self.state.download('definitions.json')

    def test_recovery_preserves_latest_manual_profile_and_uuid(self):
        self.offline_baseline()
        org = self.state.organization
        agent_id = org['agents'][0]['id']
        self.state.execute('edit-organization', {'edits': {'expected_state_version': org['state_version'],
            'agents': [{'id': agent_id, 'display_name': 'Nombre revisado manualmente', 'department': 'Gobierno manual'}]}})
        before = copy.deepcopy(self.state.organization)
        before_bytes = self.state.download('definitions.json')
        self.change_config()
        self.state.execute('design-restore', self.restore_body())
        self.assertEqual(self.state.organization, before)
        self.assertTrue(self.state.has_manual_edits)
        self.assertEqual(self.state.organization['agents'][0]['id'], agent_id)
        self.assertEqual(self.state.download('definitions.json'), before_bytes)
        self.assertEqual(self.provider.design_calls, 0)

    def test_saved_stale_design_retains_recovery_across_restart_without_consent(self):
        prior = self.offline_baseline()
        self.change_config()
        self.state.execute('project-save', {'name': 'Stale but recoverable'})
        restarted = BridgeState(credential_store=NullStore(), provider_module=self.provider,
                               project_store=self.state.project_store)
        restarted.execute('project-load', {'project_id': self.state.project['id']})
        public = restarted.public()
        self.assertTrue(public['design_recovery']['can_restore'])
        self.assertIsNone(public['pending_consent'])
        self.assertIsNone(public['generation_job'])
        self.assertEqual(public['credentials_configured'], [])
        r = public['design_recovery']
        restarted.execute('design-restore', {'confirmed': True, 'snapshot_id': r['snapshot_id'],
                                            'expected_config_version': r['expected_config_version']})
        self.assertEqual(restarted.config, prior['config'])
        self.assertEqual(restarted.organization['organization_id'], prior['organization']['organization_id'])
        self.assertEqual(len(self.provider.transport.calls), 0)
        self.assertTrue(restarted.download('definitions.json'))

    def test_diagnostic_download_is_stale_safe_and_never_contains_payload(self):
        self.offline_baseline()
        self.change_config()
        self.provider.transport = DesignTransport(fault=TimeoutError(RAW_MARKER + PRIVATE_MARKER))
        self.plan()
        self.state.execute('generation-confirm', self.approval())
        failed = self.wait('failed')
        raw = self.state.download('generation-diagnostic.json')
        report = json.loads(raw)
        self.assertEqual(report['job']['job_id'], failed['job_id'])
        for marker in (RAW_MARKER, PRIVATE_MARKER, 'UNTRUSTED_PROJECT_DATA', 'Authorization'):
            self.assertNotIn(marker, raw.decode())
        self.assertNotIn('requests', report['job'])
        self.assertNotIn('profile_specs', raw.decode())
        self.assertTrue(self.state.public()['generation_diagnostic_available'])

    def test_same_configuration_save_does_not_stale_or_destroy_pending_consent(self):
        self.offline_baseline()
        self.plan()
        old = copy.deepcopy(self.state.pending_consent)
        version = self.state.config_version
        self.state.execute('config', {'config': copy.deepcopy(self.state.config)})
        self.assertEqual(self.state.config_version, version)
        self.assertEqual(self.state.pending_consent, old)
        self.assertFalse(self.state.generation_stale)

    def test_successful_api_exports_are_same_bytes_in_package(self):
        completed = self.complete()
        archive = zipfile.ZipFile(io.BytesIO(self.state.download('package.zip')))
        for kind, name in (('definitions', 'definitions.json'), ('implementation', 'implementation.json')):
            data = self.state.download(name)
            artifact = completed['artifacts'][kind]
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact['sha256'])
            member = next(n for n in archive.namelist() if n.endswith('/' + artifact['filename']))
            self.assertEqual(archive.read(member), data)


class RecoveryHttpIndependent(PipelineCase):
    """Real HTTP on a synthetic loopback service; not a browser or user's DSH."""
    def setUp(self):
        import socket
        import threading
        from engine.bridge import LocalServer
        original_connect = socket.create_connection
        super().setUp()
        self.socket_guard.stop()
        def loopback_only(address, *args, **kwargs):
            if address[0] != '127.0.0.1':
                raise AssertionError('Only synthetic loopback HTTP is allowed')
            return original_connect(address, *args, **kwargs)
        self.socket_guard = patch.object(socket, 'create_connection', side_effect=loopback_only)
        self.socket_guard.start()
        self.addCleanup(self.socket_guard.stop)
        self.server = LocalServer(('127.0.0.1', 0), self.state)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def http(self, path, body=None, authenticated=True, csrf=True):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Origin': self.server.origin, 'Content-Type': 'application/json'}
        if authenticated:
            headers['Cookie'] = 'orgdna_session=' + self.state.cookie
        if csrf:
            headers['X-CSRF-Token'] = self.state.csrf
        connection.request('GET' if body is None else 'POST', path,
                           body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def failed(self):
        self.provider.transport = DesignTransport(fault=TimeoutError(RAW_MARKER + PRIVATE_MARKER))
        self.plan()
        self.state.execute('generation-confirm', self.approval())
        return self.wait('failed')

    def test_diagnostic_http_requires_session_and_exact_single_job_binding(self):
        job = self.failed()
        valid = '/download/generation-diagnostic.json?job_id=' + job['job_id']
        status, headers, data = self.http(valid)
        self.assertEqual(status, 200, data)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertEqual(json.loads(data)['job']['job_id'], job['job_id'])
        for marker in (PRIVATE_MARKER, RAW_MARKER, 'UNTRUSTED_PROJECT_DATA'):
            self.assertNotIn(marker, data.decode())
        for path in ('/download/generation-diagnostic.json', valid + '&job_id=' + job['job_id'],
                     '/download/generation-diagnostic.json?job_id=unknown', valid + '&unexpected=value'):
            with self.subTest(path=path):
                self.assertGreaterEqual(self.http(path)[0], 400)
        self.assertEqual(self.http(valid, authenticated=False)[0], 403)
        self.assertEqual(len(self.provider.transport.calls), 1)

    def test_restore_http_csrf_guard_and_exact_download_preservation(self):
        self.state.execute('generate', {})
        status, headers, before = self.http('/download/definitions.json')
        self.assertEqual(status, 200)
        self.state.execute('config', {'config': {'agent_count': 6, 'council_concurrency': 6}})
        recovery = self.state.public()['design_recovery']
        body = {'confirmed': True, 'snapshot_id': recovery['snapshot_id'],
                'expected_config_version': recovery['expected_config_version']}
        self.assertEqual(self.http('/api/design-restore', body, csrf=False)[0], 403)
        self.assertTrue(self.state.generation_stale)
        status, _, response = self.http('/api/design-restore', body)
        self.assertEqual(status, 200, response)
        self.assertFalse(json.loads(response)['generation_stale'])
        status, headers, after = self.http('/download/definitions.json')
        self.assertEqual(status, 200)
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertEqual(before, after)
        self.assertEqual(self.provider.design_calls, 0)
