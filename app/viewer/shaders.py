"""GLSL sources for the model viewer's renderer (OpenGL 4.1 core).

Passes: shadow depth (x3 lights) -> pre-pass (view normal + linear depth, item id + flags, single sample) -> cut
faces (per cut item: parity, cap; then laid into the pre-pass) -> SSAO + bilateral blur -> MSAA forward pass
(backdrop, opaque PBR, cut faces shaded on their plane) -> MSAA weighted-blended OIT pass (translucent parts and
x-rayed parts) -> resolve -> composite (OIT blend, selection and hover outlines, Khronos PBR Neutral, sRGB, dither).

Cut faces follow the atlas renderer's method (app/shaders.py): for each item the plane passes through, the depth
of its nearest kept front face is gathered first ("parity"); a back face with no kept front face of the same item
in front of it means the view ray entered the item through the cut, so a cap is drawn where the ray leaves the
cut-away, keyed on how far that item's far wall lies behind the plane so the innermost item wins where several
meet. The winners are laid into the pre-pass (for picking, outlines, labels and ambient occlusion) and shaded in
the forward pass like any other surface.
"""

VERSION = "#version 410 core\n"

# ------------------------------------------------------------------------------------------------
# Geometry: one vertex format for every part; the single glTF morph target is blended on the GPU, and a procedural
# model's animation (app/micro/anim.py: four morph targets, a phase and a per-item mode) rides on a second buffer.

GEOM_VS = VERSION + """
in vec3 in_pos;
in vec3 in_nrm;
in vec3 in_dpos;
in vec3 in_dnrm;
in float in_fib;
in vec4 in_col;
in vec2 in_uv;
in vec4 in_m0;
in vec4 in_m1;
in vec4 in_m2;
in vec4 in_m3;
in float in_phase;
in float in_item;            // the item this vertex belongs to (batched draws read its state from u_items)

uniform mat4 u_model;
uniform mat3 u_nmat;
uniform mat4 u_viewproj;
uniform float u_weight;
uniform int u_anim;          // 1: the procedural animation buffer is bound
uniform float u_anim_t;      // cycle phase 0..1
uniform vec4 u_aw;           // this item's four morph weights
uniform vec4 u_ag;           // (mode, glow, decay, rate)

centroid out vec3 v_wpos;
out vec3 v_wnrm;
out vec3 v_opos;
out float v_fib;
out vec4 v_col;
out vec2 v_uv;
out float v_glow;
flat out float v_item;

void main() {
    v_item = in_item;
    vec3 p = in_pos + u_weight * in_dpos;
    vec3 n = in_nrm + u_weight * in_dnrm;
    v_glow = 0.0;
    if (u_anim == 1) {
        vec4 w = u_aw;
        int mode = int(u_ag.x + 0.5);
        if (mode == 1) {                // particles on their own clocks along a curved path
            float tau = fract(u_anim_t * u_ag.w + in_phase);
            w = vec4(tau, tau * tau, 1.0 - smoothstep(0.0, 0.06, tau) * (1.0 - smoothstep(0.90, 1.0, tau)), w.w);
        }
        p += w.x * in_m0.xyz + w.y * in_m1.xyz + w.z * in_m2.xyz + w.w * in_m3.xyz;
        if (mode == 2) {                // a wave of activation: lights up at its phase, then fades
            float dt = fract(u_anim_t - in_phase);
            v_glow = u_ag.y * smoothstep(0.0, 0.006, dt) * exp(-dt / max(u_ag.z, 1e-3));
        } else {
            v_glow = u_ag.y;
        }
    }
    vec4 w = u_model * vec4(p, 1.0);
    v_wpos = w.xyz;
    v_wnrm = u_nmat * n;
    v_opos = in_pos;
    v_fib = in_fib;
    v_col = in_col;
    v_uv = in_uv;
    gl_Position = u_viewproj * w;
}
"""

# ---- per-item state of a batched draw: one draw call spans the parts of several items that shade alike, so what
# differs between items (id, selection, highlight, x-ray, opacity, a flat colour) comes from a texture by item index
ITEM_COMMON = """
uniform int u_batched;       // 1: this draw takes its per-item state from u_items
uniform sampler2D u_items;   // column = item: row 0 (id + 1, selected, highlight, x-ray), row 1 (flat colour, on),
                             // row 2 (highlight colour, opacity)
vec4 item_row(int row) { return texelFetch(u_items, ivec2(int(v_item + 0.5), row), 0); }
"""

# ---- cutting planes: the cut-away of a micro model and the cross-sections, shared by every pass
CLIP_COMMON = """
uniform vec4 u_clip0;
uniform vec4 u_clip1;
uniform vec4 u_clip2;
uniform ivec3 u_clip_on;
uniform int u_clip_mode;     // 0: any plane removes its negative side; 1: a corner (all active planes negative)
uniform int u_noclip;        // this item is never cut

bool clipped(vec3 p) {
    if (u_noclip == 1) return false;
    bool a = u_clip_on.x == 1 && dot(vec4(p, 1.0), u_clip0) < 0.0;
    bool b = u_clip_on.y == 1 && dot(vec4(p, 1.0), u_clip1) < 0.0;
    bool c = u_clip_on.z == 1 && dot(vec4(p, 1.0), u_clip2) < 0.0;
    if (u_clip_mode == 1) {
        int n = u_clip_on.x + u_clip_on.y + u_clip_on.z;
        if (n == 0) return false;
        return (u_clip_on.x == 0 || a) && (u_clip_on.y == 0 || b) && (u_clip_on.z == 0 || c);
    }
    return a || b || c;
}
"""

SHADOW_FS = VERSION + CLIP_COMMON + """
centroid in vec3 v_wpos;
void main() {
    if (clipped(v_wpos)) discard;
}
"""

PREPASS_FS = VERSION + CLIP_COMMON + """
centroid in vec3 v_wpos;
in vec3 v_wnrm;
in vec2 v_uv;
flat in float v_item;
""" + ITEM_COMMON + """
uniform mat4 u_view;
uniform float u_id;
uniform float u_flags;       // 1: selected
uniform int u_flip;          // the model matrix mirrors: front faces are the clockwise ones
uniform sampler2D u_tex;
uniform int u_has_tex;
uniform float u_alpha_cut;
layout(location = 0) out vec4 o_nd;
layout(location = 1) out vec2 o_id;
void main() {
    if (clipped(v_wpos)) discard;
    if (u_has_tex == 1 && u_alpha_cut > 0.0 && texture(u_tex, v_uv).a < u_alpha_cut) discard;
    bool front = gl_FrontFacing != (u_flip == 1);
    vec3 n = normalize(mat3(u_view) * v_wnrm);
    if (!front) n = -n;
    float d = -(u_view * vec4(v_wpos, 1.0)).z;
    o_nd = vec4(n, d);
    o_id = u_batched == 1 ? item_row(0).xy : vec2(u_id, u_flags);
}
"""

