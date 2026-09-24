# Microanatomy models: structure list and modelling brief

Each model is a small block (or tube segment) of tissue; the lymph node is modelled whole. There are 29 of them. Every structure below is a separate, selectable object in the app. Structures are grouped exactly as the app's layer tree shows them, in the same order.

## Requirements for replacement models (Blender or any other tool)

- **One object per structure**, named exactly as listed below. Use one **collection per group**, named exactly as the group names.
- **Closed (watertight) meshes.** The app's cut-away draws solid cut faces, which only works on closed surfaces. Layers may touch or nest, but each object must be closed on its own.
- **Scale and orientation:**
  - Blocks are about 2 units wide (x), 1.2–1.4 deep (z) and about 1 tall, with the tissue surface or epithelium at the top (+Y up; Blender's Z-up is converted on export).
  - Tube models (arteries, vein, trachea, nerve, skeletal muscle) run along the x axis, about 2 units long.
- **Cut-away.** The default cut removes the quadrant x < 0, z > 0 (tubes: x < 0, y > 0). Place key structures (follicles, glands, villi, osteons) so they cross those planes and get sectioned lengthwise.
- **Budget:** about 1–1.5 million triangles per model, built in under three minutes. Materials are optional; colours are assigned per structure in the app.
- **Format:** glTF 2.0 (`.glb`), or the `.blend` file itself. The app currently generates these models from code, so an importer would need to be added before external files can be used.

## How the current models are built

Worth knowing if you are asking someone to match or beat them:

- Vessels are **swept around a curved centreline** whose calibre varies along its length, with a radius that is a free function of angle and position - nothing is a cylinder of revolution. Every coat is its own closed shell, and the tubes that run inside the wall (vasa vasorum, nervi vasorum, a vein's longitudinal muscle bundles) lie in **channels** that the layers part round, so a section shows each as a clean round profile.
- Nerve and skeletal muscle are **bundles of bundles opened like a telescope**: at one end the outer sheath stops and each level of the hierarchy - fascicles, single fibres, and in muscle one fibre fraying into banded myofibrils - is pulled out further than the one containing it, each ending in a flat transverse face.
- Compact bone is a **two-dimensional mosaic of osteons** of different ages, each eroding the ones it overlaps, resolved with polygon booleans and extruded along a wedge of the shaft, so every lamella is a real closed solid.
- Cardiac muscle and pancreas are built **cell by cell**: each cardiomyocyte, acinar cell and islet cell is its own closed mesh, and cells that cross a face of the block are clipped and capped so the sides read like the cut surface of a specimen.
- The lymph node's zones (capsule, subcapsular sinus, cortex, paracortex, medulla) are all **cut from one signed-distance field by depth below the capsule**, so they nest exactly and the cut-away sections them all at once, like a slide through the hilum.
- Every free surface carries **the relief of its own cells**: endothelium as cobblestones stretched along the flow, smooth muscle as spindles wrapped around the circumference, urothelium as domed umbrella cells.
- Smooth muscle layers in the gut and bladder are **interlacing bundles** with the plexuses running in the gaps between them; the epimysium carries a **felt of individual collagen bundles**.
- Block models end with one **shared warp** applied to all of their layers at once: a sag that makes surfaces billow and side walls bow, a tissue grain, and a cell-sized micro-relief. Because the warp is a function of position, nested layers stay in register however thin they are.
- Layers that would otherwise bury their contents (thyroid connective tissue, hypodermal septa, splenic cords, bone marrow) are built as the **complement** of what sits inside them, so follicles, fat lobules, sinusoids and trabeculae stay visible.

## Where the code lives

All of it is in `app/micro/`. A model is a `MicroModel` (id, name, summary, builder, the atlas structures it is offered for, linked histology, related models, clinical notes, scale note) registered in a registry file; its builder returns the list of parts.

| File | Contents |
|---|---|
| `registry.py` | The `MODELS` table and the four skin models; imports `registry_organs.py`, then every `registry_extra_*.py` |
| `registry_organs.py` | Registration of the gut, wall, vessel, lung, bone, muscle, nerve, kidney, liver, bladder, eye, thyroid and tongue models |
| `registry_extra_*.py` | Further models, one file per batch, each with a `register_all(register)` - found and loaded automatically, so a new model needs no edit to a shared file (`registry_extra_lymphoid.py`: lymph node, spleen; `registry_extra_tissues.py`: cardiac muscle, pancreas) |
| `skin.py` | Thin, thick, scalp and axillary skin (`build_skin`) |
| `gut.py` | Duodenum, jejunum, ileum and colon (`build_gut`) |
| `walls.py` | Stomach, oesophagus and trachea |
| `vessels.py` | Muscular artery, elastic artery and vein |
| `bundles.py` | Skeletal muscle and peripheral nerve |
| `bone.py` | Compact bone |
| `kidney.py` | Nephron |
| `liver.py` | Liver lobule |
| `lung.py` | Lung acinus |
| `glands.py` | Thyroid follicles (with parathyroid) and tongue papillae |
| `organs2.py` | Urinary bladder, cornea and retina |
| `lymphoid.py` | Lymph node and spleen |
| `tissues.py` | Cardiac muscle and pancreas |
| `cellkit.py` | Helpers shared by the liver lobule and lung acinus |
| `base.py`, `cache.py`, `cells.py`, `geometry.py`, `kit.py`, `organic.py`, `sdf.py` | The shared toolkit: parts and models, the disk cache, cell mosaics, mesh primitives, signed-distance modelling and the warps and reliefs. Editing any of these invalidates every model's cache |

Built models are cached in `data/micro_cache/<id>.npz`; a model is rebuilt when the toolkit or its own builder files change. `tools/build_micro.py` builds them all in parallel and `tools/render_micro.py <id>` renders one offscreen.

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

### Cardiac muscle (ventricular wall)
- **Myocardium:** Cardiomyocytes; Intercalated discs; Perinuclear clear zone; Cardiomyocyte nuclei; Endomysial capillaries; Endomysium & perimysium
- **Vessels & nerves:** Intramyocardial arteriole; Intramyocardial venule; Coronary artery – intima; Coronary artery – media; Coronary artery – adventitia; Cardiac vein; Autonomic nerve
- **Endocardium:** Purkinje fibres; Purkinje cell sarcoplasm (glycogen); Purkinje cell nuclei; Subendocardial layer; Subendothelial connective tissue; Endocardial endothelium
- **Epicardium:** Mesothelium (visceral pericardium); Subepicardial connective tissue; Epicardial adipocytes
- A transmural block with the fibre direction turning through the wall; at one end the fibres are teased apart at their intercalated discs.

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

### Nephron & renal corpuscle
- **Renal corpuscle:** Glomerular capillaries; Mesangial cells; Podocytes (visceral layer); Bowman capsule (parietal layer); Afferent arteriole; Efferent arteriole
- **Juxtaglomerular apparatus:** Juxtaglomerular (granular) cells; Macula densa; Extraglomerular mesangial (lacis) cells
- **Proximal tubule:** Proximal convoluted tubule; Proximal straight tubule
- **Loop of Henle:** Thin descending limb; Thin ascending limb; Thick ascending limb
- **Distal nephron:** Distal convoluted tubule; Connecting tubule
- **Collecting duct:** Cortical collecting duct; Medullary collecting duct
- **Vessels:** Arcuate artery; Arcuate vein; Cortical radiate artery; Cortical radiate vein; Peritubular capillaries; Descending vasa recta; Ascending vasa recta
- **Kidney zones:** Cortex; Outer medulla – outer stripe; Outer medulla – inner stripe; Inner medulla

### Urinary bladder wall (urothelium)
- **Urothelium:** Basal cells; Intermediate cells; Umbrella cells; Uroplakin plaques (apical membrane); Umbrella cell nuclei (often binucleate); Fusiform vesicles
- **Lamina propria:** Lamina propria; Suburothelial capillary plexus; Muscularis mucosae (discontinuous); Lamina propria arterioles; Lamina propria venules
- **Detrusor muscle:** Inner longitudinal detrusor; Middle circular detrusor; Outer longitudinal detrusor; Interlacing (oblique) bundles; Interfascicular connective tissue
- **Adventitia & serosa:** Serosa (dome only); Adventitia; Perivesical fat
- **Vessels & nerves:** Vesical arteries; Vesical veins; Autonomic nerves & intramural ganglia

## Eye and endocrine

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

### Thyroid follicles
- **Thyroid follicles:** Follicular epithelium; Colloid; Resorption vacuoles; Parafollicular C cells
- **Vessels:** Perifollicular capillaries; Arteries (capsular & interlobular); Veins (capsular & interlobular)
- **Capsule & stroma:** Interfollicular connective tissue; Interlobular septa; Capsule
- **Parathyroid gland:** Parathyroid capsule; Parathyroid chief cells; Oxyphil cells; Parathyroid adipocytes; Parathyroid capillaries
