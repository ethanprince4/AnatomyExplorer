# 3D Models: "Saved views" menu cannot be closed with Escape after typing in the model search field

- Agent / run: models1 (runs models1-05, models1-06)
- Severity: functional (popup cannot be closed; main window is blocked until the menu is dismissed some other way)
- Workspace: 3D Models

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun models1-06 "press:3D Models;wait:1500;press:Find a model;wait:300;type:heart;wait:1000;press:Saved views;wait:800;dump:t6a;key:escape;wait:800;dump:t6b;press:Find a model;wait:300;press:Saved views;wait:800;key:escape;wait:800;dump:t6c;key:escape;wait:500;key:escape;wait:500;dump:t6d"
```
Reproduced in models1-05 (same steps, dumps q5b/q5d/q5f) and models1-06.

## Expected
Escape closes the "Saved views" QMenu (as it does when no search text has been typed; see runs/models1-04 r4b -> r4c).

## Actual
After "heart" is typed into the "Find a model or linked structure" field, opening "Saved views" shows a QMenu
(`root=QMenu 'Saved &views'`). Escape is delivered to the SearchLine (helper log: `key: escape -> SearchLine`) and the
menu stays open. Every later dump (t6b, t6c, t6d) still shows only the open QMenu, and the main window
widgets (including "Find a model" and "Saved views") are no longer reachable; four escapes did not close it.

Not reproduced (for contrast): with no search text, press:Saved views then key:escape closes the menu normally
(runs/models1-04 and models1-07).

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models1-06/t6a.txt (menu open after typing)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models1-06/t6b.txt (menu still open after Escape)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models1-06/t6d.txt (still open after 4 escapes total)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models1-05/q5b.txt, q5d.txt
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/models1-06/helper.log
