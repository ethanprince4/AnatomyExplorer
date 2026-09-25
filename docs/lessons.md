# Guided lessons

A lesson is a short scripted walk through one topic. Each step writes a paragraph or two, sets the 3D view up
to match it, and can ask a question before you move on. Ctrl+L, or **Lessons** (or **Lab course**) on the
Explore panel's **Study** tab.

There are **246 lessons, 1,278 steps and 1,189 recall questions**: 137 guided lessons (810 steps, 721 recall
questions) and 109 lab-course mini lessons and reviews (468 steps, 468 recall questions, 1,900 practice items; see
[The lab course](#the-lab-course)). They are filed under twelve body systems and eight regions. The browser groups
them four ways — **Course**, **System**, **Region** or **Level** — and remembers how far through each one you got.
`tools/check_lessons.py` prints the current totals.

| System | Lessons | | Region | Lessons |
|---|---|---|---|---|
| Cardiovascular | 57 | | Head & neck | 59 |
| Nervous | 35 | | Thorax | 50 |
| Digestive | 30 | | Whole body | 40 |
| Muscular | 26 | | Abdomen | 35 |
| Respiratory | 23 | | Pelvis & perineum | 21 |
| Special senses | 19 | | Upper limb | 17 |
| Reproductive | 16 | | Lower limb | 17 |
| Skeletal | 16 | | Back & spine | 7 |
| Lymphatic & immune | 8 | | | |
| Urinary | 7 | | | |
| Endocrine | 5 | | | |
| Skin & fascia | 4 | | | |

Levels are **Foundation** (22), **Core** (183) and **Advanced** (41). Advanced lessons usually name a
`prereq`, which the runner shows under the title as "After: …".

## The lab course

Lessons written for the lab course (`data/content/lessons_course_lab01.json` … `lessons_course_lab09.json`,
`lessons_course_exam1.json`, `lessons_course_exam2.json`) are bite-sized *mini lessons*, and the library opens
on them: the **Course** grouping (the default whenever course lessons exist) lists **Lab 1 … Lab 9, Lab
Practical 1, Lab Practical 2** in that order, each heading showing how many of its mini lessons you have
finished (`LAB 3  4/10 ✓ · BLOOD & HEART STRUCTURE`), and the mini lessons under it in course order with a ✓
once read and their best practice score. Every other lesson follows underneath by body system; **System**,
**Region** and **Level** group the whole library as before.

| Unit | Mini lessons | | Unit | Mini lessons |
|---|---|---|---|---|
| Lab 1 · Nerve physiology, reflexes & general senses | 9 | | Lab 6 · Respiratory structure & ventilation | 9 |
| Lab 2 · Eye, ear, hearing & balance | 11 | | Lab 7 · Exercise physiology & pulmonary health | 5 |
| Lab 3 · Blood & heart structure | 10 | | Lab 8 · Digestive & urinary anatomy | 16 |
| Lab 4 · ECG & heart function | 8 | | Lab 9 · Reproductive systems & early development | 12 |
| Lab 5 · Blood vessels & circulation | 13 | | Lab Practical 2 · Labs 6–9 | 7 |
| Lab Practical 1 · Labs 1–5 | 9 | | | |

Each lab practical is a set of review lessons ending in a practice exam with no steps. The 1,900 practice items
are 601 `find`, 439 `find_micro`, 319 `mcq`, 264 `recall`, 180 `name` and 97 `order`.

Clicking a course lesson opens its **cover**: the objectives, how far you got, your practice scores and two
buttons:

- **Learn** — the step-by-step runner below. Finishing the last step brings you back to the cover, ready to
  practise.
- **Practice** — a short graded session in a dock on the right (see [Practice mode](#practice-mode)). The runner
  also has a **Practice** button next to **Quiz me** for any lesson with something to practise.

A lab-practical review lesson with `practice_from` shows **Practice exam** instead, with a **Length** selector
(20, 40 — the default — 60, or everything). A lesson with no steps (a pure practice exam) shows only Practice.

### Course fields

```json
{
  "id": "lab03-02-formed-elements",
  "course": {"lab": 3, "order": 2, "unit": "Lab 3 · Blood & heart structure"},
  "practice": [ … ],
  "steps": [ … ]
}
```

- `course.lab` (or `course.exam` for a lab-practical review) and `course.order` place the lesson; `course.unit`
  is the heading its lab is filed under (the first lesson of a unit that has one names the heading).
  Lab-practical units read `"Lab Practical 1 · Labs 1–5"`.
- Ids are `labNN-MM-slug` (`exam1-MM-slug` for reviews), and the `NN` must match `course.lab`.
- A mini lesson has 3–5 steps of 40–90 words each, one idea per step, and 6–15 practice items; every structure
  and key term it teaches should be exercised by at least one item.
- `practice_from` (reviews only): `["lab01", "lab02", …]` — Practice draws on every practice item and step
  question of those labs, plus the lesson's own `practice`. A lesson id works too.

### Practice items

| `type` | Fields | What the student does |
|---|---|---|
| `find` | `structure` (exact atlas name) | finds it in the 3D atlas: left-click it, right-click anything in the way to peel it off (Ctrl+Z puts it back); three wrong clicks and it is shown |
| `name` | `structure` | the structure is highlighted and x-rayed; pick its name from four, the wrong ones drawn from names taught in the same lesson and lab |
| `find_micro` | `model` (micro model id), `part` (exact part name) | the model opens with its parts list and labels put away; click the part, right-click to peel parts off, three tries |
| `mcq` | `q`, `choices` (2–6), `answer` (0-based index), `why` | picks one; `why` is shown after answering, right or wrong |
| `recall` | `q`, `a` | thinks of the answer, shows it, and says honestly whether they knew it |
| `order` | `q`, `items` (in the correct order; shuffled at runtime) | drags the rows into order (or uses the arrows) and presses Check |

Any item may also carry `"why"` (shown with the feedback) and `"diagram"` (shown above the question). Every
step `check` becomes a `recall` card automatically, unless a practice item already asks the same question.

For `find` and `name` the atlas is set up the way the lesson set it up when it taught that structure — the
first step that names it in `focus`, `show`, `ghost_focus` or `frame_on` — but without selecting, x-raying or
isolating it. A structure no step names gets its own system switched on and a view that stands back from it.

### Step extras

| Key | Effect |
|---|---|
| `micro_focus` | `["<exact part names>"]` with `micro` on the same step: the model opens with those parts selected, labelled, framed and everything else x-rayed |
| `diagram` | `"<id>"`: `data/content/diagrams/<id>.svg` is drawn under the step text at the width of the panel |

Diagrams are original, hand-written SVGs for what 3D cannot show — an ECG trace, a spirogram, a reflex arc.
Draw them for the dark theme: light strokes (`#cfd8e3` and the system colours), transparent background, a
`viewBox` (so they scale), and text in a plain sans-serif. Keep them simple and labelled.

## Practice mode

`app/ui/practice.py`. A session on a mini lesson draws everything it has to practise when that is 15 items or
fewer, and 12 of them otherwise; a practice exam draws 40 (or the chosen length) from its whole pool. Items that
are due for review, never seen or often missed are drawn first, and the order is shuffled. After each answer
the panel says whether it was right and why; **Next** (or Enter) moves on, and moving on without answering
counts as a miss. Keys 1–6 pick a choice.

The summary gives the score, a breakdown by kind of question, and the missed items with their answers (double
click a structure to see it again), with **Retry missed**, **New session** and **Close**. The score of each
full session — not of a retry — is kept with the lesson's progress and shown on its card and cover.

Every answer also goes into the spaced-repetition schedule in `data/user/quiz_stats.json` (`app/srs.py`):

| Item | Scheduled under |
|---|---|
| `find`, `name` | the structure's own name — the same key the quiz uses, so a miss here comes back in **Review what is due** |
| `find_micro` | `micro:<model>:<part>` |
| `mcq`, `recall`, `order` | `card:<lesson id>:<question>#<hash>` |

The atlas is put back the way it was when the session closes. While a find or name item is live, hover
tooltips and landmark labels are off and the details panel is hidden, as in the quiz. Practice borrows the 3D
view's clicks through the quiz controller (`QuizController.delegate`), so it needs no hooks of its own in the
main window.

## What a lesson looks like

Lessons live in `data/content/lessons*.json` — any file whose name starts with `lessons` is loaded, so they
can be split up however is convenient. One object per lesson:

```json
{
  "id": "carpal-tunnel",
  "title": "The carpal tunnel",
  "system": "muscular",
  "region": "upper_limb",
  "level": "core",
  "minutes": 8,
  "summary": "Nine tendons and one nerve in a box that cannot expand.",
  "tags": ["median nerve", "compression"],
  "prereq": ["forearm-flexors"],
  "objectives": ["Name the boundaries and contents of the carpal tunnel", "…"],
  "takeaways": ["Nine tendons and the median nerve pass through; the ulnar nerve does not.", "…"],
  "see_also": {"lessons": ["hand-intrinsic-muscles"], "radiology": ["wrist_lat"],
               "micro": ["peripheral_nerve"], "histology": ["dense_regular"]},
  "steps": [ … ]
}
```

- `system` is one of `skeletal, muscular, cardiovascular, respiratory, digestive, urinary, reproductive,
  endocrine, lymphatic, nervous, sensory, integumentary`. `region` is one of `head_neck, back, thorax,
  abdomen, pelvis, upper_limb, lower_limb, general`. `level` is `foundation`, `core` or `advanced`. These
  are the library's own keys and are not the same as the dataset's system and region keys used inside a step.
- `objectives` appear in a box on the first step; `takeaways` and `see_also` appear on the last one.
- `see_also` links are live: a lesson id opens that lesson, and the others open the radiology case, the 3D
  microanatomy model or the histology slide.
- `minutes` is an estimate shown in the header; if it is omitted, two minutes a step is assumed.

## What a step looks like

```json
{
  "title": "Why the palm is spared",
  "text": "<p>The <b>palmar cutaneous branch</b> leaves the median nerve …</p>",
  "systems": ["nervous", "muscular"],
  "regions": ["upper_limb_l"],
  "side": "Left",
  "focus": ["Median nerve"],
  "show": ["Flexor retinaculum of wrist"],
  "view": "anterior",
  "frame_on": ["Radiocarpal joint"],
  "xray": true,
  "check": {"q": "Why is the thenar skin spared in carpal tunnel syndrome?",
            "a": "The palmar cutaneous branch arises proximal to the tunnel."},
  "mnemonic": "…",
  "pitfall": "…",
  "clinical": "…"
}
```

The scene keys — `systems`, `regions`, `side`, `show`, `focus`, `ghost_focus`, `isolate`, `dissect`,
`layer_only`, `clip`, `view`, `frame_on`, `camera`, `xray`, `frame`, `micro`, `histology`, `landmark` — are
handled by `apply_scene` in `app/main_window.py` and behave exactly as they do in a radiology case; see
[radiology_cases.md](radiology_cases.md) for the view and clip conventions, which are easy to get wrong.

The teaching keys are new:

| Key | Effect |
|---|---|
| `check` | `{"q": …, "a": …}` — a recall question under the text with a **Show answer** button |
| `mnemonic` | an amber box |
| `pitfall` | a red box, "Easily got wrong" |
| `clinical` | a green box, "In the clinic" |

Use `check` on most steps. The point of the runner is that you answer before you read on, and a step with no
question is a step you can skim.

## Progress

`data/user/lesson_progress.json` records, per lesson, which steps you have seen, which one you were last on,
whether you have finished it and, under `practice`, the last and best Practice scores. The library shows a
progress bar under each card, a green bar when finished, and a **Continue** card at the top for the lesson you
were last in the middle of. Nothing else in the app reads the file, and deleting it simply resets the library.

## Writing a lesson

1. **Check the names first.** Every name in `focus`, `show`, `ghost_focus` and `frame_on` must resolve
   exactly. `tools/name_probe.py` is much faster than guessing:

   ```bash
   .venv/Scripts/python.exe tools/name_probe.py "Flexor pollicis longus" "Palmaris longus"
   .venv/Scripts/python.exe tools/name_probe.py --like "flexor"
   ```

   It prints the number of structures each name resolves to, or the nearest matches when it fails. Note that
   the dataset uses `Palmaris longus muscle` but `Flexor carpi radialis`, and `Bucinator` with one C — there
   is no way to guess these.

2. **Prefer a collection to a list.** `Anterior compartment of forearm`, `Muscles of hand`, `Facial muscles`,
   `Deep gluteal muscles`, `Brainstem` and about 360 other collection names resolve to whole groups, and they
   survive dataset changes better than a hand-written list.

3. **Validate.**

   ```bash
   .venv/Scripts/python.exe tools/check_lessons.py
   ```

   It checks every structure name, the system, region and level keys, the dataset system and region keys in
   each step, that `prereq` and `see_also` point at things that exist, that every lesson has objectives and
   takeaways, and that a `check` has both a question and an answer.

   For the lab course it also checks the `course` fields and the id pattern, every practice item (its type and
   fields, exact atlas names for `find`/`name`, a valid `mcq` answer index, no duplicate `order` rows), exact
   part names for `find_micro` and `micro_focus` — by building the model's parts from `data/micro_cache`, which
   can take a minute the first time — that every `diagram` exists as a well-formed SVG with a `viewBox`, and
   that `practice_from` names real labs. A micro model that is not registered yet (or will not build right now)
   is a warning, not a failure. Warnings also flag mini lessons outside 3–5 steps or with fewer than six
   practice items.

   ```bash
   .venv/bin/python tools/check_lessons.py --only lab03          # just one lab
   .venv/bin/python tools/check_lessons.py drafts/my_lab.json    # a draft not yet in data/content
   ```

4. **Look at it.** A lesson that reads well can still frame badly:

   ```bash
   .venv/Scripts/python.exe -m app --script "wait:1500;tab:5;eval:w.lessons_panel.open_lesson('carpal-tunnel');wait:1500;eval:w.grab().save('logs/ui/x.png');wait:200;quit:"
   ```

   (`eval:` payloads must not contain a semicolon — the script splits on it.)

## Retrofitting older lessons

`tools/annotate_lessons.py` and `tools/annotate_lesson_checks.py` hold the system, region, level, objectives,
takeaways and recall questions for the lessons written before those fields existed. Both are idempotent —
they only fill in a field that is missing — so they can be run again after editing the tables in them.
