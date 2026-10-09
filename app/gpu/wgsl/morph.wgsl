// Vertex displacement shared by the visibility pass and the resolve: GEOM_VS's glTF morph target (position + weight * dpos,
// normal + weight * dnrm) and the procedural animation (app/viewer/shaders.py GEOM_VS, vertex.wgsl vs_math), pulled from the
// compact page streams. Both passes must call these with the same arguments, or ids and shading planes disagree.
//
// Concatenated after clip.wgsl (Draw), tables.wgsl and geom.wgsl (g_dpos / g_dnrm: float index, g_anim: word index; 9 words per vertex).
//
// ptab / anim_tab: wgsl/tables.wgsl (ptab_w, anim_at). The streams: wgsl/geom.wgsl (g_dpos, g_dnrm, g_anim).

// Pipeline constants set by the renderer from the frame's drawn items (renderer.FEAT_MORPH / FEAT_ANIM): false compiles the
// morph-target / procedural-animation code out; it is only set when no drawn item has a non-zero weight / an animation, so the
// branches below would not have run.
override FEAT_MORPH: bool = true;
override FEAT_ANIM: bool = true;

fn ptab_f(i: u32) -> f32 {
    return bitcast<f32>(ptab_w(i));
}

// stream 0: dpos, 1: dnrm (object space); the part's constant where the stream is not stored.
fn part_delta(d: Draw, lp: u32, v: u32, stream: u32) -> vec3<f32> {
    let base = d.b.x * PTAB_STRIDE;
    let s = bitcast<i32>(ptab_w(base + stream));
    if (s < 0) {
        let t = base + 6u + 3u * stream;
        return vec3<f32>(ptab_f(t), ptab_f(t + 1u), ptab_f(t + 2u));
    }
    let i = 3u * (u32(s) + v - ptab_w(base + 5u));
    if (stream == 0u) {
        return vec3<f32>(g_dpos(lp, i), g_dpos(lp, i + 1u), g_dpos(lp, i + 2u));
    }
    return vec3<f32>(g_dnrm(lp, i), g_dnrm(lp, i + 1u), g_dnrm(lp, i + 2u));
}

fn anim_on(d: Draw) -> bool {
    return FEAT_ANIM && anim_at(3u * d.b.y + 2u).y > 0.5;
}

// First word of the vertex in the page's anim stream, or 0xffffffff when the part carries no animation data.
fn anim_word(d: Draw, v: u32) -> u32 {
    let base = d.b.x * PTAB_STRIDE;
    let s = bitcast<i32>(ptab_w(base + 19u));
    if (s < 0) {
        return 0xffffffffu;
    }
    return 9u * (u32(s) + v - ptab_w(base + 5u));
}

fn anim_target(lp: u32, w: u32, k: u32) -> vec3<f32> {
    let xy = unpack2x16float(g_anim(lp, w + 2u * k));
    let zw = unpack2x16float(g_anim(lp, w + 2u * k + 1u));
    return vec3<f32>(xy.x, xy.y, zw.x);
}

fn anim_phase(d: Draw, lp: u32, v: u32) -> f32 {
    let w = anim_word(d, v);
    if (w == 0xffffffffu) {
        return 0.0;
    }
    return bitcast<f32>(g_anim(lp, w + 8u));
}

// Object-space position with the morph target and the animation applied (GEOM_VS: p = in_pos + u_weight * in_dpos; p += ...).
fn morph_pos(d: Draw, lp: u32, v: u32, pos: vec3<f32>) -> vec3<f32> {
    var p = pos;
    if (FEAT_MORPH && d.c.x != 0.0) {
        p = pos + d.c.x * part_delta(d, lp, v, 0u);
    }
    if (anim_on(d)) {
        let w = anim_word(d, v);
        if (w != 0xffffffffu) {
            let at = 3u * d.b.y;
            var aw = anim_at(at);
            let ag = anim_at(at + 1u);
            let t = anim_at(at + 2u).x;
            if (i32(ag.x + 0.5) == 1) {             // particles on their own clocks along a curved path
                let tau = fract(fma(t, ag.w, bitcast<f32>(g_anim(lp, w + 8u))));
                aw = vec4<f32>(tau, tau * tau, 1.0 - smoothstep(0.0, 0.06, tau) * (1.0 - smoothstep(0.90, 1.0, tau)), aw.w);
            }
            p += aw.x * anim_target(lp, w, 0u) + aw.y * anim_target(lp, w, 1u) + aw.z * anim_target(lp, w, 2u)
                + aw.w * anim_target(lp, w, 3u);
        }
    }
    return p;
}

fn morph_nrm(d: Draw, lp: u32, v: u32, nrm: vec3<f32>) -> vec3<f32> {
    if (FEAT_MORPH && d.c.x != 0.0) {
        return nrm + d.c.x * part_delta(d, lp, v, 1u);
    }
    return nrm;
}

// v_glow: the item's glow, or a wave that lights up at the vertex's phase and fades (mode 2).
fn anim_glow(d: Draw, lp: u32, v: u32) -> f32 {
    if (!anim_on(d)) {
        return 0.0;
    }
    let at = 3u * d.b.y;
    let ag = anim_at(at + 1u);
    if (i32(ag.x + 0.5) == 2) {
        let dt = fract(anim_at(at + 2u).x - anim_phase(d, lp, v));
        return ag.y * smoothstep(0.0, 0.006, dt) * exp(-dt / max(ag.z, 1e-3));
    }
    return ag.y;
}
