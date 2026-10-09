// Surface shading of the model viewer: a WGSL port of SHADING_COMMON + MAIN_FS (app/viewer/shaders.py:361-757).
//
// No entry points, no vertex layout, no implicit derivatives: nothing here calls dpdx/dpdy/fwidth/textureSample.
// Every screen-space derivative GLSL takes implicitly is an explicit field of SurfaceIn.  Shadows are always off in
// the model viewer (viewport.py:106), so shadow() is the constant 1.0 and the shadow-map code is not ported; the
// light loop keeps GLSL's expression shapes (lam * sh, mix(sh, 1.0, 0.5)) so rounding matches.
//
// BIND GROUP 1 (group 0 is left to the including pipeline; names below are module globals):
//   @binding(0) uniform  su        : ShadeU        MAIN_FS uniforms (minus shadows); packed by app/gpu/shading_uniforms.py
//   @binding(1) texture  t_items   : rgba32float   u_items, (n_items x 3) texels, column = item, read with textureLoad
//   @binding(2) texture  t_ao      : rgba16float   u_ao, filterable, rgb = bounce GI, a = occlusion; see AO ORIGIN
//   @binding(3) texture  t_spec    : rgba16float 2d-array (u_spec, one layer per roughness step, no mip levels)
//   @binding(4) texture  t_tex     : rgba8unorm-srgb or any filterable float format with mips (u_tex; 1x1 white if none)
//   @binding(5) sampler  samp_ao   : linear, clamp-to-edge
//   @binding(6) sampler  samp_env  : linear, u = repeat, v = clamp-to-edge (environment.py:121)
//   @binding(7) sampler  samp_tex  : linear, mipmap linear, repeat (renderer.py:_texture; max_anisotropy 8 in the app)
// Vertex stage inputs/outputs live in vertex.wgsl.  Concatenate vertex.wgsl + shading.wgsl + entry points into one
// module; this file owns the names PI, ShadeU, SurfaceIn, ShadeOut, Surface, su, t_*, samp_*, and the functions below.
//
// GLSL -> WGSL SEMANTIC DIFFERENCES (all handled in this file or documented as the caller's duty)
//  1. atan(y, x) is atan2(y, x) (same argument order): dir_uv and the circumferential fibre axis.
//  2. mod/% : the ported code never calls mod(); only fract/floor, which are identical (fract(x) = x - floor(x)).
//  3. Matrices are column-major in both languages.  mat3(u_view) is rebuilt from the xyz of the first three columns.
//     renderer.py:_U writes 2-D numpy arrays transposed; shading_uniforms.py does the same.  A mat3 in a WGSL uniform
//     is three 16-byte columns (48 bytes), a vec3[9] (u_sh) is array<vec4<f32>,9> with w unused.
//  4. Hashes are float (fract(sin(p) * 43758.5453123), fract(p * 0.1031)); the literals and operation order are kept
//     exactly.  There are no integer hashes.  sin() of large arguments is hardware/driver-defined in both languages.
//  5. inverse(mat3) / transpose / textureSize / sampler2DShadow only appear in shadow(), which is not ported.
//  6. Texture coordinates: uv (0,0) is the first row of the uploaded image in both APIs; no flip.  u_tex is sampled with
//     textureSampleGrad(uv, uv_dx, uv_dy) = GLSL's implicit-LOD texture().
//     The derivative flavour that reproduces GL's implicit LOD (NVIDIA, measured) is the COARSE quad difference
//     (dpdxCoarse); fwidth() of the stripe coordinate is the FINE one.  An analytic-derivative caller (visibility
//     buffer) differs from either by hardware LOD rounding only.  Anisotropic filtering (sampler max_anisotropy)
//     is implemented differently by the GL driver and by Vulkan; with anisotropy 1 on both sides the texture matches
//     to 2.2/255 on silhouette pixels (tools/perf/gpu/shade_parity.py), with 8 the two APIs diverge on grazing,
//     high-frequency texture (mean 1.2/255, max 200/255 on the test ribbon).
//  7. gl_FrontFacing -> SurfaceIn.front_facing.  WebGPU's front_facing with frontFace=ccw agrees with GL's for
//     clip-space (y up) winding; verified in tools/perf/gpu/shade_parity.py (front-facing probe).
//  8. gl_FragCoord (origin bottom-left) -> SurfaceIn.pixel (origin TOP-left, centre at +0.5).  AO ORIGIN: the AO texture
//     is addressed as pixel / u_screen, so the AO image must be in the renderer's own (top-left) row order.
//  9. fwidth(x) with x = v_fib / period -> (abs(fib_dx) + abs(fib_dy)) / period (fwidth = |dFdx| + |dFdy|).
// 10. int(x) and i32(x) both truncate toward zero; bool/int uniforms are i32; int(v_item + 0.5) -> i32 item in SurfaceIn.
// 11. GLSL `centroid` and flat provoking vertex (GL: last, WebGPU: first) are irrelevant to single-sample / constant
//     per-triangle inputs; with MSAA the caller decides where to interpolate.
// 12. Texture-array layer coordinates are float in GLSL (l0 and min(l0 + 1, layers - 1), always whole numbers) -> i32.
// 13. WGSL pow(x, y) is undefined for x < 0, as GLSL's is; the same expressions are kept (1 - VoH, 1 - NoV).
// 14. `out vec3 cell` in worley() becomes a function-scope pointer.  Ternaries become if/select with the same results.
// 15. Parameters are immutable in WGSL, so the GLSL functions that modify their argument copy it into a var.
// 16. dot() rounding: NVIDIA's GLSL compiler computes a vec3 dot as fma(z, z', fma(y, y', x * x'), WGSL dot() does not;
//     the chaotic hash (hash3, fract(sin(.) * 43758.5)) uses dot3f to reproduce it.  Other GPUs round their GLSL differently.
// 17. MAIN_FS discards clipped fragments before surface(), whose stripe fwidth() then has undefined derivatives next to a
//     cut (NVIDIA GL: up to 55/255 beside a cut plane).  Here the clip test and the derivatives are independent: every
//     lane has valid derivatives, kill is returned and the caller discards.  The parity tool moves GL's discard after
//     surface() (same picture, defined derivatives) so that the reference is not the undefined behaviour.

