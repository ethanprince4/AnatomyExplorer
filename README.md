# Anatomy Explorer

A desktop 3D anatomy viewer for Windows and Mac. It has its own OpenGL renderer and a Qt interface, and it runs entirely offline on your machine.

## Download

[![Download for Windows](https://img.shields.io/badge/Download-Windows%20installer-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Download-Windows-Installer.ps1)
&nbsp;
[![Download for Mac](https://img.shields.io/badge/Download-Mac%20%28Apple%20silicon%29-333333?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Install-Anatomy-Explorer-Mac.zip)

**[Windows](https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Download-Windows-Installer.ps1)** · **[Mac, M1 or newer, macOS 13 or later](https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Install-Anatomy-Explorer-Mac.zip)**. The full app is over 3 GB, more than GitHub allows in one file, so these small downloads fetch it in parts, check them and install it for you.

- **Windows:** right-click `Download-Windows-Installer.ps1` and choose **Run with PowerShell**. It downloads the installer parts next to itself, joins them and starts the installer; click through it. It adds Anatomy Explorer to the Start menu (and the desktop if you tick the box). If a blue "Windows protected your PC" box appears, click **More info**, then **Run anyway**.
- **Mac:** open the downloaded `Install-Anatomy-Explorer-Mac.zip` (Safari unzips it for you) and double-click **Install Anatomy Explorer**. It downloads the app (about 3.4 GB), checks every part, copies **Anatomy Explorer** into **Applications** and opens it; it needs about 8 GB of free space while it works, and if it stops you can simply run it again. The first time, macOS may say the installer "cannot be opened": go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway** (on macOS 14 and earlier, right-clicking it and choosing **Open** also works). Only the installer needs this step; the app is downloaded by the installer itself.
- These warnings appear because the app isn't signed with a paid developer certificate; after the first launch it opens normally. Your progress, quiz history and notes are kept in your user folder (`%LOCALAPPDATA%\AnatomyExplorer` on Windows, `~/Library/Application Support/AnatomyExplorer` on Mac), so updating or reinstalling never loses them. If the app ever misbehaves, its error log is in the `logs` folder there.

## What's in it

**Updates (Windows and Apple silicon Mac):** install this updater-enabled version once if you have an older copy.
After that, changed parts download automatically in the background and open on your next launch. Your study
session keeps running and your progress/settings are kept. **Updates → Check for updates** (installed app) opens a dialog with manual checks, the automatic-download option and rollback to the previous version. Some releases change large models or runtimes and still need a substantial
download. [How updates work and their limits](docs/updates.md).

- 303 lessons in 1,614 steps, filed by body system, region and level, with 1,525 recall questions built into them. 109 of them make up a lab course: bite-sized mini lessons for Labs 1–9 and two lab-practical reviews, with 1,824 graded practice items and practice exams.
- 41 interactive 3D models, all opening in one model viewer with the atlas's controls and labels: a true-scale **whole heart**, a **kidney with its nephron** in place (one zoom from the whole organ down to a podocyte) and a block of **cardiac muscle** at cell scale, plus 38 microanatomy and organ models from skin, gut wall and osteons to the eye, ear, neuron and the reproductive organs. 104 labelled radiology cases, five of them chest cases that show the disease in the model itself; spaced-repetition revision, a dissection slider that peels the body apart, and self-labelling cross-sections.
- 3,922 structures and 11.6 M triangles: bones, joints and ligaments, muscles, tendons, bursae, fascia, arteries, veins, heart, lymphatics, brain, cranial and spinal nerves, sense organs, viscera, skin regions.
- 1,109 bony and organ landmarks, 3,815 described structures, Latin names and Terminologia Anatomica 2 IDs.
- Muscle origins and insertions mapped onto bones. Innervation for 468 muscles, and the action of 466.

## Running from source

The installers above are all most people need. To run the app from a clone instead, you need Python 3.10 or newer and [Git LFS](https://git-lfs.com): the files over GitHub's 100 MB limit are stored with LFS (listed in `.gitattributes`), so install it before cloning, or run `git lfs pull` afterwards, or those files arrive as small pointer files. The repository carries the built dataset, the histology and radiology images and the 3D model library (`data/local_model_library`), so nothing has to be rebuilt.

- **Windows:** run `setup.bat` once. It creates `.venv`, installs the packages, builds the microanatomy models and adds a desktop shortcut. After that, start the app from the shortcut or `Anatomy Explorer.bat`; `run_debug.bat` runs it with a console so errors are visible.
- **macOS and Linux:**
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python -m app
  ```

Errors are written to `logs/errors.log`. The 3D models are read from `data/local_model_library` as they are, so nothing is built when one is opened. Your study progress, notes and quiz history are kept in `data/user/`, which is never committed.

## Using it

On a Mac, Ctrl in the shortcuts below means the Command key (⌘), except where macOS reserves the key: Quiz is ⌥⌘Q (⌘Q quits), Histology ⌃⌘5 (⌘H hides the app), fullscreen ⌃⌘F, the workspaces ⌃⌘1–5 (⌘⇧3–5 take screenshots), ⌘-click adds to a selection, and the Delete key hides it. The app's help and Settings → Keyboard show the Mac keys.

| Action | How |
|---|---|
| Rotate / pan / zoom | Left-drag / right- or middle-drag (or Shift+drag) / mouse wheel (zooms toward the cursor) |
| Select | Click. Ctrl+click adds to the selection. Double-click selects and focuses |
| Header and menus | The top bar has **Explore**, **Lessons**, **3D Models**, **Radiology** and **Histology** workspaces, a search box, **Saved views** and a settings (gear) button. The gear menu holds Settings, the open workspaces, **Find a command…** and every classic menu: **File**, **Selection** (back / forward, frame, hide, isolate, x-ray, show all, undo), **View** (camera views, colours, dissection, cross-sections, 3D model views, fullscreen and borderless), **Tools** (measure, saved views, screenshot, export a figure), **Study** (lessons, quiz, radiology, histology, my progress, notes, 3D models), **Help** and **Updates** (installed app). Every command keeps its keyboard shortcut, shown beside it. Along the bottom of the atlas: **Measure**, **Show all**, **Reset** and **More tools** |
| Search | Ctrl+F, then type a structure, group ("brachial plexus"), landmark ("clinoid") or Latin term. Enter jumps to the top result |
| Focus a search result | The result is highlighted and framed, and everything else goes x-ray. Hidden parts of the selection show through with a hatched overlay |
| Filter | The **Explore** panel has three groups. **Browse** chooses what is shown, with a selector for **Systems** (systems, subsystems, opacity, and a **Quick views** preset drop-down: Default, Skeleton, Muscles, Attachments, Vessels, Nerves, Organs, Surface), **Regions** (body regions), **Tree** (the full anatomical hierarchy with checkboxes) and **Models** (every installed 3D model). **Study** holds **Lab course**, **Lecture exams**, **Lessons**, **Radiology** and **Histology**. **View** has colours, x-ray, dissection and cross-sections |
| Hide / isolate / x-ray | H / I / X (also the **Selection** menu and the right-click menu). Shift+H shows everything. Ctrl+Z undoes. Esc clears |
| Views | 1 anterior, 3 right, 7 superior. Ctrl+1/3/7 give the opposite views. F frames the selection. Home resets the camera. All of them are in the **View** menu, under Camera |
| Cross-sections | **View → Cross-sections** (Ctrl+Alt+1/2/3), or the **View** tab (sagittal / coronal / transverse, each with a slider and a flip). The cut face labels itself: every structure the plane passes through is named around the edge of the view, click a label to select it, and the **View** tab lists them all |
| Dissect | **View → Dissection**, the slider on the **View** tab, or **]** / **[** to step. The body comes apart from the skin inwards. Depth is measured as a fraction of how thick the body is at each point, so the hand and the thigh are uncovered together. "Show only this layer" gives a slab instead of a peel |
| Measure | **M** (or **Tools → Measure**), then click two points. Shift+click adds another leg, which also reports the angle. Esc clears |
| Colors | Realistic; Distinct segments (muscles by function, bone and lung segments, lobes); By body system. Right-click → Set color… for one structure |
| Screenshot | F12. **Ctrl+Shift+S** exports a captioned figure instead: the view, its title, and a caption listing what is in it (also copied to the clipboard) |
| Window | **F11** is true fullscreen — the window takes the whole screen and sits above the shell, so nothing else is reachable until you leave it. **Shift+F11** is borderless instead: the title bar goes, the window fills the screen's work area, and the taskbar, alt-tab and every other window carry on working normally. In borderless mode, drag the empty part of the top bar to move the window. Both are in the **View** menu with a tick beside the one you are in, and borderless is remembered between runs. **Ctrl+B** hides the side panels for a few hundred more pixels. Explore and Details are cards on the canvas rather than windows; **View → Arrange floating panels** lays them out again |

**Trackpad.** A laptop trackpad (MacBook, or a Windows precision touchpad) works without a mouse: two-finger swipe rotates the model, pinch zooms toward the cursor, Shift + two-finger swipe pans, click selects, two-finger click opens the context menu and click-drag rotates as with a mouse. On a Mac, twisting two fingers turns the model and a two-finger double tap frames the selection (again to go home). The mouse wheel still zooms: the atlas tells the two apart by the events they send, and **Settings → Mouse & Camera → Trackpad** can force Mouse or Trackpad if a smooth-scrolling wheel is misread, make swipe pan instead of rotate, and set swipe and pinch sensitivity and direction. The same mapping drives every 3D model in the model viewer.

The **Details** panel lists everything known about the selection in collapsible sections: key facts (Latin name, TA2 ID, hierarchy, and the action and blood supply where known), clinical correlations, histology, 3D models, innervation, muscles a nerve supplies, attachment areas (shown on the bone with origins in red and insertions in blue), neighbouring structures – each marked as lying superficial or deep to the selection – landmarks, your note and the full description. All links in it can be clicked. Alt+Left / Alt+Right (or the mouse back/forward buttons) move through what you've viewed.

## Study features

| Feature | How |
|---|---|
| Lab course | **Explore → Study → Lab course** opens **My lab course**: the course organised by lab topic, from **Lab 1** (nerve physiology, reflexes and general senses) to **Lab 9** (reproductive systems and early development), then **Lab Practical 1** (Labs 1–5) and **Lab Practical 2** (Labs 6–9). 109 mini lessons, each a few short steps on one topic; every lab heading shows how many you have finished (`LAB 3  4/10 ✓`) and every card your best practice score. Opening one shows its cover — objectives, progress, scores — and two ways in. **Learn** walks through the steps with the 3D view set up for each one. **Practice** runs a short graded session in a panel beside the model, built from 1,824 practice items of six kinds: find a structure in the 3D atlas (right-click to peel away whatever is in the way), name a highlighted structure, find a part inside a 3D microanatomy model, multiple choice, recall (think of the answer, then say honestly whether you knew it) and put-in-order. Each answer is marked with a short explanation, and the summary lists what you missed with **Retry missed**. Each lab practical has review lessons plus a **Practice exam** drawn from every item of its labs, with a **Length** selector (20, 40, 60 questions or everything). Your last and best score for every lesson is kept (`data/user/lesson_progress.json`), and every answer feeds the same spaced-repetition schedule as the quiz, so what you miss comes back in **Review what is due**. Sessions favour items that are due, new to you or often missed. See `docs/lessons.md` |
| Lessons | Ctrl+L, or **Study → Lessons**: 303 lessons in 1,614 steps, the lab course included. The library is segmented by **lab course** (first), by **lecture exam**, by **body system** (skeletal, muscular, cardiovascular, respiratory, digestive, urinary, reproductive, endocrine, lymphatic, nervous, special senses, skin and fascia), by **region** (head and neck, back, thorax, abdomen, pelvis, upper limb, lower limb, whole body) or by **level** (foundation, core, advanced) — one click switches between them. Every lesson opens with what you should be able to do by the end and closes with what to remember and where to go next; 1,525 of the steps ask you a question before you move on, with the answer hidden until you ask for it, and steps can carry a mnemonic, a common mistake or a clinical note. Each step also sets the view up for you – switching systems, dissecting to a depth, isolating, sectioning, or opening the matching micrograph or 3D microanatomy model – and "Quiz me" tests you on everything the lesson named. How far you got is kept between runs: the cards show a progress bar, finished lessons are ticked green, and a **Continue** card at the top picks up where you left off (`data/user/lesson_progress.json`). Search finds lessons too. Content lives in `data/content/lessons_*.json`; `tools/check_lessons.py` validates it. See `docs/lessons.md` |
| Radiology | Ctrl+R, or **Study → Radiology**: 104 cases put a real image (radiograph, CT, MR, ultrasound, angiogram, nuclear medicine, fluoroscopy or mammogram) beside the live model, labelled on both sides. Five chest cases show disease – a massive pleural effusion, right middle lobe pneumonia, a pneumothorax, heart failure, and the CT of the same pneumonia – and the model shows the pathology itself: fluid filling the pleural cavity with the lung floated up off it, a lung collapsed back to its hilum inside a translucent pleural space, a consolidated lobe, an enlarged heart, a shifted mediastinum. Those meshes are derived from the normal anatomy by `tools/build_findings.py` and live in their own Findings system. Choosing one sets the 3D view up to match the film – the same systems, the same way round, ghosted where the beam sees through, and cut in the same plane at the same level for the cross-sectional cases. Click a numbered label on the image, or a line in its legend, and the model selects and frames the same structure; each case also carries how to read that film. Search finds cases too. Content lives in `data/content/radiology*.json`, images and their licences in `data/radiology`; `tools/check_radiology.py` validates every coordinate and name |
| Clinical correlations | 423 entries shown in Details for the structures they concern: specific disease states, injuries and procedures unique to that part. Search finds them by name or by the signs and syndromes they mention ("Colles", "Horner"). Content lives in `data/content/clinical_*.json`; add your own entries in the same format |
| Histology | Ctrl+H, or **Study → Histology** in the Explore panel: a tree of basic tissues and organ systems, 101 tissues with 1,049 micrographs from Wikimedia Commons. Selecting a structure also lists matching tissues under Details → Histology. Clicking a thumbnail opens the viewer (zoom with the wheel, arrows for next/previous, Show in 3D) |
| 3D models | **Study → 3D models**, **Details → 3D models** for the selected structure, search, a lesson step, or **File → Open 3D model file** (Ctrl+O, or drop a `.glb` / `.gltf` on the window) for any other model. Each model opens in its own tab in the model viewer, which uses the atlas's own controls and settings: the same mouse buttons, trackpad gestures, sensitivities and inversion, orbit around and zoom to the cursor, 1/3/7 views, F, Home, arrows/WASD, R, H / I / X, Shift+H, Ctrl+Z, Esc, L for labels, M to measure, Ctrl+Alt+1/2/3 for sections and F12. A few keys only mean something in a model: **PgDown / PgUp** step through its stored views, **T** switches between assembled and teased, **P** between perspective and flat projection and **Space** plays or pauses its animation. Click a part for its name, description and a **Show in the atlas** link. Labels are placed as the atlas places them: each at the most clearly visible point of its part with a leader line, crowded groups named once, and the cut face named around the edge of the view when a section is on. **Cut-away** opens a corner, **Section** cuts along any of the three planes with a slider and a flip, **Separate parts** pulls it apart, **X-ray others** ghosts everything but the selection, and a scale bar and an orientation gizmo give size and direction. The renderer draws shadows, ambient occlusion, cut faces filled like a stained section and see-through parts in the right order. `docs/model_viewer.md` has the details |
| In-house models | Three models built in Blender for this app at full resolution (notes in `models/`; the app loads them from `data/local_model_library`). **Whole heart**: a true-scale adult heart in 119 parts – four chambers made of 15 wall panels that can be hidden one at a time to look inside, the four valves with their chordae tendineae and papillary muscles, the coronary arteries and cardiac veins, and the great vessels. The lessons and the lab-course practice use it wherever the heart is studied on its own; the atlas keeps the Z-Anatomy heart in the body, where its position and relations matter. **Kidney with the nephron**: the kidney, adrenal, vessels and ureter with a juxtamedullary nephron in place, at true scale, and eight stored views (Kidney, Lobe opened, Lobe, Nephron, Corpuscle, Juxtaglomerular apparatus, Podocytes, Loop of Henle) that zoom smoothly from one scale to the next. **Cardiac muscle**: 48 cardiomyocytes joined by intercalated discs, with their nuclei, endomysium and capillaries, and a teased state that opens one disc in place. Each part has a readable name, a description and links back to the atlas (`data/content/models/*.json`) |
| Microanatomy | Thirty-eight models in the model library (`data/local_model_library`), from **Study → 3D models**, under Details → 3D models, or from search; their geometry is built by the code in `app/micro`. Tissue blocks: thin, thick, scalp and axillary skin; jejunum, duodenum, ileum, colon, stomach, oesophagus, trachea, bladder; liver lobule; pancreatic acini and islets; muscular and elastic arteries, veins; lung acinus; osteon; skeletal muscle; peripheral nerve; cornea; retina; thyroid follicles with a parathyroid; tongue papillae and taste buds; lymph node; spleen; blood cells (the formed elements as in a stained smear). Organs, drawn whole or sectioned as in a dissection or atlas plate: the eyeball with its muscles, eyelids and lacrimal apparatus; the external, middle and inner ear with magnified insets of the cochlear duct, a crista and a macula; a kidney in coronal section; the liver, gallbladder, bile ducts and pancreas; the ileocaecal region, rectum and anal canal; a molar in its socket; the female pelvis with the ovary, uterine tube, endometrium and implantation, fertilisation to blastocyst and the breast; the male pelvis with the testis, a seminiferous tubule and a spermatozoon. Every layer, gland and cell group can be selected, hidden or x-rayed, with a corner cut-away, cross-sections, labels, tissue opacity and exploded layers. The pancreas is animated: **Play** runs the secretion cycle (zymogen granules released into the acinar lumen, juice running down the ducts, insulin leaving the islet), with a speed control and a scrubber that names each stage. Cut faces are drawn as flat sections lying on the cutting plane, so a part's contents are hidden behind its cut surface as in a real slice, and shaded like a stained section, with nuclei, fibres and cell outlines. The old nephron and cardiac muscle blocks are replaced by the in-house models above |
| Quiz | Ctrl+Q, or **Study → Quiz**. Four modes: find the named structure in 3D, **hunt** it down through the whole body, name the highlighted structure (multiple choice), or type the name. In both find-type modes **right-click peels away** whatever is in the way (Ctrl+Z puts it back) and the naming context menu is suppressed, since its first line would give the answer. Questions come from what's visible, one chosen system, a lesson, or what a cross-section cuts through, and the mode you last picked is remembered |
| Hunt mode | The deep end. Every system is switched on, the Explore and Details panels are closed and nothing on screen is named — no labels, no hover tooltip. You get one structure to find: move as usual, **right-click** to peel a structure out of the way one at a time, **left-click** the one you think it is. Three tries; a wrong click is not named, so nothing gives the game away. After the third it shows the answer in green and lists the three things you actually clicked. Ctrl+Z puts back the last thing you hid, and **Put everything back** restores the lot. Targets are drawn from the ~500 structures the lessons, radiology cases and clinical notes actually name, so you are never asked to pick out one intervertebral disc from another; tick *Hunt: anything at all* to open it up to the whole atlas, or set a Topic to hunt within one system |
| Spaced repetition | Every answer schedules that structure to come back: a day later if you missed it, then four days, then longer each time you get it right. **Review what is due** on the quiz page starts a session from the schedule, and **Study → My progress** shows accuracy, how many structures are well known, what falls due over the next fortnight, and the ones you keep missing (`data/user/quiz_stats.json`) |
| Notes | N adds a note to the selected structure. Study → All my notes lists them (`data/user/notes.json`) |
| Saved views | Ctrl+D saves the camera, visibility, selection and cross-sections. The last session is restored on launch (can be turned off in Settings) |

## Settings

Ctrl+, opens Settings:

- **Mouse & Camera:** orbit, pan and zoom sensitivity, inversion, which button orbits or pans, zoom to cursor, orbit around cursor, transition duration, auto-rotate speed, field of view.
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
| Panels, workspaces and menus | `app/ui/*.py`, `app/ui/studio_shell.py`, `app/main_window.py` |
| Search ranking and synonyms | `app/search.py` |
| Pathology meshes | `tools/build_findings.py` → `data/findings`. Each finding is a transform of existing geometry (an effusion is the lung's volume below a fluid level, a collapsed lung is the lung contracted to its hilum) and `app/findings.py` appends them to the atlas at load time. See `docs/radiology_cases.md` |
| Radiology cases | `data/content/radiology*.json` – one object per case: the `id` of a downloaded image, a `crop` if only part of the file is wanted, the teaching `text` and `reading` list, a `scene` in the same format as a lesson step, and `labels` at 0–1 coordinates of the (cropped) image. `tools/grid_overlay.py` writes a coordinate grid over an image so label positions can be read off; `tools/fetch_radiology.py` downloads new images and records their licences |
| Guided lessons | `data/content/lessons_*.json` – plain JSON, one object per lesson: `system`, `region` and `level` file it in the library, `objectives`, `takeaways`, `prereq` and `see_also` wrap the teaching round it, and each step may name `focus` and `show` structures, a `side`, a `systems` preset, a `dissect` depth, a `clip` plane, a `view`, a `micro` or `histology` id, and a `check` question with its answer. `tools/name_probe.py` checks a name before you write it, `tools/check_lessons.py` validates the whole library afterwards. Full schema in `docs/lessons.md` |
| Descriptions, innervation, action, blood supply | `data/content/descriptions_extra*.json` – maps an exact structure, group or landmark name to any of `description` (used where the atlas has none), `innervation` (replaces the list the build derived), `action` and `blood_supply`. Merged at load time by `app/extra_content.py`, so nothing needs rebuilding; `tools/check_descriptions.py` validates the names and reports coverage |
| Procedural builders | `app/micro/` – registered in `registry*.py` (37 procedural models) and built by `tools/build_micro.py`. The app's model list does not read these registrations: it shows the ids in `data/content/release_models.json`, loaded from `data/local_model_library/library.json`. See `docs/microanatomy_models.md` |
| Which models the app shows | `data/content/release_models.json` lists the model ids. Their files and metadata are in `data/local_model_library/` (`library.json`). `data/content/models/<id>.json` holds the names, summaries, part names, atlas links and aliases of the three in-house models. A `.glb` dropped into `models/` is not picked up by id; see `docs/model_viewer.md` |
| Model viewer | `app/viewer/` (renderer, shaders, camera, model loaders, the viewport with its labels) and `app/ui/model_view.py` (the tab around it) |
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

The procedural microanatomy geometry is generated from code rather than downloaded. Organic shapes (villi, glands, follicles, fat cells, alveoli) are built as signed-distance fields and meshed with marching cubes, layered tissues as high-resolution height fields, and vessels, nerves and muscle as tubes swept around a curved centreline with a non-circular, cell-textured wall. Every model ends with one shared warp of all its layers so nothing looks milled. The geometry lives in `app/micro/` (`skin.py`, `gut.py`, `walls.py`, `vessels.py`, `bundles.py`, `bone.py`, `liver.py`, `lung.py`, `glands.py`, `organs2.py`, `lymphoid.py`, `tissues.py`, `blood.py`, `heart.py`, `eyeball.py`, `ear.py`, `kidney_gross.py`, `hepatobiliary.py`, `lower_gi.py`, `tooth.py`, `female.py`, `male.py`), on the toolkit in `sdf.py`, `cells.py`, `kit.py`, `organic.py` and `cellkit.py`. Models are registered in `registry.py` and `registry_organs.py`, and any `registry_extra_*.py` file is loaded automatically. The app's model list no longer comes from these registrations (see Customizing). `tools/build_micro.py` builds every registered model in parallel into `data/micro_cache` (a few minutes).

`tools/render_model.py <model_id>` renders any model – in-house, procedural or any `.glb` – to a PNG offscreen with the model viewer's own renderer (`--view`, `--state`, `--section`, `--frames` for an animation), `tools/render_micro.py` does the same with its old options, and `tools/contact_sheet.py` renders every procedural model at once - useful when changing the geometry.

`tools/fetch_radiology.py` downloads the radiographs, CT and MR images into `data/radiology` and records each one's author and licence; `docs/radiology_cases.md` explains how a case is written, and `docs/microanatomy_models.md` how the microanatomy geometry is put together.

The app itself needs `data/anatomy` (about 300 MB) and the model library `data/local_model_library` (about 2.7 GB). A rebuild also downloads these, none of which are committed; they can be deleted afterwards and are downloaded again if needed:

| Folder | Size |
|---|---|
| `tools/blender-3.6.23-windows-x64` | 1.2 GB |
| `data/raw` | 380 MB |
| `data/extracted` | 290 MB |
| `data/micro_cache` | 270 MB (rebuild with `tools/build_micro.py`, a few minutes) |

## Licence

Anatomy Explorer's code and its original content are released under the **MIT licence** (see [`LICENSE`](LICENSE)), © 2026 Ethan Prince. That content covers the lessons, clinical correlations, radiology case texts, the hand-written descriptions (`data/content/descriptions_extra*.json`), the microanatomy models, the in-house 3D models and the icon.

Third-party material keeps its own licence, and the MIT licence does not apply to it. [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) lists all of it:

- `data/anatomy` and `data/findings` are an adaptation of Z-Anatomy and BodyParts3D, under **CC BY-SA 4.0** ([`data/anatomy/LICENSE`](data/anatomy/LICENSE)). If you share the dataset or anything derived from it, credit the sources below and share it under the same licence.
- The histology and radiology images are under the licence recorded beside each one: mostly CC BY, CC BY-SA and CC0, with some public-domain images, one GFDL image and a few other free-use terms.
- The installers bundle Qt and PySide6 (LGPL-3.0) as replaceable libraries, together with the other libraries listed in `THIRD_PARTY_LICENSES.md`.

`python tools/check_licenses.py` checks that every shipped image and model records an author, a licence and a source. In the app, **Help → About** shows the licence and the full credits.

Anatomy Explorer is a study aid, not a medical device.

## Credits

- Atlas: **Z-Anatomy**, "The libre 3D atlas of anatomy", CC BY-SA 4.0 (Gauthier Kervyn et al.). Its readme credits the works it is derived from.
- Models: **BodyParts3D**, © The Database Center for Life Science (DBCLS), CC BY-SA 2.1 Japan.
- Anatomical terms: **Terminologia Anatomica 2** (FIPAT), as distributed with Z-Anatomy.
- Descriptions: **Wikipedia**, CC BY-SA 3.0, as distributed with Z-Anatomy. Hand-written texts fill the gaps (`data/content/descriptions_extra*.json`).
- Histology images: **Wikimedia Commons** contributors. Each image's author, licence and source page appear in the histology viewer. `tools/fetch_histology.py` rebuilds the collection (its stages are cached in `data/histology/cache`).
- Radiographs, CT, MR, ultrasound and other images: **Wikimedia Commons** contributors, under CC0, public-domain, CC BY and CC BY-SA licences (recorded in `data/radiology/sources.json`). Each case shows its author, licence and source page. `tools/fetch_radiology.py` downloads the images listed in `data/radiology/cache/wanted.json`.
- Clinical correlations, the hand-written descriptions, innervation, actions and blood supply, the microanatomy models and the whole heart, kidney and cardiac muscle models were made for this app.
