# Toolbar "Reset" leaves "Show only this layer" checked (View tab)

**Severity:** ux

**Reproduce (confirmed in runs viewtab1-05 and viewtab1-06):**
```
./aerun viewtab1-06 "action:toggle_panels;wait:800;press:View;wait:1200;press:Show only this layer;wait:800;press:Reset;wait:1200;dump:f02_reset_after_layer"
```

**Expected:** "Reset" in the View tab toolbar returns things to their default state, or the label makes clear it only resets the camera.

**Actual:** after "Reset", "Show only this layer" is still checked. The layer filter is only cleared by "Show all" (runs/viewtab1-05/e08_showall_clip.txt shows it unchecked) or by "Reset dissection" (runs/viewtab1-03/c15_reset_diss.txt).

**Evidence:**
- runs/viewtab1-06/f02_reset_after_layer.txt (Show only checked after Reset)
- runs/viewtab1-05/e07_press_reset.txt

Suggested feature: either clear the layer filter on Reset, or add a tooltip saying Reset only resets the camera and pointing to Show all / Reset dissection.
