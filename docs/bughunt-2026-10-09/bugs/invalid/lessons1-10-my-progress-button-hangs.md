# My progress button hangs the app (Lessons workspace)

- **Severity:** hang
- **Reproduce (confirmed in 2 runs: lessons1-09 and lessons1-10):**
  `./aerun lessons1-10 "action:lessons;wait:1200;press:My progress;wait:1800;dump:l10_myprog"`
- **Expected:** "My progress" opens the progress view (or dialog) and the harness can continue (dump works).
- **Actual:** App stops responding. Harness reports `HANG: script did not finish within 74s`. No dump file is written, so the app never reaches the post-click step. Same behaviour in the longer run lessons1-09 (100 s timeout).
- **Traceback:** none. Stack sample at `runs/lessons1-10/hang_sample.txt` shows the main thread inside the Qt event loop, in a Python slot invoked via the Qt metacall path (PySide6 `callPythonMetaMethod`), with the harness mouse event (`QTest::mouseEvent`) pending. The app's own Python frames are not visible in the sample.
- **Evidence:** `runs/lessons1-10/report.txt`, `runs/lessons1-10/hang_sample.txt`, `runs/lessons1-09/hang_sample.txt`.
- **Note:** "My notes" also hung in run lessons1-11 (see the separate report). "Continue Where You Last Left Off" works (lessons1-12).
