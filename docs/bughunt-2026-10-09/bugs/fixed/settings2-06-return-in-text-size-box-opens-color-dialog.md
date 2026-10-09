# Pressing Return in the Interface text size box opens a modal "Choose color" dialog

- **Severity:** functional
- **Area:** Settings > Display > Interface text size (value box)

## Reproduce
```
./aerun settings2-06 "settings:1;wait:800;press:1.00;key:return;wait:1200;state:x"
```
Reproduced in settings2-06 (fresh app), settings2-04 and settings2-05 (with `type:99` before the Return).
Note: `press:1.00` hits the first "1.00" box, which is Interface text size on the Display page.

## Expected
Return commits the typed value (or does nothing). No second window should appear.

## Actual
A modal `QColorDialog 'Choose color'` opens on top of Settings (state JSON: `"modal": "QColorDialog"`).
While it is open, later commands cannot reach the Settings pages (settings2-04: `settings:3` dump still shows the colour dialog).
The Return is apparently activating a default button or colour swatch in the Settings dialog. Not yet identified which control.

## Evidence
- runs/settings2-06/m6_min.json
- runs/settings2-05/m5_after_return.json
- runs/settings2-04/m4_textsize.txt (dump shows QColorDialog)
