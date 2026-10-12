"""Offline UI adapter tests, no network, provider or runtime calls."""
import copy
import tempfile
from pathlib import Path
import unittest
from engine.bridge import BridgeState
from engine.project_store import ProjectStore
from engine.plugin_shop import search_catalog
from tests_bridge import NullStore

class CapabilityHubTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=BridgeState(credential_store=NullStore(),project_store=ProjectStore(Path(self.tmp.name)/'projects'))
        self.state.execute('config',{'config':{'agent_count':3,'council_concurrency':3}})
        self.state.execute('generate',{})
        self.state.integrations.catalog={'catalog_sha256':'a'*64,'candidates':[self.candidate(i) for i in range(251)]}
    def candidate(self,i):
        return {'id':'c'+str(i),'name':'Name %04d'%i,'version':'1','description':'analysis tools','category':'tools' if i%2 else 'memory','capabilities':['analysis'],'provenance':{'entry_sha256':str(i).zfill(64)}}
    def preview(self,**extra):
        return self.state.execute('capability-preview',{'expected_state_version':self.state.organization['state_version'],'expected_revision':self.state.capabilities_hub.library.status()['revision'],'item_ids':[],'candidate_ids':['c0','c250'],'catalog_identity':'a'*64,'selection':{'mode':'all'},**extra})['capability_library']['plan']
    def apply(self,plan):
        return self.state.execute('capability-apply',{'expected_state_version':self.state.organization['state_version'],'plan_id':plan['id'],'preview_hash':plan['preview']['preview_hash'],'idempotency_key':'apply-1','confirmed':True})
    def test_preview_is_readonly_apply_is_atomic(self):
        plan=self.preview();self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
        self.assertEqual(plan['preview']['assignment_preview']['changed_count'],6)
        result=self.apply(plan);self.assertEqual(result['capability_library']['status']['item_count'],2)
        self.assertEqual(result['capability_library']['status']['assigned_count'],6)
        self.assertEqual(result['capability_library']['status']['active_count'],0)
        self.assertFalse(result['capability_library']['status']['installed'])
        self.assertIsNotNone(self.state._exports()['snapshot'].capability_library)
    def test_catalog_change_blocks_apply(self):
        plan=self.preview();self.state.integrations.catalog['catalog_sha256']='b'*64
        with self.assertRaises(ValueError):self.apply(plan)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
    def test_org_change_blocks_apply(self):
        plan=self.preview();self.state.organization['agents'][0]['title']='Changed'
        with self.assertRaises(ValueError):self.apply(plan)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
    def test_subteams_union_is_explicit(self):
        ids=[a['id'] for a in self.state.organization['agents']]
        self.state.records['subteams']=[{'id':'t1','member_ids':ids[:2]},{'id':'t2','member_ids':ids[1:]}]
        plan=self.preview(selection={'mode':'subteams','subteam_ids':['t1','t2']})
        self.assertEqual(len(plan['preview']['assignment_preview']['agent_ids']),3)
    def test_manual_reference_does_not_fetch_or_change_source(self):
        cfg=copy.deepcopy(self.state.config)
        self.state.execute('capability-save',{'expected_revision':0,'idempotency_key':'manual1','item':{'kind':'skill_instructions','name':'Review','description':'Test','content':'Review safely','provenance':{'type':'user_authored','evidence':'https://example.org/reference not fetched'}}})
        self.assertEqual(self.state.config,cfg)
        self.assertEqual(self.state.capabilities_hub.library.status()['active_count'],0)
    def test_deployment_preview_is_readonly_and_download_stales(self):
        from engine.capability_deployment import export_skillhub_library
        baseline=export_skillhub_library(self.state.capabilities_hub.library,self.state.organization)
        self.apply(self.preview())
        before=self.state.capabilities_hub.library.status()['revision']
        result=self.state.execute('capability-deployment-plan',{'baseline':baseline,'expected_state_version':self.state.organization['state_version']})
        delta=result['capability_library']['deployment']
        self.assertFalse(delta['applied']);self.assertFalse(delta['runtime_verified'])
        self.assertEqual(len(delta['affected_member_ids']),3)
        self.assertEqual(self.state.capabilities_hub.library.status()['revision'],before)
        self.assertIn(b'orgdna-skillhub-delta/1',self.state.download('capability-update.json'))
        self.state.organization['agents'][0]['title']='Changed'
        with self.assertRaises(ValueError):self.state.download('capability-update.json')

    def test_reference_read_preview_and_import_do_not_change_org_source(self):
        from unittest.mock import patch
        cfg=copy.deepcopy(self.state.config)
        item={'id':'ref-a','kind':'skill_instructions','name':'Reference','content':'Review only','provenance':{'type':'html_summary','url':'https://example.org/','evidence':'Observed fixture'}}
        result={'source_hash':'f'*64,'source_url':'https://example.org/','item_proposals':[item]}
        with patch('engine.capability_sources.read_reference',return_value=result):
            self.state.execute('capability-source-read',{'url':'https://example.org/'})
        self.assertEqual(self.state.config,cfg)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
        plan=self.preview(candidate_ids=[],reference_ids=['ref-a'],reference_hash='f'*64)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
        self.apply(plan)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],1)
        self.assertEqual(self.state.config,cfg)

    def test_save_as_forks_private_library_and_load_keeps_current_revision(self):
        self.apply(self.preview())
        self.state.execute('project-save', {'name':'Original'})
        original=copy.deepcopy(self.state.project); old_id=self.state.capabilities_hub.library_id
        self.state.execute('project-save', {'name':'Copy','as_new':True})
        self.assertNotEqual(old_id,self.state.capabilities_hub.library_id)
        self.assertEqual(self.state.capabilities_hub.library.status()['assigned_count'],6)
        self.state.execute('capability-save', {'item':{'kind':'skill_instructions','name':'Only copy','content':'Local','provenance':{'type':'user_authored','evidence':'Authored'}},'expected_revision':self.state.capabilities_hub.library.status()['revision'],'idempotency_key':'copy1'})
        self.state.execute('project-load',{'project_id':original['id'],'version_id':original['version_id'],'confirmed':True})
        self.assertEqual(self.state.capabilities_hub.library_id,old_id)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],2)

    def test_historical_project_exposes_current_library_revision(self):
        self.apply(self.preview())
        self.state.execute('project-save',{'name':'Versioned'})
        saved=copy.deepcopy(self.state.project)
        revision=self.state.capabilities_hub.library.status()['revision']
        self.state.execute('capability-save',{'item':{'kind':'skill_instructions','name':'New revision','content':'Local','provenance':{'type':'user_authored','evidence':'Authored'}},'expected_revision':revision,'idempotency_key':'history1'})
        result=self.state.execute('project-load',{'project_id':saved['id'],'version_id':saved['version_id'],'confirmed':True})
        data=result['capability_library']
        self.assertEqual(data['saved_revision'],revision)
        self.assertGreater(data['status']['revision'],revision)
        self.assertTrue(data['saved_revision_differs'])
        self.assertEqual(data['saved_revision_status'],'changed')

    def test_explicit_ai_catalog_shortlist_is_respected_without_import(self):
        body={'expected_state_version':self.state.organization['state_version'],'idempotency_key':'ai-exact','selection':{'mode':'all'},'candidate_ids':[],'catalog_candidate_ids':['c250'],'catalog_identity':'a'*64}
        result=self.state.execute('capability-ai-baseline',body)
        job=result['capability_recommendations']['job']
        self.assertEqual(job['catalog_candidate_ids'],['c250'])
        self.assertEqual(len(job['result']['candidate_pins']),1)
        self.assertEqual(self.state.capabilities_hub.library.status()['item_count'],0)
        body['idempotency_key']='ai-stale';body['catalog_identity']='b'*64
        with self.assertRaises(ValueError):self.state.execute('capability-ai-baseline',body)

    def test_complete_catalog_paging_and_filter(self):
        cat=self.state.integrations.catalog
        first=search_catalog(cat,'',limit=100);last=search_catalog(cat,'',limit=100,offset=200)
        self.assertEqual(first['total'],251);self.assertEqual(len(last['results']),51);self.assertIsNone(last['next_offset'])
        filtered=search_catalog(cat,'',category='tools',offset=100,limit=100)
        self.assertEqual(filtered['total'],125);self.assertEqual(len(filtered['results']),25)

if __name__=='__main__':unittest.main()
