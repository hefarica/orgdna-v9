"""Offline frontend contract checks. These do not constitute a real browser test."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
import re
import unittest
from engine.bridge import BridgeState
from engine.local_records import ACTIONS
from engine.governance import ACTIONS as GOVERNANCE_ACTIONS
from engine.coordination import ACTIONS as COORDINATION_ACTIONS
from engine.integration_tools import ACTIONS as INTEGRATION_ACTIONS
from engine.dsh_launcher import ACTIONS as LAUNCHER_ACTIONS
from engine.dsh_harness import ACTIONS as HARNESS_ACTIONS
from engine.resource_workflows_adapter import ACTIONS as RESOURCE_ACTIONS
from engine.capability_hub import ACTIONS as CAPABILITY_ACTIONS
from engine.integration_recommendations import ACTIONS as CAPABILITY_AI_ACTIONS
ROOT=Path(__file__).resolve().parent
class Markup(HTMLParser):
    def __init__(self): super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
class FrontendContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/'web/index.html').read_text();cls.js=(ROOT/'web/app.js').read_text();cls.css=(ROOT/'web/style.css').read_text();cls.markup=Markup();cls.markup.feed(cls.html)
    def test_unique_referenced_ids(self):
        ids=Counter(a['id'] for _,a in self.markup.tags if 'id' in a)
        self.assertFalse([k for k,v in ids.items() if v!=1]);refs=set(re.findall(r"\$\('#([\w-]+)'\)",self.js));self.assertFalse(refs-set(ids))
    def test_nine_accessible_pages(self):
        pages=[a for _,a in self.markup.tags if 'page' in a.get('class','').split()]
        self.assertEqual(len(pages),9);self.assertTrue(all('aria-labelledby' in a for a in pages))
    def test_no_external_dependencies_or_unsafe_html_sinks(self):
        self.assertNotRegex(self.js,r'innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function|localStorage|sessionStorage')
        self.assertNotRegex(self.html,r'<(?:script|link)[^>]+(?:src|href)=["\']https?://')
        self.assertNotIn('@import',self.css)
    def test_csrf_and_password_contract(self):
        self.assertIn('__CSRF_TOKEN__',self.html);self.assertIn("'X-CSRF-Token':csrf",self.js)
        keys=[a for t,a in self.markup.tags if a.get('name')=='api_key'];self.assertEqual(len(keys),1);self.assertEqual(keys[0]['type'],'password');self.assertIn("f.elements.api_key.value=''",self.js)
    def test_profile_edit_is_versioned(self):
        self.assertIn('expected_state_version:state.organization.state_version||1',self.js);self.assertIn("action('edit-organization',{edits}",self.js)
    def test_routes_exist(self):
        backend=(ROOT/'engine/bridge.py').read_text()
        routes=set(re.findall(r"(?:action|request)\('([a-z-]+)'",self.js))
        self.assertFalse([r for r in routes if r not in (ACTIONS | GOVERNANCE_ACTIONS | COORDINATION_ACTIONS | INTEGRATION_ACTIONS | LAUNCHER_ACTIONS | CAPABILITY_ACTIONS | CAPABILITY_AI_ACTIONS | HARNESS_ACTIONS | RESOURCE_ACTIONS) and "'"+r+"'" not in backend])
    def test_downloads_match_server(self):
        files=[a['href'].split('/')[-1] for t,a in self.markup.tags if t=='a' and 'download' in a]
        self.assertTrue(set(files)<={'implementation.json','council.json','definitions.json','organization.json','evidence.json','lifecycle.json','package.zip','cordis-addon.zip','cordis-implementation.json','cordis-definitions.json','capability-update.json'})
    def test_provider_calls_need_explicit_user_step(self):
        self.assertIn("action('discover-models',{confirmed:true})",self.js)
        self.assertIn("consent_id:state.pending_consent.approval_id",self.js)
        self.assertIn("payload_sha256:state.pending_consent.payload_sha256",self.js)
        self.assertIn("data_reviewed:true,budget_acknowledged:true",self.js)
    def test_claims_are_explicitly_preparatory(self):
        self.assertIn('NO INICIADO EN DSH',self.html);self.assertIn('NO INSTALADAS',self.html);self.assertIn('REGISTRO MANUAL',self.html)
    def test_tool_edit_limits_and_explicit_inheritance(self):
        fields={a['id']:a for _,a in self.markup.tags if 'id' in a}
        self.assertEqual(fields['tools-allow']['maxlength'],'51455')
        self.assertEqual(fields['tools-deny']['maxlength'],'51455')
        for source in ['names.length>256','n.length>200','names.join(',').length>51455','inherit_parent_tools','permissionBaseVersion']:
            self.assertIn(source,self.js)
        self.assertIn('UNVERIFIED_EXTERNAL / UNKNOWN',self.js)
        self.assertIn('Las skills son instrucciones y no son nombres de herramientas',self.html)
    def test_manual_governance_is_versioned(self):
        for route in ['performance-create','performance-review','promotion-create','promotion-update','skill-feedback']:
            self.assertIn("action('"+route+"'",self.js)
        self.assertIn('expected_state_version=formVersion(form)',self.js)
        self.assertIn('row.score==null',self.js)
        self.assertIn('row.rank==null',self.js)
        self.assertIn('includes_failures:true',self.js)
        self.assertIn('supersedes_review_id',self.js)
    def test_lease_controls_are_versioned_and_local(self):
        for route in ['lease-acquire','lease-renew','lease-release']:
            self.assertIn(route,self.js)
        self.assertIn('expected_version:state.coordination.version',self.js)
        self.assertIn('coordinationFailure()',self.js)
        self.assertIn('no bloquean el sistema de archivos',self.html)
        self.assertIn('ni autentica al revisor',self.html)
    def test_command_and_tool_preconditions_are_visible(self):
        for field in ['chain_of_command','reasoned_dissent','blocking_rule','report_fields']:
            self.assertIn(field,self.js) if field!='chain_of_command' else self.assertIn('Cadena de mando',self.html)
        self.assertIn('t.preconditions',self.js)
        self.assertIn('currentToolPreset()',self.js)
    def test_governance_forms_do_not_nest(self):
        # HTMLParser supplies robust IDs; a simple token stack covers form nesting.
        opened=0
        for token in re.findall(r'</?form\b[^>]*>',self.html):
            opened += -1 if token.startswith('</') else 1
            self.assertIn(opened,(0,1))
        self.assertEqual(opened,0)
    def test_no_empty_allow_claims_or_scores_from_activity(self):
        self.assertIn('No significa cero herramientas',self.html)
        self.assertIn('no cambian jerarquía, salario, herramientas ni permisos',self.html)
        self.assertNotIn('parseInt(row.score',self.js)
if __name__=='__main__':unittest.main()
