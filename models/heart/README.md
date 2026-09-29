# Whole heart, round 3: what you have and how to look inside

## Open it

Double-click `viewer\Model Viewer.bat` in the project, then File > Open and pick `heart.glb` in this folder
(`heart.viewer.json` beside it carries the cameras). `heart.blend` is the frozen Blender file. The earlier versions
are kept beside it: round 2 as `heart-v3.glb`, `heart-v3.viewer.json`, `heart-v3.blend`, `README-v3.md` and
`CHANGES-v3.md`; round 1 as `heart-v2.*`, `README-v2.md` and `CHANGES-v2.md`; round 0 as `heart-v1.*` and
`README-v1.md`.

What changed in this round, note by note: `CHANGES.md` in this folder.

## Look inside by hiding wall panels (as in round 2)

Every chamber wall is split into panels, each its own part. Click a panel to see its name, then:

- **H** hides the clicked panel only. **Shift+H** hides its whole chamber (all of that chamber's panels).
- **I** isolates the clicked part. **Shift+I** isolates its chamber.
- **Alt+H** shows everything again.
- In the **Structures** panel each chamber lists its panels, each with its own tick box.

A hidden panel leaves its neighbours' cut faces showing with crisp edges; that is deliberate.

| Chamber | Panels |
|---|---|
| Right ventricle | anterior wall, inferior wall, outflow tract |
| Left ventricle | interventricular septum, anterior wall, lateral wall, inferior wall, apex |
| Right atrium | lateral wall, posterior wall, right auricle |
| Left atrium | posterior wall, anterior wall, interatrial septum, left auricle |

Good first looks for what changed this round:

- **The left ventricle's outflow tract**: hide `left_ventricle_anterior_wall` and `left_atrium_anterior_wall`. The
  septum's opening to the aorta is now clear; the triangle that stood across it is gone.
- **The papillary muscles** (half their old size, in the colour of the ventricles' walls): hide
  `right_ventricle_anterior_wall` (tricuspid) or `left_ventricle_lateral_wall` (mitral).
- **The right atrium and its auricle**: hide `right_atrium_lateral_wall`. The strip that used to stand alone over the
  tricuspid ring now belongs to the auricle.
- **The septum from the left atrium**: hide `left_atrium_posterior_wall`. The interatrial septum no longer bulges
  into the chamber.

## What is in it (119 named parts, the same names as round 2)

- The four chambers as fifteen wall panels; five papillary muscles (halved) that grow out of the ventricular walls;
  30 chordae refitted to them; the five atrioventricular leaflets and six semilunar cusps exactly as you approved
  them; the two atrioventricular rings.
- Coronary arteries (right-dominant, all in the aorta's colour now) and cardiac veins as before (19 arteries, 20
  veins).
- Great vessels, hollow, with rounded lips at their open cut ends.
- About 2.8 million triangles.
- Colours: arteries and oxygenated vessels red, veins and deoxygenated vessels blue, valves pale cream, the
  ventricles' walls and papillary muscles one myocardium colour, the atria's walls a different one.
- Left out on purpose: pericardium, epicardial fat, trabeculae, the conduction system, labels, animation.
