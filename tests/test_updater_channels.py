"""Channel security and compatibility with the immutable v3.1.1 bootstrap.

All packages/downloads are tiny local fixtures; no account, GUI or user data.
"""
import copy
import gzip
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import updater as u

LEGACY_PATH = Path(__file__).parent / "fixtures/legacy_updater_v3_1_1.py"
legacy_spec = importlib.util.spec_from_file_location("immutable_updater_v3_1_1", LEGACY_PATH)
legacy = importlib.util.module_from_spec(legacy_spec)
legacy_spec.loader.exec_module(legacy)


class Packs:
    def __init__(self, data, callback=None):
        self.data, self.callback = data, callback
        self.bytes = 0

    def chunk(self, blob, total):
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        self.bytes += blob["size"]
        return self.data[blob["offset"]:blob["offset"]+blob["size"]]


def package(root, version, channel="stable", tag=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "_internal/data").mkdir(parents=True, exist_ok=True)
    (root / "AnatomyExplorer.exe").write_bytes(b"tiny fixture executable " + version.encode())
    (root / "_internal/VERSION").write_text(version)
    (root / "_internal/data/model.bin").write_bytes(b"unchanged atlas data"*50)
    if tag:
        (root / "_internal/UPDATE_CHANNEL.json").write_text(json.dumps({"channel": channel, "release_tag": tag}))
    manifest = {"schema": 1, "launcher": 1, "platform": "windows-x64", "version": version,
                "channel": channel, "files": [], "packs": {}, "blobs": {}, "symlinks": []}
    if tag:
        manifest["release_tag"] = tag
    packed = bytearray()
    name = "AnatomyExplorer-Windows-pack-0000.bin"
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == u.MANIFEST:
            continue
        raw = path.read_bytes()
        digest = u.sha(raw)
        compressed = gzip.compress(raw, mtime=0)
        manifest["files"].append({"path": path.relative_to(root).as_posix(), "sha256": digest,
                                  "size": len(raw), "chunks": [digest], "mode": 0o644})
        if digest not in manifest["blobs"]:
            manifest["blobs"][digest] = {"pack": name, "offset": len(packed), "size": len(compressed), "raw_size": len(raw)}
            packed.extend(compressed)
    manifest["packs"][name] = len(packed)
    u.validate_manifest(manifest)
    u.atomic_json(root / u.MANIFEST, manifest)
    return manifest, Packs(bytes(packed))


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "original"
        self.stable, self.stable_source = package(self.base, "3.1.1")  # exact legacy metadata form
        self.store = u.UpdateStore(self.base, self.root / "store")
        self.legacy = legacy.UpdateStore(self.base, self.store.root)
        self.notes = self.root / "user/notes.json"
        self.notes.parent.mkdir()
        self.notes.write_text('{"notes":"retain"}')

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, n):
        return package(self.root / f"preview{n}", f"3.90.{n}", "experimental", f"v3.90.{n}-preview.{n}")

    def stable_anchor(self):
        manifest, source = package(self.root / "stable-feature", "3.1.2", "stable", "v3.1.2")
        # The immutable 3.1.1 client itself downloads and activates feature3.1.2;
        # no newer protocol implementation participates in that first upgrade.
        self.legacy.prepare(manifest, source)
        self.legacy.activate()
        self.legacy.healthy()
        return self.store.state()["current"]

    def test_stable_default_and_cross_channel_rejection(self):
        self.assertEqual(self.store.policy(), ("stable", 0))
        manifest, source = self.preview(1)
        with self.assertRaisesRegex(u.UpdateError, "channel"):
            self.store.prepare(manifest, source)
        self.assertEqual(source.bytes, 0)
        other_install = u.UpdateStore(self.base, self.root / "separate-install")
        self.store.set_channel("experimental")
        self.assertEqual(other_install.policy(), ("stable", 0))
        with self.assertRaises(u.UpdateError):
            self.store.prepare(self.stable, self.stable_source)

    def test_malformed_channel_metadata_fails_closed(self):
        for channel in (None, [], {}, 7, True, "draft"):
            with self.subTest(channel=channel), self.assertRaises(u.UpdateError):
                u.validate_manifest(dict(self.stable, channel=channel))
        self.store.root.mkdir(exist_ok=True)
        u.atomic_json(self.store.state_file, {"channel": ["experimental"], "current": None})
        self.assertEqual(self.store.policy(), ("stable", 0))

    def test_legacy_launcher_multiple_previews_and_stable_return(self):
        anchor = self.stable_anchor()
        self.store.set_channel("experimental")
        self.assertEqual(self.store.state()["stable_anchor"], anchor)
        for n in (1, 2, 3):
            manifest, source = self.preview(n)
            self.store.prepare(manifest, source)
            self.legacy.activate()
            self.assertEqual(u.read_manifest(self.store.active())["version"], f"3.90.{n}")
            self.store.protect_stable_anchor()  # new child, before ready marker
            self.legacy.healthy()
            self.legacy.cleanup()  # actual old three-pointer keep set
            self.assertTrue(self.store.path(anchor).exists())
            self.assertEqual(self.store.state()["previous"], anchor)
        self.store.set_channel("stable")
        self.assertTrue(self.store.state()["rollback_requested"])
        self.assertEqual(u.read_manifest(self.store.active())["version"], "3.90.3", "never interrupt study")
        self.legacy.rollback()
        self.legacy.activate()
        self.assertEqual(self.store.state()["current"], anchor)
        self.assertEqual(u.read_manifest(self.store.active())["version"], "3.1.2")
        self.assertEqual(self.notes.read_text(), '{"notes":"retain"}')
        self.assertEqual((self.base / "_internal/VERSION").read_text(), "3.1.1")

    def test_disable_cancels_pending_preview_before_old_activation(self):
        self.store.set_channel("experimental")
        manifest, source = self.preview(1)
        self.store.prepare(manifest, source)
        self.assertIsNotNone(self.store.state().get("pending"))
        self.store.set_channel("stable")
        self.assertIsNone(self.store.state().get("pending"))
        self.assertEqual(self.legacy.activate(), self.base)

    def test_inflight_download_cannot_publish_after_optout_or_reoptin(self):
        self.store.set_channel("experimental")
        manifest, source = self.preview(1)
        token = self.store.policy()
        source.callback = lambda: (self.store.set_channel("stable"), self.store.set_channel("experimental"))
        result = self.store.prepare(manifest, source, policy_token=token)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(self.store.state().get("pending"))
        self.assertEqual(self.legacy.activate(), self.base)

    def test_stable_return_suppresses_delivery_until_next_launch(self):
        self.store.set_channel("experimental")
        manifest, source = self.preview(1)
        self.store.prepare(manifest, source)
        self.legacy.activate()
        self.store.protect_stable_anchor()
        self.store.set_channel("stable")
        result = self.store.prepare(self.stable, self.stable_source)
        self.assertEqual(result["status"], "returning")
        self.assertIsNone(self.store.state().get("pending"))

    def test_preview_failed_startup_rolls_back_to_stable_anchor(self):
        anchor = self.stable_anchor()
        self.store.set_channel("experimental")
        manifest, source = self.preview(1)
        self.store.prepare(manifest, source)
        self.legacy.activate()
        self.store.protect_stable_anchor()
        self.assertTrue(self.store.state()["trial"])
        self.legacy.rollback()
        self.assertEqual(self.store.state()["current"], anchor)

    def test_fresh_separate_preview_install_returns_lower_numeric_stable(self):
        manifest, source = self.preview(1)
        preview_base = self.root / "preview1"
        direct = u.UpdateStore(preview_base, self.root / "direct-store")
        self.assertEqual(direct.policy(), ("stable", 0), "fresh preview opt-in stays unchecked")
        stable, stable_source = package(self.root / "newstable", "3.1.2", "stable", "v3.1.2")
        result = direct.prepare(stable, stable_source)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(direct.active(), preview_base)
        direct.activate()
        direct.healthy()
        self.assertEqual(u.read_manifest(direct.active())["version"], "3.1.2")
        direct.set_channel("experimental")
        self.assertEqual(direct.state()["stable_anchor"], direct.state()["current"])
        self.assertEqual(u.read_manifest(preview_base)["version"], "3.90.1")

    def test_preview_metadata_required_and_exact(self):
        manifest, source = self.preview(1)
        for mutate in (lambda m: m.pop("release_tag"), lambda m: m.update(channel="stable"),
                       lambda m: m.update(release_tag="v3.90.1-preview.2"), lambda m: m.update(version="3.90.2")):
            bad = copy.deepcopy(manifest)
            mutate(bad)
            with self.assertRaises(u.UpdateError):
                u.validate_manifest(bad)
        root = self.root / "preview1"
        (root / "_internal/UPDATE_CHANNEL.json").unlink()
        with self.assertRaises(u.UpdateError):
            self.store.verify(root, manifest)

    def test_mark_ready_protects_anchor_before_supervisor_cleanup(self):
        token = self.root / "ready"
        called = []
        with patch.object(u, "store_for", return_value=unittest.mock.Mock(protect_stable_anchor=lambda: called.append(token.exists()))), \
             patch.dict(u.os.environ, AE_READY_FILE=str(token)):
            u.mark_ready()
        self.assertEqual(called, [False])
        self.assertEqual(token.read_text(), "ready")


