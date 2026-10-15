# Libraries (checkpoint 2, question C): how to port the chosen option

This copy of `app/specimen/index.html` adds three treatments of the two libraries: Lessons, and Histology before a slide
is opened. They are switched with `?variant=1|2|3` (default 3), which sets `<html data-variant>`. Models, the
Histology slide viewer and every other screen are unchanged. All colours are scheme tokens.

```
index.html?screen=lessons&variant=1
index.html?screen=histology-library&variant=2
index.html?screen=lessons&variant=3&scheme=prussian
```

| | Name | In one sentence |
|---|---|---|
| 1 | **Catalogue** | The libraries are typed lists, like an index card drawer: a number, a Literata title, progress and a count, with a 48 px slide thumbnail beside each tissue. |
| 2 | **Vitrines** | Every lab and every tissue stands lit on the wall with its caption under it, as Models does now. |
| 3 | **Lit row** | Three lit vitrines come first (Continue, Review and the next lab; or the last-opened tissue and its two neighbours), and the catalogue of option 1 follows. |

## What is shared by all three (port this whatever is chosen)

**The library room.** The same three columns on both screens, under the usual title block and on the 232 px top line:

- side column 40–290 (`.lib-side`);
- the collection, 360–1460 (`.lib-main`, 1100 px; critique section 3, item 8);
- the wall label of the selected item, 1520–1880 (`.lib-detail`, a `.label-card`, so it follows `?panel=`).

The wall label is the Specimen signature carried into the libraries: the selected thing names itself, as on Models.
- Lessons: the selected lab (Lab 3) with its ten lessons and their step counts. The four done lessons get a check, and
  the next one gets the brass bar. The button is "Open Lab 3", a plain outline.
- Histology: the selected tissue's micrograph (hidden in option 3), its name, "Epithelium · 13 slides · H&E", the
  "Look for…" line, "Open the slides" (brass) and "Jejunum model".

**Copy changes:**
- Lessons:
  - "Continue where you left off", the small label over the Continue title, is gone (critique item 14). The title,
    the step line and the button carry it.
  - The list has the column head "Lessons".
- Histology library:
  - The title is "Histology", with the caption "101 tissues · 1,049 micrographs".
  - The side column lists the 17 groups with a "Tissues" count.
  - Each group in the collection has a "Slides" column head. Inside a group, the group word is dropped from tissue
    names, as in the slide viewer's list, and "&" becomes "and".
  - A foot line reads "N of 101 shown · scroll for the rest", as on Models.

**Markup to copy:**
- the `LESSONS` section (`[data-screen-id="lessons"]`);
- the new `[data-screen-id="histology-library"]` section, plus its entry in the `.screen` display selector (line 31);
- the `.lib`, `.hl`, `.lib-side`, `.lib-main` and `.lib-detail` structure.

**CSS:** the block headed `libraries (checkpoint 2, question C)` at the end of the `<style>`. The rules are grouped by
variant. Once one option is chosen, keep the shared rules and that variant's rules, and drop the `[data-variant="n"]`
prefix from them:

| Keep for 1 | Keep for 2 | Keep for 3 |
|---|---|---|
| `.cont-row` shown, `.side-cont` hidden; the "1 and 3: catalogue rows" rules | the "2: vitrines" rules; `.side-cont` and `.side-rev` shown; `.cont-row` hidden | the "3: the lit row" rules and the "1 and 3" rules, with 42 px lab rows and `.tissues .grp { break-inside: auto }`; `.side-cont`, `.side-rev` and `.dfig` hidden |

Then delete the `.lit` markup (for 1 and 2), the `.cont-row` (for 2 and 3), the `.v1/.v2/.v3` foot spans you don't
need, and the variant line in the head script.

**JS (in the inline script):**
- `LAB_FIG` is the specimen for each lab; practicals take the figures of the labs they review. Options 1 and 3 can drop
  it on the Lessons screen; option 3 still uses its three lit figures, which are written into the markup.
- `SEL_LAB` is the selected lab.
- The `[data-labs]` renderer now emits one item markup (`.it` > `.fig`, `.no`, `.ti`, `.bar`, `.ct`, with `--p`
  as the done fraction) in place of inline-styled rows.
- `LAB3` and `[data-lab-lessons]` fill the wall label.
- `TGROUPS`, `TISSUES`, `[data-tissue-groups]` and `[data-tissues]` hold the histology catalogue: groups, names and
  slide counts from `data/histology/catalog.json`. The mockup has the first seven groups.
- The variant line in the head script: `R.dataset.variant = …`.

**Assets:** none new. The figures are existing files in `assets/plates/` and `assets/images/`.

## Figures: what the mockup borrows and what the real thing needs

