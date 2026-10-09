# Radiology Self-check: answer text is clipped in its small box after "Show answer"

- Severity: visual (ux-level)
- Case: "CT abdomen — axial, liver and spleen", Self-check tab, Question 2 of 2

## Reproduce
./aerun radio2-08 "wait:800;press:Radiology;wait:1200;wclick:0.498,0.342;wait:800;wclick:0.498,0.419;wait:800;press:Open selected case;wait:3500;wclick:0.209,0.673;wait:1000;wclick:0.213,0.807;wait:500;key:down;key:return;wait:800;press:Show answer;wait:800;shot:repro"

## Expected
The revealed answer is readable in the Self-check panel (the panel is a fixed-height box with a scrollbar).

## Actual
After "Show answer", the answer text ("Answer: Abdominal aorta and inferior vena cava") is cut off at the bottom edge of the box, so only the first half of the line is visible. The user has to find the tiny scrollbar to read it. The question text and the buttons stay visible, so the answer area looks broken rather than scrollable. The answer box is also much shorter than the Study notes box above it, which is not a problem by itself.

Suggested feature: give the answer area enough height for a typical answer, or expand the box when the answer is shown.

## Evidence
- runs/radio2-08/r8_sc.jpg
- runs/radio2-08/r8_zout.txt (QTextBrowser 'Radiology self-check question and answer' present)
