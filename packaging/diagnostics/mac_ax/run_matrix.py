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
                        help="Run one bounded plain case to localize a pre-getter hang")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [(1, "plain", "selected-first"), (2, "plain", "selected-first"),
             (2, "combined", "selected-first"), (2, "plain", "hierarchy-first"),
             (2, "combined", "hierarchy-first")]
    if args.single_plain:
        cases = cases[:1]
    results = []
    for columns, mode, order in cases:
        name = f"columns{columns}-{mode}-{order}"
        report = args.output / (name + ".jsonl")
        command = [sys.executable, str(Path(__file__).with_name("tree_ax_repro.py")),
                   "--native-probe", "--auto", "--cycles", "3", "--interval-ms", "200",
                   "--columns", str(columns), "--mode", mode, "--probe-order", order,
                   "--report", str(report)]
        # Captured stderr may contain OS crash paths; never emit or upload it.
        try:
            child = subprocess.run(command, env=dict(os.environ, QT_QPA_PLATFORM="cocoa"),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            code = child.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        rows = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()] if report.exists() else []
        complete = any(row.get("event") == "diagnostic_complete" and row.get("native_probe_exercised") for row in rows)
        getter_calls = sum(row.get("event") == "native_getter_end" for row in rows)
        passed = code == 0 and complete and getter_calls >= 24
        results.append({"case": name, "exit_code": code, "passed": passed,
                        "native_getter_completed": getter_calls,
                        "last_event": rows[-1] if rows else None})
        print(json.dumps(results[-1]), flush=True)
    summary = {"schema": 1, "cases": results, "physical_mac_validated": False,
               "external_ax_client_validated": False, "passed": all(row["passed"] for row in results)}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
