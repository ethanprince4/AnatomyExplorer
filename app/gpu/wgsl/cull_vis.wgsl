// Visibility pass of the culled clusters: indexed draws of the compacted index buffer, one per page and phase.
//
// Concatenated by app/gpu/cull.py after: `enable primitive_index;`, the id prelude (alias IdOut, fn pack_id) and clip.wgsl.
//
// The compacted index buffer holds page-local vertex ids, so the vertex shader finds the part of a vertex through the
// page's lookup table: chunk table (first part of every 32 vertices), part end vertices, part indices. Position is then
// matrix(part) * pos, the same math as visbuf.wgsl's vertex_world (HOOK: morph weight * dpos and animation go in
// world_of, together with the same hook in visbuf.wgsl; the cluster boxes already contain |weight| * dmax).
//
// Id written: 0x80000000 | (first block slot of the draw * 64 + primitive_index). primitive_index restarts at 0 in every
// draw; slot = id >> 6 (bit 31 removed) indexes slot_cluster, id & 63 is the triangle inside the block.

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read> part_xf: array<vec4<f32>>;      // 5 per part: matrix columns 0..3, (|weight|, flags, slot base, 0)
@group(0) @binding(2) var<storage, read> dinfo: array<u32>;              // per (page, phase): id slot of the draw's first block
@group(1) @binding(0) var<storage, read> pos: array<f32>;                // page positions, float32 x3
@group(1) @binding(1) var<storage, read> vlook: array<u32>;              // [chunk -> part slot] [part end vertex] [part index]
@group(2) @binding(0) var<uniform> dsel: vec4<u32>;                      // x: page * 2 + phase, y: chunk count, z: parts in the page

const CULL_TAG: u32 = 0x80000000u;

fn part_matrix(part: u32) -> mat4x4<f32> {
    let b = part * 5u;
    return mat4x4<f32>(part_xf[b], part_xf[b + 1u], part_xf[b + 2u], part_xf[b + 3u]);
}

fn part_flags(part: u32) -> u32 {
    return bitcast<u32>(part_xf[part * 5u + 4u].y);
}

fn world_of(m: mat4x4<f32>, v: u32) -> vec3<f32> {
    let p = vec3<f32>(pos[3u * v], pos[3u * v + 1u], pos[3u * v + 2u]);
    return (m * vec4<f32>(p, 1.0)).xyz;
}

// part (model index) of a page-local vertex id: parts are stored in vertex order, so scan forward from the chunk's first
fn part_of(v: u32) -> u32 {
    var i = vlook[v >> 5u];
    let ends = dsel.y;
    loop {
        if (v < vlook[ends + i]) {
            break;
        }
        i = i + 1u;
    }
    return vlook[ends + dsel.z + i];
}

struct VOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,
    @location(1) @interpolate(flat) noclip: u32,
};

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> VOut {
    let part = part_of(vi);
    let w = world_of(part_matrix(part), vi);
    var o: VOut;
    o.clip = frame.vp * vec4<f32>(w, 1.0);
    o.wpos = w;
    o.noclip = part_flags(part) & 1u;
    return o;
}

fn block_id(prim: u32) -> u32 {
    return CULL_TAG | (dinfo[dsel.x] * 64u + prim);
}

@fragment
fn fs(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    return pack_id(block_id(prim));
}

@fragment
fn fs_clip(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    if (clipped(frame.clip, in.wpos, in.noclip != 0u)) {
        discard;
    }
    return pack_id(block_id(prim));
}
