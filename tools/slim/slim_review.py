"""Stage C: before/after sheets (whole part and two close-ups, same camera and light) for every accepted part of the
given models, as JPEGs in OUT/sheets.  usage: slim_review.py OUT model ..."""
import json, math, re, sys
from pathlib import Path
import numpy as np
import moderngl
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_lib import Sheet

out = Path(sys.argv[1])
res = [json.loads(l) for l in open(out / "results.jsonl")]
sheet = Sheet()
for mid in sys.argv[2:]:
    for r in res:
        if r["model"] != mid or "slim_file" not in r:
            continue
        o = np.load(r["file"]); s = np.load(r["slim_file"])
        safe = re.sub(r"[^A-Za-z0-9]+", "_", r["part"])[:60]
        dst = out / "sheets" / f"{mid}__{safe}.jpg"
        dst.parent.mkdir(exist_ok=True)
        a = r["accepted"]
        sheet.render(o["vertices"], o["triangles"], s["vertices"], s["triangles"],
                     f"{mid} / {r['part']}:  original {r['triangles']:,}  ->  copy {a['triangles']:,} triangles "
                     f"({100 * a['triangles'] / r['triangles']:.0f}%)", dst)
        print("sheet", dst.name, flush=True)
