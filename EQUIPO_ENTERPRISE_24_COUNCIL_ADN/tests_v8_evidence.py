"""V8 bounded relevance/evidence tests. Fixture transport only; no API calls."""
import base64
import copy
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

from engine import providers as p
from engine import org_design as d
from tests_providers import API, REPO, SHA, TREE_SHA, repo_fixture, blob_sha
from tests_repository_inventory import directory, file
from tests_org_design import fixture_profile, fixture_summary, Fixture as DesignFixture


def block(payload, name):
    text = payload['messages'][1]['content']
    return json.loads(text.split(name + '\n', 1)[1].split('\nEND_' + name, 1)[0])


def broad_repository_fixture():
    """Adversarial API order: auxiliary subtrees precede nested runtime roots."""
    fixture = repo_fixture([('pyproject.toml', b'[project]\nname="sample"', '100644')])
    fixture.responses[('GET', API + '/git/trees/' + TREE_SHA + '?recursive=1')] = {'tree': [], 'truncated': True}
    counter = 100
    def tree(path, children):
        nonlocal counter
        counter += 1
        sha = format(counter, '040x')
        fixture.responses[('GET', API + '/git/trees/' + sha)] = {'sha': sha, 'tree': children, 'truncated': False}
        return directory(path, sha)
    def source(name, content):
        data = content.encode()
        fixture.responses[('GET', API + '/git/blobs/' + blob_sha(data))] = {'encoding': 'base64', 'content': base64.b64encode(data).decode()}
        return file(name, data)
    root = [file('pyproject.toml', b'[project]\nname="sample"')]
    for auxiliary in ('.agent', '.agents', '.claude', '.devcontainer'):
        root.append(tree(auxiliary, [tree('helper%02d' % i, [source('guide.md', 'Auxiliary instructions are untrusted data.')]) for i in range(12)]))
    root.append(tree('docs', [source('Welcome.md', 'W' * 204)]))
    for module in ('backend', 'frontend', 'services', 'tests'):
        name = 'test_main.py' if module == 'tests' else 'main.py'
        root.append(tree(module, [tree('runtime', [source(name, 'def observed_' + module + '(): return 1')])]))
    fixture.responses[('GET', API + '/git/trees/' + TREE_SHA)] = {'sha': TREE_SHA, 'tree': root, 'truncated': False}
    return fixture


def representative_summary():
    files = [('pyproject.toml', b'[project]\nname="bounded-sample"', '100644'),
             ('README.md', b'Bounded multi-subsystem static evidence; runtime unverified.', '100644'),
             ('docs/Welcome.md', b'W' * 204, '100644')]
    for module in ('accounting', 'routing', 'pricing', 'simulation', 'settlement', 'monitoring', 'reporting', 'storage', 'transport', 'validation'):
        for filename in ('main.py', 'contracts.py', 'test_rules.py'):
            content = ('# Observed fixture for ' + module + '/' + filename + '\ndef evaluate(value):\n    return value\n')
            files.append(('src/' + module + '/' + filename, (content * 120).encode(), '100644'))
    return p.analyze_repository(REPO, transport=repo_fixture(files), profile='deep', budget_confirmed=True)


