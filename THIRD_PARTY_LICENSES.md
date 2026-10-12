# Third-party licences and credits

Anatomy Explorer's own code and original content are under the MIT licence (see `LICENSE`). Everything listed
here belongs to someone else and keeps its own licence. The MIT licence does **not** apply to it. Section 5 says
which items are the project's own and what the owner has stated about the origin of some of them.

The app is **not** free of share-alike material. The anatomy dataset in section 1 (`data/anatomy`,
`data/findings`) is CC BY-SA 4.0 and its definition texts include Wikipedia excerpts under CC BY-SA 3.0; they are
still shipped. The histology and radiology images (sections 2 and 3) are CC0, public domain, CC BY or free use,
and none of them is share-alike.

`tools/check_licenses.py` checks that every shipped histology and radiology image records an author, a licence
and a source, and that the licence is one of those: CC0, public domain, CC BY (any version) or "Copyrighted free
use". It also checks that `LICENSE`, this file and `data/anatomy/LICENSE` are present.

## Contents

1. Anatomy dataset (`data/anatomy`, `data/findings`), CC BY-SA 4.0
2. Histology images (`data/histology`), Wikimedia Commons
3. Radiology images (`data/radiology`), Wikimedia Commons
4. Software bundled in the installers
5. Application resources, and where they came from
6. Bundled interface font (Noto Sans), SIL Open Font License 1.1 (the last section)

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

