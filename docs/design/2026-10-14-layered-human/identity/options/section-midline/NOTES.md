# Section, down the midline

Leonardo's figure in its circle, cut down the midline: one half skin, the other half the muscle beneath, one step
deeper. This is the Specimen identity mark (`../../specimen/`). The owner chose Section (`../vitruvian-b/`) at
checkpoint 1: "do section down the midline".

## What the mark shows

The figure and circle are the same as in Section: Leonardo's circle pose, 8 heads tall, tapered limbs. The circle is
centred on the navel and the soles reach it. The skin is now cut from the crown to between the feet. The viewer's
left half stays skin, in ink. The right half (head, neck, arm, trunk and leg) is the superficial muscle layer, in brass.

What carries over from Section:

- Depth step: the muscle half is drawn one step back (up and to the right, an oblique view).
- Cut wall: the thickness of the skin along the cut is a grey band (ink at 34%) running the length of the trunk,
  with a slanted cap at the crown. It reads as one clean vertical cut.
- The circle: its right half steps back with the muscle and dims to 50%, so the depth still reads where the
  figure is too small to show it.

## The muscle half

The muscle half keeps the tapered profiles: it is the skin outline less the subcutaneous layer. It has ten divisions,
checked against the app's own superficial muscle plate (`assets/plates/body_muscles.webp`; `peel_26_superficial` is one
layer deeper, with the pectoralis already gone):

| Region | Division |
|---|---|
| Neck | Sternocleidomastoid: from behind the jaw down to the sternum |
| Shoulder and chest | Deltopectoral groove, from the clavicle along the arm to the deltoid's insertion; lower border of pectoralis major, from the sternum up into the armpit |
| Abdomen | Linea semilunaris (the outer edge of the rectus sheath, with the external oblique beside it); two tendinous intersections; the inguinal ligament. The linea alba is the cut itself |
| Forearm | Brachioradialis and the wrist extensors against the flexors |
| Thigh | Sartorius, from the iliac spine across the front of the thigh to the inner knee (quadriceps outside it, adductors inside) |
| Calf | The bare front of the tibia, between tibialis anterior and the medial calf |

The lines taper at both ends. They are knocked out of the brass, so they read as grooves.

## What was weighed (`renders/checkpoint-2/logo/section-midline-explore.webp`)

- **Head split or whole.** Head split, chosen: the cut runs from the crown, as the owner described, and the mark reads
  as two halves at every size, even 16 px. With the head whole the cut has to turn under the chin. That adds a
  second, horizontal wall, the cut stops being one vertical line, and the figure looks as if it is wearing a brass suit.
  The half-brass face is the one oddity, and it is true to a section.
- **Muscle detail.** Full detail, chosen for 200 px and up. Four lines and three lines read as a sketch at wall size.
  No lines makes the brass half a gold silhouette, not a muscle layer. Full detail reads as anatomy and is still quiet.
- **Detail by size.** 90-199 px (the 256 px icon, the touch icons): three lines (chest, rectus, sartorius). At 41-89 px
  (the 128 px icon) the three lines blurred into the brass in the test, so there are none. There are none at 64 px
  and below either.
- **32 px.** A pixel of gap between the halves, or a grey pixel between them as the wall: the grey wall was chosen. It
  keeps the cut visible and holds the figure together. Mark 19 px across instead of Section's 17: the figure needs the
  extra pixels.
- **16 px.** The muscle half one pixel up and one right, or one pixel up with the halves touching: touching was
  chosen. With a gap it read as two brackets. Touching, it reads as one person in two colours, the brass half raised.
  The figure is 11 px tall.

## Drawings by size

| Mark size (larger side) | Drawing |
|---|---|
| 200 px and up (symbols, 512 and 1024 px icons) | Full divisions. Below 500 px, lines are at least 0.85 px and the ring and gaps at least 0.9-1.15 px |
| 90-199 px | Three divisions |
| 41-89 px | No divisions |
| 24-40 px (64 px icon, lockups and the app header) | Thickened figure, a ring 1.3 px wide. Skin, 1 px gap, 1 px wall, 1 px gap, muscle; 2 px step |
| 13-23 px (32 px icon) | The wall is the 1 px between the halves; 1 px step |
| 12 px and under (16 px icon, favicon) | No circle; the brass half 1 px higher, touching |

Icons of 40 px mark size and under are drawn on the pixel grid: the cut and the crown fall on pixel edges, and the steps,
gaps and rings are whole pixels. I checked them at 1x and enlarged 4x and 8x (nearest neighbour): 64, 32 and 16 px
macOS, plus 16, 24, 32 and 48 px Windows. On the macOS tile the mark spans 58% from 64 px up, as before.

## Colours

- Slate: ink `#efece6`, brass `#d4b47e`. The wall is ink at 34% (42% when small), the stepped half of the circle
  brass at 50%.
- Paper `#ece8e0`: ink `#1d2023`, brass `#8c6a32` (4.07:1).
- Mono (`currentColor`): skin 100%, muscle 62%, wall 34%, back ring 31%.

## Lockup

The Specimen proportions are unchanged: the visible mark is 1.7 cap heights, the gap 0.7 cap heights, centred on the
middle of the caps. The symbol keeps the 48 box with a 42-unit extent, so the live-text recipe in
`identity/README.md` (`width:1.379em`, `margin-right:0.352em`, `vertical-align:-0.335em`) still holds. The lockup
uses the 28 px drawing.

## How it is built

`tools/logo/vitruvian_marks.py` (`midline()`, `midline_lines()`, `midline_px()`) draws the mark with shapely.
`tools/logo/vitruvian_midline.py` writes the drawings to `tools/logo/section_midline.json`, one per mark size that
`build_identity.py` uses, and makes this folder with build_identity's own Specimen functions. So these files match
`identity/specimen/`:

    .venv312/bin/python docs/design/2026-10-14-layered-human/tools/logo/vitruvian.py midline
    <idvenv>/bin/python docs/design/2026-10-14-layered-human/tools/build_identity.py build

Symbols and lockups use only `svg` and `path` with fill and fill-opacity (QtSvg-safe). The favicon has a `<style>`
with `prefers-color-scheme`.

## Known weaknesses

- The lockup keeps Specimen's 1.7 cap proportion, which was set for a ring. In the 52 px app header the figure is
  about 28 px, and the halves and circle read but the head is a few pixels. Section's lockup used 2.2 cap heights.
  If the header feels thin, raise `LOCKUP["specimen"]`. The recipe in the README is rebuilt from it.
- The muscle half looks a little slimmer than the skin half, because the wall band takes part of its width. That is
  the depth illusion working, but it is visible.
- Some people will still find the half-brass face odd.
- The ten divisions are placed by eye against the plate, not traced from it. They are right in kind and roughly in
  place; an anatomist could still argue the line of the deltopectoral groove on a raised arm.
- At 16 px the circle is gone, so the 16 px icon and the favicon say "person in two halves", not "Leonardo".
