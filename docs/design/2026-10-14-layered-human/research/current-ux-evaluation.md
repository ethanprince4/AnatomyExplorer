# Current UX evaluation: Anatomy Explorer → Layered Human

*14 October 2026. Heuristic evaluation, cognitive walkthrough and accessibility review of the current desktop app,
written as input to the Layered Human redesign.*

## Scope and method

**What was evaluated.** The 14 screenshots in `../current/` (1920×1080, captured from the running app on 14 October 2026),
read against `PRODUCT.md`, the README sections "Using it" and "Study features", and the owner's binding brief: *simple
colours that do not distract from learning or the model; the 3D model is the focus of the app.* Where a screenshot
alone could not explain a finding, the interface code in `app/ui/` was read (`theme.py`, `studio_style.py`,
`studio_shell.py`, `search_panel.py`, `lessons.py`, `radiology.py`, `histology.py`, `settings_dialog.py`).

**How.** Nielsen's 10 heuristics, WCAG 2.2 AA (with the AAA focus criterion noted where relevant), the Intent
anti-pattern catalogue, and cognitive walkthroughs of four study tasks. Contrast ratios were calculated by hand from
the hex tokens in `theme.py` and `resources/studio/palettes.json` using the WCAG relative-luminance formula; they are
rounded to one decimal place.

**What was not evaluated.** Live keyboard traversal, screen-reader output, Mac rendering, the quiz/Hunt/practice
flows, My progress, Notes, Saved views, the radiology case library (never captured: see F12), the View tab's
dissection and section controls (never captured: see F3), and UI scales other than 1.0. Findings derived from code
rather than pixels say so. Nothing here is user-tested; severities are the evaluator's judgement.

**Screenshot key.** S01 explore default · S02 selected biceps · S03 Explore panel with search results · S04 "View
tab" · S05 cross-section · S06 lessons library · S07 lesson reader · S08 model library · S09 heart model viewer · S10
radiology "library" · S11 radiology case · S12 histology library · S13 histology viewer · S14 Settings.

---

## 1. The current design language

### Layout model

- **One persistent header card** across every workspace: a light, rounded bar (x 28–1892, y 20–78) on the dark stage
  holding the logo and "Anatomy Explorer", Back (with a history drop-down) and Forward, five workspace buttons
  (**Explore**, **Lessons**, **3D Models**, **Radiology**, **Histology**), a "Search anatomy" field, **Saved views**,
  and a gear button that holds Settings and every classic menu (File, Selection, View, Tools, Study, Help, Updates).
- **Two layout families below the header**, chosen per workspace:
  1. *Stage + floating cards* (Explore, lesson reader, model viewer, radiology): a full-bleed dark stage
     (`STAGE_BACKGROUND #141b22`) with the 3D view, light rounded cards floating over it (left panel, selection card,
     Reveal card), and a centred pill **dock** at the bottom. Explore and the model viewer add a large light display
     title at top left ("3D Anatomy", "Heart").
  2. *Light page in a dark frame* (lessons library, model library, histology library): one large light card
     (x 300–1620, max width 1320) centred on the dark stage, with ~300 px of dark margin either side. The histology
     viewer is a third variant: a light page running almost edge to edge (x 12–1908). Settings is a separate light
     dialog (840×640).

### Palette

- "Study-02 Porcelain / Cobalt" is the only theme (`theme.set_theme` always selects it; the dark token set in
  `theme.py` is now unused).
- Cards: surface `#F8FAFB`, text `#24343D` (≈12.3:1), muted `#526570` (≈5.8:1), borders `#8798A3` / `#C2CFD5`,
  a single accent, cobalt `#364F99`, with a selected fill of `#DCE6F7`.
- Stage: `#141b22` with near-white display text `#f4f5f7`.
- Colour inside the chrome is almost entirely neutral. Saturated colour comes from the anatomy (muscle red, nerve
  yellow, vessel red/blue), the cyan selection outline, H&E pinks in histology and the cobalt numbered markers on
  films.

### Type

