// Cluster culling kernels. Concatenated by app/gpu/cull.py after clip.wgsl (Frame, ClipParams) and cull_tables.wgsl
// (the table layout: cl_geom, cl_range, rng, part_xf, range_active, ptab, pstate, stats, args, dinfo, vis flags; crl: the visible-cluster lists).
//
//   cull_p1   phase 1: clusters of the frame's parts that passed the frustum test AND were visible last frame
//   cull_p2   phase 2: clusters that passed the frustum test and were NOT drawn in phase 1, kept unless the depth
//             pyramid built from phase 1's real depth hides their bounding box
//   finalize_p1 / finalize_p2   one thread: draw and dispatch arguments of the phase for every page (budget split, see fin_all)
//
// A surviving cluster takes the next free slot of its page's list IN CLUSTER ORDER (scan, see the end of run_phase) and writes its id into
// crl[slot_base + slot] = (cluster, page-local index word of its first triangle, part, triangles | ordinal of the part in its page << 8): the
// page's list of visible clusters. The first slots (budget) are gathered into the compact index buffer (cull_gather.wgsl) and drawn
// indexed (cull_idx.wgsl); the rest is drawn by cull_vis.wgsl directly (non-indexed, 192 vertices per cluster, vertex shader pull;
// the triangles are stored in cluster order, see geometry.py cluster_order).
//
// Boxes. cl_geom holds the part-space box (centre, half extents) and dmax, the largest morph displacement |dpos| of the
// cluster. Half extents grow by |weight| * dmax (the part's current morph weight) and by 2e-6 of the coordinate size
// (float rounding); the box is transformed by the part matrix of this frame, which carries explode / node offsets.

struct Cfg {
    hz: vec4<u32>,          // x: hzb levels, y: 1 = count statistics, z: hzb width, w: hzb height (level 0)
    eps: vec4<f32>,         // x: depth margin, y: screen padding in pixels, z: 1 = accept every cluster of an active range (no tests)
    cl: vec4<u32>,          // x: 1 = classify the clusters against the cut planes (a plane is on): removed ones are dropped, the ones
                            // wholly on the kept side go to the list of class 0 (drawn without the clip discard), the rest to class 1
};

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<uniform> cfg: Cfg;
@group(0) @binding(2) var<storage, read> cro: array<vec4<u32>>;           // cull_tables.wgsl
@group(0) @binding(3) var<storage, read_write> cra: array<atomic<u32>>;
@group(0) @binding(4) var<storage, read_write> crw: array<u32>;
@group(0) @binding(5) var<uniform> lay: CullLay;
@group(0) @binding(6) var<storage, read_write> crl: array<vec4<u32>>;       // visible-cluster entries, see run_phase
@group(1) @binding(0) var<uniform> sel: vec4<u32>;                        // x: page
@group(2) @binding(0) var hzb: texture_2d<f32>;

const ST_ACTIVE: u32 = 0u;          // clusters of active ranges
const ST_FRUSTUM: u32 = 1u;         // ... that pass the frustum test
const ST_FRUSTUM_TRIS: u32 = 2u;
const ST_P1: u32 = 3u;
const ST_P1_TRIS: u32 = 4u;
const ST_P2: u32 = 5u;
const ST_P2_TRIS: u32 = 6u;
const ST_OVERFLOW: u32 = 7u;
const ST_P2_TESTED: u32 = 8u;
// 9, 10: visible / visible_tris (cull_mark.wgsl)
const ST_IDX: u32 = 11u;            // slots drawn by the indexed (compact buffer) draws
const ST_PULL: u32 = 12u;           // slots drawn by the pulled draws (over the budget)
const ST_KEPT: u32 = 13u;           // clusters kept by both phases (every frame: the renderer's choice between culling and the plain draw)
const ST_PULLED: u32 = 14u;         // ... of them over the compact index budget (pulled draw)

struct Box {
    c: vec3<f32>,
    h: vec3<f32>,
};

