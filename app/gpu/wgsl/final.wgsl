// Last pass: the composited picture (GL row order, row 0 = bottom) into the target (row 0 = top, what the host and the
// read-back expect), scaled when the window is not the render size (GL: BLIT_FS, linear). dims = (w, h, out w, out h).
@group(0) @binding(0) var<uniform> dims: vec4<f32>;
@group(0) @binding(1) var src: texture_2d<f32>;
@group(0) @binding(2) var smp: sampler;

@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}

@fragment
fn fs_final(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    if (dims.x == dims.z && dims.y == dims.w) {
        return textureLoad(src, vec2<i32>(i32(frag.x), i32(dims.y) - 1 - i32(frag.y)), 0);
    }
    return textureSampleLevel(src, smp, vec2<f32>(frag.x / dims.z, 1.0 - frag.y / dims.w), 0.0);
}
