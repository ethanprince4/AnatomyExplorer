# Direction B: Specimen (site brief)

Read `BRIEF-shared.md` first. Set `data-design="specimen"`; the default scheme is `slate`. The schemes are slate,
green, prussian, aubergine, umber, charcoal, plaster and celadon.

## Thesis

The body on display, as in an anatomical museum: one specimen at a time, lit on a painted wall, with a small label you
read up close. The page refuses the category default, a white clinical SaaS page with blue buttons and icon cards. It
is a quiet exhibition you walk through, room by room, with the download desk at the end.

## Own world

- **Wall:** the scheme's stage colour (`--stage-top` to `--stage-bottom`), deep, matte and calm. Behind each specimen
  sits a soft pool of light, a radial gradient of `--spot` fading into the wall, like a spotlight.
- **Lettering:** text is "printed on the wall" (no cards) in `--text` and `--text-2`.
- **Wall labels:** the one exception. Small light cards in `--card` with `--card-text`, 4px radius, a hairline rule
  inside, sitting beside their specimen like museum labels. Their layout:
  1. title in Literata;
  2. Latin or secondary line in Literata italic;
  3. a rule;
  4. a details line in Fira Sans at 14px;
  5. an "accession" line in Fira Sans with tabular numbers (for example "Atlas · 3,922 structures · TA2 IDs").
- **Type:**
  - Display: Literata (opsz 72, weight 300–420, large, slightly tight), with italic for secondary lines.
  - Interface and body: Fira Sans (16–17px body, 600 for small headings).
- **Accent:** a quiet brass or sand (`--accent`) for active nav underlines, focus and the primary button.
- **Restraint:** generous negative space, few elements, slow and calm rhythm.

## Story

- **Understand:** a complete human body you can take apart, examined one specimen at a time.
- **Believe:**
  - the real renders, shown the way an exhibit is;
  - the labels with real names and Latin;
  - the lab course listed by topic;
  - honesty about size and warnings.
- **Do:** download (the "admission" is free, but don't make that pun in copy; keep it plain).

## First viewport (1440×900)

- **Wall:** full screen.
- **Header:**
  - Left: the mark (three nested rounded contours with one quadrant cut away, as in a cut-away specimen) and
    "Layered Human" in Literata at 22px.
  - Right: text links to the rooms (Layers, Sections, Organ to cell, Films, Study, Download) in Fira Sans at 15px. The
    current room has a 2px accent underline.
- **The specimen:** `hero26_sel_<hex>`, centred in a spotlight pool, about 88% of the viewport height.
- **Wall lettering (left, about 520px wide, vertically centred):** "Peel the body back, layer by layer." in Literata
  at about 64–76px, weight 340, with the subline below.
- **Wall label card (lower right, beside the specimen's arm, about 340px):**
  - "Biceps brachii" / "Musculus biceps brachii" (italic) / rule.
  - "Selected in the atlas. Muscular system · Upper limb."
  - A short leader line from the card to the right biceps anchor (`biceps.vr` or `.vl`, whichever is nearer the card).
- **Download:** below the lettering, two buttons (**Download for Mac** primary, **Download for Windows**), then the
  meta line "Free · about 3.4 GB · Apple silicon Mac (macOS 13 or later) or Windows".

## Signature interaction: the spotlight

- **Specimens:** every specimen on the page sits in its own pool of light.
- **Entering view:** as a specimen enters the centre of the viewport (IntersectionObserver), its pool brightens and
  widens slightly (radial gradient size/opacity) and its wall label fades up. Specimens out of focus sit in a dimmer
  pool.
- **The "Layers" room:** a long horizontal gallery of six specimens in a row, `peel_00_skin` … `peel_70_cavities`,
  each on its own pool, each with a tiny label underneath: name, depth range (e.g. "Superficial muscles · 26–40%")
  and one line of what is exposed.
- **Interaction:** hovering or focusing a specimen brightens its pool and dims the others.
- **Keyboard:** each specimen is a focusable figure.
- **Mobile:** the row becomes a horizontal scroll-snap gallery with visible overflow cues.
- **Reduced motion:** all pools are at full brightness, with no transitions.

## Rooms after the hero, in order

1. **Layers**, as above.
   - Room title in Literata: "Skin to bone, in the order you choose".
   - Copy: brief §2 "Depth that follows the body".
2. **Sections.** `section_inferior`, large and centred in a pool.
   - Labels sit around the edge as small wall lettering with hairline leaders to real anchors: lv, rv, lung_l,
     lung_r, vert, sternum, liver, pec, lat.
   - Headline: "Cut anywhere. The cut names itself."
   - A wall label card: "Transverse section through the thorax, seen from below, as on a CT. Every structure the plane
     passes through is named."
3. **Organ to cell.** Three specimens in a row, each in a smaller pool: `kidney_v_kidney`, `kidney_v_corpuscle`,
   `kidney_v_podocytes`, with labels "Kidney", "Renal corpuscle", "Podocytes". A wall label: "Kidney with the
   nephron. True scale. Eight stored views."
4. **Films.**
   - The film `cxr_pa.jpg`, framed like a lightbox print (a thin `--line` frame), and `cxr_model` beside it, with
     matching numbers (use the c1… anchors). Each number appears once on each side.
   - Copy from brief §5.
   - A second, smaller pair: `cxr_effusion.jpg` and `cxr_effusion_model`.
   - Credits on small wall labels.
5. **Study.** The app renders `specimen_slate_lesson` and `specimen_slate_practice`, hung as two large prints with
   wall labels.
   - The lab course as a printed list: Lab 1 … Lab 9, Practical 1 and 2, with their topics in Literata.
   - Mention Hunt.
6. **Under the microscope.** The micrograph with numbered pins.
7. **Built to be looked up.** A typeset list on the wall: two columns, Fira Sans, with the numbers in tabular
   figures. Not tiles.
8. **Free. Offline. Yours.** and **Acknowledgements** (credits) as two wall texts.
9. **Download desk.** Two label cards, Mac and Windows, each with its button, requirements, the steps and the warning
   note, plus the PowerShell fallback.
10. **Questions.** `details`/`summary`, printed on the wall.
11. **Footer.**

## Mobile

- Header links collapse into a menu button that opens a full-screen wall-coloured sheet.
- Wall labels sit under their specimen.

## Honest risk

A museum can feel slow and precious. Keep copy short, keep the download visible early, and don't let the mood hide
the facts.
