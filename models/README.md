# In-house 3D models

Three 3D anatomy models made in Blender for Anatomy Explorer, each a `.glb` with a `.viewer.json` sidecar beside it
(the viewer finds the sidecar by the file's name). They open in the app's model viewer (`app/viewer`, described in
`docs/model_viewer.md`): **Study → 3D models**, **Details → 3D models** when a structure they show is selected, search,
and the lessons and lab-course practice items that use them. The installers ship them.

| Model | Catalogue id | Folder | Parts | Triangles | 1 unit = |
|---|---|---|---|---|---|
| Cardiac muscle (microanatomy block) | `cardiac_muscle` | `models/cardiac-muscle/` | 257 | 2,775,990 | 10 µm |
| Whole heart | `whole_heart` | `models/heart/` | 119 | 2,794,254 | 1 cm |
| Kidney and nephron | `kidney_nephron` | `models/kidney/` | 250 | 5,188,642 | 10 µm |

What the app shows for each - its name, summary, which atlas structures offer it, a readable name, description and
atlas link for every part and group, and the aliases lessons use - is in `data/content/models/<id>.json`. The
cardiac muscle and kidney models replace the app's old procedural cardiac muscle and nephron blocks; the whole heart
is used in the lessons wherever the heart is studied on its own, while the atlas keeps the Z-Anatomy heart in the
body (`docs/model_viewer.md`, *Which heart where*).

Headless check of all three in the app (opens each in its tab, drives it through the app's actions, checks the stored
views' hidden lists and the teased state):

```
xvfb-run -a python tools/check_viewer.py whole_heart cardiac_muscle kidney_nephron      (Linux server)
python tools/check_viewer.py whole_heart cardiac_muscle kidney_nephron                  (Windows / macOS)
```

`python tools/render_model.py kidney_nephron --view Corpuscle` renders one view to `logs/`.

## What each model is

- **Cardiac muscle**: a block of cardiac muscle tissue at cell scale: 48 cardiomyocytes (each in its endomysium
  covering) joined by 30 intercalated discs, 60 nuclei with 48 pale zones, 18 capillaries with open ends at the block
  faces, red cells. Two states (assembled, and teased with the hero disc opened in place: **T**, or the **Teased**
  box), stored views V0-V6 and A1. No animation clip. `CHANGES.md` describes the last refinement.
- **Heart**: whole adult heart in 17 structures, with 15 wall panels (each its own part: **H** hides one; right-click →
  *Hide all …* hides its chamber),
  papillary muscles and chordae, all four valves, coronary arteries and cardiac veins, great vessels. No animation.
  `README.md` and `CHANGES.md` (round 3) say what to look at and what changed.
- **Kidney with the nephron**: one scene at true scale, the kidney (212 parts) with a juxtamedullary nephron (38 parts)
  in place, so one zoom runs from the whole kidney to a podocyte. The file carries eight named views (Kidney, Lobe
  opened, Lobe, Nephron, Corpuscle, Juxtaglomerular apparatus, Podocytes, Loop of Henle) with a scale-aware zoom move
  (`view_transition`, `start_view`, per-view `hidden` lists in the sidecar). `README.md` and `CHANGES.md` describe it.

The `README.md` and `CHANGES.md` files inside the folders are the notes written for the reviewer when each model was
delivered: their file paths, "double-click" hints and keys refer to the standalone viewer they were reviewed in, which
the app's model viewer has replaced (its keys are the atlas's: `docs/model_viewer.md`). They are not shipped in the
installers.

## Where the files came from (integrity)

| File | sha256 |
|---|---|
| `cardiac-muscle/cardiac_muscle.glb` | `581828fe7e0db63d007b3e801f8803bcfb68916efcdc5a63a16381a878fe39ee` |
| `heart/heart.glb` | `8091874c2f7d4341c27fb478e9b7aeeaff90c75d3b7071060bc72fcd68830ddd` |
| `kidney/kidney.glb` | `2d976162ff1f62a2b97bcfa173f4a943e37285f9d6f0b8d0223e2a056602ed95` |

Each GLB was exported from a frozen Blender file (sha256 in the sidecar's `source` block: cardiac `df293625…`, heart
`f0083f46…`, kidney `28963617…`). The `source.blend` and `manifest` paths in the sidecars point at the machine that
built them and are provenance only; the viewer does not read them. The files here are byte-identical to the delivered
ones. The cardiac model was renamed from `model.glb` / `model.viewer.json` to `cardiac_muscle.*` (both files together).

## Not included

The frozen `.blend` sources, the Blender build scripts and the check tools stay on the author's machine; the viewer
does not need them. Re-exporting a model needs Blender 5.2 and those sources (`tools/blender/export_for_viewer.py`, which
writes into `models/<name>/`).

## Git LFS

`models/kidney/kidney.glb` (128 MB) is over GitHub's 100 MB limit, so it is stored with Git LFS (a line in
`.gitattributes`), like the other large files in this repository: run `git lfs pull` after cloning if it shows up as a
small text pointer (the app then leaves the model out of its catalogue, and `packaging/prebuild.py` stops an installer
build). The other two GLBs (65 MB and 54 MB) are ordinary git files.
