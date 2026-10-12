"""Offline Plugin Shop contract, provenance and boundary tests; never install."""
import base64
import copy
import hashlib
import importlib
import json
import socket
import unittest
from unittest.mock import patch
from engine import plugin_shop as p

BASE = p.SOURCES['github_pages']
INTEGRITY = 'sha512-' + base64.b64encode(b'x' * 64).decode()
SHA = 'a' * 40


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def npm_entry(name='@fixture/browser', version='1.2.3'):
    return {'name': name, 'version': version, 'source': 'npm', 'integrity': INTEGRITY,
            'publishedAt': '2026-10-06T12:00:00Z', 'repository': 'https://github.com/fixture/browser',
            'license': 'MIT', 'metadata': 'declared', 'tier': 'community',
            'peers': ['@deepseek-ai/cordis'], 'dshPeers': {'@deepseek-ai/dsh-tools': '^0.2.0-rc.1'},
            'compatibility': {'dsh': '^0.2.0-0', 'profiles': ['web']},
            'catalog': {'category': 'tool', 'summary': {'en': 'Playwright browser tests and screenshots.'},
                        'capabilities': ['browser', 'shell']}}


def github_entry(repo='fixture/browser', subdir=None):
    entry = npm_entry('fixture-browser', SHA)
    entry.update(source='github', repo=repo, integrity=SHA)
    if subdir:
        entry['subdir'] = subdir
    return entry


def fixture_data(entries=None, **overrides):
    value = {'schemaVersion': 5, 'plugins': entries if entries is not None else [npm_entry()], 'denied': []}
    value.update(overrides)
    raw = encoded(value)
    digest = hashlib.sha256(raw).hexdigest()
    index = {'schemaVersion': value['schemaVersion'], 'builtAt': '2026-10-06T12:00:00Z',
             'count': len(value['plugins']), 'plugins': {'url': 'plugins.' + digest + '.json', 'sha256': digest}}
    return index, raw


def catalog(entries=None, **overrides):
    index, raw = fixture_data(entries, **overrides)
    return p.parse_catalog(index, raw)


def manifest(name='@fixture/browser', version='1.2.3'):
    return {'name': name, 'version': version, 'dsh': {'bundle': {'patch': 'cordis.patch.yml'}},
            'scripts': {'build': 'tsc', 'postinstall': 'node setup.js'},
            'dependencies': {'dependency': '^2.0.0'}, 'peerDependencies': {'@deepseek-ai/cordis': '*'},
            'engines': {'node': '>=22'}, 'dist': {'integrity': INTEGRITY}}


class Fixture:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        self.calls.append({'method': method, 'url': url, 'headers': headers, 'body': body})
        value = self.responses[url]
        if isinstance(value, tuple):
            return value
        return 200, {'Content-Type': 'application/json'}, value if isinstance(value, bytes) else encoded(value)


def inspected():
    c = catalog()
    url = 'https://registry.npmjs.org/%40fixture%2Fbrowser/1.2.3'
    return p.inspect_candidate(c, c['candidates'][0]['id'], transport=Fixture({url: manifest()}))


def evidence(c, **changes):
    result = {'candidate_id': c['id'], 'version': c['version'], 'entry_sha256': c['provenance']['entry_sha256'],
              'operator': 'Test operator', 'note': 'Report only; synthetic offline fixture.',
              'request_id': 'fixture-request', 'acknowledged': True}
    result.update(changes)
    return result


class PluginShopTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.create_connection', side_effect=AssertionError('No network in offline tests'))
        self.network.start()

    def tearDown(self):
        self.network.stop()

    def test_import_and_empty_catalog_do_not_network(self):
        with patch.object(socket, 'getaddrinfo', side_effect=AssertionError('No DNS')):
            importlib.reload(p)
            self.assertEqual(p.empty_catalog()['status'], 'NOT_FETCHED')
            self.assertEqual(p.empty_catalog()['candidates'], [])

    def test_fixed_source_and_exact_content_hash_fetch(self):
        idx, raw = fixture_data()
        f = Fixture({BASE + 'index.json': idx, BASE + idx['plugins']['url']: raw})
        result = p.fetch_catalog(transport=f)
        self.assertEqual(len(f.calls), 2)
        self.assertTrue(all(x['method'] == 'GET' and x['body'] is None and 'Authorization' not in x['headers'] for x in f.calls))
        self.assertEqual(result['count'], 1)
        self.assertTrue(result['network_performed'])
        self.assertFalse(result['runtime_verified'])

    def test_external_source_override_rejected_before_network(self):
        for value in ['https://evil.example/v1/', 'http://127.0.0.1', 'npm_registry', '', None]:
            with self.subTest(value=value), self.assertRaises(p.PluginShopError):
                p.fetch_catalog(value, transport=lambda *a: self.fail('Must not fetch'))

    def test_pointer_ssrf_and_paths_rejected_before_data_request(self):
        for value in ['https://127.0.0.1/a', '//evil.example/a', '../plugins.json', '%2e%2e/x', 'x\\y', 'plugins.a.json?secret=x', '.', '/plugins.json']:
            idx, _ = fixture_data()
            idx['plugins']['url'] = value
            f = Fixture({BASE + 'index.json': idx})
            with self.subTest(value=value), self.assertRaises(p.PluginShopError):
                p.fetch_catalog(transport=f)
            self.assertEqual(len(f.calls), 1)

    def test_corrupt_bytes_fail_hash_without_fallback(self):
        idx, raw = fixture_data()
        with self.assertRaisesRegex(p.PluginShopError, 'SHA-256'):
            p.parse_catalog(idx, raw + b' ')

    def test_schema_count_duplicate_keys_nan_rejected(self):
        idx, raw = fixture_data()
        for changes in [{'schemaVersion': 7}, {'schemaVersion': True}, {'count': 2}, {'count': True}]:
            bad = dict(idx, **changes)
            with self.assertRaises(p.PluginShopError):
                p.parse_catalog(bad, raw)
        for raw in [b'{"schemaVersion":5,"plugins":[],"plugins":[]}', b'{"schemaVersion":NaN}']:
            idx, _ = fixture_data([])
            digest = hashlib.sha256(raw).hexdigest()
            idx['plugins'] = {'url': 'plugins.' + digest + '.json', 'sha256': digest}
            with self.assertRaises(p.PluginShopError):
                p.parse_catalog(idx, raw)

    def test_catalog_rejects_non_json_and_oversize(self):
        with self.assertRaises(p.PluginShopError):
            p._json(b'[]', 100)
        with self.assertRaises(p.PluginShopError):
            p._json(b'{}', 1)

    def test_duplicate_identity_rejected_but_forks_not_conflated(self):
        with self.assertRaisesRegex(p.PluginShopError, 'duplicadas'):
            catalog([npm_entry(), npm_entry()])
        c = catalog([github_entry('fixture/browser'), github_entry('another/browser')])
        self.assertEqual(len({x['id'] for x in c['candidates']}), 2)

    def test_metadata_urls_never_grant_fetch_authority(self):
        entry = npm_entry()
        entry['repository'] = 'https://127.0.0.1/a'
        self.assertIsNone(catalog([entry])['candidates'][0]['repository'])
        entry['repository'] = 'javascript:alert(1)'
        self.assertIsNone(catalog([entry])['candidates'][0]['repository'])

    def test_bad_package_and_version_rejected(self):
        for name in ['-x', 'x;echo', '@x/../a', 'x@latest', '_hidden', 'X']:
            with self.subTest(name=name), self.assertRaises(p.PluginShopError):
                catalog([npm_entry(name=name)])
        for version in ['latest', '^1.2.3', '1.2.3;touch x', '01.2.3', '1.2', '1.2.3-01']:
            with self.subTest(version=version), self.assertRaises(p.PluginShopError):
                catalog([npm_entry(version=version)])

    def test_semver_exact_prerelease_is_allowed(self):
        c = catalog([npm_entry(version='1.2.3-rc.1+abc')])
        self.assertEqual(c['candidates'][0]['install_spec'], '@fixture/browser@1.2.3-rc.1+abc')

    def test_integrity_shape_and_length_validated(self):
        for value in ['sha512-short', 'sha512-' + base64.b64encode(b'x').decode(), 'sha1-deadbeef']:
            entry = npm_entry()
            entry['integrity'] = value
            with self.assertRaises(p.PluginShopError):
                catalog([entry])

    def test_github_commit_and_subdirectory_pin(self):
        c = catalog([github_entry(subdir='packages/browser')])['candidates'][0]
        self.assertEqual(c['install_spec'], 'github:fixture/browser#' + SHA + '&path:/packages/browser')
        for subdir in ['../x', 'a/../b', '/x', 'a\\b', 'x;echo']:
            with self.assertRaises(p.PluginShopError):
                catalog([github_entry(subdir=subdir)])

    def test_github_integrity_mismatch_rejected(self):
        entry = github_entry()
        entry['integrity'] = 'b' * 40
        with self.assertRaises(p.PluginShopError):
            catalog([entry])

    def test_tarball_binds_repo_and_hash(self):
        entry = github_entry()
        entry.update(version='v1.2.3', integrity='c' * 64,
                     tarball={'url': 'https://github.com/fixture/browser/releases/download/v1.2.3/pkg.tgz', 'sha256': 'c' * 64})
        c = catalog([entry])['candidates'][0]
        self.assertIn('release_archive_requires_native_inspection', c['blockers'])
        entry['tarball']['url'] = 'https://github.com/evil/browser/releases/download/v1.2.3/pkg.tgz'
        with self.assertRaises(p.PluginShopError):
            catalog([entry])

    def test_release_inspection_never_substitutes_branch_manifest(self):
        entry = github_entry()
        asset = 'https://github.com/fixture/browser/releases/download/v1.2.3/pkg.tgz'
        entry.update(version='v1.2.3', integrity='c' * 64, tarball={'url': asset, 'sha256': 'c' * 64})
        c = catalog([entry])
        url = 'https://api.github.com/repos/fixture/browser/releases/tags/v1.2.3'
        release = {'tag_name': 'v1.2.3', 'assets': [{'browser_download_url': asset, 'digest': 'sha256:' + 'c' * 64}]}
        f = Fixture({url: release})
        result = p.inspect_candidate(c, c['candidates'][0]['id'], transport=f)
        self.assertEqual(result['status'], 'inspected')
        self.assertFalse(result['inspection']['manifest_inspected'])
        self.assertFalse(result['inspection']['artifact_integrity_verified'])
        self.assertEqual(result['inspection']['scripts_status'], 'UNKNOWN_NOT_INSPECTED')
        self.assertIn('exact_manifest_not_inspected', p.create_installation_plan(result)['blockers'])
        self.assertEqual(len(f.calls), 1)
        release['assets'][0]['digest'] = 'sha256:' + 'd' * 64
        with self.assertRaises(p.PluginShopError):
            p.inspect_candidate(c, c['candidates'][0]['id'], transport=Fixture({url: release}))

    def test_test_report_must_keep_approval_request(self):
        c = inspected()
        c = p.transition_candidate(c, 'approved_by_operator', evidence=evidence(c))
        ev = evidence(c, profile='isolated', runtime_version='0.2.0', result='passed', evidence_ref='report', request_id='unapproved')
        with self.assertRaises(p.PluginShopError):
            p.transition_candidate(c, 'test_reported', evidence=ev)

    def test_denied_package_is_not_inspectable(self):
        c = catalog(denied=[{'name': '@fixture/browser', 'detail': 'Fixture denial'}])
        candidate = c['candidates'][0]
        self.assertIn('catalog_denied', p.create_installation_plan(candidate)['blockers'])
        with self.assertRaises(p.PluginShopError):
            p.inspect_candidate(c, candidate['id'], transport=lambda *a: self.fail('No call'))

    def test_catalog_review_never_implies_trust(self):
        entry = npm_entry()
        entry.update(tier='verified', review={'reviewer': 'Someone', 'reviewCommit': SHA, 'notes': 'metadata claim', 'reviewedVersion': '1.2.3'}, stars=999999)
        c = catalog([entry])['candidates'][0]
        self.assertEqual(c['trust']['catalog_tier'], 'verified')
        self.assertEqual(c['trust']['status'], 'UNVERIFIED')
        self.assertEqual(c['compatibility']['status'], 'UNVERIFIED')

    def test_search_results_are_bounded_copies_and_keep_provenance(self):
        c = catalog([npm_entry(), npm_entry('fixture-other')])
        result = p.search_catalog(c, 'playwright', limit=1)
        self.assertEqual(result['total'], 2)
        self.assertEqual(len(result['results']), 1)
        self.assertIn('catalog_sha256', result['results'][0]['provenance'])
        result['results'][0]['name'] = 'changed'
        self.assertNotEqual(c['candidates'][0]['name'], 'changed')
        with self.assertRaises(p.PluginShopError):
            p.search_catalog(c, limit=10000)

    def test_search_spanish_aliases_and_cjk_substrings(self):
        self.assertEqual(p.search_catalog(catalog(), 'navegador')['total'], 1)
        entry = npm_entry()
        entry['catalog']['summary']['en'] = '持久记忆和知识管理'
        self.assertEqual(p.search_catalog(catalog([entry]), '记忆')['total'], 1)

    def test_search_stars_do_not_affect_rank(self):
        a, b = npm_entry('a-browser'), npm_entry('b-browser')
        b['stars'] = 10**9
        result = p.search_catalog(catalog([b, a]), 'browser')
        self.assertEqual(result['results'][0]['name'], 'a-browser')

    def test_inspection_reads_exact_version_and_discloses_scripts(self):
        c = catalog()
        f = Fixture({'https://registry.npmjs.org/%40fixture%2Fbrowser/1.2.3': manifest()})
        result = p.inspect_candidate(c, c['candidates'][0]['id'], transport=f)
        self.assertEqual(result['status'], 'inspected')
        self.assertEqual(result['inspection']['build_script_names'], ['postinstall'])
        self.assertFalse(result['inspection']['artifact_integrity_verified'])
        self.assertFalse(result['inspection']['code_audited'])
        self.assertEqual(c['candidates'][0]['status'], 'proposal')

    def test_inspection_refuses_registry_identity_or_integrity_drift(self):
        c = catalog()
        for kind in ['name', 'version', 'integrity']:
            m = manifest()
            if kind == 'integrity':
                m['dist']['integrity'] = 'sha512-' + base64.b64encode(b'y' * 64).decode()
            else:
                m[kind] = 'other' if kind == 'name' else '1.2.4'
            f = Fixture({'https://registry.npmjs.org/%40fixture%2Fbrowser/1.2.3': m})
            with self.assertRaises(p.PluginShopError):
                p.inspect_candidate(c, c['candidates'][0]['id'], transport=f)

    def test_github_inspection_verifies_blob_hash_at_commit(self):
        c = catalog([github_entry(subdir='packages/browser')])
        raw = encoded(manifest('fixture-browser'))
        wrapper = {'encoding': 'base64', 'content': base64.b64encode(raw).decode(),
                   'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
        url = 'https://api.github.com/repos/fixture/browser/contents/packages/browser/package.json?ref=' + SHA
        result = p.inspect_candidate(c, c['candidates'][0]['id'], transport=Fixture({url: wrapper}))
        self.assertEqual(result['inspection']['metadata_sha256'], hashlib.sha256(raw).hexdigest())
        wrapper['sha'] = 'b' * 40
        with self.assertRaises(p.PluginShopError):
            p.inspect_candidate(c, c['candidates'][0]['id'], transport=Fixture({url: wrapper}))

    def test_network_errors_do_not_leak_remote_exception(self):
        def fail(*args):
            raise RuntimeError('secret-api-key-dont-echo')
        with self.assertRaises(p.PluginShopError) as ctx:
            p.fetch_catalog(transport=fail)
        self.assertNotIn('secret-api-key', str(ctx.exception))

    def test_redirects_are_not_followed(self):
        f = Fixture({BASE + 'index.json': (302, {'Location': 'http://127.0.0.1'}, b'')})
        with self.assertRaisesRegex(p.PluginShopError, 'HTTP 302'):
            p.fetch_catalog(transport=f)
        self.assertEqual(len(f.calls), 1)

    def test_dns_private_addresses_blocked(self):
        with patch.object(socket, 'getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaisesRegex(p.PluginShopError, 'privada'):
                p.fetch_catalog()

    def test_plan_is_dry_run_not_native_execution(self):
        c = inspected()
        with patch('subprocess.run', side_effect=AssertionError('Must never execute')):
            result = p.create_installation_plan(c, request_id='request-one')
        self.assertTrue(result['dry_run'])
        self.assertFalse(result['execution_available'])
        self.assertFalse(result['native_action_performed'])
        self.assertEqual(result['status'], 'PLAN_ONLY')
        self.assertIn('pnpm-workspace.yaml', result['backup']['files'])
        self.assertIn('compatibility.json', result['backup']['files'])
        self.assertTrue(all(check['status'] != 'PASS' for check in result['checks']))
        self.assertFalse(result['runtime_actions'][1]['enabled'])
        self.assertEqual(result['service_tracking']['request_id'], 'request-one')
        self.assertNotIn('requestId', result['runtime_actions'][1])
        self.assertIn('target', result['runtime_actions'][1])
        self.assertNotIn('spec', result['runtime_actions'][1])
        self.assertNotIn('approvedBuilds', result['runtime_actions'][1])

    def test_plan_uninspected_or_existing_package_has_blockers(self):
        c = catalog()['candidates'][0]
        result = p.create_installation_plan(c, runtime={'installed_packages': {c['name']: '0.9.0'}})
        self.assertIn('exact_manifest_not_inspected', result['blockers'])
        self.assertIn('existing_package_requires_explicit_update_review', result['blockers'])

    def test_plan_rejects_profile_paths_runtime_secrets_and_bad_request(self):
        c = inspected()
        for profile in ['../web', '/tmp/profile', 'x; echo', 'x y', '.hidden']:
            with self.assertRaises(p.PluginShopError):
                p.create_installation_plan(c, profile=profile)
        with self.assertRaises(p.PluginShopError):
            p.create_installation_plan(c, runtime={'api_key': 'secret'})
        with self.assertRaises(p.PluginShopError):
            p.create_installation_plan(c, request_id='x; touch foo')

    def test_lifecycle_cannot_skip_or_self_assert_inspection(self):
        c = catalog()['candidates'][0]
        for target in ['inspected', 'approved_by_operator', 'active_reported', 'installed']:
            with self.assertRaises(p.PluginShopError):
                p.transition_candidate(c, target, evidence=evidence(c))

    def test_lifecycle_requires_identity_and_operator_acknowledgement(self):
        c = inspected()
        for changes in [{'version': '99.0.0'}, {'candidate_id': 'other'}, {'entry_sha256': '0'*64}, {'acknowledged': False}, {'operator': ''}, {'api_key': 'x'}]:
            with self.assertRaises(p.PluginShopError):
                p.transition_candidate(c, 'approved_by_operator', evidence=evidence(c, **changes))

    def test_reported_lifecycle_never_claims_actual_installation(self):
        c = inspected()
        c = p.transition_candidate(c, 'approved_by_operator', evidence=evidence(c))
        ev = evidence(c, profile='isolated', runtime_version='0.2.0', result='passed', evidence_ref='test-report.json#sha256=fixture')
        c = p.transition_candidate(c, 'test_reported', evidence=ev)
        c = p.transition_candidate(c, 'active_reported', evidence=ev)
        self.assertEqual(c['status'], 'active_reported')
        self.assertFalse(c['runtime_verified'])
        self.assertFalse(c['installed'])
        self.assertFalse(c['active'])
        self.assertEqual(c['history'][-1]['evidence_kind'], 'OPERATOR_REPORT_UNVERIFIED')

    def test_failed_tests_cannot_be_reported_active(self):
        c = inspected()
        c = p.transition_candidate(c, 'approved_by_operator', evidence=evidence(c))
        ev = evidence(c, profile='isolated', runtime_version='0.2.0', result='failed', evidence_ref='test-report.json')
        c = p.transition_candidate(c, 'test_reported', evidence=ev)
        with self.assertRaises(p.PluginShopError):
            p.transition_candidate(c, 'active_reported', evidence=dict(ev, result='passed'))

    def test_active_report_cannot_change_target(self):
        c = inspected()
        c = p.transition_candidate(c, 'approved_by_operator', evidence=evidence(c))
        ev = evidence(c, profile='isolated', runtime_version='0.2.0', result='passed', evidence_ref='test-report.json')
        c = p.transition_candidate(c, 'test_reported', evidence=ev)
        with self.assertRaises(p.PluginShopError):
            p.transition_candidate(c, 'active_reported', evidence=dict(ev, profile='production'))

    def test_capability_wishlist_links_profiles_tools_and_candidates(self):
        org = {'agents': [{'id': 'qa', 'role': 'QA', 'title': 'Pruebas browser E2E'}]}
        result = p.capability_wishlist(org, catalog(), tool_catalog={'tools': [{'name': 'browser_snapshot', 'description': 'Read a browser page'}]})
        browser = next(g for g in result['gaps'] if g['id'] == 'browser_testing')
        self.assertEqual(browser['required_by_profiles'], ['qa'])
        self.assertIn('browser_snapshot', browser['declared_tools'])
        self.assertEqual(browser['status'], 'RUNTIME_COVERAGE_UNVERIFIED')
        self.assertTrue(browser['candidates'])
        self.assertFalse(result['runtime_verified'])

    def test_empty_catalog_does_not_invent_plugins(self):
        result = p.capability_wishlist({'agents': [{'id': 'qa', 'role': 'QA'}]}, p.empty_catalog())
        self.assertEqual(result['suggestions'], [])
        self.assertTrue(result['gaps'])
        self.assertEqual(p.search_catalog(p.empty_catalog(), 'anything')['total'], 0)


if __name__ == '__main__':
    unittest.main()
