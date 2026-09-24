# Anatomy Explorer

A native Windows desktop 3D anatomy viewer. It has its own OpenGL renderer and a Qt interface, and it runs entirely offline on your machine.

- 106 guided lessons in 498 steps, filed by body system and by region, with 409 recall questions built into them; 24 labelled radiology cases, five of them showing pathology; spaced-repetition revision, a dissection slider that peels the body apart, and self-labelling cross-sections.
- 3,922 structures and 11.6 M triangles: bones, joints and ligaments, muscles, tendons, bursae, fascia, arteries, veins, heart, lymphatics, brain, cranial and spinal nerves, sense organs, viscera, skin regions.
- 1,109 bony and organ landmarks, 3,160 descriptions, Latin names and Terminologia Anatomica 2 IDs.
- Muscle origins and insertions mapped onto bones. Innervation for 278 muscles.

## Launching

Double-click **Anatomy Explorer** on the desktop. You can also use `Anatomy Explorer.bat` in this folder.
If something goes wrong, run `run_debug.bat` to see errors in a console. Errors are also written to `logs\errors.log`.

On a new PC, or if `.venv` is deleted, run `setup.bat` once. It installs the Python packages, rebuilds the dataset if it's missing, and recreates the desktop shortcut. It needs Python 3.10 or newer from python.org.

The repository (private, github.com/ethanprince4/AnatomyExplorer) carries the built dataset, the histology and radiology images and the downloaded Sketchfab models, so a clone runs without rebuilding anything. The four files over GitHub's 100 MB limit are stored with Git LFS (listed in `.gitattributes`): install Git LFS before cloning, or run `git lfs pull` afterwards, or those files arrive as small pointer files. Not in the repository: `.venv`, the portable Blender and the Z-Anatomy source it reads (`data/raw`, `data/extracted`, only needed to rebuild the dataset), the micro-model cache (rebuilt on first use), `logs/`, and `data/user/` — your study progress and the Sketchfab API token. The downloaded models keep their creators' Creative Commons licences, several of them non-commercial or no-derivatives, so they must come out of the repository before it is ever made public.

## Using it

