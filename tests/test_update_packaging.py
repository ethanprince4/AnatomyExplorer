"""Release feeds must agree with embedded metadata without changing a sealed app."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
from update_payload import create_payload
from app.updater import UpdateStore, file_sha
from tests.fixture_paths import fixture_root


class ChannelPackagingTests(unittest.TestCase):
    def test_stable_package_has_default_off_policy_and_matching_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            bundle = root / "app"
            (bundle / "_internal").mkdir(parents=True)
            (bundle / "AnatomyExplorer.exe").write_bytes(b"test executable")
            (bundle / "_internal/VERSION").write_text("3.1.2")
            (bundle / "_internal/UPDATE_CHANNEL.json").write_text(json.dumps(
                {"channel": "stable", "release_tag": "v3.1.2"}))
            manifest = create_payload(bundle, root / "feed", "3.1.2")
            store = UpdateStore(bundle, root / "updates")
            self.assertEqual(store.policy(), ("stable", 0))
            self.assertEqual(store.verify(bundle), manifest)
            self.assertEqual(manifest["launcher"], 1)

    def test_preview_metadata_must_exist_and_match_before_packing(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            bundle = root / "app"
            (bundle / "_internal").mkdir(parents=True)
            (bundle / "AnatomyExplorer.exe").write_bytes(b"test executable")
            (bundle / "_internal/VERSION").write_text("3.90.1")
            kwargs = {"channel": "experimental", "release_tag": "v3.90.1-preview.1"}
            with self.assertRaises(ValueError):
                create_payload(bundle, root / "feed", "3.90.1", **kwargs)
            metadata = bundle / "_internal/UPDATE_CHANNEL.json"
            metadata.write_text(json.dumps({"channel": "stable", "release_tag": "v3.90.1"}))
            with self.assertRaises(ValueError):
                create_payload(bundle, root / "feed", "3.90.1", **kwargs)
            metadata.write_text(json.dumps(kwargs))
            manifest = create_payload(bundle, root / "feed", "3.90.1", **kwargs)
            self.assertEqual(manifest["channel"], "experimental")
            self.assertEqual(UpdateStore(bundle, root / "updates").policy(), ("stable", 0))

    def test_mac_channel_feed_preserves_every_sealed_bundle_byte(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            bundle = root / "Experimental.app"
            resources = bundle / "Contents/Resources"
            resources.mkdir(parents=True)
            executable = bundle / "Contents/MacOS/AnatomyExplorer"
            executable.parent.mkdir()
            executable.write_bytes(b"test executable")
            (resources / "VERSION").write_text("3.90.1")
            (resources / "UPDATE_CHANNEL.json").write_text(json.dumps(
                {"channel": "experimental", "release_tag": "v3.90.1-preview.1"}))
            seal = bundle / "Contents/_CodeSignature/CodeResources"
            seal.parent.mkdir()
            seal.write_bytes(b"already sealed bundle test marker")
            before = {p.relative_to(bundle).as_posix(): file_sha(p) for p in bundle.rglob("*") if p.is_file()}
            manifest = create_payload(bundle, root / "feed", "3.90.1", "macos-arm64",
                                      channel="experimental", release_tag="v3.90.1-preview.1")
            after = {p.relative_to(bundle).as_posix(): file_sha(p) for p in bundle.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(manifest["channel"], "experimental")
            self.assertTrue((root / "feed/AnatomyExplorer-macOS-update.json").exists())


if __name__ == "__main__":
    unittest.main()
