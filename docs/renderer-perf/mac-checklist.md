# Mac checklist for the wgpu host (cannot be checked on the Windows build machine)

Run from the repo root with the project venv (`python` below). `ANATOMY_RENDERER=wgpu` selects the wgpu viewport;
`ANATOMY_PRESENT_MODE=sync|async` selects the present mode (default async).

1. Adapter selection (Metal). `python -c "from app.gpu.device import list_adapters, get_gpu; print(list_adapters()); print(get_gpu().info)"`
   Expect a Metal adapter, not "CPU" and not OpenGL. On a dual-GPU Mac try `ANATOMY_WGPU_ADAPTER=Intel` / `=AMD` and confirm
   `get_gpu().info` changes. Check `get_gpu().prim_index` (primitive-index is not expected on Metal; the renderer must
   take its vertex-pulling path) and `get_gpu().limits["max-storage-buffer-binding-size"]`.
2. HiDPI image scaling. `python tools/perf/gpu/present_bench.py --frames 120 --work-ms 0` on a Retina display (no
   `QT_SCREEN_SCALE_FACTORS` override: edit `perfkit.env_setup` or run `tests/gpu/test_host.py`). Confirm
   `physical == width*devicePixelRatioF`, and that a 1-pixel checker pattern (`StandInRenderer(pattern=True)` in a `GpuWidget`)
   looks sharp, not blurred or shifted: `QT_QPA_PLATFORM=cocoa python -m pytest tests/gpu/test_host.py -q -k qpainter`.
   Also drag the window between a Retina and a non-Retina screen and check the texture is recreated (no stretched frame).
3. Translucency over the 3D view. `ANATOMY_RENDERER=wgpu python -m app` (or `main.py`), open a model, turn labels on and
   hover: label cards and the measure overlay must blend with the model underneath (the Overlay child widget is translucent).
   Compare against `ANATOMY_RENDERER=opengl`. Check the card edges and the orientation gizmo for dark fringes.
4. Event loop during async map. `python tools/perf/gpu/present_bench.py --modes async --frames 400` then
   `python -m pytest tests/gpu/test_host.py -q -k "async or repaint"`. The async path polls the map with a 1 ms
   `QTimer`; confirm no frame is lost when the window is idle (last frame shown), while a modal dialog or menu is open
   (nested event loop: open the File menu during auto-rotate and check the view keeps updating), and while resizing.
5. wgpu native library in the PyInstaller bundle. Build with the project spec and run
   `./dist/<app>/<app> --version`-style launch with `ANATOMY_RENDERER=wgpu`; then list
   `find dist -name "libwgpu_native*"` (must be present; packaging/AnatomyExplorer.spec has no wgpu entry, so this relies on the hook shipped in
   site-packages/wgpu/__pyinstaller; if missing add `collect_dynamic_libs("wgpu")` and `collect_data_files("wgpu")`) and
   `otool -L dist/.../libwgpu_native.dylib` (only system frameworks). If the bundle starts but falls back to OpenGL,
   run `ANATOMY_RENDERER=wgpu` from a terminal and read the logged reason (`wgpu renderer unavailable, using OpenGL`).
6. Code signing and notarisation of the dylib. `codesign --verify --deep --strict -vv dist/<app>.app` and
   `codesign -dvv dist/<app>.app/Contents/Frameworks/**/libwgpu_native.dylib` (same identity and hardened runtime as the
   other libraries), then `spctl --assess --type execute -vv dist/<app>.app` after notarisation. An unsigned or re-signed
   dylib makes dlopen fail under the hardened runtime: look for "code signature invalid" in `log show --last 2m --predicate 'process == "<app>"'`.
7. Frame pacing at 60 Hz / 120 Hz. The host caps repeat renders to the screen refresh rate (`GpuWidget.frame_cap_hz`, `None` =
   `QScreen.refreshRate()`). On a 60 Hz and a 120 Hz (ProMotion) display run auto-rotate for 30 s and read the interval
   statistics: `python tools/perf/gpu/present_bench.py --frames 600 --work-ms 4` after setting `vp.frame_cap_hz = None` in
   `run_case` (default there is uncapped). Expect mean about 16.7 / 8.3 ms with p95 under 1.2x the mean and no 2x spikes;
   compare `--modes sync` and `--modes async`. Also check that an idle window uses about 0 % CPU (no render loop).
