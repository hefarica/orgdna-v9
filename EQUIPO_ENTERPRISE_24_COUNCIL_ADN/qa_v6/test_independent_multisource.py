"""Independent V6 QA: deterministic fixtures only, no external networking."""
import hashlib
import json
import socket
import unittest
from unittest.mock import patch
from engine import providers as p, web_sources as w
from tests_providers import repo_fixture, API, SHA, TREE_SHA

ROOT='https://example.com/'
HTML=b'<html><title>Example</title><h1>Product evidence</h1><p>Visible product description for independent verification.</p></html>'
class WebFixture:
    def __init__(self, pages=None, robots=b'User-agent: *\nAllow: /\n'):
        self.pages=pages or {ROOT:(200,{'Content-Type':'text/html'},HTML)}; self.robots=robots; self.calls=[]
    def __call__(self, method,url,headers,body,timeout,max_bytes):
        self.calls.append((method,url,max_bytes))
        self.assertion(method=='GET' and body is None and 'Authorization' not in headers)
        value=(200,{'Content-Type':'text/plain'},self.robots) if url==ROOT+'robots.txt' else self.pages[url]
        if isinstance(value,Exception):raise value
        return value
    def assertion(self,ok):
        if not ok:raise AssertionError('Unexpected mutation or authentication')

class IndependentMultisourceTests(unittest.TestCase):
    def setUp(self):
        w.clear_cache();self.guard=patch('socket.create_connection',side_effect=AssertionError('No external network in QA'));self.guard.start()
    def tearDown(self):self.guard.stop()
    def test_sha_resolution_is_small_diff_free_request(self):
        f=repo_fixture([('README.md',b'hello world','100644')]);r=p.analyze_repository('https://github.com/example/project',transport=f)
        call=next(c for c in f.calls if '/commits/main' in c['url'])
        self.assertEqual(call['headers']['Accept'],'application/vnd.github.sha');self.assertEqual(call['max_bytes'],100)
        self.assertEqual(r['repository']['sha'],SHA)
        self.assertTrue(any('/git/commits/'+SHA in c['url'] for c in f.calls))
    def test_large_recursive_response_recovers_without_mutable_ref(self):
        f=repo_fixture([('README.md',b'hello world','100644')]);f.responses[('GET',API+'/git/trees/'+TREE_SHA+'?recursive=1')]=(200,{},b'x'*(p.MAX_HTTP_BYTES+1))
        r=p.analyze_repository('https://github.com/example/project',transport=f)
        self.assertEqual(r['coverage']['inventory']['method'],'bounded_subtrees');self.assertEqual(len(r['files']),1)
        self.assertNotIn('recursive=0',' '.join(c['url'] for c in f.calls))
    def test_http_failures_never_trigger_subdivision(self):
        for code in (401,403,429,500):
            f=repo_fixture([('README.md',b'hello world','100644')]);f.responses[('GET',API+'/git/trees/'+TREE_SHA+'?recursive=1')]=(code,{},b'')
            with self.assertRaises(p.HTTPFailure):p.analyze_repository('https://github.com/example/project',transport=f)
            self.assertFalse(any(c['url'].endswith('/git/trees/'+TREE_SHA) for c in f.calls))
    def test_partial_tree_retains_real_evidence(self):
        f=repo_fixture([('README.md',b'hello world','100644')],truncated=True)
        r=p.analyze_repository('https://github.com/example/project',transport=f)
        self.assertFalse(r['coverage']['inventory_complete']);self.assertTrue(r['files']);self.assertTrue(r['coverage']['gaps'])
    def test_request_budget_is_strict(self):
        f=WebFixture();r=w.analyze_website(ROOT,transport=f,max_requests=1)
        self.assertEqual(len(f.calls),1);self.assertFalse(r['evidence']);self.assertFalse(r['coverage']['complete'])
    def test_robots_disallow_does_not_fetch_page(self):
        f=WebFixture(robots=b'User-agent: *\nDisallow: /\n');r=w.analyze_website(ROOT,transport=f)
        self.assertEqual(len(f.calls),1);self.assertFalse(r['evidence'])
    def test_robots_failure_does_not_fallback(self):
        f=WebFixture();original=f.__call__
        def deny(*args):return (403,{},b'')
        r=w.analyze_website(ROOT,transport=deny);self.assertFalse(r['snapshots']);self.assertIn('robots_unverified_no_crawl',[g['reason'] for g in r['coverage']['gaps']])
    def test_redirect_to_private_or_cross_origin_is_blocked(self):
        for url in ('http://127.0.0.1/','https://internal.local/','https://elsewhere.com/'):
            f=WebFixture({ROOT:(302,{'Location':url},b'')});r=w.analyze_website(ROOT,transport=f)
            self.assertEqual(len(f.calls),2);self.assertFalse(r['evidence'])
    def test_public_dns_rejects_mixed_private_addresses(self):
        fake=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('socket.getaddrinfo',return_value=fake),self.assertRaises(p.ProviderError):p._public_addresses('example.com')
    def test_javascript_shell_is_not_evidence(self):
        f=WebFixture({ROOT:(200,{'Content-Type':'text/html'},b'<html><div id="app"></div><script>throw new Error("must not execute")</script></html>')})
        r=w.analyze_website(ROOT,transport=f);self.assertFalse(r['evidence']);self.assertEqual(r['snapshots'][0]['content_status'],'javascript_shell')
    def test_static_snapshot_sha_and_scope_are_explicit(self):
        r=w.analyze_website(ROOT,transport=WebFixture());self.assertEqual(r['source_kind'],'website');self.assertNotIn('repository',r)
        self.assertEqual(r['snapshots'][0]['sha256'],hashlib.sha256(HTML).hexdigest());self.assertFalse(r['coverage']['complete']);self.assertTrue(r['evidence'])
    def test_readonly_forms_and_scripts(self):
        body=HTML+b'<form action="/submit" method="post"><input name="email"><button>Submit</button></form><script>fetch("/mutate")</script>'
        f=WebFixture({ROOT:(200,{'Content-Type':'text/html'},body)});r=w.analyze_website(ROOT,transport=f)
        self.assertEqual(len(f.calls),2);self.assertTrue(r['snapshots'][0]['forms']);self.assertNotIn('fetch(',r['snapshots'][0]['text_excerpt'])
    def test_depth_budget_reports_unread_links(self):
        f=WebFixture({ROOT:(200,{'Content-Type':'text/html'},HTML+b'<a href="/next">Next</a>')});r=w.analyze_website(ROOT,transport=f,max_depth=0)
        self.assertEqual(len(f.calls),2);self.assertIn('depth_budget',[g['reason'] for g in r['coverage']['gaps']])
    def test_cached_snapshot_does_not_change_hash(self):
        f=WebFixture();a=w.analyze_website(ROOT,transport=f);b=w.analyze_website(ROOT,transport=f)
        self.assertEqual(a['source_hash'],b['source_hash']);self.assertEqual(b['timings']['cache_hits'],1);self.assertEqual(len(f.calls),3)
    def test_oversize_stream_charges_budget(self):
        f=WebFixture({ROOT:p.ResponseTooLarge('Respuesta HTTP supera el límite de bytes.')})
        r=w.analyze_website(ROOT,transport=f,max_bytes=200000)
        self.assertGreater(r['coverage']['bytes'],len(f.robots))

