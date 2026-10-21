"""Build small Cloudflare-only fresh-install helpers from verified frozen trees.

The multi-gigabyte, immutable v4.0.11 installer seeds already live in R2. Only
the exact changed files and the small native helper are built here. Neither
PyInstaller nor a full installer build runs. Publication is a separate step.
"""
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.updater import file_sha, legacy_manifest, validate_manifest

HERE = Path(__file__).resolve().parent / "cloudflare_installer"
ORIGIN = "https://downloads.layeredhuman.com"
PREFIX = "releases/v4.0.12/installers/cf-only-1"
VERSION = "4.0.12"
SEED_COMMIT = "3e814b9ddebbcea58e33d7541f6b02b8f890fd42"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def safe_name(name):
    if (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name
            or ":" in name or any(c in name for c in "\r\n\t")
            or any(p in {"", ".", ".."} or p.endswith((".", " ")) for p in name.split("/"))):
        raise ValueError("Unsafe inventory name")
    return name


def seed_plan():
    plan = json.loads((HERE / "seed-v4.0.11.json").read_text(encoding="utf-8"))
    if (plan["release"] != "v4.0.11" or plan["source_commit"] != SEED_COMMIT
            or plan["domain"] != "downloads.layeredhuman.com" or len(plan["original_parts"]) != 9):
        raise ValueError("Unexpected installer seed identity")
    for part in plan["original_parts"]:
        if (part["platform"] not in {"windows", "macos"} or not re.fullmatch(r"[A-Za-z0-9._-]+", part["name"])
                or type(part["size"]) is not int or part["size"] <= 0
                or not re.fullmatch(r"[a-f0-9]{64}", part["sha256"])):
            raise ValueError("Invalid seed part")
        offset = 0
        for fragment in part["fragments"]:
            if (not re.fullmatch(r"releases/v4\.0\.11/install/" + part["platform"] + r"/[A-Za-z0-9._-]+\.bin", fragment["key"])
                    or fragment["source_offset"] != offset or type(fragment["size"]) is not int
                    or not 0 < fragment["size"] <= 128 * 1024**2):
                raise ValueError("Invalid seed fragment")
            offset += fragment["size"]
        if offset != part["size"]:
            raise ValueError("Seed fragment coverage differs")
    return plan


def inventory(manifest, extra=()):
    result = []
    for entry in manifest["files"]:
        safe_name(entry["path"])
        result.append({k: entry[k] for k in ("path", "size", "sha256", "mode") if k in entry})
    result.extend(extra)
    return sorted(result, key=lambda v: v["path"])


def inventory_text(entries):
    return "".join(f"{safe_name(e['path'])}\t{e['size']}\t{e['sha256']}\t{e.get('mode', 0o644):o}\n" for e in entries)


def verify_tree(root, manifest):
    root = Path(root).resolve(strict=True)
    for entry in manifest["files"]:
        path = root / safe_name(entry["path"])
        if (not path.is_file() or path.is_symlink() or path.resolve() != path
                or path.stat().st_size != entry["size"] or file_sha(path) != entry["sha256"]):
            raise ValueError(f"Frozen file differs: {entry['path']}")
        if sys.platform != "win32" and path.stat().st_mode & 0o777 != entry.get("mode", 0o644):
            raise ValueError(f"Frozen file mode differs: {entry['path']}")
    for link in manifest.get("symlinks", []):
        path = root / safe_name(link["path"])
        if not path.is_symlink() or os.readlink(path) != link["target"] or not path.resolve().is_relative_to(root):
            raise ValueError("Frozen symlink differs")


