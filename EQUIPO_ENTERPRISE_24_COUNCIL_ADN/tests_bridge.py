"""Offline bridge contract tests. No real keys, providers, COM, or network egress.
Run: python -m unittest tests_bridge -v
"""
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from engine.bridge import (BridgeState, BridgeError, LocalServer, normalize_config,
    read_xlsx_snapshot, sheet_payload, config_fingerprint, ROOT)


class NullStore:
    def load(self): return {}
    def delete(self): pass
    def save(self, value): raise BridgeError('Fixture: persistent storage unavailable.')


class FakeProvider:
    """Trusted fixture only. Never claims a real provider response."""
    def __init__(self): self.calls=[]; self.fail=False
    def discover_models(self, provider, api_key):
        self.calls.append(('models',provider))
        return {'models':[{'id':'fixture-model','source':'live_api','availability_verified':True}], 'source':'live_api','status':'fixture','verified_at':'FIXTURE'}
    def analyze_repository(self, repo_url, ref=None):
        self.calls.append(('repo',repo_url))
        return {'repository':{'url':repo_url,'sha':'a'*40},'signals':[], 'files':[],'coverage':{'inventory_complete':True},'limits':{'fixture':True}}
    def prepare_llm_consent(self, summary, provider, model, max_output_tokens=4096):
        return {'endpoint':'https://fixture.invalid/chat/completions','provider':provider,'model':model,'payload_sha256':'f'*64,'max_output_tokens':max_output_tokens,'confirmed':False,'data_reviewed':False,'budget_acknowledged':False,'preview':summary}
    def analyze_with_llm(self, summary, provider, model, api_key, consent, max_output_tokens=4096):
        self.calls.append(('llm',provider,model))
        if self.fail: raise BridgeError('Fixture timeout; not a real provider call.')
        return {'professions':[],'skills':[], 'audit':{'fixture':True},'usage':{}}
    def prepare_model_verification_consent(self,provider,model,max_output_tokens=32):
        return dict(self.prepare_llm_consent({},provider,model,max_output_tokens),kind='model_verification')
    def verify_model(self,provider,model,api_key,consent,max_output_tokens=32):
        self.calls.append(('verification',provider,model))
        return {'provider':provider,'model':model,'status':'VERIFIED_INFERENCE','availability_verified':True,'source':'live_api','verified_at':'FIXTURE'}


def fixture_xlsx(path, agents=24, assignments=None):
    """Minimal synthetic ZIP/XML for reader testing, never a user deliverable."""
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def cell(ref,text):
        from xml.sax.saxutils import escape
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(text))}</t></is></c>'
    values={'B6':'https://github.com/example/fixture','B7':'Fixture','B8':agents,'B9':3,'B10':'generic','B11':'deepseek-official','B12':'fixture-model','B13':3,'B14':agents,'B15':'main','B21':'','B22':0}
    config=''.join(f'<row r="{ref[1:]}">{cell(ref,value)}</row>' for ref,value in values.items())
    assignment_xml=''
    for i,(aid,provider,model) in enumerate(assignments or [],6):
        assignment_xml+=f'<row r="{i}">'+cell(f'B{i}',aid)+cell(f'D{i}',provider)+cell(f'E{i}',model)+'</row>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Configuracion" sheetId="1" r:id="r1"/><sheet name="Asignacion_modelos" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData>{config}</sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet2.xml',f'<worksheet xmlns="{ns}"><sheetData>{assignment_xml}</sheetData></worksheet>')


def saved_workbook_reader(action, workbook, payload=None):
    """Doble de excel_call('Read'): lee el .xlsx GUARDADO sin Excel, sin inventar datos.

    En Windows, `BridgeState.download` relee el libro por COM (engine/bridge.py:2519) y el
    adaptador PowerShell exige que el libro este abierto en una instancia ACTIVA de Excel
    (engine/excel_bridge.ps1:82): sin Excel ese camino falla por ENTORNO, no por el producto.
    El sujeto de `test_workbook_stale_blocks_export` es la deteccion de staleness, no COM, y
    el propio producto ya trae el lector del archivo guardado (`read_xlsx_snapshot`), que
    devuelve la MISMA forma de snapshot. Se sustituye SOLO la lectura: si el archivo cambia
    en disco, el snapshot cambia, que es justo lo que el test debe observar.
    """
    if action != 'Read' or payload is not None:
        raise BridgeError('Fixture: el doble solo implementa la lectura del archivo guardado.')
    return read_xlsx_snapshot(str(workbook))


