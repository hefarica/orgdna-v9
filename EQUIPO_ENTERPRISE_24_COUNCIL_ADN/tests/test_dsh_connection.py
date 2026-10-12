"""Real Node/Python loopback integration with mocked official DSH services."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.dsh_connection import DSHConnectionManager, DSHConnectionError

class ConnectionIntegration(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(['node', str(ROOT / 'cordis_extension/tests/live_bridge_fixture.mjs')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pair = json.loads(self.proc.stdout.readline())
        self.client = DSHConnectionManager(timeout=2)
    def tearDown(self):
        self.client.disconnect()
        self.proc.stdin.close()
        try: self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
        self.proc.stdout.close(); self.proc.stderr.close()
    def connect(self):
        return self.client.connect(self.pair['port'], self.pair['pairing_code'])
    def test_actual_transport_roundtrip_preserves_scope_and_ids(self):
        state = self.connect()
        self.assertTrue(state['identity_verified'])
        self.assertFalse(state['runtime_session_identity_verified'])
        self.assertNotIn('session_token', json.dumps(state))
        profiles = self.client.read_profiles()
        self.assertEqual(profiles['agents'][0]['id'], 'definition-only-A')
        self.assertFalse(profiles['definitions_are_session_ids'])
        self.assertEqual(self.client.preview_import({'format':'agent-team-gui/definitions'})['preview']['mode'], 'merge')
        self.assertEqual(self.client.read_capabilities()['tools'], [{'name':'read_file'}])
        self.assertFalse(self.client.prepare_task_plan({'tasks':[]})['dispatch_supported'])
        with self.assertRaises(DSHConnectionError): self.client.submit_task_plan({})
        with self.assertRaises(DSHConnectionError): self.client.read_team('team-a')
        self.assertTrue(self.client.cached_status()['live_connection'])
    def test_readiness_evidence_never_claims_native_execution(self):
        self.connect()
        report = self.client.diagnose()
        self.assertEqual(report['status'], 'READINESS_INCOMPLETE')
        self.assertEqual(report['observations']['teams']['profile_count'], 1)
        self.assertEqual(len(report['observations']['teams']['definition_sha256']), 64)
        self.assertFalse(report['end_to_end_orchestration_verified'])
        self.assertFalse(report['model_calls_performed'])
        self.assertEqual(report['agentteams_uses_teams_ssot'], 'UNVERIFIED')
        self.assertNotIn(self.client._token, json.dumps(report))

    def test_code_single_use_and_wrong_code_fail_closed(self):
        with self.assertRaises(DSHConnectionError): self.client.connect(self.pair['port'],'a'*43)
        self.assertFalse(self.client.status()['live_connection'])
        self.connect()
        other = DSHConnectionManager()
        with self.assertRaises(DSHConnectionError): other.connect(self.pair['port'],self.pair['pairing_code'])
        self.assertFalse(other.status()['live_connection'])
    def test_host_loss_clears_live_status_and_secrets(self):
        self.connect(); self.proc.terminate(); self.proc.wait(timeout=5)
        state = self.client.status()
        self.assertFalse(state['live_connection']);self.assertIsNone(self.client._token)
    def test_no_auto_connection_or_network_in_cached_status(self):
        with patch('http.client.HTTPConnection', side_effect=AssertionError('network')):
            self.assertFalse(self.client.status()['live_connection'])
            self.assertFalse(self.client.cached_status()['live_connection'])
            for value in [True,0,65536,1,'9000','http://evil.example',123.4]:
                with self.assertRaises(DSHConnectionError): self.client.connect(value,'a'*43)
    def test_handshake_nested_metadata_not_copied(self):
        self.connect()
        nonce='test-nonce'
        value=self.client._request('/v1/rpc',{'operation':'handshake','nonce':nonce},token=self.client._token)
        value['versions']['password']='never-copy'
        value['capabilities']['profiles_read']['session_token']='never-copy'
        value['capabilities']['profiles_read']['reason']='never-copy'
        self.client._validate_handshake(value,nonce)
        self.assertNotIn('never-copy',json.dumps(self.client.cached_status()))
        value['nonce']='incorrect'
        with self.assertRaises(DSHConnectionError):self.client._validate_handshake(value,nonce)
    def test_native_stage_link_is_separate_and_only_verified_loopback_path(self):
        self.connect()
        nonce='test-nonce'
        value=self.client._request('/v1/rpc',{'operation':'handshake','nonce':nonce},token=self.client._token)
        value['native_stage_permission_separate']=True
        for bad in ['https://evil.example/api/orgdna-native-stage','http://127.0.0.1:9000/admin','http://user:secret@127.0.0.1/api/orgdna-native-stage']:
            value['native_stage_url']=bad
            self.client._validate_handshake(value,nonce)
            self.assertIsNone(self.client.cached_status()['native_stage_url'])
        value['native_stage_url']='http://127.0.0.1:9000/api/orgdna-native-stage'
        self.client._validate_handshake(value,nonce)
        self.assertEqual(self.client.cached_status()['native_stage_url'],value['native_stage_url'])
        self.assertTrue(self.client.cached_status()['read_only'])
        self.assertFalse(self.client.cached_status()['capabilities']['task_plan_submit']['available'])

    def test_keepalive_connection_reused_and_disconnect_revokes(self):
        self.connect(); connection=self.client._connection
        self.client.read_profiles();self.client.status()
        self.assertIs(connection,self.client._connection)
        self.client.disconnect();self.assertIsNone(self.client._connection)
        self.assertFalse(self.client.cached_status()['live_connection'])

if __name__ == '__main__': unittest.main()
