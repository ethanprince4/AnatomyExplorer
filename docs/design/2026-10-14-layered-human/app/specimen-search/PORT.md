# Search: port note (checkpoint 3)

Copy: `app/specimen-search/index.html`, the main mockup with checkpoint 2's decisions applied (15 October), plus two
extra lines and three files beside it. Open `index.html?screen=atlas&variant=1|2|3`. Click the field, type, hover,
click. Arrows, Enter and Esc also work, and Ctrl+K is bound but never shown. Set up states with
`&q=<query>&state=open|chosen&hover=<row>|auto`, and see what the app does today with `&matcher=today`.

| File | What it is |
|---|---|
| `search-index.js` | 802 real entries from the app's `SearchIndex`: every entry that any 3+ letter prefix of the demo queries returns, plus the 16 muscles the atlas figure has points for. Taken on 15 October from the index the app builds from `data/`. Fields: kind, title, subtitle, alt, system. |
| `search.js` | The matcher: a line-for-line port of `app/search.py` `search()`/`_score()`. It gives the same counts as the Python index for every demo query. It also holds the presentation (kinds, folding, the circles) and the three options. |
| `search.css` | Shared rules, then one block per option under `html[data-variant]`. Scheme tokens only. |

## The three options

| | Name | In one sentence |
|---|---|---|
| 1 | **On the body** | As you type, the matching structures get numbered circles on the model, and a short list lettered beside the body names them, with lessons, radiology and clinical notes as quieter lines below. |
| 2 | **The index** | Search turns the room into an atlas index lettered on the wall: the body steps back and dims, and the results stand in columns by kind with the matching letters marked. |
| 3 | **In the title** | The room's title is the search: the query is typed into the title, results letter themselves under it, and the one you choose becomes the title. |

**Recommendation: 1, On the body.** It is the only option where search answers the question an atlas user is really
asking, "where is it?". It answers on the model itself, in the numbered-circle language the owner already chose for
labels, while the room stays as it is. The index (2) is the most beautiful with many results and could be its "all
results" view later. The title (3) is the calmest, but it hides Systems and the wall label while you search.

## Shared by all three (carry these whichever option wins)

**Field at rest.** In `base.html` the header builds `<div class="find">…</div>`. `search.js` `init()` turns it into
`svg + <input class="sx-in">` with:
- `aria-keyshortcuts="Control+K"`, and a tooltip that names Ctrl+K;
- a placeholder in `text-2`, not `text-3`, so it reads as a place to click;
- a hairline that lifts to `text-2` on hover and `text` on focus, and a brass caret.

No key is printed. Placeholders: 1 "Search anatomy, lessons, radiology", 2 "Search the index", 3 "Search". To merge, put
the input straight into the header template in `index.html` (the `.find` line in the `[data-chrome]` loop) and drop
the swap in `init()`.

**Matcher (`search()` in search.js = `SearchIndex.search`).** Folding, synonyms, the 100/90/80/75/65 scores, the kind
bonus, the attachment and reference penalties, the length penalty, the 150 limit and the difflib fallback are all as
in the app.
- **ADDITION (not in the app today):** in the typo fallback, also compare the query with each word's first
  `len(query)` letters. In `app/search.py` `search()`, inside the `if not results and len(q) >= 4` loop:
  `r = max(SequenceMatcher(None, q, w).ratio(), SequenceMatcher(None, q, w[:len(q)]).ratio() if len(w) > len(q) else 0)`.
- With it, "bycep" goes from 0 results to 19, and "deltiod" (19), "coronery" (20) and "trapezus" (15) are unchanged.
  Without it the `bycep` state is the `none` state (`&matcher=today`).

**Presentation (`group()`, `fold()`, `meta()`, `mark()`).**
- **Kinds** are named once, in the app's room words, in this order: Structures (structure, group, landmark), Lessons,
  Radiology, Histology, Models, Clinical.
- **Folding.** A muscle's parts fold under it, as in a printed index: "Biceps brachii muscle, Muscular system · 4 parts,
  long head, short head and attachments". The second "Biceps brachii muscle" group (the attachments) folds into the
  first. A muscle known only by its attachments (biceps femoris) heads its own parts and borrows its system line from
  a real part. Scores are untouched; folding only changes how results are shown.
