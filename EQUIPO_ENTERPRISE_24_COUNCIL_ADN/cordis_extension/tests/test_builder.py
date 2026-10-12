import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import zipfile
from engine import core
from engine.cordis_extension import build_cordis_addon, extend_native_document, tool_names, SOURCE_FILES


class CordisBuilderTests(unittest.TestCase):
    def setUp(self):
        self.org=core.generate_organization({'repo_name':'Cordis test fixture','template':'generic','agent_count':24,
            'council_concurrency':24,'organization_id':str(uuid.uuid4()),'identity_mode':'new'})
        self.teams=core.export_definitions(self.org)

    def test_same24_and_no_configuration_mutation(self):
        before=copy.deepcopy((self.org,self.teams))
        result=build_cordis_addon(self.org,self.teams)
        self.assertEqual(before,(self.org,self.teams))
        self.assertEqual(result['manifest']['member_ids'],[a['id'] for a in self.org['agents']])
        self.assertEqual(result['manifest']['member_count'],24)
        self.assertEqual(result['manifest']['new_agent_count'],0)
        self.assertEqual(result['dry_run']['status'],'BLOCKED_RUNTIME_NOT_VERIFIED')
        self.assertFalse(result['manifest']['activation']['enabled'])
        extended=json.loads(result['files']['extended-native/definitions.json'])
        self.assertEqual([a['id'] for a in extended['agents']],[a['id'] for a in self.teams['agents']])
        self.assertEqual([s['id'] for s in extended['squads']],[s['id'] for s in self.teams['squads']])
        for original,variant in zip(self.teams['squads'],extended['squads']):
            self.assertEqual({k:v for k,v in original.items() if k!='collabNote'},{k:v for k,v in variant.items() if k!='collabNote'})
            self.assertTrue(variant['collabNote'].startswith(original['collabNote']))
        self.assertTrue(core.validate_definitions(extended)['valid'])
        self.assertEqual(result['zip_bytes'],build_cordis_addon(self.org,self.teams)['zip_bytes'])
        with zipfile.ZipFile(io.BytesIO(result['zip_bytes'])) as archive:
            self.assertEqual(set(archive.namelist()),set(result['files']))
            self.assertFalse(any('..' in n or n.startswith('/') for n in archive.namelist()))
            for row in result['integrated_exports'].values():
                self.assertEqual(archive.read(row['path']),result['files'][row['path']])
                self.assertTrue(row['requires_addon_activation'])
                self.assertEqual(row['variant'],'integrated_cordis')
            self.assertEqual(result['integrated_exports']['recipe']['filename'],'agent-team-recipe-'+extended['squads'][0]['id']+'.json')
            self.assertRegex(result['integrated_exports']['definitions']['filename'],r'^agent-team-backup-\d{4}-\d{2}-\d{2}\.json$')

    def test_explicit_deny_preserved(self):
        document=copy.deepcopy(self.teams)
        name=tool_names(self.org['organization_id'])[0]
        document['agents'][0]['toolScope']['deny']=[name]
        before=copy.deepcopy(document)
        result,deltas=extend_native_document(document,self.org['organization_id'],[a['id'] for a in self.org['agents']])
        self.assertEqual(document,before)
        self.assertEqual(result['agents'][0]['toolScope']['deny'],[name])
        self.assertNotIn(name,result['agents'][0]['toolScope']['allow'])
        self.assertEqual(deltas[0]['explicitly_denied_addon_tools'],[name])

    def test_cap_limits_and_foreign_roster_fail(self):
        document=copy.deepcopy(self.teams)
        document['agents'][0]['toolScope']={'allow':['synthetic_'+str(i) for i in range(256)]}
        with self.assertRaisesRegex(ValueError,'256'): extend_native_document(document,self.org['organization_id'],[a['id'] for a in self.org['agents']])
        document=copy.deepcopy(self.teams);document['agents'][0]['id']=str(uuid.uuid4())
        with self.assertRaises(ValueError):build_cordis_addon(self.org,document)

    def test_claimed_capabilities_never_activate(self):
        result=build_cordis_addon(self.org,self.teams,{'runtime_verified':True,'cookies':'should never export'})
        self.assertFalse(result['manifest']['activation']['runtime_verified'])
        self.assertNotIn(b'should never export',result['zip_bytes'])
        for payload in result['files'].values():self.assertNotIn(b'should never export',payload)

    def test_missing_org_identity_fails(self):
        del self.org['organization_id']
        with self.assertRaisesRegex(ValueError,'UUID estable'):build_cordis_addon(self.org)

    def test_extracted_zip_preflight_flat_nested_and_plugin_dependency_resolution(self):
        result=build_cordis_addon(self.org,self.teams)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with zipfile.ZipFile(io.BytesIO(result['zip_bytes'])) as archive:archive.extractall(root)
            def package_metadata(directory,version):
                package=directory/'node_modules'/'@deepseek-ai'/'dsh-tools';package.mkdir(parents=True,exist_ok=True)
                (package/'package.json').write_text(json.dumps({'name':'@deepseek-ai/dsh-tools','version':version,
                    'exports':{'./package.json':'./package.json'}}))
            def run(script,*args):
                process=subprocess.run(['node',str(script),*map(str,args)],cwd=root.parent,capture_output=True,text=True,check=False)
                self.assertEqual(process.returncode,2,process.stderr)
                report=json.loads(process.stdout)
                self.assertEqual(report['organization_id'],self.org['organization_id'])
                self.assertNotIn('Generated addon-manifest.json is missing',report['blocking_reasons'])
                self.assertEqual(report['tools_version'],'0.2.0-rc.2')
                return report
            package_metadata(root,'0.2.0-rc.2')
            flat=run(root/'preflight.mjs')
            self.assertEqual(flat['dependency_resolution_directory'],str(root))
            nested=root/'cordis_extension';nested.mkdir()
            for filename in SOURCE_FILES:
                destination=nested/filename;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(root/filename),destination)
            package_metadata(root,'synthetic-parent-package-not-the-plugin-dependency')
            package_metadata(nested,'0.2.0-rc.2')
            report=run(nested/'preflight.mjs')
            self.assertEqual(report['dependency_resolution_directory'],str(nested))
            self.assertEqual(next(c for c in report['checks'] if c['name']=='addon_manifest')['layout'],'parent_distribution_root')
            explicit=run(nested/'preflight.mjs',root)
            self.assertEqual(explicit['dependency_resolution_directory'],str(nested))

    def test_extracted_zip_overlay_native_bootstrap_with_empty_bindings(self):
        result=build_cordis_addon(self.org,self.teams)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with zipfile.ZipFile(io.BytesIO(result['zip_bytes'])) as archive:archive.extractall(root)
            config=json.loads((root/'addon-config.example.json').read_text())
            config.update(enabled=True,confirm_activation='ACTIVATE_EXISTING_ROSTER_ONLY',state_directory=str(root/'addon-data'),session_bindings={})
            config['native_stage_ui']={'enabled':True,'agentteams_state_root':str(root/'existing-native-state')}
            reviewed=root/'reviewed.json';reviewed.write_text(json.dumps(config))
            output=root/'native-overlay.yml'
            process=subprocess.run(['node',str(root/'prepare-overlay.mjs'),str(reviewed),str(output)],cwd=root.parent,capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
            overlay=json.loads(output.read_text())
            self.assertEqual(overlay[0]['insert'][0]['name'],str(root/'entry.mjs'))
            self.assertEqual(overlay[0]['insert'][0]['config']['session_bindings'],{})
            self.assertFalse((root/'addon-data').exists(),'Preparing overlay must not mount the ledger')
            config['native_stage_ui']['enabled']=False;reviewed.write_text(json.dumps(config))
            denied=root/'denied-overlay.yml'
            process=subprocess.run(['node',str(root/'prepare-overlay.mjs'),str(reviewed),str(denied)],capture_output=True,text=True)
            self.assertNotEqual(process.returncode,0)
            self.assertFalse(denied.exists())

if __name__=='__main__':unittest.main()
