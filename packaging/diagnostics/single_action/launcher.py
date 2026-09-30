"""Isolated one-action Mac picking/TLS diagnostic. Never starts the study app."""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "packaging/diagnostics/mac_ax"))
sys.dont_write_bytecode = True
for stream in ("stdout", "stderr"):
    if getattr(sys, stream) is None:
        setattr(sys, stream, open(os.devnull, "w"))


def installed_identity():
    """Read only fixed app metadata; never enumerate personal files or launch it."""
    app = Path("/Applications/Anatomy Explorer.app")
    plist = app / "Contents/Info.plist"
    if not plist.is_file():
        return {"found_in_applications": False}
    values = plistlib.loads(plist.read_bytes())
    result = {"found_in_applications": True,
              "version": values.get("CFBundleShortVersionString"),
              "build": values.get("CFBundleVersion"),
              "bundle_identifier": values.get("CFBundleIdentifier"),
              "study_app_launched": False}
    # Exact shipped renderer provenance, without reading notes/settings/caches.
    digests = {}
    for name in ("app/renderer.py", "app/shaders.py", "app/updater.py", "data/anatomy/anatomy.json"):
        path = app / "Contents/Resources" / name
        if path.is_file():
            digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["bundled_source_sha256"] = digests
    return result


def tls_probe():
    from app.https_check import check, failure_category
    from app.updater import API, SafeRedirect
    defaults = ssl.get_default_verify_paths()
    context = ssl.create_default_context()
    result = {"openssl": ssl.OPENSSL_VERSION,
              "default_trust": {"ca_file_present": bool(defaults.cafile),
                                "ca_directory_present": bool(defaults.capath),
                                "trusted_ca_count": context.cert_store_stats()["x509_ca"],
                                "certificate_required": context.verify_mode == ssl.CERT_REQUIRED,
                                "hostname_verified": context.check_hostname,
                                "original_installed_client_executed": False,
                                "interpretation": "Default trust of this isolated frozen interpreter; not the installed client's interpreter."}}
    try:
        opener = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPSHandler(context=context))
        with opener.open(urllib.request.Request(API, headers={"User-Agent": "AnatomyExplorer-Diagnostic"}), timeout=20) as response:
            result["default_trust"]["github_api_https_success"] = response.status == 200
            response.read(64)
    except Exception as exc:
        result["default_trust"].update(github_api_https_success=False, failure=failure_category(exc))
    try:
        result["packaged_roots"] = check("macos-arm64" if sys.platform == "darwin" else "windows-x64")
    except Exception as exc:
        result["packaged_roots"] = {"success": False, "failure": failure_category(exc)}
    result["success"] = result["packaged_roots"]["success"]
    return result


def task(name):
    if name == "gpu":
        from app.picking_diagnostics import run_gpu_controls, json_safe
        metadata = Path("/Applications/Anatomy Explorer.app/Contents/Resources/data/anatomy/anatomy.json")
        result = json_safe(run_gpu_controls(metadata if sys.platform == "darwin" and metadata.is_file() else None))
        if sys.platform == "darwin":
            from runtime_binary import loaded_qcocoa_identity
            result["loaded_cocoa_plugin"] = loaded_qcocoa_identity()
        # Tracebacks can expose local package paths; controls/errors stay useful.
        if "error" in result:
            result["error"] = "gpu_context_or_control_failed"
        if "error" in result.get("controls", {}):
            result["controls"]["error"] = "gpu_control_failed"
        if "error" in result.get("production_controls", {}):
            result["production_controls"]["error"] = "production_gpu_control_failed"
        return result
    return tls_probe()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("gpu", "tls"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-dialog", action="store_true")
    args = parser.parse_args(argv)
    if args.task:
        try:
            result = task(args.task)
        except Exception:
            result = {"success": False, "failure": "diagnostic_task_failed"}
        args.report.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        return 0 if result.get("success", result.get("passed", False)) else 1
    directory = Path(tempfile.mkdtemp(prefix="AnatomyExplorer-Diagnostic-"))
    output = args.report or directory / "report.json"
    result = {"schema": 1, "purpose": "Unpublished diagnostic; not an app update",
              "runtime": {"os": platform.platform(), "machine": platform.machine(),
                          "python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False))},
              "installed_app": installed_identity(), "physical_pointer_tested": False,
              "native_tree_crash_repro_attempted": False, "automatic_upload": False}
    provenance = Path(getattr(sys, "_MEIPASS", ROOT / "packaging/build/diagnostic-meta")) / "DIAGNOSTIC.json"
    if provenance.is_file():
        result["diagnostic_build"] = json.loads(provenance.read_text(encoding="utf-8"))
    # Separate children preserve completed evidence even if the GPU driver faults.
    for name in ("tls", "gpu"):
        child_report = directory / (name + ".json")
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command.append(str(Path(__file__).resolve()))
        command += ["--task", name, "--report", str(child_report)]
        qpa = "cocoa" if sys.platform == "darwin" else ("windows" if sys.platform == "win32" else "offscreen")
        env = dict(os.environ, QT_QPA_PLATFORM=qpa)
        try:
            child = subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=180)
            code = child.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        except OSError:
            code = "could_not_start"
        result[name] = json.loads(child_report.read_text(encoding="utf-8")) if child_report.is_file() else {"failure": "no_report"}
        result[name]["exit_code"] = code
        output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    result["completed"] = True
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print("Diagnostic report:", output)
    if not args.no_dialog:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.information(None, "Anatomy Explorer diagnostic complete",
                                "The report is ready. Nothing was installed or uploaded.\n\n" + str(output))
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", "-R", str(output)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
