"""Descriptions of the parts in the intestine, stomach, oesophagus, trachea, vessel, lung, bone, muscle, kidney,
liver and nerve microanatomy models (the geometry lives in gut.py, walls.py, tissues.py and organs3.py)."""

GUT = {
    "serosa": "Serosa: simple squamous mesothelium over a thin layer of loose connective tissue. Where the gut is "
              "retroperitoneal it is replaced by adventitia.",
    "long": "Outer longitudinal layer of the muscularis externa. Contraction shortens the segment; with the circular "
            "layer it produces peristalsis under control of the myenteric plexus.",
    "circ": "Inner circular layer of the muscularis externa. Contraction narrows the lumen; it thickens to form "
            "sphincters (pyloric, ileocaecal, internal anal).",
    "myenteric": "Myenteric (Auerbach) plexus: ganglia and nerve fibres between the two muscle layers controlling "
                 "motility. Absent in the distal colon in Hirschsprung disease; destroyed in achalasia and Chagas "
                 "disease.",
    "submucosa": "Submucosa: dense irregular connective tissue carrying larger blood vessels, lymphatics and the "
                 "submucosal plexus. In the jejunum it forms the core of the plicae circulares.",
    "submucosal_plexus": "Submucosal (Meissner) plexus: ganglia regulating mucosal secretion, absorption and local "
                         "blood flow.",
    "sub_artery": "Submucosal arteriole: branches to the mucosa and villus capillary networks.",
    "sub_vein": "Submucosal venule: drains mucosal capillaries toward the hepatic portal system.",
    "mm": "Muscularis mucosae: thin inner circular/outer longitudinal smooth muscle that moves the mucosa locally. "
          "Invasion beyond it defines submucosal spread of colorectal cancer.",
    "lp": "Lamina propria: loose connective tissue between the crypts, rich in plasma cells (IgA), lymphocytes, "
          "macrophages, capillaries and lymphatics – part of the gut-associated lymphoid tissue.",
    "villus_epi": "Villus epithelium: simple columnar enterocytes with a microvillous brush border (enzymes such as "
                  "lactase, sucrase) joined by tight junctions. Cells migrate from the crypts to the tip and shed "
                  "in 3–5 days.",
    "villus_core": "Villus core: lamina propria containing a capillary network, a central lacteal and smooth muscle "
                   "strands that shorten the villus to pump lymph.",
    "lacteal": "Central lacteal: blind-ended lymphatic capillary absorbing chylomicrons (dietary fat) into the "
               "lymphatic system; lymph is milky after a fatty meal.",
    "villus_cap": "Villus capillaries: fenestrated capillaries collecting absorbed sugars and amino acids into the "
                  "portal circulation.",
    "goblet": "Goblet cells: unicellular mucous glands with an apical cup of mucin granules (PAS-positive). "
              "Numbers increase from duodenum to colon.",
    "crypt": "Intestinal crypts (of Lieberkühn): tubular glands between villi containing stem cells (Lgr5+), "
             "transit-amplifying cells, enteroendocrine cells and Paneth cells.",
    "paneth": "Paneth cells: at crypt bases, with large eosinophilic apical granules of lysozyme and defensins that "
              "shape the microbiome. Abnormal in Crohn disease.",
    "brunner": "Brunner (duodenal) glands: submucosal mucous glands secreting alkaline mucus and bicarbonate to "
               "neutralise gastric acid – the histological hallmark of the duodenum.",
    "brunner_duct": "Ducts of Brunner glands open into the bases of the crypts.",
    "peyer": "Peyer patch lymphoid follicle: aggregated follicles in the ileal mucosa and submucosa with germinal "
             "centres (B cells) and surrounding T-cell zones.",
    "germinal": "Germinal centre: site of B-cell proliferation, affinity maturation and class switching to IgA.",
    "dome": "Follicle-associated epithelium (dome) with M cells that transport luminal antigens to underlying "
            "immune cells; an entry route for Salmonella and prions.",
    "surface_epi": "Surface epithelium of the colon: absorptive colonocytes (water and electrolytes) interspersed "
                   "with goblet cells.",
    "colon_crypt": "Colonic crypts: straight, closely packed tubular glands rich in goblet cells, with no Paneth "
                   "cells in the normal distal colon.",
    "taenia": "Taenia coli: the longitudinal muscle concentrated into three bands; their tone gathers the colon into "
              "haustra.",
    "follicle": "Solitary lymphoid follicle in the lamina propria and submucosa.",
}

