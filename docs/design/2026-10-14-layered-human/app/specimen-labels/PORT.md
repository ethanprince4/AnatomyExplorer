# Labels at real density: how to port the chosen option

Checkpoint 2, question A: how do labels sit on the wall? This folder is a copy of `app/specimen/index.html` with three
label treatments, switched by `?variant=1|2|3` (sets `<html data-variant>`, default 1), and a new screen
`?screen=section`. Every other screen is pixel-identical to the original. I checked peel, lesson, lessons, models,
radiology, practice, histology and settings in Gallery slate at 2x, and the maximum difference was 0.

| Option | Name | What it is |
|---|---|---|
| 1 | Free lettering | Each name is lettered on the wall beside its structure, and only a name with no clear wall within reach sits on a chip over the body. |
| 2 | Caption rails | The names stack on two rails beside the specimen, in height order, joined to their anchors by knee leaders. |
| 3 | Numbered key | Small numbered dots sit on the body, and the names are a numbered list on the wall. |

Measured in the renders (1x px, from the SVG paths):

| | Atlas, 12 labels | Section, 18 labels |
|---|---|---|
| 1 Free lettering | median leader 44, longest 124, no chips | median 118, longest 240, 6 chips (the mediastinum) |
| 2 Caption rails | median 232, longest 271 | median 497, longest 619 |
| 3 Numbered key | no leaders; key of 12 rows | no leaders; key of 18 rows |

No labels overlap and none were dropped, in any option.

---

## Shared by all three: carry these whatever is chosen

### New asset

- `labels-data.js` sets `window.LBL_DATA[plate] = { anchors, sil, size }` for `hero26_sel_7cc8da` (the atlas at 26%) and
  `section_inferior`.
  - `anchors` uses the same rule and the same keys as `assets/plates/plates.json`: the largest visible piece of the
    structure on each side of the midline (`.vl`, `.vr`), or over the whole image (`.c`), anchored at its most inscribed
    pixel.
  - `sil` is the plate's alpha in cells of 6 (atlas) or 4 (section) plate pixels, stored as `[start, end)` runs per row.
- `anchors.py` rebuilds it: `python anchors.py RAW_DIR`, where `RAW_DIR` holds the `*__ids.npz` and `*__ids.json` files
  from `tools/capture`. It only reads them.
- **Cleaner merge:**
  - Add the new targets to `TARGETS` in `tools/process_plates.py` (`hero` and `secinf`, plus `.c` anchors).
  - Write `sil` from `bundle_plates.py` into `plates.js`.
  - Then delete `labels-data.js` and read `LH_PLATES` instead. The keys are already the same.

### Markup

- **Atlas stage:**
  - Change `data-stage="tags"` to `data-stage="wall"`.
  - Labels become `<div class="lbl" data-a="biceps.vl">` with no `data-dx`/`data-dy`, because the placer decides where
    they go. The 12 labels and the HTML comment about the three swaps are in the atlas section.
  - Add `<div class="lkey" data-key></div>` after the stage. Option 3 only.
- **Section screen:** copy the whole `SECTION` block (the comment `SECTION`, about line 296). The room pattern:
  - the pool;
  - the stage with `section_inferior`;
  - 18 labels;
  - `.lkey`, for option 3 only;
  - the header;
  - `.exhibit` with the title, the caption "At the level of T8, seen from below, as on a CT", and
    `p.planes` (Sagittal, Coronal, Transverse, with `.is-cur` on Transverse);
  - the dock with `data-kind="section"`.
- **Screen switch:** add `[data-screen="section"] [data-screen-id="section"]` to the display rule (line 31).
- **Dock:** the Section button gets `class="on"` when `data-kind === 'section'` (in the `[data-dock]` loop).
- **Variant switch:** delete it when merging (the `R.dataset.variant = …` line).

### CSS (the block headed "labels at real density", lines 138–164)

Always carry:

```css
[data-stage="wall"] .lbl { background: none; padding: 0; border-radius: 0; }
[data-stage="wall"] svg.leaders .anchor:not(.is-selected) { stroke: var(--text-2); }   /* the open ring has to read on red muscle */
.planes { display: flex; gap: 22px; }
.exhibit p.planes { margin-top: 10px; color: var(--text-2); }
```

The selected label is unchanged everywhere: `.lbl.is-selected` (weight 600), `.leader.is-selected` and
`.anchor.is-selected` (the brass dot).

### JS

Carry the `<script src="labels-data.js">` tag and the script after it, which runs once `mock.js` has set
`data-ready`.

- `ROOM` holds the per-room numbers: rail x, knee reach, the longest wall leader, the vertical search and the wall area.
- `layout()` builds:
  - the silhouette grid;
  - the keep-out rectangles from `.exhibit, .cat, .label-card, .gauge, .dock, .head, .lkey` and all their children;
  - the item list.

  Then it runs one of three branches. Keep the branch you choose and drop the `variant` test and the other two.
- The page sets `data-labels="1"` when it is done (the capture script waits for it).

---

## Option 1: Free lettering

- **CSS:** the shared rules, plus the chip for names forced over the body:
  `[data-stage="wall"] .lbl.on-model { padding: 2px 6px; border-radius: 2px; background: color-mix(in srgb, var(--stage-bottom) 72%, transparent); }`
