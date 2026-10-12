"""Offline restart-preflight tests. No DSH or Windows process is executed."""
from contextlib import nullcontext
import json
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from engine.dsh_launcher import DSHLauncher, LauncherError, digest

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.script = self.root / 'DSH_RELANZAR_TODO.bat'
        self.script.write_text('@echo off\nset API_KEY=SECRET_FIXTURE\nDSH_REINICIAR.exe --allow-legacy-stop\n')
        self.exe = self.root / 'DSH_REINICIAR.exe'; self.exe.write_bytes(b'MZfixture-only')
        self.data = self.root / 'state'; self.data.mkdir(); (self.data/'history.json').write_text('{"history":"original"}')
        self.manager = DSHLauncher(self.root/'backups')
        pin=patch('engine.dsh_launcher.KNOWN_BINARIES',frozenset({digest(self.exe.read_bytes())}));pin.start();self.addCleanup(pin.stop)
        self.body = {'script_path':str(self.script),'exe_path':str(self.exe),'operation':'restart','ports':[15000,15001],'backup_paths':[str(self.data)]}
    def tearDown(self): self.tmp.cleanup()
    def inspect(self):
        self.manager.apply('dsh-launch-inspect',self.body)
        return {'plan_sha256':self.manager.public()['plan']['plan_sha256']}
    def test_inspection_never_returns_raw_secret(self):
        self.inspect(); result=self.manager.public()
        self.assertNotIn('SECRET_FIXTURE',json.dumps(result))
        self.assertEqual(result['plan']['ports'],[15000,15001]);self.assertFalse(result['execution_available'])
        self.assertEqual(result['plan']['binary_effects'],'RUNTIME_UNVERIFIED')
    def test_backup_hashes_and_original_unchanged(self):
        token=self.inspect();before=(self.data/'history.json').read_bytes()
        self.manager.apply('dsh-launch-backup',{**token,'backup_confirmed':True})
        backup=self.manager.public()['backup'];self.assertEqual(backup['status'],'VERIFIED_FILE_COPY')
        self.assertEqual(backup['sha256'],digest((self.root/'backups'/backup['filename']).read_bytes()))
        self.assertEqual((self.data/'history.json').read_bytes(),before)
        self.assertEqual(backup['application_consistency'],'UNVERIFIED')
    def test_consent_and_stale_plan(self):
        token=self.inspect()
        with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-backup',token)
        self.script.write_text('changed')
        with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-health',token)
        self.assertEqual(self.manager.public()['status'],'STALE_PLAN')
    def test_symlink_destination_rejected(self):
        token=self.inspect();other=self.root/'other';other.mkdir();(self.root/'backups').symlink_to(other,target_is_directory=True)
        with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-backup',{**token,'backup_confirmed':True})
        self.assertEqual(list(other.iterdir()),[])
    def test_health_not_identity_or_integration(self):
        token=self.inspect()
        with patch('engine.dsh_launcher.socket.create_connection',return_value=nullcontext()):self.manager.apply('dsh-launch-health',token)
        state=self.manager.public();self.assertTrue(state['health'][0]['tcp_listening']);self.assertFalse(state['health'][0]['identity_verified']);self.assertEqual(state['integration_status'],'NOT_VERIFIED')
    def test_execute_exact_argv_idempotent_and_separate_status(self):
        token=self.inspect();self.manager.apply('dsh-launch-backup',{**token,'backup_confirmed':True})
        self.manager._state['execution_available']=True
        release=threading.Event();process=Mock();process.poll.return_value=None;process.wait.side_effect=lambda: (release.wait(3),0)[1]
        consent={**token,'execute_confirmed':True,'interruption_acknowledged':True,'preservation_unverified_acknowledged':True}
        with patch('engine.dsh_launcher.on_windows',return_value=True), patch('engine.dsh_launcher.locked_executable',return_value=nullcontext()), patch('engine.dsh_launcher.subprocess.Popen',return_value=process) as popen:
            self.manager.apply('dsh-launch-execute',consent);self.manager.apply('dsh-launch-execute',consent)
            popen.assert_called_once();args,kwargs=popen.call_args
            self.assertEqual(args[0],[str(self.exe),'--headless','--no-open','--restart']);self.assertFalse(kwargs['shell']);self.assertEqual(kwargs['cwd'],str(self.exe.parent))
            self.assertFalse(self.manager.public()['run']['runtime_ready'])
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-clear',{})
        release.set()
    def test_execute_rejects_changed_backup_inventory(self):
        token=self.inspect();self.manager.apply('dsh-launch-backup',{**token,'backup_confirmed':True});self.manager._state['execution_available']=True
        (self.data/'new.json').write_text('new')
        with patch('engine.dsh_launcher.on_windows',return_value=True),patch('engine.dsh_launcher.subprocess.Popen') as spawn:
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-execute',{**token,'execute_confirmed':True,'interruption_acknowledged':True,'preservation_unverified_acknowledged':True})
            spawn.assert_not_called()
    def test_inspection_explicitly_issues_new_operation(self):
        first=self.inspect();second=self.inspect();self.assertNotEqual(first,second)
    def test_input_validation_no_network_or_commands(self):
        for path in ['//server/launch.bat','relative.bat','bad\npath.bat']:
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-inspect',{**self.body,'script_path':path})
        with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-inspect',{**self.body,'ports':[True]})
    def test_no_script_assumption_no_guessed_port(self):
        self.manager.apply('dsh-launch-inspect',{**self.body,'ports':[]});self.assertEqual(self.manager.public()['plan']['ports'],[])

    def test_stdout_allowlist_discards_secrets_and_correlates_legacy(self):
        stream=io.BytesIO(b'SECRET_FIXTURE\nCodigo: LEGACY_RESTART_CONFIRMATION | Diagnostico: C:\\private\\last-result.json\r\n')
        self.assertEqual(self.manager._read_process_signal(stream),'LEGACY_RESTART_CONFIRMATION')
        self.assertIsNone(self.manager._read_process_signal(io.BytesIO(b'text LEGACY_RESTART_CONFIRMATION text\n')))
        self.assertEqual(self.manager._read_process_signal(io.BytesIO(b'{"status":"ALREADY_RESTARTING","noDuplicate":true}\n')),'ALREADY_RESTARTING')
    def test_unknown_binary_cannot_execute_even_if_state_tampered(self):
        token=self.inspect();self.manager.apply('dsh-launch-backup',{**token,'backup_confirmed':True});self.manager._state['execution_available']=True
        with patch('engine.dsh_launcher.on_windows',return_value=True),patch('engine.dsh_launcher.KNOWN_BINARIES',frozenset()),patch('engine.dsh_launcher.subprocess.Popen') as spawn:
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-execute',{**token,'execute_confirmed':True,'interruption_acknowledged':True,'preservation_unverified_acknowledged':True})
            spawn.assert_not_called()
    def test_legacy_requires_prior_process_signal(self):
        with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-inspect',{**self.body,'legacy_stop':True})
    def test_config_read_is_explicit_and_no_defaults(self):
        appdata=self.root/'local';appdata.mkdir();(appdata/'DSH_LAUNCHER').mkdir()
        cfg=appdata/'DSH_LAUNCHER'/'launcher.json'
        with patch('engine.dsh_launcher.on_windows',return_value=True),patch.dict(os.environ,{'LOCALAPPDATA':str(appdata)}):
            self.manager.discover();self.assertIsNone(self.manager.public()['discovery']['configured'])
            cfg.write_text(json.dumps({'schema':1,'home':str(self.data),'runtime':str(self.root/'runtime'),'profile':'custom','port':16000}))
            self.manager.discover();d=self.manager.public()['discovery'];self.assertEqual(d['configured']['port'],16000);self.assertEqual(d['configured']['profile'],'custom')
            self.manager.apply('dsh-launch-inspect',{**self.body,'ports':[],'script_path':''})
            plan=self.manager.public()['plan'];self.assertEqual(plan['ports'],[16000]);self.assertEqual(plan['ports_source'],'launcher_config');self.assertIsNone(plan['script_sha256'])
            cfg.write_text('{}')
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-health',{'plan_sha256':plan['plan_sha256']})

    def test_changed_config_cancels_legacy_eligibility(self):
        appdata=self.root/'local';appdata.mkdir();(appdata/'DSH_LAUNCHER').mkdir()
        cfg=appdata/'DSH_LAUNCHER'/'launcher.json'
        value={'schema':1,'home':str(self.data),'runtime':str(self.root/'runtime'),'profile':'custom','port':16000}
        cfg.write_text(json.dumps(value))
        with patch('engine.dsh_launcher.on_windows',return_value=True),patch.dict(os.environ,{'LOCALAPPDATA':str(appdata)}):
            self.manager.discover()
            self.manager._legacy_eligible_sha=digest(self.exe.read_bytes())
            self.manager._legacy_eligible_config=self.manager.public()['discovery']['config_sha256']
            value['port']=16001;cfg.write_text(json.dumps(value))
            with self.assertRaises(LauncherError):self.manager.apply('dsh-launch-inspect',{**self.body,'legacy_stop':True})
            self.assertIsNone(self.manager._legacy_eligible_sha)
    def test_mutex_result_is_not_attributed(self):
        with patch.object(self.manager,'_result_file_hash') as check:
            result=self.manager._read_result({'process_signal':'ALREADY_RESTARTING'},None,'restart')
            self.assertEqual(result['status'],'UNVERIFIED');check.assert_not_called()

if __name__=='__main__':unittest.main()
