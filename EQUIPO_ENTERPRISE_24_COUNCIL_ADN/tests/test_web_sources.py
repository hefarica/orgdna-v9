import time
import threading
import unittest
from engine import web_sources as web
from engine import providers

BASE = 'https://example.com'
HTML = b'<html><title>Example</title><h1>Build your project</h1><a href="/about">About</a><button>Start</button><form action="/submit" method="post"><label for="email">Email address</label><input id="email" name="email"></form></html>'

class Fixture:
    def __init__(self, routes=None, robots=b'User-agent: *\nAllow: /', delay=0):
        self.routes = {'/': (200, {'Content-Type':'text/html'}, HTML), '/about': (200, {'Content-Type':'text/html'}, b'<h1>About our organization</h1>')}
        self.routes.update(routes or {})
        self.routes['/robots.txt'] = (200, {'Content-Type':'text/plain'}, robots)
        self.calls = []; self.delay=delay; self.active=0; self.peak=0; self.lock=threading.Lock()
    def __call__(self, method, url, headers, body, timeout, max_bytes):
        self.assert_request(method,headers,body)
        with self.lock: self.calls.append(url); self.active+=1; self.peak=max(self.peak,self.active)
        try:
            if self.delay: time.sleep(self.delay)
            result = self.routes.get(url[len(BASE):], (404,{},b''))
            if len(result[2])>max_bytes: raise providers.ResponseTooLarge('response_byte_limit')
            return result
        finally:
            with self.lock: self.active-=1
    def assert_request(self,method,headers,body):
        assert method=='GET' and body is None and 'Authorization' not in headers

