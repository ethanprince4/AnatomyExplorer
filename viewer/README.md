# Microanatomy Model Viewer

A small, fully offline desktop viewer for the microanatomy GLB models, at full resolution. It uses the same stack as
Anatomy Explorer (Python 3.11, PySide6, moderngl, numpy) and the app's own `.venv`. Nothing is installed and nothing
is downloaded: there is no web view and no network code.

## Open a model

1. Double-click **`viewer/Model Viewer.bat`** (or drop a `.glb` onto it). From a terminal:
   `.venv\Scripts\python.exe -m viewer [model.glb]` from the repository root.
2. **File > Open…** (Ctrl+O) and pick a `.glb` or `.gltf`. **Open Recent** lists the last ten files, and you can
   drag a file onto the window.

The Phase 7 rebuild, exported for the viewer, is `viewer/models/rebuild.glb` (its look, states and cameras come from
the sidecar `viewer/models/rebuild.viewer.json` next to it). Plain GLBs open too: without a sidecar the viewer uses
the glTF materials, the baked `COLOR_0` stripe, the reveal tags in the node extras and a fitted camera.

## Controls

| Mouse | |
|---|---|
| Left drag | orbit |
| Right or middle drag (or Shift + left) | pan |
| Wheel | zoom toward the point under the cursor |
| Click | identify a part (name, structure, label, size); empty space clears |
| Double-click | focus on the part |

| Key | |
|---|---|
| F | fit the visible model |
| 0-6, 7 | shared camera views V0-V6, anchor view A1 (also the buttons above the viewport) |
| P (or keypad 5) | perspective / orthographic (V2 and V3 are orthographic) |
| Space, L | play / pause the Contraction clip, loop |
| T | assembled / teased (the hero disc opened in place) |
| H, Shift+H | hide the selected part, hide its whole structure |
| I, Shift+I | isolate the selected part, isolate its whole structure |
| Alt+H | show all |
| C, N, O, D, S | covering, annotation, ambient occlusion, shadows, stripes |
| Esc | clear the selection |
| F12, Shift+F12 | screenshot at window size, at 2x |

The animation bar scrubs the clip within its own range (frames 40-88 at 24 fps for the rebuild) at 0.25x-2x. The
**Structures** panel lists every structure (S01…) and its parts: tick boxes for visibility (a structure with only
some parts hidden shows a partly filled box), **Isolate**, **Hide** and **Show all**; double-click a part to fly to
it. The panel's Isolate and Hide act on the highlighted row, and clicking a part in the viewport highlights that one
part, so after a click they act on the part alone (one aortic cusp, one wall panel); highlight a structure row to act
on the whole structure. **View > Lighting** switches between the harness's uniform
ambient ("Match the Cycles stills") and two studio environments; **View > Exposure** and the tone-mapping toggle
(Khronos PBR Neutral, as in the Blender renders) are there too.

## Named stage views (opt-in, added for the kidney + nephron model, phase 11)

A sidecar can step the user through scales with a list of named views. Three optional keys do it; a file without
them behaves exactly as before.

- `"view_transition": "zoom"` (top level): choosing a view moves the camera along a scale-aware path instead of the
  damped glide: the distance changes in log space and the target moves in step with it, so the start's target stays
  in frame while zooming out and the goal's target while zooming in (far-apart targets: out, across, in). Any mouse
  input takes over mid-move.
- `"hidden": [node names]` (in a camera record): choosing that view shows every part except those listed (an empty
  list shows everything); the Structures panel follows.
- `"start_view": "<name>"` (top level): the view the file opens in (else V1, else a fitted view).

Views with names longer than three characters get buttons sized to their names; in a file with no V0-V6 or A1-A3
views, the number keys 1-9 and 0 step through its views in order. Test: `viewer/tests/views.py` (headless).

## Export a model for the viewer

The export runs headless Blender on a **temporary copy** of a frozen `.blend` (the original is never opened or
saved; its sha256 is checked before and after):

```
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 ^
  --python viewer/tools/export_for_viewer.py -- --blend <route>/out/model.blend [--name rebuild]
```

It writes `viewer/models/<name>.glb` (git-ignored) with every mesh at full resolution, the `Contraction` morph
targets and clip (`export_apply=False`, `ACTIVE_ACTIONS`), `COLOR_0`, the fibre coordinate as `_FIBER_U`, node
extras and the materials; and `viewer/models/<name>.viewer.json` with what glTF cannot carry: the clip's frame
range, each state's offsets (the teased reveal is a Blender driver, not an action), the material recipes (stripe
period, I-band threshold and width, band colours, contraction shortening, nucleus mottle, facing-weighted alpha of
the covering), and the harness camera set and light rig. The manifest, `views.json`, `config.json` and
`contract.json` are found above the route automatically (or pass `--manifest`, `--views`, `--stage-config`,
`--contract`).

Offscreen render (no window), for comparisons and tests:
`python -m viewer --render V1 --out v1.png [--size 1920x1080] [--state teased] [--time 2.4] viewer/models/rebuild.glb`.
Smoke test: `.venv\Scripts\python.exe viewer/tests/smoke.py`. Hide / isolate test (headless, counts only):
`.venv\Scripts\python.exe viewer/tests/hide.py [model.glb ...]`.

## How it draws

`gltf_loader.py` reads GLB/glTF with numpy (strided, normalised and sparse accessors, morph targets, clips, KHR
material extensions, extras, custom `_` attributes). `model.py` merges every primitive into one vertex buffer
(position, normal, morph deltas, fibre coordinate, colour, UV) and resolves each part's look from the sidecar over
the glTF material. `renderer.py` draws a frame as: shadow maps for the harness key, fill and rim lights (camera
relative, like the Blender rig) -> pre-pass (normals, depth, part ids) -> multi-scale SSAO with a screen-space
one-bounce GI -> 8x MSAA forward pass (GGX, code-generated studio IBL with SH9 irradiance and a prefiltered specular
array, a wrapped subsurface-style diffuse for tissue, procedural striations whose I bands narrow while A bands keep
their width as the contraction weight rises, nucleus mottle) -> weighted blended order-independent transparency
for the covering -> composite (selection outline, Khronos PBR Neutral, sRGB, dither). Morph targets are blended
on the GPU from the clip's weight curve.

## Bringing it into Anatomy Explorer later

The renderer does not depend on the window. To adopt it:

1. Copy `viewer/` into `app/` (or import it as a package) - no new dependencies.
2. In a `QOpenGLWidget`, create `Renderer(moderngl.create_context())` in `initializeGL`, call
   `renderer.set_model(Model(path))`, and in `paintGL` call `model.evaluate(t, state, amount)` then
   `renderer.render(ctx.detect_framebuffer(self.defaultFramebufferObject()), size, camera, settings)`.
   `viewport.py` is a working example (orbit camera, picking, screenshots, clip playback) and can be embedded as is.
3. `Renderer.pick(x, y)` returns the part id and world point under the cursor, so the app's existing label and quiz
   logic can hang off `Part.structure_id` / `Part.label`.
4. Export each micro-model once with `export_for_viewer.py` and ship the `.glb` + `.viewer.json` pairs as data.