- **JS:** the `variant === '1'` branch. For each label (the selected one first, then top to bottom):
  1. Try vertical offsets up to ±96 px (atlas) or ±160 px (section), each side, preferred side first.
  2. Slide the name outwards from the anchor until it is 16 px clear of the silhouette, inside the wall area, and
     clear of the room's other text.
  3. Cost = leader length + 0.9 × |offset| + 140 for the far side + 500 if the leader crosses a name + 160 per leader
     it crosses. Keep the cheapest.
  4. If nothing is within `maxLead` (300 atlas, 330 section), put the name on a chip next to the anchor, never covering
     any anchor.
  5. An alignment pass snaps neighbouring names (and neighbouring chips) to a shared edge when the move stays clear.

  Leaders are the existing anchor → elbow → name shape.
- **Qt:**
  - **Inputs.** The existing label placer already sorts and de-overlaps; this adds a silhouette test and the chip
    fallback. The silhouette is the picking buffer's "anything drawn" mask, downsampled to cells of about 4 screen px.
    Each anchor is the most-inscribed point of the structure's largest visible piece in the same buffer: a distance
    transform at ¼ resolution is enough.
  - **Painting.** Paint names, leaders, rings and chips in the one wall-text overlay widget (critique item 36), with a
    single `paintEvent`. The chip needs a flat `chip` token (stage_bottom at 72%) in `system/schemes.py`, because
    QPainter can't use `color-mix`.
  - **Camera moves.** Re-run the search only when the camera settles. While it moves, keep each name's offset from its
    anchor.

## Option 2: Caption rails

- **CSS:** the shared rules, plus
  `[data-variant="2"] [data-stage="wall"] .lbl.left { text-align: right; }` (drop the attribute when merging) and
  `svg.leaders .rail { stroke: var(--hair); stroke-width: 1; }`.
- **JS:** the `variant === '2'` branch.
  - **Sides.** Split the labels by which side of the image's centre their anchor falls.
  - **Stacking.** Sort by anchor height. Push apart to a 30 px pitch, then pull back inside the wall area.
  - **Names.** Set each name 12 px off its rail. The rails are at x 704 / 1258 on the atlas and 390 / 1610 on the
    section.
  - **Spine.** Draw a hairline spine from the first name to the last.
  - **Leaders.** Each leader runs level from the rail to `reach` px (44 / 40) short of the anchor, then turns to it.

  This is `layoutColumns` in `app/shared/mock.js` with a spine and no chips. It does not use the silhouette.
- **Qt:** This is the same new layout mode the README already describes for Plate ("labels in margin columns"):
  - the rail x comes from the model's projected bounding box plus a gap;
  - each column is a single sort and sweep, cheap enough to run every frame while orbiting;
  - the spine is one `drawLine` in the `hair` token.

## Option 3: Numbered key

- **CSS:** the shared rules, plus `.ndot`, `.ndot.is-selected`, `.lkey`, `.lkey ol/li`, `.lkey li .ndot` and
  `.lkey li.is-selected`. Add the two placements, `[data-screen-id="atlas"] .lkey` (left 340, top 232) and
  `[data-screen-id="section"] .lkey` (left 40, top 264, under the plane names). When merging, drop the `[data-variant="3"]`
  prefixes and hide `.lbl` on wall stages.
  - **Dots:** 18 px, `stage_bottom` fill, a 1 px `leader` ring and 12 px Fira 600 digits.
  - **Selected dot:** `accent` with `on_accent` digits. It becomes the scheme's accent: pale blue in Umber.
- **JS:** the `else` branch.
  - **Numbering.** Number the anchors top to bottom (then left to right), and drop a `.ndot` on each.
  - **The key.** Write the key as `.colhead` "Labels" plus an `<ol>` of dot and name. The selected row is set in weight
    600 with the brass dot.
- **Qt:**
  - **Dots.** Draw them in the overlay as 18 px ellipses with centred digits.
  - **The key.** It is a wall list, a painted column in the same overlay, styled like Systems.
  - **Hover.** The critique's linking (hover a dot to light its row, and the reverse) needs hit-testing on both
    plus a shared "hot" index. Clicking a row selects the structure.
  - **Numbering.** Fix the numbers per view, so they don't reshuffle while the camera turns. Renumber when the label
    set changes.

---

## Anchors: where every one comes from

All 30 anchors (12 atlas, 18 section) come from the renderer's picking buffers (`hero26__ids`, `secinf__ids`). None was
placed by eye. For each one I checked a 1:1 crop of the plate against the structure's mask: the anchor pixel belongs
to the named structure in all 30.

- **Swaps on the atlas.** At 26% deep, three of the requested structures have no visible pixels in the picking buffer:
  - sternocleidomastoid, replaced by **Sternohyoid**, its neighbour in the neck;
  - temporalis, replaced by **Temporal bone** (the head is peeled to the skull);
  - external oblique, replaced by **Internal oblique**, the next layer, which is what shows.

  "Quadriceps" is labelled as its head **Rectus femoris**. **Pectoralis major** is anchored on its clavicular head, the
  only part still showing at 26%, and only on one side.
- **Names.** Labels use the mockup's short names for the picked structure or its parent:
  - "Trapezius" for "Descending part of trapezius muscle";
  - "Right lung" for its lobes;
  - "Triceps brachii" for its heads;
  - "Pectoralis major" for its heads.

  The real app names the picked part itself. Choose a display-name rule before porting.
- **Section facts** come from the picking buffer and the site:
  - The vertebra in the cut is T8, with the T8–T9 disc where the vertebral body would be.
  - "seen from below, as on a CT" is the site's own caption.
