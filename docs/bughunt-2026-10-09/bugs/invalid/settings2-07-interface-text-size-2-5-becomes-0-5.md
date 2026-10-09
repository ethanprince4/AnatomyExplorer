# Typing 2.5 into Interface text size produces ".5"

- **Severity:** functional
- **Area:** Settings > Display > Interface text size (value box)

## Reproduce
```
./aerun settings2-08 "settings:1;wait:800;press:1.00;key:ctrl+a;type:2.5;key:tab;wait:800;dump:x"
```
Same result in settings2-07 and settings2-08.

## Expected
The entered number is either accepted as 2.5, clamped to the slider's maximum, or rejected with the previous value kept.
The box should show a valid number.

## Actual
The box shows `.5` (the leading "2" is dropped and the value is not normalized or reverted). Maximum text size is therefore not reached,
and the text size is left in an invalid-looking state. The brief item "text size at maximum" could not be tested through this path.

## Evidence
- runs/settings2-07/m7_text.txt (value `.5` at `@0.716,0.396`)
- runs/settings2-08/f_text.txt
- runs/settings2-07/m7_text_main.jpg and m7_text_dlg.jpg were captured in this state
