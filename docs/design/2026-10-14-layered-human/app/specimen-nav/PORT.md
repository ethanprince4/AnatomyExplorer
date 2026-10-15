# Navigation (checkpoint 3): three options

`index.html` is apply3's base (checkpoint 2's decisions applied) with one navigation layer on top. Pick an option with
`?variant=1|2|3`, a screen with `?screen=`, a wall with `?scheme=`, and a small laptop window with `?window=1280`
(render it at a 1280 × 800 viewport). Option 3 adds a screen, `?screen=lobby&variant=3`. All three have Practice's
front page, `?screen=practice-home`; `?screen=practice` stays the running question.

**The mockup can be walked.**
- Every room, crumb, doorway, recent place, Continue, Review, Start quiz, tissue and wall is a real link.
- Back and Forward move along a place history kept for the tab. Opening a screen on its own (a render) starts from one
  made-up session, so every render names the same Back.
- The second pass's walkthrough, with every task done by clicking, is in the scratch folder as `nav2/walkthrough.md`.

Only the chrome and the ways between rooms change. Every room's content is the base's, with one exception: the model
viewer's selected part gets an **In the atlas** button. Everything is drawn with scheme tokens, so it recolours with the
wall. No keyboard hints are printed; bindings are in `aria-keyshortcuts` and tooltips.

The audit behind this (every place in the app and the mockup, how you reach it, how you get back, and the tasks) is
summarised below; the long version is in the scratch folder as `ia.md`.

## What all three share