# ------------------------------------------------------------------------------------------------
# Full-screen helpers

FSQ_VS = VERSION + """
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

BACKDROP_FS = VERSION + """
in vec2 v_uv;
uniform vec3 u_bottom;
uniform vec3 u_top;
out vec4 o_col;
void main() {
    o_col = vec4(mix(u_bottom, u_top, clamp(v_uv.y, 0.0, 1.0)), 1.0);
}
"""

BLIT_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_src;
out vec4 o_col;
void main() {
    o_col = texture(u_src, v_uv);
}
"""

SSAO_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_nd;
uniform vec2 u_tan;          // tan half-fov x, y (perspective) or half extents (ortho)
uniform int u_ortho;
uniform float u_radius;      // world units
uniform float u_bias;
uniform float u_power;
uniform int u_samples;
uniform float u_large;       // cavity radius / contact radius
uniform float u_large_mix;
uniform sampler2D u_prev;    // last frame's resolved HDR colour (one-bounce screen-space GI)
uniform float u_gi_on;
out vec4 o_ao;

vec3 view_pos(vec2 uv, float d) {
    vec2 ndc = uv * 2.0 - 1.0;
    if (u_ortho == 1) return vec3(ndc * u_tan, -d);
    return vec3(ndc * u_tan * d, -d);
}
vec2 project(vec3 p) {
    vec2 ndc = (u_ortho == 1) ? p.xy / u_tan : p.xy / (-p.z * u_tan);
    return ndc * 0.5 + 0.5;
}
float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }

void main() {
    vec4 nd = texture(u_nd, v_uv);
    if (nd.w <= 0.0) { o_ao = vec4(0.0, 0.0, 0.0, 1.0); return; }
    vec3 P = view_pos(v_uv, nd.w);
    vec3 N = normalize(nd.xyz);
    float a0 = ign(gl_FragCoord.xy) * 6.2831853;
    float r0 = ign(gl_FragCoord.yx + 17.0);
    vec3 T = normalize(abs(N.z) < 0.9 ? cross(N, vec3(0, 0, 1)) : cross(N, vec3(1, 0, 0)));
    vec3 B = cross(N, T);
    float ao = 1.0;
    vec3 gi = vec3(0.0);
    for (int scale = 0; scale < 2; ++scale) {
        float rad = (scale == 0) ? u_radius : u_radius * u_large;
        float occ = 0.0;
        float wsum = 0.0;
        for (int i = 0; i < u_samples; ++i) {
            float fi = (float(i) + r0) / float(u_samples);
            float phi = a0 + float(i) * 2.39996323 + float(scale) * 1.3;
            float ct = sqrt(1.0 - fi);                  // cosine-weighted hemisphere
            float st = sqrt(fi);
            vec3 h = vec3(cos(phi) * st, sin(phi) * st, ct);
            float sc = mix(0.15, 1.0, fract(float(i) * 0.618034 + r0));
            vec3 S = P + (T * h.x + B * h.y + N * h.z) * rad * sc * sc;
            vec2 uv = project(S);
            wsum += 1.0;
            if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) continue;
            float sd = texture(u_nd, uv).w;
            if (sd <= 0.0) continue;
            float sceneZ = -sd;
            float range = smoothstep(0.0, 1.0, rad / max(abs(P.z - sceneZ), 1e-4));
            float hit = (sceneZ >= S.z + u_bias * (1.0 + 3.0 * float(scale)) ? 1.0 : 0.0) * range;
            occ += hit;
        }
        float a = 1.0 - occ / max(wsum, 1.0);
        ao *= (scale == 0) ? a : mix(1.0, a, u_large_mix);
    }
    // one bounce: march 12 cosine-weighted rays in screen space; where a ray passes behind a visible surface,
    // that surface's shaded colour (last frame) lights this point. Escaping rays see the sky (ambient term).
    if (u_gi_on > 0.5) {
        float grad = u_radius * u_large;
        const int DIRS = 12;
        const int STEPS = 8;
        for (int i = 0; i < DIRS; ++i) {
            float fi = (float(i) + r0) / float(DIRS);
            float phi = a0 * 1.7 + float(i) * 2.39996323;
            float ct = sqrt(1.0 - fi);
            float st = sqrt(fi);
            vec3 dir = T * (cos(phi) * st) + B * (sin(phi) * st) + N * ct;
            for (int k = 1; k <= STEPS; ++k) {
                float f = (float(k) - 0.5 + 0.5 * r0) / float(STEPS);
                vec3 S = P + dir * grad * f * f + N * u_bias;
                vec2 uv = project(S);
                if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) break;
                float sd = texture(u_nd, uv).w;
                if (sd <= 0.0) continue;
                float dz = -sd - S.z;                 // > 0: the visible surface is in front of the ray point
                if (dz > u_bias && dz < grad * 0.6) {
                    vec3 Ns = texture(u_nd, uv).xyz;
                    float facing = clamp(dot(Ns, -dir) * 1.5 + 0.25, 0.0, 1.0);
                    gi += min(texture(u_prev, uv).rgb, vec3(4.0)) * facing;
                    break;
                }
            }
        }
        gi /= float(DIRS);
    }
    o_ao = vec4(gi, pow(clamp(ao, 0.0, 1.0), u_power));
}
"""

BLUR_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_src;
uniform sampler2D u_nd;
uniform vec2 u_dir;          // texel step
out vec4 o_val;
void main() {
    vec4 c = texture(u_nd, v_uv);
    if (c.w <= 0.0) { o_val = vec4(0.0, 0.0, 0.0, 1.0); return; }
    vec4 sum = vec4(0.0);
    float wsum = 0.0;
    for (int i = -6; i <= 6; ++i) {
        vec2 uv = v_uv + u_dir * float(i);
        vec4 s = texture(u_nd, uv);
        float w = exp(-float(i * i) / 18.0);
        w *= exp(-abs(s.w - c.w) / (0.02 * c.w + 1e-4) );
        w *= pow(max(dot(s.xyz, c.xyz), 0.0), 8.0);
        sum += texture(u_src, uv) * w;
        wsum += w;
    }
    o_val = sum / max(wsum, 1e-5);
}
"""

