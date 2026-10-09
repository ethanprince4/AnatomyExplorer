// Cluster culling kernels. Concatenated by app/gpu/cull.py after clip.wgsl (Frame, ClipParams) and cull_tables.wgsl
// (the table layout: cl_geom, cl_range, rng, part_xf, range_active, ptab, pstate, stats, args, disp, dinfo, slot_cluster, vis flags).
//
//   cull_p1   phase 1: clusters of the frame's parts that passed the frustum test AND were visible last frame
//   cull_p2   phase 2: clusters that passed the frustum test and were NOT drawn in phase 1, kept unless the depth
//             pyramid built from phase 1's real depth hides their bounding box
//   finalize_p1 / finalize_p2   one thread per page: draw and dispatch arguments of the phase
//
// A surviving cluster takes the next free block of its page (atomic, one global add per workgroup) and writes its id into
// slot_cluster[slot_base + block]; cull_gather.wgsl then copies the triangles into the page's compacted index buffer.
//
// Boxes. cl_geom holds the part-space box (centre, half extents) and dmax, the largest morph displacement |dpos| of the
// cluster. Half extents grow by |weight| * dmax (the part's current morph weight) and by 2e-6 of the coordinate size
// (float rounding); the box is transformed by the part matrix of this frame, which carries explode / node offsets.

struct Cfg {
    hz: vec4<u32>,          // x: hzb levels, y: 1 = count statistics, z: hzb width, w: hzb height (level 0)
    eps: vec4<f32>,         // x: depth margin, y: screen padding in pixels
};

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<uniform> cfg: Cfg;
@group(0) @binding(2) var<storage, read> cro: array<vec4<u32>>;           // cull_tables.wgsl
@group(0) @binding(3) var<storage, read_write> cra: array<atomic<u32>>;
@group(0) @binding(4) var<storage, read_write> crw: array<u32>;
@group(0) @binding(5) var<uniform> lay: CullLay;
fn crw_w(i: u32) -> u32 { return crw[i]; }
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

var<workgroup> wg_n: atomic<u32>;
var<workgroup> wg_base: u32;

fn run_phase(wid: vec3<u32>, li: u32, phase2: bool) {
    if (li == 0u) {
        atomicStore(&wg_n, 0u);
    }
    workgroupBarrier();
    let g = sel.x;
    let row = ptab_at(g);
    let c = row.x + (wid.y * 32768u + wid.x) * 64u + li;
    var keep = false;
    var ntri = 0u;
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
            if (!phase2 && stat) {
                atomicAdd(&cra[lay.c.y + ST_ACTIVE], 1u);
            }
            if (frustum_pass(mvp, bx)) {
                if (!phase2 && stat) {
                    atomicAdd(&cra[lay.c.y + ST_FRUSTUM], 1u);
                    atomicAdd(&cra[lay.c.y + ST_FRUSTUM_TRIS], nt);
                }
                if (!phase2) {
                    keep = crw[lay.e.x + c] != 0u;
                } else {
                    // phase 2 tests every cluster that passed the frustum, drawn in phase 1 or not: the ones that
                    // survive are next frame's phase 1; only the ones phase 1 did not draw are drawn now
                    let was = crw[lay.e.x + c] != 0u;
                    if (!was && stat) {
                        atomicAdd(&cra[lay.c.y + ST_P2_TESTED], 1u);
                    }
                    if (!occluded(mvp, bx)) {
                        crw[lay.e.y + c] = 1u;
                        keep = !was;
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
    var rank = 0u;
    if (keep) {
        rank = atomicAdd(&wg_n, 1u);
    }
    workgroupBarrier();
    if (li == 0u) {
        let n = atomicLoad(&wg_n);
        if (n > 0u) {
            wg_base = atomicAdd(&cra[lay.c.x + g * 8u], n);
        }
    }
    workgroupBarrier();
    if (keep) {
        let b = wg_base + rank;
        if (b < row.w) {
            crw[lay.d.w + row.z + b] = c;
        }
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

fn fin(g: u32, ph: u32) {
    let row = ptab_at(g);
    let cnt = atomicLoad(&cra[lay.c.x + g * 8u]);
    if (cnt > row.w) {
        atomicAdd(&cra[lay.c.y + ST_OVERFLOW], cnt - row.w);
    }
    let n = min(cnt, row.w);
    let begin = atomicLoad(&cra[lay.c.x + g * 8u + 1u]);
    let m = n - begin;
    let ai = g * 2u + ph;
    crw[lay.d.x + ai * 8u] = m * 192u;
    crw[lay.d.x + ai * 8u + 1u] = 1u;
    crw[lay.d.x + ai * 8u + 2u] = begin * 192u;
    crw[lay.d.x + ai * 8u + 3u] = 0u;
    crw[lay.d.x + ai * 8u + 4u] = 0u;
    crw[lay.d.y + ai * 4u] = min(m, 32768u);
    crw[lay.d.y + ai * 4u + 1u] = (m + 32767u) / 32768u;
    crw[lay.d.y + ai * 4u + 2u] = 1u;
    crw[lay.d.z + ai] = row.z + begin;
    atomicStore(&cra[lay.c.x + g * 8u + 1u], n);
}

@compute @workgroup_size(1)
fn finalize_p1(@builtin(global_invocation_id) gid: vec3<u32>) {
    fin(gid.x, 0u);
}

@compute @workgroup_size(1)
fn finalize_p2(@builtin(global_invocation_id) gid: vec3<u32>) {
    fin(gid.x, 1u);
}
