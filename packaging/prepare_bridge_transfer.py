"""Create a small source-only native bridge transfer; no models, packs, or git db."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_update_bridge import BASE_COMMIT, DEFAULT_PATCHES, patch_name

TRANSFER_FILES = (
    "app/__init__.py", "app/updater.py", "app/tls.py", "app/macho_sections.py",
    "packaging/build_update_bridge.py", "packaging/run_update_bridge.py",
    "packaging/update_payload.py", "packaging/reconstruct_bundle.py", "packaging/release_storage.py",
    "packaging/check_runtime.py", "packaging/check_bundle_update.py", "packaging/check_mac_update.py",
    "packaging/check_cocoa.py", "packaging/check_https.py", "packaging/UPDATE_BRIDGE.md",
    "packaging/diagnostics/mac_ax/run_matrix.py", "packaging/qt-cocoa/PROVENANCE.json",
    "tests/__init__.py", "tests/test_update_bridge.py",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New .zip file; existing outputs are never overwritten")
    parser.add_argument("--base-commit", default=BASE_COMMIT)
    parser.add_argument("--patch", action="append")
    args = parser.parse_args(argv)
    patches = [patch_name(name) for name in (args.patch or DEFAULT_PATCHES)]
    identities = {}
    for name in patches:
        original = subprocess.run(["git", "show", f"{args.base_commit}:{name}"], cwd=ROOT,
                                  capture_output=True, check=True).stdout
        identities[name] = {"size": len(original), "sha256": hashlib.sha256(original).hexdigest()}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    baseline = {"base_commit": args.base_commit, "candidate_source_commit": commit, "files": identities}
    files = sorted(set(TRANSFER_FILES) | set(patches))
    checksums = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    checksums["source-baseline.json"] = hashlib.sha256(json.dumps(baseline, indent=2).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for name in files:
            output.write(ROOT / name, name)
        output.writestr("source-baseline.json", json.dumps(baseline, indent=2))
        output.writestr("transfer-sha256.json", json.dumps(checksums, indent=2))
    print(json.dumps({"path": str(args.output.resolve()), "size": args.output.stat().st_size,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "baseline_source": args.base_commit, "selected_patches": patches,
                      "files": len(files) + 2}, indent=2))


if __name__ == "__main__":
    main()
