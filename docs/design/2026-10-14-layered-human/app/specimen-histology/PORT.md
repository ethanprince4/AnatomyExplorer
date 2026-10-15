# Histology library (checkpoint 3): how to port the chosen option

This copy of `app/specimen/index.html` (apply3's base, copied 15 October) changes only the Histology library screen
(`[data-screen-id="histology-library"]`). Every other screen is exactly as the base has it.

```
index.html?screen=histology-library&variant=1|2|3&state=rest|scrolled|chosen&scheme=slate|prussian|…
index.html?screen=histology-library&variant=1&edge=a|b|c|d      (bottom-edge trials; default c)
```

| | Name | In one sentence |
|---|---|---|
| 1 | **Endless catalogue** | The base's catalogue in one real scroll box with no foot line: the list fades into the wall, a thin scrollbar is the only sign that it goes on, and the group column follows the scroll. |
| 2 | **Body map** | The body stands on the wall with eight numbered circles on the organs; choosing one opens a caption rail listing that system's tissues, and the tissues found throughout the body are listed beside it. |
| 3 | **Light table** | The micrographs themselves, six to a row and butted into one sheet per group with the names lettered under them, so tissues are chosen and compared by how they look. |

**Recommendation: 1, Endless catalogue, with 2 as the Histology room's second way in later.** It is the one the owner
already trusts, it shows all 101 names and counts at reading size, and it now scrolls for real with nothing at its foot.
The body map is the most original of the three, but a third of the collection (37 tissues: the basic tissues, skin and
immune organs) has no single place on the body, so it cannot be the only way in.

Three ways a student looks: by name (1), by place, which is how a course runs (2), and by look, which is how a practical
is examined (3).

## Bottom-edge trials (option 1, and option 3 uses the same edge)

Renders `renders/checkpoint-3/histology/edge_<letter>.webp`, each the foot of the list at 1:1 (2x), at rest.

- **edge_a** The window cuts the list: no fade, no scrollbar. At rest the last visible row happens to end whole, so the list reads as finished. Rejected.
- **edge_b** The list fades into the wall's own gradient over the last 150 px (a mask, so the wall shows through, never a painted band). It reads as going on, but the only hint that you can scroll is the fade.
- **edge_c** (chosen) The fade of b plus a thin scrollbar: a 3 px `line-2` thumb with no track, which turns `text-3` on hover. The fade means no row ever looks cut off, whatever the scroll position. The scrollbar says "this scrolls" without words, and the mouse can drag it.
- **edge_d** The window cut of a plus the scrollbar. Whether it looks cut off depends on where the rows happen to land, as in a.
- Not built: the next group's heading peeking above the edge also depends on where the rows land, and the library has no dock to run under.

Checked in Chromium: the mouse wheel over the list scrolls it, and the side column's current group follows (2,400 px
down it marks Respiratory system). Clicking a group in the side column scrolls the list to it smoothly. The scrollbar
is the native one, so it can be dragged.

## What changed, by option

**Shared by all three (port whatever is chosen):**
- **Data.** `HT` holds all 17 groups and 101 tissues, generated from `data/histology/catalog.json` as
  `[id, name, slides, micrograph]`. The names follow the base: the group word is dropped inside a group and "&" becomes
  "and". The base had seven groups.
- **Micrographs.** There are 91 real ones: the base's 30 in `assets/images/histo/`, plus 61 new ones in this folder's
  `histo/` (368 × 276, 4:3 centre crops from `data/histology/images/`). The credits are in `histo/CREDITS.json`; when
  merging, move the files to `assets/images/histo/` and add the credits to `assets/images/CREDITS.json`.
  - I picked them by an H&E colour score that rejects diagrams, fluorescence and black or white borders, then chose by
    eye for 17 tissues where the score had picked a labelled or eyepiece shot.
  - Ten tissues have no real micrograph and keep the plain `.ph` placeholder: nine have only diagrams
    (strat_squamous_k, heart_valve, nail, gej, anal_canal, larynx, bronchiole, eye, meninges_cp), and Sublingual gland
    has no images at all.
  - Some picks still show a pointer or an eyepiece circle (bronchus, urethra, kidney_cortex and others), because that
    is how the collection's photographs look.