- **Meta lines** follow PORT F9 from checkpoint 2: the kind is not repeated; groups read "{system} · {n} parts";
  " — " in a title shows as ", ".
- **Matching letters.** In names they are set heavier (weight 640); option 2 also underlines them in brass. When only
  the Latin matched, the Latin is marked.
- **Open, nothing typed:**
  - "In this view": the structures labelled on screen (on the atlas: Biceps brachii, Deltoid, Serratus anterior,
    Rectus abdominis).
  - "Recent": places from `PlaceHistory` (`app/ui/places.py`). In the app this history lasts one session; it is not
    saved.
  - One line: "Type a name, a Latin name or a lesson."
- **Many results:** each kind shows a few (1: 6 structures and 2 of each other kind; 2: 16 and 3; 3: 5 and 2). Then
  comes "n more lessons", which really opens the rest in place. A kind with exactly one row over its cap shows that
  row instead of "1 more" (the link would take the row's room).
- **Nothing is ever cut through a line (fix pass 2).** The list ends on its own "more" links:
  - **Fitted to the room.** After the list is built (`build()`), `search.js` measures it. While it is taller than its
    box, the other kinds give up rows, the lowest kind first, down to one each. Then the structures give up rows,
    down to three. Trims that would leave a lone "1 more" come last. At 1920×1080 every demo state now fits with no
    scrolling. The list is measured again once the fonts have loaded.
  - **Box:** the list ends 44 px above the room's foot, level with the wall label's buttons: options 1 and 3 use
    `max-height: calc(100% - top - 44px)`; in option 2 the columns (`.sx-cols`) use `max-height: calc(100% - 136px)`.
  - **Overflow** (after "n more" opens a kind, or in a shorter window): the box scrolls under the wall's own fade, a
    CSS mask (`.sx-over`), so the wall shows through and nothing is painted over it. The foot fades over 112 px while
    more is below (`.sx-below`); the head fades over 48 px once scrolled (`.sx-above`); at the very end the foot is
    clear, so the list closes on its last link. The scrollbar is thin, with a `line-2` thumb on no track
    (`scrollbar-width: thin`).
  - Hover leaders are not drawn to a row under the fade. Opening "n more" keeps the scroll position.
  - **Qt:** the result widget does the same: take the available height, then reduce the per-kind caps in the same
    order until the rows fit. For overflow, paint the column into a layer and multiply it by a vertical
    `QLinearGradient` alpha (`CompositionMode_DestinationIn`), not a band in the wall colour. Use a thin `QScrollBar`
    with a `line-2` handle and no track.
- **None:** "Nothing for "wisdom tooth"." Then "Check the spelling, or try one word or the Latin name." Then links to
  browse Systems, Lessons, Radiology and Histology. **Typo:** "No exact match for "bycep". Close spellings:".
- **Nothing in view** (options 1 and 2, "coronary" on the muscle figure): "None of these is on the figure as shown. Each
  says where it is." Every row then says where (see "Search 3" below).
- **Chosen:** the search closes and the structure is selected. A quiet link under the field, "72 results for "bic"",
  reopens the last results with one click (`.sx-again`).
- **Choosing other kinds** goes to that kind's room in the mockup (Lessons, Radiology, Histology, Models), as
  `on_search_activated` does.

**Circles.** These are `.ndot` from checkpoint 2 labels option 3:
- 18 px, a `leader` ring on `stage-bottom`, with the number in `text`;
- the current selection is filled brass;
- hovered or keyboard-active: a `text` ring with a gap;
- a structure not in view gets a dashed `text-3` ring and "not in this view".
- The base page's global `.is-cur::after` (the rooms' brass underline) must not reach the circles:
  `.ndot.is-cur::after { content: none; }`. The first pass let it draw a brass bar under every current circle.

The circles sit on the plate's anchors (`LH_PLATES.anchors.hero26_sel_7cc8da`, both sides). `ANCHOR` in search.js maps
entry titles to anchor keys.

## Option 1: On the body
- **CSS:** the shared block plus `[data-variant="1"]`. When merging, drop the prefix.
- **Layout:** the list is lettered at left 1262, top 200, 600 wide, in the right-hand column. The box starts at 1256
  with 6 px of padding so the active circle's ring is not clipped. It ends at 1036. The depth rule fades out
  while the list is up and comes back on close.
  - Structures: number, name (Literata 21), Latin (italic 15), meta and parts (Fira 13).
  - Other kinds: one line each under a hairline, with the kind in a 110 px left column.
  - Structures in view come first, numbered top to bottom as on the body. Tag labels hide while results show; the
    circles replace them.
