// BLIT_FS. Bindings: 0 source (filterable float), 1 linear sampler.
@group(0) @binding(0) var t_src: texture_2d<f32>;
@group(0) @binding(1) var s_lin: sampler;

@fragment
fn fs_blit(@location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    return textureSampleLevel(t_src, s_lin, v_uv, 0.0);
}