fn part_matrix(part: u32) -> mat4x4<f32> {
    let b = part * 5u;
    return mat4x4<f32>(part_xf_at(b), part_xf_at(b + 1u), part_xf_at(b + 2u), part_xf_at(b + 3u));
}

fn cluster_box(c: u32, part: u32) -> Box {
    let g0 = cl_geom_at(2u * c);
    let g1 = cl_geom_at(2u * c + 1u);
    let wabs = bitcast<f32>(part_meta_at(part).x);
    var b: Box;
    b.c = g0.xyz;
    b.h = g1.xyz + vec3<f32>(wabs * g0.w) + 2e-6 * (abs(g0.xyz) + g1.xyz);
    return b;
}

// Cut planes (clip.wgsl clipped(): a point is removed where dot(vec4(world, 1), plane) < 0). The box of a cluster (part space, grown
// by |weight| * dmax and the rounding allowance in cluster_box) goes through the part matrix; the signed distance of the world
// box to a plane lies within s -/+ r (r: the extent of the oriented box along the plane normal), widened by a relative margin far
// above the float32 error of the vertex shader's world position and by `mg` world units: the visibility pass interpolates the
// world position at the pixel CENTRE, so a partly covered pixel is clipped by a position extrapolated past the triangle. 128 pixels
// of world size at the far end of the box cover it except for screen-space slivers (cutclass.py pixel_margin, the twin, says more).
//   0: every fragment is on the kept side (the cluster needs no discard), 1: may straddle, 2: every fragment is removed.
fn pixel_margin(wc: vec3<f32>, m: mat4x4<f32>, b: Box) -> f32 {
    let ty = frame.halves.y;
    if (frame.info.w == 1u) {
        return 256.0 * ty / frame.screen.y;
    }
    let R = length(m[0].xyz) * b.h.x + length(m[1].xyz) * b.h.y + length(m[2].xyz) * b.h.z;
    let depth = -(frame.view * vec4<f32>(wc, 1.0)).z;
    if (depth - R <= 1e-4) {
        return 1e30;
    }
    return 256.0 * ty * (depth + R) / frame.screen.y;
}

fn plane_range(P: vec4<f32>, wc: vec3<f32>, m: mat4x4<f32>, b: Box, mg: f32) -> vec2<f32> {
    let s = dot(P.xyz, wc) + P.w;
    let r = abs(dot(P.xyz, m[0].xyz)) * b.h.x + abs(dot(P.xyz, m[1].xyz)) * b.h.y + abs(dot(P.xyz, m[2].xyz)) * b.h.z;
    let e = 3e-5 * (abs(P.x * wc.x) + abs(P.y * wc.y) + abs(P.z * wc.z) + abs(P.w) + r) + mg * length(P.xyz);
    return vec2<f32>(s - r - e, s + r + e);
}

fn cluster_clip_class(m: mat4x4<f32>, b: Box, part: u32) -> u32 {
    let pm = part_meta_at(part);
    if ((pm.y & 1u) != 0u) {
        return 0u;                                  // never cut
    }
    if (bitcast<f32>(pm.x) != 0.0) {
        return 1u;                                  // morphed: not proved
    }
    let k = frame.clip.on;
    let wc = (m * vec4<f32>(b.c, 1.0)).xyz;
    let mg = pixel_margin(wc, m, b);
    var n = 0u;
    var any_kept = false;          // some enabled plane has the whole box on its kept side
    var all_kept = true;           // every enabled plane has
    var any_gone = false;          // some enabled plane has the whole box on its removed side
    var all_gone = true;           // every enabled plane has
    for (var i = 0u; i < 3u; i = i + 1u) {
        if (k[i] != 1u) {
            continue;
        }
        var P = frame.clip.p0;
        if (i == 1u) { P = frame.clip.p1; }
        if (i == 2u) { P = frame.clip.p2; }
        let v = plane_range(P, wc, m, b, mg);
        n = n + 1u;
        let kept = v.x >= 0.0;
        let gone = v.y < 0.0;
        any_kept = any_kept || kept;
        all_kept = all_kept && kept;
        any_gone = any_gone || gone;
        all_gone = all_gone && gone;
    }
    if (n == 0u) {
        return 0u;
    }
    if (k.w == 1u) {                                // corner: removed where every enabled plane is negative
        if (any_kept) { return 0u; }
        if (all_gone) { return 2u; }
        return 1u;
    }
    if (any_gone) { return 2u; }                    // any plane removes its side
    if (all_kept) { return 0u; }
    return 1u;
}

