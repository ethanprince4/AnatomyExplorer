// Vertex displacement shared by the visibility pass and the resolve: GEOM_VS's glTF morph target (position + weight * dpos,
// normal + weight * dnrm) and the procedural animation (app/viewer/shaders.py GEOM_VS, vertex.wgsl vs_math), pulled from the
// compact page streams. Both passes must call these with the same arguments, or ids and shading planes disagree.
//
// Concatenated after clip.wgsl (Draw) and a prelude that defines fetch_dpos(lp, i) / fetch_dnrm(lp, i) (float index) and
// fetch_anim(lp, i) (uint index; 9 words per vertex: 8 words of float16 pairs = four morph targets xyzw, then the float32 phase).
//
//   group 0 binding 2  ptab      per part: 0..4 stream bases (i32, -1 constant), 5 vertex base, 6..18 constant tail, 19 anim base
//   group 0 binding 5  anim_tab  per item, three vec4: morph weights (u_aw), (mode, glow, decay, rate) (u_ag), (anim_t, on, 0, 0)

@group(0) @binding(2) var<storage, read> ptab: array<u32>;
@group(0) @binding(5) var<storage, read> anim_tab: array<vec4<f32>>;

const PTAB_STRIDE: u32 = 20u;

fn ptab_f(i: u32) -> f32 {
    return bitcast<f32>(ptab[i]);
}

// stream 0: dpos, 1: dnrm (object space); the part's constant where the stream is not stored.
fn part_delta(d: Draw, lp: u32, v: u32, stream: u32) -> vec3<f32> {
    let base = d.b.x * PTAB_STRIDE;
    let s = bitcast<i32>(ptab[base + stream]);
    if (s < 0) {
        let t = base + 6u + 3u * stream;
        return vec3<f32>(ptab_f(t), ptab_f(t + 1u), ptab_f(t + 2u));
    }
    let i = 3u * (u32(s) + v - ptab[base + 5u]);
    if (stream == 0u) {
        return vec3<f32>(fetch_dpos(lp, i), fetch_dpos(lp, i + 1u), fetch_dpos(lp, i + 2u));
    }
    return vec3<f32>(fetch_dnrm(lp, i), fetch_dnrm(lp, i + 1u), fetch_dnrm(lp, i + 2u));
}

fn anim_on(d: Draw) -> bool {
    return anim_tab[3u * d.b.y + 2u].y > 0.5;
}

// First word of the vertex in the page's anim stream, or 0xffffffff when the part carries no animation data.
fn anim_word(d: Draw, v: u32) -> u32 {
    let base = d.b.x * PTAB_STRIDE;
    let s = bitcast<i32>(ptab[base + 19u]);
    if (s < 0) {
        return 0xffffffffu;
    }
    return 9u * (u32(s) + v - ptab[base + 5u]);
}

fn anim_target(lp: u32, w: u32, k: u32) -> vec3<f32> {
    let xy = unpack2x16float(fetch_anim(lp, w + 2u * k));
    let zw = unpack2x16float(fetch_anim(lp, w + 2u * k + 1u));
    return vec3<f32>(xy.x, xy.y, zw.x);
}

fn anim_phase(d: Draw, lp: u32, v: u32) -> f32 {
    let w = anim_word(d, v);
    if (w == 0xffffffffu) {
        return 0.0;
    }
    return bitcast<f32>(fetch_anim(lp, w + 8u));
}

// Object-space position with the morph target and the animation applied (GEOM_VS: p = in_pos + u_weight * in_dpos; p += ...).
fn morph_pos(d: Draw, lp: u32, v: u32, pos: vec3<f32>) -> vec3<f32> {
    var p = pos;
    if (d.c.x != 0.0) {
        p = pos + d.c.x * part_delta(d, lp, v, 0u);
    }
    if (anim_on(d)) {
        let w = anim_word(d, v);
        if (w != 0xffffffffu) {
            let at = 3u * d.b.y;
            var aw = anim_tab[at];
            let ag = anim_tab[at + 1u];
            let t = anim_tab[at + 2u].x;
            if (i32(ag.x + 0.5) == 1) {             // particles on their own clocks along a curved path
                let tau = fract(fma(t, ag.w, bitcast<f32>(fetch_anim(lp, w + 8u))));
                aw = vec4<f32>(tau, tau * tau, 1.0 - smoothstep(0.0, 0.06, tau) * (1.0 - smoothstep(0.90, 1.0, tau)), aw.w);
            }
            p += aw.x * anim_target(lp, w, 0u) + aw.y * anim_target(lp, w, 1u) + aw.z * anim_target(lp, w, 2u)
                + aw.w * anim_target(lp, w, 3u);
        }
    }
    return p;
}

fn morph_nrm(d: Draw, lp: u32, v: u32, nrm: vec3<f32>) -> vec3<f32> {
    if (d.c.x != 0.0) {
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
    let ag = anim_tab[at + 1u];
    if (i32(ag.x + 0.5) == 2) {
        let dt = fract(anim_tab[at + 2u].x - anim_phase(d, lp, v));
        return ag.y * smoothstep(0.0, 0.006, dt) * exp(-dt / max(ag.z, 1e-3));
    }
    return ag.y;
}
