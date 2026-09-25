"""Female reproductive system: a hemisected pelvis with the vulva in place, a breast in section and magnified
specimens of the ovary, tube, endometrium and the first week of development."""
import math

from .base import MicroModel
from .female import CUTAWAY, build_female


def register_all(register):
    model = MicroModel(
        "female_reproductive", "Female reproductive system",
        "A median section of the female pelvis as in an atlas plate: the anteverted, anteflexed uterus (fundus, "
        "body, isthmus; perimetrium, myometrium, functional and basal endometrium) and cervix projecting into the "
        "vaginal fornices, between the bladder and urethra in front and the rectum behind, with the vesicouterine "
        "and rectouterine pouches. Tubes, ovaries, the broad ligament and the ovarian, suspensory, round, "
        "uterosacral and cardinal ligaments, the uterine and ovarian vessels, ureters, pelvic floor and bony pelvis "
        "surround them, and the vulva sits in place below. Beside it: a breast in sagittal section, and magnified "
        "sections of an ovary with its follicles, the ampulla, and secretory endometrium with an implanted "
        "conceptus, above a row from fertilisation to blastocyst. Switch the cut-away off to see both sides - from "
        "above and in front for the tubes and broad ligaments, from below for the vulva.",
        build_female,
        targets={"structures": ["Mammary region", "Urogenital region", "Pubic symphysis", "Hip bone", "Levator ani",
                                "Coccygeus muscle"],
                 "groups": ["Regions of perineum", "Pelvic diaphragm"]},
        histology=["ovary", "uterine_tube", "uterus", "cervix", "vagina", "mammary", "placenta",
                   "strat_squamous_nk", "smooth_muscle", "adipose"],
        related=["male_reproductive", "bladder_wall", "lymph_node", "ileocecal_rectum"],
        cutaway=CUTAWAY, cut_at=(0.0, 0.0),
        clinical=[
            ("Ectopic pregnancy",
             "Implantation outside the uterine cavity - in ~95% the uterine tube, most often the ampulla, then the "
             "isthmus (early rupture) and the interstitial part (late, torrential bleeding); rarely the ovary, "
             "cervix, a caesarean scar or the peritoneum. Risk rises with previous pelvic inflammatory disease, "
             "tubal surgery or ectopic, IVF, smoking and pregnancy with an IUD or after sterilisation. Classic "
             "picture: 6-8 weeks' amenorrhoea, lower abdominal pain and vaginal bleeding, with a positive hCG and no "
             "intrauterine sac on transvaginal ultrasound. Rupture fills the rectouterine pouch with blood (shoulder "
             "tip pain, shock) - a surgical emergency (salpingectomy); an unruptured, small ectopic may be treated "
             "with methotrexate or expectantly."),
            ("Endometriosis & adenomyosis",
             "Endometrial glands and stroma outside the uterus, most often on the ovaries (chocolate cysts, "
             "endometriomas), the uterosacral ligaments, the rectouterine and vesicouterine pouches and the "
             "peritoneum - explained by retrograde menstruation through the tubes, coelomic metaplasia and "
             "lymphovascular spread. The deposits bleed each cycle: cyclical pelvic pain, dysmenorrhoea, deep "
             "dyspareunia, dyschezia and subfertility; a fixed retroverted uterus and nodules in the pouch of "
             "Douglas on examination. Diagnosis by laparoscopy or imaging; hormonal suppression or excision. "
             "Adenomyosis is endometrium within the myometrium: a bulky, tender uterus with heavy painful periods."),
            ("Pelvic inflammatory disease",
             "Ascending infection (Chlamydia trachomatis, Neisseria gonorrhoeae, mixed anaerobes) from the cervix "
             "through the uterus and tubes to the peritoneum - possible because the tubes open into the peritoneal "
             "cavity. Lower abdominal pain, cervical motion and adnexal tenderness, fever and discharge. "
             "Complications: tubo-ovarian abscess, pus in the rectouterine pouch, perihepatitis (Fitz-Hugh-Curtis), "
             "and tubal scarring causing infertility, ectopic pregnancy and chronic pain. Treat early with "
             "broad-spectrum antibiotics and trace partners."),
            ("Cervical cancer & the Pap smear",
             "Almost all cervical cancer is caused by persistent high-risk HPV (types 16 and 18) infecting the "
             "metaplastic cells of the transformation zone round the external os. It progresses slowly through "
             "cervical intraepithelial neoplasia (CIN 1-3) to invasive (mostly squamous) carcinoma, which spreads "
             "into the parametrium, obstructs the ureters and presents with postcoital or intermenstrual bleeding. "
             "Screening samples the transformation zone (Pap smear / liquid-based cytology, now with primary HPV "
             "testing); abnormal results go to colposcopy and excision of the zone (LLETZ/cone biopsy). HPV "
             "vaccination before sexual debut prevents most cases."),
            ("Ovarian cysts & tumours",
             "Functional cysts (a follicle that fails to ovulate, a persistent corpus luteum) are common, usually "
             "painless and resolve in 1-2 cycles; they may rupture or bleed. Polycystic ovaries carry many small "
             "antral follicles (PCOS: anovulation, hyperandrogenism). A cyst or mass can twist the ovary on its "
             "suspensory ligament and mesovarium (torsion: sudden severe pain, vomiting - emergency detorsion). "
             "Neoplasms arise from surface/tubal epithelium (serous, mucinous; high-grade serous carcinoma probably "
             "from the fimbriae), germ cells (mature cystic teratoma - dermoid) or sex-cord stroma (granulosa cell "
             "tumour, fibroma with Meigs syndrome). Ovarian cancer presents late with bloating and ascites; CA-125, "
             "ultrasound and the risk of malignancy index guide referral; BRCA1/2 carriers are offered risk-reducing "
             "salpingo-oophorectomy."),
            ("Fibroids (leiomyomas)",
             "Benign monoclonal tumours of myometrial smooth muscle, present in most women by 50 and commoner in "
             "Black women; oestrogen- and progesterone-dependent, so they grow in pregnancy and shrink after the "
             "menopause. Submucosal fibroids distort the cavity (heavy menstrual bleeding, subfertility, "
             "miscarriage), intramural ones enlarge the uterus, subserosal and pedunculated ones press on the "
             "bladder or rectum or twist. They may undergo red degeneration in pregnancy. Treated with hormonal "
             "therapy, uterine artery embolisation, myomectomy or hysterectomy; rapid growth after the menopause "
             "raises the possibility of leiomyosarcoma."),
            ("Uterovaginal prolapse",
             "The uterus and vagina are held up by the cardinal and uterosacral ligaments (level 1), the attachment "
             "of the vagina to the pelvic side wall (level 2) and the perineal body and levator ani (level 3). "
             "Childbirth (especially instrumental delivery, big babies), ageing, oestrogen loss, obesity, chronic "
             "cough and constipation weaken them. The anterior wall bulges with the bladder (cystocele) or urethra, "
             "the posterior wall with the rectum (rectocele) or small bowel from the pouch of Douglas (enterocele), "
             "and the uterus descends down the vagina - to or beyond the introitus (procidentia). Treated with "
             "pelvic floor exercises, pessaries or surgical repair."),
            ("Breast cancer & lymphatic drainage",
             "The commonest cancer in women; most are invasive ductal carcinomas of the terminal duct-lobular unit, "
             "about half in the upper outer quadrant and axillary tail where most gland lies. Signs: a hard, "
             "irregular, painless lump; skin dimpling from tethered Cooper's ligaments; peau d'orange from blocked "
             "dermal lymphatics; nipple retraction, bloody discharge or Paget disease; fixation to pectoralis or "
             "the chest wall. About 75% of lymph drains to the axillary nodes (levels I-III), the medial breast to "
             "the parasternal (internal thoracic) nodes, and some to the opposite breast and the abdomen - so "
             "tumours spread first to the axilla and then to the supraclavicular nodes, bone, lung, liver and brain. "
             "Triple assessment (examination, imaging, core biopsy); sentinel node biopsy stages the axilla; "
             "treatment tailored to oestrogen/progesterone receptor and HER2 status. Risk: age, BRCA1/2, "
             "prolonged oestrogen exposure; screening mammography."),
        ],
        scale_note="Pelvis at life size (1 unit = 100 mm; the uterus ~7.5 cm long). The breast is shown at about 0.8x; "
                   "the ovary specimen ~2.5x (follicles and corpora enlarged for clarity), the ampulla section and "
                   "endometrium ~20-30x, and the embryos ~600x, with sperm drawn much larger than life.")
    model.metres_per_unit = 0.1
    model.home_view = (math.radians(72.0), math.radians(8.0))     # from the right, square onto the median section
    register(model)
