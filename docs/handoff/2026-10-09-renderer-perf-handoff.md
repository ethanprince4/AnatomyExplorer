# Handoff: renderer performance, 9 October 2026

- **Branch:** `claude/renderer-perf`.
- **Release:** v4.0.6 ships the new wgpu renderer for the model viewer.
  - It is on by default on macOS and off elsewhere.
  - Turn it off in Settings > Display > "Fast renderer for models (new)", setting `fast_renderer`.
  - `ANATOMY_RENDERER=opengl|wgpu` overrides the setting.
- **Results:** [renderer-perf/2026-10-09-report.md](../renderer-perf/2026-10-09-report.md) has the numbers, the M1
  estimate, the 250M results (culling only, and culling + the existing LOD), memory, and what is left.

## v4.0.7 and GitHub checks

- v4.0.7 adds the Mac bug-hunt fixes (two accessibility crashes, Back/Forward, saved views, UI glitches). The
  report, per-fix notes and the Mac harness are in `docs/bughunt-2026-10-09/`.
- Pull requests run no GitHub checks. Of 31 failed check runs, only a few were real bugs: a file missing from the
  installers, wrong picking on Mac, and a Windows line-ending import failure. The rest were test, runner or
  workflow problems.
- What remains is in `release.yml`, run only for a release:
  - the Mac picking check;
  - both installer builds, with their checks on the built app: install, frozen imports including wgpu and the
    shaders, HTTPS, Cocoa plugin, Mac update.
- `updater-tests.yml` and `mac-diagnostics.yml` were deleted. The Qt Cocoa plugin rebuild they hosted is in git
  history and in `packaging/diagnostics/mac_ax/ownership_candidate/`.
- Run the test suite locally before a release.

## Rules the user set (still in force)

- **Models are off limits.**
  - Never write `.npz` model files or anything that produces them.
  - Never add coarser or simplified copies of geometry.
  - The existing LOD (`app/viewer/lod.py`) stays exactly as it is.
- **Allowed:**
  - reorder triangles and vertices;
  - compress vertex data invisibly;
  - skip what cannot be seen in the current frame.
- **The picture is the test.** It must look the same from the current viewport as the unoptimised render,
  including with layers hidden, ghosted, cut or exploded.
- Details: [renderer-perf/2026-10-09-diagnosis.md](../renderer-perf/2026-10-09-diagnosis.md).

## First thing on a Mac

Run [renderer-perf/mac-checklist.md](../renderer-perf/mac-checklist.md). v4.0.6 is the renderer's first run on Metal.

- Items 1, 8 and 9 decide whether the picture and the culler are right there.
- Item 10 gives the real speed.
- If a model looks wrong, turn the setting off, note the model and view, and compare with
  `ANATOMY_RENDERER=opengl`.

## In progress on the branch after v4.0.6 (not in the release)

One builder was still running when v4.0.6 was cut. Its notes are in the session scratchpad
(`.../scratchpad/gpu_port/l3/HANDOFF.md`). The lead's handoff is
`C:/Users/Ethan/Desktop/AnatomyExplorer/.claude/handoff/HANDOFF.md`.

- **Geometry compression stage 1** (26 -> about 19 B/tri GPU memory).
  - Vertex first-use order plus 16-bit cluster-relative indices.
  - Compressed models always draw through the culler (accept-all when culling would be off).
  - Built in a snapshot and being checked; it merges into the branch with `git merge-file` when the gates pass.

## Next, ranked (details in the report's "What is left")

1. The Mac checklist.
2. Compression stage 2: positions to 16 bits per axis in 64-vertex blocks. It is needed for the 250M atlas on an
   8 GB Air.
3. Cut views:
   - classify clusters against the cut plane, so only those that straddle it use the discarding shader (-58 ms
     UHD pancreas);
   - cache the caps plan between frames.
4. Zoomed-out overflow on integrated GPUs: a larger culler budget, or a per-frame fallback to the plain draw.
5. Screen-space passes: about 10-15 ms on the UHD of invisible savings are listed in the report.
6. Re-choose `ANATOMY_CULL_MIN_TRIS` at 4x MSAA with small models (tongue_papillae is faster culled).
