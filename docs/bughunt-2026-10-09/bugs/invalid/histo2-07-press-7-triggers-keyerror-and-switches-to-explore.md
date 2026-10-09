# Clicking the "7" control in the Histology viewer raises KeyError 'explore' and switches to Explore

- Severity: error (Python traceback) with wrong navigation
- Workspace: Histology viewer opened from a heart search

## Reproduce
```
./aerun <RUN_ID> "press:Histology;wait:1500;press:Search tissues;wait:300;type:heart;key:return;wait:1500;wdclick:0.25,0.335;wait:2500;press:Next;wait:1000;press:Next;wait:1200;dump:a;press:7;wait:1500;dump:b"
```
Reproduced in histo2-07 (first seen in histo2-04). The same steps without `press:7` (histo2-05, histo2-08) show no traceback.

## Expected
Pressing "7" does nothing in the Histology viewer, or it selects slide 7. No traceback is logged.

## Actual
The Histology viewer is replaced by the Explore 3D workspace (Explore checked, Histology unchecked). The traceback is:
```
File ".../Frameworks/app/main_window.py", line 3176, in _run_script
    self.cmds.actions[arg].trigger()
KeyError: 'explore'
```
No `action:explore` was sent in the run. The harness log shows only `press: ok '7' -> QPushButton (click)`. The selected thumbnail is still reachable with a real click on the thumbnail row (histo2-05 selected slide 7 correctly), so the reachable bug is the traceback and the navigation, not the thumbnail.

Caveat: "7" is not in the dump as a QPushButton, so the harness may be matching a hidden control. Check whether the app has a hidden "7" button or a number-key shortcut that dispatches action ids.

## Evidence
- runs/histo2-07/errors_new.txt (traceback)
- runs/histo2-07/h2-07a.txt (before: Histology checked)
- runs/histo2-07/h2-07b.txt (after: Explore checked)
- runs/histo2-04/errors_new.txt (first occurrence)
