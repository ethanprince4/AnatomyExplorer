"""Visibility pass check: WgpuRenderer against the GL Renderer, and the visibility pass timing.

  python tools/perf/gpu/visbuf_check.py compare [--models eyeball kidney_nephron pancreas] [--states default cut_plane]
  python tools/perf/gpu/visbuf_check.py timing  [--adapter "RTX 3080"] [--model pancreas] [--frames 40]
  python tools/perf/gpu/visbuf_check.py order   (draw order and LOD levels against the GL Renderer, per model)

compare: the same model, camera and state are rendered by the widget's GL renderer and by WgpuRenderer. Per pixel centre
the item ids and the linear view depths are compared. A disagreeing pixel is explained as
  cap    GL drew a cut face there (flag bit 2; the wgpu port has no caps yet),
  tie    both depths are within a few quanta of GL's 24-bit window depth (an equal-depth tie, order dependent),
  fall   GL has background, wgpu an item (a sampled triangle contains the centre by the 1e-5 edge tolerance, GL's does not),
  miss   GL has an item that no MSAA sample sees (wgpu: background), or both are items and GL's is the nearer one: its
         triangle contains the centre but none of the MSAA samples,
  edge   the pixel lies on an id boundary of the GL picture (a triangle edge or silhouette through the centre),
  other  none of the above (reported with coordinates).
timing: GPU timestamps around the visibility render pass only (no CPU readback inside the pass). Run it under
  python <S>/tools/gpu_lock.py python tools/perf/gpu/visbuf_check.py timing --adapter ...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TIE_QUANTA = 4.0          # a tie is a depth difference of at most this many 2^-24 window-depth steps


# ------------------------------------------------------------------------------------------------ device
def make_gpu(adapter_substr=None, backend=None):
    """A wgpu device on the adapter whose "name backend type" contains the strings, with every feature the renderer can
    use (primitive-index, texture-adapter-specific-format-features, timestamp-query, ...) and the adapter's own limits."""
    import wgpu
    from app.gpu.device import WANTED_FEATURES, _describe
    best = None
    for a in wgpu.gpu.enumerate_adapters_sync():
        name, be, kind = _describe(a)
        if adapter_substr and adapter_substr.lower() not in name.lower():
            continue
        if backend and backend.lower() != be.lower():
            continue
        if kind == "CPU":
            continue
        if best is None:
            best = (a, name, be, kind)
    if best is None:
        raise RuntimeError(f"no adapter matches {adapter_substr!r} {backend!r}")
    adapter, name, be, kind = best
    feats = [f for f in WANTED_FEATURES if f in adapter.features]
    dev = adapter.request_device_sync(required_features=feats, required_limits=dict(adapter.limits))
    return SimpleNamespace(adapter=adapter, device=dev, queue=dev.queue, features=set(dev.features), limits=dict(dev.limits),
                           info=f"{name} - wgpu {be} ({kind})", prim_index="primitive-index" in dev.features,
                           name=name, backend=be, adapter_type=kind)


_CAL_WGSL = """
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}
@fragment fn fs(@builtin(position) f: vec4<f32>) -> @location(0) vec4<f32> {
    var x = f.x * 0.001;
    for (var i = 0; i < 3000; i++) { x = fract(x * 1.0001 + 0.37) + sin(x); }
    return vec4<f32>(x, 0.0, 0.0, 1.0);
}
"""


def calibrate_period_ns(gpu, target_ms=120.0):
    """Nanoseconds per timestamp tick, from a pass long enough that submit+wait wall time is the GPU time."""
    import wgpu
    d, q = gpu.device, gpu.queue
    BU, TU = wgpu.BufferUsage, wgpu.TextureUsage
    mod = d.create_shader_module(code=_CAL_WGSL)
    pipe = d.create_render_pipeline(layout="auto", vertex={"module": mod, "entry_point": "vs"},
                                    fragment={"module": mod, "entry_point": "fs", "targets": [{"format": "rgba8unorm"}]},
                                    primitive={"topology": "triangle-list"})
    tex = d.create_texture(size=(2048, 2048, 1), format="rgba8unorm", usage=TU.RENDER_ATTACHMENT)
    qs = d.create_query_set(type="timestamp", count=2)
    buf = d.create_buffer(size=16, usage=BU.QUERY_RESOLVE | BU.COPY_SRC)
    reps = 1
    for _ in range(6):
        enc = d.create_command_encoder()
        t0 = time.perf_counter()
        for k in range(reps):
            tw = {"query_set": qs, "beginning_of_pass_write_index": 0} if k == 0 else {}
            if k == reps - 1:
                tw.update({"query_set": qs, "end_of_pass_write_index": 1})
            rp = enc.begin_render_pass(color_attachments=[{"view": tex.create_view(), "load_op": "clear", "store_op": "store",
                                                           "clear_value": (0, 0, 0, 1)}], timestamp_writes=tw or None)
            rp.set_pipeline(pipe)
            rp.draw(3)
            rp.end()
        enc.resolve_query_set(qs, 0, 2, buf, 0)
        q.submit([enc.finish()])
        ts = np.frombuffer(bytes(q.read_buffer(buf, 0, 16)), dtype=np.uint64).astype(np.float64)
        wall_ms = (time.perf_counter() - t0) * 1e3
        ticks = ts[1] - ts[0]
        if wall_ms >= target_ms and ticks > 0:
            return wall_ms * 1e6 / ticks, wall_ms
        reps = int(reps * max(2.0, target_ms * 1.3 / max(wall_ms, 1.0)))
    return float("nan"), wall_ms


