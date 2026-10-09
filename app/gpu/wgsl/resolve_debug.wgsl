// Debug resolve of the visibility buffer, readback gathers and the debug picture.
//
// Concatenated by app/gpu/renderer.py after the generated prelude and clip.wgsl. The prelude supplies
//   SAMPLES, ID_BITS_UNUSED, load_id(px, s), load_depth(px, s)        (the MSAA targets, group 1 bindings 0, 1)
//   GROUP_PAGE0, GROUP_PAGES, fetch_index(local_page, i), fetch_pos(local_page, v)   (the pages of this pass, group 2)
//
// Bindings (unique per module, the entry points use different subsets):
//   group 0: 0 frame, 1 draws
//   group 1: 0 vis_id, 1 vis_depth (MSAA, resolve)   2 r_tri, 3 r_info, 4 r_depth (resolved, debug and gathers)
//            5 blit source, 6 blit sampler
//   group 2: pages (resolve) 0 .. 2 n - 1             60 params, 61 points, 62 out (gathers)

@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read> draws: array<Draw>;

@group(1) @binding(2) var r_tri: texture_2d<u32>;
@group(1) @binding(3) var r_info: texture_2d<u32>;
@group(1) @binding(4) var r_depth: texture_2d<f32>;
@group(1) @binding(5) var blit_src: texture_2d<f32>;
@group(1) @binding(6) var blit_smp: sampler;

@vertex
fn vs_fsq(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}

// ------------------------------------------------------------------------------------------------ resolve
struct Hit {
    ok: bool,
    depth: f32,
    world: vec3<f32>,
};

// Linear view depth of a wgpu depth value (the inverse of the projection's z mapping).
fn lin_from_z(z: f32) -> f32 {
    let n = frame.halves.z;
    let f = frame.halves.w;
    if (frame.info.w == 1u) {
        return z * (f - n) + n;
    }
    return f * n / (f - z * (f - n));
}

// Is the centre of the pixel (NDC point c) inside triangle `prim` of draw `d`? Perspective-correct, from the
// triangle's own vertices: solve  [x_i y_i w_i] u = (c.x, c.y, 1)  for the homogeneous weights u; the point is inside
// when every u_i >= 0 (with w_pixel = 1 / sum(u) > 0), and its world position is the u-weighted vertex mean.
fn triangle_at_centre(d: Draw, prim: u32, c: vec2<f32>) -> Hit {
    var h: Hit;
    h.ok = false;
    h.depth = 0.0;
    h.world = vec3<f32>(0.0);
    let lp = d.a.w - GROUP_PAGE0;
    let at = d.a.x + 3u * prim;
    let w0 = (d.model * vec4<f32>(fetch_pos(lp, fetch_index(lp, at)), 1.0)).xyz;
    let w1 = (d.model * vec4<f32>(fetch_pos(lp, fetch_index(lp, at + 1u)), 1.0)).xyz;
    let w2 = (d.model * vec4<f32>(fetch_pos(lp, fetch_index(lp, at + 2u)), 1.0)).xyz;
    let c0 = frame.vp * vec4<f32>(w0, 1.0);
    let c1 = frame.vp * vec4<f32>(w1, 1.0);
    let c2 = frame.vp * vec4<f32>(w2, 1.0);
    let m0 = vec3<f32>(c0.x, c0.y, c0.w);
    let m1 = vec3<f32>(c1.x, c1.y, c1.w);
    let m2 = vec3<f32>(c2.x, c2.y, c2.w);
    let r = vec3<f32>(c.x, c.y, 1.0);
    let det = dot(m0, cross(m1, m2));
    if (abs(det) < 1e-30) {
        return h;                                   // edge-on or degenerate
    }
    let u = vec3<f32>(dot(r, cross(m1, m2)), dot(m0, cross(r, m2)), dot(m0, cross(m1, r))) / det;
    let s = u.x + u.y + u.z;
    let tol = -1e-5 * s;
    if (!(s > 0.0) || u.x < tol || u.y < tol || u.z < tol) {
        return h;
    }
    let z = u.x * c0.z + u.y * c1.z + u.z * c2.z;
    if (z < 0.0 || z > 1.0) {
        return h;                                   // cut by the near or far plane
    }
    let b = u / s;
    h.world = b.x * w0 + b.y * w1 + b.z * w2;
    h.depth = -(frame.view * vec4<f32>(h.world, 1.0)).z;
    h.ok = h.depth == h.depth;                      // never write NaN
    return h;
}

