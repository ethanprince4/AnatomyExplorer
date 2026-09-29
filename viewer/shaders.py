"""GLSL sources for the viewer renderer (OpenGL 4.1 core).

Passes: shadow depth (x3 lights) -> pre-pass (view normal + linear depth + part id, single sample) -> SSAO +
bilateral blur -> MSAA forward pass (backdrop, opaque PBR) -> MSAA weighted-blended OIT pass (translucent
covering) -> resolve -> composite (OIT blend, selection outline, Khronos PBR Neutral, sRGB, dither).
"""

VERSION = "#version 410 core\n"

# ------------------------------------------------------------------------------------------------
# Geometry: one vertex format for every part; the single morph target is blended on the GPU.

GEOM_VS = VERSION + """
in vec3 in_pos;
in vec3 in_nrm;
in vec3 in_dpos;
in vec3 in_dnrm;
in float in_fib;
in vec4 in_col;
in vec2 in_uv;

uniform mat4 u_model;
uniform mat3 u_nmat;
uniform mat4 u_viewproj;
uniform float u_weight;

out vec3 v_wpos;
out vec3 v_wnrm;
out vec3 v_opos;
out float v_fib;
out vec4 v_col;
out vec2 v_uv;

void main() {
    vec3 p = in_pos + u_weight * in_dpos;
    vec3 n = in_nrm + u_weight * in_dnrm;
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

SHADOW_VS = VERSION + """
in vec3 in_pos;
in vec3 in_dpos;
uniform mat4 u_model;
uniform mat4 u_viewproj;
uniform float u_weight;
void main() {
    gl_Position = u_viewproj * (u_model * vec4(in_pos + u_weight * in_dpos, 1.0));
}
"""

SHADOW_FS = VERSION + """
void main() {}
"""

PREPASS_FS = VERSION + """
in vec3 v_wpos;
in vec3 v_wnrm;
uniform mat4 u_view;
uniform float u_id;
layout(location = 0) out vec4 o_nd;
layout(location = 1) out float o_id;
void main() {
    vec3 n = normalize(mat3(u_view) * v_wnrm);
    if (!gl_FrontFacing) n = -n;
    float d = -(u_view * vec4(v_wpos, 1.0)).z;
    o_nd = vec4(n, d);
    o_id = u_id;
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
# Shading (shared by the opaque and the translucent pass)

SHADING_COMMON = """
const float PI = 3.14159265;
in vec3 v_wpos;
in vec3 v_wnrm;
in vec3 v_opos;
in float v_fib;
in vec4 v_col;
in vec2 v_uv;

uniform vec3 u_campos;
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
uniform float u_sss;
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
    vec3 sx = dFdx(s);
    vec3 sy = dFdy(s);
    float det = sx.x * sy.y - sx.y * sy.x;
    vec2 dz = vec2(0.0);
    if (abs(det) > 1e-12) {
        dz = vec2(sy.y * sx.z - sx.y * sy.z, sx.x * sy.z - sy.x * sx.z) / det;
        float lim = 4.0;
        dz = clamp(dz, vec2(-lim), vec2(lim));
    }
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

Surface surface() {
    Surface s;
    vec3 base = u_base;
    if (u_stripe == 1) {
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
    if (u_mottle == 1) {
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
"""

MAIN_FS = VERSION + SHADING_COMMON + """
out vec4 o_col;
void main() {
    Surface s = surface();
    vec3 N = normalize(v_wnrm);
    vec3 V = normalize(u_campos - v_wpos);
    if (!gl_FrontFacing) N = -N;
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
    col += u_emis;
    // selection: a soft fresnel glow in the highlight colour
    float fr = pow(1.0 - NoV, 2.0);
    col = mix(col, col * 0.7 + u_highlight_col * (0.10 + 0.55 * fr), u_highlight);
    o_col = vec4(col, 1.0);
}
"""

# weighted blended OIT (McGuire & Bavoil 2013): att0 rgb += C*a*w, att0 a *= (1-a); att1 r += a*w
OIT_FS = VERSION + SHADING_COMMON + """
uniform vec3 u_facing;       // alpha min, alpha max, exponent (Blender Layer Weight Facing)
uniform int u_facing_on;
layout(location = 0) out vec4 o_accum;
layout(location = 1) out vec4 o_weight;
void main() {
    Surface s = surface();
    vec3 N = normalize(v_wnrm);
    vec3 V = normalize(u_campos - v_wpos);
    if (!gl_FrontFacing) N = -N;
    float NoV = max(dot(N, V), 1e-4);
    float a = s.alpha;
    if (u_facing_on == 1) {
        float facing = 1.0 - pow(NoV, u_facing.z);
        a = mix(u_facing.x, u_facing.y, facing);
    }
    a = clamp(a, 0.0, 0.98);
    vec3 col = vec3(0.0);
    col += light_contrib(0, u_ldir0, u_lrad0, u_lsize0, s, N, V, NoV, 1.0);
    col += light_contrib(1, u_ldir1, u_lrad1, u_lsize1, s, N, V, NoV, 1.0);
    col += light_contrib(2, u_ldir2, u_lrad2, u_lsize2, s, N, V, NoV, 1.0);
    vec3 Nc = mat3(u_view) * N;
    vec3 Vc = mat3(u_view) * V;
    vec2 ab = env_brdf(s.rough, NoV);
    col += s.albedo * sh_irradiance(Nc) / PI * u_env_diffuse;
    vec3 spec = env_spec(reflect(-Vc, Nc), s.rough) * (s.f0 * ab.x + ab.y) * u_env_spec;
    col = mix(col, col * 0.7 + u_highlight_col * 0.4, u_highlight);
    // Cycles mixes the whole BSDF with a transparent BSDF by alpha, so the sheen is scaled by coverage too
    vec3 premul = (col + spec) * a;
    float lum = a;
    float z = gl_FragCoord.z;
    float w = clamp(pow(min(1.0, lum * 10.0) + 0.01, 3.0) * 1e8 * pow(1.0 - z * 0.9, 3.0), 1e-2, 300.0);
    o_accum = vec4(premul * w, lum);
    o_weight = vec4(lum * w, 0.0, 0.0, 0.0);
}
"""

COMPOSITE_FS = VERSION + """
in vec2 v_uv;
uniform sampler2D u_opaque;
uniform sampler2D u_accum;
uniform sampler2D u_weight;
uniform sampler2D u_id;
uniform int u_oit_on;
uniform float u_sel;
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

float edge(float target) {
    if (target < 0.5) return 0.0;
    float c = abs(texture(u_id, v_uv).r - target) < 0.5 ? 1.0 : 0.0;
    float e = 0.0;
    for (int i = 0; i < 12; ++i) {
        float a = float(i) * 0.5235988;
        vec2 o = vec2(cos(a), sin(a)) * u_outline_px * u_texel;
        float s = abs(texture(u_id, v_uv + o).r - target) < 0.5 ? 1.0 : 0.0;
        e += abs(s - c);
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
    float eh = edge(u_hover);
    float es = edge(u_sel);
    col = mix(col, u_hover_outline, eh * 0.55);
    col = mix(col, u_outline, es);
    col += (ign(gl_FragCoord.xy) - 0.5) / 255.0;
    o_col = vec4(col, 1.0);
}
"""
