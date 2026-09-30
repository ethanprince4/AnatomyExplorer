# Focused picking capture on the affected Mac

Publication remains on hold. These controls localize a failure; a Windows pass
does not establish a Mac fix. Use a parent-reviewed diagnostic source checkout
or private build. Do not change Gatekeeper, accessibility, or other OS policies.

The default user handoff is one run of the parent's combined frozen diagnostic
(GPU controls, TLS, and installed-runtime identity). The standalone commands
below are engineering entry points. A physical native trace is separately
optional only if the parent later requests it; it is not required for the
single-action handoff.

1. Run the invisible controls first (no atlas or model assets are loaded):

   ```sh
   python -m app.picking_diagnostics --gpu-controls-only --report "$HOME/Desktop/picking-gpu.json"
   ```

2. If requested separately, run a short physical-input capture in the actual `MainWindow`. Its settings
   writes, study storage, and worker cache writes are isolated in a temporary directory; its genuine
   `QMenu` and handlers are used. Add `--use-saved-view-settings` only when copying
   the affected installation's saved view preferences is useful. It copies them
   read-only before creating isolated diagnostic settings.

   ```sh
   python -m app.picking_diagnostics --native-trace --seconds 120 --report "$HOME/Desktop/picking-input.json"
   ```

   Wait for `ready_for_physical_input`, then click the forearm and note the exact
   displayed name and side. Click empty background. Right-click the same forearm
   and note whether a native popup is physically visible. Dismiss it, or choose
   Hide and note whether the clicked anatomy and visible count change. Close
   the capture window. Do not open model tabs or reproduce the separate tree
   accessibility crash as part of this picking capture.

   Frozen private builds use the same flags through their executable:

   ```sh
   "/path/to/PRIVATE diagnostic.app/Contents/MacOS/AnatomyExplorer" --pick-diagnostics --gpu-controls-only --report "$HOME/Desktop/picking-gpu.json"
   "/path/to/PRIVATE diagnostic.app/Contents/MacOS/AnatomyExplorer" --pick-diagnostics --native-trace --seconds 120 --report "$HOME/Desktop/picking-input.json"
   ```

Send the two JSON files and the observed anatomy/menu behavior to the parent
investigator. Reports include OS/GPU/driver, exact Qt/PySide patch versions,
current FBO/read buffer, component/internal formats, completeness, GL errors,
read clamp state, fixed expected values, mapped pixels, camera/frame state,
raw RGBA/depth, and exact dataset ID names/hash. Input reports are flushed at
each event so evidence preceding a native crash survives. A Qt menu Show or
aboutToShow observation does not by itself prove physical popup visibility.

The fixed encoded values are 2, 257, and 3922 (decoded IDs 1, 256, and 3921).
First a uniform supplies them; then an indexed VAO supplies object IDs through
the production `3f 3f u2 u2` format. A third oracle uses the actual Renderer
constructor, `GEOMETRY_VS`/`OPAQUE_FS`, opaque VAO, state/material textures, and
`Renderer.render` with a fixed CPU triangle and identity camera. Its occupied
pixel must contain the fixed encoded value at depth 0.5; its background must
contain 0. All three use the same production Renderer G-buffer attachment 2
and `Renderer._read_float/pick` readback. No expectation is derived from an
atlas GPU buffer. Shader source hashes and optimized VAO format are recorded. The
native GL_FALSE read is a scoped comparison and restores state; it is not a
renderer change. Controls overwrite only the isolated frame and redraw the
atlas before input capture.

| Result on affected Mac | Next investigation |
| --- | --- |
| Uniform fails | Float target/readback/draw state; examine format, bindings, errors, and native FIXED_ONLY versus GL_FALSE reads |
| Uniform passes; integer attribute fails | Packed integer VAO stride/offset/type, buffer upload, or shader input path |
| Basic controls pass; production path fails | Production shader/VAO/state/render path |
| All three pass | Actual atlas mesh IDs/association, frame freshness, physical pointer mapping and MainWindow event state |

The historical exact symptom maps encoded 1 to ID 0, *Posterior transverse
collateral sulcus (left)*, while background encoded 0 clears selection. This
is a discriminator, not proof of clamping. Atlas candidate IDs still come from
the same buffer and only demonstrate consistency with that buffer.

For an opt-in automated GPU regression in its own subprocess:

```sh
ANATOMY_GPU_DIAGNOSTICS=1 python -m unittest discover -s tests -p test_picking_diagnostics.py -v
```

Native queries use typed calls resolved by the current Qt context's
[getProcAddress](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QOpenGLContext.html).
Read-color clamp semantics are defined by the
[Khronos color-buffer-float specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_color_buffer_float.txt).
In FIXED_ONLY mode a floating-point read buffer is not supposed to clamp values
to [0,1]; an actual affected-device result is required before attributing its
symptom to clamp state or a driver defect.

The optional native UI regression uses synthetic Qt events, keeps the actual
MainWindow/QMenu/Hide code, and records `synthetic_test_driver=true`. It can show
that route works on its test device; physical Mac behavior remains a separate
check. Capture flags `picking_validated` and `physical_menu_visibility_validated`
remain false until external observation is assessed. Capture callback/sample
errors mark the report incomplete and fail its diagnostic-health result.