# ------------------------------------------------------------------------------------------------ comparison
def tie_depth_tolerance(depth, near, far, ortho):
    """Linear depth equal to TIE_QUANTA steps of a 24-bit window depth at `depth`."""
    dz = TIE_QUANTA * 2.0 ** -24 * 2.0                    # window depth -> ndc depth
    if ortho:
        return dz * (far - near) / 2.0 * np.ones_like(depth)
    return dz * depth * depth * (far - near) / (near * far) / 2.0 + 2e-4 * depth


def classify(gid, gfl, gd, wid, wd, near, far, ortho):
    """Counts and explanations of the pixels whose item ids differ. Arrays are (h, w), top row first."""
    diff = gid != wid
    n = int(diff.sum())
    out = {"pixels": int(gid.size), "disagree": n, "agree_pct": 100.0 * (1.0 - n / gid.size)}
    if n == 0:
        out.update(cap=0, tie=0, fall=0, miss=0, edge=0, other=0, other_xy=[], agree_excl_fall_pct=100.0)
        return out
    cap = diff & ((gfl & 2) != 0)
    both = diff & (gid >= 0) & (wid >= 0)
    tol = tie_depth_tolerance(np.maximum(gd, wd), near, far, ortho)
    fall = diff & ~cap & (gid < 0) & (wid >= 0)
    tie = both & ~cap & (np.abs(gd - wd) <= tol)
    bnd = np.zeros_like(diff)                                # id boundary of the GL picture (8 neighbours)
    p = np.pad(gid, 1, mode="edge")
    h, w = gid.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                bnd |= p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] != gid
    miss = diff & ~cap & ~tie & (gid >= 0) & ((wid < 0) | (gd < wd - tol))   # GL's surface holds the centre, no MSAA sample does
    edge = diff & ~cap & ~fall & ~tie & ~miss & bnd
    other = diff & ~cap & ~fall & ~tie & ~miss & ~edge
    ys, xs = np.nonzero(other)
    out.update(cap=int(cap.sum()), tie=int(tie.sum()), fall=int(fall.sum()), miss=int(miss.sum()), agree_excl_fall_pct=100.0 * (1.0 - (n - int(fall.sum())) / gid.size), edge=int(edge.sum()), other=int(other.sum()),
               other_xy=[[int(x), int(y), int(gid[y, x]), int(wid[y, x]), float(gd[y, x]), float(wd[y, x])]
                         for x, y in list(zip(xs, ys))[:8]])
    return out


def depth_stats(gid, gd, wid, wd):
    m = (gid == wid) & (gid >= 0)
    if not m.any():
        return {}
    a, b = gd[m].astype(np.float64), wd[m].astype(np.float64)
    e = np.abs(a - b)
    rel = e / np.maximum(a, 1e-9)
    return {"matched_px": int(m.sum()), "max_abs": float(e.max()), "p99_9_rel": float(np.percentile(rel, 99.9)),
            "max_rel": float(rel.max()), "mean_rel": float(rel.mean())}


def pick_compare(gl, wg, size, grid=(16, 10)):
    """Same pixels through both renderers' pick(): item, cut flag and the world point."""
    w, h = size
    n_same = n = 0
    max_dist = 0.0
    bad = []
    for j in range(grid[1]):
        for i in range(grid[0]):
            x, y = int((i + 0.5) * w / grid[0]), int((j + 0.5) * h / grid[1])
            a, b = gl.pick(x, y), wg.pick(x, y)
            n += 1
            ok = a[0] == b[0] and a[2] == b[2]
            if a[1] is not None and b[1] is not None:
                max_dist = max(max_dist, float(np.linalg.norm(np.asarray(a[1]) - np.asarray(b[1]))))
            n_same += ok
            if not ok:
                bad.append((x, y, a[0], b[0]))
    ids = gl.ids_at([(int((i + 0.5) * w / 16), int((j + 0.5) * h / 10)) for j in range(10) for i in range(16)])
    ids2 = wg.ids_at([(int((i + 0.5) * w / 16), int((j + 0.5) * h / 10)) for j in range(10) for i in range(16)])
    return {"picks": n, "same": n_same, "max_world_dist": max_dist, "different": bad[:6],
            "ids_at_same": int(sum(int(p == q) for p, q in zip(ids, ids2))), "ids_at_n": len(ids)}


