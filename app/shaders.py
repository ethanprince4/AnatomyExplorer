GEOMETRY_VS = """
#version 410 core
in vec3 in_pos;
in vec3 in_nrm;
in uint in_obj;
in uint in_mat;
in vec2 in_uv;               // imported models only (u_textured == 1)
in vec4 in_tint;
in float in_layer;

uniform mat4 u_viewproj;
uniform sampler2D u_state;
uniform sampler2D u_mats;
uniform int u_color_row;
uniform int u_pass;          // 0 opaque, 1 transparent, 2 selection mask
uniform float u_ghost_alpha;
uniform int u_textured;

out vec3 v_wpos;
out vec3 v_nrm;
out vec3 v_color;
out vec3 v_surface;
out float v_alpha;
flat out uint v_obj;
flat out int v_flags;
flat out int v_mat;
out vec2 v_uv;
out vec3 v_tint;
flat out float v_layer;
flat out vec3 v_capcol;
out float v_cut;
flat out float v_own;

void main() {
    int obj = int(in_obj);
    vec4 st = texelFetch(u_state, ivec2(obj, 0), 0);
    vec4 st2 = texelFetch(u_state, ivec2(obj, 1), 0);
    int flags = int(st.a + 0.5);
    bool visible = (flags & 1) != 0;
    bool ghost = (flags & 2) != 0;
    bool selected = (flags & 4) != 0;
    vec4 mc = texelFetch(u_mats, ivec2(int(in_mat), u_color_row), 0);
    vec4 ms = texelFetch(u_mats, ivec2(int(in_mat), 2), 0);
    float alpha = mc.a * st2.r;
    if (ghost) alpha = min(alpha, u_ghost_alpha);
    bool transparent = alpha < 0.995;
    bool keep = visible;
    if (u_pass == 0) keep = keep && !transparent;
    else if (u_pass == 1) keep = keep && transparent;
    else if (u_pass == 2) keep = keep && selected;
    if (!keep) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_wpos = vec3(0.0); v_nrm = vec3(0.0, 1.0, 0.0); v_color = vec3(0.0); v_surface = vec3(0.0);
        v_alpha = 0.0; v_obj = 0u; v_flags = 0; v_mat = 0;
        v_uv = vec2(0.0); v_tint = vec3(1.0); v_layer = -1.0; v_capcol = vec3(0.0); v_cut = 0.0; v_own = 0.0;
        return;
    }
    v_mat = int(in_mat);
    v_color = ((flags & 32) != 0) ? st.rgb : mc.rgb;
    // an imported model paints itself (vertex colours, textures) unless a flat colour is asked for
    bool own = u_textured == 1 && u_color_row == 0 && (flags & 32) == 0;
    // texture coordinates and the alpha test apply in every colour mode, so holes stay holes
    v_uv = in_uv;
    v_tint = own ? pow(in_tint.rgb, vec3(2.2)) : vec3(1.0);
    v_layer = u_textured == 1 ? in_layer : -1.0;
    v_capcol = own ? texelFetch(u_mats, ivec2(int(in_mat), 1), 0).rgb : v_color;
    v_cut = u_textured == 1 ? in_tint.a : 0.0;
    v_own = own ? 1.0 : 0.0;
    v_alpha = alpha;
    v_surface = ms.rgb;
    v_wpos = in_pos;
    v_nrm = in_nrm;
    v_obj = in_obj;
    v_flags = flags;
    gl_Position = u_viewproj * vec4(in_pos, 1.0);
}
"""

TONEMAP = """
vec3 to_display(vec3 x) {
    x *= 1.15;
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    x = clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
    return pow(x, vec3(1.0 / 2.2));
}
"""

