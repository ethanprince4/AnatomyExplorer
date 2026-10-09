# Handoff for the Mac session, 9 October 2026

You are on the user's Apple-silicon Mac, in a local checkout. Branch `claude/keen-ride-vm1yxr` (pushed, no pull
request yet). `main` is at v4.0.4 (`c3a1afb`). The main handoff is
[2026-10-09-handoff.md](2026-10-09-handoff.md), which has a status section at its top; read that first for the full
picture. This note is what to do on the Mac and what is deliberately not done.

**Do not ship 4.0.5 until the Mac check below passes.** Nobody has run the new parts list on a real Mac yet.

## Your job: the Mac check (item 1)

v4.0.4 crashed on Macs when a group was expanded in a model's parts list (jejunum). Qt hands every tree row to macOS
accessibility as a table cell, and a cell Qt had just deleted (row -1) indexed an array (`NSRangeException`). Two
fixes are on the branch and need a real Mac:

- **Main fix** (`8010279`, `b5684f7`, `90650db`): the parts list, atlas tree and histology library are now a
  self-drawn `Outline` (`app/ui/outline.py`) that exposes no table rows to accessibility.
- **Backup fix** (`c08847c`, installed in `bc4e79c`): a patched Cocoa plugin that range-checks every row and column
  lookup, for the smaller Qt lists that remain. GitHub's Mac runner passed with it, but it also passed with the old
  plugin, so CI never reproduced the crash. The evidence that it fixes anything is the code.

### Set up

```bash
git fetch origin && git checkout claude/keen-ride-vm1yxr
git lfs install && git lfs pull        # large models (jejunum, pancreas, kidney...) are LFS; without this they are stubs
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app                # runs the app from source
```

README "Running from source" has the details (Python 3.10+, Git LFS). `requirements.txt` pins PySide6 6.11.2.

### Test the outline on its own first, then with the patched plugin

The stock PySide6 wheel has the original, unpatched Cocoa plugin, so a run before installing the repair tests the
outline fix alone, which is the primary fix.

1. **Stock plugin.** Run the checklist below.
2. **Patched plugin.** `.venv/bin/python packaging/install_cocoa.py` (Apple silicon, PySide6 must be exactly 6.11.2;
   it refuses anything else and checks every hash; it prints JSON with `plugin_sha256` ending `...e3590` on success).
   Run the checklist again. To go back: `.venv/bin/pip install --force-reinstall PySide6==6.11.2`.

### Checklist (do each with VoiceOver on, Cmd+F5, and off)

1. Model library, open **Jejunum**. In the parts list expand **every** group, one at a time, then collapse them, then
   expand several quickly. Expect no crash and no hang.
2. Same in the **atlas tree** and the **histology library**.
3. Keyboard: arrows move, Right/Left open and close groups, Space ticks a row, Return activates it. Clicking an arrow or
   check box must not also select the row.
4. Look: rows, arrows, check boxes and the muted count column draw properly (light and dark appearance); jejunum shows
   grouped rows like "Lining cell nuclei 53", not 243 numbered rows. Picking a structure in 3D selects its row; picking
   a cut-face cover selects the same row as its structure (lymph node, ileum, bladder...).
5. Settings: open the keyboard-shortcuts table and the other lists with VoiceOver on. They still use Qt's table code
   but never expand.

Record pass/fail for each with and without the patched plugin. If anything crashes, collect the report from
`~/Library/Logs/DiagnosticReports/` and the app log in `~/Library/Application Support/AnatomyExplorer/logs`, and stop:
the next step is diagnosis, not release.

## If it passes: release (item 4)

The user has said Claude may use GitHub freely on this repo, but get a clear yes in chat before merging or running the
release workflow.

1. Open **one** pull request from `claude/keen-ride-vm1yxr` to `main`. PRs run the safety and diagnostics checks
   (pushing a branch runs nothing). The Mac diagnostics job will run `install_cocoa.py` with the new hash on a macOS
   runner. That is the first CI run of it; read the result. The remote says changes to `main` must go through a PR.
2. Finish `docs/releases/v4.0.5.md` (drafted; the lighter-models paragraph is a commented-out placeholder).
3. Merge, then run the release workflow (`.github/workflows/release.yml`; it uses `docs/releases/<tag>.md` as the body).
   Only a release builds installers.

## Model slimming (item 3): not done, and not for the Mac

`tools/slim` was run on the user's **Windows PC** and its output is there, not in the repo
(`C:\Users\Ethan\Desktop\AnatomyExplorer\Workspace\slim-2026-10-09`, review page `review\index.html`, venv
`Workspace\slim-venv`). 43 parts in 19 models passed (cloud run: 42): 46.8 M to 11.0 M triangles, model files 2250 to
1831 MB. The user is reviewing the close-ups on the PC and will say which models to apply. **Nothing in
`data/local_model_library` has been replaced.** Recommendation: keep the original pancreas (its copy changes the cut
face between cells; see `tools/slim/README.md`, "Known blind spot").

- Applying copies has to happen on the Windows PC, where the staged files are. If the user wants them in 4.0.5, they
  will be a separate commit on this branch (files over 100 MB must stay under Git LFS), after which pull again here and
  open each changed model once on the Mac.
- 4.0.5 does not need the slimming. If the user would rather not wait, release the Mac fix and ship the slimmed models
  in 4.0.6.
- Windows fixes already on the branch (`f9d295e`, `d50a1cc`): `run_slim.sh` did not strip `\r`, so on Windows it skipped
  the last part of every model; UTF-8 for the library file and the page; `sheets/` is created.

## About the six untracked model folders on the Windows PC

They are not on this branch and not needed. Checked against the tracked library:

| Untracked folder | Tracked counterpart | Verdict |
| --- | --- | --- |
| `cornea/6983d924760d`, `cornea/ac542bc23ca9` | `cornea/v4` (in `library.json`) | newer working builds of a model that ships; no gap |
| `eyeball/175fe2f8dd23` | `eyeball/v4` (in `library.json`) | same |
| `whole_heart/33c976b04daa` | `whole_heart/v4` (in `library.json`) | same |
| `heart_conduction/21828d9e20ec`, `pericardium_wall/26bb7d6a67c9` | none, and not in `library.json` | stand-alone earlier builds; the tracked `whole_heart/v4` already contains the conduction system and the pericardium |

None is referenced by `library.json`, so the app never loads them. Leave them uncommitted (dated 5-7 October, before the
v4 release). Old hashed folders such as `cornea/5943deb05caf` are excluded on purpose in the shared repo's
`.git/info/exclude`.

## Rules for this repo

- Never commit the runtime caches `data/anatomy/depth.npz` and `data/anatomy/samples.npz`; `git checkout --` them after
  running the app. Use explicit paths with `git add`, never `-A`.
- Run tests per module: `QT_QPA_PLATFORM=offscreen python -B -m unittest discover -s tests -p <file>`. The handoff's six
  modules pass (`test_outline`, `test_catalog_viewer_ui`, `test_studio_scene`, `test_image_workspace_ui`,
  `test_model_catalog_accessibility`, `test_macho_sections`) and `tools/check_lessons.py` prints OK. A whole-suite run
  hung in the cloud container.
- Line endings: some files are CRLF in a Windows working copy and LF in the repository; a `.gitattributes` rule makes
  `packaging/qt-cocoa/**` `-text`. `PROVENANCE.json` is stored with CRLF; keep that if you edit it.