def new_session(model_id):
    from tools.perf import perfkit as pk
    pk.env_setup()
    from tools.perf.viewer_session import ViewerSession, timed_prepare
    entry, model, _load = timed_prepare(model_id)
    sess = ViewerSession(entry, model)
    if sess.error:
        raise RuntimeError(sess.error)
    return sess


def wgpu_render(wg, gpu, sess, samples=None):
    """Render the widget's present camera / settings / frame state with the wgpu renderer."""
    import wgpu
    w = sess.w
    rw, rh = sess.render_size
    tex = getattr(wg, "_check_target", None)
    if tex is None or tex.size[:2] != (rw, rh):
        tex = gpu.device.create_texture(size=(rw, rh, 1), format="rgba8unorm",
                                        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                        | wgpu.TextureUsage.TEXTURE_BINDING)
        wg._check_target = tex
    s = w.rsettings
    if samples is not None:
        import copy
        s = copy.copy(s)
        s.msaa = samples
    wg.render(tex, (rw, rh), w.camera, s, w.frame_state())
    return tex


def run_compare(args):
    from tools.perf import make_reference as mr
    from app.gpu.renderer import WgpuRenderer
    gpu = make_gpu(args.adapter, args.backend)
    results = []
    for mid in args.models:
        sess = new_session(mid)
        wg = WgpuRenderer(gpu, page_bytes=(args.page_mib << 20) if args.page_mib else None)
        t0 = time.perf_counter()
        wg.set_model(sess.model)
        up = time.perf_counter() - t0
        print(f"[{mid}] {gpu.info} id={wg.id_format} max_samples={wg.max_samples} upload={up:.2f}s "
              f"gpu={wg.geom.stats['gpu_bytes'] / 2**20:.1f} MiB", flush=True)
        gl = sess.r
        for name, info in mr.model_states(sess):
            if name not in args.states:
                continue
            sess.warm(3)
            sess.make_current()
            gid, gfl = gl.read_ids()
            gd = gl.read_depth()
            wgpu_render(wg, gpu, sess, args.samples or None)
            wid, wfl = wg.read_ids()
            wd = wg.read_depth()
            cam = sess.w.camera
            near, far = cam.near_far()
            if args.dump:
                np.savez_compressed(Path(args.dump) / f"{mid}_{name}.npz", gid=gid, gfl=gfl, gd=gd, wid=wid, wfl=wfl, wd=wd,
                                    tri=wg.read_triangles())
            row = {"model": mid, "state": name, "size": list(sess.render_size), "samples": wg.samples,
                   "draws": len(wg.last_draws), "prim_bits": wg.last_prim_bits}
            row.update(classify(gid, gfl, gd, wid, wd, near, far, bool(cam.ortho)))
            row["depth"] = depth_stats(gid, gd, wid, wd)
            row["flags_selected_same"] = bool(np.array_equal(gfl & 1, wfl & 1))
            row.update(pick=pick_compare(gl, wg, sess.render_size))
            results.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "other_xy"}), flush=True)
            if row["other"]:
                print("   unexplained (x, y, gl id, wgpu id, gl depth, wgpu depth):", row["other_xy"], flush=True)
        wg.release()
        sess.close()
    Path(args.out).write_text(json.dumps(results, indent=1))
    print("agreement table (percent of pixels)")
    print(f"{'model':16s}{'state':12s}{'agree%':>10s}{'dis':>8s}{'cap':>7s}{'tie':>6s}{'fall':>7s}{'miss':>7s}{'edge':>7s}{'other':>6s}{'agree-fall%':>12s}{'picks':>8s}")
    for r in results:
        print(f"{r['model']:16s}{r['state']:12s}{r['agree_pct']:10.4f}{r['disagree']:8d}{r['cap']:7d}{r['tie']:6d}"
              f"{r['fall']:7d}{r['miss']:7d}{r['edge']:7d}{r['other']:6d}{r['agree_excl_fall_pct']:12.4f}{r['pick']['same']:4d}/{r['pick']['picks']}")