- **Practice is the sixth room**, and the due count lives on its name (`Practice 12`). It replaces the base's loose
  "Review 12 due" button. Clicking Practice always opens its front page (`practice-home`). A running session (the
  base's practice screen) lights Practice, not Lessons, and is reached only by starting one.
- **Practice's front page** (`practice-home`), lettered on the wall in four columns on the 232 line. Only what the app
  has:
  - **Due today**: the count and **Review what is due** (`QuizController.review_btn`, `start_review`).
  - **Your results**: items seen, answers and right overall, plus the most often missed. These are the progress
    dialog's numbers (`srs.summary`, `srs.weakest`), and **My progress** opens that dialog.
  - **Quiz by topic**: the quiz panel's topic list (`ds.systems` less `EXCLUDED_SYSTEMS`, after "Everything currently
    visible"), with each topic's due count and structures.
  - **Lab practice**: one row per lab, each starting that lab's practice (`lessons_panel.practice`).
  - **The picked topic**, Specimen style: its plate, name and counts, then the four quiz modes, Questions, the two
    tick boxes and **Start quiz**. Picking a topic is a selection, not a place.
- **Settings is a word.** The ≡ stays only for the classic menus the Qt app must still offer (progress, notes, open a
  model file, export a figure, help).
- **A trail on item pages**:
  - lesson `Lessons › The coronary circulation` (steps are not places; the lesson's own meta line gives the step);
  - practice `Practice › Lab 6 · Pressure, volume and a breath`;
  - viewer `Models › Kidney with the nephron`;
  - slide `Histology › Epithelium › Simple columnar epithelium`;
  - case `Radiology › Chest radiograph, PA`.

  Every crumb but the last is a link to its collection, so each item is one click from its collection. Front pages
  have none (option 3 shows the room).
- **Back takes places, not steps.** A place is a room page or an item; lesson steps and selections are not places (the
  lesson's own Back and Next move through steps). Back names a room's front page by the room (`Back to Atlas`) and
  an item by what it is (`Back to the lesson`, `the model`, `the slide`, `the film`, `the quiz`). Forward names its
  place too. **Alt+Left / Alt+Right** (Cmd+[ / Cmd+] on a Mac) are Back and Forward. They are bound, listed in
  `aria-keyshortcuts`, and never printed.
- **Rooms remember.** Clicking a room you are not in returns to it as you left it (the open lesson, model, slide, case);
  clicking the room you are in goes to its front page. A remembering room's tooltip says so ("Models: Kidney with the
  nephron, as you left it").
- **Keyboard.** Every navigation control is a link or button in reading order. Each takes a 2 px ring in the text
  colour (`:focus-visible`), the search field included.
- **In the atlas** on the model viewer's part card: the app's existing "Show in the atlas".

### Radiology's front page

`radiology-home` is Radiology's front page, the way `practice-home` is Practice's. A film (`radiology`) is now an item
inside it.

- **What is drawn**, on the 232 line:
  - the exhibit "Radiology", with the case count from `LH_RAD.length` (104);
  - on the left, Region with case counts. "All regions" comes first, then the regions alphabetically, as
    `app/ui/radiology.py` groups them. Thorax is chosen by default.
  - under it, Modality: the modalities in the chosen region with counts, "All" first, then a **Normal anatomy only**
    tick box (findings that end in "anatomy");
  - in the middle, a light box: "Thorax · 20 cases" over a five-column grid of film tiles. Each tile has a black
    film box, a title of up to two lines and "modality · finding". Normal anatomy comes first. The grid scrolls in
    its column when a region does not fit; Thorax fits.
  - on the right, the chosen case: a larger film, its title, "modality · region · plane · finding", the summary,
    "N labels on the film" and **Open the case**.

  A click on a tile chooses it. A double-click or Enter opens it. A filter that hides the chosen case chooses the
  first tile still shown. The data are the app's 104 real cases (`radiology-cases.js`, `window.LH_RAD`) with their
  thumbnails (`assets/images/rad/`, credits in `CREDITS.json`).
- **Wiring:**
  - `PLACE['radiology-home'] = ['radiology', []]` and `SAYS` "Radiology";
  - `SEED`: radiology-home → atlas and radiology → radiology-home;
  - `HOME.radiology = 'radiology-home'`. The film's `Radiology` crumb leads there, and so does Back on a film opened
    on its own.
  - `LEFT.radiology` stays `radiology`, so the rooms bar still reopens the room as you left it.
  - Option 2 narrows the light box to 1000 px and moves the card to 1376.
- **The app today:** `RadiologyBrowser` (`app/ui/radiology.py`) lists the cases grouped by region, with modality,
  region, plane and finding filters behind "Show filters". The front page lays the same list out as a room: the
  region list stays open, modality and the normal-anatomy filter come up front, and plane is left to the case.

## Option 1: Rooms bar

*The top bar made fully clear: six rooms, a Back that says where it goes, and a trail line on item pages.*

Header: lockup · Atlas Lessons Models Radiology Histology Practice 12 · `‹ Back to Atlas ›` · search · Saved views ·
Settings · ≡. On item pages a 14 px trail sits on its own line just under the bar (top 78).

At 1280:
- the wordmark drops to the mark;
- search narrows and its placeholder shortens to "Search";
- Back steps 26 px clear of the rooms;
- nothing wraps.

Back and Forward share a 200 px slot (`.hist.named`), as wide as the longest target, so Forward hugs the label and
search never moves between screens.

## Option 2: Side rail

*The rooms in a slim rail down the left edge of the wall; the header keeps Back, the trail and search.*

A 104 px rail, lettered on the same wall with a hairline on its right edge: the mark, then the six rooms as icon over
name (current: text colour and the brass bar under the name; Practice carries its count), and at the foot Saved views,
Settings and Menu. The room moves right by 104 px. The header holds the named Back and Forward (the same slot as
option 1), then a hairline, then the trail on item pages, then search. It has the most free space and the steadiest
place for each room, but it costs 104 px of width on every screen.

## Option 3: Lobby

*A home room the app opens to, with every room a doorway from it, and every room's trail starting at the Lobby.*

The lobby: the lit body in the middle; Continue where you left off and Review on the left; the six rooms as doorways
around the body (picture, name, one real count); Recent places (the app's place history) and Saved views on the right.
In every room the header starts `[mark] Lobby › Lessons › The coronary circulation`, so the way home is the first word
on screen. ‹ › and search follow, then the six rooms (still one click apart), then a hairline, Saved views, Settings
and ≡. Saved views used to sit beside the trail on the Atlas only, where it read as a third crumb. It is now in the
tools on every screen.

At 1280:
- Saved views folds to its bookmark icon;
- the trail drops its middle crumb and cuts the place's name at 150 px. The page's title gives it in full.

## Recommendation

**Option 1, Rooms bar.** It fixes what was actually broken (no Practice, an unnamed Back, no "where am I" inside a
room, an unlabelled Settings) without moving the model or adding a room to walk through, and it holds at 1280 with
room to spare. Option 3's lobby is the friendliest first launch, so it is worth taking its Continue, Review and Recent
places into the Lessons front page or a first-run state, rather than making every session start in a lobby.

## Renders (`renders/checkpoint-3/nav/`, Gallery slate at 2×)

- `before_{atlas,lessons,lesson,histology-library,viewer}`: the base as copied.
- `<n>_{atlas,lessons,lesson,histology-library,viewer,practice,practice-home,histology,radiology,settings}` for
  n = 1, 2, 3, and `3_lobby`; `<n>_radiology-home` and `1_radiology-home_umber` for Radiology's front page. These were re-rendered in the second pass with the first pass's jobs.
- `renders/checkpoint-3/nav2/<n>_<fix>_before|after`: 1:1 crops at 2× of each second-pass fix:
  - `back-lesson`, `back-histology`, `back-1280`: option 1's Back slot;
  - `focus`: Tab rings;
  - `practice-home`: the Practice front page, against the question screen Practice used to open;
  - `2_back`: option 2's named Back;
  - `3_saved-views`, `3_saved-views-1280`: option 3's Saved views.
- `<n>_atlas_1280`: a 1280 × 800 window. The chrome is laid out for 1280; the room under it is the 1920 room scaled to
  fit (the rooms' own small-window layout is outside this topic).
- `<n>_atlas_umber`: Umber, whose accent is blue, so every current marker and count is checked against a non-brass
  accent.
- `<n>_atlas_crop`, `<n>_lesson_crop`: the chrome at 1:1 (for option 2 the rail and header corner).
- `map_<n>`: the places and the ways between them (SVG in `maps.py` in the scratch folder, rasterised with
  `tools/raster_svg.mjs`).

## Tasks: clicks today and in each option

Mouse clicks; typing is not counted. "App" is v4.0.8, "Base" is the mockup before this round. Options 1 to 3 are now
measured: each task was done by clicking in Chromium in every option. "Fresh" means nothing is open in that room
yet; otherwise the made-up session's open items count. The first pass's counts are in brackets where they changed.

| # | Task | App | Base | 1 | 2 | 3 |
|---|---|---|---|---|---|---|
| 1 | Look at the biceps from another room | 2 | 2 | 2 | 2 | 2 |
| 2 | Continue the last lesson | 1–2 | 2 | 1 | 1 | 1 (lobby: Continue) |
| 3 | Review the 12 due | 4 (gear, Study, Quiz, Review) | 1, destination unclear | 2 (Practice, Review what is due) | 2 | 1 from the lobby, 2 from a room |
| 4 | Kidney model at its Corpuscle view | 4 | 4 | 3 fresh (Models, Kidney, Corpuscle), 2 when the kidney is open [4] | same | same |
| 5 | Jejunum slides, then the jejunum model | 7 | 4 | 4 (not drawn) | 4 | 4 |
| 6 | Open a chest film | 2 | 2 | 2 fresh, 1 when a case is open | same | same |
| 7 | Change the wall colour | 4+ | 3 (≡, Settings, wall) | 2 (Settings, the wall) | 2 | 2 |
| 8 | Back to the atlas as you left it, after reading 3 lesson steps | 4 Backs, or Explore: 1 | 1, state not shown | 1 (`Back to Atlas`, named; also Alt+Left) | 1 | 1 |
| 9 | Start a heart quiz | 6 | no way in | 3 (Practice, Cardiovascular system, Start quiz) [4] | 3 | 3 |
| 10 | Save a view, later reopen it | 3 + 2 | 3 + 2 | 3 + 2 | 3 + 2 | 3 + 2 (or 1 from the lobby) |
| 11 | From the kidney model, the renal artery in the body | 2 (right-click, Show in the atlas) | no way | 1 (In the atlas) | 1 | 1 |
| 12 | End a lab practice, back to its lesson | 2 | no way drawn | 1 (`Back to the lesson`) | 1 | 1 |
| 13 | From the kidney in the viewer, another model | 3 | Back only | 2 (trail `Models`, the model; + Open model) | 2 | 2 |
| 14 | From a micrograph, the catalogue, then another tissue | 3 | Back only | 2 (trail `Histology`, the tissue) | 2 | 2 |
| 15 | Find Settings, change the wall | 4+ | 3 | 2 | 2 (rail foot) | 2 |
| 16 | A review from any room | 4 | 1, destination unclear | 2 (Practice, Review what is due) | 2 | 2 (bar, or Lobby then Review) |

## Carrying the chosen option into `app/specimen/index.html`

Everything is in three blocks of this file:

1. **CSS**: `<style id="nav-cp3">` just before `</head>`. The shared rules come first, then one commented section per
   option, then `[data-window]` (only needed for the 1280 render). For one option, keep the shared rules and its own
   section, and drop the `[data-variant="n"]` prefixes.
2. **JS**: `<script id="nav-cp3-js">` after the base's main script. It holds `ROOMS` and `PLACE` (room, trail and Back
   target per screen) and rebuilds every `[data-chrome]` header. To merge, replace the base's `[data-chrome]` builder
   (`NAV` and its `forEach`) with the chosen branch of this one, and drop the base's "Review 12 due" button. It also
   adds the viewer's **In the atlas** button and defines `navCompact()` (1280 render only).
3. **Markup**:
   - all options: the `PRACTICE HOME` section (after `PRACTICE`), filled by the nav script (`TOPICS`, `LABP`,
     `pick`);
   - option 3 only: the `LOBBY` section (before `SETTINGS`);
   - both screens are added to the screen display rule.
4. **Wiring** (end of the nav script): the place history (`SEED`, `H`, `sessionStorage`), the rooms' memory (`LEFT`,
   `mem`), `wire()` for the rooms' own buttons, and the click and key handlers. In the Qt app these are
   `PlaceHistory`, `_show_nav_page` and shortcuts on the main window (`QKeySequence.Back`/`Forward`, plus Alt+Left/Right
   on every platform).
   It uses existing plates and images only (`body_muscles`, `body_skeleton`, `heart_home_clean`, `kidney_v_kidney`,
   `thorax_chest`, `cxr_pa.jpg`, `histo_simple_columnar.jpg`).

`render_mockups.mjs` and `render_all.py` would need `practice-home` added to `SCREENS`, and `lobby` for option 3.

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
- Option 2's rail moves every room 104 px right; nothing collides at 1920, but the viewer and the histology catalogue
  have the least slack.
- Fixed in the second pass:
  - Option 1's moving Back: Back and Forward now share a fixed slot.
  - Option 3's Saved views beside the trail: it is now in the tools.
  - Practice's undrawn front page: `practice-home` now exists.
- Radiology's front page now exists (`radiology-home`), and the film's `Radiology` crumb leads up to it. But every
  case opens the one drawn film page (the chest PA), whichever tile was chosen.
- Only one slide, one model and one lesson are drawn. "Another tissue" and "another model" reopen the same page, and
  the lab practice's Back goes to the coronary lesson.
- Rooms remember, which surprises some students the first time. A tooltip says so, and the trail gives the front page
  in one click. A first-run hint could teach it, but none is drawn.
- Option 3 keeps Back as an icon (its tooltip names the place), because its "how did I get here" is the trail from the
  Lobby. At 1280 the header has no room for a named Back.
- The Practice front page's numbers (due by topic, results, most missed) are a made-up session, chosen to add up (the
  due counts by topic sum to 12).
- The saved-view names in the lobby and the Back targets are a made-up session, chosen to be consistent across
  screens.
