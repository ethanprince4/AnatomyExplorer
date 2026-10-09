# Anatomy Explorer bug hunt — 2026-10-09

**Result: 22 bugs fixed and verified (2 of them crashes), 7 UX notes, 1 residual warning.**
Fixes are in `fixes.patch` (12 files under `app/`, applies cleanly with `patch -p1` to the shipped 4.0.5 sources).
The installed app was not modified; fixes were tested in a copy at `patched/Anatomy Explorer.app`.

## How it was tested
- ~32 Haiku agents (`lean-worker`), each driving its own scripted copy of the app through `aerun` (up to 4 at once),
  one area each: Explore tree / 3D tools / View tab / Details, search & command palette, Lessons, quiz, 3D Models,
  Radiology, Histology, Settings, saved views & history, notes/export/window modes, random action storms, crash
  hunting, and a whole-app "student journey". Agents peaked at 26–77K context (budget tightened after the pilots).
- Every report was triaged by reproducing it; 22 turned out to be test-harness artifacts or intended behaviour
  (in `bugs/invalid/`). The harness itself was fixed each time so later agents did not repeat them.
- Final regression: a full pass through all workspaces on the patched build ends cleanly (run `v-final`).

## Crashes (fixed)
| # | What | Fix |
|---|------|-----|
| 16 | **SIGSEGV after a few successive Explore searches** — 3/3 reproducible. Qt's macOS accessibility bridge crashes when the results list *adds* rows while on screen (`QAccessible::updateAccessibility` ← `endInsertRows` ← `QListWidget.addItem`). Happens whenever any accessibility client is running (VoiceOver, window managers, password managers, automation). | `stable_rows.reserve_rows`; search results reserve all 150 rows at construction. 0/3 after. |
| 21 | **SIGSEGV switching Lessons grouping chips quickly** — same crash via `CardList._row` (intermittent). | `CardList.reserve()`; lesson library, radiology library and radiology label legend reserve their maximum rows up front. Verified no list ever adds a row after startup under stress. |

## Functional / UX bugs (fixed)
1. Radiology tab while already on the Radiology library jumped away to the last case.
2. Lesson group headers counted only filtered lessons ("1/1 finished" instead of "1/9").
3. Hide/show panels needed two presses after one panel was closed.
4. A no-match search in the Explore side panel scattered its widgets down the panel.
5. Top bar highlighted "Explore" while a histology slide or radiology case was open.
6. "Related lessons (N)" on a 3D model opened an empty lesson list (now switches grouping and expands groups).
7. Return in a Settings value box opened the colour picker.
8. Histology topic tree mixed units (topics counted tissues, tissues counted images).
9. Back from an opened 3D model skipped the model library (loading placeholder was recorded as a place).
10. The opening Explore view was never in Back history.
11. Opening a saved view from another workspace restored it invisibly behind that workspace.
12. 3D model "More controls" repeated Cut-away / Separate layers already in the Reveal row.
13. Top bar highlighted "Explore" while a 3D model was open or loading.
14. Radiology self-check: revealed answer was cut off in its box.
15. Saving a view with an existing name **silently overwrote** it; empty names silently did nothing. Now asks "Replace it?" / re-prompts.
17. No visible way back to Details after closing it — added "Details" to More tools.
18. Details header repeated the name as its Latin subtitle ("Aorta" / *Aorta*).
19. Back/Forward restored the selection but not the Details page (showed "4 structures selected").
20. Escape never left Measure mode.
22. Bottom "Measure" button relabelled itself "Measure distances" and shifted the bar.

Details, files touched and the verifying run for each: `FIXES.md`. Original agent reports: `bugs/fixed/`.

## UX notes (not changed — your call) — `bugs/ux-notes/`
- **Cross-section survives Reset/Show all**: from the front it reads as a thin labelled sliver. Reset is camera-only by design; consider facing the section plane or hinting it is still on.
- **Cross-section controls are only in More tools**, not in the View tab with the other reveal controls.
- **Stopping a quiz returns you to where it started**, even if you moved to another workspace meanwhile.
- **Radiology label row → selects the whole organ and turns on ~20 of its landmark labels**, burying the case's numbered labels.
- **Lesson steps don't visibly highlight the structures their text names** (depends on authored `focus`/`ghost_focus`).
- **"Read more" stays expanded for the next structure** (shared sticky expansion preference).
- **Explore search results stay open after opening a hit** (useful for browsing; two Close buttons visible).

## Residual
- Qt still logs `QAccessibleList::child: Invalid index` warnings for some lists (`bugs/residual/`). No crash observed
  after fixes 16/21. `LessonsPanel`'s "replace a preview library" path (ui/lessons.py ~189) can still grow the lesson
  list at runtime if a larger library is swapped in.

## Not covered well
Visual correctness of 3D content (wrong labels/positions), exact quiz scoring, histology/radiology authored content
accuracy, multi-monitor/window-resize behaviour, and anything needing real keyboard shortcuts (they don't fire in the
background test app; all shortcut actions were exercised via their action IDs instead).

## Files
`fixes.patch` · `FIXES.md` · `bugs/{fixed,ux-notes,residual,invalid}/` · `runs/` (evidence) ·
test harness: `aerun`, `aeh.py`, `BRIEF.md`, `ctxstat`, `makepatch` · patched app copy: `patched/`.
