# PyInstaller spec for the installed app: a windowed one-folder build (plus a .app bundle on macOS).
# Run through packaging/build.py, which builds the caches this ships first (packaging/prebuild.py).
import os
import json
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
STAGE = ROOT / "packaging" / "build" / "stage"
VERSION = os.environ.get("APP_VERSION", "0.0.0")
CHANNEL = os.environ.get("APP_CHANNEL", "stable")
RELEASE_TAG = os.environ.get("APP_RELEASE_TAG", f"v{VERSION}")
APP_NAME = "Anatomy Explorer Experimental" if CHANNEL == "experimental" else "Anatomy Explorer"

# Everything the app reads at run time. Personal data (data/user), the raw Z-Anatomy source and scratch output are
# never shipped; data/anatomy's surface-sample and depth caches come from the stage (see prebuild.py).
# Legacy models/ assets are collected only for builds without a post-only release library.
DATA_DIRS = ["data/anatomy", "data/content", "data/findings", "data/histology", "data/radiology",
             "data/micro_cache", "data/models", "models", "app/resources", "app/ui/resources",
             "app/variants/anatomy_runtime_adapters", "app/variants/anatomy_variants"]
SKIP_DIRS = {"__pycache__", ".git", "model-library"}
SKIP_SUFFIXES = {".pyc", ".tmp", ".part", ".stackdump"}
STAGED = {"data/anatomy/samples.npz", "data/anatomy/depth.npz", "data/anatomy/dataset-manifest.json"}
# folders of which only these files are read at run time (models/ also holds the modellers' review notes)
ONLY_SUFFIXES = {"models": {".glb", ".json"}, "app/variants/anatomy_runtime_adapters": {".json"},
                 "app/variants/anatomy_variants": {".json"}}
# The reviewed adapter allowlist/teaching JSON travels in the verified updater
# payload. Locally computed generations and preferences remain external and are
# never collected from AE_MODEL_VARIANTS_DIR or the per-user variant store.


def data_files():
    out = []
    # Read-only release seed; accepted user files live outside this bundle.
    sys.path.insert(0, str(ROOT / "packaging"))
    from model_library_seed import seed_files
    seed = os.environ.get("AE_BUNDLE_MODEL_LIBRARY")
    if not seed and (ROOT / "data/local_model_library/library.json").is_file():
        seed = ROOT / "data/local_model_library"
    if seed:
        out.extend(seed_files(seed, STAGE / "release-seeds"))
    for rel in DATA_DIRS:
        if seed and rel in {"data/micro_cache", "data/models", "models"}:
            continue  # The post-only seed contains every selected model and companion.
        only = ONLY_SUFFIXES.get(rel)
        for dirpath, dirnames, filenames in os.walk(ROOT / rel):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                src = Path(dirpath) / name
                key = src.relative_to(ROOT).as_posix()
                if src.suffix in SKIP_SUFFIXES or name.endswith(".tmp.npz") or key in STAGED:
                    continue
                if only is not None and src.suffix.lower() not in only:
                    continue
                if src.suffix.lower() == ".glb" and src.stat().st_size < 1024:
                    raise SystemExit(f"{key} is a Git LFS pointer, not the model: run git lfs pull first")
                out.append((str(src), str(Path(key).parent)))
    for key in sorted(STAGED):
        src = STAGE / key
        if not src.exists():
            raise SystemExit(f"{src} is missing: run packaging/prebuild.py first")
        out.append((str(src), str(Path(key).parent)))
    return out + notice_files()


# Wheels whose code ends up in the bundle; their own licence files are copied to licenses/<name>/ (Qt/PySide6
# wheels carry none, so their LGPL/GPL texts come from packaging/licenses).
BUNDLED_DISTS = ["numpy", "scipy", "scikit-image", "shapely", "moderngl", "glcontext", "pillow", "imageio",
                 "tifffile", "lazy_loader", "networkx", "packaging", "pyinstaller", "certifi"]


