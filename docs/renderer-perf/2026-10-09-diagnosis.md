# Renderer performance: diagnosis and design rules (2026-10-09)

Branch `claude/renderer-perf`. Local commits only; nothing is pushed.

## Goal and rules (from Ethan)

- Remove the lag in the 3D views (seen on an M-series MacBook Air while rotating and zooming heavy micro models).
- Scale to the coming whole-body atlas: about 5,000 structures, about 250M triangles in total, delivered as `.npz`.
- Target: an M1-class MacBook Air at 60 fps. If a scene cannot reach that, the reason must be the chip itself
  (throughput or memory), never our framework.
- **Models are off limits.** Never write to any `.npz` model file or to anything that produces them. How the
  files are read, stored on the GPU and drawn is fair game, as long as the picture looks the same.
- Allowed: reorder triangles and vertices; compress vertex data (differences far below what can be seen);
  skip drawing anything the viewer cannot see in the current frame (off screen, hidden behind other visible
  geometry, smaller than a pixel).
- **Never** add coarser or simplified copies of geometry, not even while the camera moves.
- The picture from the current viewport must look the same as the full, unoptimised render of the same state.
  This includes states where the user has hidden outer layers, ghosted parts, cut the model or exploded it:
  whatever is exposed must render correctly.
- Any backend is allowed (moderngl, wgpu, Rust). The current renderer stays available behind a switch until
  the new one has been checked on a Mac.

## Two live renderers

| | Atlas (Z-Anatomy) | Model viewer (library, micro, GLB) |
|---|---|---|
| Widget | `app/viewport.py` `Viewport`, built at `app/main_window.py:143` | `app/viewer/viewport.py` `ModelViewport`, hosted by `app/ui/model_view.py:131` |
| Renderer | `app/renderer.py`, shaders `app/shaders.py` | `app/viewer/renderer.py`, shaders `app/viewer/shaders.py` |
| Data | `data/anatomy/vertices.bin` (28 B/vertex) + `indices.bin` (uint32) via `app/data.py:109` | `.npz` (deflate-compressed members, delta-coded indices) via `app/variants/local_runtime.py:79 decode_local_npz`, then `app/viewer/lod.py` |
| Vertex size | 28 B | 76 B (plus 36 B animation stream when animated) |
| GLSL | `#version 410 core` | `#version 410 core` |

The new atlas arrives as `.npz`, so the model-viewer path is the one that must scale first.

## What the existing "sub-pixel LOD filter" really does

`app/viewer/lod.py` builds coarser copies of large parts at load time; `app/viewer/renderer.py:385-402`
(`_lod_levels`) picks, per part and per frame on the CPU, the coarsest level whose error is at most one pixel.
Parts are never dropped for being small. Ethan is happy with how it looks, so it stays exactly as it is
(including in any new backend), but nothing new of that kind may be added.

## Findings (static read; to be confirmed by the benchmark)

### Model viewer, GPU side
1. Anti-aliasing: 8x MSAA by default, 4x when the effective pixel ratio is 1.5 or more (`app/viewer/viewport.py:54-59, 226`);
   render scale up to 2.0 with no pixel cap (`:214`). Frame targets are about 22 B per pixel per sample
   (`app/viewer/renderer.py:602-605`): roughly 0.6 GB at 1080p and 8x, over 2 GB at Retina scale 2.0.
2. Forward shading on dense meshes: `MAIN_FS` does 3 lights x 16 PCF shadow taps, 3 `inverse(mat3)`, environment
   taps, AO and two fbm noise evaluations per fragment (`app/viewer/shaders.py:600-611, 661, 671`). With
   millions of tiny triangles, every triangle shades at least a 2x2 quad, so this cost multiplies.
3. The transparent (weighted-blended OIT) pass repeats the full lighting (`shaders.py:759-810`).
4. Shadows are re-rendered while orbiting: the caster set depends on frustum culling and is part of the shadow
   cache key (`renderer.py:911, 915, 919-955`). Up to three extra geometry passes per frame.
5. Geometry passes per frame: prepass + shaded + OIT + up to 3 shadow passes + cut-face passes.
6. Full-screen passes: SSAO with up to 96 extra GI march taps per pixel (`shaders.py:183-277`), blur, composite
   with 13-tap edge searches (`:1040-1061`).
7. Draw calls: runs merge only when consecutive and with identical transforms (`renderer.py:473, 499-502`);
   textured parts never batch (`:165-166, 490-492`). Worst case is one draw per part per pass.
