from .base import MicroModel
from .gut import build_gut
from .liver import build_liver_lobule
from .lung import build_alveoli
from .bone import build_osteon
from .bundles import build_muscle, build_nerve, home_view
from .vessels import build_vessel
from .walls import build_oesophagus, build_stomach, build_trachea

TUBE_CUT = dict(cutaway=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), cut_at=(0.0, 0.0))


def register_all(register):
    register(MicroModel(
        "jejunum", "Small intestine wall (jejunum)",
        "Tall finger-like villi on a plica circularis, crypts of Lieberkühn with Paneth cells, muscularis mucosae, "
        "submucosa with Meissner plexus, two muscle layers with the Auerbach plexus, and serosa.",
        lambda: build_gut("jejunum"), targets={"structures": ["Jejunum"], "groups": ["Small intestine"]},
        histology=["jejunum", "simple_columnar", "smooth_muscle"], related=["duodenum", "ileum", "colon_wall"],
        clinical=[("Coeliac disease",
                   "Gluten-triggered T-cell injury flattens the villi (villous atrophy) with crypt hyperplasia and "
                   "intraepithelial lymphocytes, causing malabsorption, iron deficiency and dermatitis herpetiformis."),
                  ("Lactose intolerance",
                   "Loss of brush-border lactase on villus tips leaves lactose to be fermented by colonic bacteria – "
                   "bloating and osmotic diarrhoea without mucosal damage.")],
        scale_note="Block ≈ 3 mm wide; villi ≈ 0.5–1 mm tall."))
    register(MicroModel(
        "duodenum", "Duodenum wall",
        "Leaf-shaped villi, crypts and the diagnostic Brunner glands in the submucosa whose ducts open into the "
        "crypts.",
        lambda: build_gut("duodenum"), targets={"structures": ["Duodenum"]},
        histology=["duodenum", "simple_columnar"], related=["jejunum", "stomach_wall"],
        clinical=[("Peptic ulcer",
                   "Duodenal ulcers (usually H. pylori) penetrate the submucosa; posterior ulcers can erode the "
                   "gastroduodenal artery and bleed massively.")]))
    register(MicroModel(
        "ileum", "Ileum wall with Peyer patches",
        "Shorter villi rich in goblet cells overlying Peyer patches – aggregated lymphoid follicles with germinal "
        "centres beneath a dome of M-cell epithelium.",
        lambda: build_gut("ileum"), targets={"groups": ["Small intestine"]},
        histology=["ileum", "lymph_node"], related=["jejunum", "colon_wall"],
        clinical=[("Crohn disease",
                   "Transmural granulomatous inflammation favouring the terminal ileum: skip lesions, fissuring "
                   "ulcers, strictures and fistulae; B12 and bile acid malabsorption."),
                  ("Intussusception",
                   "Hypertrophied Peyer patches after viral infection can act as a lead point for ileocolic "
                   "intussusception in young children.")]))
    register(MicroModel(
        "colon_wall", "Colon wall",
        "No villi: a flat surface pitted by the openings of straight, closely packed crypts full of goblet cells, "
        "a solitary lymphoid follicle, a taenia coli band of longitudinal muscle and an appendix epiploica.",
        lambda: build_gut("colon"),
        targets={"structures": ["Ascending colon", "Transverse colon", "Descending colon", "Sigmoid colon",
                                "Free taenia", "Mesocolic taenia", "Omental taenia", "Vermiform appendix"],
                 "groups": ["Colon", "Large intestine"]},
        histology=["colon", "appendix"], related=["ileum", "jejunum"],
        clinical=[("Diverticulosis",
                   "Mucosa and submucosa herniate through weak points where vasa recta pierce the muscle between "
                   "the taeniae – most often in the sigmoid colon."),
                  ("Hirschsprung disease",
                   "Absent ganglion cells in the submucosal and myenteric plexuses of the distal colon (failed neural "
                   "crest migration) leave a tonically contracted segment; delayed passage of meconium."),
                  ("Ulcerative colitis",
                   "Continuous mucosal inflammation from the rectum with crypt abscesses and goblet-cell depletion.")]))
    register(MicroModel(
        "stomach_wall", "Stomach wall (fundus/body)",
        "Gastric pits lined by surface mucous cells lead into oxyntic glands – mucous neck cells, parietal cells, "
        "chief cells at the base and enteroendocrine cells – over a muscularis mucosae, a submucosal ruga with "
        "vessels, lymphatics and Meissner plexus, and oblique, circular and longitudinal muscle under the serosa.",
        build_stomach, targets={"structures": ["Stomach", "Mucosa of stomach"]},
        scale_note="Block ≈ 3 mm wide; mucosa ≈ 1 mm thick, with pits in its upper quarter.",
        histology=["stomach", "pylorus", "gej"], related=["oesophagus_wall", "duodenum"],
        clinical=[("Pernicious anaemia",
                   "Autoimmune destruction of parietal cells (antibodies to H+/K+-ATPase and intrinsic factor) causes "
                   "achlorhydria, B12 deficiency and megaloblastic anaemia."),
                  ("Zollinger–Ellison syndrome",
                   "A gastrinoma drives parietal-cell hyperplasia and massive acid output – multiple and distal "
                   "duodenal ulcers."),
                  ("Helicobacter pylori",
                   "Colonises the mucus layer of the antrum, causing chronic gastritis, ulcers, gastric "
                   "adenocarcinoma and MALT lymphoma.")]))
    register(MicroModel(
        "oesophagus_wall", "Oesophagus wall",
        "Thick non-keratinised stratified squamous epithelium on papillae with capillary loops, a thick muscularis "
        "mucosae, submucosal glands, the venous plexus of varices, and a muscularis externa that changes from "
        "skeletal to smooth muscle along the block (the mixed middle third), under an adventitia.",
        build_oesophagus, targets={"structures": ["Oesophagus"]},
        scale_note="Block ≈ 4 mm wide; the muscularis externa grades from skeletal fascicles at one end to smooth "
                   "muscle bundles at the other, as it does along the middle third.",
        histology=["oesophagus", "strat_squamous_nk", "gej"], related=["stomach_wall"],
        clinical=[("Oesophageal varices",
                   "Portal hypertension distends the submucosal venous plexus (left gastric–azygos anastomosis); "
                   "rupture causes life-threatening haematemesis."),
                  ("Barrett oesophagus",
                   "Chronic reflux replaces squamous epithelium with intestinal-type columnar epithelium containing "
                   "goblet cells – a precursor of adenocarcinoma."),
                  ("Achalasia",
                   "Loss of inhibitory neurons in the myenteric plexus prevents relaxation of the lower oesophageal "
                   "sphincter (bird's-beak appearance on barium swallow).")]))
    register(MicroModel(
        "trachea_wall", "Trachea wall",
        "A short length of the whole airway: a carpet of cilia and goblet cells on pseudostratified epithelium, a "
        "thick basement membrane, seromucous glands whose ducts open on the surface, C-shaped hyaline cartilage "
        "rings with chondrocytes in isogenous groups, and the trachealis closing the posterior gap.",
        build_trachea, targets={"structures": ["Trachea"], "groups": ["Bronchi"], "contains": ["bronchus"]},
        scale_note="Lumen ≈ 15 mm across; mucosa and submucosa drawn about six times too thick so cells stay "
                   "visible.", **TUBE_CUT,
        histology=["trachea", "pseudostratified", "hyaline_cartilage", "bronchus"], related=["lung_acinus"],
        clinical=[("Smoking",
                   "Paralyses cilia and causes goblet-cell hyperplasia, gland hypertrophy and squamous metaplasia – "
                   "the soil for squamous cell carcinoma."),
                  ("Tracheomalacia",
                   "Weak or deficient cartilage rings let the airway collapse on expiration, causing stridor in "
                   "infants.")]))
    register(MicroModel(
        "muscular_artery", "Muscular artery wall",
        "A thick wall round a narrow lumen: endothelium on a wavy internal elastic lamina, a media of circular smooth "
        "muscle, an external elastic lamina, and an adventitia with vasa and nervi vasorum.",
        lambda: build_vessel("muscular"), targets={"categories": ["artery"]},
        histology=["muscular_artery", "capillaries"], related=["elastic_artery", "vein_wall"],
        clinical=[("Atherosclerosis",
                   "LDL retained in the intima is oxidised and engulfed by macrophages (foam cells); smooth muscle "
                   "migrates from the media to form a fibrous cap. Cap rupture triggers thrombosis (MI, stroke)."),
                  ("Mönckeberg medial calcification",
                   "Ring-like calcification of the media in the elderly – does not narrow the lumen but makes vessels "
                   "incompressible (falsely high ankle–brachial index).")],
        **TUBE_CUT))
    register(MicroModel(
        "elastic_artery", "Elastic artery (aorta) wall",
        "A wide lumen in a relatively thin wall: a thin intima, a media of wavy fenestrated elastic lamellae with "
        "smooth muscle between them, and an adventitia whose vasa vasorum penetrate the outer media.",
        lambda: build_vessel("elastic"),
        targets={"groups": ["Aorta", "Root of aorta"], "contains": ["aorta", "pulmonary trunk"]},
        histology=["elastic_artery"], related=["muscular_artery", "vein_wall"],
        clinical=[("Aortic dissection",
                   "Blood tears through the intima into a weakened media (hypertension, Marfan, Ehlers–Danlos), "
                   "creating a false lumen – tearing chest pain radiating to the back."),
                  ("Syphilitic aortitis",
                   "Endarteritis of the vasa vasorum destroys medial elastic tissue ('tree-bark' intima), causing "
                   "ascending aortic aneurysm and aortic regurgitation.")],
        **TUBE_CUT))
    register(MicroModel(
        "vein_wall", "Vein wall with valve",
        "A wide, flattened lumen in a thin wall: a thin media, a thick adventitia with longitudinal muscle bundles, "
        "and a bicuspid valve whose cusps point towards the heart over a dilated sinus.",
        lambda: build_vessel("vein"), targets={"categories": ["vein", "pulm_vein"]},
        histology=["vein"], related=["muscular_artery"],
        clinical=[("Varicose veins & DVT",
                   "Valve incompetence in superficial leg veins causes varicosities; stasis behind valve cusps is "
                   "where deep vein thrombi begin (Virchow triad).")],
        **TUBE_CUT))
    register(MicroModel(
        "lung_acinus", "Lung acinus & alveoli",
        "A terminal bronchiole with club cells and spiral smooth muscle divides into respiratory bronchioles budding "
        "alveoli, then alveolar ducts ringed by smooth-muscle knobs and ending in alveolar sacs. Interalveolar septa "
        "carry a capillary network, type II pneumocytes, pores of Kohn and macrophages; the pulmonary arteriole runs "
        "with the airways and the venule at the acinus edge. The cut opens the acinus down its middle.",
        build_alveoli, cut_at=(1.1, 0.0),
        scale_note="Block ≈ 2.4 mm long; alveoli ≈ 0.2 mm across (a real acinus has more generations of ducts).",
        targets={"groups": ["Lungs", "Left lung", "Right lung"],
                                "contains": ["lobe of left lung", "lobe of right lung"]},
        histology=["lung", "bronchiole", "simple_squamous"], related=["trachea_wall"],
        clinical=[("Emphysema",
                   "Protease–antiprotease imbalance destroys alveolar walls: centriacinar (upper lobes, smoking) or "
                   "panacinar (lower lobes, α1-antitrypsin deficiency)."),
                  ("Neonatal respiratory distress syndrome",
                   "Premature type II pneumocytes make too little surfactant, so alveoli collapse and hyaline "
                   "membranes form; prevented by antenatal corticosteroids.")]))
    register(MicroModel(
        "compact_bone", "Compact bone & osteons",
        "A wedge of long-bone shaft from periosteum to marrow: osteons running the length of the block, with "
        "concentric lamellae, cement lines, osteocyte lacunae and canaliculi around central canals carrying a "
        "vessel pair and nerve; Volkmann canals joining them; interstitial and circumferential lamellae; periosteum "
        "(fibrous and cambium layers, Sharpey fibres, vessels) and endosteum; and the transition into trabeculae "
        "with osteoblasts, osteoclasts and red marrow. One osteon is telescoped to show its helical collagen.",
        build_osteon, targets={"categories": ["bone"]},
        histology=["compact_bone", "spongy_bone", "ossification", "bone_marrow"], related=["skeletal_muscle"],
        clinical=[("Osteoporosis",
                   "Resorption outpaces formation: cortices thin from the endosteal side, Haversian canals widen and "
                   "trabeculae perforate and disappear, causing fragility fractures of the vertebrae, hip and wrist."),
                  ("Osteogenesis imperfecta",
                   "Defective type I collagen (COL1A1/2) gives brittle bones, blue sclerae and hearing loss."),
                  ("Osteonecrosis and sequestrum",
                   "When the blood supply is cut (femoral neck fracture, steroids, osteomyelitis) osteocytes die and "
                   "their lacunae empty; dead bone is removed by osteoclasts or walled off as a sequestrum."),
                  ("Paget disease of bone",
                   "Disordered, excessive remodelling leaves a chaotic 'mosaic' of scalloped cement lines; bones "
                   "enlarge but are weak, with raised alkaline phosphatase."),
                  ("Fracture healing",
                   "The cambium layer of the periosteum and the endosteum supply the cells of the callus; stripping "
                   "the periosteum or damaging the medullary vessels delays union.")]))
    register(home_view(MicroModel(
        "skeletal_muscle", "Skeletal muscle organisation",
        "A muscle opened like a telescope: epimysium round the whole muscle, fascicles each wrapped in perimysium, "
        "polygonal fibres with peripheral nuclei and capillaries in endomysium, single fibres with satellite cells "
        "and motor end plates, and one fibre fraying into myofibrils showing every sarcomere band, T tubules and "
        "sarcoplasmic reticulum - plus a muscle spindle.",
        build_muscle, targets={"categories": ["muscle"]},
        histology=["skeletal_muscle"], related=["peripheral_nerve", "compact_bone"],
        clinical=[("Duchenne muscular dystrophy",
                   "X-linked loss of dystrophin tears the sarcolemma during contraction; fibres necrose and are "
                   "replaced by fat (calf pseudohypertrophy, Gowers sign)."),
                  ("Myasthenia gravis",
                   "Antibodies to acetylcholine receptors at the motor end plate cause fatigable weakness (ptosis, "
                   "diplopia); associated with thymoma."),
                  ("Malignant hyperthermia",
                   "RyR1 mutations let volatile anaesthetics or suxamethonium trigger uncontrolled Ca²⁺ release from "
                   "the sarcoplasmic reticulum: rigidity, rising end-tidal CO₂, hyperthermia and rhabdomyolysis. "
                   "Treated with dantrolene.")],
        scale_note="Muscle ≈ 3 mm across. Each step of the telescope is enlarged relative to the last: myofibrils "
                   "(~1 µm) and sarcomeres (~2.5 µm) are drawn 15–30× larger than life.",
        **TUBE_CUT)))
    register(MicroModel(
        "liver_lobule", "Liver lobule",
        "A hexagonal classic lobule with a rim of its neighbours: branching hepatocyte plates (zones 1–3) radiate from "
        "a central vein whose wall the sinusoids pierce; portal tracts at the corners hold a portal venule, hepatic "
        "arteriole, cuboidal bile ductule and lymphatic behind a limiting plate. Sinusoidal endothelial, Kupffer and "
        "stellate cells, bile canaliculi and canals of Hering, and one Rappaport acinus shown translucent.",
        build_liver_lobule, scale_note="Block ≈ 1.8 mm across; lobule ≈ 1.4 mm corner to corner.",
        targets={"structures": ["Liver"], "contains": ["segment of liver"]},
        histology=["liver", "gallbladder"],
        clinical=[("Cirrhosis",
                   "Activated stellate cells lay down collagen in the space of Disse; bridging fibrous septa encircle "
                   "regenerative nodules and obstruct portal flow (portal hypertension)."),
                  ("Paracetamol overdose",
                   "CYP2E1 in zone 3 converts paracetamol to NAPQI; when glutathione runs out, centrilobular necrosis "
                   "follows. N-acetylcysteine replenishes glutathione."),
                  ("Congestive hepatopathy",
                   "Right heart failure engorges central veins and zone 3 sinusoids – 'nutmeg liver'.")]))
    register(home_view(MicroModel(
        "peripheral_nerve", "Peripheral nerve",
        "A nerve opened like a telescope: epineurium with fat and vasa nervorum, fascicles each ringed by lamellar "
        "perineurium, and endoneurium packed with myelinated fibres (pale myelin rings round central axons) and "
        "Remak bundles of unmyelinated C fibres. A few fibres run on alone to show internodes, nodes of Ranvier "
        "and Schwann cell nuclei.",
        build_nerve, targets={"categories": ["nerve"]},
        histology=["peripheral_nerve", "ganglion"], related=["skeletal_muscle"],
        clinical=[("Nerve injury grades",
                   "Neurapraxia (conduction block, full recovery), axonotmesis (axons cut, sheaths intact – regrowth "
                   "~1 mm/day) and neurotmesis (whole nerve divided – needs surgical repair)."),
                  ("Guillain–Barré syndrome",
                   "Post-infectious autoimmune demyelination of peripheral nerves – ascending weakness with areflexia "
                   "and raised CSF protein."),
                  ("Diabetic neuropathy",
                   "Length-dependent axonal loss, small unmyelinated fibres first (burning feet, lost pain and "
                   "temperature sense in a stocking distribution), plus occlusion of the vasa nervorum causing acute "
                   "mononeuropathies such as a pupil-sparing third-nerve palsy.")],
        scale_note="Nerve ≈ 3 mm across; fibres drawn about 5× enlarged and internodes about 10× shorter than life "
                   "so that nodes of Ranvier fit in the block.",
        **TUBE_CUT)))
    register_more(register)


