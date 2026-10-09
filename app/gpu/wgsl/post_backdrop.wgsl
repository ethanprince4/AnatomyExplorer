// BACKDROP_FS. Bindings: 0 uniform.
struct U {
    bottom: vec3<f32>,
    _p0: f32,
    top: vec3<f32>,
    _p1: f32,
};
@group(0) @binding(0) var<uniform> u: U;

@fragment
fn fs_backdrop(@location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    return vec4<f32>(mix(u.bottom, u.top, clamp(v_uv.y, 0.0, 1.0)), 1.0);
}
