// Cut-face gather: PARITY_FS and CAP_FS of app/viewer/shaders.py as a depth-only pass and an MRT pass over the geometry pages.
// Concatenated after shading.wgsl (it supplies ShadeU `su` at group 1 binding 0, bound with a dynamic offset: one record
// per cap draw; clipped(), tissue_color()) and caps_common.wgsl.
//
//   group 0: 0 CapFrame (uniform)   1 CapDraw table (read-only storage)
//   group 1: 0 ShadeU (shading.wgsl; only the clip planes and the look fields are read)
//   group 2: the page (geometry.py geom_prelude: geo_0 at binding 0, the page offsets at binding 1), read through geom.wgsl
//   group 3: 0 parity depth (cap pass only)
//
// GLSL -> WGSL: the parity pass is a depth32float depth-only pass instead of a MIN-blended r32float target (the same
// minimum of gl_FragCoord.z; float32 blending is an optional feature); gl_FragCoord.y is height - y; gl_FrontFacing is
// front_facing (frontFace ccw, as shade_parity.py verified); the cap key is quantised to 24 bits like GL's depth buffer.

struct CapDraw {
    model: mat4x4<f32>,
    col: vec4<f32>,         // the part's constant vertex colour (const_tail)
    a: vec4<u32>,           // x: colour stream offset (stream first vertex - part first vertex, wrapping), y: 1 = has a stream, z: mirrored
    b: vec4<f32>,           // item + 1, selected flag, cap darkening (0.80 tissue / 0.62 plain), 0
};

@group(0) @binding(0) var<uniform> cf: CapFrame;
@group(0) @binding(1) var<storage, read> cdraws: array<CapDraw>;
@group(3) @binding(0) var parity_tex: texture_depth_2d;

struct CapVOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,
    @location(1) col: vec4<f32>,
    @location(2) @interpolate(flat) di: u32,
};

// World position of vertex `v` (page local) of the cap draw.  HOOK: must stay identical to visbuf.wgsl vertex_world
// (the visibility pass); morph / explode / animation displacement go into both.
fn cap_vertex_world(d: CapDraw, v: u32) -> vec3<f32> {
    let p = g_pos(0u, v);
    return (d.model * vec4<f32>(p, 1.0)).xyz;
}

@vertex
fn vs_cap(@builtin(vertex_index) vi: u32, @builtin(instance_index) di: u32) -> CapVOut {
    let d = cdraws[di];
    let v = g_vertex(0u, vi);
    let w = cap_vertex_world(d, v);
    var o: CapVOut;
    o.clip = cf.vp * vec4<f32>(w, 1.0);
    o.wpos = w;
    o.di = di;
    o.col = d.col;
    if (d.a.y == 1u) {
        o.col = g_col(0u, v + d.a.x);
    }
    return o;
}

// Resets the parity depth to 1.0 inside the scissor rectangle of the item (instead of clearing the whole target).
@vertex
fn vs_reset(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 1.0, 1.0);
}

// PARITY_FS: depth of the nearest kept front face of the item (depth test "less" keeps the minimum).
@fragment
fn fs_parity(in: CapVOut, @builtin(front_facing) ff: bool) {
    if (clipped(in.wpos)) { discard; }
    if (ff == (cdraws[in.di].a.z == 1u)) { discard; }
}

// ---- CAP_FS
fn cap_plane(P: vec4<f32>, on: i32, o: vec3<f32>, d: vec3<f32>, tf: f32, best: ptr<function, f32>,
             bn: ptr<function, vec3<f32>>, found: ptr<function, bool>) {
    if (on == 0) { return; }
    let den = dot(P.xyz, d);
    if (den <= 1e-7) { return; }
    let t = -(dot(P.xyz, o) + P.w) / den;
    if (t <= 0.0 || t >= tf) { return; }
    if ((su.u_clip_mode == 1 && t < *best) || (su.u_clip_mode != 1 && t > *best)) {
        *best = t;
        *bn = P.xyz;
        *found = true;
    }
}

// the far end of the stretch of the ray that lies on the removed side (all planes negative for a corner cut)
fn cap_span(P: vec4<f32>, on: i32, o: vec3<f32>, d: vec3<f32>, t0: ptr<function, f32>, t1: ptr<function, f32>,
            n1: ptr<function, vec3<f32>>, anyp: ptr<function, bool>) {
    if (on == 0) { return; }
    let den = dot(P.xyz, d);
    let s = dot(P.xyz, o) + P.w;
    if (abs(den) < 1e-9) {
        if (s >= 0.0) { *t1 = -1.0; }
        return;
    }
    let t = -s / den;
    if (den > 0.0) {
        if (t < *t1) { *t1 = t; *n1 = P.xyz; }
    } else {
        *t0 = max(*t0, t);
    }
    *anyp = true;
}

