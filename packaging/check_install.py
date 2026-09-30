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
from app.updater import UpdateStore


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
        print(f"Verified first install: {manifest['version']}, {len(manifest['files'])} complete hashed package files; no pending update")


if __name__ == "__main__":
    main()
