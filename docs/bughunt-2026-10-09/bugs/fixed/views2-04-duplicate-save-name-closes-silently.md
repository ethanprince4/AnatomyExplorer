# Saving a view with a duplicate name closes the dialog with no feedback

- Severity: ux (no error shown, unclear result)
- Area: Saved views > Save current view

## Reproduce
```
./aerun views2-04 "wait:1500;search:femur;activate;wait:1500;press:Saved views;wait:1200;press:Save current view;wait:1200;type:Femur;key:return;wait:1500;dump:v_dup"
```
(Requires an existing saved view named "Femur", which is present in the shared data.)

## What happened
Typing a name that already exists and pressing Return closes the save dialog. No message box, no inline error, nothing in the dump. The Saved views menu afterwards still shows a single "Femur" entry, so the user cannot tell whether the save was rejected, ignored, or overwrote the existing view.

Contrast: renaming a view to an existing name ("Rename…" to "Femur") shows the message box "A saved view with that name already exists. Choose another name." (run views2-06, r6_msg.txt). The save path gives no equivalent message.

## Expected
Same duplicate-name message as rename, or an explicit overwrite confirmation ("Replace existing view 'Femur'?").

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-04/v_dup.txt (main window only, no dialog)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-04/v_menu.txt (single Femur entry after the save)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/views2-06/r6_msg.txt (rename duplicate does show a message)

Suggested feature: a duplicate-name message on Save (with an option to replace the existing view), matching the rename dialog.
