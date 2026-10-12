"""Bridge/UI contract for harmless synthetic local unittest execution only."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from engine.bridge import BridgeState, BridgeError
from engine.project_store import ProjectStore
from tests_bridge import NullStore


class EvaluationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cwd = root / 'source'
        (self.cwd / 'tests').mkdir(parents=True)
        self.test_file = self.cwd / 'tests/test_fixture.py'
        self.test_file.write_text('import unittest\nclass SafeFixture(unittest.TestCase):\n def test_inert(self):\n  print("SYNTHETIC_PRIVATE_OUTPUT")\n  self.assertEqual(2 + 2, 4)\n')
        self.state = BridgeState(credential_store=NullStore(), project_store=ProjectStore(root / 'projects'))
        self.state.execute('config', {'config': {'agent_count': 2, 'council_concurrency': 2, 'template': 'generic'}})
        self.state.execute('generate', {})

    def plan(self):
        result = self.state.execute('evaluation-prepare', {'profile_id': 'python_unittest_v1',
            'cwd': str(self.cwd), 'test_dir': 'tests', 'agent_id': self.state.organization['agents'][0]['id'],
            'evaluator_id': 'OWNER_EXTERNAL', 'task_id': 'fixture_task', 'skill_ids': [], 'timeout_seconds': 5})
        return result['evaluations']['plans'][-1]

    def test_exact_gate_execution_evidence_and_idempotency(self):
        plan = self.plan()
        self.assertEqual(self.state.evaluations.public()['runs'], [])
        request = {'plan_id': plan['id'], 'plan_hash': plan['plan_hash']}
        with self.assertRaises(BridgeError):
            self.state.execute('evaluation-start', request)
        with self.assertRaises(ValueError):
            self.state.execute('evaluation-start', dict(request, confirmed=True, plan_hash='wrong'))
        result = self.state.execute('evaluation-start', dict(request, confirmed=True))
        run_id = result['evaluations']['runs'][0]['id']
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            run = self.state.evaluations.get(run_id)
            if run['status'] not in ('running', 'queued'):
                break
            time.sleep(.02)
        self.assertEqual(run['status'], 'pass', run)
        self.assertFalse(run['skills_verified'])
        self.assertFalse(run['independent_review_verified'])
        self.assertTrue(run['machine_verified'])
        self.state.execute('evaluation-start', dict(request, confirmed=True))
        self.assertEqual(len(self.state.evaluations.public()['runs']), 1)
        evidence = json.loads(self.state.download('evidence.json'))
        self.assertEqual(evidence['evaluations']['runs'][0]['id'], run_id)
        self.assertNotIn('SYNTHETIC_PRIVATE_OUTPUT', json.dumps(evidence))

    def test_source_change_or_self_review_blocks_execution(self):
        plan = self.plan()
        self.test_file.write_text(self.test_file.read_text() + '\n# changed after review\n')
        with self.assertRaises(ValueError):
            self.state.execute('evaluation-start', {'plan_id': plan['id'], 'plan_hash': plan['plan_hash'], 'confirmed': True})
        self.assertEqual(self.state.evaluations.public()['runs'], [])
        agent_id = self.state.organization['agents'][0]['id']
        with self.assertRaises(ValueError):
            self.state.execute('evaluation-prepare', {'profile_id': 'python_unittest_v1',
                'cwd': str(self.cwd), 'test_dir': 'tests', 'agent_id': agent_id, 'evaluator_id': agent_id,
                'task_id': 'self_review', 'skill_ids': []})


if __name__ == '__main__':
    unittest.main()
