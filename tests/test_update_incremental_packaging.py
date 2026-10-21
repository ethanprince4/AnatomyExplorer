"""Incremental release construction must preserve immutable prior pack ranges."""
import copy
import gzip
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import update_payload as packaging
from reconstruct_bundle import reconstruct_bundle
from app import updater as u
from tests.fixture_paths import fixture_root
from tests.test_updater import LocalSource
from tests.test_updater_channels import legacy


class IncrementalPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = fixture_root(self.temporary.name)
        self.base, self.target = self.root / "base", self.root / "target"
        self.old_feed, self.feed = self.root / "old-feed", self.root / "feed"
        (self.base / "_internal/app").mkdir(parents=True)
        (self.base / "AnatomyExplorer.exe").write_bytes(b"unchanged native launcher")
        (self.base / "LayeredHuman.exe").write_bytes(b"unchanged native launcher")
        (self.base / "_internal/VERSION").write_text("4.0.11")
        (self.base / "_internal/app/updater.py").write_bytes(b"old updater source")
        (self.base / "_internal/model.bin").write_bytes(os.urandom(4096))
        (self.base / "_internal/removed.bin").write_bytes(b"removed " * 500)
        self.previous = packaging.create_payload(self.base, self.old_feed, "4.0.11")
        # Reserve the real baseline's maximum index without generating 63 packs.
        original = next(iter(self.previous["packs"]))
        renamed = "AnatomyExplorer-Windows-pack-0062.bin"
        (self.old_feed / original).rename(self.old_feed / renamed)
        self.previous["packs"][renamed] = self.previous["packs"].pop(original)
        for blob in self.previous["blobs"].values():
            blob["pack"] = renamed
        shutil.copytree(self.base, self.target)
        (self.target / "_internal/VERSION").write_text("4.0.12")
        (self.target / "_internal/app/updater.py").write_bytes(b"new updater source")
        (self.target / "_internal/removed.bin").unlink()
        self.old_bytes = (self.old_feed / renamed).read_bytes()

    def package(self, **kwargs):
        return packaging.create_payload(self.target, self.feed, "4.0.12",
                                        previous_manifest=self.previous,
                                        previous_packs=self.old_feed, **kwargs)

    def test_only_new_chunks_are_compressed_and_old_offsets_and_lengths_survive(self):
        compress = gzip.compress
        with patch.object(packaging.gzip, "compress", wraps=compress) as spy:
            result = self.package()
        expected = {b"4.0.12", b"new updater source"}
        self.assertEqual({call.args[0] for call in spy.call_args_list}, expected)
        old_name = "AnatomyExplorer-Windows-pack-0062.bin"
        new_name = "AnatomyExplorer-Windows-pack-0063.bin"
        self.assertEqual(set(result["packs"]), {old_name, new_name})
        self.assertEqual(result["packs"][old_name], len(self.old_bytes))
        self.assertEqual((self.feed / old_name).read_bytes(), self.old_bytes)
        for digest in result["blobs"].keys() & self.previous["blobs"].keys():
            self.assertEqual(result["blobs"][digest], self.previous["blobs"][digest])
        self.assertNotIn("_internal/removed.bin", {entry["path"] for entry in result["files"]})
        self.assertNotIn(u.sha(b"removed " * 500), result["blobs"])
        with open(self.feed / new_name, "rb") as source:
            raw = source.read()
        self.assertEqual(len(raw), sum(blob["size"] for digest, blob in result["blobs"].items()
                                      if digest not in self.previous["blobs"]))
        self.assertLess(len(raw), len(self.old_bytes))

    def test_complete_target_reconstructs_and_both_manifest_aliases_remain_compatible(self):
        result = self.package()
        public = json.loads((self.feed / u.PUBLIC_MANIFEST).read_text())
        compatibility = json.loads((self.feed / u.MANIFEST).read_text())
        self.assertEqual(public, result)
        legacy.validate_manifest(compatibility)
        self.assertIn("LayeredHuman.exe", {entry["path"] for entry in public["files"]})
        self.assertNotIn("LayeredHuman.exe", {entry["path"] for entry in compatibility["files"]})
        rebuilt = self.root / "rebuilt"
        self.assertEqual(reconstruct_bundle(public, self.feed, rebuilt), result)
        self.assertEqual(u.UpdateStore(rebuilt, self.root / "updates").verify(rebuilt), result)
        for entry in result["files"]:
            self.assertEqual((rebuilt / entry["path"]).read_bytes(),
                             (self.target / entry["path"]).read_bytes())
        # The historical immutable bootstrap also stages the incremental feed.
        old = legacy.UpdateStore(self.base, self.root / "legacy-updates")
        old.prepare(compatibility, LocalSource(self.feed))
        old.verify(old.activate())

    def test_reference_only_output_contains_new_packs_and_never_old_pack_copies(self):
        result = packaging.create_payload(self.target, self.feed, "4.0.12",
                                          previous_manifest=self.previous)
        self.assertEqual({path.name for path in self.feed.glob("*.bin")},
                         {"AnatomyExplorer-Windows-pack-0063.bin"})
        self.assertIn("AnatomyExplorer-Windows-pack-0062.bin", result["packs"])

    def test_unchanged_bundle_reuses_every_chunk_without_creating_a_new_pack(self):
        with patch.object(packaging.gzip, "compress") as compress:
            result = packaging.create_payload(self.base, self.feed, "4.0.11",
                                              previous_manifest=self.previous,
                                              previous_packs=self.old_feed)
        compress.assert_not_called()
        self.assertEqual(result["blobs"], self.previous["blobs"])
        self.assertEqual(result["packs"], self.previous["packs"])

    def test_old_pack_copy_fallback_is_exclusive_and_preserves_source_bytes(self):
        with patch.object(packaging.os, "link", side_effect=OSError("Different volume")):
            result = self.package()
        name = next(iter(self.previous["packs"]))
        self.assertEqual((self.feed / name).read_bytes(), self.old_bytes)
        self.assertEqual((self.old_feed / name).read_bytes(), self.old_bytes)
        self.assertFalse((self.feed / name).samefile(self.old_feed / name))
        self.assertIn(name, result["packs"])

    def test_conflicting_existing_old_pack_is_never_replaced(self):
        self.feed.mkdir()
        name = next(iter(self.previous["packs"]))
        (self.feed / name).write_bytes(b"different existing immutable pack")
        with self.assertRaises(FileExistsError):
            self.package()
        self.assertEqual((self.feed / name).read_bytes(), b"different existing immutable pack")

    def test_truncated_or_corrupted_reused_pack_is_rejected(self):
        name = next(iter(self.previous["packs"]))
        path = self.old_feed / name
        path.write_bytes(self.old_bytes[:-1])
        with self.assertRaisesRegex(u.UpdateError, "pack size"):
            self.package()
        path.write_bytes(bytes(byte ^ 0xFF for byte in self.old_bytes))
        with self.assertRaisesRegex(u.UpdateError, "compressed|integrity"):
            self.package()

    def test_trusted_pack_catalog_checks_full_sha_and_requires_reused_pack_entry(self):
        name = next(iter(self.previous["packs"]))
        with self.assertRaisesRegex(u.UpdateError, "SHA-256 differs"):
            self.package(previous_pack_hashes={name: "0" * 64})
        with self.assertRaisesRegex(u.UpdateError, "missing from catalog"):
            self.package(previous_pack_hashes={})
        result = self.package(previous_pack_hashes={name: "sha256:" + u.sha(self.old_bytes)})
        self.assertIn(name, result["packs"])

    def test_existing_new_pack_is_never_overwritten(self):
        self.feed.mkdir()
        path = self.feed / "AnatomyExplorer-Windows-pack-0063.bin"
        path.write_bytes(b"existing immutable release pack")
        with self.assertRaises(FileExistsError):
            self.package()
        self.assertEqual(path.read_bytes(), b"existing immutable release pack")

    def test_pruned_unreferenced_pack_still_reserves_its_index(self):
        unused = "AnatomyExplorer-Windows-pack-0090.bin"
        self.previous["packs"][unused] = 1
        result = self.package()
        self.assertNotIn(unused, result["packs"])
        self.assertFalse((self.feed / unused).exists())
        self.assertIn("AnatomyExplorer-Windows-pack-0091.bin", result["packs"])

    def test_rejects_incomplete_or_wrong_platform_previous_inventory(self):
        incomplete = copy.deepcopy(self.previous)
        incomplete["files"] = [entry for entry in incomplete["files"] if entry["path"] != "_internal/VERSION"]
        with self.assertRaisesRegex(u.UpdateError, "Incomplete"):
            packaging.create_payload(self.target, self.feed, "4.0.12", previous_manifest=incomplete)
        with self.assertRaisesRegex(ValueError, "platform differs"):
            packaging.create_payload(self.target, self.feed, "4.0.12", "macos-arm64",
                                     previous_manifest=self.previous)

    def test_reconstruction_checks_final_file_hash_and_refuses_existing_destination(self):
        result = self.package()
        rebuilt = self.root / "rebuilt"
        rebuilt.mkdir()
        with self.assertRaises(FileExistsError):
            reconstruct_bundle(result, self.feed, rebuilt)
        corrupt = copy.deepcopy(result)
        corrupt["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(u.UpdateError, "file failed integrity"):
            reconstruct_bundle(corrupt, self.feed, self.root / "bad-rebuild")

    def test_reconstruction_rejects_remote_path_escape_before_creating_tree(self):
        result = self.package()
        result["files"][0]["path"] = "../escape.exe"
        output = self.root / "bad-path"
        with self.assertRaises(u.UpdateError):
            reconstruct_bundle(result, self.feed, output)
        self.assertFalse(output.exists())


class MacReconstructionTests(unittest.TestCase):
    def test_preserves_mode_and_safe_symlink_without_changing_sealed_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(temporary)
            bundle = root / "Original.app"
            resources = bundle / "Contents/Resources"
            resources.mkdir(parents=True)
            executable = bundle / "Contents/MacOS/AnatomyExplorer"
            executable.parent.mkdir()
            executable.write_bytes(b"native executable")
            executable.chmod(0o755)
            (resources / "VERSION").write_text("4.0.11")
            try:
                (resources / "linked-version").symlink_to("VERSION")
            except OSError:
                self.skipTest("Host does not permit fixture symlinks")
            manifest = packaging.create_payload(bundle, root / "feed", "4.0.11", "macos-arm64")
            target = root / "Rebuilt.app"
            reconstruct_bundle(manifest, root / "feed", target)
            self.assertEqual(os.readlink(target / "Contents/Resources/linked-version"), "VERSION")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE((target / "Contents/MacOS/AnatomyExplorer").stat().st_mode), 0o755)
            self.assertFalse((target / u.PUBLIC_MAC_MANIFEST).exists())
            self.assertEqual(json.loads((root / u.PUBLIC_MAC_MANIFEST).read_text()), manifest)

    def test_reconstruction_never_replaces_another_mac_bundles_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = fixture_root(temporary)
            bundle = root / "Original.app"
            (bundle / "Contents/MacOS").mkdir(parents=True)
            (bundle / "Contents/Resources").mkdir()
            (bundle / "Contents/MacOS/AnatomyExplorer").write_bytes(b"native executable")
            (bundle / "Contents/Resources/VERSION").write_text("4.0.11")
            manifest = packaging.create_payload(bundle, root / "feed", "4.0.11", "macos-arm64")
            sidecar = root / u.PUBLIC_MAC_MANIFEST
            sidecar.write_text('{"another":"app"}')
            with self.assertRaises(FileExistsError):
                reconstruct_bundle(manifest, root / "feed", root / "Rebuilt.app")
            self.assertEqual(sidecar.read_text(), '{"another":"app"}')
            self.assertFalse((root / "Rebuilt.app").exists())


if __name__ == "__main__":
    unittest.main()
