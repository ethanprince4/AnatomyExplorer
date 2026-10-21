#!/usr/bin/env python3
"""Build only the download helpers from frozen release metadata; never rebuild or repack the app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / "upstream"
PLAN = HERE.parent / "release-plan.json"
COMMIT = "3e814b9ddebbcea58e33d7541f6b02b8f890fd42"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
MAC_APP = "Install Layered Human.app"


def run(*args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def fill(path, values):
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@" + key + "@", str(value))
    left = re.search(r"@[A-Z]+@", text)
    if left:
        raise ValueError(f"Unfilled template value: {left.group()}")
    return text


def load_plan():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan["release"] != "v4.0.11" or plan["source_commit"] != COMMIT:
        raise ValueError("This helper-only build is pinned to the reviewed v4.0.11 source")
    for part in plan["original_parts"]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", part["name"]):
            raise ValueError("Unsafe part filename")
        if not re.fullmatch(r"[0-9a-f]{64}", part["sha256"]):
            raise ValueError("Invalid original-part SHA-256")
        expected = "https://github.com/ethanprince4/AnatomyExplorer/releases/download/v4.0.11/" + part["name"]
        if part["source_url"] != expected:
            raise ValueError("Unexpected original fallback URL")
        offset = 0
        for fragment in part["fragments"]:
            if (fragment["source_offset"] != offset or not 0 < fragment["size"] <= 128 * 1024**2
                    or not re.fullmatch(r"releases/v4\.0\.11/install/(?:windows|macos)/[A-Za-z0-9._-]+\.bin", fragment["key"])):
                raise ValueError("Invalid fragment layout")
            offset += fragment["size"]
        if offset != part["size"]:
            raise ValueError("Fragments do not cover the original part")
    if len(plan["original_parts"]) != 9 or sum(len(p["fragments"]) for p in plan["original_parts"]) != 64:
        raise ValueError("Unexpected release-part count")
    return plan


def prepare(out):
    plan = load_plan()
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    mirror = "https://downloads.layeredhuman.com"
    base = "https://github.com/ethanprince4/AnatomyExplorer/releases/download/v4.0.11"
    entries = []
    for part in plan["original_parts"]:
        if part["platform"] != "windows":
            continue
        fragments = ",\n".join(f'            new Fragment("{mirror}/{f["key"]}", {f["source_offset"]}L, {f["size"]}L)'
                               for f in part["fragments"])
        entries.append(f'        new Part("{part["name"]}", {part["size"]}L, "{part["sha256"]}",\n{fragments}),')
    release = fill(HERE / "windows_installer/Release.cs.in", {
        "APP": "Layered Human", "VERSION": "4.0.11", "TAG": plan["release"], "NUMBER": "4.0.11.0",
        "BASE": base, "PAGE": "https://github.com/ethanprince4/AnatomyExplorer/releases/latest",
        "SETUP": "LayeredHuman-Setup-Windows.exe", "PARTS": "\n".join(entries),
    })
    (inputs / "Release.cs").write_text(release, encoding="utf-8", newline="\n")
    mac = [p for p in plan["original_parts"] if p["platform"] == "macos"]
    size_record = json.loads((UPSTREAM / "mac-bundle-size.json").read_text(encoding="utf-8"))
    manifest = (UPSTREAM / size_record["asset"]).read_bytes()
    if "sha256:" + hashlib.sha256(manifest).hexdigest() != size_record["github_digest"]:
        raise ValueError("Mac original bundle manifest checksum changed")
    bundle_bytes = sum(f["size"] for f in json.loads(manifest)["files"])
    if bundle_bytes != size_record["bundle_bytes"]:
        raise ValueError("Mac bundle byte count changed")
    mac_inputs = out / "mac-inputs"
    mac_inputs.mkdir(parents=True, exist_ok=True)
    script = fill(HERE / "mac_installer/install.sh.in", {
        "BASE": base, "MIRROR": mirror, "DMG": "LayeredHuman-macOS-AppleSilicon.dmg",
        "BUNDLE": "Layered Human.app", "TOTAL": sum(p["size"] for p in mac), "BUNDLEBYTES": bundle_bytes,
        "PARTS": "\n".join(f"  '{p['name']} {p['sha256']} {p['size']}'" for p in mac),
        "FRAGMENTS": "\n".join(f"  '{p['name']} {f['key']} {f['size']}'" for p in mac for f in p["fragments"]),
    })
    (mac_inputs / "install.sh").write_text(script, encoding="utf-8", newline="\n")
    apple = fill(UPSTREAM / "packaging/mac_installer/Installer.applescript.in", {
        "NAME": "Layered Human", "VERSION": plan["release"],
    })
    (mac_inputs / "Installer.applescript").write_text(apple, encoding="utf-8", newline="\n")
    metadata = {"release": plan["release"], "source_commit": COMMIT, "mirror": mirror,
                "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(), "mac_bundle_bytes": bundle_bytes,
                "payloads_rebuilt": False, "native_mac_build": False, "windows_build": False}
    (out / "build-record.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return inputs, mac_inputs


def build_windows(out, inputs):
    if sys.platform != "win32" or not CSC.is_file():
        raise SystemExit(f"Windows helper requires Windows and {CSC}")
    exe = out / "Install-Layered-Human-Windows.exe"
    run(CSC, "/nologo", "/target:winexe", "/optimize+", f"/out:{exe}",
        f"/win32icon:{UPSTREAM / 'app/resources/icon.ico'}",
        f"/win32manifest:{UPSTREAM / 'packaging/windows_installer/app.manifest'}",
        "/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
        HERE / "windows_installer/Installer.cs", HERE / "windows_installer/FragmentDownloader.cs", inputs / "Release.cs")
    return exe


def build_mac(out, inputs):
    if sys.platform != "darwin":
        raise SystemExit("Mac helper requires macOS with osacompile, codesign, hdiutil, and ditto; no full app build is needed")
    with tempfile.TemporaryDirectory(prefix="lh-r2-installer-") as temp:
        work = Path(temp)
        app = work / MAC_APP
        run("osacompile", "-x", "-o", app, inputs / "Installer.applescript")
        resources = app / "Contents/Resources"
        if not resources.is_dir():
            raise SystemExit("osacompile did not produce the expected applet")
        shutil.copyfile(inputs / "install.sh", resources / "install.sh")
        (resources / "install.sh").chmod(0o755)
        run("codesign", "--force", "--deep", "--sign", "-", app)
        run("codesign", "--verify", "--deep", "--strict", app)
        stage = work / "image"
        stage.mkdir()
        run("ditto", app, stage / MAC_APP)
        dmg = out / "Install-Layered-Human-Mac.dmg"
        run("hdiutil", "create", "-volname", MAC_APP[:-4], "-srcfolder", stage, "-format", "UDZO", "-ov", dmg)
        return dmg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("prepare", "windows", "mac"))
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs, mac_inputs = prepare(out)
    artifact = None
    if args.platform == "windows":
        artifact = build_windows(out, inputs)
    if args.platform == "mac":
        artifact = build_mac(out, mac_inputs)
    if artifact:
        record_path = out / "build-record.json"
        record = json.loads(record_path.read_text())
        record["windows_build" if args.platform == "windows" else "native_mac_build"] = True
        record["artifact"] = {"name": artifact.name, "size": artifact.stat().st_size,
                              "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record["artifact"]))
    else:
        print(f"Prepared frozen build inputs in {out}")


if __name__ == "__main__":
    main()
