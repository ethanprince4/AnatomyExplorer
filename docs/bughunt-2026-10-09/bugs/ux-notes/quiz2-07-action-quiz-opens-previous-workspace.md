# action:quiz opens the wrong workspace (previous place in history) instead of the quiz setup

- Severity: functional (needs confirmation with one re-run; the rerun budget was used up)
- Area: quiz mode / navigation

## Reproduce
```
./aerun quiz2-07 "press:3D Models;wait:1500;action:quiz;wait:1500;dump:k7;press:Explore;wait:1500;action:quiz;wait:1500;dump:l7"
```
Also seen in quiz2-06:
```
./aerun quiz2-06 "action:radiology;wait:1500;action:quiz;wait:1500;press:3D Models;wait:1500;action:quiz;wait:1500;dump:i6"
```

## Expected
`action:quiz` always shows the Explore quiz setup ("Start quiz", "My progress…") and makes Explore the active tab.

## Actual
- quiz2-07, step 1 (from 3D Models): quiz setup shown on Explore. OK.
- quiz2-07, step 2 (press Explore, then action:quiz): the workspace became **3D Models** (tab checked, "Installed model catalog" with 41 rows shown). The quiz setup is gone, so "Start quiz" cannot be found. "Back to the previous place" is now enabled.
- quiz2-06: after Radiology, then 3D Models, `action:quiz` landed on **Radiology** (tab checked, Radiology case with Close/Next at bottom-left). No quiz setup visible.

In each failing case the destination is the place visited just before the current one in Back history, so `action:quiz` seems to behave like Back, not like "open quiz".

## Evidence
- runs/quiz2-07/k7.txt, k7s.json, l7.txt, m7.txt (catalog shown instead of quiz setup)
- runs/quiz2-07/k7.jpg (quiz setup on Explore after action:quiz from 3D Models)
- runs/quiz2-06/i6.txt, h6.txt, g6.txt

> Coordinator triage: by design — quiz.stop() restores the scene snapshot taken when the quiz started (study_scene.restore_scene), including the workspace. Surprising if you moved to Explore during the quiz; possible UX: only restore the workspace when the user has not navigated since starting.
