import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from engine.evaluation_runs import EvaluationRuns, EvaluationError, _sha


class Evaluations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'tests').mkdir()
        self.org = {'organization_id': 'org1', 'state_version': 1, 'agents': [
            {'id': 'author', 'skills': [{'id': 'skill1'}]}, {'id': 'reviewer', 'skills': []}]}
        self.manager = EvaluationRuns()
        self.body = {'profile_id': 'python_unittest_v1', 'cwd': str(self.root), 'test_dir': 'tests',
                     'agent_id': 'author', 'evaluator_id': 'reviewer', 'task_id': 'task1', 'skill_ids': ['skill1']}
        self.write('self.assertEqual(1 + 1, 2)')

    def write(self, statement):
        (self.root / 'tests' / 'test_fixture.py').write_text('import unittest, os, time\nclass Sample(unittest.TestCase):\n def test_local(self):\n  ' + statement + '\n', encoding='utf-8')

    def plan(self, **kw):
        return self.manager.prepare({**self.body, **kw}, self.org)

    def run_plan(self, plan):
        return self.manager.start(plan['id'], plan['plan_hash'], self.org)

    def finish(self, run):
        until = time.monotonic() + 8
        while time.monotonic() < until:
            result = self.manager.get(run['id'])
            if result['status'] not in {'queued', 'running'}:
                return result
            time.sleep(.02)
        self.fail('run did not finish')

    def test_real_pass_scoped_and_no_skill_promotion(self):
        plan = self.plan()
        self.assertTrue(Path(plan['argv'][0]).is_absolute())
        self.assertNotIn('-c', plan['argv'])
        self.assertFalse(plan['sandboxed'])
        self.assertEqual(_sha({k: v for k, v in plan.items() if k != 'plan_hash'}), plan['plan_hash'])
        run = self.finish(self.run_plan(plan))
        self.assertEqual(run['status'], 'pass')
        self.assertEqual(run['tests_run'], 1)
        self.assertTrue(run['machine_verified'])
        self.assertFalse(run['skills_verified'])
        self.assertTrue(run['independent_review_required'])
        self.assertIn(run['artifact_result_sha256'], run['evidence_ref'])

    def test_failure(self):
        self.write('self.fail("fixture failure")')
        self.assertEqual(self.finish(self.run_plan(self.plan()))['status'], 'fail')

    def test_no_tests_does_not_pass(self):
        (self.root / 'tests' / 'test_fixture.py').write_text('x=1\n')
        run = self.finish(self.run_plan(self.plan()))
        self.assertEqual(run['status'], 'fail')
        self.assertEqual(run['tests_run'], 0)

    def test_skipped_only_does_not_pass(self):
        self.write('self.skipTest("not tested")')
        self.assertEqual(self.finish(self.run_plan(self.plan()))['status'], 'fail')

    def test_exact_confirmation_required(self):
        plan = self.plan()
        with self.assertRaises(EvaluationError):
            self.manager.start(plan['id'], 'wrong', self.org)
        self.assertFalse(self.manager.runs)

    def test_doubleclick_idempotent(self):
        plan = self.plan()
        first = self.run_plan(plan)
        self.assertEqual(first['id'], self.run_plan(plan)['id'])
        self.finish(first)
        self.assertEqual(first['id'], self.run_plan(plan)['id'])
        self.assertEqual(len(self.manager.runs), 1)

    def test_source_change_invalidates_plan(self):
        plan = self.plan()
        self.write('self.assertTrue(True)')
        with self.assertRaises(EvaluationError):
            self.run_plan(plan)

    def test_source_modified_by_test_fails(self):
        self.write('open("changed.txt", "w").write("new")')
        result = self.finish(self.run_plan(self.plan()))
        self.assertEqual(result['status'], 'fail')
        self.assertFalse(result['source_unchanged'])

    def test_design_change_invalidates_plan(self):
        plan = self.plan()
        self.org['state_version'] += 1
        with self.assertRaises(EvaluationError):
            self.run_plan(plan)

    def test_expired_plan(self):
        plan = self.plan()
        with patch('engine.evaluation_runs.time.time', return_value=plan['expires_at'] + 1):
            with self.assertRaises(EvaluationError):
                self.run_plan(plan)

    def test_timeout(self):
        self.write('time.sleep(3)')
        result = self.finish(self.run_plan(self.plan(timeout_seconds=1)))
        self.assertEqual(result['status'], 'timeout')
        self.assertFalse(result['machine_verified'])

    def test_cancel(self):
        self.write('time.sleep(3)')
        run = self.run_plan(self.plan())
        self.manager.cancel(run['id'])
        self.assertEqual(self.finish(run)['status'], 'cancelled')

    def test_output_limits_and_no_secret_log(self):
        self.write('print("sk-unknownSECRET123" * 3000)')
        run = self.finish(self.run_plan(self.plan(output_limit_bytes=1024)))
        self.assertEqual(run['status'], 'fail')
        self.assertTrue(run['output_limit_exceeded'])
        self.assertNotIn('unknownSECRET123', json.dumps(self.manager.public()))

    def test_environment_does_not_inherit_keys(self):
        self.write('self.assertNotIn("OPENAI_API_KEY", os.environ)')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-fixture-key'}):
            result = self.finish(self.run_plan(self.plan()))
        self.assertEqual(result['status'], 'pass')
        self.assertNotIn('secret-fixture-key', json.dumps(result))

    def test_bad_profiles_fields_and_self_review(self):
        for kw in ({'profile_id': 'bash'}, {'argv': ['bash']}, {'env': {'SECRET': 'x'}},
                   {'evaluator_id': 'author'}, {'skill_ids': ['stale-id']}, {'timeout_seconds': 121},
                   {'output_limit_bytes': 999}, {'test_dir': '../outside'}, {'cwd': 'relative'}):
            with self.subTest(kw=kw), self.assertRaises(EvaluationError):
                self.plan(**kw)

    def test_persistent_result_contains_reference_no_raw_secret(self):
        with tempfile.TemporaryDirectory() as artifacts:
            self.manager = EvaluationRuns(artifacts)
            self.write('print("unknown-password-value")')
            run = self.finish(self.run_plan(self.plan()))
            saved = json.loads((Path(artifacts) / (run['id'] + '.json')).read_text())
            self.assertEqual(saved['result']['evidence_ref'], run['evidence_ref'])
            self.assertNotIn('unknown-password-value', json.dumps(saved))

    def test_reject_excluded_test_directories(self):
        for name in ('node_modules', '.venv', '__pycache__'):
            target = self.root / name / 'tests'
            target.mkdir(parents=True)
            (target / 'test_hidden.py').write_text('import unittest\n')
            with self.assertRaises(EvaluationError):
                self.plan(test_dir=name + '/tests')

    def test_nested_excluded_directory_is_hashed_inside_test_tree(self):
        target = self.root / 'tests' / 'node_modules'
        target.mkdir()
        (target / '__init__.py').write_text('')
        hidden = target / 'test_nested.py'
        hidden.write_text('import unittest\nclass Nested(unittest.TestCase):\n def test_nested(self): self.assertTrue(True)\n')
        plan = self.plan()
        hidden.write_text(hidden.read_text() + '# modified\n')
        with self.assertRaises(EvaluationError):
            self.run_plan(plan)

    def test_unittest_imports_project_root(self):
        (self.root / 'my_module.py').write_text('VALUE = 42\n')
        self.write('import my_module; self.assertEqual(my_module.VALUE, 42)')
        self.assertEqual(self.finish(self.run_plan(self.plan()))['status'], 'pass')

    def test_result_digest_and_agent_binding(self):
        run = self.finish(self.run_plan(self.plan()))
        verified = self.manager.verified_result(run['id'], self.org)
        self.assertEqual(verified['agent_sha256'], _sha(self.org['agents'][0]))
        self.assertEqual(verified['test_result_trust'], 'untrusted_process_report')
        self.manager.runs[run['id']]['tests_run'] = 99
        with self.assertRaises(EvaluationError):
            self.manager.verified_result(run['id'], self.org)

    def test_completed_result_source_change_blocks_feedback(self):
        run = self.finish(self.run_plan(self.plan()))
        self.write('self.assertTrue(True)')
        with self.assertRaises(EvaluationError):
            self.manager.verified_result(run['id'], self.org)
        self.assertEqual(self.manager.get(run['id'])['status'], 'pass')

    def test_pytest_missing_dependency_blocks_without_install(self):
        with patch('engine.evaluation_runs.importlib.util.find_spec', return_value=None):
            with self.assertRaisesRegex(EvaluationError, 'pytest no está instalado'):
                self.plan(profile_id='python_pytest_v1')

    @unittest.skipUnless(__import__('shutil').which('node'), 'Node not installed')
    def test_real_node_pass_and_version(self):
        (self.root / 'tests' / 'sample.test.cjs').write_text("const {test}=require('node:test'); const assert=require('node:assert'); test('fixture',()=>assert.equal(2+2,4));")
        plan = self.plan(profile_id='node_test_v1')
        self.assertNotIn('-e', plan['argv'])
        self.assertNotIn('-r', plan['argv'])
        run = self.finish(self.run_plan(plan))
        self.assertEqual(run['status'], 'pass')
        self.assertEqual(run['tests_run'], 1)
        self.assertRegex(run['executable_version'], r'^v[0-9]+\.')

    @unittest.skipUnless(__import__('shutil').which('node'), 'Node not installed')
    def test_node_file_execution_unit_is_explicit(self):
        (self.root / 'tests' / 'sample.test.cjs').write_text("console.log('nothing tested');")
        run = self.finish(self.run_plan(self.plan(profile_id='node_test_v1')))
        # Node treats a test file itself as a test; that is its actual execution unit.
        self.assertEqual(run['tests_run'], 1)
        self.assertEqual(run['tested_scope']['profile_id'], 'node_test_v1')
        self.assertFalse(run['skills_verified'])

    @unittest.skipUnless(__import__('shutil').which('node'), 'Node not installed')
    def test_real_node_fail(self):
        (self.root / 'tests' / 'sample.test.cjs').write_text("const {test}=require('node:test'); test('fixture',()=>{throw Error('failure')});")
        self.assertEqual(self.finish(self.run_plan(self.plan(profile_id='node_test_v1')))['status'], 'fail')

    @unittest.skipUnless(os.name == 'posix', 'POSIX process group check')
    def test_timeout_terminates_child_process_group(self):
        self.write('import subprocess, sys; p=subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"]); time.sleep(20)')
        result = self.finish(self.run_plan(self.plan(timeout_seconds=1)))
        self.assertEqual(result['status'], 'timeout')
        self.assertLess(result['finished_at'] - result['started_at'], 4)

if __name__ == '__main__':
    unittest.main()
