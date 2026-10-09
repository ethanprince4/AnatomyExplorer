# Parent topic counts in the filtered Histology tree do not match their children

- Severity: functional (wrong number)
- Workspace: Histology browser, tissue search (filtered tree)

## Reproduce
```
./aerun <RUN_ID> "press:Histology;wait:1500;press:Search tissues;wait:300;type:muscle;key:return;wait:1500;shot:muscle"
```
Same pattern with `type:heart` (run histo2-01).

## Expected
A parent row's count matches what it contains: either the total of its subtree, or the number of slides listed directly under it. A child count matches the rows shown under that child.

## Actual
- "Simple columnar epithelium" shows **13**, but only **1** row is listed under it ("Gut mucosal folds with a thick outer muscle layer"); the next visible row is the sibling topic "Pleura & peritoneum".
- "Epithelium" (parent) shows **9** while its children show 13 and 5 (sum 18), and it lists no rows directly.
- "Muscle tissue" (parent) shows **3** while its only child "Skeletal muscle" shows 15, and no rows are listed directly under the parent.
- Heart search: "Muscle tissue" shows **3** while "Cardiac muscle (myocardium)" shows 14 (14 rows listed, matches); "Nervous tissue" shows **2** while "Sensory & autonomic ganglia" shows 6 (6 rows listed, matches).

So the leaf topics with rows match their rows in the heart search, but the parent counts are neither the subtree total nor the number of direct rows, and in the muscle search the 13 under "Simple columnar epithelium" has only 1 row beneath it.

## Evidence
- runs/histo2-06/h2-06-muscle.jpg (screenshot of the muscle search tree)
- runs/histo2-01/h2-01-heart.jpg (screenshot of the heart search tree)
- runs/histo2-06/h2-06a.txt (dump: search-field text only, tree rows are not in the dump)
