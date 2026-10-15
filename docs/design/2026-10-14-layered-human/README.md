# Layered Human: design directions (14 October 2026)

Three design directions for the renamed app (Anatomy Explorer becomes Layered Human) and its website, layeredhuman.com.
Each direction has its own app design, its own website and 6 to 8 colour schemes. All three keep the current idea: a quiet
stage and simple colours, so the 3D body is always the brightest thing on screen.

**Start with `index.html`.** Open it in a browser. It compares the directions side by side, lets you flip through every
screen in every colour scheme, links to the three websites, and ends with a recommendation. Everything it shows is in this
folder.

## The three directions

| | Overlay | Specimen | Plate |
|---|---|---|---|
| Idea | Film leaves over a quiet board | The body on display, as in a museum | The screen as an atlas plate |
| Signature in the app | The layer rail: the dissection slider as the app's right edge, one tab per depth band | The wall label: a light card for the selection; a pool of light behind the body | Labels in two margin columns; the selection set as the plate's key; a depth rule |
| Signature on the site | The body peels as you scroll, beside the same rail | Rooms you walk through, each specimen in its own pool of light | Labels that lead: each label on Plate 1 links to the plate that explains it |
| Type | Archivo | Literata and Fira Sans | Atkinson Hyperlegible Next and Mono |
| Schemes | 8 (5 dark, 3 light), default Graphite | 6 (all dark), default Gallery slate | 7 (5 light, 2 dark), default Bristol |

All three share the same decisions about how the app works, taken from the review of the current app
(`research/current-ux-evaluation.md`):

- one stage behind every workspace, with no flash from dark to white;
- the selection always names itself;
- depth is on screen, and one dock is the same in every 3D view;
- libraries are chosen by picture;
- lesson text is set at a readable line length;
- practice names the structure you clicked by mistake.

## What is in this folder

| Path | What it is |
|---|---|
| `index.html` | The gallery. Start here. |
| `app/<direction>/index.html` | App mockups, nine screens each, HTML and CSS at 1920 × 1080. Choose a scheme and screen in the address bar, for example `app/plate/index.html?scheme=night&screen=practice`. Screens: `atlas`, `peel`, `lesson`, `lessons`, `models`, `radiology`, `practice`, `histology`, `settings`. |
| `site/<direction>/index.html` | The three websites. Each is one working page, responsive down to phone width, with its own scheme switcher. `?scheme=` picks a scheme. |
| `renders/<direction>/` | The mockups rendered to WebP: every screen in every scheme at 1×, the atlas screen of every scheme at 2× (`@2x`), and every screen of each default scheme at 2×. |
| `renders/site/` | Website captures: first screen on desktop and phone, and the whole page. |
| `renders/current/` | Two screenshots of today's app, used in the gallery. |
| `current/` | Full-resolution screenshots of today's app (v4.0.8) that the review refers to. |
| `system/schemes.py` | The 21 colour schemes. Running it writes `schemes.json`, `schemes.css` and `schemes.js`, and checks contrast. |
| `assets/plates/` | Anatomy figures rendered by the app's own renderer, with transparent backgrounds, plus label anchors (`plates.json`, `*.anchors.json`, bundled into `plates.js`). |
| `assets/fonts/`, `assets/images/` | Bundled fonts (all SIL Open Font License) and the radiographs and micrographs. `assets/images/CREDITS.json` lists sources and licences. |
| `research/` | The review of today's app (28 findings, 10 principles) and the brand and website brief. |
| `site/BRIEF-*.md` | The written briefs the websites were built from. |
| `tools/` | Everything needed to rebuild the figures and renders (see below). |

The product record is `PRODUCT.md` at the repository root. It holds the users, positioning, constraints and principles
these directions were designed against.

## Colour schemes

Each direction's schemes are tuned to its type and surfaces, so they are not interchangeable between directions.
`system/schemes.py` checks every scheme:

| Check | Minimum required | Lowest in any scheme |
|---|---|---|
| Body text | 7:1 | 7.7:1 |
| Secondary text | 4.5:1 | 6.56:1 |
| Faintest text | 3:1 | 4.77:1 |
| Accent on its surface | 4.5:1 | 5.9:1 |

All 21 schemes pass every check.

Every scheme defines the same tokens:

- **Stage:** `stage_top`, `stage_bottom` and `spot`, used behind the 3D view.
- **Surfaces:** `surface`, `surface_2`, `surface_3` and `sunken`.
- **Lines:** `line` and `line_2`.
- **Text:** `text`, `text_2` and `text_3`.
- **Accent:** `accent`, `accent_2`, `accent_soft` and `on_accent`.
- **Selection:** `select`, the selection colour inside the 3D view.

