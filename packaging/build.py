"""Build the installable app for this platform.

    python packaging/build.py [--version 1.2.3] [--skip-prebuild] [--no-package] [--jobs N]

1. packaging/prebuild.py builds the caches the app ships with.
2. PyInstaller builds packaging/dist/AnatomyExplorer/ (and on macOS packaging/dist/Anatomy Explorer.app).
3. The download is packed into packaging/dist/release/ under a fixed name, so the README can link to
   releases/latest/download/<name>:
     Windows  AnatomyExplorer-Setup-Windows.exe          (Inno Setup, packaging/installer.iss)
     macOS    AnatomyExplorer-macOS-AppleSilicon.dmg     (ad-hoc signed .app + an Applications link)
   Elsewhere only the folder is built (used to test the bundle on Linux).
The release workflow (.github/workflows/release.yml) runs this on Windows and macOS runners."""
import os
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
WIN_ASSET = "AnatomyExplorer-Setup-Windows.exe"
MAC_ASSET = "AnatomyExplorer-macOS-AppleSilicon.dmg"


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def numeric_version(v):
    """'v1.2.3' / '1.2' / 'dev' -> '1.2.3' / '1.2.0' / '0.0.0' (installers and Info.plist want plain numbers)."""
    nums = re.findall(r"\d+", v or "")[:3]
    return ".".join((nums + ["0", "0", "0"])[:3])


def pyinstaller(version, channel="stable", release_tag=None):
    env = dict(os.environ, APP_VERSION=version, APP_CHANNEL=channel,
               APP_RELEASE_TAG=release_tag or f"v{version}")
    if sys.platform == "win32":
        # Native toolkits on a developer/runner PATH (notably Poppler's ICU)
        # can shadow Windows/Qt dependencies during bindepend collection.
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        env["PATH"] = os.pathsep.join(map(str, [Path(sys.executable).parent, Path(sys.base_prefix), system / "System32", system]))
    run(sys.executable, "-m", "PyInstaller", PKG / "AnatomyExplorer.spec", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", PKG / "build" / "pyinstaller", cwd=ROOT, env=env)


def windows_installer(version, channel="stable"):
    candidates = [shutil.which("iscc"), shutil.which("ISCC"),
                  Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe"]
    iscc = next((Path(c) for c in candidates if c and Path(c).exists()), None)
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) not found: install it from https://jrsoftware.org/isdl.php")
    run(iscc, f"/DAppVersion={version}", f"/DSourceDir={DIST / 'AnatomyExplorer'}", f"/DOutputDir={RELEASE}",
        f"/DOutputName={Path(WIN_ASSET).stem}", f"/DExperimental={int(channel == 'experimental')}",
        f"/DIconFile={ROOT / 'app' / 'resources' / 'icon.ico'}",
        PKG / "installer.iss")


def mac_dmg(channel="stable", release_tag=None):
    app_name = "Anatomy Explorer Experimental" if channel == "experimental" else "Anatomy Explorer"
    app = DIST / (app_name + ".app")
    # No Developer ID: an ad-hoc signature is what lets an Apple silicon Mac run the app at all. The first launch
    # still needs right-click > Open (see README).
    run("codesign", "--force", "--deep", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    from update_payload import create_payload
    version = (app / "Contents/Resources/VERSION").read_text(encoding="utf-8").strip()
    create_payload(app, RELEASE, version, "macos-arm64", channel=channel, release_tag=release_tag)
    staging = PKG / "build" / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run("ditto", app, staging / app.name)               # ditto keeps symlinks and the signature intact
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


def main():
    args = sys.argv[1:]
    tag = args[args.index("--version") + 1] if "--version" in args else "v0.0.0"
    from app.updater import release_version
    channel = "experimental" if "-preview." in tag else "stable"
    version = release_version(tag if tag.startswith("v") else "v" + tag, channel)
    tag = tag if tag.startswith("v") else "v" + tag
    jobs = args[args.index("--jobs") + 1] if "--jobs" in args else "4"
    if "--skip-prebuild" not in args:
        run(sys.executable, PKG / "prebuild.py", "--jobs", jobs, cwd=ROOT)
    pyinstaller(version, channel, tag)
    if "--no-package" in args:
        return
    RELEASE.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        from update_payload import create_payload
        create_payload(DIST / "AnatomyExplorer", RELEASE, version, channel=channel, release_tag=tag)
        windows_installer(version, channel)
    elif sys.platform == "darwin":
        mac_dmg(channel, tag)
    else:
        print("no installer format for this platform; the app folder is in", DIST / "AnatomyExplorer")
        return
    for f in RELEASE.iterdir():
        print(f"{f.name}: {f.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
