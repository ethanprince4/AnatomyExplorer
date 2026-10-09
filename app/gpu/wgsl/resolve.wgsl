// Resolve of the visibility buffer: the geometry resolve (ids, normals, depth: GL's single-sample pre-pass), the shaded
// resolve (GL's MSAA colour buffer, resolved), and the readback gathers.
//
// Concatenated by app/gpu/renderer.py, in this order:  the generated prelude (SAMPLES, vis_id, load_id / load_ids (culled ids already decoded to (slot << bits) | primitive), bg_tex, the pages of
// this pass: fetch_*), clip.wgsl (its `clipped` renamed `clipped_draw`: shading.wgsl has its own), shading.wgsl (its
// `su` uniform gone: every use of the su fields becomes lk_u_x() (a per-part field, read from the look record apply_look selected) or sg.u_x,
// and the copy statement of shade_tri is removed, see _su_reads), tables.wgsl (the table buffer), geom.wgsl (page fetches),
// morph.wgsl (morph / animation), then this file with the generated `apply_look(rec)` (sets the word offset of a look record) and
// the lk_<field>() readers. The FEAT_* switches of shading.wgsl are pipeline constants set from the looks of the drawn parts.
//
// ROW ORDER. Everything here is in GL's row order (row 0 = bottom of the picture): the visibility pass is rendered with the
// clip y negated (so that its 4x / 8x sample pattern, defined y-down in Vulkan and y-up in GL, lands on GL's), and every
// output texture is addressed with @builtin(position).xy == gl_FragCoord.xy. Only the gather inputs (pixels counted from
// the top) and the final blit convert.
//
// Texture passes: the shaded resolve runs once per texture slot (pass_info.x; 0 = none); a pass shades only the draws of its slot
// (draw.c.z), pass_info.y = 1 adds the backdrop of empty samples (the first pass only).
//
// Bindings (unique per module, the entry points use different subsets):
//   group 0: 0 frame  1 tab (draws, ptab, anim_tab, looks: tables.wgsl)  2 tinfo (its section offsets)  4 sg (frame-wide ShadeU)
//   group 1: shading.wgsl (1 t_items, 2 t_ao, 3 t_spec, 4 t_tex, 5..7 samplers; 0 is gone)
//   group 2: 0 vis_id (MSAA)  2 bg_tex (backdrop, rgba16float)         resolve passes
//            8 cro  9 lay: the culler's decode tables (cull_decode.wgsl, ids with bit 31 set; dummies when the model is not culled)
//            3 r_tri  4 r_id  5 r_nd                                    gathers
//   group 3: the pages (geometry.py geom_prelude: geo_i at binding i, the page offsets after them) / 60 params  61 points  62 out (gathers)

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(4) var<uniform> sg: ShadeU;

@group(2) @binding(3) var r_tri: texture_2d<u32>;
@group(2) @binding(4) var r_id: texture_2d<f32>;
@group(2) @binding(5) var r_nd: texture_2d<f32>;


@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}

// ------------------------------------------------------------------------------------------------ attributes
fn sign_nz(v: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(select(-1.0, 1.0, v.x >= 0.0), select(-1.0, 1.0, v.y >= 0.0));
}

// Octahedral normal (app/gpu/geometry.py oct_decode).
fn oct_decode(p: vec2<f32>) -> vec3<f32> {
    var n = vec3<f32>(p.x, p.y, 1.0 - abs(p.x) - abs(p.y));
    if (n.z < 0.0) {
        let q = (vec2<f32>(1.0) - abs(vec2<f32>(n.y, n.x))) * sign_nz(vec2<f32>(n.x, n.y));
        n.x = q.x;
        n.y = q.y;
    }
    return n / max(length(n), 1e-30);
}

struct Vtx {
    w: vec3<f32>,            // world position
    cl: vec4<f32>,           // clip position (frame.vp: GL x, y, w; z in [0, w])
    n: vec3<f32>,            // world normal (u_nmat * n), not normalised
    opos: vec3<f32>,         // object position
    fib: f32,
    col: vec4<f32>,
    uv: vec2<f32>,
    glow: f32,
};

