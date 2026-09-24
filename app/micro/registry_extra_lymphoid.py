"""Secondary lymphoid organs: a whole lymph node and a block of spleen."""
from .base import MicroModel
from .lymphoid import build_lymph_node, build_spleen


def register_all(register):
    register(MicroModel(
        "lymph_node", "Lymph node",
        "A whole lymph node cut through its hilum: afferent lymphatics with valves pierce the capsule and empty into "
        "the subcapsular sinus; trabeculae and trabecular sinuses cross the outer cortex with its primary and "
        "secondary follicles (mantle zone, germinal centre light and dark zones); the paracortex holds high "
        "endothelial venules; medullary cords alternate with medullary sinuses crossed by reticular fibres and "
        "macrophages; artery, vein and the efferent lymphatic meet at the hilum.",
        build_lymph_node, targets={"groups": ["Lymph nodes"], "categories": ["lymph"]},
        histology=["lymph_node", "tonsil"], related=["spleen", "ileum"],
        clinical=[("Reactive lymphadenopathy",
                   "Each compartment enlarges for a different stimulus: follicular hyperplasia (many large germinal "
                   "centres) in bacterial infection, rheumatoid arthritis and early HIV; paracortical hyperplasia in "
                   "viral infection (EBV) and after vaccination; sinus histiocytosis in nodes draining a tumour or "
                   "an inflamed site. Reactive nodes are tender, mobile and usually under 1 cm; hard, fixed, painless "
                   "or supraclavicular nodes need a biopsy."),
                  ("Lymphoma",
                   "Follicular lymphoma (t(14;18), BCL2 keeps centrocytes alive) packs the node with back-to-back "
                   "follicles that lack polarity and tingible-body macrophages. Mantle cell lymphoma (t(11;14), "
                   "cyclin D1) expands the mantle zone; Burkitt lymphoma (MYC) is a germinal-centre tumour with a "
                   "'starry sky'. Hodgkin lymphoma effaces the architecture with a few Reed-Sternberg cells (CD15, "
                   "CD30) in a reactive background."),
                  ("Metastasis & the sentinel node",
                   "Carcinoma spreads through the afferent lymphatics and lodges first in the subcapsular sinus. The "
                   "sentinel node - the first node to receive lymph from a tumour, found with blue dye or a "
                   "radiotracer - is removed and examined; if it is clear, a full axillary (breast) or regional "
                   "(melanoma) dissection and its lymphoedema can be avoided. Virchow's node (left supraclavicular) "
                   "signals abdominal cancer via the thoracic duct."),
                  ("Lymphadenitis patterns",
                   "Caseating granulomas point to tuberculosis (scrofula of cervical nodes); stellate necrotising "
                   "granulomas to cat-scratch disease (Bartonella); follicular hyperplasia with monocytoid B cells "
                   "to toxoplasmosis. Anthracotic pigment in hilar nodes and tattoo pigment in axillary nodes are "
                   "harmless macrophage cargo.")],
        scale_note="Node ≈ 1 cm long; follicles 0.5-1 mm. Vessel and cell sizes exaggerated for clarity."))
    register(MicroModel(
        "spleen", "Spleen: white and red pulp",
        "A block of spleen under its capsule: a trabecula carries the trabecular artery and vein; the central artery "
        "runs in a periarteriolar lymphoid sheath with follicles and germinal centres (white pulp), ringed by the "
        "marginal sinus and marginal zone; beyond it penicillar arterioles with sheathed capillaries open into the "
        "red pulp, where splenic cords of Billroth lie between venous sinusoids of stave cells hooped by ring "
        "fibres, draining to a pulp vein.",
        build_spleen, targets={"structures": ["Spleen"]},
        histology=["spleen", "lymph_node", "blood"], related=["lymph_node", "liver_lobule"],
        clinical=[("Splenic rupture",
                   "The spleen is the organ most often injured in blunt abdominal trauma (lower left rib fractures). "
                   "Its thin capsule and pulpy, blood-filled parenchyma bleed briskly; pain may be referred to the "
                   "left shoulder (Kehr sign) through the phrenic nerve. A subcapsular haematoma can rupture days "
                   "later, and an enlarged spleen in infectious mononucleosis can rupture with minor trauma - hence "
                   "no contact sport for several weeks."),
                  ("Asplenia & encapsulated organisms",
                   "Without the marginal zone's IgM memory B cells and cord macrophages, opsonin-poor encapsulated "
                   "bacteria (Streptococcus pneumoniae, Haemophilus influenzae type b, Neisseria meningitidis) cause "
                   "overwhelming post-splenectomy sepsis. Patients are vaccinated (ideally 2 weeks before elective "
                   "splenectomy), may take prophylactic penicillin and need urgent antibiotics for any fever. "
                   "Sickle cell disease causes functional asplenia through repeated infarction (autosplenectomy)."),
                  ("Hypersplenism & haemolysis",
                   "Red cells that cannot deform through the sinusoid slits - spherocytes in hereditary "
                   "spherocytosis, IgG-coated cells in warm autoimmune haemolysis - are trapped in the cords and "
                   "destroyed (extravascular haemolysis, splenomegaly); splenectomy cures the anaemia. A big spleen "
                   "from any cause (portal hypertension, myelofibrosis, malaria, leukaemia) pools and destroys cells, "
                   "causing pancytopenia."),
                  ("Blood film after splenectomy",
                   "Howell-Jolly bodies (nuclear remnants), target cells, Heinz bodies and Pappenheimer bodies "
                   "appear because cord macrophages no longer pit inclusions from passing red cells; platelets rise "
                   "transiently."),
                  ("Splenic infarct",
                   "Splenic artery branches are end arteries, so emboli (endocarditis, atrial fibrillation) or "
                   "sickling cause pale, wedge-shaped subcapsular infarcts with left upper quadrant pain.")],
        scale_note="Block ≈ 1.5 mm wide; white pulp nodules 0.2-0.8 mm. Sinusoids and arterioles exaggerated."))
