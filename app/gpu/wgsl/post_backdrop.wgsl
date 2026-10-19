// BACKDROP_FS. Bindings: 0 uniform.
struct U {
    bottom: vec3<f32>,
    _p0: f32,
    top: vec3<f32>,
    _p1: f32,
    spot: vec3<f32>,
    strength: f32,
};
@group(0) @binding(0) var<uniform> u: U;

@fragment
fn fs_backdrop(@location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    let wall = mix(u.bottom, u.top, clamp(v_uv.y, 0.0, 1.0));
    let pool = (v_uv - vec2<f32>(0.52, 0.52)) / vec2<f32>(0.46, 0.65);
    let light = clamp(exp(-dot(pool, pool) * 2.2) * u.strength, 0.0, 1.0);
    return vec4<f32>(mix(wall, u.spot, light), 1.0);
}