class WebEvidenceTests(unittest.TestCase):
    def setUp(self): web.clear_cache()
    def test_static_evidence_is_attributed_not_repository(self):
        result=web.analyze_website(BASE,transport=Fixture())
        self.assertEqual(result['source_kind'],'website')
        self.assertEqual(result['coverage']['pages_fetched'],2)
        self.assertNotIn('repository_sha',result)
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(len(result['source_hash']),64)
        page=result['snapshots'][0]
        self.assertEqual(len(page['sha256']),64)
        self.assertEqual(page['buttons'],['Start'])
        self.assertEqual(page['forms'][0]['method'],'post')
        self.assertEqual(page['inputs'][0]['name'],'email')
    def test_robots_denial_never_fetches_page(self):
        fixture=Fixture(robots=b'User-agent: *\nDisallow: /')
        result=web.analyze_website(BASE,transport=fixture)
        self.assertEqual(fixture.calls,[BASE+'/robots.txt'])
        self.assertEqual(result['evidence'],[])
    def test_robots_failure_closed(self):
        fixture=Fixture(); fixture.routes['/robots.txt']=(503,{},b'')
        result=web.analyze_website(BASE,transport=fixture)
        self.assertEqual(len(fixture.calls),1)
        self.assertEqual(result['coverage']['status'],'no_usable_evidence')
    def test_missing_robots_allows_read(self):
        fixture=Fixture(); fixture.routes['/robots.txt']=(404,{},b'')
        self.assertTrue(web.analyze_website(BASE,transport=fixture)['evidence'])
    def test_auth_failure_does_not_bypass(self):
        result=web.analyze_website(BASE,transport=Fixture({'/':(401,{},b'')}))
        self.assertEqual(result['evidence'],[])
        self.assertTrue(any(g['reason']=='HTTP_401' for g in result['coverage']['gaps']))
    def test_cross_origin_redirect_blocked(self):
        fixture=Fixture({'/':(302,{'Location':'https://other.example/path'},b'')})
        result=web.analyze_website(BASE,transport=fixture)
        self.assertEqual(len(fixture.calls),2)
        self.assertEqual(result['snapshots'],[])
    def test_same_origin_redirect_validated(self):
        result=web.analyze_website(BASE,transport=Fixture({'/':(302,{'Location':'/about'},b'')}))
        self.assertEqual(result['snapshots'][0]['url'],BASE+'/about')
    def test_redirect_target_obeys_robots(self):
        fixture=Fixture({'/':(302,{'Location':'/private'},b'')},robots=b'User-agent: *\nDisallow: /private')
        result=web.analyze_website(BASE,transport=fixture)
        self.assertNotIn(BASE+'/private',fixture.calls)
        self.assertEqual(result['evidence'],[])
    def test_shell_no_false_evidence(self):
        fixture=Fixture({'/':(200,{'Content-Type':'text/html'},b'<div id="root"></div><script src="app.js"></script>')})
        result=web.analyze_website(BASE,transport=fixture)
        self.assertEqual(result['snapshots'][0]['content_status'],'javascript_shell')
        self.assertEqual(result['evidence'],[])
        self.assertFalse(result['snapshots'][0]['javascript_rendered'])
    def test_cache_retains_original_fetch_date_and_rechecks_robots(self):
        fixture=Fixture(); a=web.analyze_website(BASE,transport=fixture)
        before=len(fixture.calls); b=web.analyze_website(BASE,transport=fixture)
        self.assertEqual(len(fixture.calls)-before,1)
        self.assertEqual(b['timings']['cache_hits'],2)
        self.assertEqual(a['source_hash'],b['source_hash'])
        self.assertEqual(a['snapshots'][0]['fetched_at'],b['snapshots'][0]['fetched_at'])
    def test_page_and_request_budget(self):
        result=web.analyze_website(BASE,max_pages=1,max_requests=2,transport=Fixture())
        self.assertEqual(result['coverage']['requests'],2)
        self.assertEqual(result['coverage']['pages_fetched'],1)
        self.assertTrue(result['coverage']['gaps'])
    def test_depth_budget(self):
        result=web.analyze_website(BASE,max_depth=0,transport=Fixture())
        self.assertEqual(result['coverage']['pages_fetched'],1)
        self.assertTrue(any(g['reason']=='depth_budget' for g in result['coverage']['gaps']))
    def test_only_public_https_canonical_urls(self):
        for target in ('http://example.com','https://127.0.0.1','https://localhost','https://example.com:8443','https://a:pass@example.com','https://example.com/?token=secret','https://x.internal'):
            with self.subTest(target=target),self.assertRaises(providers.ProviderError): web.canonical_url(target)
        self.assertEqual(web.canonical_url(BASE+'/?b=2&utm_source=a&a=1#part'),BASE+'/?a=1&b=2')
    def test_parallelism_bounded(self):
        root=b'<h1>Home page</h1>'+b''.join(('<a href="/p%d">page</a>'%n).encode() for n in range(5))
        routes={'/':(200,{'Content-Type':'text/html'},root)}
        routes.update({'/p%d'%n:(200,{'Content-Type':'text/html'},b'<h1>Other page</h1>') for n in range(5)})
        fixture=Fixture(routes,delay=.01)
        result=web.analyze_website(BASE,concurrency=2,transport=fixture)
        self.assertEqual(result['coverage']['pages_fetched'],6)
        self.assertEqual(fixture.peak,2)
    def test_no_nonhtml_or_compressed_input(self):
        for headers in ({'Content-Type':'application/pdf'},{'Content-Type':'text/html','Content-Encoding':'gzip'}):
            self.assertFalse(web.analyze_website(BASE,transport=Fixture({'/':(200,headers,b'not html')}))['evidence'])
    def test_summary_allowlist_and_idempotent_refs(self):
        source=web.analyze_website(BASE,transport=Fixture())
        source['system']='must be discarded'
        source['snapshots'][0]['password']='must be discarded'
        source['objective']='Build from observed pages'
        safe=web.prepare_website_summary(source)
        self.assertNotIn('system',safe)
        self.assertNotIn('password',safe['snapshots'][0])
        self.assertEqual(safe,web.prepare_website_summary(safe))
        self.assertEqual(web.website_evidence_refs(safe),[BASE+'/',BASE+'/about'])
        self.assertEqual(safe['coverage']['scope']['max_pages'],12)
        self.assertEqual(safe['snapshots'][0]['inputs'][0]['label'],'Email address')
    def test_summary_rejects_corrupt_manifest(self):
        source=web.analyze_website(BASE,transport=Fixture())
        source['snapshots'][0]['sha256']='0'*64
        with self.assertRaises(providers.ProviderError): web.prepare_website_summary(source)
    def test_summary_rejects_shell_only(self):
        fixture=Fixture({'/':(200,{'Content-Type':'text/html'},b'<script src="app.js"></script>')})
        source=web.analyze_website(BASE,transport=fixture)
        with self.assertRaises(providers.ProviderError): web.prepare_website_summary(source)
    def test_failed_reads_charge_reserved_bytes(self):
        fixture=Fixture({'/':(200,{'Content-Type':'text/html'},b'x'*200000)})
        result=web.analyze_website(BASE,max_bytes=100000,concurrency=1,transport=fixture)
        self.assertGreater(result['coverage']['bytes'],90000)
        self.assertLessEqual(result['coverage']['bytes'],100000)
    def test_no_network_on_invalid_bounds(self):
        fixture=Fixture()
        with self.assertRaises(providers.ProviderError): web.analyze_website(BASE,max_pages=0,transport=fixture)
        self.assertEqual(fixture.calls,[])

if __name__=='__main__': unittest.main()
