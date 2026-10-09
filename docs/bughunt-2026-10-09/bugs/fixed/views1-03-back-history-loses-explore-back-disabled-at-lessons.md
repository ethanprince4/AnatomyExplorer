# Back history never includes Explore: Back is disabled on Lessons and the 4th Back does nothing

- Severity: functional (wrong state after back)
- Agent: views1

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun views1-05 "wait:1500;press:Lessons;wait:1500;press:3D Models;wait:2500;press:Radiology;wait:1500;press:Histology;wait:1500;action:back;wait:1200;action:back;wait:1200;action:back;wait:1200;dump:p3_b3;action:back;wait:1200;dump:p4_b4"
```
Same result in views1-03 (same chain without the dropdown steps) and views1-04.

## Expected
Started on Explore, then visited Lessons, 3D Models, Radiology, Histology. Back x4 should go Radiology, 3D Models, Lessons, Explore. Back should be disabled only after Explore.

## Actual
- Back x1 -> Radiology (correct), Back x2 -> 3D Models (correct), Back x3 -> Lessons (correct).
- At Lessons the Back button is DISABLED (dump p3_b3.txt: `Back to the previous place ... DISABLED`), although the workspace is not at the start.
- Back x4 leaves the page on Lessons (p4_b4.txt). Explore is unreachable by Back.
- The Back dropdown (wclick:0.203,0.051 on the Back arrow) at Histology lists `Histology library` (checked), `Radiology library`, `3D models library`, `Lessons library`. There is no Explore entry at all (p0_dd.txt). Explore is the place the session starts on, so it should be the last entry.
- Forward/Back in the other direction works (Histology -> Radiology -> 3D -> Radiology -> Histology), so the problem is only the first entry.

## Evidence
- runs/views1-05/p0_dd.txt, p3_b3.txt, p3_dd.txt, p4_b4.txt
- runs/views1-03/r3_b5.txt, r3_b6.txt (Back DISABLED on Lessons after 4th back, page still Lessons)
- runs/views1-02/v2_ddmenu.txt (dropdown without Explore)
- runs/views1-03/r3_b6.txt: `QToolButton 'Back to the previous place' @0.192,0.051 DISABLED` on Lessons

No traceback.
