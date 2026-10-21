"""Build and verify the bridge on the user's native computer, without Actions."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_bridge import BASE_COMMIT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--tag", default="v4.0.12")
    parser.add_argument("--base-tag", default="v4.0.11")
    parser.add_argument("--base-commit", default=BASE_COMMIT)
    parser.add_argument("--source-baseline", type=Path)
    parser.add_argument("--patch", action="append")
    parser.add_argument("--checks-only", action="store_true", help="Recheck an already built local candidate")
    args = parser.parse_args(argv)
    if sys.platform not in ("win32", "darwin"):
        parser.error("Use the user's Windows PC or Apple silicon MacBook")
    platform = "macos-arm64" if sys.platform == "darwin" else "windows-x64"
    work = args.work.resolve()
    reports = work / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    results = {"schema": 1, "platform": platform, "baseline": args.base_tag, "target": args.tag,
               "execution": "local native computer", "passed": False, "checks": []}

    def run(name, script, *arguments, timeout=180):
        command = [sys.executable, str(ROOT / "packaging" / script), *map(str, arguments)]
        print(f"Running {name}", flush=True)
        with (reports / f"{name}.log").open("w", encoding="utf-8") as output:
            completed = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=timeout)
        # Stream saved evidence only after the child exits; no app focus is taken.
        print((reports / f"{name}.log").read_text(encoding="utf-8"), flush=True)
        results["checks"].append({"name": name, "passed": completed.returncode == 0})
        if completed.returncode:
            raise RuntimeError(f"Native check failed: {name}; see {reports / (name + '.log')}")

    try:
        if not args.checks_only:
            options = ["--platform", platform, "--work", work, "--tag", args.tag,
                       "--base-tag", args.base_tag, "--base-commit", args.base_commit]
            if args.cache:
                options.extend(["--cache", args.cache.resolve()])
            baseline = args.source_baseline or (ROOT / "source-baseline.json" if (ROOT / "source-baseline.json").is_file() else None)
            if baseline:
                options.extend(["--source-baseline", baseline.resolve()])
            for name in args.patch or []:
                options.extend(["--patch", name])
            run("build", "build_update_bridge.py", *options, timeout=7200)
        bundle = "Layered Human.app" if sys.platform == "darwin" else "LayeredHuman"
        base, candidate, feed = work / "base" / bundle, work / "candidate" / bundle, work / "feed"
        executable = candidate / ("Contents/MacOS/LayeredHuman" if sys.platform == "darwin" else "LayeredHuman.exe")
        run("runtime", "check_runtime.py", executable)
        if sys.platform == "darwin":
            run("cocoa", "check_cocoa.py", executable, timeout=600)
            evidence = ROOT / "packaging/build/frozen-cocoa"
            if evidence.is_dir():
                shutil.copytree(evidence, reports / "frozen-cocoa", dirs_exist_ok=True)
            run("mac-update", "check_mac_update.py", candidate, feed, "--base", base,
                "--report", reports / "mac-update.json", timeout=1800)
        else:
            run("windows-update", "check_bundle_update.py", base, candidate, feed, timeout=1800)
            shutil.copy2(base.parent / "update-validation/real-package-result.json", reports / "windows-update.json")
            for evidence in (base.parent / "update-validation").glob("*.log"):
                shutil.copy2(evidence, reports / evidence.name)
        run("https", "check_https.py", executable, "--report", reports / "https.json", timeout=240)
        results["passed"] = True
    finally:
        (reports / "native-checks.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
