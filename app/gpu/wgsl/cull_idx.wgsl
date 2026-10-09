// Visibility pass of the culled clusters, indexed draw over the compact index buffer (cull_gather.wgsl fills it): ONE indexed indirect
// draw per page and phase for the list slots inside the budget; the slots over it are drawn by cull_vis.wgsl (same ids, same clip
// position, same render pass).
//
// Concatenated by app/gpu/cull.py after: `enable primitive_index;`, the id prelude (alias IdOut, fn pack_id), clip.wgsl,
// cull_tables.wgsl, the page prelude (geometry.py geom_prelude(1, 1, 0, uniform_binding=1)) and geom.wgsl.
//
// The compact buffer holds, for slot k of the draw, 192 index words: the three corners of the cluster's 64 triangles (triangles past
// the cluster's count repeat corner 0 of triangle 0: zero area, they keep primitive_index counting). A word is
//     page-local vertex | (ordinal of the vertex's part in its page << dsel.y)
// so the vertex shader finds the part (its matrix) without a per-vertex table: pgp maps (page, ordinal) to the model part. The index
// value is a function of the vertex alone, so the post-transform cache of the hardware works as in a plain draw.
//
// The clip position is the pulled path's and the plain draw's: frame.vp * (M * pos). The fragment shader derives the id from the
// primitive: primitive_index counts from 0 in this draw, 64 per slot (padding included), so slot = first slot of the draw +
// primitive_index / 64 (dinfo, written by finalize), cluster = crl[slot].x, triangle in the cluster = primitive_index % 64.
//     id = 0x80000000 | (cluster << 6) | triangle        (exactly cull_vis.wgsl's)
// Storage buffers: vertex stage cro + the page = 2, fragment stage crw + crl = 2.

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read> cro: array<vec4<u32>>;           // cull_tables.wgsl (vertex stage)
@group(0) @binding(2) var<storage, read> crw: array<u32>;                 // dinfo (fragment stage; also the indirect draw source)
@group(0) @binding(3) var<uniform> lay: CullLay;
@group(0) @binding(4) var<storage, read> crl: array<vec4<u32>>;           // visible-cluster entries (fragment stage)
// group 1 binding 0: the geometry page, binding 1 its offsets (geom_prelude(1, 1, 0, uniform_binding=1), read through geom.wgsl)
@group(2) @binding(0) var<uniform> dsel: vec4<u32>;                      // x: page * 2 + phase, y: vertex bits, z: first pgp entry of the page

const CULL_TAG: u32 = 0x80000000u;

fn part_matrix(part: u32) -> mat4x4<f32> {
    let b = part * 5u;
    return mat4x4<f32>(part_xf_at(b), part_xf_at(b + 1u), part_xf_at(b + 2u), part_xf_at(b + 3u));
}

fn world_of(m: mat4x4<f32>, v: u32) -> vec3<f32> {
    let p = g_pos(0u, v);
    return (m * vec4<f32>(p, 1.0)).xyz;
}

struct VOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,
    @location(1) @interpolate(flat) noclip: u32,
};

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> VOut {
    let vb = dsel.y;
    let v = vi & ((1u << vb) - 1u);
    let part = pgp_at(dsel.z + (vi >> vb));
    let w = world_of(part_matrix(part), v);
    var o: VOut;
    o.clip = frame.vp * vec4<f32>(w, 1.0);
    o.wpos = w;
    o.noclip = part_meta_at(part).y & 1u;
    return o;
}

fn slot_id(prim: u32) -> u32 {
    let e = crl[crw[lay.d.z + 2u * dsel.x] + (prim >> 6u)];
    return CULL_TAG | (e.x << 6u) | (prim & 63u);
}

@fragment
fn fs(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    return pack_id(slot_id(prim));
}

@fragment
fn fs_clip(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    if (clipped(frame.clip, in.wpos, in.noclip != 0u)) {
        discard;
    }
    return pack_id(slot_id(prim));
}
