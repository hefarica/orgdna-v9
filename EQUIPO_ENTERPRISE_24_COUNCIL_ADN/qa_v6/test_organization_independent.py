"""Independent proposal/inheritance checks; fictional agents, no execution."""
import copy
import unittest
from engine.core import generate_organization,apply_organization_edits,validate_organization
from engine.organization_design import derive_design_reports
from engine.tool_permissions import apply_tool_policy,tool_recommendation,get_tool_catalog

class IndependentOrganizationTests(unittest.TestCase):
    def test_manual_tree_and_deny_survive_explicit_revision(self):
        org=generate_organization({'agent_count':28,'max_direct_reports':3,'identity_mode':'new'})
        org=apply_organization_edits(org,{'expected_state_version':org['state_version'],'hierarchy_mode':'manual'})
        aid=org['agents'][4]['id']
        org=apply_tool_policy(org,{'expected_state_version':org['state_version'],'agent_id':aid,'allow':['ops_plan'],'deny':['ops_status']})
        before={a['id']:(a['reports_to'],a['direct_reports'],a['depth']) for a in org['agents']}
        config=dict(org['config'],identity_mode='revision',organization_id=org['organization_id'],dna_revision=org['dna_revision']+1)
        revised=generate_organization(config,previous_organization=org)
        self.assertEqual(before,{a['id']:(a['reports_to'],a['direct_reports'],a['depth']) for a in revised['agents']})
        self.assertEqual(revised['config']['hierarchy_mode'],'manual')
        self.assertTrue(validate_organization(revised)['valid'])
        agent=next(a for a in revised['agents'] if a['id']==aid)
        self.assertEqual(agent['tool_policy']['deny'],['ops_status']);self.assertEqual(agent['tool_policy']['allow'],['ops_plan'])
        proposal=tool_recommendation(agent)
        self.assertEqual(proposal['effective_deny'],['ops_status']);self.assertTrue(proposal['manual_override_preserved'])
        self.assertEqual(next(r for r in proposal['tool_rationales'] if r['name']=='ops_status')['status'],'DENIED_BY_POLICY')
    def test_imported_manual_roster_preserves_original_ids_on_revision(self):
        from engine.core import export_recipe
        original=generate_organization({'agent_count':28})
        recipe=export_recipe(original)
        imported=generate_organization({'agent_count':28,'identity_mode':'import_legacy'},base_recipe=recipe)
        imported=apply_organization_edits(imported,{'expected_state_version':imported['state_version'],'hierarchy_mode':'manual'})
        config=dict(imported['config'],identity_mode='revision',organization_id=imported['organization_id'],dna_revision=imported['dna_revision']+1)
        revised=generate_organization(config,previous_organization=imported)
        self.assertEqual([a['id'] for a in revised['agents']],[a['id'] for a in original['agents']])
        self.assertEqual({a['id']:a['reports_to'] for a in revised['agents']},{a['id']:a['reports_to'] for a in imported['agents']})
        self.assertEqual(export_recipe(revised)['squad']['id'],recipe['squad']['id'])
    def test_manual_revision_membership_change_requires_explicit_edit(self):
        org=generate_organization({'agent_count':28,'identity_mode':'new'})
        org=apply_organization_edits(org,{'expected_state_version':org['state_version'],'hierarchy_mode':'manual'})
        config=dict(org['config'],identity_mode='revision',organization_id=org['organization_id'],dna_revision=org['dna_revision']+1,agent_count=30,council_concurrency=30)
        with self.assertRaisesRegex(ValueError,'mismas identidades'):generate_organization(config,previous_organization=org)
    def test_recommendations_and_subteams_use_current_ids_without_permission_grants(self):
        known={t['name'] for t in get_tool_catalog()['tools']}
        for n in (28,30):
            org=generate_organization({'agent_count':n,'template':'generic','repo_name':'Independent fixture'})
            ids={a['id'] for a in org['agents']};before=copy.deepcopy(org)
            for agent in org['agents']:
                r=tool_recommendation(agent)
                self.assertEqual(r['agent_id'],agent['id']);self.assertTrue(r['proposal_does_not_override_policy'])
                self.assertFalse(r['runtime_verified']);self.assertEqual(r['runtime_availability'],'UNKNOWN')
                self.assertTrue(set(r['allow_candidates'])<=known)
            self.assertEqual(org,before)
            for team in org['functional_subteam_proposals']:
                self.assertTrue(set(team['member_ids'])<=ids);self.assertFalse(team['auto_execute']);self.assertFalse(team['human_profiling'])
    def test_shared_evidence_is_reported_without_false_uniqueness(self):
        org=generate_organization({'agent_count':3})
        for agent in org['agents']:
            agent['evidence_paths']=['README.md'];agent['mission']='Same declared mission';agent['skills']=[{'name':'Same specialty','source':'static_fixture'}]
        report=derive_design_reports(org)['profile_differentiation']
        self.assertFalse(report['global_uniqueness_claimed']);self.assertFalse(report['credentials_verified'])
        self.assertEqual({g['kind'] for g in report['gaps']},{'shared_evidence','duplicate_mission','duplicate_specialties'})
    def test_topology_is_acyclic_with_one_owner_and_bounded_span(self):
        for n in (1,28,30,32):
            for span in (1,3,5,8):
                org=generate_organization({'agent_count':n,'max_direct_reports':span});byid={a['id']:a for a in org['agents']}
                self.assertEqual(sum(a['reports_to']=='OWNER_EXTERNAL' for a in org['agents']),1)
                for a in org['agents']:
                    self.assertLessEqual(len(a['direct_reports']),span);seen=set();node=a
                    while node['reports_to']!='OWNER_EXTERNAL':
                        self.assertNotIn(node['id'],seen);seen.add(node['id']);node=byid[node['reports_to']]

if __name__=='__main__':unittest.main()
