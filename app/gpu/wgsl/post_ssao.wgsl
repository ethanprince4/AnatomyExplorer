// SSAO_FS (fs_ssao) and its half-resolution twin (fs_ssao_half). Bindings: 0 uniform, 1 nd (unfilterable rgba32float), 2 prev (filterable rgba16float), 3 linear, 4 nearest,
// 5 depth (unfilterable r32float, exact copy of nd.w). The centre pixel and the GI hit normal still read nd (same texel).
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
    _p0: i32,
    mode: i32,       // 0 AO + GI, 1 AO only (GI off), 2 GI only: the full-res AO / half-res GI split of PostPasses
};
// Pipeline constant: AO samples per scale (post.py run_ssao passes the same value it packs into u.samples).
override SAMPLES: i32 = 16;
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_nd: texture_2d<f32>;
@group(0) @binding(2) var t_prev: texture_2d<f32>;
@group(0) @binding(3) var s_lin: sampler;
@group(0) @binding(4) var s_near: sampler;
@group(0) @binding(5) var t_depth: texture_2d<f32>;   // r32float copy of nd.w (post_pack.wgsl): the taps read only depth
@group(0) @binding(6) var t_lo_nd: texture_2d<f32>;    // fs_ssao_half only: nd of the representative pixel of each 2x2 block
@group(0) @binding(7) var t_lo_off: texture_2d<u32>;   // its offset inside the block, dx + 2 * dy (post_down.wgsl)

fn view_pos(uv: vec2<f32>, d: f32) -> vec3<f32> {
    let ndc = uv * 2.0 - 1.0;
    if (u.ortho == 1) { return vec3<f32>(ndc * u.tan_, -d); }
    return vec3<f32>(ndc * u.tan_ * d, -d);
}
var<private> itan: vec2<f32>;
fn project(p: vec3<f32>) -> vec2<f32> {
    var ndc: vec2<f32>;
    if (u.ortho == 1) { ndc = p.xy * itan; } else { ndc = p.xy * itan * (1.0 / (-p.z)); }
    return ndc * 0.5 + 0.5;
}

// One AO tap at view-space point S (sample of the hemisphere around P): range-weighted occlusion, 0 when the tap
// is off screen, sees background or is not behind the surface (hit = 0 adds hit * range = 0 exactly).
fn ao_tap(P: vec3<f32>, S: vec3<f32>, rad: f32, bias_s: f32) -> f32 {
    let uv = project(S);
    let inb = !(uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0);
    let sd = textureSampleLevel(t_depth, s_near, uv, 0.0).x;
    let sceneZ = -sd;
    if (inb && !(sd <= 0.0) && sceneZ >= S.z + bias_s) {
        return smoothstep(0.0, 1.0, rad / max(abs(P.z - sceneZ), 1e-4));
    }
    return 0.0;
}

// pix: fragment centre of the (full-res) pixel evaluated, uvc its texture coordinate, nd its normal and depth.
fn ssao_eval(pix: vec2<f32>, uvc: vec2<f32>, nd: vec4<f32>) -> vec4<f32> {
    if (nd.w <= 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    itan = 1.0 / u.tan_;
    let P = view_pos(uvc, nd.w);
    let N = normalize(nd.xyz);
    let a0 = ign(pix) * 6.2831853;
    let r0 = ign(pix.yx + 17.0);
    let ao_on = (u.mode & 3) != 2;
    let gi_run = u.gi_on > 0.5 && (u.mode & 3) != 1;
    var Tv: vec3<f32>;
    if (abs(N.z) < 0.9) { Tv = cross(N, vec3<f32>(0.0, 0.0, 1.0)); } else { Tv = cross(N, vec3<f32>(1.0, 0.0, 0.0)); }
    let T = normalize(Tv);
    let B = cross(N, T);
    var ao = 1.0;
    var gi = vec3<f32>(0.0);
    if (ao_on) {
        // Both scales share the per-sample terms (loop interchange: i outside, scale inside). Each scale still adds its
        // taps in the same order, so occ0 / occ1 are the sums of the original per-scale loops.
        let rad0 = u.radius;
        let rad1 = u.radius * u.large;
        let bias0 = u.bias;                    // u.bias * (1.0 + 3.0 * f32(scale))
        let bias1 = u.bias * 4.0;
        let inv_n = 1.0 / f32(SAMPLES);
        var occ0 = 0.0;
        var occ1 = 0.0;
        for (var i: i32 = 0; i < SAMPLES; i++) {
            let fi_ = f32(i);
            let fr = (fi_ + r0) * inv_n;
            let ct = sqrt(1.0 - fr);
            let st = sqrt(fr);
            let sc = mix(0.15, 1.0, fract(fi_ * 0.618034 + r0));
            let ss = sc * sc;
            let phi0 = a0 + fi_ * 2.39996323;
            let phi1 = phi0 + 1.3;
            let v0 = T * (cos(phi0) * st) + B * (sin(phi0) * st) + N * ct;
            let v1 = T * (cos(phi1) * st) + B * (sin(phi1) * st) + N * ct;
            occ0 += ao_tap(P, P + v0 * (rad0 * ss), rad0, bias0);
            occ1 += ao_tap(P, P + v1 * (rad1 * ss), rad1, bias1);
        }
        let wn = max(f32(SAMPLES), 1.0);     // wsum: one per sample, taps skipped by `continue` included
        ao *= 1.0 - occ0 / wn;
        ao *= mix(1.0, 1.0 - occ1 / wn, u.large_mix);
    }
    if (gi_run) {
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
                let sd = textureSampleLevel(t_depth, s_near, uv, 0.0).x;
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

@fragment
fn fs_ssao(@builtin(position) frag: vec4<f32>, @location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    return ssao_eval(frag.xy, v_uv, textureSampleLevel(t_nd, s_near, v_uv, 0.0));
}

// Half-resolution target: texel b stands for the representative pixel of the 2x2 block b (post_down.wgsl). The result
// there is what fs_ssao computes at that pixel (same dither value, same taps), up to the ulp noise of the uv.
@fragment
fn fs_ssao_half(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let b = vec2<i32>(frag.xy);
    let o = textureLoad(t_lo_off, b, 0).x;
    let dims = textureDimensions(t_nd);
    let rep = min(b * 2 + vec2<i32>(i32(o & 1u), i32(o >> 1u)), vec2<i32>(dims) - 1);
    let pix = vec2<f32>(rep) + 0.5;
    return ssao_eval(pix, pix / vec2<f32>(dims), textureLoad(t_lo_nd, b, 0));
}
