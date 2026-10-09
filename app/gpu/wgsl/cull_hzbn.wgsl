// Next level of the depth pyramid: max of 2x2 texels of the level below (clamped at the edge).
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var dst: texture_storage_2d<r32float, write>;

@compute @workgroup_size(8, 8)
fn hzbn(@builtin(global_invocation_id) gid: vec3<u32>) {
    let o = textureDimensions(dst);
    if (gid.x >= o.x || gid.y >= o.y) {
        return;
    }
    let sd = vec2<i32>(textureDimensions(src));
    var m = 0.0;
    for (var dy = 0; dy < 2; dy = dy + 1) {
        for (var dx = 0; dx < 2; dx = dx + 1) {
            let p = min(vec2<i32>(gid.xy) * 2 + vec2<i32>(dx, dy), sd - vec2<i32>(1));
            m = max(m, textureLoad(src, p, 0).r);
        }
    }
    textureStore(dst, gid.xy, vec4<f32>(m, 0.0, 0.0, 0.0));
}