- **Hover** on a row or a circle: the name gets a `text` underline, the circle a `text` ring, and one leader runs from
  the row's number to the circle on the near arm (`paintActive()`). Click either to choose.
- **Close:** Esc, a click on the wall, or choosing.
- **Qt:** do not use the drop-down in `SearchPanel` (`app/ui/search_panel.py`). Draw a wall-lettered result column
  over the 3D view: a frameless transparent widget, the same approach `system/BUILD-NOTES.md` gives for wall text.
  - Rows are painted by a new delegate (`ResultDelegate` today draws rounded `SURFACE` fills; remove them).
  - Circles: the viewport projects each result's structure to the screen. Use `Viewport.project` (`app/viewport.py:667`)
    with the same visibility test `_update_structure_labels` (714) uses, and draw the circles in
    `_paint_structure_labels` (745) in place of tag labels while a query is active.
  - "Not in this view" means not visible at the current depth and camera. Showing a structure is today's
    `select_and_focus` with X-ray (`main_window.py:1529`).
  - New: an "in view" query per result (picking buffer or depth test). The app does not have one today.

## Option 2: The index
- **CSS:** `[data-variant="2"]`.
  - `.stage` and `.pool` take `transform: translate(668px, 40px) scale(.68)` from origin 980 568. The plate goes to
    opacity .38.
  - The title, Systems, the wall label, the rule and the dock fade out.
- **Layout:** the query is lettered at Literata 64/300 where the room title was, with "72 entries" beside it and "Close
  the index" on the right.
  - From the content top line (232), Structures runs in two 416 px columns and the other kinds in a third.
  - Entries: name and marked letters (Literata 18), Latin (italic 15), then meta and parts run in.
  - Structures in view are numbered, and the same numbers stand on the small body (circles at 1.4×).
- **Hover:** the name is underlined in `text` (the brass underline on the matched letters gives way to it, so the
  row has one line, not two) and its circle grows on the body. The columns box starts 8 px left, with 8 px of
  padding, so the circles' rings are not clipped. **Close:** Esc, "Close the index", a
  click on the body or the wall, or choosing; the room comes back.
- **Qt:** the 3D view can be scaled into the right column with a viewport rect (the camera stays put) and dimmed in the
  background pass. The index is a wall-lettered widget over the stage, in columns.

## Option 3: In the title
- **CSS:** `[data-variant="3"]`. The header field is 200 wide and only a way in. A click on it or on the room title
  (`.exhibit h1`, `contentEditable` while open) puts the caret in the title. The empty title shows "Search" in `text-3`.
- **Layout:**
  - The line under the title reads "72 found · back to Muscles, anterior view".
  - Results are lettered at left 40, top 232, 500 wide (ending at 1036), where Systems and the wall label were; those fade out while
    open. The depth rule and dock stay.
  - Structures: name (Literata 23), Latin (16), meta.
- **Hover** draws a single leader from the end of the name to a ring on the structure, one at a time. Base labels stay
  until you type.
- **Choose:** the title becomes "Biceps brachii", with the line "Musculus biceps brachii · back to Muscles, anterior
  view". The wall label then drops its own name and Latin, since the title says them. **Close:** Esc, "back to …", or a
  click on the wall.
- **Qt:** the room title (today the workspace header) becomes an editable `QLineEdit` styled as Literata 44 with no
  frame. The result column is the same widget as option 1, on the left. The hover leader uses `Viewport.project`.

## What the mockup cannot show honestly
- Only the biceps figure exists (`hero26_sel_*`). Choosing another structure in the mockup renames the wall label but
  does not change the figure.
- The muscle figure has points for 16 muscles only, so other structures that are visible (bones, vessels on the
  surface) get no circle here. The app would place one for anything visible.
- "Recent" uses the mockup's own room titles. Recent searches as such are not stored by the app.
- The index slice is 802 of 4,717 entries. Queries outside the demo words return fewer results than the app would.

## Search 3: where it is, and search in the other rooms

