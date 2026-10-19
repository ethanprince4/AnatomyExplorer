"""First-install integrity check on a disposable Windows CI runner only.

Never run this installer check on a user's desktop: an installer registers the
product even with a temporary /DIR. Local tests use copied frozen folders instead.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import UpdateStore, manifest_channel


def registered_name(target):
    """DisplayName of the uninstall entry the installer wrote for the copy in target (None if there is none)."""
    import winreg
    wanted = os.path.normcase(str(target)).rstrip("\\")
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            root = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as entry:
                    try:
                        if os.path.normcase(winreg.QueryValueEx(entry, "InstallLocation")[0]).rstrip("\\") == wanted:
                            return winreg.QueryValueEx(entry, "DisplayName")[0]
                    except OSError:
                        continue
    return None


def main():
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Installer check is restricted to disposable Windows CI")
    installer = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="AnatomyExplorer-install-check-") as d:
        target = Path(d).resolve() / "Application"
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/NOICONS",
                        "/TASKS=", f"/DIR={target}", f"/LOG={Path(d) / 'install.log'}"], check=True, timeout=600)
        store = UpdateStore(target, Path(d) / "updates")
        manifest = store.verify(target)
        assert store.active() == target
        assert not store.state().get("pending")
        assert (target / "unins000.exe").exists()
        # The name follows the build's channel (every stable installer up to v4.0.8 called itself Experimental).
        channel = manifest_channel(manifest)
        expected = "Anatomy Explorer Experimental" if channel == "experimental" else "Anatomy Explorer"
        name = registered_name(target)
        assert name == expected, f"the {channel} installer registered itself as {name!r}, not {expected!r}"
        print(f"Verified first install of {name}: {manifest['version']},{len(manifest['files'])} complete hashed package files; no pending update")


if __name__ == "__main__":
    main()
