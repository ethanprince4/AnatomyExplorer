"""Model-viewer benchmark for ONE library model (run by run_bench.py, one process per model).

    python bench_models.py <model_id> <out_dir> [--quick]

Writes <out_dir>/models/<model_id>.json: load timings, buffer facts, settled frame, orbit run (wall ms with
ctx.finish(), plus a second orbit with GL counters and per-pass GPU timers), settle-after-drag frame (label
recompute), hover pick, light-follow check.
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.perf import perfkit as pk                                  # noqa: E402


def run(model_id, out_dir, quick=False):
    pk.env_setup()
    from tools.perf.viewer_session import ViewerSession, model_stats, timed_prepare
    res = {"model": model_id, "ok": False}
    try:
        entry, model, load = timed_prepare(model_id)
        res["load"] = load
        res["stats"] = model_stats(model)
        sess = ViewerSession(entry, model)
        if sess.error:
            res["error"] = sess.error
            return res
        res["load"].update(sess.upload)
        res["load"]["first_frame_incl_context_s"] = round(sess.first_grab_s, 3)
        res["load"]["rss_after_upload_mb"] = pk.memory()["rss_mb"]
        res["buffers"] = sess.buffer_facts()
        res["gl"] = {"renderer": sess.ctx.info.get("GL_RENDERER"), "version": sess.ctx.info.get("GL_VERSION")}
        n_orbit = 24 if quick else 120
        sess.warm(4)

        # settled frame: a repaint with nothing moving (no probe, then with counters)
        res["settled_clean"] = pk.summarize([sess.paint()["wall_ms"] for _ in range(10)])
        sess.attach_probe()
        settled = [sess.paint(probe=True) for _ in range(6)]
        res["settled_frame"] = pk.aggregate(settled)
        res["settled_wall_ms_probe"] = pk.summarize([f["wall_ms"] for f in settled])

        # orbit run 1: no probe, the wall time the user would see (finish() included)
        sess.detach_probe()
        o1 = sess.orbit_run(n_orbit)
        res["orbit_wall_ms"] = pk.summarize([f["wall_ms"] for f in o1])
        res["orbit_submit_ms"] = pk.summarize([f["submit_ms"] for f in o1])
        res["orbit_wall_series_ms"] = [round(f["wall_ms"], 2) for f in o1]
        res["gl_errors"] = sorted({f["gl_error"] for f in o1 if "gl_error" in f})

        # orbit run 2: counters and per-pass GPU timers
        sess.attach_probe()
        o2 = sess.orbit_run(n_orbit, probe=True)
        res["orbit_frame"] = pk.aggregate(o2)
        res["orbit_wall_ms_probe"] = pk.summarize([f["wall_ms"] for f in o2])
        res["orbit_gpu_total_ms"] = pk.summarize([f["gpu_total_ms"] for f in o2])
        res["orbit_gpu_by_pass_p95"] = {k: round(pk.pct([f["gpu_ms"].get(k, 0.0) for f in o2], 0.95), 3)
                                       for k in sorted({k for f in o2 for k in f["gpu_ms"]})}
        res["lights"] = sess.light_follow_report()

        # settle after a drag: the labels are recomputed here (labels off, then the Labels toggle on)
        a, b = sess.settle(probe=True)
        res["after_drag_labels_off"] = {"first_frame": a, "idle_frame": b}
        sess.w.labels_on = True
        sess.w.invalidate_labels()
        sess.orbit_run(3)
        a, b = sess.settle(probe=True)
        res["after_drag_labels_on"] = {"first_frame": a, "idle_frame": b,
                                       "labels_found": len(sess.w.label_items)}
        # many models mark no item as labelled; force every item labelled (bench only, restored) to cost the label path
        saved = [it.label for it in model.items]
        for it in model.items:
            it.label = True
        sess.w.invalidate_labels()
        sess.orbit_run(3)
        a, b = sess.settle(probe=True)
        res["after_drag_labels_forced"] = {"first_frame": a, "idle_frame": b,
                                           "labels_found": len(sess.w.label_items)}
        for it, v in zip(model.items, saved):
            it.label = v
        sess.w.labels_on = False
        sess.w.invalidate_labels()

        # hover pick (what a mouse move triggers every 30 ms when not dragging)
        picks = sess.pick_samples(10, probe=True)
        res["hover_pick"] = {"wall_ms": pk.summarize([p["wall_ms"] for p in picks]),
                             "readbacks_per_pick": pk.med([p.get("readbacks") for p in picks]),
                             "readback_ms": pk.med([p.get("readback_ms") for p in picks])}
        res["shadows_enabled_in_app"] = bool(sess.w.rsettings.shadows)
        res["gpu_mem"] = {"used_mib": pk.gpu_used_mib()[0]}
        res["memory"] = pk.memory()
        res["ok"] = True
        sess.close()
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["trace"] = traceback.format_exc()[-1500:]
    finally:
        res["memory"] = pk.memory()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id")
    ap.add_argument("out_dir")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    t0 = time.perf_counter()
    res = run(a.model_id, a.out_dir, a.quick)
    res["wall_s"] = round(time.perf_counter() - t0, 1)
    pk.dump(Path(a.out_dir) / "models" / f"{a.model_id}.json", res)
    print(f"{a.model_id}: ok={res['ok']} {res.get('error', '')} {res['wall_s']}s", flush=True)


if __name__ == "__main__":
    main()