`data/histology/images` (and their `thumbs`) hold **452** images from
[Wikimedia Commons](https://commons.wikimedia.org/), each resized to at most 1280 px. For every image,
`data/histology/catalog.json` records the author, the licence and the Commons file page. The histology viewer
shows them under the image. All of them are CC0, public domain, CC BY, or "Copyrighted free use" (the Commons
tag for an image whose rights holder allows any use without conditions); `tools/check_licenses.py` rejects any other value.

| Licence | Images |
|---|---|
| [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | 161 |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 137 |
| Public domain | 79 |
| [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | 60 |
| [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | 7 |
| [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) | 6 |
| Copyrighted free use | 2 |
| **Total** | **452** |

For 8 images, Commons records no author in the file's metadata. They are credited as "Author not recorded on
Wikimedia Commons (see source page)" and linked to their file page:

- [Illu vein](https://commons.wikimedia.org/wiki/File:Illu_vein.jpg) (Public domain)
- [Illu spleen](https://commons.wikimedia.org/wiki/File:Illu_spleen.jpg) (Public domain)
- [Gobletcell](https://commons.wikimedia.org/wiki/File:Gobletcell.jpg) (Copyrighted free use)
- [Mokraćovod](https://commons.wikimedia.org/wiki/File:Mokra%C4%87ovod.jpg) (Public domain)
- [Illu ureters wall](https://commons.wikimedia.org/wiki/File:Illu_ureters_wall.jpg) (Public domain)
- [Bešika](https://commons.wikimedia.org/wiki/File:Be%C5%A1ika.jpg) (Public domain)
- [Retina](https://commons.wikimedia.org/wiki/File:Retina.gif) (Public domain)
- [HippocampalRegions](https://commons.wikimedia.org/wiki/File:HippocampalRegions.jpg) (Public domain)

## 3. Radiology images: Wikimedia Commons

The 52 images in `data/radiology/images` come from Wikimedia Commons, one for each of the 52 cases. Some were resized to at
most 1280 px or re-encoded. `data/radiology/sources.json` holds each image's record, and every case shows its author and
licence. They are 26 CC0, 5 CC BY 4.0, 6 Public domain, 5 CC BY 3.0, 9 CC BY 2.0, 1 CC BY 2.5.

| Case image | Author | Licence | Source |
|---|---|---|---|
| `angio_coronary_stenosis.png` | Maria A Pantaleo, Anna Mandrioli, Maristella Saponara, Margherita Nannini, Giovanna Erente, Cristian Lolli and Guido Biasco: Development of coronary artery stenosis in a patient with metastatic renal cell carcinoma treated with sorafenib. BMC Cancer, 2012, 12:231 doi:10.1186/1471-2407-12-231 Published: 11 June 2012 | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Angiography coronary stenosis 01](https://commons.wikimedia.org/wiki/File:Angiography_coronary_stenosis_01.jpg) |
| `angio_leg_occlusions.png` | S. P. Whiley, G. Mantokoudis, D. Ott, H. Zimmerman, and A. K. Exadaktylos | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [Lower extremity arteriography](https://commons.wikimedia.org/wiki/File:Lower_extremity_arteriography.jpg) |
| `angio_renal_fmd_after.png` | Zeina AR, Vladimir W, Barmeir E. | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Renal artery angiography in a patient with fibromuscular dysplasia (2)](https://commons.wikimedia.org/wiki/File:Renal_artery_angiography_in_a_patient_with_fibromuscular_dysplasia_(2).jpg) |
| `angio_renal_fmd_before.png` | Zeina AR, Vladimir W, Barmeir E. | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Renal artery angiography in a patient with fibromuscular dysplasia (1)](https://commons.wikimedia.org/wiki/File:Renal_artery_angiography_in_a_patient_with_fibromuscular_dysplasia_(1).jpg) |
| `ankle_ap.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal ankle - frontal](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_ankle_-_frontal.jpg) |
| `ankle_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal ankle - lateral](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_ankle_-_lateral.jpg) |
| `cspine_lat.jpg` | Staff at the Department of Radiology, UC San Diego Health | Public domain | [X-ray of the cervical spine of a 20 year old male - lateral](https://commons.wikimedia.org/wiki/File:X-ray_of_the_cervical_spine_of_a_20_year_old_male_-_lateral.jpg) |
| `ct_abdo_kidney.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal abdomen and pelvis, axial plane 35](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_abdomen_and_pelvis,_axial_plane_35.png) |
| `ct_abdo_upper.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal abdomen and pelvis, axial plane 26](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_abdomen_and_pelvis,_axial_plane_26.png) |
| `ct_bilateral_renal_calculi.png` | Kristie Guite, Louis Hinshaw and Fred Lee | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [Non-contrast CT of multiple bilateral renal calculi](https://commons.wikimedia.org/wiki/File:Non-contrast_CT_of_multiple_bilateral_renal_calculi.jpg) |
| `ct_brain.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of a normal brain, axial 21](https://commons.wikimedia.org/wiki/File:CT_of_a_normal_brain,_axial_21.png) |
| `ct_pneumonia.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [CT of lobar pneumonia](https://commons.wikimedia.org/wiki/File:CT_of_lobar_pneumonia.jpg) |
| `ct_saddle_pulmonary_embolism.png` | Aung Myat and Arif Ahsan | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Pulmonary embolism CTPA](https://commons.wikimedia.org/wiki/File:Pulmonary_embolism_CTPA.JPEG) |
| `cxr_chf.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Chest radiograph of a lung with Kerley B lines](https://commons.wikimedia.org/wiki/File:Chest_radiograph_of_a_lung_with_Kerley_B_lines.jpg) |
| `cxr_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Normal lateral chest radiograph (X-ray)](https://commons.wikimedia.org/wiki/File:Normal_lateral_chest_radiograph_(X-ray).jpg) |
| `cxr_pa.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Normal posteroanterior (PA) chest radiograph (X-ray)](https://commons.wikimedia.org/wiki/File:Normal_posteroanterior_(PA)_chest_radiograph_(X-ray).jpg) |
| `cxr_pneumonia.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of lobar pneumonia](https://commons.wikimedia.org/wiki/File:X-ray_of_lobar_pneumonia.jpg) |
| `cxr_pneumothorax.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Expired X-ray of pneumothorax](https://commons.wikimedia.org/wiki/File:Expired_X-ray_of_pneumothorax.jpg) |
| `elbow_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal elbow by anteroposterior projection](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_elbow_by_anteroposterior_projection.jpg) |
| `fluoro_achalasia.png` | Farnoosh Farrokhi, Michael F. Vaezi. | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Acha](https://commons.wikimedia.org/wiki/File:Acha.JPG) |
| `fluoro_aspiration.png` | Cristina Fuentes Santos and Bárbara Steen | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [Aspiration on barium swallow](https://commons.wikimedia.org/wiki/File:Aspiration_on_barium_swallow.jpg) |
| `fluoro_swallow_normal.png` | Hellerhoff | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [Normaler Schluck-33](https://commons.wikimedia.org/wiki/File:Normaler_Schluck-33.jpg) |
| `foot_lat.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal right foot by lateral projection](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_right_foot_by_lateral_projection.jpg) |
| `hand_pa.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal hand by dorsoplantar projection](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_hand_by_dorsoplantar_projection.jpg) |
| `hip_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal hip](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_hip.jpg) |
| `knee_ap.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal knee by anteroposterior projection](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_knee_by_anteroposterior_projection.jpg) |
| `knee_lat.jpg` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of a normal knee by lateral projection](https://commons.wikimedia.org/wiki/File:X-ray_of_a_normal_knee_by_lateral_projection.jpg) |
| `mammo_nonspecific_abnormal.png` | Unknown photographer | Public domain | [Abnormal mammogram](https://commons.wikimedia.org/wiki/File:Abnormal_mammogram.jpg) |
| `mammo_normal.png` | Unknown photographer | Public domain | [Normal mammogram](https://commons.wikimedia.org/wiki/File:Normal_mammogram.jpg) |
| `mammo_small_cancer.png` | Unknown photographer | Public domain | [Mammogram showing small lesion](https://commons.wikimedia.org/wiki/File:Mammogram_showing_small_lesion.jpg) |
| `mri_dilated_cardiomyopathy_comparison.png` | MBq | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Cardiomr dcm](https://commons.wikimedia.org/wiki/File:Cardiomr_dcm.jpg) |
| `mri_hyperacute_basal_ganglia_infarct.png` | Jian-Min Shen, Xian-Wu Xia, Wu-Gen Kang, Jian-Jun Yuan and Liang Sheng | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Cerebral infarction after 4 hours on DWI MRI](https://commons.wikimedia.org/wiki/File:Cerebral_infarction_after_4_hours_on_DWI_MRI.jpg) |
| `mri_hyperacute_basal_ganglia_infarct_adc.png` | Jian-Min Shen, Xian-Wu Xia, Wu-Gen Kang, Jian-Jun Yuan and Liang Sheng | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Cerebral infarction after 4 hours on ADC MRI](https://commons.wikimedia.org/wiki/File:Cerebral_infarction_after_4_hours_on_ADC_MRI.jpg) |
| `mri_l4_l5_disc_herniation.png` | Miguel Tremblay | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Hernie discale L4 L5](https://commons.wikimedia.org/wiki/File:Hernie_discale_L4_L5.png) |
| `nuclear_balanced_ischemia.png` | Driessen et Al. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [Tetrafosmin SPECT vs H2O cardiac PET](https://commons.wikimedia.org/wiki/File:Tetrafosmin_SPECT_vs_H2O_cardiac_PET.jpg) |
| `nuclear_bone_occult_fracture.png` | Mohamed Jarraya, Daichi Hayashi, Frank W. Roemer, Michel D. Crema, Luis Diaz, Jane Conlin, Monica D. Marra, Nabil Jomaah and Ali Guermazi | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [Bone scintigraphy of subcapital insufficiency fracture](https://commons.wikimedia.org/wiki/File:Bone_scintigraphy_of_subcapital_insufficiency_fracture.jpg) |
| `nuclear_hodgkin_petct.png` | Hg6996 | Public domain | [HodgkinLymphomPETCT](https://commons.wikimedia.org/wiki/File:HodgkinLymphomPETCT.jpg) |
| `nuclear_renal_function.png` | Danko Milošević, Ernest Bilić, Danica Batinić, Mirjana Poropat, Ranka Štern-Padovan, Slobodan Galić and Daniel Turudić | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [99mTc-MAG3 and 99mTc-DTPA renogram](https://commons.wikimedia.org/wiki/File:99mTc-MAG3_and_99mTc-DTPA_renogram.jpg) |
| `nuclear_vq_embolism.png` | Westgate EJ, FitzGerald GA | [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/) | [Pulmonary embolism scintigraphy PLoS](https://commons.wikimedia.org/wiki/File:Pulmonary_embolism_scintigraphy_PLoS.png) |
| `pelvis_ap.jpg` | Staff at the Department of Radiology, UC San Diego Health | Public domain | [X-ray of the pelvis of an 18 year old male - case 2 - anteroposterior](https://commons.wikimedia.org/wiki/File:X-ray_of_the_pelvis_of_an_18_year_old_male_-_case_2_-_anteroposterior.jpg) |
| `shoulder_ap.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Anteroposterior glenoid (Grashey view) X-ray of a normal shoulder](https://commons.wikimedia.org/wiki/File:Anteroposterior_glenoid_(Grashey_view)_X-ray_of_a_normal_shoulder.jpg) |
| `us_aaa_axial.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Ultrasonography of abdominal aortic aneurysm in axial plane](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_abdominal_aortic_aneurysm_in_axial_plane.jpg) |
| `us_carotid_complete_occlusion.png` | Shazia Mirza and Sankalp Gokhale | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [Doppler ultrasonography of complete internal carotid artery occlusion](https://commons.wikimedia.org/wiki/File:Doppler_ultrasonography_of_complete_internal_carotid_artery_occlusion.png) |
| `us_femoral_dvt.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Ultrasonography of deep vein thrombosis of the femoral vein](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_deep_vein_thrombosis_of_the_femoral_vein.jpg) |
| `us_focal_steatosis.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Ultrasonography of focal steatosis](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_focal_steatosis.jpg) |
| `us_gallstones_sludge.png` | Mikael Häggström, M.D. | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Ultrasonography of sludge and gallstones](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_sludge_and_gallstones.jpg) |
| `us_hydronephrosis_cortical_atrophy.png` | Kristoffer Lindskov Hansen; Michael Bachmann Nielsen; Caroline Ewertsen | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [Ultrasonography of hydronephrosis with dilated anechoic pelvis and calyces, along with cortical atrophy](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_hydronephrosis_with_dilated_anechoic_pelvis_and_calyces%2C_along_with_cortical_atrophy.jpg) |
| `us_normal_adult_kidney.png` | Kristoffer Lindskov Hansen; Michael Bachmann Nielsen; Caroline Ewertsen | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [Normal adult kidney](https://commons.wikimedia.org/wiki/File:Normal_adult_kidney.jpg) |
| `us_normal_liver.png` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [Ultrasonography of a normal liver](https://commons.wikimedia.org/wiki/File:Ultrasonography_of_a_normal_liver.jpg) |
| `us_paraovarian_cyst_tubal_torsion.png` | Liang Qian, Xue Wang, Dingheng Li, Songyi Li and Jiashan Ding | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [Ultrasonographic identification of a cystic mass in the right lower abdomen](https://commons.wikimedia.org/wiki/File:Ultrasonographic_identification_of_a_cystic_mass_in_the_right_lower_abdomen.jpg) |
| `wrist_lat.jpg` | Mikael Häggström | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | [X-ray of normal wrist by lateral projection](https://commons.wikimedia.org/wiki/File:X-ray_of_normal_wrist_by_lateral_projection.jpg) |
| `xr_bilateral_renal_stones.png` | Bill Rhodes from Asheville | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | [Kidney stones abdominal X-ray](https://commons.wikimedia.org/wiki/File:Kidney_stones_abdominal_X-ray.jpg) |

The case texts in `data/content/radiology*.json` carry 14 links to 7 pages of OpenStax *Anatomy and Physiology 2e*
(in 13 of the cases) as further reading; the links are references only and no OpenStax text or image is shipped. On 2026-10-12
the wording of those 13 cases was compared with the linked pages and none was found copied or close to it.

## 4. Software bundled in the installers

The Apple-silicon macOS build uses a locally rebuilt Qt 6.11.2 Cocoa platform plugin with the ownership repair
from Qt Gerrit change 765434, patch set 1 (unmerged and unreleased upstream). Only the Cocoa plugin is replaced;
the matching PySide6 wheel frameworks are retained. The accepted binary, build recipe, exact patch, modified
plugin source, upstream source reference and Qt licence texts are in `packaging/qt-cocoa` in this repository.
They are included under `licenses/qt-cocoa` in the Mac app (the binary itself is the platform plugin).
The rebuilt plugin is **arm64 only**, and macOS 13 or later is required. It retains native accessibility.

The Windows and macOS installers are built with PyInstaller and contain these libraries. Where a wheel ships
its licence files, `packaging/AnatomyExplorer.spec` copies them into the bundle under `licenses/`. The LGPL-3.0
and GPL-3.0 texts for Qt/PySide6 are in `packaging/licenses/`, and so are the wgpu-py licence text and the MIT and
Apache-2.0 texts of wgpu-native.

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
| wgpu-py 0.32 (Python bindings for WebGPU) | [BSD-2-Clause](https://github.com/pygfx/wgpu-py/blob/main/LICENSE), Copyright (c) 2019-2023, Almar Klein, Korijn van Golen; text in `packaging/licenses/wgpu-py-BSD-2-Clause.txt` | <https://github.com/pygfx/wgpu-py> |
| wgpu-native 29.0.1.1 (`wgpu_native-release.dll` inside the wgpu wheel; the version wgpu-py 0.32 targets) | MIT or Apache-2.0 (dual licence, at your choice) | <https://github.com/gfx-rs/wgpu-native> |
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

**wgpu.** The wgpu wheel carries only wgpu-py's own licence file. The installers include that file and also the
MIT and Apache-2.0 texts of wgpu-native (`packaging/licenses/wgpu-native-MIT.txt` and
`packaging/licenses/wgpu-native-Apache-2.0.txt`, copied from the wgpu-native repository at tag v29.0.1.1,
<https://github.com/gfx-rs/wgpu-native>). The wgpu-native binary also contains Rust libraries with licences of
their own, which are not inventoried here.

**Qt / PySide6 (LGPL-3.0).** Anatomy Explorer uses Qt 6 and PySide6 (Qt for Python) under the GNU Lesser General
Public License version 3 (LGPL-3.0). Qt is copyrighted by The Qt Company Ltd. and other contributors. The full
LGPL-3.0 text, and the GPL-3.0 text it builds on, are in `packaging/licenses/LGPL-3.0.txt` and
`packaging/licenses/GPL-3.0.txt`, and the installed app carries them under `licenses/`. Qt and PySide6 are used
unmodified, as dynamically linked libraries, and you may replace them with your own builds of the same (or a
compatible) version. The installed app is a PyInstaller "one-folder" bundle, and the Qt and PySide6 libraries sit
as separate files in its `_internal/PySide6` folder (`Contents/Frameworks/PySide6` in the macOS app), where you can
swap them. The app's own source code is published under MIT, so it can be rebuilt against any Qt version. **Where
to get the Qt source:** Qt's source code is at <https://download.qt.io/official_releases/qt/> (this app uses
Qt 6.11) and PySide6's at <https://code.qt.io/cgit/pyside/pyside-setup.git/>; the source of the one rebuilt
macOS plugin is in `packaging/qt-cocoa`. The installers no longer include Qt WebEngine (Chromium).

## 5. Application resources, and where they came from

The items in the first list are this project's own work and are under the MIT licence (see `LICENSE`).

- `app/resources/logo.svg` is the original Vitruvian-circle application mark. `icon.png` and `icon.ico`
  are rendered from it by `tools/make_icon.py`.
- `app/ui/resources/studio`: the 39 interface icons (16 x 16 SVG strokes), `palettes.json` and the README, made for
  the project's own interface design (the "Study-02" design the README names). The files carry no icon-set marker,
  credit or licence text of anyone else.
- The microanatomy models are generated procedurally by the code in `app/micro` (cached in `data/micro_cache`).
  The 3D models in `models/` (the whole heart, the kidney with its nephron and the cardiac muscle block) were
  built procedurally in Blender for this project from published measurements. The kidney's builder consulted
  Z-Anatomy's kidney as a reference, but none of its geometry is in the model (`models/kidney/README.md`). Together
  these are 38 of the 41 models in `data/local_model_library`; each of the 38 has a builder in this project's tree.
- The model library's text and settings: `data/local_model_library/library.json`, the 41 part guides in
  `data/content/model_parts/`, the 39 summaries in `data/content/model_summaries.json`, and the 85 adapter json
  files in `app/variants/anatomy_runtime_adapters` and `app/variants/anatomy_variants` (cameras, summaries and
  description overrides per model; some cite literature by URL as references only).
- The 102 lesson diagrams in `data/content/diagrams/` (64 named `lab*`, 38 named `lec2*`),
  hand-written SVG made of drawing primitives only: no embedded raster image, no external link, no font file
  (the text names common system fonts only).
- The lessons, clinical correlations, radiology case texts and hand-written descriptions
  (`data/content/lessons*.json`, `clinical*.json`, `radiology*.json`, `descriptions_extra*.json`).

**Statements by the owner, Ethan Prince, made on 2026-10-12.**

1. The three library models `neuron`, `capillary_bed` and `lymph_drainage` (`data/local_model_library/models`) "came
   from sources that are fine for this". He named no source. This project's tree holds no builder, credit or
   licence text for them, so none is given here and none is invented. They are the only library models that
   `LICENSE` does not claim as this project's own builds, and their part guides in `data/content/model_parts/`
   follow the same answer.
2. The lecture notes and the textbook behind the 57 "lecture exam 2" lessons
   (`data/content/lessons_lecture_exam2_*.json`, 6 files) were written for him by an AI assistant. They were not
   copied from a published textbook. 28 of those lessons have a `sources` field that names those notes and that textbook.

The Noto Sans font in the next section is the only bundled font.

## Bundled interface font

Noto Sans Regular and Bold are distributed under SIL Open Font License 1.1. The complete copyright and
license notice is included at `app/ui/resources/fonts/NotoSans/LICENSE.txt`. These font files are not MIT-licensed.
Official source: https://github.com/notofonts/latin-greek-cyrillic/releases/tag/NotoSans-v2.015
