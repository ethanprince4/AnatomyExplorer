# Clicking the active "Radiology" tab while on the case list jumps to Explore and shows the last opened case

- **Severity:** functional (wrong workspace / wrong state after Browse cases)
- **Reproduce (confirmed in runs radio1-11 and radio1-12):**
  ```
  ./aerun radio1-12 "press:Radiology;wait:1200;press:Abdomen;wait:500;press:CT kidneys — bilateral renal calculi, coronal;wait:300;press:Open selected case;wait:2500;press:Browse cases;wait:1200;press:Radiology;wait:1200;dump:r12_radpress"
  ```
- **Steps:** open a case from the Radiology list, press "Browse cases" (back on the Radiology list, "Radiology" button checked), then press the "Radiology" button again.
- **Expected:** stay on the Radiology case library (the button is already active).
- **Actual:** the workspace switches to Explore ("Explore" checked, "Radiology" unchecked) and the viewer for the previously opened case ("Browse cases", "Details", "Close" buttons) is shown.
- **Evidence:** `runs/radio1-12/r12_list.txt` (Radiology checked, list shown), `runs/radio1-12/r12_radpress.txt` (Explore checked, viewer shown); also `runs/radio1-11/r11_rad.txt`.
- **Traceback:** none.
