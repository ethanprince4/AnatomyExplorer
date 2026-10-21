"""Verify pinned fresh-install overlays and the actual Windows apply engine."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import cloudflare_installers as c
from update_payload import create_payload


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lh-fi-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base, self.candidate = self.root / "base", self.root / "candidate"
        for folder, version in ((self.base, "4.0.11"), (self.candidate, "4.0.12")):
            (folder / "_internal/app").mkdir(parents=True)
            for name in ("LayeredHuman.exe", "AnatomyExplorer.exe"):
                (folder / name).write_bytes(b"unchanged frozen launcher")
            (folder / "_internal/VERSION").write_text(version)
            (folder / "_internal/UPDATE_CHANNEL.json").write_text(json.dumps({"channel": "stable", "release_tag": "v" + version}))
            (folder / "_internal/app/updater.py").write_text("VERSION = '" + version + "'\n")
            (folder / "_internal/approved.model").write_bytes(b"unchanged approved model")
            create_payload(folder, self.root / ("old-feed" if version == "4.0.11" else "feed"), version)
        self.previous = self.root / "old-feed/LayeredHuman-Windows-update.json"
        self.manifest = self.root / "feed/LayeredHuman-Windows-update.json"
        self.out = self.root / "helpers"

    def prepare(self):
        return c.prepare("windows-x64", self.base, self.candidate, self.previous, self.manifest, self.out)

    def test_overlay_contains_all_changes_and_both_distinct_manifest_aliases(self):
        inputs, record = self.prepare()
        with zipfile.ZipFile(self.out / record["overlay"]["name"]) as archive:
            self.assertEqual(set(archive.namelist()), {
                "payload/_internal/VERSION", "payload/_internal/UPDATE_CHANNEL.json", "payload/_internal/app/updater.py",
                "metadata/LayeredHuman-Windows-update.json", "metadata/AnatomyExplorer-Windows-update.json"})
            public = json.loads(archive.read("metadata/LayeredHuman-Windows-update.json"))
            legacy = json.loads(archive.read("metadata/AnatomyExplorer-Windows-update.json"))
            self.assertEqual(len(public["files"]), len(legacy["files"]) + 1)
        text = (inputs / "inventory.tsv").read_text()
        self.assertIn("LayeredHuman-Windows-update.json\t", text)
        self.assertIn("AnatomyExplorer-Windows-update.json\t", text)
        self.assertNotIn("github", (inputs / "Release.cs").read_text().lower())
        self.assertEqual(record["prefix"], "releases/v4.0.12/installers/cf-only-1")

    def test_modified_seed_and_final_bytes_are_rejected(self):
        target = self.base / "_internal/approved.model"
        target.write_bytes(b"damaged model")
        with self.assertRaisesRegex(ValueError, "Frozen file differs"):
            self.prepare()
        target.write_bytes(b"unchanged approved model")
        (self.candidate / "_internal/app/updater.py").write_bytes(b"unreviewed source")
        with self.assertRaisesRegex(ValueError, "Frozen file differs"):
            self.prepare()

    def test_overlay_bytes_are_reproducible(self):
        _, record = self.prepare()
        first = (self.out / record["overlay"]["name"]).read_bytes()
        _, repeated = self.prepare()
        self.assertEqual(first, (self.out / repeated["overlay"]["name"]).read_bytes())
        self.assertEqual(record["overlay"], repeated["overlay"])

    def test_added_or_obsolete_paths_cannot_enter_source_only_seed_overlay(self):
        (self.candidate / "_internal/unexpected.py").write_bytes(b"changed path inventory")
        create_payload(self.candidate, self.root / "changed-feed", "4.0.12")
        self.manifest = self.root / "changed-feed/LayeredHuman-Windows-update.json"
        with self.assertRaisesRegex(ValueError, "path inventories differ"):
            self.prepare()

    def test_unsafe_inventory_names_are_rejected(self):
        for name in ("../outside", "absolute//file", "file\nname", "C:/escape", "/absolute", "dir/../file", "dir/file."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                c.safe_name(name)

    def test_mac_overlay_preserves_every_signing_change_and_checks_native_signature(self):
        old, new = self.root / "Old.app", self.root / "New.app"
        for folder, version, signature in ((old, "4.0.11", b"old signature"), (new, "4.0.12", b"new signature")):
            for path, content in (("Contents/MacOS/AnatomyExplorer", b"frozen native launcher"),
                                  ("Contents/Resources/VERSION", version.encode()),
                                  ("Contents/Resources/UPDATE_CHANNEL.json", json.dumps({"channel": "stable", "release_tag": "v" + version}).encode()),
                                  ("Contents/_CodeSignature/CodeResources", signature),
                                  ("Contents/Frameworks/native.dylib", b"native sections; " + signature)):
                target = folder / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            create_payload(folder, self.root / ("mac-old" if version == "4.0.11" else "mac-new"), version, "macos-arm64")
        inputs, record = c.prepare("macos-arm64", old, new,
                                   self.root / "mac-old/LayeredHuman-macOS-update.json",
                                   self.root / "mac-new/LayeredHuman-macOS-update.json", self.root / "mac-helpers")
        delta = (inputs / "delta.txt").read_text()
        self.assertIn("Contents/_CodeSignature/CodeResources\n", delta)
        self.assertIn("Contents/Frameworks/native.dylib\n", delta)
        shell = (inputs / "install.sh").read_text()
        self.assertIn('codesign --verify --deep --strict "$root"', shell)
        self.assertNotIn("github.com", shell)
        self.assertNotIn("@OVERLAY", shell)
        self.assertTrue(record["overlay"]["size"] > 0)

    def test_inventory_parent_regex_runs_with_available_awk(self):
        awk = Path(shutil.which("awk") or "C:/Program Files/Git/usr/bin/awk.exe")
        if not awk.is_file():
            self.skipTest("No awk available for the portable-regex regression")
        template = (c.HERE / "install.sh.in").read_text(encoding="utf-8")
        line = next(line for line in template.splitlines() if "while (sub(" in line)
        expression = line.split("awk '", 1)[1].split("' |", 1)[0]
        result = subprocess.run([str(awk), expression],
                                input="Contents/Resources/app/updater.py\nContents/MacOS/AnatomyExplorer\nRoot with spaces/file name\nbare-file\n",
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["Contents/Resources/app", "Contents/Resources", "Contents",
                                                    "Contents/MacOS", "Contents", "Root with spaces"])

    @unittest.skipUnless(sys.platform == "win32" and c.CSC.exists(), "native .NET compiler")
    def test_native_windows_success_failure_and_no_user_data_mutation(self):
        inputs, record = self.prepare()
        helper = c.build_windows(self.out, inputs)
        overlay = self.out / record["overlay"]["name"]
        outside = self.root / "user-notes.txt"
        outside.write_bytes(b"keep external notes and user models")

        def run(folder, archive=overlay):
            return subprocess.run([str(helper), "--check-staged", str(folder), "--overlay", str(archive)],
                                  capture_output=True, timeout=40).returncode

        stage = self.root / "success"
        shutil.copytree(self.base, stage)
        self.assertEqual(run(stage), 0)
        for path in self.candidate.rglob("*"):
            if path.is_file() and path.suffix != ".json":
                self.assertEqual((stage / path.relative_to(self.candidate)).read_bytes(), path.read_bytes())
        self.assertEqual(json.loads((stage / "LayeredHuman-Windows-update.json").read_text())["version"], "4.0.12")
        self.assertFalse((stage / "LayeredHuman.exe.installing").exists())

        # Corrupt immutable overlay: no file is applied, and production seed
        # launchers would already have been held by InstallSeed before this call.
        damaged = self.root / "bad.zip"
        damaged.write_bytes(overlay.read_bytes()[:-1] + b"!")
        self.assertNotEqual(run(stage, damaged), 0)
        self.assertEqual((stage / "_internal/VERSION").read_text(), "4.0.12")

        for label, extra in (("stale-file", "stale.py"), ("unexpected-directory", "extra/child.py")):
            target = self.root / label
            shutil.copytree(self.base, target)
            path = target / extra
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"must not enter the application")
            self.assertNotEqual(run(target), 0)
            self.assertFalse((target / "LayeredHuman.exe").exists())
            self.assertTrue((target / "LayeredHuman.exe.installing").exists())
            self.assertTrue((target / "AnatomyExplorer.exe.installing").exists())
            self.assertEqual((target / "_internal/VERSION").read_text(), "4.0.11")

        corrupt = self.root / "corrupt-base"
        shutil.copytree(self.base, corrupt)
        (corrupt / "_internal/approved.model").write_bytes(b"corrupt")
        self.assertNotEqual(run(corrupt), 0)
        self.assertFalse((corrupt / "LayeredHuman.exe").exists())

        # An OS denial during replacement happens after earlier payload files
        # were applied. The partial new copy must keep both launchers disabled;
        # a later retry must not accept the mixed inventory as a healthy app.
        interrupted = self.root / "interrupted-apply"
        shutil.copytree(self.base, interrupted)
        with open(interrupted / "_internal/app/updater.py", "rb"):
            self.assertNotEqual(run(interrupted), 0)
        self.assertTrue((interrupted / "LayeredHuman.exe.installing").exists())
        self.assertTrue((interrupted / "AnatomyExplorer.exe.installing").exists())
        self.assertFalse((interrupted / "LayeredHuman.exe").exists())
        self.assertNotEqual(run(interrupted), 0)
        self.assertEqual(outside.read_bytes(), b"keep external notes and user models")


if __name__ == "__main__":
    unittest.main()
