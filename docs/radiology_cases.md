# Radiology cases

A case puts one still image — a radiograph, a CT slice or an MR slice — beside the live 3D model, labelled on
both sides, and sets the model up so the two show the same thing. Ctrl+R, or the **Radiology** workspace (**Study → Radiology**).

There are 104 cases, each with its own image in `data/radiology/images`. They span eight modalities: X-ray 29,
ultrasound 19, MRI 15, CT 12, angiography 10, nuclear medicine 8, fluoroscopy 6 and mammography 5. By region:

| Region | Cases |
|---|---|
| Abdomen | 21 |
| Head and neck | 21 |
| Thorax | 20 |
| Lower limb | 12 |
| Upper limb | 8 |
| Pelvis | 8 |
| Spine | 7 |
| Breast | 5 |
| Whole body | 2 |

Five chest cases (four films and a CT, in `data/content/radiology_pathology.json`) show disease that the model can
display; see [Showing the pathology in the model](#showing-the-pathology-in-the-model).

## What a case is made of

Cases live in `data/content/radiology*.json` — any file whose name starts with `radiology` is loaded, so they can
be split up however is convenient (`radiology.json`, `radiology_limbs.json`, `radiology_limbs2.json`, `radiology_sections.json`). One
object per case:

```json
{
  "id": "hand_pa",
  "title": "Hand — dorsopalmar",
  "modality": "X-ray",
  "region": "Upper limb",
  "summary": "Eight carpal bones in two rows, and the order you must know them in.",
  "crop": [0.0, 0.0, 0.635, 1.0],
  "text": "<p>…</p>",
  "reading": ["…", "…"],
  "scene": { "systems": ["skeletal"], "regions": ["upper_limb_l"], "side": "Left",
             "view": "anterior", "frame_on": ["Scaphoid bone"] },
  "labels": [
    {"x": 0.455, "y": 0.82, "text": "Scaphoid", "structure": "Scaphoid bone",
     "note": "retrograde blood supply – proximal fractures die"}
  ]
}
```

- `id` must match a key in `data/radiology/sources.json`, which is written by `tools/fetch_radiology.py` and
  carries the file name, the Commons page, the author and the licence. A case whose image has not been
  downloaded is skipped silently, so a half-built collection still runs.
- `crop` is optional, `[x0, y0, x1, y1]` as fractions of the file. Use it when the download contains more than
  the slice you want — the CT series images each carry a locator panel on the right, cropped off here. **Label
  coordinates are fractions of the cropped image, not of the file.**
- `text` is HTML; `reading` becomes a numbered "How to read it" list beneath it.
- `scene` is exactly a lesson step (see `apply_scene` in `app/main_window.py`): `systems`, `regions`, `side`,
  `show`, `focus`, `ghost_focus`, `isolate`, `dissect`, `layer_only`, `clip`, `view`, `frame_on`, `camera`.
- `labels` are numbered in order. Each may name one `structure` or a list of `structures`; clicking the marker on
  the image, or the line in the legend, selects and frames them in 3D. A label with no structure (a CSF space, a
  clear space, a fat plane) still gets a marker and a note — it just is not clickable.

## Getting a case to match its film

Four things have to line up, and each has a gotcha.

**Which way round.** The named views put the patient's left on the right of the screen, like a film. Anterior
is on the left in the `left` view and on the right in the `right` view — so a lateral with anterior to the
image-left wants `"view": "left"`, whatever side of the body was filmed.

**Axial slices.** Use `"view": "inferior"`: from below, anterior is at the top of the screen and the patient's
left is on the right, which is the CT convention. The transverse clip keeps the half *above* the plane by
default, and that is the half you want — from below you then look straight at the cut face. (Passing `true` as
the third element of `clip` flips it and keeps the lower half instead, which is the wrong way for a CT.)

**Sagittal slices.** `clip: [0, f, true]` keeps the half on the patient's right and `"view": "left"` looks at
the cut face from the left, with anterior on the left of the screen — matching a sagittal MR.

The clip position is a fraction of the scene bounding box along that axis, not a world coordinate. The body
spans y −0.0004 … 1.7433, so a transverse fraction is `(y + 0.0004) / 1.7437`. A quick way to find the level is
to print a structure's centroid:

```
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); from app.config import DATA_DIR; from app.data import Dataset; ds=Dataset(DATA_DIR); print([(s['name'], s['centroid'][1]) for s in ds.structures if s['name']=='Vertebra T8'])"
```

**What is visible.** A joint capsule sits exactly over the bones a plain film is read for, so the bone cases ask
for `"systems": ["skeletal"]` alone; a label that names a joint still reveals it on click. Always set `regions`
explicitly — a scene with no `regions` key inherits whatever was last shown, so a case can open looking at the
previous case's limb.

**What is framed.** `frame_on` names structures to frame, and they do not have to be visible — the bone cases
frame on `"Elbow joint"` or `"Hip joint"` with the joints system switched off, which gives a tight box round the
joint while showing only bone. Beware sub-part names: `Olecranon`, `Head of femur` and `Tibial tuberosity` are
landmarks on their parent bone, so they resolve to the *whole* ulna, femur or tibia and framing on them zooms
right out. Check a name's box before using it:

```
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); import numpy as np; from app.config import DATA_DIR; from app.data import Dataset; from app.lessons import Resolver; ds=Dataset(DATA_DIR); r=Resolver(ds); ids=r.resolve_all(['Elbow joint']); print(len(ids), np.array([np.array(ds.structures[i]['bbox']).reshape(2,3) for i in ids]).reshape(-1,3).ptp(axis=0))"
```

When a scene has both a `clip` and a `frame_on`, the `frame_on` wins: a cross-section otherwise frames every
structure the plane cuts, and one long tendon in the list drags the camera out to the whole limb.

## Showing the pathology in the model

A case about disease needs the model to show the disease, so `data/findings` holds a small set of pathology
meshes derived from the normal anatomy by `tools/build_findings.py`:

| Finding | How it is built |
|---|---|
| Right pleural effusion | the right lung's own volume below a fluid level, voxelised, hole-filled and re-meshed, with a meniscus climbing the chest wall |
| Right lung compressed by effusion | the lung's vertices squeezed up above that level and pulled off the chest wall |
| Mediastinum shifted to the left | the heart and trachea translated across the midline |
| Small bilateral pleural effusions | the same fill on both sides at a low level |
| Collapsed left lung (pneumothorax) | the left lung contracted towards its hilum |
| Air in the left pleural space | the normal lung surface pushed out along its normals, as a translucent shell — the cavity the lung has left |
| Consolidated right middle lobe | the lobe itself, nudged out along its normals so it reads as its own surface |
| Enlarged heart | the four chambers scaled about their centre |

`app/findings.py` appends them to the atlas as it loads: extra materials, an extra `findings` system, and extra
structure records whose geometry is concatenated onto the vertex and index buffers in `Dataset.load_geometry`.
From that point they are ordinary structures — selectable, hideable, x-rayable, framed, and named by a
cross-section. If `data/findings` is missing the atlas loads exactly as before.

Two things to know when writing a pathology case:

- **Do not put `findings` in the scene's `systems`.** Turning the whole system on makes every finding visible,
  so a cross-section through the thorax ends up naming an effusion, a pneumothorax and an enlarged heart all at
  once. List the ones you want in `show` instead: an explicit show beats a system that is switched off.
- Put the normal side in `ghost_focus` too, so the healthy lung stays solid next to the abnormal one.

Rebuild after changing the meshes:

```bash
.venv/Scripts/python.exe tools/build_findings.py
```

It takes about a minute. Adding or removing a finding changes the number of structures, which invalidates the
surface-sample cache (`data/anatomy/samples.npz`) automatically.

## Checking label positions

`tools/label_preview.py` draws each case's labels onto its own image with the legend beside them, which is much
faster than opening the app:

```bash
.venv/Scripts/python.exe tools/label_preview.py            # every case, into logs/labels/
.venv/Scripts/python.exe tools/label_preview.py cspine_lat # just one
```

Do this for every new case. Coordinates read off a grid are easy to get a few percent wrong, and a few percent
is the difference between a marker on the vertebral body and a marker in the soft tissue in front of it. It also
accepts an image id and bare `x,y` pairs, to try positions before writing them into the JSON.

## Reading label coordinates off an image

`tools/grid_overlay.py` writes `logs/grid/<id>.png` with a labelled 0.05 grid over the image:

```bash
.venv/Scripts/python.exe tools/grid_overlay.py hand_pa cspine_lat
```

For anything small or low-contrast — carpal bones, the basal ganglia, the sinus tarsi — crop and magnify a
region with an absolute grid over it rather than guessing from the whole image. Coordinates are fractions of
the image with (0, 0) at the top left.

## Adding images

`tools/fetch_radiology.py` downloads from Wikimedia Commons:

```bash
.venv/Scripts/python.exe tools/fetch_radiology.py search "normal chest radiograph"   # candidates + licences
.venv/Scripts/python.exe tools/fetch_radiology.py info "File:Some file.jpg"          # one file's metadata
.venv/Scripts/python.exe tools/fetch_radiology.py                                    # download the wanted list
```

The wanted list is `data/radiology/cache/wanted.json`, a map of case id → Commons `File:` title (it holds 24 of the 104
current images; `data/radiology/sources.json` records all of them). The fetcher
takes the standard 1280 px thumbnail, backs off on rate limits, and records the author, licence, description and
source page in `data/radiology/sources.json`. Only use normal-anatomy images with a licence that allows reuse,
and check each one by eye before adding it — a guessed file title usually does not exist.

## Validating

```bash
.venv/Scripts/python.exe tools/check_radiology.py
```

It checks that every case's image exists, that the system and region keys are real, that label coordinates are
inside 0–1, and that every structure name resolves; it also lists any downloaded image that has no case yet.
