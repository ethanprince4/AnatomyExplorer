# Progress filter shows group counts as "x/1" instead of "x/9"

- **Severity:** functional (wrong number; low)
- **Reproduce:** two steps. (1) `./aerun lessons1-05 "action:lessons;wait:1200;press:Lab 1 · 0/9;wait:600;press:The reflex arc;wait:1500;press:Learn;wait:1000;press:Lesson tools;wait:800;press:Mark as finished;wait:1000;press:‹ Lesson overview;wait:1200;press:‹ All lessons;wait:1200"` marks one lesson finished. (2) `./aerun lessons1-06 "action:lessons;wait:1200;combo:All progress=Finished;wait:800;dump:l6_fin"` is run on a fresh app, so it needs the finished lesson from step 1 to exist. The header count then shows `1/1`. Step 2 by itself may show different results; the sequence was run as lessons1-06 with the same first steps.
- **Expected:** With "Finished" selected, the group header still shows the total lesson count for the group, e.g. `Lab 1 · 1/9 finished`.
- **Actual:** Header becomes `Lab 1 · 1/1 finished`. Other filters show the same pattern with the filtered total: "In progress" shows `Lab 1 · 0/1`, "Not started" shows `Lab 1 · 0/7`. "With practice" keeps `Lab 1 · 1/9`. The header count is inconsistent across filters.
- **Traceback:** none.
- **Evidence:** `runs/lessons1-06/l6_fin.txt` (`1/1 finished`), `runs/lessons1-06/l6_top.txt` (`1/9`), `runs/lessons1-07/l7_inprog.txt`, `runs/lessons1-07/l7_ns.txt`, `runs/lessons1-07/l7_wp.txt`.
