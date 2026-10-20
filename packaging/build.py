"""Build the installable app for this platform.

    python packaging/build.py [--version 1.2.3] [--skip-prebuild] [--no-package] [--jobs N]

1. packaging/prebuild.py builds the caches the app ships with.
2. PyInstaller builds packaging/dist/LayeredHuman/ (and on macOS packaging/dist/Layered Human.app).
3. The download is packed into packaging/dist/release/ under a fixed name, so the README can link to
   releases/latest/download/<name>:
     Windows  LayeredHuman-Setup-Windows.exe          (Inno Setup, packaging/installer.iss)
     macOS    LayeredHuman-macOS-AppleSilicon.dmg     (ad-hoc signed .app + an Applications link)
   Elsewhere only the folder is built (used to test the bundle on Linux).
The release workflow (.github/workflows/release.yml) runs this on Windows and macOS runners."""
import os
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "packaging"
DIST = PKG / "dist"
RELEASE = DIST / "release"
WIN_ASSET = "LayeredHuman-Setup-Windows.exe"
MAC_ASSET = "LayeredHuman-macOS-AppleSilicon.dmg"


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def numeric_version(v):
    """'v1.2.3' / '1.2' / 'dev' -> '1.2.3' / '1.2.0' / '0.0.0' (installers and Info.plist want plain numbers)."""
    nums = re.findall(r"\d+", v or "")[:3]
    return ".".join((nums + ["0", "0", "0"])[:3])