Specimen adds `card`, `card_text` and `card_text_2` for the wall label. Overlay adds `film_alpha` for its panels.

## Moving a direction into the Qt app

The tokens map onto what the app already has:

| Scheme token | App today |
|---|---|
| `stage_top`, `stage_bottom` | Renderer settings `bg_top`, `bg_bottom` |
| `select` | Renderer setting `selection_color` |
| `surface`, `surface_2`, `surface_3`, `sunken` | `SURFACE`, `RAISED`, `HOVER`, `SUNKEN` in `app/ui/theme.py` |
| `line`, `line_2` | `BORDER`, `BORDER_STRONG` |
| `text`, `text_2`, `text_3` | `TEXT`, `TEXT_2`, `MUTED` |
| `accent`, `accent_2`, `accent_soft`, `on_accent` | `ACCENT`, `ACCENT_TEXT`, `ACCENT_SOFT`, `ON_ACCENT` |

Notes per direction:

- **Overlay** needs no blur. Its panels are semi-opaque fills (`film_alpha` over `surface`), which QSS can draw. The layer
  rail is a new widget beside the 3D view; its tab heights are the depth bands of the dissection stops.
- **Specimen** needs one change in the renderer: a soft radial pool of `spot` light behind the model, added to the
  background pass that already draws the gradient and vignette. The wall label is a light card on a dark stage, so it
  needs its own small set of text colours (`card_*`).
- **Plate** draws labels in margin columns instead of beside the model. The label placer already sorts and
  de-overlaps labels, so this is a new layout mode for it. Bristol is light, so lesson figures, film viewers and
  micrographs need checking on a light stage. Night plate and Slate night keep the same design dark.

The fonts are bundled under the SIL Open Font License, so the app can ship them.

## Rebuilding

Pages and renders need Node with Playwright and Chromium; set `PLAYWRIGHT_MODULE` (the path to Playwright's
`index.mjs`) and `CHROMIUM_PATH` if they are not found on their own. The figures need the app itself.

1. **Colour schemes:** `python system/schemes.py`.
2. **Atlas figures:** run the app headless and capture each figure on black and on white, so its transparency can be
   recovered exactly. `tools/capture/capture.sh batch1` runs one batch; the batches are defined in
   `tools/capture/make_script.py`, and `plates.py` holds the in-app helpers.
   - You need an X server (for example `Xvfb :99 -screen 0 4096x2560x24 +extension GLX`), Mesa, and a Python 3.12
     virtualenv with the app's requirements at `.venv312`.
   - Raw captures go to `$LH_RAW`.
   - The app rewrites `data/anatomy/depth.npz` and `samples.npz` when it starts. The script restores them from git
     afterwards.
3. **Model figures:** `python tools/capture/render_models.py tools/capture/jobs_models1.json` (and `jobs_models2.json`)
   uses the model viewer's renderer. Output goes to `$LH_MODELS`.
4. **Process the figures:**
   - `python tools/process_plates.py $LH_RAW <master-dir> assets/plates` mattes the atlas figures and computes label
     anchors from the renderer's picking buffer.
   - `python tools/process_models.py $LH_MODELS/mrgba assets/plates` copies the model figures in.
   - `python tools/bundle_plates.py assets/plates` writes `plates.js`.
5. **Renders:** `python tools/render_all.py` renders every mockup screen into `renders/`.
   `node tools/render_mockups.mjs <out> <direction> <scheme|all> <screen|all> [scale]` renders a subset.
6. **Website captures:** `node tools/shot_gallery.mjs <out> <direction> <scheme> full`.

## How this was made

1. **Review of today's app.** I ran the current app headless and captured every workspace, then reviewed it screen by
   screen (`research/current-ux-evaluation.md`).
2. **Brand and website brief.** A separate brief covers positioning, voice and naming (`research/brand-and-site-brief.md`).
3. **Directions.** One was assigned by the design toolkit's concept seed (Specimen); one is the toolkit's own pick (Plate);
   one is a challenger (Overlay).
4. **Mockups.** The app mockups are HTML and CSS. Every anatomy figure in them is a real render from the app, and every
   label sits on a point read from the renderer's picking buffer.
5. **Websites.** Each was built from its written brief by an agent, then reviewed and corrected here.

The app mockups are static pictures of the design. Nothing in them is clickable, and they are not Qt code.
