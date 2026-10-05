# Third-party licences and credits

Anatomy Explorer's own code and original content are under the MIT licence (see `LICENSE`). Everything listed
here belongs to someone else and keeps its own licence. The MIT licence does **not** apply to it.

`tools/check_licenses.py` checks that every shipped image and model records an author, a licence and a
source, and that each licence is one we are allowed to redistribute.

## Contents

1. Anatomy dataset (`data/anatomy`, `data/findings`), CC BY-SA 4.0
2. Histology images (`data/histology`), Wikimedia Commons
3. Radiology images (`data/radiology`), Wikimedia Commons
4. Downloaded Sketchfab models (`data/sketchfab_models`), Creative Commons, **17 NonCommercial**
5. Software bundled in the installers
6. Application resources

---

## 1. Anatomy dataset: CC BY-SA 4.0

`data/anatomy` (the meshes, structure hierarchy, names and definition texts) and `data/findings` (the pathology
meshes derived from them) are an adaptation of the works below. They are distributed under the
[Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/) licence.
`data/anatomy/LICENSE` has the full notice.

- **Z-Anatomy**, "The libre 3D atlas of anatomy", Gauthier Kervyn et al.,
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  <https://www.z-anatomy.com/>, <https://github.com/Z-Anatomy/Models-of-human-anatomy>.
  The Z-Anatomy readme credits the further works it is derived from.
- **BodyParts3D**, © The Database Center for Life Science (DBCLS),
  [CC BY-SA 2.1 Japan](https://creativecommons.org/licenses/by-sa/2.1/jp/). <https://lifesciencedb.jp/bp3d/>.
  Z-Anatomy's meshes are derived from it.
- **Terminologia Anatomica 2 (TA2)**, Federative International Programme for Anatomical Terminology (FIPAT).
  Its term list, as distributed with Z-Anatomy, supplies the structure names and hierarchy.
  <https://fipat.library.dal.ca/>
- **Wikipedia**, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). About two thirds of the
  definition texts in `data/anatomy/definitions.json` are Wikipedia excerpts that came with Z-Anatomy. Each one
  ends with the URL of its article, whose history lists the authors. The remaining texts are Z-Anatomy's own
  (CC BY-SA 4.0), some of them in the wording of *Gray's Anatomy* (1918, public domain).

Changes: `tools/export_zanatomy.py` and `tools/build_dataset.py` exported the Z-Anatomy Blender atlas and
converted it into vertex/index buffers, a JSON hierarchy and sample caches. `tools/build_findings.py`
deformed those meshes into the pathology findings (effusion, pneumothorax, consolidation, cardiomegaly and
similar).

## 2. Histology images: Wikimedia Commons