STOMACH = {
    "surface": "Surface mucous cells: simple columnar epithelium secreting a thick, bicarbonate-rich neutral mucus "
               "gel that protects against acid and pepsin. No goblet cells in the normal stomach.",
    "pits": "Gastric pits (foveolae): funnel-shaped invaginations of the surface epithelium into which 3–7 gastric "
            "glands open.",
    "neck": "Mucous neck cells and stem cells in the gland isthmus/neck; they regenerate surface and glandular cells.",
    "parietal": "Parietal (oxyntic) cells: large pale-pink cells with intracellular canaliculi and abundant "
                "mitochondria. H+/K+-ATPase secretes HCl; they also make intrinsic factor for vitamin B12 absorption. "
                "Stimulated by gastrin, histamine (H2) and acetylcholine (M3). Targeted by PPIs.",
    "chief": "Chief (zymogen) cells: basophilic cells at the gland base secreting pepsinogen and gastric lipase.",
    "ee": "Enteroendocrine (ECL) cells: release histamine (and other hormones) in response to gastrin.",
    "glands": "Fundic (oxyntic) glands: long straight tubular glands filling the mucosa of the fundus and body.",
    "oblique": "Inner oblique muscle layer: unique to the stomach, helps churn food into chyme.",
    "rugae": "Rugae: longitudinal folds of mucosa and submucosa that flatten when the stomach distends.",
}

OES = {
    "superficial": "Superficial layer: flattened but still nucleated squamous cells – non-keratinised, so the "
                   "surface stays moist and flexible.",
    "intermediate": "Intermediate (prickle) layers: polyhedral cells joined by desmosomes; glycogen-rich cells "
                    "appear pale.",
    "basal": "Basal layer: 1–3 rows of small dark proliferating cells on the basement membrane. Basal hyperplasia "
             "is an early sign of reflux injury.",
    "papillae": "Lamina propria papillae project into the epithelium; elongation beyond 2/3 of its thickness "
                "suggests reflux oesophagitis.",
    "mm": "Muscularis mucosae: unusually thick longitudinal smooth muscle in the oesophagus.",
    "glands": "Oesophageal glands proper: small submucosal mucous glands lubricating the passage of the bolus.",
    "ducts": "Gland ducts crossing the mucosa to open on the surface.",
    "veins": "Submucosal venous plexus: a portosystemic anastomosis between left gastric (portal) and azygos "
             "(systemic) veins. In portal hypertension it dilates into oesophageal varices that can rupture.",
    "adventitia": "Adventitia: loose connective tissue binding the thoracic oesophagus to surrounding structures "
                  "(no serosa), which lets carcinoma spread early.",
    "circ": "Inner circular muscle. In the upper third skeletal muscle, middle third mixed, lower third smooth.",
    "long": "Outer longitudinal muscle.",
}

TRACH = {
    "cilia": "Cilia: ~200 motile cilia per cell (9+2 axonemes) beating ~1000 times a minute to move mucus upward. "
             "Primary ciliary dyskinesia (Kartagener) impairs this clearance.",
    "epi": "Pseudostratified ciliated columnar epithelium: ciliated cells, goblet cells, basal stem cells, brush "
           "cells and neuroendocrine cells, all resting on one basement membrane.",
    "goblet": "Goblet cells: secrete mucus that traps particles; they multiply in smokers and chronic bronchitis.",
    "bm": "Thick basement membrane (lamina reticularis) – further thickened in asthma.",
    "lp": "Lamina propria: loose connective tissue with elastic fibres, lymphocytes, plasma cells and mast cells.",
    "sub": "Submucosa: connective tissue containing seromucous glands and larger vessels.",
    "glands": "Seromucous tracheal glands: mixed glands adding watery serous fluid (with lysozyme) and mucus to the "
              "airway surface. Hypertrophy raises the Reid index in chronic bronchitis.",
    "ducts": "Gland ducts opening onto the epithelial surface.",
    "rings": "Hyaline cartilage rings: 16–20 C-shaped rings keep the airway open; their open ends face posteriorly "
             "where the trachealis muscle bridges them. Calcify with age.",
    "perichondrium": "Perichondrium: dense connective tissue around each ring, source of chondrocytes.",
    "anular": "Anular (annular) ligaments: fibroelastic membranes between rings allowing the trachea to lengthen "
              "during breathing and neck movement.",
    "adventitia": "Adventitia: connective tissue attaching the trachea to the oesophagus and neck structures.",
}