struct Tri {
    v0: Vtx,
    v1: Vtx,
    v2: Vtx,
    i0: u32,
    i1: u32,
    i2: u32,
    a0: vec3<f32>,           // cross(m1, m2), cross(m2, m0), cross(m0, m1) with m_i = (x, y, w) of the clip positions
    a1: vec3<f32>,
    a2: vec3<f32>,
    det: f32,                // > 0: counter-clockwise on screen (GL front face)
    ok: bool,
};

fn vtx_geom(d: Draw, lp: u32, v: u32) -> Vtx {
    var o: Vtx;
    let p = g_pos(lp, v);
    o.opos = p;
    o.w = (d.model * vec4<f32>(morph_pos(d, lp, v, p), 1.0)).xyz;
    o.cl = frame.vp * vec4<f32>(o.w, 1.0);
    return o;
}

struct VAttr {
    n: vec3<f32>,
    fib: f32,
    col: vec4<f32>,
    uv: vec2<f32>,
    glow: f32,
};

fn vtx_attr(d: Draw, lp: u32, v: u32) -> VAttr {
    var o: VAttr;
    let part = d.b.x;
    let base = part * PTAB_STRIDE;
    let rel = v - ptab_w(base + 5u);
    let nmat = mat3x3<f32>(d.nmat0.xyz, d.nmat1.xyz, d.nmat2.xyz);
    o.n = nmat * morph_nrm(d, lp, v, oct_decode(unpack2x16snorm(g_nrm(lp, v))));
    o.glow = anim_glow(d, lp, v);
    let s_fib = bitcast<i32>(ptab_w(base + 2u));
    let s_col = bitcast<i32>(ptab_w(base + 3u));
    let s_uv = bitcast<i32>(ptab_w(base + 4u));
    if (s_fib < 0) { o.fib = bitcast<f32>(ptab_w(base + 12u)); } else { o.fib = g_fib(lp, u32(s_fib) + rel); }
    if (s_col < 0) {
        o.col = vec4<f32>(bitcast<f32>(ptab_w(base + 13u)), bitcast<f32>(ptab_w(base + 14u)),
                          bitcast<f32>(ptab_w(base + 15u)), bitcast<f32>(ptab_w(base + 16u)));
    } else {
        o.col = g_col(lp, u32(s_col) + rel);
    }
    if (s_uv < 0) { o.uv = vec2<f32>(bitcast<f32>(ptab_w(base + 17u)), bitcast<f32>(ptab_w(base + 18u))); }
    else { o.uv = g_uv(lp, u32(s_uv) + rel); }
    return o;
}

fn tri_setup(d: Draw, prim: u32, lp: u32) -> Tri {
    var t: Tri;
    let at = d.a.x + 3u * prim;
    t.i0 = g_index(lp, at);
    t.i1 = g_index(lp, at + 1u);
    t.i2 = g_index(lp, at + 2u);
    t.v0 = vtx_geom(d, lp, t.i0);
    t.v1 = vtx_geom(d, lp, t.i1);
    t.v2 = vtx_geom(d, lp, t.i2);
    let m0 = vec3<f32>(t.v0.cl.x, t.v0.cl.y, t.v0.cl.w);
    let m1 = vec3<f32>(t.v1.cl.x, t.v1.cl.y, t.v1.cl.w);
    let m2 = vec3<f32>(t.v2.cl.x, t.v2.cl.y, t.v2.cl.w);
    t.a0 = cross(m1, m2);
    t.a1 = cross(m2, m0);
    t.a2 = cross(m0, m1);
    t.det = dot(m0, t.a0);
    t.ok = abs(t.det) >= 1e-30;
    return t;
}

fn tri_attrs(d: Draw, lp: u32, tin: Tri) -> Tri {
    var t = tin;
    let a0 = vtx_attr(d, lp, t.i0);
    let a1 = vtx_attr(d, lp, t.i1);
    let a2 = vtx_attr(d, lp, t.i2);
    t.v0.n = a0.n; t.v0.fib = a0.fib; t.v0.col = a0.col; t.v0.uv = a0.uv; t.v0.glow = a0.glow;
    t.v1.n = a1.n; t.v1.fib = a1.fib; t.v1.col = a1.col; t.v1.uv = a1.uv; t.v1.glow = a1.glow;
    t.v2.n = a2.n; t.v2.fib = a2.fib; t.v2.col = a2.col; t.v2.uv = a2.uv; t.v2.glow = a2.glow;
    return t;
}