class ReleaseFeedTests(unittest.TestCase):
    def fixture(self, tag, channel="experimental", prerelease=True):
        version = u.release_version(tag, channel)
        with tempfile.TemporaryDirectory() as d:
            manifest, _ = package(Path(d), version, channel, tag)
        raw = json.dumps(manifest).encode()
        prefix = f"https://github.com/{u.REPO}/releases/download/{tag}/"
        assets = [{"name": u.MANIFEST, "size": len(raw), "digest": "sha256:"+u.sha(raw),
                   "browser_download_url": prefix+u.MANIFEST}]
        assets += [{"name": name, "size": size, "browser_download_url": prefix+name} for name, size in manifest["packs"].items()]
        return {"tag_name": tag, "draft": False, "prerelease": prerelease, "assets": assets}, raw, manifest

    def test_experimental_selects_latest_numbered_preview_from_prereleases_only(self):
        one, _, _ = self.fixture("v3.90.1-preview.1")
        two, raw, manifest = self.fixture("v3.90.2-preview.2")
        stable, _, _ = self.fixture("v3.1.2", "stable", False)
        unrelated = {"tag_name": "v4.0.0-beta.1", "prerelease": True, "assets": []}
        draft = copy.deepcopy(two)
        draft.update(tag_name="v3.90.9-preview.9", draft=True)
        source = u.GitHubSource("windows-x64", "experimental")
        with patch.object(source, "read", side_effect=[json.dumps([one, stable, unrelated, draft, two]).encode(), raw]) as read:
            self.assertEqual(source.latest(), manifest)
        self.assertEqual(read.call_args_list[0].args[0], u.RELEASES_API)

    def test_stable_default_uses_latest_endpoint_and_rejects_preview(self):
        stable, raw, manifest = self.fixture("v3.1.2", "stable", False)
        source = u.GitHubSource("windows-x64")
        with patch.object(source, "read", side_effect=[json.dumps(stable).encode(), raw]) as read:
            self.assertEqual(source.latest(), manifest)
        self.assertEqual(read.call_args_list[0].args[0], u.API)
        preview, _, _ = self.fixture("v3.90.1-preview.1")
        with patch.object(source, "read", return_value=json.dumps(preview).encode()), self.assertRaises(u.UpdateError):
            source.latest()
        preview["prerelease"] = False
        with patch.object(source, "read", return_value=json.dumps(preview).encode()), self.assertRaises(u.UpdateError):
            source.latest()

    def test_no_compatible_preview_is_not_a_stable_or_installer_fallback(self):
        source = u.GitHubSource("macos-arm64", "experimental")
        preview, _, _ = self.fixture("v3.90.1-preview.1")  # Windows asset only
        with patch.object(source, "read", return_value=json.dumps([preview]).encode()):
            self.assertIsNone(source.latest())

    def test_exact_tag_and_trusted_asset_digest_still_required(self):
        release, raw, manifest = self.fixture("v3.90.1-preview.1")
        wrong = copy.deepcopy(manifest)
        wrong["release_tag"] = "v3.90.2-preview.2"
        bad_raw = json.dumps(wrong).encode()
        release["assets"][0].update(size=len(bad_raw), digest="sha256:"+u.sha(bad_raw))
        source = u.GitHubSource("windows-x64", "experimental")
        with patch.object(source, "read", side_effect=[json.dumps([release]).encode(), bad_raw]), self.assertRaises(u.UpdateError):
            source.latest()

    def test_new_stable_feed_tag_is_exact_while_legacy_metadata_remains_supported(self):
        release, raw, manifest = self.fixture("v3.1.2", "stable", False)
        source = u.GitHubSource("windows-x64")
        # Same numeric version under a different exact tag is not interchangeable.
        release["tag_name"] = "3.1.2"
        for asset in release["assets"]:
            asset["browser_download_url"] = asset["browser_download_url"].replace("/v3.1.2/", "/3.1.2/")
        with patch.object(source, "read", side_effect=[json.dumps(release).encode(), raw]), self.assertRaises(u.UpdateError):
            source.latest()


if __name__ == "__main__":
    unittest.main()
