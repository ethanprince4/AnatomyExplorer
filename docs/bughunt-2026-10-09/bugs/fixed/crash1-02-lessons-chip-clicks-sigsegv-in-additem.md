# CRASH (SIGSEGV) in Lessons library while chip clicks rebuild the list (intermittent, 1 of 2 runs)

**Severity:** crash
**Reproduced:** 1 of 2 runs with the exact command below. The first run crashed with exit -11. The confirmation re-run (crash1-04) exited 0. Two further stress runs (crash1-05, crash1-06) did not crash.

## Reproduce (original failing command, run crash1-02)
```
./aerun crash1-02 "action:lessons;wait:1200;dump:les1;<LOOP x5>;<KEYBOARD x2>;<EXPLORE x2>;dump:after;quit"
```
Where, in the failing run:
- LOOP = `press:Search lessons;type:zzz;wait:150;key:ctrl+a;key:backspace;wait:150;press:Lecture;wait:150;press:Lab;wait:150;press:System;wait:150;press:Region;wait:150;press:Level;wait:150;press:Lab;wait:150;combo:All progress=Finished;wait:150;combo:Finished=All progress;wait:150;press:Lab;wait:150;press:System;wait:150;type:zz;wait:120;key:backspace;wait:120;key:backspace;wait:120;type:lab;wait:150;key:ctrl+a;key:backspace;wait:150;press:Level;wait:150;press:Lecture;wait:150;press:Lecture;wait:150;`
- KEYBOARD = `settings:3;wait:1000;press:Keyboard;wait:600;press:Filter commands;type:zzz;...` (filter typed and cleared)
- EXPLORE = `esc;wait:600;action:explore;...;combo:All content=Structures;...`

The helper log stops after `press: ok 'Lab' -> QPushButton`, so the crash happened on the next chip click (Lab, System or the toggle right after it), during the first pass through the loop.

A shorter attempt (crash1-03: Lecture, Lab, System, Region, Level, Lab with the search cleared first) exited 0, so the minimal trigger is not known yet.

## Expected
Clicking a Lab/Lecture/System/Region/Level chip rebuilds the lesson list without crashing, however fast the clicks come.

## Actual
`EXC_BAD_ACCESS / SIGSEGV, KERN_INVALID_ADDRESS at 0x0`. Crash report: `~/Library/Logs/DiagnosticReports/AnatomyExplorer-2026-10-09-071640.ips`

Faulting stack (main thread, abridged):
```
QAccessible::updateAccessibility(QAccessibleEvent*)
QAbstractItemModel::endInsertRows()
Sbk_QListWidgetFunc_addItem(_object*, _object*)
PySide::CallbackDynamicSlot::call / callPythonMetaMethod   (Python slot triggered by a chip click)
QAbstractButton::mouseReleaseEvent
Sbk_QTestFunc_mouseClick
```
This is the same family as the earlier fixed crash (`bugs/fixed/details1-01-crash-during-aorta-search-after-sequence.md`). Here a QListWidget gets `addItem` calls while it is on screen and the accessibility layer is active. The chip-triggered rebuild is the trigger.

## Related warning in the same session
The re-run (crash1-04) wrote about 100 lines of stderr, including `Called accessibilityLabel on invalid object: 2147483704`. This matches the existing `bugs/storm1-08-cardlist-invalid-accessibility-index-warning.md`, now seen on the Lessons list.

## Evidence
- `runs/crash1-02/` (report.txt, helper.log, les1.txt)
- `runs/crash1-04/` (report.txt, stderr with the accessibility warnings)
- Crash report `AnatomyExplorer-2026-10-09-071640.ips`
