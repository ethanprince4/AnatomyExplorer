"""Driver for the cull spike. Run through the GPU lock:

  python S/tools/gpu_lock.py R/.venv/Scripts/python.exe R/tools/perf/spikes/cull/run.py <cmd> --adapter 3080|uhd --size 25M|100M|250M ...

cmds: smoke | measure | correct | shade | hzb
All output is JSON lines on stdout (also appended to --log).
"""
import argparse
import ctypes
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clusters as CL  # noqa: E402
import gpu as GP  # noqa: E402
import scene as SC  # noqa: E402

CACHE = os.environ.get("CULL_CACHE", "C:/Users/Ethan/AppData/Local/Temp/claude/C--Users-Ethan-Desktop-AnatomyExplorer-Worktrees-keen-ride-vm1yxr/29352135-c71d-48a1-a9a1-b56e384a2bf3/scratchpad/spikes/cull/cache")
DIMS = {"8M": (1, 2, 2), "25M": (2, 2, 2), "100M": (3, 3, 4), "250M": (4, 4, 6)}
NEAR = 0.002
FOV = 55.0


class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_gb():
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    p = PMC()
    p.cb = ctypes.sizeof(p)
    k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return p.WorkingSetSize / 2**30, p.PeakWorkingSetSize / 2**30


LOGF = None


def emit(**kw):
    s = json.dumps(kw, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    print(s, flush=True)
    if LOGF:
        with open(LOGF, "a") as fh:
            fh.write(s + "\n")


def proj_for(r):
    return SC.perspective_rz(FOV, r.W / r.H, NEAR)


def cam_pose(scene, view_name, step, views):
    eye, tgt = (np.array(v, dtype=np.float64) for v in views[view_name])
    if view_name == "inside":
        d = tgt - eye
        a = math.radians(1.0 * step)
        c, s = math.cos(a), math.sin(a)
        d = np.array([c * d[0] + s * d[2], d[1], -s * d[0] + c * d[2]])
        return SC.look_at(eye, eye + d)
    a = math.radians(0.6 * step)
    c, s = math.cos(a), math.sin(a)
    rel = eye - tgt
    rel = np.array([c * rel[0] + s * rel[2], rel[1], -s * rel[0] + c * rel[2]])
    return SC.look_at(tgt + rel, tgt)


def setup(args):
    names = CL.DEFAULT_MODELS
    geo = SC.Geometry(CACHE, names, page_bytes=args.page_mb << 20)
    sc = SC.Scene(geo, DIMS[args.size])
    ad = GP.pick_adapter(args.adapter, args.backend)
    t0 = time.time()
    r = GP.CullRenderer(ad, geo, sc, args.w, args.h)
    r.wait()
    emit(ev="setup", adapter=ad.summary, size=args.size, dims=sc.dims, instances=sc.n_inst, tris=sc.total_tris,
         clusters=sc.n_ci, unique_clusters=geo.n_clusters, unique_tris=geo.total_tris_unique,
         unique_verts=geo.total_verts_unique, vpages=len(geo.vpages), ipages=len(geo.ipages),
         upload_s=round(time.time() - t0, 2), rss_gb=rss_gb())
    return geo, sc, r


def run_frames(r, sc, views, vname, steps, readback=True, cone=True):
    proj = proj_for(r)
    out = []
    for k in steps:
        out.append(r.frame(cam_pose(sc, vname, k, views), proj, readback=readback, cone=cone))
    return out


def summarize(fr):
    keys = ["live", "frustum", "cone", "p1", "cand", "p2", "p1_tris", "p2_tris", "marked", "cpu_ms"]
    res = {k: float(np.mean([f[k] for f in fr])) for k in keys}
    res["tris_drawn"] = res["p1_tris"] + res["p2_tris"]
    res["occ_survivors"] = res["p1"] + res["p2"]
    stages = fr[0]["ms"].keys()
    res["ms"] = {s: round(float(np.mean([f["ms"][s] for f in fr])), 3) for s in stages}
    res["gpu_sum_ms"] = round(sum(res["ms"][s] for s in GP.STAGES), 3)
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in res.items()}


