// Cut-face cluster lists: which clusters of a cut part can contribute a pixel to the cap passes, written as dense lists of index
// words that the passes draw with indirect indexed draws.
//
// The parity and cap passes (caps_gather.wgsl) run the clip test on every fragment, so a cluster wholly on the removed side of the
// planes costs vertex work, triangle setup and fragments for nothing. Per cluster, with the box and plane arithmetic of
// cull_test.wgsl (cluster_clip_class; app/gpu/cutclass.py is the CPU twin and says why the classes are conservative), the class is
//     0 KEPT      every fragment is on the kept side: no clip test needed (parity: no fragment stage at all)
//     1 STRADDLE  anything else
//     2 REMOVED   every fragment is discarded by the clip test in both passes: nothing of it can reach any target
// and two lists are written per part (a cluster is 64 triangles = 192 index words, the part's index range is cluster ordered,
// clusters.py: cluster j of the part is the words first + 192 j ..; a partial last cluster is padded with zero-area triangles made
// of the part's first index):
//     region 0  cap pass     the KEPT and STRADDLE clusters in the part's cluster order (the cap pass is not order free: ties of the
//                            24-bit cap key keep the first fragment, so the original draw order is kept)
//     region 1  parity pass  the KEPT clusters from the front of the part's slots (drawn without a fragment stage: early depth
//                            rejection), the STRADDLE clusters from the back, in reverse order (with the clip test; the parity
//                            minimum does not depend on the draw order)
// The words are page-local vertex numbers (g_index: compressed pages decode here), so the draws are indexed in both page layouts.
//
// Three dispatches (caps.py encode_gather): cap_class classifies the clusters, 256 per workgroup, and scans the lists' ranks inside
// the workgroup; cap_offsets turns the workgroup totals into per-workgroup offsets and writes the indirect draw arguments; cap_fill
// (one workgroup per cluster slot, one thread per word) writes the words. Deterministic: no atomics.
//
// Concatenated by app/gpu/caps.py after caps_common.wgsl, the page prelude (geom_prelude(1, 2, 0, uniform_binding=1)) and geom.wgsl.
//   group 0: 0 CapFrame  1 CapDraw table  2 CapCull
//   group 1: 0 cluster boxes (cx cy cz dmax | hx hy hz 0)  1 table of the listed parts  2 table of the chunks  3 cluster info
//            4 chunk totals / offsets  5 indirect arguments  6 output (2 regions of `w.x` words)    (each dispatch binds a subset)
//   group 2: the page   group 3: 0 page dispatch record (dynamic offset)

struct CapCull {
    p0: vec4<f32>,
    p1: vec4<f32>,
    p2: vec4<f32>,
    on: vec4<u32>,          // enabled planes x y z, w: 1 = corner (removed where every enabled plane is negative)
    prm: vec4<f32>,         // tan(half fov y) (half height orthographic), margin in pixels, render height, 1 = orthographic
    w: vec4<u32>,           // x: words per region, y: chunks, z: parts
};

@group(0) @binding(0) var<uniform> cf: CapFrame;
@group(0) @binding(1) var<storage, read> cdraws: array<CapDraw>;
@group(0) @binding(2) var<uniform> cc: CapCull;
@group(1) @binding(0) var<storage, read> clg: array<vec4<f32>>;
@group(1) @binding(1) var<storage, read> ctab: array<vec4<u32>>;         // per part 2 vec4: (draw, first cluster, clusters, first index) (index count, first slot, first chunk, 0)
@group(1) @binding(2) var<storage, read> chk: array<vec2<u32>>;          // per chunk: (part, first cluster of the chunk within the part)
@group(1) @binding(3) var<storage, read_write> cinfo: array<u32>;        // per slot: class | KEPT rank in its chunk << 2 | STRADDLE rank << 12
@group(1) @binding(4) var<storage, read_write> ctot: array<u32>;         // per chunk (KEPT, STRADDLE): totals, then offsets in the part
@group(1) @binding(5) var<storage, read_write> args: array<u32>;         // per part 16 words: 3 indexed indirect draws of 5 words (cap, kept, straddle)
@group(1) @binding(6) var<storage, read_write> mout: array<u32>;
@group(3) @binding(0) var<uniform> pg: vec4<u32>;                        // first table entry of the page, one past the last, first slot, slots

fn plane_range(P: vec4<f32>, wc: vec3<f32>, m: mat4x4<f32>, h: vec3<f32>, mg: f32) -> vec2<f32> {
    let s = dot(P.xyz, wc) + P.w;
    let r = abs(dot(P.xyz, m[0].xyz)) * h.x + abs(dot(P.xyz, m[1].xyz)) * h.y + abs(dot(P.xyz, m[2].xyz)) * h.z;
    let e = 3e-5 * (abs(P.x * wc.x) + abs(P.y * wc.y) + abs(P.z * wc.z) + abs(P.w) + r) + mg * length(P.xyz);
    return vec2<f32>(s - r - e, s + r + e);
}

