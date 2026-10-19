# Layered Human design package

This curated package contains the selected Specimen direction and its deployable website. The desktop redesign choices recorded here are the wall treatment, Rule depth gauge, Vitrines lessons, Dock pair labels, On the body search, Side rail navigation (option 2), and Endless catalogue histology. The selected website opens at the first available renderer view (26% depth) and uses only retained CC0 reference imagery.

## Contents

- `site/specimen/` is the selected responsive website and its 404 page.
- `site/build.py` collects the pages' exact local dependencies, builds a standalone static-host folder, and checks local references.
- `site/BRIEF-*.md` records the approved website content and constraints.
- `system/` contains the shared colour schemes and Qt build notes.
- `identity/README.md` documents the selected identity.
- `app/specimen-*/PORT.md` and preserve implementation notes for the selected checkpoint 3 choices.
- `assets/` contains only the actual renderer plates, fonts, and the image used by the site. `renders/specimen/` contains the lesson captures used by the Study section.

The app mockups, unselected direction pages, checkpoint alternatives, superseded captures, removed-source imagery, and unused image derivatives have been left out of this integration copy. The original `UI/Website` branch remains unchanged.

## Build and check

From this directory, run `python site/build.py`. It writes `site/dist/`, a standalone static-site directory, and verifies that page and stylesheet references resolve to files in that build. To serve the built site locally, run `python site/build.py --serve`.

## Content and image provenance

The hero uses the 26% depth plate rendered by the application. The site’s PA chest radiograph is by Mikael Häggström (CC0); its simple-columnar micrograph is from Berkshire Community College Bioscience Image Library (CC0). Each is credited on the page with a direct Wikimedia Commons source link. The production app’s separate Z-Anatomy and BodyParts3D CC BY-SA attribution remains in the app’s licensing record.

The Windows button links to the latest GitHub release page because it does not currently publish the packaged EXE produced by the release preparer. It must not link to a guessed direct-download filename. The Mac button links to the published `Install-Anatomy-Explorer-Mac.dmg`.
