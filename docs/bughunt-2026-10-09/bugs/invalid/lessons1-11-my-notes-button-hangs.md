# My notes button appears to hang the app (Lessons workspace)

- **Severity:** hang (observed once; not re-run, since the run budget was used up)
- **Reproduce:** `./aerun lessons1-11 "action:lessons;wait:1200;press:My notes;wait:1500;dump:l11_notes;key:escape;wait:800;dump:l11_notes_esc;press:Continue Where You Last Left Off;wait:2000;dump:l11_cont"`
- **Expected:** "My notes" opens the notes view or dialog; Escape closes it; the following steps run.
- **Actual:** `HANG: script did not finish within 86s`. The dump after "My notes" was never written, so the harness stalled at or right after the click. The same happens with "My progress" (see lessons1-10-my-progress-button-hangs.md), which suggests a shared problem with the bottom-bar buttons when a dialog or panel opens.
- **Traceback:** none. Stack sample: `runs/lessons1-11/hang_sample.txt`.
- **Evidence:** `runs/lessons1-11/report.txt`, `runs/lessons1-11/hang_sample.txt`.
