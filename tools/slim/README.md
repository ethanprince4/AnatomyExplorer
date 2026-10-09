# Model slimming pipeline

Makes simplified **review copies** of the heaviest parts of the model-library models (`data/local_model_library`),
checks each copy against the original, and renders before/after comparisons. Originals are never written; approved
copies are swapped in by hand afterwards (see "Applying approved copies").

## Setup

A Python 3.11 environment with:

```
pip install bpy==5.0.1 numpy scipy moderngl==5.12.0 pillow PySide6==6.11.2
```

`bpy` is Blender as a Python module (Blender's Decimate › Collapse did best of the engines tried: pyfqmr left
artifacts, MeshLab was close, our own QEM simplifier was not better). Rendering (`render_staged.py`,
`slim_review.py`, `render_overview.py`) needs an OpenGL 4.1 context: native on macOS and Windows; on headless Linux
run under `xvfb-run -a -s "-screen 0 1600x1200x24 +extension GLX"`.

## Steps

| Step | Script | Output |
| --- | --- | --- |
| 0. audit (optional) | `tri_health.py OUT/health <model ids>`, `render_overview.py OUT/renders <ids>` | per-part triangle density, slivers, duplicates; opening-view renders. These fed the Haiku triage that picked `candidates.txt`. |
| 1. export | `slim_export.py OUT model "part" ...` | `OUT/<model>/<part>.npz` (welded, cleaned), `OUT/manifest.jsonl` |
| 2. decimate + score | `slim_decimate.py OUT [start:end]` | `OUT/<model>/<part>__slimNN.npz`, `OUT/results.jsonl` |
| 3. stage copies | `slim_stage.py OUT [models]` | `OUT/staged/<library path>` (whole model files with accepted parts swapped in), `OUT/staged/summary.json` |
| 4. shape sheets | `slim_review.py OUT <models>` | `OUT/sheets/*.jpg`: whole part and two close-ups, original vs copy |
| 5. in-app renders | `render_staged.py OUT OUT/renders <models>` | the app's own renderer, opening view and a close-up on the largest simplified part, before and after |
| 6. review page | `build_review_page.py OUT OUT/renders` | `OUT/review/index.html` + `img/` |

`run_slim.sh OUT [candidates.txt] [jobs]` runs steps 1–3. Set `PYTHON` to the environment's interpreter. Each
decimation job can take several GB on the largest parts; `jobs` = 2 is safe with 16 GB.

## The check (step 2)

Each part is decimated at 25 %; if that passes it tries 15 % then 8 %, if it fails it tries 50 %. The most reduced
passing copy is kept. A copy passes when, sampled as densely as the original:

- 99th-percentile normal angle to the original ≤ the original surface's own noise floor + 0.8°,
- share of samples over 5° ≤ floor + 0.15 percentage points,
- 99th-percentile distance excess ≤ 0.25 of a median edge.

The floor is the original compared with a second sampling of itself, so rough or folded surfaces (pancreas 52°,
tooth marrow 60°, thin skin 22°) have a high floor and the test is conservative there. Parts made of many pieces
are sampled at least `PER_PIECE` points per piece.

**Known blind spot.** The check is a percentile over the whole part, so a small local change can pass. Example: the
pancreas acinar cells at 25 % turn the gap between two cells on a cut face into a sloped dark wedge (visible only
in a close-up). Cause: `simplify_test_lib.clean` welds coincident vertices, which fuses touching cells
(8,554 pieces become 1,584) before decimation. Look at the close-ups; a fix would weld only within each original
piece.

## Normals of the copies (step 3)

`slim_stage.py` gives each copy area-weighted smooth normals of its own shape, split at creases over 60° only when
the original has hard edges (positions carrying more than one normal). Copying the original's normals onto the
coarser shape was tried and showed blotchy facets on noisy, nearly flat surfaces (bladder connective tissue).

## Applying approved copies

1. Copy `OUT/staged/<path>` over `data/local_model_library/<path>` for each approved model (paths come from
   `data/local_model_library/library.json`). The file format is unchanged; the runtime checks no hashes.
2. Files over 100 MB must stay under Git LFS (`.gitattributes` lists them; jejunum, duodenum, colon, pancreas,
   neuron and kidney already are).
3. `python tools/check_lessons.py` must print OK, then open each model once in the app and look at the cut face.
