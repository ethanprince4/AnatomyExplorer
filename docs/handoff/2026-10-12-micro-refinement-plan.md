# Handoff: overnight microanatomy refinement, 12 October 2026

Branch: `claude/laughing-fermat-g8hbbz`. Started in a cloud session at 00:17 CT, moved to a local session at 00:30 CT.
**Hard stop 6:00 a.m. Central; start writing handoffs at 5:30.**

## What the user asked for (their words, condensed)

- Refine all 41 microanatomy models in the model library "maximally". If a model is not already the best
  possible teaching representation, **delete it and restart**: "you will get better results from restarting".
  Many are "completely trash".
- Quality bar: "the worst, meanest, most stuck-up histology professor on earth". Creative, detailed, meticulous.
  No visible defects. Visually great and great for teaching.
- The models exist **for teaching, not exact anatomical correctness**: if a schematic choice teaches better, do it.
- Rendering is allowed and expected: "render the things that need to be rendered to see what's going on".
- Usage is not a concern: one queue per model, many agents, max effort.
- Each model has its own queue: refine to the best it can be, **then build animations for it**. One model can be
  animating while another is still being refined. The lead session coordinates and checks the workers' output.
- Make a worktree and keep copies of the work as you go (commit and push often).
- Skills to use: the user's `microanatomy-model-builder`, `anatomy-model-refiner`, `microanatomy-animation` and
  `3dviz-pro-max` (zips the user has), plus this repo's `.claude/skills/micro-model/SKILL.md`. The user says the
  skills are "not exactly perfect, but a good starting place".

### Where tonight's request overrides the skills

The skills were written for interactive rounds with the user. Tonight the user is asleep, so:

- Renders and visual inspection by agents **are allowed** (the skills say no renders and no vision verdicts).
  Numeric and geometric checks are still the gates; renders find the defects.
- The user **explicitly asked for animations**, so microanatomy-animation applies once a model is final.
- Bias to **rebuild**, not polish. No waiting for review notes; unattended rounds log decisions instead of asking.
- Kept from the skills: separate closed named parts; one master copied or mirrored for repeated or symmetric
  parts; sizes with sourced lower and upper bounds; no label geometry or label data; the teaching pattern
  baked into vertex colours (`c{i}` in the NPZ) where it is a pattern; original geometry only (no downloaded meshes).
- An older handoff says "models are off limits, never write `.npz`". That was the renderer-perf session's rule;
  the user's request tonight supersedes it for this work.

## How the models actually work (verified)

- The app's catalogue comes **only** from `data/local_model_library/library.json` (41 models). Each model is one
  NPZ: `data/local_model_library/models/<id>/<version>/model.npz` (or `refined.npz`). The `app/micro/*.py`
  builders are older source that the app no longer runs; they can still be read for ideas and reused as code.
- NPZ format: per part `p{i}` positions (float32, or uint16 + `b{i}` = [lo, span]), `n{i}` normals (float32 or
  int8/127), `i{i}` triangles, optional `c{i}` per-vertex linear RGB 0..1, and `meta` (JSON bytes) with a
  `parts` list: name, group, color, alpha, category, label, rank, clip, bulk, detail, description. Decoder:
  `app/variants/local_runtime.py` `decode_local_npz`. App space is +Y up; Blender is +Z up
  (app (x, y, z) = Blender (x, -z, y)).
- Each library entry has `variants.post` (what the app opens) and may have `variants.pre`, which the app shows
  as Before/After. **Plan: keep the current file as `pre` and register the new one as `post`** in a new version
  folder, so the user can compare in the app. Never overwrite an existing model file. Files over 100 MB need a
  line in `.gitattributes` (Git LFS).
- Lessons name parts (`micro_focus`, `find_micro`, practice items). **Never drop or rename a part name that
  content uses**; a rebuild keeps those names, or adds aliases in `data/content/model_parts/<id>.json`.
  `python tools/check_lessons.py` must print OK.
- Default cut-away removes x < 0, z > 0 (tubes: x < 0, y > 0). Key structures must cross it. Budget about
  1 to 1.5 M triangles.
- **Animation:** the library loader only builds an animation controller for `pancreas` (hard-coded in
  `_animation` in `app/variants/local_runtime.py`). Other models cannot animate until the generic controller
  below exists. Morph data rides in an `animation` companion NPZ (`m{index}` (n,k<=4,3), `f{index}` (n,)).
- Cardiac muscle as it stands: a stack of identical pale blue logs with no striations visible. Expect many
  models to need a restart.

## Done so far (on the branch)

- `tools/render_model.py` (and so `tools/render_micro.py`) was broken for every library model
  (`DeferredVariantEntry` has no `load`); fixed to use `prepare_cpu`. A still takes about 40 s on 4 CPU cores
  with software GL; much faster on a real GPU.
- `tools/micro_refine/npz_io.py`: `read_model` / `write_model` / `summary` for the library format, tested by
  round trip on spleen (max position error 1.5e-5, faces identical, app decoder reads it).
- Cloud only, not needed locally: Mesa/EGL libraries and Blender 4.5.3 LTS installed in the container.

## Still to build before fanning out (about 30-45 min)

1. `tools/micro_refine/blender_io.py`: run in headless Blender. `import` an NPZ into a .blend (one object per
   part, collections per group, part metadata as a JSON custom property, full part name kept there because
   Blender truncates object names at 63 characters, `c{i}` to a COLOR_0 attribute), and `export` a collection
   back to NPZ via `npz_io.write_model` (apply modifiers, triangulate, convert axes).
