# 3D Models viewer: "More controls" panel repeats Cut-away and Separate layers controls already shown in the panel

- Agent / run: models2 (run models2-6, screenshot g5.jpg)
- Severity: visual (redundant/confusing controls in the same Reveal panel; possibly unintended)
- Workspace: 3D Models -> model viewer -> Reveal panel

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun models2-6 "press:3D Models;wait:1200;wclick:0.204,0.294;press:Open model;wait:3500;press:More controls;wait:900;shot:g5"
```

## Expected
Each control appears once in the Reveal panel, or the expanded section shows only the additional controls.

## Actual
With the top-level Reveal panel visible, "More controls" expands a section that repeats the same controls: a second "Cut-away" checkbox (top row already has one) and a second "Separate layers" slider (top row already has one). The expanded section also adds "Labels", "Section", "X-ray others", "Isolate", "Show all", "Reset view", "Display", "Related" buttons. The duplicated checkbox and slider sit a few lines apart in the same panel.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-6/g5.jpg (screenshot: two "Cut-away" checkboxes and two "Separate layers" sliders in the Reveal panel)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-5/e1.txt (before More controls: one Cut-away, one Separate layers)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-5/e3.txt (after More controls: duplicates listed)
