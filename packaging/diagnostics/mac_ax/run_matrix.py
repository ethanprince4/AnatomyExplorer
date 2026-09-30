"""Run bounded native Cocoa tree controls in separate disposable processes.

Reports contain synthetic labels and runtime versions, no crash dumps or user data.
This is a macOS CI discriminator, not validation of a physical Mac's AX client.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--single-plain", action="store_true",
                        help="Run the two-column selected-first plain crash-path control")
    parser.add_argument("--private-loader-log-dir", type=Path,
                        help="Optional candidate-only logs; keep outside uploaded evidence")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [(1, "plain", "selected-first"), (2, "plain", "selected-first"),
             (2, "combined", "selected-first"), (2, "plain", "hierarchy-first"),
             (2, "combined", "hierarchy-first")]
    if args.single_plain:
        cases = [(2, "plain", "selected-first")]
    results = []
    for columns, mode, order in cases:
        name = f"columns{columns}-{mode}-{order}"
        report = args.output / (name + ".jsonl")
        command = [sys.executable, str(Path(__file__).with_name("tree_ax_repro.py")),
                   "--native-probe", "--auto", "--cycles", "3", "--interval-ms", "200",
                   "--columns", str(columns), "--mode", mode, "--probe-order", order,
                   "--report", str(report)]
        # Default stderr remains private. Candidate logs are explicitly requested
        # for load verification and must remain outside the uploaded evidence.
        streams = []
        try:
            stdout = stderr = subprocess.DEVNULL
            if args.private_loader_log_dir:
                args.private_loader_log_dir.mkdir(parents=True, exist_ok=True)
                stdout = (args.private_loader_log_dir / (name + '.stdout')).open('w', encoding='utf-8')
                stderr = (args.private_loader_log_dir / (name + '.stderr')).open('w', encoding='utf-8')
                streams = [stdout, stderr]
            child = subprocess.run(command, env=dict(os.environ, QT_QPA_PLATFORM="cocoa"),
                                   stdout=stdout, stderr=stderr, timeout=60)
            code = child.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        finally:
            for stream in streams:
                stream.close()
        rows = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()] if report.exists() else []
        complete = any(row.get("event") == "diagnostic_complete" and row.get("native_probe_exercised") for row in rows)
        getter_calls = sum(row.get("event") == "native_getter_end" for row in rows)
        probes = [row for row in rows if row.get("event") == "native_probe_end"]
        semantic_valid = bool(probes) and all(row.get("semantic_valid") is True for row in probes)
        passed = code == 0 and complete and getter_calls >= 24 and semantic_valid
        results.append({"case": name, "exit_code": code, "passed": passed,
                        "semantic_valid": semantic_valid,
                        "invalid_probe_count": sum(row.get("semantic_valid") is not True for row in probes),
                        "native_getter_completed": getter_calls,
                        "last_event": rows[-1] if rows else None})
        print(json.dumps(results[-1]), flush=True)
    summary = {"schema": 1, "cases": results, "physical_mac_validated": False,
               "external_ax_client_validated": False, "passed": all(row["passed"] for row in results)}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
