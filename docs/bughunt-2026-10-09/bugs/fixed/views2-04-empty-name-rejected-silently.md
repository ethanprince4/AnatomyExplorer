# Empty view name is rejected silently on save and on rename

- Severity: ux (action has no feedback)
- Area: Saved views > Save current view, Saved views > Manage > Rename…

## Reproduce
Save:
```
./aerun views2-04 "wait:1500;search:femur;activate;wait:1500;press:Saved views;wait:1200;press:Save current view;wait:1200;key:return;wait:1500;dump:v_empty"
```
Rename:
```
./aerun views2-04 "wait:1500;search:femur;activate;wait:1500;press:Saved views;wait:1200;press:Manage saved views;wait:1200;press:Cam C;wait:600;press:Rename;wait:1000;key:ctrl+a;key:backspace;key:return;wait:1200;dump:rn_empty"
```

## What happened
- Save with an empty name: the dialog closes, no view is added (the menu shows no new entry), and no message explains why.
- Rename to an empty name: the rename prompt closes, "Cam C" keeps its old name, and no message appears.

The user is left guessing whether the save or rename worked.

## Expected
An inline message or disabled OK button while the name field is empty (for example "Enter a name for this view"), so the user knows why nothing changed.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-04/v_empty.txt
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-04/rn_empty.txt (Manage list still shows Cam C, no message)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-04/v_menu.txt (no new empty entry)

Suggested feature: disable OK on an empty name, or show a validation message under the name field.
