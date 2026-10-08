# Microanatomy models: structure list and modelling brief

The builder code in `app/micro` registers 37 procedural models. (The procedural nephron and cardiac muscle blocks were retired for the in-house Blender models *Kidney and nephron* and *Cardiac muscle*, which open in the same model viewer: see `docs/model_viewer.md`.) The app's model list now comes from the model library (`data/local_model_library`), not from these registrations, so this document describes the builders rather than what the app displays. Most are a small block (or tube segment) of tissue; the lymph node is modelled whole, blood is a thin film of cells, and ten show whole organs or regions at dissection scale: the heart, eyeball, ear, a kidney in coronal section, the liver with the bile ducts and pancreas, the ileocaecal region with the rectum and anal canal, a tooth, and the female and male pelvis (the ear and the two pelvis models with magnified insets beside the specimen). Every structure below is a separate, selectable object in the app. Structures are grouped exactly as the app's layer tree shows them, in the same order.

## Requirements for replacement models (Blender or any other tool)

- **One object per structure**, named exactly as listed below. Use one **collection per group**, named exactly as the group names.
- **Closed (watertight) meshes.** The app's cut-away draws solid cut faces, which only works on closed surfaces. Layers may touch or nest, but each object must be closed on its own.
- **Scale and orientation:**
  - Blocks are about 2 units wide (x), 1.2–1.4 deep (z) and about 1 tall, with the tissue surface or epithelium at the top (+Y up; Blender's Z-up is converted on export).
  - Tube models (arteries, vein, trachea, nerve, skeletal muscle) run along the x axis, about 2 units long.
  - Organ models are drawn to a real scale of their own, stated in the model's scale note (the heart at 1 unit ≈ 6 cm, the eye at 2 units = 24 mm, the pelvis models at 1 unit = 10 cm).
- **Cut-away.** The default cut removes the quadrant x < 0, z > 0 (tubes: x < 0, y > 0). Place key structures (follicles, glands, villi, osteons) so they cross those planes and get sectioned lengthwise. Organ models set their own cut, usually the plane an atlas would section them in (the heart's four-chamber plane, a median section of the pelvis, a coronal section of the kidney or temporal bone).
- **Budget:** about 1–1.5 million triangles per model, built in under three minutes. Materials are optional; colours are assigned per structure in the app.
- **Format:** glTF 2.0 (`.glb`) with a `.viewer.json` sidecar, exported by `tools/blender/export_for_viewer.py`. A model in that form goes in `models/<name>/`, is described in `data/content/models/<id>.json` ; the app loads such a file only for the three in-house ids (`docs/model_viewer.md`).

## How the current models are built

Worth knowing if you are asking someone to match or beat them:

- Vessels are **swept around a curved centreline** whose calibre varies along its length, with a radius that is a free function of angle and position - nothing is a cylinder of revolution. Every coat is its own closed shell, and the tubes that run inside the wall (vasa vasorum, nervi vasorum, a vein's longitudinal muscle bundles) lie in **channels** that the layers part round, so a section shows each as a clean round profile.
- Nerve and skeletal muscle are **bundles of bundles opened like a telescope**: at one end the outer sheath stops and each level of the hierarchy - fascicles, single fibres, and in muscle one fibre fraying into banded myofibrils - is pulled out further than the one containing it, each ending in a flat transverse face.
- Compact bone is a **two-dimensional mosaic of osteons** of different ages, each eroding the ones it overlaps, resolved with polygon booleans and extruded along a wedge of the shaft, so every lamella is a real closed solid.
- The pancreas is built **cell by cell** (its acini as non-overlapping Voronoi regions, so cut faces stay clean): each acinar cell and islet cell is its own closed mesh, and cells that cross a face of the block are clipped and capped so the sides read like the cut surface of a specimen.
- The lymph node's zones (capsule, subcapsular sinus, cortex, paracortex, medulla) are all **cut from one signed-distance field by depth below the capsule**, so they nest exactly and the cut-away sections them all at once, like a slide through the hilum.
- Every free surface carries **the relief of its own cells**: endothelium as cobblestones stretched along the flow, smooth muscle as spindles wrapped around the circumference, urothelium as domed umbrella cells.
- Smooth muscle layers in the gut and bladder are **interlacing bundles** with the plexuses running in the gaps between them; the epimysium carries a **felt of individual collagen bundles**.
- Block models end with one **shared warp** applied to all of their layers at once: a sag that makes surfaces billow and side walls bow, a tissue grain, and a cell-sized micro-relief. Because the warp is a function of position, nested layers stay in register however thin they are.
- Layers that would otherwise bury their contents (thyroid connective tissue, hypodermal septa, splenic cords, bone marrow) are built as the **complement** of what sits inside them, so follicles, fat lobules, sinusoids and trabeculae stay visible.

## Animation

A model can animate by attaching per-vertex morph targets and phases to its parts (`part.anim`) and giving its dataset an `Animation` of per-part tracks (`app/micro/anim.py`). Only a few texels per part change each frame; the vertex buffers never do, and picking and cut faces follow the moving geometry. The model viewer shows Play/Pause (Space), speed and a cycle scrubber for any animated model; `app/viewer/procedural.py` hands the morph targets and phases to its renderer as a second vertex buffer, and `tools/render_micro.py <id> --time T` renders a still and `--frames N -o x.gif` a GIF. The heart's auricles are modelled in Blender by `tools/blender/heart_auricles.py` (run with a Python that has `bpy`) into `data/models/heart_auricles.npz`; bump `AURICLE_ASSET_VERSION` in `heart.py` after regenerating it.

## How cut faces are drawn

The model viewer draws cut faces as **flat sections lying on the cutting plane**, so whatever a part encloses is hidden behind its own section, as on a slide. (The main atlas instead shades the inside of each cut shell.) `Renderer._render_caps` in `app/viewer/renderer.py` runs after the pre-pass whenever a cut-away or a section is on:

1. **Per part, the nearest kept front face.** For each part in turn (parts marked not to be clipped are skipped) `PARITY_FS` writes, at every pixel, the depth of that part's nearest front face on the kept side of the cut (MIN blending).
2. **Where the plane passes through the part.** The part is drawn again with the cap shader: where its first surface behind the cut is a back face that nothing of the same part hides, the plane lies inside the part. This test holds even for meshes that are not quite watertight, unlike counting surfaces. The pixel's ray is rebuilt from the screen position, so every part meeting the plane there gets exactly the same point on it.
3. **Off-screen gather, innermost wins.** The cap colour, normal, id and true plane depth go to an off-screen buffer whose depth test is keyed on how far the part's far wall lies behind the plane. Where several nested parts are cut at the same pixel, the innermost (the one whose wall is nearest the plane) wins.
4. **Composited at plane depth.** `CAPMIX_PRE_FS` and `CAPMIX_FS` lay the gathered caps into the pre-pass and the shaded frame at their true depth on the plane, so they are depth-tested, picked, outlined and labelled like any other surface.

The caps are shaded like a stained section (`tissue_color` with nuclei, fibres and cell outlines) for procedural models, and in the part's own colour, darkened, for the others.

## Where the code lives

All of it is in `app/micro/`. A model is a `MicroModel` (id, name, summary, builder, the atlas structures it is offered for, linked histology, related models, clinical notes, scale note) registered in a registry file; its builder returns the list of parts.

| File | Contents |
|---|---|
| `registry.py` | The `MODELS` table and the four skin models; imports `registry_organs.py`, then every `registry_extra_*.py` |
| `registry_organs.py` | Registration of the gut, wall, vessel, lung, bone, muscle, nerve, kidney, liver, bladder, eye, thyroid and tongue models |
| `registry_extra_*.py` | Further models, one file per batch, each with a `register_all(register)` - found and loaded automatically, so a new model needs no edit to a shared file (`registry_extra_lymphoid.py`: lymph node, spleen; `registry_extra_tissues.py`: pancreas; `registry_extra_blood.py`: blood cells; `registry_extra_heart.py`: heart; `registry_extra_eyeball.py`: eyeball; `registry_extra_ear.py`: ear; `registry_extra_kidney_gross.py`: kidney section; `registry_extra_hepatobiliary.py`: liver, bile ducts and pancreas; `registry_extra_lower_gi.py`: ileocaecal region and rectum, tooth; `registry_extra_female.py`: female reproductive system; `registry_extra_male.py`: male reproductive system) |
| `skin.py` | Thin, thick, scalp and axillary skin (`build_skin`) |
| `gut.py` | Duodenum, jejunum, ileum and colon (`build_gut`) |
| `walls.py` | Stomach, oesophagus and trachea |
| `vessels.py` | Muscular artery, elastic artery and vein |
| `bundles.py` | Skeletal muscle and peripheral nerve |
| `bone.py` | Compact bone |
| `liver.py` | Liver lobule |
| `lung.py` | Lung acinus |
| `glands.py` | Thyroid follicles (with parathyroid) and tongue papillae |
| `organs2.py` | Urinary bladder, cornea and retina |
| `lymphoid.py` | Lymph node and spleen |
| `tissues.py` | The shared helpers and descriptions the pancreas uses |
| `pancreas.py` | Pancreas: non-overlapping acini, duct tree, islets, and its secretion animation |
| `anim.py` | Animation for micro models: morph targets, particle flow and travelling glow, evaluated in the vertex shader; see its docstring |
| `heart_motion.py` | The heart's cardiac cycle, attached at the end of `build_heart` |
| `blood.py` | Blood cells (formed elements) |
| `heart.py` | Heart: chambers, valves, vessels and conduction system |
| `eyeball.py` | Eyeball and accessory structures |
| `ear.py` | External, middle and inner ear, with the magnified insets |
| `kidney_gross.py` | Kidney in coronal section |
| `hepatobiliary.py` | Liver, gallbladder, bile ducts and pancreas |
| `lower_gi.py` | Ileocaecal region, rectum and anal canal |
| `tooth.py` | Tooth structure |
| `female.py` | Female reproductive system, breast and the magnified ovary, tube, endometrium and early-development insets |
| `male.py` | Male reproductive system, with the seminiferous tubule and spermatozoon insets |
| `cellkit.py` | Helpers shared by the liver lobule and lung acinus |
| `base.py`, `cache.py`, `cells.py`, `geometry.py`, `kit.py`, `organic.py`, `sdf.py` | The shared toolkit: parts and models, the disk cache, cell mosaics, mesh primitives, signed-distance modelling and the warps and reliefs. Editing any of these invalidates every model's cache |

Built models are cached in `data/micro_cache/<id>.npz`. `tools/build_micro.py` builds them all in parallel (or the ids you name) and `tools/render_micro.py <id>` renders one offscreen.

## Skin

### Thin (hairy) skin
- **Epidermis:** Stratum corneum; Stratum granulosum; Stratum spinosum; Stratum basale; Melanocytes
- **Dermis:** Papillary dermis; Reticular dermis
- **Hypodermis:** Hypodermis septa; Adipocytes (fat lobules)
- **Hair follicle:** Hair shaft; Inner root sheath; Outer root sheath; Hair bulb (matrix); Dermal papilla of hair
- **Glands:** Sebaceous gland; Arrector pili muscle; Eccrine sweat gland (secretory coil); Eccrine sweat duct
- **Vessels & nerves:** Arterioles; Venules; Subpapillary plexus; Papillary capillary loops; Cutaneous nerve & branches; Free nerve endings; Hair follicle nerve endings
- **Sensory receptors:** Meissner corpuscles; Pacinian corpuscles (lamellae); Pacinian axon terminal
- Surface has a rhomboid network of furrows, with the hairs emerging where furrows cross.

### Thick (glabrous) skin
- **Epidermis:** Stratum corneum; Stratum lucidum; Stratum granulosum; Stratum spinosum; Stratum basale; Melanocytes
- **Dermis:** Papillary dermis; Reticular dermis
- **Hypodermis:** Hypodermis septa; Adipocytes (fat lobules)
- **Glands:** Eccrine sweat gland (secretory coil); Eccrine sweat duct
- **Vessels & nerves:** Arterioles; Venules; Subpapillary plexus; Papillary capillary loops; Cutaneous nerve & branches; Free nerve endings
- **Sensory receptors:** Meissner corpuscles; Pacinian corpuscles (lamellae); Pacinian axon terminal
- Surface has fingerprint (friction) ridges with sweat pores along their crests; a deep rete ridge carrying the sweat duct under every ridge; no hair.

### Scalp skin
- Same structures as thin skin, minus the Meissner corpuscles, plus a **Galea aponeurotica** group (Galea aponeurotica) under the fat.
- Many deep terminal follicles in follicular units whose bulbs sit in the fat, with larger sebaceous glands.

### Axillary skin (apocrine glands)
- Same as thin skin.
- **Glands** also include: Apocrine sweat gland; Apocrine duct (opening into the hair follicle).

## Digestive tract

### Small intestine wall (jejunum)
- **Serosa & muscularis externa:** Serosa; Outer longitudinal muscle; Inner circular muscle
- **Submucosa:** Submucosa (raised into a plica circularis)
- **Mucosa:** Muscularis mucosae; Lamina propria; Intestinal crypts (of Lieberkühn); Paneth cells; Crypt base stem cells (Lgr5+)
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus; Submucosal arterioles; Submucosal venules; Mucosal branches
- **Villi:** Brush border (microvilli); Villus epithelium (enterocytes); Villus lamina propria core; Central lacteals; Villus capillary network; Villus smooth muscle; Goblet cells

### Duodenum wall
- As jejunum (broad leaf-shaped villi, no plica fold), plus under **Submucosa:** Brunner glands; Brunner gland ducts

### Ileum wall with Peyer patches
- As jejunum (shorter villi, more goblet cells, no plica fold), plus **Lymphoid tissue:** Peyer patch follicles; Germinal centres; Subepithelial dome; Follicle-associated epithelium; M cells

### Colon wall
- **Serosa & muscularis externa:** Serosa; Taenia coli & longitudinal muscle; Inner circular muscle; Appendix epiploica (fat tag)
- **Submucosa:** Submucosa
- **Mucosa:** Muscularis mucosae; Lamina propria; Colonic crypts (of Lieberkühn); Crypt base stem cells (Lgr5+); Surface epithelium (colonocytes); Goblet cells
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus; Submucosal arterioles; Submucosal venules; Mucosal branches
- **Lymphoid tissue:** Solitary lymphoid follicle; Germinal centres

### Stomach wall (fundus/body)
- **Muscularis externa:** Serosa; Outer longitudinal muscle; Middle circular muscle; Inner oblique muscle; Intermuscular connective tissue
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus; Submucosal arteries; Submucosal veins; Lymphatic vessels
- **Submucosa:** Submucosa (rugal core)
- **Mucosa:** Muscularis mucosae; Surface mucous cells & gastric pits; Lamina propria
- **Gastric glands:** Isthmus & neck (mucous neck cells); Parietal (oxyntic) cells; Chief (zymogen) cells – gland base; Enteroendocrine (ECL) cells

### Oesophagus wall
- **Wall layers:** Adventitia; Oesophageal (vagal) plexus; Adventitial arteries; Adventitial veins
- **Muscularis externa:** Outer longitudinal muscle – skeletal (upper third); Outer longitudinal muscle – smooth (lower third); Inner circular muscle – skeletal (upper third); Inner circular muscle – smooth (lower third); Intermuscular connective tissue
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus
- **Submucosa:** Submucosa; Oesophageal glands proper; Gland ducts; Submucosal venous plexus; Submucosal arteries; Lymphatic vessels
- **Mucosa:** Muscularis mucosae; Lamina propria & papillae; Papillary capillary loops
- **Stratified squamous epithelium:** Basal cell layer; Intermediate (prickle) layers; Superficial squamous layer

### Tongue papillae and taste buds
- **Mucosa:** Stratified squamous epithelium; Lamina propria
- **Papillae:** Fungiform papillae; Circumvallate papilla; Foliate papillae; Filiform papillae; Keratinised tips (filiform)
- **Glands:** Von Ebner glands; Von Ebner ducts
- **Taste buds:** Taste buds; Gustatory receptor cells; Taste pores & microvilli
- **Intrinsic muscle:** Perimysium & interstitial fat; Superior longitudinal muscle; Transverse muscle; Vertical muscle; Inferior longitudinal muscle
- **Nerves & vessels:** Glossopharyngeal nerve (IX) branch; Lingual nerve (chorda tympani) branch; Hypoglossal nerve (XII) branch; Lingual artery branch; Deep lingual vein

### Liver lobule
- **Hepatic plates:** Hepatocytes – zone 3 (centrilobular); Hepatocytes – zone 2 (midzonal); Hepatocytes – zone 1 (periportal); Hepatocytes – neighbouring lobules; Limiting plate
- **Portal triads:** Inlet venules; Portal tract connective tissue; Portal venules; Hepatic arterioles; Bile ductules; Lymphatic vessels
- **Central vein:** Central vein
- **Sinusoids:** Sinusoidal endothelial cells; Kupffer cells; Stellate (Ito) cells
- **Bile flow:** Bile canaliculi; Canals of Hering
- **Liver acinus (Rappaport):** Liver acinus – zone 1; Liver acinus – zone 2; Liver acinus – zone 3

### Pancreas (acini & islets)
- **Lobules:** Intralobular connective tissue
- **Septa & ducts:** Interlobular septa; Interlobular ducts; Interlobular artery; Interlobular vein; Intralobular ducts; Intercalated ducts
- **Acini:** Acinar cells – basal (basophilic) cytoplasm; Acinar cells – apical zymogen granules; Acinar cell nuclei; Centroacinar cells
- **Islets of Langerhans:** Beta cells (core); Alpha cells (mantle); Delta cells; Islet capillaries (fenestrated)

### Tooth structure
- **Tooth – Molar in section:** Enamel; Dentin; Pulp chamber (coronal pulp); Root canals (radicular pulp); Cementum; Apical foramen
- **Tooth – Periodontium & jaw:** Periodontal ligament; Alveolar bone proper (lamina dura); Cortical bone of mandible; Cancellous (spongy) bone; Bone marrow; Mandibular canal; Gingiva; Alveolar mucosa
- **Tooth – Nerves & vessels:** Inferior alveolar nerve & dental nerves; Inferior alveolar artery & dental arteries; Inferior alveolar vein & dental veins
- **Tooth – Adult tooth types:** Incisor – crown; Incisor – root; Canine – crown; Canine – root; Premolar – crown; Premolar – root; Molar – crown; Molar – neck; Molar – roots
- A lower first molar cut mesiodistally in its socket, with the four adult tooth types beside it.

### Liver, gallbladder, bile ducts & pancreas
- **Liver:** Right lobe of liver; Left lobe of liver; Quadrate lobe; Caudate lobe; Porta hepatis; Bare area of liver
- **Liver ligaments:** Coronary ligament; Right triangular ligament; Falciform ligament; Left triangular ligament; Round ligament of liver (ligamentum teres); Ligamentum venosum
- **Gallbladder & bile ducts:** Fundus of gallbladder; Body of gallbladder; Neck of gallbladder; Cystic duct; Right hepatic duct; Left hepatic duct; Common hepatic duct; Common bile duct; Hepatopancreatic ampulla (of Vater); Sphincter of Oddi (hepatopancreatic sphincter)
- **Pancreas:** Head of pancreas; Uncinate process of pancreas; Neck of pancreas; Body of pancreas; Tail of pancreas; Main pancreatic duct; Accessory pancreatic duct
- **Duodenum:** Duodenum: superior part (D1); Duodenum: descending part (D2); Duodenum: horizontal part (D3); Duodenum: ascending part (D4); Duodenal mucosa (circular folds); Major duodenal papilla; Minor duodenal papilla
- **Stomach & jejunum (cut ends):** Pylorus (cut end of stomach); Jejunum (cut)
- **Veins:** Hepatic veins; Hepatic portal vein; Splenic vein; Superior mesenteric vein; Inferior mesenteric vein; Inferior vena cava
- **Arteries:** Abdominal aorta; Coeliac trunk; Common hepatic artery; Hepatic artery proper; Right hepatic artery; Left hepatic artery; Cystic artery; Gastroduodenal artery; Splenic artery; Left gastric artery (cut); Superior mesenteric artery
- The liver, gallbladder, extrahepatic bile ducts, pancreas and duodenum in place, seen from the front, with the duodenum opened to show the papillae.

### Ileocecal region, rectum & anal canal
- **Ileocaecal region – Caecum & colon:** Caecum; Ascending colon (haustra); Mucosa & semilunar folds (plicae semilunares); Taenia libera (free taenia); Taenia mesocolica; Taenia omentalis; Omental (epiploic) appendices
- **Ileocaecal region – Ileocaecal junction:** Terminal ileum; Ileal mucosa; Ileocaecal valve – upper (ileocolic) lip; Ileocaecal valve – lower (ileocaecal) lip; Frenula of the ileocaecal valve
- **Ileocaecal region – Vermiform appendix:** Vermiform appendix; Appendiceal mucosa; Lymphoid follicles of the appendix; Appendiceal orifice; Mesoappendix; Appendicular artery
- **Rectum & anal canal – Rectal wall:** Rectal mucosa (upper rectum); Rectal ampulla; Superior transverse rectal fold; Middle transverse rectal fold (Kohlrausch); Inferior transverse rectal fold; Submucosa
- **Rectum & anal canal – Anal canal lining:** Anorectal junction; Anal columns (of Morgagni); Anal sinuses; Anal valves; Pectinate (dentate) line; Anal pecten (anoderm); Anus & perianal skin
- **Rectum & anal canal – Vessels, nerves & nodes:** Internal rectal venous plexus (anal cushions); External rectal venous plexus; Superior rectal artery; Superior rectal vein; Mesorectal lymph nodes
- **Rectum & anal canal – Muscle coats:** Circular muscle of rectum; Longitudinal muscle of rectum; Internal anal sphincter; Conjoint longitudinal muscle
- **Rectum & anal canal – Pelvic floor & sphincters:** External anal sphincter – deep part; External anal sphincter – superficial part; External anal sphincter – subcutaneous part; Puborectalis; Levator ani
- **Rectum & anal canal – Fat & fossae:** Mesorectum; Ischioanal fossa fat
- Two opened specimens: the caecum through a window in its front wall, with the appendix laid open, and the posterior half of a coronal section of the rectum and anal canal.

## Respiratory

### Trachea wall
- **Wall layers:** Adventitia
- **Cartilage:** Anular ligaments & fibroelastic membrane; Perichondrium; Hyaline cartilage ring (C-shaped); Trachealis muscle; Territorial matrix (isogenous groups); Lacunae; Chondrocytes
- **Mucosa & submucosa:** Lamina propria; Submucosa; Arterioles; Venules; Elastic fibres (elastic membrane)
- **Epithelium:** Basement membrane; Pseudostratified ciliated epithelium; Goblet cells; Cilia; Ciliated cell nuclei; Basal (stem) cells
- **Glands:** Mucous gland tubules; Serous demilunes & acini; Gland ducts

### Lung acinus & alveoli
- **Airways:** Respiratory bronchioles; Alveolar duct smooth muscle (knobs); Terminal bronchiole; Bronchiolar smooth muscle; Club (Clara) cells
- **Vessels:** Pulmonary arteriole (deoxygenated); Pulmonary venule (oxygenated); Alveolar capillaries
- **Alveoli:** Type II pneumocytes; Alveolar macrophages; Pores of Kohn; Interalveolar septa – respiratory bronchioles; Interalveolar septa – alveolar ducts; Interalveolar septa – alveolar sacs

## Cardiovascular

### Muscular artery wall
- **Tunica intima:** Endothelium; Subendothelial layer; Internal elastic lamina
- **Tunica media:** Tunica media (smooth muscle); External elastic lamina
- **Tunica adventitia:** Tunica adventitia; Adventitial collagen bundles; Vasa vasorum; Vasa vasorum venules; Nervi vasorum; Perivascular fat
- **Blood:** Red blood cells; Rolling leukocyte

### Elastic artery (aorta) wall
- **Tunica intima:** Endothelium; Subendothelial layer; Internal elastic lamina
- **Tunica media:** Tunica media (smooth muscle); Elastic lamellae; External elastic lamina
- **Tunica adventitia:** Tunica adventitia; Adventitial collagen bundles; Vasa vasorum; Vasa vasorum venules; Nervi vasorum; Perivascular fat
- **Blood:** Red blood cells; Rolling leukocyte

### Vein wall with valve
- **Tunica intima:** Endothelium; Subendothelial layer; Venous valve cusps
- **Tunica media:** Tunica media (smooth muscle)
- **Tunica adventitia:** Tunica adventitia; Longitudinal smooth muscle bundles; Adventitial collagen bundles; Vasa vasorum; Nervi vasorum; Perivascular fat
- **Blood:** Red blood cells; Rolling leukocyte

### Heart: chambers, valves & conduction
- **Ventricles:** Membranous part of interventricular septum; Left ventricle (myocardium); Interventricular septum; Right ventricle (myocardium); Apex of heart
- **Atria:** Fossa ovalis; Interatrial septum; Right auricle; Left auricle; Right atrium (myocardium); Left atrium (myocardium); Base of heart (posterior left atrium)
- **Heart wall:** Epicardium (visceral pericardium); Endocardium; Epicardial fat
- **Chamber interior:** Papillary muscles (left ventricle); Papillary muscles (right ventricle); Moderator band (septomarginal trabecula); Trabeculae carneae; Crista terminalis; Pectinate muscles; Opening of coronary sinus
- **Valves:** Tricuspid valve; Mitral (bicuspid) valve; Chordae tendineae; Aortic valve; Pulmonary valve; Fibrous skeleton (valve annuli)
- **Great vessels:** Ascending aorta; Arch of aorta; Thoracic (descending) aorta; Brachiocephalic trunk; Left common carotid artery; Left subclavian artery; Pulmonary trunk; Right pulmonary artery; Left pulmonary artery; Superior vena cava; Inferior vena cava; Right superior pulmonary vein; Right inferior pulmonary vein; Left superior pulmonary vein; Left inferior pulmonary vein; Ligamentum arteriosum
- **Coronary arteries:** Left coronary artery (left main); Anterior interventricular artery (LAD); Circumflex artery; Left marginal artery; Right coronary artery; Right marginal artery; Posterior interventricular artery
- **Cardiac veins:** Great cardiac vein; Coronary sinus; Middle cardiac vein; Small cardiac vein; Posterior vein of left ventricle
- **Conduction system:** Sinoatrial (SA) node; Atrioventricular (AV) node; Internodal pathways & Bachmann's bundle; Atrioventricular bundle (bundle of His); Right bundle branch; Left bundle branch; Purkinje fibres
- **Pericardium:** Fibrous pericardium; Parietal layer of serous pericardium; Pericardial cavity
- The whole adult heart opened along the four-chamber plane, with the pericardium cut open around it; about 12 cm from base to apex.

### Blood: formed elements
- **Red cells & platelets:** Erythrocytes; Rouleau; Erythrocyte cross-section; Platelets
- **Granulocytes:** Neutrophil; Band neutrophil; Neutrophil nucleus; Neutrophil granules; Eosinophil; Eosinophil nucleus; Eosinophil granules; Basophil; Basophil nucleus; Basophil granules
- **Agranulocytes:** Small lymphocyte; Large lymphocyte; Lymphocyte nucleus; Monocyte; Monocyte nucleus
- **Clot:** Fibrin; Activated platelets
- **Plasma:** Plasma
- A film of plasma a few cells deep, like the feathered edge of a smear, coloured as with Wright's stain and drawn to scale; one of each white cell is lined up along the front edge in order of abundance and cut open at its equator.

## Lymphoid

### Lymph node
- **Capsule & trabeculae:** Capsule; Trabeculae
- **Hilum & vessels:** Hilum connective tissue; Artery (hilar and medullary branches); Vein (hilar and medullary tributaries)
- **Sinuses:** Subcapsular sinus; Trabecular sinuses; Medullary sinuses; Reticular fibre meshwork; Sinus macrophages
- **Cortex:** Outer cortex (B-cell zone); Primary follicles; Mantle zone (secondary follicles); Germinal centre - light zone; Germinal centre - dark zone
- **Paracortex:** Paracortex (T-cell zone); High endothelial venules
- **Medulla:** Medullary cords
- **Lymphatics:** Afferent lymphatic vessels; Efferent lymphatic vessel; Lymphatic valves
- The whole node, a bean about 1 cm long with its hilum underneath, cut through the hilum.

### Spleen: white and red pulp
- **Capsule & trabeculae:** Mesothelium (visceral peritoneum); Capsule; Trabeculae
- **White pulp:** Periarteriolar lymphoid sheath (PALS); Splenic follicles & mantle zone; Germinal centres
- **Marginal zone:** Marginal sinus; Marginal zone
- **Red pulp:** Venous sinusoids (stave cells); Ring fibres; Splenic cords (of Billroth)
- **Vessels:** Trabecular artery; Trabecular vein; Central artery & follicular branches; Penicillar arterioles; Sheathed capillaries (Schweigger-Seidel sheaths); Pulp vein

## Musculoskeletal and nervous

### Compact bone & osteons
- **Osteons:** Central (Haversian) canals; Haversian arterioles & capillaries; Haversian venules; Haversian nerve fibres; Concentric lamellae (set A); Concentric lamellae (set B); Cement lines; Lamellar collagen fibres (telescoped osteon); Osteocytes in lacunae; Canaliculi
- **Canals:** Perforating (Volkmann) canals; Volkmann canal vessels
- **Lamellar systems:** Interstitial lamellae; Outer circumferential lamellae; Inner circumferential lamellae
- **Periosteum:** Periosteum – cambium (osteogenic) layer; Periosteum – fibrous layer; Sharpey fibres; Periosteal artery; Periosteal vein; Periosteal nerve
- **Endosteum & marrow:** Endosteum; Osteoblasts; Bone-lining cells; Osteoclasts (Howship lacunae); Trabeculae (spongy bone); Red marrow; Marrow adipocytes; Nutrient artery branch; Marrow sinusoid & central vein

### Skeletal muscle organisation
- **Connective tissue:** Epimysium; Epimysial collagen bundles; Perimysium; Endomysium
- **Muscle fibres:** Muscle fibres; Myonuclei; Satellite cells; Myofibrils
- **Nerves & vessels:** Endomysial capillaries; Perimysial arterioles; Perimysial venules; Motor nerve branch; Neuromuscular junction; Motor end plate
- **Sarcomere:** A band; I band; H zone; M line; Z disc; T tubules; Sarcoplasmic reticulum
- **Muscle spindle:** Muscle spindle capsule; Intrafusal fibres; Nuclear bag & chain nuclei; Annulospiral (Ia) sensory ending

### Peripheral nerve
- **Connective tissue:** Epineurium; Epineurial collagen bundles; Perineurium; Endoneurium; Epineurial fat
- **Nerve fibres:** Myelin sheaths (internodes); Axons; Nodes of Ranvier; Schwann cell nuclei; Remak Schwann cells; Unmyelinated axons (C fibres)
- **Vessels:** Endoneurial capillaries; Vasa nervorum (arterioles); Vasa nervorum (venules)

## Urinary

### Urinary bladder wall (urothelium)
- **Urothelium:** Basal cells; Intermediate cells; Umbrella cells; Uroplakin plaques (apical membrane); Umbrella cell nuclei (often binucleate); Fusiform vesicles
- **Lamina propria:** Lamina propria; Suburothelial capillary plexus; Muscularis mucosae (discontinuous); Lamina propria arterioles; Lamina propria venules
- **Detrusor muscle:** Inner longitudinal detrusor; Middle circular detrusor; Outer longitudinal detrusor; Interlacing (oblique) bundles; Interfascicular connective tissue
- **Adventitia & serosa:** Serosa (dome only); Adventitia; Perivesical fat
- **Vessels & nerves:** Vesical arteries; Vesical veins; Autonomic nerves & intramural ganglia

### Kidney: coronal section
- **Coverings:** Renal fascia; Perirenal fat (adipose capsule); Fibrous capsule
- **Renal cortex:** Renal cortex; Renal columns; Medullary rays
- **Renal medulla:** Renal pyramids; Renal papillae; Medullary striations
- **Collecting system:** Minor calyces; Major calyces; Renal pelvis; Ureter (proximal)
- **Renal sinus & hilum:** Renal sinus fat; Hilum of kidney
- **Arteries:** Renal artery; Segmental arteries; Interlobar arteries; Arcuate arteries; Cortical radiate (interlobular) arteries
- **Veins:** Renal vein; Segmental (sinus) veins; Interlobar veins; Arcuate veins; Cortical radiate (interlobular) veins
- **Nephron wedge:** Nephron tubule; Collecting duct; Renal corpuscle; Nephron position (lobule wedge)
- **Suprarenal gland:** Suprarenal gland – cortex; Suprarenal gland – medulla
- A right kidney bisected in the frontal plane, as in the dissection room, with its coverings and the suprarenal gland; a window in one lobe shows where a nephron and its collecting duct lie.

## Eye, ear and endocrine

### Eye: eyeball and accessory structures
- **Fibrous tunic:** Sclera; Cornea; Limbus (corneoscleral junction); Trabecular meshwork; Scleral venous sinus (canal of Schlemm)
- **Vascular tunic (uvea):** Choroid; Ciliary body (ciliary ring); Ciliary muscle; Ciliary processes; Iris; Sphincter pupillae; Dilator pupillae; Iris pigment epithelium; Pupil
- **Nervous tunic (retina):** Pigmented layer of retina; Neural layer of retina; Ora serrata; Macula lutea; Fovea centralis; Optic disc (blind spot)
- **Lens & zonule:** Lens; Lens capsule; Zonular fibres (suspensory ligament)
- **Anterior segment (aqueous humor):** Anterior chamber (aqueous humor); Posterior chamber (aqueous humor)
- **Posterior segment (vitreous chamber):** Vitreous humor (vitreous body)
- **Optic nerve & vessels:** Optic nerve (CN II); Dural sheath of optic nerve; Central retinal artery; Central retinal vein
- **Extrinsic eye muscles:** Superior rectus; Inferior rectus; Medial rectus; Lateral rectus; Superior oblique; Trochlea; Inferior oblique; Common tendinous ring; Levator palpebrae superioris
- **Eyelids:** Upper eyelid; Lower eyelid; Superior tarsal plate; Inferior tarsal plate; Tarsal (meibomian) glands; Orbicularis oculi (palpebral part); Superior tarsal muscle; Eyelashes; Medial canthus (medial palpebral commissure); Lateral canthus (lateral palpebral commissure)
- **Conjunctiva:** Palpebral conjunctiva; Superior conjunctival fornix; Inferior conjunctival fornix; Bulbar conjunctiva; Lacrimal caruncle; Plica semilunaris
- **Lacrimal apparatus:** Lacrimal gland; Excretory ducts of lacrimal gland; Lacrimal puncta; Lacrimal canaliculi; Lacrimal sac; Nasolacrimal duct
- A right eye cut parasagittally through the pupil and optic nerve, seen from the nasal side, with the orbit's muscles, eyelids, conjunctiva and lacrimal apparatus around it.

### Cornea
- **Epithelium:** Basal columnar cells; Wing cells; Superficial squamous cells; Tear film
- **Limbus:** Limbal epithelial stem cells; Limbal epithelium (extra layers); Conjunctival goblet cells; Limbal stroma & palisades of Vogt; Limbal vascular arcades; Sclera
- **Anterior cornea:** Bowman layer
- **Stroma:** Stromal lamellae; Keratocytes
- **Posterior cornea:** Pre-Descemet (Dua) layer; Descemet membrane; Endothelium
- **Drainage angle:** Schwalbe line; Schlemm canal; Collector channels & aqueous veins; Trabecular meshwork
- **Nerves:** Stromal nerves; Subbasal plexus & free nerve endings

### Retina
- **Choroid & sclera:** Sclera; Choroid stroma; Choroidal veins (Haller layer); Choroidal arteries (Sattler layer); Choroidal melanocytes; Choriocapillaris; Bruch membrane
- **Outer retina:** Retinal pigment epithelium; Rod outer segments; Rod inner segments; Cones; Outer limiting membrane
- **Neural retina layers:** Outer nuclear layer; Outer plexiform layer; Inner nuclear layer; Inner plexiform layer; Ganglion cell layer; Nerve fibre layer
- **Retinal neurons & glia:** Horizontal cells; Bipolar cells; Amacrine cells; Müller glia
- **Retinal vessels:** Retinal arteriole; Retinal venule; Superficial capillary plexus; Deep capillary plexus
- **Inner limiting membrane & vitreous:** Inner limiting membrane; Vitreous body

### Ear: external, middle and inner ear
- **External ear:** Auricular cartilage (elastic); Tragus; Antitragus; Lobule of auricle; Helix; Cranial surface of auricle; Concha of auricle; Antihelix; Scapha & triangular fossa; External acoustic meatus – cartilaginous part; External acoustic meatus – bony part; Meatal cartilage; Ceruminous & sebaceous glands; Cerumen (earwax)
- **Middle ear:** Tympanic membrane – pars tensa; Tympanic membrane – pars flaccida; Tympanic cavity (mucosal lining); Round window (secondary tympanic membrane); Pharyngotympanic (auditory) tube; Tubal cartilage; Mastoid antrum & air cells
- **Auditory ossicles:** Malleus; Incus; Stapes; Base (footplate) of stapes; Incudomallear joint; Incudostapedial joint
- **Ossicular ligaments & muscles:** Superior ligament of malleus; Lateral ligament of malleus; Posterior ligament of incus; Anterior ligament of malleus; Oval window & annular ligament; Tensor tympani; Tensor tympani tendon; Stapedius; Stapedius tendon
- **Inner ear – bony labyrinth:** Bony labyrinth (perilymph); Helicotrema; Scala vestibuli (perilymph); Scala tympani (perilymph); Osseous spiral lamina; Modiolus
- **Inner ear – membranous labyrinth:** Cochlear duct (scala media, endolymph); Basilar membrane; Vestibular (Reissner) membrane; Spiral organ (of Corti); Tectorial membrane; Semicircular ducts; Membranous ampullae; Utricle; Saccule; Endolymphatic duct & sac; Cristae ampullares; Cupulae; Maculae (utricle & saccule); Otolithic membranes & otoliths
- **Nerves:** Vestibular nerve (superior & inferior divisions); Vestibular (Scarpa) ganglion; Cochlear nerve; Vestibulocochlear nerve (VIII); Spiral ganglion; Facial nerve (VII); Geniculate ganglion; Chorda tympani
- **Temporal bone:** Petrous part (otic capsule); Mastoid process; Squamous & tympanic parts
- **Surrounding tissues:** Skin of the side of the head; Subcutaneous tissue
- **Inset: cochlear duct (magnified):** Bony wall of cochlea (magnified); Osseous spiral lamina (magnified); Spiral ligament (magnified); Stria vascularis; Spiral limbus; Scala vestibuli (magnified); Scala tympani (magnified); Cochlear duct endolymph (magnified); Vestibular membrane (magnified); Basilar membrane (magnified); Tectorial membrane (magnified); Pillar cells & tunnel of Corti; Supporting cells (Deiters, Hensen, Claudius); Inner hair cells; Outer hair cells; Spiral ganglion neurons; Hair-cell stereocilia; Cochlear nerve fibres
- **Inset: crista ampullaris (magnified):** Ampulla wall (membranous); Crista ampullaris (connective tissue core); Cupula (magnified); Type I hair cells (crista); Type II hair cells (crista); Supporting cells (crista); Stereocilia & kinocilia (crista); Ampullary nerve fibres
- **Inset: macula (magnified):** Lamina propria of macula; Gelatinous layer; Otolithic membrane (magnified); Type I hair cells (macula); Type II hair cells (macula); Supporting cells (macula); Otoconia (otoliths); Stereocilia & kinocilia (macula); Macular nerve fibres
- A coronal section through the right temporal bone, seen from in front and drawn to scale, with the cochlea's basal turn opened; beside it, magnified insets of a cochlear turn, a crista ampullaris and a macula.

### Thyroid follicles
- **Thyroid follicles:** Follicular epithelium; Colloid; Resorption vacuoles; Parafollicular C cells
- **Vessels:** Perifollicular capillaries; Arteries (capsular & interlobular); Veins (capsular & interlobular)
- **Capsule & stroma:** Interfollicular connective tissue; Interlobular septa; Capsule
- **Parathyroid gland:** Parathyroid capsule; Parathyroid chief cells; Oxyphil cells; Parathyroid adipocytes; Parathyroid capillaries

## Reproductive

### Female reproductive system
- **Bony pelvis:** Sacrum; Coccyx; Fifth lumbar vertebra (L5); Lumbosacral intervertebral disc; Hip bone; Pubic symphysis
- **Uterus:** Fundus of uterus (myometrium); Body of uterus (myometrium); Isthmus of uterus (myometrium); Perimetrium; Endometrium - functional layer; Endometrium - basal layer; Uterine cavity
- **Cervix:** Cervix of uterus; Ectocervix & transformation zone; Endocervical mucosa (plicae palmatae); Cervical canal; Internal os; External os
- **Vagina:** Vagina; Vaginal rugae (mucosa); Fornix of vagina; Vaginal orifice (introitus); Vaginal canal (lumen); Hymen (remnant)
- **Neighbouring organs:** Urinary bladder; Urine in bladder; Urethra; Ureter; Rectum; Anal canal & anus
- **Pelvic floor:** Levator ani; Coccygeus
- **Uterine tubes:** Uterine (intramural) part of uterine tube; Isthmus of uterine tube; Ampulla of uterine tube; Infundibulum of uterine tube; Fimbriae; Abdominal ostium of uterine tube
- **Ovaries:** Ovary
- **Ligaments:** Broad ligament - mesosalpinx; Broad ligament - mesometrium; Broad ligament - mesovarium; Ovarian ligament; Suspensory ligament of ovary; Round ligament of uterus; Uterosacral ligament; Cardinal ligament (transverse cervical)
- **Vessels:** Internal iliac artery; Uterine artery; Ovarian artery; Ovarian vein
- **Peritoneum:** Vesicouterine pouch; Rectouterine pouch (of Douglas)
- **External genitalia (vulva):** Labia majora; Mons pubis; Labia minora; Vestibule; Pudendal cleft; Glans of clitoris; Prepuce of clitoris; Perineal body (clinical perineum); Body of clitoris (with crura); External urethral orifice; Greater vestibular (Bartholin) glands
- **Magnified: ovary (sectioned):** Germinal (surface) epithelium; Tunica albuginea of ovary; Ovarian cortex; Ovarian medulla; Theca externa; Theca interna; Membrana granulosa (granulosa cells); Antrum (follicular fluid); Cumulus oophorus; Corpus luteum; Corpus luteum - central clot; Corpus albicans; Atretic follicle; Secondary follicles; Theca of secondary follicles; Primordial follicles; Primary follicles; Oocytes; Zona pellucida; Corona radiata; Mesovarium (cut edge); Ovarian blood vessels - arteries; Ovarian blood vessels - veins
- **Mammary gland (breast):** Skin of breast; Areola; Areolar glands (of Montgomery); Nipple; Adipose tissue of breast; Lobes of mammary gland; Axillary tail (of Spence); Lobules (alveolar glands); Lactiferous ducts; Lactiferous sinuses; Suspensory ligaments (of Cooper); Pectoral fascia; Pectoralis major; Ribs; Intercostal muscles; Axillary lymph nodes
- **Magnified: uterine tube wall (ampulla):** Serosa of uterine tube; Muscular layer of uterine tube; Mucosa of uterine tube (lamina propria folds); Tubal epithelium (ciliated & peg cells); Blood vessels of tube wall
- **Magnified: endometrium & implantation:** Myometrium (inner layer); Stratum basalis (basal layer); Stratum functionalis (functional layer); Uterine surface epithelium; Uterine glands; Spiral arteries; Straight (basal) arteries; Trophoblast of implanted blastocyst; Chorionic cavity (extraembryonic coelom); Amniotic sac (amnion); Amniotic cavity; Embryonic disc - ectoderm (epiblast); Embryonic disc - endoderm (hypoblast); Yolk sac; Connecting stalk
- **Magnified: fertilization to blastocyst:** Ovulated secondary oocyte; Corona radiata cells (ovulated oocyte); Sperm cells; Zona pellucida (early embryo); Zygote; Egg pronucleus; Sperm pronucleus; 2-cell stage; 4-cell stage; 8-cell stage; Morula; Blastocyst - trophoblast; Blastocyst - inner cell mass; Blastocele (blastocyst cavity)
- A median section of the female pelvis at life size, with a breast in sagittal section and magnified insets of an ovary, the ampulla of the tube, secretory endometrium with an implanted conceptus, and a row from fertilisation to blastocyst.

### Male reproductive system
- **Pelvis (context):** Pubic bone & ischiopubic ramus; Pubic symphysis (interpubic disc); Rectum & anal canal; Peritoneum (rectovesical pouch); Rectus abdominis
- **Bladder & urethra:** Urinary bladder (detrusor wall); Bladder mucosa & trigone; Ureter (entering the bladder); Internal urethral sphincter (bladder neck); External urethral sphincter; Prostatic urethra; Membranous (intermediate) urethra; Spongy (penile) urethra; External urethral orifice
- **Prostate & seminal glands:** Prostate - peripheral zone; Prostate - central zone; Prostate - transition zone; Anterior fibromuscular stroma; Prostatic capsule; Seminal colliculus (verumontanum); Ejaculatory duct; Bulbourethral (Cowper) gland; Seminal vesicle (seminal gland); Ampulla of ductus deferens
- **Penis:** Corpus cavernosum (erectile tissue); Tunica albuginea of corpora cavernosa; Deep artery of penis; Corpus spongiosum; Glans penis; Deep dorsal vein of penis; Dorsal artery of penis; Dorsal nerve of penis; Deep (Buck) fascia of penis; Superficial dorsal vein of penis; Skin & superficial (dartos) fascia of penis; Prepuce (foreskin); Frenulum of prepuce; Suspensory ligament of penis
- **Root of penis & perineum:** Bulb of penis; Crus of penis; Ischiocavernosus; Bulbospongiosus; Perineal body; Perineal membrane
- **Testis & epididymis:** Tunica albuginea of testis; Septa of testis; Lobules of testis (interstitial tissue); Seminiferous tubules; Mediastinum testis; Rete testis & tubuli recti; Head of epididymis; Body of epididymis; Tail of epididymis; Efferent ductules
- **Scrotum & coverings:** Tunica vaginalis (parietal layer); Internal spermatic fascia; Cremaster muscle & fascia; External spermatic fascia; Scrotal skin; Dartos muscle & fascia
- **Spermatic cord & inguinal canal:** Ductus deferens (vas deferens); Testicular artery; Pampiniform plexus & testicular vein; Genital branch of genitofemoral nerve; External oblique aponeurosis; Superficial inguinal ring; Internal oblique & transversus abdominis; Transversalis fascia; Deep inguinal ring; Inguinal ligament; Inguinal canal; Inferior epigastric artery; Inferior epigastric veins
- **Seminiferous tubule (inset, ~x200):** Basement membrane & peritubular myoid cells; Sertoli (sustentacular) cells; Sertoli cell nuclei; Spermatogonia; Primary spermatocytes; Secondary spermatocytes; Spermatids; Spermatozoa (lumen); Germ cell nuclei; Leydig (interstitial) cells; Leydig cell nuclei; Interstitial capillaries
- **Spermatozoon (inset, ~x1300):** Sperm nucleus; Acrosome; Neck (centrioles) & post-acrosomal region; Axoneme (9+2 microtubules); End piece; Midpiece (mitochondrial sheath); Principal piece (fibrous sheath)
- A midsagittal section of the male pelvis, with the right scrotum opened through the testis by a second, parasagittal cut; insets of a seminiferous tubule (~x200) and a spermatozoon (~x1300).