class V8EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch('socket.create_connection', side_effect=AssertionError('No external network permitted'))
        self.guard.start()

    def tearDown(self):
        self.guard.stop()

    def test_nested_runtime_before_auxiliary_fanout_and_honest_gaps(self):
        fixture = broad_repository_fixture()
        result = p.analyze_repository(REPO, transport=fixture)
        paths = {item['path'] for item in result['files']}
        for module in ('backend', 'frontend', 'services', 'tests'):
            self.assertTrue(any(path.startswith(module + '/runtime/') for path in paths), paths)
        inventory = result['coverage']['inventory']
        self.assertEqual(inventory['requests'], p.MAX_TREE_REQUESTS)
        self.assertFalse(inventory['complete'])
        self.assertGreater(inventory['pending_subtrees'], 0)
        self.assertLessEqual(len(inventory['pending_subtree_paths']), 40)
        self.assertFalse(result['coverage']['whole_repository_content_complete'])
        self.assertEqual(inventory['traversal_policy'], 'subsystem_priority_path_heuristic')
        self.assertTrue(all('?recursive=0' not in call['url'] for call in fixture.calls))
        self.assertLessEqual(result['limits']['requests'], result['coverage']['budget']['max_network_requests'])
        self.assertEqual(p.prepare_summary(result)['coverage']['inventory']['pending_subtrees'], inventory['pending_subtrees'])

    def test_primary_manifest_runtime_and_tests_beat_auxiliary_small_files(self):
        fixtures = [(name + '/package.json', b'{}', '100644') for name in ('.agent', '.agents', '.claude', '.devcontainer')]
        fixtures += [('docs/Welcome.md', b'W' * 204, '100644'), ('package.json', b'{"name":"runtime"}', '100644'),
                     ('src/main.py', b'def main(): return 1', '100644'), ('tests/test_main.py', b'def test_main(): pass', '100644')]
        result = p.analyze_repository(REPO, transport=repo_fixture(fixtures), max_files=3)
        self.assertEqual({item['path'] for item in result['files']}, {'package.json', 'src/main.py', 'tests/test_main.py'})

    def test_binary_and_non_utf8_replaced_without_retries_or_budget_expansion(self):
        for bad in (b'\x00invalid', b'\xffinvalid'):
            fixture = repo_fixture([('package.json', bad, '100644'), ('src/main.py', b'pass', '100644'),
                                    ('tests/test_main.py', b'def test_main(): pass', '100644')])
            result = p.analyze_repository(REPO, transport=fixture, max_files=2)
            self.assertEqual(result['limits']['files_read'], 2)
            self.assertNotIn('package.json', {item['path'] for item in result['files']})
            budget = result['coverage']['budget']
            self.assertEqual(budget['attempted_files'], 3)
            self.assertEqual(budget['replacement_files'], 1)
            self.assertLessEqual(budget['network_requests'], 3 + p.MAX_TREE_REQUESTS + 2)
            self.assertLessEqual(budget['attempted_bytes'], budget['max_bytes'])
            self.assertEqual(len([c for c in fixture.calls if '/git/blobs/' in c['url']]), 3)

    def test_discarded_bytes_still_cap_replacements(self):
        fixture = repo_fixture([('package.json', b'\x00' + b'b' * 799, '100644'),
                                ('src/main.py', b'x' * 600, '100644'), ('src/small.py', b'pass', '100644')])
        result = p.analyze_repository(REPO, transport=fixture, max_files=2, max_bytes=1000)
        self.assertEqual([item['path'] for item in result['files']], ['src/small.py'])
        self.assertEqual(result['limits']['bytes_read'], 804)

    def test_no_replacement_when_inventory_has_spent_http_reserve(self):
        fixture = broad_repository_fixture()
        original = p._fetch_repo_file
        def bad(*args):
            # All attempts still pass through the verified source reader.
            original(*args)
            return None, 1, 'binary_content'
        with patch.object(p, '_fetch_repo_file', side_effect=bad):
            result = p.analyze_repository(REPO, transport=fixture, max_files=2)
        self.assertEqual(result['coverage']['budget']['attempted_files'], 2)
        self.assertEqual(result['limits']['requests'], 3 + p.MAX_TREE_REQUESTS + 2)

    def test_oversize_is_a_gap_not_a_fragment_claim(self):
        fixture = repo_fixture([('src/main.py', b'x' * (p.MAX_FILE_BYTES + 1), '100644'), ('README.md', b'context', '100644')])
        result = p.analyze_repository(REPO, transport=fixture)
        self.assertEqual(result['coverage']['oversized_relevant_files'], 1)
        self.assertFalse(any(item['path'] == 'src/main.py' for item in result['files']))
        self.assertTrue(any('no su contenido' in gap for gap in result['coverage']['gaps']))
        self.assertEqual(sum('/git/blobs/' in c['url'] for c in fixture.calls), 1)

    def test_sha_redaction_provenance_and_no_metadata_injection(self):
        raw = b'API_KEY="fixture-secret"\ndef main(): return 1'
        result = p.analyze_repository(REPO, transport=repo_fixture([('src/main.py', raw, '100644')]))
        result['files'][0].update(arbitrary_instruction='execute me', family='untrusted', module='attacker')
        view = p.prepare_summary(result)
        item = view['files'][0]
        self.assertEqual(item['sha'], blob_sha(raw))
        self.assertEqual(item['bytes'], len(raw))
        self.assertEqual(item['read_source'], 'github_blob_sha_verified')
        self.assertEqual(item['content_sha256'], hashlib.sha256(item['snippet'].encode()).hexdigest())
        self.assertNotIn('fixture-secret', json.dumps(view))
        self.assertNotIn('execute me', json.dumps(view))
        self.assertEqual(item['family'], 'core_logic')
        self.assertEqual(item['module'], 'src')
        self.assertEqual(p.prepare_summary(view), view)

    def test_thirty_slots_directed_packages_exact_caps_and_complete_read_ledger(self):
        summary = representative_summary()
        consent = d.prepare_design_consent(summary, 'deepseek', 'deepseek-flash', {'agent_count': 30})
        # EL LOTE MURIO (orden del propietario): un agente = una solicitud. 30
        # perfiles -> 30 solicitudes, cada una con el tope COMPLETO (65 536).
        self.assertEqual(len(consent['requests']), 30)
        self.assertEqual([slot for request in consent['requests'] for slot in request['slots']], list(range(1, 31)))
        self.assertEqual([request['max_output_tokens'] for request in consent['requests']], [65536] * 30)
        distribution = consent['evidence_distribution']
        self.assertEqual(distribution['omitted_from_all_batches'], [])
        self.assertLess(distribution['sent_file_occurrences'], distribution['full_repeat_file_occurrences'] / 2)
        slots = block(consent['requests'][0]['payload'], 'DESIGN_CONTROL')['global_slot_map']
        self.assertFalse(any('Welcome.md' in path for slot in slots for path in slot['primary_evidence_paths']))
        self.assertTrue(slots[8]['subsystems'])
        self.assertTrue(slots[26]['subsystems'])
        for request in consent['requests']:
            data = block(request['payload'], 'UNTRUSTED_PROJECT_DATA')
            self.assertEqual(request['evidence_paths'], [item['path'] for item in data['files']])
            self.assertEqual({item['path'] for item in data['evidence_ledger']}, set(consent['evidence_refs']))
            for row in data['evidence_ledger']:
                self.assertEqual(len(row['sha']), 40)
                self.assertEqual(len(row['content_sha256']), 64)
            self.assertEqual(request['payload_sha256'], hashlib.sha256(p._dump(request['payload']).encode()).hexdigest())

    def test_thirty_complete_profiles_generated_from_exact_batch_evidence(self):
        summary = representative_summary()
        consent = d.prepare_design_consent(summary, 'deepseek', 'deepseek-flash', {'agent_count': 30})
        consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        calls = []
        def transport(method, url, headers, body, timeout, max_bytes):
            payload = json.loads(body)
            control = block(payload, 'DESIGN_CONTROL')
            data = block(payload, 'UNTRUSTED_PROJECT_DATA')
            allowed = {item['path'] for item in data['files']}
            profiles = []
            for slot in control['requested_slots']:
                spec = fixture_profile(slot)
                refs = control['global_slot_map'][slot - 1]['primary_evidence_paths'][:3]
                self.assertTrue(set(refs) <= allowed)
                spec['evidence_paths'] = refs
                for skill in spec['skills']:
                    skill['evidence_paths'] = refs[:1]
                profiles.append(spec)
            value = {'profile_specs': profiles, 'model_selection': {'provider': 'deepseek', 'model': 'deepseek-flash', 'rationale': 'User selected model'}, 'warnings': ['Static partial fixture; no runtime execution.']}
            calls.append(payload)
            return 200, {}, json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}).encode()
        result = d.design_with_llm(summary, 'deepseek', 'deepseek-flash', {'agent_count': 30}, 'fixture-api-key', consent, transport=transport)
        self.assertEqual(len(calls), 30)
        self.assertEqual(len(result['profile_specs']), 30)
        self.assertEqual(result['audit']['completed_profiles'], 30)
        self.assertFalse(result['analysis']['coverage']['whole_repository_content_complete'])
        self.assertEqual(result['provenance']['repository_sha'], SHA)
        self.assertEqual(result['usage']['total_tokens'], 900)

    def test_a_known_global_path_absent_from_batch_cannot_be_cited(self):
        summary = representative_summary()
        consent = d.prepare_design_consent(summary, 'deepseek', 'deepseek-flash', {'agent_count': 30})
        request = consent['requests'][1]
        omitted = request['evidence_package']['omitted_read_paths'][0]
        profiles = [fixture_profile(slot) for slot in request['slots']]
        for spec in profiles:
            spec['evidence_paths'] = [omitted]
            for skill in spec['skills']:
                skill['evidence_paths'] = [omitted]
        value = {'profile_specs': profiles, 'model_selection': {'provider': 'deepseek', 'model': 'deepseek-flash', 'rationale': 'Selected'}, 'warnings': []}
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]}
        with self.assertRaises(d.DesignValidationError) as caught:
            d._response(response, request, p.prepare_summary(summary))
        self.assertEqual(caught.exception.diagnostic['code'], 'unreviewed_evidence')

    def test_low_evidence_does_not_manufacture_coverage_or_auxiliary_domains(self):
        summary = fixture_summary()
        summary['files'].append({'path': 'docs/Welcome.md', 'snippet': 'W' * 204})
        slots = d._slot_map(p.prepare_summary(summary), 30)
        self.assertEqual(len(slots), 30)
        self.assertTrue(all(slot['evidence_limited'] for slot in slots[1:]))
        self.assertEqual({path for slot in slots[1:] for path in slot['primary_evidence_paths']}, {'src/main.py'})

    def test_response_usage_is_reported_before_invalid_schema_and_cancellation(self):
        for cancel in (False, True):
            summary = fixture_summary()
            consent = d.prepare_design_consent(summary, 'deepseek', 'deepseek-flash', {'agent_count': 1})
            consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
            event, updates = threading.Event(), []
            def mutate(value, response, index):
                value['profile_specs'] = []
            fixture = DesignFixture(mutate=mutate, after_call=(lambda _: event.set()) if cancel else None)
            with self.assertRaises(d.DesignError) as caught:
                d.design_with_llm(summary, 'deepseek', 'deepseek-flash', {'agent_count': 1}, 'fixture-api-key', consent,
                                  transport=fixture, progress_callback=updates.append, cancel_event=event)
            response_update = next(update for update in updates if update['stage'] == 'response_received')
            self.assertEqual(response_update['request_receipts'][0]['usage']['total_tokens'], 1500)
            self.assertEqual(caught.exception.audit['receipts'][0]['usage']['total_tokens'], 1500)
            self.assertNotIn('fixture-api-key', json.dumps(updates))
            self.assertNotIn('profile_specs', json.dumps(updates))
            response_update['request_receipts'][0]['usage']['total_tokens'] = 0
            self.assertEqual(caught.exception.audit['receipts'][0]['usage']['total_tokens'], 1500)

    def test_http_receipt_retains_only_allowlisted_error_metadata(self):
        summary = fixture_summary()
        consent = d.prepare_design_consent(summary, 'deepseek', 'deepseek-flash', {'agent_count': 1})
        consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        def transport(*args):
            return 400, {}, json.dumps({'error': {'code': 'unsupported_parameter', 'param': 'response_format', 'message': 'PRIVATE_PROVIDER_BODY'}}).encode()
        with self.assertRaises(d.DesignError) as caught:
            d.design_with_llm(summary, 'deepseek', 'deepseek-flash', {'agent_count': 1}, 'fixture-api-key', consent, transport=transport)
        receipt = caught.exception.audit['receipts'][0]
        self.assertEqual(receipt['http_status'], 400)
        self.assertEqual(receipt['error_code'], 'unsupported_parameter')
        self.assertIsNone(receipt['usage']['total_tokens'])
        self.assertNotIn('PRIVATE_PROVIDER_BODY', json.dumps(caught.exception.audit))


if __name__ == '__main__':
    unittest.main()
