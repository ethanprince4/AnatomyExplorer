# Layered Human identity files

The marks, lockups, app icons and favicons for the three design directions. Every file here is made by
`tools/build_identity.py`. Change the script, not the files.

## Rebuild

1. `.venv312/bin/python docs/design/2026-10-14-layered-human/tools/build_identity.py outline`
   traces the body silhouette into `plate/figure.json`. It needs scipy and scikit-image.
2. `.venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline json`
   draws the Specimen mark with shapely and writes it to `tools/logo/section_midline.json` (see below).
3. `python docs/design/2026-10-14-layered-human/tools/build_identity.py build`
   writes all SVGs, rasterises them with Chromium (`tools/raster_svg.mjs`) and packs the `.icns` and `.ico` files.
   It needs fontTools, brotli, uharfbuzz, Pillow and numpy, plus node with Playwright.

The build reads the colours from `system/schemes.json`. It reads every `.icns` and `.ico` back and checks that
each size holds the image rendered for that size.

## The Specimen mark: Section, down the midline

Leonardo's figure in its circle, cut down the midline. The viewer's left half is skin, in ink. The right half (head,
arm, trunk and leg) is the superficial muscle layer, in brass, drawn one step back: up and to the right, as in an
oblique view. The thickness of the skin along the cut is drawn as a band (ink at 34%), and the right half of the
circle steps back with the muscle and dims to 50%. The owner chose it at checkpoint 1 (see
`options/section-midline/NOTES.md`).

The brass half carries a few muscle divisions, checked against the app's own superficial muscle plate: the
sternocleidomastoid, the lower border of pectoralis major, the deltopectoral groove, the brachioradialis, the
linea semilunaris and two tendinous intersections of the rectus sheath, the inguinal ligament, the sartorius and
the bare front of the tibia. The linea alba is the cut itself.

The mark is drawn once per size, like an optical size, by `tools/logo/vitruvian.py midline`, which writes
`tools/logo/section_midline.json` (frame units, one drawing per mark size in output pixels). `build_identity.py`
places those drawings; it has no geometry of its own for this mark.

| Mark size (its larger side) | Drawing |
|---|---|
| 200 px and up, symbols | Full: all the divisions. |
| 90-199 px | Three divisions: pectoral border, linea semilunaris, sartorius. |
| 41-89 px (the 128 px icon) | No divisions. |
| 24-40 px (64 px icon, lockups, app header) | Thickened figure, heavier circle. Skin, a pixel of gap, a pixel of wall, a pixel of gap, muscle. |
| 13-23 px (32 px icon) | The wall is the one pixel between the halves; the muscle half sits a pixel higher and to the right. |
| 12 px and under (16 px icon, favicon) | No circle. The halves touch; the brass half sits one pixel higher. |

Icons of 40 px mark size and under are set on the pixel grid: the cut and the crown fall on pixel edges.

## Files per direction (`overlay/`, `specimen/`, `plate/`)

| File | Use |
|---|---|
| `symbol-dark.svg`, `symbol-light.svg` | The mark on its own, 48×48 box. Safe for Qt's QtSvg. |
| `symbol-mono.svg` | One colour, `currentColor`. Set the colour with CSS. |
| `lockup-dark.svg`, `lockup-light.svg`, `lockup-mono.svg` | Mark plus wordmark, text as outlines, tight box. |
| `icon-1024.png` | macOS master in the default appearance. |
| `icon-1024-alt.png` | The other appearance, for macOS and iOS dark or light icon modes. |
| `icon.icns` | macOS app icon: 16, 32, 64, 128, 256, 512 and 1024 px, each rendered from vector. |
| `icon.ico` | Windows app icon: 16, 24, 32, 48, 64, 128 and 256 px. |
| `favicon.svg` | Website favicon. Transparent; switches colours with `prefers-color-scheme`. |
| `favicon.ico`, `favicon-32.png` | Favicon fallbacks (16, 32, 48 px), tiled. |
| `apple-touch-icon.png` | 180×180, opaque square. iOS rounds the corners itself. |
| `icon-192.png`, `icon-512.png` | Web app manifest icons. Maskable: the mark stays inside the central 80% circle. |
| `src/` | The SVGs that were rasterised for the icons. |

The icon names match `app/resources/`, so the rename phase can swap them in.

`plate/figure.json` holds the traced body outline: a smooth version, a thickened version for 32 px and below,
and the anchor points. The frame is 1000 units high, top at 0, centred on x 0.
The dot sits on `biceps.vl` and the ring on `rectus_femoris.vr` (the middle of the front of the thigh).
The spares are `sartorius.vr`, `deltoid.vl`, `pectoralis.vl`, `sartorius.vl` and `tibialis_anterior.vl`.
The old 48-box mockups put the thigh point on `sartorius.vr`, which sits further in. `plates.js` has no
`pectoralis.vr`.

## Sizes

All three icons share one extent so they sit well side by side. On the 824 px macOS tile the films and the
Specimen mark span 57-58% of the tile and the figure is 76% of its height. On the Windows 256 tile: 62-63% and 82%.

The small icons are drawn on the pixel grid, not scaled down:

- Windows 16, 24 and 32 px: full-bleed tile, films of 10, 14 and 20 px, rings with whole-pixel centres.
- macOS 16 and 32 px: the same 824 tile, with the mark set in output pixels. Overlay films are 7 px on 2 px
  steps at 16 px and 14 px on 3 px steps at 32 px. The Specimen mark is 11 px tall at 16 px (no circle) and 19 px
  across at 32 px; on the Windows and favicon tiles 12, 18, 24 and 36 px at 16, 24, 32 and 48 px.
