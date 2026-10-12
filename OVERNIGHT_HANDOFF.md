# Overnight micro-model refinement: handoff (read this first)

You are the **coordinator**. The user is asleep and won't answer questions, so log your decisions and keep going.
**Hard stop: 6:00 a.m. Central. Start writing handoffs at 5:30.**

The user has opted in to large multi-agent workflows: "I want forty workflows going", "Opus on everything, max
reasoning", "do not concern yourself with usage". Use the Workflow tool.

## What the user wants

- **Refine all 41 microanatomy models** in the model library to the highest possible quality: "the worst,
  meanest, most stuck-up histology professor on earth". Creative, detailed, meticulous, no visible defects.
- **If a model isn't already the best possible representation, delete it and restart.** The user says many are
  "completely trash" and that restarting gives better results. Bias towards rebuilding.
- **The models are for teaching, not exact anatomical correctness.** If a schematic choice teaches better, do it.
- **Render whatever you need to render** to see what's going on.
- **One queue per model.** Refine it to the best it can be, then build an animation for it. One model can be
  animating while another is still refining. You coordinate the workers and check their output.
- **Work in a worktree and keep copies:** commit and push often.

## Setup

1. **Code.** Use the repo `ethanprince4/AnatomyExplorer`, branch `claude/laughing-fermat-g8hbbz`:
   `git fetch origin claude/laughing-fermat-g8hbbz && git checkout claude/laughing-fermat-g8hbbz && git lfs pull`.
   The branch already has:
   - a fix to `tools/render_model.py`: it was broken for every library model, because `entry.load()` doesn't
     exist there; it now uses `entry.prepare_cpu(token)`;
   - `tools/micro_refine/npz_io.py`, a reader and writer for the library format, tested by round trip.

   A cloud session may push one more commit (generic animation support), so always `git pull --no-rebase`
   before you push.
2. **Dependencies:** `pip install -r requirements.txt pillow`, and Blender 4.5 LTS for headless builds.
3. **Skills.** They are in the working directory: microanatomy-model-builder, anatomy-model-refiner,
   microanatomy-animation and 3dviz-pro-max. Also use the repo's `.claude/skills/micro-model/SKILL.md`.
   - Make sure the skills are installed where Claude Code loads them.
   - The builder skill refers to `~/.claude/skills/3dviz-pro-max/...` by path, so fix up those paths if needed.
4. **Check a render:** `python tools/render_micro.py cardiac_muscle -o test.png --size 700`.

## Key facts (verified)

- **Where the models come from.** The app loads micro models only from `data/local_model_library/library.json`
  (41 models). Each is one NPZ at `models/<id>/<version>/model.npz` or `refined.npz`.
  - The `app/micro/*.py` builders are old source the app no longer runs. Reuse them for ideas or code.
  - NPZ decoder: `decode_local_npz` in `app/variants/local_runtime.py`.
- **Axes:** the app is +Y up; Blender is +Z up. App (x, y, z) equals Blender (x, -z, y).
- **Before/After.** A library entry can carry `variants.pre` and `variants.post`; the app opens `post` and offers
  Before/After.
  - Register each new model as `post` in a **new version folder**, and keep the current file as `pre`.
  - Never overwrite a model file.
  - Files over 100 MB need a Git LFS line in `.gitattributes`.
- **Rendering a candidate without touching library.json.** Set `AE_LOCAL_MODEL_LIBRARY` to a scratch folder
  whose `library.json` holds just that model, with absolute paths. Entries there override the bundled ones, model
  by model.
- **Lessons name parts.** Never drop or rename a part name that content uses: keep the name, or add an alias in
  `data/content/model_parts/<id>.json`. `python tools/check_lessons.py` must print OK.
- **Cut-away and budget.** The default cut-away removes x < 0, z > 0 (tubes: x < 0, y > 0), so key structures
  must cross it. Budget about 1 to 1.5 M triangles per model.
