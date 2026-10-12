"""Immutable inventory reuse, offline transport fixtures only."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from engine import providers as p
from tests_providers import API, REPO, SHA, TREE_SHA, repo_fixture
from tests_repository_inventory import large_fixture


class InventoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch('socket.create_connection', side_effect=AssertionError('No network'))
        self.guard.start()
        self.cache = p.RepositoryCache()

    def tearDown(self):
        self.guard.stop()

    def read(self, fixture=None, **kwargs):
        f = fixture or large_fixture('truncated')
        return p.analyze_repository(REPO, transport=f, cache=self.cache, **kwargs), f

    def test_reuse_skips_recursive_and_all_subtrees_but_resolves_branch(self):
        first, _ = self.read()
        second, f = self.read()
        self.assertEqual(len(f.calls), 3)
        self.assertEqual(second['limits']['requests'], 3)
        self.assertEqual(second['limits']['inventory_cache_hits'], 1)
        self.assertEqual(second['coverage']['inventory']['requests'], 0)
        self.assertEqual(second['coverage']['inventory']['origin_requests'], 3)
        self.assertEqual(second['tree'], first['tree'])
        self.assertIn('memory_cache', second['coverage']['inventory']['read_source'])
        self.assertIn('read_source', p.prepare_summary(second)['coverage']['inventory'])
        self.assertGreater(first['limits']['response_bytes_observed'], second['limits']['response_bytes_observed'])
        self.assertGreaterEqual(second['limits']['elapsed_ms'], 0)
        second['tree'].clear()
        third, _ = self.read()
        self.assertEqual(third['tree'], first['tree'])

    def test_changed_tree_invalidates_but_changed_commit_same_tree_reuses(self):
        self.read()
        f = large_fixture('truncated')
        new_commit, new_tree = 'd' * 40, 'e' * 40
        f.responses[('GET', API + '/commits/main')] = (200, {}, new_commit.encode())
        f.responses[('GET', API + '/git/commits/' + new_commit)] = {'sha': new_commit, 'tree': {'sha': TREE_SHA}}
        r, _ = self.read(f)
        self.assertEqual(r['limits']['inventory_cache_hits'], 1)
        f.responses[('GET', API + '/git/commits/' + new_commit)]['tree']['sha'] = new_tree
        f.responses[('GET', API + '/git/trees/' + new_tree + '?recursive=1')] = {'sha': new_tree, 'tree': []}
        r, _ = self.read(f)
        self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        self.assertEqual(r['tree'], [])

    def test_read_budgets_and_policy_budgets_isolate_entries(self):
        self.read()
        r, _ = self.read(max_files=1)
        self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        with patch.object(p, 'MAX_TREE_REQUESTS', p.MAX_TREE_REQUESTS - 1):
            r, _ = self.read()
            self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        with patch.object(p, '_INVENTORY_POLICY_VERSION', 2):
            r, _ = self.read()
            self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        with self.assertRaises(p.ConsentRequired):
            self.read(profile='deep')

    def test_failures_not_hidden_by_cached_inventory(self):
        self.read()
        for stage in ('', '/commits/main', '/git/commits/' + SHA):
            for status in (401, 403, 429):
                f = large_fixture('truncated')
                f.responses[('GET', API + stage)] = (status, {}, b'{}')
                with self.assertRaises(p.ProviderError):
                    self.read(f)
        def broken(*args):
            raise p.ProviderError('DNS blocked')
        with self.assertRaisesRegex(p.ProviderError, 'DNS blocked'):
            p.analyze_repository(REPO, transport=broken, cache=self.cache)

    def test_partial_inventory_not_cached(self):
        with patch.object(p, 'MAX_TREE_REQUESTS', 2):
            first, _ = self.read()
            second, f = self.read()
        self.assertFalse(first['coverage']['inventory_complete'])
        self.assertEqual(second['limits']['inventory_cache_hits'], 0)
        self.assertTrue(any('/git/trees/' in c['url'] for c in f.calls))

    def test_clear_disable_and_shared_byte_entry_bounds(self):
        self.read()
        self.cache.clear()
        self.assertEqual(self.cache._bytes, 0)
        r, _ = self.read()
        self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        f = large_fixture('truncated')
        r = p.analyze_repository(REPO, transport=f, cache=None)
        self.assertEqual(r['limits']['inventory_cache_hits'], 0)
        self.cache = p.RepositoryCache(max_bytes=1000, max_entries=2)
        for _ in range(3):
            self.read()
            self.assertLessEqual(self.cache._bytes, 1000)
            self.assertLessEqual(len(self.cache._entries), 2)
            self.assertEqual(self.cache._bytes, sum(len(v) for v in self.cache._entries.values()))

    def test_concurrent_reads_do_not_corrupt_cache(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.read()[0], range(8)))
        self.assertTrue(all(r['tree'] == results[0]['tree'] for r in results))
        self.assertEqual(self.cache._bytes, sum(len(v) for v in self.cache._entries.values()))
        self.assertLessEqual(self.cache._bytes, self.cache.max_bytes)
        self.assertEqual(self.read()[0]['limits']['inventory_cache_hits'], 1)


if __name__ == '__main__':
    unittest.main()
