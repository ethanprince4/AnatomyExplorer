from .base import MicroModel
from .lower_gi import build_ileocecal_rectum
from .tooth import build_tooth

TEETH = ["Upper medial incisor", "Upper lateral incisor", "Upper canine", "Upper first premolar",
         "Upper second premolar", "Upper first molar tooth", "Upper second molar tooth", "Lower medial incisor",
         "Lower lateral incisor", "Lower canine", "Lower first premolar", "Lower second premolar",
         "Lower first molar tooth", "Lower second molar tooth"]


def register_all(register):
    m = MicroModel(
        "ileocecal_rectum", "Ileocecal region, rectum & anal canal",
        "Two opened specimens at dissection scale. Left: the caecum opened through a window in its front wall, "
        "showing the terminal ileum entering through the lips and frenula of the ileocaecal valve, the orifice of "
        "the vermiform appendix below it, semilunar folds, and outside the three taeniae coli converging on the "
        "appendix base, haustra and omental appendices; the appendix is laid open lengthwise to show its lymphoid "
        "follicles, with its mesoappendix and appendicular artery. Right: the posterior half of a coronal section "
        "of the rectum and anal canal – transverse rectal folds, ampulla, anorectal junction, anal columns, valves "
        "and sinuses on the pectinate line, anal pecten and skin, the smooth internal and skeletal external "
        "sphincters, puborectalis and levator ani, the internal and external venous plexuses, mesorectum and "
        "ischioanal fossa.",
        build_ileocecal_rectum,
        targets={"structures": ["Vermiform appendix", "Meso-appendix", "Appendicular artery", "Appendicular nodes",
                                "Ascending colon", "Free taenia", "Mesocolic taenia", "Omental taenia",
                                "Precaecal nodes", "Retrocaecal nodes", "External anal sphincter", "Anal region",
                                "Levator ani", "Tendinous arch of levator ani", "Pubo-analis muscle",
                                "Superior anorectal artery"]},
        histology=["colon", "appendix", "anal_canal", "ileum"],
        related=["colon_wall", "ileum"],
        clinical=[
            ("Appendicitis & McBurney's point",
             "Obstruction of the appendix lumen (faecolith, lymphoid hyperplasia) leads to distension, ischaemia "
             "and bacterial invasion. Visceral pain is first felt around the umbilicus (T10), then localises to the "
             "right iliac fossa once the parietal peritoneum is irritated, with maximal tenderness at McBurney's "
             "point – one-third of the way along the line from the right anterior superior iliac spine to the "
             "umbilicus, over the constant appendix base. A retrocaecal appendix gives a positive psoas sign, a "
             "pelvic one an obturator sign and rectal tenderness. The appendicular artery is an end artery, so "
             "gangrene and perforation (peritonitis, appendix mass or abscess) follow if treatment is delayed."),
            ("Haemorrhoids",
             "Enlarged, prolapsing anal cushions of the internal rectal venous plexus (at 3, 7 and 11 o'clock). "
             "Internal haemorrhoids arise above the pectinate line: painless, bright red bleeding on the paper and "
             "in the pan, graded I–IV by prolapse (rubber-band ligation, haemorrhoidectomy). External haemorrhoids "
             "lie below it under somatically innervated skin, so a thrombosed one is exquisitely painful. Risk "
             "factors: straining, constipation, pregnancy. Rectal varices of portal hypertension are distinct."),
            ("Anal fissure",
             "A longitudinal tear in the anoderm below the pectinate line, usually posterior midline, from passing "
             "hard stool: tearing pain on defecation and fresh blood. Chronic fissures (sentinel pile, exposed "
             "internal sphincter fibres) persist because internal sphincter spasm makes the posterior anoderm "
             "ischaemic – relaxed with topical GTN or diltiazem, botulinum toxin, or lateral internal "
             "sphincterotomy. Off-midline fissures suggest Crohn's disease, HIV, syphilis or carcinoma."),
            ("Colorectal cancer",
             "Adenocarcinoma arising from adenomatous polyps (adenoma–carcinoma sequence), or through mismatch-repair "
             "deficiency (Lynch syndrome). Right-sided (caecal) tumours present late with iron-deficiency anaemia; "
             "left-sided and rectal ones with altered bowel habit, bleeding, tenesmus and obstruction. Staged by "
             "depth through the wall (T), nodes (N) and metastases (M, liver first via the portal system). Rectal "
             "cancer is treated by total mesorectal excision, with preoperative chemoradiotherapy when MRI shows a "
             "threatened mesorectal fascia; screening by faecal immunochemical test and colonoscopy."),
            ("Anorectal abscess & fistula",
             "Infection of the anal glands that open into the anal sinuses spreads into the intersphincteric plane "
             "and then to the perianal skin, the ischioanal fossa (possibly round the back as a horseshoe abscess) "
             "or above levator ani. A fistula-in-ano is the track left between the sinus and the skin; its course "
             "relative to the external sphincter decides how much muscle may safely be divided."),
            ("Ileocaecal region at colonoscopy & in obstruction",
             "The caecum is recognised by the ileocaecal valve, the appendiceal orifice and the converging taeniae. "
             "In distal large-bowel obstruction a competent ileocaecal valve creates a closed loop: the thin-walled "
             "caecum distends most and may perforate. Crohn's disease favours the terminal ileum and caecum.")],
        scale_note="Gross specimens: 1 unit ≈ 6 cm (caecum ≈ 7.5 cm wide, anal canal ≈ 4 cm long). Wall coats are "
                   "drawn about 1.5× their true thickness so each layer reads in section.")
    m.cut_on = False                      # both specimens are already opened
    m.home_view = (0.35, 0.22)
    m.metres_per_unit = 0.06
    register(m)

    t = MicroModel(
        "tooth", "Tooth structure",
        "A lower first molar cut in the mesiodistal plane in its socket: crown, neck and two roots; enamel, "
        "dentin, the pulp chamber with its pulp horns and the root canals opening at the apical foramina, cementum, "
        "the periodontal ligament, the alveolar bone proper and the cortical and spongy bone of the mandible, "
        "with the gingiva and its sulcus. The inferior alveolar nerve, artery and vein run in the mandibular "
        "canal and send branches through each apical foramen into the pulp. Beside it, the four adult tooth "
        "types. Adult (permanent) dentition: 32 teeth, dental formula per quadrant I2 C1 P2 M3; deciduous "
        "(primary, milk) dentition: 20 teeth, I2 C1 M2 – no premolars. Deciduous teeth erupt from ~6 months "
        "(lower central incisors) to ~2 years (second molars) and are shed from ~6 to 12 years; permanent teeth "
        "erupt from ~6 years (first molars) to 17–21 years (third molars, wisdom teeth).",
        build_tooth,
        targets={"groups": ["Teeth"], "structures": TEETH + ["Gingiva"],
                 "contains": ["molar tooth", "incisor", "canine", "premolar"]},
        histology=["tooth", "oral_mucosa", "compact_bone", "spongy_bone"],
        related=["compact_bone", "tongue_papillae"],
        clinical=[
            ("Dental caries",
             "Plaque bacteria (Streptococcus mutans, lactobacilli) ferment dietary sugars to acid that "
             "demineralises enamel below pH ~5.5 – first a chalky white spot, then a cavity. Enamel has no cells "
             "and cannot repair itself; once decay reaches dentin it spreads sideways along the "
             "dentinoenamel junction and down the dentinal tubules (sensitivity to cold and sweet). Fluoride "
             "(fluorapatite), fissure sealants, diet and brushing prevent it; restorations replace lost tissue."),
            ("Pulpitis & periapical abscess",
             "When caries or trauma reaches the pulp it becomes inflamed; because the pulp is enclosed in rigid "
             "dentin with only a narrow apical foramen for its vessels, swelling strangles its own blood supply. "
             "Reversible pulpitis gives brief pain to stimuli; irreversible pulpitis gives lingering, throbbing "
             "pain, and the pulp dies. Infection then leaves through the apical foramen as a periapical abscess "
             "(tender to bite, loss of the lamina dura on X-ray) and can spread through bone into the face or neck "
             "(Ludwig's angina from lower molars). Treated by root canal therapy or extraction."),
            ("Gingivitis & periodontal disease",
             "Plaque at the gingival margin causes gingivitis – red, swollen gums that bleed on brushing, fully "
             "reversible. In periodontitis the junctional epithelium migrates down the root, the sulcus deepens "
             "into a periodontal pocket, and the periodontal ligament and alveolar bone are destroyed: gum "
             "recession, tooth mobility and eventual tooth loss. It is the main cause of tooth loss in adults and "
             "is worsened by smoking and diabetes."),
            ("Inferior alveolar nerve block",
             "Local anaesthetic injected at the mandibular foramen on the inner ramus numbs all the lower teeth on "
             "that side, and via the mental nerve the lower lip and chin. Lower third molar extraction can injure "
             "the inferior alveolar nerve where the roots lie close to the mandibular canal (numb lip), or the "
             "lingual nerve (numb tongue)."),
            ("Dental X-rays",
             "Enamel is the most radio-opaque tissue in the body, then dentin; the pulp is radiolucent. The lamina "
             "dura is a thin white line round each root, separated from it by the dark periodontal ligament space – "
             "its loss or widening at the apex marks periapical infection.")],
        scale_note="1 unit = 1 cm: the molar crown is ≈ 11 mm wide and 7.5 mm high, its roots ≈ 14 mm long. "
                   "Cementum and periodontal ligament are drawn thicker than life (≈ 0.1–0.3 mm).")
    t.cut_on = False                      # the molar is already sectioned
    t.home_view = (0.3, 0.2)
    t.metres_per_unit = 0.01
    register(t)
