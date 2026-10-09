# 3D Models: Back after opening a model goes to the Explore 3D Anatomy view, skipping the 3D Models catalog

- Agent / run: models2 (reproduced in runs models2-4, models2-5, models2-6)
- Severity: functional (wrong state after back; the catalog the user came from is skipped on the first Back)
- Workspace: 3D Models -> Explore (model viewer)

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun models2-5 "press:3D Models;wait:1200;press:Find a model;type:heart;wait:1000;wclick:0.207,0.294;wait:600;press:Open model;wait:4000;action:back;wait:2500;state:x;dump:x"
```
(The same steps were run as the first part of models2-4 and models2-5/models2-6; the budget did not allow a separate re-run of this exact string. The Back/state part is identical to models2-5 and models2-6.)

## Expected
Back returns to the place the user came from: the 3D Models catalog (center widget CollectionWorkspace, Find a model field, 20 visible rows).

## Actual
Back lands on the Explore workspace showing the default full-body "3D Anatomy" view (center widget QSplitter, Explore checked, no catalog). Only a second Back reaches the 3D Models catalog. Forward then returns to the opened model (ModelView).
Inconsistent: in models2-7 (third model opened after two earlier open/back cycles) Back went straight to the catalog, so the skip seems to happen on the first open.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-5/e4.jpg (screenshot after Back: "3D Anatomy" full-body view, Explore checked)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-5/e4s.json (center 0, QSplitter)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-5/e6s.json (after second Back: center 1, CollectionWorkspace)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-6/g2.txt and g2s.json (same result after opening a different model)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-4/d4.txt (Back after open: Explore, no catalog)