def prepare(platform, base, candidate, previous, manifest, out):
    previous_path, manifest_path = Path(previous), Path(manifest)
    previous = validate_manifest(json.loads(previous_path.read_text(encoding="utf-8")))
    manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    if (manifest["version"] != VERSION or manifest.get("release_tag") != "v" + VERSION
            or previous["version"] != "4.0.11" or manifest["platform"] != platform
            or previous["platform"] != platform or manifest.get("channel", "stable") != "stable"):
        raise ValueError("Fresh installer is pinned to the validated stable bridge")
    prior = {e["path"]: e for e in previous["files"]}
    final = {e["path"]: e for e in manifest["files"]}
    if prior.keys() != final.keys() or previous.get("symlinks", []) != manifest.get("symlinks", []):
        raise ValueError("Bridge seed and final path inventories differ")
    verify_tree(base, previous)
    verify_tree(candidate, manifest)
    changed = [e for name, e in final.items() if (e["sha256"], e.get("mode", 0o644)) !=
               (prior[name]["sha256"], prior[name].get("mode", 0o644))]
    if not changed:
        raise ValueError("Bridge overlay is empty")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / ("windows-inputs" if platform == "windows-x64" else "mac-inputs")
    inputs.mkdir(exist_ok=True)
    label = "Windows" if platform == "windows-x64" else "Mac"
    archive = out / f"LayeredHuman-{label}-4.0.12-overlay.zip"
    aliases = (("LayeredHuman-Windows-update.json", manifest),
               ("AnatomyExplorer-Windows-update.json", legacy_manifest(manifest))) if platform == "windows-x64" else (
                   ("LayeredHuman-macOS-update.json", manifest), ("AnatomyExplorer-macOS-update.json", manifest))
    metadata, alias_entries = {}, []
    for name, value in aliases:
        data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        metadata[name] = data
        alias_entries.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": 0o644})
    # Only regular, reviewed manifest paths enter the archive. No extraction-time
    # links, directory entries or files chosen by untrusted network metadata.
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for entry in sorted(changed, key=lambda e: e["path"]):
            info = zipfile.ZipInfo("payload/" + safe_name(entry["path"]), date_time=(2026, 10, 20, 0, 0, 0))
            info.external_attr = (0o100000 | entry.get("mode", 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, (Path(candidate) / entry["path"]).read_bytes())
        for name, data in metadata.items():
            info = zipfile.ZipInfo("metadata/" + name, date_time=(2026, 10, 20, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
    entries = inventory(manifest, alias_entries if platform == "windows-x64" else ())
    (inputs / "base-inventory.tsv").write_text(inventory_text(inventory(previous)), encoding="utf-8", newline="\n")
    (inputs / "inventory.tsv").write_text(inventory_text(entries), encoding="utf-8", newline="\n")
    (inputs / "delta.txt").write_text("".join(e["path"] + "\n" for e in sorted(changed, key=lambda e:e["path"])), encoding="utf-8", newline="\n")
    (inputs / "symlinks.tsv").write_text("".join(f"{safe_name(e['path'])}\t{e['target']}\n" for e in manifest.get("symlinks", [])), encoding="utf-8", newline="\n")
    for name, data in metadata.items():
        (inputs / name).write_bytes(data)
    record = {"schema": 1, "version": VERSION, "platform": platform, "prefix": PREFIX,
              "overlay": {"name": archive.name, "size": archive.stat().st_size, "sha256": file_sha(archive)},
              "changed_files": len(changed), "changed_file_bytes": sum(e["size"] for e in changed),
              "bundle_bytes": sum(e["size"] for e in entries), "full_installer_rebuilt": False,
              "native_helper_built": False, "inventory_sha256": file_sha(inputs / "inventory.tsv")}
    record["base_manifest_sha256"] = file_sha(previous_path)
    record["final_manifest_sha256"] = file_sha(manifest_path)
    parts = [p for p in seed_plan()["original_parts"] if p["platform"] == ("windows" if platform == "windows-x64" else "macos")]
    record["seed_bytes"] = sum(p["size"] for p in parts)
    if platform == "windows-x64":
        source = windows_source(parts, record)
        (inputs / "Release.cs").write_text(source, encoding="utf-8", newline="\n")
    else:
        values = {"@VERSION@": VERSION, "@ORIGIN@": ORIGIN, "@PREFIX@": PREFIX,
                  "@OVERLAY@": archive.name, "@OVERLAYSIZE@": record["overlay"]["size"],
                  "@OVERLAYSHA@": record["overlay"]["sha256"], "@TOTAL@": record["seed_bytes"],
                  "@BUNDLEBYTES@": record["bundle_bytes"],
                  "@PARTS@": "\n".join(f"  '{p['name']} {p['sha256']} {p['size']}'" for p in parts),
                  "@FRAGMENTS@": "\n".join(f"  '{p['name']} {f['key']} {f['size']}'" for p in parts for f in p["fragments"])}
        script = (HERE / "install.sh.in").read_text(encoding="utf-8")
        for key, value in values.items():
            script = script.replace(key, str(value))
        if re.search(r"@[A-Z]+@", script):
            raise ValueError("Unfilled Mac helper template")
        (inputs / "install.sh").write_text(script, encoding="utf-8", newline="\n")
        apple = (HERE / "Installer.applescript.in").read_text(encoding="utf-8").replace("@NAME@", "Layered Human").replace("@VERSION@", VERSION)
        (inputs / "Installer.applescript").write_text(apple, encoding="utf-8", newline="\n")
    (out / f"{platform}-helper-build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return inputs, record


def windows_source(parts, record):
    lines = []
    for p in parts:
        fragments = ",\n".join(f'            new Fragment("{ORIGIN}/{f["key"]}", {f["source_offset"]}L, {f["size"]}L)' for f in p["fragments"])
        lines.append(f'        new Part("{p["name"]}", {p["size"]}L, "{p["sha256"]}",\n{fragments}),')
    return '\n'.join([
        'using System.Reflection;', '[assembly: AssemblyTitle("Install Layered Human")]',
        '[assembly: AssemblyVersion("4.0.12.0")]', 'static class Release {',
        ' public const string AppName="Layered Human", Version="4.0.12", Setup="LayeredHuman-Setup-Windows.exe";',
        f' public const string Origin="{ORIGIN}", Base="{ORIGIN}", Page="https://layeredhuman.com";',
        f' public const string OverlayUrl="{ORIGIN}/{PREFIX}/{record["overlay"]["name"]}";',
        f' public const string OverlayHash="{record["overlay"]["sha256"]}";',
        f' public const long OverlaySize={record["overlay"]["size"]}L;',
        ' public static readonly Part[] Parts={', *lines, ' };', '}']) + '\n'


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def build_windows(out, inputs):
    if sys.platform != "win32" or not CSC.is_file():
        raise ValueError("Compile the Windows helper natively with the .NET Framework compiler")
    target = Path(out) / "Install-Layered-Human-Windows.exe"
    run(CSC, "/nologo", "/target:winexe", "/optimize+", f"/out:{target}",
        f"/win32icon:{ROOT / 'app/resources/icon.ico'}", f"/win32manifest:{ROOT / 'packaging/windows_installer/app.manifest'}",
        "/r:System.dll", "/r:System.Core.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
        "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
        f"/resource:{inputs / 'inventory.tsv'},inventory.tsv", f"/resource:{inputs / 'base-inventory.tsv'},base-inventory.tsv",
        f"/resource:{inputs / 'delta.txt'},delta.txt", HERE / "Installer.cs", HERE / "FragmentDownloader.cs",
        HERE / "FreshInstall.cs", inputs / "Release.cs")
    return target


def build_mac(out, inputs):
    if sys.platform != "darwin":
        raise ValueError("Build the Mac applet natively with osacompile/codesign/hdiutil")
    target = Path(out) / "Install-Layered-Human-Mac.dmg"
    with tempfile.TemporaryDirectory(prefix="lh-cf-helper-") as temp:
        app = Path(temp) / "Install Layered Human.app"
        run("osacompile", "-x", "-o", app, inputs / "Installer.applescript")
        resources = app / "Contents/Resources"
        for name in ("install.sh", "inventory.tsv", "base-inventory.tsv", "delta.txt", "symlinks.tsv"):
            shutil.copy2(inputs / name, resources / name)
        (resources / "install.sh").chmod(0o755)
        run("codesign", "--force", "--deep", "--sign", "-", app)
        run("codesign", "--verify", "--deep", "--strict", app)
        stage = Path(temp) / "image"
        stage.mkdir()
        run("ditto", app, stage / app.name)
        run("hdiutil", "create", "-volname", "Install Layered Human", "-srcfolder", stage, "-format", "UDZO", "-ov", target)
        run("hdiutil", "verify", target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("windows-x64", "macos-arm64"))
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    inputs, record = prepare(args.platform, args.base, args.candidate, args.previous_manifest, args.manifest, args.out)
    if not args.prepare_only:
        target = build_windows(args.out, inputs) if args.platform == "windows-x64" else build_mac(args.out, inputs)
        record["helper"] = {"name": target.name, "size": target.stat().st_size, "sha256": file_sha(target)}
        record["native_helper_built"] = True
        (args.out / f"{args.platform}-helper-build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
