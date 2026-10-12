import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from engine.capability_deployment import publish_package, rollback_publication, export_skillhub_library, build_deployment_plan, build_skillhub_delta, apply_skillhub_delta

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.org=str(uuid4()); self.namespace='orgdna_'+self.org.replace('-','')
        self.ids=[str(uuid4()) for _ in range(30)]
    def publish(self, **kwargs):
        return publish_package({'entry.mjs':b'// inert','data/library.json':b'{}'},self.root,self.namespace,'1.0.0',self.org,**kwargs)
    def test_preview_publish_readback_rollback_preserves_other_plugins(self):
        other=self.root/'other-plugin'; other.mkdir();(other/'config.json').write_text('unchanged')
        preview=self.publish();self.assertFalse(Path(preview['target']).exists())
        result=self.publish(approve=True); self.assertIn('NOT_ACTIVATED',result['status'])
        self.assertFalse(result['receipt']['runtime_activated'])
        self.assertEqual(rollback_publication(self.root,result['receipt'])['status'],'ROLLBACK_PREVIEW')
        rollback_publication(self.root,result['receipt'],approve=True)
        self.assertEqual((other/'config.json').read_text(),'unchanged')
    def test_existing_version_refuses_no_overwrite(self):
        result=self.publish(approve=True)
        with self.assertRaises(FileExistsError):self.publish(approve=True)
        self.assertEqual((Path(result['target'])/'entry.mjs').read_bytes(),b'// inert')
    def test_modified_or_foreign_file_blocks_rollback(self):
        result=self.publish(approve=True); target=Path(result['target'])
        (target/'foreign').write_text('preserve')
        with self.assertRaisesRegex(ValueError,'foreign'):rollback_publication(self.root,result['receipt'],approve=True)
        (target/'foreign').unlink();(target/'entry.mjs').write_text('changed')
        with self.assertRaisesRegex(ValueError,'modified'):rollback_publication(self.root,result['receipt'],approve=True)
    def test_namespace_traversal_symlink(self):
        for name in ('../config','/tmp/escape','a/../x','a\\x'):
            with self.assertRaises(ValueError):publish_package({name:b'x'},self.root,self.namespace,'1',self.org,approve=True)
        with self.assertRaises(ValueError):publish_package({'x':b'x'},self.root,'other','1',self.org)
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):publish_package({'x':b'x'},link,self.namespace,'1',self.org)
    def test_paginated_export_30_members_no_identity_creation(self):
        members=self.ids
        class Library:
            def search(self,offset,limit):
                rows=[{'id':str(i),'kind':'skill_instructions','name':'item','content':'help','content_hash':'a'*64} for i in range(230)]
                return {'revision':4,'items':rows[offset:offset+limit],'next_offset':offset+limit if offset+limit<len(rows) else None}
            def manifest_page(self,offset,limit):
                rows=[{'agent_id':m,'item_id':str(i),'kind':'skill_instructions','content_hash':'a'*64,'active':True} for m in members for i in range(30)]
                return {'revision':4,'items':rows[offset:offset+limit],'next_offset':offset+limit if offset+limit<len(rows) else None}
        org={'organization_id':self.org,'agents':[{'id':x} for x in self.ids]}
        result=export_skillhub_library(Library(),org)
        self.assertEqual(len(result['items']),230);self.assertEqual(len(result['assignments']),900)
        self.assertEqual(result['member_ids'],self.ids)
        plan=build_deployment_plan(result,self.org,self.ids)
        self.assertFalse(plan['runtime_activated']);self.assertEqual(plan['new_agents'],0)
    def test_delta_cas_keeps_ids_backup_and_runtime_pending(self):
        base={'protocol':'orgdna-skillhub/1','organization_id':self.org,'namespace':self.namespace,'member_ids':self.ids,'revision':1,'items':[],'assignments':[],'context_budget_bytes':12000,'permission_grants':[],'runtime_verified':False,'connectors':[]}
        target=copy.deepcopy(base);target['revision']=2
        delta=build_skillhub_delta(base,target,{'organization_id':self.org,'agents':[{'id':x} for x in self.ids]})
        folder=self.root/self.namespace/'v1';folder.mkdir(parents=True);file=folder/'skillhub-library.json'
        encode=lambda value:(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        file.write_bytes(encode(base));org={'organization_id':self.org,'agents':[{'id':x} for x in self.ids]}
        self.assertEqual(apply_skillhub_delta(file,delta,org)['status'],'DELTA_PREVIEW');self.assertEqual(file.read_bytes(),encode(base))
        result=apply_skillhub_delta(file,delta,org,approve=True)
        self.assertEqual(file.read_bytes(),encode(target));self.assertEqual(Path(result['backup_path']).read_bytes(),encode(base))
        self.assertFalse(result['runtime_activated']);self.assertEqual(delta['member_ids'],self.ids)
        with self.assertRaisesRegex(ValueError,'STALE_BASE'):apply_skillhub_delta(file,delta,org,approve=True)
        reverse=build_skillhub_delta(target,base,org);apply_skillhub_delta(file,reverse,org,approve=True)
        self.assertEqual(file.read_bytes(),encode(base))

    def test_changed_revision_refused(self):
        class Library:
            def search(self,offset,limit):return {'revision':1,'items':[],'next_offset':None}
            def manifest_page(self,offset,limit):return {'revision':2,'items':[],'next_offset':None}
        with self.assertRaisesRegex(ValueError,'changed'):export_skillhub_library(Library(),{'organization_id':self.org,'agents':[{'id':x} for x in self.ids]})

if __name__=='__main__':unittest.main()
