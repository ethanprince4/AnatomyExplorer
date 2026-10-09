// The culler's tables, in three storage buffers (at most three per stage). Every section is addressed through the uniform `lay`
// (cull.py _sections writes it):
//   cro  array<vec4<u32>>   read only; part_xf and range_active are rewritten by cull.py every frame (queue writes)
//        lay.a  (vec4 units)  x cl_geom: 2 per cluster, (cx cy cz dmax) and (hx hy hz 0) as f32 bits;  y cl_range: cluster -> range;
//                             z rng: 2 per range, (part page first ntri) and (cfirst tfirst ccount 0);
//                             w ptab: per page (cluster first, cluster end, slot base, capacity)
//        lay.b  (vec4 units)  x part_xf: 5 per part, matrix columns 0..3 as f32 bits, then (|weight| bits, flags, slot0, ordinal of the part in its page);
//                             y range_active;  z pinfo: per page (vertex bits, 1 = indexed draw allowed, first entry of the page in pgp, 0);
//                             w pgp: one word per (page, ordinal): the model part (the indexed draw's vertex shader decodes it from the index)
//   cra  array<atomic<u32>>  lay.c (words)  x pstate: 8 per page;  y stats: 16;  z seen: one flag per cluster (statistics only)
//   crw  array<u32>          lay.d (words)  x args: 16 per (page, phase): words 0..4 the indexed draw (index_count = slots * 192, 1,
//                             first_index = first compact slot * 192, 0, 0), words 8..11 the pulled draw of the slots that did not fit
//                             the budget (non-indexed, vertex_count = slots * 192, 1, 0, 0), words 12..14 the gather dispatch (x, y, 1);
//                             y unused;  z dinfo: 2 per (page, phase): list slot of the indexed draw's first cluster, then of the pulled
//                             draw's first cluster;  w unused
//   crl  array<vec4<u32>>    the visible-cluster lists (one per page, phases back to back): (cluster, page-local index word of the
//                             cluster's first triangle, part, triangles in the cluster); written by cull_test, read by cull_vis
//                             lay.e (words)  x vis_prev, y vis_next: visible-next-frame flags per cluster (swapped every frame)
// crw is also the indirect-draw source, so every stage that is not a culling kernel binds it read only.
// A module that includes this file declares `cro` and `lay`. Every culling entry's last (ntri) word also carries the part ordinal: w = ntri | (ordinal << 8).

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

fn pinfo_at(g: u32) -> vec4<u32> {
    return cro[lay.b.z + g];
}

fn pgp_at(i: u32) -> u32 {
    return cro[lay.b.w + (i >> 2u)][i & 3u];
}
