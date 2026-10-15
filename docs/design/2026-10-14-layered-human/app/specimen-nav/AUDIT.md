# Navigation audit (checkpoint 3)

Written on 15 October 2026, before the three navigation options were drawn. `PORT.md` has the options and the clicks
measured in them.

Sources: in the app's code, `app/main_window.py` (`_build_menus`, `_build_toolbar`, `_register_workspace_actions`,
`_update_workspace_header`, `_show_nav_page`, `open_saved_view`), `app/ui/studio_shell.py` (`StudioHeader`,
`CollectionWorkspace`), `app/ui/nav.py` (`NavTabWidget`), `app/ui/places.py` (`PlaceHistory`), `app/ui/lessons.py`,
`app/ui/quiz.py`, `app/ui/practice.py`, `app/ui/histology.py`, `app/ui/model_view.py`, `app/ui/saved_views.py`, README
"Using it" and "Study features", the design folder's `research/current-ux-evaluation.md` (F12, F17, F18), and the
Specimen mockup.

## 1. The real app today (v4.0.8)

### Places, how you reach them, how you get back

| Place | Reached by | Back out |
|---|---|---|
| **Explore** (the atlas, titled "3D Anatomy" on the stage) | header **Explore**; Workspace menu Ctrl+1; opening a saved view; "Show in the atlas" from a model part; "Show in 3D" from a slide | any other header room |
| Explore panel (floating card): Browse (Systems, Regions, Tree, Models), Study (Lab course, Lecture exams, Lessons, Radiology, Histology), View | always beside the atlas; View menu "Explore panel" | close button; Ctrl+B |
| Details panel (selection) | selecting anything | close; View menu "Details panel" |
| **Lessons** library (Lab course, Lecture exams, Body system, Region, Level; Continue card) | header **Lessons**; Ctrl+L; Study menu | other rooms |
| Lesson cover (objectives, scores, Learn, Practice) | a lesson card | "‹ All lessons" |
| Lesson reader (step N of M, Show answer, ‹ Back / Next ›, Lesson tools) | Learn / Continue; header **Lessons** returns here while a lesson is open | "‹ Lesson overview", "‹ All lessons" |
| Lab practice session (panel beside the model) | Practice on a lesson cover or in the reader; Practice exam on a lab practical | Finish / Close; summary "Retry missed" |
| **3D Models** library (41) | header **3D Models**; Ctrl+2; Study menu "3D models"; Details → 3D models; search; a lesson step | other rooms |
| Model viewer (one center tab per model) | Open on a model; Details → 3D models; lesson step | header 3D Models (library); gear → Open workspaces lists the tabs |
| **Radiology** library (104 cases) and case (film beside the live model) | header **Radiology**; Ctrl+R; search; Study menu | Browse cases; other rooms |
| **Histology** library (tree of 101 tissues) and slide viewer (a center tab) | header **Histology**; Ctrl+H; Details → Histology; model "Related" → Histology | other rooms; the open slide tab stays in Open workspaces |
| Quiz (floating panel over the atlas: mode, topic, count, Start quiz, Review what is due, My progress) | Study menu → Quiz; Ctrl+Q | Finish / Close |
| Review what is due | a button inside the Quiz panel only | Finish |
| Search | header field (Enter); Ctrl+F focuses the Explore panel's own search | clear the field |
| Saved views (menu: Save current view, the views, Manage…) and the Manage dialog | header **Saved views**; Tools menu; Ctrl+D saves | the view opens in Explore; Esc closes the dialog |
| Settings dialog (Mouse & Camera, Display, Behavior, Keyboard) | gear menu → Settings; File menu; Ctrl+, | OK / Cancel |
| My progress, All my notes, Note, About, Updates, Find a command | Study / Help / Updates menus inside the gear; Ctrl+Shift+P | close the dialog |
| Back / Forward | header arrows; Back's arrow lists 15 recent places; Alt+Left/Right; mouse back/forward buttons | |

### How moving around works

- **Five rooms** in the header (Explore, Lessons, 3D Models, Radiology, Histology), then search, Saved views and a gear
  that holds Settings, the open workspaces, Find a command and every classic menu.
- **Back is global.** `PlaceHistory` records a place whenever navigation settles: the lesson step being read and the
  scene beside it, the atlas and its selection, a model and its part, a slide, a case, a library page (60 entries). So
  three Next clicks in a lesson are three Back clicks; a student who reads five steps and wants the atlas back must press
  Back five times or use the arrow's list.
- **Rooms half-remember.** Lessons returns to the open lesson (`_show_nav_page`: runner page → reader); 3D Models and
  Histology always land on their library and the open model or slide survives only as a hidden center tab, found again
  through gear → Open workspaces. Radiology lands on the library (F12 fixed this).
- **Practice and review have no room.** The quiz is a floating panel over the atlas, reached from a menu. "Review what
  is due" is a button inside that panel. Lab practice runs beside the model and the header still says Lessons.
- **Two names for one room**: header "Explore", stage title "3D Anatomy" (F18); "3D Models" / "Model library".
- **Cross links that exist**: model part → "Show in the atlas"; model → Related lessons, → Histology; slide → "Show in 3D"
  (atlas structures); atlas selection → Details → 3D models, Histology, clinical notes; radiology label → selects the
  structure in the live model. **Missing**: a slide straight to its microanatomy model (the link exists only the other
  way, `entry.histology` on the model), a lesson step's structure to the atlas.

## 2. The Specimen mockup (base before checkpoint 3)

Header on every screen: mark + "Layered Human" · Atlas, Lessons, Models, Radiology, Histology · ‹ › · search field ·
"Review 12 due" · "Saved views" · ≡ Menu.

