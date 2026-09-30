"""Read-only SDK/toolchain inventory; never downloads, configures or builds Qt."""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import PySide6
from PySide6.QtCore import QLibraryInfo, qVersion


def inspect():
    version = qVersion()
    qt = Path(PySide6.__file__).resolve().parent / "Qt"
    candidates = [qt]
    for name in ("QTDIR", "Qt6_DIR"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))
    candidates.extend((Path("/opt/homebrew/opt/qt"), Path("/usr/local/opt/qt")))
    configs = []
    for prefix in candidates:
        for path in (prefix / "lib/cmake/Qt6Core/Qt6CoreConfigVersion.cmake",
                     prefix / "lib/cmake/Qt6Core/Qt6CoreConfigVersionImpl.cmake",
                     prefix.parent / "Qt6Core/Qt6CoreConfigVersion.cmake"):
            if path.is_file():
                match = re.search(r'set\(PACKAGE_VERSION\s+"?([0-9.]+)', path.read_text(errors="replace"))
                configs.append({"matching_version": bool(match and match.group(1) == version)})
    headers = Path(QLibraryInfo.path(QLibraryInfo.HeadersPath))
    private_header = (headers / "QtGui" / version / "QtGui/private/qaccessiblecache_p.h").is_file()
    framework_headers = (qt / "lib/QtGui.framework/Headers" / version / "QtGui/private/qaccessiblecache_p.h").is_file()
    clang = shutil.which("xcrun") is not None
    if clang:
        result = subprocess.run(["xcrun", "--find", "clang++"], capture_output=True, timeout=10)
        clang = result.returncode == 0
    return {"schema": 1, "qt": version, "pyside": PySide6.__version__,
            "matching_qt_cmake_config_found": any(row["matching_version"] for row in configs),
            "qt_private_accessibility_headers_found": private_header or framework_headers,
            "cmake_available": shutil.which("cmake") is not None,
            "ninja_available": shutil.which("ninja") is not None,
            "apple_clang_available": clang,
            "plugin_build_attempted": False,
            "paths_or_credentials_recorded": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = inspect()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