8. One VBO and one uint32 IBO for the whole model, no chunking (`renderer.py:307-383`).
9. `gl_FragDepth` writes and `discard` disable early depth rejection in several programs.

### Model viewer, CPU side
1. Full redraw on every mouse event and every frame while moving (`viewport.py:258-307, 683`).
2. Hover picking every 30 ms with synchronous 1x1 readbacks (`viewport.py:686-693`, `renderer.py:1272-1273`).
3. Per-frame allocations in `frame_state` (`viewport.py:331-351`) and per-frame settings parsing (`:221-237`).
4. Label recompute: full-frame id/depth readback and `bincount` (`viewport.py:745-836`); the cache key includes
   the camera, so every camera change refreshes it.
5. Loading: several full-size copies (`app/viewer/model.py:190-192`, `app/viewer/imported.py:253`), float64/int64
   intermediates in the glTF path (`app/gltf.py:139-170`), `np.add.at` normals (`model.py:122-130`),
   O(groups x items) `_group_sid` (`model.py:651-660`), `deepcopy` in `model_loading.py:44-50`, deflate
   decompression of up to 390 MB `.npz` files on every open.
6. UI: `_filter_tree` is O(items) per keystroke (`app/ui/model_view.py:557-593`); `_sync_tree` is O(rows x sids)
   per visibility change (`:628-639`).

### Atlas
1. Hard cap: 4,096 structures (`app/state.py:4, 31`; `app/renderer.py:96`). The 5,000-structure atlas would fail.
2. Three full-buffer draws per frame (opaque, mask, transparent); hidden geometry is discarded in the vertex
   shader, so every pass processes every triangle (`app/shaders.py:61-71`, `app/renderer.py:492, 502, 562`).
3. Cut faces: about 8-10 GL calls and 2 draws per cap part per frame (`renderer.py:370-442`).
4. Labels: up to 180 synchronous single-pixel readbacks per paint, also during orbit (`app/viewport.py:711-734`);
   landmarks: up to 60 per-point depth reads (`renderer.py:678-688`); reference anchors read the whole id
   buffer and run scipy per settle (`viewport.py:843-900`).
5. Geometry is loaded twice on the GUI thread (`viewport.py:275, 766`).
6. Every drag and wheel event triggers a full render with no coalescing.
7. Resize recreates about 16 full-window targets (`renderer.py:254-295`).

## Hardware and API constraints for a new backend (wgpu 0.32 -> Metal / Vulkan / D3D12)

- macOS OpenGL stops at 4.1: no compute, no storage buffers, no indirect multi-draw. GPU-driven culling needs a
  new backend; wgpu is the chosen one (Metal on Mac).
- Metal has no multi-draw-indirect: use compute-compacted index lists or vertex pulling with one indirect draw
  per pass.
- M1 has no 64-bit atomics: no software rasterisation. Hardware-rasterised visibility ids (R32Uint) are fine.
- Apple GPUs cannot write timestamps inside passes: time at encoder boundaries.
- Only 256 MB per buffer is guaranteed: page geometry across several buffers; read `adapter.limits` at runtime.
- M1: 68 GB/s memory bandwidth shared by CPU and GPU, 8 GB total. 250M triangles at 60 fps is 15 billion
  triangles per second, which no laptop GPU can draw, so culling is required; memory requires compact vertices.
- Budget at 250M triangles: positions quantised to 16 bits per component within each part's box plus
  octahedral normals is about 10-12 B per vertex; cluster-local 8-bit indices are 3 B per triangle. Measured in
  the cull spike: 12.18 B per triangle including cluster records, about 3.05 GB at 252M, against more than
  12 GB in today's format. Existing LOD levels, per-frame index lists and frame targets come on top.
- Qt embedding: `rendercanvas.qt.QRenderWidget`. The `screen` present method uses a native child surface;
  `bitmap` copies through Qt. Today both viewers paint overlays on the GL widget itself, so a native surface
  needs a separate overlay widget.
- The Intel UHD 770 in this PC is the only weak-GPU stand-in for the M1, and only wgpu can target it.

## Culling must stay correct when the state changes

- Only geometry that is visible, opaque and unclipped in the current frame may hide anything. Ghosted,
  transparent and cut-away structures never occlude. Nothing about visibility is precomputed or baked.
- Hide/show, ghosting, clip planes, explode and the animation frame invalidate the previous frame's visible set
  (the two-pass occlusion scheme must not leave a one-frame hole).
