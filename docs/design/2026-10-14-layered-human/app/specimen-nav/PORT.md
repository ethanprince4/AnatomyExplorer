# Navigation (checkpoint 3): three options

`index.html` is apply3's base (checkpoint 2's decisions applied) with one navigation layer on top. Pick an option with
`?variant=1|2|3`, a screen with `?screen=`, a wall with `?scheme=`, and a small laptop window with `?window=1280`
(render it at a 1280 × 800 viewport). Option 3 adds a screen, `?screen=lobby&variant=3`.

Only the chrome and the ways between rooms change. Every room's content is the base's, with one exception: the model
viewer's selected part gets an **In the atlas** button. Everything is drawn with scheme tokens, so it recolours with the
wall. No keyboard hints are printed; bindings are in `aria-keyshortcuts` and tooltips.

The audit behind this (every place in the app and the mockup, how you reach it, how you get back, and the tasks) is
summarised below; the long version is in the scratch folder as `ia.md`.

## What all three share

- **Practice is the sixth room**, and the due count lives on its name (`Practice 12`). It replaces the base's loose
  "Review 12 due" button. Its front page is the quiz set-up the app already has (Review what is due, quiz by topic,
  My progress); a session (the base's practice screen) lights Practice, not Lessons.
- **Settings is a word.** The ≡ stays only for the classic menus the Qt app must still offer (progress, notes, open a
  model file, export a figure, help).
- **A trail on item pages**: lesson `Lessons › The coronary circulation › Step 2 of 7`, practice `Practice › Lab 6 ·
  Pressure, volume and a breath`, viewer `Models › Kidney with the nephron`, slide `Histology › Epithelium › Simple
  columnar epithelium`, case `Radiology › Chest radiograph, PA`. Front pages have none (option 3 shows the room).
- **Back takes places, not steps.** A place is a room page or an item; lesson steps and selections are not places (the
  lesson's own Back and Next move through steps). Back's tooltip always names its target.
- **Rooms remember.** Clicking a room you are not in returns to it as you left it (the open lesson, model, slide, case);
  clicking the room you are in goes to its front page.
- **In the atlas** on the model viewer's part card: the app's existing "Show in the atlas".

## Option 1: Rooms bar

*The top bar made fully clear: six rooms, a Back that says where it goes, and a trail line on item pages.*

Header: lockup · Atlas Lessons Models Radiology Histology Practice 12 · `‹ Back to Lessons` › · search · Saved views ·
Settings · ≡. On item pages a 14 px trail sits on its own line just under the bar (top 78). At 1280 the wordmark drops
to the mark and search narrows; nothing wraps.

## Option 2: Side rail

*The rooms in a slim rail down the left edge of the wall; the header keeps Back, the trail and search.*

A 104 px rail, lettered on the same wall with a hairline on its right edge: the mark, then the six rooms as icon over
name (current: text colour and the brass bar under the name; Practice carries its count), and at the foot Saved views,
Settings and Menu. The room moves right by 104 px. The header holds ‹ ›, the trail on item pages, and search. It has
the most free space and the steadiest place for each room, but it costs 104 px of width on every screen.

## Option 3: Lobby

*A home room the app opens to, with every room a doorway from it, and every room's trail starting at the Lobby.*

The lobby: the lit body in the middle; Continue where you left off and Review on the left; the six rooms as doorways
around the body (picture, name, one real count); Recent places (the app's place history) and Saved views on the right.
In every room the header starts `[mark] Lobby › Lessons › The coronary circulation`, so the way home is the first word
on screen. ‹ › and search follow, then the six rooms (still one click apart), Settings and ≡. Saved views appears in
the Atlas header only, beside the trail.

## Recommendation

**Option 1, Rooms bar.** It fixes what was actually broken (no Practice, an unnamed Back, no "where am I" inside a
room, an unlabelled Settings) without moving the model or adding a room to walk through, and it holds at 1280 with
room to spare. Option 3's lobby is the friendliest first launch, so it is worth taking its Continue, Review and Recent
places into the Lessons front page or a first-run state, rather than making every session start in a lobby.

## Renders (`renders/checkpoint-3/nav/`, Gallery slate at 2×)

- `before_{atlas,lessons,lesson,histology-library,viewer}`: the base as copied.
- `<n>_{atlas,lessons,lesson,histology-library,viewer,practice,histology,radiology,settings}` for n = 1, 2, 3, and
  `3_lobby`.
- `<n>_atlas_1280`: a 1280 × 800 window. The chrome is laid out for 1280; the room under it is the 1920 room scaled to
  fit (the rooms' own small-window layout is outside this topic).
- `<n>_atlas_umber`: Umber, whose accent is blue, so every current marker and count is checked against a non-brass
  accent.
- `<n>_atlas_crop`, `<n>_lesson_crop`: the chrome at 1:1 (for option 2 the rail and header corner).
- `map_<n>`: the places and the ways between them (SVG in `maps.py` in the scratch folder, rasterised with
  `tools/raster_svg.mjs`).

## Tasks: clicks today and in each option

Mouse clicks; typing is not counted. "App" is v4.0.8, "Base" is the mockup before this round.

| # | Task | App | Base | 1 | 2 | 3 |
|---|---|---|---|---|---|---|
| 1 | Look at the biceps from another room | 2 | 2 | 2 | 2 | 2 |
| 2 | Continue the last lesson | 1–2 | 2 | 1 | 1 | 1 (lobby: Continue) |
| 3 | Review the 12 due | 4 (gear, Study, Quiz, Review) | 1, destination unclear | 2 | 2 | 1 from the lobby, 2 from a room |
| 4 | Kidney model at its Corpuscle view | 4 | 4 | 4 | 4 | 4 |
| 5 | Jejunum slides, then the jejunum model | 7 | 4 | 4 | 4 | 4 |
| 6 | Open a chest film | 2 | 2 | 2 | 2 | 2 |
| 7 | Change the wall colour | 4+ | 3 (≡, Settings, wall) | 2 | 2 | 2 |
| 8 | Back to the atlas as you left it, after reading 3 lesson steps | 4 Backs, or Explore: 1 | 1, state not shown | 1 (`Back to Atlas`, named) | 1 | 1 |
| 9 | Start a heart quiz | 6 | no way in | 4 (Practice, Topic, Cardiovascular, Start) | 4 | 4 |
| 10 | Save a view, later reopen it | 3 + 2 | 3 + 2 | 3 + 2 | 3 + 2 | 3 + 2 (or from the lobby) |
| 11 | From the kidney model, the renal artery in the body | 2 (right-click, Show in the atlas) | no way | 1 | 1 | 1 |
| 12 | End a lab practice, back to its lesson | 2 | no way drawn | 1 (`Back to Lab 6`) | 1 | 1 |

## Carrying the chosen option into `app/specimen/index.html`

Everything is in three blocks of this file:

1. **CSS**: `<style id="nav-cp3">` just before `</head>`. The shared rules come first, then one commented section per
   option, then `[data-window]` (only needed for the 1280 render). For one option, keep the shared rules and its own
   section, and drop the `[data-variant="n"]` prefixes.
2. **JS**: `<script id="nav-cp3-js">` after the base's main script. It holds `ROOMS` and `PLACE` (room, trail and Back
   target per screen) and rebuilds every `[data-chrome]` header. To merge, replace the base's `[data-chrome]` builder
   (`NAV` and its `forEach`) with the chosen branch of this one, and drop the base's "Review 12 due" button. It also
   adds the viewer's **In the atlas** button and defines `navCompact()` (1280 render only).
3. **Markup**: option 3 only, the `LOBBY` section (before `SETTINGS`), and `lobby` added to the screen display rule.
   It uses existing plates and images only (`body_muscles`, `body_skeleton`, `heart_home_clean`, `kidney_v_kidney`,
   `thorax_chest`, `cxr_pa.jpg`, `histo_simple_columnar.jpg`).

`render_mockups.mjs` and `render_all.py` would need `lobby` added to `SCREENS` for option 3.

## What the Qt app needs

- **Header** (`app/ui/studio_shell.py`, `StudioHeader.__init__`): add Practice to `self.navigation` with a count label
  fed by the quiz schedule (`quiz.QuizController`, the number behind `review_btn`); rename Explore to Atlas and
  3D Models to Models (also `_update_workspace_header` and `set_workspace` keys, and F18); replace the gear's icon-only
  button with a `Settings` text button that triggers `actions["settings"]`, and keep a separate ≡ menu for
  `_populate_commands`. Option 1: give `back_button` a text label from `set_places` (`"Back to " + label`), dropping its
  split menu arrow (the recent list moves to a right-click or long-press). Option 2: move the room buttons into a new
  vertical `QWidget` docked at the left of `self.workspace` in `MainWindow._build_workspace_header`; the header row
  keeps back/forward, a trail and search. Option 3: a new lobby page in `CollectionWorkspace` and a `home` button.
- **Trail**: a new small widget (a row of flat link buttons) under or in the header, filled from what
  `_update_workspace_header` already computes: the workspace, `lessons_panel.lesson.title` and step, the open model's
  `entry.name`, the histology tissue and group, `radiology_panel.case.title`. Each crumb calls the existing owner:
  `_show_lesson_library`, the lesson cover (`‹ Lesson overview`), `_show_catalog`, `show_histology_tab`, `show_radiology`.
- **Back takes places** (`app/ui/places.py`, `PlaceHistory.push`, and `MainWindow._note_place`): stop pushing a new
  entry for each lesson step or selection change in the same room item (update the label in place instead, as `push`
  already does when the key repeats: make the key the room and item, not the step).
- **Rooms remember** (`MainWindow._show_nav_page`, `_show_catalog`, `show_histology_tab`, `show_radiology`): when the
  room has an open item (`self.micro_tabs`, the histology viewer tab, the open case), go to it; when the room is
  already current, go to its library. Lessons already does this.
- **Practice room**: today the quiz is a floating panel (`QuizController.dock`, registered with `_floating_panels`) and
  lab practice runs beside the model (`app/ui/practice.py`). The room's front page can be the quiz panel's set-up
  widgets shown full height in `CollectionWorkspace`; a running session keeps today's layout, with the header lighting
  Practice. This is new structure, not new features.
- **In the atlas** on the viewer's part card: the existing `atlasRequested` signal (`model_view.py`, "Show in the atlas"
  in the part's context menu), surfaced as a button.
- **Slide to model**: the base's "Jejunum model" button needs a reverse lookup the app does not have yet: models list
  their tissues (`entry.histology`), but tissues do not list their models. Build the map once from
  `content.micro_models` in `open_histology`.
- **Lobby** (option 3): Continue uses `lessons_panel`'s resume data, Review uses the quiz schedule, Recent places is
  `PlaceHistory.recent()`, and Saved views is `_saved_views()`. All of it exists; only the page is new. The app opens to
  it instead of restoring the last session's room (`session restore` in Settings → Behavior would decide).

## Weak or unresolved

- The 1280 renders scale the 1920 room under the chrome; the atlas's own small-window layout (gauge height, label card
  against the systems list) is not designed here.
- The Practice room's front page is described, not drawn: no screen exists for it in the base.
- Option 2's rail moves every room 104 px right; nothing collides at 1920, but the viewer and the histology catalogue
  have the least slack.
- Option 1's named Back changes width with its target, so the search field's left edge moves slightly between places.
- In option 3, Saved views sits beside the trail on the Atlas only; it could be mistaken for part of the trail.
- The saved-view names in the lobby and the Back targets are a made-up session, chosen to be consistent across
  screens.
