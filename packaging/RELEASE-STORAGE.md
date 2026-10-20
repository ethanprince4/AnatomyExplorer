# Release runner storage

GitHub documents 14 GB of SSD storage for the standard Windows and Apple-silicon
Mac labels used here. Its runner-image maintainers clarify that this is a minimum
**free-space** promise, rather than the filesystem's total capacity. Actual free
space varies with the image. See [the runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
and [the maintainer's disk-space explanation](https://github.com/actions/runner-images/issues/10511).

The successful [19 October 2026 release run](https://github.com/ethanprince4/AnatomyExplorer/actions/runs/39331758511)
used Windows `windows-2025-vs2026` image `20261007.264.1` with a `D:\a` workspace,
and Mac `macos-14-arm64` image `20260831.0302.1`. Its logs do not record free disk
space. Its old Windows app was 3,137,271,564 bytes, with 2,817,019,597 feed bytes
and an approximately 2,711 MB installer. The Mac app was 3,072,362,713 bytes,
with 2,784,349,978 feed bytes and an approximately 2,791 MB DMG. Those figures
describe the older NPZ release and are not a budget for the new GLB library.

## Bounded preparation

`prepare_release_runner.py` runs only in a fresh GitHub-hosted checkout with an
Actions run ID. It removes unselected model inputs from that disposable checkout,
selects exactly the LFS objects needed by the post-only seed and other shipped
data, and writes their cache key. Historical unselected NPZ LFS objects are not
downloaded. LFS checkout files share the verified object-cache bytes by hardlink.

The initial free-space target is `max(40 GiB, 5 × selected asset bytes + 8 GiB)`.
The selected size uses LFS declared lengths when the checkout still has pointers.
This reserves room for compressed outputs, a full Windows installation and the
unchanged production Mac updater reserve. If needed, preparation removes only
unused preinstalled toolchains: alternate Xcode applications while retaining the
entire selected Xcode, Windows Android/modern .NET SDKs on the affected volume,
or unused Linux publisher SDKs. Paths and hosted-runner identity are checked
before removal. Python, Node, Git, GitHub CLI, Windows .NET Framework C# compiler,
Inno Setup and the selected Apple compiler/SDK remain available.

## Copy lifetime

`AE_RELEASE_HARDLINKS=1` is restricted to GitHub-hosted builds. It shares immutable
model files between source, temporary post-only seed and final app; ordinary
developer builds and portable exports retain independent copies. Code and
binaries undergoing signing remain independent. The Mac spec builds its BUNDLE
directly from EXE and the collected tables, a [supported PyInstaller input](https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/building/osx.py),
so it no longer produces an unused full COLLECT folder first. After signing,
the read-only DMG staging tree shares the sealed application's bytes, and its
signature is verified before image creation. Distribution files still contain
all selected models and companions, with no dependency on build-time paths.

Temporary directories use the runner's workspace volume. This allows native
update fixtures to reuse unchanged data on the same filesystem. A cross-volume
link failure falls back to an independent copy only after checking available
space; it never substitutes or drops an asset.

## Exact per-run budget and remaining verification

Build logs now record actual bundle bytes `B`, feed bytes `P`, installer/DMG bytes
`I`, and free bytes. Shared model links eliminate the repeated full-library
allocations; staging metadata and normal code/runtime caches still use storage.
The full Windows install check additionally needs `B + 256 MiB`. The Mac update
check still requires `2B + 256 MiB` free according to the production updater's
conservative guard. Splitting an oversized installer temporarily needs another
`I + 256 MiB` while the original and all parts coexist. These checks are logged
before their respective operations.

The Mac user-facing helper also reads the actual uncompressed bundle size from
the adjacent update manifest. It embeds that size in `install.sh` and requires
`2 × DMG bytes + uncompressed app bytes + 1 GiB` on the download volume, plus
the app and reserve on the destination volume. This covers parts, the joined
image and the staged replacement while the previous installed app remains
available. Generated install notes use the same calculation; the website avoids
the obsolete fixed 8 GB estimate.

Tiny local tests prove shared-file identity, copy fallback, selected-only LFS
selection, exact seed contents and the local-session cleanup guards. They do not
establish native Mac signing or actual free space in a future hosted image.
The next complete release build must confirm its logged budget and retain all
existing native install, signing, HTTPS and incremental-update checks.
