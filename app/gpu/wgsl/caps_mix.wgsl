// CAPMIX_FS: the cut faces shaded on their plane, deferred (the surface comes from the cap targets), drawn full-screen at
// the depth of the face on its plane into the frame's colour and depth targets.  Concatenated AFTER shading.wgsl
// (ShadeU `su` at group 1, shade_opaque, highlight_mix, view_vector) and caps_common.wgsl.
//
//   group 0: 0 CapFrame (uniform)
//   group 1: shading.wgsl bindings (the frame's lights / environment / AO; the same bind group the main shading uses)
//   group 2: 0 cap albedo+roughness (rgba16float)  1 cap normal+f0 (rgba16float)  2 cap id (rg32float)  3 cap zp (r32float)
//
// Pipeline state (app/gpu/caps.py), fs_mix: depth test "less" with depth WRITE on against the frame's depth (GL: depth_ms,
// and the OIT pass then tests against the cap depth too), no blending.  fs_col: no depth, one rgba32float target.  Emission, glow and the item highlight of MAIN_FS are not
// part of CAPMIX_FS.  The AO texture is addressed with the top-left pixel position (see shading.wgsl AO ORIGIN).

@group(0) @binding(0) var<uniform> cf: CapFrame;
@group(2) @binding(0) var cap_albedo: texture_2d<f32>;
@group(2) @binding(1) var cap_normal: texture_2d<f32>;
@group(2) @binding(2) var cap_id: texture_2d<f32>;
@group(2) @binding(3) var cap_zp: texture_2d<f32>;

struct MixOut {
    @location(0) color: vec4<f32>,
    @builtin(frag_depth) depth: f32,
};

// Does a cut face at window depth `zp` replace a sample whose depth is `sample_depth`?  GL: depth test "less" between the
// face (quantised to the 24 bits of the depth buffer) and the stored sample depth.  For a pass that shades per sample
// (the renderer's resolve) instead of drawing fs_mix onto a multisampled target.
fn cap_covers(zp: f32, sample_depth: f32) -> bool {
    return zp > 0.0 && q24(zp) < q24(sample_depth);
}

// CAPMIX_FS body.  cpx: texel of the cap targets (top row first); fc: GL's gl_FragCoord.xy; pixel: the AO texture's pixel
// (the row order of the target being written, see shading.wgsl AO ORIGIN).
fn cap_shade(cpx: vec2<i32>, fc: vec2<f32>, pixel: vec2<f32>, zp: f32) -> vec3<f32> {
    let ndc = fc / cf.screen.xy * 2.0 - 1.0;
    let w = cf.inv_vp * vec4<f32>(ndc, zp * 2.0 - 1.0, 1.0);
    let wpos = w.xyz / w.w;
    let alb = textureLoad(cap_albedo, cpx, 0);
    let nrm = textureLoad(cap_normal, cpx, 0);
    let idf = textureLoad(cap_id, cpx, 0).xy;
    var s_in: SurfaceIn;
    s_in.wpos = wpos;
    s_in.opos = wpos;
    s_in.col = vec4<f32>(1.0);
    s_in.pixel = pixel;
    var s: Surface;
    s.albedo = alb.rgb;
    s.alpha = 1.0;
    s.rough = alb.a;
    s.metal = 0.0;
    s.f0 = vec3<f32>(nrm.w);
    var N = normalize(nrm.xyz);
    let V = view_vector(wpos);
    if (dot(N, V) < 0.0) { N = -N; }
    var col = shade_opaque(s_in, s, N, V);
    let NoV = max(dot(N, V), 1e-4);
    let flags = i32(idf.y + 0.5);
    if ((flags & 1) != 0) {
        col = highlight_mix(col, NoV, 0.45, cf.sel_col.rgb);
    } else if (abs(idf.x - cf.hover.x) < 0.5) {
        col = highlight_mix(col, NoV, 0.18, cf.hover_col.rgb);
    }
    return col;
}

// Top-row-first colour + depth targets (the visibility buffer's): GL's CAPMIX_FS draw, depth test "less", depth write on.
@fragment
fn fs_mix(@builtin(position) pos: vec4<f32>) -> MixOut {
    let px = vec2<i32>(i32(pos.x), i32(pos.y));
    let zp = textureLoad(cap_zp, px, 0).x;
    if (zp <= 0.0) { discard; }
    var o: MixOut;
    o.color = vec4<f32>(cap_shade(px, vec2<f32>(pos.x, cf.screen.y - pos.y), pos.xy, zp), 1.0);
    o.depth = zp;
    return o;
}

// GL-row-order single-sample target (the renderer's intermediate textures): rgb = shaded cut face, a = its window depth,
// 0 where there is none.  The shading resolve decides per sample with cap_covers(a, sample depth).
@fragment
fn fs_col(@builtin(position) pos: vec4<f32>) -> @location(0) vec4<f32> {
    let px = vec2<i32>(i32(pos.x), i32(pos.y));
    let cpx = vec2<i32>(px.x, i32(cf.screen.y) - 1 - px.y);
    let zp = textureLoad(cap_zp, cpx, 0).x;
    if (zp <= 0.0) { return vec4<f32>(0.0); }
    return vec4<f32>(cap_shade(cpx, pos.xy, pos.xy, zp), zp);
}
