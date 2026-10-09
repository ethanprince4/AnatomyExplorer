# Open view on a view saved from Explore does not switch back to Explore when run from Lessons

- Severity: functional (saved view restore leaves wrong workspace)
- Agent: views1

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun views1-08 "wait:1500;press:Explore;wait:1000;press:Saved views;wait:800;press:Save current view;wait:800;type:Cam C;key:return;wait:1000;press:Lessons;wait:1500;press:Saved views;wait:800;press:Manage saved views;wait:1200;press:Cam C;wait:400;press:Open view;wait:2000;state:u3_from_les"
```
Reproduced in views1-06 (view saved on Explore, opened from Lessons: Lessons canvas still shown in m2_after_open.txt) and views1-07 (t3_open.json).

## Expected
"Open view" restores the saved setup, which includes the workspace it was saved in (the Delete prompt calls it "the saved setup"). Opening a view saved on Explore while on Lessons should bring the Explore workspace back.

## Actual
The camera does get restored (views1-08 u1_changed.jpg is zoomed/rotated; u2_restored.jpg shows the default front view on Explore). But when opened from Lessons the app stays on Lessons: state JSON is `"center_widget":"CollectionWorkspace"` (Lessons) after Open view, and the Lessons tab is still checked. The Explore tab is not reselected.

## Notes
Confidence is medium: it is not 100% certain the saved view was meant to store the workspace, but the saved setup clearly includes view state and the brief expects restore after a workspace change. Check the spec before fixing.

## Evidence
- runs/views1-08/u2_explore.json, u3_from_les.json (center 0 QSplitter then center 1 CollectionWorkspace)
- runs/views1-08/u1_changed.jpg, u2_restored.jpg (camera restored correctly on Explore)
- runs/views1-06/m2_after_open.txt (Lessons canvas after Open view for a view saved on Explore)
- runs/views1-07/t3_open.json

No traceback.
