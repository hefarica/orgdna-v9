"""Resource plans and per-role review, fixtures only: never executes DataInventor."""
import copy,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from engine import resource_workflows as w
from engine.bridge import BridgeState
from engine.project_store import ProjectStore
from tests_bridge import NullStore
from tests.test_resource_workflows import org,answer

class IndependentResourceWorkflowTests(unittest.TestCase):
    def setUp(self):self.org=org(3);self.ref=w.datainventor_research_reference()
    def consent(self,**kw):
        c=w.prepare_workflow_consent(self.org,self.ref,'deepseek','deepseek-flash',**kw);c.update(confirmed=True,data_reviewed=True,budget_acknowledged=True);return c
    def call(self,c,**kw):return w.workflows_with_llm(self.org,self.ref,'deepseek','deepseek-flash','QA_SYNTHETIC_ONLY',c,**kw)
    def test_role_workflows_are_proposals_with_unverified_prerequisites(self):
        with patch.object(w.p,'_request',side_effect=AssertionError('No API')):r=w.baseline_resource_workflows(self.org,self.ref)
        self.assertFalse(self.ref['live_fetch_performed']);self.assertEqual(r['status'],'PROPOSED_NOT_TESTED');self.assertFalse(r['installed']);self.assertEqual(r['audit']['requests'],0)
        for row in r['agents']:
            wf=row['workflow'];self.assertFalse(wf['limits']['execution_authorized']);self.assertIsNone(wf['limits']['currency_budget']);self.assertEqual(wf['source_version']['backend_version'],'unknown');self.assertEqual(wf['source_version']['api_contract'],'unknown');self.assertTrue(wf['prerequisites']);self.assertTrue(wf['acceptance_tests'])
        self.assertEqual({a['agent_id'] for a in r['agents']},{a['id'] for a in self.org['agents']});self.assertTrue(all(i['kind']=='skill_instructions' for i in r['item_proposals']))
    def test_startup_gate_remains_pending_and_reaches_activated_context(self):
        from engine.capability_library import CapabilityLibrary
        with patch.object(w.p,'_request',side_effect=lambda *a,**kw:answer(kw['payload'])):r=self.call(self.consent())
        namespaces=set()
        for row in r['agents']:
            gate=row['workflow']['startup_gate'];self.assertEqual(gate['status'],'pending_integration');self.assertEqual(gate['configuration_status'],'not_persisted');self.assertEqual(gate['acceptance_status'],'not_run');self.assertFalse(gate['execution_authorized']);self.assertIsNone(gate['installer']);self.assertIn('configuration_readback_verified',gate['ready_requires']);self.assertIn('independent_acceptance_pass',gate['ready_requires']);self.assertIn('read_only_investigation',gate['allowed_while_blocked']);namespaces.add(gate['configuration_namespace'])
        self.assertEqual(len(namespaces),3)
        with tempfile.TemporaryDirectory() as folder:
            lib=CapabilityLibrary(Path(folder)/'state.sqlite','qa-startup');lib.import_items(r['item_proposals'],0,'import')
            ids=r['agent_item_ids'][self.org['agents'][0]['id']];plan=lib.preview(self.org,ids,{'mode':'selected','agent_ids':[self.org['agents'][0]['id']]},'activate');lib.apply(self.org,plan,'activate')
            context=lib.active_context(self.org,self.org['agents'][0]['id'])
            self.assertIn('startup_gate',context['text']);self.assertIn('pending_integration',context['text']);self.assertEqual(context['deferred_item_ids'],[])
    def test_source_and_role_changes_reject_before_paid_call(self):
        for change in ('source','role'):
            c=self.consent();original=copy.deepcopy((self.org,self.ref))
            if change=='source':self.ref['item_proposals'][0]['provenance']['evidence']+=' Modified'
            else:self.org['agents'][0]['role']='Other role'
            with patch.object(w.p,'_request') as request,self.assertRaises(w.p.ConsentRequired):self.call(c)
            request.assert_not_called();self.org,self.ref=original
    def test_forged_endpoint_or_runtime_success_is_rejected(self):
        mutations=[lambda v:v['workflows'][0].update(steps=['Usar https://example.org/run']),lambda v:v['workflows'][0].update(runtime_verified=True),lambda v:v['workflows'][0].update(source_ids=['unknown'])]
        for mutate in mutations:
            with self.subTest(mutate=mutate),patch.object(w.p,'_request',side_effect=lambda *a,**kw:answer(kw['payload'],mutate)),self.assertRaises(w.WorkflowError):self.call(self.consent())
    def test_second_batch_invalid_result_counts_attempts_and_publishes_nothing(self):
        c=self.consent(batch_size=1,max_requests=3);calls=[]
        def fake(*args,**kw):
            calls.append(1)
            return answer(kw['payload'],(lambda v:v['workflows'][0].update(source_ids=['unknown'])) if len(calls)==2 else None)
        with patch.object(w.p,'_request',side_effect=fake),self.assertRaises(w.WorkflowError) as caught:self.call(c,batch_size=1,max_requests=3)
        self.assertEqual(len(calls),2);self.assertEqual(caught.exception.audit['requests'],2);self.assertNotIn('agents',caught.exception.audit)
        with patch.object(w.p,'_request') as request,self.assertRaises(w.p.ConsentRequired):self.call(c,batch_size=1,max_requests=3)
        request.assert_not_called()
    def test_live_source_callback_change_stops_after_current_request(self):
        c=self.consent(batch_size=1,max_requests=3);calls=[]
        def fake(*a,**kw):calls.append(1);return answer(kw['payload'])
        with patch.object(w.p,'_request',side_effect=fake),self.assertRaises(w.WorkflowError) as caught:self.call(c,batch_size=1,max_requests=3,current_reference=lambda:{} if calls else self.ref)
        self.assertEqual(caught.exception.status,'STALE');self.assertEqual(len(calls),1)
    def test_bridge_per_role_assignment_is_inert_atomic_and_not_cross_product(self):
        with tempfile.TemporaryDirectory() as folder:
            state=BridgeState(credential_store=NullStore(),project_store=ProjectStore(Path(folder)/'projects'))
            state.execute('config',{'config':{'agent_count':3,'council_concurrency':3}});state.execute('generate',{})
            config=copy.deepcopy(state.config);state.execute('resource-workflow-example',{})
            result=state.execute('resource-workflow-baseline',{'expected_state_version':state.organization['state_version'],'selection':{'mode':'all'},'reference_hash':state.capabilities_hub.reference['source_hash'],'idempotency_key':str(uuid.uuid4())})['resource_workflows']['job']
            mapping=result['result']['agent_item_ids'];self.assertEqual(state.capabilities_hub.library.status()['item_count'],0)
            public=state.execute('resource-workflow-preview',{'job_id':result['job_id'],'expected_state_version':state.organization['state_version'],'expected_revision':0,'action':'assign'})
            preview=public['resource_workflows']['preview'];self.assertEqual(preview['changed_count'],3);self.assertEqual(state.capabilities_hub.library.status()['item_count'],0)
            state.execute('resource-workflow-apply',{'expected_state_version':state.organization['state_version'],'preview_hash':preview['preview_hash'],'idempotency_key':'qa-apply','confirmed':True})
            manifest=state.capabilities_hub.library.manifest_page()['items'];self.assertEqual(len(manifest),3)
            for row in manifest:self.assertIn(row['item_id'],mapping[row['agent_id']]);self.assertFalse(row['active']);self.assertFalse(row['installed'])
            self.assertEqual(state.config,config)

if __name__=='__main__':unittest.main()