SHADING_COMMON = TONEMAP + """
uniform vec3 u_eye;
uniform vec3 u_light_key;
uniform vec3 u_light_fill;
uniform vec4 u_clip0;
uniform vec4 u_clip1;
uniform vec4 u_clip2;
uniform ivec3 u_clip_on;
uniform int u_clip_mode;
uniform vec3 u_sel_color;
uniform vec3 u_hover_color;

bool clipped(vec3 p) {
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

vec3 cap_normal(vec3 V) {
    vec3 n = vec3(0.0);
    if (u_clip_on.x == 1) n += u_clip0.xyz;
    if (u_clip_on.y == 1) n += u_clip1.xyz;
    if (u_clip_on.z == 1) n += u_clip2.xyz;
    n = -normalize(n);
    return dot(n, V) < 0.0 ? -n : n;
}

vec3 shade(vec3 base, vec3 N, vec3 V, vec3 surf) {
    float wrap = 0.30;
    float d1 = max((dot(N, u_light_key) + wrap) / (1.0 + wrap), 0.0);
    float d2 = max((dot(N, u_light_fill) + wrap) / (1.0 + wrap), 0.0);
    float hemi = N.y * 0.5 + 0.5;
    vec3 ambient = mix(vec3(0.10, 0.095, 0.09), vec3(0.24, 0.25, 0.27), hemi);
    vec3 diffuse = base * (ambient + d1 * vec3(1.00, 0.97, 0.93) * 0.95 + d2 * vec3(0.60, 0.68, 0.80) * 0.30);
    vec3 H = normalize(u_light_key + V);
    float gloss = max(surf.g, 1.0);
    float spec = pow(max(dot(N, H), 0.0), gloss) * surf.r * (gloss + 8.0) / 60.0;
    float ndv = max(dot(N, V), 0.0);
    float rim = pow(1.0 - ndv, 3.0) * surf.b;
    return diffuse + vec3(spec) * 0.9 + rim * vec3(0.55, 0.60, 0.70);
}

// ---- an imported model's own colour: vertex colour times its base colour texture
uniform sampler2DArray u_albedo;

// sampled first thing in main(), in uniform control flow; the holes of an alpha-tested texture (label cards,
// masked leaves) are discarded in every mode, cut faces included
vec4 texel(vec2 uv, float layer, float cut) {
    vec4 t = texture(u_albedo, vec3(uv, max(layer, 0.0)));
    if (layer >= 0.0 && cut > 0.0 && t.a < cut) discard;
    return t;
}

vec3 albedo(vec3 base, vec3 tint, vec4 t, float layer, float own) {
    vec3 c = base * tint;
    if (layer >= 0.0 && own > 0.5) c *= pow(t.rgb, vec3(2.2)) * 0.9;
    return c;
}

// ---- tissue texturing (microanatomy views only): mottled stain, fibres, nuclei on cut faces
uniform int u_detail;
uniform sampler2D u_mats;

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

vec3 tissue_color(vec3 base, vec3 p, int mat, bool cap) {
    if (u_detail == 0) return base;
    vec4 dp = texelFetch(u_mats, ivec2(mat, 3), 0);
    float mottle = dp.r;
    float scale = dp.g;
    float density = dp.b;
    int fiber = int(dp.a + 0.5);
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
    return c;
}

vec3 decorate(vec3 lit, int flags, vec3 N, vec3 V) {
    float ndv = max(dot(N, V), 0.0);
    if ((flags & 4) != 0) {
        float fres = pow(1.0 - ndv, 3.0);
        lit = mix(lit, lit * 0.85 + u_sel_color * 0.12, 0.45) + u_sel_color * fres * 0.18;
    }
    if ((flags & 8) != 0) {
        lit = lit * 1.18 + u_hover_color * 0.05;
    }
    return lit;
}
"""

