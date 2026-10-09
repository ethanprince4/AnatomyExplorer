// The renderer's tables, in ONE storage buffer (binding 1 of group 0; one binding instead of four, for adapters that allow
// few storage buffers per stage). Sections start at 256-byte aligned word offsets, given by the uniform `tinfo`:
//   tinfo.x  ptab       per part, PTAB_STRIDE words: 0..4 stream bases (i32, -1 constant), 5 vertex base, 6..18 constant tail, 19 anim base
//   tinfo.y  anim_tab   per item, three vec4: morph weights (u_aw), (mode, glow, decay, rate) (u_ag), (anim_t, on, 0, 0)
//   tinfo.z  looks      per look record, ShadeU (shading_uniforms.py layout), read field by field by the generated apply_look
//   tinfo.w  draws      per draw slot, ten vec4: the Draw record of clip.wgsl
// Concatenated after clip.wgsl (Draw).

@group(0) @binding(1) var<storage, read> tab: array<vec4<u32>>;
@group(0) @binding(2) var<uniform> tinfo: vec4<u32>;

const PTAB_STRIDE: u32 = 20u;

fn tab_w(i: u32) -> u32 {
    return tab[i >> 2u][i & 3u];
}

fn ptab_w(i: u32) -> u32 {
    return tab_w(tinfo.x + i);
}

fn anim_at(i: u32) -> vec4<f32> {
    return bitcast<vec4<f32>>(tab[(tinfo.y >> 2u) + i]);
}

fn load_draw(slot: u32) -> Draw {
    let b = (tinfo.w >> 2u) + 10u * slot;
    var d: Draw;
    d.model = mat4x4<f32>(bitcast<vec4<f32>>(tab[b]), bitcast<vec4<f32>>(tab[b + 1u]),
                          bitcast<vec4<f32>>(tab[b + 2u]), bitcast<vec4<f32>>(tab[b + 3u]));
    d.nmat0 = bitcast<vec4<f32>>(tab[b + 4u]);
    d.nmat1 = bitcast<vec4<f32>>(tab[b + 5u]);
    d.nmat2 = bitcast<vec4<f32>>(tab[b + 6u]);
    d.a = tab[b + 7u];
    d.b = tab[b + 8u];
    d.c = bitcast<vec4<f32>>(tab[b + 9u]);
    return d;
}
