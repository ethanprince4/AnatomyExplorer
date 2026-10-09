// For the resolve pass: turn an id written by cull_vis.wgsl into what the resolve needs. cull.py replaces __GROUP__ with the bind
// group index the renderer reserves.
//   ids with bit 31 clear are the renderer's own ids ((slot << bits) | primitive) and need no decoding.
//   id = 0x80000000 | (cluster << 6) | triangle-in-cluster. Geometry is stored in cluster order, so the stored triangle number
//   inside the (part, level) index range is 64 * (cluster - first cluster of its range) + triangle-in-cluster, and the triangle's
//   three index words are the ones at (range first index + 3 * stored triangle). No permutation table is needed on the GPU.
//
// Bindings of group __GROUP__ (cull.py decode_bind_group_entries() lists the buffers): 0 cro (read only storage, FRAGMENT),
// 1 lay (uniform). cull_tables.wgsl, which must be included in the same module, defines the table layout. ONE storage buffer.
@group(__GROUP__) @binding(0) var<storage, read> cro: array<vec4<u32>>;
@group(__GROUP__) @binding(1) var<uniform> lay: CullLay;

fn cull_is_culled(id: u32) -> bool {
    return (id & 0x80000000u) != 0u;
}

struct CullTri {
    part: u32,        // model part index
    page: u32,        // geometry page of the part (the renderer's page number, as geometry.py numbers them)
    first: u32,       // page-local index word of the triangle's first corner (add geo_off(page, G_INDEX) for the page buffer word)
    tri: u32,         // stored triangle number inside the part's index range of the level that was drawn
};

fn cull_decode_tri(id: u32) -> CullTri {
    let c = (id & 0x7fffffffu) >> 6u;
    let r = cl_range_at(c);
    let rr0 = rng_at(2u * r);
    let rr1 = rng_at(2u * r + 1u);
    let t = 64u * (c - rr1.x) + (id & 63u);
    return CullTri(rr0.x, rr0.y, rr0.z + 3u * t, t);
}

// the renderer's own (draw slot, primitive) pair: slot0 of the part (set by the renderer through FrameParts.slot0) plus
// (triangle >> bits) is the slot that holds the triangle; bits = the renderer's primitive bits (frame.info.x)
fn cull_decode(id: u32, bits: u32) -> vec2<u32> {
    let d = cull_decode_tri(id);
    let slot0 = part_meta_at(d.part).z;
    return vec2<u32>(slot0 + (d.tri >> bits), d.tri & ((1u << bits) - 1u));
}