PREFILTER_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_src;
uniform float u_rough;
uniform float u_src_w;
out vec4 o_col;
const float PI = 3.14159265;
vec3 uv_dir(vec2 uv) {
    float phi = (uv.x - 0.5) * 2.0 * PI;
    float th = uv.y * PI;
    return vec3(sin(th) * sin(phi), cos(th), -sin(th) * cos(phi));
}
vec2 dir_uv(vec3 d) {
    return vec2(0.5 + atan(d.x, -d.z) / (2.0 * PI), acos(clamp(d.y, -1.0, 1.0)) / PI);
}
vec2 hammersley(uint i, uint n) {
    uint b = i;
    b = (b << 16u) | (b >> 16u);
    b = ((b & 0x55555555u) << 1u) | ((b & 0xAAAAAAAAu) >> 1u);
    b = ((b & 0x33333333u) << 2u) | ((b & 0xCCCCCCCCu) >> 2u);
    b = ((b & 0x0F0F0F0Fu) << 4u) | ((b & 0xF0F0F0F0u) >> 4u);
    b = ((b & 0x00FF00FFu) << 8u) | ((b & 0xFF00FF00u) >> 8u);
    return vec2(float(i) / float(n), float(b) * 2.3283064365386963e-10);
}
void main() {
    vec3 N = uv_dir(v_uv);
    if (u_rough < 0.02) { o_col = vec4(textureLod(u_src, v_uv, 0.0).rgb, 1.0); return; }
    float a = u_rough * u_rough;
    vec3 up = abs(N.y) < 0.999 ? vec3(0, 1, 0) : vec3(1, 0, 0);
    vec3 T = normalize(cross(up, N));
    vec3 B = cross(N, T);
    vec3 sum = vec3(0.0);
    float wsum = 0.0;
    const uint COUNT = 1024u;
    float texel_sa = 4.0 * PI / (u_src_w * u_src_w * 0.5);
    for (uint i = 0u; i < COUNT; ++i) {
        vec2 xi = hammersley(i, COUNT);
        float ph = 2.0 * PI * xi.x;
        float ct = sqrt((1.0 - xi.y) / (1.0 + (a * a - 1.0) * xi.y));
        float st = sqrt(1.0 - ct * ct);
        vec3 H = T * (st * cos(ph)) + B * (st * sin(ph)) + N * ct;
        vec3 L = normalize(2.0 * dot(N, H) * H - N);
        float NoL = dot(N, L);
        if (NoL > 0.0) {
            float d = (ct * ct * (a * a - 1.0) + 1.0);
            float D = a * a / (PI * d * d);
            float pdf = D / 4.0 + 1e-4;
            float sa = 1.0 / (float(COUNT) * pdf);
            float lod = max(0.5 * log2(sa / texel_sa) + 1.0, 0.0);
            sum += textureLod(u_src, dir_uv(L), lod).rgb * NoL;
            wsum += NoL;
        }
    }
    o_col = vec4(sum / max(wsum, 1e-5), 1.0);
}
"""

# ------------------------------------------------------------------------------------------------
# Shading (shared by the opaque, translucent and cut-face passes). The surface inputs are declared by each shader:
# as varyings in the geometry passes, as plain globals the cut-face pass fills in from its buffers.

GEOM_INPUTS = """
centroid in vec3 v_wpos;
in vec3 v_wnrm;
in vec3 v_opos;
in float v_fib;
in vec4 v_col;
in vec2 v_uv;
in float v_glow;
flat in float v_item;
"""

SHADING_COMMON = ITEM_COMMON + """
const float PI = 3.14159265;

uniform vec3 u_campos;
uniform int u_ortho;
uniform vec3 u_viewdir;      // toward the camera (orthographic views)
uniform mat4 u_view;
uniform vec2 u_screen;

uniform sampler2D u_ao;
uniform float u_ao_on;
uniform float u_ao_direct;

uniform vec3 u_ldir0; uniform vec3 u_ldir1; uniform vec3 u_ldir2;
uniform vec3 u_lrad0; uniform vec3 u_lrad1; uniform vec3 u_lrad2;
uniform float u_lsize0; uniform float u_lsize1; uniform float u_lsize2;
uniform mat4 u_lmat0; uniform mat4 u_lmat1; uniform mat4 u_lmat2;
uniform sampler2DShadow u_shadow0; uniform sampler2DShadow u_shadow1; uniform sampler2DShadow u_shadow2;
uniform float u_ltexel0; uniform float u_ltexel1; uniform float u_ltexel2;
uniform float u_lsoft0; uniform float u_lsoft1; uniform float u_lsoft2;
uniform float u_shadow_on;

uniform vec3 u_sh[9];
uniform sampler2DArray u_spec;
uniform float u_spec_layers;
uniform float u_env_diffuse;
uniform float u_env_spec;
uniform float u_bounce;

uniform vec3 u_base;
uniform float u_alpha;
uniform float u_rough;
uniform float u_metal;
uniform float u_f0;
uniform float u_wrap;
uniform vec3 u_emis;
uniform int u_use_vcol;
uniform int u_has_tex;
uniform sampler2D u_tex;

uniform int u_stripe;
uniform vec4 u_stripe_p;     // period, rest threshold, edge, i_mix
uniform float u_shorten;
uniform float u_weight;
uniform vec3 u_stripe_a;
uniform vec3 u_stripe_b;

uniform int u_mottle;
uniform vec4 u_mottle_p;     // scale, from_min, from_max, octaves
uniform vec3 u_mottle_a;
uniform vec3 u_mottle_b;

uniform int u_detail_on;
uniform vec4 u_detail;       // tissue texturing: mottle, cells per unit, nucleus fraction, fibre axis

uniform float u_highlight;
uniform vec3 u_highlight_col;

float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }

