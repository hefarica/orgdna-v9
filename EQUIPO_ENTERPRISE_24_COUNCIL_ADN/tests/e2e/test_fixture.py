"""Pure Python fixture checks. No HTTP server, browser, network or subprocess run."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fixture_server import FixtureState, MemoryOnlyStore, SENTINEL, bridge, denied

class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='orgdna-fixture-test-')
        self.root=Path(self.temp.name)
        self.patch=patch.object(bridge,'ROOT',self.root);self.patch.start()
        self.state=FixtureState(self.root)
    def tearDown(self):
        self.state.fixture_provider.release.set()
        active=self.state.generation._active()
        if active:self.state.execute('generation-cancel',{'job_id':active['job_id']})
        self.patch.stop();self.temp.cleanup()
    def wait(self,status):
        limit=time.monotonic()+10
        while time.monotonic()<limit:
            job=self.state.generation.public()
            if job and job['status']==status:return job
            time.sleep(.01)
        self.fail(repr(self.state.generation.public()))
    def test_seed_and_storage_are_synthetic(self):
        state=self.state.public()
        self.assertEqual(len(state['organization']['agents']),4)
        self.assertIn(str(self.root),str(self.state.project_store.root))
        self.assertEqual(state['verification']['provider_live_calls'],'NOT_RUN_E2E_FIXTURE_ONLY')
        self.assertNotIn(SENTINEL,json.dumps(state))
    def test_external_and_runtime_actions_are_denied(self):
        for action in ['dsh-connect','dsh-disconnect','dsh-launch-execute','dsh-launch-backup',
                       'dsh-harness-start','import-workbook','evaluation-start','plugin-shop-refresh']:
            with self.assertRaises(bridge.BridgeError):self.state.execute(action,{})
        with self.assertRaises(RuntimeError):denied()
    def test_credentials_cannot_persist_or_use_a_real_value(self):
        with self.assertRaises(bridge.BridgeError):self.state.execute('credentials',{'api_key':'real-value-disallowed'})
        with self.assertRaises(bridge.BridgeError):MemoryOnlyStore().save({})
    def test_real_pipeline_accepts_inert_provider_and_exact_native_exports(self):
        self.state.execute('generation-plan',{'idempotency_key':'fixture-selftest','new_project':True})
        self.wait('awaiting_consent');p=self.state.pending_consent
        self.assertEqual(self.state.fixture_provider.design_calls,0)
        self.state.execute('generation-confirm',{'job_id':p['job_id'],'consent_id':p['approval_id'],
            'config_version':p['config_version'],'payload_sha256':p['payload_sha256'],
            'confirmed':True,'data_reviewed':True,'budget_acknowledged':True,
            'partial_inventory_acknowledged':bool(p.get('partial_inventory_required')),'coverage_sha256':p.get('coverage_sha256')})
        self.wait('completed')
        backup=json.loads(self.state.download('definitions.json'));recipe=json.loads(self.state.download('implementation.json'))
        self.assertEqual(backup['agents'],recipe['agents']);self.assertEqual(len(recipe['agents']),4)
        self.assertEqual(backup['format'],'agent-team-gui/definitions');self.assertEqual(recipe['format'],'agent-team-gui/recipe')
        self.assertEqual(self.state.fixture_provider.design_calls,1)
    def test_readonly_dsh_observation_has_no_connection(self):
        result=self.state.execute('dsh-status',{})
        self.assertFalse(result['dsh_connection']['runtime_write_supported'])
        self.assertFalse(result['dsh_connection']['status'].get('live_connection',False))
    def performance(self, task='fixture-delivery'):
        aid=self.state.organization['agents'][-1]['id']
        self.state.execute('performance-create', dict(expected_state_version=self.state.organization['state_version'],
            agent_id=aid, task_id=task, title='Synthetic deliverable', candidate_sha='a'*40,
            comparison_group='fixture-comparable', budget=10, budget_unit='minutes',
            acceptance_criteria=['One','Two'], evidence=['fixture://delivery']))
        return self.state.records['performance_records'][-1]
    def review(self, row, quality=2):
        body=dict(performance_id=row['id'], reviewer_id='EXTERNAL:fixture-reviewer',
            expected_state_version=self.state.organization['state_version'],
            external_reviewer_name='Synthetic reviewer', appointed_by='OWNER_EXTERNAL',
            appointment_evidence=['fixture://appointment'], conflict_of_interest=False, includes_failures=True,
            rationale='Manual synthetic evidence', evidence=['fixture://review'],
            measurements={'quality':{'numerator':quality,'denominator':2},
              'compliance':{'numerator':2,'denominator':2},'efficiency':{'budget':10,'actual':10},
              'collaboration':{'numerator':2,'denominator':2},'evidence':{'numerator':2,'denominator':2}})
        current=next(r for r in self.state.records['performance_records'] if r['id']==row['id'])
        if current['reviews']:body['supersedes_review_id']=current['reviews'][-1]['id']
        self.state.execute('performance-review',body)
    def test_governance_synthetic_review_correction_and_manual_promotion(self):
        row=self.performance();self.review(row)
        first=self.state.records['performance_records'][0]['reviews'][0]
        self.review(row,1)
        reviews=self.state.records['performance_records'][0]['reviews']
        self.assertEqual([r['score'] for r in reviews],[100,85])
        self.assertEqual(reviews[1]['supersedes_review_id'],first['id'])
        agents=json.dumps(self.state.organization['agents'],sort_keys=True)
        self.state.execute('promotion-create',dict(expected_state_version=self.state.organization['state_version'],
            agent_id=row['agent_id'],comparison_group=row['comparison_group'],kind='recognition',
            recommendation='Synthetic recognition',evidence=['fixture://proposal']))
        proposal=self.state.records['promotion_records'][0]
        for status, reviewer in [('supervisor_reviewed',proposal['supervisor_id']),('owner_approved','OWNER_EXTERNAL')]:
            self.state.execute('promotion-update',dict(expected_state_version=self.state.organization['state_version'],
                promotion_id=proposal['id'],status=status,reviewer_id=reviewer,conflict_of_interest=False,
                note='Synthetic declaration',evidence=['fixture://decision']))
        self.assertEqual(self.state.records['promotion_records'][0]['status'],'owner_approved')
        self.assertEqual(json.dumps(self.state.organization['agents'],sort_keys=True),agents)
    def test_governance_five_samples_and_single_sample_guards(self):
        row=self.performance();self.review(row)
        body=dict(agent_id=row['agent_id'],comparison_group=row['comparison_group'],
            recommendation='Synthetic proposal',evidence=['fixture://proposal'])
        for kind in ['promotion','succession']:
            with self.assertRaisesRegex(ValueError,'umbrales/muestras'):
                self.state.execute('promotion-create',dict(body,kind=kind,expected_state_version=self.state.organization['state_version']))
        for i in range(1,5):self.review(self.performance('sample-'+str(i)))
        self.state.execute('promotion-create',dict(body,kind='promotion',expected_state_version=self.state.organization['state_version']))
        self.assertTrue(self.state.records['promotion_records'][0]['score_snapshot']['promotion_eligible'])
    def lease(self, index, path):
        return self.state.execute('lease-acquire',dict(owner_agent_id=self.state.organization['agents'][index]['id'],
            task_id='writer-'+str(index),workspace=self.state.fixture_workspace,paths=[path],base_sha='b'*40,
            expected_version=self.state.public()['coordination']['version'],ttl_seconds=60))
    def test_leases_stay_temporary_and_enforce_conflict_and_writer_limit(self):
        first=self.lease(0,'src');lease=first['coordination']['leases'][0]
        with self.assertRaisesRegex(ValueError,'Conflicto'):self.lease(1,'src/nested')
        self.lease(1,'docs');self.lease(2,'tests')
        with self.assertRaisesRegex(ValueError,'tres'):self.lease(3,'unused')
        for action in ['lease-renew','lease-release']:
            self.state.execute(action,dict(lease_id=lease['id'],owner_agent_id=lease['owner_agent_id'],
                task_id=lease['task_id'],ttl_seconds=120,expected_version=self.state.public()['coordination']['version']))
        self.assertEqual(self.state.public()['coordination']['active_writer_count'],2)
        with self.assertRaisesRegex(bridge.BridgeError,'synthetic temporary'):
            self.state.execute('lease-acquire',{'workspace':'/not-the-fixture'})
    def test_model_priority_synthetic_catalog_persists(self):
        self.state.execute('discover-models',{'confirmed':True})
        self.state.execute('model-preferences',dict(expected_state_version=self.state.organization['state_version'],
            preferences=[{'provider':'deepseek-official','model':'fixture-model','user_rank':7}]))
        self.assertEqual(self.state.public()['models'][0]['user_rank'],7)
        self.assertEqual(self.state.fixture_provider.design_calls,0)
    def test_control_matrix_has_nine_pages_and_never_claims_passed(self):
        data=json.loads((Path(__file__).parent/'control-matrix.json').read_text())
        self.assertEqual(data['browser_execution'],'NOT_RUN')
        pages={r['page'] for r in data['controls']}
        self.assertTrue({'inicio','organigrama','perfiles','council','habilidades','modelos','repositorio','exportaciones','registro'}<=pages)
        self.assertTrue(all(r['browser_status']=='NOT_RUN' for r in data['controls']))
    def test_matrix_mappings_reference_authored_cases_and_real_source_families(self):
        here=Path(__file__).parent
        matrix=json.loads((here/'control-matrix.json').read_text())
        cases=json.loads((here/'authored-cases.json').read_text())
        names={case['title'] for case in cases['tests']}
        self.assertEqual(len(names),cases['count'])
        self.assertEqual(sum(matrix['counts'].values()),len(matrix['controls']))
        for row in matrix['controls']:
            self.assertIn('behavior_family',row)
            self.assertIn('control_role',row)
            if row['functional_status']=='NOT_RUN':
                self.assertTrue(row['case_ids'],row['locator'])
                self.assertTrue(set(row['case_ids']) <= names,row['locator'])
                self.assertTrue((here/row['suite']).is_file())
        dynamic={r['locator'] for r in matrix['controls'] if r['source']=='javascript'}
        self.assertNotIn('#governance-records button',dynamic)
        self.assertNotIn('.plugin-candidate button',dynamic)
        self.assertTrue({'#merit-ranking button','.plugin-result button','#performance-authors input'} <= dynamic)
    def test_summary_locator_labels_are_unique_and_preserve_source_inventory(self):
        import sys
        sys.path.insert(0,str(Path(__file__).parent))
        from build_matrix import Inventory, ROOT
        source=Inventory();source.feed((ROOT/'web/index.html').read_text())
        matrix=json.loads((Path(__file__).parent/'control-matrix.json').read_text())
        static=[r for r in matrix['controls'] if r['source']=='html']
        self.assertEqual(len(static),len(source.rows))
        for row, original in zip(static,source.rows):
            self.assertEqual(row['tag'],original['tag'])
            if row['tag']=='summary':
                label=' '.join(original['label_text'].split())
                text=label.split('0 / 3')[0].strip() if 'Coordinar edición local por rutas' in label else label
                self.assertEqual(row['locator'],'summary:has-text('+json.dumps(text,ensure_ascii=False)+')')
                self.assertEqual(sum(text in ' '.join(other['label_text'].split()) for other in source.rows if other['tag']=='summary'),1)

if __name__=='__main__':unittest.main(verbosity=2)
