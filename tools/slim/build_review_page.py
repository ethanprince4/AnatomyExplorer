"""Build the model-slimming review page: SLIM/review/index.html plus its images under SLIM/review/img/.
usage: build_review_page.py SLIM_DIR RENDER_DIR"""
import json, re, shutil, sys
from pathlib import Path

slim, renders = Path(sys.argv[1]), Path(sys.argv[2])
dst = slim / "review"
img = dst / "img"
if img.exists():
    shutil.rmtree(img)
img.mkdir(parents=True)
res = [json.loads(l) for l in open(slim / "results.jsonl")]
staged = {s["model"]: s for s in json.loads((slim / "staged" / "summary.json").read_text())}
counts = {}
for l in open(renders / "counts.jsonl"):
    c = json.loads(l)
    counts[(c["model"], c["tag"])] = c["triangles"]
names = {}
lib = json.loads((Path(__file__).resolve().parents[2] / "data/local_model_library/library.json").read_text())["models"]
for mid in staged:
    names[mid] = lib.get(mid, {}).get("name") or mid.replace("_", " ").title()


def safe(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text)[:60]


models = []
for mid, st in sorted(staged.items(), key=lambda kv: -(kv[1]["part_triangles_before"] - kv[1]["part_triangles_after"])):
    parts = []
    for r in sorted((r for r in res if r["model"] == mid and r.get("accepted")), key=lambda r: -r["triangles"]):
        sheet = slim / "sheets" / f"{mid}__{safe(r['part'])}.jpg"
        rel = None
        if sheet.exists():
            rel = f"img/sheet__{mid}__{safe(r['part'])}.jpg"
            shutil.copy(sheet, dst / rel)
        a = r["accepted"]
        parts.append({"name": r["part"], "before": r["triangles"], "after": a["triangles"],
                      "angle": a.get("angle_p99"), "floor": a.get("angle_p99_floor"),
                      "dist": a.get("dist_excess_edges"), "sheet": rel})
    views = {}
    for view in ("open", "close"):
        pair = {}
        for tag in ("before", "after"):
            src = renders / f"{mid}__{view}__{tag}.jpg"
            if src.exists():
                rel = f"img/{mid}__{view}__{tag}.jpg"
                shutil.copy(src, dst / rel)
                pair[tag] = rel
        if len(pair) == 2:
            views[view] = pair
    models.append({"id": mid, "name": names[mid], "parts": parts, "views": views,
                   "model_before": counts.get((mid, "before")), "model_after": counts.get((mid, "after")),
                   "mb_before": round(st["bytes_before"] / 1e6, 1), "mb_after": round(st["bytes_after"] / 1e6, 1),
                   "part_before": st["part_triangles_before"], "part_after": st["part_triangles_after"]})
failed = [{"model": names.get(r["model"]) or lib.get(r["model"], {}).get("name") or r["model"], "part": r["part"],
           "triangles": r["triangles"]}
          for r in sorted(res, key=lambda r: -r["triangles"]) if not r.get("accepted")]
data = {"models": models, "failed": failed}
template = (Path(__file__).parent / "review_template.html").read_text()
(dst / "index.html").write_text(template.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))))
total = sum(p.stat().st_size for p in img.iterdir())
print(f"{len(models)} models, {sum(len(m['parts']) for m in models)} parts, {len(failed)} not simplified, "
      f"{len(list(img.iterdir()))} images, {total / 1e6:.1f} MB")