const PI: f32 = 3.14159265;

struct ShadeU {
    // per-draw state shared with the pre-pass: cutting planes
    u_clip0: vec4<f32>,
    u_clip1: vec4<f32>,
    u_clip2: vec4<f32>,
    u_clip_on: vec3<i32>,
    u_clip_mode: i32,       // 0: any plane removes its negative side; 1: a corner (all active planes negative)
    u_noclip: i32,          // this item is never cut
    u_batched: i32,         // 1: per-item state comes from t_items
    u_flip: i32,            // the model matrix mirrors: front faces are the clockwise ones
    u_ortho: i32,
    u_campos: vec3<f32>,
    u_alpha_cut: f32,
    u_viewdir: vec3<f32>,   // toward the camera (orthographic views)
    u_ao_on: f32,
    u_view: mat4x4<f32>,
    u_screen: vec2<f32>,
    u_ao_direct: f32,
    u_env_diffuse: f32,
    u_ldir0: vec3<f32>,
    u_lsize0: f32,
    u_ldir1: vec3<f32>,
    u_lsize1: f32,
    u_ldir2: vec3<f32>,
    u_lsize2: f32,
    u_lrad0: vec3<f32>,
    u_env_spec: f32,
    u_lrad1: vec3<f32>,
    u_bounce: f32,
    u_lrad2: vec3<f32>,
    u_spec_layers: f32,
    u_sh: array<vec4<f32>, 9>,   // xyz = SH9 irradiance coefficients (9 x vec3)
    u_base: vec3<f32>,
    u_alpha: f32,
    u_rough: f32,
    u_metal: f32,
    u_f0: f32,
    u_wrap: f32,
    u_emis: vec3<f32>,
    u_use_vcol: i32,
    u_has_tex: i32,
    u_stripe: i32,
    u_shorten: f32,
    u_weight: f32,
    u_stripe_p: vec4<f32>,       // period, rest threshold, edge, i_mix
    u_stripe_a: vec3<f32>,
    u_mottle: i32,
    u_stripe_b: vec3<f32>,
    u_detail_on: i32,
    u_mottle_p: vec4<f32>,       // scale, from_min, from_max, octaves
    u_mottle_a: vec3<f32>,
    u_highlight: f32,
    u_mottle_b: vec3<f32>,
    u_detail: vec4<f32>,         // tissue texturing: mottle, cells per unit, nucleus fraction, fibre axis
    u_highlight_col: vec3<f32>,
}

