# States: what to carry into `app/specimen/index.html`

This adds three states of existing screens (critique section 3, items 5, 6 and 7):

- search as a catalogue drawer on the atlas;
- lesson text that points at the model;
- practice feedback in the model.

Each state can be rendered with `?state=`:

| `?state=` | Screen | What it shows |
|---|---|---|
| `search_open` | atlas | The drawer with "biceps" typed, keyboard focus on the first result |
| `search_empty` | atlas | The drawer with "bycep" typed, which finds nothing in the real index |
| `lesson_hover_term` | lesson | The term "anterior interventricular branch" hovered |
| `lesson_hover_label` | lesson | The label "Circumflex artery" hovered |
| `lesson_hover_dot` | lesson | Step dot 3 hovered |
| `practice_wrong` | practice | A wrong click on serratus anterior. This is also the practice screen with no `?state=`. |
| `practice_right` | practice | The right answer |

Hover also works live. On the atlas, Ctrl K or a click on the search line opens the drawer, ↑ and ↓ move the focus, and
Esc closes it. On the lesson, the dock's Labels button turns the labels off, and the brass hairlines go with them.

Renders are in `renders/checkpoint-2/states/`.

## 1. CSS

Copy the block that begins `/* ===... STATES (checkpoint 2)` at the end of this file's `<style>` to the end of the
original's `<style>`. It is self-contained and uses only the scheme tokens and the existing classes (`.label-card`,
`.colhead`, `.meta`, `.keys`, `.dots`, `.lbl`, `svg.leaders`). Nothing above it was changed.

## 2. Markup

All of these changes are in this file. Diff it against `app/specimen/index.html` to see them.

**Atlas.** Two `<div class="label-card drawer" data-drawer data-show="…" hidden>` blocks follow the atlas
`<header class="head" data-chrome="atlas">`: the results and the empty state. The drawer uses `.label-card`, so it
follows `?panel=wall|plaque|frame`. In every treatment it is opaque (`--sunken`), because it hangs over the model, and
its top edge is a 1 px `--text` line: the lit search line, carried across. JS sets its `left` to the search line's left
edge. Its right edge is 40 px from the window's edge.

**Lesson.**
- `.app` gets `data-labels="on"`.
- The two bold terms that are also labels get `class="term" data-for="lad"` and `data-for="lcx"`. The keys are the
  label anchors in `heart_lesson_*.anchors.json`.
- "anterior two thirds of the interventricular septum" stays plain bold, because it has no label.
- The step dots become `<div class="dots steps">`.
- The step line gets `data-step-line` and `white-space:nowrap`. The longest step title runs to about x = 800, over
  empty wall.

**Practice.**
- The plate's mask also fades the bottom (`#000 950px, transparent 1048px`), as it already fades the neck. The 12 ticks
  then sit on the wall at the lower edge, not on the abdomen.
- Labels for both moments are marked with `data-show`:
  - the miss is `serratus.vr`, moved out onto the wall (`data-dx="300" data-dy="70"`);
  - the hit is `ext_ic.vl` (`data-dx="-380" data-dy="40"`).
- The card holds the wrong feedback and the right feedback ("**Yes,** the external intercostal muscles."). The right
  feedback has `min-height:96px`, so the card does not jump.
- The right column "This session / 3 of 12" is replaced by a **Mode** list (Find it in 3D current; Hunt with its
  subtitle; the two Name it modes), a rule and "Labels stay off while you practise."
- A new `<div class="ticks">` holds 12 `.dots` ticks and "Question 4 of 12 · 3 right".
- " · question 4 of 12" is removed from the title caption, because the ticks now say it.

## 3. JS

Copy `states.js` into `app/specimen/` and load it after the inline script and before `plates.js`/`mock.js`, as here.

- Before `mock.js` runs, it reads `?state=`, sets the screen and removes the `.lbl[data-show]` labels the moment does
  not use.
- After `data-ready`, it pairs each label with its leader and anchor (in `mock.js` drawing order) and adds a brass halo
  to each lesson anchor and the rings to the practice anchors. It then wires the hovers and keys and sets
  `data-states="1"`.

When merging, keep the `data-show` logic, or hard-code one moment per screen.

No new image assets. No change to `mock.js`, `plates.js` or the schemes.

## 4. What the Qt app needs

### Search drawer
- **Data:** none new. `app/search.py` already indexes:
  - structures, groups and landmarks with their Latin (`alt`, lines 61, 66–67, 76–77);
  - lessons (131);
  - radiology cases (153);
  - clinical notes and histology tissues (112, 116);
  - 3D models (120).
- **Grouping:** Structures = structure, group, landmark. Lessons = lesson. Cases = radiology and clinical. Tissues =
  tissue. Models (`micro`) has no group in the critique. Add a fifth group, "Models", shown only when it has hits.
