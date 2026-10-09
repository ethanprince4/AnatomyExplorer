"""Build <run>/summary.md (one table per section) from the raw JSON a run produced.

    python summary.py <run_dir> [--baseline <other_run_dir>]
"""
import argparse
import json
from pathlib import Path


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def f(v, nd=1):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:,.{nd}f}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def short_pass(k):
    return k.replace("t.fbo_", "").replace("fbo_", "")


def models_of(run):
    out = {}
    for p in sorted((Path(run) / "models").glob("*.json")):
        d = load(p)
        if d:
            out[d["model"]] = d
    return out


def build(run, baseline=None):
    run = Path(run)
    L = [f"# Renderer benchmark: {run.name}", ""]
    meta = load(run / "run.json") or {}
    if meta:
        L += [f"Settings: {meta.get('settings', '')}", f"GPU: {meta.get('gpu', '')}", f"Started: {meta.get('started', '')}", ""]
    ms = models_of(run)
    good = {k: v for k, v in ms.items() if v.get("ok")}
    bad = {k: v for k, v in ms.items() if not v.get("ok")}
    order = sorted(good, key=lambda k: -good[k]["stats"]["triangles"])

    L += ["## 1. Load (app prepare chain: decode, prepare incl. lod.build, GPU upload)", ""]
    rows = []
    for k in order:
        d = good[k]
        s, l, b = d["stats"], d["load"], d["buffers"]
        rows.append([k, f(s["triangles"]), f(s["vertices"]), s["parts"], s["items"], f"{s['lod_parts']} x {s['lod_levels_per_part']}",
                     f(b["bytes_per_vertex"]), f(l["decode_s"], 2), f(l["prepare_other_s"], 2), f(l["lod_build_s"], 2),
                     f(l.get("upload_s"), 2), f(d["memory"]["peak_rss_mb"], 0),
                     f((l.get("gpu_used_after_mib") or 0) - (l.get("gpu_used_before_mib") or 0), 0)])
    L += table(["model", "triangles", "vertices", "parts", "items", "LOD parts x levels", "B/vertex", "decode s",
                "prepare s (excl. decode, LOD)", "lod.build s", "upload s", "peak RSS MB", "GPU MiB (upload)"], rows)
    if bad:
        L += ["", "Failed: " + "; ".join(f"{k}: {v.get('error', '?')}" for k, v in bad.items())]

    L += ["", "## 2. Frames at 2560x1600, DPR 2 (model viewer; wall ms includes ctx.finish())", ""]
    rows = []
    for k in order:
        d = good[k]
        o, fr = d["orbit_wall_ms"], d["orbit_frame"]
        rows.append([k, f(d["settled_clean"]["median"]), f(o["median"]), f(o["p95"]), f(o["max"]), f(d["orbit_submit_ms"]["median"]),
                     f(fr["gpu_total_ms"]), f(fr["draws_total"], 0), f(fr["model_draws"], 0), f(fr["geometry_passes"], 0),
                     f(fr["tris_submitted"] / 1e6, 2), f(fr["readbacks"], 0), f(fr["shadow_rerendered"], 0),
                     d["buffers"]["msaa_samples_used"]])
    L += table(["model", "settled ms", "orbit median ms", "orbit p95", "orbit max", "CPU submit ms", "GPU ms (sum of passes)",
                "draw calls", "model draws", "geometry passes", "Mtri submitted", "readbacks/frame", "frames w/ shadow pass (of 120)", "MSAA"], rows)

    passes = sorted({p for k in good for p in good[k]["orbit_frame"]["gpu_ms"]})
    L += ["", "## 3. GPU ms per pass during the orbit (median over frames)", ""]
    rows = [[k] + [f(good[k]["orbit_frame"]["gpu_ms"].get(p), 2) for p in passes] for k in order]
    L += table(["model"] + [short_pass(p) for p in passes], rows)

    L += ["", "## 4. Settle after a drag, hover pick, labels (wall ms; readbacks)", ""]
    rows = []
    for k in order:
        d = good[k]
        a0 = d["after_drag_labels_off"]["first_frame"]
        a1 = d["after_drag_labels_forced"]["first_frame"]
        hp = d["hover_pick"]
        rows.append([k, f(a0["wall_ms"]), f(a0["readbacks"], 0), f(a1["wall_ms"]), f(a1["readbacks"], 0),
                     f(a1["readback_bytes"] / 1e6, 2), d["after_drag_labels_forced"]["labels_found"],
                     f(hp["wall_ms"]["median"], 2), f(hp["readbacks_per_pick"], 0)])
    L += table(["model", "settle ms (labels off)", "readbacks", "settle ms (labels on, all items labelled)", "readbacks", "readback MB",
                "labels found", "hover pick ms", "readbacks/pick"], rows)

    L += ["", "## 5. Lights and shadows", ""]
    rows = []
    for k in order[:3]:
        li = good[k].get("lights") or {}
        rows.append([k, li.get("yaw_change_deg"), li.get("key_light_world_dir_a"), li.get("key_light_world_dir_b"),
                     li.get("key_light_angle_between_deg"), li.get("lights_follow_camera"), good[k].get("shadows_enabled_in_app")])
    L += table(["model", "camera yaw change (deg)", "key light world dir A", "dir B", "light turned (deg)", "lights follow camera",
                "shadows enabled in app"], rows)
    L += ["", "Shadow maps are disabled by the viewport (`app/viewer/viewport.py:106` sets `rsettings.shadows = False`), so the shadow pass "
              "never runs in the app; `tools/slim/bench_viewer.py` used the renderer default (shadows on).", ""]

    at = load(run / "atlas.json")
    L += ["## 6. Atlas (app/viewport.py + app/renderer.py, Z-Anatomy data)", ""]
    if at and at.get("ok"):
        fa, ld = at["facts"], at["load"]
        L += [f"Structures {fa['structures']}, triangles {fa['triangles']:,}, vertices {fa['vertices']:,}, {fa['bytes_per_vertex']} B/vertex, "
              f"VBO {fa['vbo_mib']} MiB, IBO {fa['ibo_mib']} MiB, render {fa['render_size']}, {fa['msaa']}.",
              f"Load: dataset {ld['dataset_s']} s, geometry decode {ld.get('load_geometry_s')} s, upload {ld.get('upload_s')} s, "
              f"peak RSS {at['memory']['peak_rss_mb']} MB.", ""]
        rows = []
        for tag, key in (("default settings", "default_settings"), ("structure labels on", "structure_labels_on")):
            d = at[key]
            fr = d["orbit_frame"]
            rows.append([tag, f(d["settled_clean"]["median"]), f(d["orbit_wall_ms"]["median"]), f(d["orbit_wall_ms"]["p95"]),
                         f(fr["gpu_total_ms"]), f(fr["draws_total"], 0), f(fr["model_draws"], 0), f(fr["geometry_passes"], 0),
                         f(fr["readbacks"], 0), f(fr["readback_ms"], 2), f(d["after_drag"]["first_frame"]["readbacks"], 0),
                         f(d["hover_pick"]["wall_ms"]["median"], 2)])
        L += table(["scenario", "settled ms", "orbit median ms", "orbit p95", "GPU ms", "draw calls", "model draws", "geometry passes",
                    "readbacks/frame", "readback ms/frame", "readbacks first frame after drag", "hover pick ms"], rows)
        ap = sorted({p for key in ("default_settings", "structure_labels_on") for p in at[key]["orbit_frame"]["gpu_ms"]})
        L += ["", "Atlas GPU ms per pass (orbit median):", ""]
        L += table(["scenario"] + ap, [[t] + [f(at[key]["orbit_frame"]["gpu_ms"].get(p), 2) for p in ap]
                                       for t, key in (("default", "default_settings"), ("labels on", "structure_labels_on"))])
    else:
        L += [f"Not measured: {(at or {}).get('error', 'no atlas.json')}"]

    L += ["", "## 7. Stress ramp (model viewer, copies of one model on a grid)", ""]
    st = [load(p) for p in sorted((run / "stress").glob("*.json"), key=lambda p: int(p.stem[:-1]))] if (run / "stress").exists() else []
    if st:
        rows = []
        for d in st:
            sc, up = d.get("scene", {}), d.get("upload", {})
            fr = d.get("orbit_frame", {})
            rows.append([f"{d['target_triangles'] // 1_000_000}M", f(sc.get("triangles")), sc.get("copies"), sc.get("parts"),
                         f(d.get("build_scene_s"), 1), f(up.get("upload_s"), 1), f(d.get("load_total_s"), 1),
                         f(d.get("buffers", {}).get("bytes_per_vertex")), f(d.get("buffers", {}).get("vbo_mib"), 0),
                         f(d.get("buffers", {}).get("ibo_mib"), 0), f(d.get("gpu_delta_mib"), 0),
                         f((d.get("orbit_wall_ms") or {}).get("median")), f(fr.get("gpu_total_ms")), f(fr.get("draws_total"), 0),
                         f(d.get("memory", {}).get("peak_rss_mb"), 0), "ok" if d.get("ok") else "FAILED"])
        L += table(["target", "triangles", "copies", "parts", "build scene s", "upload s", "load total s", "B/vertex", "VBO MiB",
                    "IBO MiB", "GPU MiB used (delta)", "orbit median ms", "GPU ms", "draw calls", "peak RSS MB", "result"], rows)
        for d in st:
            if not d.get("ok"):
                L += ["", f"Failure at {d['target_triangles'] // 1_000_000}M: stage '{d.get('failure', {}).get('stage')}': "
                          f"{d.get('failure', {}).get('reason')}; peak RSS {d.get('memory', {}).get('peak_rss_mb')} MB; "
                          f"GPU used at the time {d.get('gpu_used_after_upload_mib')} of {d.get('gpu_total_mib')} MiB; base model {d.get('base')}."]
        L += ["", f"Base model for the copies: {st[0].get('base')}; scene items are capped at 4096 by SceneState."]
    else:
        L += ["Not run."]

    L += ["", "## 8. Reference set", ""]
    refs = sorted((run / "reference").glob("*/index.json")) if (run / "reference").exists() else []
    rows = []
    for p in refs:
        d = load(p)
        for s, v in d["states"].items():
            rows.append([d["model"], s, v["mean_rgb"], v["distinct_ids"]])
        for s in d.get("states_missing", []):
            rows.append([d["model"], s, "n/a for this model", ""])
    L += table(["model", "state", "mean RGB", "distinct ids in 16x10 pick grid"], rows) if rows else ["Not run."]
    cmp = load(run / "reference_selfcheck.json")
    if cmp:
        ok = [r for r in cmp["images"] if "error" not in r]
        L += ["", f"Self-check (two renders of the same states, same machine): {len(ok)} images, worst mean abs diff "
                  f"{max((r['mean_abs_diff'] for r in ok), default=0)}, worst % pixels > {cmp['threshold']}/255 "
                  f"{max((r['pct_pixels_over_threshold'] for r in ok), default=0)}, lowest pick agreement "
                  f"{min((r['pick_agreement_pct'] for r in ok if r['pick_agreement_pct'] is not None), default='n/a')}%."]

    if baseline:
        bm = models_of(baseline)
        L += ["", f"## 9. Repeat check against {Path(baseline).name} (target: within about 5 percent)", ""]
        rows = []
        for k in order:
            if k not in bm or not bm[k].get("ok"):
                continue
            a, b = bm[k], good[k]
            def pc(x, y):
                return "-" if not x else f"{(y - x) / x * 100:+.1f}%"
            fa, fb = a["orbit_frame"], b["orbit_frame"]
            g = fb["gpu_ms"]
            rows.append([k, f(a["orbit_wall_ms"]["median"]), f(b["orbit_wall_ms"]["median"]),
                         pc(a["orbit_wall_ms"]["median"], b["orbit_wall_ms"]["median"]),
                         f(fa["gpu_total_ms"]), f(fb["gpu_total_ms"]), pc(fa["gpu_total_ms"], fb["gpu_total_ms"]),
                         pc(a["orbit_wall_ms_probe"]["median"], b["orbit_wall_ms_probe"]["median"]),
                         "yes" if fa["draws_total"] == fb["draws_total"] and fa["readbacks"] == fb["readbacks"] else "NO"])
        L += table(["model", "orbit ms (baseline)", "orbit ms (repeat)", "diff", "GPU ms (baseline)", "GPU ms (repeat)", "diff",
                    "orbit ms with timers diff", "same draw calls and readbacks"], rows)
    (run / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return run / "summary.md"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--baseline", default=None)
    a = ap.parse_args()
    print(build(a.run, a.baseline))
