// Visibility pass of the culled clusters that did not fit the compact index budget (cull_idx.wgsl draws the others): ONE non-indexed
// draw per page and phase, vertex shader pull (no index buffer). With budget 0 (ANATOMY_CULL_BUDGET=0) it draws everything.
//
// Concatenated by app/gpu/cull.py after: the id prelude (alias IdOut, fn pack_id), clip.wgsl, cull_tables.wgsl, the page prelude
// (geometry.py geom_prelude) and geom.wgsl.
//
// The draw has vertex_count = visible clusters * 192 (64 triangles x 3 corners; first_vertex is 0 and the draw's first slot comes
// from dinfo). Vertex v of the draw: k = v / 192 picks the k-th visible cluster of the draw, tri = (v % 192) / 3 its triangle,
// corner = v % 3. The page stores the triangles of every cullable index range in cluster order (geometry.py cluster_order), so
// cluster c = the j-th cluster of range r owns the 192 index words at (range first index + 192 * j): the vertex index of this
// corner is read straight from the page. Clusters shorter than 64 triangles leave the tail triangles with one shared
// position for all three corners (zero area, never rasterised).
//
// Position = matrix(part) * pos, the same math as visbuf.wgsl's vertex_world, so the clip position is bit-identical to a plain
// draw of the same triangle (HOOK: morph weight * dpos and animation go in world_of, together with the same hook in visbuf.wgsl;
// the cluster boxes already contain |weight| * dmax).
//
// Id written (flat, equal on all three corners, so the provoking vertex does not matter):
//     0x80000000 | (cluster << 6) | triangle-in-cluster          cluster < 2^25 (cull.py checks it at prepare)
// The stored triangle number inside the range is 64 * (cluster - first cluster of the range) + triangle-in-cluster; the original
// triangle is perm[range tfirst + that] (cull_decode.wgsl, TriangleOrder / ClusterCuller.decode_ids on the CPU).

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read> cro: array<vec4<u32>>;           // cull_tables.wgsl
@group(0) @binding(2) var<storage, read> crw: array<u32>;                 // read only, indirect draw source: dinfo (the pulled draw's: 2 * (page * 2 + phase) + 1)
@group(0) @binding(3) var<uniform> lay: CullLay;
@group(0) @binding(4) var<storage, read> crl: array<vec4<u32>>;           // visible-cluster entries (cull_tables.wgsl)
// group 1 binding 0: the geometry page, binding 1 its offsets (geom_prelude(1, 1, 0, uniform_binding=1), read through geom.wgsl)
@group(2) @binding(0) var<uniform> dsel: vec4<u32>;                      // x: page * 2 + phase

const CULL_TAG: u32 = 0x80000000u;

fn part_matrix(part: u32) -> mat4x4<f32> {
    let b = part * 5u;
    return mat4x4<f32>(part_xf_at(b), part_xf_at(b + 1u), part_xf_at(b + 2u), part_xf_at(b + 3u));
}

fn part_flags(part: u32) -> u32 {
    return part_meta_at(part).y;
}

fn world_of(m: mat4x4<f32>, v: u32) -> vec3<f32> {
    let p = g_pos(0u, v);
    return (m * vec4<f32>(p, 1.0)).xyz;
}

struct VOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,
    @location(1) @interpolate(flat) noclip: u32,
    @location(2) @interpolate(flat) id: u32,
};

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> VOut {
    let k = vi / 192u;
    let local = vi - k * 192u;
    let tri = local / 3u;
    let corner = local - tri * 3u;
    let e = crl[crw[lay.d.z + 2u * dsel.x + 1u] + k];      // cluster, first index word, part, triangles | ordinal << 8
    let c = e.x;
    var o: VOut;
    if (tri >= (e.w & 255u)) {
        o.clip = vec4<f32>(2.0, 2.0, 2.0, 1.0);
        o.wpos = vec3<f32>(0.0);
        o.noclip = 1u;
        o.id = CULL_TAG;
        return o;
    }
    let part = e.z;
    let v = g_index(0u, e.y + 3u * tri + corner);
    let w = world_of(part_matrix(part), v);
    o.clip = frame.vp * vec4<f32>(w, 1.0);
    o.wpos = w;
    o.noclip = part_flags(part) & 1u;
    o.id = CULL_TAG | (c << 6u) | tri;
    return o;
}

@fragment
fn fs(in: VOut) -> @location(0) IdOut {
    return pack_id(in.id);
}

@fragment
fn fs_clip(in: VOut) -> @location(0) IdOut {
    if (clipped(frame.clip, in.wpos, in.noclip != 0u)) {
        discard;
    }
    return pack_id(in.id);
}