OPAQUE_FS = """
#version 410 core
in vec3 v_wpos;
in vec3 v_nrm;
in vec3 v_color;
in vec3 v_surface;
in float v_alpha;
flat in uint v_obj;
flat in int v_flags;
flat in int v_mat;
in vec2 v_uv;
in vec3 v_tint;
flat in float v_layer;
flat in vec3 v_capcol;
in float v_cut;
flat in float v_own;

uniform mat3 u_view3;
uniform mat4 u_viewproj;
""" + SHADING_COMMON + """
layout(location = 0) out vec4 o_color;
layout(location = 1) out vec4 o_normal;
layout(location = 2) out float o_id;
#ifdef CAP_PASS
layout(location = 3) out float o_zp;      // depth of the cut face on the plane; the depth buffer holds the key
#endif

#ifdef CAP_DEPTH
// Caps drawn in their own pass, one part at a time (Renderer._draw_caps): u_parity holds the depth of the part's
// nearest kept front face at each pixel.
uniform sampler2D u_parity;
uniform mat4 u_inv_viewproj;       // the ray is rebuilt from the pixel, so every part meeting the plane at a pixel
uniform vec2 u_viewport;           // gets the very same depth there and the drawing order settles which shows

void cap_plane(vec4 P, int on, vec3 d, float tf, inout float best, inout vec3 bn, inout bool found) {
    if (on == 0) return;
    float den = dot(P.xyz, d);
    if (den <= 1e-5) return;
    float t = -(dot(P.xyz, u_eye) + P.w) / den;
    if (t <= 0.0 || t >= tf) return;
    if ((u_clip_mode == 1 && t < best) || (u_clip_mode != 1 && t > best)) {
        best = t;
        bn = P.xyz;
        found = true;
    }
}

// Where the ray leaves the cut-away before reaching this back face: the far end of the stretch of the ray that
// lies on the removed side (all planes negative for a corner cut, any plane for the other modes).
void span(vec4 P, int on, vec3 d, inout float t0, inout float t1, inout vec3 n1, inout bool any) {
    if (on == 0) return;
    float den = dot(P.xyz, d);
    float s = dot(P.xyz, u_eye) + P.w;
    if (abs(den) < 1e-7) { if (s >= 0.0) t1 = -1.0; return; }
    float t = -s / den;
    if (den > 0.0) { if (t < t1) { t1 = t; n1 = P.xyz; } } else t0 = max(t0, t);
    any = true;
}

bool cut_exit(vec3 d, float tf, out float t, out vec3 n) {
    n = vec3(0.0, 1.0, 0.0);
    t = 0.0;
    if (u_clip_mode == 1) {
        float t0 = 0.0, t1 = 1e9;
        bool any = false;
        span(u_clip0, u_clip_on.x, d, t0, t1, n, any);
        span(u_clip1, u_clip_on.y, d, t0, t1, n, any);
        span(u_clip2, u_clip_on.z, d, t0, t1, n, any);
        t = t1;
        return any && t0 < t1 && t1 > 0.0 && t1 < tf;
    }
    float best = -1e9;
    bool found = false;
    cap_plane(u_clip0, u_clip_on.x, d, tf, best, n, found);
    cap_plane(u_clip1, u_clip_on.y, d, tf, best, n, found);
    cap_plane(u_clip2, u_clip_on.z, d, tf, best, n, found);
    t = best;
    return found;
}
#endif

void main() {
    vec4 tx = texel(v_uv, v_layer, v_cut);
    bool cutobj = (v_flags & 64) == 0;
    if (cutobj && clipped(v_wpos)) discard;
    vec3 V = normalize(u_eye - v_wpos);
    vec3 N = normalize(v_nrm);
    bool anyClip = cutobj && (u_clip_on.x + u_clip_on.y + u_clip_on.z) > 0;
    vec3 lit;
    vec3 capp = v_wpos;           // where the cut face is textured: the back face, or the plane itself
#ifdef CAP_DEPTH
    gl_FragDepth = gl_FragCoord.z;                // written on one path, so it must be written on all
#ifdef CAP_PASS
    if (gl_FrontFacing || !anyClip) discard;
    if (texelFetch(u_parity, ivec2(gl_FragCoord.xy), 0).r < gl_FragCoord.z) discard;   // part entered after the cut
#endif
#endif
    if (!gl_FrontFacing && anyClip) {
        N = cap_normal(V);
#ifdef CAP_PASS
        // put the cut face on the plane where the ray leaves the cut-away, not on the far wall of the part
        vec4 far = u_inv_viewproj * vec4(gl_FragCoord.xy / u_viewport * 2.0 - 1.0, 1.0, 1.0);
        vec3 d = normalize(far.xyz / far.w - u_eye);
        float tf = length(v_wpos - u_eye);
        float best;
        vec3 bn;
        if (!cut_exit(d, tf, best, bn)) discard;
        capp = u_eye + d * best;
        vec4 c = u_viewproj * vec4(capp, 1.0);
        o_zp = clamp(c.z / c.w * 0.5 + 0.5, 1e-7, 1.0);
        // where several parts' cut faces meet at a pixel, the innermost is the one whose far wall comes first
        // behind the plane, so that distance is what the depth test compares; CAPMIX_FS then puts the winner on
        // the plane at its true depth
        float behind = max(tf - best, 0.0);
        gl_FragDepth = behind / (behind + 0.05);
        N = -normalize(bn);
#endif
        vec3 capcol = tissue_color(v_capcol, capp, v_mat, true) * (u_detail == 1 ? 0.80 : 0.62);
        lit = shade(capcol, N, V, vec3(0.05, 8.0, 0.0));
    } else {
        if (!gl_FrontFacing) N = -N;
        lit = shade(tissue_color(albedo(v_color, v_tint, tx, v_layer, v_own), v_wpos, v_mat, false), N, V, v_surface);
    }
    float isCap = (!gl_FrontFacing && anyClip) ? 0.0 : 1.0;
    lit = decorate(lit, v_flags, N, V);
    o_color = vec4(lit, 1.0);
    o_normal = vec4(normalize(u_view3 * N), isCap);
    o_id = float(v_obj) + 1.0;
}
"""