vec3 hash3(vec3 p) {
    p = vec3(dot(p, vec3(127.1, 311.7, 74.7)), dot(p, vec3(269.5, 183.3, 246.1)), dot(p, vec3(113.5, 271.9, 124.6)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float gnoise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    vec3 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    float n000 = dot(hash3(i + vec3(0, 0, 0)), f - vec3(0, 0, 0));
    float n100 = dot(hash3(i + vec3(1, 0, 0)), f - vec3(1, 0, 0));
    float n010 = dot(hash3(i + vec3(0, 1, 0)), f - vec3(0, 1, 0));
    float n110 = dot(hash3(i + vec3(1, 1, 0)), f - vec3(1, 1, 0));
    float n001 = dot(hash3(i + vec3(0, 0, 1)), f - vec3(0, 0, 1));
    float n101 = dot(hash3(i + vec3(1, 0, 1)), f - vec3(1, 0, 1));
    float n011 = dot(hash3(i + vec3(0, 1, 1)), f - vec3(0, 1, 1));
    float n111 = dot(hash3(i + vec3(1, 1, 1)), f - vec3(1, 1, 1));
    return mix(mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),
               mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y), u.z);
}
float fbm(vec3 p, int octaves) {
    float sum = 0.0, amp = 1.0, norm = 0.0;
    for (int o = 0; o < 6; ++o) {
        if (o >= octaves) break;
        sum += amp * gnoise(p);
        norm += amp;
        amp *= 0.5;
        p *= 2.0;
    }
    return 0.5 + 0.75 * sum / norm;
}

// ---- tissue texturing of the procedural microanatomy models (the atlas renderer's, app/shaders.py): a mottled
// stain, fibres along an axis and, on cut faces, cells with nuclei
float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}
vec3 hash33(vec3 p) {
    p = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}
float vnoise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = mix(hash13(i), hash13(i + vec3(1, 0, 0)), f.x);
    float b = mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), f.x);
    float c = mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), f.x);
    float d = mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), f.x);
    return mix(mix(a, b, f.y), mix(c, d, f.y), f.z);
}
float fbm3(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p = p * 2.03 + vec3(11.7, 3.1, 7.9);
        a *= 0.5;
    }
    return s / 0.9375;
}
float worley(vec3 p, out vec3 cell) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    float best = 9.0;
    cell = i;
    for (int z = -1; z <= 1; z++)
        for (int y = -1; y <= 1; y++)
            for (int x = -1; x <= 1; x++) {
                vec3 g = vec3(float(x), float(y), float(z));
                vec3 r = g + hash33(i + g) * 0.8 + 0.1 - f;
                float d = dot(r, r);
                if (d < best) { best = d; cell = i + g; }
            }
    return sqrt(best);
}
vec3 tissue_color(vec3 base, vec3 p, bool cap) {
    if (u_detail_on == 0) return base;
    float mottle = u_detail.x;
    float scale = u_detail.y;
    float density = u_detail.z;
    int fiber = int(u_detail.w + 0.5);
    // fibre axis: 1 x, 2 y, 3 z, 4 circumferential around the x axis (vessel media, sphincters)
    vec3 axis = fiber == 1 ? vec3(1.0, 0.0, 0.0) : (fiber == 2 ? vec3(0.0, 1.0, 0.0) :
                (fiber == 3 ? vec3(0.0, 0.0, 1.0) : normalize(vec3(0.0, -p.z, p.y) + vec3(1e-5))));
    float n = fbm3(p * max(scale * 0.22, 3.0));
    float broad = fbm3(p * 7.0 + 3.1);                       // blotches the size of a lobule, not of a cell
    vec3 c = base * (1.0 + mottle * (n - 0.5) * 1.9 + mottle * (broad - 0.5) * 1.5);
    if (fiber > 0) {
        float along = fiber == 4 ? atan(p.z, p.y) * length(p.yz) : dot(p, axis);
        float stripes = sin(along * scale * 5.0 + n * 4.0);
        c *= 1.0 - 0.07 * smoothstep(0.2, 1.0, stripes);
    }
    if (cap && scale > 0.0) {
        vec3 q = p * scale;
        if (fiber > 0) q = q - axis * dot(q, axis) * 0.72;   // elongated cells along fibres
        vec3 cell;
        float d = worley(q, cell);
        float nucleus = (1.0 - smoothstep(0.17, 0.26, d)) * step(hash13(cell * 1.37 + 4.1), density);
        c *= 1.0 - 0.10 * smoothstep(0.50, 0.72, d);
        c = mix(c, vec3(0.085, 0.045, 0.19), nucleus * 0.82);
    }
    return max(c, vec3(0.0));
}

vec3 sh_irradiance(vec3 n) {
    return max(u_sh[0]
        + u_sh[1] * n.y + u_sh[2] * n.z + u_sh[3] * n.x
        + u_sh[4] * (n.x * n.y) + u_sh[5] * (n.y * n.z) + u_sh[6] * (3.0 * n.z * n.z - 1.0)
        + u_sh[7] * (n.x * n.z) + u_sh[8] * (n.x * n.x - n.y * n.y), vec3(0.0));
}

vec2 dir_uv(vec3 d) {
    return vec2(0.5 + atan(d.x, -d.z) / (2.0 * PI), acos(clamp(d.y, -1.0, 1.0)) / PI);
}
vec3 env_spec(vec3 r_cam, float rough) {
    float l = clamp(rough, 0.0, 1.0) * (u_spec_layers - 1.0);
    float l0 = floor(l);
    vec2 uv = dir_uv(r_cam);
    vec3 a = texture(u_spec, vec3(uv, l0)).rgb;
    vec3 b = texture(u_spec, vec3(uv, min(l0 + 1.0, u_spec_layers - 1.0))).rgb;
    return mix(a, b, l - l0);
}
vec2 env_brdf(float r, float NoV) {
    const vec4 c0 = vec4(-1.0, -0.0275, -0.572, 0.022);
    const vec4 c1 = vec4(1.0, 0.0425, 1.04, -0.04);
    vec4 rr = r * c0 + c1;
    float a004 = min(rr.x * rr.x, exp2(-9.28 * NoV)) * rr.x + rr.y;
    return vec2(-1.04, 1.04) * a004 + rr.zw;
}
vec3 multibounce(float ao, vec3 albedo) {
    vec3 a = 2.0404 * albedo - 0.3324;
    vec3 b = -4.7951 * albedo + 0.6417;
    vec3 c = 2.7552 * albedo + 0.6903;
    return max(vec3(ao), ((ao * a + b) * ao + c) * ao);
}