fn corner(mvp: mat4x4<f32>, b: Box, k: u32) -> vec4<f32> {
    let s = vec3<f32>(select(-1.0, 1.0, (k & 1u) != 0u), select(-1.0, 1.0, (k & 2u) != 0u), select(-1.0, 1.0, (k & 4u) != 0u));
    return mvp * vec4<f32>(b.c + b.h * s, 1.0);
}

// bit mask of the frustum planes the clip-space point is outside of
fn outside_mask(p: vec4<f32>) -> u32 {
    let m = 1e-5 * abs(p.w);
    var r = 0u;
    if (p.x < -p.w - m) { r |= 1u; }
    if (p.x > p.w + m) { r |= 2u; }
    if (p.y < -p.w - m) { r |= 4u; }
    if (p.y > p.w + m) { r |= 8u; }
    if (p.z < -m) { r |= 16u; }
    if (p.z > p.w + m) { r |= 32u; }
    return r;
}

fn frustum_pass(mvp: mat4x4<f32>, b: Box) -> bool {
    var allm = 63u;
    for (var k = 0u; k < 8u; k = k + 1u) {
        allm = allm & outside_mask(corner(mvp, b, k));
    }
    return allm == 0u;
}

// true when the nearest point of the box is behind the farthest depth stored over every pixel the box can touch
fn occluded(mvp: mat4x4<f32>, b: Box) -> bool {
    var zmin = 1e30;
    var lo = vec2<f32>(1e30);
    var hi = vec2<f32>(-1e30);
    for (var k = 0u; k < 8u; k = k + 1u) {
        let p = corner(mvp, b, k);
        if (p.w < 1e-6) {
            return false;
        }
        let q = p.xyz / p.w;
        zmin = min(zmin, q.z);
        lo = min(lo, q.xy);
        hi = max(hi, q.xy);
    }
    let W = frame.screen.x;
    let H = frame.screen.y;
    let pad = cfg.eps.y;
    let x0 = clamp((lo.x * 0.5 + 0.5) * W - pad, 0.0, W - 0.01);
    let x1 = clamp((hi.x * 0.5 + 0.5) * W + pad, 0.0, W - 0.01);
    let y0 = clamp((0.5 - hi.y * 0.5) * H - pad, 0.0, H - 0.01);
    let y1 = clamp((0.5 - lo.y * 0.5) * H + pad, 0.0, H - 0.01);
    var lvl = 0u;
    var size = 2.0;
    var ix0 = u32(x0 / size);
    var ix1 = u32(x1 / size);
    var iy0 = u32(y0 / size);
    var iy1 = u32(y1 / size);
    loop {
        if ((ix1 - ix0 <= 1u && iy1 - iy0 <= 1u) || lvl + 1u >= cfg.hz.x) {
            break;
        }
        lvl = lvl + 1u;
        size = size * 2.0;
        ix0 = u32(x0 / size);
        ix1 = u32(x1 / size);
        iy0 = u32(y0 / size);
        iy1 = u32(y1 / size);
    }
    if (lvl > 0u) {                    // one level finer: at most 4 x 4 texels, tighter footprint
        lvl = lvl - 1u;
        size = size * 0.5;
        ix0 = u32(x0 / size);
        ix1 = u32(x1 / size);
        iy0 = u32(y0 / size);
        iy1 = u32(y1 / size);
    }
    let dim = textureDimensions(hzb, i32(lvl));
    ix1 = min(ix1, dim.x - 1u);
    iy1 = min(iy1, dim.y - 1u);
    ix0 = min(ix0, ix1);
    iy0 = min(iy0, iy1);
    var fmax = 0.0;
    for (var yy = iy0; yy <= iy1; yy = yy + 1u) {
        for (var xx = ix0; xx <= ix1; xx = xx + 1u) {
            fmax = max(fmax, textureLoad(hzb, vec2<u32>(xx, yy), i32(lvl)).r);
        }
    }
    return zmin > fmax + cfg.eps.x;
}