class BridgeStateTests(unittest.TestCase):
    def setUp(self): self.provider=FakeProvider();self.state=BridgeState(credential_store=NullStore(),provider_module=self.provider)
    def test_default_offline_generation_and_export(self):
        self.state.execute('generate',{})
        self.assertEqual(len(self.state.organization['agents']),24)
        self.assertFalse(self.provider.calls)
        for name in ('organization.json','implementation.json','council.json','evidence.json'):
            self.assertIsInstance(json.loads(self.state.download(name)),dict)
    def test_generation_invalidated_by_config(self):
        self.state.execute('generate',{})
        self.state.execute('config',{'config':{'agent_count':7,'council_concurrency':7}})
        with self.assertRaises(BridgeError):self.state.download('implementation.json')
        self.state.execute('generate',{})
        self.assertEqual(len(self.state.organization['agents']),7)
    def test_model_overrides_survive_generation(self):
        self.state.execute('generate',{})
        aid=self.state.organization['agents'][0]['id']
        self.state.model_overrides={aid:{'provider':'zai','model':'fixture-model'}}
        self.state.execute('generate',{})
        self.assertEqual(self.state.organization['agents'][0]['provider'],'zai')
        self.assertEqual(self.state.organization['agents'][0]['model'],'fixture-model')
    def test_key_never_in_state_or_receipt(self):
        secret='fixture-secret-do-not-use'
        self.state.execute('credentials',{'provider':'deepseek-official','api_key':secret})
        self.state.receipt('fixture','warning',f'contains {secret}')
        serialized=json.dumps(self.state.public())
        self.assertNotIn(secret,serialized);self.assertIn('[REDACTED]',serialized)
    def test_quote_backslash_secret_redaction(self):
        secret='SYNTHETIC"SLASH\\NONCREDENTIAL_991'
        self.state.credentials['deepseek']=secret
        self.assertNotIn(secret, self.state.redact({'nested':[{'message':'token='+secret}]} )['nested'][0]['message'])
    def test_unavailable_preserved_in_excel_payload(self):
        self.state.execute('generate',{})
        rows=sheet_payload(self.state.organization,[{'provider':'deepseek','model':'missing','available':False}],[])['sheets']['models']['rows']
        self.assertEqual(rows[0][3],'UNAVAILABLE')
    def test_models_require_confirmation_and_map_route(self):
        self.state.credentials['deepseek-official']='fixture-key'
        with self.assertRaises(BridgeError):self.state.execute('discover-models',{})
        self.state.execute('discover-models',{'confirmed':True})
        self.assertEqual(self.provider.calls,[('models','deepseek')])
        self.assertEqual(self.state.models[0]['provider'],'deepseek-official')
        self.assertIs(self.state.models[0]['available'],True)
    def _prepare(self):
        self.state.execute('config',{'config':{'repo_url':'https://github.com/example/fixture', 'model':'fixture-model'}})
        self.state.credentials['deepseek-official']='fixture-key'
        self.state.execute('discover-models', {'confirmed': True})
        self.state.execute('analyze-repository',{})
        self.assertFalse(any(c[0]=='llm' for c in self.provider.calls))
        self.state.execute('prepare-analysis',{})
        self.state.credentials['deepseek-official']='fixture-key'
        pending=self.state.pending_consent
        return {'confirmed':True,'consent_id':pending['approval_id'],'payload_sha256':pending['payload_sha256'],'data_reviewed':True,'budget_acknowledged':True}
    def test_website_configuration_is_explicit_and_preserves_url(self):
        self.state.execute('config', {'config': {'source_kind': 'website', 'repo_url': 'https://example.org/docs/'}})
        self.assertEqual(self.state.config['source_kind'], 'website')
        self.assertEqual(self.state.config['repo_url'], 'https://example.org/docs/')
        self.state.repo_inventory = {'source_kind': 'website'}
        self.state.execute('config', {'config': {'source_kind': 'github_repository', 'repo_url': 'https://github.com/example/fixture'}})
        self.assertIsNone(self.state.repo_inventory)
        with self.assertRaises(BridgeError):
            self.state.execute('config', {'config': {'repo_url': 'https://example.org/docs/'}})

    def test_manual_analysis_partial_coverage_needs_bound_ack(self):
        self._prepare()
        self.state.repo_inventory['coverage'] = {'inventory_complete': False, 'gaps': ['unknown subtree']}
        self.state.execute('prepare-analysis', {})
        pending = self.state.pending_consent
        approval = {'confirmed': True, 'consent_id': pending['approval_id'],
                    'payload_sha256': pending['payload_sha256'], 'data_reviewed': True, 'budget_acknowledged': True}
        with self.assertRaises(BridgeError):
            self.state.execute('confirm-analysis', approval)
        with self.assertRaises(BridgeError):
            self.state.execute('confirm-analysis', dict(approval, partial_inventory_acknowledged=True, coverage_sha256='wrong'))
        self.assertFalse(any(call[0] == 'llm' for call in self.provider.calls))
        self.state.execute('confirm-analysis', dict(approval, partial_inventory_acknowledged=True,
                                                   coverage_sha256=pending['coverage_sha256']))
        self.assertEqual(sum(call[0] == 'llm' for call in self.provider.calls), 1)

    def test_consent_requires_all_flags_and_no_replay(self):
        approval=self._prepare()
        with self.assertRaises(BridgeError):self.state.execute('confirm-analysis',dict(approval,data_reviewed=False))
        self.state.execute('confirm-analysis',approval)
        self.assertIsNone(self.state.pending_consent)
        with self.assertRaises(BridgeError):self.state.execute('confirm-analysis',approval)
        self.assertEqual(sum(c[0]=='llm'for c in self.provider.calls),1)
    def test_failed_request_consumes_consent(self):
        approval=self._prepare();self.provider.fail=True
        with self.assertRaises(BridgeError):self.state.execute('confirm-analysis',approval)
        self.assertIsNone(self.state.pending_consent)
        with self.assertRaises(BridgeError):self.state.execute('confirm-analysis',approval)
        self.assertEqual(sum(c[0]=='llm'for c in self.provider.calls),1)
    def test_config_change_invalidates_consent(self):
        approval=self._prepare()
        self.state.execute('config',{'config':{'model':'new-model'}})
        with self.assertRaises(BridgeError):self.state.execute('confirm-analysis',approval)
    def test_changed_repo_invalidates_inventory(self):
        self._prepare();self.state.execute('config',{'config':{'repo_url':'https://github.com/other/fixture'}})
        self.assertIsNone(self.state.repo_inventory)
    def test_workbook_stale_blocks_export(self):
        # Sin Excel: se sustituye SOLO la lectura COM por el lector guardado del producto
        # (saved_workbook_reader). Un skip habria dejado sin cobertura esta guarda de
        # exportacion en toda maquina Windows sin Excel; el doble la ejercita de verdad.
        with patch('engine.bridge.excel_call',side_effect=saved_workbook_reader):
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'fixture.xlsx';fixture_xlsx(path)
                self.state.execute('import-workbook',{'workbook':str(path)})
                self.state.execute('generate',{})
                self.assertTrue(self.state.download('organization.json'))
                fixture_xlsx(path,agents=7)
                with self.assertRaises(BridgeError):self.state.download('implementation.json')
    def test_xlsx_assignments_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.xlsx';fixture_xlsx(path,assignments=[('id1','zai','glm-fixture')])
            snapshot=read_xlsx_snapshot(path)
            self.assertEqual(snapshot['model_overrides']['id1']['provider'],'zai')
            self.assertTrue(config_fingerprint(snapshot['config']).endswith('|0'))
    def test_excel_payload_capacities_and_preserve_formulas(self):
        self.state.execute('generate',{})
        payload=sheet_payload(self.state.organization,[],[])
        self.assertNotIn('organization',payload['sheets'])
        self.assertEqual(len(payload['sheets']['cv']['rows']),216)
        with self.assertRaises(BridgeError):sheet_payload(self.state.organization,[{'model':str(i)} for i in range(201)],[])
    def test_static_com_formula_protection(self):
        script=(ROOT/'engine'/'excel_bridge.ps1').read_text()
        self.assertLess(script.index("$cell.NumberFormat = '@'"),script.index('$cell.Value2 = [string]$value'))
        self.assertIn('if ($cell.HasFormula)',script)
        self.assertNotIn('ExecutionPolicy Bypass',script)
    def test_invalid_config_rejected(self):
        for raw in ({'agent_count':41},{'max_direct_reports':0},{'api_key':'secret'},{'repo_url':'https://127.0.0.1/x/y'},{'repo_url':'https://github.com/a/b?token=x'},{'implementation_concurrency':4}):
            with self.subTest(raw=raw),self.assertRaises(BridgeError):normalize_config(raw)
    def test_local_verification_requires_separate_consent(self):
        self.state.credentials['deepseek-official']='fixture-key'
        self.state.execute('prepare-verification',{})
        self.assertFalse(self.provider.calls)
        p=self.state.pending_consent
        self.state.credentials['deepseek-official']='fixture-key'
        self.state.execute('confirm-analysis',{'confirmed':True,'data_reviewed':True,'budget_acknowledged':True,'consent_id':p['approval_id'],'payload_sha256':p['payload_sha256']})
        self.assertIs(self.state.models[0]['available'],True)
        self.assertIsNone(self.state.analysis)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.state=BridgeState(credential_store=NullStore())
        self.server=LocalServer(('127.0.0.1',0),self.state)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.host=f'127.0.0.1:{self.server.server_port}'
        status,headers,body=self.request('GET','/')
        self.cookie=headers['Set-Cookie'].split(';')[0]
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        connection.request(method,path,body=body,headers=headers or {})
        response=connection.getresponse();payload=response.read();result=(response.status,dict(response.getheaders()),payload);connection.close();return result
    def post_headers(self):return {'Host':self.host,'Origin':'http://'+self.host,'Cookie':self.cookie,'Content-Type':'application/json','X-CSRF-Token':self.state.csrf}
    def test_html_assets_and_csp(self):
        status,headers,body=self.request('GET','/')
        self.assertEqual(status,200);self.assertIn(b'OrgDNA',body)
        self.assertNotIn(b'__CSRF_TOKEN__',body);self.assertNotIn(b'__MAX_AGENTS__',body);self.assertEqual(headers['X-Frame-Options'],'DENY')
        for path in ('/app.js','/style.css'):self.assertEqual(self.request('GET',path)[0],200)
    def test_bad_host_origin_csrf_cookie_blocked(self):
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.example'})[0],403)
        for field in ('Origin','X-CSRF-Token','Cookie'):
            headers=self.post_headers();headers.pop(field)
            self.assertEqual(self.request('POST','/api/generate','{}',headers)[0],403)
    def test_get_cannot_mutate(self):
        self.assertEqual(self.request('GET','/api/generate',headers={'Cookie':self.cookie})[0],404)
        self.assertIsNone(self.state.organization)
    def test_post_generate_download(self):
        self.assertEqual(self.request('POST','/api/generate','{}',self.post_headers())[0],200)
        status,headers,body=self.request('GET','/download/council.json',headers={'Cookie':self.cookie})
        self.assertEqual(status,200);self.assertIn('attachment',headers['Content-Disposition']);json.loads(body)
    def test_body_bound(self):
        self.assertEqual(self.request('POST','/api/config','x'*140000,self.post_headers())[0],413)
    def test_bind_not_loopback_rejected(self):
        with self.assertRaises(BridgeError):LocalServer(('0.0.0.0',0),self.state)

if __name__=='__main__':unittest.main(verbosity=2)
