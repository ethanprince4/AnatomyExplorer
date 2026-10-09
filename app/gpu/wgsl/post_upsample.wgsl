// UPSAMPLE. Joint-bilateral 2x upsample of a half-res SSAO/GI texture to full resolution.
// Bindings: 0 uniform, 1 nd (full-res, unfilterable), 2 lo (half-res rgba16float), 3 hi (full-res rgba16float),
// 4 lo_nd (half-res rgba32float, nd of each block's representative pixel, post_down.wgsl).
// Full pixel q lies at q/2 - 1/4 in half-res texel-index space (texel centres at block centres), so the bilinear weights
// are 3/4 for the block that contains q and 1/4 for its neighbour on q's side of the block. Each of the four texels is
// further weighted by the blur's own depth and normal terms between its representative pixel and q, so values do not
// leak across a depth edge or a crease (the blur's own terms: exp(-|dz| / (0.02 z + 1e-4)) and max(n.n, 0)^8).
// mode 0: all four channels from lo; mode 1: rgb from lo, a from hi (the full-res AO pass: GI at half resolution only).
struct U {
    mode: i32,
    _p0: i32,
    _p1: i32,
    _p2: i32,
};
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var t_nd: texture_2d<f32>;
@group(0) @binding(2) var t_lo: texture_2d<f32>;
@group(0) @binding(3) var t_hi: texture_2d<f32>;
@group(0) @binding(4) var t_lo_nd: texture_2d<f32>;

@fragment
fn fs_upsample(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let q = vec2<i32>(frag.xy);
    let c = textureLoad(t_nd, q, 0);
    if (c.w <= 0.0) { return vec4<f32>(0.0, 0.0, 0.0, 1.0); }
    let lo_max = vec2<i32>(textureDimensions(t_lo)) - 1;
    let i0 = (q + 1) / 2 - 1;                                    // block to the left/below of q's position
    let f = vec2<f32>(0.75 - 0.5 * f32(q.x & 1), 0.75 - 0.5 * f32(q.y & 1));   // weight of block i0 + 1
    var sum = vec4<f32>(0.0);
    var wsum = 0.0;
    for (var k: i32 = 0; k < 4; k++) {
        let dx = k & 1;
        let dy = k >> 1;
        var bil = 1.0;
        if (dx == 1) { bil *= f.x; } else { bil *= 1.0 - f.x; }
        if (dy == 1) { bil *= f.y; } else { bil *= 1.0 - f.y; }
        let ij = clamp(i0 + vec2<i32>(dx, dy), vec2<i32>(0), lo_max);
        let s = textureLoad(t_lo_nd, ij, 0);
        var w = exp(-abs(s.w - c.w) / (0.02 * c.w + 1e-4));
        w *= pow(max(dot(s.xyz, c.xyz), 0.0), 8.0);
        w = bil * (w + 1e-12);
        sum += textureLoad(t_lo, ij, 0) * w;
        wsum += w;
    }
    var o = sum / wsum;
    if (u.mode == 1) { o.a = textureLoad(t_hi, q, 0).a; }
    return o;
}
