// Geometry fetches, shared by every pass that reads the compact pages (visbuf, resolve, oit, caps, cull_vis, cull_gather).
// This file and app/gpu/geometry.py are the only places that know how a page is laid out.
//
// A page is one buffer of uint32 words: positions, normals, the variable streams, the animation stream and the uint32
// index data, each section starting at a 256-byte aligned word offset. The pipeline's prelude (geometry.py geom_prelude)
// declares the page buffers it binds and defines
//     fn geo_word(lp: u32, word: u32) -> u32          word `word` of page `lp` (the pipeline's own page number)
//     fn geo_off(lp: u32, section: u32) -> u32        first word of a section (G_* below)
// Element indices are the page's: v = page-local vertex, or for g_dpos / g_dnrm / g_anim the float / word index inside the
// stream (the part tables hold the stream bases, ptab in wgsl/tables.wgsl).

const G_POS: u32 = 0u;
const G_NRM: u32 = 1u;
const G_DPOS: u32 = 2u;
const G_DNRM: u32 = 3u;
const G_FIB: u32 = 4u;
const G_COL: u32 = 5u;
const G_UV: u32 = 6u;
const G_ANIM: u32 = 7u;
const G_INDEX: u32 = 8u;

fn g_index(lp: u32, i: u32) -> u32 {
    return geo_word(lp, geo_off(lp, G_INDEX) + i);
}

fn g_pos(lp: u32, v: u32) -> vec3<f32> {
    let o = geo_off(lp, G_POS) + 3u * v;
    return vec3<f32>(bitcast<f32>(geo_word(lp, o)), bitcast<f32>(geo_word(lp, o + 1u)), bitcast<f32>(geo_word(lp, o + 2u)));
}

fn g_nrm(lp: u32, v: u32) -> u32 {
    return geo_word(lp, geo_off(lp, G_NRM) + v);
}

fn g_fib(lp: u32, v: u32) -> f32 {
    return bitcast<f32>(geo_word(lp, geo_off(lp, G_FIB) + v));
}

fn g_col(lp: u32, v: u32) -> vec4<f32> {
    let o = geo_off(lp, G_COL) + 4u * v;
    return vec4<f32>(bitcast<f32>(geo_word(lp, o)), bitcast<f32>(geo_word(lp, o + 1u)),
                     bitcast<f32>(geo_word(lp, o + 2u)), bitcast<f32>(geo_word(lp, o + 3u)));
}

fn g_uv(lp: u32, v: u32) -> vec2<f32> {
    let o = geo_off(lp, G_UV) + 2u * v;
    return vec2<f32>(bitcast<f32>(geo_word(lp, o)), bitcast<f32>(geo_word(lp, o + 1u)));
}

// morph target streams: i = 3 * vertex + component
fn g_dpos(lp: u32, i: u32) -> f32 {
    return bitcast<f32>(geo_word(lp, geo_off(lp, G_DPOS) + i));
}

fn g_dnrm(lp: u32, i: u32) -> f32 {
    return bitcast<f32>(geo_word(lp, geo_off(lp, G_DNRM) + i));
}

// procedural animation stream: 9 words per vertex (8 words of float16 pairs = four morph targets xyzw, then the float32 phase)
fn g_anim(lp: u32, i: u32) -> u32 {
    return geo_word(lp, geo_off(lp, G_ANIM) + i);
}