- Part and cluster bounds include morph and explode displacement.
- The reference views for every check cover: default view, outer layers hidden then zoomed out, a cut plane,
  ghosted parts, mid-explode and mid-animation, each with click-result samples.

## Spike results (2026-10-09)

Details: `spike-embed-handoff.md`, `spike-cull-handoff.md`, baseline numbers in `baseline-summary.md`.

Baseline (RTX 3080, 2560x1600, pixel ratio 2, 4x MSAA): the model viewer is limited by per-pixel shading of
dense meshes, not by triangle count. Pancreas (25M triangles) orbits at 25-29 ms, of which the shaded main pass
is 16.5 ms and the depth prepass 5.5 ms; tongue_papillae (1.7M triangles) takes 21 ms and its cost moves with
the view angle. The atlas orbits at 4.9 ms with labels off. The current renderer fails at the 250M stress level
("out of range offset") at 16 GB of process memory; 150M is the last level that loads (51 ms per frame).

Qt embedding: present through `bitmap`. The `screen` method mis-blends translucent widgets over the 3D view.
Bitmap costs about 7 ms per frame at 2560x1600 on Windows for readback and blit, so the presenter must read back
asynchronously (double-buffered) instead of stalling the GUI thread. The overlay is already a separate QWidget.
`wgpu`, `rendercanvas`, `cffi` and (macOS) `rubicon-objc` are not yet in `requirements.txt`.

GPU culling (compute, wgpu, 9 real models tiled to 25M/100M/252M triangles):
- Two-phase hi-Z culling never removed a visible pixel: 0 false-cull pixels over 3 views x (cold, moved, 20% and
  50% hidden with no warm-up, re-shown) x 3 sizes x 2 GPUs. Shading from quantised data matched within 0.6/255.
- Quantisation error: positions 7.6e-6 of the part diagonal, normals 0.024 degrees.
- 252M, whole model in view: 25.6 ms (3080) / 646 ms (UHD 770); close view 14.7 / 375 ms; inside 1.6 / 40 ms.
  This run had no LOD. The UHD is limited by vertex setup (same time at 1280x800).
- Phase 2 draws 4-9x the clusters that end up visible (layered anatomy leaks through the depth pyramid).
- 64-triangle clusters are 22-33% faster than larger ones.
- Back-face (cone) culling is not allowed: the viewer draws both faces and open sheets change 1.4-2.4% of
  pixels without it. It may only become a per-part opt-in for proven closed meshes.
- Shadows are off by default and the lights follow the camera, so lighting needs no shadow passes by default.

## Port design (decided 2026-10-09)

1. New package `app/gpu/` on wgpu. The model viewer gets a wgpu backend behind a switch; OpenGL stays the
   default until the wgpu picture matches the references, and the app falls back to OpenGL automatically if wgpu
   fails to start.
2. First milestone, because it removes today's lag: a visibility buffer (MSAA, R32Uint ids + depth) and one
   per-pixel shading pass that reproduces today's look, with today's CPU part culling and the existing LOD.
   Cluster culling (part, then cluster frustum, then two-phase hi-Z) comes on top for the 250M atlas.
3. Two raster paths chosen at run time: indexed draws reading `primitive_index` where the adapter has it, and the
   spike's vertex-pulling path otherwise.
4. Geometry is paged across buffers sized from `adapter.limits`; on unified-memory Macs no CPU copy of uploaded
   geometry is kept (the prepared cache is memory-mapped).
5. Every existing pass is ported: OIT, cut caps, SSAO with its previous-frame GI read, edges/composite, picking
   with asynchronous readback, labels. Today's output is matched, including oddities; any intended change is
   written down.
6. Reference images use a fixed warm-up frame count in both renderers, because SSAO reads the previous frame.
7. Results at 250M are reported twice: culling only, and culling plus the existing LOD.

## Plan

1. Benchmark harness (`tools/perf/`): load, frame, per-pass GPU time, counts (draws, readbacks, passes, bytes per
   vertex), orbit run, stress ramp to failure, reference images and pick samples, image comparison.
2. Two wgpu spikes before any port: Qt embedding inside `StudioScene` with overlays (both present methods,
   2560x1600) and compute cluster culling on the stress scene (RTX 3080 and UHD 770).
3. Fixes that hold regardless of backend: CPU-side stalls, loading, UI scaling, atlas structure cap.
4. New wgpu core for the model viewer: compact vertex format, clusters, GPU culling (frustum, cone, hi-Z),
   visibility buffer, per-pixel shading, all existing passes and the existing LOD behaviour; then the atlas.
5. Every change is measured against the baseline and compared image by image.
