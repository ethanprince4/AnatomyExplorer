# Search: results panel's search field does not follow the top search box

- Severity: functional (stale content)
- Area: global search box and the results panel's own search field ("SearchLine")

## Reproduce
```
./aerun search1-03 "press:Search anatomy;type:femur;key:return;wait:1500;wclick:0.766,0.051;key:ctrl+a;key:delete;wait:1000;dump:x"
```
Also: with the panel open, type `.*[(` in the top box and Return, then type an emoji in the top box (no Return) and dump.
(Observed in run search1-03. Not re-run because the budget was used up.)

## Expected
The panel's search field and results should follow the top box, or the panel should close when the top box is cleared.

## Actual
- After clearing the top box (empty, shows "Search anatomy"), the panel field still reads "carpal tunnel" and the list still has 2 results.
- The panel field lags one query behind the top box. With the top box at `.*[(`, the panel field shows `<b>x</b>` with 50 rows. With the top box at an emoji, the panel field shows `.*[(`.

## Evidence
- runs/search1-03/r3_empty.txt (top box empty, SearchLine 'carpal tunnel', rows=2)
- runs/search1-03/r3_regex.txt (top '.*[(', SearchLine '<b>x</b>', rows=50)
- runs/search1-03/r3_emoji.txt (top emoji, SearchLine '.*[(')
