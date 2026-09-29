# The model viewer

Every 3D model other than the atlas itself opens in the model viewer, each in its own tab beside **3D Anatomy**:

- the three **in-house models** made in Blender at full resolution (`models/`): *Whole heart*, *Kidney and nephron*
  and *Cardiac muscle*;
- the 37 **procedural microanatomy models** the app builds from code (`app/micro`, see `docs/microanatomy_models.md`);
- the 21 **downloaded models**, Creative Commons models fetched once from Sketchfab (`data/sketchfab_models`);
- any other `.glb` / `.gltf` file, through **File → Open 3D model file** (Ctrl+O) or by dropping it on the window.

They open from **Study → 3D models**, **Details → 3D models** (the models that show the selected structure: those
that show the structure itself first, then those of its nearest group and so on, and within each the in-house models
before the procedural and downloaded ones, so selecting any part of the heart offers the whole heart first), search, the top folder of the Histology tab, the **Related** menu of another model, and lesson steps
and practice items (`micro`, `micro_focus`, `find_micro`).

The viewer replaced three older pieces: the app's own microanatomy view, the standalone viewer the Blender models were
delivered with (`viewer/`), and the embedded Sketchfab player, which streamed models from sketchfab.com. The app has
no web view and needs no internet connection.

## Controls

The model viewer uses the atlas's controls and reads them from the same settings, so a change in **Settings → Mouse &
Camera** or **Settings → Keyboard** applies to both.

