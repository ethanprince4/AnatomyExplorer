# Clicking to the right of the "Skeletal system" checkbox label does not toggle it

- **Severity:** functional (low)
- **Area:** Explore workspace, Anatomy tree "Systems" panel, system checkboxes

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun tree1-07 "action:toggle_panels;wait:1200;wclick:0.161,0.520;wait:1200;dump:x1;wclick:0.12,0.520;wait:1200;dump:x2"
```
Re-run confirmed the same result (tree1-04, tree1-06, tree1-07).

## Expected
Clicking the checkbox row (label area or the empty part of the checkbox widget) toggles the system on/off.

## Actual
- Click at FX 0.161 (the centre of the QCheckBox widget as listed in the dump, just right of the text "Skeletal system"): state stays `checked`, nothing changes.
- Click at FX 0.12 (on the label text) and at the box (FX 0.07): state toggles.
- Using `press:Skeletal system` (which clicks the same 0.161 centre) also does nothing, so a dump-driven press on this checkbox never toggles it.

## Evidence
- runs/tree1-07/g2.txt, g3.txt (checked, unchanged after click at 0.161), g4.txt (unchecked after click at 0.12)
- runs/tree1-06/f5.txt -> f6.txt -> f7.txt (label clicks toggle)
- runs/tree1-04/c0.txt, c1.txt, c2.txt (two press:Skeletal system, still checked)
- runs/tree1-05/e1.txt (press, still checked), e2.txt (wclick at box: unchecked)
