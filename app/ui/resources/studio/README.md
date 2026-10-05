# Study-02 production styling

Source: `AnatomyExplorer-Stronger-UI-Base-Source/Anatomy-Explorer-Study-02/native/palettes.json` and `native/studio.py`. The palette JSON and three SVG interface glyphs per source palette are copied without alteration. No reference screenshots or anatomy images are included or used.

Porcelain/Cobalt is the default: canvas #E9ECEE, surface #F8FAFB, selected #DCE6F7, cobalt #364F99, and the distinctive navy selection card #2D3C52 with #FAFBFC text. The existing semantic theme API remains available for all workspaces. Slate stays a preference; Study surfaces use the source Graphite roles in that mode.

Controls prefer installed Noto Sans, then Segoe UI Variable Text, Segoe UI, Inter, Cantarell, Ubuntu, DejaVu Sans, then the platform UI fallback. Body text is 10.5 points (14 logical pixels at 96 DPI). On macOS the existing system-font selection remains. Subject headings prefer Georgia, Bitstream Charter, Noto Serif, DejaVu Serif, then the system title font, matching the source order. No font files are bundled or installed. Text size follows the existing UI scale preference.

Named surfaces: surface, selectionSurface, previewSurface, selectedModel, modelRow, globalBar, globalSearch, deep, dock. Labels can use studioDisplay/studioEyebrow; selectionSurface labels with muted=true use paper_muted. Buttons support quiet, paperAction, active, secondary, tab in addition to existing primary/success/danger/ghost semantics. Keyboard focus remains distinct from selected state. studio_style helpers style existing native widgets and do not replace their contents or callbacks.

This changes application chrome only. Model materials, lighting, camera data, renderer backgrounds and geometry remain independent. Tests construct unshown native widgets and inspect tokens, resource availability, fallback selection and action preservation; they do not render models or capture screenshots.
