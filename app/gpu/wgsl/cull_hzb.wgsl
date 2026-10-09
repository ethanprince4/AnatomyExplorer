// Depth pyramid from this frame's real MSAA depth. Level 0 is half the render size (ceil) and holds the FARTHEST of all
// samples of a 2x2 block of pixels (a background sample counts as 1.0, so a pixel that is not fully covered never
// occludes); every further level is the max of 2x2 texels with clamped reads, so odd edges are never dropped.
// One thread per PIXEL reads all its samples (adjacent threads read adjacent pixels: the multisample depth surface is
// fetched in cache-line order, ~6x faster than one thread per 2x2 block on Intel UHD 770); the quad max is taken in
// workgroup memory. A 16x16 pixel tile makes an 8x8 texel tile of level 0; edge pixels are clamped like before.
// cull.py prepends: alias DepthTex = texture_depth_multisampled_2d|texture_depth_2d, const SAMPLES: u32 and
// fn load_depth(p: vec2<i32>, s: i32) -> f32.

@group(0) @binding(0) var dsrc: DepthTex;
@group(0) @binding(1) var dst: texture_storage_2d<r32float, write>;

var<workgroup> tile: array<f32, 256>;

@compute @workgroup_size(16, 16)
fn hzb0(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>) {
    let sd = vec2<i32>(textureDimensions(dsrc));
    let p = min(vec2<i32>(wid.xy * 16u + lid.xy), sd - vec2<i32>(1));
    var m = 0.0;
    for (var s = 0; s < i32(SAMPLES); s = s + 1) {
        m = max(m, load_depth(p, s));
    }
    tile[lid.y * 16u + lid.x] = m;
    workgroupBarrier();
    if (lid.x < 8u && lid.y < 8u) {
        let o = textureDimensions(dst);
        let t = wid.xy * 8u + lid.xy;
        if (t.x < o.x && t.y < o.y) {
            let b = lid.y * 2u * 16u + lid.x * 2u;
            let v = max(max(tile[b], tile[b + 1u]), max(tile[b + 16u], tile[b + 17u]));
            textureStore(dst, t, vec4<f32>(v, 0.0, 0.0, 0.0));
        }
    }
}
