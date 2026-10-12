"""Harness tests: inert launcher double plus real loopback addon fixture.
No Windows EXE, user installation, profile, account or private network involved.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.dsh_harness import DSHHarness, HarnessError, definition_hash
from engine.dsh_connection import DSHConnectionManager, DSHConnectionError
from engine.dsh_launcher import LauncherError


class FakeLauncher:
    def __init__(self):
        self.calls = []
        self.busy = False
        self.available = True
        self.fail = False
        self.state = {}

    def apply(self, action, body):
        self.calls.append((action, copy.deepcopy(body)))
        if action == 'dsh-launch-inspect':
            self.state = {'plan': {'plan_sha256': 'a' * 64, 'operation': body['operation'],
                'arguments': ['--headless', '--no-open', '--reuse'], 'ports': [3080]},
                'execution_available': self.available, 'backup': None, 'run': None}
        elif body.get('plan_sha256') != 'a' * 64:
            raise LauncherError('Plan changed')
        elif action == 'dsh-launch-health':
            self.state['health'] = [{'port': 3080, 'tcp_listening': self.busy, 'identity_verified': False}]
        elif action == 'dsh-launch-backup':
            self.state['backup'] = {'status': 'VERIFIED_FILE_COPY'}
        elif action == 'dsh-launch-execute':
            if self.fail:
                raise LauncherError('Synthetic launch failure')
            self.state['run'] = {'status': 'EXITED', 'exit_code': 0}
        return copy.deepcopy(self.state)

    def executions(self):
        return [call for call in self.calls if call[0] == 'dsh-launch-execute']


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.launcher = FakeLauncher()
        self.now = 100
        self.harness = DSHHarness(self.launcher, clock=lambda: self.now)

    def prepare(self, **kwargs):
        return self.harness.apply('dsh-harness-prepare', kwargs)

    def approval(self):
        return {'plan_sha256': self.harness.public()['plan']['plan_sha256'],
                'start_confirmed': True, 'backup_confirmed': True, 'execute_confirmed': True,
                'interruption_acknowledged': True, 'preservation_unverified_acknowledged': True}

    def test_prepare_is_read_only_and_plan_is_exact(self):
        state = self.prepare()
        self.assertEqual(state['status'], 'AWAITING_START_APPROVAL')
        self.assertEqual([call[0] for call in self.launcher.calls], ['dsh-launch-inspect', 'dsh-launch-health'])
        plan = dict(state['plan'])
        digest = plan.pop('plan_sha256')
        self.assertEqual(digest, hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest())
        self.assertFalse(state['live_connection'])
        self.assertFalse(state['automatic_installation_available'])

    def test_start_once_wait_bounded_exit_zero_never_connected(self):
        self.prepare(wait_seconds=10)
        state = self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(state['status'], 'WAITING_RUNTIME')
        self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(len(self.launcher.executions()), 1)
        self.now = 111
        state = self.harness.apply('dsh-harness-check')
        self.assertEqual(state['status'], 'START_TIMEOUT_NO_RETRY')
        self.assertFalse(state['live_connection'])
        self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(len(self.launcher.executions()), 1)

    def test_no_restart_or_legacy_or_bad_wait(self):
        for body in ({'operation': 'restart'}, {'legacy_stop': True}, {'wait_seconds': 121},
                     {'wait_seconds': True}, {'wait_seconds': float('nan')}, {'bridge_port': True}):
            with self.assertRaises((HarnessError, DSHConnectionError)):
                self.harness.apply('dsh-harness-prepare', body)
        self.assertEqual(self.launcher.calls, [])

    def test_busy_port_never_started_or_assumed_dsh(self):
        self.launcher.busy = True
        self.assertEqual(self.prepare()['status'], 'EXISTING_LISTENER_PAIRING_REQUIRED')
        state = self.harness.apply('dsh-harness-start', self.approval())
        self.assertFalse(state['live_connection'])
        self.assertEqual(self.launcher.executions(), [])
        self.assertFalse(any(action == 'dsh-launch-backup' for action, _ in self.launcher.calls))

    def test_missing_prerequisites_fail_closed(self):
        self.launcher.available = False
        self.assertEqual(self.prepare()['status'], 'LOCAL_PREREQUISITES_REQUIRED')
        self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(self.launcher.executions(), [])

    def test_approval_and_hash_required_before_mutation(self):
        self.prepare()
        for key in ('plan_sha256', 'start_confirmed', 'backup_confirmed', 'execute_confirmed',
                    'interruption_acknowledged', 'preservation_unverified_acknowledged'):
            payload = self.approval()
            del payload[key]
            with self.assertRaises(HarnessError):
                self.harness.apply('dsh-harness-start', payload)
        self.assertEqual(self.launcher.executions(), [])
        self.assertFalse(any(action == 'dsh-launch-backup' for action, _ in self.launcher.calls))

    def test_changed_launcher_plan_blocks_action(self):
        self.prepare()
        original = self.launcher.apply
        def stale(action, body):
            if action == 'dsh-launch-health':
                raise LauncherError('Plan changed')
            return original(action, body)
        self.launcher.apply = stale
        with self.assertRaises(LauncherError):
            self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(self.launcher.executions(), [])

    def test_failed_launch_not_retried(self):
        self.launcher.fail = True
        self.prepare()
        with self.assertRaises(LauncherError):
            self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(self.harness.public()['status'], 'START_FAILED_NO_RETRY')
        self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(len(self.launcher.executions()), 1)

    def test_listener_appears_during_backup_no_launch(self):
        self.prepare()
        original = self.launcher.apply
        def newly_busy(action, body):
            result = original(action, body)
            if action == 'dsh-launch-backup':
                self.launcher.busy = True
            return result
        self.launcher.apply = newly_busy
        state = self.harness.apply('dsh-harness-start', self.approval())
        self.assertEqual(state['status'], 'EXISTING_LISTENER_PAIRING_REQUIRED')
        self.assertEqual(self.launcher.executions(), [])

    def test_pending_plan_cannot_be_hidden_or_replaced(self):
        self.prepare()
        self.harness.apply('dsh-harness-start', self.approval())
        for action in ('dsh-harness-clear', 'dsh-harness-prepare'):
            with self.assertRaises(HarnessError):
                self.harness.apply(action)


class LoopbackHarnessTests(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(['node', str(ROOT / 'cordis_extension/tests/live_bridge_fixture.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pair = json.loads(self.proc.stdout.readline())
        self.client = DSHConnectionManager(timeout=2)
        self.launcher = FakeLauncher()
        self.launcher.busy = True
        self.harness = DSHHarness(self.launcher, self.client)
        self.harness.apply('dsh-harness-prepare', {'bridge_port': self.pair['port']})

    def tearDown(self):
        self.client.disconnect()
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill(); self.proc.wait()
        self.proc.stdout.close(); self.proc.stderr.close()

    def pair_payload(self):
        return {'plan_sha256': self.harness.public()['plan']['plan_sha256'],
                'bridge_port': self.pair['port'], 'pairing_code': self.pair['pairing_code'], 'pair_confirmed': True}

    def test_real_authenticated_bridge_and_double_readback(self):
        state = self.harness.apply('dsh-harness-pair', self.pair_payload())
        self.assertEqual(state['status'], 'READ_ONLY_VERIFIED')
        self.assertTrue(state['live_connection'])
        self.assertTrue(state['readback']['double_readback_matches'])
        self.assertEqual(state['readback']['profile_count'], 1)
        self.assertEqual(len(state['readback']['definition_sha256']), 64)
        self.assertFalse(state['native_execution_verified'])
        self.assertFalse(state['readback']['runtime_session_identity_verified'])
        self.assertNotIn(self.pair['pairing_code'], json.dumps(state))
        self.assertNotIn(self.client._token, json.dumps(state))
        self.assertEqual(self.launcher.executions(), [])

    def test_explicit_pairing_approval_and_plan_port_bound(self):
        payload = self.pair_payload()
        del payload['pair_confirmed']
        with self.assertRaises(HarnessError):
            self.harness.apply('dsh-harness-pair', payload)
        payload = self.pair_payload()
        payload['bridge_port'] += 1
        with self.assertRaises(HarnessError):
            self.harness.apply('dsh-harness-pair', payload)
        self.assertFalse(self.client.cached_status()['live_connection'])

    def test_expected_roster_mismatch_never_passes(self):
        self.harness.apply('dsh-harness-prepare', {'bridge_port': self.pair['port'], 'expected_definition_sha256': '0' * 64})
        state = self.harness.apply('dsh-harness-pair', self.pair_payload())
        self.assertEqual(state['status'], 'READBACK_MISMATCH_OR_CONNECTION_LOST')
        self.assertFalse(state['readback']['expected_definition_matches'])

    def test_public_invalidates_expired_evidence_without_network(self):
        self.harness.apply('dsh-harness-pair', self.pair_payload())
        self.client._expires = 1
        def forbidden(*args, **kwargs):
            self.fail('public must never perform network I/O')
        self.client._request = forbidden
        state = self.harness.public()
        self.assertEqual(state['status'], 'PAIRING_REQUIRED')
        self.assertFalse(state['live_connection'])
        self.assertIsNone(state['readback'])

    def test_lost_bridge_invalidates_connection_and_evidence(self):
        self.harness.apply('dsh-harness-pair', self.pair_payload())
        self.proc.terminate(); self.proc.wait(timeout=5)
        state = self.harness.apply('dsh-harness-check')
        self.assertFalse(state['live_connection'])
        self.assertIsNone(state['readback'])
        self.assertNotEqual(state['status'], 'READ_ONLY_VERIFIED')

    def test_roster_changed_between_reads_is_not_verified(self):
        self.client.connect(self.pair['port'], self.pair['pairing_code'])
        actual = self.client.read_profiles
        count = [0]
        def changed():
            value = actual()
            count[0] += 1
            if count[0] >= 3:  # diagnose reads once, then first and second readback
                value['agents'][0]['name'] = 'Changed in the second read'
            return value
        self.client.read_profiles = changed
        state = self.harness.apply('dsh-harness-verify')
        self.assertEqual(state['status'], 'READBACK_MISMATCH_OR_CONNECTION_LOST')
        self.assertFalse(state['readback']['double_readback_matches'])


if __name__ == '__main__':
    unittest.main()
