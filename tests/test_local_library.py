import json
from pathlib import Path
import tempfile
import unittest
from app.variants.local_library import LocalLibrary, MergedLocalLibrary
from app.variants.catalog import load_active_catalog, DeferredVariantEntry, VariantPreferenceCommit
from app.variants.readiness import verify_dataset_ready

class Token:
    def check(self):pass

class LocalLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        for name in ('before.npz','after.npz'):(self.root/name).write_bytes(b'fixture; catalog does not decode geometry')
    def library(self,models):
        (self.root/'library.json').write_text(json.dumps({'schema':'ae.local-library.v1','models':models}))
        return LocalLibrary(self.root)
    def test_partial_missing_and_unknown_model(self):
        store=self.library({'custom_model':{'name':'Custom','variants':{'pre':{'path':'before.npz'},'post':{'path':'missing.npz'}}},'missing':{'variants':{'pre':{'path':'none.npz'}}}})
        catalog=load_active_catalog(store=store)
        self.assertTrue(catalog.ready);self.assertEqual(list(catalog),['custom_model'])
        self.assertEqual(catalog['custom_model'].available_variants,('pre',));self.assertEqual(len(catalog.warnings),2)
        self.assertTrue(verify_dataset_ready(store)['dataset_ready'])
    def test_selection_roundtrip_and_reconstruction(self):
        store=self.library({'sample':{'variants':{'pre':{'path':'before.npz'},'post':{'path':'after.npz'}}}})
        catalog=load_active_catalog(store=store);entry=catalog['sample']
        self.assertEqual(entry.variant,'post')
        before=entry.for_variant('pre');result=VariantPreferenceCommit(before).prepare_cpu(Token())
        self.assertEqual(result.token,before.descriptor.token)
        rebuilt=DeferredVariantEntry(before.meta,store)
        self.assertEqual(rebuilt.variant,'pre');self.assertEqual(rebuilt.descriptor.path,self.root/'before.npz')
    def test_empty_and_missing_distinguished(self):
        store=self.library({});catalog=load_active_catalog(store=store)
        self.assertTrue(catalog.ready);self.assertFalse(catalog);self.assertEqual(catalog.error,'')
        (self.root/'library.json').unlink();broken=load_active_catalog(store=store)
        self.assertFalse(broken.ready);self.assertIn('local model library',broken.error)
    def test_seed_preferences_stay_external(self):
        self.library({"sample":{"variants":{"pre":"before.npz"}}})
        preferences=self.root/"user"/"selection.json"
        store=LocalLibrary(self.root,preferences_path=preferences)
        store.select("sample","pre")
        self.assertTrue(preferences.exists())
        self.assertFalse((self.root/"preferences.json").exists())

    def test_user_override_keeps_other_seed_models_and_origins(self):
        seed=self.root/'seed';user=self.root/'user';seed.mkdir();user.mkdir()
        for root in (seed,user):(root/'mesh.npz').write_bytes(b'fixture')
        (seed/'library.json').write_text(json.dumps({'models':{'A':{'variants':{'pre':'mesh.npz'}},'B':{'variants':{'pre':{'path':'mesh.npz','companions':{'notes':'notes.json'}}}}}}))
        (user/'library.json').write_text(json.dumps({'models':{'A':{'name':'User A','variants':{'post':'mesh.npz'}}}}))
        store=MergedLocalLibrary(seed,user)
        catalog=load_active_catalog(store=store)
        self.assertEqual(set(catalog),{'A','B'})
        self.assertEqual(catalog['A'].name,'User A')
        self.assertEqual(catalog['A'].descriptor.root,user)
        self.assertEqual(catalog['B'].descriptor.root,seed)
        store.select('B','pre')
        self.assertTrue((user/'preferences.json').exists())
        self.assertFalse((seed/'preferences.json').exists())
        # An updater can replace the seed manifest; untouched B follows it.
        (seed/'updated.npz').write_bytes(b'new fixture')
        (seed/'library.json').write_text(json.dumps({'models':{'A':{'variants':{'pre':'mesh.npz'}},'B':{'name':'Updated B','variants':{'pre':'updated.npz'}}}}))
        refreshed=DeferredVariantEntry(catalog['B'].meta,store)
        self.assertEqual(refreshed.name,'Updated B')
        self.assertEqual(refreshed.descriptor.path,seed/'updated.npz')
        self.assertEqual(store.metadata('A').name,'User A')

    def test_new_override_manifest_is_detected(self):
        seed=self.root/'seed';user=self.root/'user';seed.mkdir()
        (seed/'mesh.npz').write_bytes(b'fixture')
        (seed/'library.json').write_text(json.dumps({'models':{'A':{'variants':{'pre':'mesh.npz'}}}}))
        store=MergedLocalLibrary(seed,user);catalog=load_active_catalog(store=store)
        user.mkdir();(user/'result.npz').write_bytes(b'fixture')
        (user/'library.json').write_text(json.dumps({'models':{'A':{'variants':{'post':'result.npz'}}}}))
        refreshed=DeferredVariantEntry(catalog['A'].meta,store)
        self.assertEqual(refreshed.variant,'post')
        self.assertEqual(refreshed.descriptor.path,user/'result.npz')

    def test_cancel_does_not_save_preference(self):
        store=self.library({'sample':{'variants':{'pre':'before.npz'}}})
        def cancel():raise RuntimeError('cancelled')
        with self.assertRaises(RuntimeError):store.select('sample','pre',before_persist=cancel)
        self.assertFalse(store.preferences_path.exists())

if __name__=='__main__':unittest.main()