def pyinstaller(version, channel="stable", release_tag=None, model_library=None):
    from release_storage import ci_links_enabled, require_space
    ci_links_enabled()  # Reject accidental hardlink builds outside disposable CI.
    require_space(PKG, 256 * 1024**2, 'Before frozen build')
    if sys.platform == "darwin":
        # Fail before packaging if the exact accepted wheel/plugin cannot be established.
        from install_cocoa import install
        install()
    env = dict(os.environ, APP_VERSION=version, APP_CHANNEL=channel,
               APP_RELEASE_TAG=release_tag or f"v{version}")
    if model_library:
        env["AE_BUNDLE_MODEL_LIBRARY"] = str(Path(model_library).resolve())
    if sys.platform == "win32":
        # Native toolkits on a developer/runner PATH (notably Poppler's ICU)
        # can shadow Windows/Qt dependencies during bindepend collection.
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        env["PATH"] = os.pathsep.join(map(str, [Path(sys.executable).parent, Path(sys.base_prefix), system / "System32", system]))
    run(sys.executable, "-m", "PyInstaller", PKG / "LayeredHuman.spec", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", PKG / "build" / "pyinstaller", cwd=ROOT, env=env)
    # Old immutable launchers start this exact filename. Include a regular-file
    # alias before signing/packing; a symlink would fail their required-file check.
    bundle = DIST / (("Layered Human Experimental" if channel == "experimental" else "Layered Human") + ".app")
    binaries = bundle / "Contents/MacOS" if sys.platform == "darwin" else DIST / "LayeredHuman"
    suffix = ".exe" if sys.platform == "win32" else ""
    shutil.copy2(binaries / ("LayeredHuman" + suffix), binaries / ("AnatomyExplorer" + suffix))


def windows_installer(version, channel="stable"):
    candidates = [shutil.which("iscc"), shutil.which("ISCC"),
                  Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe"]
    iscc = next((Path(c) for c in candidates if c and Path(c).exists()), None)
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) not found: install it from https://jrsoftware.org/isdl.php")
    run(iscc, f"/DAppVersion={version}", f"/DSourceDir={DIST / 'LayeredHuman'}", f"/DOutputDir={RELEASE}",
        f"/DOutputName={Path(WIN_ASSET).stem}", *(["/DExperimental"] if channel == "experimental" else []),
        f"/DIconFile={ROOT / 'app' / 'resources' / 'icon.ico'}",
        PKG / "installer.iss")


def mac_dmg(channel="stable", release_tag=None):
    app_name = "Layered Human Experimental" if channel == "experimental" else "Layered Human"
    app = DIST / (app_name + ".app")
    # No Developer ID: an ad-hoc signature is what lets an Apple silicon Mac run the app at all. The first launch
    # still needs right-click > Open (see README).
    run("codesign", "--force", "--deep", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    from update_payload import create_payload
    version = (app / "Contents/Resources/VERSION").read_text(encoding="utf-8").strip()
    manifest = create_payload(app, RELEASE, version, "macos-arm64", channel=channel, release_tag=release_tag)
    staging = PKG / "build" / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    from release_storage import ci_links_enabled, immutable_copy
    if ci_links_enabled():
        # The sealed app and DMG staging are read-only from here onward. Sharing
        # their bytes avoids an additional full bundle; symlinks stay symlinks.
        shutil.copytree(app, staging / app.name, symlinks=True, copy_function=immutable_copy)
        run("codesign", "--verify", "--deep", "--strict", staging / app.name)
    else:
        run("ditto", app, staging / app.name)
    (staging / "Applications").symlink_to("/Applications")
    out = RELEASE / MAC_ASSET
    out.unlink(missing_ok=True)
    cmd = ["hdiutil", "create", "-volname", app_name, "-srcfolder", staging, "-fs", "HFS+",
           "-format", "UDZO", "-imagekey", "zlib-level=9", "-ov", out]
    for attempt in range(3):            # hdiutil now and then fails with "Resource busy" on CI machines
        try:
            run(*cmd)
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(15)
    shutil.rmtree(staging, ignore_errors=True)
    return manifest


def selected_model_library(args):
    """Resolve the same seed as the spec before scheduling procedural builders."""
    explicit = args[args.index("--model-library") + 1] if "--model-library" in args else os.environ.get("AE_BUNDLE_MODEL_LIBRARY")
    seed = Path(explicit).resolve() if explicit else ROOT / "data/local_model_library"
    if not explicit and not (seed / "library.json").is_file():
        return None
    data = json.loads((seed / "library.json").read_text(encoding="utf-8-sig"))
    rows = data.get("models", [])
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    if not rows:
        raise ValueError("Release model library has no models")
    for row in rows:
        post = row.get("variants", {}).get("post")
        path = post.get("path") if isinstance(post, dict) else post
        if not path or not (seed / path).is_file():
            raise ValueError(f"{row.get('id', '<unnamed>')}: release requires an available post-refine model")
    # The seed collector validates portable companion paths when packaging.
    return str(seed)


def main():
    args = sys.argv[1:]
    tag = args[args.index("--version") + 1] if "--version" in args else "v0.0.0"
    from app.updater import release_version
    channel = "experimental" if "-preview." in tag else "stable"
    version = release_version(tag if tag.startswith("v") else "v" + tag, channel)
    tag = tag if tag.startswith("v") else "v" + tag
    jobs = args[args.index("--jobs") + 1] if "--jobs" in args else "4"
    model_library = selected_model_library(args)
    if "--skip-prebuild" not in args:
        flags = ["--skip-micro", "--skip-models"] if model_library else []
        run(sys.executable, PKG / "prebuild.py", "--jobs", jobs, *flags, cwd=ROOT)
    pyinstaller(version, channel, tag, model_library=model_library)
    if "--no-package" in args:
        return
    RELEASE.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        from update_payload import create_payload
        manifest = create_payload(DIST / "LayeredHuman", RELEASE, version, channel=channel, release_tag=tag)
        windows_installer(version, channel)
    elif sys.platform == "darwin":
        manifest = mac_dmg(channel, tag)
    else:
        print("no installer format for this platform; the app folder is in", DIST / "LayeredHuman")
        return
    bundle_bytes = sum(entry['size'] for entry in manifest['files'])
    feed_bytes = sum(manifest['packs'].values())
    installer_bytes = (RELEASE / (MAC_ASSET if sys.platform == 'darwin' else WIN_ASSET)).stat().st_size
    print(f"release storage: bundle={bundle_bytes:,}; feed={feed_bytes:,}; installer={installer_bytes:,}; "
          f"free={shutil.disk_usage(RELEASE).free:,}; "
          f"additional_native_check={(bundle_bytes * (2 if sys.platform == 'darwin' else 1) + 256 * 1024**2):,}; "
          f"additional_split={installer_bytes + 256 * 1024**2:,}", flush=True)
    for f in RELEASE.iterdir():
        print(f"{f.name}: {f.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