fn cluster_class(m: mat4x4<f32>, c: u32) -> u32 {
    let g0 = clg[2u * c];
    let g1 = clg[2u * c + 1u];
    let h = g1.xyz + 2e-6 * (abs(g0.xyz) + g1.xyz);
    let wc = (m * vec4<f32>(g0.xyz, 1.0)).xyz;
    var mg: f32;
    if (cc.prm.w > 0.5) {
        mg = cc.prm.y * 2.0 * cc.prm.x / cc.prm.z;
    } else {
        let R = length(m[0].xyz) * h.x + length(m[1].xyz) * h.y + length(m[2].xyz) * h.z;
        let depth = -(cf.view * vec4<f32>(wc, 1.0)).z;
        if (depth - R <= 1e-4) {
            mg = 1e30;
        } else {
            mg = cc.prm.y * 2.0 * cc.prm.x * (depth + R) / cc.prm.z;
        }
    }
    var n = 0u;
    var any_kept = false;
    var all_kept = true;
    var any_gone = false;
    var all_gone = true;
    for (var i = 0u; i < 3u; i = i + 1u) {
        if (cc.on[i] != 1u) {
            continue;
        }
        var P = cc.p0;
        if (i == 1u) { P = cc.p1; }
        if (i == 2u) { P = cc.p2; }
        let v = plane_range(P, wc, m, h, mg);
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
    if (cc.on.w == 1u) {
        if (any_kept) { return 0u; }
        if (all_gone) { return 2u; }
        return 1u;
    }
    if (any_gone) { return 2u; }
    if (all_kept) { return 0u; }
    return 1u;
}

var<workgroup> sc: array<u32, 256>;
var<workgroup> s_e: u32;
var<workgroup> s_dead: u32;

@compute @workgroup_size(256)
fn cap_class(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let c = wid.y * 32768u + wid.x;
    if (c >= cc.w.y) {
        return;
    }
    let ch = chk[c];
    let e0 = ctab[2u * ch.x];
    let e1 = ctab[2u * ch.x + 1u];
    let j = ch.y + li;
    var cls = 3u;
    var v = 0u;
    if (j < e0.z) {
        cls = cluster_class(cdraws[e0.x].model, e0.y + j);
        v = select(0u, 1u, cls == 0u) | select(0u, 65536u, cls == 1u);
    }
    sc[li] = v;
    workgroupBarrier();
    for (var d = 1u; d < 256u; d = d << 1u) {                       // inclusive scan of (KEPT count, STRADDLE count << 16)
        var t = 0u;
        if (li >= d) {
            t = sc[li - d];
        }
        workgroupBarrier();
        sc[li] = sc[li] + t;
        workgroupBarrier();
    }
    let inc = sc[li];
    if (j < e0.z) {
        let ex = inc - v;
        cinfo[e1.y + j] = cls | ((ex & 0xFFFFu) << 2u) | ((ex >> 16u) << 12u);
    }
    if (li == 255u) {
        ctot[2u * c] = inc & 0xFFFFu;
        ctot[2u * c + 1u] = inc >> 16u;
    }
}

@compute @workgroup_size(64)
fn cap_offsets(@builtin(global_invocation_id) gid: vec3<u32>) {
    let t = gid.x;
    if (t >= cc.w.z) {
        return;
    }
    let e0 = ctab[2u * t];
    let e1 = ctab[2u * t + 1u];
    let nch = (e0.z + 255u) / 256u;
    var ko = 0u;
    var so = 0u;
    for (var c = 0u; c < nch; c = c + 1u) {
        let i = e1.z + c;
        let k = ctot[2u * i];
        let s = ctot[2u * i + 1u];
        ctot[2u * i] = ko;
        ctot[2u * i + 1u] = so;
        ko = ko + k;
        so = so + s;
    }
    let w = cc.w.x;
    let a = t * 16u;
    args[a] = (ko + so) * 192u;                                      // cap: KEPT and STRADDLE in order
    args[a + 1u] = 1u;
    args[a + 2u] = e1.y * 192u;
    args[a + 3u] = 0u;
    args[a + 4u] = 0u;
    args[a + 5u] = ko * 192u;                                        // parity, KEPT: the front of the part's slots
    args[a + 6u] = 1u;
    args[a + 7u] = w + e1.y * 192u;
    args[a + 8u] = 0u;
    args[a + 9u] = 0u;
    args[a + 10u] = so * 192u;                                       // parity, STRADDLE: the back
    args[a + 11u] = 1u;
    args[a + 12u] = w + (e1.y + e0.z - so) * 192u;
    args[a + 13u] = 0u;
    args[a + 14u] = 0u;
}

@compute @workgroup_size(192)
fn cap_fill(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let sl = wid.y * 32768u + wid.x;
    if (sl >= pg.w) {
        return;
    }
    let k = pg.z + sl;
    if (li == 0u) {
        var lo = pg.x;
        var hi = pg.y;
        while (hi - lo > 1u) {                                        // last entry whose first slot is <= k
            let mid = (lo + hi) / 2u;
            if (ctab[2u * mid + 1u].y <= k) { lo = mid; } else { hi = mid; }
        }
        s_e = lo;
        s_dead = g_index(0u, ctab[2u * lo].w);
    }
    workgroupBarrier();
    let info = cinfo[k];
    let cls = info & 3u;
    if (cls == 2u) {
        return;
    }
    let e0 = ctab[2u * s_e];
    let e1 = ctab[2u * s_e + 1u];
    let j = k - e1.y;
    let ch = e1.z + j / 256u;
    let rk = ctot[2u * ch] + ((info >> 2u) & 1023u);                  // clusters of each list before this one
    let rs = ctot[2u * ch + 1u] + ((info >> 12u) & 1023u);
    var v = s_dead;
    if (li < min(192u, e1.x - 192u * j)) {
        v = g_index(0u, e0.w + 192u * j + li);
    }
    let w = cc.w.x;
    mout[(e1.y + rk + rs) * 192u + li] = v;
    if (cls == 0u) {
        mout[w + (e1.y + rk) * 192u + li] = v;
    } else {
        mout[w + (e1.y + e0.z - 1u - rs) * 192u + li] = v;
    }
}