- **Animation is pancreas-only today.** The controller is hard-coded in `_animation` in
  `app/variants/local_runtime.py`. Build a generic, data-driven controller once, early (if the cloud session's
  commit isn't on the branch):
  - a JSON companion with role `animation_controller` that holds the period, labelled phases and per-part
    tracks (morph, flow or wave), mapped onto the Track and Animation classes in `app/micro/anim.py`;
  - curves are declarative only (no code eval): window ramps, keyframes, sine, scale and sum;
  - pancreas keeps working, and bad data falls back to a warning and a still model;
  - add a validator, a unit test and a GIF proof with `render_micro.py <id> --frames N`.
- **An old rule doesn't apply tonight.** An older handoff says "models are off limits / never write .npz". That
  was the renderer session's rule; the user's request tonight overrides it.

## Where tonight overrides the skills

- **Agents may render and inspect.** Numeric and geometric checks remain the gates; renders find the defects.
- **The user explicitly wants animations,** so microanatomy-animation applies once a model is final.
- **Rebuild by default,** and don't wait for review notes.
- **Kept from the skills:**
  - closed, named, separate parts;
  - one master copied or mirrored for repeated or symmetric parts;
  - sourced size ranges;
  - no label geometry;
  - the pattern baked into vertex colours;
  - original geometry only.

## Per-model queue

1. **Audit.**
   - Render the current model from several views, including the cut face, and list its parts and lesson uses.
   - Write a harsh defect list.
   - Decide: REBUILD (the default) or REFINE.
2. **Brief.** What a student must find, sizes with sourced bounds, a colour plan (H&E-like and distinct;
   arteries red, veins blue, nerves yellow) and what the cut face must show.
3. **Build** with a committed build script. Closed parts; no unit clipped into a square bar at block faces;
   a natural staggered layout; smooth shading.
4. **Critique loop.** Render, then independent critic agents attack it (histology professor, 3D craft, teaching
   clarity), then fix. Repeat until a round finds nothing new. After two failed passes on one defect, change
   the construction method.
5. **Gate.**
   - Every part is closed, non-empty and uniquely named; lesson part names are present; the triangle count is
     in budget; the model loads with no warnings; `check_lessons.py` prints OK.
   - Make before/after side-by-sides with `tools/micro_sbs.py`.
   - Register the model, then commit and push.
6. **Animation.**
   - One honest clip that teaches a real process.
   - Check closed junctions, volume and a seamless loop, and make a GIF.
   - Register it, then commit and push.

Keep each worker writing only inside its own model's folders; shared app code and `library.json` changes go
through you.

## Schedule (Central)

- **Until ~1:30:** finish the tools and the animation controller; run one model end to end as a pilot.
- **~1:30 to 4:45:** all queues running. Check each queue every 20 to 30 minutes, look at its renders, push back
  hard on weak work, and restart attempts that are settling.
- **4:45:** tell the queues to finish. **5:15:** every queue saves its last good state and a short note.
- **5:30 to 5:55:** merge finished work and write `docs/handoff/2026-10-12-micro-refinement-handoff.md`
  (per model: status, before/after images, what is still weak, next step). Push.

## The 41 model ids (keep them exactly)

spleen, oesophagus_wall, stomach_wall, ileum, tooth, tongue_papillae, bladder_wall, thin_skin, scalp, thick_skin,
blood_cells, cardiac_muscle, cornea, elastic_artery, whole_heart, hepatobiliary, kidney_nephron, liver_lobule,
lung_acinus_review_v2, lymph_node, muscular_artery, peripheral_nerve, retina, skeletal_muscle,
thyroid_parathyroid_review_v2, trachea_wall, vein_wall, male_reproductive, female_reproductive, ear, eyeball,
compact_bone, axillary_skin, ileocecal_rectum, jejunum, capillary_bed, lymph_drainage, duodenum, colon_wall,
pancreas, neuron
