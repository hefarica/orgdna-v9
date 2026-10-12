"""Companion snapshots are optional and hash-bound without altering DSH roots."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from engine import core, export_artifacts as exports, bundle
from engine.capability_library import CapabilityLibrary
from engine.capability_deployment import export_skillhub_library, skillhub_manifest_bytes

class CapabilityExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.org = core.generate_organization({'agent_count': 24, 'template': 'generic', 'repo_name': 'OfflineFixture', 'identity_mode': 'new', 'organization_id': 'bf99bba8-93e8-4d41-97b3-ed45b73f24f9'})
        self.library = CapabilityLibrary(Path(self.temp.name)/'library.sqlite', 'fixture')
        self.library.import_items([{'id':'review', 'kind':'skill_instructions', 'name':'Review evidence',
                                   'content':'Review observed evidence before acting.', 'tags':[],
                                   'provenance':{'type':'user_authored','evidence':'Offline fixture'}}],0,'import')
        self.companion = export_skillhub_library(self.library,self.org)
        self.time = 1791417600000

    def test_absence_preserves_original_shape(self):
        a=exports.build_export_snapshot(self.org, exported_at=self.time)
        b=exports.build_export_snapshot(self.org, exported_at=self.time, capability_library=None)
        self.assertEqual(dict(a.files),dict(b.files))
        self.assertIsNone(a.capability_library)
        self.assertNotIn('companions',a.manifest)
        self.assertNotIn(exports.CAPABILITY_FILENAME,a.package_files)

    def test_companion_hash_and_dsh_bytes(self):
        a=exports.build_export_snapshot(self.org,exported_at=self.time)
        b=exports.build_export_snapshot(self.org,exported_at=self.time,capability_library=self.companion)
        for role in ('implementation.json','definitions.json','council.json'):
            self.assertEqual(a.file_for(role),b.file_for(role))
        raw=b.file_for(exports.CAPABILITY_FILENAME)
        self.assertEqual(raw,skillhub_manifest_bytes(self.companion))
        self.assertEqual(b.manifest['companions'][0]['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertTrue(exports.validate_export_files(b.package_files,self.org)['valid'])
        self.companion['revision'] += 1
        self.assertNotEqual(self.companion,b.capability_library)
        returned=b.capability_library;returned['items'].clear()
        self.assertTrue(b.capability_library['items'])

    def test_tamper_missing_wrong_roster_rejected(self):
        b=exports.build_export_snapshot(self.org,exported_at=self.time,capability_library=self.companion)
        for operation in ('tamper','missing'):
            files=dict(b.package_files)
            if operation=='missing': files.pop(exports.CAPABILITY_FILENAME)
            else:
                obj=json.loads(files[exports.CAPABILITY_FILENAME]);obj['revision']+=1
                files[exports.CAPABILITY_FILENAME]=exports.json_bytes(obj)
            self.assertFalse(exports.validate_export_files(files,self.org)['valid'])
        invalid=copy.deepcopy(self.companion);invalid['member_ids'].reverse()
        with self.assertRaises(ValueError):exports.build_export_snapshot(self.org,capability_library=invalid)

    def test_active_context_bound_to_prompts_and_receipt(self):
        original=copy.deepcopy(self.org)
        selected=self.org['agents'][0]['id']
        plan=self.library.preview(self.org,['review'],{'mode':'selected','agent_ids':[selected]},'activate')
        self.library.apply(self.org,plan,'activate')
        active=export_skillhub_library(self.library,self.org)
        snapshot=exports.build_export_snapshot(self.org,exported_at=self.time,capability_library=active)
        self.assertEqual(self.org,original)
        base=core.export_recipe(self.org)['agents']
        for before,after in zip(base,snapshot.implementation['agents']):
            if before['id']==selected:
                self.assertIn('CAPACIDAD_REFERENCIA=',after['systemPrompt'])
                stripped=dict(after);stripped['systemPrompt']=before['systemPrompt']
                self.assertEqual(before,stripped)
            else:self.assertEqual(before,after)
        self.assertEqual(snapshot.manifest['context_compilation']['agents'][selected]['included_item_ids'],['review'])
        self.assertTrue(exports.validate_export_files(snapshot.package_files,self.org)['valid'])
        self.assertTrue(exports.validate_export_files(snapshot.package_files)['valid'])
        payload=bundle.build_package_bytes(self.org,export_snapshot=snapshot)
        self.assertTrue(bundle.validate_bundle(payload)['valid'])
        inactive=self.library.preview(self.org,['review'],{'mode':'selected','agent_ids':[selected]},'deactivate')
        self.library.apply(self.org,inactive,'deactivate')
        removed=exports.build_export_snapshot(self.org,exported_at=self.time,capability_library=export_skillhub_library(self.library,self.org))
        self.assertEqual(base,removed.implementation['agents'])
        self.assertNotIn('context_compilation',removed.manifest)

    def test_bundle_roundtrip_accepts_companion(self):
        b=exports.build_export_snapshot(self.org,exported_at=self.time,capability_library=self.companion)
        payload=bundle.build_package_bytes(self.org,export_snapshot=b)
        report=bundle.validate_bundle(payload)
        self.assertTrue(report['valid'],report)
        other=copy.deepcopy(self.companion);other['revision']+=1
        with self.assertRaises(ValueError):bundle.build_package_bytes(self.org,export_snapshot=b,capability_library=other)

if __name__=='__main__':unittest.main()
