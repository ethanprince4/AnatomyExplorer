import sys, json
for f in sys.argv[1:]:
    for line in open(f):
        if line.startswith("RESULT "):
            d = json.loads(line[7:])
            print(f.split("/")[-1], d["method"], d["overlay"], d["when"], "card", d["card"]["match_qt_render"], "/", d["card"]["samples"], "labels", [l["ok"] for l in d["labels"]],
                  "scan", d["viewport_scan"], "ctr", d["frame_counter_samples"][:1], "->", d["corner_after"][1], "frames", d.get("frames_before_reparent"), d["last_frame"],
                  "sc", d["swapchain"], d["canvas_phys"], "mm", d["size_mismatch_frames"], "native", {k: v["native_attr"] for k, v in d["native"].items()}, "winid", d.get("winid_at_first_show"), d.get("winid_now"))
            break
    else:
        print(f, "NO RESULT", open(f).read()[-300:])
