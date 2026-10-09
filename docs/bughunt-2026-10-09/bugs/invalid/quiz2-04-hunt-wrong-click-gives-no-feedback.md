# Clicking a wrong structure in "Find it in 3D" gives no visible feedback

- Severity: ux
- Area: quiz mode, Find it in 3D

## Reproduce
```
./aerun quiz2-04 "action:quiz;wait:1200;press:Start quiz;wait:2500;wclick:0.4,0.4;wait:900;wclick:0.55,0.45;wait:900;shot:q4c"
```

## Expected / Actual
The question is "Posterior transverse collateral sulcus" (Question 1 of 20, 0 correct). After two clicks in the 3D view (one on background, one on the arm) the panel is unchanged: still "Question 1 of 20 · 0 correct", no "wrong" message, no miss counter, no highlight. The user cannot tell whether a click registered, and the "three wrong clicks reveal the answer" rule cannot be seen.

Suggested feature: show a short "Not that one (1/3)" line and a brief highlight or outline on the clicked structure after each wrong click.

## Evidence
- runs/quiz2-04/q4.jpg (question shown), runs/quiz2-04/q4c.jpg (no feedback after the clicks)
- runs/quiz2-04/q4.txt, q4b.txt