| Screen | Room lit | Where am I? | Ways out shown |
|---|---|---|---|
| atlas / peel / section | Atlas | title "Muscles, anterior view"; section is a dock state (Section on) | rooms; Full entry |
| lessons | Lessons | title | Continue; lab cards; Review what is due |
| lesson | Lessons | "Step 2 of 7 · The coronary circulation · Advanced" | step Back / Next only: **no way to the lesson's overview or to All lessons** |
| practice | **Lessons** | "Lab 6 practice · … question 4 of 12" | Show me, Skip: **no way to end the session or back to the lesson** |
| models | Models | title | Open model, Lessons (6) |
| viewer | Models | "View 2 of 13 · Kidney · true scale" | **no way back to the 41 models except the room name; no way to the atlas** |
| radiology case | Radiology | title | Previous / Next case; **no way to the case list** |
| histology-library | Histology | title | the catalogue |
| histology slide | Histology | title "Simple columnar epithelium" | Jejunum model, Lessons (4); **no way back to the catalogue except the room name** |
| settings | none (the ≡ gets the brass bar) | title | — |

Places with **no visible way in**: Practice (only from inside a lesson cover, not drawn), the quiz (heart quiz:
nowhere), My progress and notes (≡ only), Settings (an unlabelled ≡), the section view (the dock's Section, fine as a
state). "Review 12 due" is a button with no destination: which room does it open?

Places where **it is unclear where you are**: the lesson (four levels deep, one room name lit), practice (Lessons lit,
but it is a test), the viewer and the slide (an item inside a room, the room's front page one unlabelled click away),
Settings (no room lit). Back and Forward are two bare chevrons with no word, and nothing says where Back goes.

## 3. Tasks and clicks today

Clicks are mouse clicks (typing counts as none). "App" is v4.0.8; "Base" is the mockup the options start from.

| # | Task | App today | Base mockup |
|---|---|---|---|
| 1 | Look at the biceps (from another room) | Explore, click biceps: 2 | Atlas, click biceps: 2 |
| 2 | Continue the last lesson | Lessons (lands in the reader if a lesson is open, else Continue): 1–2 | Lessons, Continue: 2 |
| 3 | Review the 12 due | gear, Study, Quiz, Review what is due: 4 (Ctrl+Q then 1) | "Review 12 due": 1, destination unknown |
| 4 | Open the kidney model at its Corpuscle view | 3D Models, kidney, Open, Corpuscle view: 4 | Models, kidney, Open model, Corpuscle thumbnail: 4 |
| 5 | Open the jejunum slides, then the jejunum model | Histology, Digestive, Jejunum, a slide: 4; then 3D Models, jejunum, Open: 3 = 7 | Histology, Jejunum, Open the slides: 3; Jejunum model: 1 = 4 |
| 6 | Open a chest film | Radiology, the case: 2 | Radiology, the case: 2 |
| 7 | Change the wall colour | gear, Settings, Display, Background: 4+ | ≡, (Settings not drawn), a wall: 3 |
| 8 | Get back to the atlas as you left it, after reading 3 steps of a lesson | Back ×4, or Explore: 1 (the atlas keeps its state) | Atlas: 1, nothing says the state is kept; Back ×4 |
| 9 | Start a heart quiz | gear, Study, Quiz, Topic, Cardiovascular system, Start quiz: 6 | no way in |
| 10 | Save a view, and later come back to it | Saved views, Save current view, OK: 3; Saved views, the view: 2 | the same: 3 + 2 |
| 11 | From the kidney model, see the renal artery in the body | right-click part, Show in the atlas: 2 | no way |
| 12 | End a lab practice and go back to its lesson | Finish, ‹ Lesson overview: 2 | no way drawn |

## 4. Principles for this product

1. **Mouse first.** Every place is one visible, worded target away; nothing depends on a shortcut or a hover to be
   found. Shortcuts stay (aria-keyshortcuts, tooltips), never printed in the chrome.
2. **The model is the hero.** Chrome stays lettered on the wall, quieter than the specimen; the stage never shrinks for
   navigation.
3. **The museum's rooms.** A small, fixed set of rooms, always in the same order and the same place. A room you return to
   is as you left it (the lesson open at its step, the model at its view, the slide you were looking at); clicking the
   room you are already in takes you to its front.
4. **A beginner is never lost.** The room is always marked; inside a room, a short trail names the item and its parent,
   each part a link. Back names where it goes.
5. **An expert is never slowed.** Room to room is one click in every option; Back takes whole places, not every step
   or selection; shortcuts and the mouse back button keep working.
6. **Tests are a room.** Practice (quiz, review due, lab practice) is a place you can see and enter, and the due
   count lives on its door, not as a loose button.

## 5. What every option fixes (shared)

- **Practice becomes the sixth room**, with the due count on it. Its front is the quiz set-up the app already has
  (Review what is due, a quiz by topic, practice exams, My progress); a session runs on the model as today.
- **Settings is a word**, not an unlabelled ≡. The ≡ stays only for the classic menus the Qt app must still offer.
- **A trail on every item page**: lesson, practice, viewer, slide, case. Front pages need none.
- **Back takes places**: room pages and items, not lesson steps or selections (the lesson's own Back/Next handle
  steps). Its target is named.
- **Rooms remember**: Models returns to the open model, Histology to the open slide, Radiology to the open case,
  Lessons to the open lesson, as the app already does for Lessons.
- **Two missing ways**: a model's selected part gets "In the atlas" on its label (the app's "Show in the atlas"), and the
  slide keeps its model link (the app needs the reverse of `entry.histology`).
