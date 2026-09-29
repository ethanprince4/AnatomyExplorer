# Kidney with its nephron: what you have and how to go from one to the other

## Open it

Double-click `viewer\Model Viewer.bat` in the project (`C:\Users\Ethan\Desktop\Desktop Stuff\Claude Anatomy\.claude\worktrees\3dviz-model-quality-review-a03b70`),
then File > Open and pick `kidney.glb` in `C:\Users\Ethan\.anatomy-trial\kidney-review\`. `kidney.viewer.json` beside
it carries the views. `kidney.blend` is the frozen Blender file. What each model changed to fit together: `CHANGES.md`.

Use the viewer from that project folder: the views below need its small new view features (they are in the viewer
since this delivery). An older copy of the viewer still opens the file, but its views would not hide anything.

## The idea

One model, at true size. The nephron is not a copy beside the kidney: it lives inside the kidney, where a
juxtamedullary nephron really sits. Its corpuscle is in the innermost cortex of the middle anterior lobe, just above
the corticomedullary junction and beside the arcuate artery; its afferent arteriole comes straight off that artery;
its loop and collecting duct run down the lobe's medullary ray inside the pyramid, pointing at the papilla. You get
from the kidney to the nephron by zooming in. Nothing is enlarged: every part, kidney and nephron, is at its real
size, and the zoom reaches all the way down to the 0.05 um slits between the podocyte feet.

## Going from the kidney to the nephron

The view buttons along the top run in order, left to right (the number keys 1 to 8 do the same). Each click moves
the camera smoothly to the view; when the scale changes a lot it zooms, going out, across and back in when the two
places are far apart, so you always see where you are going. Any mouse move takes over straight away. A view that
needs parts out of the way hides them itself; clicking **Kidney** shows everything again.

| # | View | What you see | What it hides |
|---|---|---|---|
| 1 | **Kidney** | the whole kidney and adrenal from the front and a little to the side, facing the lobe that holds the nephron | nothing |
| 2 | **Lobe opened** | the same camera; the lobe over the nephron opens up, and inside it hangs a thin thread: the nephron | the renal capsule, the middle anterior lobe's cortical arch and its pyramid |
| 3 | **Lobe** | the opened lobe: the nephron hanging from the inner cortex toward the papilla, beside the arcuate artery and vein and the interlobular vessels | the same three parts |
| 4 | **Nephron** | the whole nephron, 8.7 mm long, from its corpuscle to its hairpin deep in the medulla | the same three parts |
| 5 | **Corpuscle** | the renal corpuscle with the afferent arteriole coming off the arcuate artery, the efferent arteriole leaving, the start of the proximal tubule | the kidney's tissue and far vessels (the arcuate and interlobular vessels at the site stay) |
| 6 | **Juxtaglomerular apparatus** | the macula densa, the granular cells in the afferent wall, the lacis cells | as view 5 |
| 7 | **Podocytes** | one capillary loop bare, with three podocytes and their interdigitating feet | as view 5, and the parietal layer of Bowman's capsule |
| 8 | **Loop of Henle** | the hairpin, 7.2 mm below the corpuscle, with its capillary plexus | as view 5 |

The close views (5 to 8) put the kidney's tissue away because the lobe's walls would otherwise block the viewer's
light: with them shown, none of the corpuscle was reached by the key light; with them hidden, all of it is.

You can also do it all by hand: hide the three parts named in view 2 (or tick them off in Structures), then zoom
toward the nephron with the wheel.

## How big things are on the screen

Nothing is magnified; the views only bring the camera closer. The fields and the matching zoom:

| View | Field across the window | Zoom against the Kidney view | Size on a 40 cm wide window, against life |
|---|---|---|---|
| Kidney, Lobe opened | 236 mm | 1x | 1.7x |
| Lobe | 22 mm | 11x | 18x |
| Nephron | 9.5 mm | 25x | 42x |
| Corpuscle | 1.1 mm | 215x | 365x |
| Loop of Henle | 0.30 mm | 790x | 1,330x |
| Juxtaglomerular apparatus | 0.16 mm | 1,470x | 2,500x |
| Podocytes | 0.05 mm | 4,700x | 8,000x |

## Where the nephron sits, in numbers

- The kidney builder's nephron site NS1 is in the mid-cortex (3.6 mm deep), for a cortical nephron. This nephron is
  juxtamedullary (the only kind with all three limbs), so its corpuscle sits 0.45 mm above the corticomedullary
  junction along its own axis: 6.84 mm below the capsule, where the cortex is 7.2 mm thick.
- NS1's own ray reaches the junction right at the pyramid's rim, where the nephron's loop would run out of the pyramid.
  So the corpuscle moved 2.8 mm along the arcuate artery onto the same pyramid's base, the first place where the
  whole nephron stays inside the pyramid.
- Its axis is NS1's medullary ray: the line to the tip of the papilla (the kidney's baked striations converge there
  too). It leans 38 degrees from the junction's perpendicular, because the ray converges on the papilla.
- The spin about that axis was chosen by a search so the nephron clears every kidney vessel (at least 38 um) and its
  afferent arteriole reaches the arcuate artery on the shortest, gentlest path.

## Known limits, said plainly

- The venous ends (the three ascending vasa recta and the cortical venule) and both collecting-duct ends stay open cut
  ends, as the nephron builder made them, like the kidney's own cut vessel ends: the arcuate vein is 0.39 to 0.52 mm
  from the venous ends, and joining them would mean inventing half a millimetre of vein each. The collecting duct
  stops 5.4 mm short of the papilla's tip (its last stretch, the papillary duct, was not modelled).
- The kidney's small arteries are solid, so the afferent arteriole's lumen ends on the arcuate artery's wall.
- The nephron is embedded in the lobe's tissue, like every nephron; you see it by hiding the parts over it (the views
  do that). Nothing of it pokes out of the tissue.
- Because the nephron leans toward the papilla, its own zone lines (junction, outer and inner stripe) cross the
  kidney's by up to about 0.3 mm across its width.
- Size: 250 parts, 5.19 million triangles (the two models alone are 5.12 million), just above the 5 million mark. The
  viewer reads it in 0.4 s and puts it on the graphics card in 0.2 s (335 MB of buffers).
- The viewer's shadows are fitted to everything shown, so at nephron scale they are soft and broad.

## Credits

- **Kidney, adrenal, vessels and ureter:** built procedurally in headless Blender by the kidney builder from sourced
  sizes (Glodny 2009, Gray 1918, Alyami 2024, Choi 2010, Gregory 2023, Balawender 2018, Standring 2016, Zelenko 2004,
  Mohiuddin 2017, Mompeo-Corredera 2022, Rahmani 2025, Satyapal 1995, Bonsib 2007, Sampaio & Aragao 1990, Shen 2016,
  Yang 2023, Pedersen 1993, Shang 2015, Ansari 2022, Agackiran 2024, Ataee Kachuee 2025, Vincent 1994, Gurun 2021,
  Siddiqua 2014 and 2021, Saadi 2022, Olewnik 2018, Neal 2018). **Z-Anatomy** (CC BY-SA 4.0, from BodyParts3D, CC BY-SA
  2.1 JP) was the kidney builder's reference: its kidney, adrenal and vessels were consulted and its adrenal measured
  (it is oversized, as you suspected); none of its geometry is in this model.
- **Nephron:** built procedurally by the nephron builder from sourced sizes (Madsen, Nielsen and Tisher in Brenner &
  Rector's The Kidney; Puelles 2012; Neal 2018; Dische 1992; da Silva 2020; Lorenzi 2020; Silverman and Glick 1969;
  Kriz, Kaissling and Le Hir; and the rest listed in its `checks/sizes.json`).
- **Integration:** placement, the one join, colours, names and the stage views, this lane
  (`trial/routes/kidney-int/`); every step measured, logged in its `log/events.jsonl`.
