"""Offline release integration: real update packs, activation and rollback."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))
from app.updater import UpdateStore, UpdateError, safe_path
from update_payload import create_payload
from model_library_seed import seed_files


class Packs:
    def __init__(self, path): self.path = path
    def chunk(self, blob, total):
        with (self.path / blob['pack']).open('rb') as stream:
            stream.seek(blob['offset'])
            return stream.read(blob['size'])


class LibraryReleaseTests(unittest.TestCase):
    def test_activation_rollback_cleanup_preserve_accepted_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / 'profile/AnatomyExplorer/model-library'
            library.mkdir(parents=True)
            (library / 'accepted.npz').write_bytes(b'accepted geometry')
            (library / 'library.json').write_text('{"models":[]}')
            (library / 'preferences.json').write_text('{"kidney":"post"}')
            before = {p.name:p.read_bytes() for p in library.iterdir()}
            for name, version in [('base','1.0.0'),('next','1.0.1')]:
                bundle = root / name
                (bundle / '_internal/data/local_model_library').mkdir(parents=True)
                (bundle / 'AnatomyExplorer.exe').write_bytes(version.encode())
                (bundle / '_internal/VERSION').write_text(version)
                (bundle / '_internal/data/local_model_library/library.json').write_text('{"models":[]}')
                manifest = create_payload(bundle, root / (name+'packs'), version)
            store = UpdateStore(root/'base', root/'profile/AnatomyExplorer/updates/test')
            self.assertEqual(store.prepare(manifest,Packs(root/'nextpacks'))['status'],'ready')
            self.assertNotEqual(store.activate(),root/'base')
            store.healthy()
            self.assertTrue(store.rollback())
            store.cleanup()
            self.assertEqual(before,{p.name:p.read_bytes() for p in library.iterdir()})

    def test_mutable_library_cannot_be_update_payload(self):
        for path,platform in [('_internal/model-library/library.json','windows-x64'),
                              ('Contents/Resources/model-library/library.json','macos-arm64')]:
            with self.assertRaises(UpdateError): safe_path(path,platform)
        safe_path('_internal/data/local_model_library/library.json')

    def test_seed_packages_models_but_not_personal_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'sample.npz').write_bytes(b'geometry')
            (root/'library.json').write_text(json.dumps({'models':[{'id':'sample','variants':{'post':'sample.npz'}}]}))
            (root/'preferences.json').write_text('{}')
            files=seed_files(root)
            self.assertEqual({Path(src).name for src,dst in files},{'sample.npz','library.json'})
            self.assertTrue(all(Path(dst).as_posix()=='data/local_model_library' for src,dst in files))

if __name__ == '__main__': unittest.main()
