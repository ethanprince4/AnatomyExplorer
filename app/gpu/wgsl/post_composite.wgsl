// COMPOSITE_FS. Bindings: 0 uniform, 1 opaque, 2 accum, 3 weight (filterable float), 4 id (unfilterable rg32float),
// 5 linear sampler, 6 nearest sampler. There is no FXAA in this pass; "edges" are the selection / hover outlines
// (12 taps on a ring + centre = 13 samples of the id texture each).
struct U {
    outline: vec3<f32>,
    hover: f32,
    hover_outline: vec3<f32>,
    exposure: f32,
    texel: vec2<f32>,
    outline_px: f32,
    oit_on: i32,
    has_sel: i32,
    tonemap: i32,
    _p0: i32,
    _p1: i32,
};
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_opaque: texture_2d<f32>;
@group(0) @binding(2) var t_accum: texture_2d<f32>;
@group(0) @binding(3) var t_weight: texture_2d<f32>;
@group(0) @binding(4) var t_id: texture_2d<f32>;
@group(0) @binding(5) var s_lin: sampler;
@group(0) @binding(6) var s_near: sampler;

fn pbr_neutral(color_in: vec3<f32>) -> vec3<f32> {
    var color = color_in;
    const startCompression: f32 = 0.8 - 0.04;
    const desaturation: f32 = 0.15;
    let x = min(color.r, min(color.g, color.b));
    var offset = 0.04;
    if (x < 0.08) { offset = x - 6.25 * x * x; }
    color -= offset;
    let peak = max(color.r, max(color.g, color.b));
    if (peak < startCompression) { return color; }
    const d: f32 = 1.0 - startCompression;
    let newPeak = 1.0 - d * d / (peak + d - startCompression);
    color *= newPeak / peak;
    let g = 1.0 - 1.0 / (desaturation * (peak - newPeak) + 1.0);
    return mix(color, newPeak * vec3<f32>(1.0), g);
}
fn srgb(c_in: vec3<f32>) -> vec3<f32> {
    let c = clamp(c_in, vec3<f32>(0.0), vec3<f32>(1.0));
    return mix(c * 12.92, 1.055 * pow(c, vec3<f32>(1.0 / 2.4)) - 0.055, step(vec3<f32>(0.0031308), c));
}

fn is_sel(uv: vec2<f32>) -> f32 {
    let f = textureSampleLevel(t_id, s_near, uv, 0.0).g;
    return fmod_gl(floor(f + 0.5), 2.0);
}
fn is_id(uv: vec2<f32>, target_id: f32) -> f32 {
    if (abs(textureSampleLevel(t_id, s_near, uv, 0.0).r - target_id) < 0.5) { return 1.0; }
    return 0.0;
}

fn edge_sel(v_uv: vec2<f32>) -> f32 {
    let c = is_sel(v_uv);
    var e = 0.0;
    for (var i: i32 = 0; i < 12; i++) {
        let a = f32(i) * 0.5235988;
        let o = vec2<f32>(cos(a), sin(a)) * u.outline_px * u.texel;
        e += abs(is_sel(v_uv + o) - c);
    }
    var k = 1.0;
    if (c > 0.5) { k = 0.6; }
    return clamp(e / 4.0, 0.0, 1.0) * k;
}
fn edge_id(v_uv: vec2<f32>, target_id: f32) -> f32 {
    if (target_id < 0.5) { return 0.0; }
    let c = is_id(v_uv, target_id);
    var e = 0.0;
    for (var i: i32 = 0; i < 12; i++) {
        let a = f32(i) * 0.5235988;
        let o = vec2<f32>(cos(a), sin(a)) * u.outline_px * u.texel;
        e += abs(is_id(v_uv + o, target_id) - c);
    }
    var k = 1.0;
    if (c > 0.5) { k = 0.6; }
    return clamp(e / 4.0, 0.0, 1.0) * k;
}

@fragment
fn fs_composite(@builtin(position) frag: vec4<f32>, @location(0) v_uv: vec2<f32>) -> @location(0) vec4<f32> {
    var col = textureSampleLevel(t_opaque, s_lin, v_uv, 0.0).rgb;
    if (u.oit_on == 1) {
        let acc = textureSampleLevel(t_accum, s_lin, v_uv, 0.0);
        let wsum = textureSampleLevel(t_weight, s_lin, v_uv, 0.0).r;
        let reveal = clamp(acc.a, 0.0, 1.0);
        if (wsum > 1e-6) { col = (acc.rgb / wsum) * (1.0 - reveal) + col * reveal; }
    }
    col *= exp2(u.exposure);
    if (u.tonemap == 1) { col = pbr_neutral(col); }
    col = srgb(col);
    let eh = edge_id(v_uv, u.hover);
    var es = 0.0;
    if (u.has_sel == 1) { es = edge_sel(v_uv); }
    col = mix(col, u.hover_outline, eh * 0.55);
    col = mix(col, u.outline, es);
    col += (ign(frag.xy) - 0.5) / 255.0;
    return vec4<f32>(col, 1.0);
}
