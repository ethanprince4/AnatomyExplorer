"""Q5: run the spec's own unused() filter against the paths the wgpu and rendercanvas hooks would add."""
import re, sys
from pathlib import Path
src = Path(sys.argv[1]).read_text(encoding="utf-8")
a = src.index("UNUSED_QT = re.compile"); b = src.index("a.binaries = [e for e")
ns = {"re": re, "Path": Path}
exec(src[a:b], ns)
for dest in ["wgpu/resources/wgpu_native-release.dll", "wgpu/resources/webgpu.idl", "wgpu/resources/wgpu.h",
             "wgpu/backends/wgpu_native/_api.py", "rendercanvas/qt.py", "rendercanvas/contexts/wgpucontext.py",
             "PySide6/Qt/plugins/platforms/qwindows.dll", "PySide6/Qt6OpenGL.dll"]:
    print(f"{dest:60s} dropped={ns['unused'](dest)}")
