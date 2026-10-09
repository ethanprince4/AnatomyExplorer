// DOWN. Picks the representative pixel of every 2x2 block of nd for the half-resolution AO/GI passes.
// Bindings: 0 nd (full-res, unfilterable). Targets: 0 rgba32float = nd of the chosen pixel (xyz normal, w view depth),
// 1 r8uint = its offset in the block, dx + 2 * dy.
// Rule: among the pixels with a surface (nd.w > 0) take the one whose depth is closest to the mean depth of those
// pixels (the first one on a tie, scanning (0,0) (1,0) (0,1) (1,1)). A block that touches the silhouette is therefore
// represented by a surface pixel, and a block that straddles a depth step by the majority surface. A block with no
// surface keeps (0,0), a background pixel.
@group(0) @binding(0) var t_nd: texture_2d<f32>;

struct Out {
    @location(0) nd: vec4<f32>,
    @location(1) off: vec4<u32>,
};

@fragment
fn fs_down(@builtin(position) frag: vec4<f32>) -> Out {
    let b = vec2<i32>(frag.xy) * 2;
    let hi = vec2<i32>(textureDimensions(t_nd)) - 1;
    var v: array<vec4<f32>, 4>;
    var cnt = 0.0;
    var sum = 0.0;
    for (var k: i32 = 0; k < 4; k++) {
        v[k] = textureLoad(t_nd, min(b + vec2<i32>(k & 1, k >> 1), hi), 0);
        if (v[k].w > 0.0) { cnt += 1.0; sum += v[k].w; }
    }
    var best = 0;
    if (cnt > 0.0) {
        let mean = sum / cnt;
        var bd = 1e30;
        for (var k: i32 = 0; k < 4; k++) {
            if (v[k].w > 0.0) {
                let e = abs(v[k].w - mean);
                if (e < bd) { bd = e; best = k; }
            }
        }
    }
    var o: Out;
    o.nd = v[best];
    o.off = vec4<u32>(u32(best), 0u, 0u, 0u);
    return o;
}
