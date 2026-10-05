# Radiology teaching library

104 image teaching cases, 454 numbered labels and 128 self-check questions. The runtime images have 104 distinct published source-file pages. A teaching case can contain paired views, several modality panels or a reviewed still from a cine image; the count does not mean independent patients.

The source image and the atlas serve different teaching purposes. The atlas is not registered to patient images. CT/MRI section references display only their selected physical atlas plane. An oblique scan may use an explicitly approximate orthogonal atlas reference. MRCP, angiography, radiographs, ultrasound and functional images retain their appropriate projection or reference mode.

Published scan findings remain scoped to their source captions and visible image evidence. Labels without an available atlas structure remain image-only. Original baseline case IDs and structure aliases are preserved.

## Coverage

| Modality | Cases |
|---|---:|
| Angiography | 10 |
| CT | 12 |
| Fluoroscopy | 6 |
| MRI | 15 |
| Mammography | 5 |
| Nuclear medicine | 8 |
| Ultrasound | 19 |
| X-ray | 29 |

| Body region | Cases |
|---|---:|
| Abdomen | 21 |
| Breast | 5 |
| Head and neck | 21 |
| Lower limb | 12 |
| Pelvis | 8 |
| Spine | 7 |
| Thorax | 20 |
| Upper limb | 8 |
| Whole body | 2 |

| Plane / projection | Cases |
|---|---:|
| AP glenoid (Grashey) projection | 1 |
| AP projection | 5 |
| Axial | 17 |
| Coronal | 1 |
| Dorsopalmar projection | 1 |
| Functional | 5 |
| Lateral projection | 6 |
| Longitudinal | 8 |
| Oblique | 3 |
| PA projection | 1 |
| Planar | 4 |
| Projection | 39 |
| Sagittal | 5 |
| Transverse | 4 |
| Unspecified | 4 |

## Provenance and reuse

[sources.json](sources.json) records image authors, individual source pages, licenses and source descriptions. New images also record reviewed-input and runtime SHA-256 values, crop changes and privacy-review evidence. The [per-image license inventory](LICENSES.md) lists each displayed asset. Cropped images retain their source license, including ShareAlike conditions. Numbered labels are a separate application overlay. New runtime PNGs contain fresh pixel data with image metadata removed; reviewed crops remove identifying film headers.

## Local verification

Run with this clone's Windows virtual environment. GPU checks use the coordinated local render queue and the isolated launch wrapper.

```powershell
& .\.venv\Scripts\python.exe -B .\tools\check_radiology.py --json .\local-verification\radiology\inventory.json
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_radiology_content.py
& .\.venv\Scripts\python.exe -B .\tools\local_launch.py --tool tools/check_radiology_ui.py
# Queue this GPU check through tools/local_render_queue.py:
& .\.venv\Scripts\python.exe -B .\tools\local_launch.py --tool tools/check_radiology_sections.py --all-workflows
```

Validation checks local image decoding, image hashes, license fields, finite normalized coordinates, questions and all linked anatomy. Native section checks reconstruct every foreground depth pixel, verify all three anatomical axes and orientation, and exercise selection, side handling, saved views, close/reset and ordinary projection workflows. Numeric checks complement visual review and do not constitute clinical certification.
