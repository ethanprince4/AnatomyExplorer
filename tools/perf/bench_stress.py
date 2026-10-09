"""One level of the model-viewer stress ramp (run by run_bench.py, one process per level).

    python bench_stress.py <base_model> <target_triangles> <out_dir> [--rss-limit-gb 16] [--frames 30]

Builds a scene of copies of the base model on a grid (tools/perf/stress_model.py), opens it in the real ModelViewport,
and measures load time, GPU memory (nvidia-smi), and frame times. A watchdog thread ends the process (recording where
it was) if its working set passes the limit. Result: <out_dir>/stress/<target>.json with ok / failure stage and reason.
"""
import argparse
import os
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.perf import perfkit as pk                                  # noqa: E402

RES = {"ok": False, "stage": "start"}


def watchdog(limit_mb, path):
    while True:
        time.sleep(0.4)
        m = pk.memory()
        RES["max_rss_seen_mb"] = max(RES.get("max_rss_seen_mb", 0), m["rss_mb"])
        if m["rss_mb"] > limit_mb:
            RES["failure"] = {"stage": RES.get("stage"), "reason": f"process working set {m['rss_mb']:.0f} MB passed the "
                                                                   f"{limit_mb:.0f} MB limit"}
            RES["memory"] = m
            pk.dump(path, RES)
            os._exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("target", type=float)
    ap.add_argument("out_dir")
    ap.add_argument("--rss-limit-gb", type=float, default=16.0)
    ap.add_argument("--frames", type=int, default=30)
    a = ap.parse_args()
    target = int(a.target)
    path = Path(a.out_dir) / "stress" / f"{target // 1_000_000}M.json"
    pk.env_setup()
    RES.update({"base": a.base, "target_triangles": target, "total_ram_mb": pk.total_ram_mb()[0]})
    threading.Thread(target=watchdog, args=(a.rss_limit_gb * 1024, path), daemon=True).start()
    t_all = time.perf_counter()
    gpu0, gpu_total = pk.gpu_used_mib()
    RES["gpu_baseline_used_mib"], RES["gpu_total_mib"] = gpu0, gpu_total
    try:
        from tools.perf import stress_model
        from tools.perf.viewer_session import ViewerSession, timed_prepare
        RES["stage"] = "prepare base"
        entry, base, load = timed_prepare(a.base)
        RES["base_prepare"] = load
        RES["stage"] = "tile"
        k = stress_model.copies_for(base, target)
        t0 = time.perf_counter()
        model, info = stress_model.tile(base, k)
        RES["scene"] = info
        RES["build_scene_s"] = round(time.perf_counter() - t0, 2)
        del base
        RES["rss_after_scene_mb"] = pk.memory()["rss_mb"]
        RES["stage"] = "open (GPU upload)"
        t0 = time.perf_counter()
        sess = ViewerSession(entry, model)
        RES["open_s"] = round(time.perf_counter() - t0, 2)
        RES["upload"] = sess.upload
        if sess.error:
            RES["failure"] = {"stage": "open", "reason": sess.error}
            raise RuntimeError(sess.error)
        err = sess.ctx.error
        RES["gl_error_after_upload"] = err
        RES["buffers"] = sess.buffer_facts()
        RES["gpu_used_after_upload_mib"] = pk.gpu_used_mib()[0]
        RES["gpu_delta_mib"] = RES["gpu_used_after_upload_mib"] - gpu0
        RES["load_total_s"] = round(time.perf_counter() - t_all, 2)
        RES["rss_after_upload_mb"] = pk.memory()["rss_mb"]
        if err != "GL_NO_ERROR":
            RES["failure"] = {"stage": "upload", "reason": f"GL error {err}"}
            raise RuntimeError(err)
        RES["stage"] = "frames"
        sess.warm(2)
        o1 = sess.orbit_run(a.frames)
        RES["orbit_wall_ms"] = pk.summarize([f["wall_ms"] for f in o1])
        RES["orbit_submit_ms"] = pk.summarize([f["submit_ms"] for f in o1])
        RES["gl_errors"] = sorted({f["gl_error"] for f in o1 if "gl_error" in f})
        RES["stage"] = "frames with timers"
        sess.attach_probe()
        o2 = sess.orbit_run(max(6, a.frames // 3), probe=True)
        RES["orbit_frame"] = pk.aggregate(o2)
        RES["gpu_used_after_frames_mib"] = pk.gpu_used_mib()[0]
        if RES["gl_errors"]:
            RES["failure"] = {"stage": "frames", "reason": f"GL error {RES['gl_errors']}"}
        else:
            RES["ok"] = True
        RES["stage"] = "done"
        sess.close()
    except Exception as exc:
        RES.setdefault("failure", {"stage": RES.get("stage"), "reason": f"{type(exc).__name__}: {exc}"})
        RES["trace"] = traceback.format_exc()[-1200:]
    RES["memory"] = pk.memory()
    RES["wall_s"] = round(time.perf_counter() - t_all, 1)
    pk.dump(path, RES)
    print(f"stress {target // 1_000_000}M: ok={RES['ok']} {RES.get('failure', '')} {RES['wall_s']}s", flush=True)
    os._exit(0 if RES["ok"] else 1)


if __name__ == "__main__":
    main()
