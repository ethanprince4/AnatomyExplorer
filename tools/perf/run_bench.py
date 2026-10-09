"""Renderer benchmark harness: one command, sequential. Run it under the shared GPU lock:

    python <scratch>/tools/gpu_lock.py <repo>/.venv/Scripts/python.exe <repo>/tools/perf/run_bench.py --run baseline \
        --out-root <scratch>/bench [--models a,b,c | heaviest:3:<other_run>] [--quick] [--skip-stress] [--skip-atlas]
        [--skip-reference] [--stress-levels 25,50,100,150,250] [--stress-base <model>] [--rss-limit-gb 16]

Sections: model viewer per model (load, frames, orbit, GPU timers, counters, hover, labels, lights), atlas, stress
ramp (stops at the first failure), reference views + a determinism self-check, summary.md + raw JSON.
Every measured part runs in its own child process (peak RSS and failures stay isolated). Nothing under data/ is
written; models are only read.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from tools.perf import perfkit as pk                                  # noqa: E402

REF_MODELS = ["kidney_nephron", "pancreas", "eyeball", "whole_heart", "tooth", "thin_skin"]


def child(args, log, timeout):
    """Run a child process; returns (returncode, seconds)."""
    t0 = time.perf_counter()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with open(log, "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.call([sys.executable, *map(str, args)], stdout=fh, stderr=subprocess.STDOUT,
                                 cwd=str(ROOT), env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            rc = -999
    return rc, time.perf_counter() - t0


def library_ids():
    sys.path.insert(0, str(ROOT))
    out = subprocess.run([sys.executable, "-c",
                          "import sys;sys.path.insert(0,r'%s');from PySide6.QtGui import QGuiApplication as G;G([]);"
                          "from app.viewer.catalog import load_catalog;print(' '.join(load_catalog()))" % ROOT],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout.split()
    return out


def pick_models(spec, out_root):
    if spec.startswith("heaviest:"):
        _, n, other = spec.split(":", 2)
        runs = Path(other) if Path(other).exists() else Path(out_root) / other
        rows = []
        for p in (runs / "models").glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("ok"):
                rows.append((d["stats"]["triangles"], d["model"]))
        return [m for _, m in sorted(rows, reverse=True)[:int(n)]]
    if spec == "all":
        return library_ids()
    return [s for s in spec.split(",") if s]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--models", default="all")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--skip-stress", action="store_true")
    ap.add_argument("--skip-atlas", action="store_true")
    ap.add_argument("--skip-reference", action="store_true")
    ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--stress-levels", default="25,50,100,150,250", help="millions of triangles")
    ap.add_argument("--stress-base", default=None, help="model to copy (default: the heaviest static model measured)")
    ap.add_argument("--rss-limit-gb", type=float, default=16.0)
    ap.add_argument("--baseline", default=None, help="another run (name or folder) to compare repeat numbers against")
    ap.add_argument("--model-timeout", type=int, default=1500)
    a = ap.parse_args()

    out = Path(a.out_root) / a.run
    (out / "logs").mkdir(parents=True, exist_ok=True)
    used, total = pk.gpu_used_mib()
    ram_total, ram_free = pk.total_ram_mb()
    (out / "run.json").write_text(json.dumps({
        "settings": "2560x1600 physical px, device pixel ratio 2 (QT_SCREEN_SCALE_FACTORS=2), default user settings, "
                    "real ModelViewport / Viewport widgets", "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gpu": f"{used}/{total} MiB used at start (other agents may share the GPU)", "args": vars(a),
        "ram_total_mb": ram_total, "ram_free_mb": ram_free, "quick": a.quick}, indent=1), encoding="utf-8")
    models = pick_models(a.models, a.out_root)
    print(f"[run {a.run}] {len(models)} models -> {out}", flush=True)
    t_all = time.perf_counter()

    if not a.skip_models:
        for i, mid in enumerate(models, 1):
            rc, sec = child([HERE / "bench_models.py", mid, out] + (["--quick"] if a.quick else []),
                            out / "logs" / f"model_{mid}.log", a.model_timeout)
            ok = (out / "models" / f"{mid}.json").exists()
            print(f"  model {i}/{len(models)} {mid}: rc={rc} json={'yes' if ok else 'NO'} {sec:.0f}s", flush=True)

    if not a.skip_atlas:
        rc, sec = child([HERE / "bench_atlas.py", out] + (["--quick"] if a.quick else []), out / "logs" / "atlas.log", 1800)
        print(f"  atlas: rc={rc} {sec:.0f}s", flush=True)

    if not a.skip_stress:
        base = a.stress_base
        if base is None:
            best = (0, "kidney_nephron")
            for p in (out / "models").glob("*.json"):
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("ok") and not d["stats"]["animated"] and d["buffers"]["bytes_per_vertex"] <= 24.5:
                    best = max(best, (d["stats"]["triangles"], d["model"]))
            base = best[1]
        print(f"  stress base model: {base}", flush=True)
        for lvl in (float(x) for x in a.stress_levels.split(",")):
            target = int(lvl * 1_000_000)
            rc, sec = child([HERE / "bench_stress.py", base, target, out, "--rss-limit-gb", a.rss_limit_gb],
                            out / "logs" / f"stress_{int(lvl)}M.log", 3600)
            print(f"  stress {int(lvl)}M: rc={rc} {sec:.0f}s", flush=True)
            if rc != 0:
                print("  stress ramp stopped at the first failure", flush=True)
                break

    if not a.skip_reference:
        ref_models = [m for m in REF_MODELS if m in set(library_ids())]
        for tag in ("reference", "reference_repeat"):
            for mid in ref_models:
                rc, sec = child([HERE / "make_reference.py", "model", mid, out / tag], out / "logs" / f"{tag}_{mid}.log", 1800)
                print(f"  {tag} {mid}: rc={rc} {sec:.0f}s", flush=True)
            rc, sec = child([HERE / "make_reference.py", "atlas", out / tag], out / "logs" / f"{tag}_atlas.log", 1800)
            print(f"  {tag} atlas: rc={rc} {sec:.0f}s", flush=True)
            if a.quick:
                break
        if (out / "reference_repeat").exists():
            from tools.perf import compare_refs
            res = compare_refs.compare_folders(out / "reference", out / "reference_repeat")
            (out / "reference_selfcheck.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
            (out / "reference_selfcheck.md").write_text(compare_refs.markdown(res), encoding="utf-8")

    from tools.perf import summary
    base_dir = None
    if a.baseline:
        base_dir = Path(a.baseline) if Path(a.baseline).exists() else Path(a.out_root) / a.baseline
    print(f"[run {a.run}] done in {time.perf_counter() - t_all:.0f}s -> {summary.build(out, base_dir)}", flush=True)


if __name__ == "__main__":
    main()