- **F9 fix:** `search_panel.py:82` prefixes the kind to a subtitle that already starts with it
  (`group` subtitles are built as `"Group · …"` at `search.py:66`, lessons as `"Lesson · …"` at 131). Show the kind
  once, as the group head, and lead the meta line with the system:
  - group: `"{system name} · {n} parts"`;
  - structure: `"{system} · {subsystem}"`;
  - attachment: `"Muscle attachments · on the {base, lower case}"`.
  - The two "Biceps brachii muscle" groups are then told apart at once: "Muscular system · 4 parts" and "Muscle
    attachments · 2 parts".
- **Data dash:** " — " in titles ("Biceps brachii muscle — insertion") is shown as ", ".
- **Widget:** a frameless drop-down under the search line, the full width from the line to the right margin, on
  `SUNKEN`, with a 1 px `TEXT` top edge.
  - Rows are drawn by the delegate: name in Literata 19, Latin in Literata italic 16 (`TEXT_2`), meta in Fira 13.
  - The focus ring is 2 px `TEXT_2`, not brass, because brass means "current".
  - The focused row shows an "Enter" key cap.
  - ↑, ↓ and Esc already exist (`SearchLine`, `search_panel.py:94–98`).
- **Empty state:** copy from the brand brief (`research/brand-and-site-brief.md:240`).
- **Enter = "Isolate and label"** is new behaviour. Today activation selects the result.
  - It is **not rendered**: the plates in `assets/plates/` have no isolated biceps, and cutting the biceps pixels out
    of `hero26_sel_*` would leave out the parts hidden under the deltoid and pectoralis major. That would be a
    dishonest isolate.
  - The render it needs: the atlas camera of `hero26_sel_*` with Isolate on the group "Biceps brachii muscle" (both
    sides), on black and on white for the matte, in each scheme's selection colour, plus picking-buffer anchors
    (`tools/capture`, then `process_plates.py`).

### Lesson terms
- **Data:**
  - The step's `focus`/`show` names (`lessons_cardio_heart.json`, the lesson at line 191) are the labels.
  - The step text's `<b>` terms do not name them exactly: "anterior interventricular branch" is the label "Anterior
    interventricular artery", and "circumflex branch" is "Circumflex artery of heart".
  - So the app needs a term-to-structure map: either a `data-for`-style attribute in the step HTML (`<b
    for="Anterior interventricular artery">`), or a resolver that matches bold text against the step's names through
    `lessons.Resolver` and the search synonyms. The explicit attribute is safer. This is an authoring task for the
    lesson files.
- **Widget:** the lesson text is a rich-text view. Underline the mapped terms with a 1 px `ACCENT` line (70 %) while
  labels are on. On hover, tell the label placer to raise that label (full `TEXT`, 1.5 px `TEXT` leader, brass halo at
  its anchor) and lower the others (`MUTED`, leader at 30 %). On label hover, back-highlight the term with
  `ACCENT_SOFT`.
- **Step dots:** each takes hover. The step line beside them shows "Step n of 7 · *{step title}*" in Literata italic,
  the same pattern as the gauge stops. Step titles come from the lesson JSON.

### Practice
- **Marks:** a 1.5 px ring (r 11) and a leader at the structure's label anchor, in `TEXT_2` for the clicked mistake and
  `ACCENT` for the right answer. Plus the name at the leader's end.
- **Tint:** the critique asked for a neutral tint of the clicked structure. The plates have no per-structure ID image
  for `thorax_chest`, so the mockup uses only the ring at a real anchor. In Qt, the selection pass can tint honestly:
  - `quiz.py` already flashes the wrong pick red for 900 ms (`_flash_structures`, line 926) and shows the answer in
    green;
  - change both to the scheme's neutral (`TEXT_2`-ish) and `ACCENT`;
  - keep the wrong pick's name on the wall until the next click, instead of the 900 ms flash.
- **Timing:** today a right answer advances after 1.6 s (`quiz.py:896`). The critique asks for two seconds: use
  `_advance.start(2000)`.
- **Hunt:** must never name the wrong pick (`quiz.py:915`, brand brief line 237). In Hunt, draw the neutral ring and no
  name.
- **Ticks:** 12 `.dots`-style ticks.
  - The colours used: right is brass at 55 %, current is brass, upcoming is `HAIR`.
  - A missed question would use `MUTED`. No miss appears in these renders.
  - The session length comes from the session builder (`lessons.build_session`).
- **Modes:** the four modes are `quiz.py:31` `MODES`, with Hunt's subtitle "Find one structure. Nothing is labelled."
  from the brand brief (line 284). Dashes in the app's mode names become commas here.