def notice_files():
    """LICENSE, THIRD_PARTY_LICENSES.md and a VERSION file at the bundle root (app/ui/about.py reads them), and
    the licence texts of the bundled libraries under licenses/. data/anatomy/LICENSE ships with data/anatomy."""
    from importlib.metadata import PackageNotFoundError, distribution
    out = [(str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_LICENSES.md"), ".")]
    out += [(str(p), "licenses") for p in sorted((ROOT / "packaging" / "licenses").glob("*.txt"))]
    for name in BUNDLED_DISTS:
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue
        for f in dist.files or []:
            path = str(f)
            if ".dist-info/" in path and any(k in Path(path).name.upper() for k in ("LICEN", "COPYING", "NOTICE")):
                sub = Path(path.split(".dist-info/", 1)[1]).parent
                sub = Path(*sub.parts[1:]) if sub.parts[:1] == ("licenses",) else sub
                out.append((str(f.locate()), (Path("licenses") / name / sub).as_posix()))
    for cand in (Path(sys.base_prefix) / "LICENSE.txt",
                 Path(sys.base_prefix) / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"):
        if cand.exists():
            out.append((str(cand), "licenses/python"))
            break
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "VERSION").write_text(VERSION, encoding="utf-8")
    out.append((str(STAGE / "VERSION"), "."))
    (STAGE / "UPDATE_CHANNEL.json").write_text(
        json.dumps({"channel": CHANNEL, "release_tag": RELEASE_TAG}), encoding="utf-8")
    out.append((str(STAGE / "UPDATE_CHANNEL.json"), "."))
    if sys.platform == "darwin":
        for src in sorted((ROOT / "packaging/qt-cocoa").rglob("*")):
            if src.is_file() and src.name != "libqcocoa.dylib":
                relative = src.relative_to(ROOT / "packaging/qt-cocoa")
                out.append((str(src), (Path("licenses/qt-cocoa") / relative.parent).as_posix()))
    return out


a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT), str(ROOT / "packaging/diagnostics/mac_ax")],
    datas=data_files(),
    # registry.py finds registry_extra_*.py by listing its folder, so the whole package is collected
    hiddenimports=collect_submodules("app") + collect_submodules("glcontext")
                  + ["tree_ax_repro", "mac_native_probe", "runtime_binary"],
    # the app has no web view and no QML since the model viewer replaced the Sketchfab player: leaving these out
    # keeps Chromium (Qt WebEngine) and the QML runtime out of the installers
    excludes=["tkinter", "matplotlib", "IPython", "PyQt5", "PyQt6", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
              "PySide6.QtQuickControls2", "PySide6.QtQml", "PySide6.QtPositioning", "PySide6.QtMultimedia",
              "PySide6.QtPdf", "PySide6.QtPdfWidgets"],
    # the app package ships as plain .py files: the micro-model cache is keyed on a digest of app/micro's sources,
    # and registry.py globs its own folder, so both behave exactly as they do from source
    module_collection_mode={"app": "py"},
    noarchive=False,
)

# A safety net for the excludes above: no Qt library, plugin or resource of a module the app does not use ends up in
# the bundle even if some other package drags it in (Qt WebEngine alone is Chromium, a few hundred MB).
UNUSED_QT = re.compile(
    r"^(lib)?Qt6?(3D\w*|Charts\w*|DataVisualization\w*|Graphs\w*|Location|Multimedia\w*|Quick\w*|Qml\w*|"
    r"Sensors\w*|SpatialAudio|TextToSpeech|RemoteObjects\w*|Scxml\w*|Positioning\w*|"
    r"StateMachine\w*|VirtualKeyboard\w*|WebView\w*|WebEngine\w*|WebChannel\w*|Labs\w*|Pdf\w*|SerialPort|Sql|"
    r"WebSockets|Wayland\w*|WlShellIntegration)"
    r"(\.|_debug\.|$)")
# Chromium's helper process, its resource packs and its translations
WEBENGINE_FILES = re.compile(r"^(QtWebEngineProcess(\.exe|\.app)?|qtwebengine\w*\.pak|icudtl\.dat|v8_context_snapshot\w*\.bin|"
                             r"qtwebengine_locales|qtwebengine_devtools_resources\w*\.pak)$")


def unused(dest):
    parts = Path(dest).parts
    if len(parts) > 2 and parts[0] == "PySide6" and parts[1] == "Qt" and parts[2] == "qml":
        return True
    if "qmltooling" in parts:
        return True
    if any(WEBENGINE_FILES.match(p) for p in parts):
        return True
    # plugins that only work with the libraries dropped here
    if re.match(r"^(lib)?(qtvirtualkeyboardplugin|qpdf|qtposition_nmea)(\.|$)", parts[-1]):
        return True
    return any(UNUSED_QT.match(p) for p in parts)


a.binaries = [e for e in a.binaries if not unused(e[0])]
a.datas = [e for e in a.datas if not unused(e[0])]
pyz = PYZ(a.pure)

icon = str(ROOT / "app" / "resources" / ("icon.ico" if sys.platform == "win32" else "icon.png"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnatomyExplorer",
    console=bool(os.environ.get("AE_CONSOLE_BUILD")),
    icon=icon,
    upx=False,
    target_arch="arm64" if sys.platform == "darwin" else None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AnatomyExplorer", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APP_NAME + ".app",
        icon=icon,
        bundle_identifier="io.github.ethanprince4.anatomyexplorer" + (".experimental" if CHANNEL == "experimental" else ""),
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.medical",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
