"""Require signed frozen Cocoa section identity and native selected-tree semantics."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.macho_sections import section_identity


def main():
    executable = Path(sys.argv[1]).resolve()
    contents = executable.parent.parent
    if contents.name != "Contents" or sys.platform != "darwin":
        raise RuntimeError("Expected a macOS app executable")
    plugins = {p.resolve() for p in contents.rglob("libqcocoa.dylib")}
    if len(plugins) != 1:
        raise RuntimeError("Expected exactly one final Cocoa plugin")
    plugin = plugins.pop()
    provenance = json.loads((Path(__file__).parent / "qt-cocoa/PROVENANCE.json").read_text())
    # Link-command rewrites and signing may change file bytes, never code/data sections.
    sections = section_identity(plugin)
    if sections != provenance["file_backed_sections"] or set(sections) != {"arm64"}:
        raise RuntimeError("Final Cocoa plugin sections differ from the accepted repair")
    final_hash = hashlib.sha256(plugin.read_bytes()).hexdigest()
    output = Path("packaging/build/frozen-cocoa")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="AnatomyExplorer-frozen-Cocoa-") as temporary:
        env = dict(os.environ, QT_QPA_PLATFORM="cocoa", AE_TEST_SETTINGS_DIR=temporary,
                   QT_OWNERSHIP_PLUGIN_SHA256=final_hash, QT_OWNERSHIP_WHEEL_ROOT=str(contents))
        # The frozen bootloader sets its own library search paths. Do not import SDK Qt.
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            env.pop(key, None)
        subprocess.run([sys.executable, "packaging/diagnostics/mac_ax/run_matrix.py",
                        "--executable", str(executable), "--output", str(output / "matrix")],
                       env=env, timeout=360, check=True)
        subprocess.run([str(executable), "--pick-diagnostics", "--gpu-controls-only", "--report",
                        str((output / "gpu.json").resolve())], env=env, timeout=90, check=True)
    summary = json.loads((output / "matrix/summary.json").read_text())
    identities = []
    for path in (output / "matrix").glob("*.jsonl"):
        identities.extend(row for row in (json.loads(line) for line in path.read_text().splitlines())
                          if row.get("event") == "ownership_runtime")
    gpu = json.loads((output / "gpu.json").read_text())
    valid = (len(summary["cases"]) == len(identities) == 5 and summary["passed"] and gpu["passed"]
             and all(row.get("frozen") and row.get("candidate_plugin_loaded")
                     and row.get("all_qt_frameworks_from_wheel") for row in identities))
    report = {"passed": bool(valid), "frozen_cocoa": True, "final_plugin_sha256": final_hash,
              "accepted_plugin_sha256": provenance["candidate_plugin_sha256"],
              "file_backed_sections_identical": True, "architecture": "arm64",
              "native_getters_completed": sum(row["native_getter_completed"] for row in summary["cases"]),
              "physical_mac_validated": False, "upstream_status": "NEW; unreleased"}
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    if not valid:
        raise RuntimeError("Frozen Cocoa runtime/semantic validation failed")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