struct ResolveOut {
    @location(0) tri: u32,                          // packed triangle id of the pixel centre, 0 background
    @location(1) info: vec4<u32>,                   // item + 1, flags (1 selected; 2, a cut face, is set by the cap pass)
    @location(2) depth: f32,                        // linear view depth, 0 background
    @builtin(frag_depth) order: f32,                // combines the passes of several page groups (front-most wins)
};

// For the pixel: the front-most triangle among those of its samples that contains the pixel centre (equal depth:
// the smaller packed id, the earlier draw, as GL's "<" keeps the first); when none contains it, the front-most
// sample (equal depth: smaller id) with the depth of that sample. Containing triangles order before samples.
// The single-sample textures (tri, info, depth) keep GL's row order, row 0 = bottom of the picture, like the post-pass
// textures; the visibility buffer (rendered with wgpu's y-down framebuffer) has row 0 = top. flip_row converts.
fn flip_row(p: vec2<i32>) -> vec2<i32> {
    return vec2<i32>(p.x, i32(frame.screen.y) - 1 - p.y);
}

@fragment
fn fs_resolve(@builtin(position) frag: vec4<f32>) -> ResolveOut {
    let px = flip_row(vec2<i32>(frag.xy));
    let c = vec2<f32>((f32(px.x) + 0.5) / frame.screen.x * 2.0 - 1.0, 1.0 - (f32(px.y) + 0.5) / frame.screen.y * 2.0);
    let bits = frame.info.x;
    let mask = (1u << bits) - 1u;
    var best_id = 0u;
    var best_depth = 3.0e38;
    var near_id = 0u;
    var near_z = 2.0;
    for (var s = 0; s < i32(SAMPLES); s++) {
        let id = load_id(px, s);
        if (id == 0u) {
            continue;
        }
        let d = draws[id >> bits];
        if (d.a.w < GROUP_PAGE0 || d.a.w >= GROUP_PAGE0 + GROUP_PAGES) {
            continue;
        }
        let z = load_depth(px, s);
        if (z < near_z || (z == near_z && id < near_id)) {
            near_z = z;
            near_id = id;
        }
        var seen = false;
        for (var t = 0; t < s; t++) {
            if (load_id(px, t) == id) {
                seen = true;
            }
        }
        if (seen) {
            continue;
        }
        let h = triangle_at_centre(d, id & mask, c);
        if (!h.ok || clipped(frame.clip, h.world, (d.b.z & DRAW_NOCLIP) != 0u)) {
            continue;
        }
        if (h.depth < best_depth || (h.depth == best_depth && id < best_id)) {
            best_depth = h.depth;
            best_id = id;
        }
    }
    var o: ResolveOut;
    let zfar = max(frame.halves.w, 1e-6);
    if (best_id != 0u) {
        o.tri = best_id;
        o.depth = best_depth;
        o.order = 0.5 * clamp(best_depth / zfar, 0.0, 1.0);
    } else if (near_id != 0u) {
        o.tri = near_id;
        o.depth = lin_from_z(near_z);
        o.order = 0.5 + 0.5 * clamp(o.depth / zfar, 0.0, 1.0);
    } else {
        discard;
    }
    let d = draws[o.tri >> bits];
    o.info = vec4<u32>(d.b.y + 1u, select(0u, 1u, (d.b.z & DRAW_SELECTED) != 0u), 0u, 0u);
    return o;
}

