// Copies the triangles of the clusters a phase kept into the page's compacted index buffer: block b (64 triangles =
// 192 indices) is written by one workgroup, thread t writes triangle t. Short clusters are padded with degenerate
// triangles (three copies of the first vertex), which the rasteriser drops. Dispatched indirectly with the size
// cull_test.wgsl's finalize wrote (args holds the block range of the phase).

@group(0) @binding(0) var<storage, read> slot_cluster: array<u32>;
@group(0) @binding(1) var<storage, read> cl_range: array<u32>;
@group(0) @binding(2) var<storage, read> rng: array<vec4<u32>>;
@group(0) @binding(3) var<storage, read> perm: array<u32>;
@group(0) @binding(4) var<storage, read> ptab: array<vec4<u32>>;
@group(0) @binding(5) var<storage, read> args: array<u32>;
@group(1) @binding(0) var<uniform> sel: vec4<u32>;                       // x: page, y: phase
@group(1) @binding(1) var<storage, read> index_in: array<u32>;
@group(1) @binding(2) var<storage, read_write> compact: array<u32>;

@compute @workgroup_size(64)
fn gather(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) t: u32) {
    let ai = sel.x * 2u + sel.y;
    let m = args[ai * 8u] / 192u;
    let begin = args[ai * 8u + 2u] / 192u;
    let k = wid.y * 32768u + wid.x;
    if (k >= m) {
        return;
    }
    let blk = begin + k;
    let row = ptab[sel.x];
    let c = slot_cluster[row.z + blk];
    let r = cl_range[c];
    let rr0 = rng[2u * r];
    let rr1 = rng[2u * r + 1u];
    let j = c - rr1.x;
    let ntri = min(64u, rr0.w - 64u * j);
    let pbase = rr1.y + 64u * j;
    let o = (blk * 64u + t) * 3u;
    if (t < ntri) {
        let f = rr0.z + 3u * perm[pbase + t];
        compact[o] = index_in[f];
        compact[o + 1u] = index_in[f + 1u];
        compact[o + 2u] = index_in[f + 2u];
    } else {
        let v = index_in[rr0.z + 3u * perm[pbase]];
        compact[o] = v;
        compact[o + 1u] = v;
        compact[o + 2u] = v;
    }
}
