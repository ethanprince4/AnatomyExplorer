"""Release collection reads source only and never falls back to pre geometry."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'packaging'))
from model_library_seed import stage_post_library,seed_files,export_post_library

class PostSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source';self.root.mkdir()
    def write(self,path,data=b'asset'):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    def manifest(self,models):
        self.write('library.json',json.dumps({'schema':'ae.local-library.v1','models':models}).encode())
    def test_post_assets_only_and_source_unchanged(self):
        for path in ['pre.npz','post.npz','history/old.npz','report.json','colors.npz','controls.json','inset.npz','unused.glb','witnesses.json','tooth_pre_refine.teaching.json']:
            self.write(path)
        self.manifest({'a':{'name':'A','variants':{'pre':{'path':'pre.npz'},'post':{'path':'post.npz',
            'report':'report.json','runtime_controls':'controls.json','companions':{'colors':'colors.npz', 'witnesses':'witnesses.json', 'viewer':'tooth_pre_refine.teaching.json'},
            'components':{'cell_inset':{'path':'inset.npz'}}}}}})
        before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        stage=stage_post_library(self.root)
        self.assertEqual({p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()},
                         {'library.json','post.npz','controls.json','colors.npz','inset.npz','tooth.teaching.json'})
        manifest=json.loads((stage/'library.json').read_text())
        self.assertEqual(set(manifest['models']['a']['variants']),{'post'})
        self.assertNotIn('report',manifest['models']['a']['variants']['post'])
        self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_portable_export_keeps_ids_and_normalizes_public_names(self):
        self.write('post.npz')
        self.manifest({'lung_acinus_review_v2':{'name':'Internal review title','variants':{'post':'post.npz'}}})
        target=Path(self.temp.name)/'release'
        export_post_library(self.root,target)
        data=json.loads((target/'library.json').read_text())
        self.assertEqual(set(data['models']),{'lung_acinus_review_v2'})
        self.assertEqual(data['models']['lung_acinus_review_v2']['name'],'Lung acinus (version 2)')
        self.assertEqual((target/'post.npz').read_bytes(),b'asset')
        with self.assertRaisesRegex(ValueError,'empty directory'):export_post_library(self.root,target)
        with self.assertRaisesRegex(ValueError,'outside'):export_post_library(self.root,self.root/'export')

    def test_missing_posts_report_all_models_without_substitution(self):
        self.write('pre.npz');self.manifest({'a':{'variants':{'pre':'pre.npz'}},'b':{'variants':{}}})
        with self.assertRaisesRegex(ValueError,'Missing post: a, b'):stage_post_library(self.root)
    def test_missing_selected_asset_and_escape_fail_actionably(self):
        self.manifest([{'id':'a','variants':{'post':{'path':'missing.npz'}}}])
        with self.assertRaisesRegex(FileNotFoundError,'declared release asset is missing'):stage_post_library(self.root)
        self.manifest([{'id':'a','variants':{'post':{'path':'../outside.npz'}}}])
        with self.assertRaisesRegex(ValueError,'relative to the library'):stage_post_library(self.root)
    def test_build_spec_files_use_persistent_staging_paths(self):
        self.write('post.npz');self.manifest([{'id':'a','variants':{'post':'post.npz'}}])
        files=seed_files(self.root,Path(self.temp.name)/'build')
        self.assertEqual(len(files),2)
        self.assertTrue(all(Path(p).is_file() and not Path(p).is_relative_to(self.root) for p,_ in files))
        self.assertTrue(all(dest=='data/local_model_library' or dest=='data\\local_model_library' for _,dest in files))
        with self.assertRaisesRegex(ValueError,'outside'):stage_post_library(self.root,self.root/'stage')

if __name__=='__main__':unittest.main()
