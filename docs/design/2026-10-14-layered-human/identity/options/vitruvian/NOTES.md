# Vitruvian: Peel

Leonardo's figure on three sheets of glass, receding in depth: skin in front, then the muscle, then the skeleton.

## What the mark shows

Each sheet is Leonardo's square (side = the figure's height). The figure stands in the circle pose: arms raised until
the fingertips are level with the crown, legs spread until the soles reach the circle. The front sheet carries the
skin, solid ink, and the circle (centred on the navel, touching the base of the square), drawn in perspective with
the sheet. The second sheet carries the muscle in brass: the same figure less the subcutaneous layer, with the linea
alba, the tendinous intersections, the lower edge of pectoralis, the inguinal folds, the deltoid groove and the
knee cut into it. The third sheet carries the skeleton in ink at 58%: skull, ribs, spine, pelvis and long bones.

The figure is built for this mark, not traced: tapered two-sided limb profiles (deltoid, biceps and triceps,
brachioradialis, vastus lateralis and medialis, both heads of the calf), a torso profile with shoulders, chest, waist
and hips, and Leonardo's proportions (8 heads, span = height, shoulders a quarter of the height, the square centred
on the pubis). All geometry is in `tools/logo/vitruvian_geom.py`.

## How the layering reads

- Perspective: the sheets turn 28° about a vertical axis and step back, so they foreshorten and overlap like the
  plates in the app's peel view.
- Occlusion: every nearer shape cuts a gap into whatever lies behind it. The gaps are explicit geometry, with no masks.
- Glass: each sheet is ink at 7%, so where the sheets overlap the tint builds up and the stack shows its depth.
- Colour order: ink, brass, dim ink. The same order as the app's dissection slider (skin, muscles, skeleton).

## Drawings by size

| Use | Drawing |
|---|---|
| 128 px and up, the wall, print | Full: three figures, sheets, circle (`symbol-*.svg`). Below 512 px the hairlines are held to at least 0.9 px. |
| Lockups, the app header, 64 px icon | Figure in the circle, with the two deeper sheets as plain brass and grey panels (the lockup drawing). |
| 32 px icon, `symbol-small.svg` | Figure and the two panels, no circle. Limbs at least 1.3 px. |
| 16 px icon, favicon | The same, heavier: limbs and gaps about 1 px. |

On the macOS tile the full mark spans 66% of the tile (it is wide and short, so its height is about 51%). At 32 and
16 px the small drawings span 76% and 80%.

Checked pixel by pixel at 64, 32 and 16 px (4x and 8x nearest-neighbour), and at 1x on the board. At 16 px the
figure keeps its head, raised arms and spread legs, and the brass and grey panels read as layers behind it.

## Colours

- Slate: ink `#efece6`, brass `#d4b47e` (6.7:1 on `#2a3138`). Bone ink at 58%, glass ink at 7%, sheet edges ink at
  50/36/30%.
- Paper `#ece8e0`: ink `#1d2024`, brass `#8c6a32` (4.1:1 on the paper, 3.5:1 on `#dbd7d0`).
- Mono (`currentColor`): skin 100%, muscle 62%, bone 58%, glass 7%.

## Lockup

The lockup takes the lockup drawing. Symbol height 2.25 cap heights (1.597em), width 2.077em. The gap from the
symbol to the ink of the "L" is 0.5 cap heights (0.355em). The symbol is centred on the middle of the caps. Literata
450, opsz 36, tracking -0.005em, as in the Specimen lockup.

Clear space: half the symbol's height on every side. Minimum: full drawing 96 px wide, lockup drawing 28 px high,
the small drawings below that.

## QtSvg

Symbols and lockups use only `svg` and `path`, with fill and fill-opacity. There is no clipPath, mask, gradient,
style or text. The favicon has a `<style>` with `prefers-color-scheme` (browsers only). The icon tile uses the same
gradients and shadow filter as `build_identity.mac_icon`.

## Files

`symbol-dark|light|mono.svg`, `symbol-small.svg`, `lockup-dark|light.svg`, `favicon.svg`, `icon-1024|128|64|32|16.png`,
`icon.icns` (16-1024, each size from its own SVG), `src/macos-*.svg` (the icon sources), `src/symbol-16.svg`.
Rebuild: `.venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py build`.

## Known weaknesses

- The full mark is an illustration more than a sign. It has three figures, three sheets and a circle, so it needs
  room: under about 96 px it has to change drawing, and the small drawings lose the circle (the Vitruvian cue).
- At 16 px the figure is a white "X" with a head, and the layers are two coloured panels, not figures.
- The figure is in the circle pose only. Leonardo's second pose (arms level, legs together) is left out, because it
  doubled the limbs into a tangle on every sheet.
- The muscle and bone sheets are close in tone in the mono version.
- The circle is on the front sheet, so it is an ellipse. That is correct in perspective, but less iconic than a
  true circle.