# The cut faces gathered by the cap pass, laid onto the scene at their depth on the cutting plane
CAPMIX_FS = """
#version 410 core
in vec2 v_uv;
uniform sampler2D u_cap_color;
uniform sampler2D u_cap_normal;
uniform sampler2D u_cap_id;
uniform sampler2D u_cap_zp;
layout(location = 0) out vec4 o_color;
layout(location = 1) out vec4 o_normal;
layout(location = 2) out float o_id;
void main() {
    ivec2 px = ivec2(gl_FragCoord.xy);
    float zp = texelFetch(u_cap_zp, px, 0).r;
    if (zp <= 0.0) discard;
    gl_FragDepth = zp;
    o_color = texelFetch(u_cap_color, px, 0);
    o_normal = texelFetch(u_cap_normal, px, 0);
    o_id = texelFetch(u_cap_id, px, 0).r;
}
"""

# Depth of one part's nearest kept front face per pixel (MIN blending), for the cap pass
PARITY_FS = """
#version 410 core
in vec3 v_wpos;
flat in int v_flags;
uniform vec4 u_clip0;
uniform vec4 u_clip1;
uniform vec4 u_clip2;
uniform ivec3 u_clip_on;
uniform int u_clip_mode;
out vec4 o_flip;
void main() {
    bool a = u_clip_on.x == 1 && dot(vec4(v_wpos, 1.0), u_clip0) < 0.0;
    bool b = u_clip_on.y == 1 && dot(vec4(v_wpos, 1.0), u_clip1) < 0.0;
    bool c = u_clip_on.z == 1 && dot(vec4(v_wpos, 1.0), u_clip2) < 0.0;
    bool cut = u_clip_mode == 1
        ? ((u_clip_on.x + u_clip_on.y + u_clip_on.z) > 0 && (u_clip_on.x == 0 || a) && (u_clip_on.y == 0 || b) && (u_clip_on.z == 0 || c))
        : (a || b || c);
    if (cut || !gl_FrontFacing) discard;
    o_flip = vec4(gl_FragCoord.z);
}
"""

TRANSPARENT_FS = """
#version 410 core
in vec3 v_wpos;
in vec3 v_nrm;
in vec3 v_color;
in vec3 v_surface;
in float v_alpha;
flat in uint v_obj;
flat in int v_flags;
flat in int v_mat;
in vec2 v_uv;
in vec3 v_tint;
flat in float v_layer;
flat in vec3 v_capcol;
in float v_cut;
flat in float v_own;
""" + SHADING_COMMON + """
out vec4 o_color;

void main() {
    vec4 tx = texel(v_uv, v_layer, v_cut);
    if ((v_flags & 64) == 0 && clipped(v_wpos)) discard;
    vec3 V = normalize(u_eye - v_wpos);
    vec3 N = normalize(v_nrm);
    if (!gl_FrontFacing) N = -N;
    vec3 lit = shade(tissue_color(albedo(v_color, v_tint, tx, v_layer, v_own), v_wpos, v_mat, false), N, V, v_surface);
    float ndv = abs(dot(N, V));
    float a = v_alpha;
    if ((v_flags & 2) != 0) {
        float l = dot(lit, vec3(0.3, 0.59, 0.11));
        lit = mix(lit, vec3(l) * vec3(0.85, 0.92, 1.0), 0.55);
        a = v_alpha * (0.25 + 1.6 * pow(1.0 - ndv, 2.5));
        a = clamp(a, 0.0, 0.85);
    }
    lit = decorate(lit, v_flags, N, V);
    o_color = vec4(to_display(lit), a);
}
"""

