# Approved Study-02 Porcelain interface

Only Anatomy-Explorer-Study-02 is the source. The latest approved reference uses a dark #141b22 stage around the unchanged native renderer, pale #f4f5f7 subject headings, white rounded global bar and Model contents panel, compact light Reveal instrument, navy #2D3C52 selected-part card, and white floating icon-and-text dock.

Porcelain is forced regardless of legacy saved preferences; no alternative appearance is exposed. Native font fallbacks remain Noto Sans/system sans for controls and Georgia/Charter/Noto Serif/DejaVu Serif for subject titles. No fonts are downloaded. Model materials, lighting and camera data are unchanged.

studio_style.icon(name) returns thin-stroke 24px SVG interface assets: brand, select, parts, reveal, section, measure, labels, reset, settings, search, down, check. Aliases layers/eye/ruler are supported. Named scene surfaces are studioShell, studioHeader, studioScene, globalBar, studioCard, studioInstrument, studioDock, selectionSurface. studioCardTitle uses compact18px sans; studioSelectionTitle uses28px serif; studioDisplay uses34px pale serif. These assets contain no anatomy renders.
