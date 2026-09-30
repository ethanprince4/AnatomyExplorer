"""Small independent diagnostic: Qt/NumPy/ModernGL/TLS, no anatomy/model assets."""
import sys
import os
import json
from pathlib import Path
from importlib.metadata import distribution
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
datas = [(str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_LICENSES.md"), ".")]
metadata = ROOT / "packaging/build/diagnostic-meta/DIAGNOSTIC.json"
metadata.parent.mkdir(parents=True, exist_ok=True)
metadata.write_text(json.dumps({"source_commit": os.environ.get("GITHUB_SHA", "local-unpublished"),
                                "diagnostic_version": "1.0.0", "stable_release": False}), encoding="utf-8")
datas.append((str(metadata), "."))
datas += [(str(p), "licenses") for p in (ROOT / "packaging/licenses").glob("*.txt")]
for name in ("numpy", "moderngl", "glcontext", "certifi", "pyinstaller"):
    for f in distribution(name).files or []:
        if ".dist-info/" in str(f) and any(x in f.name.upper() for x in ("LICEN", "COPYING", "NOTICE")):
            datas.append((str(f.locate()), "licenses/" + name))
for candidate in (Path(sys.base_prefix) / "LICENSE.txt",
                  Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"):
    if candidate.is_file():
        datas.append((str(candidate), "licenses/python"))
        break
a = Analysis([str(ROOT / "packaging/diagnostics/single_action/launcher.py")],
             pathex=[str(ROOT), str(ROOT / "packaging/diagnostics/mac_ax")], datas=datas,
             hiddenimports=collect_submodules("glcontext"),
             excludes=["app.main_window", "app.viewport", "app.data", "app.micro", "app.models",
                       "scipy", "skimage", "shapely", "matplotlib", "tkinter", "IPython",
                       "PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.QtQml"],
             module_collection_mode={"app": "py"})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AnatomyExplorerDiagnostic",
          console=False, upx=False, target_arch="arm64" if sys.platform == "darwin" else None,
          codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="AnatomyExplorerDiagnostic", upx=False)
if sys.platform == "darwin":
    bundle = BUNDLE(coll, name="Anatomy Explorer Diagnostic.app", version="1.0.0",
                    bundle_identifier="io.github.ethanprince4.anatomyexplorer.diagnostic",
                    info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0"})
