# What changed in round 3: the outside gaps are closed, the aorta's opening is clear, the papillary muscles are half size, and the wall panels shade cleanly

## The file to open

- `C:\Users\Ethan\.anatomy-trial\heart-review\heart.glb`, with `heart.viewer.json` beside it. Double-click
  `viewer\Model Viewer.bat` in the project and use File > Open, or drop the .glb onto it. `README.md` explains the
  panels (click one, **H** hides it, **Shift+H** its chamber, **Alt+H** shows all).
- The frozen Blender file is `heart.blend` in the same folder.
- Round 2 is kept beside it as `heart-v3.glb`, `heart-v3.viewer.json`, `heart-v3.blend`, `README-v3.md` and
  `CHANGES-v3.md`. Rounds 1 and 0 are still there as `heart-v2.*` and `heart-v1.*`.

## Your notes, one by one

Numbers come from probes on the geometry, never from looking. A "shaded off" face is one whose shading turns more
than 45° away from its own surface: it shows as a dark or bright patch. A "gap" is how far a piece's edge stands off
the exact line where it should meet its neighbour; 0.01 cm is 0.1 mm.

- **S1** the crater on the left-ventricle apex: **done.** It was a flat patch where the meshing grid clipped the
  ventricle: 249 vertices sat on the grid's edge, and 104 faces were shaded off. Now 0 and 0.
- **S2** the pulmonary trunk "compensating for a valve": **done.** The three sinuses no longer show through. The outer
  radius over the sinus heights differed between sectors by 0.034-0.061 cm. Now it differs by 0.001 cm or less. The
  root's outside is one smooth round surface, 1.38 cm at its base and 1.42 cm where the trunk begins; the sinuses stay
  inside, where the cusps sit. Faces shaded off: 214 to 3. Sharp edges: 20.5 to 1.0 cm.
- **S3** the rough border of the outflow tract and the right ventricle's front wall: **partly done.** The discoloration
  is much less: faces shaded off went from 530 to 190 (outflow tract), 142 to 8 (front wall) and 407 to 92 (septum).
  Across their seam the surface turns at most 44° per cm (it was 97°), median 18° (was 13.5°). Where the septum
  reaches the surface the seams still turn 55-70° per cm: that is the groove between the ventricles itself, and I
  left it. My first "ridge" count went up, but it only measures how wide a gently curved band is; see "Seen".
- **S4** the discoloration where the left ventricle's lateral wall, inferior wall and apex meet: **done.** The three
  panels now meet on one exact point (the lateral wall stood 0.031 cm off it, the inferior wall 0.021 cm; now 0.000
  for both). Faces shaded off: apex 21 to 4, inferior wall 85 to 11.
- **S5** the right ventricle's wall pulled out to fix the IVC join: **done.** The ventricle's wall is back to the
  ventricle's own shape (vertices 0.25 cm or more off it: 321 to 0; vertices within 0.5 cm of the IVC: 225 to 0), and
  the join is made in the right atrium's posterior wall, in the atrium's colour. Its faces shaded off: 111 to 0.
- **S6** rough edges on the trunk's start and middle: **done.** The trunk starts flush on the outflow tract: outer
  radius 1.381 cm just above the start, 1.380 just below. There is no ring-shaped edge (profile bend 0.83 per cm).
- **S7** gaps where the SVC and the two brachiocephalic veins meet: **done.** Largest gap at the corner 0.038 cm to
  0.014 cm; the slit through the wall 0.037 to 0.005. Along the left brachiocephalic vein's seam with the SVC,
  samples over 0.02 cm went from 6 to 0.
- **S8** the gap where the interatrial septum and the left atrium's front and back walls meet: **done.** The corner
  gap went from 0.032 cm to 0.0001. A hairline slit through the wall stays at 0.026 cm (it was 0.032).
- **S9** the gap between the right atrium's back and side walls near the IVC: **done.** Largest gap along the seam
  0.050 cm to 0.005; the slit through the wall 0.033 to 0.005. (A mesh repair step had pulled back a few corners by
  up to half a voxel; it now nudges them into place.)
- **S10** the tiny gaps between the right ventricle's front and lower walls and the apex: **done.** Seam 0.022 to
  0.018 cm; slit through the wall 0.032 to 0.009; corner 0.0007.
- **S11** the gap at the exposed septum: **done.** Corner 0.060 cm to 0.0001; slit 0.044 to 0.018. The exposed septum
  itself is as you liked it.
- **S12** the left atrium's back wall dipping between the pulmonary veins: **done.** A low web fills each side. Dip
  depth: right 0.42 to 0.02 cm, left 0.47 to 0.10.
- **S13** the gap where the right atrium's back wall meets the SVC: **not changed.** That seam is closed to 0.05 mm at
  321 of 322 probe points; one pinhole of 0.019 cm is left, exactly where it was. I could not find a second gap.
- **S14** the septum not smooth with the heart open: **done.** Faces shaded off 407 to 92; sharp edges 38 to 16 cm.
- **S15** papillary muscles half size, chordae refitted: **done.** Lengths: mitral 2.0 to 1.0 cm, tricuspid front 1.8
  to 0.9, back 1.2 to 0.67 (a smaller one would fall under the sourced minimum), septal 0.75 to 0.375. Widths go from
  0.82 to 0.41 (mitral), 0.61 to 0.32, 0.53 to 0.38, 0.57 to 0.37. Volumes are about a fifth of what they were. All 30 chordae start inside their muscle and were refitted (median length 1.49 to 1.41 cm; thickness as you
  approved it). Three of the septal muscle's cords poke out of it by up to 0.06 mm, which is the mesh, not a fault
  you would see.