def run_order(args):
    """Per state: the parts drawn, their LOD levels and their GL index-buffer span starts (= the draw order that decides
    equal-depth ties) against what the GL Renderer drew in its pre-pass."""
    from tools.perf import make_reference as mr
    from app.gpu.renderer import WgpuRenderer
    gpu = make_gpu(args.adapter, args.backend)
    ok_all = True
    for mid in args.models:
        sess = new_session(mid)
        wg = WgpuRenderer(gpu)
        wg.set_model(sess.model)
        gl = sess.r
        parts = sess.model.parts
        for name, _info in mr.model_states(sess):
            if name not in args.states:
                continue
            sess.warm(2)
            seen = []
            orig = gl._runs

            def spy(ps, kind, _orig=orig):
                ps = list(ps)
                if kind == "pre":
                    seen.append(ps)
                return _orig(ps, kind)
            gl._runs = spy
            sess.warm(1)
            gl._runs = orig
            gl_parts = seen[-1]
            wgpu_render(wg, gpu, sess)
            mine = {parts[pi].id: (k, first) for _slot, pi, k, first, _n in wg.last_draws}
            gl_set = {p.id for p in gl_parts}
            same_set = gl_set == set(mine)
            same_levels = {pid: k for pid, k in gl._level.items()} == {pid: k for pid, k in wg._level.items()}
            starts_ok = all(gl._span(p)[0] == wg.geom.gl_keys[next(i for i, q in enumerate(parts) if q.id == p.id)][mine[p.id][0]]
                            for p in gl_parts if p.id in mine)
            order_ok = [e[3] for e in wg.last_draws] and True
            keys = [wg.geom.gl_keys[pi][k] for _s, pi, k, _f, _n in wg.last_draws]
            order_ok = keys == sorted(keys)
            ok = same_set and same_levels and starts_ok and order_ok
            ok_all &= ok
            print(f"{mid:16s}{name:12s} parts gl={len(gl_set)} wgpu={len(mine)} same_set={same_set} levels_equal={same_levels} "
                  f"span_starts_equal={starts_ok} sorted_by_gl_order={order_ok} lod_parts={len(gl._level)}", flush=True)
        wg.release()
        sess.close()
    print("ORDER OK" if ok_all else "ORDER DIFFERS")


# ------------------------------------------------------------------------------------------------ timing
def run_timing(args):
    from tools.perf import make_reference as mr
    from app.gpu.renderer import WgpuRenderer
    gpu = make_gpu(args.adapter, args.backend)
    period, wall = calibrate_period_ns(gpu)
    print(f"{gpu.info}: timestamp period {period:.3f} ns/tick (calibration pass {wall:.0f} ms wall)", flush=True)
    sess = new_session(args.model)
    out = {"adapter": gpu.info, "period_ns": period, "model": args.model, "size": list(sess.render_size), "rows": []}
    wg = WgpuRenderer(gpu, profile=True)
    wg.ts_period_ns = period
    wg.set_model(sess.model)
    for name, _info in mr.model_states(sess):
        if name != "default":
            continue
        sess.warm(3)
        for samples in (4, 1):
            for _ in range(6):
                wgpu_render(wg, gpu, sess, samples)
            v, r, t = [], [], []
            for _ in range(args.frames):
                wgpu_render(wg, gpu, sess, samples)
                v.append(wg.timings["vis_ms"])
                r.append(wg.timings["resolve_ms"])
                t.append(wg.timings["total_ms"])
            row = {"samples": wg.samples, "requested": samples, "draws": len(wg.last_draws),
                   "triangles": int(sum(e[4] for e in wg.last_draws) // 3),
                   "vis_ms_median": float(np.median(v)), "vis_ms_min": float(np.min(v)), "vis_ms_p95": float(np.percentile(v, 95)),
                   "resolve_ms_median": float(np.median(r)), "total_ms_median": float(np.median(t))}
            out["rows"].append(row)
            print(json.dumps(row), flush=True)
    if args.baseline and Path(args.baseline).exists():
        b = json.loads(Path(args.baseline).read_text())
        out["gl_prepass_ms"] = {"settled": b["settled_frame"]["gpu_ms"]["t.fbo_pre"],
                                "orbit": b["orbit_frame"]["gpu_ms"]["t.fbo_pre"]}
        print("GL prepass (baseline):", out["gl_prepass_ms"])
    Path(args.out).write_text(json.dumps(out, indent=1))
    wg.release()
    sess.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("compare", "timing", "order"))
    ap.add_argument("--models", nargs="+", default=["eyeball", "kidney_nephron", "pancreas"])
    ap.add_argument("--states", nargs="+", default=["default", "cut_plane"])
    ap.add_argument("--model", default="pancreas")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--page-mib", type=int, default=0)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--samples", type=int, default=0, help="override the sample count (default: the GL renderer's rule)")
    ap.add_argument("--dump", default=None, help="folder for the per-pixel arrays of every compared state (npz)")
    ap.add_argument("--out", default="visbuf_check.json")
    args = ap.parse_args()
    {"compare": run_compare, "timing": run_timing, "order": run_order}[args.mode](args)


if __name__ == "__main__":
    main()
