"""Independent harness state machine with inert doubles, no user DSH/EXE."""
import copy,json,unittest
from concurrent.futures import ThreadPoolExecutor
from engine.dsh_harness import DSHHarness,HarnessError,definition_hash
from engine.dsh_launcher import LauncherError
from tests.test_dsh_harness import FakeLauncher

class ConnectionFixture:
    def __init__(self):self.live=False;self.calls=[];self.profiles={'agents':[{'id':'qa-profile','name':'QA'}],'squads':[{'id':'qa-squad','members':['qa-profile']}]}
    def cached_status(self):return {'live_connection':self.live,'identity_verified':self.live}
    def status(self):return self.cached_status()
    def connect(self,port,code):self.calls.append((port,code));self.live=True
    def diagnose(self):return {'writes_performed':False,'model_calls_performed':False}
    def read_profiles(self):return copy.deepcopy(self.profiles)
    def disconnect(self):self.live=False

class IndependentHarnessTests(unittest.TestCase):
    def setUp(self):
        self.launcher=FakeLauncher();self.conn=ConnectionFixture();self.now=100
        self.h=DSHHarness(self.launcher,self.conn,clock=lambda:self.now)
    def plan(self,**kw):return self.h.apply('dsh-harness-prepare',{'wait_seconds':5,**kw})['plan']
    def approve(self,p):return {'plan_sha256':p['plan_sha256'],'start_confirmed':True,'backup_confirmed':True,'execute_confirmed':True,'interruption_acknowledged':True,'preservation_unverified_acknowledged':True}
    def test_concurrent_start_exactly_once_and_exit_zero_never_native_execution(self):
        p=self.plan()
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda _:self.h.apply('dsh-harness-start',self.approve(p)),range(6)))
        self.assertEqual(len(self.launcher.executions()),1);self.assertFalse(self.h.public()['live_connection']);self.assertFalse(self.h.public()['native_execution_verified'])
        self.now=106;self.assertEqual(self.h.apply('dsh-harness-check')['status'],'START_TIMEOUT_NO_RETRY')
        self.h.apply('dsh-harness-start',self.approve(p));self.assertEqual(len(self.launcher.executions()),1)
    def test_prepare_and_unapproved_requests_do_not_backup_or_execute(self):
        p=self.plan()
        with self.assertRaises(HarnessError):self.h.apply('dsh-harness-start',{'plan_sha256':p['plan_sha256']})
        wrong=self.approve(p);wrong['plan_sha256']='0'*64
        with self.assertRaises(HarnessError):self.h.apply('dsh-harness-start',wrong)
        self.assertFalse(any(a in ('dsh-launch-backup','dsh-launch-execute') for a,_ in self.launcher.calls))
    def test_occupied_port_is_preserved_and_not_authenticated(self):
        self.launcher.busy=True;p=self.plan();state=self.h.apply('dsh-harness-start',self.approve(p))
        self.assertEqual(state['status'],'EXISTING_LISTENER_PAIRING_REQUIRED');self.assertFalse(state['live_connection']);self.assertFalse(self.launcher.executions())
    def test_readback_roster_hash_and_loss_are_distinct_from_runtime_task(self):
        p=self.plan(bridge_port=19001,expected_definition_sha256=definition_hash(self.conn.profiles))
        state=self.h.apply('dsh-harness-pair',{'plan_sha256':p['plan_sha256'],'bridge_port':19001,'pair_confirmed':True,'pairing_code':'QA_PRIVATE_PAIRING'})
        self.assertEqual(state['status'],'READ_ONLY_VERIFIED');self.assertTrue(state['readback']['expected_definition_matches']);self.assertFalse(state['native_execution_verified']);self.assertFalse(state['readback']['runtime_session_identity_verified']);self.assertNotIn('QA_PRIVATE_PAIRING',json.dumps(state))
        self.conn.live=False;state=self.h.public();self.assertFalse(state['live_connection']);self.assertIsNone(state['readback'])
    def test_wrong_roster_or_changed_pairing_target_not_green(self):
        p=self.plan(bridge_port=19001,expected_definition_sha256='0'*64)
        payload={'plan_sha256':p['plan_sha256'],'bridge_port':19002,'pair_confirmed':True,'pairing_code':'secret'}
        with self.assertRaises(HarnessError):self.h.apply('dsh-harness-pair',payload)
        self.assertFalse(self.conn.calls);payload['bridge_port']=19001
        result=self.h.apply('dsh-harness-pair',payload);self.assertEqual(result['status'],'READBACK_MISMATCH_OR_CONNECTION_LOST');self.assertFalse(result['readback']['expected_definition_matches'])
    def test_unexpected_launch_failure_is_consumed_and_visibly_failed(self):
        p=self.plan();original=self.launcher.apply
        def unexpected(action,body):
            if action=='dsh-launch-execute':self.launcher.calls.append((action,body));raise RuntimeError('opaque-private-launch-detail')
            return original(action,body)
        self.launcher.apply=unexpected
        with self.assertRaises(Exception):self.h.apply('dsh-harness-start',self.approve(p))
        self.assertEqual(self.h.public()['status'],'START_FAILED_NO_RETRY');self.assertNotIn('opaque-private-launch-detail',json.dumps(self.h.public()))
        self.h.apply('dsh-harness-start',self.approve(p));self.assertEqual(len(self.launcher.executions()),1)
    def test_missing_prerequisites_no_restart_and_no_installation(self):
        self.launcher.available=False;p=self.plan();state=self.h.apply('dsh-harness-start',self.approve(p))
        self.assertEqual(state['status'],'LOCAL_PREREQUISITES_REQUIRED');self.assertFalse(state['automatic_installation_available']);self.assertFalse(self.launcher.executions())
        with self.assertRaises(HarnessError):self.plan(operation='restart')
        self.assertEqual(p['operation'],'reuse');self.assertFalse(p['terminates_processes']);self.assertFalse(p['installs_plugins'])

if __name__=='__main__':unittest.main()
