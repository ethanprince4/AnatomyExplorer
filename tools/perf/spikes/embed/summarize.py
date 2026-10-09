"""Print a compact table from the bench_*.log files in a folder."""
import glob, json, sys, os
for f in sorted(glob.glob(os.path.join(sys.argv[1], "bench_*.log"))):
    for line in open(f):
        if line.startswith("RESULT "):
            d = json.loads(line[7:])
            print(os.path.basename(f)[6:-4], "dpr", d["dpr"], "sc", d["swapchain"], "log", d["widget_logical"], "mm", d["size_mismatch_frames"],
                  "fps", d["fps"], "int p50/p95/max", d["interval_ms_p50"], d["interval_ms_p95"], d["interval_ms_max"],
                  "acq", d["acquire_ms_p50"], "cb", d["draw_cb_ms_p50"], "jit idle", d["jitter_idle_ms"], "render", d["jitter_render_ms"],
                  "ticks/s", d["timer_ticks_per_s_render"], "px", d["grab_corner_rgb"])
