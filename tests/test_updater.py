"""Protocol tests with isolated installs, real compressed packs and bounded reads."""
import copy
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import updater as u
from tests.fixture_paths import fixture_root

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
from update_payload import create_payload


class LocalSource:
    def __init__(self, packs, fail_at=None, corrupt=False):
        self.packs = packs
        self.calls = 0
        self.bytes = 0
        self.fail_at = fail_at
        self.corrupt = corrupt

    def chunk(self, b, total):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("Simulated connection interrupted")
        with open(self.packs / b["pack"], "rb") as f:
            f.seek(b["offset"])
            data = f.read(b["size"])
        self.bytes += len(data)
        return data[:-3] + b"bad" if self.corrupt else data


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = fixture_root(self.temp.name)
        self.base = self.root / "install"
        self.next = self.root / "candidate"
        self.packs = self.root / "packs"
        self.base.mkdir()
        (self.base / "AnatomyExplorer.exe").write_bytes(b"old executable")
        (self.base / "_internal/data/anatomy").mkdir(parents=True)
        (self.base / "_internal/app").mkdir()
        (self.base / "_internal/VERSION").write_text("3.1.0")
        (self.base / "_internal/app/ui.py").write_text("print('old')")
        self.large = os.urandom(u.CHUNK_SIZE * 2 + 500)
        (self.base / "_internal/data/anatomy/model.bin").write_bytes(self.large)
        self.old_manifest = create_payload(self.base, self.root / "oldpacks", "3.1.0")
        shutil.copytree(self.base, self.next)
        (self.next / "_internal/VERSION").write_text("3.1.1")
        (self.next / "_internal/app/ui.py").write_text("print('new')")
        self.manifest = create_payload(self.next, self.packs, "3.1.1")
        self.store = u.UpdateStore(self.base, self.root / "updates")
        self.user = self.root / "user/notes.json"
        self.user.parent.mkdir()
        self.user.write_text('{"personal":"keep me"}')

    def tearDown(self):
        self.temp.cleanup()

    def test_first_install_no_update_and_downgrade(self):
        self.store.verify(self.base)
        self.assertEqual(self.store.active(), self.base)
        src = LocalSource(self.packs)
        self.assertEqual(self.store.prepare(self.old_manifest, src)["status"], "current")
        older = copy.deepcopy(self.old_manifest)
        older["version"] = "2.0.0"
        older["release_tag"] = "v2.0.0"
        self.assertEqual(self.store.prepare(older, src)["status"], "current")
        self.assertEqual(src.bytes, 0)

    def test_incremental_activation_rollback_data_preserved(self):
        src = LocalSource(self.packs)
        result = self.store.prepare(self.manifest, src)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.store.active(), self.base, "running version must not switch")
        self.assertLess(result["downloaded"], 200, "code-only update must not download the atlas")
        activated = self.store.activate()
        self.store.verify(activated)
        self.assertTrue(self.store.state()["trial"])
        self.store.healthy()
        self.assertFalse(self.store.state()["trial"])
        self.store.request_rollback()
        self.assertTrue(self.store.state()["rollback_requested"])
        self.store.rollback()
        self.assertEqual(self.store.active(), self.base)
        self.assertEqual(self.user.read_text(), '{"personal":"keep me"}')
        self.assertEqual((self.base / "_internal/VERSION").read_text(), "3.1.0")

    def test_partial_large_asset_only_changed_block(self):
        p = self.next / "_internal/data/anatomy/model.bin"
        content = bytearray(self.large)
        content[u.CHUNK_SIZE + 100] ^= 1
        p.write_bytes(content)
        manifest = create_payload(self.next, self.packs, "3.1.1")
        source = LocalSource(self.packs)
        result = self.store.prepare(manifest, source)
        self.assertLess(result["downloaded"], u.CHUNK_SIZE + 10000)
        self.assertGreater(result["reused"], u.CHUNK_SIZE)
        self.store.verify(self.store.activate())

    def test_interrupted_resume_and_corrupt_download(self):
        source = LocalSource(self.packs, fail_at=2)
        with self.assertRaises(OSError):
            self.store.prepare(self.manifest, source)
        self.assertFalse(self.store.state().get("pending"))
        self.assertEqual(self.store.active(), self.base)
        resumed = LocalSource(self.packs)
        self.store.prepare(self.manifest, resumed)
        self.assertEqual(resumed.calls, 1, "completed verified chunk/file should resume")
        self.store.verify(self.store.activate())
        broken = u.UpdateStore(self.base, self.root / "broken-updates")
        with self.assertRaises(u.UpdateError):
            broken.prepare(self.manifest, LocalSource(self.packs, corrupt=True))
        self.assertFalse(broken.state().get("pending"))

    def test_low_disk_permission_error(self):
        with patch.object(u.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            with self.assertRaisesRegex(u.UpdateError, "disk space"):
                self.store.prepare(self.manifest, LocalSource(self.packs))
        self.assertFalse(self.store.state().get("pending"))
        with patch.object(u.os, "replace", side_effect=PermissionError("permission denied")):
            with self.assertRaises(PermissionError):
                self.store.prepare(self.manifest, LocalSource(self.packs))
        self.assertEqual(self.store.active(), self.base)
        self.assertEqual(self.user.read_text(), '{"personal":"keep me"}')

    def test_corrupt_staged_version_refused(self):
        self.store.prepare(self.manifest, LocalSource(self.packs))
        pending = self.store.path(self.store.state()["pending"])
        (pending / "_internal/app/ui.py").write_text("corrupt")
        with self.assertRaises(u.UpdateError):
            self.store.activate()
        self.assertEqual(self.store.active(), self.base)

    def test_lock_crash_recovery_and_malformed_state(self):
        with u.lock(self.root / "one.lock"):
            with self.assertRaises(u.UpdateError):
                with u.lock(self.root / "one.lock"):
                    self.fail("lock must serialize concurrent operations")
        with u.lock(self.root / "one.lock"):
            pass
        self.store.root.mkdir(exist_ok=True)
        self.store.state_file.write_text('{"current":"../escape"}')
        self.assertEqual(self.store.active(), self.base)
        self.store.state_file.write_text("broken JSON")
        self.assertEqual(self.store.active(), self.base)

    def test_manifest_traversal_duplicates_protocol_and_size(self):
        for path in ("../../user/notes.json", "_internal/data/user/token.json", "_internal/CON", "_internal/test.", "_internal/X:y", "_internal\\oops", "/AnatomyExplorer.exe"):
            bad = copy.deepcopy(self.manifest)
            bad["files"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(u.UpdateError):
                u.validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        bad["files"].append(dict(bad["files"][0], path=bad["files"][0]["path"].upper()))
        with self.assertRaises(u.UpdateError):
            u.validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        bad["launcher"] = 2
        with self.assertRaises(u.UpdateError):
            u.validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        next(iter(bad["blobs"].values()))["offset"] = -1
        with self.assertRaises(u.UpdateError):
            u.validate_manifest(bad)

    def test_bounded_decompression_and_url_trust(self):
        bomb = gzip.compress(b"x" * (u.CHUNK_SIZE * 2), mtime=0)
        with self.assertRaises(u.UpdateError):
            u.unpack_chunk(bomb, 10, u.sha(b"x" * 10))
        for url in ("http://github.com/release", "https://evil.com/", "https://github.com.evil.com/", "https://u:p@github.com/", "https://github.com:444/"):
            with self.subTest(url=url), self.assertRaises(u.UpdateError):
                u.trusted_url(url)
        self.assertEqual(u.trusted_url(u.API), u.API)

    def test_github_manifest_digest_and_repository_binding(self):
        raw = json.dumps(self.manifest).encode()
        prefix = f"https://github.com/{u.REPO}/releases/download/v3.1.1/"
        assets = [{"name": u.MANIFEST, "size": len(raw), "digest": "sha256:" + u.sha(raw), "browser_download_url": prefix + u.MANIFEST}]
        assets.extend({"name": n, "size": s, "browser_download_url": prefix + n} for n, s in self.manifest["packs"].items())
        release = {"tag_name": "v3.1.1", "assets": assets, "draft": False, "prerelease": False}
        source = u.GitHubSource("windows-x64")
        with patch.object(source, "read", side_effect=[json.dumps(release).encode(), raw]):
            self.assertEqual(source.latest(), self.manifest)
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with patch.object(source, "read", side_effect=[json.dumps(release).encode(), raw]), self.assertRaisesRegex(u.UpdateError, "integrity"):
            source.latest()
        release["assets"][0]["browser_download_url"] = "https://github.com/someone/else/releases/download/v3.1.1/" + u.MANIFEST
        with patch.object(source, "read", return_value=json.dumps(release).encode()), self.assertRaises(u.UpdateError):
            source.latest()

    def test_range_server_full_response_rejected(self):
        source = u.GitHubSource()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.url = "https://release-assets.githubusercontent.com/file"
        response.status = 200
        response.headers = {"Content-Range": "bytes 0-9/100"}
        with patch.object(source.opener, "open", return_value=response), self.assertRaisesRegex(u.UpdateError, "incremental"):
            source.read("https://github.com/file", 10, expected_range="bytes 0-9/100")
        response.read.assert_not_called()

    def test_launcher_waits_for_child_on_bookkeeping_permission_failure(self):
        child = unittest.mock.Mock(returncode=0)
        child.poll.side_effect = [None, 0]

        def spawn(command, env):
            Path(env["AE_READY_FILE"]).write_text("ready")
            return child

        with patch.object(u, "store_for", return_value=self.store), patch.object(u.subprocess, "Popen", side_effect=spawn) as popen, patch.object(self.store, "healthy", side_effect=PermissionError("state denied")), patch.object(u.time, "sleep"):
            self.assertEqual(u.launch_managed([]), 0)
        self.assertEqual(popen.call_count, 1, "must never launch a second process over live study")
        self.assertEqual(child.poll.call_count, 2, "first child must finish")

    def test_trial_startup_failure_and_power_loss_roll_back(self):
        self.store.prepare(self.manifest, LocalSource(self.packs))
        selected = self.store.activate()
        self.assertTrue(self.store.state()["trial"])
        # Previous trial never made a ready marker (e.g. power loss). Next launch
        # must go to base before starting a new child.
        child = unittest.mock.Mock(returncode=0)
        child.poll.return_value = 0
        with patch.object(u, "store_for", return_value=self.store), patch.object(u.subprocess, "Popen", return_value=child) as popen:
            u.launch_managed([])
        self.assertEqual(Path(popen.call_args.args[0][0]).parent, self.base)
        self.assertNotEqual(selected, self.base)
        # A new child exits before ready, then the launcher starts the retained base.
        self.store.prepare(self.manifest, LocalSource(self.packs))
        failed = unittest.mock.Mock(returncode=1)
        failed.poll.return_value = 1
        with patch.object(u, "store_for", return_value=self.store), patch.object(u.subprocess, "Popen", side_effect=[failed, child]) as popen:
            u.launch_managed([])
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(self.store.active(), self.base)

    def test_reinstalled_newer_base_replaces_older_update(self):
        self.store.prepare(self.manifest, LocalSource(self.packs))
        updated = self.store.activate()
        self.store.healthy()
        self.assertNotEqual(updated, self.base)
        child = unittest.mock.Mock(returncode=0)
        child.poll.return_value = 0

        def spawn(command, env):
            Path(env["AE_READY_FILE"]).write_text("ready")
            return child

        # An older original keeps running its update.
        with patch.object(u, "store_for", return_value=self.store), patch.object(u.subprocess, "Popen", side_effect=spawn) as popen:
            u.launch_managed([])
        self.assertEqual(Path(popen.call_args.args[0][0]).parent, updated)
        # The user installs a newer release over the original: it runs, not the older update.
        (self.base / "_internal/VERSION").write_text("3.1.2")
        create_payload(self.base, self.root / "reinstallpacks", "3.1.2")
        with patch.object(u, "store_for", return_value=self.store), patch.object(u.subprocess, "Popen", side_effect=spawn) as popen:
            u.launch_managed([])
        self.assertEqual(Path(popen.call_args.args[0][0]).parent, self.base)
        self.assertIsNone(self.store.state().get("current"))

    def test_cleanup_does_not_delete_unpublished_prepared_version(self):
        self.store.versions.mkdir(parents=True)
        version = self.store.versions / "3.2.0-aaaaaaaaaaaaaaaa"
        version.mkdir()
        with u.lock(self.store.root / "prepare.lock"):
            self.store.cleanup()
            self.assertTrue(version.exists(), "complete but unpublished directory is still preparing")
        self.store.cleanup()
        self.assertFalse(version.exists())

    @unittest.skipIf(os.name == "nt", "unprivileged POSIX symlink path test; Mac CI exercises it")
    def test_staging_and_cache_symlink_escape_refused(self):
        self.store.root.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.store.root / "chunks").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(u.UpdateError, "storage"):
            self.store.prepare(self.manifest, LocalSource(self.packs))
        self.assertEqual(list(outside.iterdir()), [])


@unittest.skipIf(os.name == "nt", "a Mac bundle layout with POSIX permissions")
class ReplaceOriginalMacAppTests(unittest.TestCase):
    """An update that ran healthily can be copied over the original app, so Finder shows its version and icon."""

    @staticmethod
    def bundle(path, version, icon, data):
        (path / "Contents/MacOS").mkdir(parents=True)
        (path / "Contents/Resources/data").mkdir(parents=True)
        launcher = path / "Contents/MacOS/AnatomyExplorer"
        if sys.platform == "darwin":
            shutil.copyfile("/bin/echo", launcher)       # codesign needs a real executable
        else:
            launcher.write_bytes(b"launcher")
        os.chmod(launcher, 0o755)
        (path / "Contents/Info.plist").write_text('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleExecutable</key><string>AnatomyExplorer</string><key>CFBundleIdentifier</key><string>io.github.ethanprince4.updatertest</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>')
        (path / "Contents/Resources/VERSION").write_text(version)
        (path / "Contents/Resources/icon.icns").write_bytes(icon)
        (path / "Contents/Resources/data/atlas.bin").write_bytes(data)
        if sys.platform == "darwin":                     # verify() checks the signature on macOS
            subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(path)], check=True, capture_output=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = fixture_root(self.temp.name)
        self.base = root / "Applications/Anatomy Explorer.app"
        data = os.urandom(300_000)
        self.bundle(self.base, "3.1.0", b"old icon", data)
        candidate = root / "next/Anatomy Explorer.app"
        self.bundle(candidate, "3.1.1", b"new icon", data)
        manifest = create_payload(candidate, root / "packs", "3.1.1", "macos-arm64")
        self.store = u.UpdateStore(self.base, root / "updates")
        self.store.prepare(manifest, LocalSource(root / "packs"))
        self.updated = self.store.activate()

    def tearDown(self):
        self.temp.cleanup()

    def test_replaces_the_original_with_the_running_update(self):
        self.assertIsNone(self.store.replaceable_base(), "a trial launch is not offered yet")
        self.store.healthy()
        self.assertEqual(self.store.replaceable_base(), "3.1.1")
        self.assertEqual(self.store.replace_base(), "3.1.1")
        self.assertEqual((self.base / "Contents/Resources/VERSION").read_text(), "3.1.1")
        self.assertEqual((self.base / "Contents/Resources/icon.icns").read_bytes(), b"new icon")
        self.assertTrue(os.access(self.base / "Contents/MacOS/AnatomyExplorer", os.X_OK))
        self.assertIsNone(self.store.state().get("current"))
        self.assertEqual(self.store.active(), self.base)
        self.assertEqual([p.name for p in self.base.parent.iterdir()], ["Anatomy Explorer.app"])
        self.assertIsNone(self.store.replaceable_base())
        # The original is set aside (its launcher may still run) and goes at the next healthy launch's cleanup.
        self.assertTrue(any((self.store.root / "retired").iterdir()))
        self.store.cleanup()
        self.assertFalse((self.store.root / "retired").exists())
        self.assertFalse(self.updated.exists())

    def test_a_damaged_update_leaves_the_original_untouched(self):
        self.store.healthy()
        (self.updated / "Contents/Resources/data/atlas.bin").write_bytes(b"damaged")
        with self.assertRaisesRegex(u.UpdateError, "integrity"):
            self.store.replace_base()
        self.assertEqual((self.base / "Contents/Resources/VERSION").read_text(), "3.1.0")
        self.assertEqual([p.name for p in self.base.parent.iterdir()], ["Anatomy Explorer.app"])
        self.assertEqual(self.store.active(), self.updated)

    def test_not_offered_for_another_channel_or_an_unwritable_folder(self):
        self.store.healthy()
        with patch.object(u.os, "access", return_value=False):
            self.assertIsNone(self.store.replaceable_base())
        windows = u.UpdateStore(self.base.parent, self.store.root)
        self.assertIsNone(windows.replaceable_base())