@group(1) @binding(0) var<uniform> su: ShadeU;
@group(1) @binding(1) var t_items: texture_2d<f32>;
@group(1) @binding(2) var t_ao: texture_2d<f32>;
@group(1) @binding(3) var t_spec: texture_2d_array<f32>;
@group(1) @binding(4) var t_tex: texture_2d<f32>;
@group(1) @binding(5) var samp_ao: sampler;
@group(1) @binding(6) var samp_env: sampler;
@group(1) @binding(7) var samp_tex: sampler;

// The interpolated inputs of one surface sample (GLSL GEOM_INPUTS) plus everything GLSL gets implicitly.
struct SurfaceIn {
    wpos: vec3<f32>,
    wnrm: vec3<f32>,         // interpolated, not normalised
    opos: vec3<f32>,
    fib: f32,
    col: vec4<f32>,
    uv: vec2<f32>,
    glow: f32,
    item: i32,
    front_facing: bool,
    pixel: vec2<f32>,        // framebuffer position, origin top-left, pixel centre at +0.5 (see AO ORIGIN)
    uv_dx: vec2<f32>,        // d(uv)/dx, d(uv)/dy in pixels
    uv_dy: vec2<f32>,
    fib_dx: f32,             // d(fib)/dx, d(fib)/dy in pixels (fwidth of the stripe coordinate)
    fib_dy: f32,
}

struct ShadeOut {
    color: vec4<f32>,        // rgb = shaded colour, a = 1 (the GLSL o_col)
    alpha: f32,              // surface alpha (u_alpha * texture alpha), what the alpha test compares
    kill: bool,              // GLSL would discard: clipped(), or the alpha test failed
}

struct Surface {
    albedo: vec3<f32>,
    alpha: f32,
    rough: f32,
    metal: f32,
    f0: vec3<f32>,
}

// ---- per-item state of a batched draw: row 0 (id + 1, selected, highlight, x-ray), row 1 (flat colour, on),
// row 2 (highlight colour, opacity)
fn item_row(item: i32, row: i32) -> vec4<f32> {
    return textureLoad(t_items, vec2<i32>(item, row), 0);
}

// ---- cutting planes (CLIP_COMMON)
fn clipped(p: vec3<f32>) -> bool {
    if (su.u_noclip == 1) { return false; }
    let a = su.u_clip_on.x == 1 && dot(vec4<f32>(p, 1.0), su.u_clip0) < 0.0;
    let b = su.u_clip_on.y == 1 && dot(vec4<f32>(p, 1.0), su.u_clip1) < 0.0;
    let c = su.u_clip_on.z == 1 && dot(vec4<f32>(p, 1.0), su.u_clip2) < 0.0;
    if (su.u_clip_mode == 1) {
        let n = su.u_clip_on.x + su.u_clip_on.y + su.u_clip_on.z;
        if (n == 0) { return false; }
        return (su.u_clip_on.x == 0 || a) && (su.u_clip_on.y == 0 || b) && (su.u_clip_on.z == 0 || c);
    }
    return a || b || c;
}

