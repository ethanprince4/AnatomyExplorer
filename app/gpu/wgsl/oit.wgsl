// Weighted blended order-independent transparency of the model viewer (translucent and x-rayed "ghost" parts):
// a WGSL port of OIT_FS (app/viewer/shaders.py:759-810) with GEOM_VS's vertex math, plus the multisample resolve that
// feeds the composite pass.  Concatenated by app/gpu/oit.py after vertex.wgsl + shading.wgsl (they own VtxAttr, PartXf,
// vs_math, SurfaceIn, Surface, su, t_*, samp_*, surface(), light_contrib(), item_highlight(), ...).
//
// BIND GROUPS
//   0  (vertex + fragment)  @binding(0) uniform ofr : OitFrame      GL view-projection (z is remapped here)
//                           @binding(1) storage read odraws : array<OitDraw>   one record per draw, indexed by instance_index
//   1  shading.wgsl's group 1 (binding 0 = `su`, bound with a dynamic offset: one ShadeU record per draw)
//   2  (vertex)             the geometry page, geometry.py's streams as read-only storage buffers
//   (resolve entry points use their own layout: group 0 = the two multisampled targets)
//
// DIFFERENCES FROM OIT_FS / GEOM_VS (all deliberate)
//  1. Vertex pulling.  Attributes are read from geometry.py's compact page: position f32x3, octahedral normal
//     (unpack2x16snorm, geometry.oct_decode), and the five variable streams (dpos, dnrm, fib, col, uv) through the
//     part's stream base, or the part's constant tail where the stream is constant.  in_item is the draw's item.
//     The procedural animation streams come from the page's 'anim' stream and the renderer's per-item table (oanim).
//  2. Derivatives.  GLSL takes the texture LOD and fwidth(v_fib) implicitly; here uv uses the COARSE quad difference and
//     the fibre coordinate the FINE one (what GL does on NVIDIA, measured in shade_parity.py), all computed at the top of
//     the entry point in uniform control flow.  OIT_FS discards clipped fragments before surface() (undefined
//     derivatives next to a cut, the same latent bug as MAIN_FS); here every lane has defined derivatives and the
//     discard is last.
//  3. Clip space.  The clip position is ofr.vp * vec4(world, 1) with the same pre-remapped matrix and expression as visbuf.wgsl (vs_math's own
//     clip is not used), so ghost and opaque depths agree bit for bit; gl_FragCoord.z equals @builtin(position).z (both 0..1 of the same
//     GL depth range), so the weight uses it unchanged.  The target is NOT flipped: rows are top-first like the
//     visibility pass's depth, which this pass depth-tests against.  `oit_resolve` flips into GL row order.
//  4. The OIT-only uniforms (u_facing, u_facing_on, u_ghost, u_ghost_alpha, u_alpha_mul) are fields of the draw record.
//  5. Light occlusion is the constant 1.0, no AO / multibounce / bounce / u_emis (as OIT_FS), the order of the
//     operations is OIT_FS's: facing mix, opacity (x item opacity when batched), lights, environment, glow, ghost
//     recolour, highlight, clamp, weight.
//  6. The luminance of the ghost recolour uses dot3f (shading.wgsl item 16: NVIDIA's rounding of a GLSL vec3 dot).

struct OitFrame {
    vp: mat4x4<f32>,        // GL_TO_WGPU_Z * GL view-projection (z remapped to 0..1), column-major, as the visibility pass's frame.vp
    size: vec4<f32>,        // target width, height
}

struct OitDraw {
    model: mat4x4<f32>,     // u_model
    nmat0: vec4<f32>,       // u_nmat columns
    nmat1: vec4<f32>,
    nmat2: vec4<f32>,
    tail0: vec4<f32>,       // geometry.const_tail[part] (13 floats): dpos xyz, dnrm xyz, fib, col rgba, uv
    tail1: vec4<f32>,
    tail2: vec4<f32>,
    tail3: vec4<f32>,
    sb0: vec4<i32>,         // page-local first vertex of the part in the dpos, dnrm, fib, col streams (-1 = constant)
    sb1: vec4<i32>,         // uv stream base, part vertex base (page local), item, 0
    misc: vec4<f32>,        // u_weight (morph), u_ghost (0/1), u_ghost_alpha, u_alpha_mul
    facing: vec4<f32>,      // u_facing (alpha min, alpha max, exponent), u_facing_on (0/1)
}

