# Models for the Model Viewer

Three new 3D anatomy models, each as a `.glb` with a `.viewer.json` sidecar beside it (the viewer finds the sidecar by
the file's name), and the viewer that opens them (`viewer/`). This is a handoff: nothing under `app/` was changed, and
the models are not wired into Anatomy Explorer yet.

| Model | Folder | Parts | Triangles | 1 unit = | State |
|---|---|---|---|---|---|
| Cardiac muscle (microanatomy block) | `models/cardiac-muscle/` | 257 | 2,775,990 | 10 µm | Finished. Approved by the user on 2026-09-27 (model D with the three requested changes) |
| Whole heart | `models/heart/` | 119 | 2,794,254 | 1 cm | Round 3, frozen 2026-09-29. Delivered for the user's review; no notes back yet |
| Kidney with the nephron, integrated | `models/kidney/` | 250 | 5,188,642 | 10 µm | **Unfinished.** The current state, delivered 2026-09-28 for review |

## Open them

From the repository root, with the app's environment (`setup.bat` creates `.venv` from `requirements.txt`). The viewer
needs PySide6, moderngl, numpy and Pillow (Pillow comes with scikit-image), all installed that way, and a GPU and
driver with OpenGL 4.1 core:

```
.venv\Scripts\python.exe -m viewer models\heart\heart.glb          (Windows)
python -m viewer models/heart/heart.glb                             (macOS / Linux: same command, not tested there)
```

Or drop a `.glb` onto `viewer\Model Viewer.bat` (Windows, uses the repository's `.venv`). Controls and everything else
about the viewer, including how to bring it into the app later, are in `viewer/README.md`.

Headless tests (Qt offscreen, counts only, nothing rendered), all passing on these three files:

```
QT_QPA_PLATFORM=offscreen python viewer/tests/views.py  models/kidney/kidney.glb models/heart/heart.glb models/cardiac-muscle/cardiac_muscle.glb
QT_QPA_PLATFORM=offscreen python viewer/tests/hide.py   models/kidney/kidney.glb models/heart/heart.glb models/cardiac-muscle/cardiac_muscle.glb
```

## What each model is

- **Cardiac muscle**: a block of cardiac muscle tissue at cell scale: 48 cardiomyocytes (each in its endomysium
  covering) joined by 30 intercalated discs, 60 nuclei with 48 pale zones, 18 capillaries with open ends at the block
  faces, red cells. Two states (assembled, and teased with the hero disc opened in place: **T**), cameras V0-V6 and A1.
  No animation clip and no label text. `CHANGES.md` describes the last refinement.
- **Heart**: whole adult heart in 17 structures, with 15 wall panels (each its own part: **H** hides one, **Shift+H** its chamber),
  papillary muscles and chordae, all four valves, coronary arteries and cardiac veins, great vessels. No animation.
  `README.md` and `CHANGES.md` (round 3) say what to look at and what changed.
- **Kidney with the nephron**: one scene at true scale, the kidney (212 parts) with a juxtamedullary nephron (38 parts)
  in place, so one zoom runs from the whole kidney to a podocyte. The file carries eight named views (Kidney, Lobe
  opened, Lobe, Nephron, Corpuscle, Juxtaglomerular apparatus, Podocytes, Loop of Henle) with a scale-aware zoom move
  (`view_transition`, `start_view`, per-view `hidden` lists in the sidecar). `README.md` and `CHANGES.md` describe it.

The `README.md` and `CHANGES.md` files inside the folders are the notes written for the reviewer when each model was
delivered: their file paths and "double-click" hints refer to the original machine, not this repository.

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
does not need them. Re-exporting a model needs Blender 5.2 and those sources (`viewer/tools/export_for_viewer.py`).

## Git LFS

`models/kidney/kidney.glb` (128 MB) is over GitHub's 100 MB limit, so it is stored with Git LFS (a line in
`.gitattributes`), like the other large files in this repository: run `git lfs pull` after cloning if it shows up as a
small text pointer. The other two GLBs (65 MB and 54 MB) are ordinary git files.
