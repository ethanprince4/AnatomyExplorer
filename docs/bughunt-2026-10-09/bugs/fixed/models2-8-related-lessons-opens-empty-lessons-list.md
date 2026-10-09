# 3D Models viewer: "Related lessons (2)" opens the Lessons page with no lessons listed

- Agent / run: models2 (run models2-8)
- Severity: functional (empty panel that should have content)
- Workspace: 3D Models -> model viewer -> Lessons

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun models2-8 "press:3D Models;wait:1200;wclick:0.204,0.294;press:Open model;wait:3500;press:Related lessons;wait:1500;dump:k3"
```
(Run once as part of models2-8; the model's button read "Related lessons (2)" before the press.)

## Expected
The Lessons page shows the 2 lessons related to the open structure (or the related-lessons filter is applied to the list).

## Actual
The app switches to the Lessons workspace (Lessons checked, Back enabled). The "Lesson library" list reports rows=120 but shows only one row: "No lessons match these filters. Clear the search or choose A...". The "Lab" category chip is checked and "All progress" is selected. No related lesson is visible. Escape does nothing here.
Possible cause to check: the "Lab" chip is on, which may hide the related lessons, but the related-lesson link did not carry any filter to the user.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-8/k1.txt (viewer shows "Related lessons (2)")
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-8/k3.txt (Lessons page, "No lessons match these filters")
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models2-8/k3s.json