// ---- arithmetic that must round like NVIDIA's GLSL compiler (the hashes turn one rounding step into a new value)
// dot() of two vec3 is evaluated as fma(z, z', fma(y, y', x * x')); WGSL dot() rounds differently (47% of hash3 results
// differ), and fract(sin(.) * 43758.5453123) multiplies a 1-ulp difference of its argument into an unrelated value.
// fract(a * b) of a computed argument is written out as (a * b) - floor(a * b), the product repeated: that is the
// arithmetic the GLSL compiler produces; the built-in fract() (or a helper taking the product as an argument)
// differs for 11-30% of the inputs of hash13/hash33.  Plain fract(x) of a variable is identical in both.
// Measured with the isolated tests in S/gpu_port/shading/{hash_test,h13_test,tissue_test}.py: every noise function
// (hash3, gnoise, fbm, hash13, hash33, worley) now matches bit for bit; vnoise/fbm3 differ by <1e-3 (mix rounding).
fn dot3f(a: vec3<f32>, b: vec3<f32>) -> f32 {
    return fma(a.z, b.z, fma(a.y, b.y, a.x * b.x));
}
fn hash3(p_in: vec3<f32>) -> vec3<f32> {
    let p = vec3<f32>(dot3f(p_in, vec3<f32>(127.1, 311.7, 74.7)), dot3f(p_in, vec3<f32>(269.5, 183.3, 246.1)),
                      dot3f(p_in, vec3<f32>(113.5, 271.9, 124.6)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
fn gnoise(p: vec3<f32>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    let u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    let n000 = dot(hash3(i + vec3<f32>(0.0, 0.0, 0.0)), f - vec3<f32>(0.0, 0.0, 0.0));
    let n100 = dot(hash3(i + vec3<f32>(1.0, 0.0, 0.0)), f - vec3<f32>(1.0, 0.0, 0.0));
    let n010 = dot(hash3(i + vec3<f32>(0.0, 1.0, 0.0)), f - vec3<f32>(0.0, 1.0, 0.0));
    let n110 = dot(hash3(i + vec3<f32>(1.0, 1.0, 0.0)), f - vec3<f32>(1.0, 1.0, 0.0));
    let n001 = dot(hash3(i + vec3<f32>(0.0, 0.0, 1.0)), f - vec3<f32>(0.0, 0.0, 1.0));
    let n101 = dot(hash3(i + vec3<f32>(1.0, 0.0, 1.0)), f - vec3<f32>(1.0, 0.0, 1.0));
    let n011 = dot(hash3(i + vec3<f32>(0.0, 1.0, 1.0)), f - vec3<f32>(0.0, 1.0, 1.0));
    let n111 = dot(hash3(i + vec3<f32>(1.0, 1.0, 1.0)), f - vec3<f32>(1.0, 1.0, 1.0));
    return mix(mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),
               mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y), u.z);
}
fn fbm(p_in: vec3<f32>, octaves: i32) -> f32 {
    var p = p_in;
    var sum = 0.0;
    var amp = 1.0;
    var norm = 0.0;
    for (var o = 0; o < 6; o++) {
        if (o >= octaves) { break; }
        sum += amp * gnoise(p);
        norm += amp;
        amp *= 0.5;
        p *= 2.0;
    }
    return 0.5 + 0.75 * sum / norm;
}

// ---- tissue texturing of the procedural microanatomy models: a mottled stain, fibres along an axis and, on cut
// faces, cells with nuclei
fn hash13(p_in: vec3<f32>) -> f32 {
    var p = (p_in * 0.1031) - floor(p_in * 0.1031);
    p += dot3f(p, p.zyx + 31.32);
    return ((p.x + p.y) * p.z) - floor((p.x + p.y) * p.z);
}
fn hash33(p_in: vec3<f32>) -> vec3<f32> {
    var p = (p_in * vec3<f32>(0.1031, 0.1030, 0.0973)) - floor(p_in * vec3<f32>(0.1031, 0.1030, 0.0973));
    p += dot3f(p, p.yxz + 33.33);
    return ((p.xxy + p.yxx) * p.zyx) - floor((p.xxy + p.yxx) * p.zyx);
}
fn vnoise(p: vec3<f32>) -> f32 {
    let i = floor(p);
    var f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    let a = mix(hash13(i), hash13(i + vec3<f32>(1.0, 0.0, 0.0)), f.x);
    let b = mix(hash13(i + vec3<f32>(0.0, 1.0, 0.0)), hash13(i + vec3<f32>(1.0, 1.0, 0.0)), f.x);
    let c = mix(hash13(i + vec3<f32>(0.0, 0.0, 1.0)), hash13(i + vec3<f32>(1.0, 0.0, 1.0)), f.x);
    let d = mix(hash13(i + vec3<f32>(0.0, 1.0, 1.0)), hash13(i + vec3<f32>(1.0, 1.0, 1.0)), f.x);
    return mix(mix(a, b, f.y), mix(c, d, f.y), f.z);
}
fn fbm3(p_in: vec3<f32>) -> f32 {
    var p = p_in;
    var s = 0.0;
    var a = 0.5;
    for (var i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p = p * 2.03 + vec3<f32>(11.7, 3.1, 7.9);
        a *= 0.5;
    }
    return s / 0.9375;
}
fn worley(p: vec3<f32>, cell: ptr<function, vec3<f32>>) -> f32 {
    let i = floor(p);
    let f = fract(p);
    var best = 9.0;
    *cell = i;
    for (var z = -1; z <= 1; z++) {
        for (var y = -1; y <= 1; y++) {
            for (var x = -1; x <= 1; x++) {
                let g = vec3<f32>(f32(x), f32(y), f32(z));
                let r = g + hash33(i + g) * 0.8 + 0.1 - f;
                let d = dot(r, r);
                if (d < best) { best = d; *cell = i + g; }
            }
        }
    }
    return sqrt(best);
}
fn tissue_color(base: vec3<f32>, p: vec3<f32>, is_cap: bool) -> vec3<f32> {
    if (su.u_detail_on == 0) { return base; }
    let mottle = su.u_detail.x;
    let scale = su.u_detail.y;
    let density = su.u_detail.z;
    let fiber = i32(su.u_detail.w + 0.5);
    // fibre axis: 1 x, 2 y, 3 z, 4 circumferential around the x axis (vessel media, sphincters)
    var axis: vec3<f32>;
    if (fiber == 1) {
        axis = vec3<f32>(1.0, 0.0, 0.0);
    } else if (fiber == 2) {
        axis = vec3<f32>(0.0, 1.0, 0.0);
    } else if (fiber == 3) {
        axis = vec3<f32>(0.0, 0.0, 1.0);
    } else {
        axis = normalize(vec3<f32>(0.0, -p.z, p.y) + vec3<f32>(1e-5));
    }
    let n = fbm3(p * max(scale * 0.22, 3.0));
    let broad = fbm3(p * 7.0 + 3.1);                       // blotches the size of a lobule, not of a cell
    var c = base * (1.0 + mottle * (n - 0.5) * 1.9 + mottle * (broad - 0.5) * 1.5);
    if (fiber > 0) {
        var along: f32;
        if (fiber == 4) { along = atan2(p.z, p.y) * length(p.yz); } else { along = dot(p, axis); }
        let stripes = sin(along * scale * 5.0 + n * 4.0);
        c *= 1.0 - 0.07 * smoothstep(0.2, 1.0, stripes);
    }
    if (is_cap && scale > 0.0) {
        var q = p * scale;
        if (fiber > 0) { q = q - axis * dot(q, axis) * 0.72; }   // elongated cells along fibres
        var cell: vec3<f32>;
        let d = worley(q, &cell);
        let nucleus = (1.0 - smoothstep(0.17, 0.26, d)) * step(hash13(cell * 1.37 + 4.1), density);
        c *= 1.0 - 0.10 * smoothstep(0.50, 0.72, d);
        c = mix(c, vec3<f32>(0.085, 0.045, 0.19), nucleus * 0.82);
    }
    return max(c, vec3<f32>(0.0));
}

fn sh_irradiance(n: vec3<f32>) -> vec3<f32> {
    return max(su.u_sh[0].xyz
        + su.u_sh[1].xyz * n.y + su.u_sh[2].xyz * n.z + su.u_sh[3].xyz * n.x
        + su.u_sh[4].xyz * (n.x * n.y) + su.u_sh[5].xyz * (n.y * n.z) + su.u_sh[6].xyz * (3.0 * n.z * n.z - 1.0)
        + su.u_sh[7].xyz * (n.x * n.z) + su.u_sh[8].xyz * (n.x * n.x - n.y * n.y), vec3<f32>(0.0));
}

fn dir_uv(d: vec3<f32>) -> vec2<f32> {
    return vec2<f32>(0.5 + atan2(d.x, -d.z) / (2.0 * PI), acos(clamp(d.y, -1.0, 1.0)) / PI);
}
fn env_spec(r_cam: vec3<f32>, rough: f32) -> vec3<f32> {
    let l = clamp(rough, 0.0, 1.0) * (su.u_spec_layers - 1.0);
    let l0 = floor(l);
    let uv = dir_uv(r_cam);
    let a = textureSampleLevel(t_spec, samp_env, uv, i32(l0), 0.0).rgb;
    let b = textureSampleLevel(t_spec, samp_env, uv, i32(min(l0 + 1.0, su.u_spec_layers - 1.0)), 0.0).rgb;
    return mix(a, b, l - l0);
}
fn env_brdf(r: f32, NoV: f32) -> vec2<f32> {
    let c0 = vec4<f32>(-1.0, -0.0275, -0.572, 0.022);
    let c1 = vec4<f32>(1.0, 0.0425, 1.04, -0.04);
    let rr = r * c0 + c1;
    let a004 = min(rr.x * rr.x, exp2(-9.28 * NoV)) * rr.x + rr.y;
    return vec2<f32>(-1.04, 1.04) * a004 + rr.zw;
}
fn multibounce(ao: f32, albedo: vec3<f32>) -> vec3<f32> {
    let a = 2.0404 * albedo - 0.3324;
    let b = -4.7951 * albedo + 0.6417;
    let c = 2.7552 * albedo + 0.6903;
    return max(vec3<f32>(ao), ((ao * a + b) * ao + c) * ao);
}

// Shadows are off in the model viewer: shadow() returns 1.0 (the GLSL `u_shadow_on < 0.5` path).
fn shadow_off() -> f32 { return 1.0; }

fn D_ggx(NoH: f32, a: f32) -> f32 {
    let a2 = a * a;
    let d = NoH * NoH * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d);
}
fn V_smith(NoV: f32, NoL: f32, a: f32) -> f32 {
    let a2 = a * a;
    let gv = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
    let gl = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
    return 0.5 / max(gv + gl, 1e-5);
}
fn F_schlick(f0: vec3<f32>, VoH: f32) -> vec3<f32> {
    return f0 + (1.0 - f0) * pow(1.0 - VoH, 5.0);
}