fn cluster_ntri(rr0: vec4<u32>, rr1: vec4<u32>, c: u32) -> u32 {
    let j = c - rr1.x;
    return min(64u, rr0.w - 64u * j);
}

var<workgroup> wg_s: array<u32, 64>;              // scan of the workgroup's survivors: count of class 0 in the low 16 bits, of class 1 in the high 16
var<workgroup> sc_s: array<u32, 256>;             // cull_scan

fn run_phase(wid: vec3<u32>, li: u32, phase2: bool) {
    let g = sel.x;
    let row = ptab_at(g);
    let c = row.x + (wid.y * 32768u + wid.x) * 64u + li;
    var keep = false;
    var ntri = 0u;
    var cls = 0u;                   // 0: wholly kept side (or no cut), 1: straddles, 2: wholly removed
    let stat = cfg.hz.y != 0u;
    if (c < row.y) {
        let r = cl_range_at(c);
        if (range_active_at(r) != 0u) {
            let rr0 = rng_at(2u * r);
            let rr1 = rng_at(2u * r + 1u);
            let part = rr0.x;
            let bx = cluster_box(c, part);
            let mvp = frame.vp * part_matrix(part);
            let nt = cluster_ntri(rr0, rr1, c);
            if (cfg.cl.x != 0u) {
                cls = cluster_clip_class(part_matrix(part), bx, part);
            }
            if (!phase2 && stat) {
                atomicAdd(&cra[lay.c.y + ST_ACTIVE], 1u);
            }
            if (cfg.eps.z > 0.5) {
                // accept all: phase 1 draws the whole range, phase 2 nothing; the flags make the next phase-1 frame draw them too.
                // A cluster wholly on the removed side of the cut planes is still not drawn.
                keep = !phase2 && cls != 2u;
                if (!phase2) {
                    crw[lay.e.y + c] = 1u;
                }
                if (keep) {
                    ntri = nt;
                    if (stat) {
                        atomicAdd(&cra[lay.c.y + ST_P1], 1u);
                        atomicAdd(&cra[lay.c.y + ST_P1_TRIS], nt);
                    }
                }
            } else if (frustum_pass(mvp, bx)) {
                if (!phase2 && stat) {
                    atomicAdd(&cra[lay.c.y + ST_FRUSTUM], 1u);
                    atomicAdd(&cra[lay.c.y + ST_FRUSTUM_TRIS], nt);
                }
                if (!phase2) {
                    keep = crw[lay.e.x + c] != 0u && cls != 2u;
                } else {
                    // phase 2 tests every cluster that passed the frustum, drawn in phase 1 or not: the ones that
                    // survive are next frame's phase 1; only the ones phase 1 did not draw are drawn now
                    let was = crw[lay.e.x + c] != 0u;
                    if (!was && stat) {
                        atomicAdd(&cra[lay.c.y + ST_P2_TESTED], 1u);
                    }
                    if (!occluded(mvp, bx)) {
                        crw[lay.e.y + c] = 1u;
                        keep = !was && cls != 2u;
                    }
                }
                if (keep) {
                    ntri = nt;
                    if (stat) {
                        atomicAdd(&cra[lay.c.y + select(ST_P1, ST_P2, phase2)], 1u);
                        atomicAdd(&cra[lay.c.y + select(ST_P1_TRIS, ST_P2_TRIS, phase2)], nt);
                    }
                }
            }
        }
    }
    // The lists are per (page, class): list v = page + G * class, with G = lay.e.w pages. Class 1 only exists while cfg.cl.x is set.
    // Deterministic order: the survivors of a list keep the cluster order (the order of the plain draw), whatever the scheduling. The rank
    // of a survivor inside its workgroup comes from an inclusive scan (no atomics); the workgroup's counts go to wgcnt, cull_scan turns
    // them into the offsets of the list, and cull_fill writes the entries (the flag word of the cluster carries class and rank).
    let kc = min(cls, 1u);
    let v = select(0u, select(1u, 65536u, kc == 1u), keep);
    wg_s[li] = v;
    workgroupBarrier();
    var s = v;
    for (var d = 1u; d < 64u; d = d << 1u) {
        var o = 0u;
        if (li >= d) {
            o = wg_s[li - d];
        }
        workgroupBarrier();
        s = s + o;
        wg_s[li] = s;
        workgroupBarrier();
    }
    if (c < row.y) {
        let rank = ((s - v) >> (16u * kc)) & 0xffffu;
        crw[lay.d.y + c] = select(0u, (rank + 1u) | (kc << 30u), keep);
    }
    if (li == 0u) {
        let tot = wg_s[63];
        let wi = lay.d.w + 2u * (pinfo_at(g).w + wid.y * 32768u + wid.x);
        crw[wi] = tot & 0xffffu;
        crw[wi + 1u] = tot >> 16u;
    }
}