float shadow_tap(int i, vec3 c) {
    if (i == 0) return texture(u_shadow0, c);
    if (i == 1) return texture(u_shadow1, c);
    return texture(u_shadow2, c);
}
const vec2 POISSON[16] = vec2[](
    vec2(-0.94201624, -0.39906216), vec2(0.94558609, -0.76890725), vec2(-0.09418410, -0.92938870),
    vec2(0.34495938, 0.29387760), vec2(-0.91588581, 0.45771432), vec2(-0.81544232, -0.87912464),
    vec2(-0.38277543, 0.27676845), vec2(0.97484398, 0.75648379), vec2(0.44323325, -0.97511554),
    vec2(0.53742981, -0.47373420), vec2(-0.26496911, -0.41893023), vec2(0.79197514, 0.19090188),
    vec2(-0.24188840, 0.99706507), vec2(-0.81409955, 0.91437590), vec2(0.19984126, 0.78641367),
    vec2(0.14383161, -0.14100790));

float shadow(int i, vec3 P, vec3 N, vec3 L) {
    if (u_shadow_on < 0.5) return 1.0;
    mat4 M = (i == 0) ? u_lmat0 : ((i == 1) ? u_lmat1 : u_lmat2);
    float texel = (i == 0) ? u_ltexel0 : ((i == 1) ? u_ltexel1 : u_ltexel2);
    float soft = (i == 0) ? u_lsoft0 : ((i == 1) ? u_lsoft1 : u_lsoft2);
    float NoL = clamp(dot(N, L), 0.0, 1.0);
    vec3 p = P + N * texel * (1.0 + 1.5 * (1.0 - NoL));
    vec4 lp = M * vec4(p, 1.0);
    vec3 s = lp.xyz * 0.5 + 0.5;
    if (s.x < 0.0 || s.y < 0.0 || s.x > 1.0 || s.y > 1.0 || s.z > 1.0) return 1.0;
    // receiver-plane depth bias: follow the receiver's own depth slope across the filter kernel, so a
    // tilted surface does not shadow itself when the kernel is wide (soft area-light penumbrae)
    // Use the continuous shading normal for the receiver plane. Screen derivatives expose
    // individual tessellation planes on smooth curved receivers under a wide PCF kernel.
    vec3 ns = transpose(inverse(mat3(M))) * N;
    vec2 dz = vec2(0.0);
    if (abs(ns.z) > 1e-8) dz = clamp(-ns.xy / ns.z, vec2(-4.0), vec2(4.0));
    float a = ign(gl_FragCoord.xy + float(i) * 7.0) * 6.2831853;
    mat2 R = mat2(cos(a), sin(a), -sin(a), cos(a));
    float sum = 0.0;
    float n = float((i == 0) ? textureSize(u_shadow0, 0).x : ((i == 1) ? textureSize(u_shadow1, 0).x : textureSize(u_shadow2, 0).x));
    float zbias = 0.5 / n;              // about a third of a texel in depth units (range 3r, texel 2r/n)
    for (int k = 0; k < 16; ++k) {
        vec2 o = R * POISSON[k] * soft;
        sum += shadow_tap(i, vec3(s.xy + o, s.z + dot(dz, o) - zbias));
    }
    return sum / 16.0;
}

float D_ggx(float NoH, float a) {
    float a2 = a * a;
    float d = NoH * NoH * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d);
}
float V_smith(float NoV, float NoL, float a) {
    float a2 = a * a;
    float gv = NoL * sqrt(NoV * NoV * (1.0 - a2) + a2);
    float gl = NoV * sqrt(NoL * NoL * (1.0 - a2) + a2);
    return 0.5 / max(gv + gl, 1e-5);
}
vec3 F_schlick(vec3 f0, float VoH) {
    return f0 + (1.0 - f0) * pow(1.0 - VoH, 5.0);
}

struct Surface { vec3 albedo; float alpha; float rough; float metal; vec3 f0; };

vec3 view_vector(vec3 P) {
    return u_ortho == 1 ? u_viewdir : normalize(u_campos - P);
}

Surface surface() {
    Surface s;
    vec3 base = u_base;
    bool flat_on = false;            // a colour mode or a custom colour replaces the look's own colouring
    if (u_batched == 1) {
        vec4 f = item_row(1);
        if (f.w > 0.5) { base = f.rgb; flat_on = true; }
    }
    if (flat_on) {
    } else if (u_stripe == 1) {
        float x = v_fib / u_stripe_p.x;
        float fw = fwidth(x);
        float thr = u_stripe_p.y / max(1.0 - u_shorten * u_weight, 0.2);
        float ab = abs(fract(x) - 0.5);
        float e = max(u_stripe_p.z, fw * 0.75);
        float f = smoothstep(thr - e, thr + e, ab);
        float avg = clamp(1.0 - 2.0 * thr, 0.0, 1.0);
        f = mix(f, avg, smoothstep(0.22, 0.55, fw));
        base = mix(u_stripe_a, u_stripe_b, f * u_stripe_p.w);
    } else if (u_stripe == 2) {
        base = u_stripe_a;
    } else if (u_use_vcol == 1) {
        base *= v_col.rgb;
    }
    if (u_mottle == 1 && !flat_on) {
        float n = fbm(v_opos * u_mottle_p.x, int(u_mottle_p.w));
        float f = smoothstep(u_mottle_p.y, u_mottle_p.z, n);
        base = mix(u_mottle_a, u_mottle_b, f);
    }
    float alpha = u_alpha;
    if (u_has_tex == 1) {
        vec4 t = texture(u_tex, v_uv);
        base *= t.rgb;
        alpha *= t.a;
    }
    base = tissue_color(base, v_opos, false);
    s.albedo = base * (1.0 - u_metal);
    s.f0 = mix(vec3(u_f0), base, u_metal);
    s.alpha = alpha;
    s.rough = clamp(u_rough, 0.04, 1.0);
    s.metal = u_metal;
    return s;
}

