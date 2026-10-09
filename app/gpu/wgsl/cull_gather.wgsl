// Gather of the compact index buffer: for each of the first `fit` slots of a page's visible-cluster list (finalize_p* decides how
// many fit the budget) copy the cluster's 64 triangle slots, 192 index words, to compact slot cs + k. One workgroup per slot,
// one thread per word (coalesced reads of the page's index section, coalesced writes). Words are
//     page-local vertex | (part ordinal << dsel.y)      (cull_idx.wgsl decodes them)
// and the slots of triangles past the cluster's count repeat corner 0 of triangle 0 (a zero-area triangle).
//
// Concatenated by app/gpu/cull.py after the page prelude (geom_prelude(1, 1, 0, uniform_binding=1)) and geom.wgsl. Dispatched indirectly from crw (words 12..14 of the (page, phase) record). Storage buffers: crl, crw, cidx, the page = 4.

// the part of cull_tables.wgsl's CullLay this shader reads (the struct must match; the tables themselves are not needed here)
struct CullLay {
    a: vec4<u32>,
    b: vec4<u32>,
    c: vec4<u32>,
    d: vec4<u32>,
    e: vec4<u32>,
};

@group(0) @binding(0) var<uniform> lay: CullLay;
@group(0) @binding(1) var<storage, read> crl: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> crw: array<u32>;                 // read only: this dispatch's indirect source too
@group(0) @binding(3) var<storage, read_write> cidx: array<u32>;
// group 1: the geometry page + offsets
@group(2) @binding(0) var<uniform> dsel: vec4<u32>;                      // x: page * 2 + phase, y: vertex bits

@compute @workgroup_size(192)
fn gather(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let a = lay.d.x + dsel.x * 16u;
    let k = wid.y * 32768u + wid.x;
    let fit = crw[a] / 192u;
    if (k >= fit) {
        return;
    }
    let e = crl[crw[lay.d.z + dsel.x * 2u] + k];
    var w = e.y;
    if (li / 3u < (e.w & 255u)) {
        w = e.y + li;
    }
    cidx[crw[a + 2u] + k * 192u + li] = g_index(0u, w) | ((e.w >> 8u) << dsel.y);
}