// Homogeneous weights u of the point with NDC (x, y): sum_i u_i * (x_i, y_i, w_i) = (x, y, 1). The perspective-correct
// barycentrics are u / sum(u), also outside the triangle (GL extrapolates its varyings the same way).
fn tri_u(t: Tri, c: vec2<f32>) -> vec3<f32> {
    let r = vec3<f32>(c.x, c.y, 1.0);
    return vec3<f32>(dot(r, t.a0), dot(r, t.a1), dot(r, t.a2)) / t.det;
}

fn tri_b(t: Tri, c: vec2<f32>) -> vec3<f32> {
    let u = tri_u(t, c);
    return u / (u.x + u.y + u.z);
}

fn ndc_of(p: vec2<i32>) -> vec2<f32> {
    return vec2<f32>((f32(p.x) + 0.5) / frame.screen.x * 2.0 - 1.0, (f32(p.y) + 0.5) / frame.screen.y * 2.0 - 1.0);
}

// ------------------------------------------------------------------------------------------------ geometry resolve
struct GeomOut {
    @location(0) tri: u32,                          // packed triangle id of the pixel centre, 0 background
    @location(1) id: vec2<f32>,                     // item + 1, flags (1 selected; 2, a cut face, is set by the cap pass)
    @location(2) nd: vec4<f32>,                     // view-space unit normal (facing the viewer's side), linear view depth
    @builtin(frag_depth) order: f32,                // combines the passes of several page groups (front-most wins)
};

fn lin_depth(world: vec3<f32>) -> f32 {
    return -(frame.view * vec4<f32>(world, 1.0)).z;
}

// For the pixel: the front-most triangle among those of its samples that contains the pixel CENTRE (GL's pre-pass is one
// sample at the centre). Equal depth: the smaller packed id (the earlier draw: GL's "<" keeps the first). None contains it:
// background, like GL when no triangle covers the centre.
@fragment
fn fs_geom(@builtin(position) frag: vec4<f32>) -> GeomOut {
    let px = vec2<i32>(frag.xy);
    let c = ndc_of(px);
    let bits = frame.info.x;
    let mask = (1u << bits) - 1u;
    var best_id = 0u;
    var best_depth = 3.0e38;
    var ids = load_ids(px);
    for (var s = 0; s < i32(SAMPLES); s++) {
        let id = ids[s];
        if (id == 0u) { continue; }
        let d = load_draw(id >> bits);
        if (d.a.w < GROUP_PAGE0 || d.a.w >= GROUP_PAGE0 + GROUP_PAGES) { continue; }
        var seen = false;
        for (var q = 0; q < s; q++) {
            if (ids[q] == id) { seen = true; }
        }
        if (seen) { continue; }
        let t = tri_setup(d, id & mask, d.a.w - GROUP_PAGE0);
        if (!t.ok) { continue; }
        let u = tri_u(t, c);
        let sum = u.x + u.y + u.z;
        let tol = -1e-5 * sum;
        if (!(sum > 0.0) || u.x < tol || u.y < tol || u.z < tol) { continue; }
        let z = u.x * t.v0.cl.z + u.y * t.v1.cl.z + u.z * t.v2.cl.z;
        if (z < 0.0 || z > 1.0) { continue; }                           // cut by the near or far plane
        let b = u / sum;
        let world = b.x * t.v0.w + b.y * t.v1.w + b.z * t.v2.w;
        if (clipped_draw(frame.clip, world, (d.b.z & DRAW_NOCLIP) != 0u)) { continue; }
        let depth = lin_depth(world);
        if (depth != depth) { continue; }
        if (depth < best_depth || (depth == best_depth && id < best_id)) {
            best_depth = depth;
            best_id = id;
        }
    }
    if (best_id == 0u) { discard; }
    let d = load_draw(best_id >> bits);
    let t = tri_attrs(d, d.a.w - GROUP_PAGE0, tri_setup(d, best_id & mask, d.a.w - GROUP_PAGE0));
    let b = tri_b(t, c);
    let wn = b.x * t.v0.n + b.y * t.v1.n + b.z * t.v2.n;
    let vm = mat3x3<f32>(frame.view[0].xyz, frame.view[1].xyz, frame.view[2].xyz);
    var n = normalize(vm * wn);
    let front = (t.det > 0.0) != ((d.b.z & DRAW_MIRRORED) != 0u);
    if (!front) { n = -n; }
    var o: GeomOut;
    o.tri = best_id;
    o.id = vec2<f32>(f32(d.b.y + 1u), select(0.0, 1.0, (d.b.z & DRAW_SELECTED) != 0u));
    o.nd = vec4<f32>(n, best_depth);
    o.order = 0.5 * clamp(best_depth / max(frame.halves.w, 1e-6), 0.0, 1.0);
    return o;
}

