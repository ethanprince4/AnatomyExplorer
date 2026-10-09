// Shared by the visibility pass and the resolve (concatenated in front of them by app/gpu/renderer.py):
// the per-frame uniform, the per-draw table record and the cutting planes.
//
// Port of CLIP_COMMON (app/viewer/shaders.py): the cut-away of a micro model and the cross-sections.

struct ClipParams {
    p0: vec4<f32>,          // plane 0..2: dot(vec4(world, 1), plane) < 0 is the removed side
    p1: vec4<f32>,
    p2: vec4<f32>,
    on: vec4<u32>,          // x, y, z: plane enabled; w: mode (0: any plane removes its side, 1: a corner)
};

struct Frame {
    vp: mat4x4<f32>,        // GL view-projection with z remapped to wgpu's [0, 1] (z' = 0.5 z + 0.5 w)
    view: mat4x4<f32>,      // GL view matrix: linear depth = -(view * world).z
    clip: ClipParams,
    screen: vec4<f32>,      // width, height, 0, 0
    halves: vec4<f32>,      // tan(half fov) x, y (or ortho half extents), near, far
    info: vec4<u32>,        // id bits for the primitive index, sample count, draws in the table, 1 = orthographic
};

// One record per draw slot (slot 0 is reserved for "background"). 160 bytes.
struct Draw {
    model: mat4x4<f32>,     // part matrix (world = model * position)
    nmat0: vec4<f32>,       // inverse transpose of the upper 3x3, one column per vec4
    nmat1: vec4<f32>,
    nmat2: vec4<f32>,
    a: vec4<u32>,           // first index (page local), base vertex (always 0), triangle count, page
    b: vec4<u32>,           // part, item, flags (bit 0: never cut, bit 1: mirrored, bit 2: selected), LOD level
    c: vec4<f32>,           // morph weight, 0, 0, 0
};

const DRAW_NOCLIP: u32 = 1u;
const DRAW_MIRRORED: u32 = 2u;
const DRAW_SELECTED: u32 = 4u;

fn clipped(clip: ClipParams, p: vec3<f32>, noclip: bool) -> bool {
    if (noclip) {
        return false;
    }
    let q = vec4<f32>(p, 1.0);
    let a = clip.on.x == 1u && dot(q, clip.p0) < 0.0;
    let b = clip.on.y == 1u && dot(q, clip.p1) < 0.0;
    let c = clip.on.z == 1u && dot(q, clip.p2) < 0.0;
    if (clip.on.w == 1u) {
        let n = clip.on.x + clip.on.y + clip.on.z;
        if (n == 0u) {
            return false;
        }
        return (clip.on.x == 0u || a) && (clip.on.y == 0u || b) && (clip.on.z == 0u || c);
    }
    return a || b || c;
}