- **S16** where the muscles join the walls: **partly done.** Sharp edges off the join: mitral muscles 1.4 to 0.6 cm,
  tricuspid front 0.26 to 0.04, back 0.51 to 0.15. The tricuspid septal muscle went from 0.0 to 0.53 cm, and it is now
  only 0.4 cm long. The join lines stay as straight as before (1.04-1.10, where 1.0 is a straight line).
- **S17** the muscles' colour: **done.** All five use the ventricles' own material.
- **S18** hard edges and shadowy patterns in the left ventricle: **done for three of the four panels.** Faces shaded
  off: front wall 126 to 6, lower wall 85 to 11, apex 21 to 4. The side wall stays at 78 to 66, and its sharp edges
  went 6.8 to 7.3 cm.
- **S19** the triangle across the aorta's opening and the ridge: **done.** The opening runs straight up the aortic
  axis. Of rays fired up that axis from 1.2 cm below the valve, 79 % now pass (it was 30 %); from 0.6 cm below, 91 %
  (55 %). What is left is the septum and the curtain beside the opening.
- **S20** the aorta coming through the septum: **done.** The root now starts at the valve ring. Root points showing
  inside the ventricle: 399 to 0. Root vertices below the ring: 3,082 to 0.
- **S21** the left atrium not meeting the mitral ring: **done.** The atrium reaches the ring all round: the largest
  gap went from 0.30 cm to none, and angles round the ring with a gap from 31 of 72 to 0.
- **S22** the right atrium's detached strip, the tricuspid ring and the right auricle: **done.** The side wall is one
  piece (it was three); the strip over the tricuspid ring belongs to the auricle. The atrium reaches the ring
  (gap 0.10 cm to none; 24 to 0 of 72 angles). Faces shaded off: auricle 162 to 91, side wall 136 to 95, back wall
  81 to 58.
- **S23** the coronary arteries' colour: **done.** All 19 arteries now use the aorta's own colour and shininess. The
  veins keep their blue.
- **S24** the lower ascending aorta: **done.** Faces shaded off in its lower part 262 to 0; sharp edges 30.1 to
  18.5 cm; whole part 247 to 72.
- **S25** every piece on its own: **mostly done.** Parts made of several separate shells: 4 to 0 (right atrium's side
  wall had 3, right ventricle's front wall 2, the left main coronary artery 9, the right coronary artery 2). Faces
  shaded off over all wall panels: 2,130 to 814 (5,058 to 2,775 in all 119 parts). Sharp edges away from seams: 401 to
  254 cm in all. Open edges 0, spikes 0. Left: the rims round the pulmonary veins' openings in the left atrium's back
  wall (117 faces, was 110) and a few small knots where three panels meet.
- **S26** the interatrial septum bulging into the left atrium: **done.** Concave vertices on its left-atrial face 924
  to 388; the largest concave patch 823 to 175. The aortic root's own bulge into the atrium's front wall is anatomy
  and stays.
- **S27** the right pulmonary artery swelling to take in the trunk's outcrop: **done.** Its reach past its own tube
  0.50 cm to 0.11; vertices more than 0.1 cm beyond 854 to 1.

## Kept as you approved

- Point for point: all leaflets and cusps, both valve rings.
- Their shape and course, apart from what your notes required: the great vessels, the left auricle, the coronary
  arteries and veins, the coronary sinus's outside connection. The great vessels moved by 0.02 cm or less except
  where S2, S6, S20, S24, S27 asked (ascending aorta, trunk, both pulmonary arteries).
- **Because the surface under them moved:** the conus artery ran on the old, narrower outflow tract and would have
  sunk 0.4 cm into the wall, so it is laid again on the surface as it is now (moved up to 0.45 cm, 0.27 on
  average, outward). The AV
  nodal artery moved up to 0.22 cm (median 0.10) with the crux under S5. A handful of vertices on ten other coronary
  vessels moved by 0.017 cm or less; their courses did not change.

## Seen but not changed

- My first count for S3 ("ridge vertices", curvature over 2 per cm) rose from 447 to 588. It counts how wide a gently
  curved band is, not how flat the surface is, so I replaced it with the turning across the seam (above).
- The seam between the interatrial septum and the left ventricle's front wall, inside the heart beside the aortic
  root, has one 0.06 cm notch (it was 0.03); the mesh repair that closed S9 and S7 left it a little worse.
- The right ventricle's outflow tract has a knot about 0.3 cm wide just under the pulmonary valve, where three
  panels meet; a few triangle pairs cross there. Similar small knots sit at other three-panel corners.
- The left pulmonary artery has a 0.03 cm crack in one place along its seam with the trunk.
- The check that keeps intramural vessels inside the wall misread the AV nodal artery (it is inside all along), so I
  added a test on the tube's whole cross-section. It passes this model and fails a copy with the artery lifted out.

## Proof that nothing else changed

- The unchanged build reproduced round 2 exactly (119 of 119 parts identical point for point).
- After the fixes: 32 parts unchanged point for point; 87 changed, none added or removed, every one of them under one
  of your items or a stated consequence (above). The leaflets, cusps and rings are among the unchanged.
- Blood spaces: three (left, right, outside), and every opening leads only where the anatomy does, with the valves
  hidden, plugged, or all parts in.
- Every part is closed (0 open edges); 2,794,254 triangles. All 15 model checks pass on the model and on the viewer
  file, and so do the viewer-file payload checks.

## Time and cost

- Wall clock: about 15 hours in all, from the evening of 2026-09-28 to the late morning of 2026-09-29: about eight hours
  of the earlier session's build work, the rest this session's finish (four more full builds of 30-40 minutes each). Tokens:
  this session about 0.5 million; the earlier session's are not recorded here. No checker agents, no renders.