2. `tools/micro_refine/gate.py`: on a candidate NPZ: every part non-empty and closed (edges shared by exactly two
   faces after welding), no duplicate names, triangle total in budget, every part name the old model's lessons
   use still present, loads through `decode_local_npz` with no warnings, and (optional, slower) no overlap
   between pieces of one part. JSON report; exit 0 pass, 2 finding, 3 could not run.
3. `tools/micro_refine/register.py <id> <new npz>`: moves the current `post` to `pre` (once), sets the new
   `post`, keeps the companions, prints the diff of `library.json`.
4. `tools/micro_refine/render_set.py <id>`: one model load, a standard set of views (home cut, home uncut, top,
   front, back, a close-up of the cut corner, any `--focus` close-ups) plus a contact sheet. Same views before and
   after, so `tools/micro_sbs.py` can make side-by-sides.
5. **Generic animation controller** (shared app change, do it once, early):
   - JSON companion with role `animation_controller`, schema `ae.micro-animation.v1`:
     `{"title", "period", "speeds", "phases": [[start, end, label]], "tracks": {"<part name | group | prefix*>":
     {"mode": "morph"|"flow"|"wave", "weights": [curves x4], "glow": curve, "rate": n}}}`.
   - A curve is a constant or a safe declarative form: `{"window": [a,b,c,d]}` (anim.window), `{"keys":
     [[t,v],...], "interp": "linear"|"smooth"}` (cyclic), `{"sine": {...}}`, `{"scale": k, "of": curve}`,
     `{"sum": [...]}`. No code eval.
   - Wire into `_animation`: use the JSON when present, keep the pancreas fallback, and degrade bad data to a
     warning and a still model.
   - A validator CLI (track names resolve, morph vertex counts match, seamless loop) and a
     `write_animation(...)` helper.
   - A unit test, a short section in `docs/microanatomy_models.md`, and an end-to-end proof with
     `tools/render_micro.py <id> --frames 6 -o x.gif`.
   (The cloud session had an agent on this when the move happened; if its result is not on the branch, redo it.)
6. Copy the four skills into `~/.claude/skills/` (the builder skill reads `~/.claude/skills/3dviz-pro-max/...`).

## The per-model pipeline (one queue per model, worktree per model)

1. **Audit.**
   - Render the current model (render_set), list its parts, and list the lesson references to it
     (`grep -rn "<id>" data/content`).
   - Read `data/content/model_parts/<id>.json` and the model's summary in `library.json`.
   - Write a harsh defect list. Verdict: **REBUILD** (default unless it is already the best possible teaching
     version) or REFINE.
2. **Brief** (builder skill Stage 1, short): what a student must find, the identity checklist, sizes with sourced
   lower and upper bounds, the colour plan (H&E-inspired, distinct; arteries red, veins blue, nerves yellow,
   lymphatics green or pale), and what the cut face must show.
3. **Build:** a build script committed to the repo (Blender `tools/blender/micro/<id>/build.py` or a numpy
   builder), exporting through `npz_io`. Closed parts, master copies, no square-bar clipping at block faces,
   staggered natural layout, smooth shading, grooves at boundaries.
4. **Critique loop:** render_set, then two or three independent critic agents (a harsh histology professor, a
   3D-craft critic, a teaching-clarity critic) attack the renders and the numbers, then fix. Repeat until a
   round finds nothing new. After two failed passes on one defect, change the construction method.
5. **Gate:** `gate.py` passes, `check_lessons.py` OK, before/after side-by-sides made, registered as
   `post` with the old file as `pre`. Commit and push.
6. **Animation**, only after the model is final: one honest clip that teaches a real process (cardiac
   contraction, ciliary beat, peristalsis, secretion flow, blood flow in a capillary bed, an action
   potential along a node of Ranvier...). Check closed junctions, volume and seamless loop. Render a GIF.
   Register the companions. Commit and push.

## Schedule (Central time)

- Until about 1:15: finish the toolkit and the animation controller; pilot one model end to end.
- 1:15 to 4:45: all model queues running; the lead checks every queue every 20-30 minutes, looks at the renders,
  sends critique, restarts weak attempts, and merges finished models into this branch after re-checking.
- 4:45: tell queues to finish. 5:15: every queue pushes its last good state and a short per-model note.
- 5:30 to 5:55: merge what is finished; write `docs/handoff/2026-10-12-micro-refinement-handoff.md`
  (per model: status, before/after images, what is still weak, next step); push.

## The 41 models

spleen, oesophagus_wall, stomach_wall, ileum, tooth, tongue_papillae, bladder_wall, thin_skin, scalp, thick_skin,
blood_cells, cardiac_muscle, cornea, elastic_artery, whole_heart, hepatobiliary, kidney_nephron, liver_lobule,
lung_acinus_review_v2, lymph_node, muscular_artery, peripheral_nerve, retina, skeletal_muscle,
thyroid_parathyroid_review_v2, trachea_wall, vein_wall, male_reproductive, female_reproductive, ear, eyeball,
compact_bone, axillary_skin, ileocecal_rectum, jejunum, capillary_bed, lymph_drainage, duodenum, colon_wall,
pancreas, neuron.

The ids must stay as they are (lessons and packaging use them), including the `_review_v2` ones.
