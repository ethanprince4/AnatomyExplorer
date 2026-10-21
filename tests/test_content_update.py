"""Complete content snapshots preserve runtime/native bytes and explicit scope."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import build_content_update as content
from app import updater as u
from update_payload import create_payload


class ContentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.base = self.root / "base" / "LayeredHuman"
        self.source = self.root / "source"
        self.output = self.root / "output"

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def fixture(self, mac=False, large=False):
        if mac:
            self.base = self.root / "base" / "Layered Human.app"
        self.prefix = "Contents/Resources/" if mac else "_internal/"
        for relative, data in {
            self.prefix + "VERSION": b"4.0.12",
            self.prefix + "UPDATE_CHANNEL.json": b'{"channel":"stable","release_tag":"v4.0.12"}',
            self.prefix + "app/updater.py": b"# preserved runtime source\n",
            self.prefix + "data/content/lesson.json": b'{"lesson":"old"}',
            self.prefix + "data/local_model_library/old.npz": b"A" * u.CHUNK_SIZE + b"old tail" if large else b"old model bytes",
            self.prefix + "data/local_model_library/keep.npz": b"approved unchanged model",
        }.items():
            self.write(self.base / relative, data)
        if mac:
            for name in ("LayeredHuman", "AnatomyExplorer"):
                self.write(self.base / "Contents/MacOS" / name, b"\xcf\xfa\xed\xfefrozen-native-main")
            self.write(self.base / "Contents/Frameworks/preserved.dylib", b"\xcf\xfa\xed\xfeunchanged-native-library")
            self.write(self.base / "Contents/_CodeSignature/CodeResources", b"previous outer seal")
            self.write(self.base / "Contents/Info.plist", plistlib.dumps({"CFBundleExecutable": "LayeredHuman",
                "CFBundleVersion": "4.0.12", "CFBundleShortVersionString": "4.0.12"}))
        else:
            for name in ("LayeredHuman.exe", "AnatomyExplorer.exe"):
                self.write(self.base / name, b"MZfrozen-native-main")
        self.old_feed = self.root / "old-feed"
        self.previous = create_payload(self.base, self.old_feed, "4.0.12", "macos-arm64" if mac else "windows-x64")
        self.manifest_path = self.old_feed / u.manifest_names(self.previous["platform"])[0]
        self.catalog_path = self.root / "catalog.json"
        self.catalog = {name: {"sha256": u.file_sha(self.old_feed / name), "size": size}
                        for name, size in self.previous["packs"].items()}
        self.catalog_path.write_text(json.dumps(self.catalog))
        self.map_path = self.root / "patch-map.json"
        self.mapping = {"schema": 1, "files": [], "remove": []}
        self.add_patch("data/content/lesson.json", b'{"lesson":"refined tongue"}')
        self.add_patch("data/local_model_library/new.npz", b"new refined model bytes")
        self.mapping["remove"] = ["data/local_model_library/old.npz"]
        self.save_map()

    def add_patch(self, name, data, target=None):
        self.write(self.source / name, data)
        self.mapping["files"].append({"source": name, "target": target or name,
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})

    def save_map(self):
        self.map_path.write_text(json.dumps(self.mapping))

    def build(self, **kwargs):
        return content.build_content_update(self.base, self.manifest_path, u.file_sha(self.manifest_path),
            self.catalog_path, u.file_sha(self.catalog_path), self.map_path, self.source, self.output, **kwargs)

    def test_complete_inventory_explicit_removal_omits_live_bytecode_and_preserves_base(self):
        self.fixture()
        self.write(self.base / "_internal/app/__pycache__/updater.cpython-311.pyc", b"unlisted live bytecode")
        before = {entry["path"]: u.file_sha(self.base / entry["path"]) for entry in self.previous["files"]}
        manifest, report = self.build()
        candidate = self.output / "candidate/LayeredHuman"
        names = {entry["path"] for entry in manifest["files"]}
        expected = (set(before) - {"_internal/data/local_model_library/old.npz"}) | {"_internal/data/local_model_library/new.npz"}
        self.assertEqual(names, expected)
        self.assertFalse(any("__pycache__" in str(path) for path in candidate.rglob("*")))
        self.assertEqual((candidate / "_internal/app/updater.py").read_bytes(), b"# preserved runtime source\n")
        self.assertEqual({name: u.file_sha(self.base / name) for name in before}, before)
        self.assertEqual((candidate / "LayeredHuman.exe").read_bytes(), (self.base / "LayeredHuman.exe").read_bytes())
        self.assertEqual((candidate / "_internal/VERSION").read_bytes(), b"4.0.13")
        self.assertEqual(report["removed_files"], ["_internal/data/local_model_library/old.npz"])
        self.assertIn("_internal/app/__pycache__/updater.cpython-311.pyc", report["ignored_unlisted_bytecode_or_sidecars"])

    def test_changed_hardlinked_model_reuses_chunks_without_modifying_baseline(self):
        self.fixture(large=True)
        old = self.base / "_internal/data/local_model_library/old.npz"
        original_hash = u.file_sha(old)
        self.mapping = {"schema": 1, "files": [], "remove": []}
        self.add_patch("data/local_model_library/old.npz", b"A" * u.CHUNK_SIZE + b"refined tail")
        self.save_map()
        manifest, report = self.build()
        old_entry = next(entry for entry in self.previous["files"] if entry["path"].endswith("/old.npz"))
        new_entry = next(entry for entry in manifest["files"] if entry["path"].endswith("/old.npz"))
        self.assertEqual(old_entry["chunks"][0], new_entry["chunks"][0])
        self.assertEqual(self.previous["blobs"][old_entry["chunks"][0]], manifest["blobs"][new_entry["chunks"][0]])
        self.assertEqual(u.file_sha(old), original_hash)
        self.assertNotEqual(old.stat().st_ino, (self.output / "candidate/LayeredHuman/_internal/data/local_model_library/old.npz").stat().st_ino)
        self.assertGreater(report["reused_pack_bytes"], 0)
        self.assertGreater(report["new_pack_bytes"], 0)
        self.assertFalse(any((self.output / "feed" / name).exists() for name in self.previous["packs"]))
        known = json.loads((self.output / "known-packs.json").read_text())
        self.assertTrue(all(known[name] == self.catalog[name] for name in self.previous["packs"] if name in manifest["packs"]))

    def test_optional_local_old_packs_produce_complete_byte_feed(self):
        self.fixture()
        manifest, _ = self.build(previous_packs=self.old_feed)
        self.assertTrue(all((self.output / "feed" / name).stat().st_size == size for name, size in manifest["packs"].items()))

    def test_input_authentication_rejects_wrong_manifest_or_catalog_identity(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
            content.authenticate_inputs(self.manifest_path, "0" * 64, self.catalog_path, u.file_sha(self.catalog_path))
        with self.assertRaisesRegex(ValueError, "catalog SHA-256"):
            content.authenticate_inputs(self.manifest_path, u.file_sha(self.manifest_path), self.catalog_path, "0" * 64)
        first = next(iter(self.catalog))
        self.catalog[first]["size"] += 1
        self.catalog_path.write_text(json.dumps(self.catalog))
        with self.assertRaisesRegex(ValueError, "matching trusted"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_tampered_baseline_or_unlisted_nonbytecode_is_rejected(self):
        self.fixture()
        path = self.base / "_internal/app/updater.py"
        before = path.read_bytes()
        path.write_bytes(b"tampered runtime")
        with self.assertRaisesRegex(ValueError, "Prior bundle file differs"):
            self.build()
        path.write_bytes(before)
        self.write(self.base / "_internal/unlisted-model.glb", b"unexpected unmanaged bundle content")
        with self.assertRaisesRegex(ValueError, "Unlisted source bundle file"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_native_runtime_and_undeclared_removal_paths_are_rejected(self):
        self.fixture()
        for name in ("app/updater.py", "data/runtime.dll", "data/unsafe.framework/image.png", "../data/model.npz"):
            with self.subTest(name=name), self.assertRaises((ValueError, u.UpdateError)):
                content.resource_path(name, "windows-x64")
        for header in (b"MZ", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
            with self.subTest(header=header.hex()):
                self.mapping = {"schema": 1, "files": [], "remove": []}
                self.add_patch("data/native.json", header + b"native masquerading as content")
                self.save_map()
                with self.assertRaisesRegex(ValueError, "native executable header"):
                    self.build()
        self.mapping = {"schema": 1, "files": [], "remove": ["data/local_model_library/absent.npz"]}
        self.save_map()
        with self.assertRaisesRegex(ValueError, "existing managed content"):
            self.build()

    def test_existing_output_and_nonnewer_version_are_rejected(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "numerically newer"):
            self.build(version="4.0.12")
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.build()

    def test_mac_signing_signs_only_outer_app_and_keeps_strict_deep_verification(self):
        with patch.object(content.sys, "platform", "darwin"), patch.object(content.subprocess, "run") as run:
            content.sign_outer_app(Path("old.app"), Path("new.app"))
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", "old.app"],
            ["/usr/bin/codesign", "--force", "--sign", "-", "new.app"],
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", "new.app"]])
        with patch.object(content.sys, "platform", "darwin"), patch.object(content.subprocess, "run",
                side_effect=[subprocess.CompletedProcess([], 0), subprocess.CalledProcessError(1, [])]) as run:
            with self.assertRaisesRegex(RuntimeError, "no deep re-sign fallback"):
                content.sign_outer_app(Path("old.app"), Path("new.app"))
        self.assertEqual(run.call_count, 2)

    def test_mac_builder_rejects_any_nested_library_signing_mutation(self):
        self.fixture(mac=True)
        real_verify = content.verify_baseline

        def verify_on_host(bundle, manifest):
            # Windows cannot express Unix 0644/0755 mode bits. Authenticate all
            # bytes and retain actual host modes while mocking only that check.
            return real_verify(bundle, {**manifest, "platform": "windows-x64"})

        def corrupt_nested(base, candidate):
            (candidate / "Contents/Frameworks/preserved.dylib").write_bytes(b"\xcf\xfa\xed\xfere-signed nested library")

        with patch.object(content, "verify_baseline", side_effect=verify_on_host), \
             patch.object(content, "sign_outer_app", side_effect=corrupt_nested):
            with self.assertRaisesRegex(ValueError, "preserved nested native file"):
                self.build()
        self.assertEqual((self.base / "Contents/Frameworks/preserved.dylib").read_bytes(), b"\xcf\xfa\xed\xfeunchanged-native-library")


if __name__ == "__main__":
    unittest.main()