- Plate at 32 px and below: the thickened figure in solid ink with the biceps dot. A thin ring of paper sets the
  dot off from the dark figure. No leaders.

## Colours

Ink is the scheme's `text`, accent is its `accent`, and the tile ground runs from `stage_top` to `stage_bottom`.

| Direction | Dark | Light | Default |
|---|---|---|---|
| Overlay | `graphite` | `clear` | dark |
| Specimen | `slate` (Gallery slate), plus `spot` as the light pool behind the mark | paper (`SPECIMEN_LIGHT` in the script) | dark |
| Plate | `night` | `bristol` | light |

To recolour a symbol for another scheme, swap the ink for that scheme's `text` and the accent for its `accent`.
The tints are opacities, so they follow the ink.

- Overlay films: ink at 0.22 on dark, 0.16 on light. At 32 px and below: 0.34 and 0.26. The core is the accent.
- Specimen: skin in ink, muscle in brass: the accent `#d4b47e` on dark, `#8c6a32` on paper (4.1:1 on `#ece8e0`).
  The cut wall is ink at 0.34 (0.42 when small), the stepped half of the circle brass at 0.5. One colour
  (`currentColor`): the muscle at 0.62.
- Plate: figure in ink at 0.18 on dark and 0.16 on light, outline in ink at 0.45. The biceps dot is the accent.
  The thigh ring is ink with a paper fill (the scheme's `stage_top`). At 32 px and below the figure is solid ink.

## QtSvg notes

The `symbol-dark` and `symbol-light` files use only `path`, `rect`, `circle` and `g`, with fill, fill-opacity,
stroke and stroke-opacity. There is no clipPath, mask, filter, CSS or `currentColor`.
QtSvg has no clipPath, so the Overlay core (where all three films overlap) is drawn as its own path.
For the main geometry it is `M22 15H33V26A7 7 0 0 1 26 33H15V22A7 7 0 0 1 22 15Z`.
The films sit in one `<g fill-opacity>`, so each film is translucent and the overlaps build up.

## Clear space and minimum sizes

- Symbols: keep clear space equal to the core's diameter on every side.
  That is 18 units of 48 for Overlay and the dot's diameter for Plate. Specimen: a fifth of the mark (8 units of
  48), about three widths of the cut wall.
- Lockups: keep clear space equal to the cap height.
- Overlay and Specimen symbols: 16 px minimum. The full Specimen symbol from 64 px; below that, its lockup drawing
  down to 24 px, then the 16 px drawing. At 32 px and below, use the small versions (the favicon,
  `src/windows-16.svg` to `windows-32.svg` and `src/macos-16.svg`, `macos-32.svg` show them).
- Plate figure plate: 32 px minimum. Below that, use the solid figure with the dot only.
- Lockups: font size at least 13 px (a cap height of about 9 px).

## Lockups with live text

The HTML mockups use an inline symbol next to live text. These recipes reproduce the outlined lockups.

- Overlay: Archivo, `font-weight: 640; font-stretch: 90%; letter-spacing: -0.01em`. The visible films are
  2.1× the cap height; the gap is 0.8× the cap height. The symbol is centred on the middle of the caps.
- Specimen: Literata, `font-weight: 450; font-variation-settings: "opsz" 36; letter-spacing: -0.005em`.
  The visible mark (the circle with its stepped half) is 2.2× the cap height; the gap is 0.45× the cap height.
  Centred on the middle of the caps.
- Plate: Atkinson Hyperlegible Next, `font-weight: 700; letter-spacing: -0.01em`, then a leader.
  The leader starts 0.32em after the last letter, is 1.15em long and 0.07em thick, and sits at the middle of the
  x-height. It ends in an accent dot of radius 0.2em centred on its end.
  Markup: `<svg viewBox="0 0 1350 400"><path d="M0 200H1150" stroke="currentColor" stroke-width="70"/>`
  `<circle cx="1150" cy="200" r="200" fill="var(--accent)"/></svg>`.

Exact sizes in em. The build writes them from the measured fonts. They were checked by laying each outlined
lockup over its live-text version in Chromium; the two match to the pixel. The `@font-face` rule must declare
the axis ranges: `font-weight: 100 900` with `font-stretch: 62% 125%` for Archivo, `200 900` for Literata
and `200 800` for Atkinson Hyperlegible Next. Without them Chromium
clamps the weight to 400 and the live text comes out lighter than the outlines.

<!-- recipes:start -->
- Overlay: symbol `width:1.646em; height:1.646em; margin-right:0.377em; vertical-align:-0.480em`. At 15.5px: symbol 25.5px, margin 5.8px.
- Specimen: symbol `width:1.785em; height:1.785em; margin-right:0.149em; vertical-align:-0.538em`. At 23px: symbol 41.1px, margin 3.4px.
- Plate: leader `<svg viewBox="0 0 1350 400">` `width:1.35em; height:0.40em; margin-left:0.276em; vertical-align:0.048em`.
- Overlay metrics: cap 686, x-height 526, units per em 1000, ink left 69, axes {'wght': 640, 'wdth': 90}.
- Specimen metrics: cap 710, x-height 510, units per em 1000, ink left 59, axes {'opsz': 36, 'wght': 450}.
- Plate metrics: cap 668, x-height 496, units per em 1000, ink left 60, axes {'wght': 700}.
<!-- recipes:end -->
