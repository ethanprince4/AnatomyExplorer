from .anim import AnimatedModel
from .base import MicroModel
from .pancreas import build_pancreas, pancreas_animation
from .tissues import build_cardiac


def register_all(register):
    register(MicroModel(
        "cardiac_muscle", "Cardiac muscle (ventricular wall)",
        "A transmural block of ventricular wall: branching, striated cardiomyocytes with central nuclei joined by "
        "stepped intercalated discs, in laminae whose direction turns through the wall, with a capillary-rich "
        "endomysium. Purkinje fibres lie beneath the endocardium; the epicardium carries fat, a coronary artery, a "
        "cardiac vein and an autonomic nerve. At one end the fibres are teased apart at their discs.",
        build_cardiac,
        targets={"groups": ["Heart"],
                 "structures": ["Left ventricle", "Right ventricle", "Left atrium", "Right atrium"],
                 "contains": ["papillary muscle"]},
        histology=["cardiac_muscle", "heart_valve", "serosa", "adipose"],
        related=["skeletal_muscle", "muscular_artery", "elastic_artery"],
        clinical=[("Myocardial infarction & troponin",
                   "Occlusion of an epicardial coronary artery by thrombus on a ruptured plaque kills myocytes from "
                   "the subendocardium outwards (the wavefront). Leaked cardiac troponin I/T rises from ~3 h and "
                   "stays up for 7–10 days. Histology: wavy fibres and contraction bands in hours, coagulative "
                   "necrosis with neutrophils at 1–3 days, macrophages at 3–7 days (the weakest wall – rupture "
                   "risk), granulation tissue and then a collagen scar by 2 months. Myocytes do not regenerate."),
                  ("Hypertrophic cardiomyopathy",
                   "Autosomal dominant sarcomere mutations (β-myosin heavy chain, myosin-binding protein C) give "
                   "asymmetric septal hypertrophy with myocyte disarray – fibres and myofibrils in a whorled, "
                   "haphazard pattern instead of parallel laminae – and interstitial fibrosis. The disarray is an "
                   "arrhythmic substrate: the commonest cause of sudden cardiac death in young athletes."),
                  ("Hypertrophy vs dilatation",
                   "Pressure overload (hypertension, aortic stenosis) adds sarcomeres in parallel – wider cells, "
                   "concentric hypertrophy, enlarged 'boxcar' nuclei. Volume overload adds them in series – longer "
                   "cells and eccentric hypertrophy. Capillary numbers do not keep pace, so hypertrophied "
                   "subendocardium is prone to ischaemia."),
                  ("Myocarditis & arrhythmogenic cardiomyopathy",
                   "Viral (coxsackie B) myocarditis shows lymphocytes with myocyte necrosis. In arrhythmogenic "
                   "(right ventricular) cardiomyopathy, mutations in desmosomal proteins of the intercalated disc "
                   "(plakophilin-2) let myocytes detach and be replaced by fat and fibrous tissue."),
                  ("Conduction system",
                   "The Purkinje network runs in the subendocardium, so subendocardial ischaemia or fibrosis causes "
                   "bundle branch block; ventricular fibrillation after infarction often starts from surviving "
                   "Purkinje fibres at the border zone.")],
        scale_note="Block ≈ 0.5 mm wide; the wall is compressed – the real left ventricle is ≈ 10 mm thick and "
                   "cardiomyocytes ≈ 100 × 15 µm."))
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
