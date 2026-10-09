# Export figure from Histology opens a modal save dialog that blocks the app and cannot be dismissed by the harness (HANG)

- Severity: hang
- Note: the first failing run was histo1-01 (hang at `action:export_figure`, followed by quit). The minimal reproduction is histo1-02.

## Reproduce
```
./aerun <RUN_ID> "action:histology_tab;wait:1500;action:export_figure;wait:1500;dump:h1-dlg;key:escape;wait:800;state:h1-dlg-after;quit"
```
Reproduced twice (histo1-01 and histo1-02), exit status 3 (HANG) both times.

## Expected
Export figure opens a save dialog that can be dismissed with Escape or Cancel, and the app keeps responding (dump and state work while it is open).

## Actual
The main thread sits in `QFileDialog::getSaveFileName` (via a Python slot on export_figure). The `dump:` step never runs, so the harness cannot read the dialog and Escape is never delivered to it. The script times out at about 81 to 162 s and the app is killed.

## Traceback / evidence
No Python traceback. The sample shows the main thread in `QFileDialog::getSaveFileName`:
- runs/histo1-02/hang_sample.txt
- runs/histo1-01/hang_sample.txt
- runs/histo1-01/helper.log (last helper line is key:escape sent to MainWindow)

Unverified: whether Escape should dismiss this dialog in a real session (the harness may simply not deliver keys to a native sheet). Worth checking manually whether Export figure's save panel can be cancelled.