### Rows that are not in view say where they are
A structure row with no circle gets two quiet lines under its meta, in all three options (option 2 runs them in):
- **Where**, from the app's data: "On the back of the heart, 85% deep", "On the back, 20% deep", "Inside the heart, in the
  aortic valve, 70% deep", "In the chest, behind the ribs, 46% deep". The percentage is the structure's relative depth
  from `DepthIndex` (`app/depth.py`, cached in `data/anatomy/depth.npz`); "back"/"front of the heart" compare the
  structure's centroid (`anatomy.json`) with the body or the heart's centre (z, + is the front); "inside" is a valve or
  leaflet. Groups take their shallowest muscular part. The mockup carries these values, worked out once on 15 October, as
  `LH_WHERE` at the end of `search-index.js`; the app has the depth index and the centroids loaded, so the port reads
  them there.
- **What choosing does**, one of three, in this order:
  1. *Peel*: "Choosing it peels to 40%". The gauge steps to the stop (its own `]` and `[`), the plate becomes the
     plate at that depth, and a brass circle sits on the structure. Only where the mockup can show it: `Heart` on
     `peel40_ids` (picking-buffer anchors).
  2. *Turn*: "Choosing it turns the body round" (biceps femoris, 48%: present at 26%), or "... and lifts the cut to 16%"
     (trapezius, 20%: the 26% cut has peeled it). `body_back`, circles placed by eye on clearly visible muscle.
  3. *Room*: where no picture here shows it, the row names the room that does. "Shown in the lesson The coronary
     circulation, step 2" (left coronary artery: the lesson plate has its projected point, `lmain`); "Shown whole on the
     Heart model" for the other heart structures (the Models room opens with the query, narrowed to the Heart).
  Otherwise: "Choosing it lifts the cut to 16%" when the structure is shallower than the cut (proposed; the mockup
  only selects it), else "Choosing it shows it through what lies in front" (today's `select_and_focus(sids, xray=True)`).
- Not shown: the right coronary artery is 46% deep, so a 55% cut removes it and at 40% the ribs cover it; no plate
  here shows it, so it goes to the Heart model. The left coronary stem (65%) lies under the pulmonary trunk on
  `peel_55_skeleton`, so it is not circled there.
- **After choosing**, the search closes, the wall label takes the structure's name, Latin, "Where" and "System" (the
  biceps facts are dropped), and focus stays in the field with the query; typing or the down arrow reopens the list.
  Searching again restores the figure the circles belong to. Esc clears.

### Rows found by their text say what they mention
A lesson, film, case or tissue whose name and subtitle don't hold the query, but whose text does, says why it is
there, in place of its details line, so the row keeps to one line: "The liver · mentions coronary ligaments", "The
reflex arc · mentions the long head of biceps brachii", "Balanced ischemia: SPECT, PET and angiography · mentions the
severe coronary stenosis". In the Lessons room, where each lesson has a full line, the phrase follows the details.
The phrase is, in this order (`why()` in `search.js`; in the app, a helper beside `SearchIndex` reading the same
`alt` text it already searches):
1. The structure name the word sits in, as the text's list of structures has it: a capitalised word and the
   lower-case words after it, up to six words ("Inferior papillary muscle of left ventricle"). Words that open a
   sentence rather than a name don't count ("Behind the heart", "Four muscles", "Explain…", and the sources' own
   "Source-marked …"). A list run together ("Hip bone urethra corpus cavernosum") gives the name up to the word.
2. Else the word with the describing word beside it: "coronary ligaments", "papillary muscles", "bicuspid aortic valve",
   "heart failure".
