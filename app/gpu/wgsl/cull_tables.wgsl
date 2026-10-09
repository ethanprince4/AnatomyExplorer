// The culler's tables, in three storage buffers plus the perm buffer (layout v2: at most five storage buffers per stage). Every
// section is addressed through the uniform `lay` (cull.py _sections writes it):
//   cro  array<vec4<u32>>   read only; part_xf and range_active are rewritten by cull.py every frame (queue writes)
//        lay.a  (vec4 units)  x cl_geom: 2 per cluster, (cx cy cz dmax) and (hx hy hz 0) as f32 bits;  y cl_range: cluster -> range;
//                             z rng: 2 per range, (part page first ntri) and (cfirst tfirst ccount 0);
//                             w ptab: per page (cluster first, cluster end, slot base, capacity)
//        lay.b  (vec4 units)  x part_xf: 5 per part, matrix columns 0..3 as f32 bits, then (|weight| bits, flags, slot0, 0);  y range_active
//   cra  array<atomic<u32>>  lay.c (words)  x pstate: 8 per page;  y stats: 16;  z seen: one flag per block slot
//   crw  array<u32>          lay.d (words)  x args: 8 per (page, phase), indexed draw arguments;  y disp: 4 per (page, phase), gather
//                             dispatch size;  z dinfo: per (page, phase), id slot of the draw's first block;  w slot_cluster
//                             lay.e (words)  x vis_prev, y vis_next: visible-next-frame flags per cluster (swapped every frame)
// crw is also the indirect-draw / indirect-dispatch source, so every stage that is not a culling kernel binds it read only.
// A module that includes this file declares `cro`, `lay` and `fn crw_w(i: u32) -> u32` (word i of crw).

struct CullLay {
    a: vec4<u32>,
    b: vec4<u32>,
    c: vec4<u32>,
    d: vec4<u32>,
    e: vec4<u32>,
};

fn cl_geom_at(i: u32) -> vec4<f32> {
    return bitcast<vec4<f32>>(cro[lay.a.x + i]);
}

fn cl_range_at(c: u32) -> u32 {
    return cro[lay.a.y + (c >> 2u)][c & 3u];
}

fn rng_at(i: u32) -> vec4<u32> {
    return cro[lay.a.z + i];
}

fn ptab_at(g: u32) -> vec4<u32> {
    return cro[lay.a.w + g];
}

fn part_xf_at(i: u32) -> vec4<f32> {
    return bitcast<vec4<f32>>(cro[lay.b.x + i]);
}

fn part_meta_at(part: u32) -> vec4<u32> {
    return cro[lay.b.x + part * 5u + 4u];
}

fn range_active_at(r: u32) -> u32 {
    return cro[lay.b.y + (r >> 2u)][r & 3u];
}

fn slot_cluster_at(s: u32) -> u32 {
    return crw_w(lay.d.w + s);
}