| Action | How |
|---|---|
| Rotate / pan / zoom | Left-drag / right- or middle-drag (or Shift+drag) / mouse wheel (zooms toward the cursor) |
| Select | Click. Ctrl+click adds to the selection. Double-click selects and focuses |
| Search | Ctrl+F, then type a structure, group ("brachial plexus"), landmark ("clinoid") or Latin term. Enter jumps to the top result |
| Focus a search result | The result is highlighted and framed, and everything else goes x-ray. Hidden parts of the selection show through with a hatched overlay |
| Filter | **Systems** tab: systems, subsystems, opacity and presets. **Regions** tab: body regions. **Tree** tab: full anatomical hierarchy with checkboxes |
| Hide / isolate / x-ray | H / I / X (also on the toolbar and the right-click menu). Shift+H shows everything. Ctrl+Z undoes. Esc clears |
| Views | 1 anterior, 3 right, 7 superior. Ctrl+1/3/7 give the opposite views. F frames the selection. Home resets the camera |
| Cross-sections | Toolbar **Cross-section**, or the **View** tab (sagittal / coronal / transverse, each with a slider and a flip). The cut face labels itself: every structure the plane passes through is named around the edge of the view, click a label to select it, and the **View** tab lists them all |
| Dissect | Toolbar **Dissect**, the slider on the **View** tab, or **]** / **[** to step. The body comes apart from the skin inwards. Depth is measured as a fraction of how thick the body is at each point, so the hand and the thigh are uncovered together. "Show only this layer" gives a slab instead of a peel |
| Measure | **M**, then click two points. Shift+click adds another leg, which also reports the angle. Esc clears |
| Colors | Realistic; Distinct segments (muscles by function, bone and lung segments, lobes); By body system. Right-click → Set color… for one structure |
| Screenshot | F12. **Ctrl+Shift+S** exports a captioned figure instead: the view, its title, and a caption listing what is in it (also copied to the clipboard) |
| Window | **F11** is true fullscreen — the window takes the whole screen and sits above the shell, so nothing else is reachable until you leave it. **Shift+F11** is borderless instead: the title bar goes, the window fills the screen's work area, and the taskbar, alt-tab and every other window carry on working normally. Drag the empty part of the menu bar to move it. Both are in the **View** menu with a tick beside the one you are in, and the mode is remembered between runs. **Ctrl+B** hides the side panels for a few hundred more pixels. Explore and Details are side panels and always open docked — if one gets dragged or double-clicked into a floating window, **View → Dock the side panels** puts it back, and it is docked again on the next launch either way |

The **Details** panel lists everything known about the selection in collapsible sections: key facts (Latin name, TA2 ID, hierarchy), clinical correlations, histology, 3D microanatomy, innervation, muscles a nerve supplies, attachment areas (shown on the bone with origins in red and insertions in blue), neighbouring structures – each marked as lying superficial or deep to the selection – landmarks, your note and the full description. All links in it can be clicked. Alt+Left / Alt+Right (or the mouse back/forward buttons) move through what you've viewed.

## Study features

| Feature | How |
|---|---|
| Lessons | Ctrl+L or toolbar **Lessons**: 106 guided walks in 498 steps. The library is segmented by **body system** (skeletal, muscular, cardiovascular, respiratory, digestive, urinary, reproductive, endocrine, lymphatic, nervous, special senses, skin and fascia), by **region** (head and neck, back, thorax, abdomen, pelvis, upper limb, lower limb, whole body) or by **level** (foundation, core, advanced) — one click switches between the three. Every lesson opens with what you should be able to do by the end and closes with what to remember and where to go next; 409 of the steps ask you a question before you move on, with the answer hidden until you ask for it, and steps can carry a mnemonic, a common mistake or a clinical note. Each step also sets the view up for you – switching systems, dissecting to a depth, isolating, sectioning, or opening the matching micrograph or 3D microanatomy model – and "Quiz me" tests you on everything the lesson named. How far you got is kept between runs: the cards show a progress bar, finished lessons are ticked green, and a **Continue** card at the top picks up where you left off (`data/user/lesson_progress.json`). Search finds lessons too. Content lives in `data/content/lessons_*.json`; `tools/check_lessons.py` validates it. See `docs/lessons.md` |
| Radiology | Ctrl+R or toolbar **Radiology**: 24 cases put a real radiograph, CT or MR slice beside the live model, labelled on both sides. Five of them show disease – a massive pleural effusion, right middle lobe pneumonia, a pneumothorax, heart failure – and the model shows the pathology itself: fluid filling the pleural cavity with the lung floated up off it, a lung collapsed back to its hilum inside a translucent pleural space, a consolidated lobe, an enlarged heart, a shifted mediastinum. Those meshes are derived from the normal anatomy by `tools/build_findings.py` and live in their own Findings system. Choosing one sets the 3D view up to match the film – the same systems, the same way round, ghosted where the beam sees through, and cut in the same plane at the same level for the cross-sectional cases. Click a numbered label on the image, or a line in its legend, and the model selects and frames the same structure; each case also carries how to read that film. Search finds cases too. Content lives in `data/content/radiology*.json`, images and their licences in `data/radiology`; `tools/check_radiology.py` validates every coordinate and name |
| Online 3D models | **Study → Online 3D models (Sketchfab)** opens a tab with a curated list of teaching models from Sketchfab beside Sketchfab's own player — annotations, animation, wireframe and the model inspector all work as on the website. With **Use my controls** on (the default) the model is driven by the atlas's own camera code instead of Sketchfab's: the same mouse buttons, sensitivities, inversion, easing, 1/3/7 views, F, Home, arrow/WASD keys and auto-rotate, taken from Settings — a transparent layer takes the input and moves the player's camera through Sketchfab's official Viewer API. Zoom goes to the centre of the view rather than the cursor (the API cannot say what is under it); switch the box off to use Sketchfab's own controls and click its annotation hotspots, or jump to an annotation from the list. Selecting a structure in the atlas lists any matching model under **Details → Online 3D models**, search finds them by name, and **Show in the atlas** goes the other way. The models stream from sketchfab.com through the public embed that Sketchfab offers for every published model, so they need an internet connection and nothing is downloaded or copied; each stays its creator's, credited in the tab. The player runs in an off-the-record web profile (no cookies or cache saved) with do-not-track set. The list lives in `data/content/sketchfab.json`; `tools/check_sketchfab.py --live` validates it |
| Downloaded 3D models | Models whose creators allow downloads (21 of the list, all Creative Commons) can also be fetched once through Sketchfab's official Download API — `python tools/fetch_sketchfab.py`, with your own API token from sketchfab.com → Settings → Password & API in `data/user/sketchfab_token.txt` — into `data/sketchfab_models/`. They then open offline in the atlas's own renderer (**Study → Downloaded 3D models**, the **Open downloaded copy** button in the Sketchfab tab, or the model's name under **Details → 3D models**): your controls, clickable parts with a part list, hide/isolate/X-ray, cut-away, labels and **Separate parts**, with the creator's colours, vertex painting and textures. Each part carries a proper name, a short description and, where it depicts a structure the atlas has, a **Show in the atlas** link; the naming lives in `data/content/sketchfab_parts/<uid>.json` (`tools/sketchfab_parts.py` lists a model's raw parts and `--check` validates the files). The creator and licence are shown in the tab; **Sketchfab player** opens the same model online with its annotations. Only models marked downloadable are fetched — the rest stay in the embedded player |
| Clinical correlations | 250 entries shown in Details for the structures they concern: specific disease states, injuries and procedures unique to that part. Search finds them by name or by the signs and syndromes they mention ("Colles", "Horner"). Content lives in `data/content/clinical_*.json`; add your own entries in the same format |
| Histology | **Histology** tab on the left: a tree of basic tissues and organ systems with micrographs from Wikimedia Commons. Selecting a structure also lists matching tissues under Details → Histology. Clicking a thumbnail opens the viewer (zoom with the wheel, arrows for next/previous, Show in 3D) |
| 3D microanatomy | Details → Microanatomy (3D), or the top folder of the Histology tab. Twenty-five procedural models open in their own tab (thin, thick, scalp and axillary skin; jejunum, duodenum, ileum, colon, stomach, oesophagus, trachea, bladder; muscular and elastic arteries, veins; lung acinus; osteon; skeletal muscle; nephron; liver lobule; peripheral nerve; cornea; retina; thyroid follicles; tongue papillae and taste buds). Every layer, gland and cell group can be selected, hidden or x-rayed, with a corner cut-away, labels, tissue opacity and exploded layers. Cut faces are shaded like a stained section, with nuclei, fibres and cell outlines |
| Quiz | Ctrl+Q or toolbar **Quiz**. Four modes: find the named structure in 3D, **hunt** it down through the whole body, name the highlighted structure (multiple choice), or type the name. In both find-type modes **right-click peels away** whatever is in the way (Ctrl+Z puts it back) and the naming context menu is suppressed, since its first line would give the answer. Questions come from what's visible, one chosen system, a lesson, or what a cross-section cuts through, and the mode you last picked is remembered |
| Hunt mode | The deep end. Every system is switched on, the Explore and Details panels are closed and nothing on screen is named — no labels, no hover tooltip. You get one structure to find: move as usual, **right-click** to peel a structure out of the way one at a time, **left-click** the one you think it is. Three tries; a wrong click is not named, so nothing gives the game away. After the third it shows the answer in green and lists the three things you actually clicked. Ctrl+Z puts back the last thing you hid, and **Put everything back** restores the lot. Targets are drawn from the ~500 structures the lessons, radiology cases and clinical notes actually name, so you are never asked to pick out one intervertebral disc from another; tick *Hunt: anything at all* to open it up to the whole atlas, or set a Topic to hunt within one system |
| Spaced repetition | Every answer schedules that structure to come back: a day later if you missed it, then four days, then longer each time you get it right. **Review what is due** on the quiz page starts a session from the schedule, and **Study → My progress** shows accuracy, how many structures are well known, what falls due over the next fortnight, and the ones you keep missing (`data/user/quiz_stats.json`) |
| Notes | N adds a note to the selected structure. Study → All my notes lists them (`data/user/notes.json`) |
| Saved views | Ctrl+D saves the camera, visibility, selection and cross-sections. The last session is restored on launch (can be turned off in Settings) |

## Settings

Ctrl+, opens Settings:

- **Mouse & Camera:** orbit, pan and zoom sensitivity, inversion, which button orbits or pans, zoom to cursor, orbit around cursor, animation speed, field of view.
- **Display:** UI and text scale, label size and count, render scale, anti-aliasing, ambient occlusion, background and highlight colors.
- **Behavior:** click and double-click actions, selecting both sides, session restore.
- **Keyboard:** every shortcut can be rebound, with conflict detection.

## Customizing

| What | Where |
|---|---|
| Lighting, selection/hover colors, backgrounds, default settings | `app/config.py` |
| Material colors, systems, subsystems, regions, which layers are on by default | `tools/build_dataset.py`, then re-run it (about 3 s): `.venv\Scripts\python.exe tools\build_dataset.py` |
| Shaders (lighting, x-ray look, outlines, ambient occlusion) | `app/shaders.py` |
| Rendering passes, picking | `app/renderer.py` |
| Mouse controls, labels, orientation gizmo | `app/viewport.py` |
| Panels and toolbar | `app/ui/*.py`, `app/main_window.py` |
| Search ranking and synonyms | `app/search.py` |
| Pathology meshes | `tools/build_findings.py` → `data/findings`. Each finding is a transform of existing geometry (an effusion is the lung's volume below a fluid level, a collapsed lung is the lung contracted to its hilum) and `app/findings.py` appends them to the atlas at load time. See `docs/radiology_cases.md` |
| Radiology cases | `data/content/radiology*.json` – one object per case: the `id` of a downloaded image, a `crop` if only part of the file is wanted, the teaching `text` and `reading` list, a `scene` in the same format as a lesson step, and `labels` at 0–1 coordinates of the (cropped) image. `tools/grid_overlay.py` writes a coordinate grid over an image so label positions can be read off; `tools/fetch_radiology.py` downloads new images and records their licences |
| Guided lessons | `data/content/lessons_*.json` – plain JSON, one object per lesson: `system`, `region` and `level` file it in the library, `objectives`, `takeaways`, `prereq` and `see_also` wrap the teaching round it, and each step may name `focus` and `show` structures, a `side`, a `systems` preset, a `dissect` depth, a `clip` plane, a `view`, a `micro` or `histology` id, and a `check` question with its answer. `tools/name_probe.py` checks a name before you write it, `tools/check_lessons.py` validates the whole library afterwards. Full schema in `docs/lessons.md` |
| How deep each structure counts as | `app/depth.py` (cached in `data/anatomy/depth.npz`) |
| What a cross-section is deemed to cut | `app/section.py` |
| Review scheduling | `app/srs.py` |

Code changes take effect the next time you launch; nothing needs compiling.

## How the data is built

`tools\build_all.bat` rebuilds everything from source:

1. Downloads the Z-Anatomy Blender atlas and the TA2 term list.
2. Downloads portable Blender 3.6. It's used headlessly, only to read the `.blend` file.
3. `tools/export_zanatomy.py` exports every mesh and curve with its hierarchy, landmarks and descriptions to `data/extracted`.
4. `tools/build_dataset.py` converts that into the app's GPU-ready format in `data/anatomy`.

The microanatomy models are generated from code rather than downloaded. Organic shapes (villi, glands, follicles, fat cells, alveoli) are built as signed-distance fields and meshed with marching cubes, layered tissues as high-resolution height fields, and vessels, nerves and muscle as tubes swept around a curved centreline with a non-circular, cell-textured wall. Every model ends with one shared warp of all its layers so nothing looks milled. The geometry lives in `app/micro/` (`skin.py`, `gut.py`, `walls.py`, `vessels.py`, `bundles.py`, `bone.py`, `organs2.py`, `organs3.py`), on the toolkit in `sdf.py`, `cells.py`, `kit.py` and `organic.py`. `tools/build_micro.py` builds every model in parallel into `data/micro_cache` (about 2.5 minutes); a model whose source changed is rebuilt automatically the next time it is opened.

`tools/render_micro.py <model_id>` renders any model to a PNG offscreen with the app's own shaders, and `tools/contact_sheet.py` does all of them at once - useful when changing the geometry.

`tools/fetch_radiology.py` downloads the radiographs, CT and MR images into `data/radiology` and records each one's author and licence; `docs/radiology_cases.md` explains how a case is written, and `docs/microanatomy_models.md` how the microanatomy geometry is put together.

The app itself only needs `data/anatomy` (about 300 MB). You can delete these to save space; `build_all.bat` will download them again if needed:

| Folder | Size |
|---|---|
| `tools/blender-3.6.23-windows-x64` | 1.2 GB |
| `data/raw` | 380 MB |
| `data/extracted` | 290 MB |
| `data/micro_cache` | 430 MB (rebuild with `tools/build_micro.py`, about 2.5 min) |

## Credits and license

- Models: **BodyParts3D**, © The Database Center for Life Science, CC BY-SA 2.1 Japan.
- Atlas: **Z-Anatomy**, CC BY-SA 4.0 (Gauthier Kervyn et al.), with the derived works credited in its readme.
- Descriptions: **Wikipedia**, CC BY-SA 3.0.
- Histology images: **Wikimedia Commons** contributors. Each image's author, license and source page appear in the histology viewer. `tools/fetch_histology.py` rebuilds the collection (its stages are cached in `data/histology/cache`).
- Radiographs, CT and MR images: **Wikimedia Commons** contributors – most of them CC0 by Mikael Häggström, M.D., with two public-domain films and two CC BY-SA images. Each case shows its author, licence and source page. `tools/fetch_radiology.py` rebuilds the collection from `data/radiology/cache/wanted.json`.
- Clinical correlations and microanatomy models were written for this app.

You can use this freely for personal study. If you share the dataset or anything derived from it, credit the sources above and share it under the same CC BY-SA license.
