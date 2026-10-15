# Search: port note (checkpoint 3)

Copy: `app/specimen-search/index.html`, the apply3 base (`S0/apply3/base.html`) with two extra lines and three files
beside it. Open `index.html?screen=atlas&variant=1|2|3`. Click the field, type, hover, click. Arrows, Enter and Esc also
work, and Ctrl+K is bound but never shown. Set up states with `&q=<query>&state=open|chosen&hover=<row>|auto`, and see
what the app does today with `&matcher=today`.

| File | What it is |
|---|---|
| `search-index.js` | 802 real entries from the app's `SearchIndex`: every entry that any 3+ letter prefix of the demo queries returns, plus the 16 muscles the atlas figure has points for. Extracted by `S/extract.py` from `data/`. Fields: kind, title, subtitle, alt, system. |
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
  comes "n more lessons", which really opens the rest in place. Lists scroll with no scrollbar and no foot line.
- **None:** "Nothing for "wisdom tooth"." Then "Check the spelling, or try one word or the Latin name." Then links to
  browse Systems, Lessons, Radiology and Histology. **Typo:** "No exact match for "bycep". Close spellings:".
- **Nothing in view** (options 1 and 2, "coronary" on the muscle figure): "None of these is in this view. Choosing one
  shows it." It is honest: the coronary arteries are not drawn on this figure.
- **Chosen:** the search closes and the structure is selected. A quiet link under the field, "72 results for "bic"",
  reopens the last results with one click (`.sx-again`).
- **Choosing other kinds** goes to that kind's room in the mockup (Lessons, Radiology, Histology, Models), as
  `on_search_activated` does.

**Circles.** These are `.ndot` from checkpoint 2 labels option 3:
- 18 px, a `leader` ring on `stage-bottom`, with the number in `text`;
- the current selection is filled brass;
- hovered or keyboard-active: a `text` ring with a gap;
- a structure not in view gets a dashed `text-3` ring and "not in this view".

The circles sit on the plate's anchors (`LH_PLATES.anchors.hero26_sel_7cc8da`, both sides). `ANCHOR` in search.js maps
entry titles to anchor keys.

## Option 1: On the body
- **CSS:** the shared block plus `[data-variant="1"]`. When merging, drop the prefix.
- **Layout:** the list is lettered at left 1262, top 200, 600 wide, in the right-hand column. The depth rule fades out
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
- **Hover:** the name is underlined in `text` and its circle grows on the body. **Close:** Esc, "Close the index", a
  click on the body or the wall, or choosing; the room comes back.
- **Qt:** the 3D view can be scaled into the right column with a viewport rect (the camera stays put) and dimmed in the
  background pass. The index is a wall-lettered widget over the stage, in columns.

## Option 3: In the title
- **CSS:** `[data-variant="3"]`. The header field is 200 wide and only a way in. A click on it or on the room title
  (`.exhibit h1`, `contentEditable` while open) puts the caret in the title. The empty title shows "Search" in `text-3`.
- **Layout:**
  - The line under the title reads "72 found · back to Muscles, anterior view".
  - Results are lettered at left 40, top 232, 500 wide, where Systems and the wall label were; those fade out while
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
