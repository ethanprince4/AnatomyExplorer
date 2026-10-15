# Layered Human: design (14 and 15 October 2026)

The design for the renamed app (Anatomy Explorer becomes Layered Human) and its website, layeredhuman.com. Three
directions were explored; the owner chose **Specimen**, the museum direction: the 3D body stands on a dark gallery wall
under a spotlight, Literata for display and reading, Fira Sans for the interface. Gallery slate is the default and all six
walls are dark. Overlay and Plate are kept as an archive.

**Start with `index.html`.** Open it in a browser. It leads with Specimen (every screen on every wall, the mark, the
website), links the checkpoint pages, and keeps Overlay and Plate further down. Everything it shows is in this folder.

## Decisions

The owner decides at checkpoints, picking from three options per question. Each checkpoint has its own page.

| Checkpoint | Page | Decided |
|---|---|---|
| 1 | `checkpoint-1.html` | Panels: the wall. The wall label and the tool dock are lettered straight onto the wall; the plaque and frame treatments are dropped. Logo: Section cut down the midline (now the Specimen identity in `identity/specimen/`). The website's download buttons stay as they are. |
| 2 | `checkpoint-2.html` | Depth gauge: Rule, without the "Dissection" head and with a knob as tall as the percentage's figures. Lessons: Vitrines. Histology library: the Catalogue, with no foot line (how the endless list ends goes to checkpoint 3). The model viewer room is kept as built. Search: the drop-down is rejected, and no "Ctrl K" is printed in the chrome (the key stays bound). No white or light panels anywhere. Labels: the numbered key, placed better, with caption rails on demand (checkpoint 3). |
| 3 | `checkpoint-3.html` | Waiting for the owner's picks. Four questions, three options each, the first recommended. Labels: Dock pair, Wall line, Corner key. Search: On the body, The index, In the title. Navigation: Rooms bar, Side rail, Lobby. Histology library: Endless catalogue, Body map, Light table. Each option can be tried in `app/specimen-labels3/`, `app/specimen-search/`, `app/specimen-nav/` and `app/specimen-histology/`. |

Checkpoint 1's picks are applied to `app/specimen/`, `site/specimen/` and this gallery. The mockup and the website now
have one panel treatment, the wall, and no `?panel=` switch. Checkpoint 2's decisions are applied to `app/specimen/`:
the Rule gauge, Vitrines for the lessons, the Catalogue, the viewer, the search without a drop-down and no light panels.
The Rule is also the website's depth gauge. Before and after pictures are in `renders/checkpoint-3/apply/`.

## The three directions