VESSEL = {
    "endothelium": "Endothelium: simple squamous cells regulating clotting (NO, prostacyclin, von Willebrand "
                   "factor), permeability and vascular tone. Endothelial dysfunction starts atherosclerosis.",
    "subendo": "Subendothelial layer of the intima: thin connective tissue where LDL accumulates and atherosclerotic "
               "plaques form.",
    "iel": "Internal elastic lamina: fenestrated sheet of elastin separating intima from media – wavy in section "
           "because the artery constricts after death. Split and reduplicated in atherosclerosis.",
    "media_musc": "Tunica media: 10–40 layers of circularly arranged smooth muscle cells controlling vessel diameter "
                  "and blood distribution.",
    "eel": "External elastic lamina: thinner elastic sheet at the boundary of media and adventitia.",
    "adventitia": "Tunica adventitia: connective tissue of collagen and elastic fibres anchoring the vessel, carrying "
                  "vasa vasorum and nerves.",
    "vasa": "Vasa vasorum: small vessels supplying the outer wall of large vessels.",
    "nervi": "Nervi vasorum: sympathetic fibres releasing noradrenaline onto medial smooth muscle.",
    "rbc": "Red blood cells: biconcave anucleate discs about 7.5 µm across.",
    "wbc": "Leukocyte rolling along the endothelium before emigrating (mostly in venules).",
    "lamellae": "Elastic lamellae: 40–70 concentric fenestrated elastin sheets that store energy in systole and "
                "recoil in diastole (Windkessel effect).",
    "media_elastic": "Smooth muscle cells between the elastic lamellae synthesise elastin and collagen. Degeneration "
                     "(cystic medial necrosis, Marfan syndrome) weakens the wall.",
    "vein_media": "Thin tunica media: a few layers of smooth muscle with much collagen.",
    "vein_adv": "Thick adventitia: the dominant layer of veins, containing longitudinal smooth muscle bundles in "
                "large veins such as the IVC.",
    "valve": "Venous valve: paired semilunar cusps of intima reinforced by collagen and elastic fibres. Incompetent "
             "valves cause varicose veins and chronic venous insufficiency.",
    "long_muscle": "Longitudinal smooth muscle bundles in the adventitia of large veins.",
}

LUNG = {
    "tb": "Terminal bronchiole: the last purely conducting airway – simple cuboidal epithelium with club cells, a "
          "complete layer of smooth muscle and no cartilage or glands.",
    "rb": "Respiratory bronchiole: its wall is interrupted by scattered alveoli, beginning gas exchange. "
          "Centriacinar emphysema (smoking) destroys this region first.",
    "duct": "Alveolar ducts: passages lined almost entirely by alveolar openings, with smooth muscle knobs at the rims.",
    "sac": "Alveolar sacs: clusters of alveoli at the end of each duct.",
    "alveoli": "Alveoli: ~300–500 million air spaces of ~200 µm lined by type I (flat, gas exchange) and type II "
               "(surfactant) pneumocytes. Panacinar emphysema (α1-antitrypsin deficiency) destroys them uniformly.",
    "cap": "Alveolar capillaries: a dense network in the interalveolar septa; the air–blood barrier is ~0.5 µm thick.",
    "t2": "Type II pneumocytes: cuboidal cells with lamellar bodies secreting surfactant (DPPC) that lowers surface "
          "tension; deficient in neonatal respiratory distress syndrome. They proliferate to repair injury.",
    "mac": "Alveolar macrophage ('dust cell'): phagocytoses particles and microbes; haemosiderin-laden in chronic "
           "left heart failure ('heart failure cells').",
    "pa": "Pulmonary arteriole: carries deoxygenated blood and runs alongside the airway (bronchovascular bundle). "
          "Hypoxic vasoconstriction diverts blood from poorly ventilated alveoli.",
    "pv": "Pulmonary venule: carries oxygenated blood in the connective-tissue septa at the edge of the lobule.",
    "sm": "Smooth muscle rings of the bronchiole – contract in asthma and anaphylaxis.",
    "club": "Club (Clara) cells: dome-shaped secretory cells producing club cell secretory protein and detoxifying "
            "inhaled toxins with cytochrome P450.",
}