// ------------------------------------------------------------------------------------------------ debug picture
fn hash_u(x: u32) -> u32 {
    var v = x * 747796405u + 2891336453u;
    let w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

fn item_colour(item: u32) -> vec3<f32> {
    let h = hash_u(item * 2654435761u + 12345u);
    let r = f32(h & 255u) / 255.0;
    let g = f32((h >> 8u) & 255u) / 255.0;
    let b = f32((h >> 16u) & 255u) / 255.0;
    return mix(vec3<f32>(0.25), vec3<f32>(r, g, b), 0.75) + 0.2;
}

fn depth_at(p: vec2<i32>) -> f32 {
    let dim = vec2<i32>(textureDimensions(r_depth));
    return textureLoad(r_depth, flip_row(clamp(p, vec2<i32>(0), dim - 1)), 0).x;
}

// Facing from the depth gradient (a stand-in for the normal, which the debug resolve does not fetch).
@fragment
fn fs_debug(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let px = vec2<i32>(frag.xy);
    let info = textureLoad(r_info, flip_row(px), 0);
    if (info.x == 0u) {
        let t = frag.y / frame.screen.y;
        return vec4<f32>(mix(vec3<f32>(0.125, 0.14, 0.17), vec3<f32>(0.07, 0.08, 0.10), t), 1.0);
    }
    let d = depth_at(px);
    var gx = 0.0;
    var gy = 0.0;
    let dl = depth_at(px + vec2<i32>(-1, 0));
    let dr = depth_at(px + vec2<i32>(1, 0));
    let du = depth_at(px + vec2<i32>(0, -1));
    let dd = depth_at(px + vec2<i32>(0, 1));
    gx = select(dr - d, d - dl, abs(d - dl) < abs(dr - d));
    gy = select(dd - d, d - du, abs(d - du) < abs(dd - d));
    gx = select(gx, 0.0, dl <= 0.0 || dr <= 0.0);
    gy = select(gy, 0.0, du <= 0.0 || dd <= 0.0);
    let pw = select(2.0 * frame.halves.y * d / frame.screen.y, 2.0 * frame.halves.y / frame.screen.y, frame.info.w == 1u);
    let facing = 1.0 / sqrt(1.0 + (gx * gx + gy * gy) / max(pw * pw, 1e-20));
    var col = item_colour(info.x) * (0.3 + 0.7 * facing);
    if (info.y == 1u) {
        col = mix(col, vec3<f32>(1.0, 0.85, 0.45), 0.35);
    }
    return vec4<f32>(col, 1.0);
}

@fragment
fn fs_blit(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    return textureSampleLevel(blit_src, blit_smp, frag.xy / frame.screen.zw, 0.0);
}

// ------------------------------------------------------------------------------------------------ gathers
struct Params {
    full: vec2<u32>,
    grid: vec2<u32>,
    step: u32,
    count: u32,
    pad: vec2<u32>,
};
@group(2) @binding(60) var<uniform> prm: Params;
@group(2) @binding(61) var<storage, read> pts: array<vec2<i32>>;
@group(2) @binding(62) var<storage, read_write> outv: array<vec4<f32>>;

// One cell of the label grid (GL read_label_samples): ids and flags at the cell origin, depth and id at its centre.
// Cells are counted from the top; the origin is the cell's top-left pixel, the centre origin + step / 2 clamped.
@compute @workgroup_size(8, 8, 1)
fn cs_labels(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= prm.grid.x || g.y >= prm.grid.y) {
        return;
    }
    let origin = vec2<i32>(i32(g.x * prm.step), i32(g.y * prm.step));
    let centre = min(origin + vec2<i32>(i32(prm.step / 2u)), vec2<i32>(prm.full) - 1);
    let a = textureLoad(r_info, flip_row(origin), 0);
    let b = textureLoad(r_info, flip_row(centre), 0);
    outv[g.y * prm.grid.x + g.x] = vec4<f32>(f32(a.x), f32(a.y), textureLoad(r_depth, flip_row(centre), 0).x, f32(b.x));
}

// Points (x, y from the top-left): item + 1, flags, depth, triangle id (bits of the u32).
@compute @workgroup_size(64, 1, 1)
fn cs_points(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= prm.count) {
        return;
    }
    let p = flip_row(pts[g.x]);
    let a = textureLoad(r_info, p, 0);
    outv[g.x] = vec4<f32>(f32(a.x), f32(a.y), textureLoad(r_depth, p, 0).x, bitcast<f32>(textureLoad(r_tri, p, 0).x));
}
