# Save screenshot writes a .jpg file when the user types a .png name

- Severity: ux (unverified whether intended; not re-run to confirm)
- Found in: notes1-07 (single run; budget did not allow a clean re-run)

## Reproduce
```
./aerun notes1-07 "search:femur;activate;wait:2500;press:Settings and application commands;wait:800;press:Study;wait:800;press:Edit note for selection;wait:1200;key:ctrl+a;type:Long femur note with symbols & unicode: αβγ 日本語 🦴 and a fairly long tail of words to see how the list row truncates in the My notes dialog;press:Save note;wait:1000;press:Settings and application commands;wait:800;press:Study;wait:800;press:All my notes…;wait:1500;dump:n7_notes;key:escape;wait:600;press:Settings and application commands;wait:800;press:Tools;wait:800;press:Save screenshot;wait:1500;dump:n7_shotdlg;type:/Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/notes1-07/femur_shot_a.png;key:return;wait:2000;dump:n7_after_shot"
```

## Expected
The file is saved with the name the user typed (femur_shot_a.png), or the dialog's filter/format is set to JPEG
before the user types, so the extension matches what is written.

## Actual
The file on disk is `femur_shot_a.jpg` (JPEG data, 1100x633). No `.png` file was written. The save dialog's
filename field showed the typed `.png` path, and the completer popup was still open after Return.

## Evidence
- runs/notes1-07/femur_shot_a.jpg (`file` reports JPEG image data)
- runs/notes1-07/n7_shotdlg.txt (dialog before typing)
- runs/notes1-07/helper.log

## Notes
- Also observed: after typing a path and pressing Return, the filename field's completer popup stays open and
  the dialog needs a second Escape or Return. Probably normal Qt behaviour, not filed.