MASK_FS = """
#version 410 core
in vec3 v_wpos;
flat in int v_flags;
in vec2 v_uv;
flat in float v_layer;
in float v_cut;
uniform sampler2DArray u_albedo;
uniform vec4 u_clip0;
uniform vec4 u_clip1;
uniform vec4 u_clip2;
uniform ivec3 u_clip_on;
uniform int u_clip_mode;
out float o_mask;
void main() {
    if (v_layer >= 0.0 && v_cut > 0.0 && texture(u_albedo, vec3(v_uv, v_layer)).a < v_cut) discard;
    bool a = u_clip_on.x == 1 && dot(vec4(v_wpos, 1.0), u_clip0) < 0.0;
    bool b = u_clip_on.y == 1 && dot(vec4(v_wpos, 1.0), u_clip1) < 0.0;
    bool c = u_clip_on.z == 1 && dot(vec4(v_wpos, 1.0), u_clip2) < 0.0;
    bool cut = u_clip_mode == 1
        ? ((u_clip_on.x + u_clip_on.y + u_clip_on.z) > 0 && (u_clip_on.x == 0 || a) && (u_clip_on.y == 0 || b) && (u_clip_on.z == 0 || c))
        : (a || b || c);
    if (cut && (v_flags & 64) == 0) discard;
    o_mask = 1.0;
}
"""

FULLSCREEN_VS = """
#version 410 core
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

SSAO_FS = """
#version 410 core
in vec2 v_uv;
uniform sampler2D u_depth;
uniform sampler2D u_normal;
uniform sampler2D u_noise;
uniform mat4 u_proj;
uniform mat4 u_inv_proj;
uniform vec3 u_kernel[16];
uniform float u_radius;
uniform vec2 u_noise_scale;
out float o_ao;

vec3 view_pos(vec2 uv) {
    float d = texture(u_depth, uv).r;
    vec4 p = u_inv_proj * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.xyz / p.w;
}

void main() {
    float d = texture(u_depth, v_uv).r;
    if (d >= 1.0 || texture(u_normal, v_uv).a < 0.5) { o_ao = 1.0; return; }
    vec3 P = view_pos(v_uv);
    vec3 N = normalize(texture(u_normal, v_uv).xyz);
    vec3 rnd = normalize(texture(u_noise, v_uv * u_noise_scale).xyz * 2.0 - 1.0);
    vec3 T = normalize(rnd - N * dot(rnd, N));
    vec3 B = cross(N, T);
    mat3 TBN = mat3(T, B, N);
    float occ = 0.0;
    for (int i = 0; i < 16; i++) {
        vec3 S = P + TBN * u_kernel[i] * u_radius;
        vec4 off = u_proj * vec4(S, 1.0);
        vec2 suv = off.xy / off.w * 0.5 + 0.5;
        if (suv.x < 0.0 || suv.y < 0.0 || suv.x > 1.0 || suv.y > 1.0) continue;
        float sd = view_pos(suv).z;
        float range = smoothstep(0.0, 1.0, u_radius / max(abs(P.z - sd), 1e-6));
        occ += (sd >= S.z + 0.025 * u_radius ? 1.0 : 0.0) * range;
    }
    o_ao = 1.0 - occ / 16.0;
}
"""

BLUR_FS = """
#version 410 core
in vec2 v_uv;
uniform sampler2D u_src;
uniform vec2 u_texel;
out float o_ao;
void main() {
    float sum = 0.0;
    for (int x = -2; x < 2; x++)
        for (int y = -2; y < 2; y++)
            sum += texture(u_src, v_uv + (vec2(x, y) + 0.5) * u_texel).r;
    o_ao = sum / 16.0;
}
"""

COMPOSITE_FS = """
#version 410 core
""" + TONEMAP + """
in vec2 v_uv;
uniform sampler2D u_color;
uniform sampler2D u_ao;
uniform sampler2D u_depth;
uniform vec3 u_bg_top;
uniform vec3 u_bg_bottom;
uniform float u_ao_strength;
uniform int u_ao_on;
out vec4 o_color;
void main() {
    float d = texture(u_depth, v_uv).r;
    if (d >= 1.0) {
        float t = smoothstep(0.0, 1.0, v_uv.y);
        vec2 c = v_uv - 0.5;
        float vig = 1.0 - dot(c, c) * 0.35;
        o_color = vec4(mix(u_bg_bottom, u_bg_top, t) * vig, 1.0);
        return;
    }
    vec3 col = texture(u_color, v_uv).rgb;
    if (u_ao_on == 1) {
        float ao = texture(u_ao, v_uv).r;
        col *= mix(1.0, ao, u_ao_strength);
    }
    o_color = vec4(to_display(col), 1.0);
}
"""

FINAL_FS = """
#version 410 core
in vec2 v_uv;
uniform sampler2D u_hdr;
uniform sampler2D u_mask;
uniform sampler2D u_mask_depth;
uniform sampler2D u_depth;
uniform sampler2D u_id;
uniform vec2 u_texel;
uniform float u_hover_id;
uniform vec3 u_sel_color;
uniform vec3 u_hover_color;
uniform int u_has_selection;
out vec4 o_color;

