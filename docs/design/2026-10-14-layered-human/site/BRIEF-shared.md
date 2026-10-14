# layeredhuman.com: shared brief for all three directions

This brief is for whoever builds one of the three website directions. Read it together with the direction brief
(`BRIEF-overlay.md`, `BRIEF-specimen.md` or `BRIEF-plate.md`).

## What the site is for

Layered Human (renamed from Anatomy Explorer) is a free, offline, desktop 3D anatomy atlas for Windows and
Apple-silicon Macs. The site has one job: **earn the download honestly**. It shows the mechanism working with real
renders from the app, names the real content, and puts the size, the system requirements and the operating-system
warnings beside the download button.

- **Product truth:** `/PRODUCT.md`.
- **Copy, claims, voice and section order:** `../research/brand-and-site-brief.md` §1–§7. Use hero option A unless
  the direction brief says otherwise. Use only README numbers (3,922 structures; 303 lessons in 1,614 steps; 1,525
  recall questions; 109 lab-course lessons; 1,824 practice items; 41 models; 104 radiology cases; 101 tissues;
  1,049 micrographs; 1,109 landmarks; 423 clinical correlations; innervation for 468 muscles and the action of 466;
  about 3.4 GB; Mac: Apple silicon, macOS 13 or later, about 8 GB free while installing).
- **Never:** testimonials, user counts, ratings, institutions, press, comparisons ("only", "first", "unlike"),
  outcome promises, clinical claims, "free forever", or any number not in the README.

## Files and assets (all paths relative to `site/<direction>/index.html`)

- **Output:** a single `site/<direction>/index.html` with inline `<style>` and `<script>`. No frameworks, no build
  step and no external JavaScript. It must work when opened straight from disk (`file://`): no `fetch()` of local
  files; use the provided `.js` data files instead.
- **Fonts:** `<link rel="stylesheet" href="../../assets/fonts/fonts.css">` (self-hosted: Archivo, Literata, Fira
  Sans, Atkinson Hyperlegible Next, Atkinson Hyperlegible Mono). Don't load Google Fonts or any other host.
- **Colour schemes:**
  - Load `../../system/schemes.css` and `../../system/schemes.js` (`window.LH_SCHEMES`).
  - Put `data-design="<direction>"` and `data-scheme="<default>"` on `<html>`. That gives you CSS custom properties:
    `--stage-top --stage-bottom --spot --surface --surface-2 --surface-3 --sunken --line --line-2 --text --text-2
    --text-3 --accent --accent-2 --accent-soft --on-accent --select`, plus `--card --card-text --card-text-2`
    (Specimen) and `--film-alpha` (Overlay). `LH_SCHEMES[direction].schemes[key].mode` is `light` or `dark`; mirror
    it as `data-mode` on `<html>` for mode-specific shadows.
  - Use only these tokens for colour. No hard-coded colours except pure black/white for image mattes.
  - Build a **scheme switcher**: small, unobtrusive, keyboard accessible, listing every scheme of the direction by
    name with a swatch. It sets `data-scheme`/`data-mode` live, reads `?scheme=` from the URL first, and remembers
    the choice in `localStorage` inside try/catch.
- **Real renders:** the app's own renderer, matted to transparency. They are `../../assets/plates/<name>.webp`:
  - **Whole body, anterior:** `body_muscles`, `body_skeleton`, `body_organs`, `body_vessels_nerves`, `body_back`
    (posterior), `body_three_quarter`.
  - **The peel sequence (same camera):** `peel_00_skin` (Skin surface, 0%), `peel_16_fascia` (Deep fascia, 16%),
    `peel_26_superficial` (Superficial muscles, 26%), `peel_40_deep` (Deep muscles, 40%), `peel_55_skeleton` (Skeleton
    & joints, 55%), `peel_70_cavities` (Body cavities, 70%).
  - **Selection:** `hero26_sel_<hex>`, the body at 26% depth with both biceps brachii selected. `<hex>` is the
    scheme's `select` colour without `#`, so pick the file matching the active scheme in JS.
  - **Transverse section:** `section_inferior`, a transverse section of the thorax seen from below, as on a CT
    (anterior up, patient's right on the viewer's left).
  - **Chest radiograph scene:** `cxr_model` (thorax set up like the PA film) and `cxr_effusion_model` (a massive
    right pleural effusion; the fluid is shown in the model). The films are `../../assets/images/cxr_pa.jpg`
    (CC0, Mikael Häggström) and `../../assets/images/cxr_effusion.jpg` (CC BY-SA 4.0, Sara Nabih).
  - **Heart:** `heart_home_clean` (true-scale heart without the pericardium), `heart_open` (chambers opened),
    `heart_lesson_<hex>` (LAD and circumflex highlighted).
  - **Kidney, organ to cell:** `kidney_v_kidney` → `kidney_v_corpuscle` → `kidney_v_podocytes`; also
    `kidney_v_nephron`.
  - **Other models:** `cardiac_muscle`, and thumbnails `thumb_<id>` (eyeball, ear, tooth, compact_bone, thin_skin,
    liver_lobule, blood_cells, lymph_node, spleen, retina, skeletal_muscle, peripheral_nerve, hepatobiliary, …).
  - **Histology:** `../../assets/images/histo_simple_columnar.jpg` (CC BY-SA 4.0, Echinaceapallida) and
    `histo_sc_01..13.jpg`. Credits are in `../../assets/images/CREDITS.json`.
  - **Label anchors:** `../../assets/plates/plates.js` sets `window.LH_PLATES.anchors[<plate>][<key>] = {x, y}` in
    the plate's own pixels (also `r`, `bbox`). Use them to place leader-line labels exactly on real structures. Scale
    by `displayedWidth / naturalWidth`.
    - Keys for `hero26_sel_7cc8da`: `biceps.vl`, `deltoid.vl`, `pectoralis.vr`, `brachioradialis.vl`,
      `rectus_abdominis.vr`, `sartorius.vl`, `rectus_femoris.vr`, `vastus_medialis.vr`, `tibialis_anterior.vl`, …
      (`.vl` = viewer's left = the patient's right).
    - `section_inferior`: `lv`, `rv`, `ra`, `la`, `lung_l`, `lung_r`, `vert`, `sternum`, `pec`, `lat`, `liver`,
      `serratus`, `trapezius` (each `.vl`/`.vr`).
    - `cxr_model`: `c1`… (numbers match the film labels).
    - `heart_lesson_<hex>`: `lad`, `lcx`, `lmain`, `aorta`, `pulm`.
    - `peel40_ids`: `liver`, `stomach`, `smallint`, `heart`, `ribs`, `quadratus`.
    - Print `Object.keys(LH_PLATES.anchors)` to see every set.
  - **App mockup renders**, to show the app at work: `../../renders/<direction>/<direction>_<scheme>_<screen>.webp`
    where screen is `atlas`, `peel`, `lesson`, `lessons`, `models`, `radiology`, `practice`, `histology` or
    `settings`. They may not exist yet while you build: reference them with `loading="lazy"`, a fixed aspect-ratio box
    (1920×1080), and the default scheme in the path. Swap the scheme in the path in JS when the scheme changes.

