// SSAO_FS. Bindings: 0 uniform, 1 nd (unfilterable rgba32float), 2 prev (filterable rgba16float), 3 linear, 4 nearest.
// abs() uses ported literally: abs(N.z) < 0.9 (tangent choice), abs(P.z - sceneZ) (range check). u_ortho is an
// i32, u_gi_on stays an f32 compared with > 0.5, exactly as in GLSL.
struct U {
    tan_: vec2<f32>,
    ortho: i32,
    samples: i32,
    radius: f32,
    bias: f32,
    power: f32,
    large: f32,
    large_mix: f32,
    gi_on: f32,
    _p0: f32,
    _p1: f32,
};
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_nd: texture_2d<f32>;
@group(0) @binding(2) var t_prev: texture_2d<f32>;
@group(0) @binding(3) var s_lin: sampler;
@group(0) @binding(4) var s_near: sampler;

fn view_pos(uv: vec2<f32>, d: f32) -> vec3<f32> {
    let ndc = uv * 2.0 - 1.0;
    if (u.ortho == 1) { return vec3<f32>(ndc * u.tan_, -d); }
    return vec3<f32>(ndc * u.tan_ * d, -d);
}
fn project(p: vec3<f32>) -> vec2<f32> {
    var ndc: vec2<f32>;
    if (u.ortho == 1) { ndc = p.xy / u.tan_; } else { ndc = p.xy / (-p.z * u.tan_); }
    return ndc * 0.5 + 0.5;
}

@fragment
fn fs_ssao(@builtin(position) frag: vec4<f32>, @location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    let nd = textureSampleLevel(t_nd, s_near, v_uv, 0.0);
    if (nd.w <= 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    let P = view_pos(v_uv, nd.w);
    let N = normalize(nd.xyz);
    let a0 = ign(frag.xy) * 6.2831853;
    let r0 = ign(frag.yx + 17.0);
    var Tv: vec3<f32>;
    if (abs(N.z) < 0.9) { Tv = cross(N, vec3<f32>(0.0, 0.0, 1.0)); } else { Tv = cross(N, vec3<f32>(1.0, 0.0, 0.0)); }
    let T = normalize(Tv);
    let B = cross(N, T);
    var ao = 1.0;
    var gi = vec3<f32>(0.0);
    for (var scale: i32 = 0; scale < 2; scale++) {
        var rad = u.radius;
        if (scale != 0) { rad = u.radius * u.large; }
        var occ = 0.0;
        var wsum = 0.0;
        for (var i: i32 = 0; i < u.samples; i++) {
            let fi = (f32(i) + r0) / f32(u.samples);
            let phi = a0 + f32(i) * 2.39996323 + f32(scale) * 1.3;
            let ct = sqrt(1.0 - fi);
            let st = sqrt(fi);
            let h = vec3<f32>(cos(phi) * st, sin(phi) * st, ct);
            let sc = mix(0.15, 1.0, fract(f32(i) * 0.618034 + r0));
            let S = P + (T * h.x + B * h.y + N * h.z) * rad * sc * sc;
            let uv = project(S);
            wsum += 1.0;
            if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) { continue; }
            let sd = textureSampleLevel(t_nd, s_near, uv, 0.0).w;
            if (sd <= 0.0) { continue; }
            let sceneZ = -sd;
            let range = smoothstep(0.0, 1.0, rad / max(abs(P.z - sceneZ), 1e-4));
            var hit = 0.0;
            if (sceneZ >= S.z + u.bias * (1.0 + 3.0 * f32(scale))) { hit = 1.0; }
            occ += hit * range;
        }
        let a = 1.0 - occ / max(wsum, 1.0);
        if (scale == 0) { ao *= a; } else { ao *= mix(1.0, a, u.large_mix); }
    }
    if (u.gi_on > 0.5) {
        let grad = u.radius * u.large;
        const DIRS: i32 = 12;
        const STEPS: i32 = 8;
        for (var i: i32 = 0; i < DIRS; i++) {
            let fi = (f32(i) + r0) / f32(DIRS);
            let phi = a0 * 1.7 + f32(i) * 2.39996323;
            let ct = sqrt(1.0 - fi);
            let st = sqrt(fi);
            let dir = T * (cos(phi) * st) + B * (sin(phi) * st) + N * ct;
            for (var k: i32 = 1; k <= STEPS; k++) {
                let f = (f32(k) - 0.5 + 0.5 * r0) / f32(STEPS);
                let S = P + dir * grad * f * f + N * u.bias;
                let uv = project(S);
                if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) { break; }
                let sd = textureSampleLevel(t_nd, s_near, uv, 0.0).w;
                if (sd <= 0.0) { continue; }
                let dz = -sd - S.z;
                if (dz > u.bias && dz < grad * 0.6) {
                    let Ns = textureSampleLevel(t_nd, s_near, uv, 0.0).xyz;
                    let facing = clamp(dot(Ns, -dir) * 1.5 + 0.25, 0.0, 1.0);
                    gi += min(textureSampleLevel(t_prev, s_lin, uv, 0.0).rgb, vec3<f32>(4.0)) * facing;
                    break;
                }
            }
        }
        gi /= f32(DIRS);
    }
    return vec4<f32>(gi, pow(clamp(ao, 0.0, 1.0), u.power));
}
