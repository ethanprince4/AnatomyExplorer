# Viewport left as a thin midline sliver after a chain of visibility/clip/label actions; Reset and Show all do not restore the body

**Severity:** functional (wrong state after Reset / Show all)
**Agent:** vis1 (run vis1-01, confirmed by identical re-run vis1-07)

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun vis1-07 "search:biceps;activate;wait:3000;action:hide;wait:800;action:undo;wait:800;action:isolate;wait:800;action:show_all;wait:800;action:xray;action:xray;action:both_sides;action:default_visibility;action:undo;action:peel_in;action:peel_in;action:peel_out;action:peel_reset;action:color_mode;action:color_mode;action:color_mode;action:color_mode;action:clip_sagittal;action:clip_coronal;action:clip_transverse;action:landmarks;action:structure_labels;action:measure;action:measure;action:landmarks;action:structure_labels;wait:1000;action:reset_view;action:show_all;action:undo;wait:800;press:Show all;wait:800;press:Reset;wait:800;shot:vis1-07-end;quit"
```

## Expected
After "Reset", "Show all" and "reset_view", the full body model is shown at normal size and framing, with no clipping, and the label overlay matches the toggle state (two structure_labels and two landmarks toggles should leave both off).

## Actual
The 3D viewport shows only a narrow vertical strip near the body midline (about 1/8 of the window width). Structure labels for spinal cord / brain / cranial structures are still drawn along it, even though structure_labels and landmarks were each toggled twice. Nothing in the UI indicates that clip planes are still active. The bottom bar still reads "Measure distances" (unchecked) after two measure toggles, while a fresh session shows "Measure". The strip reproduces identically in both runs.

Hypothesis (not confirmed): the clip_sagittal/coronal/transverse planes are not cleared by Reset / Show all, which would leave only a thin slice of the model visible. Not yet isolated to a minimal command.

## Evidence
- runs/vis1-01/vis1-01-end.jpg (first run)
- runs/vis1-07/vis1-07-end.jpg (identical re-run)
- runs/vis1-07/report.txt
- For comparison, a fresh biceps hide shows the full body: runs/vis1-03/vis1-03-b.jpg

## Update from vis2 (bisect): minimal repro found
Agent: vis2. Bisected the chain with one fresh app per chain (each followed by press:Reset, then a screenshot).

Minimal repro (reproduces the sliver, screenshot runs/vis2-01/vis2-1-after-reset.jpg):
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun vis2-01 "search:biceps;activate;wait:3000;action:clip_sagittal;wait:800;press:Reset;wait:1500;shot:vis2-1-after-reset;quit"
```
The viewport shows only the thin midline strip with spinal cord / brain / cranial labels, the same as in vis1-01. So the sagittal clip plane survives Reset. This confirms the hypothesis above for the sagittal plane only.

Chains that do NOT reproduce it (each followed by press:Reset, full body or expected state shown):
- `action:clip_coronal;press:Reset` -> full body visible (runs/vis2-02/vis2-2-after-reset.jpg). Not the cause.
- `action:peel_in` x3 `;press:Reset` -> full body visible, no peel left (runs/vis2-03/vis2-3-after-reset.jpg). Not the cause.
- `action:isolate;press:Reset` -> only the two biceps remain (runs/vis2-04/vis2-4-after-reset.jpg). Reset does not clear isolate; this is probably by design (Reset is a view reset, Show all restores visibility), so it is not reported as a bug on its own.

Not yet checked: whether press:Show all clears the sagittal clip after Reset (run runs/vis2-06 took the screenshot, not inspected). Next probe: `clip_sagittal;press:Reset;press:Show all` and then `action:clip_sagittal` again to see if the toggle state is still on.
Evidence: runs/vis2-01/vis2-1-after-reset.jpg, runs/vis2-01/report.txt, runs/vis2-06/vis2-6-after-showall.jpg (unreviewed).

> Coordinator triage: Reset is documented as camera-only ('Reset the camera view') and Show all as visibility-only, so an active sagittal cross-section survives both and is seen edge-on from the anterior home view as a thin labelled slab. Working as designed; possible UX improvement: Reset (or the home view) could face the active section plane, or Show all could mention that a section is still on.
