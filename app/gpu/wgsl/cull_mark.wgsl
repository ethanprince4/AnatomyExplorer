// Visibility record for the next frame: the clusters that own at least one sample of the final id image.
//   mark   one thread per pixel: flag the block slot of every culled id (bit 31) found in any sample
//   apply  one thread per slot: flagged slot -> vis_next[cluster] = 1, clear the flag, count truly visible clusters
// cull.py prepends: `const SAMPLES: u32;`, the id texture declaration `@group(0) @binding(0) var vis_id: ...` and
// `fn load_id(p: vec2<i32>, s: i32) -> u32`.

@group(0) @binding(1) var<storage, read_write> seen: array<atomic<u32>>;
@group(0) @binding(2) var<storage, read_write> vis_next: array<u32>;
@group(0) @binding(3) var<storage, read> slot_cluster: array<u32>;
@group(0) @binding(4) var<storage, read_write> stats: array<atomic<u32>>;
@group(0) @binding(5) var<storage, read> cl_range: array<u32>;
@group(0) @binding(6) var<storage, read> rng: array<vec4<u32>>;
@group(0) @binding(7) var<uniform> nslots: vec4<u32>;                    // x: slot count

const ST_VISIBLE: u32 = 9u;
const ST_VISIBLE_TRIS: u32 = 10u;

@compute @workgroup_size(8, 8)
fn mark(@builtin(global_invocation_id) gid: vec3<u32>) {
    let d = vec2<u32>(textureDimensions(vis_id));
    if (gid.x >= d.x || gid.y >= d.y) {
        return;
    }
    var prev = 0u;
    for (var s = 0; s < i32(SAMPLES); s = s + 1) {
        let id = load_id(vec2<i32>(gid.xy), s);
        if ((id & 0x80000000u) != 0u && id != prev) {
            let k = (id & 0x7fffffffu) >> 6u;
            if (atomicLoad(&seen[k]) == 0u) {
                atomicStore(&seen[k], 1u);
            }
        }
        prev = id;
    }
}

@compute @workgroup_size(64)
fn apply(@builtin(global_invocation_id) gid: vec3<u32>, @builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let s = (wid.y * 32768u + wid.x) * 64u + li;
    if (s >= nslots.x) {
        return;
    }
    if (atomicLoad(&seen[s]) != 0u) {
        atomicStore(&seen[s], 0u);
        let c = slot_cluster[s];
        vis_next[c] = 1u;
        let r = cl_range[c];
        let rr1 = rng[2u * r + 1u];
        let rr0 = rng[2u * r];
        atomicAdd(&stats[ST_VISIBLE], 1u);
        atomicAdd(&stats[ST_VISIBLE_TRIS], min(64u, rr0.w - 64u * (c - rr1.x)));
    }
}
