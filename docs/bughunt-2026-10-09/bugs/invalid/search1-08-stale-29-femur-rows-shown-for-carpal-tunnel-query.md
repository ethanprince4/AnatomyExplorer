# Search: results list shows 29 femur rows under a "carpal tunnel" query after a lesson was opened

- Severity: functional (stale content after switching items), unconfirmed by re-run
- Area: global search results panel after navigating

## Reproduce
```
./aerun search1-08 "wclick:0.766,0.051;key:ctrl+a;type:femur;key:return;wait:1500;wclick:0.162,0.475;wait:2500;wclick:0.766,0.051;key:ctrl+a;type:carpal tunnel;key:return;wait:1500;dump:x"
```
(Observed once in run search1-08 as the f_carpal step. Not re-run because the budget was used up.)

## Expected
After typing "carpal tunnel" and pressing Return, the "Search results" list should show the results for "carpal tunnel". Earlier, the same query in search1-03 gave 2 rows.

## Actual
The dump shows the search box reads "carpal tunnel" and the "Search results" QListWidget has rows=29, which is the count for the "femur" query. Lessons is checked, so the list is left over from the earlier femur search.

## Evidence
- runs/search1-08/f_carpal.txt (QLineEdit 'carpal tunnel', Search results rows=29)
- runs/search1-03/r3_carpal_open.txt (same query, rows=2, for comparison)