3. Else the word alone.
Abbreviations and nerve numerals keep their capitals ("the facial nerve VII", "the LAD anterior interventricular
artery"). A case names conditions, so it takes no article ("mentions heart failure"), and neither does a plural
("mentions papillary muscles").

### One rule for every room (option 1)
**Answers appear where the room shows its things.** The room's own list narrows in place, circles go on the room's
picture (numbered in the list's order), and matches from the other rooms sit below as quieter lines (room word in
`text-3`, two names, "and n more"). The same field, the same keys (arrows, Enter, Esc, Ctrl+K, never printed).
| Room | Typing narrows | Circles on | Other rooms go |
|---|---|---|---|
| Models viewer | the parts tree, with ancestors kept (in `text-3`); the tree's own filter line shows the query and "3 parts" | the plate's labelled points that match; tags hide | under the tree |
| Models collection | the tiles (name and caption) | — | under the tiles |
| Histology library | the tissue tiles; groups with none hide | — | under the tiles |
| Histology slide | the key list (non-matches dim, so the numbers keep their pins) | the matching pins get a ring | under the key list |
| Lessons | the labs give way to the matching lessons, as lines | — | under the list |
| Lesson, Radiology | nothing narrows (the field shows "Back to “coronary”" after arriving from a result) | — | — |
| Practice | **search answers nothing while a question is open**: it would give the answer away. Proposed: the field stays, placeholder "Search after this question". Not built. |
Choosing one of the room's own things selects it there (viewer part, tissue, model) and leaves "Back to “q”" under
the field; choosing another room's line opens that room with the query.

### States (all `?variant=1&scheme=slate&...`)
| Render (`renders/checkpoint-3/search3/`) | Parameters |
|---|---|
| `1_atlas_coronary-where` (+ `_umber`) | `q=coronary&hover=auto` |
| `1_atlas_heart-peeled` | `q=heart&state=chosen&pick=0` |
| `1_atlas_trapezius-back` | `q=trapezius&state=chosen&pick=0` |
| `1_atlas_bic-femoris-hover` / `-back` | `q=bic&hover=2` / `q=bic&state=chosen&pick=2` |
| `1_lesson_coronary-chosen` | `screen=lesson&q=coronary&state=chosen` |
| `1_viewer_renal` | `screen=viewer&q=renal&hover=auto` |
| `1_histology-library_muscle` | `screen=histology-library&q=muscle&hover=auto` |
| `1_histology_nucleus` | `screen=histology&q=nucleus` |
| `1_lessons_coronary` | `screen=lessons&q=coronary&hover=auto` |
| `1_models_coronary` | `screen=models&q=coronary` |
`pick=<n>` chooses the n-th row of the list (0-based) on load.

### What the Qt app needs
- **Where:** `DepthIndex.depth[sid]` is the depth; `SceneState.depth_cut` (`app/state.py`) the cut. A result is in view
  when `SceneState.visible_mask()[sid]` and the picking test of option 1 say so. The facing test needs the camera:
  compare the structure's centroid with the view direction in `Viewport`. Phrase from `DISSECTION_STOPS`
  (`app/ui/view_panel.py`).
- **Peel/turn on choose:** in `MainWindow.on_search_activated` (`main_window.py:1529`), before `select_and_focus`, set
  the cut to the deepest stop at or above the structure's depth (`ViewPanel.set_depth` → `SceneState.set_depth`), or lift
  it when the structure is shallower than the cut; if the structure faces away, orbit the camera 180° about the body's
  axis. Fall back to X-ray when something still covers it (picking test). Circle with `Viewport.project`.
- **Room offers:** a small table from structure to lesson step / model (the lesson's `structures` lists and
  `data/content/model_summaries.json` already hold this).
- **Rooms:** each room exposes "narrow to this query" on the widget that owns its list: `ModelView._filter_tree`
  (`app/ui/model_view.py:606`, already a parts filter: feed it the header query), `HistologyBrowser._filter`
  (`app/ui/histology.py:153`), `LessonsPanel` (`app/ui/lessons.py`), the Models catalogue `ModelCatalogPanel`
  (`app/ui/search_panel.py:256`), `HistologyViewer` for slide labels. The "other rooms" lines are the
  `SearchIndex.search` results minus the room's own kind. `PracticePanel` (`app/ui/practice.py`) ignores the query
  while a question is open.

### Weak or unresolved
- The heart's circle on `peel40_ids` marks the heart, not a vessel; at body scale the coronaries are too small to point
  at. The plate has an anchor for each half of the heart a few pixels apart, so the circle sits on the larger.
- `body_back` circles are by eye; the back plate's own depth is the muscle view, so "16%" is the gauge, not a new render.
- The viewer's third circle (Renal capsule) sits under the collapsed Kidney: its row is listed only while a search
  finds it, and the Kidney opens round it, as the Qt tree filter searches closed groups.
- Rows that only lift the cut, or only show through in X-ray, have no picture in the mockup: choosing them renames the
  wall label only.
- Options 2 and 3 carry the where lines and the peel/turn/room choices, but the room search is built for option 1 only.
