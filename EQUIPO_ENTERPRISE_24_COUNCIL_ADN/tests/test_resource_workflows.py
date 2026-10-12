"""Deterministic/offline tests. No network, real secrets or external execution."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from engine import resource_workflows as w
from engine.capability_library import CapabilityLibrary


def org(n=3):
    roles = ['Ingeniería de datos', 'QA calidad', 'IA modelos']
    return {'organization_id': 'fixture-org', 'state_version': 4,
            'agents': [{'id': 'a' + str(i), 'role': roles[i % 3], 'mission': 'Diseñar entregables verificables'} for i in range(n)]}


def answer(payload, mutate=None):
    data = json.loads(payload['messages'][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    value = {'workflows': [{'agent_id': a['id'], 'objective': 'Proponer un lote verificable',
                            'prerequisites': ['Verificar el contrato antes de preparar el adaptador'],
                            'steps': ['Diseñar una prueba independiente'], 'deliverables': ['manifest.json'],
                            'acceptance_tests': ['Revisar esquema y cobertura'],
                            'source_ids': [data['sources'][0]['source_id']]} for a in data['agents']]}
    if mutate:
        mutate(value)
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(value)}}]}


class ResourceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.organization = org()
        self.reference = w.datainventor_research_reference()

    def consent(self, **kw):
        consent = w.prepare_workflow_consent(self.organization, self.reference, 'deepseek', 'deepseek-flash', **kw)
        consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        return consent

    def run_ai(self, consent, **kw):
        return w.workflows_with_llm(self.organization, self.reference, 'deepseek', 'deepseek-flash', 'fixture-key-not-real', consent, **kw)

    def test_baseline_tangible_distinct_roles_no_api(self):
        before = copy.deepcopy((self.organization, self.reference))
        with patch.object(w.p, '_request', side_effect=AssertionError('No API')):
            result = w.baseline_resource_workflows(self.organization, self.reference)
        self.assertEqual(result['mode'], 'deterministic')
        self.assertEqual(result['audit']['requests'], 0)
        self.assertIn('no generado por IA', result['mode_notice'])
        plans = [a['workflow'] for a in result['agents']]
        self.assertEqual(len(set(p['objective'] for p in plans)), 3)
        self.assertIn('dataset.jsonl', plans[0]['deliverables'])
        self.assertIn('manifest.json', plans[0]['deliverables'])
        self.assertIn('quality-report.json', plans[0]['deliverables'])
        self.assertTrue(all(p['acceptance_tests'] and p['prerequisites'] for p in plans))
        self.assertEqual((self.organization, self.reference), before)
        self.assertFalse(result['active'])

    def test_research_snapshot_never_claims_live_backend(self):
        self.assertFalse(self.reference['live_fetch_performed'])
        self.assertEqual(self.reference['source_kind'], 'research_snapshot')
        plan = w.baseline_resource_workflows(self.organization, self.reference)['agents'][0]['workflow']
        self.assertEqual(plan['source_version']['backend_version'], 'unknown')
        self.assertEqual(plan['source_version']['backend_license'], 'unknown')
        self.assertEqual(plan['source_version']['api_contract'], 'unknown')
        self.assertIn('sólo versiona la envoltura', plan['source_version']['note'])
        self.assertFalse(plan['limits']['execution_authorized'])
        self.assertIsNone(plan['limits']['currency_budget'])

    def test_startup_gate_blocks_dependent_tasks_until_verified_install_and_acceptance(self):
        result = w.baseline_resource_workflows(self.organization, self.reference)
        gates = [row['workflow']['startup_gate'] for row in result['agents']]
        self.assertEqual(len({g['configuration_namespace'] for g in gates}), 3)
        for gate in gates:
            self.assertEqual(gate['trigger'], 'dsh_startup_before_tasks')
            self.assertEqual(gate['status'], 'pending_integration')
            self.assertEqual(gate['blocking_scope'], 'dependent_tasks')
            self.assertEqual(gate['installed_capability_status'], 'unverified')
            self.assertEqual(gate['configuration_status'], 'not_persisted')
            self.assertEqual(gate['acceptance_status'], 'not_run')
            self.assertIn('namespaced_configuration_persisted', gate['ready_requires'])
            self.assertIn('independent_acceptance_pass', gate['ready_requires'])
            self.assertEqual(gate['steps'], w._STARTUP_STEPS)
            self.assertIsNone(gate['installer'])
            self.assertFalse(gate['execution_authorized'])
        content = result['item_proposals'][0]['content']
        self.assertIn('Al arrancar en DSH, aplicar primero startup_gate', content)
        self.assertIn('no iniciar tareas dependientes', content)
        again = w.baseline_resource_workflows(self.organization, self.reference)
        self.assertEqual(gates[0]['configuration_namespace'], again['agents'][0]['workflow']['startup_gate']['configuration_namespace'])

    def test_generic_reference_does_not_claim_datainventor(self):
        ref = copy.deepcopy(self.reference); ref['source_url'] = 'https://example.org/reference'
        plan = w.baseline_resource_workflows(self.organization, ref)['agents'][0]['workflow']
        self.assertNotIn('wrapper_commit', plan['source_version'])

    def test_reference_requires_observed_hash_and_existing_agent_ids(self):
        for ref in ({}, dict(self.reference, source_hash='bad'), dict(self.reference, item_proposals=[]),
                    dict(self.reference, source_url='http://example.org'), dict(self.reference, source_url='https://example.org/?secret=value')):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                w.baseline_resource_workflows(self.organization, ref)
        with self.assertRaises(ValueError):
            w.baseline_resource_workflows(self.organization, self.reference, ['stale-agent'])

    def test_library_import_assign_and_activate_are_separate(self):
        result = w.baseline_resource_workflows(self.organization, self.reference, ['a0'])
        with tempfile.TemporaryDirectory() as tmp:
            lib = CapabilityLibrary(Path(tmp) / 'cap.sqlite', 'fixture')
            lib.import_items(result['item_proposals'], 0, 'import')
            self.assertEqual(lib.status()['active_count'], 0)
            ids = result['agent_item_ids']['a0']
            preview = lib.preview(self.organization, ids, {'mode': 'selected', 'agent_ids': ['a0']}, 'activate', 1)
            lib.apply(self.organization, preview, 'activate')
            context = lib.active_context(self.organization, 'a0')
            self.assertIn('dataset.jsonl', json.dumps(context))
            self.assertIn('startup_gate', context['text'])
            self.assertIn('pending_integration', context['text'])
            self.assertIn('no iniciar tareas dependientes', context['text'])
            self.assertIn('evaluación canónica', json.dumps(context, ensure_ascii=False))
            self.assertFalse(lib.read_items(ids)[0]['runtime_verified'])

    def test_exact_consent_and_provider_mutations_block_before_call(self):
        for key in ('model', 'provider', 'endpoint', 'source_hash', 'reference_sha256', 'target_sha256', 'payload_sha256', 'approval_id', 'max_requests'):
            consent = self.consent(); consent[key] = 'changed'
            with self.subTest(key=key), patch.object(w.p, '_request') as call:
                with self.assertRaises(w.p.ConsentRequired): self.run_ai(consent)
                call.assert_not_called()

    def test_changed_source_or_role_requires_new_consent(self):
        consent = self.consent()
        self.reference['item_proposals'][0]['provenance']['evidence'] += ' Updated'
        with patch.object(w.p, '_request') as call:
            with self.assertRaises(w.p.ConsentRequired): self.run_ai(consent)
            call.assert_not_called()
        consent = self.consent(); self.organization['agents'][0]['role'] = 'Changed'
        with patch.object(w.p, '_request') as call:
            with self.assertRaises(w.p.ConsentRequired): self.run_ai(consent)
            call.assert_not_called()

    def test_ai_uses_exact_provider_and_keeps_immutable_gates(self):
        consent = self.consent()
        with patch.object(w.p, '_request', side_effect=lambda *a, **kw: answer(kw['payload'])) as call:
            result = self.run_ai(consent)
        self.assertEqual(result['mode'], 'ai')
        self.assertEqual(call.call_args.args[1], consent['endpoint'])
        self.assertEqual(call.call_args.kwargs['payload']['model'], 'deepseek-flash')
        self.assertFalse(result['runtime_verified'])
        self.assertNotIn('fixture-key-not-real', json.dumps(result))
        for a in result['agents']:
            self.assertEqual(a['workflow']['guardrails'], w._GUARDRAILS)
            self.assertEqual(a['workflow']['startup_gate']['steps'], w._STARTUP_STEPS)
            self.assertEqual(a['workflow']['startup_gate']['status'], 'pending_integration')
            self.assertTrue(set(w._REQUIREMENTS) <= set(a['workflow']['prerequisites']))
            self.assertTrue(set(w._TESTS) <= set(a['workflow']['acceptance_tests']))

    def test_response_rejects_unknown_sources_agents_tools_and_runtime_claims(self):
        mutations = [lambda v: v['workflows'][0].update(agent_id='fake'),
                     lambda v: v['workflows'][0].update(source_ids=['fake']),
                     lambda v: v['workflows'][0].update(runtime_verified=True),
                     lambda v: v['workflows'][0].update(objective='Plugin instalado'),
                     lambda v: v['workflows'][0].update(steps=['Consultar /predict']),
                     lambda v: v['workflows'][0].update(steps=['curl https://example.org']),
                     lambda v: v['workflows'][0].update(steps=[]),
                     lambda v: v['workflows'].pop(), lambda v: v.update(extra='bad')]
        for mutation in mutations:
            with self.subTest(mutation=mutation), patch.object(w.p, '_request', side_effect=lambda *a, **kw: answer(kw['payload'], mutation)):
                with self.assertRaises(w.WorkflowError): self.run_ai(self.consent())

    def test_cancel_stale_and_no_partial_batches(self):
        self.organization = org(8)
        for kind in ('cancel', 'org', 'reference'):
            consent = self.consent(); changed = threading.Event()
            def fake(*a, **kw):
                changed.set(); return answer(kw['payload'])
            kwargs = {'cancel_check': changed.is_set} if kind == 'cancel' else {
                'current_organization' if kind == 'org' else 'current_reference': lambda: {} if changed.is_set() else (self.organization if kind == 'org' else self.reference)}
            with self.subTest(kind=kind), patch.object(w.p, '_request', side_effect=fake) as call:
                with self.assertRaises(w.WorkflowError) as exc: self.run_ai(consent, **kwargs)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(exc.exception.status, 'CANCELLED' if kind == 'cancel' else 'STALE')
                self.assertNotIn('agents', exc.exception.audit)

    def test_failure_spends_consent_and_never_retries(self):
        consent = self.consent()
        with patch.object(w.p, '_request', side_effect=RuntimeError('hidden upstream message')) as call:
            with self.assertRaises(w.WorkflowError) as exc: self.run_ai(consent)
            self.assertNotIn('hidden', str(exc.exception))
            with self.assertRaises(w.p.ConsentRequired): self.run_ai(consent)
            self.assertEqual(call.call_count, 1)

    def test_batch_bounds_and_context_preview(self):
        self.organization = org(32)
        consent = self.consent()
        self.assertEqual(consent['planned_requests'], 8)
        self.assertEqual(len(consent['preview']['agents']), 32)
        self.assertIn('evidence', consent['preview']['sources'][0])
        with self.assertRaises(ValueError): self.consent(max_requests=1)
        with self.assertRaises(ValueError): self.consent(max_output_tokens=True)

    def test_secret_in_reference_rejected_without_transmission(self):
        self.reference['item_proposals'][0]['provenance']['evidence'] = 'Bearer ' + 'X' * 30
        with patch.object(w.p, '_request') as call:
            with self.assertRaises(ValueError): self.consent()
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
