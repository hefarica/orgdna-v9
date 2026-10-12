"""Additive local publication and paginated manifests; no real DSH activation."""
import copy,json,tempfile,unittest,uuid
from pathlib import Path
from engine.capability_deployment import build_deployment_plan,publish_package,rollback_publication,export_skillhub_library,validate_skillhub_manifest

class LibraryFixture:
    def __init__(self,org,n=400):
        self.items=[{'id':'item-'+str(i),'kind':'skill_instructions','name':'Method '+str(i),'description':'Static method','content':'Reference only','tags':[],'content_hash':format(i+1,'064x')} for i in range(n)]
        self.assignments=[{'agent_id':a['id'],'item_id':i['id'],'kind':i['kind'],'content_hash':i['content_hash'],'active':False} for a in org['agents'] for i in self.items]
    def page(self,rows,offset,limit):
        return {'items':rows[offset:offset+limit],'revision':1,'next_offset':offset+limit if offset+limit<len(rows) else None}
    def search(self,offset=0,limit=100):return self.page(self.items,offset,limit)
    def manifest_page(self,offset=0,limit=100):return self.page(self.assignments,offset,limit)

class IndependentDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.org={'organization_id':str(uuid.uuid4()),'agents':[{'id':str(uuid.uuid4())} for _ in range(30)]}
        self.namespace='orgdna_'+self.org['organization_id'].replace('-','');self.files={'manifest.json':b'{"fixture":true}','skills/reference.md':b'Reference, never an executable.'}
    def test_large_assignment_manifest_does_not_inherit_item_count_cap(self):
        lib=LibraryFixture(self.org,400);manifest=export_skillhub_library(lib,self.org)
        self.assertEqual(len(manifest['items']),400);self.assertEqual(len(manifest['assignments']),12000)
        self.assertEqual(set(manifest['member_ids']),{a['id'] for a in self.org['agents']});self.assertFalse(manifest['runtime_verified'])
    def test_preview_does_not_write_or_claim_native_activation(self):
        target=self.root/'newdestination'
        p=publish_package(self.files,target,self.namespace,'v1',self.org['organization_id'])
        self.assertFalse(target.exists());self.assertEqual(p['status'],'PREVIEW_ONLY');self.assertFalse(p['receipt']['runtime_activated'])
    def test_new_version_readback_no_overwrite_and_safe_rollback(self):
        result=publish_package(self.files,self.root,self.namespace,'v1',self.org['organization_id'],approve=True);target=Path(result['target'])
        self.assertEqual(result['status'],'PUBLISHED_BYTES_VERIFIED_NOT_ACTIVATED')
        for name,data in self.files.items():self.assertEqual((target/name).read_bytes(),data)
        with self.assertRaises(FileExistsError):publish_package(self.files,self.root,self.namespace,'v1',self.org['organization_id'],approve=True)
        preview=rollback_publication(self.root,result['receipt']);self.assertEqual(preview['status'],'ROLLBACK_PREVIEW');self.assertTrue(target.exists())
        other=self.root/'unrelated';other.write_text('untouched')
        rollback_publication(self.root,result['receipt'],approve=True);self.assertFalse(target.exists());self.assertEqual(other.read_text(),'untouched')
    def test_rollback_refuses_foreign_or_changed_files(self):
        result=publish_package(self.files,self.root,self.namespace,'v1',self.org['organization_id'],approve=True);target=Path(result['target'])
        (target/'foreign.txt').write_text('foreign')
        with self.assertRaises(ValueError):rollback_publication(self.root,result['receipt'],approve=True)
        self.assertTrue(target.exists());(target/'foreign.txt').unlink();(target/'manifest.json').write_text('changed')
        with self.assertRaises(ValueError):rollback_publication(self.root,result['receipt'],approve=True)
        self.assertTrue(target.exists())
    def test_paths_and_org_namespace_fail_closed(self):
        for name in ('../outside','/absolute','nested/../outside','bad\\path','x:y','.publication.json'):
            with self.subTest(name=name),self.assertRaises(ValueError):publish_package({name:b'x'},self.root,self.namespace,'v1',self.org['organization_id'],approve=True)
        with self.assertRaises(ValueError):publish_package(self.files,self.root,'foreign_namespace','v1',self.org['organization_id'],approve=True)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_manifest_mismatch_unknown_member_and_fake_runtime_rejected(self):
        manifest=export_skillhub_library(LibraryFixture(self.org,1),self.org)
        for change in ('member','runtime','activation'):
            bad=copy.deepcopy(manifest)
            if change=='member':bad['assignments'][0]['agent_id']=str(uuid.uuid4())
            elif change=='runtime':bad['runtime_verified']=True
            else:bad['items'][0]['kind']='plugin_package';bad['assignments'][0]['kind']='plugin_package';bad['assignments'][0]['active']=True
            with self.subTest(change=change),self.assertRaises(ValueError):validate_skillhub_manifest(bad,self.org)
        plan=build_deployment_plan(manifest,self.org['organization_id'],manifest['member_ids'])
        self.assertEqual(plan['new_agents'],0);self.assertFalse(plan['runtime_activated']);self.assertEqual(plan['network_calls'],0)
    def test_delta_is_explicit_hash_bound_and_keeps_backup(self):
        from engine.capability_deployment import build_skillhub_delta,apply_skillhub_delta,_bytes
        base=export_skillhub_library(LibraryFixture(self.org,1),self.org);target=copy.deepcopy(base);target['revision']+=1;target['assignments'][0]['active']=True
        delta=build_skillhub_delta(base,target,self.org)
        folder=self.root/self.namespace;folder.mkdir();path=folder/'skillhub-library.json';path.write_bytes(_bytes(base))
        preview=apply_skillhub_delta(path,delta,self.org);self.assertEqual(preview['status'],'DELTA_PREVIEW');self.assertEqual(path.read_bytes(),_bytes(base))
        result=apply_skillhub_delta(path,delta,self.org,approve=True)
        self.assertEqual(path.read_bytes(),_bytes(target));self.assertEqual(Path(result['backup_path']).read_bytes(),_bytes(base));self.assertFalse(result['runtime_activated']);self.assertFalse(result['existing_profiles_modified'])
        with self.assertRaises(ValueError):apply_skillhub_delta(path,delta,self.org,approve=True)
    def test_delta_tamper_and_foreign_namespace_do_not_write(self):
        from engine.capability_deployment import build_skillhub_delta,apply_skillhub_delta,_bytes
        base=export_skillhub_library(LibraryFixture(self.org,1),self.org);target=copy.deepcopy(base);target['revision']+=1;target['assignments'][0]['active']=True
        delta=build_skillhub_delta(base,target,self.org);folder=self.root/self.namespace;folder.mkdir();path=folder/'skillhub-library.json';path.write_bytes(_bytes(base))
        bad=copy.deepcopy(delta);bad['affected_member_ids']=[]
        with self.assertRaises(ValueError):apply_skillhub_delta(path,bad,self.org,approve=True)
        self.assertEqual(path.read_bytes(),_bytes(base))
        foreign=self.root/'skillhub-library.json';foreign.write_bytes(_bytes(base))
        with self.assertRaises(ValueError):apply_skillhub_delta(foreign,delta,self.org,approve=True)
        self.assertEqual(foreign.read_bytes(),_bytes(base))
    def test_registry_revision_change_aborts_export(self):
        lib=LibraryFixture(self.org,101);original=lib.search
        def unstable(offset=0,limit=100):
            page=original(offset,limit)
            if offset:page['revision']=2
            return page
        lib.search=unstable
        with self.assertRaises(ValueError):export_skillhub_library(lib,self.org)

if __name__=='__main__':unittest.main()