- **The wall label** (`[data-hlabel]`) is filled by `label(id)`; clicking any tissue calls `choose(id)`.
  - `HDETAIL` holds the "Look for" text and the model link for Simple columnar (the base's own text) and Jejunum
    (written from the catalogue's `features`). Both link to the Jejunum model: `app/micro/registry_organs.py` lists
    jejunum and simple_columnar under that model.
  - Any other tissue shows its micrograph, name and "group · N slides", without the note or the model button.
- **The head script** sets `data-variant`, `data-hstate` and `data-edge`. Drop the variant and state lines after the
  merge.
- **CSS:** the block headed `histology library (checkpoint 3)` at the end of `<style>`.
  - Keep the unprefixed rules, plus the rules prefixed with the chosen `[data-variant="n"]` (drop that prefix).
  - For option 1 or 3, keep the `[data-edge="c"]` rules as plain rules.
  - The base's `.hl .lib-main` mask is replaced.

**1 Endless catalogue.**
- Markup:
  - `.lib-main` becomes the scroll box: `overflow-y: auto`, 1124 px wide with 24 px of right padding for the scrollbar,
    and `padding-bottom: 160px` on `.tissues` so the last group can rise clear of the fade.
  - The tissues are laid out as stacked groups, each split into two balanced columns (`.items { columns: 2 }`), so a
    group reads down and then across, and the next group always starts below it.
  - The side column `[data-tissue-groups]` items carry `data-g`.
- JS:
  - `spy()` marks the group whose heading is within 48 px of the top, or the last group at the bottom of the list.
  - Clicks on the side column call `main.scrollTo(... smooth)`.
  - Rows get a hover tint (`text` at 6%), and the hovered title brightens to `text`.
- `hlPose()` only sets up the render states. Drop it after the merge.

**2 Body map.**
- Markup: `.bmap` holds the `body_organs` figure (880 px tall, in its own pool), an SVG for the leader, and
  `.rail [data-rail]`. The side column becomes "Throughout the body" (`[data-throughout]`).
- The pins (`PINS`), numbered top to bottom:
  1. Brain and spinal cord (6)
  2. Eye and ear (4)
  3. Endocrine glands, on the neck (6)
  4. Respiratory system (6)
  5. Heart and blood vessels (5)
  6. Digestive system (19)
  7. Urinary system, on the bladder (5)
  8. Reproductive systems: Male 6 and Female 7, on the figure's pelvis
  - Throughout the body: Epithelium 9, Connective tissue 5, Cartilage and bone 6, Blood and bone marrow 2, Muscle tissue
    3, Nervous tissue 2, Immune organs 4, Skin 6.
  - Total: 64 + 37 = 101.
- The pins are `.hpin` circles: 30 px, a `leader` ring on `stage-bottom`. The chosen one is filled with the brass
  accent and `on-accent`, as in the labels language.
- The caption rail is set level with its pin, so the leader (`leader`, 1.5 px) runs straight across. Its heading
  repeats the circle and gives "N tissues · N slides" (Digestive: 19 tissues · 162 slides). Its rows are the catalogue
  rows, in two columns.
- **Honest limits:**
  - `assets/plates/` has no picking-buffer anchors for `body_organs`, so I placed the pins by eye on the figure.
  - The figure is male, so the Reproductive pin stands for both systems.
  - Immune organs (spleen, thymus, tonsil, lymph nodes) are listed as found throughout the body rather than pinned.
    The spleen is hidden in this figure.
  - The real app should take the pin points from the renderer's picking buffer, as the atlas labels do.

**3 Light table.**
- The same markup as 1. `.items` becomes a 6-column grid with a 4 px gutter. Each tile is a 4:3 micrograph about
  180 × 135 px, with its name in Fira 13 under it (two lines at most); the counts are hidden, and the group heading
  gives "N tissues" instead.
- Selected tile: a 2 px brass outline, and the name in brass. Hovered tile: a 1 px `text` outline.
- Scroll, edge and side column are as in 1.

## Building it in Qt

These touch `app/ui/histology.py` (`HistologyBrowser`, which today is a filterable `Outline` tree with tissue and image
rows), `app/content.py` (`Content.thumb_path`, `Content.histology`) and `app/main_window.py` (the `histology` place
and `show_histology_tab`). Opening a tissue stays `HistologyViewer.show_tissue(tissue_id, 0)`. The model button uses the
reverse of `entry.histology` in `app/micro/registry*.py`, the link that `model_view.py` already follows the other way
(`openHistology`).

- **Every option:**
  - The library is a `LibraryRoom` on the wall gradient and pool, as in checkpoint 2's PORT.md, with the wall label as
    the Models detail card.
  - "Look for" needs either a new short field in `catalog.json` or the first one or two `features` joined; the catalogue
    has no such field today.
  - Stain needs the same: it exists only inside image descriptions, so "H&E" can be shown only where the representative
    image's description says it.
  - Thumbnails: `data/histology/thumbs/` are 208 × 156, enough for 1 and 2. For 3 at 180 px wide on a 2x screen they
    are soft: either generate 368 × 276 thumbs once (as I did here), or load the full image scaled.
  - A curated representative image per tissue: a new `thumb` index per tissue in `catalog.json`; the picks in
    `histo/CREDITS.json` are a starting point.
- **1:** a `QScrollArea` holding one widget per group (a heading label and two `QListView`s, or one view with a
  two-column delegate).
  - The fade is a `QGraphicsOpacityEffect` with a gradient mask on the viewport, or a paint pass over the bottom
    150 px in the wall's own colours.
  - The scrollbar is styled with QSS (`QScrollBar:vertical { width: 9px; background: transparent }`, handle `line-2`).
  - Scroll-spy: `verticalScrollBar().valueChanged` → find the group whose `y()` is within 48 px of the top.
    `ensureWidgetVisible` or an animated `setValue` scrolls to a clicked group.
- **2:** a `QWidget` painting the body figure (a pre-rendered transparent PNG, as in `assets/plates/`) and the eight
  pins, plus a rail widget.
  - The pin points must come from the picking buffer (the `tools/capture` path that made the atlas anchors).
  - The groups-to-place table (eight pins plus the throughout list) is new data and lives in no file today.
  - This needs the new figure render with anchors; nothing else is new.
- **3:** a `QListView` in `IconMode` per group (fixed 180 × 135 grid, spacing 4, text under the icon), or one view
  whose delegate paints group headings as full-width rows.
  - Cheap, apart from the thumbnails above.

## Renders (`renders/checkpoint-3/histology/`, Gallery slate at 2x unless named)

- `before_histology-library`
- `n_histology-library` (rest), `_scrolled`, `_chosen` and `_prussian` for n = 1, 2, 3.
- Crops at 1:1:
  - `1_edge_crop`
  - `2_histology-library_crop`: the pins, leader and rail.
  - `3_histology-library_crop`: the sheet in the middle of the collection. The hovered tile, Stomach, may fall just
    outside the crop.
- `edge_a` to `edge_d`.
- What each state shows:
  - Rest is the room as it opens, with Simple columnar as the last tissue opened.
  - Scrolled is the middle of the collection (Skin into Digestive system) with a row (1) or tile (3) hovered. For 2 it
    is circle 4, Respiratory system, chosen, with Lung alveoli hovered.
  - Chosen is Jejunum, with its label and "Open the slides".
- Prussian was the other scheme: its blue wall is the hardest test for the pink and purple micrographs and the brass.
