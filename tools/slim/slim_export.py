"""Stage A: export candidate parts of one model, cleaned and welded, for the decimation stage.
usage: slim_export.py OUT model "part" ...   (appends to OUT/manifest.jsonl)"""
import json, re, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_viewer import setup
from simplify_test_lib import clean
from PySide6.QtGui import QGuiApplication
QGuiApplication.instance() or QGuiApplication([])
out = Path(sys.argv[1]); mid = sys.argv[2]; parts = sys.argv[3:]
m, _ = setup(mid)
pos = m.vertices[:, :3].astype(np.float64)
(out / mid).mkdir(parents=True, exist_ok=True)
for name in parts:
    p = next((p for p in m.parts if p.name == name), None)
    if p is None:
        print("missing", mid, name); continue
    t = m.indices[p.first:p.first + p.count].reshape(-1, 3).astype(np.int64)
    u = np.unique(t)
    size = float(np.linalg.norm(pos[u].max(0) - pos[u].min(0)))
    v, f = clean(pos, t, size)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name)[:60]
    path = out / mid / f"{safe}.npz"
    np.savez_compressed(path, vertices=v, triangles=f)
    with open(out / "manifest.jsonl", "a") as fh:
        fh.write(json.dumps({"model": mid, "part": name, "file": str(path), "triangles": int(len(t)), "cleaned": int(len(f))}) + "\n")
    print(mid, name[:40], len(t), "->", len(f), flush=True)