@compute @workgroup_size(64)
fn cull_p1(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    run_phase(wid, li, false);
}

@compute @workgroup_size(64)
fn cull_p2(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    run_phase(wid, li, true);
}

// Offsets of the lists (one workgroup per list v = page + pages * class): the exclusive scan of the per-workgroup survivor counts in
// workgroup order, started at the list's counter (phase 2 continues after phase 1); the counter ends at the list's new length.
@compute @workgroup_size(256)
fn cull_scan(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let pages = lay.e.w;
    let g = wid.x % pages;
    let q = wid.x / pages;
    let row = ptab_at(g);
    let nwg = (row.y - row.x + 63u) / 64u;
    let wb = pinfo_at(g).w;
    var carry = atomicLoad(&cra[lay.c.x + wid.x * 8u]);
    for (var t = 0u; t < nwg; t = t + 256u) {
        let i = t + li;
        var x = 0u;
        if (i < nwg) {
            x = crw[lay.d.w + 2u * (wb + i) + q];
        }
        sc_s[li] = x;
        workgroupBarrier();
        var s = x;
        for (var d = 1u; d < 256u; d = d << 1u) {
            var o = 0u;
            if (li >= d) {
                o = sc_s[li - d];
            }
            workgroupBarrier();
            s = s + o;
            sc_s[li] = s;
            workgroupBarrier();
        }
        if (i < nwg) {
            crw[lay.d.w + 2u * (wb + i) + q] = carry + (s - x);
        }
        carry = carry + sc_s[255];
        workgroupBarrier();
    }
    if (li == 0u) {
        atomicStore(&cra[lay.c.x + wid.x * 8u], carry);
    }
}

// Writes the entries of the survivors of a phase at (offset of the workgroup + rank) of their list.
@compute @workgroup_size(64)
fn cull_fill(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let g = sel.x;
    let row = ptab_at(g);
    let c = row.x + (wid.y * 32768u + wid.x) * 64u + li;
    if (c >= row.y) {
        return;
    }
    let f = crw[lay.d.y + c];
    if (f == 0u) {
        return;
    }
    let kc = f >> 30u;
    let rank = (f & 0x3fffffffu) - 1u;
    let base = crw[lay.d.w + 2u * (pinfo_at(g).w + wid.y * 32768u + wid.x) + kc];
    let rowc = ptab_at(g + kc * lay.e.w);
    let b = base + rank;
    if (b < rowc.w) {
        let r = cl_range_at(c);
        let rr0 = rng_at(2u * r);
        let rr1 = rng_at(2u * r + 1u);
        crl[rowc.z + b] = vec4<u32>(c, rr0.z + 192u * (c - rr1.x), rr0.x, cluster_ntri(rr0, rr1, c) | (part_meta_at(rr0.x).w << 8u));
    }
}

