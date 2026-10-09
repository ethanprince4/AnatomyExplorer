"""Atlas (Z-Anatomy) benchmark: python bench_atlas.py <out_dir> [--quick]. Writes <out_dir>/atlas.json."""
import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.perf import perfkit as pk                                  # noqa: E402


def scenario(sess, n_orbit):
    """Settled frame, orbit (wall, then counters and GPU timers), settle after drag, hover pick."""
    out = {}
    sess.warm(4)
    out["settled_clean"] = pk.summarize([sess.paint()["wall_ms"] for _ in range(10)])
    sess.attach_probe()
    settled = [sess.paint(probe=True) for _ in range(6)]
    out["settled_frame"] = pk.aggregate(settled)
    sess.detach_probe()
    o1 = sess.orbit_run(n_orbit)
    out["orbit_wall_ms"] = pk.summarize([f["wall_ms"] for f in o1])
    out["orbit_submit_ms"] = pk.summarize([f["submit_ms"] for f in o1])
    out["orbit_wall_series_ms"] = [round(f["wall_ms"], 2) for f in o1]
    out["gl_errors"] = sorted({f["gl_error"] for f in o1 if "gl_error" in f})
    sess.attach_probe()
    o2 = sess.orbit_run(n_orbit, probe=True)
    out["orbit_frame"] = pk.aggregate(o2)
    out["orbit_wall_ms_probe"] = pk.summarize([f["wall_ms"] for f in o2])
    out["orbit_gpu_total_ms"] = pk.summarize([f["gpu_total_ms"] for f in o2])
    out["orbit_gpu_by_pass_p95"] = {k: round(pk.pct([f["gpu_ms"].get(k, 0.0) for f in o2], 0.95), 3)
                                   for k in sorted({k for f in o2 for k in f["gpu_ms"]})}
    a = sess.paint(probe=True)
    b = sess.paint(probe=True)
    out["after_drag"] = {"first_frame": a, "idle_frame": b}
    picks = sess.pick_samples(10, probe=True)
    out["hover_pick"] = {"wall_ms": pk.summarize([p["wall_ms"] for p in picks]),
                         "readbacks_per_pick": pk.med([p.get("readbacks") for p in picks])}
    sess.detach_probe()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    pk.env_setup()
    from tools.perf.atlas_session import AtlasSession
    n = 24 if a.quick else 120
    res = {"ok": False}
    t0 = time.perf_counter()
    try:
        sess = AtlasSession()
        res["load"] = sess.load
        res["facts"] = sess.facts()
        res["gl"] = {"renderer": sess.ctx.info.get("GL_RENDERER"), "version": sess.ctx.info.get("GL_VERSION")}
        res["default_settings"] = scenario(sess, n)
        res["structure_labels_default"] = bool(sess.settings.get("show_structure_labels"))
        # the user turns "structure labels" on: up to max_landmarks x3 single-pixel picks per paint
        sess.settings["show_structure_labels"] = True
        sess.state.render_changed.emit()
        res["structure_labels_on"] = scenario(sess, n)
        sess.close()
        res["gpu_mem_used_mib"] = pk.gpu_used_mib()[0]
        res["ok"] = True
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
        res["trace"] = traceback.format_exc()[-1500:]
    res["memory"] = pk.memory()
    res["wall_s"] = round(time.perf_counter() - t0, 1)
    pk.dump(Path(a.out_dir) / "atlas.json", res)
    print(f"atlas: ok={res['ok']} {res.get('error', '')} {res['wall_s']}s", flush=True)


if __name__ == "__main__":
    main()