`data/histology/images` (and their `thumbs`) hold **1021** images from
[Wikimedia Commons](https://commons.wikimedia.org/), each resized to at most 1280 px. For every image,
`data/histology/catalog.json` records the author, the licence and the Commons file page. The histology viewer
shows them under the image.

| Licence | Images |
|---|---|
| [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | 271 |
| [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | 248 |
| [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | 164 |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 147 |
| Public domain | 85 |
| [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | 63 |
| [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/) | 15 |
| [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | 10 |
| [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) | 6 |
| [CC BY-SA 2.0 DE](https://creativecommons.org/licenses/by-sa/2.0/de/) | 4 |
| [CC BY-SA 2.5](https://creativecommons.org/licenses/by-sa/2.5/) | 2 |
| Copyrighted free use | 2 |
| No restrictions (Flickr Commons / Internet Archive Book Images) | 2 |
| [GNU FDL](https://www.gnu.org/licenses/fdl-1.2.html) (text shipped in `packaging/licenses/GFDL-1.2.txt`) | 1 |
| [CC BY-SA 3.0 DE](https://creativecommons.org/licenses/by-sa/3.0/de/) | 1 |

For 18 images, Commons records no author in the file's metadata. They are credited as "Author not recorded on
Wikimedia Commons (see source page)" and linked to their file page:

- [Hyaline cartilage](https://commons.wikimedia.org/wiki/File:Hyaline_cartilage.jpg) (CC BY-SA 3.0)
- [Compact bone - ground cross section](https://commons.wikimedia.org/wiki/File:Compact_bone_-_ground_cross_section.jpg) (CC BY-SA 3.0)
- [Spongy bone - trabecules](https://commons.wikimedia.org/wiki/File:Spongy_bone_-_trabecules.jpg) (CC BY-SA 3.0)
- [Spinal Cord Progenitors Isolated from the Cord and Grown in Tissue Culture as Adherent Cultures or Nonadherent Nanospheres](https://commons.wikimedia.org/wiki/File:Spinal_Cord_Progenitors_Isolated_from_the_Cord_and_Grown_in_Tissue_Culture_as_Adherent_Cultures_or_Nonadherent_Nanospheres.png) (CC BY 4.0)
- [HippocampalRegions](https://commons.wikimedia.org/wiki/File:HippocampalRegions.jpg) (Public domain)
- [Aorta histo](https://commons.wikimedia.org/wiki/File:Aorta_histo.jpg) (CC BY-SA 3.0)
- [Illu vein](https://commons.wikimedia.org/wiki/File:Illu_vein.jpg) (Public domain)
- [Illu spleen](https://commons.wikimedia.org/wiki/File:Illu_spleen.jpg) (Public domain)
- [Toothbud11-19-05labeled](https://commons.wikimedia.org/wiki/File:Toothbud11-19-05labeled.jpg) (CC BY-SA 3.0)
- [Gobletcell](https://commons.wikimedia.org/wiki/File:Gobletcell.jpg) (Copyrighted free use)
- [Animal liver](https://commons.wikimedia.org/wiki/File:Animal_liver.jpg) (CC BY-SA 3.0)
- [Mokraćovod](https://commons.wikimedia.org/wiki/File:Mokra%C4%87ovod.jpg) (Public domain)
- [Transverseureter](https://commons.wikimedia.org/wiki/File:Transverseureter.png) (Public domain)
- [Illu ureters wall](https://commons.wikimedia.org/wiki/File:Illu_ureters_wall.jpg) (Public domain)
- [Bešika](https://commons.wikimedia.org/wiki/File:Be%C5%A1ika.jpg) (Public domain)
- [Oviduct-histo](https://commons.wikimedia.org/wiki/File:Oviduct-histo.jpg) (CC BY-SA 3.0)
- [VaginaHisto](https://commons.wikimedia.org/wiki/File:VaginaHisto.jpg) (CC BY-SA 3.0)
- [Retina](https://commons.wikimedia.org/wiki/File:Retina.gif) (Public domain)

## 3. Radiology images: Wikimedia Commons

The 24 images in `data/radiology/images` come from Wikimedia Commons. Some were resized to at most 1280 px or
re-encoded. `data/radiology/sources.json` holds each image's record, and every case shows its author and licence.

| Case image | Author | Licence | Source |
|---|---|---|---|
| `cxr_pa.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Normal posteroanterior (PA) chest radiograph (X-ray).jpg](https://commons.wikimedia.org/wiki/File:Normal_posteroanterior_(PA)_chest_radiograph_(X-ray).jpg) |
| `cxr_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Normal lateral chest radiograph (X-ray).jpg](https://commons.wikimedia.org/wiki/File:Normal_lateral_chest_radiograph_(X-ray).jpg) |
| `hand_pa.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal hand by dorsoplantar projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_hand_by_dorsoplantar_projection.jpg) |
| `wrist_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal wrist by lateral projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_wrist_by_lateral_projection.jpg) |
| `elbow_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal elbow by anteroposterior projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_elbow_by_anteroposterior_projection.jpg) |
| `knee_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal knee by anteroposterior projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_knee_by_anteroposterior_projection.jpg) |
| `knee_lat.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal knee by lateral projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_knee_by_lateral_projection.jpg) |
| `foot_lat.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal right foot by lateral projection.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_right_foot_by_lateral_projection.jpg) |
| `hip_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal hip.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_hip.jpg) |
| `pelvis_ap.jpg` | Staff at the Department of Radiology, UC San Diego Health | Public domain | [X-ray of the pelvis of an 18 year old male - case 2 - anteroposterior.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_the_pelvis_of_an_18_year_old_male_-_case_2_-_anteroposterior.jpg) |
| `cspine_lat.jpg` | Staff at the Department of Radiology, UC San Diego Health | Public domain | [X-ray of the cervical spine of a 20 year old male - lateral.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_the_cervical_spine_of_a_20_year_old_male_-_lateral.jpg) |
| `ct_abdo_upper.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal abdomen and pelvis, axial plane 26.png](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_abdomen_and_pelvis,_axial_plane_26.png) |
| `ct_abdo_kidney.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal abdomen and pelvis, axial plane 35.png](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_abdomen_and_pelvis,_axial_plane_35.png) |
| `ct_brain.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal brain, axial 21.png](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_brain,_axial_21.png) |
| `mri_brain_t2.png` | Sean Novak | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | [Brain-T2-axial.png](https://commons.wikimedia.org/wiki/File:Brain-T2-axial.png) |
| `mri_knee.jpg` | Marios G Lykissas, George I Mataliotakis, Nikolaos Paschos, Christos Panovrakos, Alexandros E Beris and Christos D Papageorgiou | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/) | [MRT ACL PCL 01.jpg](https://commons.wikimedia.org/wiki/File:MRT_ACL_PCL_01.jpg) |
| `shoulder_ap.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Anteroposterior glenoid (Grashey view) X-ray of a normal shoulder.jpg](https://commons.wikimedia.org/wiki/File:Anteroposterior_glenoid_(Grashey_view)_X-ray_of_a_normal_shoulder.jpg) |
| `ankle_ap.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal ankle - frontal.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_ankle_-_frontal.jpg) |
| `ankle_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal ankle - lateral.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_ankle_-_lateral.jpg) |
| `cxr_pneumonia.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of lobar pneumonia.jpg](https://commons.wikimedia.org/wiki/File:X-ray_of_lobar_pneumonia.jpg) |
| `ct_pneumonia.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of lobar pneumonia.jpg](https://commons.wikimedia.org/wiki/File:CT_of_lobar_pneumonia.jpg) |
| `cxr_chf.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Chest radiograph of a lung with Kerley B lines.jpg](https://commons.wikimedia.org/wiki/File:Chest_radiograph_of_a_lung_with_Kerley_B_lines.jpg) |
| `cxr_pneumothorax.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Expired X-ray of pneumothorax.jpg](https://commons.wikimedia.org/wiki/File:Expired_X-ray_of_pneumothorax.jpg) |
| `cxr_effusion.jpg` | Sara Nabih | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | [Unilateral Pleural Effusion.jpg](https://commons.wikimedia.org/wiki/File:Unilateral_Pleural_Effusion.jpg) |

## 4. Downloaded Sketchfab models: Creative Commons

> **Non-commercial notice.** 17 of the 21 models in `data/sketchfab_models` are under NonCommercial licences:
> 11 under CC BY-NC or CC BY-NC-SA, and 6 under CC BY-NC-ND. They may be used **for non-commercial purposes only**.
> Anatomy Explorer is free, non-commercial software, and it redistributes these models **unmodified**, exactly
> as Sketchfab's Download API supplied them (`model.glb`). The six **NoDerivatives (ND)** models are never
> modified, and no altered copy of them is shipped. Hiding parts, cut-aways and exploded views happen only on
> screen, at run time. The part names and descriptions in `data/content/sketchfab_parts/` are separate notes
> about the models and are not part of them. If you reuse or redistribute Anatomy Explorer, including
> commercially, you must follow each model's own licence. The simplest way to use Anatomy Explorer commercially
> is to delete the NonCommercial models' folders.

The models were downloaded through Sketchfab's official Download API, and only models their creators marked as
downloadable were fetched. Each folder's `info.json` records the model's creator, licence and page, and the app
shows them in the model's tab. The creators own their models. Anatomy Explorer is not affiliated with Sketchfab
or with any of the creators, and none of them endorses it. Sketchfab is a trademark of its owner.

| Model | Author | Licence | Folder (uid) |
|---|---|---|---|
| [Epithelium of the Trachea](https://sketchfab.com/3d-models/epithelium-of-the-trachea-cb418d1b3f234f04bd3e17075970b222) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `cb418d1b3f234f04bd3e17075970b222` |
| [Ligaments of the Female Pelvis](https://sketchfab.com/3d-models/ligaments-of-the-female-pelvis-34f74adaf3ec4105b987f6162ed85eef) | [University of Dundee School of Medicine](https://sketchfab.com/tilt) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `34f74adaf3ec4105b987f6162ed85eef` |
| [Long Bone](https://sketchfab.com/3d-models/long-bone-900a320bdc6244bd8f6b761441031ae9) | [iqcenter](https://sketchfab.com/iqcenter) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `900a320bdc6244bd8f6b761441031ae9` |
| [Mesenteric Artery Wall](https://sketchfab.com/3d-models/mesenteric-artery-wall-82116db1c25d4bac8ac35dfbab37b578) | [XR Life Science](https://sketchfab.com/GLS) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `82116db1c25d4bac8ac35dfbab37b578` |
| [Plastinated Heart0137 Classic Valve View](https://sketchfab.com/3d-models/plastinated-heart0137-classic-valve-view-a82aea949e4b470f888dd43983ed83cf) | [VisibleHeartLabs](https://sketchfab.com/VisibleHeartLabs) | [**CC BY-NC 4.0**](https://creativecommons.org/licenses/by-nc/4.0/) | `a82aea949e4b470f888dd43983ed83cf` |
| [Anatomy of the airways](https://sketchfab.com/3d-models/anatomy-of-the-airways-ad7d7e16b98f421db0cda79f265fcc8d) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `ad7d7e16b98f421db0cda79f265fcc8d` |
| [Anatomy of the Inner Ear](https://sketchfab.com/3d-models/anatomy-of-the-inner-ear-f80bda64666c4b8aaac8f63b7b82a0a0) | [University of Dundee School of Medicine](https://sketchfab.com/tilt) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `f80bda64666c4b8aaac8f63b7b82a0a0` |
| [Anatomy of the skin](https://sketchfab.com/3d-models/anatomy-of-the-skin-56c98c3710d94360a3481dc81aa4910f) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `56c98c3710d94360a3481dc81aa4910f` |
| [Bicuspid Aortic Valve (BAV)](https://sketchfab.com/3d-models/bicuspid-aortic-valve-bav-67fa45d3d8fc46eb948648f2e3474a08) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `67fa45d3d8fc46eb948648f2e3474a08` |
| [Cardiac Anatomy: Coronary arteries of the heart](https://sketchfab.com/3d-models/cardiac-anatomy-coronary-arteries-of-the-heart-00b5f4ec0b984325b453f8df07cd0cb5) | [HannahNewey](https://sketchfab.com/HannahNewey) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `00b5f4ec0b984325b453f8df07cd0cb5` |
| [Cardiac Anatomy: External view of human heart](https://sketchfab.com/3d-models/cardiac-anatomy-external-view-of-human-heart-a3f0ea2030214a6bbaa97e7357eebd58) | [HannahNewey](https://sketchfab.com/HannahNewey) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `a3f0ea2030214a6bbaa97e7357eebd58` |
| [Cardiac conduction system](https://sketchfab.com/3d-models/cardiac-conduction-system-20a5e36391474f2b99e1a4c94c707b47) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `20a5e36391474f2b99e1a4c94c707b47` |
| [Heart, valves and auscultation sites](https://sketchfab.com/3d-models/heart-valves-and-auscultation-sites-89835764b1e045ee8b4921454254c7c9) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `89835764b1e045ee8b4921454254c7c9` |
| [Urinary tract](https://sketchfab.com/3d-models/urinary-tract-822b2eeb033f42f6a8e0e141287bf34d) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `822b2eeb033f42f6a8e0e141287bf34d` |
| [Ventricular Septal Defect](https://sketchfab.com/3d-models/ventricular-septal-defect-e4e0143741f64025af101658210c8c5d) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-SA 4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/) | `e4e0143741f64025af101658210c8c5d` |
| [Abdomen Anatomy](https://sketchfab.com/3d-models/abdomen-anatomy-ed05d3b7b49b4014a09d7a9d62e4f421) | [E-learning UMCG](https://sketchfab.com/eLearningUMCG) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `ed05d3b7b49b4014a09d7a9d62e4f421` |
| [Epithelium of the Bladder](https://sketchfab.com/3d-models/epithelium-of-the-bladder-a5174dcebd2e478d88b65a85a500c344) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `a5174dcebd2e478d88b65a85a500c344` |
| [Epithelium of the Colon](https://sketchfab.com/3d-models/epithelium-of-the-colon-8973d00c48b848c08beb9d1ff01bdb0e) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `8973d00c48b848c08beb9d1ff01bdb0e` |
| [Epithelium of the Duodenum](https://sketchfab.com/3d-models/epithelium-of-the-duodenum-9e24c98f1e924d40a274acb03428fab4) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `9e24c98f1e924d40a274acb03428fab4` |
| [Polycystic kidney](https://sketchfab.com/3d-models/polycystic-kidney-0ff51e6303e84b83a75d510192a34e92) | [Sieben Medical Art](https://sketchfab.com/siebenmedicalart) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `0ff51e6303e84b83a75d510192a34e92` |
| [Visible Interactive Human - Exploding skull](https://sketchfab.com/3d-models/visible-interactive-human-exploding-skull-252887e2e755427c90d9e3d0c6d3025f) | [WitmerLab at Ohio University](https://sketchfab.com/witmerlab) | [**CC BY-NC-ND 4.0**](https://creativecommons.org/licenses/by-nc-nd/4.0/) | `252887e2e755427c90d9e3d0c6d3025f` |

## 5. Software bundled in the installers

The Apple-silicon macOS build uses a locally rebuilt Qt 6.11.2 Cocoa platform plugin with the ownership repair
from Qt Gerrit change 765434, patch set 1 (unmerged and unreleased upstream). Only the Cocoa plugin is replaced;
the matching PySide6 wheel frameworks are retained. The accepted binary, build recipe, exact patch, modified
plugin source, upstream source reference and Qt licence texts are in `packaging/qt-cocoa` in this repository.
They are included under `licenses/qt-cocoa` in the Mac app (the binary itself is the platform plugin).
The rebuilt plugin is **arm64 only**, and macOS 13 or later is required. It retains native accessibility.

The Windows and macOS installers are built with PyInstaller and contain these libraries. Where a wheel ships
its licence files, `packaging/AnatomyExplorer.spec` copies them into the bundle under `licenses/`. The LGPL-3.0
and GPL-3.0 texts for Qt/PySide6 are in `packaging/licenses/`.

| Component | Licence | Project |
|---|---|---|
| Python 3.11 | [PSF License](https://docs.python.org/3/license.html) | <https://www.python.org/> |
| Qt 6 | [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) | <https://www.qt.io/> |
| PySide6 6.11 | [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) | <https://pyside.org/> |
| shiboken6 6.11 | [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) | <https://pyside.org/> |
| NumPy 2.4 (with OpenBLAS) | [BSD-3-Clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt) and bundled permissive licences | <https://numpy.org/> |
| SciPy 1.17 (with OpenBLAS, libgfortran) | [BSD-3-Clause](https://github.com/scipy/scipy/blob/main/LICENSE.txt); libgfortran GPL-3.0 with the GCC Runtime Library Exception | <https://scipy.org/> |
| scikit-image 0.26 | [BSD-3-Clause](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt) | <https://scikit-image.org/> |
| Shapely 2.1 | [BSD-3-Clause](https://github.com/shapely/shapely/blob/main/LICENSE.txt) | <https://github.com/shapely/shapely> |
| GEOS (inside Shapely) | [LGPL-2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html) | <https://libgeos.org/> |
| ModernGL 5.12 | [MIT](https://github.com/moderngl/moderngl/blob/main/LICENSE) | <https://github.com/moderngl/moderngl> |
| glcontext 3.0 | [MIT](https://github.com/moderngl/glcontext/blob/main/LICENSE) | <https://github.com/moderngl/glcontext> |
| Pillow 12 (with libjpeg, libpng, zlib, FreeType and others) | [MIT-CMU (HPND)](https://github.com/python-pillow/Pillow/blob/main/LICENSE) | <https://python-pillow.github.io/> |
| imageio 2.37 | [BSD-2-Clause](https://github.com/imageio/imageio/blob/master/LICENSE) | <https://github.com/imageio/imageio> |
| tifffile | [BSD-3-Clause](https://github.com/cgohlke/tifffile/blob/master/LICENSE) | <https://github.com/cgohlke/tifffile> |
| lazy_loader | [BSD-3-Clause](https://github.com/scientific-python/lazy-loader/blob/main/LICENSE.md) | <https://github.com/scientific-python/lazy-loader> |
| NetworkX 3.6 | [BSD-3-Clause](https://github.com/networkx/networkx/blob/main/LICENSE.txt) | <https://networkx.org/> |
| packaging | [Apache-2.0 or BSD-2-Clause](https://github.com/pypa/packaging/blob/main/LICENSE) | <https://github.com/pypa/packaging> |
| certifi and Mozilla CA roots | [MPL-2.0](https://github.com/certifi/python-certifi/blob/master/LICENSE) | <https://github.com/certifi/python-certifi> |
| PyInstaller bootloader | [GPL-2.0-or-later with the PyInstaller bootloader exception](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt), which allows distributing the built app under any licence | <https://pyinstaller.org/> |

**Qt / PySide6 (LGPL-3.0).** Qt and PySide6 are used unmodified, as dynamically linked libraries, under the GNU
Lesser General Public License v3. You may replace them with your own builds of the same (or a compatible)
version. The installed app is a PyInstaller "one-folder" bundle, and the Qt and PySide6 libraries sit as
separate files in its `_internal/PySide6` folder (`Contents/Frameworks/PySide6` in the macOS app), where you can
swap them. The app's own source code is published under MIT, so it can be rebuilt against any Qt version. Qt's
source code is at <https://download.qt.io/official_releases/qt/> and PySide6's at
<https://code.qt.io/cgit/pyside/pyside-setup.git/>. The installers no longer include Qt WebEngine (Chromium).

## 6. Application resources

- `app/resources/logo.svg` is the original Vitruvian-circle application mark. `icon.png` and `icon.ico`
  are rendered from it by `tools/make_icon.py`; these original application graphics are part of this project (MIT).
- The microanatomy models (`app/micro`, cached in `data/micro_cache`) are generated procedurally by this
  project's code and are MIT-licensed.
- The 3D models in `models/` (the whole heart, the kidney with its nephron and the cardiac muscle block) were
  built procedurally in Blender for this project from published measurements and are part of it (MIT). The
  kidney's builder consulted Z-Anatomy's kidney as a reference, but none of its geometry is in the model
  (`models/kidney/README.md`). So are the lessons, clinical correlations, radiology case texts,
  hand-written descriptions (`data/content/descriptions_extra*.json`) and Sketchfab part notes.
- The app uses no bundled fonts. It uses the operating system's own.

## Bundled interface font

Noto Sans Regular and Bold are distributed under SIL Open Font License 1.1. The complete copyright and
license notice is included at `app/ui/resources/fonts/NotoSans/LICENSE.txt`. These font files are not MIT-licensed.
Official source: https://github.com/notofonts/latin-greek-cyrillic/releases/tag/NotoSans-v2.015
