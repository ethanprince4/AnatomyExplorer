# Cull spike handoff (R=worktree keen-ride-vm1yxr)
Code: R/tools/perf/spikes/cull/{clusters,scene,shaders,gpu,run}.py. Run: bash S/spikes/cull/go.sh <outname> <cmd> --size 25M|100M|250M --adapter 3080|uhd
Cmds: smoke, measure, correct (--nocull adds back-face test), shade, hzb, calib. Logs: S/spikes/cull/<outname>.jsonl
Cluster cache: S/spikes/cull/cache (9 models, 23.5M unique tris, 347K clusters, 68 tris/cluster avg).
Done: clusters+quantisation errors (pos 7.6e-6 of part diag, normal 0.0243 deg), pipeline works, correctness 8M on 3080 OK
(0 false culls; hide first-frame OK), shade check vs CPU (max err 0.57/255), HZB exact vs numpy (all 12 levels).
Timestamp period: NVIDIA 1.0 ns, Intel 52.083 ns (19.2 MHz) - verified by wall/ts ratio.
Next: run correct+measure for 25M/100M/250M on both adapters, write final report (<=40 lines).
Open: p2 survivors high in moved views (sphere bounds loose); cold frame cost at 250M on UHD.
## Status update (final results collected)
All runs done: meas_/corr_{25M,100M,250M}_{3080,uhd}.jsonl, diag250*.jsonl, exp64/exp32 (smaller clusters), lowres_250_uhd.jsonl. Tables: python S/spikes/cull/tab.py <file>; ctab.py for correctness.
Correctness: 0 false-cull pixels in every case (3 views x cold/moved/hide20/hide50/show, 3 sizes, 2 adapters); id mismatches are depth ties only (<=22 px).
Findings: p2 (HZB survivors) = 4-9x truly visible clusters, contribute 0 pixels in static view; dominates frame time. UHD is vertex/setup-bound (same ms at 1280x800).
Smaller max-tris clusters (64) cut frame 22-27% (less degenerate lanes). Backface culling off changes 1.4-2.4% of fg pixels (open sheets) -> cone culling not legal as-is.
Only remaining: write the <=40 line reply.
