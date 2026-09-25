"""The whole heart: chambers, valves, coronary circulation, conduction system and pericardium."""
import math

from .base import MicroModel
from .heart import CUT_NORMAL, build_heart


def register_all(register):
    n = tuple(float(v) for v in CUT_NORMAL)
    model = MicroModel(
        "heart", "Heart: chambers, valves & conduction",
        "The whole adult heart in its natural position, opened along the four-chamber plane: right and left atria "
        "(auricles, pectinate muscles, crista terminalis, fossa ovalis) and ventricles (trabeculae carneae, "
        "papillary muscles, chordae tendineae, moderator band); the tricuspid, mitral, pulmonary and aortic valves "
        "on the fibrous skeleton; the great vessels with the arch and its branches; the coronary arteries and "
        "cardiac veins in their sulci under epicardial fat; the conduction system from the SA node to the Purkinje "
        "fibres; and the pericardium cut open to show its fibrous and serous layers.",
        build_heart,
        targets={"groups": ["Heart", "Arteries of heart", "Cardiac veins", "Valvular complex of heart"],
                 "structures": ["Right atrium", "Left atrium", "Right ventricle", "Left ventricle", "Coronary sinus"]},
        histology=["cardiac_muscle", "heart_valve", "elastic_artery", "serosa", "adipose"],
        related=["cardiac_muscle", "elastic_artery", "muscular_artery"],
        # the cut removes everything in front of the four-chamber plane (both planes are that plane, so the
        # quadrant cut-away becomes a half-space)
        cutaway=((-n[0], -n[1], -n[2]), n), cut_at=(0.0, 0.0),
        clinical=[
            ("Myocardial infarction territories",
             "Each coronary artery owns a territory, so the ECG leads with ST elevation point to the culprit. LAD "
             "(anterior interventricular): anterior wall, apex and anterior two-thirds of the septum - V1-V4; "
             "proximal occlusion also knocks out the bundle branches. Circumflex: lateral wall - I, aVL, V5-V6. "
             "Right coronary (in right-dominant hearts, ~70-80%): inferior wall via the posterior interventricular "
             "artery - II, III, aVF - plus the right ventricle (ST elevation in V4R, hypotension that worsens with "
             "nitrates) and usually the SA and AV nodes, hence bradycardia and heart block. The posteromedial "
             "papillary muscle has a single (PDA) supply and ruptures after inferior MI (acute mitral "
             "regurgitation); septal rupture and free-wall rupture with tamponade peak 3-5 days after infarction."),
            ("Valve disease & auscultation areas",
             "Valves are heard downstream of their anatomical position: aortic - right 2nd intercostal space at the "
             "sternal edge; pulmonary - left 2nd intercostal space; tricuspid - left lower sternal border (4th-5th "
             "space); mitral - apex (left 5th space, midclavicular line). S1 is closure of the AV valves, S2 of the "
             "semilunar valves (A2 then P2, splitting on inspiration). Aortic stenosis: ejection systolic murmur to "
             "the carotids. Mitral regurgitation: pansystolic murmur to the axilla. Mitral stenosis (rheumatic): "
             "mid-diastolic rumble with opening snap, left atrial enlargement and atrial fibrillation. Aortic "
             "regurgitation: early diastolic murmur at the left sternal edge, collapsing pulse."),
            ("Heart block & bundle branch block",
             "The AV node and bundle of His are the only normal electrical path through the fibrous skeleton. "
             "First-degree block: PR > 200 ms. Second-degree Mobitz I (Wenckebach, usually nodal): PR lengthens "
             "until a beat drops. Mobitz II (infranodal): sudden dropped QRS without PR change - risk of complete "
             "block. Third-degree (complete) block: P waves and QRS complexes independent, with a junctional "
             "(narrow, 40-60/min) or ventricular (broad, 20-40/min) escape rhythm - pacemaker. Right bundle branch "
             "block: broad QRS, RSR' in V1. Left bundle branch block: broad QRS, deep S in V1, notched R in V6 "
             "(new LBBB with chest pain = treat as MI). Accessory pathways across the annulus give "
             "Wolff-Parkinson-White pre-excitation (short PR, delta wave)."),
            ("Pericarditis & cardiac tamponade",
             "Pericarditis (viral, post-MI/Dressler, uraemic, autoimmune): sharp pleuritic chest pain eased by "
             "sitting forwards, a scratchy friction rub, widespread concave ST elevation with PR depression. Fluid "
             "or blood filling the pericardial cavity faster than the inelastic fibrous pericardium can stretch "
             "compresses the thin-walled right heart: cardiac tamponade - Beck's triad (hypotension, raised JVP, "
             "muffled heart sounds), pulsus paradoxus (>10 mmHg fall in systolic pressure on inspiration), "
             "electrical alternans. Treated by pericardiocentesis, a needle from the left subxiphoid angle aimed "
             "towards the left shoulder. Chronic constrictive pericarditis (TB, radiotherapy) shows a pericardial "
             "knock and Kussmaul's sign."),
            ("Septal defects & fetal remnants",
             "The fossa ovalis and ligamentum arteriosum are what is left of the fetal shunts (foramen ovale, ductus "
             "arteriosus). A patent foramen ovale (~25% of adults) can let a venous clot cross to the systemic "
             "circulation (paradoxical embolism). Atrial septal defects give fixed splitting of S2; ventricular "
             "septal defects (most at the membranous septum) a harsh pansystolic murmur; a patent ductus a "
             "continuous machinery murmur. Long-standing left-to-right shunts can reverse (Eisenmenger syndrome)."),
        ],
        scale_note="Whole adult heart ≈ 12 cm from base to apex (1 unit ≈ 6 cm). Epicardium, endocardium, "
                   "conduction tissue and valve thickness exaggerated for clarity.")
    model.metres_per_unit = 0.06
    # open looking straight at the cut face of the four-chamber plane, from in front and slightly above
    model.home_view = (math.atan2(n[0], n[2]), math.asin(n[1]))
    register(model)
