"""Install only the provenance-pinned arm64 Cocoa repair into a matching wheel."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys

ROOT = Path(__file__).resolve().parent / "qt-cocoa"
EXPECTED = "d836df28d891cec26ad5899c9bade9d8b292bea298b13760c5019ce25f6e3590"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("Cocoa repair is only validated for Apple silicon macOS")
    import PySide6
    if PySide6.__version__ != "6.11.2":
        raise RuntimeError("Cocoa repair requires the exact matching 6.11.2 wheel")
    wheel = Path(PySide6.__file__).resolve().parent / "Qt"
    acceptance = json.loads((ROOT / "acceptance.json").read_text())
    plugin = ROOT / "libqcocoa.dylib"
    if digest(plugin) != EXPECTED or acceptance["candidate_plugin_sha256"] != EXPECTED:
        raise RuntimeError("Untrusted Cocoa repair binary")
    if not all(acceptance.get(key) is True for key in
               ("passed", "matrix_passed", "isolated_runtime_verified", "framework_hashes_unchanged")):
        raise RuntimeError("Cocoa repair lacks accepted isolated evidence")
    before = {p.name: digest(p / "Versions/A" / p.stem) for p in (wheel / "lib").glob("Qt*.framework")}
    if before != acceptance["framework_hashes_before"]:
        raise RuntimeError("Qt wheel frameworks differ from the accepted runtime")
    target = wheel / "plugins/platforms/libqcocoa.dylib"
    if digest(target) not in (acceptance["original_wheel_plugin_sha256"], EXPECTED):
        raise RuntimeError("Unexpected original Cocoa plugin")
    shutil.copy2(plugin, target)
    after = {p.name: digest(p / "Versions/A" / p.stem) for p in (wheel / "lib").glob("Qt*.framework")}
    if digest(target) != EXPECTED or before != after:
        raise RuntimeError("Cocoa replacement changed runtime frameworks")
    print(json.dumps({"plugin_sha256": EXPECTED, "frameworks_unchanged": True,
                      "architectures": "arm64", "upstream_status": "NEW; unreleased"}))


if __name__ == "__main__":
    install()
