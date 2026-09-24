from .base import MicroModel
from .gut import build_gut
from .kidney import build_nephron
from .organs3 import build_alveoli, build_liver_lobule
from .bone import build_osteon
from .bundles import build_muscle, build_nerve
from .vessels import build_vessel
from .walls import build_oesophagus, build_stomach, build_trachea

TUBE_CUT = dict(cutaway=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), cut_at=(0.0, 0.0))
# The aorta is already a telescoped cutaway, so a cut along its whole length would only chop the steps into planks.
# Instead the cut opens a window in the adventitia-covered half alone (x > 0, which starts a little past where the
# adventitia begins): the half of the wall facing the default up-and-front viewpoint (0.5 y + 0.87 z > 0) is taken
# away there, so the lumen, its blood and a second cross-section through every layer come into view while the
# telescoped steps stay whole. Dragging the first plane slides the window along the vessel.
WEDGE_CUT = dict(cutaway=((-1.0, 0.0, 0.0), (0.0, 0.5, 0.866)), cut_at=(0.0, 0.0))


def _opens_uncut(model):
    """Open a model with its cut-away switched off. For a model that is its own cutaway (the telescoped aorta shows
    every layer's surface and ends in a clean full cross-section) a default cut only chops that design into planks;
    the cut stays available from the viewer's Cut-away checkbox. MicroView and tools/render_micro.py read this."""
    model.cut_on = False
    return model


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
        "No villi: a flat surface over straight, closely packed crypts full of goblet cells, a solitary lymphoid "
        "follicle and a taenia coli band of longitudinal muscle.",
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
        "Surface mucous cells and gastric pits leading into long oxyntic glands with parietal and chief cells, a "
        "rugal fold, and the three-layered muscularis externa with its inner oblique layer.",
        build_stomach, targets={"structures": ["Stomach", "Mucosa of stomach"]},
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
        "Thick non-keratinised stratified squamous epithelium on papillae, a prominent muscularis mucosae, "
        "submucosal glands and venous plexus, and muscularis externa covered by adventitia.",
        build_oesophagus, targets={"structures": ["Oesophagus"]},
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
        "Pseudostratified ciliated epithelium with goblet cells on a thick basement membrane, seromucous glands in "
        "the submucosa and hyaline cartilage rings linked by anular ligaments.",
        build_trachea, targets={"structures": ["Trachea"], "groups": ["Bronchi"], "contains": ["bronchus"]},
        histology=["trachea", "pseudostratified", "hyaline_cartilage", "bronchus"], related=["lung_acinus"],
        clinical=[("Smoking",
                   "Paralyses cilia and causes goblet-cell hyperplasia, gland hypertrophy and squamous metaplasia – "
                   "the soil for squamous cell carcinoma."),
                  ("Tracheomalacia",
                   "Weak or deficient cartilage rings let the airway collapse on expiration, causing stridor in "
                   "infants.")]))
    register(MicroModel(
        "muscular_artery", "Muscular artery wall",
        "Endothelium, internal elastic lamina, a thick smooth-muscle media, external elastic lamina and adventitia "
        "with vasa and nervi vasorum.",
        lambda: build_vessel("muscular"), targets={"categories": ["artery"]},
        histology=["muscular_artery", "capillaries"], related=["elastic_artery", "vein_wall"],
        clinical=[("Atherosclerosis",
                   "LDL retained in the intima is oxidised and engulfed by macrophages (foam cells); smooth muscle "
                   "migrates from the media to form a fibrous cap. Cap rupture triggers thrombosis (MI, stroke)."),
                  ("Mönckeberg medial calcification",
                   "Ring-like calcification of the media in the elderly – does not narrow the lumen but makes vessels "
                   "incompressible (falsely high ankle–brachial index).")],
        **TUBE_CUT))
    register(_opens_uncut(MicroModel(
        "elastic_artery", "Elastic artery (aorta) wall",
        "A thick media of concentric elastic lamellae with smooth muscle between them, and an adventitia with vasa "
        "vasorum.",
        lambda: build_vessel("elastic"),
        targets={"groups": ["Aorta", "Root of aorta"], "contains": ["aorta", "pulmonary trunk"]},
        histology=["elastic_artery"], related=["muscular_artery", "vein_wall"],
        clinical=[("Aortic dissection",
                   "Blood tears through the intima into a weakened media (hypertension, Marfan, Ehlers–Danlos), "
                   "creating a false lumen – tearing chest pain radiating to the back."),
                  ("Syphilitic aortitis",
                   "Endarteritis of the vasa vasorum destroys medial elastic tissue ('tree-bark' intima), causing "
                   "ascending aortic aneurysm and aortic regurgitation.")],
        **WEDGE_CUT)))
    register(MicroModel(
        "vein_wall", "Vein wall with valve",
        "Large thin-walled lumen, a thin media, a thick adventitia with longitudinal muscle bundles, and a bicuspid "
        "valve.",
        lambda: build_vessel("vein"), targets={"categories": ["vein", "pulm_vein"]},
        histology=["vein"], related=["muscular_artery"],
        clinical=[("Varicose veins & DVT",
                   "Valve incompetence in superficial leg veins causes varicosities; stasis behind valve cusps is "
                   "where deep vein thrombi begin (Virchow triad).")],
        **TUBE_CUT))
    register(MicroModel(
        "lung_acinus", "Lung acinus & alveoli",
        "A terminal bronchiole leading to respiratory bronchioles, alveolar ducts and sacs wrapped in capillaries, "
        "with type II pneumocytes, a macrophage and the accompanying pulmonary vessels.",
        build_alveoli, targets={"groups": ["Lungs", "Left lung", "Right lung"],
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
        "Cylindrical osteons of concentric lamellae around central canals, osteocytes in lacunae, a Volkmann canal, "
        "interstitial lamellae, periosteum with Sharpey fibres and the endosteal/marrow surface.",
        build_osteon, targets={"categories": ["bone"]},
        histology=["compact_bone", "spongy_bone", "ossification", "bone_marrow"], related=["skeletal_muscle"],
        clinical=[("Osteoporosis",
                   "Resorption outpaces formation: cortices thin and trabeculae disappear, causing fragility fractures "
                   "of the vertebrae, hip and wrist."),
                  ("Osteogenesis imperfecta",
                   "Defective type I collagen (COL1A1/2) gives brittle bones, blue sclerae and hearing loss.")]))
    register(MicroModel(
        "skeletal_muscle", "Skeletal muscle organisation",
        "Epimysium, fascicles wrapped in perimysium, fibres in endomysium with peripheral nuclei, an exposed fibre "
        "showing myofibrils and striations, capillaries, a neuromuscular junction and a muscle spindle.",
        build_muscle, targets={"categories": ["muscle"]},
        histology=["skeletal_muscle"], related=["peripheral_nerve", "compact_bone"],
        clinical=[("Duchenne muscular dystrophy",
                   "X-linked loss of dystrophin tears the sarcolemma during contraction; fibres necrose and are "
                   "replaced by fat (calf pseudohypertrophy, Gowers sign)."),
                  ("Myasthenia gravis",
                   "Antibodies to acetylcholine receptors at the motor end plate cause fatigable weakness (ptosis, "
                   "diplopia); associated with thymoma.")],
        **TUBE_CUT))
    register(MicroModel(
        "nephron", "Nephron & renal corpuscle",
        "Glomerulus in Bowman capsule with afferent/efferent arterioles and JG cells, proximal tubule, loop of Henle, "
        "distal tubule with macula densa, collecting duct, peritubular capillaries and vasa recta.",
        build_nephron, targets={"structures": ["Kidney", "Renal pelvis"]},
        histology=["kidney_cortex", "kidney_medulla"],
        clinical=[("Nephrotic vs nephritic",
                   "Podocyte injury (minimal change, FSGS, membranous) leaks protein – nephrotic syndrome; "
                   "inflammation of glomerular capillaries (post-streptococcal, IgA) causes haematuria and "
                   "hypertension – nephritic."),
                  ("Diuretic targets",
                   "Acetazolamide – PCT; loop diuretics – NKCC2 of the thick ascending limb; thiazides – NCC of the "
                   "DCT; amiloride and spironolactone – principal cells of the collecting duct."),
                  ("Acute tubular necrosis",
                   "Ischaemia or toxins (aminoglycosides, contrast) kill PCT and thick-limb cells, forming muddy-brown "
                   "granular casts.")],
        cut_at=(-5.0, 5.0)))
    register(MicroModel(
        "liver_lobule", "Liver lobule",
        "Radiating hepatocyte plates in zones 1–3 around a central vein, portal triads (portal venule, hepatic "
        "arteriole, bile ductule) at the corners, bile canaliculi, Kupffer and stellate cells.",
        build_liver_lobule, targets={"structures": ["Liver"], "contains": ["segment of liver"]},
        histology=["liver", "gallbladder"],
        clinical=[("Cirrhosis",
                   "Activated stellate cells lay down collagen in the space of Disse; bridging fibrous septa encircle "
                   "regenerative nodules and obstruct portal flow (portal hypertension)."),
                  ("Paracetamol overdose",
                   "CYP2E1 in zone 3 converts paracetamol to NAPQI; when glutathione runs out, centrilobular necrosis "
                   "follows. N-acetylcysteine replenishes glutathione."),
                  ("Congestive hepatopathy",
                   "Right heart failure engorges central veins and zone 3 sinusoids – 'nutmeg liver'.")]))
    register(MicroModel(
        "peripheral_nerve", "Peripheral nerve",
        "Epineurium with fat and vessels around fascicles bounded by perineurium; myelinated fibres with internodes "
        "and nodes of Ranvier, axons, Schwann cell nuclei and unmyelinated Remak bundles in the endoneurium.",
        build_nerve, targets={"categories": ["nerve"]},
        histology=["peripheral_nerve", "ganglion"], related=["skeletal_muscle"],
        clinical=[("Nerve injury grades",
                   "Neurapraxia (conduction block, full recovery), axonotmesis (axons cut, sheaths intact – regrowth "
                   "~1 mm/day) and neurotmesis (whole nerve divided – needs surgical repair)."),
                  ("Guillain–Barré syndrome",
                   "Post-infectious autoimmune demyelination of peripheral nerves – ascending weakness with areflexia "
                   "and raised CSF protein.")],
        **TUBE_CUT))
    register_more(register)


def register_more(register):
    from .glands import build_thyroid, build_tongue
    from .organs2 import build_bladder, build_cornea, build_retina
    register(MicroModel(
        "bladder_wall", "Urinary bladder wall (urothelium)",
        "Transitional epithelium with dome-shaped umbrella cells, intermediate and basal cells on a folded lamina "
        "propria, a discontinuous muscularis mucosae and the three interlacing layers of the detrusor muscle.",
        build_bladder, targets={"structures": ["Urinary bladder", "Ureter"]},
        histology=["bladder", "transitional", "ureter"], related=["nephron"],
        clinical=[("Urothelial carcinoma staging",
                   "Tumours confined to the mucosa (Ta/Tis) or lamina propria (T1) are treated by resection and "
                   "intravesical BCG; invasion of the detrusor (T2) usually needs cystectomy – so the biopsy must "
                   "include muscle."),
                  ("Haemorrhagic cystitis",
                   "Acrolein, a metabolite of cyclophosphamide and ifosfamide, injures the urothelium; mesna binds "
                   "it in the urine.")]))
    register(MicroModel(
        "cornea", "Cornea",
        "Five layers of the cornea: non-keratinised stratified squamous epithelium with its tear film, Bowman layer, "
        "the lamellar collagen stroma with keratocytes and nerves, Descemet membrane and the endothelial pump layer.",
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
        scale_note="Central cornea ≈ 0.55 mm thick; epithelium ≈ 50 µm."))
    register(MicroModel(
        "retina", "Retina",
        "The ten layers of the retina from the retinal pigment epithelium and rods and cones to the nerve fibre "
        "layer, with Müller glia, retinal vessels, Bruch membrane, choroid and sclera behind.",
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
        scale_note="Retina ≈ 250 µm thick near the macula; the model exaggerates photoreceptor size."))
    register(MicroModel(
        "thyroid_follicles", "Thyroid follicles",
        "Colloid-filled follicles lined by follicular epithelium, parafollicular C cells, perifollicular capillary "
        "baskets, interfollicular connective tissue and the capsule.",
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
        "Dorsal tongue with keratinised filiform papillae, fungiform papillae with taste buds, a circumvallate "
        "papilla whose trench walls are lined with taste buds and flushed by von Ebner glands, over interlacing "
        "intrinsic skeletal muscle.",
        build_tongue, targets={"structures": ["Tongue"], "groups": ["Muscles of tongue"]},
        histology=["tongue", "strat_squamous_nk", "skeletal_muscle"], related=["oesophagus_wall"],
        clinical=[("Taste loss localisation",
                   "Anterior two-thirds (fungiform) via chorda tympani – lost in Bell palsy proximal to the chorda; "
                   "posterior third (vallate) via glossopharyngeal nerve."),
                  ("Atrophic glossitis",
                   "Loss of filiform papillae gives a smooth, sore, beefy-red tongue in iron, B12 or folate deficiency."),
                  ("Geographic tongue",
                   "Migrating patches of filiform papilla loss with white serpiginous borders – benign.")]))
