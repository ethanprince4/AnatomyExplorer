# Reviewed tongue papillae integration

Integrated the user's approved `Model_Reviews/tongue_papillae/refined/model.npz` as
an exact copy. No geometry, normals, topology, colors or embedded metadata were
rewritten. Original Desktop and website worktrees were not edited. Base commit:
`5d727268ac62269d603b61132041fe4e354f1050`.

- Protected original: `C:/Users/Ethan/Desktop/AnatomyExplorer/Model_Reviews/tongue_papillae/refined/model.npz`.
- SHA256 before copying, after checking, and in the installed copy:
  `965291ab046d0869e5d7e424407e4ece676df56bd851c34eb8319fbf9c8f2783`.
- Size: 39,670,935 bytes. Ordinary Git binary under the repository's existing
  under-100-MB asset convention; no LFS fetch was required.
- Supplied format: `anatomy-npz-f32-delta-v1`, float32 positions and normals,
  int32 delta triangle indices; no vertex-color arrays. Authored hex material
  colors, alpha, groups, clipping, bulk and detail flags are retained.
- 29 unique selectable keys, 2,097,364 vertices, 4,083,312 triangles, six groups.
- Nominal scale remains 0.005 metres/unit, explicitly uncalibrated. The supplied
  model descriptions retain the local 4x cellular enlargement, 19 sampled cells
  per bud, schematic counts and spacing, and comparative regional arrangement.

## Integration changes

The `tongue_papillae/post` catalog variant now points to `native-20261021`.
The older source model and sidecars remain preserved in Git and this worktree.
The source's first 29 canonical keys and six group names match existing app
conventions. The existing two-category parts tree is retained; obsolete guide
entries for absent meshes were removed. The real native tree represents all 29
parts, and all 29 return their own IDs through actual isolated GPU picking.

The previous 40-part asset had 11 additional meshes absent from the supplied
replacement: Vallate teaching cover; Taste nuclear teaching cover; Taste cell
teaching cover; Gland teaching cover; Gland nuclear teaching cover; Intramuscular
connective tissue; Muscle connective teaching cover; Foliate outlet teaching
cover; Gland stromal teaching cover; Vallate outlet epithelial cover; Outlet
basement teaching cover. No substitutes were invented.

New tongue-only sidecars expose eight views of actual retained anatomy. Old
cover-dependent opened/restored views were retired. Hidden masks contain only
existing keys. Taste-cell and muscle views hide their opaque enclosing tissue;
detail cameras were framed after native UI inspection. The standard app adds
its existing ninth `Full teaching model` catalog overview and cutaway at runtime.
No shared viewer behavior or updater/helper code changed.

The selector plate was regenerated with `tools/render_catalogue_specimens.py`
using the installed new model and its Overview camera. Its new tongue profile
uses the app's existing OpenGL renderer, tissue defaults, and silhouette alpha
recovery. The thumbnail SHA is in `catalogue-render.json` and `audit.json`.

Three existing lessons were updated: `lab08-02-oral-cavity-mastication` adds the
related model; `lab08-03-tongue-papillae-taste` links papilla and taste-cell views,
adds a gland/duct step and three find-in-model exercises; `oral-cavity-tongue`
links papilla and sensory-branch views. Five steps use exact live part keys.
Model scale limitations are explained where needed. The taste-signaling text
now distinguishes ATP release from type III synapses, as stated by the supplied
model's gustatory-cell description. Gland facts come from its gland/duct
descriptions and the existing part guide. No new external anatomy claims or
unsupported meshes were added.

## Evidence and limits

- `audit.json`: complete supplied-buffer checks, per-part hashes/bounds/metadata,
  native load, guide/lesson/view resolution, eight app-renderer captures and 29
  isolated GPU IDs plus real `Renderer.pick` returns. GPU: NVIDIA RTX 3080,
  OpenGL 4.1. `view-00.webp` through `view-07.webp` were visually inspected.
- `selector.png`: actual `ModelCatalogPanel`, filtered to tongue, rendered with
  the Qt offscreen plugin; new grid plate and large selected preview inspected.
