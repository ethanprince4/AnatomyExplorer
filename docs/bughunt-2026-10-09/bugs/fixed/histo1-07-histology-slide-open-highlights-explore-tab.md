# Opening a histology slide highlights the "Explore" nav tab instead of "Histology"

- Severity: functional (wrong state after navigation)
- Workspace: Histology (HistologyViewer opened from the Histology browser)

## Reproduce
```
./aerun <RUN_ID> "action:histology_tab;wait:1500;press:Search tissues;wait:300;type:heart;key:return;wait:1500;wdclick:0.25,0.335;wait:2000;state:h1-7;dump:h1-7;quit"
```
Confirmed in runs histo1-06 and histo1-07.

## Expected
Histology tab stays checked while a histology slide is open in HistologyViewer.

## Actual
State reports `center_widget: HistologyViewer`, but the top nav shows `Explore` checked and `Histology` unchecked. The viewer is in the Histology workspace, so the highlight is wrong.

## Evidence
- runs/histo1-07/h1-7.txt (dump after opening slide: Explore checked, Histology unchecked)
- runs/histo1-07/h1-7.json (center_widget HistologyViewer)
- runs/histo1-06/h1-6a.txt (same state, earlier run)
