# Double-clicking a case row in the Radiology list does not open the case

- **Severity:** functional
- **Reproduce (seen in radio1-05, radio1-06, radio1-11):**
  ```
  ./aerun radio1-06 "press:Radiology;wait:800;press:Abdomen;wait:500;dpress:CT abdomen — axial, liver and spleen;wait:2500;dump:r6_dclick"
  ```
- **Expected:** per the app's own convention, double-clicking a row opens the selected case in the viewer.
- **Actual:** the list stays on the Radiology case library; no viewer appears. The row is selected (the "Open selected case" button is enabled), and the case only opens after pressing "Open selected case" (or Enter then that button).
- **Caveat:** the harness reports the dclick as ok, so it is possible the synthetic double-click does not trigger the app's activation path. Verify by hand with a real double-click before fixing.
- **Evidence:** `runs/radio1-06/r6_dclick.txt`, `runs/radio1-11/r11_dc.txt`, `runs/radio1-05/r5_v1.txt`.
- **Traceback:** none.
