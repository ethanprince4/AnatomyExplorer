# Lesson steps do not highlight the structures they name in the 3D view

- Severity: ux
- Area: Lessons, step walk, 3D view (lesson "The root of the neck and the thoracic inlet", opened via search "brachial plexus" then Learn)

## Reproduce
```
./aerun <RUN_ID> "action:lessons;wait:1500;press:System;wait:1000;wclick:0.5,0.221;type:brachial plexus;key:return;wait:1500;press:Learn;wait:3000;press:Next;wait:2000;press:Next;wait:2000;shot:check"
```
(Run used: lessons3-05, which walked all 5 steps with state:/dump: after each Next.)

## What happened
- Step 3 "Branches of the subclavian artery" names the vertebral, internal thoracic, thyrocervical, costocervical and dorsal scapular arteries. The 3D view (runs/lessons3-05/l3_shot_a.jpg) shows a red/blue tube and a horizontal branch. Nothing is labelled or highlighted as a named branch, and the view does not indicate which structure the step is about.
- Step 5 "The apex of the lung and the sympathetic chain" names the lung apex, the sympathetic trunk, the stellate ganglion and the T1 root of the brachial plexus. The 3D view (runs/lessons3-05/l3_shot_b.jpg) shows both lungs in grey, unhighlighted, plus two cyan tubes running up beside the spine. Those tubes are not labelled and do not clearly correspond to any named structure in the step text.
- The camera and model do change per step (front-on lungs at step 5 vs. a different view at step 3), but no highlight or isolation is tied to the step's structures.

## Expected
Each lesson step that names a structure should show or highlight that structure in the 3D view, or offer a control to do so (for example a "Show this step's structures" action that uses isolate/highlight).

## Suggested feature
Per-step structure highlighting: the lesson step should carry the list of structures it names, and the 3D view should highlight or isolate them when the step is shown, with a label.

## Evidence
- runs/lessons3-05/l3_shot_a.jpg (step 3 of 5)
- runs/lessons3-05/l3_shot_b.jpg (step 5 of 5)
- runs/lessons3-05/l3_st1.json … l3_st5.json (state, no structure info)
- runs/lessons3-05/l3_d2.txt, l3_d5.txt (dumps, step widgets)

## Notes
Not confirmed as a functional bug: I could not verify from the screenshots which exact structures are drawn in cyan, so this is filed as ux only.
