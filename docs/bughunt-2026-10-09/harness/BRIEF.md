# Bug-hunt brief (read fully, then start)

You are testing the desktop app **Anatomy Explorer** for bugs. You drive it only through the shell tool
`/Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/aerun`. Never use any other way to control the app.

## How a run works
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun <RUN_ID> "cmd;cmd;cmd"
```
Always give the shell call a timeout of 600000 ms (runs can queue behind other agents' runs).
Each run launches a fresh app (≈10 s), executes the commands in order, then kills it and prints a report.
Use RUN_ID = `<your agent id>-<n>` (e.g. `radio3-07`). Results go to `runs/<RUN_ID>/`.
Exit status: 0 ok, 2 CRASH, 3 HANG, 4 Python errors. The report shows tracebacks and a HELPER LOG
(`NOT FOUND` / `DISABLED` lines mean your press target did not exist — that is not an app bug).
`HELPER-ERROR` lines are harness problems, never report them as app bugs.

Commands (separated by `;`, arguments must not contain `;`):
- `press:TEXT` click the visible button, field or list row whose text/tooltip contains TEXT (exact match preferred). `rpress:` right-click, `dpress:` double-click.
- `wclick:FX,FY` click at a fraction of the window (0–1). Screenshot images are 1100 px wide x ≈690 tall, so FX = x/1100, FY = y/690. `wrclick:` `wdclick:` too.
- `type:TEXT` type into the focused field. `key:return` `key:escape` `key:tab` `key:down` `key:ctrl+z` etc.
- `combo:LABEL=ITEM` choose ITEM in a dropdown.
- `dump:NAME` writes `NAME.txt`: every clickable widget and list row with its `@fx,fy` centre. Cheap — use it instead of screenshots to find targets.
- `shot:NAME` screenshot of the window (`NAME.jpg`); `shottop:NAME` screenshot of an open dialog/popup.
- `state:NAME` current workspace and open dialogs as JSON.
- `wait:MS` pause (give 800–1500 ms after anything that loads; 3D models may need 3000+).
- App commands: `action:ID` (IDs below), `search:TEXT` then `activate` (opens top search hit), `view:anterior|posterior|left|right|superior|inferior`, `orbit:DX,DY`, `zoom:F`, `click:FX,FY` (inside the 3D viewport only), `settings:N` (settings page N), `esc`, `quit` (close app normally — tests shutdown).

Action IDs: search settings screenshot export_figure fullscreen borderless toggle_panels escape back forward save_view
histology_tab frame reset_view view_anterior view_posterior view_right view_left view_superior view_inferior
orbit_left orbit_right orbit_up orbit_down zoom_in zoom_out auto_rotate hide isolate xray both_sides show_all
default_visibility undo structure_labels landmarks measure peel_in peel_out peel_reset color_mode clip_sagittal
clip_coronal clip_transverse quiz lessons radiology note open_model_file model_next_view model_prev_view
(more may exist; an unknown ID shows as a KeyError — that is your typo, not a bug).

Notes: dialogs/popups work normally — use `shottop:` or `dump:` (dumps the open dialog) and `key:escape` or
`press:Close` to leave them. `type:` works with any unicode. User data (lesson progress, notes, saved views)
persists between runs and is shared with other agents, so do not rely on a clean state.

## Budget — strict
Your context must stay small. **At most 7 `aerun` calls and at most 4 image views** (reading a .jpg). Prefer
`dump:` text over images, and read dumps with `grep` for what you need (never cat a whole dump twice).
Do not re-read report.txt files — the aerun output already printed it. Put many steps in one run (10–30 commands is fine). Read only the files you need.
When the budget is used, stop and write your final message.

## What counts as a bug
Crash, hang, Python traceback, a dialog/popup that cannot be closed, a button that does nothing or the wrong
thing, broken/overlapping/clipped/unreadable layout, empty panels that should have content, wrong state after
back/forward/undo, stale content after switching items, settings that do not apply. Be adversarial: rapid
switching, repeating actions, empty/odd input (very long text, symbols, unicode), escape at odd times, doing
things in unusual orders. Do not report: slow loading, harness messages, things you are unsure of without evidence.

## UX gaps and missing features (also wanted)
Also file things that are not broken but make the app awkward: dead ends with no way back, a page you cannot
leave or undo, controls that exist in one workspace but are missing in a similar one, actions with no feedback,
confusing labels, destructive actions without confirmation, lists that open empty or collapsed when you came for
specific items. Use severity `ux` and add one line "Suggested feature:" saying what should exist.

## Reporting
For each **new** bug write `bugs/<RUN_ID>-<slug>.md` (first `ls bugs/` and skip anything already reported) with:
title, severity (crash/hang/error/functional/visual), the exact `./aerun` command that reproduces it (minimal if
you can — re-run once to confirm), what happened vs expected, the traceback (if any), evidence file paths.

Your **final message** (it goes to the coordinator, keep it ≤ 25 lines): bugs filed (file names, one line each),
what you covered, what you did NOT get to, and ideas worth probing next.

## Known non-bugs (do not file)
- Clicking a checkbox's label text toggles it (normal). The Systems sub-tab rows are checkboxes.
- "Reset this page" restoring "Restore camera…" to checked (that is the default). Shortcut conflicts show a warning line in the dialog.
- Tabs that hide when a case has no content for them (e.g. Radiology "Teaching view").
- A Radiology case or Histology slide replaces the Explore canvas; pressing Explore closes it.
- Anything the HELPER LOG marks as NOT FOUND / HELPER-ERROR.
Prefer bugs with hard evidence: an error, a stuck UI, contradictory state, or clearly broken layout.
- `action:ID` never blocks now (dialogs it opens can be dumped/escaped); an unknown ID is logged as UNKNOWN (your typo).
- In combos the label is the CURRENT value text; dump: first to get it.
- Keyboard SHORTCUTS (Esc, Ctrl+…, F11, letters) do not fire in the background test app; use `action:ID` instead
  (e.g. `action:escape`). `key:` is only for typing into fields, lists and dialogs. Never file "shortcut does nothing".
