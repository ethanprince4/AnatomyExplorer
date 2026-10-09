"""WGSL for the culling spike. Everything is plain WGSL 1.0 storage buffers, no multi-draw, no 64-bit atomics."""

import os

TRI_VERTS = int(os.environ.get("CULL_MAXT", "124")) * 3  # fixed vertex count per cluster draw (unused triangle slots collapse)

HEADER = """
struct Globals {
  view: mat4x4<f32>,
  viewproj: mat4x4<f32>,
  planes: array<vec4<f32>, 5>,
  cam: vec4<f32>,
  screen: vec4<f32>,   // W, H, P00, P11
  misc: vec4<f32>,     // near
  u: vec4<u32>,        // n_ci, hzb_levels, flags (bit0: cone cull), 0
  light: vec4<f32>,
};
@group(0) @binding(0) var<uniform> G: Globals;
"""

# geometry fetch shared by raster and shade passes. bindings 1..10 fixed.
GEOM = """
@group(0) @binding(1) var<storage, read> ci_table: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read> clusters: array<u32>;
@group(0) @binding(3) var<storage, read> instances: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> parts: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> vp0: array<u32>;
@group(0) @binding(6) var<storage, read> vp1: array<u32>;
@group(0) @binding(7) var<storage, read> vp2: array<u32>;
@group(0) @binding(8) var<storage, read> vp3: array<u32>;
@group(0) @binding(9) var<storage, read> ip0: array<u32>;
@group(0) @binding(10) var<storage, read> ip1: array<u32>;

fn vword(page: u32, i: u32) -> u32 {
  switch page {
    case 0u: { return vp0[i]; }
    case 1u: { return vp1[i]; }
    case 2u: { return vp2[i]; }
    default: { return vp3[i]; }
  }
}
fn iword(page: u32, i: u32) -> u32 {
  switch page {
    case 0u: { return ip0[i]; }
    default: { return ip1[i]; }
  }
}
fn v16(page: u32, i: u32) -> u32 {          // i = uint16 index inside the page
  return (vword(page, i >> 1u) >> ((i & 1u) * 16u)) & 0xffffu;
}
fn i8(page: u32, b: u32) -> u32 {
  return (iword(page, b >> 2u) >> ((b & 3u) * 8u)) & 0xffu;
}
fn s16(u: u32) -> f32 { return f32(i32(u << 16u) >> 16u) / 32767.0; }

fn load_pos(part: u32, vpage: u32, vidx: u32) -> vec3<f32> {
  let o = vidx * 5u;
  let q = vec3<f32>(f32(v16(vpage, o)), f32(v16(vpage, o + 1u)), f32(v16(vpage, o + 2u)));
  let lo = parts[part * 2u].xyz;
  let ext = parts[part * 2u + 1u].xyz;
  return lo + q * (ext / 65535.0);
}
fn load_nrm(vpage: u32, vidx: u32) -> vec3<f32> {
  let o = vidx * 5u;
  let ex = s16(v16(vpage, o + 3u));
  let ey = s16(v16(vpage, o + 4u));
  var v = vec3<f32>(ex, ey, 1.0 - abs(ex) - abs(ey));
  let t = max(-v.z, 0.0);
  v.x = v.x + select(t, -t, v.x >= 0.0);
  v.y = v.y + select(t, -t, v.y >= 0.0);
  return normalize(v);
}
fn to_world(inst: u32, p: vec3<f32>) -> vec3<f32> {
  let r0 = instances[inst * 4u];
  let r1 = instances[inst * 4u + 1u];
  let r2 = instances[inst * 4u + 2u];
  return vec3<f32>(dot(r0.xyz, p) + r0.w, dot(r1.xyz, p) + r1.w, dot(r2.xyz, p) + r2.w);
}
fn dir_to_world(inst: u32, n: vec3<f32>) -> vec3<f32> {
  let r0 = instances[inst * 4u];
  let r1 = instances[inst * 4u + 1u];
  let r2 = instances[inst * 4u + 2u];
  return normalize(vec3<f32>(dot(r0.xyz, n), dot(r1.xyz, n), dot(r2.xyz, n)));
}
"""

