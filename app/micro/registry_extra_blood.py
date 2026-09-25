"""Blood: the formed elements in plasma, as on a Wright-stained smear."""
from .base import MicroModel
from .blood import K, build_blood


def register_all(register):
    m = MicroModel(
        "blood_cells", "Blood: formed elements",
        "A thin sheet of plasma, a few cells deep like the feathered edge of a smear, with every formed element drawn "
        "to scale and coloured as with Wright's stain. Along the front edge one of each white cell is lined up in "
        "order of abundance (neutrophil, small and large lymphocyte, monocyte, eosinophil, basophil) and cut open at "
        "its equator to show the nucleus and granules; more lie scattered among the biconcave red cells behind, with "
        "a band neutrophil, a rouleau, a red cell cut through its middle, resting platelets and, in the back corner, "
        "an early clot of fibrin with activated platelets and trapped red cells.",
        build_blood,
        targets={"structures": ["Heart", "Spleen", "Ascending aorta", "Superior vena cava", "Inferior vena cava"],
                 "groups": ["Heart"]},
        histology=["blood", "bone_marrow", "spleen"], related=["spleen", "lymph_node"],
        clinical=[("Anaemia",
                   "A low haemoglobin, classified by red-cell size (MCV). Microcytic, hypochromic cells with wide "
                   "central pallor and pencil cells: iron deficiency (blood loss, poor intake) or thalassaemia. "
                   "Macrocytic cells with hypersegmented neutrophils: vitamin B12 (pernicious anaemia) or folate "
                   "deficiency. Normocytic: acute bleeding, chronic disease, kidney failure (low erythropoietin), "
                   "marrow failure or haemolysis (raised reticulocytes, bilirubin and LDH). Symptoms: fatigue, "
                   "breathlessness, pallor, tachycardia."),
                  ("Sickle cell disease",
                   "Homozygous HbS (Glu6Val in beta-globin) polymerises when deoxygenated, turning red cells into "
                   "rigid sickles that block small vessels (painful vaso-occlusive crises, acute chest syndrome, "
                   "stroke, splenic infarction and autosplenectomy - hence infection with encapsulated bacteria) "
                   "and are destroyed early (haemolytic anaemia, red-cell life ~20 days). The heterozygous trait "
                   "protects against falciparum malaria. Hydroxycarbamide raises fetal haemoglobin, which does not "
                   "sickle."),
                  ("Neutrophilia vs lymphocytosis",
                   "The differential count (100 white cells, normally Neutrophils > Lymphocytes > Monocytes > "
                   "Eosinophils > Basophils) points to the cause. Neutrophilia with a left shift (band forms, toxic "
                   "granulation) suggests acute bacterial infection, e.g. appendicitis or pneumonia, or steroids and "
                   "tissue necrosis. Lymphocytosis suggests viral infection (atypical reactive lymphocytes in "
                   "glandular fever), pertussis or, in an older adult with smudge cells, chronic lymphocytic "
                   "leukaemia. Monocytosis points to chronic infection such as tuberculosis."),
                  ("Eosinophilia",
                   "Raised eosinophils (above ~0.5 x 10^9/L): in the UK most often allergy - asthma, hay fever, "
                   "eczema, drug reactions; worldwide, helminth infection (Strongyloides, schistosomiasis, "
                   "hookworm, trichinosis). Also Addison disease, Hodgkin lymphoma, eosinophilic granulomatosis "
                   "with polyangiitis and hypereosinophilic syndrome, where eosinophil granule proteins damage the "
                   "heart (endomyocardial fibrosis)."),
                  ("Thrombocytopenia",
                   "Platelets below 150 x 10^9/L; spontaneous bleeding usually only below ~20. Petechiae, purpura, "
                   "nosebleeds and gum bleeding (platelet-type bleeding) rather than the joint and muscle bleeds of "
                   "haemophilia. Causes: reduced production (marrow failure, leukaemia, chemotherapy, B12/folate "
                   "deficiency, alcohol), increased destruction (immune thrombocytopenia, heparin-induced "
                   "thrombocytopenia, DIC, TTP) or pooling in a big spleen. Check the film for clumping, which "
                   "gives a falsely low count."),
                  ("Leukaemia",
                   "Clonal proliferation of white-cell precursors that crowds out the marrow: anaemia, infections "
                   "(no working neutrophils) and bleeding (thrombocytopenia). Acute leukaemias flood the blood with "
                   "blasts - ALL in children, AML in adults (Auer rods). Chronic myeloid leukaemia (BCR-ABL, "
                   "Philadelphia chromosome) gives a huge white count of neutrophils at all stages with basophilia "
                   "and splenomegaly and responds to imatinib; chronic lymphocytic leukaemia gives a lymphocytosis "
                   "of small mature-looking B cells with smudge cells.")],
        scale_note="Field ≈ 97 × 77 µm, all cells to true scale (red cell 7.5 µm); granules slightly enlarged. "
                   "White cells are cut open at their equator; far more white cells than in real blood (~1 per "
                   "600 red cells).")
    m.metres_per_unit = 1e-6 / K          # measuring tool reads true micrometres
    m.cut_on = False                      # the white cells are their own cut-away
    m.home_view = (-0.22, 0.80)
    register(m)
