# Clicking a system NAME in Explore > Systems toggles its visibility and never updates the Details panel

- **Severity:** functional (medium confidence; expected behaviour inferred from the Tree sub-tab hint)
- **Reproduce (confirmed twice):**
  `./aerun <RUN_ID> "action:toggle_panels;wait:1500;wclick:0.12,0.753;wait:1000;dump:x"`
  (run tree2-07: Cardiovascular system goes from checked to unchecked after clicking its name; the dump shows `QCheckBox 'Cardiovascular system' ... unchecked`).
  Same with `wclick:0.12,0.612` on "Muscular system" (runs tree2-03, tree2-05).

## What happens
- Clicking the name text of a system row in Explore > Systems > Browse toggles the checkbox, hiding/showing the whole system in 3D (Muscular hidden, count goes to 0/627, 3D muscle layer disappears).
- The Details panel ("Anatomy details") stays on the generic "Anatomy Explorer / Explore and study" overview text before and after the click.

## Expected
The Tree sub-tab of the same panel says "Check to show or hide; select a name to explore." That implies name clicks are meant to select/explore the system (and update Details), with only the checkbox controlling visibility. In Systems, the name click acts as a checkbox toggle instead, so the name does not explore it.

## Notes
- Not the same as bugs/invalid/tree1-07-systems-checkbox-label-right-side-does-not-toggle.md (that was clicks on the right side of the row not toggling).
- Evidence: runs/tree2-03/tree2-03-name-click.jpg (Details still overview after clicking "Muscular system" name, muscles hidden in 3D); runs/tree2-03/tree2-03-uncheck.jpg; dumps runs/tree2-03/tree2-03-a.txt, runs/tree2-07/tree2-07-a.txt.
- Not verified visually for the Tree sub-tab name click (image budget used up).