RASTER = HEADER + GEOM + """
@group(0) @binding(11) var<storage, read> list: array<u32>;

struct VOut {
  @builtin(position) pos: vec4<f32>,
  @location(0) @interpolate(flat) id: u32,
};

@vertex
fn vs(@builtin(vertex_index) vi: u32, @builtin(instance_index) ii: u32) -> VOut {
  var out: VOut;
  out.id = 0u;
  out.pos = vec4<f32>(2.0, 2.0, 2.0, 1.0);
  let ci = list[ii];
  let e = ci_table[ci];
  let cmeta = clusters[e.y * 12u + 5u];
  let tcount = (cmeta >> 7u) & 127u;
  let t = vi / 3u;
  let k = vi - t * 3u;
  if (t >= tcount) { return out; }
  let vpage = (cmeta >> 14u) & 15u;
  let ipage = (cmeta >> 18u) & 15u;
  let vfirst = clusters[e.y * 12u + 6u];
  let ioff = clusters[e.y * 12u + 7u];
  let part = bitcast<u32>(instances[e.x * 4u + 3u].z);
  let local = i8(ipage, ioff + t * 3u + k);
  let wp = to_world(e.x, load_pos(part, vpage, vfirst + local));
  out.pos = G.viewproj * vec4<f32>(wp, 1.0);
  out.id = ((ci << 7u) | t) + 1u;
  return out;
}

@fragment
fn fs(@location(0) @interpolate(flat) id: u32) -> @location(0) vec4<u32> {
  return vec4<u32>(id, 0u, 0u, 0u);
}
"""

SHADE = HEADER + GEOM + """
@group(0) @binding(11) var vis: texture_2d<u32>;

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
  let x = f32((vi << 1u) & 2u) * 2.0 - 1.0;
  let y = f32(vi & 2u) * 2.0 - 1.0;
  return vec4<f32>(x, y, 0.0, 1.0);
}

fn hash_color(h: u32) -> vec3<f32> {
  var x = h * 747796405u + 2891336453u;
  x = ((x >> ((x >> 28u) + 4u)) ^ x) * 277803737u;
  x = (x >> 22u) ^ x;
  return vec3<f32>(f32(x & 255u), f32((x >> 8u) & 255u), f32((x >> 16u) & 255u)) / 255.0 * 0.6 + 0.35;
}

@fragment
fn fs(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
  let id = textureLoad(vis, vec2<i32>(frag.xy), 0).r;
  if (id == 0u) { return vec4<f32>(0.02, 0.02, 0.03, 1.0); }
  let idm = id - 1u;
  let ci = idm >> 7u;
  let t = idm & 127u;
  let e = ci_table[ci];
  let cmeta = clusters[e.y * 12u + 5u];
  let vpage = (cmeta >> 14u) & 15u;
  let ipage = (cmeta >> 18u) & 15u;
  let vfirst = clusters[e.y * 12u + 6u];
  let ioff = clusters[e.y * 12u + 7u];
  let inst4 = instances[e.x * 4u + 3u];
  let part = bitcast<u32>(inst4.z);
  let item = bitcast<u32>(inst4.y);
  let b = ioff + t * 3u;
  let l0 = vfirst + i8(ipage, b);
  let l1 = vfirst + i8(ipage, b + 1u);
  let l2 = vfirst + i8(ipage, b + 2u);
  let c0 = G.viewproj * vec4<f32>(to_world(e.x, load_pos(part, vpage, l0)), 1.0);
  let c1 = G.viewproj * vec4<f32>(to_world(e.x, load_pos(part, vpage, l1)), 1.0);
  let c2 = G.viewproj * vec4<f32>(to_world(e.x, load_pos(part, vpage, l2)), 1.0);
  let nx = frag.x / G.screen.x * 2.0 - 1.0;
  let ny = 1.0 - frag.y / G.screen.y * 2.0;
  let a = vec3<f32>(c0.x - nx * c0.w, c1.x - nx * c1.w, c2.x - nx * c2.w);
  let bb = vec3<f32>(c0.y - ny * c0.w, c1.y - ny * c1.w, c2.y - ny * c2.w);
  var lam = cross(a, bb);
  lam = lam / (lam.x + lam.y + lam.z);
  let n = dir_to_world(e.x, normalize(lam.x * load_nrm(vpage, l0) + lam.y * load_nrm(vpage, l1) + lam.z * load_nrm(vpage, l2)));
  let lit = 0.2 + 0.8 * max(dot(n, normalize(G.light.xyz)), 0.0);
  return vec4<f32>(hash_color(item) * lit, 1.0);
}
"""