// ------------------------------------------------------------------------------------------------ shaded resolve
// Round to the 16-bit float GL's colour buffer holds.
fn q16(v: vec3<f32>) -> vec3<f32> {
    let c = clamp(v, vec3<f32>(-65504.0), vec3<f32>(65504.0));
    let a = unpack2x16float(pack2x16float(c.xy));
    let b = unpack2x16float(pack2x16float(vec2<f32>(c.z, 0.0)));
    return vec3<f32>(a.x, a.y, b.x);
}

fn fib_at(t: Tri, p: vec2<i32>) -> f32 {
    let b = tri_b(t, ndc_of(p));
    return b.x * t.v0.fib + b.y * t.v1.fib + b.z * t.v2.fib;
}

fn uv_at(t: Tri, p: vec2<i32>) -> vec2<f32> {
    let b = tri_b(t, ndc_of(p));
    return b.x * t.v0.uv + b.y * t.v1.uv + b.z * t.v2.uv;
}

// One triangle at the pixel centre: MAIN_FS with GL's varyings (perspective-correct, extrapolated on the triangle's plane).
// GL's implicit derivatives are quad differences: fwidth() of the stripe coordinate is the FINE pair (same row / column),
// the texture LOD uses the COARSE pair of the quad (here its lower-left pixel), see shading.wgsl note 6.
fn shade_tri(d: Draw, prim: u32, px: vec2<i32>, c: vec2<f32>, frag: vec2<f32>, fallback: vec3<f32>) -> vec3<f32> {
    let lp = d.a.w - GROUP_PAGE0;
    let t0 = tri_setup(d, prim, lp);
    if (!t0.ok) { return fallback; }
    let t = tri_attrs(d, lp, t0);
    su = sg;
    apply_look(bitcast<u32>(d.c.y));
    let b = tri_b(t, c);
    var si: SurfaceIn;
    si.wpos = b.x * t.v0.w + b.y * t.v1.w + b.z * t.v2.w;
    si.wnrm = b.x * t.v0.n + b.y * t.v1.n + b.z * t.v2.n;
    si.opos = b.x * t.v0.opos + b.y * t.v1.opos + b.z * t.v2.opos;
    si.fib = b.x * t.v0.fib + b.y * t.v1.fib + b.z * t.v2.fib;
    si.col = b.x * t.v0.col + b.y * t.v1.col + b.z * t.v2.col;
    si.uv = b.x * t.v0.uv + b.y * t.v1.uv + b.z * t.v2.uv;
    si.glow = b.x * t.v0.glow + b.y * t.v1.glow + b.z * t.v2.glow;
    si.item = i32(d.b.y);
    si.front_facing = t.det > 0.0;
    si.pixel = frag;
    si.uv_dx = vec2<f32>(0.0);
    si.uv_dy = vec2<f32>(0.0);
    si.fib_dx = 0.0;
    si.fib_dy = 0.0;
    let q = vec2<i32>(px.x & ~1, px.y & ~1);
    if (FEAT_STRIPE && su.u_stripe == 1) {
        si.fib_dx = fib_at(t, vec2<i32>(q.x + 1, px.y)) - fib_at(t, vec2<i32>(q.x, px.y));
        si.fib_dy = fib_at(t, vec2<i32>(px.x, q.y + 1)) - fib_at(t, vec2<i32>(px.x, q.y));
    }
    if (FEAT_TEX && su.u_has_tex == 1) {
        let u00 = uv_at(t, q);
        si.uv_dx = uv_at(t, vec2<i32>(q.x + 1, q.y)) - u00;
        si.uv_dy = uv_at(t, vec2<i32>(q.x, q.y + 1)) - u00;
    }
    let o = shade_main_ex(si);
    if (o.kill) { return fallback; }
    return o.color.rgb;
}