@unittest.skipUnless(sys.platform == "darwin", "real macOS signature/symlink check runs on macOS CI")
class MacBundleTests(unittest.TestCase):
    def test_signed_bundle_incremental_reconstruction(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            base = root / "original/Anatomy Explorer.app"
            (base / "Contents/MacOS").mkdir(parents=True)
            (base / "Contents/Resources/data").mkdir(parents=True)
            (base / "Contents/Frameworks").mkdir()
            shutil.copyfile("/bin/echo", base / "Contents/MacOS/AnatomyExplorer")
            os.chmod(base / "Contents/MacOS/AnatomyExplorer", 0o755)
            (base / "Contents/Info.plist").write_text('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleExecutable</key><string>AnatomyExplorer</string><key>CFBundleIdentifier</key><string>io.github.ethanprince4.updatertest</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>')
            (base / "Contents/Resources/VERSION").write_text("3.1.0")
            (base / "Contents/Resources/data/atlas.bin").write_bytes(os.urandom(1024 * 1024))
            (base / "Contents/Frameworks/data").symlink_to("../Resources/data")
            subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(base)], check=True, capture_output=True)
            candidate = root / "next/Anatomy Explorer.app"
            shutil.copytree(base, candidate, symlinks=True)
            (candidate / "Contents/Resources/VERSION").write_text("3.1.1")
            subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(candidate)], check=True, capture_output=True)
            manifest = create_payload(candidate, root / "packs", "3.1.1", "macos-arm64")
            store = u.UpdateStore(base, root / "updates")
            result = store.prepare(manifest, LocalSource(root / "packs"))
            self.assertLess(result["downloaded"], 1024 * 1024)
            active = store.activate()
            self.assertTrue((active / "Contents/Frameworks/data").is_symlink())
            self.assertTrue(os.access(active / "Contents/MacOS/AnatomyExplorer", os.X_OK))
            store.verify(active)  # actual codesign --verify --deep --strict
            store.rollback()
            self.assertEqual(store.active(), base)


if __name__ == "__main__":
    unittest.main()
