# Layered Human identity files

The marks, lockups, app icons and favicons for the three design directions. Every file here is made by
`tools/build_identity.py`. Change the script, not the files.

## Rebuild

1. `.venv312/bin/python docs/design/2026-10-14-layered-human/tools/build_identity.py outline`
   traces the body silhouette into `plate/figure.json`. It needs scipy and scikit-image.
2. `python docs/design/2026-10-14-layered-human/tools/build_identity.py build`
   writes all SVGs, rasterises them with Chromium (`tools/raster_svg.mjs`) and packs the `.icns` and `.ico` files.
   It needs fontTools, brotli, uharfbuzz, Pillow and numpy, plus node with Playwright.

The build reads the colours from `system/schemes.json`. It reads every `.icns` and `.ico` back and checks that
each size holds the image rendered for that size.

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
and the anchor points (biceps, thigh and a few spares). The frame is 1000 units high, top at 0, centred on x 0.

## Colours

Ink is the scheme's `text`, accent is its `accent`, and the tile ground runs from `stage_top` to `stage_bottom`.

| Direction | Dark | Light | Default |
|---|---|---|---|
| Overlay | `graphite` | `clear` | dark |
| Specimen | `slate` (Gallery slate), plus `spot` as the light pool behind the mark | `plaster` | dark |
| Plate | `night` | `bristol` | light |

To recolour a symbol for another scheme, swap the ink for that scheme's `text` and the accent for its `accent`.
The tints are opacities, so they follow the ink.

- Overlay films: ink at 0.22 on dark, 0.16 on light. At 32 px and below: 0.34 and 0.26. The core is the accent.
- Specimen: skin ring in ink, muscle ring in ink at 0.55 on dark and 0.5 on light (0.62 and 0.58 when small).
  The core is the accent.
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
  That is 18 units of 48 for Overlay, 13 for Specimen and the dot's diameter for Plate.
- Lockups: keep clear space equal to the cap height.
- Overlay and Specimen symbols: 16 px minimum. Below 32 px, use the small versions (the favicon and
  `src/windows-16.svg` to `windows-32.svg` show them).
- Plate figure plate: 32 px minimum. Below that, use the solid figure with the dot only.
- Lockups: font size at least 13 px (a cap height of about 9 px).

## Lockups with live text

The HTML mockups use an inline symbol next to live text. These recipes reproduce the outlined lockups.

- Overlay: Archivo, `font-weight: 640; font-stretch: 90%; letter-spacing: -0.01em`. The visible films are
  2.1× the cap height; the gap is 0.8× the cap height. The symbol is centred on the middle of the caps.
- Specimen: Literata, `font-weight: 450; font-variation-settings: "opsz" 36; letter-spacing: -0.005em`.
  The visible circle is 1.7× the cap height; the gap is 0.7× the cap height. Centred on the middle of the caps.
- Plate: Atkinson Hyperlegible Next, `font-weight: 700; letter-spacing: -0.01em`, then a leader.
  The leader starts 0.32em after the last letter, is 1.15em long and 0.07em thick, and sits at the middle of the
  x-height. It ends in an accent dot of radius 0.2em centred on its end.
  Markup: `<svg viewBox="0 0 1350 400"><path d="M0 200H1150" stroke="currentColor" stroke-width="70"/>`
  `<circle cx="1150" cy="200" r="200" fill="var(--accent)"/></svg>`.

Exact sizes in em. The build writes these from the measured fonts. Until then the values below are estimates
from the cap heights; the margins assume no side bearing.

<!-- recipes:start -->
- Overlay: symbol `width:1.646em; height:1.646em; margin-right:≈0.45em minus the "L" side bearing; vertical-align:-0.480em`. At 15.5px: symbol 25.5px.
- Specimen: symbol `width:1.360em; height:1.360em; margin-right:≈0.41em minus the "L" side bearing; vertical-align:-0.330em`. At 23px: symbol 31.3px.
- Plate: leader `width:1.35em; height:0.40em; margin-left:≈0.32em; vertical-align:0.048em`.
<!-- recipes:end -->