class ConsentBindingTests(unittest.TestCase):
    def setUp(self):
        w.clear_cache();self.web=w.analyze_website(ROOT,transport=WebFixture())
    def test_website_design_consent_retains_source_and_has_no_git_sha(self):
        from engine import org_design
        c=org_design.prepare_design_consent(self.web,'deepseek','deepseek-flash',{'agent_count':3,'source_kind':'website'})
        payload=json.dumps(c)
        self.assertIn(self.web['source_hash'],payload);self.assertIn(self.web['snapshots'][0]['sha256'],payload)
        self.assertNotIn('"repository_sha"',payload)
        self.assertFalse(c['confirmed'])
    def test_website_manual_analysis_consent_and_exact_url_refs(self):
        c=p.prepare_llm_consent(self.web,'deepseek','deepseek-flash')
        self.assertFalse(c['confirmed']);self.assertIn(self.web['source_hash'],json.dumps(c))
        data=p.prepare_summary(self.web)
        value={'professions':[{'id':'web_analyst','title':'Analista web','expertise':['HTML'],'methods':['Revisar formularios estáticos'],'evidence_paths':[ROOT],'confidence':'low'}],
               'skills':[],'model_selection':{'provider':'deepseek','model':'deepseek-flash','rationale':'Selección explícita'},'warnings':['Cobertura parcial']}
        validated=p.validate_analysis(value,data,'deepseek','deepseek-flash')
        self.assertEqual(validated['professions'][0]['evidence_paths'],[ROOT])
    def test_website_source_hash_mismatch_is_rejected(self):
        import copy
        bad=copy.deepcopy(self.web);bad['source_hash']='0'*64
        with self.assertRaises(p.ProviderError):w.prepare_website_summary(bad)
    def test_empty_evidence_cannot_prepare_llm(self):
        from engine import org_design
        f=WebFixture({ROOT:(200,{'Content-Type':'text/html'},b'<script>run()</script>')})
        web=w.analyze_website(ROOT,transport=f)
        with self.assertRaises(p.ProviderError):org_design.prepare_design_consent(web,'deepseek','deepseek-flash',{'agent_count':3,'source_kind':'website'})
    def test_changed_snapshot_invalidates_payload_digest(self):
        from engine import org_design
        import copy
        a=org_design.prepare_design_consent(self.web,'deepseek','deepseek-flash',{'agent_count':3,'source_kind':'website'})
        changed=copy.deepcopy(self.web);changed['snapshots'][0]['text_excerpt']+=' Additional evidence.'
        b=org_design.prepare_design_consent(changed,'deepseek','deepseek-flash',{'agent_count':3,'source_kind':'website'})
        self.assertNotEqual(a['payload_sha256'],b['payload_sha256'])
    def test_labels_before_controls_are_associated(self):
        f=WebFixture({ROOT:(200,{'Content-Type':'text/html'},HTML+b'<label for="email">Email address</label><input id="email">')})
        web=w.analyze_website(ROOT,transport=f)
        self.assertEqual(web['snapshots'][0]['inputs'][0]['label'],'Email address')

if __name__=='__main__':unittest.main()
