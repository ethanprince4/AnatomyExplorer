# Layered Human design

The app and website follow the selected **Specimen** direction: anatomy is displayed against a dark gallery wall, with wall-lettered controls and a midline identity mark. Display and reading type use Literata; interface type uses Fira Sans.

Six dark wall palettes are available: Gallery slate (default), Museum green, Prussian, Aubergine, Umber, and Charcoal. Anatomy imagery retains its authored colors.

The selected checkpoint 3 choices are a dock-pair Labels / Show all control, search placed on the body, a side navigation rail, and an endless histology catalogue. The existing anatomy dock exposes Section, X-ray, Isolate, Hide, Measure, Labels, Reset view, and More tools. Compact icon controls retain full accessible names and action tooltips; Labels and Show all remain text controls. The parent menu keeps geometry “Show all” distinct from caption “Show all”.

The desktop shell uses a 104 px rail, a top brand/search bar, the atlas workspace, a depth rule at the right, and a bottom tool row. The tree is opened through Parts/More tools when needed. The website implementation is under `docs/design/2026-10-14-layered-human/site/specimen`; the native desktop implementation is in `app/ui/studio_shell.py`, `app/ui/studio_scene.py`, and `app/ui/studio_style.py`.

The website decisions and source references are recorded in `docs/design/2026-10-14-layered-human/README.md`; integration choices and boundaries are in `docs/integration/layered-human.md`.
