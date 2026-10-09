// Depth pyramid from this frame's real MSAA depth. Level 0 is half the render size (ceil) and holds the FARTHEST of all
// samples of a 2x2 block of pixels (a background sample counts as 1.0, so a pixel that is not fully covered never
// occludes); every further level is the max of 2x2 texels with clamped reads, so odd edges are never dropped.
// cull.py prepends: `alias DepthTex = texture_depth_multisampled_2d|texture_depth_2d;`, `const SAMPLES: u32;` and
// `fn load_depth(p: vec2<i32>, s: i32) -> f32`.

@group(0) @binding(0) var dsrc: DepthTex;
@group(0) @binding(1) var dst: texture_storage_2d<r32float, write>;

@compute @workgroup_size(8, 8)
fn hzb0(@builtin(global_invocation_id) gid: vec3<u32>) {
    let o = textureDimensions(dst);
    if (gid.x >= o.x || gid.y >= o.y) {
        return;
    }
    let sd = vec2<i32>(textureDimensions(dsrc));
    var m = 0.0;
    for (var dy = 0; dy < 2; dy = dy + 1) {
        for (var dx = 0; dx < 2; dx = dx + 1) {
            let p = min(vec2<i32>(gid.xy) * 2 + vec2<i32>(dx, dy), sd - vec2<i32>(1));
            for (var s = 0; s < i32(SAMPLES); s = s + 1) {
                m = max(m, load_depth(p, s));
            }
        }
    }
    textureStore(dst, gid.xy, vec4<f32>(m, 0.0, 0.0, 0.0));
}
