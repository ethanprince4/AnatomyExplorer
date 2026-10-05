"""Build dispatch tests; no geometry builders, installer or GPU work."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent

def module(name):
    spec = importlib.util.spec_from_file_location('release_' + name, ROOT / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class SeedPrebuildTests(unittest.TestCase):
    def test_seed_skips_micro_but_keeps_atlas_and_original_models(self):
        build, prebuild = module('build'), module('prebuild')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / 'data/local_model_library'
            seed.mkdir(parents=True)
            (seed / 'post.npz').write_bytes(b'fixture')
            (seed / 'library.json').write_text(json.dumps({'models': [{'id':'sample', 'variants':{'post':'post.npz'}}]}))
            with patch.object(build, 'ROOT', root), patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', ['build.py','--no-package']), patch.object(build, 'run') as run, patch.object(build, 'pyinstaller') as freeze:
                build.main()
                self.assertIn('--skip-micro', run.call_args.args)
                self.assertEqual(freeze.call_args.kwargs['model_library'], str(seed))
            with patch.object(sys, 'argv', ['prebuild.py', '--skip-micro']), patch.object(prebuild, 'micro') as micro, patch.object(prebuild, 'anatomy') as anatomy, patch.object(prebuild, 'models') as models:
                prebuild.main()
                micro.assert_not_called()
                anatomy.assert_called_once()
                models.assert_called_once()
            (seed / 'library.json').write_text(json.dumps({'models':[{'id':'sample','variants':{'pre':'post.npz'}}]}))
            with patch.object(build, 'ROOT', root), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError): build.selected_model_library([])
    def test_no_seed_keeps_procedural_prebuild(self):
        build, prebuild = module('build'), module('prebuild')
        with tempfile.TemporaryDirectory() as temporary, patch.object(build,'ROOT',Path(temporary)), patch.dict(os.environ,{},clear=True):
            self.assertIsNone(build.selected_model_library([]))
        with patch.object(sys,'argv',['prebuild.py']), patch.object(prebuild,'micro') as micro, patch.object(prebuild,'anatomy'), patch.object(prebuild,'models'):
            prebuild.main()
            micro.assert_called_once_with(4)

if __name__ == '__main__': unittest.main()