fn view_vector(P: vec3<f32>) -> vec3<f32> {
    if (su.u_ortho == 1) { return su.u_viewdir; }
    return normalize(su.u_campos - P);
}

// surface(): the material at one sample.  Returns the Surface; the alpha test is the caller's (shade_main_ex).
fn surface(s_in: SurfaceIn) -> Surface {
    var s: Surface;
    var base = su.u_base;
    var flat_on = false;            // a colour mode or a custom colour replaces the look's own colouring
    if (su.u_batched == 1) {
        let f = item_row(s_in.item, 1);
        if (f.w > 0.5) { base = f.rgb; flat_on = true; }
    }
    if (flat_on) {
    } else if (su.u_stripe == 1) {
        let x = s_in.fib / su.u_stripe_p.x;
        let fw = (abs(s_in.fib_dx) + abs(s_in.fib_dy)) / su.u_stripe_p.x;      // fwidth(x)
        let thr = su.u_stripe_p.y / max(1.0 - su.u_shorten * su.u_weight, 0.2);
        let ab = abs(fract(x) - 0.5);
        let e = max(su.u_stripe_p.z, fw * 0.75);
        var f = smoothstep(thr - e, thr + e, ab);
        let avg = clamp(1.0 - 2.0 * thr, 0.0, 1.0);
        f = mix(f, avg, smoothstep(0.22, 0.55, fw));
        base = mix(su.u_stripe_a, su.u_stripe_b, f * su.u_stripe_p.w);
    } else if (su.u_stripe == 2) {
        base = su.u_stripe_a;
    } else if (su.u_use_vcol == 1) {
        base *= s_in.col.rgb;
    }
    if (su.u_mottle == 1 && !flat_on) {
        let n = fbm(s_in.opos * su.u_mottle_p.x, i32(su.u_mottle_p.w));
        let f = smoothstep(su.u_mottle_p.y, su.u_mottle_p.z, n);
        base = mix(su.u_mottle_a, su.u_mottle_b, f);
    }
    var alpha = su.u_alpha;
    if (su.u_has_tex == 1) {
        let t = textureSampleGrad(t_tex, samp_tex, s_in.uv, s_in.uv_dx, s_in.uv_dy);
        base *= t.rgb;
        alpha *= t.a;
    }
    base = tissue_color(base, s_in.opos, false);
    s.albedo = base * (1.0 - su.u_metal);
    s.f0 = mix(vec3<f32>(su.u_f0), base, su.u_metal);
    s.alpha = alpha;
    s.rough = clamp(su.u_rough, 0.04, 1.0);
    s.metal = su.u_metal;
    return s;
}

