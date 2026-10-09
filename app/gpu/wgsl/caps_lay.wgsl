// CAPMIX_PRE_FS: lays the cut faces into the single-sample id / depth targets of the frame (GL: the pre-pass nd and id
// textures and their depth).  Concatenated after caps_common.wgsl.
//
//   group 0: 0 CapFrame (uniform)
//   group 1: 0 cap normal (rgba16float)  1 cap id (rg32float)  2 cap zp (r32float)   (cap targets, top row first)
//            3 copy of the frame's nd texture (rgba32float, GL row order: view normal, linear view depth; 0 = background)
//
// fs_lay_gl targets (GL row order, row 0 = bottom: the renderer's `id` and `nd`), both with load_op "load":
//   0 id  rg32float  item + 1, flags (|2 on a cut face)       1 nd  rgba32float  view-space normal, linear depth
// A cut face replaces the pixel when its window depth is smaller than the one stored (GL: depth test "less" against the
// 24-bit pre-pass depth, background 1.0): the stored linear depth is converted back to window depth and both are
// quantised to 24 bits.  tri / res_order of the renderer are not touched.
//
// fs_depth (no colour target): writes the window depth of the cut faces into a depth attachment (top row first, the
// visibility buffer's depth, any sample count) with test "less" -- GL's depth_ms after CAPMIX_FS, which the OIT pass tests.

@group(0) @binding(0) var<uniform> cf: CapFrame;
@group(1) @binding(0) var cap_normal: texture_2d<f32>;
@group(1) @binding(1) var cap_id: texture_2d<f32>;
@group(1) @binding(2) var cap_zp: texture_2d<f32>;
@group(1) @binding(3) var nd_in: texture_2d<f32>;

// window depth (z_ndc * 0.5 + 0.5 of GL's projection) of a linear view depth
fn window_of_linear(d: f32) -> f32 {
    let n = cf.depth.x;
    let f = cf.depth.y;
    if (cf.depth.z > 0.5) {
        return (d - n) / (f - n);
    }
    return f * (d - n) / (d * (f - n));
}

struct LayOut {
    @location(0) id: vec4<f32>,
    @location(1) nd: vec4<f32>,
};

@fragment
fn fs_lay_gl(@builtin(position) pos: vec4<f32>) -> LayOut {
    let px = vec2<i32>(i32(pos.x), i32(pos.y));                           // GL row order
    let cpx = vec2<i32>(px.x, i32(cf.screen.y) - 1 - px.y);               // cap targets: top row first
    let zp = textureLoad(cap_zp, cpx, 0).x;
    if (zp <= 0.0) { discard; }
    let ex = textureLoad(nd_in, px, 0).w;
    var stored = 1.0;
    if (ex > 0.0) { stored = q24(window_of_linear(ex)); }
    if (!(q24(zp) < stored)) { discard; }
    let v_uv = vec2<f32>(pos.x / cf.screen.x, pos.y / cf.screen.y);
    let w = cf.inv_vp * vec4<f32>(v_uv * 2.0 - 1.0, zp * 2.0 - 1.0, 1.0);
    let C = w.xyz / w.w;
    let n = textureLoad(cap_normal, cpx, 0).xyz;
    let vm = mat3x3<f32>(cf.view[0].xyz, cf.view[1].xyz, cf.view[2].xyz);
    var o: LayOut;
    o.nd = vec4<f32>(normalize(vm * n), -(cf.view * vec4<f32>(C, 1.0)).z);
    o.id = vec4<f32>(textureLoad(cap_id, cpx, 0).xy, 0.0, 0.0);
    return o;
}

struct DepthOut {
    @builtin(frag_depth) depth: f32,
};

@fragment
fn fs_depth(@builtin(position) pos: vec4<f32>) -> DepthOut {
    let zp = textureLoad(cap_zp, vec2<i32>(i32(pos.x), i32(pos.y)), 0).x;
    if (zp <= 0.0) { discard; }
    var o: DepthOut;
    o.depth = zp;
    return o;
}