# ---------------- culling ----------------
CULL_COMMON = HEADER + """
struct Args { vertex_count: u32, instance_count: atomic<u32>, first_vertex: u32, first_instance: u32, };
@group(0) @binding(1) var<storage, read> ci_table: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read> clusters: array<u32>;
@group(0) @binding(3) var<storage, read> instances: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read_write> args: array<Args, 2>;
@group(0) @binding(9) var<storage, read_write> counters: array<atomic<u32>, 16>;

fn cluster_ws(inst: u32, cl: u32) -> vec4<f32> {
  let r0 = instances[inst * 4u];
  let r1 = instances[inst * 4u + 1u];
  let r2 = instances[inst * 4u + 2u];
  let s = instances[inst * 4u + 3u].x;
  let c = vec3<f32>(bitcast<f32>(clusters[cl * 12u]), bitcast<f32>(clusters[cl * 12u + 1u]), bitcast<f32>(clusters[cl * 12u + 2u]));
  let r = bitcast<f32>(clusters[cl * 12u + 3u]);
  return vec4<f32>(dot(r0.xyz, c) + r0.w, dot(r1.xyz, c) + r1.w, dot(r2.xyz, c) + r2.w, r * s);
}
fn in_frustum(c: vec3<f32>, r: f32) -> bool {
  for (var i = 0u; i < 5u; i = i + 1u) {
    if (dot(G.planes[i].xyz, c) + G.planes[i].w < -r) { return false; }
  }
  return true;
}
fn back_facing(inst: u32, cl: u32, c: vec3<f32>, r: f32) -> bool {
  let cone = unpack4x8snorm(clusters[cl * 12u + 4u]);
  let cutoff = cone.w;
  if (cutoff >= 0.9999) { return false; }
  let ax = normalize(cone.xyz);
  let r0 = instances[inst * 4u];
  let r1 = instances[inst * 4u + 1u];
  let r2 = instances[inst * 4u + 2u];
  let aw = normalize(vec3<f32>(dot(r0.xyz, ax), dot(r1.xyz, ax), dot(r2.xyz, ax)));
  let v = c - G.cam.xyz;
  return dot(v, aw) >= cutoff * length(v) + r;
}
var<workgroup> wg_n1: atomic<u32>;
var<workgroup> wg_n2: atomic<u32>;
var<workgroup> wg_base1: u32;
var<workgroup> wg_base2: u32;
var<workgroup> wg_s: array<atomic<u32>, 8>;
"""

CULL1 = CULL_COMMON + """
@group(0) @binding(4) var<storage, read> inst_flags: array<u32>;
@group(0) @binding(5) var<storage, read> vis_prev: array<u32>;
@group(0) @binding(6) var<storage, read_write> list1: array<u32>;
@group(0) @binding(8) var<storage, read_write> cand: array<u32>;

@compute @workgroup_size(64)
fn main(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
  if (li == 0u) {
    atomicStore(&wg_n1, 0u); atomicStore(&wg_n2, 0u);
    for (var k = 0u; k < 8u; k = k + 1u) { atomicStore(&wg_s[k], 0u); }
  }
  workgroupBarrier();
  let i = (wid.y * 32768u + wid.x) * 64u + li;
  var kind = 0u;
  var rank = 0u;
  if (i < G.u.x) {
    let e = ci_table[i];
    if ((inst_flags[e.x] & 1u) == 0u) {
      atomicAdd(&wg_s[0], 1u);
      let ws = cluster_ws(e.x, e.y);
      if (in_frustum(ws.xyz, ws.w)) {
        atomicAdd(&wg_s[1], 1u);
        var culled = false;
        if ((G.u.z & 1u) != 0u) { culled = back_facing(e.x, e.y, ws.xyz, ws.w); }
        if (!culled) {
          atomicAdd(&wg_s[2], 1u);
          if (vis_prev[i] != 0u) {
            kind = 1u;
            atomicAdd(&wg_s[3], (clusters[e.y * 12u + 5u] >> 7u) & 127u);
          } else {
            kind = 2u;
          }
        }
      }
    }
  }
  if (kind == 1u) { rank = atomicAdd(&wg_n1, 1u); }
  if (kind == 2u) { rank = atomicAdd(&wg_n2, 1u); }
  workgroupBarrier();
  if (li == 0u) {
    let n1 = atomicLoad(&wg_n1);
    let n2 = atomicLoad(&wg_n2);
    if (n1 > 0u) { wg_base1 = atomicAdd(&args[0].instance_count, n1); }
    if (n2 > 0u) { wg_base2 = atomicAdd(&counters[4], n2); }
    atomicAdd(&counters[0], atomicLoad(&wg_s[0]));
    atomicAdd(&counters[1], atomicLoad(&wg_s[1]));
    atomicAdd(&counters[2], atomicLoad(&wg_s[2]));
    atomicAdd(&counters[6], atomicLoad(&wg_s[3]));
  }
  workgroupBarrier();
  if (kind == 1u) { list1[wg_base1 + rank] = i; }
  if (kind == 2u) { cand[wg_base2 + rank] = i; }
}
"""