void main() {
    vec3 col = texture(u_hdr, v_uv).rgb;

    if (u_has_selection == 1) {
        float m = texture(u_mask, v_uv).r;
        float sd = texture(u_depth, v_uv).r;
        float md = texture(u_mask_depth, v_uv).r;
        if (m > 0.5 && md > sd + 1e-6) {
            // selected surface hidden behind other tissue: show it through
            vec2 px = v_uv / u_texel;
            float hatch = step(0.5, fract((px.x + px.y) / 9.0));
            col = mix(col, u_sel_color, 0.28 + 0.10 * hatch);
        }
        float edge = 0.0;
        float occluded = 0.0;
        if (m < 0.5) {
            for (int i = 0; i < 12; i++) {
                float ang = float(i) * 0.5235988;
                vec2 o = vec2(cos(ang), sin(ang)) * 2.5 * u_texel;
                float mm = texture(u_mask, v_uv + o).r;
                if (mm > 0.5) {
                    edge = 1.0;
                    float nd = texture(u_mask_depth, v_uv + o).r;
                    float ssd = texture(u_depth, v_uv + o).r;
                    if (nd > ssd + 1e-6) occluded += 1.0;
                }
            }
        }
        if (edge > 0.5) {
            float vis = occluded > 0.0 ? 0.55 : 1.0;
            col = mix(col, u_sel_color * 1.1, vis);
        }
    }

    if (u_hover_id > 0.5) {
        float id = texture(u_id, v_uv).r;
        if (abs(id - u_hover_id) > 0.5) {
            float e = 0.0;
            e += float(abs(texture(u_id, v_uv + vec2(u_texel.x, 0)).r - u_hover_id) < 0.5);
            e += float(abs(texture(u_id, v_uv - vec2(u_texel.x, 0)).r - u_hover_id) < 0.5);
            e += float(abs(texture(u_id, v_uv + vec2(0, u_texel.y)).r - u_hover_id) < 0.5);
            e += float(abs(texture(u_id, v_uv - vec2(0, u_texel.y)).r - u_hover_id) < 0.5);
            if (e > 0.0) col = mix(col, u_hover_color, 0.85);
        }
    }
    float luma = dot(col, vec3(0.299, 0.587, 0.114));
    o_color = vec4(col, luma);
}
"""

FXAA_FS = """
#version 410 core
in vec2 v_uv;
uniform sampler2D u_src;
uniform vec2 u_texel;
uniform int u_enabled;
out vec4 o_color;

void main() {
    vec4 c = texture(u_src, v_uv);
    if (u_enabled == 0) { o_color = vec4(c.rgb, 1.0); return; }
    float lM = c.a;
    float lNW = texture(u_src, v_uv + vec2(-1.0, -1.0) * u_texel).a;
    float lNE = texture(u_src, v_uv + vec2( 1.0, -1.0) * u_texel).a;
    float lSW = texture(u_src, v_uv + vec2(-1.0,  1.0) * u_texel).a;
    float lSE = texture(u_src, v_uv + vec2( 1.0,  1.0) * u_texel).a;
    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    if (lMax - lMin < max(0.0312, lMax * 0.125)) { o_color = vec4(c.rgb, 1.0); return; }
    vec2 dir = vec2(-((lNW + lNE) - (lSW + lSE)), ((lNW + lSW) - (lNE + lSE)));
    float reduce = max((lNW + lNE + lSW + lSE) * 0.03125, 1.0 / 128.0);
    float rmin = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
    dir = clamp(dir * rmin, vec2(-8.0), vec2(8.0)) * u_texel;
    vec3 a = 0.5 * (texture(u_src, v_uv + dir * (1.0 / 3.0 - 0.5)).rgb + texture(u_src, v_uv + dir * (2.0 / 3.0 - 0.5)).rgb);
    vec3 b = a * 0.5 + 0.25 * (texture(u_src, v_uv + dir * -0.5).rgb + texture(u_src, v_uv + dir * 0.5).rgb);
    float lB = dot(b, vec3(0.299, 0.587, 0.114));
    o_color = vec4((lB < lMin || lB > lMax) ? a : b, 1.0);
}
"""
