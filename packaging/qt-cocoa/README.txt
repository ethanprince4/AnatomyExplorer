Qt 6.11.2 Cocoa ownership repair for Apple-silicon Anatomy Explorer

This is a locally rebuilt arm64 plugin, not a released upstream Qt fix.
Qt Gerrit 765434 patch set 1 is NEW/unmerged. The exact patch, modified
Cocoa plugin sources, build wrapper, upstream licenses and original native
acceptance evidence are included here. The Qt wheel frameworks are unchanged.

Exact source: https://github.com/qt/qtbase/tree/ef55f427f2c8b410d34f8a7681020a3000cf6866
Patch: https://codereview.qt-project.org/changes/765434/revisions/c7fd3f34b997bb363be15650647665b3b6b8a5f4/patch
Build recipe: packaging/diagnostics/mac_ax/ownership_candidate/build.sh
Accepted run: https://github.com/ethanprince4/AnatomyExplorer/actions/runs/36783679697

Baseline unchanged 6.11.2 plugin reproduces the selected-first two-column
native accessibility crash; one-column survival also destroys accessibility.
The repair passed all five fresh-process native controls, 150 getter calls,
with usable AXOutline hierarchy, matching selection counts and no framework
changes. These are runner results, not a physical macOS 26.6.2 validation.

Minimum macOS is 13.0. The binary is arm64 only. install_cocoa.py pins the
accepted full hash and exact matching wheel. check_cocoa.py additionally
requires all file-backed sections unchanged after PyInstaller link edits
and signing, the final loaded plugin identity and all five native controls.

Source and build files are supplied for rebuilding and replacing this LGPL
component. The application's MIT license does not replace Qt's licenses.
