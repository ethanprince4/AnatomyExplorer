// Visibility pass: one indexed draw per draw slot, instance_index = slot. Writes (slot << prim_bits) | primitive_index
// into an MSAA id target (slot 0 = background) and depth (z in [0, 1], "less", cleared to 1, no face culling: the
// viewer draws both faces, as the GL pre-pass does). Row 0 of the target = bottom of the picture (GL's row order).
//
// Concatenated by app/gpu/renderer.py after: `enable primitive_index;`, the generated prelude (alias IdOut,
// fn pack_id), clip.wgsl (Frame, Draw, clipped), tables.wgsl (draws, ptab, anim_tab: one buffer), the page binding (geometry.py
// geom_prelude, group 1) and geom.wgsl, morph.wgsl.

@group(0) @binding(0) var<uniform> frame: Frame;

struct VOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) wpos: vec3<f32>,                                // centre interpolation, as GL's pre-pass on one sample
    @location(1) @interpolate(flat) slot: u32,
};

// World position of vertex `v` (page local) of the draw: part matrix * (position + morph + animation), morph.wgsl.
fn vertex_world(d: Draw, v: u32) -> vec3<f32> {
    let p = g_pos(0u, v);
    return (d.model * vec4<f32>(morph_pos(d, 0u, v, p), 1.0)).xyz;
}

@vertex
fn vs(@builtin(vertex_index) vi: u32, @builtin(instance_index) slot: u32) -> VOut {
    let d = load_draw(slot);
    let w = vertex_world(d, g_vertex(0u, vi));
    var o: VOut;
    let cl = frame.vp * vec4<f32>(w, 1.0);
    // Rendered bottom-up, like GL: wgpu's framebuffer is y-down, so the clip y is negated and row 0 of the target is the
    // bottom of the picture. This also puts the MSAA sample pattern (defined y-down in Vulkan, y-up in GL; the same numbers)
    // where GL has it.
    o.clip = vec4<f32>(cl.x, -cl.y, cl.z, cl.w);
    o.wpos = w;
    o.slot = slot;
    return o;
}

@fragment
fn fs(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    return pack_id((in.slot << frame.info.x) | prim);
}

// Same, with the cutting planes: clipped fragments are discarded (GL: PREPASS_FS). Used only while a plane is on,
// so the common case keeps early depth rejection. TODO (later step): alpha-cut textures discard here too.
@fragment
fn fs_clip(in: VOut, @builtin(primitive_index) prim: u32) -> @location(0) IdOut {
    if (clipped(frame.clip, in.wpos, (load_draw(in.slot).b.z & DRAW_NOCLIP) != 0u)) {
        discard;
    }
    return pack_id((in.slot << frame.info.x) | prim);
}