PREP = CULL_COMMON + """
@group(0) @binding(4) var<storage, read_write> dispatch: array<u32, 4>;
@compute @workgroup_size(1)
fn main() {
  let n = atomicLoad(&counters[4]);
  let wgs = (n + 63u) / 64u;
  dispatch[0] = min(wgs, 32768u);
  dispatch[1] = (wgs + 32767u) / 32768u;
  dispatch[2] = 1u;
  atomicStore(&counters[3], atomicLoad(&args[0].instance_count));
}
"""

CULL2 = CULL_COMMON + """
const FINE: bool = true;

@group(0) @binding(5) var<storage, read> cand: array<u32>;
@group(0) @binding(6) var<storage, read_write> list2: array<u32>;
@group(0) @binding(10) var hzb: texture_2d<f32>;

fn occluded(inst: u32, cl: u32) -> bool {
  let r0 = instances[inst * 4u];
  let r1 = instances[inst * 4u + 1u];
  let r2 = instances[inst * 4u + 2u];
  let c = vec3<f32>(bitcast<f32>(clusters[cl * 12u]), bitcast<f32>(clusters[cl * 12u + 1u]), bitcast<f32>(clusters[cl * 12u + 2u]));
  let h = vec3<f32>(bitcast<f32>(clusters[cl * 12u + 8u]), bitcast<f32>(clusters[cl * 12u + 9u]), bitcast<f32>(clusters[cl * 12u + 10u]));
  let wc = vec3<f32>(dot(r0.xyz, c) + r0.w, dot(r1.xyz, c) + r1.w, dot(r2.xyz, c) + r2.w);
  let vc = (G.view * vec4<f32>(wc, 1.0)).xyz;
  let a0 = (G.view * vec4<f32>(vec3<f32>(r0.x, r1.x, r2.x) * h.x, 0.0)).xyz;
  let a1 = (G.view * vec4<f32>(vec3<f32>(r0.y, r1.y, r2.y) * h.y, 0.0)).xyz;
  let a2 = (G.view * vec4<f32>(vec3<f32>(r0.z, r1.z, r2.z) * h.z, 0.0)).xyz;
  let near = G.misc.x;
  var zmin = 1e30;
  var lo = vec2<f32>(1e30, 1e30);
  var hi = vec2<f32>(-1e30, -1e30);
  for (var k = 0u; k < 8u; k = k + 1u) {
    let sx = select(-1.0, 1.0, (k & 1u) != 0u);
    let sy = select(-1.0, 1.0, (k & 2u) != 0u);
    let sz = select(-1.0, 1.0, (k & 4u) != 0u);
    let p = vc + a0 * sx + a1 * sy + a2 * sz;
    let zf = -p.z;
    if (zf <= near) { return false; }
    zmin = min(zmin, zf);
    let q = vec2<f32>(p.x / zf * G.screen.z, p.y / zf * G.screen.w);
    lo = min(lo, q);
    hi = max(hi, q);
  }
  let W = G.screen.x;
  let H = G.screen.y;
  let x0 = clamp((lo.x * 0.5 + 0.5) * W, 0.0, W - 0.01);
  let x1 = clamp((hi.x * 0.5 + 0.5) * W, 0.0, W - 0.01);
  let y0 = clamp((0.5 - hi.y * 0.5) * H, 0.0, H - 0.01);
  let y1 = clamp((0.5 - lo.y * 0.5) * H, 0.0, H - 0.01);
  var lvl = 0u;
  var size = 2.0;
  var ix0 = u32(x0 / size); var ix1 = u32(x1 / size);
  var iy0 = u32(y0 / size); var iy1 = u32(y1 / size);
  loop {
    if ((ix1 - ix0 <= 1u && iy1 - iy0 <= 1u) || lvl + 1u >= G.u.y) { break; }
    lvl = lvl + 1u;
    size = size * 2.0;
    ix0 = u32(x0 / size); ix1 = u32(x1 / size);
    iy0 = u32(y0 / size); iy1 = u32(y1 / size);
  }
  // one level finer: at most 4x4 texels, tighter footprint
  if (lvl > 0u && FINE) {
    lvl = lvl - 1u;
    size = size * 0.5;
    ix0 = u32(x0 / size); ix1 = u32(x1 / size);
    iy0 = u32(y0 / size); iy1 = u32(y1 / size);
  }
  let dnear = near / zmin;
  let l = i32(lvl);
  for (var yy = iy0; yy <= iy1; yy = yy + 1u) {
    for (var xx = ix0; xx <= ix1; xx = xx + 1u) {
      if (textureLoad(hzb, vec2<u32>(xx, yy), l).r <= dnear) { return false; }
    }
  }
  return true;
}

@compute @workgroup_size(64)
fn main(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
  if (li == 0u) {
    atomicStore(&wg_n2, 0u);
    atomicStore(&wg_s[0], 0u);
  }
  workgroupBarrier();
  let i = (wid.y * 32768u + wid.x) * 64u + li;
  var keep = false;
  var rank = 0u;
  if (i < atomicLoad(&counters[4])) {
    let ci = cand[i];
    let e = ci_table[ci];
    let ws = cluster_ws(e.x, e.y);
    if (!occluded(e.x, e.y)) {
      keep = true;
      atomicAdd(&wg_s[0], (clusters[e.y * 12u + 5u] >> 7u) & 127u);
    }
  }
  if (keep) { rank = atomicAdd(&wg_n2, 1u); }
  workgroupBarrier();
  if (li == 0u) {
    let n2 = atomicLoad(&wg_n2);
    if (n2 > 0u) { wg_base2 = atomicAdd(&args[1].instance_count, n2); }
    atomicAdd(&counters[7], atomicLoad(&wg_s[0]));
  }
  workgroupBarrier();
  if (keep) { list2[wg_base2 + rank] = cand[i]; }
}
"""

