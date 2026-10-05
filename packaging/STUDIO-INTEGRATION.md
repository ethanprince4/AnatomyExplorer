# Stronger UI and independent model library

The supplied Study-02 Porcelain/Cobalt design now wraps the real Qt application.
Explore, Learn and Collection route to existing application state. Global search,
saved views, menus and study actions retain their production owners. Model tabs
use the native renderer with Parts, Reveal and Section cards and a compact dock;
the prototype's static scene images are not shipped as a replacement viewer.

The Collection workspace offers independent Before/After model choices. Local
models do not require all models to finish together or carry lineage receipts.
Importing a saved result creates a new local revision and preserves rollback.
Optional incompatible metadata is reported; it does not block the whole library.
Available inset files load independently, with their own cameras and scale.

## Bringing in accepted models later

`tools/import_refiner.py` imports selected saved refiner results into a portable
library. The combined Desktop launcher selects its sibling model-library folder.
Installed applications merge an optional bundled seed with per-model external
overrides. See COMBINED-RELEASE.md for release seed and updater details.

No refined 3D models are included in this code change. Existing repository model
assets remain the baseline until accepted replacements are supplied.

## Validation scope

Focused tests exercise actual Qt widgets, navigation, card visibility, responsive
study layouts, native loading, import/rollback, and updater preservation of user
models. They do not use screenshots or anatomical visual judgments. The broader
existing release workflow normally runs on pull requests and performs platform checks.
This initial draft is submitted with CI skipped at the user's request to avoid
restarting the extended diagnostics/build cycle. Platform checks remain pending.
An earlier full local discovery stalled and was stopped; focused local results
must not be read as proof that every platform test or signed installer passed.

This work preserves the existing graphics approach. It does not introduce a GPU
requirement for users, pre-rendered scenes, or an additional renderer redesign.
