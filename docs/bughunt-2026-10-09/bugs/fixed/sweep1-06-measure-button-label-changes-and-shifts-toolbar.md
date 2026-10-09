# Bottom toolbar "Measure" label changes between "Measure" and "Measure distances" and shifts neighbouring buttons

- Severity: visual (low)
- Workspace: Explore, bottom toolbar (Measure / Show all / Reset / More tools)

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun sweep1-06 "wait:1500;dump:a1;action:radiology;wait:1500;dump:a2;action:back;wait:1200;dump:a3"
```
Not re-run as written. The label change was seen in sweep1-01, sweep1-02 and sweep1-04 (see evidence below). The command above is the intended minimal repro, so re-run it to confirm.

## Expected
The same control has the same name in the same workspace. Its accessible name should not change depending on navigation history, and the toolbar should not move.

## Actual
- Fresh start on Explore: the button is named "Measure" at @0.407,0.943 and "Show all" is at @0.471.
- Explore after navigating (Explore reached via Back from Lessons, or after the quiz): the same button is named "Measure distances" and sits at @0.407, while "Show all" moves to @0.492 and "Reset" to @0.549.
- Radiology: "Measure distances" at @0.616, "Show all" at @0.701, "Reset" at @0.758, "More tools" at @0.820.

So the bar's buttons shift position whenever the label switches. Anyone who learned the layout will click the wrong button. The label is not stable on the same screen.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-04/u1.txt (Explore, "Measure" @0.407)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-04/u12.txt (Explore after quiz, "Measure distances" @0.407)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-01/j14.txt (Explore with quiz panel open: "Measure distances" @0.407, "Show all" @0.492)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-02/s2_g.txt (Explore after Back, "Measure distances")
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-04/u6.txt (Radiology, "Measure distances" @0.616)

No traceback.
