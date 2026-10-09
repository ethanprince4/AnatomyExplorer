// Vertex math of the model viewer: a WGSL port of GEOM_VS (app/viewer/shaders.py:22-77).
//
// Pure functions, no entry points, no resources, no vertex buffer layout: the caller decodes the attributes
// (however they are stored or compressed), supplies the per-part data and gets back what the fragment stage needs.
// Concatenate with shading.wgsl (a vertex-pulling or visibility-buffer pass can call vs_math from any stage).
//
// Differences from GLSL, all handled here:
//  * Matrices are column-major in both; PartXf is a plain value struct (no uniform layout).  `nmat` is the GLSL
//    u_nmat (= inverse(M[:3,:3]).T, renderer.py:_transform) and multiplies as nmat * n.
//  * Clip space: GL clips z to [-w, w], WebGPU to [0, w].  `VtxOut.clip` is already in WebGPU convention:
//    z' = 0.5 * (z + w), computed from GL's u_viewproj * w.  (Camera matrices stay exactly as the GL renderer builds them.)
//  * int(u_ag.x + 0.5) and i32(...) both truncate toward zero; fract/smoothstep/exp are identical in both languages.
//  * v_item is a flat float in GLSL; here the item is an i32 (int(v_item + 0.5) is what the fragment shader uses).
//  * GLSL `w` (the morph weights vec4) and `w` (the world position vec4) share a name in GEOM_VS; they are
//    `aw` and `wp` here.

// Decoded vertex attributes (GLSL in_*).  m0..m3 and phase are only read when PartXf.anim == 1.
struct VtxAttr {
    pos: vec3<f32>,
    nrm: vec3<f32>,
    dpos: vec3<f32>,        // the glTF morph target, blended with PartXf.weight
    dnrm: vec3<f32>,
    fib: f32,
    col: vec4<f32>,
    uv: vec2<f32>,
    m0: vec4<f32>,          // procedural animation morph targets (xyz used)
    m1: vec4<f32>,
    m2: vec4<f32>,
    m3: vec4<f32>,
    phase: f32,
    item: f32,              // in_item
}

// Per-part (and per-item animation) data (GLSL u_model, u_nmat, u_viewproj, u_weight, u_anim, u_anim_t, u_aw, u_ag).
struct PartXf {
    model: mat4x4<f32>,
    nmat: mat3x3<f32>,
    viewproj: mat4x4<f32>,
    weight: f32,
    anim: i32,              // 1: the procedural animation buffer is bound
    anim_t: f32,            // cycle phase 0..1
    aw: vec4<f32>,          // this item's four morph weights
    ag: vec4<f32>,          // (mode, glow, decay, rate)
}

// What the fragment stage interpolates (GLSL v_*), plus the clip position.
struct VtxOut {
    clip: vec4<f32>,        // WebGPU clip space (z in [0, w])
    wpos: vec3<f32>,
    wnrm: vec3<f32>,
    opos: vec3<f32>,
    fib: f32,
    col: vec4<f32>,
    uv: vec2<f32>,
    glow: f32,
    item: i32,
}

fn vs_math(a: VtxAttr, x: PartXf) -> VtxOut {
    var o: VtxOut;
    o.item = i32(a.item + 0.5);
    var p = a.pos + x.weight * a.dpos;
    let n = a.nrm + x.weight * a.dnrm;
    o.glow = 0.0;
    if (x.anim == 1) {
        var aw = x.aw;
        let mode = i32(x.ag.x + 0.5);
        if (mode == 1) {                // particles on their own clocks along a curved path
            let tau = fract(fma(x.anim_t, x.ag.w, a.phase));
            aw = vec4<f32>(tau, tau * tau, 1.0 - smoothstep(0.0, 0.06, tau) * (1.0 - smoothstep(0.90, 1.0, tau)), aw.w);
        }
        p += aw.x * a.m0.xyz + aw.y * a.m1.xyz + aw.z * a.m2.xyz + aw.w * a.m3.xyz;
        if (mode == 2) {                // a wave of activation: lights up at its phase, then fades
            let dt = fract(x.anim_t - a.phase);
            o.glow = x.ag.y * smoothstep(0.0, 0.006, dt) * exp(-dt / max(x.ag.z, 1e-3));
        } else {
            o.glow = x.ag.y;
        }
    }
    let wp = x.model * vec4<f32>(p, 1.0);
    o.wpos = wp.xyz;
    o.wnrm = x.nmat * n;
    o.opos = a.pos;
    o.fib = a.fib;
    o.col = a.col;
    o.uv = a.uv;
    let cl = x.viewproj * wp;
    o.clip = vec4<f32>(cl.x, cl.y, 0.5 * (cl.z + cl.w), cl.w);
    return o;
}