| | Overlay | Specimen | Plate |
|---|---|---|---|
| Idea | Film leaves over a quiet board | The body on display, as in a museum | The screen as an atlas plate |
| Signature in the app | The layer rail: the dissection slider as the app's right edge, one tab per depth band | The wall label: the selection lettered on the wall beside the body; a pool of light behind it | Labels in two margin columns; the selection set as the plate's key; a depth rule |
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
| `checkpoint-1.html`, `checkpoint-2.html`, `checkpoint-3.html` | The checkpoint pages: the options put to the owner, and (from checkpoint 2) what was decided before. |
| `app/<direction>/index.html` | App mockups, HTML and CSS at 1920 × 1080. Choose a scheme and screen in the address bar, for example `app/specimen/index.html?scheme=green&screen=practice`. Overlay and Plate have nine screens: `atlas`, `peel`, `lesson`, `lessons`, `models`, `radiology`, `practice`, `histology`, `settings`. Specimen has eleven: those nine plus `viewer` (the opened model; `&view=corpuscle` for the close view) and `histology-library`. On the atlas and peel, `&gauge=drag` and `&gauge=only` show the gauge's other states. |
| `app/specimen-<topic>/` | Working copies of the Specimen mockup, each with a `PORT.md` that says how to carry it into `app/specimen/`. Checkpoint 2: `labels`, `gauge`, `library`, `states`, `viewer` (decided). Checkpoint 3, the options waiting for a pick: `labels3`, `search`, `nav` and `histology`, each with `?variant=1\|2\|3`. `app/specimen-nav/AUDIT.md` is the navigation audit behind them: every place in today's app, how you reach it and how you get back. |
| `identity/` | Marks, lockups, app icons and favicons for each direction; `identity/README.md` says which drawing to use at which size. |
| `site/<direction>/index.html` | The three websites. Each is one working page, responsive down to phone width, with its own scheme switcher. `?scheme=` picks a scheme. |
| `site/specimen/` | The chosen website, as it will ship: `index.html`, `404.html`, `robots.txt`, `sitemap.xml` and its images in `img/` (see *The website* below). |
| `site/build.py` | Builds the website into `site/dist/`, one folder for a static host. |
| `renders/<direction>/` | The mockups rendered to WebP: every screen in every scheme at 1×, the atlas screen of every scheme at 2× (`@2x`), and every screen of each default scheme at 2×. Specimen 82, Overlay 88, Plate 78: 248 in all. |
| `renders/site/` | Website captures: first screen on desktop (1× and 2×) and phone (2×), and the whole page, four per direction. |
| `renders/checkpoint-1/`, `renders/checkpoint-2/` | The pictures on the checkpoint pages: option renders, logo boards and before/after captures. |
| `renders/checkpoint-3/` | Checkpoint 3's pictures: `apply/` (checkpoint 2's decisions in the main mockup, before and after); the options, `labels/`, `search/` and `search3/`, `nav/` and `nav2/` (each topic's second pass), `histology/`; the passes over the main mockup, `knob/`, `audit/` and `cleanup/`; and the website's passes, `site/`, `site2/` and `site3/`. |
| `renders/current/` | Two screenshots of today's app, used in the gallery. |
| `current/` | Full-resolution screenshots of today's app (v4.0.8) that the review refers to. |
| `system/schemes.py` | The 21 colour schemes. Running it writes `schemes.json`, `schemes.css` and `schemes.js`, and checks contrast. |
| `system/BUILD-NOTES.md` | Notes for building Specimen in the Qt app: type, flat colours, wall text over the 3D view. |
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

| Check | Minimum required | Lowest, Specimen (6) | Lowest, all 21 |
|---|---|---|---|
| Body text (`text` on `surface`; on the wall) | 7:1 | 10.85:1; 11.17:1 | 9.76:1; 7.73:1 |
| Secondary text (`text_2` on `surface`; on the wall) | 4.5:1 | 7.48:1; 9.37:1 | 7.14:1; 6.56:1 |
| Faintest text (`text_3` on `surface`) | 3:1 | 5.04:1 | 4.77:1 |
| Accent on its surface | 4.5:1 | 6.47:1 | 5.94:1 |
| Text on the accent (`on_accent`) | 4.5:1 | 8.61:1 | 6.19:1 |
| `leader` on `spot` (Specimen) | 3:1 | 3.12:1 | |
| `hair` on the wall (Specimen, decoration) | 1.4:1 | 1.70:1 | |

All 21 schemes pass every check (recomputed 15 October from `system/schemes.py`'s own `report()`). The lowest
Specimen values are all in Gallery slate, except `leader` (Museum green) and `hair` (Charcoal).

Specimen's text now sits on the wall itself, so it was also measured against the lightest parts of the wall. On
`stage_top` (the top of the gradient) the lowest values are `text` 11.17:1, `text_2` 7.70:1, `text_3` 5.19:1, the accent
6.66:1 and the ghost button edge (`text` at 41%) 3.22:1. In the centre of the pool (`spot`) `text_3` drops to 3.74:1 and
the accent to 4.80:1 (both Gallery slate), so faint text and brass text should not sit in the middle of the pool. Nothing
in the mockups does.

Every scheme defines the same tokens:

- **Stage:** `stage_top`, `stage_bottom` and `spot`, used behind the 3D view.
- **Surfaces:** `surface`, `surface_2`, `surface_3` and `sunken`.
- **Lines:** `line` and `line_2`.
- **Text:** `text`, `text_2` and `text_3`.
- **Accent:** `accent`, `accent_2`, `accent_soft` and `on_accent`.
- **Selection:** `select`, the selection colour inside the 3D view.

Specimen adds flat colours for what the mockups would otherwise mix in CSS, flattened over the middle of the wall
gradient, so QSS and QPainter can use them:

| Token | Is | Use | Gallery slate |
|---|---|---|---|
| `hair` | `text` at 16% over the wall | Rules and dividers on the wall. Decoration only (about 1.7:1): never a control's border. | `#44494d` |
| `leader` | `text` at 55% | Label leaders and the open anchor rings; at least 3:1 on `spot`, so they read in the pool. | `#949594` |
| `card_line` | `text` at 9% over the plaque | The plaque's top edge and dock dividers. Unused since checkpoint 1 dropped the plaque; still in the scheme files. | `#41464a` |

Specimen also still defines `card`, `card_text` and `card_text_2`, from the light wall label that the wall replaced.
Nothing in `app/specimen/` or `site/specimen/` uses them now. Overlay adds `film_alpha` for its panels.

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
  background pass that already draws the gradient and vignette. The wall label and the dock are lettered on the wall in
  the ordinary text colours, with `hair` rules and `leader` lines. `system/BUILD-NOTES.md` has the details.
- **Plate** draws labels in margin columns instead of beside the model. The label placer already sorts and
  de-overlaps labels, so this is a new layout mode for it. Bristol is light, so lesson figures, film viewers and
  micrographs need checking on a light stage. Night plate and Slate night keep the same design dark.

The fonts are bundled under the SIL Open Font License, so the app can ship them.

## The website

`site/specimen/index.html` is layeredhuman.com: one page that works from 320 to 2560 px wide, on all six walls.
`?scheme=<wall>` or `#wall-<wall>` picks a wall (`slate`, `green`, `prussian`, `aubergine`, `umber`, `charcoal`), and
the page remembers the visitor's choice. It opens straight from this folder: it reaches the plates, fonts and renders it
shares with the mockups through `../../`.

- **The 404 page** (`404.html`): "Not on display.", a lit empty case, the way home and the rooms of the home page.
- **The head**: title and description, the canonical address, a theme colour that follows the wall, a social card for
  link previews (`img/og-card.jpg`, 1200 × 630) and structured data (JSON-LD) describing the app.
- **`robots.txt` and `sitemap.xml`**: everything may be indexed; the sitemap lists the one page.

**Publishing.** From this folder, `python site/build.py` writes `site/dist/`: the home page and the 404 page at the root
of one folder, with only the files they use, about 13 MB in 118 files. It stops if a page names a file that is not
here, and checks every link in the result. `python site/build.py --serve` builds it and serves it at
http://localhost:8000 the way a host does, missing addresses included. Upload the contents of `site/dist/` to a static
host. GitHub Pages, Netlify, Cloudflare Pages and Vercel all serve its `404.html` for addresses that do not exist. For
a site that will not sit at the root of its domain, add `--base /path/`.

**Before launch.** The Mac button links to `releases/latest/download/Install-Layered-Human-Mac.dmg`, but today's
release names the file `Install-Anatomy-Explorer-Mac.dmg` (`MAC_INSTALLER` in `packaging/prepare_release_assets.py`;
the release notes in `.github/workflows/publish-built-release.yml` name it too). Until the release file is renamed with
the app, or the button points at the old name, the Mac button leads to GitHub's "Not Found". The Windows button's
`Download-Windows-Installer.ps1` matches today's release.

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
5. **Renders:** `python tools/render_all.py [direction ...]` renders every mockup screen into `renders/`
   (`python tools/render_all.py specimen` for Specimen only).
   `node tools/render_mockups.mjs <out> <direction> <scheme|all> <screen|all> [scale]` renders a subset. The viewer's close
   view is not in the standard set: render it with `MOCKUP_QUERY="view=corpuscle"` and the `viewer` screen.
6. **Website captures:** `node tools/shot_gallery.mjs <out> <direction> <scheme> full` writes three PNGs to `<out>`. Save
   them as `renders/site/<direction>_site_desktop@2x.webp` (the 2880 × 1800 capture),
   `<direction>_site_desktop.webp` (the same, scaled to 1440 × 900), `<direction>_site_mobile@2x.webp` and
   `<direction>_site_page.webp` (the whole page, scaled to 720 wide).
7. **The Specimen website's Study section** shows each wall's lesson render,
   `renders/specimen/specimen_<wall>_lesson.webp` (and `@2x.webp`), cropped by CSS fractions of the 1920 × 1080 screen
   (`--cx`, `--cy`, `--cw`, `--ch` on `.scene-crop`; the narrow layouts set their own). On phones the heart has its own
   picture, `specimen_<wall>_lesson-heart.webp`: the lesson screen at twice the size with the names hidden
   (`[data-screen-id="lesson"] .lbl { visibility: hidden }`), clipped at 1250, 450, 480 × 510 css px, so 960 × 1020. Its
   pins 1 to 3 are placed by percentages in the page. After re-rendering the lesson screen, redo the heart pictures and
   check the crops and the pins at desktop, tablet and phone widths.

## How this was made

1. **Review of today's app.** I ran the current app headless and captured every workspace, then reviewed it screen by
   screen (`research/current-ux-evaluation.md`).
2. **Brand and website brief.** A separate brief covers positioning, voice and naming (`research/brand-and-site-brief.md`).
3. **Directions.** One was assigned by the design toolkit's concept seed (Specimen); one is the toolkit's own pick (Plate);
   one is a challenger (Overlay). The owner chose Specimen.
4. **Checkpoints.** Each later round is put to the owner as a checkpoint page with three options per question.
5. **Mockups.** The app mockups are HTML and CSS. Every anatomy figure in them is a real render from the app, and every
   label sits on a point read from the renderer's picking buffer.
6. **Websites.** Each was built from its written brief by an agent, then reviewed and corrected here.

The app mockups are HTML pictures of the design, not Qt code. Some of them work: in `app/specimen/` the depth gauge
drags and takes the arrow keys, the viewer's two sliders move and the kidney on Models opens the viewer. The checkpoint
3 copies go further: the labels open their captions, the search answers what you type, the navigation mockup can be
walked from room to room and the Histology library scrolls.
