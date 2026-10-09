// BLUR_FS. Bindings: 0 uniform, 1 src (filterable float, rgba16float), 2 nd (unfilterable), 3 linear, 4 nearest.
struct U {
    dir: vec2<f32>,
    _p0: vec2<f32>,
};
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_src: texture_2d<f32>;
@group(0) @binding(2) var t_nd: texture_2d<f32>;
@group(0) @binding(3) var s_lin: sampler;
@group(0) @binding(4) var s_near: sampler;

@fragment
fn fs_blur(@location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    let c = textureSampleLevel(t_nd, s_near, v_uv, 0.0);
    if (c.w <= 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    var sum = vec4<f32>(0.0);
    var wsum = 0.0;
    for (var i: i32 = -6; i <= 6; i++) {
        let uv = v_uv + u.dir * f32(i);
        let s = textureSampleLevel(t_nd, s_near, uv, 0.0);
        var w = exp(-f32(i * i) / 18.0);
        w *= exp(-abs(s.w - c.w) / (0.02 * c.w + 1e-4));
        w *= pow(max(dot(s.xyz, c.xyz), 0.0), 8.0);
        sum += textureSampleLevel(t_src, s_lin, uv, 0.0) * w;
        wsum += w;
    }
    return sum / max(wsum, 1e-5);
}
