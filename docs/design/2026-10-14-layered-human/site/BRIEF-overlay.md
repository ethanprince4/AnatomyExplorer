# Direction A: Overlay (site brief)

Read `BRIEF-shared.md` first. Set `data-design="overlay"`; the default scheme is `graphite`. The schemes are
graphite, slate, moss, plum, smoke, clear, fog and sand.

## Thesis

The body as a stack of transparent overlays you lift one at a time, like the acetate plates in an old encyclopedia,
where turning a clear sheet took the skin off the muscles. The page refuses the category default: a split hero with a
glowing hologram body and feature cards. Here the page *is* the stack of sheets.

## Own world

- **Board:** a quiet board (the scheme's stage gradient, top to bottom, with a soft vignette) under milky film leaves.
- **Leaves:** `--surface` at `--film-alpha`, 1px `--line` edge, a 1px inner top highlight, a soft long shadow and
  12px radius. Where two leaves overlap, the overlap reads denser, the way acetate does.
- **No glass blur.** Real acetate is clear or milky, not frosted.
- **Accent:** one accent (`--accent`) for the active tab, the depth cursor and the primary button.
- **Type:** Archivo throughout.
  - Headlines use its condensed width (`font-stretch: 78%–86%`), weight 650–720, large sizes with tight tracking
    (−0.02em).
  - Body is 17px/1.6 at normal width.
  - Numbers are tabular.
- **The tab rail:** a vertical stack of tabs on the right edge, like the coloured index tabs on a reference manual's
  fore-edge. Each tab is a layer of the body, and its height is proportional to its depth band:
  - Skin surface 0–8%
  - Superficial fascia 8–16%
  - Deep fascia 16–26%
  - Superficial muscles 26–40%
  - Deep muscles 40–55%
  - Skeleton & joints 55–70%
  - Body cavities 70–85%
  - Deepest structures 85–100%

  Layers already peeled are lifted and faded; the current tab is pulled out, filled with `--accent-soft`, with its
  name in `--accent-2`; a 2px accent line marks the exact depth, with a readout ("40% · Deep muscles").

## Story

- **Understand:** one slider takes a whole real body apart from the skin inwards, and every layer is a real render
  from the app.
- **Believe:** the peel is real (six real renders), the cut labels itself, one viewer goes from kidney to podocyte,
  films sit beside the model, and the lab course is real (Labs 1–9 by topic).
- **Do:** download for Mac or Windows, with the size and the warning stated beside the button.

## First viewport (1440×900)

- **Board:** fills the screen.
- **Top-left leaf:** the mark (three overlapping rounded sheets, the front one in accent) and the wordmark
  "Layered Human" in Archivo semi-condensed. Beside it, quiet text links: Layers, Sections, Organ to cell, Films,
  Study, Download.
- **The body:** `peel_00_skin`, centre-right, about 82% of the viewport height.
- **The rail:** hugs the right edge at full height, with the cursor at 0% "Skin surface".
- **The headline leaf (left, about 560px wide, vertically centred):**
  - Headline: "Peel the body back, layer by layer." at about 72–84px.
  - Subline from the brand brief (option A).
  - Two buttons: **Download for Mac** (primary) and **Download for Windows** (secondary).
  - A meta line: "Free · about 3.4 GB · Apple silicon Mac (macOS 13 or later) or Windows · What to expect when
    installing" (the last part is an in-page link).
- **Hint:** "Scroll to peel" with the rail's cursor sits just above the fold.

## Signature interaction: scroll-driven peel

- **Layout:** the "Layers" chapter is a sticky stage, about 600vh tall. A sticky full-height board shows the body, and
  the rail stays at the right edge.
- **Scroll:** maps to depth 0 → 0.70. The six peel plates are stacked at the same position and crossfade by depth: at
  any moment at most two are visible, one fading out over the next. The rail cursor moves to the exact depth and the
  readout updates ("26% · Superficial muscles"). Peeled tabs lift (fade, shift right by about 16px).
- **Layer text:** a film leaf on the left changes per layer, with the layer name (big, condensed) and one or two
  plain sentences of what is exposed:
  - **Skin:** "The surface, with every skin region named."
  - **Deep fascia:** "The wrappings under the skin."
  - **Superficial muscles:** "Every muscle you can feel."
  - **Deep muscles:** "The ribcage, the abdominal organs, the deep muscles of the limbs."
  - **Skeleton & joints:** "Bone and ligament."
  - **Body cavities:** "Heart, lungs and gut in their spaces."

  Close with the README fact: "Depth is measured against how thick the body is at each point, so the hand and the
  thigh come away together."
- **Rail tabs:** clicking a tab scrolls to that layer.
- **Keyboard:** the rail is a list of buttons (`aria-current` on the current layer).
- **Implementation:** use the scroll position (requestAnimationFrame) and CSS opacity/transform only. No library.
- **Reduced motion:** the chapter becomes a static grid of the six plates with their names and depths.

## Sections after the peel, in order

Each section sits on the board and uses leaves.

1. **Sections.** `section_inferior`, large, on a leaf-framed stage.
   - About eight labels sit around the edge with leader lines to real anchors: lv, rv, ra, lung_l, lung_r, vert,
     sternum, liver, lat, pec. Labels use the patient's side the anchors give.
   - Headline: "Cut anywhere. The cut names itself."
   - Copy from the brand brief §3. Add one line: "Seen from below, as on a CT."
2. **Organ to cell.** Three overlapping film cards, fanned slightly so their edges show the stack:
   `kidney_v_kidney`, `kidney_v_corpuscle`, `kidney_v_podocytes`. Each has a caption ("Kidney", "Corpuscle",
   "Podocytes"). Headline: "From the kidney to a podocyte, in one zoom." Then a strip of six model thumbnails with
   names, and a link to the models.
3. **Films beside the model.** `cxr_pa.jpg` with the numbered pins, beside `cxr_model` with matching numbered labels
   (use the `cxr_model` anchors c1…).
   - Below, a smaller pair: `cxr_effusion.jpg` with `cxr_effusion_model`, captioned "Chest: massive pleural effusion.
     The fluid is in the model."
   - Copy from brief §5, with the honesty line in small text.
   - Credits beside each film.
4. **Lessons that set up the view.** The app render `overlay_graphite_lesson` in a large framed leaf, plus three or
   four real lesson titles.
5. **Practise like the practical.** The app render `overlay_graphite_practice`, plus the lab course list (Labs 1–9
   and Practicals 1–2 with their topics). Copy from brief §7. Mention Hunt.
6. **Under the microscope.** The micrograph with numbered pins, plus brief §8 copy.
7. **Built to be looked up.** A two-column fact list on one leaf. Not big-number tiles.
8. **Free. Offline. Yours.** and **Built on open anatomy** (credits), side by side.
9. **Download.**
   - Two leaves, Mac and Windows, each with its button, requirements and the three numbered steps.
   - The "Why the warning?" note.
   - The Windows PowerShell fallback in a code block with a copy button.
10. **FAQ.** Six to eight questions from brief §5 /help, as `details`/`summary`.
11. **Footer.**

## Mobile

- The rail becomes a horizontal strip of layer tabs pinned under the header.
- The peel chapter uses the same crossfade, with the body at full width and the text leaf below it.

## Honest risk

Scroll-linked crossfades can feel gimmicky if slow. Keep each layer's scroll distance short (about 100vh) and the
transitions quick.
