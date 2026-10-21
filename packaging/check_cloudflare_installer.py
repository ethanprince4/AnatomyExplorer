"""Apply the actual Windows helper to an isolated seed copy, never invoking Inno.

This verifies the production overlay/complete-inventory engine and native frozen
runtime. It deliberately does not install/register/uninstall an application.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from build_update_bridge import clone_bundle
from app.updater import file_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This check exercises the compiled native Windows helper")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    baseline = args.base.resolve()
    protected = [baseline / "_internal/app/updater.py", baseline / "_internal/VERSION"]
    before = {str(p): file_sha(p) for p in protected}
    started = time.monotonic()
    stage = work / "app"
    clone_bundle(baseline, stage)
    sentinel = work / "external-user-notes.txt"
    sentinel.write_bytes(b"outside application; preserve notes, preferences and model overrides\n")
    subprocess.run([str(args.helper.resolve()), "--check-staged", str(stage), "--overlay", str(args.overlay.resolve())],
                   check=True, timeout=300)
    report = work / "runtime.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LOCALAPPDATA=str(work / "profile"),
               AE_TEST_SETTINGS_DIR=str(work / "settings"))
    subprocess.run([str(stage / "LayeredHuman.exe"), "--runtime-check", "--report", str(report)],
                   env=env, check=True, timeout=90)
    runtime = json.loads(report.read_text(encoding="utf-8"))
    if not runtime["frozen"] or not runtime["runtime_imports"] or runtime["version"] != "4.0.12":
        raise RuntimeError("Frozen bootstrap runtime differs")
    if before != {str(p): file_sha(p) for p in protected}:
        raise RuntimeError("Read-only original seed was changed")
    if sentinel.read_bytes() != b"outside application; preserve notes, preferences and model overrides\n":
        raise RuntimeError("External user data was changed")
    result = {"schema": 1, "passed": True, "platform": "windows-x64", "helper_sha256": file_sha(args.helper),
              "overlay_sha256": file_sha(args.overlay), "runtime": runtime,
              "inno_executed": False, "registration_changed": False, "user_data_preserved": True,
              "original_seed_preserved": True, "seconds": round(time.monotonic() - started, 3)}
    (work / "helper-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
