# Vitruvian: Section

Leonardo's figure in its circle with a quarter of the skin cut away, so the muscle shows one layer deeper.

## What the mark shows

The figure stands in Leonardo's circle pose. The fingertips are level with the crown and the soles reach the circle,
which is centred on the navel and touches the base of the square. A quadrant is cut out of the skin from the navel
upwards and to the right, like the app's Section tool. In the opening lies the muscle, in brass: the right arm, the
right half of the chest and the right half of the head, with the pectoral, deltoid and abdominal divisions cut in.
The quadrant of the circle steps back with it and dims to 50%.

It keeps the current Specimen mark's idea (rings with a quarter cut away, brass inside) and gives it a body.

The figure is built for this mark (tapered limb profiles, real shoulders, waist, thighs and calves, 8 heads, span =
height). See `tools/logo/vitruvian_geom.py`.

## How the layering reads

- Depth step: the muscle is drawn one step back (up and to the right, an oblique view), so it sits behind the skin
  and not beside it.
- The cut walls: the thickness of the skin along both cut planes is drawn as a grey band (ink at 34%), with a
  slanted cap where the vertical cut leaves the head. This band is what makes the cut read as a cut.
- The circle repeats the step: its quadrant is pushed back by the same amount and dimmed. That gives a second
  depth cue that still reads when the figure is small.

## Drawings by size

| Use | Drawing |
|---|---|
| 128 px and up, the wall, print | Full, with the muscle divisions (`symbol-*.svg`). Below 512 px the ring and the gaps are held to at least 0.9 px. |
| Lockups, the app header, 64 and 32 px icons, `symbol-small.svg` | Thickened figure, a heavier ring and a deeper step, no muscle lines. |
| 16 px icon, favicon | Heavier still and no circle: the white figure with the brass quadrant (arm and shoulder) set back. |

On the macOS tile the mark spans 58% of the tile, the same as the current Specimen mark. At 32 and 16 px it spans
66% and 74%.

Checked pixel by pixel at 64, 32 and 16 px (4x and 8x nearest-neighbour), and at 1x on the board.

## Colours

- Slate: ink `#efece6`, brass `#d4b47e`. Cut walls in ink at 34%, the stepped quadrant of the circle in brass at 50%.
- Paper `#ece8e0`: ink `#1d2024`, brass `#8c6a32` (4.1:1).
- Mono (`currentColor`): skin 100%, muscle 62%, walls 34%, back ring 31%.

## Lockup

The lockup takes the 32 px drawing. Symbol 1.562em square (2.2 cap heights). The gap to the ink of the "L" is 0.45
cap heights (0.320em), and the symbol is centred on the middle of the caps. Literata 450, opsz 36, tracking -0.005em.

Clear space: the width of the cut wall times three, about a fifth of the symbol, on every side. Minimum: full
drawing 64 px, 32 px drawing down to 24 px, then the 16 px drawing.

## QtSvg

Symbols and lockups use only `svg` and `path`, with fill and fill-opacity. There is no clipPath, mask, gradient,
style or text. The favicon has a `<style>` with `prefers-color-scheme`.

## Files

As in `../vitruvian/`: symbols, `symbol-small.svg`, lockups, `favicon.svg`, `icon-1024|128|64|32|16.png`, `icon.icns`,
and `src/`. Rebuild: `.venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py build`.

## Known weaknesses

- It shows two layers, not three. A second step down to the skeleton was tried (see the explorations). The
  skeleton of the raised arm stuck out of the quadrant as a stick and cluttered the mark.
- The cut splits the face down the middle. It is true to a section, but some people will find the half-brass
  head odd.
- At 16 px the brass quadrant separates from the body and can read as a raised hand or a flag.
- The muscle divisions in the full drawing are few and schematic. A demanding anatomist will want them placed
  better.