# --------------------------------------------------------------------------- measure
def cmd_measure(args):
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    emit(ev="memory", **r.memory_report(), bytes_per_unique_tri=geo.bytes_total() / geo.total_tris_unique,
         unique_geometry_bytes=geo.bytes_total())
    proj = proj_for(r)
    cp = cam_pose(sc, "near", 0, views)
    rat = []
    for _ in range(3):
        r.clear_visible()
        t0 = time.perf_counter()
        fr = r.frame(cp, proj)
        rat.append((time.perf_counter() - t0) * 1e3 / fr["ms"]["total_span"])
    emit(ev="timestamp_check", wall_over_gpu_span=[round(x, 3) for x in rat], period_ns=r.ts_period)
    for vname in args.views.split(","):
        r.clear_visible()
        # cold frame: all visible bits zero
        cold = r.frame(cam_pose(sc, vname, 0, views), proj)
        r.wait()
        emit(ev="cold", view=vname, **summarize([cold]))
        static = run_frames(r, sc, views, vname, [0] * args.frames)
        emit(ev="static", view=vname, **summarize(static[2:]))
        orbit = run_frames(r, sc, views, vname, list(range(1, args.frames + 1)))
        emit(ev="orbit", view=vname, **summarize(orbit))
        # throughput: back-to-back submits, no readbacks
        r.wait()
        t0 = time.perf_counter()
        cpu = run_frames(r, sc, views, vname, list(range(args.frames + 1, 2 * args.frames + 1)), readback=False)
        t_enc = time.perf_counter()
        r.wait()
        t1 = time.perf_counter()
        emit(ev="throughput", view=vname, wall_ms_per_frame=round((t1 - t0) / args.frames * 1e3, 3),
             cpu_ms_per_frame=round(float(np.mean([c["cpu_ms"] for c in cpu])), 3), rss_gb=rss_gb())


# --------------------------------------------------------------------------- compare
def compare(ids_a, d_a, ids_b, d_b):
    """a = culled, b = reference. Reverse-Z: larger depth is nearer."""
    diff = ids_a != ids_b
    n = int(diff.sum())
    da, db = d_a[diff], d_b[diff]
    tie = int((da == db).sum())
    false_cull = int((db > da).sum())     # reference is nearer than the culled render: something was wrongly dropped
    extra_near = int((da > db).sum())     # culled render nearer than the reference
    return {"fg_pixels": int((ids_b != 0).sum()), "id_mismatch": n, "depth_ties": tie,
            "false_cull_px": false_cull, "culled_nearer_px": extra_near,
            "distinct_ids_ref": int(len(np.unique(ids_b))), "distinct_ids_cull": int(len(np.unique(ids_a)))}


def hide_set(sc, eye, frac):
    c = sc._inst_centers()
    d = np.linalg.norm(c - eye, axis=1)
    thr = np.quantile(d, frac)
    return (d <= thr).astype(np.uint32)


