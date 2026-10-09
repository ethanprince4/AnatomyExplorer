// PREFILTER_FS. Bindings: 0 uniform, 1 equirect source (rgba32float or rgba16float, full mip chain), 2 trilinear
// sampler (repeat in u, clamp in v). Output row index == v (row 0 at v = 0), the same layout as GL's array layers.
struct U {
    rough: f32,
    src_w: f32,
    _p0: f32,
    _p1: f32,
};
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_src: texture_2d<f32>;
@group(0) @binding(2) var s_env: sampler;

const PI: f32 = 3.14159265;

fn uv_dir(uv: vec2<f32>) -> vec3<f32> {
    let phi = (uv.x - 0.5) * 2.0 * PI;
    let th = uv.y * PI;
    return vec3<f32>(sin(th) * sin(phi), cos(th), -sin(th) * cos(phi));
}
fn dir_uv(d: vec3<f32>) -> vec2<f32> {
    return vec2<f32>(0.5 + atan2(d.x, -d.z) / (2.0 * PI), acos(clamp(d.y, -1.0, 1.0)) / PI);
}
fn hammersley(i: u32, n: u32) -> vec2<f32> {
    var b = i;
    b = (b << 16u) | (b >> 16u);
    b = ((b & 0x55555555u) << 1u) | ((b & 0xAAAAAAAAu) >> 1u);
    b = ((b & 0x33333333u) << 2u) | ((b & 0xCCCCCCCCu) >> 2u);
    b = ((b & 0x0F0F0F0Fu) << 4u) | ((b & 0xF0F0F0F0u) >> 4u);
    b = ((b & 0x00FF00FFu) << 8u) | ((b & 0xFF00FF00u) >> 8u);
    return vec2<f32>(f32(i) / f32(n), f32(b) * 2.3283064365386963e-10);
}

@fragment
fn fs_prefilter(@location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    let N = uv_dir(v_uv);
    if (u.rough < 0.02) { return vec4<f32>(textureSampleLevel(t_src, s_env, v_uv, 0.0).rgb, 1.0); }
    let a = u.rough * u.rough;
    var upv = vec3<f32>(1.0, 0.0, 0.0);
    if (abs(N.y) < 0.999) { upv = vec3<f32>(0.0, 1.0, 0.0); }
    let T = normalize(cross(upv, N));
    let B = cross(N, T);
    var sum = vec3<f32>(0.0);
    var wsum = 0.0;
    const COUNT: u32 = 1024u;
    let texel_sa = 4.0 * PI / (u.src_w * u.src_w * 0.5);
    for (var i: u32 = 0u; i < COUNT; i++) {
        let xi = hammersley(i, COUNT);
        let ph = 2.0 * PI * xi.x;
        let ct = sqrt((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y));
        let st = sqrt(1.0 - ct * ct);
        let H = T * (st * cos(ph)) + B * (st * sin(ph)) + N * ct;
        let L = normalize(2.0 * dot(N, H) * H - N);
        let NoL = dot(N, L);
        if (NoL > 0.0) {
            let d = (ct * ct * (a * a - 1.0) + 1.0);
            let D = a * a / (PI * d * d);
            let pdf = D / 4.0 + 1e-4;
            let sa = 1.0 / (f32(COUNT) * pdf);
            let lod = max(0.5 * log2(sa / texel_sa) + 1.0, 0.0);
            sum += textureSampleLevel(t_src, s_env, dir_uv(L), lod).rgb * NoL;
            wsum += NoL;
        }
    }
    return vec4<f32>(sum / max(wsum, 1e-5), 1.0);
}
