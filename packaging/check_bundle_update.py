"""Local real-package delta/launch check without installer registration or study data.

Usage: python packaging/check_bundle_update.py BASE_FOLDER NEW_FOLDER PACK_FOLDER
Windows GPU/Qt session required. Both folders must be isolated *test* builds.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import UpdateStore, read_manifest, sha


class Packs:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.bytes = 0

    def chunk(self, blob, total):
        with open(self.directory / blob["pack"], "rb") as f:
            f.seek(blob["offset"])
            data = f.read(blob["size"])
        self.bytes += len(data)
        return data


def main():
    base, candidate, packs = map(lambda p: Path(p).resolve(), sys.argv[1:4])
    test_root = base.parent / "update-validation"
    profile = test_root / "profile"
    settings_dir = test_root / "qt-settings"
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LOCALAPPDATA=str(profile), AE_TEST_SETTINGS_DIR=str(settings_dir))
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_dir))
    settings = QSettings("AnatomyExplorer", "Anatomy Explorer")
    settings.setValue("test/preserved", "keep-me")
    settings.sync()
    user = profile / "AnatomyExplorer/user"
    user.mkdir(parents=True, exist_ok=True)
    fixtures = {"notes.json": b'{"1":"Keep this test note"}', "quiz_stats.json": b'{}'}
    for name, content in fixtures.items():
        (user / name).write_bytes(content)

    def launch(folder):
        subprocess.run([str(folder / "AnatomyExplorer.exe"), "--script", "wait:2000;quit:"], env=env, check=True, timeout=90)
        settings.sync()
        assert settings.value("test/preserved") == "keep-me", "Qt settings lost"
        assert all((user / name).read_bytes() == content for name, content in fixtures.items()), "study files changed"

    # First launch of the new frozen build. Its launcher supports isolated INI.
    launch(candidate)
    key = sha(str(base).casefold().encode())[:16]
    store = UpdateStore(base, profile / "AnatomyExplorer/updates" / key)
    source = Packs(packs)
    manifest = read_manifest(candidate)
    result = store.prepare(manifest, source)
    assert store.active() == base, "prepared update changed live version"
    # The old stable launcher starts the verified new child; only that child's
    # launcher/UI uses Qt, with the isolated preferences set above.
    launch(base)
    assert store.active() != base and store.state().get("trial") is False, "new UI never confirmed healthy"
    store.verify(store.active())
    no_update = store.prepare(manifest, source)
    assert no_update["status"] == "current"
    store.rollback()
    assert store.active() == base
    store.verify(base)
    total = sum(f["size"] for f in manifest["files"])
    result.update(bundle_bytes=total, feed_bytes=sum(manifest["packs"].values()),
                  percent_of_full_feed=100 * result["downloaded"] / sum(manifest["packs"].values()),
                  first_launch=True, next_launch_activation=True, healthy_ui=True,
                  no_update=True, rollback=True, user_data_and_qt_settings_preserved=True)
    output = test_root / "real-package-result.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(output)


if __name__ == "__main__":
    main()