// One light.  `L` is the direction toward the light, `E` its radiance, `size` its equal-area radius.
fn light_contrib(L: vec3<f32>, E: vec3<f32>, size: f32, s: Surface, N: vec3<f32>, V: vec3<f32>, NoV: f32,
                 occl: f32) -> vec3<f32> {
    let NoL = dot(N, L);
    let lam = max(NoL, 0.0);
    let w = su.u_wrap;
    let wr = max((NoL + w) / (1.0 + w), 0.0);
    if (wr <= 0.0) { return vec3<f32>(0.0); }
    let sh = shadow_off();
    // subsurface-style wrap: the light that wraps past the terminator is tinted by the tissue colour
    let tint = sqrt(clamp(s.albedo / max(max(s.albedo.r, max(s.albedo.g, s.albedo.b)), 1e-3), vec3<f32>(0.0),
                          vec3<f32>(1.0)));
    let diff = s.albedo / PI * (lam * sh + (wr - lam) * tint * mix(sh, 1.0, 0.5));
    var spec = vec3<f32>(0.0);
    if (lam > 0.0) {
        let H = normalize(L + V);
        let NoH = max(dot(N, H), 0.0);
        let VoH = max(dot(V, H), 0.0);
        let a = s.rough * s.rough;
        let a2 = clamp(a + size * 0.5, 0.0, 1.0);        // area-light widening (Karis)
        let norm = (a / a2) * (a / a2);
        spec = D_ggx(NoH, a2) * norm * V_smith(NoV, lam, a) * F_schlick(s.f0, VoH) * lam * sh;
    }
    return (diff + spec) * E * occl;
}

