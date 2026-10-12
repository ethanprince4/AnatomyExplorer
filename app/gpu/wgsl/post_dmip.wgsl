// DMIP. One level of the SSAO depth chain from the level below (PostPasses.build_depth_mips).
// Bindings: 0 src = level i - 1 of the r32float depth texture (unfilterable). Target: level i.
// Each texel takes ONE texel of its 2x2 block below, the pick rotating with the texel's parity (McGuire et al.,
// Scalable Ambient Obscurance, 2012). It is always a depth that exists in the picture, never a mean or a min/max: a mean
// would invent surfaces at depth steps and turn the background's 0 into a tiny depth, a min/max would bias the occlusion.
@group(0) @binding(0) var t_src: texture_2d<f32>;

@fragment
fn fs_dmip(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let p = vec2<i32>(frag.xy);
    let hi = vec2<i32>(textureDimensions(t_src)) - 1;
    return textureLoad(t_src, min(p * 2 + vec2<i32>(p.y & 1, p.x & 1), hi), 0);
}
