# Layered Human: brand and website brief

*14 October 2026. Written for the rename of Anatomy Explorer and the launch of layeredhuman.com.*

**Method.** The strategic frame follows `/strategize`: five foundational questions, situation → complication →
resolution, and the brief template. The voice, naming and copy follow `/articulate`: principles with limits on both
sides, real product copy as examples, plain language and copy that can be translated.

**Sources.** `PRODUCT.md`, `README.md`, the lesson, radiology and model files in `data/content/`, the current
screenshots in `../current/`, and the interface strings in `app/ui/` (for naming only).

**Evidence rule.** Every number in draft site copy comes from `README.md`. Facts that `PRODUCT.md` marks *(inferred)*
are still marked *(inferred)* here. Nothing in this brief comes from user research, because none exists. Anything
the owner must confirm is listed in [§8 Open questions](#8-open-questions-for-the-owner).

---

## 0. Strategic frame

### Situation
Anatomy Explorer is a mature, free, offline desktop atlas. It has 3,922 structures, 303 lessons, 41 3D models,
104 radiology cases and 101 histology tissues. Right now its only shop window is a GitHub README written for
developers. That page has download badges, PowerShell instructions and a section on rebuilding from Blender.

### Complication (checked against the evidence, not sized to fit the answer)
- **The name describes the category, not the product.** "Anatomy Explorer" could be any atlas. The things only this
  app does are the depth-fraction dissection slider, sections that label themselves, one viewer from organ to cell,
  and films beside the live model. The current name says none of this. *Evidence: README, PRODUCT.md.*
- **The download asks a lot.** It is about 3.4 GB. It comes from GitHub. On first run Windows shows "Windows protected
  your PC" and macOS says the installer "cannot be opened". *Evidence: README, Download section.* To a student, that
  combination looks like risk.
- **What we do not know.** We have no evidence that students fail to find the app, that they drop out partway through
  installing, or how many there are. The complication is a **trust and clarity gap at the moment of download**, not a
  proven acquisition problem. This brief does not claim more than that.

### Resolution
Give the app a name that states the mechanism (**Layered Human**). Then build a site whose one job is to **earn the
download honestly**:

- show the mechanism working;
- show the real content by name;
- state the size, the system requirements and the OS warnings before anyone clicks;
- keep the credits visible.

### Five foundational questions: where we stand

| Question | What we know | Strength | Gap |
|---|---|---|---|
| Problem validation | Students must find, name and read structures for lab practicals and lecture exams. The app's lab course is built around exactly that. | Medium (the content is built for it; the need is inferred) | No interviews. Severity and frequency are not measured. |
| Audience | A&P students on a lab course (Labs 1–9 and two practicals) and lecture exams. Secondary: self-learners. | Inferred (PRODUCT.md) | Which course the lab structure mirrors. Year of study. Mac/Windows split. |
| Solution fit | A desktop app that works offline, with local progress and long sessions. It is not a web app, so the 3.4 GB download is the price of depth. | Strong for capability, weak for reach | Whether students accept 3.4 GB plus unsigned-installer warnings. |
| Feature validation | The full feature set ships today. | n/a | No usage data, so we cannot tell which features drive use. Don't rank features on the site by guesswork. Lead with the core verbs. |
| Competitive landscape | Categories only: subscription 3D atlas apps, browser atlases, free open atlases (including **Z-Anatomy**, which this app builds on), textbooks and lab manuals, flashcard and spaced-repetition apps, and the lab's own models and specimens. | Weak (not researched for this brief) | We have verified nothing about any named competitor. The site must not compare. |

**On "no competitor can truthfully copy":** use it as an internal positioning test, never as a site claim. The site
describes what the app does and lets the reader compare. It never says "only", "first" or "unlike…". Z-Anatomy is
both a source and a free alternative. It gets credit, never contrast.

### Goals
1. Someone who reads the hero understands within one screen what the app is, who it is for and what it costs (nothing,
   about 3.4 GB of download).
2. Nobody who starts the download is surprised by the size, the requirements or the OS warning.
3. Credits and the "study aid, not a medical device" line are visible on every page.

### Guiding principles
- **The body is the proof.** Every section shows a real render or screenshot of the app, never stock art.
- **Name the real thing.** Real lesson titles, real cases, real model names.
- **Earn the 3.4 GB.** Put the cost and the warnings beside the button, not on a page behind it.
- **Credit in plain sight.** Sources are part of the product's honesty, not legal small print.

### Hypotheses (testable later; none of them is a site claim)
- H1: If the hero shows the dissection slider moving, more visitors scroll past the hero than with a still image.
  This assumes the mechanism is the hook.
- H2: If the size and the OS warning appear beside the download button, fewer people start a download they don't
  finish. Measure this with GitHub release asset download counts against completed first-run installs, but only
  if the owner wants to measure installs at all.
- H3: If the course overview lists Labs 1–9 by topic, students on a matching course recognise it faster than from
  feature copy. This assumes students search by lab topic.

### Scope (phase 1)
- **In:** one long landing page, and Download, Course overview, Credits & licences and Help/FAQ pages. Static HTML
  (PRODUCT.md, Stack).
- **Out:** blog, accounts, newsletter, donations, analytics decisions, comparison pages and translated versions. These
  are deferred, not rejected.

---

## 1. What the name promises, and the positioning

### What "Layered Human" promises
- **Layered:** the body comes apart in an order you control, skin first and bone last, and you can put it back. It
  also promises depth in the other sense: organ to tissue to cell, atlas to film to micrograph.
- **Human:** the whole body, not one region or one system. It also hints at a tone: calm and humane, made by a person
  for people studying late.
- **What the name does not say:** "anatomy". Until the name is known, it always needs a descriptor: **Layered Human:
  a free 3D anatomy atlas**. Use that in the page title, the app's About box, the installer window, the GitHub repo
  description and social previews.
- **Risks:** "layered" can read as fashion (layered clothing) or psychology. The first image fixes that. The hero must
  show the body mid-peel, never an abstract mark on its own.

### Positioning (one sentence)
> **Layered Human is a free 3D anatomy atlas for your computer that lets you peel the body from skin to bone, cut
> sections that name what they pass through, and zoom from an organ to a cell, with lessons, films and practice
> built around it, all offline.**

Short form for meta descriptions and social previews:
> Peel the body from skin to bone. Free 3D anatomy for Windows and Mac. Works offline.

### The mechanism (internal; each point maps to a README fact)
1. **Depth that follows the body.** The slider peels from the skin inwards. Depth is a fraction of how thick the body
   is at each point, so the hand and the thigh are uncovered together.
2. **Sections that label themselves.** Every structure the plane passes through is named around the edge of the
   view. Click a label to select it.
3. **One viewer, organ to cell.** The kidney model goes in one zoom from the whole organ to a podocyte, through eight
   stored views.
4. **Films beside the live model.** Click a numbered label on a radiograph and the model selects and frames the same
   structure. In five chest cases the model shows the disease itself.
5. **Yours, offline.** It runs on your own machine. Progress, quiz history and notes stay in your user folder.

---

## 2. Audience and their real scene

### Primary: A&P students preparing for lab practicals and lecture exams *(inferred)*
**Scene.** It is the evening, at a laptop or desk, in a long session. The lab practical is coming. At the bench they
will have to find a structure on a model, name the one that is tagged, and read a film. In lecture exams they need
the pathway, the wall layers, the sequence. Right now they have a lab manual, lecture slides, maybe a textbook atlas,
flashcards, and limited time with the lab's own models.

**Their words:** lab practical, lecture exam, origin and insertion, "what is this", "where does it go", tunics, the
layers of the gut wall, the brachial plexus, the cubital fossa. The content already uses these words. So should the
site.

**Content they will recognise** (real titles from `data/content/`):
- Lab course reviews: *Lab 1 review: nerves, reflexes and general senses* · *Lab 2 review: the eye and vision* ·
  *Lab 3 review: the heart* · *Lab 4 review: the ECG and heart function* · *Lab 5 review: veins, the portal system
  and fetal circulation* · *Lab 6 review: the respiratory system* · *Lab 8 review: the urinary system* · *Lab 9
  review: the female system and early development*
- Lessons: *The brachial plexus* · *The rotator cuff* · *The cubital fossa* · *The femoral triangle* · *The
  conducting system of the heart* · *The fetal circulation and what becomes of it* · *The floor of the skull and what
  leaves by each hole* · *Reading the gut wall, oesophagus to colon* · *The nephron, segment by segment*
- Radiology: *Chest radiograph — PA* · *Chest — right middle lobe pneumonia* · *Chest — massive pleural effusion* ·
  *CT head — axial, non-contrast* · *MRI brain — axial T2* · *Normal adult kidney: longitudinal ultrasound* ·
  *CT kidneys — bilateral renal calculi, coronal*
- Models: whole heart · kidney with the nephron · cardiac muscle · eyeball · ear · liver lobule · lung acinus ·
  osteon · neuron · pancreas · male and female reproductive

### Secondary: self-learners
People who are curious, changing career, drawing or training, or who just want a free offline atlas. They need to
know they can **explore without a course**: the atlas, search and the models all work on their own.

### What each must believe before downloading 3.4 GB

| Belief | Who | What earns it on the site |
|---|---|---|
| "This covers what I'm tested on." | Students | Lab course listed by topic (Labs 1–9, two practicals). Real lesson titles. Practice that looks like the practical: find it, name the highlighted structure, read a film. |
| "It's really free. There's no catch." | Both | "Free" next to every download button. MIT-licensed code, a link to GitHub, no sign-up step anywhere on the site. |
| "It will run on my computer." | Both | Apple silicon (M1 or newer), macOS 13 or later; Windows. The size beside the button. Mac needs about 8 GB free while installing. |
| "The warning doesn't mean it's unsafe." | Both | Say why before they see it: the app isn't signed with a paid developer certificate. Show the exact click path. The code is public. |
| "It's worth 3.4 GB rather than a website." | Both | It works offline. 3,922 structures, 41 models, 104 cases, 1,049 micrographs, shown, not just counted. |
| "The anatomy is trustworthy." | Both | Sources named: Z-Anatomy, BodyParts3D, Terminologia Anatomica 2, Wikimedia Commons. Latin names and TA2 IDs. |
| "I won't lose my progress." | Students | Progress, quiz history and notes are kept in your user folder. Updating or reinstalling never loses them. |
| "I can just look around." | Self-learners | Search by structure, group, landmark or Latin term. Models open from search. |

---

## 3. Voice and tone

**Attributes:** precise, calm, honest, concrete, on your side.

### Five voice principles

**1. Name it exactly: precise, not pedantic.**
Use the anatomical term the course uses. Explain it once, briefly, and only where a student would actually stall.

| Do | Don't |
|---|---|
| "Right middle lobe pneumonia" | "A lung problem" |
| "Superficial or deep to the selection" | "In front of or behind it-ish" |
| "Find the cubital fossa." | "Find the elbow pit thing (cubital fossa, a triangular depression…)" |

**2. Concrete over impressive: show the mechanism, skip the adjectives.**
Say what happens when you use it. Numbers come from the README or don't appear.

| Do | Don't |
|---|---|
| "Depth is measured against how thick the body is at each point, so the hand and the thigh come away together." | "Revolutionary layer technology." |
| "104 radiology cases beside the live model." | "Tons of real-world imaging!" |
| "Click a label on the film and the model selects the same structure." | "Seamlessly integrated multimodal learning." |

**3. Calm, not cheerful: built for long evening sessions.**
No exclamation marks, no streaks, no guilt, no confetti. Good news is brief, and misses are information.

| Do | Don't |
|---|---|
| "Nothing is due today." *(current app string; keep it)* | "🔥 Don't break your streak!" |
| "Not that one. {n} tries left." | "Wrong! Try again!" |
| "You missed {n}. Retry missed?" | "Oops, you'll get it next time!" |

**4. Honest about limits: say what it isn't before anyone assumes.**
Name the cost, the warning and the boundary of the claim.

| Do | Don't |
|---|---|
| "The model is set up to match the film. It is not a scan of this patient." | "See the patient's anatomy in 3D." |
| "About 3.4 GB. Windows may warn you the first time; here's why." | "Quick, easy install." |
| "A study aid, not a medical device." | (leaving it to the footer's small print) |

**5. One student at one desk: second person, short sentences, plain verbs.**
Write to a single tired person, not to "learners". Aim for sentences under 20 words. Avoid idioms, because the copy
must survive translation (`/localize`).

| Do | Don't |
|---|---|
| "Find it. Name it. Read the film." | "Empower learners to leverage immersive visualisation." |
| "Pick up where you left off." | "Resume your personalised learning journey." |
| "Your progress stays on your computer." | "Your data is stored locally in a user-scoped directory." |

### How the app speaks vs how the site speaks
The voice is the same everywhere. The tone and the job differ.

| | App | Site |
|---|---|---|
| Job | Get out of the way of the body; tell you exactly what happened | Earn the download; show, then say |
| Labels | Nouns for places (Atlas, Lessons), verbs for actions (Section, Measure, Show all). One or two words, no articles. | Section headlines are short statements of what you can do. |
| Person | Mostly impersonal in labels; "you" in guidance and feedback | Always "you" |
| Numbers | Live counts ("Review what is due ({n})") | Only README numbers, written the same way each time (3,922; 1,049) |
| Warmth | Low and steady | A little warmer, never cute |
| Punctuation | No exclamation marks. Sentence case. Ellipsis only on commands that open a dialog ("Set color…"). | The same |

### Tone across contexts (real app moments)

| Context | Tone | Example |
|---|---|---|
| Lesson step | Patient, specific | "Recall before you reveal." → recommended: "Recall it first, then show the answer." (avoids the clash with "Reveal"; see §4) |
| Practice, correct | Brief | "Yes, the ulnar nerve." |
| Practice, wrong (Hunt) | Neutral; never names the wrong pick | "Not that one. {n} tries left." |
| Practice summary | Factual, with a next step | "{correct} of {total}. Retry the {missed} you missed." |
| Empty: nothing due | Settled, with an offer | "Nothing is due today. Practise a lab, or start a Hunt." |
| Empty: no search result | Helpful | "Nothing called "{query}". Try the Latin name, or a group such as "brachial plexus"." |
| Empty: no notes yet | Explains the value | "No notes yet. Select a structure and press N to add one." |
| Error: a model won't open | What happened, what to do, where the log is | "This model couldn't open. Try opening it again. If it keeps failing, the details are in the logs folder." |
| Error: Mac installer stopped | Reassuring, actionable (README-true) | "The download stopped. Run the installer again; it picks up the parts it already checked." *(confirm the resume behaviour; the README says "you can simply run it again")* |
| Radiology caveat | Plain and honest (keep the current meaning) | "The model shows the related anatomy. It isn't fitted to this image, so shape, level and pathology can differ." |
| Destructive | Clear consequence | "Put everything back? This shows every structure you peeled away." / buttons: "Put everything back" · "Keep going" |

---

## 4. Naming system

**Rules.** Workspaces are **nouns for places**. Tools are **verbs or short noun phrases for actions**. Anatomical terms
stay exact (dissection, section, sagittal / coronal / transverse, superficial / deep). Brand verbs ("peel", "layer")
belong on the website and in tooltips, **not** in place of anatomical terms. One word means one thing across the
whole app.

**Collisions found in the current interface** (from `app/ui/`):
- **"Reveal" has three meanings.** The model viewer's panel for tissue opacity, separating layers and cut-away
  (`studio_scene.py`). The quiz button that shows the answer (`quiz.py`). And "Reveal controls", which opens the
  atlas's View tab (`studio_shell.py`).
- **"Reset" has two meanings.** It resets the camera on the bottom bars. In the Reveal panel it resets opacity, the
  separation and the cut-away (`model_view.py`).
- **The same thing has two names.** "Section" on the model dock is "Cross-section" in its More menu. "Model contents"
  is the card for the "Parts" button.

| Current | Recommendation | Why |
|---|---|---|
| Anatomy Explorer | **Layered Human** (descriptor: "3D anatomy atlas") | The owner's decision. Keep the descriptor until the name is known. |
| Explore (workspace) | **Rename → Atlas** | The other workspaces are content nouns. The app already says "the atlas" ("Show in the atlas", "the atlas's controls"). "Explore" was the old name's verb, and the screen heading already reads "3D Anatomy", a third name. The panel keeps its groups **Browse / Study / View**. |
| Lessons | **Keep** | Exact, and the student's word. |
| 3D Models | **Rename → Models** (keep "3D models" in site prose) | Everything in the app is 3D, so "3D" doesn't tell the tabs apart. Shorter in the bar. Also fixes the breadcrumb "Collection / 3D models". Low risk; test it. |
| Radiology | **Keep** | Course vocabulary. Covers radiograph, CT, MR, ultrasound and the other image types. |
| Histology | **Keep** | Course vocabulary. |
| Saved views | **Keep** | Accurate: it saves the camera, visibility, selection and sections. |
| Reveal (model viewer panel) | **Rename → Layers** | It holds tissue opacity, "Separate layers / parts", cut-away and teased: the layer controls. This is the one place where the brand word is also the exact word. |
| Reveal (quiz button) | **Rename → Show answer** | Says what happens. Removes the collision. |
| Reveal controls (atlas menu) | **Rename → View controls** | It opens the View tab, so say so. |
| Measure | **Keep** | A verb, exact. |
| Show all | **Keep** | Matches Shift+H. The tooltip already explains "and leave isolation". |
| Reset (camera) | **Rename → Reset view** | Removes the ambiguity. The tooltip already says "Reset the camera view". |
| Reset (Layers panel) | **Rename → Reset layers** | Says what it resets. |
| More tools | **Keep** | Signals overflow honestly. |
| Dissection slider | **Keep "Dissection"; end labels Superficial ↔ Deep** | "Dissection" is what instructors say, and it is precise. *Superficial/deep* are the terms the Details panel already uses. "Peel" is the site's verb and the tooltip's ("Peel the body from the skin inwards"). Keep **"Show only this layer"**. |
| Cross-sections | **Control: Section. Menu: View → Sections. Prose: cross-section.** Plane names unchanged. | One term across the atlas and the model viewer. Fixes "Section" vs "Cross-section". |
| Hunt mode | **Keep "Hunt"** | The one playful name, and it earns it: it describes the task exactly. Add a one-line subtitle: "Find one structure. Nothing is labelled." |
| Review what is due | **Keep, with a count** ("Review what is due ({n})"; empty: "Nothing is due today") | Already plain and honest. Don't turn it into a streak. |
| Model contents / Parts | **Use "Parts" for both** | One name per thing. |

---

## 5. Website: layeredhuman.com

### Site map
```
/            Landing page (one long page)
/download    Download and install, step by step
/course      Lab course and lessons overview
/credits     Credits & licences
/help        Help and FAQ
```
**Footer on every page:** "Layered Human is a free study aid, not a medical device. Anatomy data: Z-Anatomy and
BodyParts3D (CC BY-SA). Images: Wikimedia Commons contributors. Code: MIT. · Credits & licences · GitHub · Help"

**The download button.** The Windows link downloads a `.ps1` script, which looks alarming without context. Every
download button therefore goes to `/download#windows` or `/download#mac`. The download starts there **and** the steps
are on screen at the same moment. The page detects the visitor's OS and shows its button first, with the other
platform beside it.

**Proof assets** (all real, all recaptured under the new name: the current screenshots in `../current/` still show
"Anatomy Explorer" in the header):
- A dissection loop: the same body at three slider positions (render with the app's `--script` capture).
- A transverse section with its edge labels.
- The kidney's stored views from Kidney to Podocytes (`tools/render_model.py kidney_nephron --view …`).
- *Chest radiograph — PA* beside the model (current `11_radiology_case.png`, recaptured).
- A lesson step (current `07_lesson_reader.png`) and the Lessons library (`06_lessons_library.png`).
- A histology viewer (`13_histology_viewer.png`).
- The whole heart (`09_model_heart.png`).

Every image gets alt text that names what is shown ("Transverse section through the thorax, each cut structure
named around the edge"). Every loop respects reduced motion and falls back to a still frame.

### Landing page, in order

#### 1. Hero
**Job:** say what it is, who it's for, and what it costs, in one screen.
**Proof:** the dissection loop; the body peeling from the skin inwards.
**Copy (recommended, alternative A below):**
> # Peel the body back, layer by layer.
> A free 3D anatomy atlas for your computer. Slide from skin to bone, cut a section that names itself, and study for
> your lab practical offline.
>
> **[Download for Mac]** **[Download for Windows]**
> Free · about 3.4 GB · Apple silicon Mac (macOS 13 or later) or Windows · [What to expect when installing](/download)

#### 2. Peel
**Job:** explain the central mechanism so it is believable.
**Proof:** three stills side by side, labelled "Skin", "Muscle", "Bone". No percentages, because none are in the README.
> ## Depth that follows the body
> Drag the dissection slider and the body comes apart from the skin inwards. Depth is measured against how thick the
> body is at each point, so the hand and the thigh are uncovered together. Want one layer on its own? Show only that
> slab.
>
> → *See how a lesson uses it* (anchor to §6)

#### 3. Section
**Job:** show the second mechanism, the one that answers "what is this?".
**Proof:** a transverse section with its edge labels; a cursor clicks one label.
> ## Cut anywhere. The cut names itself.
> Section the body sagittally, coronally or transversely. Every structure the plane passes through is named around
> the edge of the view. Click a name to select it.

#### 4. Zoom: organ to cell
**Job:** show depth of scale, and that the models are part of one tool rather than add-ons.
**Proof:** the kidney's stored views as a strip: Kidney → Lobe → Nephron → Corpuscle → Podocytes. A still of the
whole heart.
> ## From the kidney to a podocyte, in one zoom
> 41 interactive 3D models open in the same viewer, with the same controls and labels as the atlas. Step the kidney
> from the whole organ down to the podocytes. Hide the heart's wall panels one at a time to look inside a true-scale
> heart in 119 parts.
>
> → *Browse the models* (anchor to §8 list)

#### 5. Films beside the model
**Job:** connect the model to real images, the part of the practical students fear most.
**Proof:** *Chest radiograph — PA* with numbered labels and the model beside it; then *Chest — massive pleural
effusion* with the fluid shown in the model.
> ## Read the film with the body beside it
> 104 radiology cases put a real radiograph, CT, MR or ultrasound next to the live model, labelled on both sides.
> Click a number on the film and the model selects the same structure. In five chest cases, the model shows the
> disease itself.
>
> <small>The model is set up to match each film. It is not a scan of that patient.</small>

#### 6. Lessons that set up the view
**Job:** show that the app teaches, not just displays.
**Proof:** a lesson step (*The brachial plexus* or *The conducting system of the heart*) with the view already set up.
> ## Every lesson sets up the view for you
> 303 lessons in 1,614 steps. Each step switches systems, dissects to a depth, sections or opens a micrograph, so
> you're always looking at the right thing. 1,525 of the steps ask you a question before you move on.
>
> **[See the course and lessons →](/course)**

#### 7. Practise like the practical
**Job:** speak straight to the lab-practical scene.
**Proof:** the Practice panel beside the model; the Hunt screen with nothing labelled.
> ## Find it. Name it. Read the film.
> The lab course covers Labs 1–9 and two lab practicals in 109 mini lessons, with 1,824 graded practice items. Find a
> structure in 3D, name the one that's highlighted, or put the steps in order. Then sit a practice exam of 20, 40 or
> 60 questions, or everything.
>
> In **Hunt**, nothing is labelled. Peel structures away one at a time and find the one you're asked for, in three
> tries.
>
> What you miss comes back a day later, then after four days, then less often as you get it right.

#### 8. Under the microscope
**Job:** complete the "real images" proof and name the micro models.
**Proof:** the histology viewer and a micro model with a cut face.
> ## Tissue, slide and model together
> 101 tissues with 1,049 micrographs. The 3D models show the same layers in depth, and you can select, hide or
> cut through each one: the gut wall, the liver lobule, the osteon, the retina.

#### 9. The atlas in numbers
**Job:** proof of depth for the sceptic, without hype.
**Proof:** a quiet band of facts. No icons and no animated counters.
> ## Built to be looked up
> - 3,922 structures, from bones and ligaments to cranial nerves and skin regions
> - 1,109 bony and organ landmarks
> - Latin names and Terminologia Anatomica 2 IDs
> - Origins and insertions mapped on the bone
> - Innervation for 468 muscles, and the action of 466
> - 423 clinical correlations, searchable by sign or syndrome

#### 10. Yours, offline
**Job:** answer "what's the catch?" before it is asked.
> ## Free. Offline. Yours.
> Layered Human runs entirely on your computer. Your progress, quiz history and notes stay in your own user folder,
> and updating or reinstalling never loses them. Updates download in the background. The code is open source under
> the MIT licence.
>
> → *Read the code on GitHub*

#### 11. Honest sources
**Job:** keep the credits visible and turn them into trust.
> ## Built on open anatomy
> The 3D atlas is adapted from **Z-Anatomy** and **BodyParts3D**, shared under CC BY-SA. Terms follow
> **Terminologia Anatomica 2**. Radiology and histology images come from **Wikimedia Commons** contributors, and each
> one shows its author and licence. Layered Human is a study aid, not a medical device.
>
> → *Credits & licences*

#### 12. Final download
**Job:** a second chance to download, with expectations set.
> ## Ready when you are
> About 3.4 GB. Free for Apple silicon Macs (macOS 13 or later) and Windows. The first time you open it, your
> computer may warn you because the app isn't signed with a paid certificate. [Here's what to click.](/download)
>
> **[Download for Mac]** **[Download for Windows]**

### Three alternative hero pairs

| | Headline | Subline |
|---|---|---|
| **A** (recommended) | Peel the body back, layer by layer. | A free 3D anatomy atlas for your computer. Slide from skin to bone, cut a section that names itself, and study for your lab practical offline. |
| **B** | Skin to bone, at your own pace. | Drag one slider and the whole body opens from the surface inwards. 303 lessons set up each view for you. Free for Windows and Mac. |
| **C** | Find every structure before the practical. | 3,922 structures in one 3D body you can peel, section and quiz yourself on. Free, and it works offline. |

A states the mechanism, and the name echoes it. B suits self-learners best. C speaks most directly to students, but
it puts exams ahead of the mechanism, so test it against A (H1).

### Secondary pages

#### /download
**Job:** get a working install with no surprises. **Structure:** OS-detected first card, the other OS beside it, then
the steps, then "after installing".

> # Download Layered Human
> Free. About 3.4 GB. The small download fetches the full app in parts, checks them and installs it for you.
>
> ### Mac
> Apple silicon (M1 or newer), macOS 13 or later. You need about 8 GB free while it installs.
> **[Download for Mac]**
> 1. Open the downloaded disk image and double-click **Install Layered Human**.
> 2. If macOS says the installer "cannot be opened", go to **System Settings → Privacy & Security**, scroll down
>    and click **Open Anyway**.
> 3. The installer downloads the app, checks every part, copies it into **Applications** and opens it. If it stops,
>    run it again.
>
> ### Windows
> **[Download for Windows]**
> 1. Right-click the downloaded file and choose **Run with PowerShell**.
> 2. It downloads the installer parts, joins them and starts the installer. Click through it.
> 3. If a blue "Windows protected your PC" box appears, click **More info**, then **Run anyway**.
>
> ### Why the warning?
> The app isn't signed with a paid developer certificate, so your computer can't check who made it. Only the
> installer needs the extra click. After the first launch the app opens normally. The code is public on GitHub.
>
> ### After installing
> Your progress, quiz history and notes are kept in your user folder, so updates and reinstalls never lose them.
> Changed parts download in the background and open on your next launch. Some updates are large.
>
> Using Linux, or want to run it from source? [Instructions on GitHub](README).

*Installer and file names must be renamed to match (they currently read "Anatomy Explorer"; see §8).*

#### /course: Lab course and lessons
**Job:** let a student check, before downloading, that their topics are covered. Use only real titles.

> # The course inside Layered Human
> 303 lessons in 1,614 steps, filed by lab course, lecture exam, body system, region and level (foundation, core,
> advanced).
>
> ## The lab course
> 109 mini lessons, each a few short steps on one topic. **Learn** walks through the steps with the 3D view set up.
> **Practice** runs a short graded session beside the model.
>
> | Lab | Topics (from the review lessons) |
> |---|---|
> | Lab 1 | Nerves, reflexes and general senses |
> | Lab 2 | The eye and vision; the ear, hearing and balance |
> | Lab 3 | Blood; the heart |
> | Lab 4 | The ECG and heart function |
> | Lab 5 | Vessel walls and the arteries; veins, the portal system and fetal circulation |
> | Lab 6 | The respiratory system |
> | Lab 7 | Lung function and fitness |
> | Lab 8 | The digestive system; the urinary system |
> | Lab 9 | The male reproductive system; the female system and early development |
> | Lab Practical 1 | Review of Labs 1–5, with a practice exam |
> | Lab Practical 2 | Review of Labs 6–9, with a practice exam |
>
> ## Beyond the lab course
> A sample from the library: *The brachial plexus* · *The rotator cuff* · *The carpal tunnel* · *The femoral
> triangle* · *The skull: vault, face and sutures* · *The brainstem* · *The coronary circulation* · *From the
> tracheal wall to the alveolus* · *Nerve injuries of the upper limb*.
>
> Your course may be organised differently. Search finds any structure, lesson or case by name.

*Don't name a university, course code or textbook (see §6). The lab order mirrors one course* (inferred).

#### /credits: Credits & licences
**Job:** meet CC BY-SA attribution and show honesty. The content is the README's Licence and Credits sections,
rewritten for the new name:
- Atlas: Z-Anatomy, "The libre 3D atlas of anatomy", CC BY-SA 4.0 (Gauthier Kervyn et al.).
- Models: BodyParts3D, © The Database Center for Life Science (DBCLS), CC BY-SA 2.1 Japan.
- Terms: Terminologia Anatomica 2 (FIPAT). Descriptions: Wikipedia, CC BY-SA 3.0.
- Images: Wikimedia Commons contributors; each image shows its author, licence and source in the app.
- Code and original content: MIT, © 2026 Ethan Prince. Qt and PySide6 under LGPL-3.0.
- "If you share the anatomy dataset or anything made from it, credit these sources and share it under the same
  licence."
- "Layered Human is a study aid, not a medical device."

#### /help: Help and FAQ
Every answer below is README-true.
- **Is it really free?** Yes. Download it from GitHub releases. The code is MIT-licensed.
- **Do I need the internet?** Only to download it and to get updates. After that it runs entirely on your computer.
- **Which computers does it run on?** Windows, and Macs with Apple silicon (M1 or newer) on macOS 13 or later. On
  Linux you can run it from source.
- **Why is it so big?** About 3.4 GB: a whole-body atlas with 3,922 structures, 41 models and the radiology and
  histology images, all stored on your machine so it works offline.
- **Why does my computer warn me?** The app isn't signed with a paid developer certificate. [What to click.](/download)
- **Where is my progress?** In your user folder. Updating or reinstalling never loses it.
- **Will it match my course?** It has a lab course for Labs 1–9 and two practicals, plus lessons by system, region
  and level. [See the topics.](/course)
- **Can I use it to diagnose?** No. It's a study aid, not a medical device. Radiology models are set up to match
  each film, not fitted to it.
- **Something went wrong.** The app writes an error log to the `logs` folder in your user folder. [Report it on
  GitHub.]
- **I had Anatomy Explorer.** It's the same app with a new name. *(Confirm what happens to existing installs and the
  user folder, §8.)*

---

## 6. Claims

### Ten claims the site may make

| # | Claim (site wording) | README fact backing it |
|---|---|---|
| 1 | "3,922 structures in one 3D body." | "3,922 structures and 11.6 M triangles: bones, joints and ligaments, muscles, …" |
| 2 | "Peel the body from the skin inwards; the hand and the thigh are uncovered together." | Dissect: "The body comes apart from the skin inwards. Depth is measured as a fraction of how thick the body is at each point, so the hand and the thigh are uncovered together." |
| 3 | "Cut a section and every structure it passes through is named." | Cross-sections: "The cut face labels itself: every structure the plane passes through is named around the edge of the view, click a label to select it" |
| 4 | "41 3D models in one viewer, from the kidney down to a podocyte." | "41 interactive 3D models, all opening in one model viewer … a kidney with its nephron in place (one zoom from the whole organ down to a podocyte)" |
| 5 | "104 radiology cases beside the live model; in five chest cases the model shows the disease." | "104 cases put a real image … beside the live model, labelled on both sides. Five chest cases show disease … and the model shows the pathology itself" |
| 6 | "303 lessons in 1,614 steps, with 1,525 recall questions. Each step sets up the view." | "303 lessons in 1,614 steps … 1,525 of the steps ask you a question … Each step also sets the view up for you" |
| 7 | "A lab course for Labs 1–9 and two lab practicals: 109 mini lessons, 1,824 graded practice items, practice exams." | "109 of them make up a lab course: bite-sized mini lessons for Labs 1–9 and two lab-practical reviews, with 1,824 graded practice items and practice exams." |
| 8 | "101 tissues with 1,049 micrographs." | Histology: "101 tissues with 1,049 micrographs from Wikimedia Commons" |
| 9 | "Runs offline. Your progress, quiz history and notes stay on your computer, through every update." | "it runs entirely offline on your machine"; "Your progress, quiz history and notes are kept in your user folder … so updating or reinstalling never loses them." |
| 10 | "Free, with open-source code under the MIT licence." | Licence: "code and its original content are released under the MIT licence"; downloads from GitHub releases. ("Free" is the owner's statement in the brief; the README has no price.) |

**Also supportable:** Hunt with three tries and nothing named; spaced repetition ("a day later if you missed it,
then four days"); Latin names and TA2 IDs; innervation for 468 muscles and the action of 466; 1,109 landmarks; 423
clinical correlations; a true-scale whole heart in 119 parts; captioned figure export; trackpad gestures; every
shortcut can be rebound.

### Claims the site must not make
- **Social proof of any kind:** testimonials, quotes, user or download counts, star ratings, "trusted by", university
  or course logos, "used at…", press mentions, awards. None exist.
- **Comparisons:** "the only", "the first", "unlike [product]", "better than", competitor names or comparison tables.
  Nothing has been verified.
- **Course or textbook alignment:** "matches your syllabus", "aligned to [textbook]", a named university or course
  code. The lab order mirrors one course *(inferred)*, and the lecture-exam lessons use one book's chapter numbering.
- **Outcomes:** "ace your practical", "improve your grades", "exam-ready", "learn anatomy in X days".
- **Clinical use:** "diagnose", "clinical tool", "patient-specific", "the model is the patient's anatomy", "medically
  validated / certified / accurate". The app is a study aid, not a medical device, and radiology models are not fitted
  to the image.
- **Wrong medium:** "cadaver", "real dissection", "photographic", "VR/AR", "AI".
- **Wrong platforms:** Intel Macs, macOS versions before 13, iPad, phone, web or browser, Chromebook, and Linux as a
  download (it runs from source only). A Windows version number (not stated in the README).
- **Install comfort:** "lightweight", "small download", "instant", "signed / verified", "no warnings".
- **Absolute offline or privacy claims:** "never needs the internet" (download and updates do). "We collect no data"
  or "private by design" until the owner confirms there is no telemetry.
- **Absolutes about content:** "every structure in the body", "complete anatomy", "all of A&P". "True-scale" applies
  only to the whole heart and the kidney with the nephron; never apply it to "all models".
- **Measurement accuracy:** no "millimetre-accurate" or similar for Measure. Accuracy isn't stated.
- **Permanence or price promises:** "free forever", "always free", pricing tiers, donation tiers.
- **Update promises:** "updates are always small". The README says some releases need a substantial download.
- **Any number not in the README.**

---

## 7. Wordmark and logo concepts (in words)

Constraint: simple colours that don't compete with the model (owner, binding). The old Vitruvian circle is retired.
Every concept below works in one colour and at favicon size.

**1. The cut-away: nested contours with a corner opened.**
Three concentric rounded outlines (skin, muscle, bone), like contour lines or the rings of a section. One quadrant
is cut away so you can see in to the innermost ring, borrowing the model viewer's own "Cut-away". As an icon it
reads as "layers, opened". Beside it sits the wordmark in a plain humanist sans: **Layered Human**, sentence case, one
weight. Recommended for the app icon and favicon, because it is the strongest at small sizes.

**2. The depth rule: a wordmark sitting on the slider.**
The words **Layered Human** sit on a thin horizontal rule split into three segments, each a lighter tint of one colour
(superficial to deep). A small round thumb rests partway along it. The rule is the dissection slider's track, so the
same shape can appear in the app's own slider and as the site's section divider. The mark is static; on the site,
a reduced-motion-safe version can slide the thumb once on load.

**3. The label: the name as one of the app's own labels.**
The wordmark sits inside the same pill the app uses for structure labels. A thin leader line runs from the pill to
a single dot, as if the name were labelling a structure on a cut face. It ties straight to "sections that label
themselves". It makes a distinctive site motif: section headings can use the same leader-line device to point at
the screenshot below them. It is weaker as an app icon, so pair it with concept 1.

**Recommendation:** concept 1 for the icon and favicon, the plain wordmark for the app header, and concept 3's
leader line as the site's graphic device. Visual design itself is a separate discipline. This section only sets the
idea each mark must carry.

---

## 8. Open questions for the owner

1. **Audience *(inferred)*.** Is the lab course modelled on your own course? May the site say "built alongside an
   A&P lab course" without naming it?
2. **"No account".** PRODUCT.md says there is no account or subscription, but the README doesn't say so outright.
   Confirm before the site says "no account".
3. **Telemetry.** Does the app send anything at all (update checks aside)? This decides whether the site can make any
   privacy claim.
4. **Windows size and requirements.** The README gives about 3.4 GB and 8 GB of free space only for the Mac. Confirm
   the Windows size, free space and minimum Windows version.
5. **Rename mechanics.** Installer names (`Install-Anatomy-Explorer-Mac.dmg`), the Start-menu name, the user folder
   (`AnatomyExplorer`) and the GitHub repo all carry the old name. Will updates migrate existing installs and keep
   the user folder? The FAQ needs one true sentence about this.
6. **Mac installer resume.** The README says "if it stops you can simply run it again". Does it reuse parts it has
   already checked? That decides the error copy in §3.
7. **Analytics.** Should the site measure anything? If so, prefer GitHub release download counts over page tracking.
   That would let H1 and H2 be tested.
8. **Free forever?** The site will say "free". Do you want to say anything about the future?
