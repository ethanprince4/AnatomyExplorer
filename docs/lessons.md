# Guided lessons

A lesson is a short scripted walk through one topic. Each step writes a paragraph or two, sets the 3D view up
to match it, and can ask a question before you move on. Ctrl+L, or **Lessons** on the lower row of the Explore
panel's switcher.

There are **137 lessons, 810 steps and 721 recall questions**, filed under twelve body systems and eight
regions. The browser groups them three ways — **System**, **Region** or **Level** — and remembers how far
through each one you got.

| System | Lessons | | Region | Lessons |
|---|---|---|---|---|
| Muscular | 26 | | Head & neck | 37 |
| Nervous | 26 | | Abdomen | 20 |
| Cardiovascular | 20 | | Thorax | 18 |
| Skeletal | 16 | | Whole body | 18 |
| Digestive | 16 | | Upper limb | 16 |
| Respiratory | 9 | | Lower limb | 15 |
| Special senses | 6 | | Pelvis & perineum | 7 |
| Lymphatic & immune | 5 | | Back & spine | 6 |
| Endocrine | 5 | | | |
| Skin & fascia | 3 | | | |
| Urinary | 3 | | | |
| Reproductive | 2 | | | |

Levels are **Foundation** (12), **Core** (88) and **Advanced** (37). Advanced lessons usually name a
`prereq`, which the runner shows under the title as "After: …".

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

`data/user/lesson_progress.json` records, per lesson, which steps you have seen, which one you were last on
and whether you have finished it. The library shows a progress bar under each card, a green bar when
finished, and a **Continue** card at the top for the lesson you were last in the middle of. Nothing else in
the app reads the file, and deleting it simply resets the library.

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

4. **Look at it.** A lesson that reads well can still frame badly:

   ```bash
   .venv/Scripts/python.exe -m app --script "wait:1500;tab:5;eval:w.lessons_panel.open_lesson('carpal-tunnel');wait:1500;eval:w.grab().save('logs/ui/x.png');wait:200;quit:"
   ```

   (`eval:` payloads must not contain a semicolon — the script splits on it.)

## Retrofitting older lessons

`tools/annotate_lessons.py` and `tools/annotate_lesson_checks.py` hold the system, region, level, objectives,
takeaways and recall questions for the lessons written before those fields existed. Both are idempotent —
they only fill in a field that is missing — so they can be run again after editing the tables in them.