HZB0 = """
@group(0) @binding(0) var src: texture_depth_2d;
@group(0) @binding(1) var dst: texture_storage_2d<r32float, write>;
@group(0) @binding(2) var<uniform> dims: vec4<u32>;   // logical src w,h, dst w,h
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let d = dims.zw;
  if (gid.x >= d.x || gid.y >= d.y) { return; }
  let sd = dims.xy;
  let p = gid.xy * 2u;
  let p1 = min(p + vec2<u32>(1u, 1u), sd - vec2<u32>(1u, 1u));
  let m = min(min(textureLoad(src, p, 0), textureLoad(src, vec2<u32>(p1.x, p.y), 0)),
              min(textureLoad(src, vec2<u32>(p.x, p1.y), 0), textureLoad(src, p1, 0)));
  textureStore(dst, gid.xy, vec4<f32>(m, 0.0, 0.0, 0.0));
}
"""

HZBN = """
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var dst: texture_storage_2d<r32float, write>;
@group(0) @binding(2) var<uniform> dims: vec4<u32>;   // logical src w,h, dst w,h
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let d = dims.zw;
  if (gid.x >= d.x || gid.y >= d.y) { return; }
  let sd = dims.xy;
  let p = gid.xy * 2u;
  let p1 = min(p + vec2<u32>(1u, 1u), sd - vec2<u32>(1u, 1u));
  let m = min(min(textureLoad(src, p, 0).r, textureLoad(src, vec2<u32>(p1.x, p.y), 0).r),
              min(textureLoad(src, vec2<u32>(p.x, p1.y), 0).r, textureLoad(src, p1, 0).r));
  textureStore(dst, gid.xy, vec4<f32>(m, 0.0, 0.0, 0.0));
}
"""

MARK = """
@group(0) @binding(0) var vis: texture_2d<u32>;
@group(0) @binding(1) var<storage, read_write> vis_next: array<atomic<u32>>;
@group(0) @binding(2) var<storage, read_write> counters: array<atomic<u32>, 16>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let d = textureDimensions(vis);
  if (gid.x >= d.x || gid.y >= d.y) { return; }
  let id = textureLoad(vis, gid.xy, 0).r;
  if (id != 0u) {
    let ci = (id - 1u) >> 7u;
    if (atomicLoad(&vis_next[ci]) == 0u) {
      if (atomicExchange(&vis_next[ci], 1u) == 0u) { atomicAdd(&counters[8], 1u); }
    }
  }
}
"""

DUMP = """
@group(0) @binding(0) var vis: texture_2d<u32>;
@group(0) @binding(1) var dep: texture_depth_2d;
@group(0) @binding(2) var<storage, read_write> outb: array<u32>;
@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let d = textureDimensions(vis);
  if (gid.x >= d.x || gid.y >= d.y) { return; }
  let o = (gid.y * d.x + gid.x) * 2u;
  outb[o] = textureLoad(vis, gid.xy, 0).r;
  outb[o + 1u] = bitcast<u32>(textureLoad(dep, gid.xy, 0));
}
"""
