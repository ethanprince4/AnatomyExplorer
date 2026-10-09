# wgpu port: module layout and contracts (2026-10-09)

Read with `2026-10-09-diagnosis.md` (rules, findings, design) and `port-inventory/` (a map of today's GL code;
always port from the GLSL and Python themselves, the inventories only say where to look).

## Switch and fallback

- Setting `renderer_backend` = `"opengl"` (default) or `"wgpu"`; environment variable `ANATOMY_RENDERER`
  (`opengl` / `wgpu`) overrides it. Read where the model view builds its viewport (`app/ui/model_view.py:131`).
- If `wgpu` is chosen but the device, renderer or first frame fails, the model view builds the OpenGL viewport
  instead and logs the reason once. OpenGL stays the default until the wgpu picture matches the references.
- `ANATOMY_WGPU_ADAPTER=<substring>` picks an adapter by name (used to test on the Intel UHD 770).

## Modules (`app/gpu/`)

| Module | Owner | Contents |
|---|---|---|
| `device.py` | host builder | `get_gpu()` -> shared `Gpu` (adapter, device, queue, `features` set, `limits` dict, `info` string, `prim_index` bool); raises `GpuUnavailable`. One device per process, high-performance adapter by default. |
| `host.py` | host builder | `GpuWidget(QWidget)`: owns the output texture (rgba8unorm, physical size), presents it through Qt (bitmap path, asynchronous double-buffered readback, see below), keeps child overlay widgets on top. |
| `viewport.py` | host builder | `WgpuModelViewport(ViewportCore, GpuWidget)`. |
| `renderer.py` | core builder | `WgpuRenderer(gpu)` with the GL `Renderer`'s public API (below). |
| `geometry.py` | core builder | compact geometry, paging, upload, per-part draw ranges incl. existing LOD levels. |
| `wgsl/*.wgsl` | per pass | shaders; `wgsl/shading.wgsl` is the port of today's surface shading (`SHADING_COMMON`, `MAIN_FS`). |

`app/viewer/viewport_core.py`: `ViewportCore`, everything in today's `ModelViewport` that does not touch GL
(camera, input, labels logic, overlay painting, animation, measuring). `ModelViewport(ViewportCore, QOpenGLWidget)`
keeps today's behaviour exactly.

## Renderer API (same as `app/viewer/renderer.py` `Renderer`, see `port-inventory/i6_viewport_interface.txt` §1)

- `set_model(model)`, `release()`, `render(target, size, camera, s, fs=None, out_size=None)` where `target` is a
  `wgpu.GPUTexture` (rgba8unorm, usage RENDER_ATTACHMENT | COPY_SRC | TEXTURE_BINDING) of `out_size or size`.
- `pick(x, y)`, `read_ids()`, `read_depth()`, `read_label_samples(step)`, `ids_at(points)`,
  `world_from_pixel(x, y, d)`, `read_final(target, size)` -> (h, w, 3) uint8.
- Attributes `frame_ok`, `size`, `last_vp`, `samples`, `gl_info` (adapter description).
- `Settings` and `FrameState` are imported from `app.viewer.renderer`, never copied.

## Presenting

Render into the host texture, copy it into one of two mappable buffers, map asynchronously, paint the newest
completed image with `QPainter.drawImage`. A synchronous mode (same-frame) stays available behind a flag; the
host builder measures both at 2560x1600 and the faster one with at most one frame of latency is the default.

## Picture rules

- Match today's output, oddities included (for example stale uniforms in batched draws). Any intended change is
  written in `docs/renderer-perf/port-changes.md` with the reason.
- Shadows are always off in the model viewer (`app/viewer/viewport.py:106`); their code paths are not ported.
- References: `tools/perf/make_reference.py` renders each state through `grab_image`, which renders 3 frames
  before reading. SSAO reads the previous frame, so the wgpu history must start and reset exactly as GL's
  `t["opaque"]` does (check its creation, clearing and recreation on resize); otherwise comparisons drift.
- Compression of geometry must be invisible: report position, normal, colour and UV errors in numbers.

## Rules for every builder

`S/notes/BUILDER_RULES.md` applies (never write models or `R/data`, only your files, no git, GPU lock for timing,
no image viewing, compare by numbers, run tests, short reply). New tests go in `tests/gpu/` and skip when no
adapter is available.
