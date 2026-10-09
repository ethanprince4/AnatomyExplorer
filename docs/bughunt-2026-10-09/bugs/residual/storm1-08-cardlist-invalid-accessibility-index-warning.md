# CardList emits "Invalid index at: -76" accessibility warnings during lesson navigation

- Severity: error (stderr Qt warning; no visible symptom seen)
- Found in: storm1-04, storm1-05, storm1-08 (reproduced in storm1-08)
- Not reproduced in: storm1-03, storm1-06 (Lessons + quiz only), storm1-07 (search box typing only)

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun storm1-08 "press:Lessons;wait:1200;action:lessons;wait:100;action:quiz;wait:100;action:lessons;wait:100;action:quiz;wait:100;action:quiz;wait:100;action:lessons;wait:100;action:lessons;wait:100;press:Histology;wait:800;action:quiz;wait:100;press:Lessons;wait:800;action:lessons;wait:100;action:lessons;wait:100;action:back;wait:100;action:forward;wait:100;action:back;wait:100;action:back;wait:100;action:forward;wait:100;press:Radiology;wait:1000;action:quiz;wait:100;action:note;wait:100;action:lessons;wait:100;action:radiology;wait:100;action:radiology;wait:100;press:Explore;wait:800;action:escape;wait:100;action:escape;wait:100;action:quiz;wait:100;action:lessons;wait:100;press:Lessons;wait:800;dump:r8;state:r8"
```
Minimal repro not isolated. Shorter prefixes (Lessons + quiz toggles only, storm1-06; search typing only, storm1-07) did not trigger it. Run storm1-08 is the shortest reproducer found so far (the trigger is somewhere in the Histology/Radiology/back-forward part).

## Expected
No warnings on stderr. Lesson list accessibility queries should use valid row indexes.

## Actual
Run exits with status ok, but stderr contains:
```
QAccessibleList::child: Invalid index at: -76 0
qt.accessibility.core: Invalid child in QAccessibleEvent: CardList(0x...) child: -76
QCocoaAccessibility::notifyAccessibilityUpdate: invalid element
```
The warning is always about CardList with index -76. The on-screen state looked normal in the runs checked (dump and state show Lessons and no modal).

## Traceback / evidence
- No Python traceback for these runs.
- runs/storm1-08/stderr.txt (also runs/storm1-08/report.txt, runs/storm1-08/r8.txt, runs/storm1-08/r8.json)
- runs/storm1-04/stderr.txt, runs/storm1-05/stderr.txt (same three lines, longer sequences)
- runs/storm1-06/ and runs/storm1-07/ have no such stderr (negative results)

## Update from storm2 (bisect)
- storm2-01: exact storm1-08 command re-run once; warning reproduced (same three stderr lines, CardList child -76).
- storm2-02: first half of the storm1-08 command (Lessons/quiz/Histology/back/forward, ends before press:Radiology) did NOT print the warning.
- storm2-03: second half only (press:Radiology onward, ending with dump:h3) DID print it, on a fresh app.
- storm2-04: shorter minimal repro, still prints it:
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun storm2-04 "press:Radiology;wait:1000;action:quiz;wait:100;action:note;wait:100;action:lessons;wait:100;action:radiology;wait:100;action:radiology;wait:100;dump:h4"
```
  Evidence: runs/storm2-04/stderr.txt (report shows the three lines under OTHER STDERR).
- storm2-05 and storm2-06 (same as storm2-04 without the two action:radiology steps): the app hung at launch (macOS restore prompt, before any command ran; see final report), so the bisect result for those is inconclusive. Shortest confirmed repro is storm2-04.
