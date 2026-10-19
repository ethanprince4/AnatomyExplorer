# Layered Human integration

This checkout combines `claude/v4.0.9-next` at `86884d06aa69473db93d0c015b73c911d3d7b98a`
with the selected Specimen design from `UI/Website` at
`3e46b376b7df7dec66a4b9c3b0ac0f472de191b1`.

The owner selected Dock pair labels, On the body search, Side rail navigation,
and Endless catalogue histology on 19 October 2026. Rule depth gauge, Vitrines
lessons, the midline mark, six dark walls and Specimen were already selected.

The atlas has no skin/hair exterior. Neither its controls nor website should
suggest such a mesh exists. Genuine skin histology and dedicated local teaching
models remain legitimate content. The website uses available exposed-anatomy
captures instead of the old exterior depiction.

The original source checkouts and alternative designs are preserved. Next's
pending camera/review changes were copied; the separate Desktop main checkout's
opt-in GLB start-visibility fix was reconciled into ModelView. The GPU page store
now has a runtime caller, with cache failure falling back to normal preparation.

Visible branding is Layered Human; existing preferences and updater/install
identifiers retain compatibility. Installer download asset filenames remain the
existing Anatomy Explorer names and are used verbatim by the website.

The selected website lives in `docs/design/2026-10-14-layered-human/site/specimen`.
From its design folder, `python site/build.py` builds `site/dist` for static hosting.
Prototype image sources that next deliberately removed are not restored to the
runtime or deployed website. Atlas/BodyParts3D attribution remains separate.

The final launcher uses `tools/launch_review.py` with the existing shared runtime
and preview preferences. Source visuals, runtime checks and human acceptance are
recorded separately; test passes do not establish anatomical acceptance.

## Verification, 19 October 2026

The assembled application was captured without activating a desktop window at
1600 by 1000 logical pixels. Atlas OpenGL and WgpuModelViewport both produced
valid frames on the local RTX 3080. Eight routes were captured: atlas, search,
lessons, model catalogue, model viewer, histology, practice home and a live quiz.
The independent visual review's three material findings (truncated atlas tools,
missing course rows and empty initial histology preview) were corrected and
rechecked. This does not establish native macOS or anatomical acceptance.

Focused checks passed: 14 shell/search/navigation tests, 18 lesson tests,
25 image-workspace tests, the model framing/start-visibility tests, practice
home tests and 35 GPU page-cache tests. The image-license checker passed for
451 histology image files and 52 radiology cases. No broad performance or
geometry benchmark was repeated for the visual integration.

Desktop `Open Current.cmd` now explicitly targets this managed integration
checkout, instead of selecting a worktree by timestamp. Its prior contents are
preserved in `Open Current.previous.cmd` here. The preview launcher reuses the
existing shared runtime and user-data location.

The static website can be hosted on Cloudflare Pages' free tier. Domain renewal
is separate. Cloudflare DNS has not been changed; the initial hosted preview
is private on ChatGPT Sites. See the design README for the current download
link policy while new installers are being built.
