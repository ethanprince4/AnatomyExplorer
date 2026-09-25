"""Male reproductive system: a midsagittal section of the pelvis with the testis, cord and inguinal canal."""
import math

from .base import MicroModel
from .male import build_male


def register_all(register):
    model = MicroModel(
        "male_reproductive", "Male reproductive system",
        "A midsagittal section of the male pelvis: bladder on the prostate (peripheral, central and transition "
        "zones, anterior stroma, colliculus), seminal vesicle and ampulla joining as the ejaculatory duct, and the "
        "prostatic, membranous and spongy urethra to the external orifice. Bulbourethral glands, external "
        "sphincter and perineal membrane; the root (bulb and crura under bulbospongiosus and ischiocavernosus) and "
        "body of the penis with its corpora, glans, prepuce, dorsal vessels and nerves. The right scrotum is opened "
        "through the testis to show every covering, the septa, lobules and tubules, rete testis, efferent ductules "
        "and epididymis, with the spermatic cord running up through the inguinal canal. Insets: a seminiferous "
        "tubule and a spermatozoon. Turn the cut-away off to see the genitalia whole.",
        build_male,
        targets={"structures": ["Testis", "Epididymis", "Ductus deferens", "Ejaculatory duct", "Prostate",
                                "Seminal gland", "Urethra", "Penis", "Glans penis", "Corpus spongiosum of penis",
                                "Corpus cavernosum of penis", "Deep dorsal vein of penis", "Dorsal artery of penis",
                                "Deep artery of penis", "Superficial dorsal veins of penis"]},
        histology=["testis", "epididymis", "ductus_deferens", "seminal_vesicle", "prostate", "penis", "urethra",
                   "bladder"],
        related=["bladder_wall", "kidney_section", "lymph_node"],
        clinical=[
            ("Cryptorchidism",
             "The testis develops on the posterior abdominal wall and descends through the inguinal canal behind "
             "the processus vaginalis, guided by the gubernaculum, reaching the scrotum by birth. In ~3% of term "
             "(30% of preterm) boys it is arrested - in the abdomen, the canal or at the superficial ring (distinguish "
             "from a retractile testis pulled up by an active cremaster, which can be brought down). An undescended "
             "testis is too warm for spermatogenesis (subfertility) and carries a several-fold higher risk of "
             "germ cell tumour (seminoma); orchidopexy by 6-12 months improves fertility and makes the testis "
             "examinable, but does not fully remove the cancer risk."),
            ("Inguinal hernia",
             "Indirect hernia: through the deep ring lateral to the inferior epigastric vessels, along the canal "
             "inside the cord coverings, often into the scrotum - a patent processus vaginalis; the commonest hernia "
             "in both sexes and all ages. Direct hernia: through the posterior wall medial to the vessels "
             "(Hesselbach triangle), outside the internal spermatic fascia, in older men; rarely scrotal. Both emerge "
             "above and medial to the pubic tubercle (a femoral hernia is below and lateral). An irreducible, tender "
             "hernia may be strangulated - an emergency. Repair (open mesh or laparoscopic) must spare the "
             "ilioinguinal nerve, the genital branch of the genitofemoral nerve and the cord."),
            ("Varicocele",
             "Dilated veins of the pampiniform plexus - a 'bag of worms' above and behind the testis, larger on "
             "standing or Valsalva. ~90% are left-sided: the left testicular vein is longer and enters the left "
             "renal vein at a right angle, and can be compressed. It raises testicular temperature and is a common "
             "treatable cause of male infertility. A sudden right-sided or non-collapsing varicocele needs imaging "
             "for a retroperitoneal mass or a renal tumour obstructing the vein."),
            ("Testicular torsion",
             "Twisting of the testis on its spermatic cord, usually in adolescents with a 'bell-clapper' deformity "
             "(the tunica vaginalis attached high on the cord so the testis hangs free). Sudden severe scrotal pain, "
             "nausea, a high-riding, horizontally lying tender testis and an absent cremasteric reflex. Venous then "
             "arterial occlusion: salvage is ~90% within 6 h and falls steeply after. It is a surgical emergency - "
             "explore without waiting for imaging, untwist and fix both testes (the other side has the same "
             "anatomy). Differentials: torsion of the appendix testis (blue dot), epididymo-orchitis (gradual, "
             "Prehn sign)."),
            ("Benign prostatic hyperplasia & prostate cancer (DRE)",
             "BPH is nodular hyperplasia of the transition zone round the proximal prostatic urethra (DHT-driven), "
             "causing lower urinary tract symptoms, retention, bladder trabeculation, stones and hydronephrosis; on "
             "DRE the gland is smooth, firm, symmetrically enlarged with the median sulcus preserved. Treatment: "
             "α1-blockers, 5α-reductase inhibitors, TURP. Prostate adenocarcinoma arises mainly in the peripheral "
             "zone, next to the rectum - so it is felt early on DRE as a hard, irregular nodule, often before urinary "
             "symptoms. PSA, multiparametric MRI and biopsy confirm it; Gleason grade from the biopsy guides "
             "treatment. It spreads to pelvic nodes and to bone (osteoblastic metastases, back pain)."),
            ("Vasectomy",
             "Through a small incision in the upper scrotum the ductus deferens is palpated in the cord (a firm cord "
             "separate from the soft pampiniform veins), divided and its ends tied or cauterised on each side. "
             "Sperm production continues but sperm are reabsorbed; ejaculate volume barely changes because ~95% "
             "comes from the seminal vesicles, prostate and bulbourethral glands, and erection and testosterone are "
             "unaffected (the testicular artery and Leydig cells are untouched). Sterility is not immediate: sperm "
             "stored beyond the cut must be cleared, confirmed by semen analysis after ~3 months."),
            ("Urethral injury & extravasation",
             "A pelvic fracture tears the membranous urethra above the perineal membrane (urine into the "
             "extraperitoneal pelvis). A straddle injury tears the bulbar urethra below it: urine and blood spread "
             "in the superficial perineal pouch under Colles fascia into the scrotum, penis and lower abdominal "
             "wall, but not the thighs (attachment to the fascia lata). Blood at the meatus is a contraindication to "
             "blind catheterisation."),
        ],
        # the cut-away removes the whole left half (z > 0) - the midsagittal section
        cutaway=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), cut_at=(9.0, 0.0),
        scale_note="Section block ≈ 200 mm across (1 unit = 10 cm); the right testis and scrotum are opened by a "
                   "second, parasagittal cut. Tubules, ducts and nerves are drawn a little wider than life; the "
                   "insets are magnified (tubule ~x200, spermatozoon ~x1300).")
    model.home_view = (math.radians(-28.0), math.radians(12.0))
    register(model)