| | |
|---|---|
| Mouse and trackpad | As in the atlas: the orbit and pan buttons, sensitivities, inversion, orbit around the cursor, zoom to the cursor, the trackpad gestures (swipe, pinch, twist, two-finger double tap) |
| Click, Ctrl+click, double-click | Select, add to the selection, and the double-click action from Settings (focus, isolate or x-ray focus) |
| Right-click | The part's menu: frame, x-ray others, isolate, hide, hide or select its whole group, show in the atlas, copy name |
| 1 / 3 / 7, Ctrl+1 / 3 / 7 | Anterior, right, superior views and their opposites. In-house models are in anatomical position (+Z anterior, +X the body's left), so these views mean what they say; the orientation gizmo shows A/P/L/R/S/I |
| F, Home | Frame the selection (or the visible model), go to the model's start view |
| Arrows / WASD, = / -, R | Turn, zoom, auto-rotate |
| H, I, X, Shift+H, Ctrl+Z, Esc | Hide, isolate, x-ray everything but the selection, show all, undo, clear (measurement, then x-ray, then selection) |
| L | Labels on or off |
| M | Measure (in µm, mm or cm from the model's scale; a downloaded model whose real size is not known gives lengths as a percentage of its width) |
| Ctrl+Alt+1 / 2 / 3 | Sagittal, coronal and transverse sections |
| F12, Ctrl+Shift+S | Screenshot, labelled figure |
| **PgDown / PgUp** | Next / previous stored view of the model (its view buttons or the **Views** menu) |
| **T** | Assembled / teased (the cardiac muscle opens its hero intercalated disc in place) |
| **P** | Perspective / flat (orthographic) projection |
| **Space** | Play / pause the model's animation (the procedural heart's heartbeat, the pancreas's secretion cycle) |

The keys in bold exist only for models and are rebindable under **3D models** in Settings → Keyboard. The atlas's
dissection keys (`[`, `]`, `Ctrl+[`) and **B** (both sides) have no meaning in a model and do nothing in a model tab.
Where the standalone viewer the Blender models came with used other keys, the atlas's win: its **Shift+H** and
**Shift+I** (hide or isolate a whole structure) are the right-click menu's *Hide all …* and *Select all …* (then **I**),
**Shift+H** and **Alt+H** show everything as in the atlas, and its number keys for views are **PgDown / PgUp**.

## Labels

Labels work the way they do in the atlas. On each settled frame the viewer reads back the id buffer and, for every
part to be named (the selection, or with **Labels** on every labelled part in view), puts its dot at the part's
*pole of inaccessibility*: the visible pixel deepest inside the part's visible region, so the dot sits where the part
is most clearly seen. The cards are laid out radially around the model with leader lines, trying several positions
each to avoid collisions; a group whose parts are too crowded to name one by one (the nephron's tubule segments,
the kidney's cortical arches) is named once. Labels whose anchor becomes hidden behind something as the model turns
are drawn dimmed. When a section is on, the cut face names itself: every part the plane passes through is listed in two
columns along the sides of the view, with a leader to its cut surface. Hovering shows the part's name. A scale bar
and, for models in anatomical position, an orientation gizmo sit in the corners.

## Where the code lives

| File | Contents |
|---|---|
| `app/viewer/renderer.py`, `shaders.py`, `environment.py` | The renderer: shadow maps, a pre-pass of normals and part ids, cut faces (below), SSAO with one bounce of indirect light, an 8x MSAA forward pass (GGX with a studio environment, wrapped diffuse for tissue, procedural striations and nucleus mottle), weighted-blended transparency for see-through and x-rayed parts, and a composite with the selection and hover outlines |
| `app/viewer/camera.py` | The orbit camera, with the stored views of a model and the scale-aware zoom between them |
| `app/viewer/gltf_loader.py`, `model.py` | glTF reading, and the viewer's model: parts, items (what is selected and labelled), groups, states, cameras |
| `app/viewer/procedural.py` | A procedural microanatomy model as a viewer model (its colours, tissue shading, cut-away, layers and animation) |
| `app/viewer/imported.py` | A downloaded model as a viewer model, with the hand-written part names of `data/content/sketchfab_parts` |
| `app/viewer/catalog.py` | The catalogue of every model the app can open, and the metadata of the in-house models |
| `app/viewer/dataset.py` | The small adapter that lets the atlas's `SceneState` (hide, isolate, x-ray, undo, selection) run a model |
| `app/viewer/viewport.py` | The viewport widget: the atlas's mouse and trackpad handling, picking, labels, sections, measuring |
| `app/ui/model_view.py` | The tab: parts list, view buttons, section bar, display menu, details |

### Cut faces

Cut faces lie on the cutting plane, so whatever a part encloses is hidden behind its own section, as on a slide. For
each cut part the renderer finds, per pixel, whether the plane passes through the part (the first surface behind the
plane is one of the part's back faces), gathers the caps of all parts in an off-screen buffer where the innermost part
wins, and lays them into the frame at their true depth, so they are picked, outlined and labelled like any other
surface. Procedural models shade them like a stained section; the others in the part's colour.

## In-house GLB models

A model is a `.glb` and a `.viewer.json` sidecar with the same name, in `models/<name>/`, plus a metadata file in
`data/content/models/<id>.json`. `tools/blender/export_for_viewer.py` exports both from a frozen `.blend` (headless
Blender; the original file is never opened or saved) into `models/<name>/`.

The sidecar carries what glTF cannot: `um_per_bu` (micrometres per unit, for the scale bar and measuring), `states`
(offsets per node for the teased state), `materials` (the procedural recipes: stripe period and bands, nucleus
mottle, facing-weighted alpha), `structures` (the groups, `S01`…), `clip` (an animation clip's frame range), the
light rig and the cameras. A camera record may carry `note` (shown on its button), `hidden` (the node names the view
hides; an empty list shows everything), and `state`. Top-level `start_view` names the view the model opens in (else
`V1`, else a framed home view) and `"view_transition": "zoom"` moves between views along a scale-aware path, so that
the kidney zooms from the whole organ to a podocyte without losing its place. The exporter's turntable views
(`V0`–`V6`), composed for a wide render, keep their direction but are framed to the viewport.

The metadata file:

```json
{
  "id": "whole_heart", "file": "models/heart/heart.glb", "order": 1, "name": "Whole heart",
  "summary": "…", "scale_note": "…", "oriented": true,
  "targets": {"structures": ["Left ventricle", "…"], "groups": ["Heart"]},
  "histology": ["cardiac_muscle", "heart_valve"], "related": ["heart", "cardiac_muscle"], "clinical": [["title", "text"]],
  "groups": {"S01": {"name": "Left ventricle", "description": "…", "atlas": ["Left ventricle"]}},
  "parts": {"<node name>": {"name": "…", "description": "…", "atlas": ["…"], "label": true}},
  "aliases": {"Tricuspid valve": ["group:S15"],
              "Papillary muscles (left ventricle)": ["mitral_anterolateral_papillary_muscle", "…"]}
}
```

`targets`, together with every atlas structure a group or part links to, decides which atlas selections offer the
model under Details → 3D models; `order` places it among the in-house models there (the whole heart before the
cardiac muscle block). `groups` and `parts` give every
group and part a readable name, a description and links back to the atlas (**Show in the atlas**); parts named
`<stem>__017` without an entry are called after their group ("Cardiomyocyte 17"). `aliases` map the names lessons and
practice items use onto node names or whole groups. A lesson step names parts in `micro_focus` (and practice items in
`find_micro` answers) by a part's name, its node name, a group's name or an alias; `tools/check_lessons.py` resolves
every one of them against the models.

## Which heart where

The atlas keeps the Z-Anatomy heart: it is part of the body, and anything about the heart's position and relations
(the mediastinum, the chest wall, surface markings, the ECG leads, the fetal circulation with its liver and umbilical
vessels, referred pain) is taught on it. Wherever the heart is studied on its own - its chambers, walls, valves,
coronary vessels, the lab-course practice items - lessons open the *Whole heart* model instead. The procedural *Heart:
chambers, valves & conduction* model stays for what only it shows: the conduction system (SA and AV nodes, bundle
branches, Purkinje network), the fossa ovalis and crista terminalis, and the animated heartbeat.

## Tools

| Tool | |
|---|---|
| `tools/render_model.py <id or file>` | Render a model offscreen with the viewer's renderer: `--view`, `--state`, `--section axis:pos[:flip]`, `--focus`, `--explode`, `--time`, `--frames N` for an animation GIF (`tools/render_micro.py` keeps the old command line) |
| `tools/check_viewer.py [id ...]` | Open models in the app and drive them through its actions: drawing, picking, labels, hide / isolate / show all / undo, x-ray, a section, every stored view's hidden list, the teased state (needs OpenGL 4.1; `xvfb-run -a` on a server) |
| `tools/check_lessons.py` | Every lesson and practice item, including every part name they give a model |
| `tools/sketchfab_parts.py`, `tools/check_sketchfab.py` | The downloaded models' part names and catalogue |
| `tools/blender/export_for_viewer.py` | Export a Blender model and its sidecar |
