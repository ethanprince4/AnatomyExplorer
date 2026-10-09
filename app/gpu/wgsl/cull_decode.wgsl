// For the resolve pass: turn an id written by cull_vis.wgsl into the renderer's own (draw slot, primitive) pair, so
// everything after it stays as it is. cull.py replaces __GROUP__ with the bind group index the renderer reserves.
//   ids with bit 31 clear are the renderer's own ids ((slot << bits) | primitive) and need no decoding.
// bits = the renderer's primitive bits (frame.info.x); the part's first draw slot (per part, set by the renderer when it
// passes the frame's parts to ClusterCuller.encode) plus (triangle >> bits) is the slot that holds the triangle.

// Bindings of group __GROUP__: 0 cro, 1 crw (read only), 2 cd_perm, 3 lay; cull.py decode_bind_group_entries() lists them
// (cull_tables.wgsl, which must be included in the same module, defines the table layout).
@group(__GROUP__) @binding(0) var<storage, read> cro: array<vec4<u32>>;
@group(__GROUP__) @binding(1) var<storage, read> crw: array<u32>;
@group(__GROUP__) @binding(2) var<storage, read> cd_perm: array<u32>;
@group(__GROUP__) @binding(3) var<uniform> lay: CullLay;
fn crw_w(i: u32) -> u32 { return crw[i]; }

fn cull_is_culled(id: u32) -> bool {
    return (id & 0x80000000u) != 0u;
}

fn cull_decode(id: u32, bits: u32) -> vec2<u32> {
    let s = (id & 0x7fffffffu) >> 6u;
    let c = slot_cluster_at(s);
    let r = cl_range_at(c);
    let rr0 = rng_at(2u * r);
    let rr1 = rng_at(2u * r + 1u);
    let tri = cd_perm[rr1.y + 64u * (c - rr1.x) + (id & 63u)];
    let slot0 = part_meta_at(rr0.x).z;
    return vec2<u32>(slot0 + (tri >> bits), tri & ((1u << bits) - 1u));
}