def cmd_correct(args):
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    for vname in args.views.split(","):
        pose0 = cam_pose(sc, vname, 0, views)
        eye = np.linalg.inv(pose0)[:3, 3]
        r.set_hidden(np.zeros(sc.n_inst, np.uint32))
        r.clear_visible()
        # 1: cold first frame
        st = r.frame(pose0, proj)
        ids, dep = r.dump()
        rid, rdep = r.reference(pose0, proj)
        emit(ev="cmp", view=vname, case="cold", p1=st["p1"], p2=st["p2"], **compare(ids, dep, rid, rdep))
        # 2: warmed, then first frame after a camera move (stale visible bits)
        for _ in range(3):
            r.frame(pose0, proj)
        pose1 = cam_pose(sc, vname, 6, views)
        st = r.frame(pose1, proj)
        ids, dep = r.dump()
        rid, rdep = r.reference(pose1, proj)
        emit(ev="cmp", view=vname, case="moved6", p1=st["p1"], p2=st["p2"], **compare(ids, dep, rid, rdep))
        # 3: hide the outer instances nearest the camera, first frame after, no warm-up
        for frac in (0.2, 0.5):
            for _ in range(2):
                r.frame(pose1, proj)
            hid = hide_set(sc, eye, frac)
            r.set_hidden(hid)
            st = r.frame(pose1, proj)
            ids, dep = r.dump()
            rid, rdep = r.reference(pose1, proj, hidden=hid)
            emit(ev="cmp", view=vname, case=f"hide{int(frac*100)}%_first_frame", hidden_instances=int(hid.sum()), p1=st["p1"], p2=st["p2"],
                 **compare(ids, dep, rid, rdep))
            # and show them again: the previously hidden clusters are not in the visible set
            r.set_hidden(np.zeros(sc.n_inst, np.uint32))
            st = r.frame(pose1, proj)
            ids, dep = r.dump()
            rid, rdep = r.reference(pose1, proj)
            emit(ev="cmp", view=vname, case=f"show_after_hide{int(frac*100)}%", p1=st["p1"], p2=st["p2"], **compare(ids, dep, rid, rdep))
        # 4: back-face culling legality: reference with and without culling
        if args.nocull:
            rid, rdep = r.reference(pose1, proj)
            nid, ndep = r.reference(pose1, proj, cull_mode="none")
            ch = rid != nid
            emit(ev="backface_effect", view=vname, fg_pixels=int((rid != 0).sum()), pixels_changed_by_culling_off=int(ch.sum()),
                 depth_changed=int((rdep != ndep).sum()), fg_gained=int(((rid == 0) & (nid != 0)).sum()))
    emit(ev="done", rss_gb=rss_gb())


