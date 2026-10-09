// Full-screen post passes, ported from app/viewer/shaders.py (FSQ_VS, BACKDROP_FS, BLIT_FS, SSAO_FS, BLUR_FS,
// PREFILTER_FS, COMPOSITE_FS). This file is prepended to every post_*.wgsl pass by app/gpu/post.py.
//
// GLSL -> WGSL semantic differences handled:
//  1. ROW ORDER. Every texture these passes read or write keeps GL's row order (row 0 = bottom of the picture,
//     v_uv.y = 0 there). The vertex shader maps uv.y = 0 to clip y = +1 (row 0 in wgpu), so v_uv, the fragment's
//     @builtin(position).xy (== gl_FragCoord.xy, same half-pixel centres and same row index), the SSAO projection,
//     the backdrop gradient, the outline taps and both ign() dither patterns port verbatim. Consequence for the
//     renderer: geometry passes must write bottom-up (negate clip y, swap the front face), and the final image must
//     be flipped on read-back exactly as GL's read_final does. Mirroring instead would move nearest-sampler ties.
//  2. textureSample() needs uniform control flow; these shaders sample inside early returns, loops with
//     continue/break and ifs, so every fetch is textureSampleLevel(.., 0.0) (GL texture() had no mips there).
//  3. Samplers are separate objects: nearest (non-filtering, for rgba32float nd and rg32float id which are
//     unfilterable-float) and linear (GL's default LINEAR for ao, opaque, accum, weight, prev). All clamp: the GL
//     targets set repeat_x = repeat_y = False. Environment source: linear + mip-linear, repeat in u, clamp in v.
//  4. GLSL ternary a ? b : c -> select(c, b, a) (argument order reversed, both sides evaluated) or an if where
//     the branch has side effects or cost (edge_sel / edge_id / the GI block).
//  5. GLSL mod(x, y) (floored) -> fmod_gl(); WGSL % is truncated. atan(y, x) -> atan2(y, x). gl_VertexID -> vertex_index.
//  6. GLSL implicit int->float conversions are explicit f32()/i32()/u32(); bool flags are i32 in uniform
//     buffers (a float 1.0 read as int is not 1). Uniform structs are packed to WGSL std140-like alignment
//     (vec3 = 16-byte aligned, struct size multiple of 16) by app/gpu/post.py (offsets asserted in the tests).
//  7. `const uint COUNT` / `const int DIRS` -> module-scope const with explicit type; the hammersley masks are
//     ported literally with u suffixes (WGSL shifts on u32 behave as GLSL's: count < 32).
//  8. pow(x, y) with x == 0 is exp2(y*log2(x)) in WGSL (= 0 for y > 0, same as the GL driver); all uses clamp x >= 0.
//  9. Output formats: backdrop/ssao/blur targets are rgba16float, composite/blit rgba8unorm (non-sRGB; the shader
//     encodes sRGB itself, as in GL where the default framebuffer is linear-write). Unorm8 store rounds to nearest
//     in both APIs. nd is rgba32float, id rg32float, ao rgba16float, opaque/accum rgba16float, weight r16float
//     (identical to GL's f4/f2 formats, no precision change).
//  10. Early `return` before the end of main is legal in WGSL fragment functions; no discard is used.
//  12. v_uv interpolation noise. NVIDIA's GL and Vulkan interpolate v_uv bit-identically (0 differing pixels), Intel
//     Vulkan differs by 1 ulp (6e-8) in about half the pixels. The outline taps at u_outline_px = 1.5 (any render
//     height <= 810) land exactly on nearest-texel boundaries, so that 1-ulp noise decides which texel is read: the
//     result is hardware-dependent in GL as well. Cannot be removed without changing the picture; measured in
//     tools/perf/gpu/post_parity.py (combos A, C, D vs F).

struct VOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> VOut {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    var o: VOut;
    o.uv = p;
    o.pos = vec4<f32>(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0, 0.0, 1.0);
    return o;
}

// 11. ign(): dot(p, k) is written as fma(p.y, k.y, p.x * k.x). GLSL leaves FMA contraction to the driver; the NVIDIA
//     GL driver contracts it exactly this way (bit-identical a0 on all 921,600 pixels at 1280x720, versus 24% of
//     pixels off by up to 4e-4 * 6.28 rad with a plain dot()), and an explicit fma() makes the result deterministic
//     across WGSL back ends. The decorrelated second hash ign(frag.yx + 17.0) still differs in 1.4% of pixels
//     (ulp-level, driver-specific contraction of the +17 offset).
fn ign(p: vec2<f32>) -> f32 {
    return fract(52.9829189 * fract(fma(p.y, 0.00583715, p.x * 0.06711056)));
}

fn fmod_gl(x: f32, y: f32) -> f32 {
    return x - y * floor(x / y);
}