- `native.json`, `native-overview.png`, `native-lesson-00.webp`,
  `native-lesson-01.webp`: actual Windows `ModelView`/QOpenGLWidget with a valid
  context and successful frames. Window used `WA_DontShowOnScreen` and
  `WA_ShowWithoutActivating`. All five lesson-step calls selected their expected
  visible keys. Saved captures were inspected; no desktop window was taken over.
- Scoped `tools/check_lessons.py --only` checks passed for all three edited
  lesson IDs. `git diff --check` passed.
- `regression-tests.json`: four nearby existing unittest modules ran 19 tests:
  eight passed, eleven errored on stale mock interfaces (`FakeView` lacks
  `_set_catalogue_clipping`; `SimpleNamespace` lacks `settings`). Their test
  files and the implicated application files match the parent commit exactly.
  Actual ModelView calls pass. Unrelated fixtures were left unchanged.

The approved source contains 4,804 zero-length normals across ten parts. The
unchanged native decoder repairs these in memory, yielding finite unit normals;
the exact source/copy hash remains unchanged. This is disclosed in the audit,
not hidden by rewriting the approved model. Numeric/schema and picking checks
do not establish anatomical acceptance or universal collision freedom. No
macOS, wgpu, packaged-install or production-release checks were performed.

The source-preservation and native-opening portions of the local
`anatomy-refinement-workflow` skill were applied (SKILL.md, execution.md and
workflow.md). Geometry-construction, rebuilding and bulk-tissue correction were
inapplicable to this user-approved, byte-preserved integration; bulk surfaces
were inspected in saved native and renderer views. No builders were run.

## Exact deployment footprint

`deployment-footprint.json` records sizes, hashes and reference checks. Active
changed application/content files are:

- `data/local_model_library/library.json`
- `data/local_model_library/models/tongue_papillae/native-20261021/model.npz`
- `data/local_model_library/models/tongue_papillae/native-20261021/model.controls.json`
- `data/local_model_library/models/tongue_papillae/native-20261021/teaching_recipe.json`
- `app/ui/resources/studio/model-vitrines/thumb_tongue_papillae.webp`
- `data/content/model_parts/tongue_papillae.json`
- `data/content/lessons_course_lab08.json`
- `data/content/lessons_digestive_upper.json`

Prior active assets, now unreferenced by every retained catalog variant/lesson:

- `data/local_model_library/models/tongue_papillae/v4/model.npz`
- `data/local_model_library/models/tongue_papillae/native-20261020/model.controls.json`
- `data/local_model_library/models/tongue_papillae/native-20261020/teaching_recipe.json`

The preserved historical `data/local_model_library/models/tongue_papillae/v4/recipe.json`
also has no active catalog/lesson reference. Lessons use the stable model ID and
resolve to the new Post variant. The existing `post_library_data` release-seed
collector selects exactly the three new `native-20261021` files for tongue and
none of these four old assets. Parent may omit the four unreferenced managed
files from a subsequent complete deployment snapshot; no source/history/review
file was deleted here. The thumbnail, guide and lesson files replace the same
active logical paths, so those paths must remain in the snapshot. This evidence
folder and the render-tool profile are development material.

No VERSION change, PR, merge, tag, Actions run, R2 upload or publication occurred.
The production website remains held. Parent owns subsequent content publication.

## Reproduce bounded checks

From the repository root, using a Python environment with NumPy, PySide6,
moderngl and Pillow:

```powershell
python tools/render_catalogue_specimens.py tongue_papillae --report docs/model-integrations/2026-10-21-tongue-papillae/catalogue-render.json
python docs/model-integrations/2026-10-21-tongue-papillae/verify_integration.py --source C:/Users/Ethan/Desktop/AnatomyExplorer/Model_Reviews/tongue_papillae/refined/model.npz
python docs/model-integrations/2026-10-21-tongue-papillae/capture_native.py
python tools/check_lessons.py --only lab08-03-tongue-papillae-taste
python tools/check_lessons.py --only lab08-02-oral-cavity-mastication
python tools/check_lessons.py --only oral-cavity-tongue
```
