# Escape does not leave Measure mode (View tab)

**Severity:** functional

**Reproduce (confirmed in runs viewtab1-03, -05, -06):**
```
./aerun viewtab1-06 "action:toggle_panels;wait:800;press:View;wait:1200;action:measure;wait:800;action:escape;wait:1000;dump:f01_after_escape"
```

**Expected:** after Measure is turned on and Escape is pressed, Measure leaves measure mode and the "Measure distances" toolbar button returns to unchecked.

**Actual:** the "Measure distances" toolbar button stays checked after `action:escape`. The button only turns off when pressed again (`press:Measure distances`), which works.

**Evidence:**
- runs/viewtab1-06/f01_after_escape.txt (Measure distances checked)
- runs/viewtab1-05/e02_measure.txt vs e03_after_esc.txt (still checked after escape)
- runs/viewtab1-03/c11_measure.txt vs c12_after_esc.txt
- runs/viewtab1-05/e04_measure_toggle_off.txt (toggling off by press works)

No traceback. Note: the two measure clicks in viewtab1-04 (runs/viewtab1-04/d03_measure.jpg) did not show a visible distance line or label on the body, so measurement feedback itself is also unverified.
