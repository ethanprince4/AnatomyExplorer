"""Compare two reference folders made by make_reference.py (or run_bench.py).

    python compare_refs.py <folder_a> <folder_b> [--out compare] [--threshold 8]

For every <model>/<state>.png present in both: mean absolute difference (0..255, over RGB), percent of pixels where any
channel differs by more than the threshold (default 8/255), maximum difference, and pick agreement (percent of the
16x10 sample points that pick the same item id). Writes <out>.json and <out>.md next to --out (default: inside
folder_b). Exit code 0 always; the numbers are the result.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np


def load_png(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def compare_pair(pa, pb, threshold):
    a, b = load_png(pa), load_png(pb)
    if a.shape != b.shape:
        return {"error": f"size differs {a.shape} vs {b.shape}"}
    d = np.abs(a - b)
    px = d.max(axis=2)
    return {"mean_abs_diff": round(float(d.mean()), 4),
            "pct_pixels_over_threshold": round(float((px > threshold).mean() * 100.0), 4),
            "max_diff": int(d.max()), "size": [int(a.shape[1]), int(a.shape[0])]}


def pick_agreement(ja, jb):
    try:
        a = json.loads(Path(ja).read_text(encoding="utf-8"))["picks"]["ids"]
        b = json.loads(Path(jb).read_text(encoding="utf-8"))["picks"]["ids"]
    except (OSError, KeyError, ValueError):
        return None
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return None
    return round(float((a == b).mean() * 100.0), 2)


def compare_folders(fa, fb, threshold=8):
    fa, fb = Path(fa), Path(fb)
    rows, missing = [], []
    for pa in sorted(fa.glob("*/*.png")):
        rel = pa.relative_to(fa)
        pb = fb / rel
        if not pb.exists():
            missing.append(str(rel))
            continue
        row = {"model": rel.parts[0], "state": rel.stem}
        row.update(compare_pair(pa, pb, threshold))
        row["pick_agreement_pct"] = pick_agreement(pa.with_suffix(".json"), pb.with_suffix(".json"))
        rows.append(row)
    only_b = [str(p.relative_to(fb)) for p in sorted(fb.glob("*/*.png")) if not (fa / p.relative_to(fb)).exists()]
    return {"a": str(fa), "b": str(fb), "threshold": threshold, "images": rows,
            "missing_in_b": missing, "missing_in_a": only_b}


def markdown(res):
    lines = [f"# Reference comparison", "", f"A: `{res['a']}`", f"B: `{res['b']}`",
             f"Threshold: {res['threshold']}/255 on any channel", "",
             "| model | state | mean abs diff | % px > thr | max diff | pick agreement % |", "|---|---|---|---|---|---|"]
    for r in res["images"]:
        if "error" in r:
            lines.append(f"| {r['model']} | {r['state']} | {r['error']} | | | {r['pick_agreement_pct']} |")
        else:
            lines.append(f"| {r['model']} | {r['state']} | {r['mean_abs_diff']} | {r['pct_pixels_over_threshold']} | "
                         f"{r['max_diff']} | {r['pick_agreement_pct']} |")
    ok = [r for r in res["images"] if "error" not in r]
    if ok:
        lines += ["", f"Images compared: {len(ok)}. Worst mean diff {max(r['mean_abs_diff'] for r in ok)}, "
                      f"worst % over threshold {max(r['pct_pixels_over_threshold'] for r in ok)}, "
                      f"lowest pick agreement {min((r['pick_agreement_pct'] for r in ok if r['pick_agreement_pct'] is not None), default='n/a')}."]
    if res["missing_in_b"] or res["missing_in_a"]:
        lines += ["", f"Only in A: {res['missing_in_b']}", f"Only in B: {res['missing_in_a']}"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", default=None, help="path prefix for <out>.json / <out>.md")
    ap.add_argument("--threshold", type=int, default=8)
    args = ap.parse_args(argv)
    res = compare_folders(args.a, args.b, args.threshold)
    out = Path(args.out) if args.out else Path(args.b) / "compare"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    out.with_suffix(".md").write_text(markdown(res), encoding="utf-8")
    ok = [r for r in res["images"] if "error" not in r]
    print(f"compared {len(ok)} images; worst mean diff {max((r['mean_abs_diff'] for r in ok), default=0)}; "
          f"lowest pick agreement {min((r['pick_agreement_pct'] for r in ok if r['pick_agreement_pct'] is not None), default='n/a')}"
          f" -> {out.with_suffix('.md')}")
    return res


if __name__ == "__main__":
    main()
