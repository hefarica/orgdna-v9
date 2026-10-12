"""Offline structural quality regression; no providers, install, or live execution."""
import copy
import unittest
import uuid
from engine.core import generate_organization, apply_organization_edits, validate_organization, _rebuild_derived
from engine.organization_design import ALGORITHM, functional_hierarchy, derive_design_reports
from engine.tool_permissions import tool_recommendation, apply_tool_policy, get_tool_catalog, EXTRA_PRESETS

class OrganizationDesignTests(unittest.TestCase):
    def test_all_sizes_and_spans(self):
        for n in range(1,33):
            for span in (1,3,5,8):
                org=generate_organization({'agent_count':n,'max_direct_reports':span})
                self.assertTrue(org['validation']['valid'], (n,span,org['validation']['errors']))
                self.assertEqual(org['hierarchy']['algorithm'],ALGORITHM)
                self.assertEqual(len(org['hierarchy']['assignment_rationales']),n)
                self.assertEqual({a['id']:a['reports_to'] for a in org['agents']},functional_hierarchy(org['agents'],span)[0])
                self.assertTrue(all(len(a['direct_reports'])<=span for a in org['agents']))

    def test_personalops_not_technical_manager(self):
        for span in (3,5,8):
            org=generate_organization({'agent_count':30,'max_direct_reports':span})
            roles={a['role']:a for a in org['agents']}
            for code in ('QUANT','GRAPH','MARKET'):
                self.assertNotEqual(roles[code]['reports_to'],roles['OWNEROPS']['id'])

    def test_current_tool_ids_and_six_presets(self):
        org=generate_organization({'agent_count':30,'template':'generic','repo_name':'NewExample'})
        known={t['name'] for t in get_tool_catalog()['tools']}
        for a in org['agents']:
            r=tool_recommendation(a)
            self.assertEqual(r['agent_id'],a['id'])
            self.assertEqual(r['runtime_availability'],'UNKNOWN')
            self.assertEqual(len(r['tool_rationales']),len(set(r['allow_candidates'])|set(a['tool_policy']['allow'])))
            if a['role'] in EXTRA_PRESETS:
                self.assertGreater(len(r['allow_candidates']),3)
                self.assertTrue(set(r['allow_candidates'])<=known)
        quant=next(a for a in org['agents'] if a['role']=='QUANT')
        self.assertTrue(tool_recommendation(quant)['breadth_review']['required'])
        legacy=copy.deepcopy(quant); legacy['tool_policy'].pop('recommendation_version')
        self.assertEqual(tool_recommendation(legacy)['agent_id'],quant['id'])

    def test_manual_tree_and_tool_deny_preserved(self):
        org=generate_organization({'agent_count':28})
        org=apply_organization_edits(org,{'expected_state_version':1,'hierarchy_mode':'manual'})
        original={a['id']:a['reports_to'] for a in org['agents']}
        aid=org['agents'][3]['id']
        org=apply_tool_policy(org,{'expected_state_version':org['state_version'],'agent_id':aid,'allow':['ops_plan'],'deny':['ops_status']})
        rebuilt=_rebuild_derived(copy.deepcopy(org))
        self.assertEqual(original,{a['id']:a['reports_to'] for a in rebuilt['agents']})
        a=next(a for a in rebuilt['agents'] if a['id']==aid)
        self.assertEqual(a['tool_policy']['deny'],['ops_status'])
        self.assertTrue(tool_recommendation(a)['manual_override_preserved'])
        self.assertTrue(rebuilt['validation']['valid'])

    def test_subteam_members_and_differentiation_gaps(self):
        org=generate_organization({'agent_count':30})
        ids={a['id'] for a in org['agents']}
        for team in org['functional_subteam_proposals']:
            self.assertTrue(set(team['member_ids'])<=ids)
            self.assertFalse(team['auto_execute'])
            self.assertFalse(team['human_profiling'])
        org['agents'][1]['mission']=org['agents'][0]['mission']
        report=derive_design_reports(org)['profile_differentiation']
        self.assertTrue(any(g['kind']=='duplicate_mission' for g in report['gaps']))
        self.assertFalse(report['global_uniqueness_claimed'])

if __name__=='__main__': unittest.main()
