// Copies the triangles of the clusters a phase kept into the page's compacted index buffer: block b (64 triangles =
// 192 indices) is written by one workgroup, thread t writes triangle t. Short clusters are padded with degenerate
// triangles (three copies of the first vertex), which the rasteriser drops. Dispatched indirectly with the size
// cull_test.wgsl's finalize wrote (args holds the block range of the phase).
// Concatenated after cull_tables.wgsl, the page prelude (geometry.py geom_prelude) and geom.wgsl.

@group(0) @binding(0) var<storage, read> cro: array<vec4<u32>>;           // cull_tables.wgsl
@group(0) @binding(1) var<storage, read> crw: array<u32>;                 // read only: it is also the indirect-dispatch source
@group(0) @binding(2) var<storage, read> perm: array<u32>;
@group(0) @binding(3) var<uniform> lay: CullLay;
@group(1) @binding(0) var<uniform> sel: vec4<u32>;                       // x: page, y: phase
// group 1 binding 1: the geometry page (geom_prelude(1, 1, 1, uniform_binding=3): geo_0, pgo), read through geom.wgsl
@group(1) @binding(2) var<storage, read_write> compact: array<u32>;
fn crw_w(i: u32) -> u32 { return crw[i]; }

@compute @workgroup_size(64)
fn gather(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) t: u32) {
    let ai = sel.x * 2u + sel.y;
    let m = crw[lay.d.x + ai * 8u] / 192u;
    let begin = crw[lay.d.x + ai * 8u + 2u] / 192u;
    let k = wid.y * 32768u + wid.x;
    if (k >= m) {
        return;
    }
    let blk = begin + k;
    let row = ptab_at(sel.x);
    let c = slot_cluster_at(row.z + blk);
    let r = cl_range_at(c);
    let rr0 = rng_at(2u * r);
    let rr1 = rng_at(2u * r + 1u);
    let j = c - rr1.x;
    let ntri = min(64u, rr0.w - 64u * j);
    let pbase = rr1.y + 64u * j;
    let o = (blk * 64u + t) * 3u;
    if (t < ntri) {
        let f = rr0.z + 3u * perm[pbase + t];
        compact[o] = g_index(0u, f);
        compact[o + 1u] = g_index(0u, f + 1u);
        compact[o + 2u] = g_index(0u, f + 2u);
    } else {
        let v = g_index(0u, rr0.z + 3u * perm[pbase]);
        compact[o] = v;
        compact[o + 1u] = v;
        compact[o + 2u] = v;
    }
}
