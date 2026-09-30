"""Exercise incremental assembly of the real signed release .app on macOS CI.

Derive a disposable older-version baseline, re-sign only that test copy, then
update using the actual candidate feed. Never change the distribution bundle.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import MAC_MANIFEST, UpdateStore


class Packs:
    def __init__(self, root):
        self.root = root

    def chunk(self, b, total):
        with open(self.root / b["pack"], "rb") as f:
            f.seek(b["offset"])
            return f.read(b["size"])


def main():
    if sys.platform != "darwin":
        raise SystemExit("macOS required")
    original, feed = map(lambda s: Path(s).resolve(), sys.argv[1:3])
    manifest = json.loads((feed / MAC_MANIFEST).read_text())
    with tempfile.TemporaryDirectory(prefix="AnatomyExplorer-mac-update-") as d:
        root = Path(d).resolve()
        base = root / "base/Anatomy Explorer.app"

        def copy_file(src, dst):
            rel = Path(src).relative_to(original).as_posix()
            if rel.startswith(("Contents/Resources/data/", "Contents/Resources/models/")):
                try:
                    os.link(src, dst)
                    return dst
                except OSError:
                    pass
            return shutil.copy2(src, dst)

        shutil.copytree(original, base, symlinks=True, copy_function=copy_file)
        target = tuple(map(int, manifest["version"].split(".")))
        assert target > (0, 0, 0)
        # A test-only numeric older version; no historical release is rewritten.
        (base / "Contents/Resources/VERSION").write_text("0.0.0")
        metadata = base / "Contents/Resources/UPDATE_CHANNEL.json"
        metadata.write_text(json.dumps({"channel": "stable", "release_tag": "v0.0.0"}))
        subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(base)], check=True)
        store = UpdateStore(base, root / "updates")
        if manifest.get("channel") == "experimental":
            store.set_channel("experimental")
        result = store.prepare(manifest, Packs(feed))
        assert store.active() == base
        active = store.activate()
        store.verify(active)  # all hashes, symlink containment, actual codesign verification
        assert store.prepare(manifest, Packs(feed))["status"] == "current"
        store.healthy()
        store.rollback()
        assert store.active() == base
        # Assert the real release bundle is still sealed after all test operations.
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(original)], check=True)
        result.update(bundle_bytes=sum(f["size"] for f in manifest["files"]), feed_bytes=sum(manifest["packs"].values()),
                      signed_original_preserved=True, signed_staged_bundle=True, rollback=True)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
