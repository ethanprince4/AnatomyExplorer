# Radiology: clicking "Image labels" row 1 does not visibly highlight the matching 3D structure

- Severity: functional (medium confidence, based on screenshot evidence)
- Case: "CT abdomen — axial, liver and spleen" (Abdomen group)

## Reproduce
./aerun radio2-08 "wait:800;press:Radiology;wait:1200;wclick:0.498,0.342;wait:800;wclick:0.498,0.419;wait:800;press:Open selected case;wait:3500;wclick:0.136,0.673;wait:1000;wclick:0.211,0.735;wait:1500;shot:repro"
(0.136,0.673 = "Image labels" tab; 0.211,0.735 = row "1. Liver, right lobe")

## Expected
Selecting a numbered image label should highlight that structure ("Liver, right lobe") in the 3D view, and the 2D CT marker should match.

## Actual
- The CT marker "1" is highlighted with its tooltip "Liver, right lobe" (correct).
- The 3D view does not visibly highlight the liver right lobe. Instead the 3D label set changes from the default ~15 labels to about 20 liver-segment labels (Porta hepatis, Quadrate lobe, Caudate process, Fossa for gallbladder, etc.) that are not in the case's label list.
- After clicking CT marker "2" (0.205,0.322) the 3D view shows "2 Liver left lobe" and "1 Liver right lobe" with orange leader lines and the liver-segment labels disappear again. So the 3D response is inconsistent between the list row and the CT marker.

## Evidence
- runs/radio2-08/r8_clk1.jpg (after clicking row 1)
- runs/radio2-08/r8_sc.jpg (after clicking CT marker 2; 3D shows the orange highlight)
- runs/radio2-07/r7_il.jpg (Image labels tab before any row click, default 3D labels)
- runs/radio2-08/r8_ctclk.txt

> Coordinator triage: the row click does select the mapped structure ('Liver', run v-r28d), but selecting a whole organ also turns on all of its landmark labels (~20 liver segments/impressions), which bury the case's numbered labels. Suggested: while a radiology case is open, label-row picks should highlight without adding the structure's landmark labels (or map 'right lobe' to the right-lobe landmark).
