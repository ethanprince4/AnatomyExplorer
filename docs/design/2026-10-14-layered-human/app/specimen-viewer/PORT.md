# Model viewer room: what to port

The opened model, `?screen=viewer`. It is the kidney with the nephron, the model the Models library shows lit.
`?view=kidney` (the default) is the model's start view, Kidney. `?view=corpuscle` is the close view.

- Clicking the kidney tile in Models opens the room, and so does its "Open model" button.
- In the room, the Kidney and Corpuscle tiles in the views strip switch between the two states.
- Scheme and panel treatment carry over (`?scheme=`, `?panel=`).

Renders are in `renders/checkpoint-2/viewer/`.

## 1. Carry into `app/specimen/index.html`

Every change is in `app/specimen-viewer/index.html`. Diff it against `app/specimen/index.html`: these are the only differences.

**CSS**

1. Add `[data-screen="viewer"] [data-screen-id="viewer"]` to the screen display rule (line 31).
2. Add the block that starts with `/* ---- model viewer: the opened model`, at the end of `<style>`. It defines:
   - `.parts` (the tree: rows `.l0`, `.l1`, `.l2`, `.cat0`, `.off`, `.open`, `.is-sel`, and the chevron `.tw`);
   - `.box.part` (the tri-state box);
   - `.vcol` (the right column);
   - `.reveal` (`.ctl`, `.track`, `.fill`, `.tick`, `.knob`, `.v`, `.v.word`, `.opt`);
   - `.vstrip` (`.grp`, `.tiles`, tile `a`, `a.empty`);
   - `.stage img.plate.close` (the top and bottom fade on a close view);
   - `.spec` (the library's hover).

   It uses only existing tokens (`--text*`, `--accent*`, `--line-2`, `--hair`, `--spot`, `--stage-bottom`, `--edge`), so it recolours with every scheme.

**Markup**

- The `<section data-screen-id="viewer">` before SETTINGS.
- It uses the existing `.pool`, `.stage`, `.head` (`data-chrome="models"`, so Models stays the current room), `.exhibit`, `.colhead`, `.views`, `.rule`, `.btn`, `.label-card` and `.dock`.
- The wall label and the dock use the shared classes, so they follow wall, plaque and frame.

**JS**, inside the main IIFE:

- **Models library:**
  - `openURL()`.
  - The `[data-collection]` tiles become `<a class="spec">`. Only the kidney has an `href`, and the inline `opacity:.55` moves into `.spec .pool`.
  - The `[data-open]` click handler, plus `data-open="kidney"` on the "Open model" button.
- **The viewer block:** `VIEW_GROUPS`, `STATES`, and the `[data-screen-id="viewer"]` builder.

**Anchors**

- One small `<script>` between `plates.js` and `mock.js` adds anchors for `kidney_v_kidney` and `kidney_v_corpuscle` to `LH_PLATES.anchors`.
- They were placed by eye on the renders. When `tools/process_plates.py` can read these plates' picking buffers, write real `*.anchors.json` and delete this script.

**Assets:** none new. The room uses `assets/plates/kidney_v_*.webp`.

**`tools/render_mockups.mjs`**

- Add `'viewer'` to `SCREENS`. Until then, render it with `node tools/render_mockups.mjs <out> specimen slate viewer 2`.
- The close view needs `MOCKUP_QUERY="view=corpuscle"`.

## 2. What the Qt app needs

The room is today's model viewer (`app/ui/model_view.py`, `app/ui/studio_scene.py`) with its parts laid out on the wall. Most of it already exists.

| In the mockup | In the app today | Work |
|---|---|---|
| Title and caption on the wall | `StudioScene.subject`, `breadcrumb` (`studio_scene.py` l.18–19) | Paint in the one wall-text overlay (BUILD-NOTES, "Wall text over the 3D view"). The caption is "View n of N · <view name> · <scale>". The scale words come from the camera `note` (`recipe.json` `viewer_cameras`). |
| Parts tree, tri-state boxes, open categories | `Outline` tree (`model_view.py` l.441–447), categories from the parts guide (l.483+), top level open (l.524), tri-state sync (l.713), filter "Filter parts or groups…" (l.432) | Restyle only: no panel, 14 px rows at 31 px, 18 px indent, Literata nowhere. Selection: weight 600 plus the brass dot (paint it in the item delegate). |
| Reveal: Tissue opacity, Separate layers, Cut-away, Reset | `_compact_reveal` (l.283–340), card "Reveal" (`studio_scene.py` l.30) | Restyle the two QSliders as the gauge's flat cousin (1 px track at text-3 60 %, 3 px brass fill, 15 px brass knob with a 4 px wall ring, ticks at quarters). Readouts: "100%" in accent-2, and the italic word *assembled* at 0 (the model's own name for that state, `model.py` l.412). Opacity is disabled when a model has no bulk tissue (l.305, l.850). |
| Section: Sagittal, Coronal, Transverse | `SECTION_NAMES` (`viewport_core.py` l.46), menu (l.832–840) | Plain text items, brass bar on the active plane. |
| Wall label for the selected part | `selectionSurface` with Isolate and Details (`studio_scene.py` l.33–44), Hide (l.457–459) | Same `label-card` treatments as the atlas. Body text comes from the parts guide `groups[...].description`; the Clinical row from its `clinical[0][0]`. |
| Stored views strip | A combo box "Choose a stored view" when a model has more than 3 views (l.787–812), PgUp/PgDn (l.796, `info_panel.py` l.489) | **New widget.** One row of 64 × 49 tiles under the stage, grouped, with the current one outlined in brass at offset 4. Click calls `set_named_view`. PgUp/PgDn already step through the views. |
| Zoom between views | `view_transition == "zoom"` uses the scale-aware path (`viewport_core.py` l.513, `camera.py` l.322) | None. The move to an ORTHO view (Nephron (15x schematic), the three Source section views) cuts without a blend (`camera.py` l.302–305). |

**Data the app does not have yet**

1. **A group for each stored view.**
   - The strip groups the kidney's 13 views by the spaces the model holds: Overview, Whole kidney, Nephron 15×, Section diagram.
   - Today that is only in the camera notes.
   - Add a `"group"` key to each `viewer_cameras` record in the teaching recipes. With no group, the strip shows one unnamed row.
2. **A thumbnail for every stored view.**
   - Render them with the app's own renderer at the camera record (`tools/capture/render_models.py` does this), with transparent backgrounds, at 128 × 98 px for 2×.
   - Cache them beside the model.
   - The kidney needs **13**. Six exist today: Kidney, Lobe, Nephron (15x schematic), Corpuscle, Juxtaglomerular apparatus and Podocytes.
   - All released models with a teaching recipe need **333** (35 models). The heart alone has 23, more than one strip holds at 64 px, so a strip longer than about 14 tiles needs scroll chevrons or a second row.
   - The mockup shows the 7 missing kidney views as empty hairline tiles.
3. **Label anchors for close views.** They come from the picking buffer, as for the atlas plates.

**Renders the full room needs:** one stage render per stored view (13 for the kidney), plus 13 thumbnails. The mockup uses two real stage renders (Kidney, Corpuscle) and six real thumbnails.
