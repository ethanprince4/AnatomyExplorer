# What the integration changed in each model, and why

Sources, read only and never saved over (sha256 checked before and after every run):
`kidney-parts/kidney/kidney.blend` (212 parts, 2,626,826 triangles, sha eddcb22a) and
`kidney-parts/nephron/nephron.blend` (38 parts, 2,492,228 triangles, sha cfd774a9).
Result: `kidney-review/kidney.blend`, 250 parts, 5,188,642 triangles. Every number below is in
`trial/routes/kidney-int/log/checks/`.

## The kidney

| Change | Why | Proof |
|---|---|---|
| Every vertex scaled by exactly 1000 and shifted, so 1 unit = 10 um and the nephron's corpuscle is the origin (the kidney keeps its body orientation) | one true-scale scene: the viewer's closest zoom (0.05 units) then reaches 0.5 um, so the whole path from kidney to podocyte is one zoom; the origin at the corpuscle keeps float precision finest where the detail is | every kept part equals its source x1000 within 0.0049 um; its corner normals within 0.017 (set again after the move: moving the vertices alone flipped normals on sliver corners, a logged dead end) |
| Four vessels at the site re-swept finer: Arcuate artery (middle anterior, upper side) 10 -> 64 sides; Arcuate vein (middle anterior, upper side) 10 -> 48; Interlobular arteries and Interlobular veins (middle anterior, upper side) 8 -> 32 | at nephron scale these four sit in the close views (the nearest is 68 um from the nephron) and their 8-10 sides would read as polygons at 200-1,500x; the artery also carries the join | the kidney builder's own sweep code on the centrelines and radii its own path code reproduces (median 0.06 um from the delivered rings); the delivered vertices lie within 0.09-0.23 um (median) of the new surfaces; same names, materials, flare, caps and tunnels; 8,236 -> 70,912 triangles |
| Nothing else | the brief: keep the content as delivered | 208 parts identical after the unit change |

The re-swept vessels sit in the tunnels cut for the coarser ones; where the finer surface bulges past the old flat
faces it reaches up to 13 um into the surrounding tissue (the delivered vessels already reached 11 um; the kidney
builder's accepted overlaps went to about 80 um). All inside the tissue, where it cannot be seen.

## The nephron

| Change | Why | Proof |
|---|---|---|
| Placed in the kidney: turned by one rotation (its object matrix), corpuscle at the origin; mesh data untouched | it lives in place: innermost cortex of the middle anterior lobe, 0.45 mm above the junction along its axis (6.84 mm below the capsule), axis on NS1's ray to the papilla tip, spin chosen by search | 36 of 38 parts' mesh data identical to the source (difference 0.0); the two below keep every source vertex up to the trim unmoved |
| The afferent arteriole continued to the arcuate artery (the one join): both parts trimmed at their last clean ring before the open end (0.0041 mm back) and continued from those exact rings, 72-86 um further on a smooth curve (turning 33 degrees in all, never tighter than a 59 um radius), same lumen (21 um) and wall (6.6 um), the smooth muscle flaring 1.5x onto the artery | the delivered arteriole ended in an open stub "near the arcuate artery"; at the site it now leaves the arcuate artery, as juxtamedullary afferent arterioles do (from the first stretch of a cortical radial artery or straight from the arcuate artery) | 0 open, 0 non-manifold, 0 misoriented edges; 192 rim vertices on the artery's drawn surface within 0.00013 um; the endothelium's and smooth muscle's shared surface coincident (gap 0.0); the new stretch at least 145 um from every other nephron part; the red cells stay in the lumen |
| Names in plain words, like the kidney's: `afferent_arteriole_smooth_muscle` -> "Afferent arteriole smooth muscle", `parietal_layer_of_bowmans_capsule` -> "Parietal layer of Bowman's capsule", `collecting_duct_cortical` -> "Cortical collecting duct" and so on (the builder's own words; full list in `build/names.py`) | one naming style across the model, the one you review by; the nephron's structure titles were already in plain words | 38 renamed, 0 collisions |
| Structure ids S01-S33 -> S41-S73 | the kidney also uses S01-S35; the same id would merge a kidney group and a nephron group in the Structures panel | 63 structure groups, none shared |
| Afferent arteriole smooth muscle now uses the kidney's artery material; Cortical venule the kidney's vein material | the same tissue gets one colour, and the arteriole meets the arcuate artery with no colour step (your heart note R13) | materials `arteriole_media` and the nephron's `vein` removed, nothing else recoloured |
| The venous ends, the collecting duct's two ends: unchanged, still open cut ends | the arcuate vein is 0.39-0.52 mm from the venous ends; joining them would invent vessel; open cut ends are this project's convention for vessels that continue | `log/checks/open_ends.json` |

## Where the two meet (checked together)

- The nephron touches one kidney part, the arcuate artery, at the join; every other vessel, the calyx, capsule and
  sinus fat are at least 303 um away, and no nephron point lies inside any of them.
- The nephron lies inside the lobe's tissue (cortical arch and pyramid) as nephrons do: of 208,199 sampled nephron
  vertices, 208,001 are inside tissue, 198 in the arcuate artery's tunnel (the arteriole's last stretch), 0 outside.
  No pocket is carved: it would add about 100,000 hidden triangles only to satisfy an overlap check.
- All 250 parts closed: 0 open, 0 non-manifold, 0 misoriented edges.

## The viewer (small additions, only active for a file that asks for them)

A view can name the parts it hides; a file can ask for the zoom-style move between views and name its start view;
view buttons fit their names; number keys step through named views. Files without those keys behave as before:
smoke.py, hide.py and a new views.py pass on the cardiac rebuild, the heart, the kidney and the nephron files.