vec3 light_contrib(int i, vec3 L, vec3 E, float size, Surface s, vec3 N, vec3 V, float NoV, float occl) {
    float NoL = dot(N, L);
    float lam = max(NoL, 0.0);
    float w = u_wrap;
    float wr = max((NoL + w) / (1.0 + w), 0.0);
    if (wr <= 0.0) return vec3(0.0);
    float sh = shadow(i, v_wpos, N, L);
    // subsurface-style wrap: the light that wraps past the terminator is tinted by the tissue colour
    vec3 tint = sqrt(clamp(s.albedo / max(max(s.albedo.r, max(s.albedo.g, s.albedo.b)), 1e-3), 0.0, 1.0));
    vec3 diff = s.albedo / PI * (lam * sh + (wr - lam) * tint * mix(sh, 1.0, 0.5));
    vec3 spec = vec3(0.0);
    if (lam > 0.0) {
        vec3 H = normalize(L + V);
        float NoH = max(dot(N, H), 0.0);
        float VoH = max(dot(V, H), 0.0);
        float a = s.rough * s.rough;
        float a2 = clamp(a + size * 0.5, 0.0, 1.0);        // area-light widening (Karis)
        float norm = (a / a2) * (a / a2);
        spec = D_ggx(NoH, a2) * norm * V_smith(NoV, lam, a) * F_schlick(s.f0, VoH) * lam * sh;
    }
    return (diff + spec) * E * occl;
}

vec3 shade_opaque(Surface s, vec3 N, vec3 V) {
    float NoV = max(dot(N, V), 1e-4);
    float ao = 1.0;
    vec3 gi = vec3(0.0);
    if (u_ao_on > 0.5) {
        vec4 aog = texture(u_ao, gl_FragCoord.xy / u_screen);
        ao = aog.a;
        gi = aog.rgb;
    }
    float occl = mix(1.0, ao, u_ao_direct);
    vec3 col = vec3(0.0);
    col += light_contrib(0, u_ldir0, u_lrad0, u_lsize0, s, N, V, NoV, occl);
    col += light_contrib(1, u_ldir1, u_lrad1, u_lsize1, s, N, V, NoV, occl);
    col += light_contrib(2, u_ldir2, u_lrad2, u_lsize2, s, N, V, NoV, occl);
    vec3 Nc = mat3(u_view) * N;
    vec3 Vc = mat3(u_view) * V;
    vec3 Rc = reflect(-Vc, Nc);
    vec2 ab = env_brdf(s.rough, NoV);
    vec3 amb_d = s.albedo * sh_irradiance(Nc) / PI * u_env_diffuse;
    vec3 amb_s = env_spec(Rc, s.rough) * (s.f0 * ab.x + ab.y) * u_env_spec;
    col += amb_d * multibounce(ao, s.albedo) + amb_s * ao;
    col += s.albedo * gi * u_bounce;
    return col;
}

vec3 highlight(vec3 col, float NoV, float amount, vec3 hcol) {
    float fr = pow(1.0 - NoV, 2.0);
    return mix(col, col * 0.7 + hcol * (0.10 + 0.55 * fr), amount);
}

vec3 item_highlight(vec3 col, float NoV) {
    if (u_batched == 1) return highlight(col, NoV, item_row(0).z, item_row(2).rgb);
    return highlight(col, NoV, u_highlight, u_highlight_col);
}
"""

MAIN_FS = VERSION + CLIP_COMMON + GEOM_INPUTS + SHADING_COMMON + """
uniform int u_flip;
uniform float u_alpha_cut;
out vec4 o_col;
void main() {
    if (clipped(v_wpos)) discard;
    Surface s = surface();
    if (u_has_tex == 1 && u_alpha_cut > 0.0 && s.alpha < u_alpha_cut) discard;
    vec3 N = normalize(v_wnrm);
    vec3 V = view_vector(v_wpos);
    if (gl_FrontFacing == (u_flip == 1)) N = -N;
    vec3 col = shade_opaque(s, N, V);
    col += u_emis;
    col += v_glow * (s.albedo * 1.6 + vec3(0.30, 0.30, 0.26));     // a conduction impulse, a secretion
    col = item_highlight(col, max(dot(N, V), 1e-4));
    o_col = vec4(col, 1.0);
}
"""

# weighted blended OIT (McGuire & Bavoil 2013): att0 rgb += C*a*w, att0 a *= (1-a); att1 r += a*w
OIT_FS = VERSION + CLIP_COMMON + GEOM_INPUTS + SHADING_COMMON + """
uniform vec3 u_facing;       // alpha min, alpha max, exponent (Blender Layer Weight Facing)
uniform int u_facing_on;
uniform int u_flip;
uniform int u_ghost;         // x-rayed: a faint, cool, rim-weighted ghost of the part
uniform float u_ghost_alpha;
uniform float u_alpha_mul;   // the tissue opacity slider
uniform float u_alpha_cut;
layout(location = 0) out vec4 o_accum;
layout(location = 1) out vec4 o_weight;
void main() {
    if (clipped(v_wpos)) discard;
    Surface s = surface();
    if (u_has_tex == 1 && u_alpha_cut > 0.0 && s.alpha < u_alpha_cut) discard;
    vec3 N = normalize(v_wnrm);
    vec3 V = view_vector(v_wpos);
    if (gl_FrontFacing == (u_flip == 1)) N = -N;
    float NoV = max(dot(N, V), 1e-4);
    float a = s.alpha;
    if (u_facing_on == 1) {
        float facing = 1.0 - pow(NoV, u_facing.z);
        a = mix(u_facing.x, u_facing.y, facing);
    }
    a *= u_batched == 1 ? item_row(2).w : u_alpha_mul;
    vec3 col = vec3(0.0);
    col += light_contrib(0, u_ldir0, u_lrad0, u_lsize0, s, N, V, NoV, 1.0);
    col += light_contrib(1, u_ldir1, u_lrad1, u_lsize1, s, N, V, NoV, 1.0);
    col += light_contrib(2, u_ldir2, u_lrad2, u_lsize2, s, N, V, NoV, 1.0);
    vec3 Nc = mat3(u_view) * N;
    vec3 Vc = mat3(u_view) * V;
    vec2 ab = env_brdf(s.rough, NoV);
    col += s.albedo * sh_irradiance(Nc) / PI * u_env_diffuse;
    col += v_glow * (s.albedo * 1.6 + vec3(0.30, 0.30, 0.26));
    vec3 spec = env_spec(reflect(-Vc, Nc), s.rough) * (s.f0 * ab.x + ab.y) * u_env_spec;
    if ((u_batched == 1 ? item_row(0).w > 0.5 : u_ghost == 1)) {
        float l = dot(col, vec3(0.3, 0.59, 0.11));
        col = mix(col, vec3(l) * vec3(0.85, 0.92, 1.0), 0.55);
        spec *= 0.5;
        a = u_ghost_alpha * (0.25 + 1.6 * pow(1.0 - NoV, 2.5));
        a = min(a, 0.85);
    }
    col = item_highlight(col, NoV);
    a = clamp(a, 0.0, 0.98);
    // Cycles mixes the whole BSDF with a transparent BSDF by alpha, so the sheen is scaled by coverage too
    vec3 premul = (col + spec) * a;
    float lum = a;
    float z = gl_FragCoord.z;
    float w = clamp(pow(min(1.0, lum * 10.0) + 0.01, 3.0) * 1e8 * pow(1.0 - z * 0.9, 3.0), 1e-2, 300.0);
    o_accum = vec4(premul * w, lum);
    o_weight = vec4(lum * w, 0.0, 0.0, 0.0);
}
"""

# ------------------------------------------------------------------------------------------------
# Cut faces

# Depth of one item's nearest kept front face per pixel (MIN blending)
PARITY_FS = VERSION + CLIP_COMMON + """
centroid in vec3 v_wpos;
uniform int u_flip;
out vec4 o_depth;
void main() {
    if (clipped(v_wpos)) discard;
    if (gl_FrontFacing == (u_flip == 1)) discard;
    o_depth = vec4(gl_FragCoord.z);
}
"""

# A cut face of one item: albedo, plane normal, id and the depth of the face on its plane; the depth buffer holds
# the key that makes the innermost item win
CAP_FS = VERSION + CLIP_COMMON + GEOM_INPUTS + SHADING_COMMON + """
uniform int u_flip;
uniform sampler2D u_parity;
uniform mat4 u_inv_viewproj;
uniform mat4 u_viewproj;
uniform vec2 u_viewport;
uniform float u_key_scale;
uniform float u_id;
uniform float u_flags;
uniform float u_cap_dark;
layout(location = 0) out vec4 o_albedo;    // albedo, roughness
layout(location = 1) out vec4 o_normal;    // world normal, f0
layout(location = 2) out vec2 o_id;        // item id, flags (2 = cut face)
layout(location = 3) out float o_zp;       // window depth of the face on its plane

