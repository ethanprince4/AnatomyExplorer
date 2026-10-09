# "Teaching view" tab is not visible in the case viewer (only "Scan" shows)

- **Severity:** visual
- **Reproduce:**
  ```
  ./aerun radio1-06 "press:Radiology;wait:800;press:Abdomen;wait:500;dpress:CT abdomen — axial, liver and spleen;wait:2500;press:Open selected case;wait:2500;shot:r6_teach"
  ```
- **Expected:** the image-area tab bar shows two tabs, "Scan" and "Teaching view", as the widget tree reports (`tabs=Scan|Teaching view`).
- **Actual:** the screenshot shows only a "Scan" tab with its underline; no "Teaching view" tab is drawn at the left of the image panel, so the second mode is not discoverable (or is clipped). I did not verify by screenshot whether clicking the tab area (wclick:0.12,0.232) switches modes.
- **Evidence:** `runs/radio1-06/r6_teach.jpg` (image panel top-left), `runs/radio1-06/r6_teach.txt`.
- **Traceback:** none.
