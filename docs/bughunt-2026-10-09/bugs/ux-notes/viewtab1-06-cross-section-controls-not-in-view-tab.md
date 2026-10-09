# Cross-section controls are not in the View tab and clip actions show no state there

**Severity:** ux

**Reproduce:**
```
./aerun viewtab1-06 "action:toggle_panels;wait:800;press:View;wait:1200;dump:g01_view;action:clip_sagittal;wait:2000;dump:g02_after_clip;press:More tools;wait:800;dump:g03_more"
```

**Expected:** the View tab has the cross-section controls (clip checkboxes and their sliders) as the brief describes, or at least shows whether a cross-section is active. The Details text says "Cross-sections label themselves", so the feature is meant to be discoverable.

**Actual:** the View tab has no clip checkbox or slider. Cross-sections are only reachable through the "More tools" menu, which has a "Cross-sections" item (no sub-controls explored yet). After `action:clip_sagittal` the View tab dump is unchanged. The 3D view does change: the body is turned to a side view with many cross-section landmark labels stacked near the top of the body.

**Evidence:**
- runs/viewtab1-01/v01_view_tab.txt (no clip widgets in View tab)
- runs/viewtab1-04/d01_clip_s.txt and d01_clip_s_shot.jpg (sagittal cut shows labels in a dense column)
- runs/viewtab1-04/d02_more.txt (More tools menu lists "Cross-sections")

Suggested feature: add "Cross-sections" sagittal / coronal / transverse checkboxes with sliders to the View tab next to Dissection, with on/off state that matches action:clip_* and reset by Show all.
