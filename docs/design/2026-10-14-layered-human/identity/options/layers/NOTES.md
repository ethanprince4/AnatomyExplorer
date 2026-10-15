# Layers: Vitrine

Three glass plates stand one behind the other, turned 34 degrees, like anatomical plates in a museum case. Each plate
carries one of the app's own layers: the skin in front, the superficial muscle behind it, the skeleton in brass at the
back.

Everything here is made by `tools/logo/layers.py`. Change the script, not the files. From the repository root:

    .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/layers.py

That one command rebuilds this folder, the board and the contact sheet. The script header lists what else it needs.

## What the mark shows

- **The figures are the product's own layers.** The skin and muscle outlines are traced from the alpha channels of
  `peel_00_skin.webp` and `body_muscles.webp`. The plates share one camera, so `plates.js` boxes align them exactly.
  They are smoothed, simplified and redrawn as Catmull-Rom Beziers; sharp corners stay sharp.
  The figures keep the model's proportions: about 8 heads, real shoulders, waist and calves.
  Two corrections: the hands become tapered mittens (the fingers broke up at small sizes), and the skin's crown takes
  its curve from the muscle layer, because the model's hair made the head flat-topped.
- **The skeleton is drawn, not traced.** Its traced silhouette came out as a box: the scapulae fill the ribcage
  outline. So it is drawn as strokes and two filled shapes on landmarks measured on `body_skeleton.webp`:
  - skull with cheekbones, jaw and orbits;
  - clavicles, spine, ribcage with costal arch and two ribs;
  - pelvis with its inlet;
  - the long bones, with gaps at the joints.
- **The muscle plate** carries four faint lines: the linea alba, the lower borders of pectoralis major, the inguinal
  ligaments and sartorius. They make it read as muscle rather than a grey ghost.

## How the layering reads

- **Depth:** real perspective (yaw 34 degrees, plates 300 units apart on a 1000-unit figure). The plates converge,
  the back figures shrink, and each plate's glass edge crosses the figure behind it.
- **Overlap:** the skin plate is opaque and hides part of the muscle figure.
- **Transparency:** the muscle is ink at 50%, so the brass pelvis and humerus show through it.
- **Order:** front to back follows the app's peel, from the skin inward.

## Sizes: one drawing per range, each checked

| Use | Drawing | Notes |
|---|---|---|
| 128 px and up, symbol files | large | glass edges at least 1 px at 128 |
| 64 px | medium | heavier bones (2.2×), outlines thickened 5 plate px |
| 30-32 px: `symbol-small.svg`, `icon-32.png`, app header | small | outlines thickened 10 px; bones drawn as heavy strokes (skull, spine, ribcage oval, pelvis, limbs); glass edges exactly 1 px; snapped to the pixel grid |
| 16 px: `icon-16.png`, `favicon.svg` | tiny | no glass, no muscle: the white skin figure and a brass figure, 40 degrees and 760 units apart, so each keeps a head pixel and two legs |

Mark extent on the 824 macOS tile, by largest side: 74% at 1024, 76% at 128, 80% at 64, 88% at 32, 92% at 16.
The small sizes run larger than the current 58% because the mark is tall and thin, not a disc.

I checked each icon at 1:1 and the 64, 32 and 16 px icons enlarged 8×. The board shows the ladder and the 4×
enlargements.

## Colours

| | Ink | Brass | Muscle | Glass |
|---|---|---|---|---|
| Dark (slate) | `#efece6` | `#d4b47e` | ink 50% | fill ink 5%, edges ink 40% |
| Light (paper `#ece8e0`) | `#1d2024` | `#8d6c35` | ink 50% | fill ink 5%, edges ink 40% |
| Mono | `currentColor` | `currentColor` | 50% | 5%, 40% |

`#8d6c35` is the brass darkened at the same hue (37.7°, L 38%, S 45%). On paper it is 3.97:1 against `#ece8e0` and
3.38:1 against the darker `#ddd8ce`. Brass on slate is 6.66:1.

## Files and QtSvg

- `symbol-*.svg` and `lockup-*.svg` use only `path`, with fill, fill-opacity, stroke, stroke-opacity, stroke-width,
  stroke-linecap and stroke-linejoin. There is no clipPath, mask, gradient, CSS or `<text>`.
  Holes (orbits, pelvic inlet) are rings in the opposite direction, so the default nonzero rule cuts them.
  Coordinates have at most 2 decimals.
- `favicon.svg` uses `<style>` with `prefers-color-scheme`: dark ink and dark brass on light tab bars, the slate
  colours on dark ones.
- `src/macos-*.svg` are the icon sources. They contain the tile gradients and the shadow filter.
- The skin plate is opaque. At 94% the glass edge behind it showed through the front figure as a line.

## Lockup

The plates are 3.3 cap heights tall, centred on the caps, with a gap of 0.45 cap heights to the Literata wordmark
(`build_identity.wordmark("specimen")`). The lockups use the 64 px drawing, so the bones keep their weight at
wordmark sizes. Their glass edges are 1 px at a 24 px cap height.

In the 52 px app header the small drawing is set at 2.0 cap heights: 31 px beside the wordmark at 22 px.

Clear space: one cap height. Minimum size: the small drawing below 48 px, the tiny one at 16 px.

## Known weaknesses

- **At 16 px it is two figures, white and gold, not one layered body.** The glass and the muscle cannot survive
  there. It is recognisable as this mark, but on its own it could read as "two people".
- **Three figures side by side can read as a group of people.** The glass plates and the identical pose carry the
  idea that it is one body in layers. Without them (the 16 px drawing, a careless crop) the reading weakens.
- **The large drawing is detailed for an app icon:** thin glass edges, a skeleton of strokes. It is at its best from
  64 px up and in print, and relies on the small drawings below that.
- **The front figure is a smooth, bald silhouette.** It reads as a mannequin more than as a person.
- **The skeleton is a careful diagram, not an engraving.** The joints are gaps, the hands are single strokes and the
  feet are short.