# --------------------------------------------------------------------------- shade check
def cmd_shade(args):
    """Compare the GPU shading pass against a float64 CPU evaluation at random pixels."""
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    pose = cam_pose(sc, "outside", 0, views)
    r.clear_visible()
    for _ in range(3):
        r.frame(pose, proj)
    ids, dep = r.dump()
    # read colour texture
    W, H = r.W, r.H
    bpr = ((W * 4 + 255) // 256) * 256
    rb = r.device.create_buffer(size=bpr * H, usage=GP.BU.MAP_READ | GP.BU.COPY_DST)
    enc = r.device.create_command_encoder()
    enc.copy_texture_to_buffer({"texture": r.t_color}, {"buffer": rb, "bytes_per_row": bpr, "rows_per_image": H}, (W, H, 1))
    r.q.submit([enc.finish()])
    rb.map_sync(GP.wgpu.MapMode.READ)
    img = np.frombuffer(bytes(rb.read_mapped()), dtype=np.uint8).reshape(H, bpr)[:, :W * 4].reshape(H, W, 4).copy()
    rb.unmap()
    rng = np.random.default_rng(3)
    ys, xs = np.nonzero(ids)
    pick = rng.choice(len(ys), 3000, replace=False)
    VP = proj @ pose
    ld = np.array([0.35, 0.8, 0.5])
    ld /= np.linalg.norm(ld)
    errs = []
    for k in pick:
        y, x = int(ys[k]), int(xs[k])
        got = img[y, x, :3].astype(np.float64) / 255.0
        want = cpu_shade(geo, sc, int(ids[y, x]) - 1, VP, x + 0.5, y + 0.5, r.W, r.H, ld)
        errs.append(np.abs(got - want).max())
    errs = np.array(errs)
    emit(ev="shade_check", samples=len(errs), max_err_8bit=float(errs.max() * 255), mean_err_8bit=float(errs.mean() * 255),
         over_2_levels=int((errs * 255 > 2.0).sum()), over_4_levels=int((errs * 255 > 4.0).sum()))


def cpu_shade(geo, sc, idm, VP, px, py, W, H, ld):
    ci, t = idm >> 7, idm & 127
    inst, cl = sc.ci_table[ci]
    rec = geo.cluster_rec[cl]
    meta = int(rec[5])
    vpage, ipage = (meta >> 14) & 15, (meta >> 18) & 15
    vfirst, ioff = int(rec[6]), int(rec[7])
    ip = np.frombuffer(geo.ipages[ipage], dtype=np.uint8)
    loc = ip[ioff + t * 3: ioff + t * 3 + 3].astype(np.int64)
    vp = np.frombuffer(geo.vpages[vpage], dtype=np.uint16).reshape(-1, 5)
    part = int(sc.part_ids[inst])
    lo, ext = geo.part_lo[part].astype(np.float32), geo.part_ext[part].astype(np.float32)
    A = sc.instances[inst, :3, :3].astype(np.float64)
    tt = sc.instances[inst, :3, 3].astype(np.float64)
    P, N, CL_ = [], [], []
    for l in loc:
        v = vp[vfirst + l]
        p = lo.astype(np.float64) + v[:3].astype(np.float64) * (ext.astype(np.float64) / 65535.0)
        w = A @ p + tt
        P.append(w)
        CL_.append(VP @ np.append(w, 1.0))
        e = CL.oct_decode(v[3:5].view(np.int16)[None, :])[0]
        N.append(e)
    nx = px / W * 2 - 1
    ny = 1 - py / H * 2
    a = np.array([c[0] - nx * c[3] for c in CL_])
    b = np.array([c[1] - ny * c[3] for c in CL_])
    lam = np.cross(a, b)
    lam /= lam.sum()
    n = sum(lam[i] * N[i] for i in range(3))
    n /= np.linalg.norm(n)
    n = A @ n
    n /= np.linalg.norm(n)
    lit = 0.2 + 0.8 * max(float(n @ ld), 0.0)
    item = np.uint32(sc.item_ids[inst])
    x = np.uint32((int(item) * 747796405 + 2891336453) & 0xFFFFFFFF)
    sh = int((int(x) >> 28) + 4)
    x = np.uint32((((int(x) >> sh) ^ int(x)) * 277803737) & 0xFFFFFFFF)
    x = np.uint32((int(x) >> 22) ^ int(x))
    xi = int(x)
    col = np.array([xi & 255, (xi >> 8) & 255, (xi >> 16) & 255]) / 255.0 * 0.6 + 0.35
    return col * lit


# --------------------------------------------------------------------------- hzb check
def cmd_hzb(args):
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    pose = cam_pose(sc, "outside", 0, views)
    r.clear_visible()
    for _ in range(2):
        r.frame(pose, proj)
    ids, dep = r.dump()
    # the HZB left by the frame was built from the phase-1 depth; rebuild from the final depth for an exact check
    enc = r.device.create_command_encoder()
    cp = enc.begin_compute_pass()
    for lvl in range(r.hzb_levels):
        cp.set_pipeline(r.P["hzb0" if lvl == 0 else "hzbn"])
        cp.set_bind_group(0, r.bg["hzb"][lvl])
        w, h = r.hzb_dims[lvl]
        cp.dispatch_workgroups((w + 7) // 8, (h + 7) // 8, 1)
    cp.end()
    r.q.submit([enc.finish()])
    bad = 0
    cur = dep.astype(np.float32)
    for lvl in range(r.hzb_levels):
        w, h = r.hzb_dims[lvl]
        bpr = ((w * 4 + 255) // 256) * 256
        rb = r.device.create_buffer(size=bpr * h, usage=GP.BU.MAP_READ | GP.BU.COPY_DST)
        enc = r.device.create_command_encoder()
        enc.copy_texture_to_buffer({"texture": r.t_hzb, "mip_level": lvl}, {"buffer": rb, "bytes_per_row": bpr, "rows_per_image": h}, (w, h, 1))
        r.q.submit([enc.finish()])
        rb.map_sync(GP.wgpu.MapMode.READ)
        got = np.frombuffer(bytes(rb.read_mapped()), dtype=np.float32).reshape(h, bpr // 4)[:, :w].copy()
        rb.unmap()
        H0, W0 = cur.shape
        pad = np.full((h * 2, w * 2), np.inf, dtype=np.float32)
        pad[:H0, :W0] = cur
        want = pad.reshape(h, 2, w, 2).min(axis=(1, 3))
        mism = int((got != want).sum())
        bad += mism
        emit(ev="hzb_level", level=lvl, dims=(w, h), mismatches=mism)
        cur = want
    emit(ev="hzb_total_mismatch", n=bad)


def cmd_calib(args):
    """Wall time of a heavy frame vs the timestamp span (checks the timestamp period assumption)."""
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    pose = cam_pose(sc, "near", 0, views)
    r.clear_visible()
    r.frame(pose, proj)
    r.wait()
    rows = []
    for _ in range(8):
        r.clear_visible()   # cold frame = heavy
        t0 = time.perf_counter()
        fr = r.frame(pose, proj)      # includes the sync readback
        t1 = time.perf_counter()
        rows.append((t1 - t0) * 1e3 / max(fr["ms"]["total_span"], 1e-9))
    emit(ev="calib", wall_over_timestamp=[round(x, 2) for x in rows], last_span_ms=fr["ms"]["total_span"])


def cmd_diag(args):
    """Why do phase-2 survivors pass? Re-test them on the CPU against the final full-resolution depth."""
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    vname = args.views.split(",")[0]
    pose = cam_pose(sc, vname, 0, views)
    r.clear_visible()
    for _ in range(4):
        st = r.frame(pose, proj)
    ids, dep = r.dump()
    n2 = st["p2"]
    lst = np.frombuffer(r.read_buffer(r.b_list2, ((n2 * 4 + 15) // 16) * 16), dtype=np.uint32)[:n2]
    rng = np.random.default_rng(5)
    pick = lst[rng.choice(n2, min(4000, n2), replace=False)]
    marked = np.zeros(sc.n_ci, bool)
    marked[(ids[ids != 0] - 1) >> 7] = True
    W, H = r.W, r.H
    res = {"sampled": len(pick), "contributes_pixels": 0, "exact_rect_pass": 0, "exact_rect_cull": 0, "behind_all": 0, "off_or_near": 0}
    fr = []
    for ci in pick:
        inst, cl = sc.ci_table[ci]
        rec = geo.cluster_rec[cl]
        c = rec[0:3].view(np.float32).astype(np.float64)
        h = rec[8:11].view(np.float32).astype(np.float64)
        A = sc.instances[inst, :3, :3].astype(np.float64)
        t = sc.instances[inst, :3, 3].astype(np.float64)
        pts = []
        for k in range(8):
            sgn = np.array([(k & 1) * 2 - 1, ((k >> 1) & 1) * 2 - 1, ((k >> 2) & 1) * 2 - 1])
            pts.append(np.append(A @ (c + sgn * h) + t, 1.0))
        cl4 = (proj @ pose @ np.array(pts).T).T
        if (cl4[:, 3] <= NEAR).any():
            res["off_or_near"] += 1
            continue
        nd = cl4[:, :2] / cl4[:, 3:4]
        x0 = int(np.clip((nd[:, 0].min() * 0.5 + 0.5) * W, 0, W - 1)); x1 = int(np.clip((nd[:, 0].max() * 0.5 + 0.5) * W, 0, W - 1))
        y0 = int(np.clip((0.5 - nd[:, 1].max() * 0.5) * H, 0, H - 1)); y1 = int(np.clip((0.5 - nd[:, 1].min() * 0.5) * H, 0, H - 1))
        dn = NEAR / cl4[:, 3].min()
        reg = dep[y0:y1 + 1, x0:x1 + 1]
        fr.append((x1 - x0 + 1, y1 - y0 + 1, float((reg <= dn).mean())))
        # same exact-rect test with a PCA oriented box of the cluster's real vertices
        meta = int(rec[5]); vpage = (meta >> 14) & 15; vcnt = meta & 127
        vp = np.frombuffer(geo.vpages[vpage], dtype=np.uint16).reshape(-1, 5)
        part = int(sc.part_ids[inst])
        q = vp[int(rec[6]): int(rec[6]) + vcnt, :3].astype(np.float64)
        pv = geo.part_lo[part].astype(np.float64) + q * (geo.part_ext[part].astype(np.float64) / 65535.0)
        mu = pv.mean(0)
        _, _, vt = np.linalg.svd(pv - mu, full_matrices=False)
        loc = (pv - mu) @ vt.T
        lo_, hi_ = loc.min(0), loc.max(0)
        cen_o = (lo_ + hi_) / 2
        he = (hi_ - lo_) / 2
        pts2 = []
        for k in range(8):
            sgn = np.array([(k & 1) * 2 - 1, ((k >> 1) & 1) * 2 - 1, ((k >> 2) & 1) * 2 - 1])
            pl = mu + (cen_o + sgn * he) @ vt
            pts2.append(np.append(A @ pl + t, 1.0))
        c2 = (proj @ pose @ np.array(pts2).T).T
        if (c2[:, 3] > NEAR).all():
            nd2 = c2[:, :2] / c2[:, 3:4]
            ax0 = int(np.clip((nd2[:, 0].min() * 0.5 + 0.5) * W, 0, W - 1)); ax1 = int(np.clip((nd2[:, 0].max() * 0.5 + 0.5) * W, 0, W - 1))
            ay0 = int(np.clip((0.5 - nd2[:, 1].max() * 0.5) * H, 0, H - 1)); ay1 = int(np.clip((0.5 - nd2[:, 1].min() * 0.5) * H, 0, H - 1))
            dn2 = NEAR / c2[:, 3].min()
            if dep[ay0:ay1 + 1, ax0:ax1 + 1].min() <= dn2:
                res["obb_exact_rect_pass"] = res.get("obb_exact_rect_pass", 0) + 1
            else:
                res["obb_exact_rect_cull"] = res.get("obb_exact_rect_cull", 0) + 1
        if marked[ci]:
            res["contributes_pixels"] += 1
        if reg.min() <= dn:
            res["exact_rect_pass"] += 1
        else:
            res["exact_rect_cull"] += 1
    fr = np.array(fr)
    res["median_rect_w"] = float(np.median(fr[:, 0])); res["median_rect_h"] = float(np.median(fr[:, 1]))
    res["median_frac_pixels_not_occluded"] = float(np.median(fr[:, 2]))
    res["p90_frac_pixels_not_occluded"] = float(np.quantile(fr[:, 2], 0.9))
    emit(ev="diag", view=vname, p2=n2, **res)


def cmd_smoke(args):
    geo, sc, r = setup(args)
    views = SC.make_views(sc)
    proj = proj_for(r)
    for v in views:
        r.clear_visible()
        fr = [r.frame(cam_pose(sc, v, k, views), proj) for k in range(3)]
        emit(ev="smoke", view=v, **summarize(fr[1:]))


def main():
    global LOGF
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--adapter", default="3080")
    ap.add_argument("--backend", default="Vulkan")
    ap.add_argument("--size", default="25M")
    ap.add_argument("--views", default="outside,near,inside")
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--page-mb", type=int, default=64)
    ap.add_argument("--w", type=int, default=2560)
    ap.add_argument("--h", type=int, default=1600)
    ap.add_argument("--nocull", action="store_true")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    LOGF = args.log
    {"smoke": cmd_smoke, "measure": cmd_measure, "correct": cmd_correct, "shade": cmd_shade, "hzb": cmd_hzb, "calib": cmd_calib, "diag": cmd_diag}[args.cmd](args)


if __name__ == "__main__":
    main()