## Download facts (use exactly)

- **Mac:** `https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Install-Anatomy-Explorer-Mac.dmg`.
  Apple silicon (M1 or newer), macOS 13 or later, about 8 GB free while installing. Steps:
  1. Open the disk image and double-click the installer.
  2. If macOS says it "cannot be opened": System Settings → Privacy & Security → Open Anyway.
  3. It downloads about 3.4 GB, checks each part, copies the app into Applications and opens it. If it stops, run it
     again.
- **Windows:** `https://github.com/ethanprince4/AnatomyExplorer/releases/latest/download/Download-Windows-Installer.ps1`.
  Steps:
  1. Right-click the downloaded file and choose **Run with PowerShell**. Double-clicking it opens Notepad instead.
  2. It downloads the installer parts, joins them and starts the installer.
  3. If "Windows protected your PC" appears: **More info**, then **Run anyway**.

  If that doesn't work, open PowerShell in your Downloads folder and run
  `Set-ExecutionPolicy -Scope Process Bypass -Force; $ProgressPreference='SilentlyContinue'; .\Download-Windows-Installer.ps1`.
- **Why the warning:** "The app isn't signed with a paid developer certificate, so your computer can't check who made
  it. Only the installer needs the extra click. The code is public on GitHub."
- **Code:** `https://github.com/ethanprince4/AnatomyExplorer` (MIT).
- **Footer on every page:** "Layered Human is a free study aid, not a medical device. Anatomy data: Z-Anatomy and
  BodyParts3D (CC BY-SA). Images: Wikimedia Commons contributors. Code: MIT." with links to Credits & licences (an
  in-page section), GitHub, and Help (an in-page FAQ section is fine).

## Quality floor (all directions)

- **Semantics and access:**
  - Semantic landmarks, one `h1`, and an ordered heading outline.
  - A visible focus ring (2px, offset 2px, accent).
  - Text contrast ≥ 4.5:1. Every scheme's tokens already pass; don't put text on photos without a matte.
  - Images carry alt text that names what is shown, for example: "The body at 40 % dissection depth: ribcage,
    abdominal organs and deep muscles exposed".
- **Motion:**
  - One signature interaction, built for real, as the direction brief describes.
  - Respect `prefers-reduced-motion`: show the end state, with no scroll-linked animation.
  - Content is visible by default; never hide content behind an animation that might not run.
- **Responsive:** desktop at 1440 and 1280 wide, and mobile at 390. No horizontal scroll; 16px side gutters on mobile.
  The scheme switcher stays reachable on mobile.
- **Refuse these:**
  - kicker or eyebrow labels above headings;
  - gradient text;
  - glass or blur as decoration;
  - coloured `border-left` callouts;
  - hard offset shadows;
  - hero-metric templates (a big number with a small label);
  - same-size icon cards;
  - emoji;
  - section numbers that carry no information.

  Icons are inline SVG drawn in one stroke weight. A copy of the app's icon paths is in `../../app/shared/icons.js`;
  you may inline any of them.
- **Theme the details:** text selection, the caret, scrollbars, focus rings, link underline offset, and tabular
  numerals for numbers.
- **Performance:**
  - `loading="lazy"` below the fold;
  - explicit `width`/`height` or `aspect-ratio` on every image;
  - no image larger than it is shown at 2×.

## Self-review

You may run `node ../../tools/shot_site.mjs index.html <out-prefix> [scheme]`. It writes desktop and mobile
screenshots (first viewport and full page) to `<out-prefix>_*.png` and prints any page errors.
- **Viewing:** open the PNGs to check your work. Check at least the default scheme, one light and one dark scheme.
- **Rounds:** do no more than two rounds of fixes.
- **Where to save:** put screenshots in a scratch folder outside the repository.

Write only `site/<direction>/index.html` (and nothing else in the repository).
