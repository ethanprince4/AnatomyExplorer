// PACK. Bindings: 0 nd (unfilterable rgba32float). Writes nd.w (linear view depth, 0 = background) to an r32float
// target of the same size: bit-exact, 4 B per texel for the SSAO taps. textureLoad at the fragment's own texel (the
// target and the source share size and row order).
@group(0) @binding(0) var t_nd: texture_2d<f32>;

@fragment
fn fs_pack(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let d = textureLoad(t_nd, vec2<i32>(frag.xy), 0).w;
    return vec4<f32>(d, 0.0, 0.0, 1.0);
}
