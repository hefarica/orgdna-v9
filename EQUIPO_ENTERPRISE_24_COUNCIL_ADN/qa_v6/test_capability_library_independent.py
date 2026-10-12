"""Independent SQLite capability assignment checks; no plugins are installed."""
import copy,tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from engine.capability_library import CapabilityLibrary,CapabilityLibraryError

def organization():
    return {'organization_id':'qa-current','state_version':1,'agents':[{'id':'qa-agent-'+str(i),'role':'Reviewer','skills':[],'tool_policy':{'allow':[],'deny':['shell']}} for i in range(30)],'functional_subteams':[{'id':'qa-subteam','member_ids':['qa-agent-2','qa-agent-7']}]}
def item(i=0,kind='skill_instructions',content='Read evidence and propose a method.'):
    return {'id':'qa-item-'+str(i),'kind':kind,'name':'QA evidence '+str(i),'content':content,'provenance':{'type':'user_authored','evidence':'Synthetic QA local fixture'}}

class IndependentCapabilityLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite';self.lib=CapabilityLibrary(self.path,'qa-project');self.org=organization()
        self.lib.import_items([item()],0,'initial')
    def test_batch_all_atomic_replay_and_current_ids(self):
        original=copy.deepcopy(self.org);plan=self.lib.preview(self.org,['qa-item-0'],{'mode':'all'})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.lib.apply(self.org,plan,'same-request'),range(4)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(self.lib.status()['assigned_count'],30);self.assertEqual(self.lib.status()['revision'],2)
        self.assertEqual({r['agent_id'] for r in self.lib.manifest_page()['items']},{a['id'] for a in self.org['agents']})
        self.assertEqual(self.org,original);self.assertFalse(results[0]['installed']);self.assertEqual(results[0]['permission_changes'],[])
    def test_concurrent_distinct_requests_do_not_double_apply(self):
        plan=self.lib.preview(self.org,['qa-item-0'],{'mode':'all'})
        def apply(key):
            try:return self.lib.apply(self.org,plan,key)
            except CapabilityLibraryError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(apply,['one','two']))
        self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(self.lib.status()['revision'],2);self.assertEqual(self.lib.status()['assigned_count'],30)
    def test_invalid_member_mixed_batch_has_no_partial_mutation(self):
        for ids in (['qa-agent-1','unknown'],['unknown']):
            with self.assertRaises(CapabilityLibraryError):self.lib.preview(self.org,['qa-item-0'],{'mode':'selected','agent_ids':ids})
        self.assertEqual(self.lib.status()['assigned_count'],0)
        with self.assertRaises(CapabilityLibraryError):self.lib.import_items([item(1),item(0,content='different')],1,'bad')
        self.assertEqual(self.lib.status()['item_count'],1);self.assertEqual(self.lib.status()['revision'],1)
    def test_plan_tamper_and_changed_org_cannot_grant_activation(self):
        plan=self.lib.preview(self.org,['qa-item-0'],{'mode':'all'})
        changed=copy.deepcopy(self.org);changed['agents'][0]['role']='Changed role'
        with self.assertRaises(CapabilityLibraryError):self.lib.apply(changed,plan,'changed')
        bad=copy.deepcopy(plan);bad['action']='activate'
        with self.assertRaises(CapabilityLibraryError):self.lib.apply(self.org,bad,'tampered')
        self.assertEqual(self.lib.status()['active_count'],0)
    def test_plugin_assignment_never_becomes_installation_or_active_context(self):
        self.lib.import_items([item(1,'plugin_package'),item(2,'connector')],1,'packages')
        plan=self.lib.preview(self.org,['qa-item-1','qa-item-2'],{'mode':'all'})
        self.lib.apply(self.org,plan,'assign')
        for iid in ('qa-item-1','qa-item-2'):
            with self.assertRaises(CapabilityLibraryError):self.lib.preview(self.org,[iid],{'mode':'all'},'activate')
        self.assertEqual(self.lib.active_context(self.org,'qa-agent-1')['text'],'');self.assertFalse(self.lib.status()['installed']);self.assertFalse(self.lib.status()['runtime_verified'])
    def test_context_deferred_without_silent_partial_item(self):
        self.lib.import_items([item(1,content='Z'*10000)],1,'large')
        plan=self.lib.preview(self.org,['qa-item-0','qa-item-1'],{'mode':'selected','agent_ids':['qa-agent-1']},'activate');self.lib.apply(self.org,plan,'active')
        context=self.lib.active_context(self.org,'qa-agent-1',1000)
        self.assertLessEqual(context['bytes'],1000);self.assertFalse(context['truncated_content']);self.assertIn('qa-item-1',context['deferred_item_ids']);self.assertNotIn('ZZZ',context['text']);self.assertFalse(context['training_weights_changed'])
    def test_undo_conflict_does_not_overwrite_later_assignment(self):
        plan=self.lib.preview(self.org,['qa-item-0'],{'mode':'all'});first=self.lib.apply(self.org,plan,'assign')
        active=self.lib.preview(self.org,['qa-item-0'],{'mode':'selected','agent_ids':['qa-agent-1']},'activate');second=self.lib.apply(self.org,active,'activate')
        with self.assertRaises(CapabilityLibraryError):self.lib.undo(self.org,first['revision'],second['revision'],'undo-old')
        self.assertEqual(self.lib.status()['assigned_count'],30);self.assertEqual(self.lib.status()['active_count'],1)
    def test_combined_import_assignment_preview_is_inert_then_atomic(self):
        before=self.lib.status()
        plan=self.lib.preview_import_items(self.org,[item(1)],['qa-item-0'],{'mode':'all'})
        self.assertEqual(self.lib.status(),before)
        result=self.lib.apply_import_preview(self.org,plan,'combo')
        self.assertTrue(result['atomic_import_and_assignment']);self.assertEqual(self.lib.status()['item_count'],2);self.assertEqual(self.lib.status()['assigned_count'],60)
        self.assertEqual(result,self.lib.apply_import_preview(self.org,plan,'combo'))
        self.assertEqual(self.lib.status()['assigned_count'],60)
    def test_combined_assignment_failure_rolls_back_new_import(self):
        plan=self.lib.preview_import_items(self.org,[item(1)],[],{'mode':'all'})
        bad=copy.deepcopy(plan);bad['assignment_preview']['effects'][0]['after']=True
        from engine.capability_library import _hash
        unsigned=dict(bad);unsigned.pop('preview_hash');bad['preview_hash']=_hash(unsigned)
        before=self.lib.status()
        with self.assertRaises(CapabilityLibraryError):self.lib.apply_import_preview(self.org,bad,'badcombo')
        self.assertEqual(self.lib.status(),before);self.assertEqual(self.lib.search('QA evidence 1')['total'],0)
    def test_save_as_fork_has_independent_future_without_replay_keys(self):
        import uuid
        self.lib.apply(self.org,self.lib.preview(self.org,['qa-item-0'],{'mode':'all'}),'assign')
        fork=self.lib.fork(uuid.uuid4().hex,expected_revision=2)
        self.assertEqual(fork.status()['assigned_count'],30)
        fork.import_items([item(1)],fork.status()['revision'],'initial')
        fork.apply(self.org,fork.preview(self.org,['qa-item-0'],{'mode':'all'},'unassign'),'unassign')
        self.assertEqual(fork.status()['assigned_count'],0);self.assertEqual(self.lib.status()['assigned_count'],30);self.assertEqual(self.lib.status()['item_count'],1)
        with self.assertRaises(CapabilityLibraryError):self.lib.fork(fork.project_id)
    def test_private_registry_persists_and_is_project_isolated(self):
        self.lib.apply(self.org,self.lib.preview(self.org,['qa-item-0'],{'mode':'all'}),'assign')
        reopened=CapabilityLibrary(self.path,'qa-project');other=CapabilityLibrary(self.path,'different-project')
        self.assertEqual(reopened.status()['assigned_count'],30);self.assertEqual(other.status()['item_count'],0);self.assertEqual(other.status()['assigned_count'],0)

if __name__=='__main__':unittest.main()