@group(0) @binding(0) var<uniform> ofr: OitFrame;
@group(0) @binding(1) var<storage, read> odraws: array<OitDraw>;
@group(0) @binding(2) var<storage, read> oanim: array<vec4<f32>>;     // per item: u_aw, u_ag, (anim_t, on, 0, 0) (renderer anim_tab)

// group 2: the page (geometry.py geom_prelude: geo_0 at binding 0, the page offsets at binding 1) read through geom.wgsl

fn sign_nz(v: vec2<f32>) -> vec2<f32> {
    return select(vec2<f32>(-1.0), vec2<f32>(1.0), v >= vec2<f32>(0.0));
}

// geometry.oct_unpack + oct_decode
fn oct_normal(u: u32) -> vec3<f32> {
    let p = unpack2x16snorm(u);
    var n = vec3<f32>(p.x, p.y, 1.0 - abs(p.x) - abs(p.y));
    if (n.z < 0.0) {
        let q = (vec2<f32>(1.0) - abs(vec2<f32>(n.y, n.x))) * sign_nz(n.xy);
        n = vec3<f32>(q.x, q.y, n.z);
    }
    return n / max(length(n), 1e-30);
}

fn tail_at(d: OitDraw, k: i32) -> f32 {
    switch (k >> 2) {
        case 0: { return d.tail0[k & 3]; }
        case 1: { return d.tail1[k & 3]; }
        case 2: { return d.tail2[k & 3]; }
        default: { return d.tail3[k & 3]; }
    }
}

fn pull(d: OitDraw, v: i32) -> VtxAttr {
    var a: VtxAttr;
    a.pos = g_pos(0u, u32(v));
    a.nrm = oct_normal(g_nrm(0u, u32(v)));
    let l = v - d.sb1.y;                                   // vertex index inside the part
    if (d.sb0.x >= 0) {
        let i = 3 * (d.sb0.x + l);
        a.dpos = vec3<f32>(g_dpos(0u, u32(i)), g_dpos(0u, u32(i + 1)), g_dpos(0u, u32(i + 2)));
    } else {
        a.dpos = vec3<f32>(tail_at(d, 0), tail_at(d, 1), tail_at(d, 2));
    }
    if (d.sb0.y >= 0) {
        let i = 3 * (d.sb0.y + l);
        a.dnrm = vec3<f32>(g_dnrm(0u, u32(i)), g_dnrm(0u, u32(i + 1)), g_dnrm(0u, u32(i + 2)));
    } else {
        a.dnrm = vec3<f32>(tail_at(d, 3), tail_at(d, 4), tail_at(d, 5));
    }
    if (d.sb0.z >= 0) {
        a.fib = g_fib(0u, u32(d.sb0.z + l));
    } else {
        a.fib = tail_at(d, 6);
    }
    if (d.sb0.w >= 0) {
        a.col = g_col(0u, u32(d.sb0.w + l));
    } else {
        a.col = vec4<f32>(tail_at(d, 7), tail_at(d, 8), tail_at(d, 9), tail_at(d, 10));
    }
    if (d.sb1.x >= 0) {
        a.uv = g_uv(0u, u32(d.sb1.x + l));
    } else {
        a.uv = vec2<f32>(tail_at(d, 11), tail_at(d, 12));
    }
    a.m0 = vec4<f32>(0.0);
    a.m1 = vec4<f32>(0.0);
    a.m2 = vec4<f32>(0.0);
    a.m3 = vec4<f32>(0.0);
    a.phase = 0.0;
    if (d.sb1.w >= 0) {
        let w = 9u * u32(d.sb1.w + l);
        a.m0 = vec4<f32>(unpack2x16float(g_anim(0u, w)), unpack2x16float(g_anim(0u, w + 1u)));
        a.m1 = vec4<f32>(unpack2x16float(g_anim(0u, w + 2u)), unpack2x16float(g_anim(0u, w + 3u)));
        a.m2 = vec4<f32>(unpack2x16float(g_anim(0u, w + 4u)), unpack2x16float(g_anim(0u, w + 5u)));
        a.m3 = vec4<f32>(unpack2x16float(g_anim(0u, w + 6u)), unpack2x16float(g_anim(0u, w + 7u)));
        a.phase = bitcast<f32>(g_anim(0u, w + 8u));
    }
    a.item = f32(d.sb1.z);
    return a;
}