fn shade_opaque(s_in: SurfaceIn, s: Surface, N: vec3<f32>, V: vec3<f32>) -> vec3<f32> {
    let NoV = max(dot(N, V), 1e-4);
    var ao = 1.0;
    var gi = vec3<f32>(0.0);
    if (su.u_ao_on > 0.5) {
        let aog = textureSampleLevel(t_ao, samp_ao, s_in.pixel / su.u_screen, 0.0);
        ao = aog.a;
        gi = aog.rgb;
    }
    let occl = mix(1.0, ao, su.u_ao_direct);
    var col = vec3<f32>(0.0);
    col += light_contrib(su.u_ldir0, su.u_lrad0, su.u_lsize0, s, N, V, NoV, occl);
    col += light_contrib(su.u_ldir1, su.u_lrad1, su.u_lsize1, s, N, V, NoV, occl);
    col += light_contrib(su.u_ldir2, su.u_lrad2, su.u_lsize2, s, N, V, NoV, occl);
    let vm = mat3x3<f32>(su.u_view[0].xyz, su.u_view[1].xyz, su.u_view[2].xyz);   // mat3(u_view)
    let Nc = vm * N;
    let Vc = vm * V;
    let Rc = reflect(-Vc, Nc);
    let ab = env_brdf(s.rough, NoV);
    let amb_d = s.albedo * sh_irradiance(Nc) / PI * su.u_env_diffuse;
    let amb_s = env_spec(Rc, s.rough) * (s.f0 * ab.x + ab.y) * su.u_env_spec;
    col += amb_d * multibounce(ao, s.albedo) + amb_s * ao;
    col += s.albedo * gi * su.u_bounce;
    return col;
}

