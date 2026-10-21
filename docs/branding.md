# Layered Human branding and upgrade compatibility

Public application names, download helpers, shortcuts and release titles use
**Layered Human**. New builds produce `LayeredHuman.exe`, `Layered Human.app`,
`LayeredHuman-Setup-Windows.exe` and `LayeredHuman-macOS-AppleSilicon.dmg`.
Oversized releases publish `Install-Layered-Human-Windows.exe` and
`Install-Layered-Human-Mac.dmg`; the Mac helper opens as **Install Layered Human**.
Preview builds use **Layered Human Experimental**. Source setup creates a
**Layered Human** shortcut, and its console-free launcher is `Layered Human.bat`.
The PyInstaller specification is `packaging/LayeredHuman.spec`.

## Intentional compatibility names

- The repository stays at `ethanprince4/AnatomyExplorer` for now, by the owner's
  choice. Installed v4.0.10 and older clients require that exact repository
  prefix in GitHub asset metadata. A GitHub redirect alone cannot satisfy their
  check after a rename. The retained legacy transport binds all packs to their
  manifest's exact repository and release. The active 4.0.12 client instead uses
  the fixed Cloudflare origin and needs no GitHub access for subsequent updates.
- Both stable and experimental Inno Setup AppIds are unchanged. Upgrades find
  their existing installation directory; fresh installations use the new name.
  The installer replaces the old named shortcuts with Layered Human shortcuts.
  The macOS bundle identifier stays `io.github.ethanprince4.anatomyexplorer`
  (with `.experimental` for previews) to preserve its installed identity.
- Qt's `AnatomyExplorer` / `Anatomy Explorer` settings identity, application-data
  folders, external model-library and model-variant stores remain unchanged.
  Saved notes, progress, preferences and user-installed models retain their
  established locations. The source-review preference identity also remains
  unchanged.
- New bundles include a regular-file `AnatomyExplorer.exe` or
  `Contents/MacOS/AnatomyExplorer` alias of the new executable. Already installed
  immutable launchers require these paths. Their staged Mac update folder is
  still `Anatomy Explorer.app` inside private update storage; the new public
  installed bundle is `Layered Human.app`. Updating an existing Mac installation
  preserves its original fallback bundle and its original outer filename.
- New releases publish `LayeredHuman-Windows-update.json` and
  `LayeredHuman-macOS-update.json` alongside the old `AnatomyExplorer-*` manifest
  filenames. The Windows compatibility manifest omits only `LayeredHuman.exe`,
  a root path older validators reject. Both manifests use the same chunks and
  `AnatomyExplorer-{Windows,macOS}-pack-NNNN.bin` files. Old clients stage and
  launch the compatibility executable; new clients prefer the public executable.
  Mac manifests are identical, and neither is inserted into the signed bundle.
- Camera-feed filenames, screenshot PNG metadata keys and review-tool locks
  retain their existing `AnatomyExplorer` identifiers so captured files and
  existing tools remain interoperable. Source asset paths, authored credits,
  old release notes, crash reports and historical handoffs retain their factual
  names. Third-party authors and licence terms have not been renamed.

## Future repository rename

Keep the GitHub bridge available at the current address for older clients.
Clients that receive 4.0.12 use Cloudflare independently of the repository name.
Clients that miss the bridge still need a manual
installation after a rename unless an old-address compatibility feed is kept.
Do not promise uninterrupted updates for those clients based on redirects.
Keep the old protocol manifests, executable aliases, pack names and install/data
identities for as long as supported immutable launchers need them.

## Validation boundary

Source checks cover new and old manifest selection, exact repository binding,
legacy-validator acceptance, staging, activation and rollback with tiny local
packages. The release workflow retains first-install verification on disposable
Windows CI and actual signed bundle checks on macOS. Source tests do not replace
those native release checks. No installer should be registered on the owner's
desktop merely to test this rename.
