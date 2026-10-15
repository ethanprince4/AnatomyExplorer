# Building Specimen in the Qt app: notes

Notes for moving the Specimen mockup (`app/specimen/index.html`) into the PySide6 app. They come from the design
critique before checkpoint 2. The mockup is HTML; these are the places where HTML does something Qt can't do the same
way.

## Type

- **Literata needs code, not QSS.** The mockup uses Literata at weights 340, 360, 400, 420, 440 and 560, and sets the
  `opsz` axis (14, 18, 24, 36, 48, 72). Qt sets variable axes only from code (`QFont.setVariableAxis`, Qt 6.7 or
  later). `requirements.txt` pins PySide6 6.11.2, so this is available. QSS can't do it.
- **One font table.** Put a small table in `app/ui/theme.py`: role, family, pixel size, weight, opsz. Build every
  QFont from it, so the roles stay consistent.
- **Whole pixel sizes.** `QFont.setPixelSize` takes an int. The mockup now uses nine sizes: 12 (keys, credits),
  13 (meta, column heads, counts), 14 (list rows, stage labels, card text), 15 (nav, buttons, main UI), 18 (prose),
  20 (current gauge stop, specimen captions, lab titles), 24 (card question), 32 (card title, big numbers) and 44
  (page title).
- **Ship TTF.** The design folder bundles WOFF2 for the browser. Qt's WOFF2 support depends on how Qt was built, so
  ship the TTF files in the app. Literata and Fira Sans are under the SIL Open Font License.
- **One baseline in the header.** The wordmark, the room names, Back and Forward, search and the right-hand items sit
  on the wordmark's baseline, not centred in their boxes. In Qt, align them on a shared baseline in the layout (or
  paint the header text in one place).

## Colours

- **Flat tokens only.** QSS and QPainter need flat colours, not `color-mix()`. `system/schemes.py` now defines
  `hair`, `leader` and `card_line` for every Specimen scheme, flattened over the middle of the wall gradient:
  - `hair`: text at 16 %, for rules and dividers.
  - `leader`: text at 55 %, for label leaders and the open anchor rings. The contrast check holds it at 3:1 or more
    against `spot`, so it reads in the pool too.
  - `card_line`: text at 9 % over the plaque, for the plaque's top edge and its dock dividers. Used only if the
    owner picks the plaque treatment.
- **Decoration only.** `hair` (about 1.6:1 on the wall) and `card_line` (about 1.3:1 on the plaque) are decoration.
  Never use them for a control's border; a control needs 3:1. The schemes check reports `hair` against the wall with
  a 1.4:1 floor so it can't fade further.
- **Still mixed in the mockup.** These are still `color-mix()` in the HTML and need flat values when built:
  - `--edge`, the ghost button outline (text at 41 %, at least 3:1 on the wall). It is a control border, so check
    it in every scheme.
  - `--tint`, the plaque fill (text at 6 %), if the plaque is chosen.
  - The label chip behind stage labels (`stage_bottom` at 72 %), the pool's middle stop (`spot` at 55 %), the done
    lesson dots (`accent` at 55 %) and the past gauge stops (`text_3` at 72 %, which item 8 replaces anyway).
- **"Current" is a bar, not an underline.** For text the current item gets a 2 px brass bar 4 px under the line box
  (a `border-bottom` with padding in QSS, which can't colour or offset an underline). For pictures it is a 2 px
  brass outline 4 px outside the picture.

## Wall text over the 3D view

- `GpuWidget` (`app/gpu/host.py`) keeps translucent children on top, but every child repaint re-blits the frame
  beneath it.
- The atlas puts about 40 text items on the stage: the title, 9 system rows, the quick views, 8 gauge stops and the
  labels. Don't make each one a transparent QLabel.
- Paint the static wall text in one overlay widget with a single `paintEvent`. Don't repaint it while the camera
  moves; only the labels that follow the model need to move.

## One wall in every room

- Lessons, Models, Histology and Settings are plain widgets; Atlas, peel, lesson, radiology and practice are on the
  renderer.
- They must paint exactly the same gradient and pool as the renderer's background pass. If they don't, switching
  from Atlas to Lessons shows a step in the wall.
- Use one function for both, with the same sRGB stops and the same dither.
