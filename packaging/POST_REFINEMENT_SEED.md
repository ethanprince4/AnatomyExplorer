# Post-refine release model seed

Set `AE_BUNDLE_MODEL_LIBRARY` to the completed editable library. Packaging reads it without modifying it and creates an isolated temporary staging directory under `packaging/build/stage/release-seeds`. The manifest placed in the release contains only each selected model's `post` variant. Only its primary file, declared runtime controls, companions and components are copied. Pre variants, review reports, history, preferences and unreferenced geometry are not collected. JSON contents do not trigger recursive collection of incidental source paths.

Every selected row must have a post variant. A build reports all missing model IDs in one actionable error and refuses to substitute pre files or silently omit models. Finish those models before releasing, or explicitly select a smaller manifest if a partial release is intended. Missing declared supporting files also identify the model and path. There are no geometry/lineage/hash validation gates.

The build spec accepts absolute paths from the temporary stage. These directories remain alive for the PyInstaller process and are released on process exit. Staging inside the editable library is rejected. Merely updating this helper does not import active refinement outputs or run a release build.

When a release seed is selected, the spec excludes obsolete `data/micro_cache` and `data/models` baseline folders. The local runtime resolves explicit manifest paths and does not need those builder caches. Protected approved GLBs in `models/` remain a separate bundled source; the whole-body atlas in `data/anatomy`, study images and authored adapter JSON remain unchanged. The post-only rule applies to the refined model seed, not removal of these protected reference/atlas assets.

## Portable export for Git/release preparation

After the run has finished and the intended completed source library is selected, export into a new or empty folder:

```powershell
python packaging/model_library_seed.py 'C:/path/to/completed-library' --output 'C:/path/to/application/data/local_model_library'
```

The exporter leaves the source untouched, refuses nonempty output targets, retains model IDs, and normalizes public titles through `app.variants.display_names.display_name`. The result is a standalone portable directory, unlike the build-only temporary stage. It can be staged into the release repository after inspection. Exporting is not performed automatically while refinement is active.

Protected GLBs are resolved separately by `app.config.ROOT / metadata["file"]`. In a source launch ROOT is the application directory; in a frozen app it is the PyInstaller resource directory. Matching `.viewer.json` sidecars should travel alongside their approved GLB files. Copy their existing relative `models/` subdirectories into that ROOT; do not point the app at a different source checkout just to find assets.