fn draw_xf(d: OitDraw) -> PartXf {
    var x: PartXf;
    x.model = d.model;
    x.nmat = mat3x3<f32>(d.nmat0.xyz, d.nmat1.xyz, d.nmat2.xyz);
    x.viewproj = ofr.vp;
    x.weight = d.misc.x;
    let at = 3 * d.sb1.z;
    let ex = oanim[at + 2];
    x.anim = select(0, 1, ex.y > 0.5);
    x.anim_t = ex.x;
    x.aw = oanim[at];
    x.ag = oanim[at + 1];
    return x;
}

struct OVOut {
    @builtin(position) pos: vec4<f32>,
    @location(0) @interpolate(perspective, centroid) wpos: vec3<f32>,      // GEOM_INPUTS: `centroid in vec3 v_wpos`
    @location(1) wnrm: vec3<f32>,
    @location(2) opos: vec3<f32>,
    @location(3) fib: f32,
    @location(4) col: vec4<f32>,
    @location(5) uv: vec2<f32>,
    @location(6) glow: f32,
    @location(7) @interpolate(flat) item: i32,
    @location(8) @interpolate(flat) slot: u32,
}

// Vertex index = the (page-local) index value; instance index = the draw record (draw_indexed first_instance).
@vertex
fn vs_oit(@builtin(vertex_index) vi: u32, @builtin(instance_index) slot: u32) -> OVOut {
    let d = odraws[slot];
    let r = vs_math(pull(d, i32(vi)), draw_xf(d));
    var o: OVOut;
    o.pos = ofr.vp * vec4<f32>(r.wpos, 1.0);          // the visibility pass's expression: bit-equal depth for coplanar parts
    if (ofr.size.z > 0.5) { o.pos.y = -o.pos.y; }      // bottom-up rasterisation (OitPass(flip_y=True))
    o.wpos = r.wpos;
    o.wnrm = r.wnrm;
    o.opos = r.opos;
    o.fib = r.fib;
    o.col = r.col;
    o.uv = r.uv;
    o.glow = r.glow;
    o.item = r.item;
    o.slot = slot;
    return o;
}

// Depth only (the opaque stand-in of the parity tool and tests): same vertex stage, no fragment stage.

struct OitOut {
    @location(0) accum: vec4<f32>,      // rgba16float: rgb += premultiplied colour * w, a *= (1 - a)
    @location(1) weight: vec4<f32>,     // r16float:    r += a * w
}

