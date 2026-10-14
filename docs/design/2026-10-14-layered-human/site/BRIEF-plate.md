# Direction C: Plate (site brief)

Read `BRIEF-shared.md` first. Set `data-design="plate"`; the default scheme is `bristol`. The schemes are bristol,
greycard, linen, celadon, newsprint, night and slatenight.

## Thesis

The page as an atlas plate: a figure on paper, labels set in two clean margin columns with fine leader lines, a plate
number and a caption. Students already learn from plates like this. The page refuses the category default, a hero
headline over a screenshot and a row of feature cards. Here the labels around the figure *are* the page's contents,
and each one leads to the plate that explains it.

## Own world

- **Paper and ink:** paper is `--stage-top`/`--surface`; ink is `--text`, `--text-2` and `--text-3`; the second ink
  is `--accent`. Hairline rules come from `--line` and `--line-2`.
- **No shadows, no cards, no rounded corners** beyond 2px. Hierarchy comes from type, rules and space.
- **Type:** Atkinson Hyperlegible Next, chosen because legibility is an atlas's job.
  - Display: 700–800, large and tight.
  - Labels: 15–16px at 500.
  - Captions: 15px italic.
  - Plate numbers, figure letters and IDs: Atkinson Hyperlegible Mono.
- **Page furniture:**
  - A running head: a thin rule with "Layered Human" left, the current plate title centre, and the plate number
    right.
  - Folios.
  - Figure letters (A, B, C…) in mono.
  - Captions that begin "Plate 3." or "Fig. 3B."
- **Margin-column labels:** labels sit in a left and a right column at fixed x, sorted by the height of their anchor,
  pushed apart so they never overlap. Each joins its anchor with a horizontal run and one diagonal, ending in a small
  ring (or a filled dot when selected), like a printed plate. Selected labels are 700 weight with the accent leader.

## Story

- **Understand:** the app is an atlas you can take apart. Every plate on the page is a real figure from it.
- **Believe:**
  - real figures and real labels on real structures;
  - the dissection sequence as a figure row;
  - the section as a labelled plate;
  - the kidney zoom with insets;
  - the film paired with the model by number;
  - the lab course listed.
- **Do:** download, with an honest caption about size and warnings.

## First viewport (1440×900): Plate 1

- **Running head** at the top.
- **The figure:** `hero26_sel_<hex>`, centred, about 86% of the viewport height.
- **Margin labels:** about six on each side, using real anchors from `hero26_sel_7cc8da` (`deltoid`, `pectoralis`,
  `biceps` (selected), `brachioradialis`, `rectus_abdominis`, `sartorius`, `rectus_femoris`, `vastus_medialis`,
  `tibialis_anterior`, `serratus`…). Each label has two lines:
  1. the structure name in ink;
  2. under it, in `--text-3` at 13px, the feature that structure leads to. For example:
     - "Biceps brachii / *Select anything for its nerve, action and blood supply*";
     - "Rectus abdominis / *Peel to any depth*";
     - "Pectoralis major / *Section through it*";
     - "Sartorius / *Practise finding it*".
- **Labels as navigation:** each label links to its section (#peel, #sections, #films, #study…).
- **Caption block (bottom-left, max 520px):**
  - "**Plate 1.** Layered Human, a free 3D anatomy atlas for your computer." Then the headline "Peel the body back,
    layer by layer." at about 56–64px, 800 weight, then the subline.
  - **Download for Mac** (primary, filled ink-accent, square 2px corners) and **Download for Windows** (outlined).
  - The meta line.

## Signature interaction: labels that lead

- **Highlighting:** hovering or focusing a margin label thickens its leader, fills its anchor dot in accent and dims
  the other labels to `--text-3`. The same happens in reverse: hovering near an anchor highlights its label.
- **Navigation:** clicking scrolls to the plate the label names.
- **Layout:** position everything in JS from the anchors (scale = rendered width / natural width), on resize too.
  Draw leaders in one absolutely positioned SVG.
- **Mobile:** labels become a numbered key list under the figure, and the figure gets small numbered rings at the
  anchors.
- **Reduced motion:** no transitions; highlight states still work.

## Plates after Plate 1, in order

Each plate has a plate number in the running head, a title, a figure and a caption.

1. **Plate 2, Dissection.**
   - A figure row A–F: `peel_00_skin`, `peel_16_fascia`, `peel_26_superficial`, `peel_40_deep`,
     `peel_55_skeleton`, `peel_70_cavities`. Equal heights, aligned feet. Under each: the letter in mono, the layer
     name and the depth range.
   - A horizontal depth rule under the row, with the eight stops marked and labelled "Superficial" … "Deep".
   - Caption: "Fig. 2A–F. The same body at six depths…" plus the brief's §2 copy.
2. **Plate 3, Sections.** `section_inferior`, large. About 10–12 labels in two margin columns from real anchors: lv,
   rv, ra, la, lung_l, lung_r, vert, sternum, pec, lat, liver, serratus. Caption: "Plate 3. Transverse section
   through the thorax at T8, seen from below, as on a CT. In the app, the cut names everything it passes through:
   click a name to select it."
3. **Plate 4, Organ to cell.** `kidney_v_kidney` large, with two inset frames (thin ink rectangles joined by zoom
   lines) showing `kidney_v_corpuscle` and `kidney_v_podocytes`. Figure letters A, B, C. Caption from brief §4.
4. **Plate 5, Films.**
   - `cxr_pa.jpg` and `cxr_model` side by side, linked by the same numbers: numbered rings on the film, numbered
     margin labels on the model.
   - A legend table below: number, structure, what to look for. Use the case's notes, for example "Right
     hemidiaphragm, higher than the left: the liver is under it."
   - Credits in the caption.
   - A smaller second figure: `cxr_effusion.jpg` with `cxr_effusion_model`.
5. **Plate 6, Lessons and practice.** The app renders `plate_bristol_lesson` and `plate_bristol_practice` as figures
   with captions, plus the lab course as an index-style table (Lab, topic, lessons).
6. **Plate 7, Histology.** The micrograph with numbered rings and a key.
7. **Index.** The README facts typeset like a book index, alphabetical, with numbers right-aligned in mono (for
   example "Clinical correlations 423", "Landmarks 1,109", "Micrographs 1,049").
8. **Colophon.** Credits and licences, and "Free. Offline. Yours."
9. **Download.** Two columns, Mac and Windows: steps as a numbered list, the warning note, and the PowerShell fallback
   in a mono code block with a copy button.
10. **FAQ.** `details`/`summary`.
11. **Footer.**

## Mobile

- The running head shortens to the plate number and title.
- Figure rows scroll horizontally with snap.
- Margin labels turn into numbered keys (see the signature interaction).

## Honest risk

The atlas page is the most familiar of the three directions for this category. Its edge has to come from typographic
precision and the labels-as-navigation idea, so execute them perfectly.
