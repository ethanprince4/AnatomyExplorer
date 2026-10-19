# Product

<!-- impeccable:product-schema 1 -->

> Written on 14 October 2026 for the "Layered Human" rename. The owner asked for the redesign to run unattended
> ("complete the entire thing autonomously"), so there was no interview round. Facts marked *(inferred)* come from
> the repository, not from the owner, and should be confirmed.

## Platform

web

The product has two surfaces. The desktop app is a PySide6 (Qt 6) application for Windows and Apple-silicon Macs.
It draws its own chrome with style sheets and bundled fonts, so it keeps one design language on both systems rather
than following each OS. The marketing site at layeredhuman.com is a website.

## Stack

- **App:** the existing codebase. Interface tokens live in `app/ui/theme.py`, `app/ui/studio_style.py` and
  `app/ui/resources/studio/palettes.json`. The 3D renderer (OpenGL, and wgpu on macOS) is separate from the
  interface theme.
- **Website:** delegated. The owner said a plain HTML file is fine, so the site is static HTML and CSS with
  self-hosted fonts and no framework.

## Users

*(inferred)* The main users are students in a human anatomy and physiology course, at undergraduate or pre-health
level. They work through a lab course (Labs 1–9 and two lab practicals) and lecture exams, and study alone at a
laptop or desktop in long sessions, often in the evening. Their job is to find, name and understand structures,
then prove it in a practical exam: find it in the body, name what is highlighted, and read a film.

A secondary audience is self-learners and anyone else who wants a free, offline 3D atlas.

## Product Purpose

The product is an offline desktop 3D anatomy atlas and study environment. It turns a complete 3D body into
something you can study from: guided lessons set up the view for you, practice and spaced repetition bring back
what you miss, and radiology and histology tie the model to real images. Success means a student can walk into a
lab practical having found every structure themselves.

## Positioning

The dissection slider compares rendered anatomy at increasing depths. Its first available view starts at the superficial muscles; there is no exterior skin or hair model in the atlas.
Cross-sections label every structure they cut. One model viewer zooms from an organ to a cell, from the kidney down
to a podocyte. Radiology films sit beside a related anatomy view; the model is not a scan of the patient and does not reproduce each image’s pathology. The whole app runs on
the student's own machine with no account and no subscription. The name "Layered Human" describes this mechanism.

## Operating Context

- **Install:** Windows and Mac installers download about 3.4 GB in parts. Updates download in the background.
- **Data:** progress, quiz history and notes stay in the user's own folder.
- **Workspaces:** Explore (the atlas), Lessons, 3D Models, Radiology and Histology, plus Saved views and Settings.
- **Input:** mouse, trackpad gestures and dense keyboard shortcuts, all of which can be rebound.
- **Routine:** study sessions, a lab course organised by lab, practical exams with timed lengths, and a daily
  review of what is due.

## Capabilities and Constraints

- **Atlas:** 3,922 structures and 11.6 M triangles; 1,109 landmarks; Latin names and TA2 IDs; origins and
  insertions mapped on bone; innervation for 468 muscles and the action of 466.
- **Lessons:** 303 lessons in 1,614 steps, with 1,525 recall questions. The lab course has 109 mini lessons and
  1,824 graded practice items.
- **3D models:** 41 models, three built in-house: a true-scale whole heart in 119 parts, a kidney with linked nephron views, and cardiac muscle.
- **Images:** 52 radiology cases, and 101 histology tissues with 451 images.
- **Study tools:** quiz modes including Hunt, spaced repetition, a progress view, notes, and captioned figure
  export.
- **Models are off limits.** No geometry changes, no simplified copies, and the existing LOD stays as it is.
- **Renderer stays independent.** Model materials, lighting and camera are not part of the interface theme. The
  viewport background is a user setting (Settings → Display).
- **Licence:** credits to Z-Anatomy and BodyParts3D (CC BY-SA) and the image licences must stay visible. The app is
  "a study aid, not a medical device".
- **Rename:** the app is renamed from "Anatomy Explorer" to "Layered Human"; the domain is layeredhuman.com.

## Brand Commitments

- Name: **Layered Human**. Domain: **layeredhuman.com**. Both stated by the owner.
- Colour: simple colours that do not distract from the learning or the model. The 3D model is the focus of the app.
  Stated by the owner and binding.
- The owner set no other constraints.
- An earlier mark, the Vitruvian circle in `app/resources/logo.svg`, is evidence only. The rename frees it.

## Evidence on Hand

- Real counts are in `README.md`.
- Real lessons, cases and parts are in `data/content/`.
- Radiology and histology images come from Wikimedia Commons, with their licences recorded.
- The in-house models are in `models/` and `data/local_model_library/`.
- The app can render real images of the atlas and models (`tools/render_model.py`, the app's `--script` capture).
- Download links point at GitHub releases, and the code is MIT-licensed.
- There are no testimonials, user numbers, institutions, press, ratings or pricing tiers. None may be invented.

## Product Principles

1. The body is the subject. The interface frames it and steps back.
2. Every view teaches something: lessons, cases and practice set up the scene for the student.
3. Layers are the way in: reveal, peel, section and zoom are the core verbs.
4. It is yours and it works offline: no account, local progress, honest sources.
5. It stays calm for long sessions: low glare, a clear hierarchy and no gamified noise.

## Accessibility & Inclusion

- **Contrast:** the existing theme targets WCAG AA for text and records its contrast ratios.
- **Keyboard:** every shortcut can be rebound.
- **Scale:** UI and text scale run from 0.8× to 1.6×.
- **Colour meaning:** colour is never the only carrier of meaning. Origins are red and insertions blue in the atlas,
  so their labels and legend must stay.
- **Motion:** reduced motion must be respected on the website.
