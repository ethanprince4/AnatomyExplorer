"""Gross anatomy of the kidney: a whole right kidney opened in coronal section."""
from .base import MicroModel
from .kidney_gross import build_kidney_section


def register_all(register):
    m = MicroModel(
        "kidney_section", "Kidney: coronal section",
        "A right kidney bisected in the frontal plane, as in the dissection room, with its coverings: renal fascia, "
        "perirenal fat and the fibrous capsule. The cut face shows the granular cortex, the renal columns dipping "
        "between striated renal pyramids, medullary rays, and papillae cupped by minor calyces that join into "
        "major calyces, the renal pelvis and the ureter. The renal sinus fat surrounds them and opens at the hilum "
        "(vein, artery, pelvis). Blood runs renal → segmental → interlobar (in the columns) → arcuate (over the "
        "pyramid bases) → cortical radiate arteries, with companion veins. A window in one lobe shows where a "
        "nephron and its collecting duct lie. The suprarenal gland caps the upper pole.",
        build_kidney_section,
        targets={"structures": ["Kidney", "Renal pelvis", "Renal sinus", "Hilum of kidney", "Ureter",
                                "Right renal artery", "Left renal artery", "Right renal vein", "Left renal vein",
                                "Intrarenal arteries of right kidney", "Intrarenal arteries of left kidney",
                                "Intrarenal veins of right kidney", "Intrarenal veins of left kidney",
                                "Anterior branch of renal artery", "Posterior branch of renal artery"]},
        histology=["kidney_cortex", "kidney_medulla", "ureter", "adrenal"],
        related=["kidney_nephron", "bladder_wall"],
        # one frontal cut: both planes remove z > 0, so the whole anterior half comes away
        cutaway=((0.0, 0.0, -1.0), (0.0, 0.0, 1.0)), cut_at=(0.0, 0.0),
        clinical=[
            ("Kidney stones & staghorn calculi",
             "Most stones are calcium oxalate, seeded on Randall plaques at the papillae; others are calcium "
             "phosphate, uric acid (radiolucent), cystine, and struvite (magnesium ammonium phosphate) formed in "
             "alkaline urine infected by urease-splitting bacteria such as Proteus. Struvite grows into a staghorn "
             "calculus that casts the renal pelvis and branches into the calyces; it needs complete removal "
             "(percutaneous nephrolithotomy) because the bacteria live in it. A small stone passing down the "
             "ureter impacts at the pelviureteric junction, the pelvic brim or the vesicoureteric junction, causing "
             "colic from loin to groin with haematuria; an obstructed infected kidney is an emergency (drain it)."),
            ("Pyelonephritis",
             "Usually an ascending infection (E. coli) from the bladder, helped by vesicoureteric reflux, "
             "obstruction, pregnancy or a catheter: fever, loin pain and costovertebral-angle tenderness from the "
             "stretched capsule, with white-cell casts in the urine. Bacteria climb the collecting ducts from the "
             "papillae, so the polar compound papillae, whose ducts open widely, are most exposed and chronic "
             "reflux scars the poles (coarse cortical scars over blunted, clubbed calyces)."),
            ("Hydronephrosis",
             "Dilatation of the pelvis and calyces behind an obstruction - pelviureteric junction obstruction "
             "(often congenital, or a crossing lower-pole vessel), a stone, tumour, pregnancy or an enlarged "
             "prostate. The calyces lose their cupped shape and become clubbed, the papillae flatten and, if it "
             "lasts, the pressure thins the medulla and then the cortex to a rim. Ultrasound shows a fluid-filled "
             "sinus; relief within days to weeks usually saves function."),
            ("Renal cell carcinoma",
             "Arises from proximal tubule epithelium in the cortex (clear cell type: VHL loss; smoking, obesity, "
             "von Hippel-Lindau disease). Classic triad of haematuria, flank pain and mass is late; many are found "
             "by chance on imaging. It is staged by its spread through the coverings shown here: confined to the "
             "kidney (T1-T2), into sinus or perirenal fat or the renal vein (T3a) - it grows along the vein into the "
             "vena cava (T3b-c) - and through the renal fascia (T4). Paraneoplastic effects: erythropoietin "
             "(polycythaemia), PTHrP (hypercalcaemia), renin."),
            ("Polycystic kidney disease",
             "Autosomal dominant PKD (PKD1/polycystin-1, PKD2) grows cysts from every part of the nephron and "
             "collecting duct, so both kidneys enlarge massively and the normal pattern of cortex, pyramids and "
             "calyces seen here is replaced by cysts; kidney failure usually by middle age, with hypertension, "
             "flank pain, haematuria, liver cysts and berry aneurysms. Autosomal recessive PKD dilates the "
             "collecting ducts radially in infancy. Simple cortical cysts, by contrast, are common and harmless."),
            ("Renal infarction and papillary necrosis",
             "Segmental and arcuate arteries are end arteries: an embolus (atrial fibrillation, endocarditis) gives a "
             "pale wedge-shaped infarct with its base on the capsule. The papillae, at the end of the vasa recta, "
             "are the most vulnerable tissue - papillary necrosis in analgesic abuse, diabetes, sickle cell "
             "disease and obstructed infection."),
        ],
        scale_note="Kidney ≈ 11 cm long, 6 cm wide, 3-4 cm thick. The capsule, fascia and calyx walls are drawn "
                   "thicker, and the nephron in the window many times larger, than life.")
    m.home_view = (0.30, 0.16)
    m.metres_per_unit = 0.05                  # 1 model unit = 5 cm
    register(m)