void cap_plane(vec4 P, int on, vec3 o, vec3 d, float tf, inout float best, inout vec3 bn, inout bool found) {
    if (on == 0) return;
    float den = dot(P.xyz, d);
    if (den <= 1e-7) return;
    float t = -(dot(P.xyz, o) + P.w) / den;
    if (t <= 0.0 || t >= tf) return;
    if ((u_clip_mode == 1 && t < best) || (u_clip_mode != 1 && t > best)) {
        best = t;
        bn = P.xyz;
        found = true;
    }
}

// the far end of the stretch of the ray that lies on the removed side (all planes negative for a corner cut)
void span(vec4 P, int on, vec3 o, vec3 d, inout float t0, inout float t1, inout vec3 n1, inout bool any) {
    if (on == 0) return;
    float den = dot(P.xyz, d);
    float s = dot(P.xyz, o) + P.w;
    if (abs(den) < 1e-9) { if (s >= 0.0) t1 = -1.0; return; }
    float t = -s / den;
    if (den > 0.0) { if (t < t1) { t1 = t; n1 = P.xyz; } } else t0 = max(t0, t);
    any = true;
}

bool cut_exit(vec3 o, vec3 d, float tf, out float t, out vec3 n) {
    n = vec3(0.0, 1.0, 0.0);
    t = 0.0;
    if (u_clip_mode == 1) {
        float t0 = 0.0, t1 = 1e30;
        bool any = false;
        span(u_clip0, u_clip_on.x, o, d, t0, t1, n, any);
        span(u_clip1, u_clip_on.y, o, d, t0, t1, n, any);
        span(u_clip2, u_clip_on.z, o, d, t0, t1, n, any);
        t = t1;
        return any && t0 < t1 && t1 > 0.0 && t1 < tf;
    }
    float best = -1e30;
    bool found = false;
    cap_plane(u_clip0, u_clip_on.x, o, d, tf, best, n, found);
    cap_plane(u_clip1, u_clip_on.y, o, d, tf, best, n, found);
    cap_plane(u_clip2, u_clip_on.z, o, d, tf, best, n, found);
    t = best;
    return found;
}

void main() {
    if (clipped(v_wpos)) discard;
    if (gl_FrontFacing != (u_flip == 1)) discard;                 // back faces only
    if (texelFetch(u_parity, ivec2(gl_FragCoord.xy), 0).r < gl_FragCoord.z) discard;   // entered after the cut
    vec2 ndc = gl_FragCoord.xy / u_viewport * 2.0 - 1.0;
    vec4 a = u_inv_viewproj * vec4(ndc, -1.0, 1.0);
    vec4 b = u_inv_viewproj * vec4(ndc, 1.0, 1.0);
    vec3 o = a.xyz / a.w;
    vec3 d = normalize(b.xyz / b.w - o);
    float tf = dot(v_wpos - o, d);
    float best;
    vec3 bn;
    if (!cut_exit(o, d, tf, best, bn)) discard;
    vec3 C = o + d * best;
    vec4 c = u_viewproj * vec4(C, 1.0);
    float behind = max(tf - best, 0.0);
    gl_FragDepth = behind / (behind + u_key_scale);
    vec3 base = u_base;
    if (u_stripe == 1 || u_stripe == 2) base = mix(u_stripe_a, u_stripe_b, 0.35);
    else if (u_use_vcol == 1) base *= v_col.rgb;
    if (u_mottle == 1) base = mix(u_mottle_a, u_mottle_b, 0.5);
    base = tissue_color(base, C, true) * u_cap_dark;
    o_albedo = vec4(base * (1.0 - u_metal), clamp(u_rough, 0.04, 1.0));
    o_normal = vec4(-normalize(bn), u_f0);
    o_id = vec2(u_id, u_flags + 2.0);
    o_zp = clamp(c.z / c.w * 0.5 + 0.5, 1e-7, 1.0);
}
"""

# The cut faces gathered by the cap passes, laid into the pre-pass at their depth on the plane
CAPMIX_PRE_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_cap_normal;
uniform sampler2D u_cap_id;
uniform sampler2D u_cap_zp;
uniform mat4 u_inv_viewproj;
uniform mat4 u_view;
layout(location = 0) out vec4 o_nd;
layout(location = 1) out vec2 o_id;
void main() {
    ivec2 px = ivec2(gl_FragCoord.xy);
    float zp = texelFetch(u_cap_zp, px, 0).r;
    if (zp <= 0.0) discard;
    gl_FragDepth = zp;
    vec4 w = u_inv_viewproj * vec4(v_uv * 2.0 - 1.0, zp * 2.0 - 1.0, 1.0);
    vec3 C = w.xyz / w.w;
    vec3 n = texelFetch(u_cap_normal, px, 0).xyz;
    o_nd = vec4(normalize(mat3(u_view) * n), -(u_view * vec4(C, 1.0)).z);
    o_id = texelFetch(u_cap_id, px, 0).rg;
}
"""

