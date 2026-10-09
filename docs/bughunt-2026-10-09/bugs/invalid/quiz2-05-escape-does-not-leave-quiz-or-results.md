# Escape does not close the quiz question or the results panel

- Severity: ux
- Area: quiz mode, keyboard

## Reproduce
```
./aerun quiz2-05 "action:quiz;wait:1200;press:Start quiz;wait:2000;wclick:0.5,0.2;wait:900;press:Skip;wait:1000;press:Finish;wait:1200;key:escape;wait:800;dump:e5"
```

## Expected / Actual
Escape should leave the quiz (or at least the results panel). Actual:
- Results panel ("0 / 1 correct", "Retry missed", "New quiz", "Close") is still shown after Escape. Focus moves to the review list (QListWidget).
- A question in progress is not closed by Escape either (runs/quiz2-03/q3d.txt: still "Hint / Reveal / Skip / Finish" after escape).
- The setup panel also ignores Escape (runs/quiz2-07/p7.txt).

The only way out is the small "Close" button in the panel corner, so there is no keyboard way to leave the quiz.

Suggested feature: Escape closes the results/quiz panel (or asks to stop if a quiz is running), and the Close button is reachable by Tab.

## Evidence
- runs/quiz2-05/f5.jpg (results panel, taken before the Escape press), runs/quiz2-05/e5.txt
- runs/quiz2-03/q3d.txt, runs/quiz2-07/p7.txt
