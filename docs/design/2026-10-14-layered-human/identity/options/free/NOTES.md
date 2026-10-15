# Quarter (logo option "free")

The body, standing in the anatomical position, with the skin cut away from its upper right quarter: from the crown
down the midline to the hip, and the whole arm. Where the skin is gone you see the app's own superficial muscle
layer, in brass.

Every file here is made by `tools/logo/free.py` (see the top of that file). Change the script, not the files.

```
/home/user/AnatomyExplorer/.venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/free.py
```

## How the layering reads

- Two layers, one inside the other: skin (ink) and muscle (brass). The muscle is the real outline of
  `peel_26_superficial`, so it sits inside the skin line: the brass skull is lower than the hair, the brass arm is
  thinner, and there is more space between the arm and the flank than on the skin side.
- The skin has thickness. Its cut faces show as two bands: down the midline (facing right, in shade: ink at 0.4) and
  round the hip (facing up, lit: ink at 0.72). The hip cut is seen from a little above, so it curves round the body
  like a real section. That curve is what makes the mark read as a solid body and not as two colours.
- The skin casts a narrow shadow on the muscle beside the midline (black at 0.22).
- The quarter cut is the old Specimen mark's idea (rings with a quarter cut away) carried into a human figure.

## Drawing

- Outlines are traced from the app's plates (`peel_00_skin`, `peel_26_superficial`), placed in the shared camera frame
  with the boxes in `plates.js`, smoothed, and mirrored so the figure is exactly symmetric. The fingers are closed
  into a calm hand. About 8 heads tall, as the model is.
- Cut height 470 of 1000 (the iliac crest), skin faces 10 units thick, hip section seen at ry/rx 0.37.
- Paths are cubic Beziers, coordinates to 2 decimals. The symbol is 48 units high in a tight box centred on the midline.

## Small sizes

The cut faces are thinner than a pixel below about 64 px, so the small sizes are separate drawings, hinted on the pixel
grid (`tools/logo/free_pixels.py`, grids of full and half pixels, mirrored, midline on a pixel edge):

| Grid | Used for |
|---|---|
| 30 px figure | `symbol-small.svg` (32 px box), app header use at 32 px and below |
| 22 px figure | `icon-32.png` (the macOS tile is 26 px there) |
| 15 px figure | `favicon.svg`, `src/symbol-small-16.svg` |
| 12 px figure | `icon-16.png` (the tile is 13 px) |

Each keeps the head, a neck where there is room, the shoulders, the arm hanging in a one-pixel channel, and two legs.
The brass is the same cut: the upper right and the arm. Checked enlarged 4x and at 1x on the board.

## Colours

| | Ink | Accent | Faces | Shadow |
|---|---|---|---|---|
| Dark (slate wall) | `#efece6` | `#d4b47e` | ink at 0.4 and 0.72 | black at 0.22 |
| Light (paper `#ece8e0`) | `#1d2024` | `#8c6c37` | ink at 0.55 and 0.3 | black at 0.16 |
| Mono | `currentColor` | `currentColor` at 0.45 | left open (the step shows as a gap) | none |

The darker brass `#8c6c37` is 3.98:1 on the paper and 3.36:1 against the ink. On the wall `#2a3138` the brass is 6.66:1
and the ink 11.17:1.

## Files

- `symbol-dark.svg`, `symbol-light.svg`, `symbol-mono.svg`: path elements with fill and fill-opacity only (QtSvg-safe).
- `symbol-small.svg`: the 30 px pixel drawing in a 32 box, dark colours. `src/symbol-small-16.svg` and
  `src/symbol-small-light.svg` are its 16 px and light versions.
- `lockup-dark.svg`, `lockup-light.svg`, `lockup-mono.svg`: Literata wordmark outlined by `build_identity.wordmark()`.
  The figure is 2.25 cap heights high, centred on the caps, 0.42 cap heights from the text. At 20 px Literata the
  figure is about 32 px high, which suits the 52 px app header.
  Live text: symbol-dark.svg `width:0.654em; height:1.630em; margin-right:0.215em; vertical-align:-0.460em`.
- `icon-1024.png` (default, dark), `icon-1024-light.png`, `icon-128/64/32/16.png`, `icon.icns` (16 to 1024, each
  rendered for its size). The macOS tile, drop shadow and spotlight follow `build_identity.mac_icon()`; the figure is
  78% of the tile's height.
- `favicon.svg`: the 15 px drawing; colours switch with `prefers-color-scheme`.
- `src/`: the SVGs the PNGs were made from.

## Clear space and minimum sizes

- Clear space round the symbol: the width of the head on every side.
- The full drawing works down to about 48 px high. Below that, use the small drawings.
- Lockup: Literata 13 px or more.

## Known weaknesses

- It is a narrow, upright figure, so it fills a square tile less than a round or spread-armed mark does. In the app
  header it is quiet.
- At 32 px and below it reads as a figure in two colours. The depth (cut faces, curved hip section) only shows from
  about 64 px up.
- Two layers, not three. A deeper cut showing the skeleton was tried and dropped: it made the brass area busy and lost
  the clean quarter.
- The vitruvian option's "Section" uses the same idea (a quarter of the skin cut away, with a cut face) on Leonardo's
  pose. Quarter differs in the pose (arms down, the app's own model), the real muscle outline and the curved hip section,
  but the two should not both go to the owner.
- The hand is simplified to a mitten; at board size the left hand still shows a small thumb bump.
