# Website content and implementation facts

This is the approved handoff for the selected Specimen website at layeredhuman.com. `site/specimen/index.html` is the source page; `site/build.py` collects its dependencies, emits a static-host directory, and checks links. The site is plain HTML, CSS and JavaScript with bundled fonts. It works responsively and supports reduced motion.

## Product facts

- Layered Human is a free offline desktop anatomy atlas for Windows and Apple-silicon Macs.
- The atlas has 3,922 structures. The active model catalogue in this integration checkout has 41 entries. The app has 303 lessons in 1,614 steps, 1,525 recall questions, 109 lab-course mini lessons, 1,824 graded practice items, 52 radiology cases, 101 histology tissues, 451 histology images and 1,109 landmarks.
- The dissection view starts at the first available 26% depth render. No exterior skin or hair plate is available. Do not invent one or claim the first render is bare muscle.
- The kidney copy is: “Explore the kidney, vessels and ureter, with linked views of a nephron and its microscopic structures.” Do not call the kidney model true scale or describe its adrenal.
- The PA film is a real CC0 radiograph shown beside related model anatomy, not a scan of the patient. The micrograph is a real CC0 simple-columnar image. Their authors, licences and source links appear in the page.
- The site is a study aid, not a medical device. Do not invent testimonials, user counts, institutions, outcomes, pricing or availability.

## Installer links

- Mac: the published asset `Install-Anatomy-Explorer-Mac.dmg` at the GitHub latest-release download URL.
- Windows: the GitHub latest-release page. Link directly to a Windows executable only after that exact asset is present in a published release. At present the release page is the truthful destination; describe its helper and steps as listed there.

## Visual and interaction decisions

The selected direction is Specimen: a dark gallery wall, Literata display type, Fira Sans interface type, real app-renderer figures, a restrained brass accent and no light cards except the small wall labels. The six retained walls are slate, green, prussian, aubergine, umber and charcoal. Visitors can switch and remember the wall. Motion respects `prefers-reduced-motion`; keyboard focus remains visible.

The page leads with the 26% render and depth control, then layers, cross-section, organ-to-cell, films, study, download and credits. All anatomy renders are from this application’s renderer. The site does not ship prototype screenshots or removed-source images.
