# Microanatomy models: structure list and modelling brief

Each model is a small block (or tube segment) of tissue. Every structure below is a separate, selectable object in the app. Structures are grouped exactly as the app's layer tree shows them.

## Requirements for replacement models (Blender or any other tool)

- **One object per structure**, named exactly as listed below. Use one **collection per group**, named exactly as the group names.
- **Closed (watertight) meshes.** The app's cut-away draws solid cut faces, which only works on closed surfaces. Layers may touch or nest, but each object must be closed on its own.
- **Scale and orientation:**
  - Blocks are about 2 units wide (x), 1.2–1.4 deep (z) and about 1 tall, with the tissue surface or epithelium at the top (+Y up; Blender's Z-up is converted on export).
  - Tube models (arteries, vein, nerve, skeletal muscle) run along the x axis, about 2 units long.
- **Cut-away.** The default cut removes the quadrant x < 0, z > 0 (tubes: x < 0, y > 0). Place key structures (follicles, glands, villi, osteons) so they cross those planes and get sectioned lengthwise.
- **Budget:** roughly 0.5–4 million triangles per model. Materials are optional; colours are assigned per structure in the app.
- **Format:** glTF 2.0 (`.glb`), or the `.blend` file itself. The app currently generates these models from code, so an importer would need to be added before external files can be used.

## How the current models are built

Worth knowing if you are asking someone to match or beat them:

- Vessels, nerves and muscle are **swept around a curved centreline** whose calibre varies along its length, with a radius that is a free function of angle and position - nothing is a cylinder of revolution. A contracted artery's intima is thrown into longitudinal folds, so its lumen is star-shaped in section.
- Every free surface carries **the relief of its own cells**: endothelium as cobblestones stretched along the flow, smooth muscle as spindles wrapped around the circumference, urothelium as domed umbrella cells.
- Dense connective tissue - adventitia, epineurium, epimysium, the fibrous periosteum - is a **felt of individual collagen bundles** rather than a smooth sleeve, and smooth muscle layers in the gut and bladder are **interlacing bundles** with the plexuses running in the gaps between them.
- Every block model ends with one **shared warp** applied to all of its layers at once: a sag that makes surfaces billow and side walls bow, a tissue grain, and a cell-sized micro-relief. Because the warp is a function of position, nested layers stay in register however thin they are.
- Layers that would otherwise bury their contents (thyroid stroma, tracheal anular ligament, tongue interstitium) are built as the **complement** of what sits inside them, so follicles, cartilage rings and muscle bundles stay visible.

## Skin

### Thin (hairy) skin
- **Epidermis:** Stratum corneum; Stratum granulosum; Stratum spinosum; Stratum basale; Melanocytes
- **Dermis:** Papillary dermis; Reticular dermis
- **Hypodermis:** Hypodermis septa; Adipocytes (fat lobules)
- **Hair follicle:** Hair shaft; Inner root sheath; Outer root sheath; Hair bulb (matrix); Dermal papilla of hair
- **Glands:** Sebaceous gland; Arrector pili muscle; Eccrine sweat gland (secretory coil); Eccrine sweat duct
- **Vessels & nerves:** Arterioles; Venules; Subpapillary plexus; Papillary capillary loops; Cutaneous nerve & branches
- **Sensory receptors:** Pacinian corpuscles (lamellae); Pacinian axon terminal

### Thick (glabrous) skin
- **Epidermis:** Stratum corneum; Stratum lucidum; Stratum granulosum; Stratum spinosum; Stratum basale; Melanocytes
- **Dermis:** Papillary dermis; Reticular dermis
- **Hypodermis:** Hypodermis septa; Adipocytes (fat lobules)
- **Glands:** Eccrine sweat gland (secretory coil); Eccrine sweat duct
- **Vessels & nerves:** Arterioles; Venules; Subpapillary plexus; Papillary capillary loops; Cutaneous nerve & branches
- **Sensory receptors:** Meissner corpuscles; Pacinian corpuscles (lamellae); Pacinian axon terminal
- Surface has fingerprint (epidermal) ridges with sweat pores; no hair.

### Scalp skin
- Same structures as thin skin, minus the Pacinian corpuscles.
- Many deep terminal follicles whose bulbs sit in the fat, with larger sebaceous glands.

### Axillary skin (apocrine glands)
- Same as thin skin, minus the Pacinian corpuscles.
- **Glands** also include: Apocrine sweat gland; Apocrine duct (opening into the hair follicle).

## Digestive tract

### Small intestine wall (jejunum)
- **Serosa & muscularis externa:** Serosa; Outer longitudinal muscle; Inner circular muscle
- **Submucosa:** Submucosa (raised into a plica circularis)
- **Mucosa:** Muscularis mucosae; Intestinal crypts (of Lieberkühn); Lamina propria; Paneth cells
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus; Submucosal arterioles; Submucosal venules; Mucosal branches
- **Villi:** Villus epithelium (enterocytes); Villus lamina propria core; Central lacteals; Villus capillary network; Villus smooth muscle; Goblet cells

### Duodenum wall
- As jejunum (leaf-shaped villi, no plica fold, no villus smooth muscle), plus under **Submucosa:** Brunner glands; Brunner gland ducts

### Ileum wall with Peyer patches
- As jejunum (shorter villi, more goblet cells, no plica fold), plus **Lymphoid tissue:** Peyer patch follicles; Germinal centres

### Colon wall
- **Serosa & muscularis externa:** Serosa; Taenia coli & longitudinal muscle; Inner circular muscle
- **Submucosa:** Submucosa
- **Mucosa:** Muscularis mucosae; Surface & crypt epithelium (no villi); Lamina propria; Goblet cells
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal (Meissner) plexus; Submucosal arterioles; Submucosal venules; Mucosal branches
- **Lymphoid tissue:** Solitary lymphoid follicle; Germinal centres

### Stomach wall (fundus/body)
- **Muscularis externa:** Serosa; Outer longitudinal muscle; Middle circular muscle; Inner oblique muscle
- **Nerves & vessels:** Myenteric (Auerbach) plexus; Submucosal arteries; Submucosal veins
- **Submucosa:** Submucosa (rugal core)
- **Mucosa:** Muscularis mucosae; Surface mucous cells & gastric pits; Gland neck & body (mucous neck cells); Parietal (oxyntic) cells; Chief (zymogen) cells – gland base; Lamina propria

### Oesophagus wall
- **Wall layers:** Adventitia
- **Muscularis externa:** Outer longitudinal muscle; Inner circular muscle
- **Nerves & vessels:** Myenteric (Auerbach) plexus
- **Submucosa:** Submucosa
- **Mucosa:** Muscularis mucosae; Lamina propria & papillae
- **Stratified squamous epithelium:** Basal cell layer; Intermediate (prickle) layers; Superficial squamous layer
- **Glands & vessels:** Oesophageal glands; Gland ducts; Submucosal artery; Submucosal venous plexus

### Tongue papillae and taste buds
- **Mucosa:** Stratified squamous epithelium & papillae (filiform, fungiform and circumvallate papillae with its trench); Lamina propria
- **Papillae:** Taste buds
- **Muscle & glands:** Von Ebner glands; Von Ebner ducts; Intrinsic muscle (interstitium); Longitudinal fibres; Transverse fibres; Vertical fibres
- **Nerves & vessels:** Glossopharyngeal nerve branch; Lingual artery branch

### Liver lobule
- **Hepatic plates:** Hepatocytes – zone 3 (centrilobular); Hepatocytes – zone 2 (midzonal); Hepatocytes – zone 1 (periportal); Bile canaliculi
- **Central vein:** Central vein
- **Sinusoids:** Kupffer cells; Stellate (Ito) cells
- **Portal triads:** Portal tract connective tissue; Portal venules; Hepatic arterioles; Bile ductules

## Respiratory

### Trachea wall
- **Wall layers:** Adventitia
- **Cartilage:** Anular ligaments; Hyaline cartilage rings; Perichondrium
- **Mucosa & submucosa:** Submucosa; Lamina propria
- **Epithelium:** Basement membrane; Pseudostratified ciliated epithelium; Cilia; Goblet cells
- **Glands:** Mucous gland acini; Serous demilunes; Gland ducts

### Lung acinus & alveoli
- **Alveoli:** Alveolar septa (type I pneumocytes); Type II pneumocytes; Alveolar macrophages
- **Airways:** Terminal bronchiole wall; Respiratory bronchiole; Bronchiolar smooth muscle; Club (Clara) cells
- **Vessels:** Alveolar capillaries; Pulmonary arteriole (deoxygenated); Pulmonary venule (oxygenated)

## Cardiovascular

### Muscular artery wall
- **Tunica intima:** Endothelium; Subendothelial layer; Internal elastic lamina
- **Tunica media:** Tunica media (smooth muscle); External elastic lamina
- **Tunica adventitia:** Tunica adventitia; Adventitial collagen bundles; Vasa vasorum; Nervi vasorum; Perivascular fat
- **Blood:** Red blood cells; Rolling leukocyte

### Elastic artery (aorta) wall
- **Tunica intima:** Endothelium; Subendothelial layer
- **Tunica media:** Tunica media (smooth muscle); Elastic lamellae
- **Tunica adventitia:** Tunica adventitia; Adventitial collagen bundles; Vasa vasorum; Nervi vasorum; Perivascular fat
- **Blood:** Red blood cells; Rolling leukocyte

### Vein wall with valve
- **Tunica intima:** Endothelium; Venous valve cusps
- **Tunica media:** Tunica media (smooth muscle)
- **Tunica adventitia:** Tunica adventitia; Adventitial collagen bundles; Vasa vasorum; Nervi vasorum; Perivascular fat; Longitudinal smooth muscle bundles
- **Blood:** Red blood cells; Rolling leukocyte

## Musculoskeletal and nervous

### Compact bone & osteons
- **Osteons:** Central (Haversian) canals; Canal vessels & nerves; Concentric lamellae (set A); Concentric lamellae (set B); Cement lines; Osteocytes in lacunae; Canaliculi; Perforating (Volkmann) canal; Volkmann canal vessel
- **Bone matrix:** Interstitial lamellae & matrix
- **Periosteum:** Outer circumferential lamellae; Periosteum – cambium layer; Periosteum – fibrous layer; Sharpey fibres
- **Marrow side:** Endosteum; Trabeculae (spongy bone); Red marrow

### Skeletal muscle organisation
- **Connective tissue:** Epimysium; Epimysial collagen bundles; Perimysium; Endomysium (fascicle sheaths)
- **Muscle fibres:** Muscle fibres; Myonuclei; Myofibrils
- **Nerves & vessels:** Endomysial capillaries; Motor nerve branch; Neuromuscular junction; Muscle spindle capsule; Intrafusal fibres

### Peripheral nerve
- **Connective tissue:** Epineurium; Epineurial collagen bundles; Perineurium; Endoneurium; Vasa nervorum; Epineurial fat
- **Nerve fibres:** Myelin sheaths (internodes, with nodes of Ranvier); Axons; Remak Schwann cells; Unmyelinated axons (C fibres); Schwann cell nuclei

## Urinary

### Nephron & renal corpuscle
- **Renal corpuscle:** Glomerular capillaries; Podocytes; Bowman capsule (parietal layer); Afferent arteriole; Efferent arteriole; Juxtaglomerular cells
- **Tubule:** Proximal convoluted tubule; Straight proximal tubule; Distal convoluted tubule; Collecting duct; Macula densa
- **Loop of Henle:** Thin descending limb; Thin ascending limb; Thick ascending limb
- **Vessels:** Peritubular capillaries; Vasa recta

### Urinary bladder wall (urothelium)
- **Wall layers:** Adventitia
- **Detrusor muscle:** Outer longitudinal detrusor; Middle circular detrusor; Inner longitudinal detrusor
- **Mucosa:** Lamina propria; Muscularis mucosae (discontinuous)
- **Urothelium:** Basal cells; Intermediate cells; Umbrella cells
- **Vessels & nerves:** Subepithelial capillary plexus; Arterioles; Venules; Autonomic nerve

## Eye and endocrine

### Cornea
- **Posterior cornea:** Endothelium; Descemet membrane
- **Stroma:** Stroma; Collagen lamellae; Keratocytes; Corneal nerves & subbasal plexus
- **Anterior cornea:** Bowman layer
- **Epithelium:** Basal columnar cells; Wing cells; Superficial squamous cells; Tear film

### Retina
- **Outer coats:** Sclera; Choroid stroma; Choroidal vessels; Choriocapillaris; Bruch membrane
- **Photoreceptors & RPE:** Retinal pigment epithelium; Rod outer segments; Rod inner segments; Cones
- **Neural retina:** Outer limiting membrane; Outer nuclear layer; Outer plexiform layer; Inner nuclear layer; Inner plexiform layer; Ganglion cell layer; Ganglion cells; Bipolar cells; Nerve fibre layer; Inner limiting membrane; Müller glia; Retinal arteriole; Retinal venule
- **Vitreous:** Vitreous body

### Thyroid follicles
- **Follicles:** Follicular epithelium; Colloid; Parafollicular C cells
- **Stroma & capsule:** Perifollicular capillaries; Interfollicular connective tissue; Capsule; Capsular artery