fn highlight_mix(col: vec3<f32>, NoV: f32, amount: f32, hcol: vec3<f32>) -> vec3<f32> {
    let fr = pow(1.0 - NoV, 2.0);
    return mix(col, col * 0.7 + hcol * (0.10 + 0.55 * fr), amount);
}

fn item_highlight(item: i32, col: vec3<f32>, NoV: f32) -> vec3<f32> {
    if (su.u_batched == 1) { return highlight_mix(col, NoV, item_row(item, 0).z, item_row(item, 2).rgb); }
    return highlight_mix(col, NoV, su.u_highlight, su.u_highlight_col);
}

// MAIN_FS main(): clip test, surface, alpha test, shade, emission, glow, highlight.  `kill` is the GLSL discard.
fn shade_main_ex(s_in: SurfaceIn) -> ShadeOut {
    var o: ShadeOut;
    o.color = vec4<f32>(0.0);
    o.alpha = 0.0;
    o.kill = true;
    if (clipped(s_in.wpos)) { return o; }
    let s = surface(s_in);
    o.alpha = s.alpha;
    if (su.u_has_tex == 1 && su.u_alpha_cut > 0.0 && s.alpha < su.u_alpha_cut) { return o; }
    var N = normalize(s_in.wnrm);
    let V = view_vector(s_in.wpos);
    if (s_in.front_facing == (su.u_flip == 1)) { N = -N; }
    var col = shade_opaque(s_in, s, N, V);
    col += su.u_emis;
    col += s_in.glow * (s.albedo * 1.6 + vec3<f32>(0.30, 0.30, 0.26));     // a conduction impulse, a secretion
    col = item_highlight(s_in.item, col, max(dot(N, V), 1e-4));
    o.color = vec4<f32>(col, 1.0);
    o.kill = false;
    return o;
}

// Colour only: rgb as MAIN_FS writes it, a = 1.0 (a = 0.0 when GLSL would have discarded; use shade_main_ex to
// see the surface alpha).
fn shade_main(s_in: SurfaceIn) -> vec4<f32> {
    let o = shade_main_ex(s_in);
    return vec4<f32>(o.color.rgb, select(1.0, 0.0, o.kill));
}
