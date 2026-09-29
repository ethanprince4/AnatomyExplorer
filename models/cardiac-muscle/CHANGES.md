# What changed

This is model D (the refinement you rated 8) with exactly your three changes, and nothing else.

## Pale-zone tips

- **Source:** "Myocardial lipofuscin (original).jpg" by Mikael Häggström, M.D., an H&E section of heart muscle on
  Wikimedia Commons, public domain (CC0):
  https://commons.wikimedia.org/wiki/File:Myocardial_lipofuscin_(original).jpg
  The pale zones there hold yellow-brown lipofuscin grains, so their outline stands out clearly against the red fibres.
- **How it was measured:** 11 zone tips from 8 zones, traced from the pixel colours (not by eye), each fitted with
  the same shape as the model: a cone of some taper angle ending in a round cap of some radius. The traced points and
  the fit for every tip are in `pale-zone-tip-anatomy.json`.
- **What the figure shows:** the zones do taper to a tip, at about the same angle the model already had, but the tip
  is round, not a point: the round cap is about one fifth of the zone's half-width.
- **Before -> after (62 tips that are not cut by a block face):**
  - taper half-angle: 11.2° (9.8-12.9°) -> 12.2° on every tip (the figure's median)
  - apex radius: essentially a point (0.015 µm, 0.5 % of the half-width) -> 0.64 µm (20.5 % of the half-width)
  - "triangle at the end" (the half-angle of the triangle from the apex to where the zone reaches 10 % of its
    width; smaller = sharper): 11.7° (10.3-13.5°) -> 75.4°. The tip now ends in a small dome.
- Every zone now gets the same tip angle and apex, whatever the shape of its nucleus. The tips are a little shorter
  than before (about 0.5-0.7 of a nucleus length past the nucleus, was 0.72). No zone pokes out of its cell (0 before
  and after).

## Capillary ends

- **Before:** 15 of 36 ends open, 21 capped. Every vessel ended in a rounded cap at the -X side. The three vessels
  cut open along the front face were capped at both ends.
- **After: 36 of 36 open, 0 capped.** Each vessel runs on past the rounded cell ends on the -X side and is cut open on
  one flat plane (x = -10.0, just inside the block's existing edge, so the block did not grow). This works like the
  +X face, so each vessel reads as cut where the tissue sample ends. The three front vessels now also run to the +X
  face and are cut open there. Every cut rim is softened like the existing +X rims.
- Measured by geometry: a ray sent into each end travels at least 5 µm into an open lumen (every end: the full 10 µm
  the test allows). The walls stay closed solids. Every extension clears every cell and every other vessel. Every
  vessel keeps its old path, and no red cell moved.
- Why a plane on the -X side: that side has no flat face (whole rounded cells). Other options were loops joining vessel
  ends in pairs (new vessel shapes nobody asked for) or an open end at each cell's own tip (ragged, no common edge).

## Label data removed

- D had added invisible text data: a label on all 257 parts, a caption and an anchor point on the opened disc, and on
  every one of the 30 discs a record of which two cells it joins and the fibre direction. All of it is gone, from the
  model and from the viewer file.
- Every part now keeps exactly the properties the original model had (its structure name and ID, the "label" on
  capillaries, binucleate cells, the plum red cells and the junction plaques, and the tags for the opened disc).

## Everything else

- The same 257 parts, the same materials and the same layout. Only the 48 pale-zone meshes and the 18 capillary
  meshes changed. Every other mesh is identical to D's, checked point for point (D's build reproduced exactly: 257
  of 257 identical before any change).
- Triangles 2,704,544 -> 2,760,228 (the vessel extensions and the rounded caps); still under 3M.
- Seen, not changed: the harness still reports 0.875 of cells with a capillary nearby (D's value).

## Follow-up: one nucleus unit, copied everywhere (your notes 1 and 3)

- **What changed:** every nucleus with its pale zone is now the same unit: perinuclear zone 39
  (`perinuclear_zone__039`, with `nucleus_myocyte__050`, in `cardiomyocyte__039`; the top-middle unit on the long cut
  face). Nucleus 14.3 x 5.4 µm, zone 27.9 x 6.2 µm, everywhere. Nothing else moved.
- **Right half, mirrored:** "right" is screen-right in the long-cut-face view (V2), which is world -X. If you meant the
  other half, say so. The unit was split across its long axis at its middle, the left half dropped and the right half
  mirrored; the seam is one shared ring (closed, no crease).
- **Why zone 39 looked lopsided:** the zone itself was already the same at both ends. Its axis ran 0.8° out of the cut
  face, so the face sliced it deeper at one end: its section ran 9.0 µm right of the middle and 10.3 µm left. Every
  copy cut by the long face now lies parallel to the face at the depth that shows the right half: 9.1 µm each way,
  within 0.06 µm of the old right half. All 11 units on the long face show the same section (within 0.02 µm).
- **Two-nucleus cells (12):** two separate copies, one per nucleus, in a row along the cell, 1 µm between their tips,
  centred where the pair was. Cells 1 and 40 slid 1 µm and 0.5 µm along the cell to fit. Cell 2 (bottom front row,
  middle, between two discs) has room for only 0.4 µm between the tips; they do not touch. Both copies stay in the
  cell's one pale-zone part, so no part name changed.
- Units cut by the long face or the end face are still cut by that face.
- **Checked by geometry:**
  - 60 units (60 nuclei; 60 zones in 48 zone parts), each the same shape as zone 39's copy: largest difference
    0.00001 µm (cut units compared where they are not cut).
  - Nucleus width / cell width 0.27-0.31 (median 0.29), all inside the sourced 0.20-0.35.
  - No unit pokes out of its cell (0 points outside); every zone stays at least 0.55 µm inside its cell.
  - Everything else is identical point for point: 149 of 257 parts unchanged, only the 60 nuclei and 48 zones changed;
    names, materials and properties unchanged. Triangles 2,760,228 -> 2,775,990.

**The file to open:** `C:\Users\Ethan\.anatomy-trial\p81-review\model.glb`. Keep `model.viewer.json` beside it.
Open it in `viewer\Model Viewer.bat` with File > Open, or drop the .glb onto the viewer. The previous version is kept
beside it as `model-v1.glb` (with `model-v1.viewer.json`).
