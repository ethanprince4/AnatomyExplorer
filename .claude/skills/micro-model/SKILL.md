---
name: micro-model
description: Build, redesign or animate a 3D microanatomy model in AnatomyExplorer (app/micro). Use for any work on a micro model's geometry, colours, cut faces or animation, including Blender-assisted parts. Covers the loop, the rules that break the app if ignored, verification, and how to present before/after results.
---

# Microanatomy model workflow

A micro model is Python code in `app/micro/` that returns a list of `Part`s: one closed mesh per named structure. The app
caches the built meshes in `data/micro_cache/<id>.npz`, keyed on a digest of the toolkit and the model's builder files, so
**any source edit forces a rebuild**. Read `docs/microanatomy_models.md` first: its structure list, requirements and
"How the current models are built" section are the spec.

## Hard rules (break these and the app or the lessons break)

1. **Never rename or remove a part that content uses.** Lessons and practice items name parts (`micro_focus`,
   `find_micro`). Snapshot the names before you start (step 1 below) and keep every one; adding parts is fine.
2. **Closed meshes, and no overlap within a part.** The cut-away draws solid caps where the cutting plane is inside a
   part. Open meshes or overlapping pieces of the same part give jagged, shattered cut faces (the old pancreas had this).
   Neighbouring cells should be separate, non-overlapping solids, such as Voronoi regions shrunk apart or SDF cells
   clipped against each other.
3. **Place the key structures across the cut.** The default cut removes x < 0, z > 0 (tubes: x < 0, y > 0); organs set
   their own `cut_at`. Whatever the model teaches must be sectioned by that cut.
4. **Budget:** about 1 to 1.5 M triangles and a build under three minutes. Everything runs on users' laptops.
5. **Original geometry only.** Never download third-party meshes, "free" model packs or rips. Tools such as Blender, bpy
   and numpy are fine; the shapes must come from our code or our own Blender scripts (`tools/blender/*.py`, which write
   `data/models/*.npz`). After regenerating a Blender asset, bump its version constant in the builder, because the cache
   digest covers code, not data files.
6. **Colours:** believable and H&E-inspired, but pleasant and distinguishable. No saturated purple slabs. Colours carry
   meaning: keep conduction green, arteries red and veins blue unless there is a reason to change them.
7. **Rest pose = lesson pose.** An animated model must look like a normal static model when not playing, at time 0.

## The loop (keep it cheap: iteration speed is the whole game)

The sandbox has no GPU, and a full app frame costs about 3 s. Do not launch the full app to iterate.

1. **Baseline**
   ```bash
   python tools/check_micro.py <id> --names-out /tmp/names_<id>.json   # part-name snapshot + stats
   python tools/render_micro.py <id> -o before_<id>.png --size 800      # plus 2-4 views: --yaw/--pitch/--zoom
   ```
   Write down what is actually wrong. Be specific, for example "acini overlap, so cut faces shatter", or "ventricles are
   ellipsoids with no acute margin". Fix the worst two or three problems, not everything.
2. **Iterate:** edit, then `python tools/render_micro.py <id> -o x.png --size 800`, then look at the image. Lower the
   builder's mesh resolution while iterating, and restore it for the final build. Use `--only`/`--hide`/`--focus`
   to inspect a structure, and `--no-cut` to see the outer surface.
3. **Time-box:** a first honest result within about 30 minutes per model. If a detail is fiddly, take the simpler
   option and note the limitation; do not go on debugging side-quests.
4. **Verify**
   ```bash
   python tools/check_micro.py <id> --rebuild --names-against /tmp/names_<id>.json   # 0 failures; read the warnings
   python tools/check_lessons.py                                                     # must print OK
   ```
   Then check the model once in the real app (headless: see below) and look at the cut face.
5. **Present:** render the same views as the baseline, then
   `python tools/micro_sbs.py before.png after.png -o cmp_<id>.jpg` (needs Pillow, a dev-only dependency: `pip install pillow`). Report what was wrong, what changed, what is
   still weak, and the triangle count and build time. Say plainly when the result is only a modest improvement.

## Animation (optional)

`app/micro/anim.py` explains itself in its docstring; `heart_motion.py` and `pancreas.py` are the worked examples.

- **Per vertex:** attach up to 4 morph targets and a phase: `part.anim = {"morph": (n,k,3), "phase": (n,)}`, in
  the vertex order of `part.mesh.arrays()`.
- **Per part:** a `Track` gives the weights over the cycle. The modes are `MODE_MORPH` (contraction, valves),
  `MODE_FLOW` (particles on their own clocks along a curved path) and `MODE_WAVE` (a travelling glow set by activation
  time).
- **Register:** use `AnimatedModel` with an `Animation(period, tracks, phases=[(start, end, label)], title=...)`. The micro view then
  shows Play, speed and the scrubber automatically.
- **Render:** `render_micro.py <id> --time T` for a still; `--frames 12 -o a.gif` while iterating and `--frames 24`
  for the final GIF (it also writes a contact strip).
- **Visibility:** if the motion is buried inside opaque tissue, it doesn't teach anything. Place it on the cut face,
  or show it with `--only` in the GIF.

## Running the app headless (final check only)

```bash
export QT_QPA_PLATFORM=xcb QTWEBENGINE_DISABLE_SANDBOX=1
xvfb-run -a -s "-screen 0 1440x900x24 +extension GLX" python -m app --no-restore \
  --script "wait:4000;link:micro=<id>;wait:12000;shot:/tmp/app_<id>.png;quit"
git checkout -- data/anatomy/depth.npz data/anatomy/samples.npz    # app runs rewrite these caches
```

Script commands are separated by `;`, so `eval:` payloads must not contain semicolons. `logs/errors.log` must not exist
afterwards.

## Before you hand back

- `check_micro.py` shows 0 failures, and every warning is explained.
- `check_lessons.py` prints OK.
- The before/after side-by-sides and the GIF (if animated) are produced.
- There are no stray edits outside the model's own files; any shared file you changed (toolkit, renderer, shaders) is
  called out, because changing the toolkit rebuilds every model.
- `docs/microanatomy_models.md` is updated if parts or groups changed.