BONE = {
    "canal": "Central (Haversian) canal: runs along each osteon carrying capillaries, venules, nerves and loose "
             "connective tissue.",
    "vessels": "Vessels and nerve within the central canal.",
    "lamellae": "Concentric lamellae: 4–20 rings of mineralised matrix around each central canal. Collagen fibres "
                "alternate direction between neighbouring lamellae, like plywood, resisting torsion.",
    "cement": "Cement (reversal) line: mineral-rich, collagen-poor boundary marking where osteon remodelling "
              "stopped. Cracks tend to stop at cement lines.",
    "osteocytes": "Osteocytes: former osteoblasts trapped in lacunae, connected by canaliculi. They sense mechanical "
                  "strain and orchestrate remodelling; they die when blood supply is lost (avascular necrosis).",
    "interstitial": "Interstitial lamellae: remnants of older osteons partly removed by remodelling, filling the "
                    "spaces between intact osteons.",
    "volkmann": "Perforating (Volkmann) canal: runs across the bone to connect central canals with each other, the "
                "periosteum and the marrow cavity. Not surrounded by concentric lamellae.",
    "outer_circ": "Outer circumferential lamellae: continuous rings beneath the periosteum encircling the whole "
                  "shaft, laid down by appositional growth.",
    "periosteum_f": "Periosteum – fibrous layer: dense connective tissue anchored by Sharpey (perforating) fibres; "
                    "richly innervated, so fractures hurt.",
    "periosteum_c": "Periosteum – cambium (osteogenic) layer: osteoprogenitor cells that form fracture callus and "
                    "allow bones to grow in width.",
    "sharpey": "Sharpey fibres: collagen bundles from the periosteum and tendons embedded in the outer lamellae.",
    "endosteum": "Endosteum: thin cellular layer lining the marrow cavity and trabeculae, with osteoblasts and "
                 "osteoclasts.",
    "trabeculae": "Trabeculae of spongy bone lining the marrow cavity.",
    "marrow": "Red marrow between trabeculae.",
}

MUSCLE = {
    "epimysium": "Epimysium: dense connective tissue sheath around the whole muscle, continuous with tendon and "
                 "deep fascia.",
    "perimysium": "Perimysium: connective tissue around each fascicle carrying larger vessels and nerves. Muscle "
                  "spindles lie within it. Inflamed in dermatomyositis (perifascicular atrophy).",
    "endomysium": "Endomysium: delicate reticular fibres and basal lamina around each fibre with capillaries. "
                  "Inflamed in polymyositis.",
    "fibers": "Muscle fibres (cells): multinucleated syncytia up to several cm long and 10–100 µm wide, packed with "
              "myofibrils; nuclei lie at the periphery.",
    "myofibrils": "Myofibrils: chains of sarcomeres (A and I bands, Z discs) made of actin and myosin filaments; "
                  "their alignment produces cross-striations. Dystrophin anchors them to the membrane (absent in "
                  "Duchenne dystrophy).",
    "nuclei": "Peripheral myonuclei beneath the sarcolemma; satellite cells nearby repair damage.",
    "cap": "Capillaries in the endomysium: type I (slow oxidative) fibres have the richest capillary supply.",
    "nerve": "Motor nerve branch: axons of alpha motor neurons; one neuron and all the fibres it supplies form a "
             "motor unit.",
    "nmj": "Neuromuscular junction (motor end plate): acetylcholine release onto nicotinic receptors in junctional "
           "folds. Antibodies against these receptors cause myasthenia gravis; against presynaptic Ca²⁺ channels, "
           "Lambert–Eaton syndrome.",
    "spindle": "Muscle spindle: encapsulated stretch receptor of intrafusal fibres wrapped by Ia sensory endings, "
               "mediating the stretch reflex.",
    "fascicle": "Fascicles: bundles of muscle fibres visible to the naked eye as the grain of meat.",
}

NEPH = {
    "glom": "Glomerular capillaries: fenestrated capillary tuft filtering ~180 L of plasma per day. The filtration "
            "barrier is endothelium, glomerular basement membrane and podocyte slit diaphragms (nephrin).",
    "bowman": "Bowman capsule (parietal layer): simple squamous epithelium enclosing the urinary space. Crescents "
              "form here in rapidly progressive glomerulonephritis.",
    "podocytes": "Podocytes (visceral layer): foot processes interdigitate around capillaries. Effacement causes "
                 "nephrotic syndrome (minimal change disease).",
    "aff": "Afferent arteriole: brings blood to the glomerulus; constricted by NSAID loss of prostaglandins.",
    "eff": "Efferent arteriole: drains the glomerulus; constricted by angiotensin II to maintain GFR (ACE "
           "inhibitors dilate it).",
    "jg": "Juxtaglomerular cells: modified smooth muscle of the afferent arteriole secreting renin when perfusion "
          "falls.",
    "md": "Macula densa: tall crowded cells of the distal tubule sensing NaCl delivery (tubuloglomerular feedback).",
    "pct": "Proximal convoluted tubule: cuboidal cells with a brush border reabsorbing ~65% of filtered Na⁺ and "
           "water, all glucose and amino acids. Most vulnerable to ischaemic acute tubular necrosis.",
    "thin_desc": "Thin descending limb: permeable to water, not solutes – concentrates tubular fluid.",
    "thin_asc": "Thin ascending limb: impermeable to water, passively loses NaCl.",
    "tal": "Thick ascending limb: Na⁺-K⁺-2Cl⁻ cotransporter (blocked by loop diuretics) – the 'diluting segment'.",
    "dct": "Distal convoluted tubule: Na⁺-Cl⁻ cotransporter (thiazide target) and PTH-regulated Ca²⁺ reabsorption.",
    "cd": "Collecting duct: principal cells (ENaC, aquaporin-2 under ADH) and intercalated cells (acid–base).",
    "ptc": "Peritubular capillaries: continue from the efferent arteriole to reclaim reabsorbed fluid.",
    "vr": "Vasa recta: hairpin capillaries of juxtamedullary nephrons preserving the medullary osmotic gradient.",
    "cortex": "Renal cortex interstitium.",
    "medulla": "Renal medulla interstitium (hyperosmotic).",
}