struct CutExit {
    ok: bool,
    t: f32,
    n: vec3<f32>,
};

fn cut_exit(o: vec3<f32>, d: vec3<f32>, tf: f32) -> CutExit {
    var r: CutExit;
    var n = vec3<f32>(0.0, 1.0, 0.0);
    if (su.u_clip_mode == 1) {
        var t0 = 0.0;
        var t1 = 1e30;
        var anyp = false;
        cap_span(su.u_clip0, su.u_clip_on.x, o, d, &t0, &t1, &n, &anyp);
        cap_span(su.u_clip1, su.u_clip_on.y, o, d, &t0, &t1, &n, &anyp);
        cap_span(su.u_clip2, su.u_clip_on.z, o, d, &t0, &t1, &n, &anyp);
        r.t = t1;
        r.n = n;
        r.ok = anyp && t0 < t1 && t1 > 0.0 && t1 < tf;
        return r;
    }
    var best = -1e30;
    var found = false;
    cap_plane(su.u_clip0, su.u_clip_on.x, o, d, tf, &best, &n, &found);
    cap_plane(su.u_clip1, su.u_clip_on.y, o, d, tf, &best, &n, &found);
    cap_plane(su.u_clip2, su.u_clip_on.z, o, d, tf, &best, &n, &found);
    r.t = best;
    r.n = n;
    r.ok = found;
    return r;
}

struct CapOut {
    @location(0) albedo: vec4<f32>,         // albedo, roughness
    @location(1) normal: vec4<f32>,         // world normal, f0
    @location(2) id: vec4<f32>,             // item + 1, flags (selected 1, cut face 2), 0, 0
    @location(3) zp: vec4<f32>,             // window depth of the face on its plane
    @builtin(frag_depth) key: f32,          // how far the item's far wall lies behind the plane: the innermost item wins
};

@fragment
fn fs_cap(in: CapVOut, @builtin(front_facing) ff: bool) -> CapOut {
    let d_ = cdraws[in.di];
    if (clipped(in.wpos)) { discard; }
    if (ff != (d_.a.z == 1u)) { discard; }                                   // back faces only
    let px = vec2<i32>(i32(in.clip.x), i32(in.clip.y));
    if (textureLoad(parity_tex, px, 0) < in.clip.z) { discard; }             // entered after the cut
    let fc = vec2<f32>(in.clip.x, cf.screen.y - in.clip.y);                  // gl_FragCoord.xy
    let ndc = fc / cf.screen.xy * 2.0 - 1.0;
    let a = cf.inv_vp * vec4<f32>(ndc, -1.0, 1.0);
    let b = cf.inv_vp * vec4<f32>(ndc, 1.0, 1.0);
    let o = a.xyz / a.w;
    let d = normalize(b.xyz / b.w - o);
    let tf = dot(in.wpos - o, d);
    let ce = cut_exit(o, d, tf);
    if (!ce.ok) { discard; }
    let C = o + d * ce.t;
    let c = cf.vp_gl * vec4<f32>(C, 1.0);
    let behind = max(tf - ce.t, 0.0);
    var base = su.u_base;
    if (su.u_stripe == 1 || su.u_stripe == 2) {
        base = mix(su.u_stripe_a, su.u_stripe_b, 0.35);
    } else if (su.u_use_vcol == 1) {
        base = base * in.col.rgb;
    }
    if (su.u_mottle == 1) { base = mix(su.u_mottle_a, su.u_mottle_b, 0.5); }
    base = tissue_color(base, C, true) * d_.b.z;
    var out: CapOut;
    out.key = q24(behind / (behind + cf.screen.z));
    out.albedo = vec4<f32>(base * (1.0 - su.u_metal), clamp(su.u_rough, 0.04, 1.0));
    out.normal = vec4<f32>(-normalize(ce.n), su.u_f0);
    out.id = vec4<f32>(d_.b.x, d_.b.y + 2.0, 0.0, 0.0);
    out.zp = vec4<f32>(clamp(c.z / c.w * 0.5 + 0.5, 1e-7, 1.0), 0.0, 0.0, 0.0);
    return out;
}