// GL's MSAA colour buffer, resolved: every sample holds the colour of the front-most triangle covering it (shaded once per
// pixel and triangle, at the pixel centre, as the rasteriser does) or the backdrop; the resolve averages the 16-bit values.
// Several page groups add their share (the target blends additively); the backdrop is added by the first group only.
@fragment
fn fs_shade(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let px = vec2<i32>(frag.xy);
    let c = ndc_of(px);
    let bits = frame.info.x;
    let mask = (1u << bits) - 1u;
    let bgc = textureLoad(bg_tex, px, 0).rgb;
    var ids = load_ids(px);
    // Cut faces (caps.py): rgb = shaded face, a = its window depth (0 = none). A sample it passes the depth test on is the face,
    // not the surface (GL: CAPMIX_FS draws into the MSAA buffer); marked CAP_SAMPLE so that it joins no triangle's count.
    let cc = textureLoad(cap_col, px, 0);
    if (pass_info.z != 0u && cc.a > 0.0) {
        for (var s = 0; s < i32(SAMPLES); s++) {
            if (cap_covers(cc.a, load_depth(px, s))) { ids[s] = CAP_SAMPLE; }
        }
    }
    var acc = vec3<f32>(0.0);
    var counted = 0u;
    for (var s = 0; s < i32(SAMPLES); s++) {
        let id = ids[s];
        if (id == CAP_SAMPLE) {
            if (pass_info.y == 1u) {
                acc += q16(cc.rgb);
                counted++;
            }
            continue;
        }
        if (id == 0u) {
            if (pass_info.y == 1u) {
                acc += bgc;
                counted++;
            }
            continue;
        }
        let d = load_draw(id >> bits);
        if (d.a.w < GROUP_PAGE0 || d.a.w >= GROUP_PAGE0 + GROUP_PAGES) { continue; }
        if (bitcast<u32>(d.c.z) != pass_info.x) { continue; }
        var first = true;
        var count = 1u;
        for (var q = 0; q < i32(SAMPLES); q++) {
            if (ids[q] == id) {
                if (q < s) { first = false; }
                if (q > s) { count++; }
            }
        }
        if (!first) { continue; }
        acc += q16(shade_tri(d, id & mask, px, c, frag.xy, bgc)) * f32(count);
        counted += count;
    }
    if (counted == 0u) { discard; }
    let inv = 1.0 / f32(SAMPLES);
    return vec4<f32>(acc * inv, f32(counted) * inv);
}

// ------------------------------------------------------------------------------------------------ gathers
fn flip_row(p: vec2<i32>) -> vec2<i32> {
    return vec2<i32>(p.x, i32(frame.screen.y) - 1 - p.y);
}

struct Params {
    full: vec2<u32>,
    grid: vec2<u32>,
    step: u32,
    count: u32,
    pad: vec2<u32>,
};
@group(3) @binding(60) var<uniform> prm: Params;
@group(3) @binding(61) var<storage, read> pts: array<vec2<i32>>;
@group(3) @binding(62) var<storage, read_write> outv: array<vec4<f32>>;

// One cell of the label grid (GL read_label_samples): ids and flags at the cell origin, depth and id at its centre.
// Cells are counted from the top; the origin is the cell's top-left pixel, the centre origin + step / 2 clamped.
@compute @workgroup_size(8, 8, 1)
fn cs_labels(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= prm.grid.x || g.y >= prm.grid.y) {
        return;
    }
    let origin = vec2<i32>(i32(g.x * prm.step), i32(g.y * prm.step));
    let centre = min(origin + vec2<i32>(i32(prm.step / 2u)), vec2<i32>(prm.full) - 1);
    let a = textureLoad(r_id, flip_row(origin), 0);
    let b = textureLoad(r_id, flip_row(centre), 0);
    outv[g.y * prm.grid.x + g.x] = vec4<f32>(a.x, a.y, textureLoad(r_nd, flip_row(centre), 0).w, b.x);
}

// Points (x, y from the top-left): item + 1, flags, depth, triangle id (bits of the u32).
@compute @workgroup_size(64, 1, 1)
fn cs_points(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= prm.count) {
        return;
    }
    let p = flip_row(pts[g.x]);
    let a = textureLoad(r_id, p, 0);
    outv[g.x] = vec4<f32>(a.x, a.y, textureLoad(r_nd, p, 0).w, bitcast<f32>(textureLoad(r_tri, p, 0).x));
}
