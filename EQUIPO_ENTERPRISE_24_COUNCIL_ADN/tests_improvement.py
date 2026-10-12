"""Offline improvement contracts. Synthetic records, no API or cloud spend."""
import copy
import json
import unittest
from engine import improvement as i, org_design as d
from engine.core import generate_organization
from tests_org_design import fixture_profile, fixture_summary, Fixture


def organization():
    profiles = [fixture_profile(1)]
    analysis = d._analysis(fixture_summary(), profiles, 'deepseek', 'deepseek-flash', [])
    return generate_organization({'agent_count': 1}, analysis=analysis, profile_specs=profiles)


def result(org):
    agent = org['agents'][0]
    row = {'id': 'run-fixture-1', 'status': 'fail', 'organization_id': org['organization_id'],
           'organization_sha256': i.digest(org), 'agent_id': agent['id'], 'agent_sha256': i.digest(agent),
           'task_id': 'task-1', 'skill_ids': [agent['skills'][0]['id']], 'source_sha256': 'a'*64,
           'source_unchanged': True, 'machine_execution_observed': True, 'tests_run': 3, 'exit_code': 1,
           'reason': 'tests_failed', 'stdout': 'TOP_SECRET_LOG', 'stderr': 'TOP_SECRET_TRACE',
           'tested_scope': {'argv': ['/private/local/python', 'secret-path']}}
    row['artifact_result_sha256'] = i.digest(row)
    return row


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.org = organization()
        self.run = result(self.org)
        self.feedback = i.build_feedback_package([self.run], self.org)
        self.context = {'organization': self.org, 'feedback': self.feedback}

    def test_allowlist_and_hypothesis(self):
        serialized = json.dumps(self.feedback)
        for private in ('TOP_SECRET', '/private/local', 'secret-path', 'argv', 'stderr'):
            # Policy itself names stderr; raw data and command names must be absent.
            if private != 'stderr': self.assertNotIn(private, serialized)
        self.assertFalse(self.feedback['evaluations'][0]['skill_deficiency_established'])
        self.assertEqual(self.feedback['targets'][0]['kind'], 'test_failure_observed')
        self.assertTrue(self.feedback['targets'][0]['retest_criteria'])

    def test_tamper_and_version_and_source_block(self):
        for change in ({'exit_code': 0}, {'agent_sha256': 'f'*64}, {'organization_id': 'other'},
                       {'machine_execution_observed': False}, {'source_unchanged': False}):
            row = copy.deepcopy(self.run); row.update(change)
            if 'exit_code' not in change:
                row['artifact_result_sha256'] = i.digest({k:v for k,v in row.items() if k != 'artifact_result_sha256'})
            with self.assertRaises(i.ImprovementError): i.build_feedback_package([row], self.org)
        with self.assertRaises(i.ImprovementError): i.build_feedback_package([self.run], self.org, 'b'*64)
        with self.assertRaises(i.ImprovementError): i.revision_view(self.context, 2)

    def test_pass_is_not_invented_gap(self):
        row = copy.deepcopy(self.run); row['status'] = 'pass'
        row['artifact_result_sha256'] = i.digest({k:v for k,v in row.items() if k != 'artifact_result_sha256'})
        with self.assertRaises(i.ImprovementError): i.build_feedback_package([row], self.org)

    def test_consent_binds_feedback_and_refuses_stale(self):
        plan = d.prepare_design_consent(fixture_summary(), 'deepseek', 'deepseek-flash', {'agent_count': 1}, revision_context=self.context)
        self.assertEqual(plan['improvement_summary'], self.feedback)
        content = plan['requests'][0]['payload']['messages'][1]['content']
        self.assertIn('UNTRUSTED_REVISION_CONTEXT', content)
        self.assertNotIn('TOP_SECRET', content)
        ordinary = d.prepare_design_consent(fixture_summary(), 'deepseek', 'deepseek-flash', {'agent_count': 1})
        self.assertNotEqual(ordinary['payload_sha256'], plan['payload_sha256'])
        ordinary.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        fixture = Fixture()
        with self.assertRaises(Exception):
            d.design_with_llm(fixture_summary(), 'deepseek', 'deepseek-flash', {'agent_count': 1}, 'fixture-key', ordinary,
                              transport=fixture, revision_context=self.context)
        self.assertEqual(fixture.calls, [])

    def test_model_correction_preserves_names_and_retest_proposal(self):
        plan = d.prepare_design_consent(fixture_summary(), 'deepseek', 'deepseek-flash', {'agent_count': 1}, revision_context=self.context)
        plan.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        def change(value, response, idx):
            spec = value['profile_specs'][0]
            spec['name'] = 'P01_Renamed'; spec['display_name'] = 'Nombre alternativo'
            spec['responsibilities'][0] = 'Reproducir el fallo observado con un caso mínimo y contrastar prueba y entorno.'
        revised = d.design_with_llm(fixture_summary(), 'deepseek', 'deepseek-flash', {'agent_count': 1}, 'fixture-key', plan,
                                   transport=Fixture(mutate=change), revision_context=self.context)
        self.assertEqual(revised['profile_specs'][0]['name'], self.org['agents'][0]['name'])
        self.assertEqual(revised['profile_specs'][0]['display_name'], self.org['agents'][0]['display_name'])
        candidate = copy.deepcopy(self.org)
        candidate['agents'][0]['responsibilities'] = revised['profile_specs'][0]['responsibilities']
        candidate['agents'][0]['tool_policy'] = {'dangerous': True}
        proposal = i.finalize_proposal(self.org, candidate, self.feedback)
        self.assertEqual(candidate['agents'][0]['tool_policy'], self.org['agents'][0]['tool_policy'])
        self.assertEqual(proposal['status'], 'proposed'); self.assertFalse(proposal['skills_verified'])
        self.assertTrue(proposal['diff']); self.assertTrue(proposal['retest_plan'])

    def test_warning_only_rejected(self):
        # Stored runtime profile adds supervisory responsibilities; make comparison exact.
        org = copy.deepcopy(self.org)
        spec = fixture_profile(1)
        org['agents'][0]['responsibilities'] = spec['responsibilities']
        org['agents'][0]['deliverables'] = spec['deliverables']
        org['agents'][0]['skills'] = spec['skills']
        with self.assertRaises(i.ImprovementError): i.validate_target_changes([spec], org, self.feedback)

    def test_source_anchor_mismatch(self):
        org = copy.deepcopy(self.org); org.setdefault('provenance', {})['repository_sha'] = 'a'*40
        i.validate_source_baseline(fixture_summary(), org)
        org['provenance']['repository_sha'] = 'b'*40
        with self.assertRaises(i.ImprovementError): i.validate_source_baseline(fixture_summary(), org)

if __name__ == '__main__': unittest.main()