@fragment
fn fs_oit(i: OVOut, @builtin(front_facing) ff: bool) -> OitOut {
    let d = odraws[i.slot];
    var si: SurfaceIn;
    si.wpos = i.wpos;
    si.wnrm = i.wnrm;
    si.opos = i.opos;
    si.fib = i.fib;
    si.col = i.col;
    si.uv = i.uv;
    si.glow = i.glow;
    si.item = i.item;
    si.front_facing = ff;
    si.pixel = i.pos.xy;
    si.uv_dx = dpdxCoarse(i.uv);
    si.uv_dy = dpdyCoarse(i.uv);
    si.fib_dx = dpdxFine(i.fib);
    si.fib_dy = dpdyFine(i.fib);
    let s = surface(si);
    var kill = clipped(i.wpos);
    if (su.u_has_tex == 1 && su.u_alpha_cut > 0.0 && s.alpha < su.u_alpha_cut) { kill = true; }
    if (kill) { discard; }
    var N = normalize(i.wnrm);
    let V = view_vector(i.wpos);
    if (ff == (su.u_flip == 1)) { N = -N; }
    let NoV = max(dot(N, V), 1e-4);
    var a = s.alpha;
    if (d.facing.w > 0.5) {
        let facing = 1.0 - pow(NoV, d.facing.z);
        a = mix(d.facing.x, d.facing.y, facing);
    }
    let batched = su.u_batched == 1;
    a *= select(d.misc.w, item_row(i.item, 2).w, batched);
    var col = vec3<f32>(0.0);
    col += light_contrib(su.u_ldir0, su.u_lrad0, su.u_lsize0, s, N, V, NoV, 1.0);
    col += light_contrib(su.u_ldir1, su.u_lrad1, su.u_lsize1, s, N, V, NoV, 1.0);
    col += light_contrib(su.u_ldir2, su.u_lrad2, su.u_lsize2, s, N, V, NoV, 1.0);
    let vm = mat3x3<f32>(su.u_view[0].xyz, su.u_view[1].xyz, su.u_view[2].xyz);   // mat3(u_view)
    let Nc = vm * N;
    let Vc = vm * V;
    let ab = env_brdf(s.rough, NoV);
    col += s.albedo * sh_irradiance(Nc) / PI * su.u_env_diffuse;
    col += i.glow * (s.albedo * 1.6 + vec3<f32>(0.30, 0.30, 0.26));
    var spec = env_spec(reflect(-Vc, Nc), s.rough) * (s.f0 * ab.x + ab.y) * su.u_env_spec;
    var ghost = d.misc.y > 0.5;
    if (batched) { ghost = item_row(i.item, 0).w > 0.5; }
    if (ghost) {
        let l = dot3f(col, vec3<f32>(0.3, 0.59, 0.11));
        col = mix(col, vec3<f32>(l) * vec3<f32>(0.85, 0.92, 1.0), 0.55);
        spec *= 0.5;
        a = d.misc.z * (0.25 + 1.6 * pow(1.0 - NoV, 2.5));
        a = min(a, 0.85);
    }
    col = item_highlight(i.item, col, NoV);
    a = clamp(a, 0.0, 0.98);
    // Cycles mixes the whole BSDF with a transparent BSDF by alpha, so the sheen is scaled by coverage too
    let premul = (col + spec) * a;
    let lum = a;
    let z = i.pos.z;
    let w = clamp(pow(min(1.0, lum * 10.0) + 0.01, 3.0) * 1e8 * pow(1.0 - z * 0.9, 3.0), 1e-2, 300.0);
    var o: OitOut;
    o.accum = vec4<f32>(premul * w, lum);
    o.weight = vec4<f32>(lum * w, 0.0, 0.0, 0.0);
    return o;
}

// ---- resolve: average the samples of the two multisampled targets (what GL's framebuffer copy does) and write them
// in GL's row order (row 0 = bottom of the picture), the layout every post pass reads.  `MS_TEX` is replaced by
// texture_multisampled_2d<f32> or texture_2d<f32> (one sample per pixel) by app/gpu/oit.py.
@group(0) @binding(0) var r_accum: MS_TEX;
@group(0) @binding(1) var r_weight: MS_TEX;

@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}

struct ResOut {
    @location(0) accum: vec4<f32>,
    @location(1) weight: vec4<f32>,
}

@fragment
fn oit_resolve(@builtin(position) pos: vec4<f32>) -> ResOut {
    let dims = textureDimensions(r_accum);
    let px = vec2<i32>(i32(pos.x), select(i32(dims.y) - 1 - i32(pos.y), i32(pos.y), FLIP_ROWS == 0));          // output row r (GL order) <- picture row h-1-r
    let n = SAMPLE_COUNT;
    var a = vec4<f32>(0.0);
    var w = 0.0;
    for (var k = 0; k < n; k++) {
        a += textureLoad(r_accum, px, SAMPLE_ARG);
        w += textureLoad(r_weight, px, SAMPLE_ARG).r;
    }
    var o: ResOut;
    o.accum = a / f32(n);
    o.weight = vec4<f32>(w / f32(n), 0.0, 0.0, 1.0);
    return o;
}
