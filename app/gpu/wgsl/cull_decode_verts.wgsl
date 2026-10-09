// Optional, for resolve pipelines that already include geom.wgsl (g_index): the three page-local vertex ids of a culled triangle.
// Concatenate after cull_decode.wgsl and geom.wgsl. `lp` is the pipeline's own page number of d.page: bind the geometry pages in
// the resolve in geometry-page order, so that lp == d.page (geom_prelude numbers its pages 0 .. n-1 in binding order).
fn cull_tri_verts(lp: u32, d: CullTri) -> vec3<u32> {
    return vec3<u32>(g_index(lp, d.first), g_index(lp, d.first + 1u), g_index(lp, d.first + 2u));
}
