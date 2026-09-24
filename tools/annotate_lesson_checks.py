"""Add a recall question to the steps of the lessons written before the runner could ask one.

Every step in the newer lessons ends with a question the learner answers before revealing the answer; this
script gives the earlier lessons the same. Keyed by lesson id and step index, and it never overwrites a check
a step already has, so it is safe to run again.

    .venv/Scripts/python.exe tools/annotate_lesson_checks.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "data" / "content"

CHECKS = {
    "neck-triangles": {
        0: ("What are the attachments of sternocleidomastoid, and what does it do?",
            "Manubrium and medial clavicle to the mastoid process; one side turns the head to the opposite side, both flex the neck."),
        1: ("Name the three contents of the carotid sheath.",
            "Common (then internal) carotid artery, internal jugular vein and the vagus nerve."),
        2: ("A firm lump in the posterior triangle of an adult. What is the first thing you must exclude?",
            "A malignant lymph node — from the head, neck or, for a supraclavicular node, the chest or abdomen."),
        3: ("Why does a thyroid swelling rise when the patient swallows?",
            "Pretracheal fascia binds the gland to the larynx, which rises during a swallow."),
    },
    "orbit": {
        1: ("Which nerve supplies the lateral rectus, and what happens when it fails?",
            "The abducens (VI) — the eye cannot abduct and the patient has horizontal diplopia worse on looking that way."),
        2: ("What does superior oblique do when the eye is adducted?",
            "It depresses it — which is how you test the trochlear nerve."),
        3: ("A down-and-out eye with ptosis and a dilated pupil. Which nerve, and why does the pupil matter?",
            "The oculomotor nerve (III). A dilated pupil suggests external compression, such as an aneurysm, rather than a medical palsy."),
    },
    "facial-nerve": {
        0: ("Through which foramen does the facial nerve leave the skull?",
            "The stylomastoid foramen."),
        1: ("Name the five terminal branches of the facial nerve.",
            "Temporal, zygomatic, buccal, marginal mandibular and cervical."),
        2: ("Which part of the face is spared in an upper motor neurone lesion, and why?",
            "The forehead — it has bilateral cortical innervation."),
    },
    "circle-of-willis": {
        1: ("Which part of the body does an anterior cerebral artery stroke affect most?",
            "The contralateral leg — its cortical territory is the medial surface of the hemisphere."),
        2: ("Why does a middle cerebral artery stroke affect the face and arm more than the leg?",
            "It supplies the lateral convexity, where the face and hand have the largest cortical representation."),
        3: ("Name three features of a posterior circulation stroke.",
            "Vertigo, diplopia, dysarthria, ataxia or visual field loss — any three."),
        4: ("Where is the commonest site of a berry aneurysm?",
            "The anterior communicating artery."),
    },
    "ventricles": {
        0: ("Which channel connects the lateral ventricle to the third?",
            "The interventricular foramen (of Monro)."),
        1: ("Where is cerebrospinal fluid produced and where is it absorbed?",
            "Produced by the choroid plexus; absorbed through the arachnoid granulations into the dural venous sinuses."),
        2: ("Which part of the ventricular system most often obstructs?",
            "The cerebral aqueduct — the narrowest point."),
    },
    "spinal-cord": {
        0: ("Where does the spinal cord end in an adult, and why is that not where the vertebral column ends?",
            "At L1/L2 — the column grows faster than the cord after the third fetal month."),
        1: ("Which space does an epidural anaesthetic go into, and what does it contain?",
            "The extradural space, containing fat and the internal vertebral venous plexus."),
        2: ("Why does a hemisection cause loss of pain on the opposite side but loss of vibration on the same side?",
            "Spinothalamic fibres cross within a segment or two of entering the cord; dorsal column fibres do not cross until the medulla."),
    },
    "knee-joint": {
        0: ("What makes the knee stable despite having two round condyles on a flat plateau?",
            "The ligaments, the menisci and the muscles — very little bony congruence."),
        1: ("Which cruciate stops the tibia sliding forwards, and which test detects its rupture?",
            "The anterior cruciate ligament; the anterior drawer and Lachman tests."),
        2: ("Why does the medial meniscus tear more often than the lateral?",
            "It is attached to the medial collateral ligament and so is less mobile."),
        3: ("Which muscle unlocks the extended knee?",
            "Popliteus, by laterally rotating the femur on the tibia."),
    },
    "shoulder-joint": {
        0: ("How much of the humeral head is in contact with the glenoid at any time?",
            "About a third."),
        1: ("In which direction does the shoulder usually dislocate, and which nerve must you test?",
            "Anteroinferiorly; test the axillary nerve."),
        2: ("What is the scapulohumeral rhythm?",
            "About 2° of glenohumeral movement for every 1° of scapular rotation."),
    },
    "hip-joint": {
        0: ("Which is the strongest ligament in the body, and what does it prevent?",
            "The iliofemoral ligament — it prevents hyperextension and lets you stand without muscular effort."),
        1: ("Why does an intracapsular femoral neck fracture threaten the head?",
            "It tears the retinacular vessels that run up the neck from the medial circumflex femoral artery."),
        2: ("A patient stands on the left leg and the right hip drops. Which muscles are weak and on which side?",
            "The left gluteus medius and minimus — the standing side."),
    },
    "ankle-foot": {
        0: ("Why is the ankle most stable in dorsiflexion?",
            "The talus is wider anteriorly, so it wedges into the mortise."),
        1: ("Which ligament is torn first in an inversion injury?",
            "The anterior talofibular ligament."),
        2: ("Which ligament is the keystone of the medial longitudinal arch?",
            "The plantar calcaneonavicular (spring) ligament."),
    },
    "cranial-nerves": {
        0: ("Which cranial nerves carry parasympathetic fibres?",
            "III, VII, IX and X."),
        1: ("Which nerves leave through the jugular foramen?",
            "IX, X and XI."),
        2: ("What are the three divisions of the trigeminal nerve and which is motor?",
            "Ophthalmic, maxillary and mandibular; only the mandibular division carries motor fibres."),
        3: ("The tongue deviates to the left on protrusion. Which nerve is damaged?",
            "The left hypoglossal nerve."),
    },
    "larynx": {
        0: ("Which is the only complete ring of cartilage in the airway?",
            "The cricoid cartilage."),
        1: ("Which intrinsic muscle abducts the vocal folds?",
            "Posterior cricoarytenoid — the only abductor."),
        2: ("Why is the left recurrent laryngeal nerve more often affected than the right?",
            "It loops under the aortic arch and has a long intrathoracic course."),
    },
    "ear": {
        0: ("What do the three ossicles achieve?",
            "Impedance matching — amplifying vibration about twentyfold so it can move fluid in the cochlea."),
        1: ("Which part of the inner ear detects rotation, and which detects linear acceleration?",
            "The semicircular canals detect rotation; the utricle and saccule detect linear acceleration."),
        2: ("Weber's test lateralises to the right and Rinne is negative on the right. What kind of deafness?",
            "Right conductive deafness."),
    },
    "pelvic-floor": {
        0: ("Which part of levator ani maintains the anorectal angle?",
            "Puborectalis, slinging round the anorectal junction."),
        1: ("Which nerve roots supply levator ani?",
            "S3–S4 directly, with a contribution from the pudendal nerve (S2–S4)."),
        2: ("Which nerve supplies the perineum, and where can it be blocked?",
            "The pudendal nerve, blocked at the ischial spine."),
    },
    "brachial-plexus": {
        1: ("Between which two muscles do the roots of the plexus emerge?",
            "Scalenus anterior and scalenus medius."),
        4: ("Which terminal branch winds round the surgical neck of the humerus?",
            "The axillary nerve."),
    },
    "rotator-cuff": {
        0: ("Name the four rotator cuff muscles.",
            "Supraspinatus, infraspinatus, teres minor and subscapularis."),
        1: ("Why does supraspinatus tear more often than the others?",
            "It passes through the narrow subacromial space and has a relatively avascular zone near its insertion."),
        2: ("Which two cuff muscles laterally rotate the shoulder?",
            "Infraspinatus and teres minor."),
        3: ("Which cuff muscle medially rotates the arm, and how do you test it?",
            "Subscapularis — the lift-off or belly-press test."),
    },
    "carpal-tunnel": {
        0: ("What forms the roof of the carpal tunnel?",
            "The flexor retinaculum, between the scaphoid and trapezium laterally and the pisiform and hook of hamate medially."),
        1: ("How many tendons pass through the carpal tunnel, and which nerve?",
            "Nine tendons — four FDS, four FDP and flexor pollicis longus — with the median nerve."),
        2: ("Why is sensation over the thenar eminence preserved in carpal tunnel syndrome?",
            "The palmar cutaneous branch of the median nerve arises proximal to the tunnel and passes over the retinaculum."),
        3: ("Which muscles waste in a long-standing median nerve compression at the wrist?",
            "The thenar muscles — abductor pollicis brevis, opponens pollicis and flexor pollicis brevis."),
    },
    "cubital-fossa": {
        0: ("Name the boundaries of the cubital fossa.",
            "Pronator teres medially, brachioradialis laterally, and an imaginary line between the epicondyles above."),
        1: ("What are the contents from lateral to medial?",
            "Radial nerve, biceps tendon, brachial artery and median nerve."),
        2: ("Which structure protects the brachial artery from a needle in the fossa?",
            "The bicipital aponeurosis."),
    },
    "femoral-triangle": {
        0: ("What forms the three boundaries of the femoral triangle?",
            "Inguinal ligament above, sartorius laterally, adductor longus medially."),
        1: ("Give the contents of the femoral triangle from lateral to medial.",
            "Femoral nerve, artery, vein, empty space and lymphatics — NAVEL."),
        2: ("Why does a femoral hernia strangulate so readily?",
            "The femoral ring is narrow and bounded by the sharp lacunar ligament medially."),
        3: ("Which three structures run in the adductor canal?",
            "Femoral artery, femoral vein and the saphenous nerve."),
    },
    "popliteal-fossa": {
        0: ("Which muscles form the upper and lower borders of the popliteal fossa?",
            "Biceps femoris and semimembranosus above; the two heads of gastrocnemius below."),
        1: ("Give the order of the neurovascular structures from superficial to deep.",
            "Tibial nerve, popliteal vein, popliteal artery."),
        2: ("Where does the common fibular nerve become vulnerable after leaving the fossa?",
            "At the neck of the fibula, where it is subcutaneous."),
    },
    "gluteal-sciatic": {
        0: ("Which structure leaves the pelvis above piriformis?",
            "The superior gluteal nerve and vessels."),
        1: ("Where does the sciatic nerve run in the buttock?",
            "Midway between the ischial tuberosity and the greater trochanter."),
        2: ("Which quadrant of the buttock is used for an intramuscular injection?",
            "The upper outer quadrant."),
    },
    "breast": {
        0: ("Over which ribs does the breast lie, and what is the axillary tail?",
            "Ribs 2 to 6; the axillary tail of Spence extends into the axilla through the deep fascia."),
        2: ("What proportion of breast lymph drains to the axilla?",
            "About 75%; most of the rest goes to the internal thoracic (parasternal) nodes."),
        3: ("Which two nerves are at risk during axillary clearance, and what does each injury cause?",
            "Long thoracic nerve — winged scapula; thoracodorsal nerve — weak latissimus dorsi."),
    },
    "autonomics": {
        0: ("Where do the two autonomic outflows leave the central nervous system?",
            "Sympathetic from T1–L2; parasympathetic from cranial nerves III, VII, IX, X and from S2–S4."),
        1: ("Where do sympathetic ganglia lie compared with parasympathetic ones?",
            "Sympathetic ganglia lie close to the cord in the chain or as prevertebral ganglia; parasympathetic ganglia lie in or near the target organ."),
        2: ("How far along the gut does the vagus supply?",
            "To the junction of the proximal two thirds and distal third of the transverse colon."),
        3: ("Why is cardiac pain felt in the left arm and jaw?",
            "Cardiac afferents enter at T1–T4, the same segments as the skin of the arm and the upper chest."),
    },
    "lymphatics": {
        0: ("Which parts of the body does the right lymphatic duct drain?",
            "The right side of the head and neck, the right upper limb and the right side of the thorax."),
        1: ("What does an enlarged left supraclavicular node suggest?",
            "Abdominal malignancy, classically gastric — Virchow's node, at the end of the thoracic duct."),
        2: ("Why does the lymph drainage of the testis differ from that of the scrotum?",
            "The testis descends from the posterior abdominal wall and keeps its para-aortic drainage; the scrotal skin is perineal and drains to inguinal nodes."),
    },
    "abdominal-wall": {
        1: ("Which way do the fibres of external oblique run?",
            "Downwards and forwards — hands-in-pockets."),
        2: ("Which layer do the segmental nerves of the abdominal wall run in?",
            "Between internal oblique and transversus abdominis."),
        3: ("What changes at the arcuate line?",
            "Below it all three aponeuroses pass in front of rectus abdominis, leaving only transversalis fascia behind."),
        4: ("Which two arteries anastomose within the rectus sheath?",
            "The superior epigastric (from the internal thoracic) and the inferior epigastric (from the external iliac)."),
    },
    "inguinal-canal": {
        1: ("What forms the posterior wall of the inguinal canal?",
            "Transversalis fascia, reinforced medially by the conjoint tendon."),
        2: ("What are the contents of the inguinal canal in the male?",
            "The spermatic cord and the ilio-inguinal nerve (which runs on the cord rather than through the deep ring)."),
        3: ("How do you distinguish a direct from an indirect hernia at operation?",
            "By its relation to the inferior epigastric vessels — indirect is lateral, direct is medial."),
    },
    "diaphragm": {
        1: ("Give the three main diaphragmatic openings and their levels.",
            "Inferior vena cava at T8, oesophagus at T10, aorta at T12."),
        2: ("Which nerve roots form the phrenic nerve?",
            "C3, C4 and C5."),
    },
    "intercostal-space": {
        0: ("Name the three muscle layers of an intercostal space.",
            "External, internal and innermost intercostal muscles."),
        1: ("In what order do the vein, artery and nerve lie in the costal groove?",
            "Vein, artery, nerve — from above downwards."),
        2: ("Where is the safe triangle for a chest drain?",
            "Between the lateral border of pectoralis major, the lateral border of latissimus dorsi and the fifth intercostal space."),
    },
    "mediastinum": {
        0: ("Name three things that happen at the level of the sternal angle.",
            "The arch of the aorta begins and ends, the trachea divides at the carina, and it is the T4/5 disc level."),
        1: ("What lies in the middle mediastinum?",
            "The pericardium, the heart, the roots of the great vessels and the phrenic nerves."),
    },
    "vertebral-column": {
        0: ("Which curves of the spine are present at birth?",
            "The thoracic and sacral (primary) curves."),
        1: ("Which joint provides most of the rotation of the head?",
            "The atlanto-axial joint, around the dens."),
        2: ("Which interspace is used for a lumbar puncture and why?",
            "L3/4 or L4/5 — below the end of the cord at L1/L2, using the iliac crests (L4) as the landmark."),
    },
    "heart-chambers": {
        0: ("Which chamber lies most anteriorly, and which forms the apex?",
            "The right ventricle is most anterior; the left ventricle forms the apex."),
        1: ("Where do you listen for the mitral valve, and why is it not over the valve itself?",
            "At the apex, in the fifth intercostal space in the midclavicular line — sound is carried downstream in the direction of blood flow."),
        2: ("Which artery supplies the anterior two thirds of the interventricular septum?",
            "The anterior interventricular (left anterior descending) branch of the left coronary artery."),
        3: ("ST elevation in leads II, III and aVF. Which artery?",
            "The right coronary artery — an inferior infarct."),
    },
    "bronchial-tree": {
        0: ("At what level does the trachea divide, and why does an inhaled object go right?",
            "At the carina, level with the sternal angle; the right main bronchus is wider, shorter and more vertical."),
        1: ("Which lung has three lobes, and what is the left lung's equivalent of the middle lobe?",
            "The right; the lingula, part of the left upper lobe."),
        2: ("What makes a bronchopulmonary segment surgically resectable?",
            "It has its own segmental bronchus and artery, with its veins running between segments."),
    },
    "coeliac-foregut": {
        0: ("Which three arteries supply the gut, and which part does each supply?",
            "Coeliac trunk — foregut; superior mesenteric — midgut; inferior mesenteric — hindgut."),
        1: ("Name the three branches of the coeliac trunk.",
            "Left gastric, splenic and common hepatic arteries."),
        3: ("Where is foregut pain felt, and why?",
            "In the epigastrium — visceral afferents run back with the sympathetic supply to T6–T9."),
    },
    "portal-system": {
        0: ("Which two veins unite to form the portal vein, and where?",
            "The splenic and superior mesenteric veins, behind the neck of the pancreas."),
        1: ("Name three sites of portosystemic anastomosis.",
            "Lower oesophagus, the umbilicus (caput medusae), the rectum, and the retroperitoneum — any three."),
        2: ("Which vessel supplies the centre of a liver lobule with oxygen, and which zone suffers first in shock?",
            "Blood flows from the portal triad to the central vein, so zone 3, around the central vein, is most hypoxic."),
    },
    "kidney-retroperitoneum": {
        0: ("At what vertebral levels do the kidneys lie, and why is the right lower?",
            "T12 to L3; the right is pushed down by the liver."),
        1: ("Name the three constrictions of the ureter.",
            "The pelvi-ureteric junction, the crossing of the pelvic brim, and the vesico-ureteric junction."),
        2: ("Which part of the nephron reabsorbs most of the filtered load?",
            "The proximal convoluted tubule — around two thirds of the filtered sodium and water."),
        3: ("What kind of epithelium lines the bladder, and why?",
            "Urothelium (transitional epithelium) — it stretches and is impermeable to urine."),
    },
    "skin-layers": {
        1: ("Name the layers of the epidermis from the base upwards.",
            "Stratum basale, spinosum, granulosum, (lucidum in thick skin) and corneum."),
        2: ("Why can a superficial partial-thickness burn heal without grafting?",
            "Epithelial stem cells survive in the hair follicles and sweat glands deep in the dermis."),
    },
}


def main():
    added = 0
    for path in sorted(CONTENT.glob("lessons*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for lesson in doc:
            table = CHECKS.get(lesson.get("id"))
            if not table:
                continue
            for index, (q, a) in table.items():
                if index >= len(lesson["steps"]):
                    print(f"{lesson['id']}: no step {index}")
                    continue
                step = lesson["steps"][index]
                if not step.get("check"):
                    step["check"] = {"q": q, "a": a}
                    added += 1
                    touched = True
        if touched:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"updated {path.name}")
    print(f"{added} checks added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