**Lessons, option 2 (one specimen per lab):**
- Honest:
  - Lab 1: peripheral nerve model.
  - Lab 2: eye and ear models.
  - Lab 3: heart.
  - Lab 6: the radiology thorax, with lungs.
  - Lab 8: liver with bile ducts, and the kidney.
  - Lab 9: the male and female reproductive models.
- Stand-ins:
  - Lab 4, "ECG and heart function": the opened heart. It should show the conduction system.
  - Lab 5, "Blood vessels and circulation": the whole-body vessels figure, which shows the nerves too.
  - Lab 7, "Exercise physiology and pulmonary health": the lung acinus.
- Practicals show the figures of the labs they review (Practical 1 leaves out Lab 4's).
- **The real thing needs:**
  - 3 new lab figures for the lab course.
  - About 23 group figures for the other arrangements, counted from the 303 lessons' own fields: 12 body systems,
    8 regions and 3 levels (a level has no natural specimen). Some can reuse the figures here.
  - The lecture-exam grouping needs a few more.
  - If a lab's lessons are also shown as vitrines once it is opened, 303 figures, one per lesson.

**Lessons, option 3:**
- Continue: the heart, for "The coronary circulation".
- Review: the chest and abdomen muscles (`thorax_close`), standing in for "the structures you practised".
- Next: the opened heart, for Lab 4.
- In the real app these three change with the user's state, so they cannot be hand-picked plates. Each lesson step
  already stores a 3D view. The app would render that view to a small transparent thumbnail, offscreen, with the
  model renderer (the same path `tools/capture/render_models.py` uses) and cache it. Because Continue can be any of
  the 303 lessons, this needs either the runtime render or one figure per lesson.

**Option 1** needs no figures.

**Histology, all three options:**
- The mockup has micrographs of one tissue only, simple columnar epithelium. Every other tissue is a plain grey
  placeholder (`.ph`, `--surface-2`). I did not put 3D models in their place: a micrograph is a full-bleed pink and
  purple rectangle, and a model on the wall would misrepresent how the room looks.
- **The real thing needs no new figures.** `data/histology/catalog.json` lists micrographs for 100 of the 101
  tissues; Sublingual gland has none. The work is choosing one representative image per tissue. The first image in
  each list is a sensible default; a curated pick is better for tissues whose first image is a diagram.
- Option 1's 48 × 36 thumbnails and option 2's 184 × 138 slides are center crops (`object-fit: cover`).

## Building it in Qt

All three options:
- One `LibraryRoom` widget with three regions: a side column, the collection and the wall label. It is painted on the
  same wall gradient and pool as the renderer (critique item 37).
- The wall label is the same widget as the Models detail card.
- Progress is a 2 px track in `hair` with an `accent` fill. That is two `fillRect` calls, or a `QProgressBar`
  with QSS on its chunk.
- The selected row's brass bar is a `border-bottom` on the title label, sized to the text (put the title in its
  own `QLabel` with `QSizePolicy.Maximum`).
- Slide thumbnails come from `data/histology/thumbs/`, which mirrors `images/`.

**1 Catalogue.**
- Lessons: a `QListView` with a custom delegate, painted in four columns (number, title in Literata 20, progress,
  count) at 52 px rows.
- Histology: the same delegate with a 48 × 36 pixmap, laid out in two columns. Either use `QListView` in
  `IconMode` with a fixed grid width, or use two views fed by one model split at a group boundary; the second is
  simpler for keeping groups whole. Group heads are non-selectable rows.
- Cheapest of the three.

**2 Vitrines.**
- A `QListView` in `IconMode`, or a `QGridLayout` in a scroll area as Models will need. Use 4 columns for labs at
  252 px cells and 5 for tissues.
- Each cell paints the pool (a radial gradient of `spot` at 55 %), then the figure scaled to fit a 146 px box, then
  a centered caption.
- Selection is a 2 px `accent` rectangle at 4 px offset.
- Figures must be pre-rendered transparent PNGs. Cost: the figures above.

**3 Lit row.**
- Three `Vitrine` widgets (a pool, a figure, a Literata 20 title, a meta line and one button) above the option 1
  catalogue, at 42 px lab rows.
- The figures come from the runtime thumbnail render described above. For Histology they are the last-opened
  tissue's representative micrograph and those of its two catalogue neighbours.
- The lit row is fixed and does not scroll; the catalogue below it scrolls.

## Notes for whoever merges

- The slide viewer's tissue list in the Histology room differs from the catalogue. It shows "Stratified squamous 4",
  where the catalogue has two tissues with 3 and 1 slides. It also files "Hyaline cartilage" under Connective tissue;
  the catalogue has it under Cartilage and bone. The library follows the catalogue. The viewer is outside this topic.
- Count mismatch: "1,049 micrographs" (the brand brief and the site) against 991 in the catalogue's per-tissue lists.
  The library uses 1,049, as the review's F15 recommends. One of the two numbers is wrong.
