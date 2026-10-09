// For the resolve pass: turn an id written by cull_vis.wgsl into the renderer's own (draw slot, primitive) pair, so
// everything after it stays as it is. cull.py replaces __GROUP__ with the bind group index the renderer reserves.
//   ids with bit 31 clear are the renderer's own ids ((slot << bits) | primitive) and need no decoding.
// bits = the renderer's primitive bits (frame.info.x); the part's first draw slot (per part, set by the renderer when it
// passes the frame's parts to ClusterCuller.encode) plus (triangle >> bits) is the slot that holds the triangle.

@group(__GROUP__) @binding(0) var<storage, read> cd_slot_cluster: array<u32>;
@group(__GROUP__) @binding(1) var<storage, read> cd_cl_range: array<u32>;
@group(__GROUP__) @binding(2) var<storage, read> cd_rng: array<vec4<u32>>;
@group(__GROUP__) @binding(3) var<storage, read> cd_perm: array<u32>;
@group(__GROUP__) @binding(4) var<storage, read> cd_part_xf: array<vec4<f32>>;

fn cull_is_culled(id: u32) -> bool {
    return (id & 0x80000000u) != 0u;
}

fn cull_decode(id: u32, bits: u32) -> vec2<u32> {
    let s = (id & 0x7fffffffu) >> 6u;
    let c = cd_slot_cluster[s];
    let r = cd_cl_range[c];
    let rr0 = cd_rng[2u * r];
    let rr1 = cd_rng[2u * r + 1u];
    let tri = cd_perm[rr1.y + 64u * (c - rr1.x) + (id & 63u)];
    let slot0 = bitcast<u32>(cd_part_xf[rr0.x * 5u + 4u].z);
    return vec2<u32>(slot0 + (tri >> bits), tri & ((1u << bits) - 1u));
}
