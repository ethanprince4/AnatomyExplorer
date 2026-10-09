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
const G_CDIR: u32 = 9u;
const G_IDX16: u32 = 10u;
const G_IDXHI: u32 = 11u;
const G_POSQ: u32 = 12u;
const G_POSF: u32 = 13u;

// Index fetch: `i` is a logical index position of the page (the ranges of GpuGeometry.ranges address them), the result the
// page-local vertex number. Uncompressed pages (GEO_CMP false, the prelude's constant): the u32 index section. Compressed
// pages: cluster c = i / 192 has a base vertex and 192 x u16 offsets (cdir, idx16); a WIDE cluster (cdir bit 31, slot in the low
// bits) keeps the low 16 bits of the vertex in idx16 and the high 16 bits in idxhi.
fn g_index(lp: u32, i: u32) -> u32 {
    if (GEO_CMP) {
        let c = i / 192u;
        let j = i - c * 192u;
        let e = geo_word(lp, geo_off(lp, G_CDIR) + c);
        let w = geo_word(lp, geo_off(lp, G_IDX16) + c * 96u + (j >> 1u));
        let lo = (w >> ((j & 1u) << 4u)) & 0xffffu;
        if ((e & 0x80000000u) == 0u) {
            return e + lo;
        }
        let h = geo_word(lp, geo_off(lp, G_IDXHI) + (e & 0x7fffffffu) * 96u + (j >> 1u));
        return lo | (((h >> ((j & 1u) << 4u)) & 0xffffu) << 16u);
    }
    return geo_word(lp, geo_off(lp, G_INDEX) + i);
}

// The three vertices of the triangle whose first logical index position is `i` (a multiple of 3, so the triangle lies in one
// 192-position cluster chunk): one cdir word and at most two idx16 words (two idxhi words for a wide cluster) instead of three
// separate g_index fetches. Same values as g_index(lp, i), g_index(lp, i + 1), g_index(lp, i + 2).
fn g_tri(lp: u32, i: u32) -> vec3<u32> {
    if (GEO_CMP) {
        let c = i / 192u;
        let j = i - c * 192u;
        let e = geo_word(lp, geo_off(lp, G_CDIR) + c);
        let k = j >> 1u;
        let o = geo_off(lp, G_IDX16) + c * 96u + k;
        let w0 = geo_word(lp, o);
        let w1 = geo_word(lp, o + 1u);
        var lo = vec3<u32>(w0 & 0xffffu, w0 >> 16u, w1 & 0xffffu);
        if ((j & 1u) != 0u) {
            lo = vec3<u32>(w0 >> 16u, w1 & 0xffffu, w1 >> 16u);
        }
        if ((e & 0x80000000u) == 0u) {
            return lo + vec3<u32>(e);
        }
        let oh = geo_off(lp, G_IDXHI) + (e & 0x7fffffffu) * 96u + k;
        let h0 = geo_word(lp, oh);
        let h1 = geo_word(lp, oh + 1u);
        var hi = vec3<u32>(h0 & 0xffffu, h0 >> 16u, h1 & 0xffffu);
        if ((j & 1u) != 0u) {
            hi = vec3<u32>(h0 >> 16u, h1 & 0xffffu, h1 >> 16u);
        }
        return lo | (hi << vec3<u32>(16u));
    }
    return vec3<u32>(geo_word(lp, geo_off(lp, G_INDEX) + i), geo_word(lp, geo_off(lp, G_INDEX) + i + 1u),
                     geo_word(lp, geo_off(lp, G_INDEX) + i + 2u));
}

// The vertex a non-indexed draw invocation `vi` (= logical index position) works on. Indexed draws of uncompressed pages hand the
// shader the index value itself, so there it is vi.
fn g_vertex(lp: u32, vi: u32) -> u32 {
    if (GEO_CMP) {
        return g_index(lp, vi);
    }
    return vi;
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