def register_more(register):
    from .glands import build_thyroid, build_tongue
    from .organs2 import build_bladder, build_cornea, build_retina
    register(MicroModel(
        "bladder_wall", "Urinary bladder wall (urothelium)",
        "Urothelium shown empty at one end (thick, domed umbrella cells, rugae) and filling at the other (thin, "
        "flat umbrella cells): binucleate umbrella cells with uroplakin plaques and fusiform vesicles, intermediate "
        "and basal cells, a lamina propria with its capillary plexus, discontinuous muscularis mucosae and vessels, "
        "the interlacing fascicles of the three detrusor layers, adventitia with fat, and the serosa of the dome.",
        build_bladder, targets={"structures": ["Urinary bladder", "Ureter"]},
        histology=["bladder", "transitional", "ureter"], related=["kidney_nephron"],
        clinical=[("Urothelial carcinoma staging",
                   "Tumours confined to the mucosa (Ta/Tis) or lamina propria (T1) are treated by resection and "
                   "intravesical BCG; invasion of the detrusor (T2) usually needs cystectomy – so the biopsy must "
                   "include muscle."),
                  ("Haemorrhagic cystitis",
                   "Acrolein, a metabolite of cyclophosphamide and ifosfamide, injures the urothelium; mesna binds "
                   "it in the urine.")]))
    register(MicroModel(
        "cornea", "Cornea",
        "Peripheral cornea running into the limbus: tear film, non-keratinised epithelium, Bowman layer, the "
        "plywood of stromal lamellae with keratocytes and nerves, pre-Descemet (Dua) layer, Descemet membrane and "
        "endothelium; then the limbal stem cell niche in the palisades of Vogt, conjunctiva, sclera and the "
        "drainage angle with trabecular meshwork and Schlemm canal.",
        build_cornea, targets={"structures": ["Cornea"]},
        histology=["cornea", "strat_squamous_nk"], related=["retina"],
        clinical=[("Corneal abrasion and ulcer",
                   "Epithelial defects stain with fluorescein and heal in days; contact lens wearers are at risk of "
                   "Pseudomonas and Acanthamoeba keratitis, which can perforate the stroma."),
                  ("Fuchs endothelial dystrophy",
                   "Progressive endothelial cell loss with guttae on Descemet membrane causes stromal oedema, glare "
                   "and morning blurring; treated with endothelial keratoplasty."),
                  ("Keratoconus",
                   "Thinning and conical bulging of the stroma produces irregular astigmatism; collagen cross-linking "
                   "halts progression.")],
        scale_note="Central cornea ≈ 0.55 mm thick; epithelium ≈ 50 µm. The limbus is squeezed in sideways."))
    register(MicroModel(
        "retina", "Retina",
        "The ten layers of the retina built from their cells - RPE, rods and cones, the nuclear and plexiform "
        "layers with bipolar, horizontal, amacrine and ganglion cells, the nerve fibre layer and inner limiting "
        "membrane - with Müller glia, retinal vessels and capillary plexuses, and Bruch membrane, choriocapillaris, "
        "choroid and sclera behind.",
        build_retina, targets={"structures": ["Retina", "Optic nerve (II)"]},
        histology=["retina", "eye"], related=["cornea"],
        clinical=[("Retinal detachment",
                   "Fluid enters between the neural retina and the RPE (usually through a tear), cutting the "
                   "photoreceptors off from the choriocapillaris: flashes, floaters and a curtain over vision."),
                  ("Age-related macular degeneration",
                   "Dry: drusen in Bruch membrane and RPE atrophy. Wet: choroidal vessels break through Bruch "
                   "membrane and leak – treated with anti-VEGF injections."),
                  ("Diabetic retinopathy",
                   "Pericyte loss and microaneurysms, hard exudates in the outer plexiform layer, cotton-wool spots "
                   "in the nerve fibre layer and eventually neovascularisation.")],
        scale_note="Retina ≈ 250 µm thick near the macula; cells are drawn larger and fewer than in life."))
    register(MicroModel(
        "thyroid_follicles", "Thyroid follicles",
        "Colloid-filled follicles of every size packed in three dimensions, lined by follicular epithelium whose "
        "height follows activity, with resorption vacuoles, parafollicular C cells and perifollicular capillary "
        "baskets; lobules divided by septa under the capsule, and a parathyroid gland with chief cells, oxyphil "
        "cells and fat in the corner.",
        build_thyroid, targets={"structures": ["Thyroid gland"]},
        histology=["thyroid", "parathyroid"],
        clinical=[("Graves disease",
                   "TSH-receptor antibodies make follicular cells tall and columnar with scalloped, pale colloid – "
                   "hyperthyroidism with diffuse goitre."),
                  ("Hashimoto thyroiditis",
                   "Lymphocytic infiltrate with germinal centres destroys follicles; surviving cells become "
                   "eosinophilic Hürthle cells – hypothyroidism."),
                  ("Papillary carcinoma",
                   "The commonest thyroid cancer: papillae with optically clear 'Orphan Annie' nuclei, nuclear grooves "
                   "and psammoma bodies; spreads to cervical lymph nodes.")],
        scale_note="Follicles 50–500 µm across."))
    register(MicroModel(
        "tongue_papillae", "Tongue papillae and taste buds",
        "Dorsal tongue with rows of keratinised filiform papillae, fungiform papillae with taste buds, a "
        "circumvallate papilla whose trench walls are lined with taste buds and flushed by von Ebner glands, and "
        "foliate papillae on the lateral margin, over intrinsic skeletal muscle interlacing in three planes.",
        build_tongue, targets={"structures": ["Tongue"], "groups": ["Muscles of tongue"]},
        histology=["tongue", "strat_squamous_nk", "skeletal_muscle"], related=["oesophagus_wall"],
        clinical=[("Taste loss localisation",
                   "Anterior two-thirds (fungiform) via chorda tympani – lost in Bell palsy proximal to the chorda; "
                   "posterior third (vallate) via glossopharyngeal nerve."),
                  ("Atrophic glossitis",
                   "Loss of filiform papillae gives a smooth, sore, beefy-red tongue in iron, B12 or folate deficiency."),
                  ("Geographic tongue",
                   "Migrating patches of filiform papilla loss with white serpiginous borders – benign.")]))
