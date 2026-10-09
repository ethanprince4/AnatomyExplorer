# "Reset this page" on Settings > Behavior does not revert "Restore camera, visibility and selection on startup"

- **Severity:** functional
- **Area:** Settings dialog, Behavior tab, "Reset this page" button

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun settings1-08 "action:settings;wait:1200;settings:2;wait:800;press:Restore camera;wait:400;dump:r8_a;press:Reset this page;wait:800;dump:r8_b;press:Close;wait:800;action:settings;wait:1200;settings:2;wait:800;dump:r8_c;press:Close;wait:500;state:r8_end"
```
Reproduced in settings1-06 and settings1-08 (same result both times).

## Expected
Default for "Restore camera, visibility and selection on startup" is unchecked (it was unchecked on every fresh open before the test). After pressing "Reset this page" the checkbox should be unchecked again, and it should stay unchecked after Close and reopen.

## Actual
- Press "Restore camera" -> checkbox becomes checked (dump r8_a: checked).
- Press "Reset this page" -> checkbox still checked (dump r8_b: checked).
- Close, reopen Settings > Behavior -> still checked (dump r8_c: checked). The reset did not persist.

## Evidence
- runs/settings1-08/r8_a.txt, r8_b.txt, r8_c.txt, r8_end.json
- runs/settings1-06/r6_beh.txt (unchecked), r6_beh_reset.txt (still checked after Reset this page)
- Note: the same "Reset this page" correctly reset Display page values (Interface text size 1.50 -> 1.00, runs/settings1-06/r6_disp_reset.txt).
- The Restore camera checkbox was left checked by these tests (not restored, the harness cannot undo it cleanly).
