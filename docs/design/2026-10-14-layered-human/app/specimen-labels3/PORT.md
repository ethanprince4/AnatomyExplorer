# Labels, checkpoint 3: the owner's mixture, and where "Show all" lives

This folder is a copy of `app/specimen/index.html` as it stood once checkpoint 2's decisions were applied (15 October),
with the owner's labels mixture built into the atlas, a new section screen, the lesson and practice. `?variant=1|2|3`
sets `<html data-variant>` (default 1). Everything outside labels, the lesson and practice is as the base has it.

| `?` | Values |
|---|---|
| `variant` | `1` Dock pair, `2` Wall line, `3` Corner key |
| `screen` | `atlas`, `section` (new), `lesson`, `practice`, and every base screen |
| `lstate` | atlas and section: `circles` (only the selected rail), `one` (plus one rail: Rectus femoris on the atlas, Trapezius on the section), `all` (Show all). Lesson: `default`, `term` (the term "anterior interventricular branch" hovered), `all` (Labels on, Show all). Practice: `wrong1`, `wrong2` (the default), `right` |

Everything is live, too: click a circle, a key entry, Show all, the dock's Labels button; hover a circle or a lesson
term; Tab through the circles; Esc closes every rail.

## The mixture (all three options)

- **Labels on** draws numbered circles on the body and nothing else. Numbers are fixed for the view: top to bottom,
  then left to right (cp2's rule).
- **A circle is a button.** `<button class="ndot" aria-expanded="false" aria-label="10, Rectus femoris">`, an 18 px
  disc in a 28 px hit area, inserted in number order so Tab walks 1, 2, 3. Focus ring: 2 px `text_2` (the app's one
  focus ring, never brass).
  - closed: `stage_bottom` disc, 1 px `leader` ring, `text` digit (cp2's dot);
  - open: the disc turns to `text` with a `stage_bottom` digit, so open circles read at a glance;
  - selected: `accent` disc, `on_accent` digit, open or closed; its rail is open by default and its name is weight 600.
- **Click** toggles the circle's caption rail: the name on a rail beside the specimen, joined by a knee leader that
  stops 2 px short of the disc. Open names stack on their side in anchor-height order at a 30 px pitch, with a hairline
  spine from the first open name to the last: checkpoint 2's option 2, drawn only for the open ones.
- **Hover or focus** a closed circle: its rail is drawn faint (name in `text_3`, leader at 50 %) until clicked.
- **Show all** opens every rail and then reads **Hide all**. **Esc** closes every rail, the selected one too.

## The three options

| | Name | What it is |
|---|---|---|
| 1 | Dock pair | Show all is the second half of the dock's Labels control, there only while Labels is on. |
| 2 | Wall line | The room's caption line ends "· 12 labels · Show all" while Labels is on. |
| 3 | Corner key | A compact numbered key in the top right corner, level with the title, headed "Labels  Show all"; a key entry opens its rail exactly like its circle. |

**Recommendation: option 1, Dock pair.** It puts Show all on the Labels button itself, so the link is plain without
any extra words on the wall, and the dock is the same in every 3D room, so it works the same in the atlas, the section,
a lesson and the model viewer. Option 2 depends on each room's caption and sits far from the circles. Option 3 is well
placed, but it brings back the list of names that the owner's idea removes.

- **Option 1, Dock pair.** While Labels is on, the dock's Labels button gets a second half, "Show all", with no
  divider: the 2 px bar runs on under it, brass under Labels (on) and the line colour under Show all, so the two read
  as one control. The dock grows by about 90 px while Labels is on and stays centred. Nothing new on the wall.
- **Option 2, Wall line.** The caption line under the title ends "· 12 labels · Show all" (atlas), "· 18 labels · Show
  all" (section) or, in a lesson, the step line ends "· 3 labels · Show all". Show all is weight 500 with a `leader`
  hairline under it. It stays on one line, so nothing moves when Labels is turned on.
- **Option 3, Corner key.** Checkpoint 2's key moves out of the left column, where it crowded Systems, to the top right
  corner, level with the title, across the page from it. It is a compact grid whose number order runs down the columns
  (4 columns: 3 rows for 12 labels, 5 rows for 18; 1 column for a lesson's 3). Its head is "Labels  Show all". Each
  entry is a button with `aria-expanded`: it opens its rail exactly like its circle, and hovering it draws that rail
  faint. Names on the right rail stay below the key.

### Measured (1x px, from the DOM boxes of every render)

The rails and circles are the same in all three options, so the leaders are the same too.

| State | Rails | Longest leader | Names pushed off their side | Overlaps |
|---|---|---|---|---|
| atlas, circles | 1 (Biceps brachii) | 164 | none | none |
| atlas, one | 2 (+ Rectus femoris) | 207 | none | none |
| atlas, all | 12 | 260 | none | none |
| section, circles | 1 (Left ventricle) | 468 | none | none |
| section, all | 18 | 608 | none | none |
| lesson, term | 1 (Anterior interventricular artery) | 200 | none | none |
| lesson, all | 3 | 241 | none | none |

- **The gauge.** The rightmost rail name on the atlas ends at x 1383, and the gauge's box starts at 1540: 157 px clear
  in every state. Option 1's control is in the dock, and option 2's is in the top-left caption. Option 3's key
  (x 1270–1880, y 112–216) ends 16 px above the gauge's box (232), and about 24 px above the "Superficial" cap at its
  top. That is the tightest gap in the set, and there is no collision. The section has no gauge.
- **Overlaps checked:** name and name, name and circle, and each name against the gauge, the dock, the wall label, the
  title block, Systems and the key. None in any state of any option. The circles never overlap: the closest pair is the
  lesson's 1 and 2 (Left coronary artery and Circumflex artery), whose centres are 21 px apart, which leaves a 3 px gap
  between the 18 px discs. Their 28 px hit areas overlap by 7 px; the later one wins.
- **Side:** every name stays on the side of its anchor (split at the image's centre). The lesson uses only the right
  rail (x 1652), because all three anchors are right of the heart's centre; its longest name ends at x 1860, 20 px
  inside the margin.
- **The hardest scheme is Umber** (`*_atlas_all_umber`). Its accent is pale blue, so the selected circle (pale blue)
  and the open circles (the text colour) are both light discs, and they are told apart only by hue. Weight 600 on the
  selected name helps. If that is too weak, give the selected circle a 1.5 px `stage_bottom` gap ring plus an outer
  `accent` ring.


## Carry into `app/specimen/index.html`

### Shared, whichever option is chosen

**Files.** Copy `labels3.js` and `labels-data.js` (checkpoint 2's anchors and silhouettes, unchanged) into
`app/specimen/`, and load both after `mock.js`:

```html
<script src="labels-data.js"></script>
<script src="labels3.js"></script>
```

**CSS.** Copy the block `LABELS (checkpoint 3)` from the end of this file's `<style>`. Keep the shared part (circles,
rails, `.showall`, `.planes`, the lesson terms, the practice markers, `.ticks`, `.modes`) and the section of the
chosen option; drop the other two options' sections and the `[data-variant="n"]` prefixes.

**Markup.**
- *Atlas:* the stage becomes `data-stage="wall"` with checkpoint 2's 12 `.lbl[data-a]` (the selected one has
  `is-selected`); the caption `<p>` gets `data-lcap`; add `<div class="lkey" data-key></div>` after the stage.
- *Section:* copy the whole `SECTION` block (from the comment to `</section>`), and add
  `[data-screen="section"] [data-screen-id="section"]` to the screen display rule. The dock template marks Section
  `on` when `data-kind="section"` (one line in the `[data-dock]` loop).
- *Lesson:* `.app` gets `data-labels="off"` (the lesson opens with no labels); the stage becomes `data-stage="wall"`
  with three `.lbl[data-a]` (`lmain` Left coronary artery, `lcx` Circumflex artery, `lad` Anterior interventricular
  artery; none selected, brass means the selection); the two bold terms get `class="term" data-for="lad|lcx"`; the step
  line gets `data-lcap` and `white-space:nowrap`; add the `.lkey`.
- *Practice:* replace the whole practice section with this file's (stage `data-stage="markers"` with the three
  `.pmark`s and three `.lbl`s, the card with three `data-pshow` feedbacks, the Mode list, the ticks; " · question 4
  of 12" leaves the caption because the ticks say it).
- Delete the `?variant` script in `<head>` and the `lstate` handling in `run()` when merging, or keep `lstate` for
  renders.

**JS (`labels3.js`).**
- `ROOM`: per room, the rail x on each side (`null` = no rail), the knee reach, the wall area, and which rail
  `lstate=one` opens.
- `setup()`: reads anchors (LBL_DATA, else `LH_PLATES.anchors` with `{select}`), numbers them, writes the circle
  buttons, and calls `buildControls()`, which adds the three Show all homes (dock pair, caption line, key). Keep the
  one you choose.
- `render()`: sets every circle's state and `aria-expanded`, then stacks and draws the open rails per side. With the
  corner key, names on the right rail stay below the key.
- `practice()`: places the markers at their anchors and draws the rails. `?mode=hunt` drops the rails and names, but the mockup does not switch the card copy or the Mode list for Hunt, so no Hunt state is rendered.

### Option 1, Dock pair
- CSS: `.lb-pair`, `.lb-div`, `.dock .lb-pair .showall`, `.dock .lb-main` padding.
- JS: the `lab` block in `buildControls()` (inserts `<span class="lb-pair">` after the Labels button and wires Labels
  on and off).

### Option 2, Wall line
- CSS: `.lcount` and `.lcount .showall`.
- JS: the `cap` block in `buildControls()` (appends `· <n> labels · Show all` to the `[data-lcap]` element).

### Option 3, Corner key
- CSS: `.lkey` (right 40, top 112), `.lk-head`, `.lkey .showall`, `.lkey ol`, `.lk-row` and its states.
- JS: the `key` block in `buildControls()` (writes the key: 1 column up to 4 entries, else 4 columns, number order
  running down the columns), and `keyB` in `render()`.

## What the Qt app needs

All of it is the existing label overlay in `app/viewer/viewport_core.py`, painted in its one `paintEvent`.

- **Anchors: none new.** `_compute_labels()` already puts each label's dot "where it is most clearly visible": the
  pixel deepest inside its visible region, from the picking buffer (`read_label_samples`, `distance_transform_edt`).
  The circles sit on those points.
- **Painting:** `_paint_labels()` today draws radial cards ("each name sits out from its dot, away from the middle").
  Replace it with: circles at the anchors (18 px ellipses with centred Fira 600 digits); for the open set only, the
  rail columns. A column is one sort and sweep (cp2's option 2 note: the rail x from the model's projected bounding
  box plus a gap), cheap enough to run every frame while orbiting. The spine is one `drawLine` in `hair`.
- **State:** a set of open item indices per view, beside `labels_on`. The selection is always in it on select.
  Renumber, and clear the set, only when the label set changes (`label_hosts()` returns a different list), never
  while the camera moves.
- **Input:** `label_at()` and `_label_rects` already hit-test labels, and `mousePressEvent` today picks the structure
  on a label click. Split it: a click on a circle toggles its rail; a click on a rail name selects the structure (what
  a label click does today). Hover: track the circle under the cursor in `mouseMoveEvent` and paint its rail faint.
  Esc: clear the open set.
- **Keyboard:** the circles are painted, not widgets, so they need an accessible focus chain: a focus index on the
  viewport (Tab and Shift+Tab move it while the viewport has focus, Space or Enter toggles), a 2 px `TEXT_2` ring, and
  `QAccessibleInterface` children reporting "10, Rectus femoris, expanded". This is new work.
- **Show all:**
  - option 1: a second `QToolButton` beside the Labels action in the dock, shown when `labels_on` (the labels toggle is the `landmarks` action, `app/main_window.py` line 454, next to `structure_labels`). Watch the
    name: the app already has a `show_all` action (line 451) that unhides every hidden structure. Give this one its own
    id (`labels_show_all`) and the tooltip "Show every label", so the two never get confused;
  - option 2: a link at the end of the room caption (the caption is a label on the wall overlay);
  - option 3: the key is a painted column in the same overlay, top right, with its own hit-test rects.
- **Lesson:** `app/ui/lessons.py` renders the step text. The step's `focus` and `show` names
  (`data/content/lessons_cardio_heart.json`, "The left coronary artery": focus Anterior interventricular artery,
  Circumflex artery of heart; show Left coronary artery, Heart) are the step's labels. The bold terms do not name them
  exactly, so the lesson files need a term-to-structure map, `<b for="Anterior interventricular artery">`, as
  checkpoint 2 said. On term hover: show that one circle with a brass halo and open its rail, even with labels off.
  Labels start off in a lesson; that is a new default.
- **Practice:** `app/ui/quiz.py` `handle_click()`.
  - Today a wrong pick flashes red for 900 ms (`_flash_structures(..., RED)`) and the answer turns green
    (`_show_answer(GREEN)`). Instead, keep a marker per wrong click at that structure's anchor, numbered by
    `cur["wrong"]`, until the question ends; and on the right click a filled `ACCENT` marker with a check at the
    answer's anchor. Neutral, not red: the marker and the name are the feedback.
  - The marker goes at the structure's label anchor, not the raw click point, so it sits on the named structure.
  - Hunt (`self.mode == "hunt"`, line 915, "naming the wrong structure would give the game away"): the numbered rings
    are drawn, with no rails and no names. The card says "Not that one. 2 tries left." as today. Only when the
    question ends (out of tries) does Hunt name them, as `_clicked_summary` already does.
  - The ticks: 12 `.dots` ticks, from the session builder.

## Anchors

Atlas and section: checkpoint 2's 30, all from the picking buffers (`hero26__ids`, `secinf__ids`); see
`../specimen-labels/PORT.md`. Lesson: `lmain`, `lcx`, `lad` from `heart_lesson_*.anchors.json` (the model
renderer's buffer). Practice: from `assets/plates/plates.json` `thorax_chest`; I read each anchor pixel in
`thoraxchest__ids.npz` (offset by the plate's box, x + 582): `serratus.vr` (1514, 1060) is Serratus anterior muscle,
`sternum.vl` (974, 992) is Body of sternum, `ext_ic.vl` (678, 859) is External intercostal muscles. None was placed by
eye.
