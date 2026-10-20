"""Release feeds must agree with embedded metadata without changing a sealed app."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
from update_payload import create_payload
from app import updater as u
from app.updater import UpdateStore, file_sha
from tests.fixture_paths import fixture_root
from tests.test_updater import LocalSource
from tests.test_updater_channels import legacy


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
            self.assertEqual((root / "feed" / u.MAC_MANIFEST).read_bytes(),
                             (root / "feed" / u.PUBLIC_MAC_MANIFEST).read_bytes())


class BrandingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture_root(self.temp.name)
        self.base, self.candidate, self.feed = (self.root / name for name in ("base", "candidate", "feed"))
        for bundle, version in ((self.base, "4.0.10"), (self.candidate, "4.0.11")):
            (bundle / "_internal").mkdir(parents=True)
            (bundle / "AnatomyExplorer.exe").write_bytes(b"launcher " + version.encode())
            (bundle / "_internal/VERSION").write_text(version)
        (self.candidate / "LayeredHuman.exe").write_bytes((self.candidate / "AnatomyExplorer.exe").read_bytes())
        create_payload(self.base, self.root / "old-feed", "4.0.10")
        self.manifest = create_payload(self.candidate, self.feed, "4.0.11")
        self.compat = json.loads((self.feed / u.MANIFEST).read_text())

    def release(self, repo=u.REPO):
        prefix = f"https://github.com/{repo}/releases/download/v4.0.11/"
        assets = []
        for name in (u.MANIFEST, u.PUBLIC_MANIFEST):
            raw = (self.feed / name).read_bytes()
            assets.append({"name": name, "size": len(raw), "digest": "sha256:" + u.sha(raw),
                           "browser_download_url": prefix + name})
        assets.extend({"name": name, "size": size, "browser_download_url": prefix + name}
                      for name, size in self.manifest["packs"].items())
        return {"tag_name": "v4.0.11", "assets": assets, "draft": False, "prerelease": False}

    def test_legacy_bootstrap_can_stage_new_brand_and_new_updater_can_take_over(self):
        self.assertIn("LayeredHuman.exe", {entry["path"] for entry in self.manifest["files"]})
        self.assertNotIn("LayeredHuman.exe", {entry["path"] for entry in self.compat["files"]})
        legacy.validate_manifest(self.compat)
        old = legacy.UpdateStore(self.base, self.root / "updates")
        old.prepare(self.compat, LocalSource(self.feed))
        active = old.activate()
        old.verify(active)
        self.assertEqual(u.application_executable(active).name, "AnatomyExplorer.exe")
        new = UpdateStore(self.base, old.root)
        self.assertEqual(new.verify(active)["version"], "4.0.11")
        new.healthy()
        new.rollback()
        new.prepare(self.manifest, LocalSource(self.feed))
        active = old.activate()  # the immutable launcher still supervises this installation
        old.verify(active)
        self.assertEqual(u.application_executable(active).name, "LayeredHuman.exe")
        self.assertEqual(new.verify(active), self.manifest)

    def test_new_feed_prefers_public_manifest_and_old_feed_prefers_compatibility_manifest(self):
        release = self.release()
        new = u.GitHubSource(platform="windows-x64")
        with patch.object(new, "read", return_value=(self.feed / u.PUBLIC_MANIFEST).read_bytes()):
            self.assertEqual(new.from_release(release), self.manifest)
        self.assertEqual(new.manifest_name, u.PUBLIC_MANIFEST)
        old = legacy.GitHubSource()
        with patch.object(old, "read", side_effect=[json.dumps(release).encode(), (self.feed / u.MANIFEST).read_bytes()]):
            self.assertEqual(old.latest(), self.compat)

    def test_future_repository_identity_is_fixed_and_packs_cannot_cross_repositories(self):
        release = self.release("ethanprince4/LayeredHuman")
        source = u.GitHubSource(platform="windows-x64")
        with patch.object(source, "read", return_value=(self.feed / u.PUBLIC_MANIFEST).read_bytes()):
            self.assertEqual(source.from_release(release), self.manifest)
            release["assets"][-1]["browser_download_url"] = release["assets"][-1]["browser_download_url"].replace(
                "ethanprince4/LayeredHuman", u.REPO)
            with self.assertRaisesRegex(u.UpdateError, "untrusted release pack"):
                source.from_release(release)
        release = self.release("someone/LayeredHuman")
        with self.assertRaisesRegex(u.UpdateError, "trusted repository"):
            source.from_release(release)

    def test_invalid_public_manifest_never_silently_falls_back_to_legacy(self):
        release = self.release()
        release["assets"][1]["digest"] = "sha256:" + "0" * 64
        source = u.GitHubSource(platform="windows-x64")
        with patch.object(source, "read", return_value=(self.feed / u.PUBLIC_MANIFEST).read_bytes()):
            with self.assertRaisesRegex(u.UpdateError, "integrity"):
                source.from_release(release)


if __name__ == "__main__":
    unittest.main()
