"""Protect release identities, source boundaries and immutable baseline assets."""
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import build_update_bridge as bridge
import check_bundle_update


class Response(io.BytesIO):
    url = "https://release-assets.githubusercontent.com/verified-release-asset"


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def asset(self, data=b"verified asset"):
        return {"name": "AnatomyExplorer-Windows-pack-0000.bin", "size": len(data),
                "digest": "sha256:" + bridge.hashlib.sha256(data).hexdigest(),
                "browser_download_url": "https://github.com/ethanprince4/AnatomyExplorer/releases/download/"
                                        "v4.0.11/AnatomyExplorer-Windows-pack-0000.bin"}

    def test_release_asset_requires_exact_repository_tag_size_and_api_digest(self):
        asset = self.asset()
        checked = bridge.checked_asset(asset, "ethanprince4/AnatomyExplorer", "v4.0.11", asset["size"])
        self.assertEqual(checked["sha256"], asset["digest"][7:])
        for updates in ({"digest": None}, {"digest": "sha256:" + "g" * 64}, {"size": True},
                        {"name": "../pack.bin"}, {"browser_download_url": asset["browser_download_url"] + "?replacement"}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                bridge.checked_asset({**asset, **updates}, "ethanprince4/AnatomyExplorer", "v4.0.11")
        with self.assertRaises(ValueError):
            bridge.checked_asset(asset, "ethanprince4/AnatomyExplorer", "v4.0.12")
        with self.assertRaises(ValueError):
            bridge.checked_asset(asset, "ethanprince4/AnatomyExplorer", "v4.0.11", asset["size"] + 1)

    def test_download_verifies_before_publish_and_rechecks_cached_bytes(self):
        data = b"verified asset"
        asset = bridge.checked_asset(self.asset(data), "ethanprince4/AnatomyExplorer", "v4.0.11")
        with patch.object(bridge.urllib.request, "urlopen", return_value=Response(data)) as fetch:
            path = bridge.download_asset(asset, self.root)
        self.assertEqual(path.read_bytes(), data)
        with patch.object(bridge.urllib.request, "urlopen", side_effect=AssertionError("Verified cache fetched")):
            bridge.download_asset(asset, self.root)
        path.write_bytes(b"changed bytes!")
        with patch.object(bridge.urllib.request, "urlopen", return_value=Response(data)):
            bridge.download_asset(asset, self.root)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(fetch.call_count, 1)
        path.unlink()
        with patch.object(bridge.urllib.request, "urlopen", return_value=Response(b"bad")), self.assertRaises(ValueError):
            bridge.download_asset(asset, self.root)
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name(path.name + ".bridge-download").exists())

    def fixture(self, mac=False):
        base, candidate, source = (self.root / name for name in ("base", "candidate", "source"))
        resource = "Contents/Resources" if mac else "_internal"
        for name, data in (("app/updater.py", b"VALUE = 'old'\n"), ("app/micro/approved.py", b"MODEL = 'approved'\n"),
                           ("data/local_model_library/model.glb", b"accepted model bytes"),
                           ("VERSION", b"4.0.11"), ("UPDATE_CHANNEL.json", b'{"channel":"stable","release_tag":"v4.0.11"}')):
            path = base / resource / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if mac:
            (base / "Contents/Info.plist").write_bytes(plistlib.dumps({
                "CFBundleVersion": "4.0.11", "CFBundleShortVersionString": "4.0.11", "CFBundleName": "Layered Human"}))
        else:
            for name in ("AnatomyExplorer.exe", "LayeredHuman.exe"):
                (base / name).write_bytes(b"unchanged frozen launcher")
        patch_source = source / "app/updater.py"
        patch_source.parent.mkdir(parents=True)
        patch_source.write_bytes(b"VALUE = 'new'\n")
        bridge.clone_bundle(base, candidate)
        return base, candidate, source, resource

    def apply(self, base, candidate, source, mac=False):
        result = subprocess.CompletedProcess([], 0, stdout=b"VALUE = 'old'\n")
        with patch.object(bridge.subprocess, "run", return_value=result):
            return bridge.patch_bundle(base, candidate, source, ["app/updater.py"], bridge.BASE_COMMIT,
                                       "4.0.12", "macos-arm64" if mac else "windows-x64", "v4.0.12")

    def test_selected_source_patch_preserves_original_and_approved_assets_and_aliases(self):
        base, candidate, source, resources = self.fixture()
        original_code = base / resources / "app/updater.py"
        candidate_code = candidate / resources / "app/updater.py"
        self.assertNotEqual(original_code.stat().st_ino, candidate_code.stat().st_ino)
        original_model = base / resources / "data/local_model_library/model.glb"
        candidate_model = candidate / resources / "data/local_model_library/model.glb"
        self.assertEqual(original_model.stat().st_ino, candidate_model.stat().st_ino)
        self.apply(base, candidate, source)
        self.assertEqual(original_code.read_bytes(), b"VALUE = 'old'\n")
        self.assertEqual(candidate_code.read_bytes(), b"VALUE = 'new'\n")
        self.assertEqual((candidate / resources / "app/micro/approved.py").read_bytes(), b"MODEL = 'approved'\n")
        self.assertEqual(candidate_model.read_bytes(), original_model.read_bytes())
        self.assertEqual((candidate / "AnatomyExplorer.exe").read_bytes(), (candidate / "LayeredHuman.exe").read_bytes())
        self.assertEqual(json.loads((candidate / resources / "UPDATE_CHANNEL.json").read_bytes()),
                         {"channel": "stable", "release_tag": "v4.0.12"})

    def test_frozen_source_must_match_exact_pinned_git_blob(self):
        base, candidate, source, resources = self.fixture()
        (base / resources / "app/updater.py").write_bytes(b"VALUE = 'unexpected'\n")
        with self.assertRaisesRegex(ValueError, "pinned source commit"):
            self.apply(base, candidate, source)
        self.assertEqual((candidate / resources / "VERSION").read_bytes(), b"4.0.11")

    def test_transferred_pinned_source_catalog_needs_no_git_checkout(self):
        base, candidate, source, resources = self.fixture()
        old = (base / resources / "app/updater.py").read_bytes()
        catalog = {"base_commit": bridge.BASE_COMMIT, "files": {
            "app/updater.py": {"size": len(old), "sha256": bridge.hashlib.sha256(old).hexdigest()}}}
        with patch.object(bridge.subprocess, "run", side_effect=AssertionError("Git is unavailable on transfer")):
            bridge.patch_bundle(base, candidate, source, ["app/updater.py"], bridge.BASE_COMMIT,
                                "4.0.12", "windows-x64", "v4.0.12", source_baseline=catalog)
        self.assertEqual((candidate / resources / "app/updater.py").read_bytes(), b"VALUE = 'new'\n")

    def test_mac_patch_updates_both_bundle_version_fields_before_signing(self):
        base, candidate, source, resources = self.fixture(mac=True)
        self.apply(base, candidate, source, mac=True)
        info = plistlib.loads((candidate / "Contents/Info.plist").read_bytes())
        self.assertEqual((info["CFBundleVersion"], info["CFBundleShortVersionString"]), ("4.0.12", "4.0.12"))
        self.assertEqual(info["CFBundleName"], "Layered Human")
        self.assertEqual(plistlib.loads((base / "Contents/Info.plist").read_bytes())["CFBundleVersion"], "4.0.11")

    def test_patch_paths_cannot_target_data_or_escape_app(self):
        for name in ("../app/updater.py", "app/../updater.py", "app\\updater.py", "/app/updater.py",
                     "app//updater.py", "app/updater.py/", "data/model.py", "app/model.glb"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bridge.patch_name(name)

    def test_complete_delta_rejects_unselected_changed_or_removed_assets(self):
        previous = {"platform": "windows-x64", "files": [
            {"path": "_internal/app/updater.py", "sha256": "old"},
            {"path": "_internal/data/approved.glb", "sha256": "asset"}], "symlinks": []}
        target = {**previous, "files": [{"path": "_internal/app/updater.py", "sha256": "new"}, previous["files"][1]]}
        result = bridge.verify_delta(self.root, self.root, previous, target, {"_internal/app/updater.py"})
        self.assertTrue(result["baseline_assets_and_unselected_sources_preserved"])
        with self.assertRaisesRegex(ValueError, "Unexpected frozen bundle change"):
            bridge.verify_delta(self.root, self.root, previous,
                {**target, "files": [target["files"][0], {"path": "_internal/data/approved.glb", "sha256": "changed"}]},
                {"_internal/app/updater.py"})
        with self.assertRaisesRegex(ValueError, "preserve every baseline path"):
            bridge.verify_delta(self.root, self.root, previous, {**target, "files": target["files"][:1]}, set())

    def test_windows_native_profile_avoids_checkout_nested_dll_path_limit(self):
        base = self.root / "base/LayeredHuman"
        old_profile = Path("C:/Users/Ethan/Desktop/LayeredHuman-Cloudflare-Updater/packaging/build/cloudflare-bridge/"
                           "windows-v4.0.12/base/update-validation/profile")
        with self.assertRaisesRegex(ValueError, "too deep"):
            check_bundle_update.validate_profile_paths(old_profile, base, "4.0.12")
        length = check_bundle_update.validate_profile_paths(self.root / "profile", base, "4.0.12")
        self.assertLess(length, 240)


if __name__ == "__main__":
    unittest.main()
