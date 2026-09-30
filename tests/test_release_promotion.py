"""Publication rejects altered archives and files outside the tested feed."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('release_promotion',
    Path(__file__).resolve().parents[1] / 'packaging/promote_3_1_2.py')
PROMOTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMOTE)


class ReleasePromotionTests(unittest.TestCase):
    def fixture(self, root, extra=None, version='3.1.2', pack_bytes=b'abc'):
        manifest = {'schema': 1, 'platform': 'windows-x64', 'launcher': 1,
                    'version': version, 'channel': 'stable', 'release_tag': 'v' + version,
                    'files': [{'path': path, 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest(),
                               'chunks': []} for path in ('AnatomyExplorer.exe', '_internal/VERSION')],
                    'blobs': {}, 'packs': {'AnatomyExplorer-Windows-pack-0000.bin': 3}}
        archive = root / 'input.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('AnatomyExplorer-Setup-Windows.exe', b'tested installer')
            bundle.writestr('AnatomyExplorer-Windows-update.json', json.dumps(manifest))
            bundle.writestr('AnatomyExplorer-Windows-pack-0000.bin', pack_bytes)
            if extra:
                bundle.writestr(extra, b'must not publish')
        item = dict(PROMOTE.ARTIFACTS[0], bytes=archive.stat().st_size,
                    sha256=PROMOTE.digest(archive))
        output = root / 'assets'
        output.mkdir()
        return archive, item, output

    def test_exact_flat_installer_and_complete_feed_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, item, output = self.fixture(Path(directory))
            manifest = PROMOTE.extract_verified(archive, item, output)
            self.assertEqual(manifest['version'], '3.1.2')
            self.assertEqual(len(list(output.iterdir())), 3)
            self.assertEqual((output / item['name']).read_bytes(), b'tested installer')

    def test_changed_archive_digest_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, item, output = self.fixture(Path(directory))
            item['sha256'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'archive bytes'):
                PROMOTE.extract_verified(archive, item, output)
            self.assertFalse(list(output.iterdir()))

    def test_diagnostic_artifact_and_traversal_cannot_be_published(self):
        for extra in ('controls.json', '../private.txt', 'folder/file', 'folder\\file'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                archive, item, output = self.fixture(Path(directory), extra=extra)
                with self.assertRaises(RuntimeError):
                    PROMOTE.extract_verified(archive, item, output)
                self.assertFalse(list(output.iterdir()))

    def test_wrong_version_and_truncated_pack_are_rejected(self):
        for options in ({'version': '3.1.1'}, {'pack_bytes': b'a'}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                archive, item, output = self.fixture(Path(directory), **options)
                with self.assertRaises(RuntimeError):
                    PROMOTE.extract_verified(archive, item, output)
                self.assertFalse(list(output.iterdir()))

    def test_uploaded_inventory_requires_exact_names_size_hash_and_completion(self):
        import copy
        inventory = {'installer.exe': {'bytes': 100, 'sha256': 'a' * 64}}
        release = {'assets': [{'name': 'installer.exe', 'size': 100,
                              'digest': 'sha256:' + 'a' * 64, 'state': 'uploaded'}]}
        self.assertEqual(set(PROMOTE.verify_inventory(release, inventory)), {'installer.exe'})
        for field, value in (('name', 'controls.json'), ('size', 99),
                             ('digest', 'sha256:' + 'b' * 64), ('state', 'new')):
            with self.subTest(field=field):
                changed = copy.deepcopy(release)
                changed['assets'][0][field] = value
                with self.assertRaises(RuntimeError):
                    PROMOTE.verify_inventory(changed, inventory)
        for assets in ([], release['assets'] * 2):
            with self.subTest(assets=assets), self.assertRaises(RuntimeError):
                PROMOTE.verify_inventory({'assets': assets}, inventory)


if __name__ == '__main__':
    unittest.main()
