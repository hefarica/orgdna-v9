"""Real loopback HTTP, synthetic upstream sources. Not a browser/live API test."""
import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from engine.bridge import BridgeState, LocalServer
from engine.project_store import ProjectStore
from engine import providers, web_sources
from tests_bridge import NullStore
from qa_v6.test_independent_multisource import WebFixture, ROOT
from tests_providers import repo_fixture

class HTTPMultisourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=BridgeState(credential_store=NullStore(),project_store=ProjectStore(Path(self.temp.name)/'projects'))
        self.server=LocalServer(('127.0.0.1',0),self.state)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def request(self,path,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Cookie':'orgdna_session='+self.state.cookie,'Origin':self.server.origin,'X-CSRF-Token':self.state.csrf,'Content-Type':'application/json'}
        conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers)
        response=conn.getresponse();result=(response.status,dict(response.getheaders()),response.read());conn.close();return result
    def action(self,name,body):
        status,_,data=self.request('/api/'+name,body);self.assertEqual(status,200,data[:500]);return json.loads(data)
    def test_capability_only_changes_preserve_native_dsh_bytes(self):
        with patch('engine.export_artifacts.time.time',return_value=1790000000):
            self.action('generate',{})
            before={name:self.request('/download/'+name)[2] for name in ('definitions.json','implementation.json','council.json')}
        with patch('engine.export_artifacts.time.time',return_value=1790000123):
            self.action('capability-save',{'expected_revision':0,'idempotency_key':'qa-local-save','item':{'id':'qa-local','kind':'skill_instructions','name':'QA reference','content':'Review evidence.','provenance':{'type':'user_authored','evidence':'Synthetic local instruction'}}})
            for name,value in before.items():self.assertEqual(self.request('/download/'+name)[2],value,name)
            state=self.action('capability-preview',{'expected_state_version':self.state.organization['state_version'],'expected_revision':1,'item_ids':['qa-local'],'selection':{'mode':'all'}})
            plan=state['capability_library']['plan']
            self.action('capability-apply',{'expected_state_version':self.state.organization['state_version'],'plan_id':plan['id'],'preview_hash':plan['preview']['preview_hash'],'idempotency_key':'qa-local-assign','confirmed':True})
            for name,value in before.items():self.assertEqual(self.request('/download/'+name)[2],value,name)
            self.assertIsNotNone(self.state._exports()['snapshot'].capability_library)
    def test_both_sources_real_http_and_three_downloads_30_agents(self):
        repo=providers.analyze_repository('https://github.com/example/project',transport=repo_fixture([('README.md',b'Public synthetic project evidence','100644')]))
        web=web_sources.analyze_website(ROOT,transport=WebFixture())
        for kind,url,inventory in [('github_repository','https://github.com/example/project',repo),('website',ROOT,web)]:
            self.action('config',{'config':{'source_kind':kind,'repo_url':url,'repo_name':'Synthetic '+kind,'agent_count':30,'council_concurrency':30,'model':'deepseek-flash'}})
            target='engine.web_sources.analyze_website' if kind=='website' else 'engine.providers.analyze_repository'
            with patch(target,return_value=inventory),patch('engine.providers.analyze_with_llm',side_effect=AssertionError('No LLM before approval')):
                self.action('analyze-repository',{})
                self.assertEqual(self.state.repo_inventory,inventory)
                self.action('generate',{})
            self.assertEqual(len(self.state.organization['agents']),30)
            downloads={}
            for alias in ('definitions.json','implementation.json','package.zip'):
                status,headers,data=self.request('/download/'+alias);self.assertEqual(status,200,data[:200]);self.assertTrue(data)
                self.assertIn('attachment;',headers['Content-Disposition']);downloads[alias]=data
            definitions=json.loads(downloads['definitions.json']);recipe=json.loads(downloads['implementation.json'])
            self.assertEqual(len(definitions['agents']),30);self.assertEqual(len(recipe['agents']),30)
            self.assertEqual([a['id'] for a in definitions['agents']],[a['id'] for a in recipe['agents']])
            with zipfile.ZipFile(io.BytesIO(downloads['package.zip'])) as archive:
                self.assertIsNone(archive.testzip())
                for alias in ('definitions.json','implementation.json'):
                    self.assertIn(downloads[alias],[archive.read(n) for n in archive.namelist() if n.endswith('.json')])
            if kind=='website':self.assertFalse(self.state.organization.get('analysis',{}).get('repository',{}).get('sha'))

if __name__=='__main__':unittest.main()