// Finalize of a phase, ONE thread for all pages. The compact index buffer (lay.e.z slots of 64 triangles, shared by both phases: the
// gather of phase 2 only runs after pass 1 has finished reading it) is split between the pages in proportion to their visible slots
// when the phase does not fit (the lists of both classes of a page share its pinfo); a page that cannot use an indexed draw (pinfo.y == 0) takes none. The first `fit` slots of a page's
// list are gathered into the compact buffer and drawn indexed; the others are drawn by the pulled non-indexed draw.
fn fin_all(ph: u32) {
    let G = lay.e.w * select(1u, 2u, cfg.cl.x != 0u);       // lists: page + pages * class
    let budget = lay.e.z;
    var total = 0u;
    for (var g = 0u; g < G; g = g + 1u) {
        let row = ptab_at(g);
        let n = min(atomicLoad(&cra[lay.c.x + g * 8u]), row.w);
        if (pinfo_at(g % lay.e.w).y != 0u) {
            total += n - atomicLoad(&cra[lay.c.x + g * 8u + 1u]);
        }
    }
    var used = 0u;
    for (var g = 0u; g < G; g = g + 1u) {
        let row = ptab_at(g);
        let cnt = atomicLoad(&cra[lay.c.x + g * 8u]);
        if (cnt > row.w) {
            atomicAdd(&cra[lay.c.y + ST_OVERFLOW], cnt - row.w);
        }
        let n = min(cnt, row.w);
        let begin = atomicLoad(&cra[lay.c.x + g * 8u + 1u]);
        let m = n - begin;
        var fit = 0u;
        if (pinfo_at(g % lay.e.w).y != 0u) {
            fit = m;
            if (total > budget) {
                fit = min(m, u32(f32(m) * (f32(budget) / f32(total))));
            }
            fit = min(fit, budget - used);
        }
        let cs = used;
        used += fit;
        let ai = g * 2u + ph;
        let a = lay.d.x + ai * 16u;
        // drawIndexedIndirect: index count, instance count, first index, base vertex, first instance (the last two stay 0)
        crw[a] = fit * 192u;
        crw[a + 1u] = 1u;
        crw[a + 2u] = cs * 192u;
        crw[a + 3u] = 0u;
        crw[a + 4u] = 0u;
        // drawIndirect: vertex count, instance count, first vertex, first instance. first_vertex stays 0 (not every backend adds it to
        // vertex_index in an indirect draw); the shader adds dinfo (the list slot of the draw's first cluster).
        crw[a + 8u] = (m - fit) * 192u;
        crw[a + 9u] = 1u;
        crw[a + 10u] = 0u;
        crw[a + 11u] = 0u;
        // gather dispatch: one workgroup per slot, 2D (the shaders index y * 32768 + x)
        crw[a + 12u] = min(fit, 32768u);
        crw[a + 13u] = (fit + 32767u) / 32768u;
        crw[a + 14u] = 1u;
        crw[lay.d.z + ai * 2u] = row.z + begin;
        crw[lay.d.z + ai * 2u + 1u] = row.z + begin + fit;
        atomicStore(&cra[lay.c.x + g * 8u + 1u], n);
        atomicAdd(&cra[lay.c.y + ST_KEPT], m);
        atomicAdd(&cra[lay.c.y + ST_PULLED], m - fit);
        if (cfg.hz.y != 0u) {
            atomicAdd(&cra[lay.c.y + ST_IDX], fit);
            atomicAdd(&cra[lay.c.y + ST_PULL], m - fit);
        }
    }
}

@compute @workgroup_size(1)
fn finalize_p1() {
    fin_all(0u);
}

@compute @workgroup_size(1)
fn finalize_p2() {
    fin_all(1u);
}