# ... and shaded in the forward pass (deferred: the surface comes from the cap buffers)
CAPMIX_FS = VERSION + """
vec3 v_wpos;
vec3 v_wnrm;
vec3 v_opos;
float v_fib;
vec4 v_col;
vec2 v_uv;
float v_glow;
float v_item;
""" + SHADING_COMMON + """
uniform sampler2D u_cap_albedo;
uniform sampler2D u_cap_normal;
uniform sampler2D u_cap_id;
uniform sampler2D u_cap_zp;
uniform mat4 u_inv_viewproj;
uniform float u_hover_id;
uniform vec3 u_sel_col;
uniform vec3 u_hover_col;
out vec4 o_col;
void main() {
    ivec2 px = ivec2(gl_FragCoord.xy);
    float zp = texelFetch(u_cap_zp, px, 0).r;
    if (zp <= 0.0) discard;
    gl_FragDepth = zp;
    vec2 ndc = gl_FragCoord.xy / u_screen * 2.0 - 1.0;
    vec4 w = u_inv_viewproj * vec4(ndc, zp * 2.0 - 1.0, 1.0);
    v_wpos = w.xyz / w.w;
    v_opos = v_wpos;
    v_fib = 0.0;
    v_col = vec4(1.0);
    v_uv = vec2(0.0);
    v_glow = 0.0;
    vec4 alb = texelFetch(u_cap_albedo, px, 0);
    vec4 nrm = texelFetch(u_cap_normal, px, 0);
    vec2 idf = texelFetch(u_cap_id, px, 0).rg;
    Surface s;
    s.albedo = alb.rgb;
    s.rough = alb.a;
    s.metal = 0.0;
    s.f0 = vec3(nrm.w);
    s.alpha = 1.0;
    vec3 N = normalize(nrm.xyz);
    vec3 V = view_vector(v_wpos);
    if (dot(N, V) < 0.0) N = -N;
    vec3 col = shade_opaque(s, N, V);
    float NoV = max(dot(N, V), 1e-4);
    int flags = int(idf.y + 0.5);
    if ((flags & 1) != 0) col = highlight(col, NoV, 0.45, u_sel_col);
    else if (abs(idf.x - u_hover_id) < 0.5) col = highlight(col, NoV, 0.18, u_hover_col);
    o_col = vec4(col, 1.0);
}
"""

COMPOSITE_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_opaque;
uniform sampler2D u_accum;
uniform sampler2D u_weight;
uniform sampler2D u_id;
uniform int u_oit_on;
uniform int u_has_sel;
uniform float u_hover;
uniform vec3 u_outline;
uniform vec3 u_hover_outline;
uniform float u_exposure;
uniform int u_tonemap;       // 1 = Khronos PBR Neutral, 0 = Standard (clamp)
uniform vec2 u_texel;
uniform float u_outline_px;
out vec4 o_col;

vec3 pbr_neutral(vec3 color) {
    const float startCompression = 0.8 - 0.04;
    const float desaturation = 0.15;
    float x = min(color.r, min(color.g, color.b));
    float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
    color -= offset;
    float peak = max(color.r, max(color.g, color.b));
    if (peak < startCompression) return color;
    const float d = 1.0 - startCompression;
    float newPeak = 1.0 - d * d / (peak + d - startCompression);
    color *= newPeak / peak;
    float g = 1.0 - 1.0 / (desaturation * (peak - newPeak) + 1.0);
    return mix(color, newPeak * vec3(1.0), g);
}
vec3 srgb(vec3 c) {
    c = clamp(c, 0.0, 1.0);
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}
float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }

float is_sel(vec2 uv) {
    float f = texture(u_id, uv).g;
    return mod(floor(f + 0.5), 2.0);
}
float is_id(vec2 uv, float target) {
    return abs(texture(u_id, uv).r - target) < 0.5 ? 1.0 : 0.0;
}

float edge_sel() {
    float c = is_sel(v_uv);
    float e = 0.0;
    for (int i = 0; i < 12; ++i) {
        float a = float(i) * 0.5235988;
        vec2 o = vec2(cos(a), sin(a)) * u_outline_px * u_texel;
        e += abs(is_sel(v_uv + o) - c);
    }
    return clamp(e / 4.0, 0.0, 1.0) * (c > 0.5 ? 0.6 : 1.0);
}

float edge_id(float target) {
    if (target < 0.5) return 0.0;
    float c = is_id(v_uv, target);
    float e = 0.0;
    for (int i = 0; i < 12; ++i) {
        float a = float(i) * 0.5235988;
        vec2 o = vec2(cos(a), sin(a)) * u_outline_px * u_texel;
        e += abs(is_id(v_uv + o, target) - c);
    }
    return clamp(e / 4.0, 0.0, 1.0) * (c > 0.5 ? 0.6 : 1.0);
}

void main() {
    vec3 col = texture(u_opaque, v_uv).rgb;
    if (u_oit_on == 1) {
        vec4 acc = texture(u_accum, v_uv);
        float wsum = texture(u_weight, v_uv).r;
        float reveal = clamp(acc.a, 0.0, 1.0);          // att0.a holds prod(1 - a) (multiplicative blend)
        if (wsum > 1e-6) col = (acc.rgb / wsum) * (1.0 - reveal) + col * reveal;
    }
    col *= exp2(u_exposure);
    col = (u_tonemap == 1) ? pbr_neutral(col) : col;
    col = srgb(col);
    float eh = edge_id(u_hover);
    float es = u_has_sel == 1 ? edge_sel() : 0.0;
    col = mix(col, u_hover_outline, eh * 0.55);
    col = mix(col, u_outline, es);
    col += (ign(gl_FragCoord.xy) - 0.5) / 255.0;
    o_col = vec4(col, 1.0);
}
"""
