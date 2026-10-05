# Combined application release preparation

The application still updates from **ethanprince4/AnatomyExplorer**. Its HTTPS,
GitHub manifest digest, downloaded chunk integrity, activation and rollback
mechanisms remain intact. These checks protect executable downloads; the local
model library does not require geometry hashes, generation lineage or a batch
preparation certificate.

## Library locations

- The combined development launcher selects its sibling `model-library` using
  `AE_LOCAL_MODEL_LIBRARY`.
- Installed Windows applications use `%LOCALAPPDATA%/AnatomyExplorer/model-library`
  when that library has a `library.json`. macOS uses the existing application
  user-data location under `~/Library/Application Support/AnatomyExplorer`.
- A release can contain a read-only initial library at
  `data/local_model_library`. User selections are saved outside the application.
  External models override matching seed models individually; untouched seed
  models remain available. Updates replace the seed, never the user's external
  library.

The updater rejects `model-library` directories inside application payloads.
The differently named read-only `data/local_model_library` is allowed. The
installer only replaces application files; no uninstall deletion rule targets
the external library.

## Preparing a release with models

Use a portable library whose manifest paths are relative to its folder. Keep
only the models intended for distribution there, along with their companion
files and appropriate attribution. Personal `preferences.json` is excluded.
The collector checks file availability and portable paths, not model lineage or
anatomical certification. It does not build or refine any model.

```powershell
python packaging/build.py --version vX.Y.Z --model-library "C:\path\to\release-library"
```

Replace `vX.Y.Z` with the approved version. For the existing GitHub release
workflow, put the intended seed under `data/local_model_library` in the release
source (use the repository's existing large-file storage policy for large
assets). The spec discovers it automatically. `--model-library` provides an
alternative without copying a second library into the source tree. New
`app/variants/local_library.py` code is collected automatically with the rest of
the `app` package.

The seed is optional at the code level so source-only builds remain usable.
**Before publishing a model-bearing release, include the intended seed and
verify it in a fresh installation without an external library.** An absent seed
does not automatically download the accepted models from this local computer.
Ordinary bundled atlas and legacy models continue to follow existing packaging.

## Verification and publication boundary

```powershell
python packaging/test_local_library_release.py
python -m unittest tests.test_updater tests.test_updater_channels tests.test_update_packaging tests.test_fixture_paths -v
```

The additional offline test builds actual tiny update packs, prepares and
activates an update, rolls back, cleans old versions, and checks that accepted
external files and preferences are unchanged. It also checks the seed/personal
data boundary. This is not a graphics test or a frozen installer test.

The existing release workflow still performs Windows installer/runtime checks
and native macOS Cocoa/signature/update checks. Missing upstream packaging,
license and reusable workflow files were restored from official repository
commit `f341499f47028c01b436c17e8556d4a129556273`; the restoration inventory is
`packaging/UPSTREAM_RESTORED.json`. Existing graphics behavior was not redesigned.

Local validation has **not** built or signed a release, published assets, or
demonstrated a native Mac launch. Check the pull request's current Actions status
for remote platform results. A release still requires the accepted model assets,
dependencies and platform build checks; opening the code pull request does not
publish a release.