- One sans family across the chrome (Noto Sans–style), mostly 13–16 px, semibold for list titles and button labels.
- One display size (34 px × scale, rendered ≈48 px at 1920) used only for the stage title ("3D Anatomy", "Heart").
- Captions and meta lines at ≈11–12 px ("17 results · Enter to open", "109 of 303 lessons · 0 finished · 0 in
  progress", the radiology disclaimer).
- Sentence case throughout the chrome, with exceptions in model titles ("Axillary Skin", "Female Reproductive
  System").

### Components

Rounded cards (14–16 px radius), outlined text buttons, grey filled buttons, cobalt filled buttons, pill chips
("Lab", "Lecture", "System", "Region", "Level"), full-width drop-downs, disclosure-triangle lists, checkbox trees,
sliders paired with spin boxes (Settings), white atlas-style label pills with leader lines and anchor dots in 3D,
numbered cobalt circles on radiographs, dark numbered chips on micrographs, a thumbnail filmstrip (histology) and a
dark navy "selection" card (model viewer).

### What works and must be kept

These are concrete, observed strengths. A redesign that loses them is a regression.

1. **A dark, flat, neutral stage with the body centred and nothing behind it** (S01, S02, S05, S09, S11). The stage has
   no gradient, texture, vignette or decoration, so the anatomy carries all the colour. This is the owner's brief,
   already met inside the stage.
2. **Selection rendered in the model itself** (S02): a cyan outline on the selected muscle and translucent "x-ray" on
   everything else, so the selected part reads instantly in its spatial context. The cyan does not appear in any
   tissue colour. Keep the outline-plus-ghost treatment and keep the outline hue reserved for selection.
3. **Atlas-style labels** (S05, S07, S09, S11): small white pills with dark text, thin leader lines to an anchor dot,
   placed outside the silhouette and stacked in tidy columns. They read like a printed atlas plate and never sit on
   the tissue they name. Keep the form; fix the collisions (F4) and leader-line crossings (F22).
4. **Numbered pairing between a real image and the model** (S11): marker "8" on the film and "8 Left ventricle" on the
   model link the two with no colour coding, and the case notes explain how to read the film. It is the clearest
   teaching device in the app.
5. **Teaching copy in a teacher's voice**, where it exists: "What you see is not organs but the **edges** where tissues
   of different density meet… Lose the air and you lose the line" (S11); "By the end you should be able to…" (S07);
   "Students should look for the single layer of tall cells with basal nuclei" (S13). Keep this voice and extend it to
   the model library (see F7).
6. **Restraint in the chrome**: one accent colour, sentence-case labels in words ("Show all", "Reset", "Saved views"),
   no icon-only navigation in the header, no badges, streaks, confetti or gamified noise. This matches product
   principle 5, "calm for long sessions".
7. **Context-sensitive keyboard hints in plain words**: "Up/Down to choose · Enter to open" (S08), "Scroll or use + / −
   to zoom · Drag or use arrows to pan · Home to fit" (S11), "17 results · Enter to open" (S03). Back and Forward name
   their destination in the tooltip ("Back to …", `studio_shell.set_places`).
8. **Active workspace shown by more than colour**: the checked header button has a fill, a border and a colour change
   (S01 "Explore", S06 "Lessons"). Accent text on the selected fill is ≈6.1:1.
9. **Attribution kept with the image** (S11 "Image: Source and licence · Mikael Häggström · CC0"; S13 "Micrograph ·
   Echinaceapallida · CC BY-SA 4.0 · Wikimedia Commons"). This is a licence requirement in `PRODUCT.md` and is well
   placed: next to the image, not buried in an About box.
10. **The histology viewer's structure** (S13): large image, numbered labels with leader lines, a numbered filmstrip
    of all 13 micrographs, and a caption beneath. This is the right anatomy for an image viewer; it needs tidying
    (F16), not replacing.
11. **The model viewer's parts tree** (S09): grouped checkboxes ("Chambers › Atria, Ventricles", "Heart valves › Valve
    rings…") with a filter field, "Check to show or hide", and a live "6 parts selected" count. It is direct
    manipulation of visibility with clear state.

---

## Anti-pattern verdict

**Clean of deceptive patterns.** No confirmshaming, false urgency, streak pressure, nagging, pre-checked consent or
data collection was found. Progress is shown neutrally ("0/9 finished") with no punishment for absence.

**Common UX anti-patterns present:**

- *Mystery-meat container*: the gear icon holds seven classic menus.
- *Mystery-meat toggle*: "Lesson tools" hides replay, quiz, practice and completion.
- *Stale context*: the panel title does not describe its content.
- *Interactive-looking non-controls*: the "X-ray" badge and the "No 3D link" button.
- *Duplicated controls* for one action on one screen.

These are P1–P2 usability defects, not harms.

---

## 2. Findings

Severity scale: **P0** blocks a core task or violates regulation. **P1** major friction on a core study task, or a
direct conflict with the binding brief. **P2** degraded but recoverable. **P3** polish.

**No P0 findings.** Every core task in the screenshots can be completed by some route. The P1s are where students
will stall, miss the product's main idea, or work against glare for hours.

Counts: P0 0 · P1 8 · P2 14 · P3 6.

### P1: Major

#### F1. Selecting a structure in Explore names nothing on screen
- **Where:** S02 (also S03–S05).
- **What the user experiences:** The student searches "biceps brachii" and presses Enter. Both biceps light up in cyan
  and the body goes x-ray, but nothing on screen says what is selected. There is no label on the model, no selection
  card and no Details card, and the large stage title still reads "3D Anatomy". The facts the README promises in
  Details (Latin name, innervation, action, attachments) are one hidden card away. With the Details card closed, as in
  every Explore capture, the only visible way back to it is **More tools → Details** (or a shortcut the student has to
  know). In the model viewer, by contrast, a selection immediately raises a card ("6 parts selected · Isolate these
  structures or open their details", S09).
- **Heuristics:** H1 Visibility of system status, H6 Recognition rather than recall, H4 Consistency (the model viewer
  does it, the atlas doesn't).
- **Recommendation:** Every 3D stage gets one shared selection component that always shows the selected name (plus
  Latin name and system) on the stage, with **Details**, **Isolate**, **Hide** and **X-ray** as its actions. Use the
  prime top-left slot, now spent on the static "3D Anatomy" title, for the selection name, or attach a compact card to
  the dock. Closing the full Details card must never remove the name.
- **Route:** `/journey` (selection flow), `/organize` (where Details lives).

#### F2. The product's core verbs (dissect, section, reveal) are not visible in Explore
- **Where:** S01–S05.
- **What the user experiences:** `PRODUCT.md` positions the product on "the body comes apart in layers you control";
  principle 3 is "reveal, peel, section and zoom are the core verbs". The default Explore screen (S01) offers
  **Measure**, **Show all**, **Reset** and **More tools**. Measure is a secondary tool, and none of the four peels or
  cuts anything. The dissection slider and the section planes sit behind:
  - the Explore panel's View group (not reachable in S04: see F3),
  - **More tools → Reveal controls** and **More tools → Cross-sections**,
  - the gear menu → View, or
  - keys (`]`, `[`, Ctrl+Alt+1/2/3).

  A first-time student who never opens "More tools" will not find out that the body can be peeled at all. The tools
  also go by three names: README "Dissect"/"View tab", menu "Reveal controls", panel title "View tools"
  (`studio_shell.update_title`).
- **Heuristics:** H6 Recognition rather than recall, H7 Flexibility (accelerators exist, the visible path does not),
  H4 Consistency (naming), product principle 3.
- **Recommendation:** Put **Dissect** (a depth slider with the current layer named), **Section** (plane picker + level),
  **X-ray/Reveal** and **Isolate** directly on the stage dock in Explore, and use the same dock in the model viewer,
  lesson reader and radiology 3D pane. Move Measure into a secondary group. Give each tool one name and use it in the
  dock, the menu, the panel and the README.
- **Route:** `/organize` (tool hierarchy and naming), `/journey` (dock interaction).

#### F3. The Explore panel's title contradicts its content, and search takes over the panel
- **Where:** S03, S04, S05.
- **What the user experiences:** The left card is titled **"Systems"** in S03 and **"Regions"** in S04 and S05, but in
  all three it shows the same 17 search results for "biceps brachii". The title is the name of whichever hidden tab
  was last active (`studio_shell.FloatingPanels.update_title` copies `tabs.tabText`). The three groups the README
  describes (**Browse**, **Study**, **View**) have no visible switcher in any capture. S04 was meant to show the View
  tab and instead shows search results under "Regions": while a query is in the panel, the dissection and section
  controls cannot be seen. The stale results then stay up while the student sections the body (S05), taking 384 px of
  the stage. Meanwhile the header field "Search anatomy" is empty, so there are two search boxes with different
  contents on one screen.
- **Heuristics:** H4 Consistency and standards, H1 Visibility of system status, H3 User control (no obvious way from
  results back to Browse/View except clearing the field), anti-pattern *stale context*.
- **Recommendation:**
  - Make one search entry point per scope. The header search opens results in a results surface titled "Results for
    'biceps brachii'" with a clear "Back to Browse" action.
  - Keep the panel's group switcher (Browse / Study / View) permanently visible at the top of the panel.
  - Title the panel after what it shows.
  - Clear or collapse results when the student moves to a stage tool.
- **Route:** `/organize`.

#### F4. Cross-section labels collide with the dock, and the cut face is seen edge-on
- **Where:** S05.
- **What the user experiences:** The transverse section's labels run in two columns of 11 along the bottom of the
  torso. The last row runs under the dock: "Rectus abdominis m…" is cut off on the left at x≈760 and
  "…dominis muscle" on the right. With the camera still anterior, the cut face is seen edge-on, so the
  "self-labelling cut face" shows as 22 leader lines converging on a horizontal line. There is no on-stage indication
  that a section is active, which plane it is, or at what level. The headline feature looks like clutter at the
  bottom of the screen.
- **Heuristics:** H1 Visibility of system status, H8 Aesthetic and minimalist design. The overlap is the same failure
  that WCAG 2.4.11 targets for focus (content obscured by author-created chrome).
- **Recommendation:**
  - Reserve a safe area: the label layout must treat the dock, the cards and the header as obstacles.
  - When a section is turned on, offer (or default to) a camera that faces the cut, e.g. superior view for a
    transverse plane.
  - Show a small persistent section chip on the stage ("Transverse · level 42% · Flip · ✕").
- **Route:** `/specify` (label safe-area rule), `/journey` (section entry).

#### F5. Moving between workspaces switches between a dark stage and bright full pages, and the header is the brightest thing on the 3D stage
- **Where:** S01→S06→S07→S08→S09→S12→S13, and S14.
- **What the user experiences:**
  - Explore, the lesson reader, the model viewer and radiology are dark stages.
  - The lessons library, model library and histology library are 1320 px light cards on dark.
  - The histology viewer is a near-full-screen light page with a grey matte.
  - Settings is a light dialog.

  Going Explore → Lessons → lesson reader → 3D Models goes dark → light → dark → light, each time across most of a
  1920×1080 screen. For a student working in the evening (`PRODUCT.md` Users) this is a repeated glare step.
  On every dark stage, the light header bar (≈1864×58 px of `#F8FAFB`) sits above the model as the brightest,
  highest-contrast element on screen, brighter than the skin and bone it frames (S01, S02). The owner's brief says
  the model is the focus and colours must not distract. Here the chrome out-shines the model.
- **Heuristics:** H8 Aesthetic and minimalist design, H4 Consistency (two visual worlds), owner brief, product
  principles 1 and 5.
- **Recommendation:** Pick one visual world for the whole app and apply it to libraries, readers, viewers and
  Settings. Given the brief, that is a dim neutral stage with mid-tone surfaces, or light surfaces dimmed to well
  below the model's luminance. Keep chrome luminance clearly below the model's on every 3D stage. The header should
  recede (stage-toned, not a white slab). Libraries can stay light-on-content as long as the switch is not a
  full-screen flash.
- **Route:** `/specify` (token system), `/philosopher` for the one-world decision if contested.

#### F6. The lesson reader has a narrow measure, a crowded control stack, and hides completion behind "Lesson tools"
- **Where:** S07.
- **What the user experiences:**
  - **Measure.** The reader is a 337 px card with a ≈275 px text column, about 35–40 characters per line ("Both
    coronary arteries arise from the" = 37). This is below the 45–75 range for sustained reading, so each paragraph
    becomes a tall ribbon. The "By the end you should be able to" box takes ≈260 px before the step begins, leaving
    ≈350 px of visible body text.
  - **Repeated position.** The step position is stated four times: a 7-segment progress bar, a drop-down "1. Where
    they start", "Step 1 of 7", and the heading "Where they start".
  - **Controls.** Five buttons in three stacked rows. Two filled cobalt primaries, **Show answer** and **Next ›**,
    sit in adjacent rows and compete. **Recall question** looks like an action but only scrolls to the question
    (`lessons.py`: `scrollToAnchor("recall")`). **Lesson tools** is a toggle whose tooltip says it holds "replay,
    quiz, practice and completion controls", so finishing a lesson and "Quiz me" are hidden behind a generic label.
  - **Missing context.** The lesson title "The coronary circulation" appears only inside the card. The stage has no
    title (unlike Explore and the model viewer) and no dock (unlike every other 3D stage), though it shows the same
    whole-heart model as S09.
- **Heuristics:** H8 (repetition), H6 (hidden completion), H4 (no dock, no stage title), H2 ("Recall question" is not
  what it does), anti-pattern *mystery-meat toggle*.
- **Recommendation:**
  - Widen the reading column to ≈380–440 px, or let it resize, for 50–70 characters per line.
  - Collapse objectives after step 1.
  - State the position once (segments with "1 of 7" and the step title in the picker).
  - Keep exactly one primary per state: **Show answer** while a recall question is open, otherwise **Next**.
  - Put **Finish lesson** and **Quiz me** visibly on the last step.
  - Rename "Recall question" to say what it does ("Go to question").
  - Give the stage the same dock and title as other 3D views.
- **Route:** `/journey` (reader flow), `/articulate` (labels).

#### F7. The model library is a text list with engineering copy and a weak primary action
- **Where:** S08 (copy also S09; S14 for a related leak).
- **What the user experiences:**
  - **No images.** The 41 models are a plain list of names ("Axillary Skin", "Bladder Wall", "Blood Cells"…) with no
    thumbnails, in an app whose subject is visual and whose models are its showcase. Students choose by recognising
    a picture, not by recalling a tissue-block name.
  - **Developer copy.** The overview for the first model reads: "Source-preserving axillary skin with separate
    apocrine/follicular and eccrine/surface routes, restored full context and explicit isolation views." Under Scale:
    "metres_per_unit=0.001 is a viewer display convention, not validated morphometry." These are build notes, not
    teaching copy.
  - **Weak primary.** **Open model** is a grey filled button that looks disabled.
  - **Empty space.** About 60% of the card (x 740–1600, y 500–1030) is empty.
  - **Related leak.** Settings shows the internal design-round name "Study-02 Porcelain." as an orphan line (S14).
- **Heuristics:** H2 Match with the real world, H6 Recognition rather than recall, H8 (empty space), H4 (primary action
  styling).
- **Recommendation:**
  - Show the models as a grid of rendered thumbnails. The app can render them (`tools/render_model.py`), so this
    needs no model changes.
  - Rewrite overviews in the teacher voice of the radiology notes ("What it shows / what to look for / scale in
    plain words").
  - Make **Open model** the one filled primary.
  - Remove internal names from user-facing copy.
- **Route:** `/articulate` (copy), `/organize` (library layout), `/fortify` (missing-thumbnail fallback).

#### F8. Keyboard focus is hard to tell apart from selection and from rest
- **Where:** Code (`theme.py` lines 344, 401, 434–437; `studio_style.py` lines 59–61, 87–88); visible in S01–S13
  header.
- **What the user experiences:** Focus is shown almost everywhere by changing a border to the accent colour.
  - **Header buttons.** The checked workspace button already has an accent border (`:checked`), so keyboard focus on
    an unchecked workspace looks like a second active workspace, and focus on the active one shows no change at all.
  - **Search field.** The resting border is 2 px `#82949F`, heavier than any other control, so it looks focused in
    every screenshot. Its focus state changes only the hue to `#364F99`, a ≈2.4:1 change.
  - **Checkboxes.** Focus is a 1 px outline.
  - **Legacy nav tabs.** Focus changes text colour only (`QPushButton#navTab:focus`).

  The app sells "dense keyboard shortcuts"; a student tabbing through the header cannot reliably tell where they are.
- **Heuristics:** WCAG 2.4.7 Focus Visible (met in letter, weak in practice), 2.4.13 Focus Appearance (AAA: fails the
  3:1 change and 2 px perimeter), 1.4.11 Non-text Contrast, H1.
- **Recommendation:** Use one focus ring for the whole app: a 2 px outline offset 2 px outside the control, at ≥3:1
  against both the control and its background, never the same treatment as *checked* or *selected*. Give the search
  field a normal resting border.
- **Route:** `/include`.
- *Severity note:* rated P1 because keyboard use is a stated primary input. Verify with a live Tab walk; screenshots
  cannot show focus movement.

### P2: Minor

#### F9. Search results print the type twice ("Group · Group", "Lesson · Lesson")
- **Where:** S03–S05.
- **What:** Every result's meta line starts with a doubled type: "Group · Group · 4 structures · Muscular system ·
  …", "Lesson · Lesson · Nervous · Back & spine · 5 steps". The duplication pushes the useful part (system, region,
  step count) into the ellipsis. Cause: `search_panel.py:82` prefixes `kind` to a subtitle that already begins with
  the kind. Two results are both titled "Biceps brachii muscle" ("4 structures · Muscular system" vs "2 structures ·
  Muscle attachmen…") and are told apart only by the truncated text.
- **Heuristics:** H8, H6.
- **Recommendation:** Show the type once, as a small label or icon column. Lead the meta line with the
  disambiguating fact. Give the two groups distinct titles ("Biceps brachii (muscle)", "Biceps brachii
  (attachments)").
- **Route:** `/articulate`.

#### F10. Radiology header: a badge that looks like the primary button, metadata said three times, and zoom controls said twice
- **Where:** S10, S11.
- **What:**
  - **Badge as button.** The title row reads "Chest radiograph — PA" followed by a filled cobalt **X-ray** pill,
    then outlined **Browse cases**, **Details**, **Close**. "X-ray" is a non-interactive modality badge
    (`radiology.py`: `QLabel` with `tag_css(INFO)`), but it is the most button-like element in the row and looks
    like the selected or primary action.
  - **Repeated metadata.** The line beneath repeats it: "X-ray · Thorax · PA projection · Normal anatomy". So "X-ray"
    and "PA" each appear twice in 40 px.
  - **One-tab tab bar.** The image area has a tab bar with one tab, "Scan".
  - **"Fit" twice.** The zoom row has **−**, the readout "Fit", **+**, then a button "Fit scan".
  - **Unclear scope.** **Previous** / **Next** at the bottom do not say whether they step through labels or cases.
- **Heuristics:** H4, H8, 1.4.11 (a badge must not share the button affordance).
- **Recommendation:**
  - Style badges as quiet text tags, never as filled buttons.
  - Keep one metadata line.
  - Drop the single tab.
  - Label the readout as a percentage and keep one "Fit" control.
  - Make the stepping explicit: "‹ Previous case", "Next case ›".
- **Route:** `/articulate`, `/specify`.

#### F11. The model viewer offers the same actions two or three times
- **Where:** S09.
- **What:**
  - **Repeated selection controls.** "6 parts selected" appears in the parts card and again as a 840×100 px navy card
    over the centre of the stage ("6 parts selected · Isolate these structures or open their details."). **Isolate**
    appears in both. **Show all** appears in the parts card and the dock. **Reset** appears in the Reveal card and
    the dock, and they reset different things.
  - **Selection card covers the subject.** It sits directly over the course of the right coronary artery, the
    structure just selected.
  - **Unlabelled Reveal controls.** The Reveal card has an unlabelled drop-down "Right edge" and two sliders ("Tissue
    opacity", "Separate layers") with no values.
- **Heuristics:** H4, H8, H6, H1.
- **Recommendation:** One selection component (shared with Explore, F1), placed where it never covers the stage
  centre. Each action appears once per screen. Name the scope of each reset ("Reset view", "Reset reveal"). Label the
  cut-away drop-down ("Cut-away corner: right edge") and show slider values.
- **Route:** `/organize`, `/articulate`.

#### F12. The Radiology tab opens straight into a case; the case library is not a landing page
- **Where:** S10 = S11 (identical captures).
- **What:** Choosing **Radiology** shows the chest PA case, not the 104 cases. The library sits behind a secondary
  outlined **Browse cases** button in the case header. The other library workspaces (Lessons, 3D Models, Histology)
  land on their library, so the student cannot predict whether a workspace tab opens a list or an item.
- **Heuristics:** H4, H3, H6.
- **Recommendation:** Every workspace tab lands on the same kind of thing: either always the library (with "Continue:
  Chest radiograph — PA" at the top), or always the last item with a visible, consistent "All cases" breadcrumb.
- **Route:** `/organize`, `/journey`.

#### F13. Docks, close controls and button hierarchy differ between workspaces
- **Where:** S01, S07, S09, S11, S13.
- **What:**
  - **Docks:**
    - Explore (S01) and radiology (S11): bordered text buttons **Measure · Show all · Reset · More tools**.
    - Model viewer (S09): borderless icon + label **Measure · Labels · Show all · Reset · More tools**.
    - Lesson reader (S07): no dock, though it is the same 3D model.
    - Histology viewer: no dock; its zoom controls are a toolbar at the top instead.
  - **Close controls:** "Close" text button (Explore panel), "×" (Reveal card), outlined "Close" (radiology), "‹ Lesson
    overview" (reader), "Close" (Settings).
  - **Primary actions** take at least four looks:
    - filled cobalt ("Show answer", "Next ›");
    - light-blue fill on a navy card ("Isolate");
    - grey fill ("Open model", "Lesson tools", "My progress", "Reset", "More controls", "Related lessons (40)");
    - outlined ("Browse cases").
- **Heuristics:** H4.
- **Recommendation:**
  - One dock component with the same order and treatment on every 3D stage. Context-specific tools are added at a
    fixed end.
  - One close affordance.
  - A three-level button hierarchy (primary filled, secondary outlined, tertiary text), with exactly one primary per
    surface.
- **Route:** `/specify`.

#### F14. Selected list rows are shown by a 1.2:1 fill alone
- **Where:** S03 ("Biceps brachii muscle" row), S08 ("Axillary Skin" row).
- **What:** The selected row's only cue is the `#DCE6F7` fill on `#F8FAFB`, about 1.2:1. On a dim or glossy laptop
  screen the current row is hard to find, which matters because Enter opens it ("Enter to open").
- **Heuristics:** WCAG 1.4.11 Non-text Contrast (state indicator), 1.4.1 Use of Colour.
- **Recommendation:** Add a non-colour cue that reaches 3:1, such as a 3 px leading bar in the accent or a bold title
  plus a border, and keep it distinct from the focus ring (F8).
- **Route:** `/include`.

#### F15. Histology library: no title, unlabelled numbers, counts that disagree, an orphan "Clear"
- **Where:** S12.
- **What:**
  - **No heading.** The lessons library has a heading ("Learn & recall") and the model library has one ("3D
    models"); the histology page starts with "100 tissues · 991 images".
  - **Counts disagree.** Below that, "101 topics shown". The README and `PRODUCT.md` say 101 tissues and 1,049
    micrographs. The right-aligned numbers per group (Epithelium 65, Digestive system 162, …) have no label and add
    up to 1,071, matching neither figure.
  - **Orphan control.** A lone **Clear** button sits on its own row under an empty search field.
  - **No previews.** There are no thumbnails.
  - **Empty space.** The lower 35% of the card is empty.
- **Heuristics:** H4, H2, H8, H1.
- **Recommendation:**
  - Add the page heading.
  - Use one count definition, shown once ("101 tissues · 1,049 images").
  - Label the per-group number ("65 images").
  - Put Clear inside the search field.
  - Show a representative micrograph per tissue.
- **Route:** `/articulate`, `/fortify` (count consistency).

#### F16. Histology viewer repeats its title three times and "Fit" twice; "No 3D link" is a disabled button used as information
- **Where:** S13.
- **What:**
  - **Title three times.** "Simple columnar epithelium" (card title), then a full-width drop-down "Simple columnar
    epithelium around a large central lumen", then the caption heading "Simple columnar epithelium around a large
    central lumen".
  - **Zoom row.** **Fit · 100% · − · Fit · +**, where the second "Fit" is the zoom readout (`histology.py`:
    `zoom_label`).
  - **Disabled button as status.** "No 3D link" is a disabled-looking button (≈2.3:1 grey on grey) used to state a
    fact.
  - **Different frame.** The page is edge to edge (x 12–1908) while the histology library above it is a 1320 px
    card, another frame change on one tab.
- **Heuristics:** H8, H4, H1.
- **Recommendation:** Title once, picker for the image, caption without repeating the heading. One fit control and a
  numeric readout. When a tissue has no 3D link, omit the button or say so in the caption. Same frame as the
  library.
- **Route:** `/articulate`, `/specify`.

#### F17. The header is dense and hides the classic menus behind a gear
- **Where:** S01–S13.
- **What:**
  - **Crowded history control.** Back carries a split drop-down chevron squeezed into a 46 px button next to
    Forward. The disabled Forward state (S01) is barely different from enabled Back.
  - **Unbalanced spacing.** The five workspace buttons sit 40–60 px apart, while search, Saved views and the gear are
    pushed right.
  - **Gear as menu bar.** The gear holds Settings, open workspaces, "Find a command…", File, Selection, View, Tools,
    Study, Help and Updates, i.e. the whole menu bar behind one unlabelled icon with the tooltip "Settings and
    application commands".
  - **Saved views over-weighted.** Saved views, a tertiary feature, gets the same header weight as search.
- **Heuristics:** H6, H8, anti-pattern *mystery-meat container*.
- **Recommendation:**
  - Group the header into three zones: identity + history | workspaces | search + one "Menu" control with a text
    label.
  - Show "Find a command… (Ctrl+K-style shortcut)" as a visible entry in the search field rather than buried in the
    gear.
  - Move Saved views into the stage (it saves a stage state).
  - Make the disabled history state clearly disabled.
- **Route:** `/organize`.

#### F18. The stage title says "3D Anatomy" while the tab says "Explore"
- **Where:** S01–S05 (and S09 "Heart").
- **What:** The largest text in Explore is a 48 px "3D Anatomy" that never changes, whatever is selected, sectioned
  or filtered. The workspace is called **Explore** in the header and README, and "3D Anatomy" again in the gear's
  workspace list (`main_window.py:172, 844`). In the model viewer the same slot holds the model's name, which is
  useful. Related naming drift: "Lessons" (tab) / "Learn & recall" (page title) / "Learn" (panel title); "Parts"
  (More tools) / "Tree" (README) / "Anatomy tree" (panel title); "3D Models" (tab) / "3D models" (page).
- **Heuristics:** H4, H8.
- **Recommendation:** One name per thing, used everywhere. Use the stage-title slot for live context (the selection,
  or the active preset such as "Muscles · anterior"), not a static label.
- **Route:** `/articulate`, `/organize`.

#### F19. The lessons library: progress before topic, a 1250 px drop-down for one word, stranded actions
- **Where:** S06.
- **What:**
  - **Progress first.** Each lab row reads "Lab 1 · 0/9 finished · Nerve physiology, reflexes & general senses". The
    progress comes before the topic and the word "finished" is repeated eleven times, so the eye has to skip it to
    scan topics.
  - **Naming drift.** "Practical 1 · Labs 1–5" is "Lab Practical 1" in the README.
  - **Over-wide filter.** The "All progress" filter is a full-width (≈1250 px) drop-down for a one- or two-word
    value.
  - **Stranded actions.** **My progress** and **My notes** are grey buttons stranded at the bottom-left, under ≈140 px
    of empty card.
  - **No first-run starting point.** With nothing started, there is no "Start here" or suggested first lesson; the
    page is eleven collapsed rows.
- **Heuristics:** H8, H4, H6; `/fortify` first-run state.
- **Recommendation:**
  - Lead with the topic, then progress as a compact meter ("Nerve physiology, reflexes & general senses · 0 of 9").
  - Size the filter to its content and place it beside the chips.
  - Move My progress / My notes to the page header.
  - Give the empty state a first suggested lesson.
- **Route:** `/articulate`, `/fortify`.

#### F20. Teaching blocks intrude, cut off, at the edge of the frame
- **Where:** S07, S09.
- **What:** The whole-heart model's enlarged "wall and atrial teaching blocks" (named in its description) sit as a
  large translucent cuboid on the right of the stage, cut off by the window edge (x≈1470–1920). It competes with the
  heart and is not mentioned by the lesson step. *This is about default framing and visibility, not geometry:* models
  are off limits.
- **Heuristics:** H8.
- **Recommendation:** Lesson steps and the model's default view should frame the subject and hide teaching blocks
  unless the step uses them, through the existing step view set-up and part visibility.
- **Route:** `/journey` (lesson view set-up), content authors.

#### F21. The model description panel opens with long technical paragraphs above the parts
- **Where:** S09.
- **What:** Before the parts filter, the card shows two paragraphs, the second at ≈12 px grey: "Gross heart and
  conduction system: 1 unit = 1 cm… Internodal paths represent preferential atrial muscle routes, not insulated
  tracts." The parts tree, the panel's working content, starts at y≈450 and gets six visible rows before scrolling.
- **Heuristics:** H8, H2.
- **Recommendation:** One-sentence summary with "About this model" disclosure for scale notes. Give the parts tree the
  height.
- **Route:** `/articulate`.

#### F22. Radiology 3D leader lines cross, and label order follows the number, not position
- **Where:** S11.
- **What:** On the model, the left label column reads 2, 4, 5, 3, 18, 7, 16, 11, 14, 12. Lines from "18 Thoracic
  spine" and "5 Superior vena cava" cross others to reach the midline. In a dense chest view the crossings make it
  slower to follow a line to its structure.
- **Heuristics:** H8.
- **Recommendation:** Order labels within a column by anchor height to remove crossings, and keep the number as the
  link to the film.
- **Route:** `/specify`.

### P3: Polish

#### F23. Settings: an orphan line without a label, and a setting that depends on another with no sign of it
- **Where:** S14.
- **What:** Under "Interface", an indented line with no label: "Study-02 Porcelain. Educational images and model
  materials keep their original colours." (the theme picker is hidden, `settings_dialog.py:243`). "Show rendering
  time in status bar" is ticked while "Show bottom status bar" is not, with no indication that the first has no
  effect. Settings is also a separate light dialog (F5).
- **Recommendation:** Remove the orphan or turn it into a plain note ("Images and models keep their original
  colours"). Indent and disable dependent options.
- **Route:** `/articulate`.

#### F24. Small grey caption text carries required information
- **Where:** S11, S13.
- **What:** The radiology disclaimer ("The atlas illustrates related anatomy. It is not registered to this image…")
  and the licence line are ≈11 px. The muted token passes AA (≈5.8:1), but the `FAINT` token (`#76858E` on
  `#F8FAFB`, ≈3.6:1) fails 1.4.3 for any small text that uses it. Licences must stay visible (`PRODUCT.md`).
- **Recommendation:** Captions at least 12 px at scale 1.0, never in `FAINT`. Keep them adjacent to the image.
- **Route:** `/include`.

#### F25. Button and card borders are below 3:1
- **Where:** S01, S06, S08.
- **What:** Outlined buttons use `#8798A3` on `#F8FAFB` (≈2.9:1), and card dividers use `#C2CFD5` (≈1.5:1).
  Outlined buttons inside the dock rely on that border as their only boundary.
- **Recommendation:** Borders that define a control's hit area at ≥3:1. Decorative dividers may stay faint.
- **Route:** `/include`.

#### F26. Title case leaks into model names
- **Where:** S08, S09.
- **What:** "Axillary Skin", "Female Reproductive System", "Ileocecal Region and Rectum" in a sentence-case UI.
- **Recommendation:** Sentence case for model names.
- **Route:** `/articulate`.

#### F27. Hover and selection may be hard to tell apart, since both use an outline (not verified)
- **Where:** S02, S09; Settings S14 "Outline structure under the cursor".
- **What:** Hover and selection both use outlines. Whether the student can tell "under the cursor" from "selected"
  could not be verified from stills.
- **Recommendation:** Hover and selection must differ in more than intensity, e.g. a thin hover outline vs a thick
  selection outline plus the selection name (F1). Verify live.
- **Route:** `/include`.

#### F28. Colours are hard-coded in the shell, bypassing tokens
- **Where:** Code: `studio_shell.py:245–249` (`#f8fafb`, `#94a6b1`, `#24343d`), `studio_style.py:8` (`#141b22`), and
  dock/subject colours in `build_stylesheet`.
- **What:** A redesign that changes tokens will leave these surfaces behind, which is how a second visual world
  appears.
- **Recommendation:** Every surface colour from one token set. Delete the unused dark set or make it real.
- **Route:** `/specify`.

---

## Heuristic verdicts

| Heuristic | Verdict | Deciding finding |
|---|---|---|
| H1 Visibility of system status | **Broken** | F1: selection names nothing. Also F4 (no section indicator). |
| H2 Match with the real world | **Broken** | F7: "metres_per_unit=0.001 is a viewer display convention, not validated morphometry." |
| H3 User control and freedom | **Strained** | F3 (no path from results back to Browse/View), F12. Undo, Esc and Show all are good. |
| H4 Consistency and standards | **Broken** | F3, F5, F13: panel title vs content, two visual worlds, four button styles, three docks. |
| H5 Error prevention | **Holds** | No destructive actions seen; "Reset this page" in Settings is scoped. |
| H6 Recognition rather than recall | **Broken** | F2: core layer tools hidden behind "More tools". F7: no thumbnails. |
| H7 Flexibility and efficiency | **Holds** (P3 only) | Rich, rebindable shortcuts, keyboard hints and Back/Forward history. The gap is the visible path for novices (F2), counted under H6. |
| H8 Aesthetic and minimalist design | **Broken** | F5 (header brighter than the model), F6 (step position stated four times). |
| H9 Recognise and recover from errors | **Not assessed** | No error states captured. |
| H10 Help and documentation | **Strained** | Inline hints are good. The gear holds Help but the visible header offers none (F17). |

---

## Cognitive walkthroughs

Ratings per step: **Pass** (four yes), **Hesitation** (one no), **Failure** (two or more no). Q1 motivation, Q2
visibility, Q3 understanding, Q4 feedback.

### Task A: "Find the biceps brachii and read its nerve supply"
| Step | Q1 | Q2 | Q3 | Q4 | Rating |
|---|---|---|---|---|---|
| Type in "Search anatomy", press Enter | Yes | Yes | Yes | Yes: highlighted, framed, x-ray | Pass |
| Confirm what is selected | Yes | **No**: no name anywhere (S02) | n/a | **No** | **Failure** |
| Open Details to read innervation | Yes | **No**: card closed, path is More tools → Details | Hesitant: "More tools" doesn't suggest facts | Yes | **Failure** |

The student's story breaks at step 2. They can see the muscle but cannot confirm what it is, which is the exact skill
a practical exam tests.

### Task B: "Peel the body down to the deep muscles"
| Step | Q1 | Q2 | Q3 | Q4 | Rating |
|---|---|---|---|---|---|
| Look for a dissection control | Yes | **No**: not on dock (S01) | n/a | n/a | Failure |
| Open More tools → "Reveal controls" | Yes | Hidden in a menu | **No**: "Reveal" ≠ "dissect" | Yes | **Failure** |
| Drag the dissection slider | Yes | Yes (once open) | Yes | Yes | Pass (not captured) |

### Task C: "Take a transverse section and read what it cuts"
| Step | Q1 | Q2 | Q3 | Q4 | Rating |
|---|---|---|---|---|---|
| Find cross-sections | Yes | **No** on stage (More tools / View tab / keys) | Yes | n/a | Hesitation |
| Read the cut-face labels | Yes | Partly: labels at bottom, last row under dock (S05) | **No**: face is edge-on | **No**: no section indicator | **Failure** |

### Task D: "Work through one lesson step and finish the lesson"
| Step | Q1 | Q2 | Q3 | Q4 | Rating |
|---|---|---|---|---|---|
| Open a lesson from the library | Yes | Yes (S06, rows expand) | Yes | Yes | Pass |
| Read the step and answer the recall question | Yes | Yes | **No**: "Recall question" vs "Show answer", two primaries | Yes | Hesitation |
| Move on | Yes | Yes: "Next ›" | Yes | Yes: progress segment | Pass |
| Finish the lesson / quiz on it | Yes | **No**: inside "Lesson tools" | **No**: label does not say so | n/a | **Failure** |

---

## 3. Cross-workspace consistency map

| Workspace (screens) | Visual world | Header | Stage / page title | Left panel | Other floating UI | Primary action and its style | Dock | Close / back | Search field |
|---|---|---|---|---|---|---|---|---|---|
| **Explore** (S01–S05) | Dark stage, light cards | Shared light bar | "3D Anatomy", 48 px display, static | Explore card titled after a hidden tab ("Systems", "Regions"); shows search results | None (Details hidden) | None visible; dock buttons all equal weight | Bordered text: Measure · Show all · Reset · More tools | "Close" text | Header "Search anatomy" + panel field (two) |
| **Lessons library** (S06) | Light 1320 px card on dark | Shared | "Learn & recall", 20 px bold | None | None | None (rows expand); grey My progress / My notes at bottom | None | n/a | "Search lessons, objectives or topics" + header |
| **Lesson reader** (S07) | Dark stage, light card | Shared | None on stage; "The coronary circulation" inside card | Reader card (337 px) | None | Two filled cobalt: Show answer, Next › | **None** | "‹ Lesson overview" link | Header only |
| **Model library** (S08) | Light 1320 px card on dark | Shared | "3D models", 18 px bold | List inside card | None | **Grey** "Open model" | None | n/a | "Find a model or linked structure…" + header |
| **Model viewer** (S09) | Dark stage, light cards + navy card | Shared | "Heart", 48 px display, live | Description + parts tree card | Reveal card (right); navy selection card (centre-bottom) | Light-blue filled "Isolate" on navy card; grey Isolate/Hide/Show all in panel | **Borderless icon+label**: Measure · Labels · Show all · Reset · More tools | "×" (Reveal) | "Filter parts or groups…" + header |
| **Radiology case** (S10, S11) | Light half-page (790 px) beside dark 3D pane | Shared | "Chest radiograph — PA", 18 px bold, in card | Film + notes card | None | **Filled cobalt "X-ray" is a badge**, not an action; buttons outlined | Bordered text (as Explore), centred in 3D pane | Outlined "Close" | Header only |
| **Histology library** (S12) | Light 1320 px card on dark | Shared | **None** | None | None | None; orphan "Clear" | None | n/a | "Search tissues, images or features…" + header |
| **Histology viewer** (S13) | Light near-full-bleed page, grey matte | Shared | "Simple columnar epithelium", plus twice more | None | None | None; "Browse tissues", "Details", "Source" outlined | **None**; zoom toolbar at top | "Browse tissues" | Header only |
| **Settings** (S14) | Light modal dialog | Covered by dialog | "Settings", 20 px bold | Tabs: Mouse & Camera · Display · Behavior · Keyboard | n/a | "Close" outlined (grey) | n/a | "Close" | None |

**Summary of the map:**

- Each column has at least three variants.
- The header is the one constant, and it is the element the brief most wants to recede (F5).
- Primary actions are filled cobalt in one place, grey in another, a badge in a third, and absent in four.
- Docks come in three forms, and two 3D stages have none.

---

## 4. Ten principles the redesign must follow

1. **The model is the brightest, largest thing on every 3D screen.** All chrome, including the header, stays clearly
   below the model's luminance and saturation. Colour in the interface is reserved for state (selection, focus,
   progress), never decoration. *(F5; owner brief; product principle 1)*
2. **One visual world across the app.** Libraries, readers, image viewers, the 3D stage and Settings share one stage
   tone, one surface treatment and one frame width logic. Changing workspace never flashes the screen from dark to
   bright. *(F5, F16, F23)*
3. **The selection always names itself on the stage.** One shared selection component in Explore, the model viewer,
   lessons and radiology shows the name and the four actions (Details, Isolate, Hide, X-ray), and never covers the
   structure it names. *(F1, F11)*
4. **Layers are visible, not hidden.** Dissect, Section, X-ray/Reveal and Isolate sit on the stage in one dock
   component that is identical in every 3D context. A first-time student can peel and cut the body without opening a
   menu. *(F2, F13, Task B)*
5. **Say what it is, once, with one name.** A panel's title describes its content. Each feature has one name used in
   the dock, menu, panel and docs. Metadata, step position and titles appear once per screen. *(F3, F6, F9, F10, F16,
   F18)*
6. **Chrome never covers anatomy or its labels.** Docks, cards and the header are obstacles for the label layout. A
   cut face is shown face-on with a visible indicator of plane and level. *(F4, F11, F20)*
7. **One primary action per surface, and a strict button hierarchy.** Filled means primary and nothing else is
   filled. Badges never look like buttons. Disabled looks disabled, and nothing that works looks disabled. *(F7, F10,
   F13, F16)*
8. **Libraries show the thing in the student's language.** Models, tissues and cases are chosen by picture, with
   descriptions written in the teacher voice of the radiology notes. Counts are labelled and agree with each other
   and with the README. *(F7, F15, F19, F21)*
9. **Reading surfaces are built for reading.** Lesson text runs at 50–70 characters per line. Objectives collapse
   after they are read. Finishing a lesson and quizzing on it are visible actions on the last step, not inside a
   generic toggle. *(F6, Task D)*
10. **Focus, selection and state are visible without colour alone.** One 2 px offset focus ring at ≥3:1, distinct
    from checked and selected. Selected rows and controls meet 3:1 non-text contrast. Small text never drops below
    4.5:1. *(F8, F14, F24, F25)*

---

## Recommended actions, by owning skill

- **`/organize`** for F2, F3, F12, F17, F18 (with `/journey`). This is the largest cluster: where tools, results and
  libraries live, and what each is called. Start with the shared dock and the panel's group switcher, since F1–F4
  all depend on them.
- **`/journey`** for F1 (selection flow), F4 (section entry and camera), F6 (lesson reader states), F12 (workspace
  landing), F20 (lesson view framing).
- **`/articulate`** for F7, F9, F10, F15, F16, F18, F19, F21, F23, F26. Most are quick copy fixes. F9 is a one-line
  code fix (`search_panel.py:82`).
- **`/include`** for F8, F14, F24, F25, F27. Verify F8 and F27 with a live keyboard and hover pass before redesign.
- **`/specify`** for F4 (label safe area), F13 (dock, close and button components), F22, F28 (single token set). This
  is the hand-off that keeps the redesign from growing a second visual world again.
- **`/fortify`** for F7 (thumbnail fallback), F15 (count consistency), F19 (first-run lessons state).
- **`/investigate`** follow-up: a five-student test of Tasks A–D on the current build would confirm the four
  walkthrough failures before and after the redesign.

**Suggested order:**

1. F5 and F2/F13: decide the one visual world and the shared dock.
2. F1/F11: the shared selection component.
3. F3: the panel and search model.
4. F6: the lesson reader.
5. F7: the libraries.
6. Copy and accessibility fixes alongside.
