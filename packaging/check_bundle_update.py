"""Local real-package delta/launch check without installer registration or study data.

Usage: python packaging/check_bundle_update.py BASE_FOLDER NEW_FOLDER PACK_FOLDER
Windows GPU/Qt session required. Both folders must be isolated *test* builds.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import UpdateStore, application_executable, read_manifest, sha


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


class NativeProcessStillRunning(RuntimeError):
    """Retain the disposable profile if its owned process could not be stopped."""


def dll_preflight(bundle):
    """Load native plugins without Qt initialization, GUI, or Python SDK Qt."""
    import contextlib
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    kernel.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
    results = []
    with contextlib.ExitStack() as stack:
        for name in ("_internal", "_internal/PySide6", "_internal/shiboken6"):
            directory = Path(bundle) / name
            if directory.is_dir():
                stack.enter_context(os.add_dll_directory(str(directory)))
        for name in ("qwindows.dll", "qoffscreen.dll"):
            path = Path(bundle) / "_internal/PySide6/plugins/platforms" / name
            handle = kernel.LoadLibraryExW(str(path), None, 0x100 | 0x1000)
            results.append({"plugin": name, "path_length": len(str(path)), "loaded": bool(handle),
                            "winerror": 0 if handle else ctypes.get_last_error()})
            if handle:
                kernel.FreeLibrary(handle)
    print(json.dumps(results, indent=2))
    if not all(row["loaded"] for row in results):
        raise SystemExit("Native DLL preflight failed; no GUI launch was attempted")


def validate_profile_paths(profile, base, version):
    # LoadLibraryExW can reject a 258-character plugin path with error 206,
    # even though Python can read the same DLL and all its hashes are correct.
    # Keep the test profile outside a potentially deep checkout/build tree.
    key = sha(str(base).casefold().encode())[:16]
    plugin = Path(profile) / "AnatomyExplorer/updates" / key / "versions" / (version + "-" + "f" * 16)
    plugin = plugin / "_internal/PySide6/plugins/platforms/qoffscreen.dll"
    if len(str(plugin)) >= 240:
        raise ValueError("Disposable update profile is too deep for native Windows Qt DLL loading")
    return len(str(plugin))


def check_update(base, candidate, packs, test_root, output_root):
    profile = test_root / "profile"
    settings_dir = test_root / "qt-settings"
    manifest = read_manifest(candidate)
    plugin_path_length = validate_profile_paths(profile, base, manifest["version"])
    output_root.mkdir(parents=True, exist_ok=True)
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
        label = "old-base" if folder == base else "candidate"
        with (output_root / f"{label}-launch.log").open("w", encoding="utf-8") as output:
            process = subprocess.Popen([str(application_executable(folder)), "--script", "wait:2000;quit:"],
                                       env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                # This PID was created here. Terminate its entire supervisor/child
                # tree before any temporary-profile cleanup can occur.
                try:
                    stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                             capture_output=True, timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    raise NativeProcessStillRunning(f"Could not confirm owned process tree {process.pid} stopped") from None
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise NativeProcessStillRunning(f"Owned process {process.pid} did not close; profile retained") from None
                if stopped.returncode:
                    raise NativeProcessStillRunning(f"Owned process tree {process.pid} could not be stopped")
                raise RuntimeError(f"Frozen {label} timed out; its owned process tree was stopped") from None
        if code:
            raise RuntimeError(f"Frozen {label} returned {code}; see {label}-launch.log")
        settings.sync()
        assert settings.value("test/preserved") == "keep-me", "Qt settings lost"
        assert all((user / name).read_bytes() == content for name, content in fixtures.items()), "study files changed"

    key = sha(str(base).casefold().encode())[:16]
    store = UpdateStore(base, profile / "AnatomyExplorer/updates" / key)
    source = Packs(packs)
    result = store.prepare(manifest, source)
    assert store.active() == base, "prepared update changed live version"
    staged = store.path(store.state()["pending"])
    # The separate standard-library-only process has no imported SDK Qt DLLs.
    # Probe both exact native paths before either app UI is opened.
    for label, folder in (("candidate", candidate), ("staged", staged)):
        probe = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dll-preflight", str(folder)],
                               env=env, capture_output=True, text=True, timeout=30)
        (output_root / f"{label}-dll-preflight.log").write_text(probe.stdout + probe.stderr, encoding="utf-8")
        if probe.returncode:
            raise RuntimeError(f"Native {label} DLL preflight failed; no GUI launch was attempted")
    # First launch of the new frozen build. Its launcher supports isolated INI.
    launch(candidate)
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
                  no_update=True, rollback=True, user_data_and_qt_settings_preserved=True,
                  staged_qt_plugin_path_length=plugin_path_length)
    output = output_root / "real-package-result.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(output)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dll-preflight":
        dll_preflight(Path(sys.argv[2]).resolve())
        return
    base, candidate, packs = map(lambda p: Path(p).resolve(), sys.argv[1:4])
    # Do not nest LOCALAPPDATA under the frozen bundle's checkout path. Apart
    # from MAX_PATH, a short independent directory models an ordinary install's
    # user-profile update store more accurately.
    test_root = Path(tempfile.mkdtemp(prefix="LH-update-")).resolve()
    closed = True
    try:
        check_update(base, candidate, packs, test_root, base.parent / "update-validation")
    except NativeProcessStillRunning:
        closed = False
        print(f"Retained disposable profile until owned processes close: {test_root}", file=sys.stderr)
        raise
    finally:
        if closed:
            if test_root.parent != Path(tempfile.gettempdir()).resolve() or not test_root.name.startswith("LH-update-"):
                raise ValueError("Unexpected disposable profile cleanup path")
            shutil.rmtree(test_root)


if __name__ == "__main__":
    main()
