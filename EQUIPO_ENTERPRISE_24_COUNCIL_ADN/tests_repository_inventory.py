"""Large-repository regression tests. Offline only; no credentials or paid calls."""
import base64
import copy
import json
import unittest
from unittest.mock import patch, MagicMock
from engine import providers as p
from tests_providers import API, REPO, SHA, TREE_SHA, Fixture, blob_sha, repo_fixture

CHILD = 'c' * 40


def file(path, data=b'pass', size=None):
    return {'path': path, 'type': 'blob', 'mode': '100644', 'sha': blob_sha(data),
            'size': len(data) if size is None else size}


def directory(path='src', sha=CHILD):
    return {'path': path, 'type': 'tree', 'mode': '040000', 'sha': sha}


def large_fixture(cause='oversize'):
    f = repo_fixture([('README.md', b'project', '100644')])
    root = '/git/trees/' + TREE_SHA
    f.responses[('GET', API + root + '?recursive=1')] = (200, {}, b'x' * (p.MAX_HTTP_BYTES + 1)) if cause == 'oversize' else {'tree': [], 'truncated': True}
    f.responses[('GET', API + root)] = {'sha': TREE_SHA, 'tree': [file('README.md', b'project'), directory()], 'truncated': False}
    f.responses[('GET', API + '/git/trees/' + CHILD)] = {'sha': CHILD, 'tree': [file('main.py')], 'truncated': False}
    f.responses[('GET', API + '/git/blobs/' + blob_sha(b'pass'))] = {'encoding': 'base64', 'content': base64.b64encode(b'pass').decode()}
    return f


class RepositoryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch('socket.create_connection', side_effect=AssertionError('external network forbidden'))
        self.guard.start()

    def tearDown(self):
        self.guard.stop()

    def test_sha_resolution_never_requests_commit_diff(self):
        for ref in ['main', 'feature/slash', 'v1.0', SHA]:
            f = repo_fixture([('README.md', b'hi', '100644')], ref=ref)
            r = p.analyze_repository(REPO, ref=ref, transport=f)
            self.assertEqual(f.calls[1]['headers']['Accept'], 'application/vnd.github.sha')
            self.assertEqual(f.calls[1]['max_bytes'], 100)
            self.assertEqual(f.calls[2]['url'], API + '/git/commits/' + SHA)
            self.assertEqual(r['repository']['tree_sha'], TREE_SHA)

    def test_oversize_recursive_recovers_at_fixed_sha_and_omits_recursive_parameter(self):
        for cause in ('oversize', 'truncated'):
            f = large_fixture(cause)
            r = p.analyze_repository(REPO, transport=f)
            self.assertEqual({x['path'] for x in r['files']}, {'README.md', 'src/main.py'})
            self.assertTrue(r['coverage']['inventory_complete'])
            self.assertEqual(r['coverage']['inventory']['method'], 'bounded_subtrees')
            self.assertEqual(r['coverage']['inventory']['requests'], 3)
            self.assertEqual(r['limits']['requests'], len(f.calls))
            self.assertEqual(sum('?recursive=' in c['url'] for c in f.calls), 1)
            self.assertTrue(all(x['sha'] for x in r['tree']))

    def test_http_transport_size_rejection_uses_same_recovery(self):
        f = large_fixture()
        def transport(*args):
            if args[1].endswith('?recursive=1'):
                raise p.ResponseTooLarge('Respuesta HTTP supera el límite de bytes.')
            return f(*args)
        r = p.analyze_repository(REPO, transport=transport)
        self.assertTrue(r['coverage']['inventory_complete'])
        self.assertGreater(r['coverage']['inventory']['response_bytes_charged'], p.MAX_HTTP_BYTES)

    def test_dns_tls_auth_json_errors_never_trigger_fallback(self):
        for failure in (p.ProviderError('Fallo de red/TLS.'), p.HTTPFailure(403), p.ProviderError('Respuesta JSON inválida.')):
            f = large_fixture()
            def transport(*args):
                if args[1].endswith('?recursive=1'):
                    raise failure
                return f(*args)
            with self.assertRaises(p.ProviderError) as caught:
                p.analyze_repository(REPO, transport=transport)
            self.assertEqual(caught.exception.endpoint_stage, 'tree_recursive')
            self.assertFalse(any(c['url'].endswith('/git/trees/' + TREE_SHA) for c in f.calls))

    def test_oversized_nonrecursive_child_discloses_missing_inventory(self):
        f = large_fixture()
        f.responses[('GET', API + '/git/trees/' + CHILD)] = (200, {}, b'x' * (p.MAX_HTTP_BYTES + 1))
        r = p.analyze_repository(REPO, transport=f)
        self.assertFalse(r['coverage']['inventory_complete'])
        self.assertTrue(any('Subárbol demasiado grande' in x for x in r['coverage']['gaps']))
        self.assertEqual([x['path'] for x in r['files']], ['README.md'])

    def test_no_empty_partial_success(self):
        f = large_fixture()
        f.responses[('GET', API + '/git/trees/' + TREE_SHA)] = (200, {}, b'x' * (p.MAX_HTTP_BYTES + 1))
        with self.assertRaises(p.ProviderError) as caught:
            p.analyze_repository(REPO, transport=f)
        self.assertEqual(caught.exception.code, 'inventory_unavailable')
        self.assertFalse(any('/git/blobs/' in c['url'] for c in f.calls))

    def test_binary_and_oversized_are_skipped_before_blob_requests(self):
        f = large_fixture()
        f.responses[('GET', API + '/git/trees/' + CHILD)]['tree'] = [file('huge.py', size=40001), file('picture.png', size=7_000_000), file('main.py')]
        r = p.analyze_repository(REPO, transport=f)
        self.assertEqual(r['coverage']['oversized_relevant_files'], 1)
        self.assertEqual(r['coverage']['unsupported_files'], 1)
        self.assertEqual(sum('/git/blobs/' in c['url'] for c in f.calls), 2)

    def test_request_budget_is_bounded_and_partial(self):
        f = large_fixture()
        with patch.object(p, 'MAX_TREE_REQUESTS', 2):
            r = p.analyze_repository(REPO, transport=f)
        self.assertEqual(r['coverage']['inventory']['requests'], 2)
        self.assertFalse(r['coverage']['inventory_complete'])
        self.assertTrue(any('solicitudes' in x for x in r['coverage']['gaps']))

    def test_depth_budget_is_bounded_and_partial(self):
        f = large_fixture()
        with patch.object(p, 'MAX_TREE_DEPTH', 0):
            r = p.analyze_repository(REPO, transport=f)
        self.assertEqual(r['coverage']['inventory']['requests'], 2)
        self.assertFalse(r['coverage']['inventory_complete'])
        self.assertTrue(any('profundidad' in x for x in r['coverage']['gaps']))

    def test_entries_budget_is_bounded_and_partial(self):
        f = large_fixture()
        with patch.object(p, 'MAX_TREE_ENTRIES', 2):
            r = p.analyze_repository(REPO, transport=f)
        self.assertLessEqual(r['coverage']['tree_entries_seen'], 2)
        self.assertFalse(r['coverage']['inventory_complete'])

    def test_accumulated_bytes_are_bounded_and_partial(self):
        f = large_fixture('truncated')
        # Root fits, child hits the total response budget rather than per-response budget.
        with patch.object(p, 'MAX_TREE_BYTES', 510):
            r = p.analyze_repository(REPO, transport=f)
        self.assertLessEqual(r['coverage']['inventory']['response_bytes_charged'], 510)
        self.assertFalse(r['coverage']['inventory_complete'])

    def test_time_budget_prevents_next_request(self):
        f = large_fixture('truncated')
        with patch.object(p.time, 'monotonic', side_effect=[0, 0, 0, 121]):
            r = p.analyze_repository(REPO, transport=f)
        self.assertFalse(r['coverage']['inventory_complete'])
        self.assertEqual(r['coverage']['inventory']['requests'], 2)

    def test_cycles_duplicate_child_names_and_embedded_paths_fail_closed(self):
        for rows in ([directory(sha=TREE_SHA)], [file('a.py'), file('a.py')], [file('a/b.py')]):
            f = large_fixture('truncated')
            f.responses[('GET', API + '/git/trees/' + TREE_SHA)]['tree'] = rows
            with self.assertRaises(p.ProviderError):
                p.analyze_repository(REPO, transport=f)

    def test_tree_sha_mismatch_fail_closed(self):
        f = large_fixture('truncated')
        f.responses[('GET', API + '/git/trees/' + CHILD)]['sha'] = TREE_SHA
        with self.assertRaises(p.ProviderError):
            p.analyze_repository(REPO, transport=f)

    def test_shared_tree_sha_under_different_paths_is_not_deduplicated(self):
        f = large_fixture('truncated')
        f.responses[('GET', API + '/git/trees/' + TREE_SHA)]['tree'] += [directory('other')]
        r = p.analyze_repository(REPO, transport=f)
        self.assertEqual({x['path'] for x in r['files']}, {'README.md', 'src/main.py', 'other/main.py'})

    def test_sensitive_and_generated_subtrees_never_fetched_and_disclosed(self):
        f = large_fixture('truncated')
        f.responses[('GET', API + '/git/trees/' + TREE_SHA)]['tree'] = [file('README.md', b'project'), directory('node_modules'), directory('.env')]
        r = p.analyze_repository(REPO, transport=f)
        self.assertFalse(r['coverage']['inventory_complete'])
        self.assertEqual(r['coverage']['inventory']['excluded_subtrees'], 2)
        self.assertFalse(any(c['url'].endswith('/git/trees/' + CHILD) for c in f.calls))

    def test_inventory_details_survive_consent_preview_hash(self):
        r = p.analyze_repository(REPO, transport=large_fixture())
        first = p.prepare_llm_consent(r, 'deepseek', 'deepseek-flash')
        self.assertIn('inventory', first['preview']['coverage'])
        changed = copy.deepcopy(r)
        changed['coverage']['inventory']['requests'] += 1
        second = p.prepare_llm_consent(changed, 'deepseek', 'deepseek-flash')
        self.assertNotEqual(first['payload_sha256'], second['payload_sha256'])

    def test_body_deadline_prevents_slow_drip_from_resetting_timeout(self):
        conn = MagicMock()
        response = conn.getresponse.return_value
        response.status = 200
        response.getheader.return_value = None
        response.read1.return_value = b'x'
        with patch.object(p, '_public_addresses', return_value=['8.8.8.8']), patch.object(p, '_PinnedHTTPS', return_value=conn), patch.object(p.time, 'monotonic', side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(p.ProviderError, 'Tiempo máximo'):
                p._https_transport('GET', API, {}, None, 1, 300)
        self.assertEqual(response.read1.call_count, 1)
        conn.close.assert_called_once()

    def test_actual_transport_content_length_and_chunked_limit_are_typed(self):
        for length, data in [('301', b''), (None, b'a' * 301)]:
            conn = MagicMock()
            response = conn.getresponse.return_value
            response.status = 200
            response.getheader.return_value = length
            response.read1.side_effect = [data, b'']
            with patch.object(p, '_public_addresses', return_value=['8.8.8.8']), patch.object(p, '_PinnedHTTPS', return_value=conn):
                with self.assertRaises(p.ResponseTooLarge):
                    p._https_transport('GET', API, {}, None, 10, 300)
            conn.close.assert_called_once()



class LoopbackTransportBounds(unittest.TestCase):
    """Use real HTTP reads on loopback while substituting only pinned TLS dialer.

    This does not change production URL/DNS/TLS guards or contact GitHub.
    """
    def test_real_content_length_and_chunked_streams_are_bounded(self):
        import http.client
        import http.server
        import threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                if self.path.endswith('/length'):
                    self.send_header('Content-Length', '5000000')
                    self.end_headers()
                    return
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                try:
                    self.wfile.write(b'200\r\n' + b'x' * 512 + b'\r\n0\r\n\r\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def dial(host, address, timeout):
                return http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=timeout)
            for suffix in ('length', 'chunked'):
                with self.subTest(suffix=suffix), patch.object(p, '_public_addresses', return_value=['8.8.8.8']), patch.object(p, '_PinnedHTTPS', side_effect=dial):
                    with self.assertRaises(p.ResponseTooLarge):
                        p._https_transport('GET', API + '/' + suffix, {}, None, 2, 300)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__ == '__main__':
    unittest.main()
