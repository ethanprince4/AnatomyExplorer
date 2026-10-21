"""Exercise incremental assembly of the real signed release .app on macOS CI.

Use --base for the actual reconstructed historical release and its immutable
launcher. Without --base retain the ordinary release workflow's synthetic older
copy. Never change either supplied distribution bundle.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import MAC_MANIFEST, UpdateStore, application_executable, sha
from release_storage import require_space


class Packs:
    def __init__(self, root):
        self.root = root

    def chunk(self, b, total):
        with open(self.root / b["pack"], "rb") as f:
            f.seek(b["offset"])
            return f.read(b["size"])


def main(argv=None):
    if sys.platform != "darwin":
        raise SystemExit("macOS required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("feed", type=Path)
    parser.add_argument("--base", type=Path, help="Actual historical signed baseline; exercise its frozen launcher")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    original, feed = args.original.resolve(), args.feed.resolve()
    manifest = json.loads((feed / MAC_MANIFEST).read_text())
    require_space(feed, sum(entry['size'] for entry in manifest['files']) * 2 + 256 * 1024**2,
                  'Native signed update check (unchanged production reserve)')
    with tempfile.TemporaryDirectory(prefix="LayeredHuman-mac-update-") as d:
        root = Path(d).resolve()
        base = args.base.resolve() if args.base else root / "base/Layered Human.app"

        def copy_file(src, dst):
            rel = Path(src).relative_to(original).as_posix()
            if rel.startswith(("Contents/Resources/data/", "Contents/Resources/models/")):
                try:
                    os.link(src, dst)
                    return dst
                except OSError:
                    pass
            return shutil.copy2(src, dst)

        if not args.base:
            shutil.copytree(original, base, symlinks=True, copy_function=copy_file)
            target = tuple(map(int, manifest["version"].split(".")))
            assert target > (0, 0, 0)
            # A test-only numeric older version; no historical release is rewritten.
            (base / "Contents/Resources/VERSION").write_text("0.0.0")
            metadata = base / "Contents/Resources/UPDATE_CHANNEL.json"
            metadata.write_text(json.dumps({"channel": "stable", "release_tag": "v0.0.0"}))
            subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(base)], check=True)
        else:
            historical = (base / "Contents/Resources/VERSION").read_text().strip()
            assert tuple(map(int, historical.split("."))) < tuple(map(int, manifest["version"].split(".")))
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(base)], check=True)
        home = root / "profile-home"
        local = home / "Library/Application Support/AnatomyExplorer"
        settings_dir = root / "qt-settings"
        settings_file = settings_dir / "AnatomyExplorer/Anatomy Explorer.ini"
        settings_file.parent.mkdir(parents=True)
        settings_file.write_text("[test]\npreserved=keep-me\n", encoding="utf-8")
        user = local / "user"
        user.mkdir(parents=True)
        fixtures = {"notes.json": b'{"1":"Keep this Mac test note"}', "quiz_stats.json": b'{}'}
        for name, data in fixtures.items():
            (user / name).write_bytes(data)
        env = dict(os.environ, HOME=str(home), AE_TEST_SETTINGS_DIR=str(settings_dir))

        def launch(bundle):
            subprocess.run([str(application_executable(bundle, mac=True)), "--script", "wait:2000;quit:"],
                           env=env, check=True, timeout=120)
            assert all((user / name).read_bytes() == data for name, data in fixtures.items()), "Study data changed"
            assert "preserved=keep-me" in settings_file.read_text(), "Qt settings lost"

        key = sha(str(base).casefold().encode())[:16]
        store = UpdateStore(base, local / "updates" / key if args.base else root / "updates")
        if manifest.get("channel") == "experimental":
            store.set_channel("experimental")
        result = store.prepare(manifest, Packs(feed))
        assert store.active() == base
        if args.base:
            # This is the historical frozen supervisor, not a source imitation.
            # It activates the signed staged child and waits for healthy UI.
            launch(original)
            launch(base)
            active = store.active()
            assert active != base and store.state().get("trial") is False, "New frozen UI never confirmed healthy"
        else:
            active = store.activate()
        store.verify(active)  # all hashes, symlink containment, actual codesign verification
        assert store.prepare(manifest, Packs(feed))["status"] == "current"
        if not args.base:
            store.healthy()
        store.rollback()
        assert store.active() == base
        if args.base:
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(base)], check=True)
        # Assert the real release bundle is still sealed after all test operations.
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(original)], check=True)
        result.update(bundle_bytes=sum(f["size"] for f in manifest["files"]), feed_bytes=sum(manifest["packs"].values()),
                      signed_original_preserved=True, signed_staged_bundle=True, rollback=True,
                      real_historical_baseline=bool(args.base), old_frozen_launcher=bool(args.base),
                      healthy_ui=bool(args.base), no_update=True,
                      user_data_and_qt_settings_preserved=bool(args.base))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