LIVER = {
    "cv": "Central vein: drains sinusoidal blood toward the hepatic veins. Zone 3 around it suffers first in "
          "hypoxia, right heart failure ('nutmeg liver') and paracetamol toxicity.",
    "z1": "Zone 1 (periportal) hepatocytes: receive the most oxygenated blood; main site of gluconeogenesis and "
          "oxidative metabolism; first affected by viral hepatitis and some toxins (e.g. cocaine).",
    "z2": "Zone 2 (midzonal) hepatocytes: intermediate oxygen supply; affected in yellow fever.",
    "z3": "Zone 3 (centrilobular) hepatocytes: least oxygen, richest in cytochrome P450 – site of drug metabolism, "
          "alcoholic steatosis and ischaemic necrosis.",
    "pv": "Portal venule: branch of the portal vein delivering nutrient-rich blood from the gut (~75% of hepatic "
          "blood flow).",
    "ha": "Hepatic arteriole: oxygenated blood (~25% of flow) mixing with portal blood in the sinusoids.",
    "bd": "Bile ductule: cuboidal epithelium carrying bile toward the hilum, opposite to blood flow. Ductular "
          "proliferation occurs in biliary obstruction.",
    "triad": "Portal tract connective tissue: surrounds the triad; the limiting plate of hepatocytes around it is "
             "breached in interface hepatitis.",
    "kupffer": "Kupffer cells: resident macrophages in the sinusoids clearing bacteria, endotoxin and old "
               "erythrocytes.",
    "stellate": "Hepatic stellate (Ito) cells: store vitamin A in the space of Disse; when activated they become "
                "myofibroblasts laying down collagen in cirrhosis.",
    "canaliculi": "Bile canaliculi: tiny channels between adjacent hepatocytes sealed by tight junctions, draining to "
                  "the canals of Hering at the portal tract.",
    "septa": "Interlobular connective tissue: delicate in humans (prominent in pig liver), outlining the classic "
             "hexagonal lobule.",
}

NERVE = {
    "epineurium": "Epineurium: dense irregular connective tissue with fat and vessels binding fascicles into a nerve; "
                  "it is sutured in nerve repair.",
    "perineurium": "Perineurium: concentric layers of flattened perineurial cells joined by tight junctions – the "
                   "blood–nerve barrier.",
    "endoneurium": "Endoneurium: loose connective tissue around individual fibres; axonal regrowth follows endoneurial "
                   "tubes at ~1 mm/day after injury.",
    "myelin": "Myelin sheath: spiral wraps of Schwann cell membrane (one Schwann cell per internode) speeding "
              "conduction. Attacked in Guillain–Barré syndrome.",
    "axon": "Axon: the conducting process; in myelinated fibres ion channels cluster at the nodes.",
    "node": "Nodes of Ranvier: unmyelinated gaps rich in voltage-gated Na⁺ channels allowing saltatory conduction.",
    "unmyelinated": "Unmyelinated C fibres: several thin axons embedded in one Schwann cell (Remak bundle) – slow "
                    "pain, temperature and postganglionic autonomic fibres.",
    "schwann": "Schwann cell nuclei: elongated nuclei at the edge of the myelin sheath.",
    "vasa": "Vasa nervorum: vessels in the epineurium; their occlusion in diabetes causes ischaemic mononeuropathy.",
    "fat": "Epineurial adipocytes cushioning the fascicles.",
}
