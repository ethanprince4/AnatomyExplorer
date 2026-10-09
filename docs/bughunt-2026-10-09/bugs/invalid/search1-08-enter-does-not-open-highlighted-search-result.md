# Search: Enter / Down do not open the highlighted result in the top search

- Severity: functional
- Area: global search box ("Search anatomy") and its results panel

## Reproduce
```
./aerun search1-08 "wclick:0.766,0.051;key:ctrl+a;type:femur;wait:800;key:return;wait:1500;key:down;key:return;wait:3000;dump:x;shot:x"
```
(Confirmed in a single run, search1-08. Not re-run because the budget was used up.)

## Expected
The results panel says "29 results · Enter to open". Pressing Return (after Down to move the highlight) should open the highlighted result, here the "Femur" Structure row.

## Actual
The panel stays open on the Systems/search view. The "Femur" row stays highlighted, the 3D view stays on Explore with no structure selected, and the Explore tab stays checked. Pressing Return in the search box again did nothing either. Mouse clicks on rows do work (a click on the "Femur, tibia and fibula" lesson row opened the lesson), so only the keyboard path is broken. The same thing happened for "carpal tunnel" in search1-02 and search1-03 (Down + Return left the panel open).

## Evidence
- runs/search1-08/f_struct.txt and f_struct.json (center 0, Explore checked)
- runs/search1-08/f_struct_main.jpg (panel open, Femur row highlighted, no structure opened)
- runs/search1-05/r5_femur_main.jpg (Enter after typing shows the results panel)
- runs/search1-02/a_femur_after.txt
