"""Release storage checks use owned tiny files; no hosted cleanup or network."""
import json
import importlib.util
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging'))
from model_library_seed import install_seed_files, post_library_data, seed_files
from prepare_release_runner import checkout_lfs, hosted_checkout, required_lfs
from release_storage import ci_links_enabled, immutable_copy


class ReleaseStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_ci_seed_and_frozen_app_share_read_only_assets_without_losing_companions(self):
        library = self.root / 'library'
        library.mkdir()
        (library / 'model.glb').write_bytes(b'accepted native geometry')
        (library / 'tooth_pre_refine.teaching.json').write_bytes(b'accepted teaching metadata')
        (library / 'unused.npz').write_bytes(b'old unselected geometry')
        (library / 'library.json').write_text(json.dumps({'models': {'tooth': {'variants': {'post': {
            'path': 'model.glb', 'companions': {'viewer': 'tooth_pre_refine.teaching.json'}}}}}}))
        before = {path.name: path.read_bytes() for path in library.iterdir()}
        metadata, selected = post_library_data(library)
        self.assertEqual(set(selected), {'model.glb', 'tooth.teaching.json'})
        files = seed_files(library, self.root / 'build', link_assets=True)
        frozen = self.root / 'frozen/_internal'
        install_seed_files(files, frozen)
        destination = frozen / 'data/local_model_library'
        self.assertEqual({path.name for path in destination.iterdir()},
                         {'model.glb', 'tooth.teaching.json', 'library.json'})
        self.assertTrue(os.path.samefile(library / 'model.glb', destination / 'model.glb'))
        self.assertTrue(os.path.samefile(library / 'tooth_pre_refine.teaching.json', destination / 'tooth.teaching.json'))
        self.assertEqual(json.loads((destination / 'library.json').read_text()), metadata)
        self.assertEqual(before, {path.name: path.read_bytes() for path in library.iterdir()})

    def test_copy_fallback_is_independent_when_links_are_unavailable(self):
        source, destination = self.root / 'source', self.root / 'destination'
        source.write_bytes(b'preserved')
        with patch('release_storage.os.link', side_effect=OSError('different filesystem')):
            immutable_copy(source, destination)
        destination.write_bytes(b'changed copy')
        self.assertEqual(source.read_bytes(), b'preserved')

    def test_selected_lfs_excludes_historical_models_but_keeps_atlas(self):
        rows = [{'name': name} for name in ('data/anatomy/vertices.bin', 'models/old.glb',
                'data/local_model_library/old.npz', 'data/local_model_library/accepted.glb')]
        selected = {self.root / 'data/local_model_library/accepted.glb'}
        self.assertEqual([row['name'] for row in required_lfs(self.root, rows, selected)],
                         ['data/anatomy/vertices.bin', 'data/local_model_library/accepted.glb'])
        self.assertEqual(required_lfs(self.root, rows, None), rows)

    def test_lfs_checkout_links_exact_cached_object_without_a_second_allocation(self):
        digest = hashlib.sha256(b'accepted model').hexdigest()
        storage = self.root / '.git/lfs/objects'
        cached = storage / digest[:2] / digest[2:4] / digest
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b'accepted model')
        target = self.root / 'model.glb'
        target.write_bytes(b'git lfs pointer')
        checkout_lfs(self.root, storage, [{'name': 'model.glb', 'oid': digest, 'oid_type': 'sha256', 'size': 14}])
        self.assertTrue(os.path.samefile(cached, target))
        self.assertEqual(cached.read_bytes(), b'accepted model')

    def test_corrupt_lfs_cache_is_rejected_before_the_pointer_is_replaced(self):
        digest = hashlib.sha256(b'accepted model').hexdigest()
        storage = self.root / '.git/lfs/objects'
        cached = storage / digest[:2] / digest[2:4] / digest
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b'corrupted data')
        target = self.root / 'model.glb'
        target.write_bytes(b'original pointer')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            checkout_lfs(self.root, storage, [{'name': 'model.glb', 'oid': digest, 'oid_type': 'sha256', 'size': 14}])
        self.assertEqual(target.read_bytes(), b'original pointer')

    def test_hardlink_and_cleanup_modes_reject_developer_or_self_hosted_sessions(self):
        for environment in ({'AE_RELEASE_HARDLINKS': '1'},
                            {'AE_RELEASE_HARDLINKS': '1', 'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted'}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(ValueError):
                    ci_links_enabled()
                with self.assertRaises(SystemExit):
                    hosted_checkout()

    def test_mac_dmg_creation_reaches_image_build_with_shared_sealed_data(self):
        path = Path(__file__).resolve().parents[1] / 'packaging/build.py'
        spec = importlib.util.spec_from_file_location('release_storage_build', path)
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        dist, pkg = self.root / 'dist', self.root / 'packaging'
        app = dist / 'Layered Human.app'
        model = app / 'Contents/Resources/data/local_model_library/model.glb'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'accepted geometry')
        (app / 'Contents/Resources/VERSION').write_text('4.0.11')
        binaries = app / 'Contents/MacOS'
        binaries.mkdir()
        (binaries / 'AnatomyExplorer').write_bytes(b'fixture bootloader')
        (binaries / 'LayeredHuman').write_bytes(b'fixture bootloader')
        commands = []
        def run(*command, **kwargs):
            commands.append(command)
            if command[0] == 'hdiutil':
                staged = pkg / 'build/dmg/Layered Human.app' / model.relative_to(app)
                self.assertTrue(os.path.samefile(model, staged))
                Path(command[-1]).write_bytes(b'fixture disk image')
        with patch.object(build, 'DIST', dist), patch.object(build, 'PKG', pkg), \
                patch.object(build, 'RELEASE', dist / 'release'), patch.object(build, 'run', side_effect=run), \
                patch.dict(os.environ, {'AE_RELEASE_HARDLINKS': '1', 'GITHUB_ACTIONS': 'true',
                                        'RUNNER_ENVIRONMENT': 'github-hosted'}), \
                patch.object(Path, 'symlink_to', lambda path, target: path.write_text(str(target))):
            manifest = build.mac_dmg()
        self.assertEqual(manifest['platform'], 'macos-arm64')
        self.assertTrue((dist / 'release' / build.MAC_ASSET).is_file())
        self.assertEqual(sum(command[0] == 'hdiutil' for command in commands), 1)
        self.assertTrue(any(command[:4] == ('codesign', '--verify', '--deep', '--strict')
                            and 'build/dmg' in Path(command[4]).as_posix() for command in commands))
        self.assertEqual(model.read_bytes(), b'accepted geometry')


if __name__ == '__main__':
    unittest.main()
