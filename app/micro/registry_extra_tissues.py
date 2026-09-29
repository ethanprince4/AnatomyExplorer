from .anim import AnimatedModel
from .pancreas import build_pancreas, pancreas_animation


def register_all(register):
    register(AnimatedModel(
        "pancreas", "Pancreas (acini & islets)",
        "Lobules of serous acini separated by connective tissue septa. Each acinus is a cluster of pyramidal cells "
        "with basophilic bases and apical zymogen granules around a lumen with pale centroacinar cells. "
        "Intercalated ducts drain to intralobular ducts and an interlobular duct with its artery and vein in a "
        "septum. Pale, richly capillarised islets of Langerhans sit among the acini: beta cells in the core, alpha "
        "cells in the mantle, scattered delta cells. Play the secretion cycle to watch zymogen granules fuse with the "
        "apical membrane, pancreatic juice run down the ducts and the beta cells release insulin.",
        build_pancreas,
        animation=pancreas_animation(),
        targets={"structures": ["Pancreas", "Head of pancreas", "Neck of pancreas", "Body of pancreas",
                                "Tail of pancreas", "Uncinate process of pancreas", "Pancreatic duct",
                                "Accessory pancreatic duct"]},
        histology=["pancreas", "islets", "parotid"],
        related=["liver_lobule", "duodenum"],
        clinical=[("Acute pancreatitis",
                   "Gallstones and alcohol (also hypertriglyceridaemia, hypercalcaemia, ERCP, drugs) cause "
                   "premature activation of trypsinogen inside acinar cells; trypsin activates the other enzymes "
                   "and the gland digests itself – fat necrosis with calcium soaps (hypocalcaemia), haemorrhage and "
                   "SIRS. Serum lipase > 3× normal; epigastric pain radiating to the back."),
                  ("Type 1 vs type 2 diabetes",
                   "Type 1: T-cell-mediated destruction of beta cells (insulitis; antibodies to GAD65, insulin, "
                   "IA-2, ZnT8) – absolute insulin deficiency, ketoacidosis. Type 2: insulin resistance with "
                   "progressive beta-cell failure; islets contain amyloid (amylin/IAPP) deposits. Alpha cells are "
                   "spared in both, and unopposed glucagon worsens hyperglycaemia."),
                  ("Cystic fibrosis",
                   "Defective CFTR in the centroacinar and duct cells stops chloride and bicarbonate secretion, so "
                   "the enzyme-rich secretion stays thick, plugs the ducts and destroys the acini: fibrosis and "
                   "cysts, fat malabsorption (steatorrhoea, fat-soluble vitamin deficiency) and later CF-related "
                   "diabetes as the islets are engulfed."),
                  ("Chronic pancreatitis",
                   "Repeated injury (mainly alcohol) replaces acini with fibrosis and calcified duct stones while "
                   "islets survive longest – exocrine failure (steatorrhoea) precedes endocrine failure (diabetes)."),
                  ("Pancreatic tumours",
                   "Ductal adenocarcinoma arises from duct epithelium (usually the head – painless obstructive "
                   "jaundice, Courvoisier sign; CA19-9). Neuroendocrine tumours arise from islet cells: insulinoma "
                   "(Whipple triad), gastrinoma (Zollinger–Ellison), glucagonoma (necrolytic migratory erythema), "
                   "somatostatinoma, VIPoma (watery diarrhoea).")],
        scale_note="Block ≈ 1 mm wide; acini ≈ 80 µm and islets ≈ 150 µm across. A lobule is larger than the block."))
