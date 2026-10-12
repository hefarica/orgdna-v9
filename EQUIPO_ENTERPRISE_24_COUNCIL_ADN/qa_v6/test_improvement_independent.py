"""Cross-feature evaluation→consent→revision with real inert tests and mock LLM."""
import copy,json,tempfile,time,unittest,uuid
from pathlib import Path
import tests_generation_pipeline as gp
from engine.bridge import BridgeError
from engine.evaluation_runs import EvaluationError
from engine import improvement

class IndependentImprovementTests(unittest.TestCase):
    setUp=gp.GenerationPipelineTests.setUp
    tearDown=gp.GenerationPipelineTests.tearDown
    wait_for=gp.GenerationPipelineTests.wait_for
    plan=gp.GenerationPipelineTests.plan
    approval=gp.GenerationPipelineTests.approval
    complete=gp.GenerationPipelineTests.complete
    def failed_evaluation(self):
        self.complete()
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.test_root=Path(tmp.name);(self.test_root/'tests').mkdir()
        (self.test_root/'tests'/'test_failure.py').write_text('import unittest\nclass Q(unittest.TestCase):\n def test_q(self): self.fail("opaque-secret-qa")\n')
        org=self.state.organization
        plan=self.state.evaluations.prepare({'profile_id':'python_unittest_v1','cwd':str(self.test_root),'test_dir':'tests','agent_id':org['agents'][0]['id'],'evaluator_id':'OWNER_EXTERNAL','task_id':'qa-task','skill_ids':[]},org)
        run=self.state.evaluations.start(plan['id'],plan['plan_hash'],org)
        until=time.monotonic()+8
        while time.monotonic()<until:
            r=self.state.evaluations.get(run['id'])
            if r['status'] not in ('queued','running'):
                self.assertEqual(r['status'],'fail');self.assertTrue(r['source_unchanged']);return r
            time.sleep(.02)
        self.fail('Fixture did not terminate')
    def test_feedback_rejects_random_run_id_and_stale_org(self):
        run=self.failed_evaluation()
        with self.assertRaises(BridgeError):self.state.execute('generation-plan',{'idempotency_key':str(uuid.uuid4()),'new_project':False,'improvement_run_ids':[str(uuid.uuid4())]})
        changed=copy.deepcopy(self.state.organization);changed['state_version']+=1
        with self.assertRaises(EvaluationError):self.state.evaluations.verified_result(run['id'],changed)
    def test_model_change_after_consent_invalidates_approval_without_llm_call(self):
        run=self.failed_evaluation()
        self.plan(new_project=False,improvement_run_ids=[run['id']])
        old_approval=self.approval();calls=self.provider.design_calls
        self.state.execute('config',{'config':{'model':'changed-fixture-model'}})
        with self.assertRaises(BridgeError):self.state.execute('generation-confirm',old_approval)
        self.assertEqual(self.provider.design_calls,calls)
    def test_feedback_rejects_source_changed_after_evaluation(self):
        run=self.failed_evaluation()
        (self.test_root/'tests'/'test_failure.py').write_text('import unittest\n')
        with self.assertRaises((BridgeError,EvaluationError)):
            self.state.execute('generation-plan',{'idempotency_key':str(uuid.uuid4()),'new_project':False,'improvement_run_ids':[run['id']]})
    def test_proposal_is_hash_bound_no_raw_logs_same_ids_and_unverified_skills(self):
        run=self.failed_evaluation();before=copy.deepcopy(self.state.organization);calls=self.provider.design_calls
        base=self.provider.design_with_llm
        def revised(*args,**kwargs):
            result=base(*args,**kwargs)
            result['profile_specs'][0]['responsibilities'][0]='Diagnosticar el fallo observado mediante un caso mínimo y documentar criterios de retest.'
            return result
        self.provider.design_with_llm=revised
        self.plan(new_project=False,improvement_run_ids=[run['id']])
        self.assertEqual(self.provider.design_calls,calls)
        pending=self.state.pending_consent
        self.assertIn('improvement_summary',pending);self.assertNotIn('opaque-secret-qa',json.dumps(pending))
        self.assertEqual(pending['model'],self.state.config['model']);self.assertFalse(pending['improvement_summary']['skills_verified'])
        bad=self.approval();bad['payload_sha256']='0'*64
        with self.assertRaises(BridgeError):self.state.execute('generation-confirm',bad)
        self.assertEqual(self.provider.design_calls,calls)
        self.state.execute('generation-confirm',self.approval());job=self.wait_for('completed')
        after=self.state.organization
        self.assertEqual([a['id'] for a in before['agents']],[a['id'] for a in after['agents']])
        proposal=after['improvement_proposal'];self.assertEqual(proposal['status'],'proposed');self.assertTrue(proposal['diff']);self.assertTrue(proposal['retest_plan'])
        self.assertFalse(proposal['skills_verified']);self.assertFalse(proposal['weights_trained'])
        self.assertEqual(self.provider.design_calls,calls+1)
    def test_unchanged_target_is_not_a_successful_improvement(self):
        run=self.failed_evaluation();before=copy.deepcopy(self.state.organization)
        self.plan(new_project=False,improvement_run_ids=[run['id']]);self.state.execute('generation-confirm',self.approval());self.wait_for('failed')
        self.assertEqual(self.state.organization,before)

if __name__=='__main__':unittest.main()
