"""Independent local runner checks with purpose-built inert Python fixtures."""
import copy,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from engine.evaluation_runs import EvaluationRuns,EvaluationError

class IndependentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'tests').mkdir();self.write('self.assertTrue(True)')
        self.org={'organization_id':'qa-org','state_version':1,'agents':[{'id':'author','skills':[{'id':'skill-1'}]},{'id':'reviewer','skills':[]}]}
        self.manager=EvaluationRuns()
        self.body={'profile_id':'python_unittest_v1','cwd':str(self.root),'test_dir':'tests','agent_id':'author','evaluator_id':'reviewer','task_id':'task-qa','skill_ids':['skill-1']}
    def write(self,statement):
        (self.root/'tests'/'test_qa.py').write_text('import unittest,os,time\nclass Q(unittest.TestCase):\n def test_q(self):\n  '+statement+'\n')
    def finish(self,run):
        stop=time.monotonic()+8
        while time.monotonic()<stop:
            result=self.manager.get(run['id'])
            if result['status'] not in ('queued','running'):return result
            time.sleep(.02)
        self.fail('Evaluation did not terminate')
    def test_plan_preparation_does_not_spawn_and_rejects_shell_fields(self):
        with patch('engine.evaluation_runs.subprocess.Popen') as launch:
            plan=self.manager.prepare(self.body,self.org)
            self.assertFalse(plan['sandboxed']);launch.assert_not_called()
            for key in ('command','argv','env','shell','executable'):
                with self.subTest(key=key),self.assertRaises(EvaluationError):self.manager.prepare(dict(self.body,**{key:'untrusted'}),self.org)
            launch.assert_not_called()
    def test_excluded_test_directory_is_not_unbound_executable_source(self):
        for dirname in ('.venv','node_modules','__pycache__'):
            folder=self.root/dirname/'tests';folder.mkdir(parents=True)
            (folder/'test_unsafe.py').write_text('import unittest\n')
            with self.subTest(dirname=dirname),self.assertRaises(EvaluationError):
                self.manager.prepare(dict(self.body,test_dir=dirname+'/tests'),self.org)
    def test_nested_excluded_package_cannot_change_after_consent(self):
        hidden=self.root/'tests'/'node_modules';hidden.mkdir();(hidden/'__init__.py').write_text('')
        source=hidden/'test_hidden.py';source.write_text('import unittest\nclass Hidden(unittest.TestCase):\n def test_hidden(self): self.assertTrue(True)\n')
        try:
            plan=self.manager.prepare(self.body,self.org)
        except EvaluationError:
            return  # Fail-closed rejection of such a test tree is safe.
        source.write_text('import unittest\nclass Hidden(unittest.TestCase):\n def test_hidden(self): self.fail("changed after approval")\n')
        with patch.object(self.manager,'_execute') as execute,self.assertRaises(EvaluationError):
            self.manager.start(plan['id'],plan['plan_hash'],self.org)
    def test_symlink_in_test_tree_rejected(self):
        target=self.root/'tests'/'link.py'
        target.symlink_to(self.root/'tests'/'test_qa.py')
        with self.assertRaises(EvaluationError):self.manager.prepare(self.body,self.org)
    def test_hash_and_state_are_required_before_process(self):
        plan=self.manager.prepare(self.body,self.org)
        with patch('engine.evaluation_runs.subprocess.Popen') as launch:
            with self.assertRaises(EvaluationError):self.manager.start(plan['id'],'0'*64,self.org)
            changed=copy.deepcopy(self.org);changed['state_version']=2
            with self.assertRaises(EvaluationError):self.manager.start(plan['id'],plan['plan_hash'],changed)
            self.write('self.assertTrue(1)')
            with self.assertRaises(EvaluationError):self.manager.start(plan['id'],plan['plan_hash'],self.org)
            launch.assert_not_called()
    def test_verified_result_is_hash_bound_but_never_verifies_skill(self):
        plan=self.manager.prepare(self.body,self.org);run=self.finish(self.manager.start(plan['id'],plan['plan_hash'],self.org))
        self.assertEqual(run['status'],'pass');self.assertFalse(run['skills_verified']);self.assertFalse(run['independent_review_verified']);self.assertEqual(run['test_result_trust'],'untrusted_process_report')
        self.assertEqual(self.manager.verified_result(run['id'],self.org)['id'],run['id'])
        self.manager.runs[run['id']]['tests_run']+=1
        with self.assertRaises(EvaluationError):self.manager.verified_result(run['id'],self.org)
    def test_no_environment_secret_or_raw_log_leaks(self):
        self.write('self.assertNotIn("ORG_QA_SECRET",os.environ); print("unknown-sensitive-marker-qa")')
        plan=self.manager.prepare(self.body,self.org)
        with patch.dict(os.environ,{'ORG_QA_SECRET':'secret-qa-value'}):run=self.finish(self.manager.start(plan['id'],plan['plan_hash'],self.org))
        self.assertEqual(run['status'],'pass');self.assertNotIn('unknown-sensitive-marker-qa',json.dumps(self.manager.public()));self.assertNotIn('secret-qa-value',json.dumps(self.manager.public()))
    def test_timeout_and_retry_are_not_implicit(self):
        self.write('time.sleep(5)');plan=self.manager.prepare(dict(self.body,timeout_seconds=1),self.org)
        run=self.finish(self.manager.start(plan['id'],plan['plan_hash'],self.org))
        self.assertEqual(run['status'],'timeout');self.assertFalse(run['machine_verified'])
        replay=self.manager.start(plan['id'],plan['plan_hash'],self.org)
        self.assertEqual(replay['id'],run['id']);self.assertEqual(len(self.manager.runs),1)

if __name__=='__main__':unittest.main()
