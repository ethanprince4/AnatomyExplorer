// Cut faces ("caps") of the model viewer, shared head: the per-frame uniform and the full-screen vertex stage.
//
// Port of the cut-face passes of app/viewer/shaders.py (PARITY_FS, CAP_FS, CAPMIX_PRE_FS, CAPMIX_FS) and
// app/viewer/renderer.py (_render_caps, _capmix).  Concatenated by app/gpu/caps.py in front of caps_gather.wgsl,
// caps_lay.wgsl and caps_mix.wgsl.
//
// Row order: the cap targets are rendered like the visibility buffer (row 0 = TOP of the picture, y-down framebuffer);
// GL's gl_FragCoord (origin bottom-left) is rebuilt as (x, height - y).  caps_lay.wgsl writes into the renderer's
// res_* textures, which keep GL's row order (row 0 = bottom), and flips the row when it reads the cap targets.

struct CapFrame {
    vp: mat4x4<f32>,        // GL view-projection with z remapped to [0, 1] (the matrix of Frame.vp): rasterisation
    vp_gl: mat4x4<f32>,     // GL view-projection exactly as u_viewproj (window depth of the cut face on its plane)
    inv_vp: mat4x4<f32>,    // inverse(GL view-projection), float32 of the float64 inverse (u_inv_viewproj)
    view: mat4x4<f32>,      // GL view matrix: linear depth = -(view * world).z
    screen: vec4<f32>,      // width, height, key scale (model_diag * 0.02), 0
    depth: vec4<f32>,       // near, far, 1 = orthographic, 0
    hover: vec4<f32>,       // hovered item + 1 (-1: none), 0, 0, 0
    sel_col: vec4<f32>,     // u_sel_col (rgb)
    hover_col: vec4<f32>,   // u_hover_col (rgb)
};

// 24-bit unorm round trip: GL keeps the cap key and the pre-pass depth in 24-bit depth buffers, so two values closer
// than 1 / (2^24 - 1) are equal there (ties keep the first draw).  The same quantisation is applied here.
fn q24(x: f32) -> f32 {
    return round(clamp(x, 0.0, 1.0) * 16777215.0) / 16777215.0;
}

@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}
