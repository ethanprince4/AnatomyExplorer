# Shortcut recorder accepts a key already in use by another command, with no conflict warning

- **Severity:** functional (low)
- **Area:** Settings dialog, Keyboard tab, "Customizable keyboard shortcuts" table

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun settings1-06 "action:settings;wait:1200;settings:3;wait:800;press:Press shortcut;key:ctrl+f;wait:500;dump:r6_conflict"
```
(ctrl+f is recorded as the Cmd+F shortcut.)

## Expected
Assigning a shortcut that is already bound to another command should show a conflict warning, or swap/clear the other binding. The table should not end up with two commands on the same shortcut silently.

## Actual
The second column of one row is set to the same key (⌘F) as the first column of another row. No warning or dialog appeared (dump r6_conflict.txt lists ⌘F at two cells, rows at y=0.409 and y=0.530). "Reset all shortcuts" afterwards restored defaults.

## Caveats
- The table rows have blank labels in the dump, so the command names behind each row were not verified.
- The recorder may have been focused on a different row than intended (the row positions shifted between dumps).

## Evidence
- runs/settings1-06/r6_conflict.txt
- runs/settings1-03/r3_k1.txt (single ⌘K recorded correctly, for comparison)
