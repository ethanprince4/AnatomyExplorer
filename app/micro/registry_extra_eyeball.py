"""The eye: the right eyeball with its extrinsic muscles, eyelids, conjunctiva and lacrimal apparatus."""
from .base import MicroModel
from .eyeball import build_eyeball

EYE_TARGETS = [
    "Eyeball", "Eye", "Cornea", "Sclera", "Iris", "Pupil", "Lens", "Retina", "Vitreous body", "Zonular fibres",
    "Sphincter pupillae", "Dilator pupillae", "Anterior chamber of eyeball", "Anterior segment of eyeball",
    "Posterior segment of eyeball", "Posterior pole of eyeball", "Central retinal artery",
    "Superior rectus muscle", "Inferior rectus muscle", "Medial rectus muscle", "Lateral rectus muscle",
    "Superior oblique muscle", "Inferior oblique muscle", "Levator palpebrae superioris", "Common tendinous ring",
    "Eyelids", "Upper eyelid", "Lower eyelid", "Superior tarsus", "Inferior tarsus", "Eyelashes",
    "Palpebral part of orbicularis oculi", "Lacrimal apparatus", "Lacrimal gland", "Lacrimal canaliculus",
    "Lacrimal sac", "Nasolacrimal duct",
]

EYE_CLINICAL = [
    ("Glaucoma",
     "An optic neuropathy - loss of ganglion cell axons with cupping of the optic disc and a characteristic "
     "peripheral field loss - usually with raised intraocular pressure because aqueous humor drains too slowly. "
     "Open-angle glaucoma (resistance in the trabecular meshwork and canal of Schlemm) is painless and silent "
     "until late: hence screening with tonometry, disc examination and visual fields. Acute angle closure (the "
     "iris blocks the angle, often when the pupil dilates in a hyperopic eye) is an emergency: a painful red eye, "
     "halos, vomiting, a hazy cornea and a fixed mid-dilated pupil. Treatment lowers pressure by cutting aqueous "
     "production at the ciliary processes (timolol, dorzolamide, acetazolamide) or increasing outflow "
     "(prostaglandin analogues, pilocarpine, laser trabeculoplasty or iridotomy, trabeculectomy)."),
    ("Cataract",
     "Opacity of the lens - the commonest cause of reversible blindness worldwide. Risk factors: age, diabetes, "
     "corticosteroids, UV light, smoking, trauma, congenital rubella and galactosaemia. Gradual painless blur, "
     "glare around lights, faded colours and a dimmed red reflex. Surgery (phacoemulsification) opens the "
     "anterior lens capsule, emulsifies and aspirates the lens and places an artificial lens in the capsular "
     "bag; the posterior capsule may cloud later and is opened with a YAG laser. A white pupillary reflex in "
     "a child is congenital cataract or retinoblastoma until proven otherwise."),
    ("Refractive errors",
     "Myopia (nearsightedness): the eyeball is too long (or the cornea too curved), so distant images focus in "
     "front of the retina; corrected with a concave (minus) lens. Hyperopia (farsightedness): the eyeball is too "
     "short, images focus behind the retina; convex (plus) lens. Astigmatism: the cornea (or lens) is curved "
     "more in one meridian than another, so lines in one orientation blur on the astigmatism chart; cylindrical "
     "lenses or toric implants correct it. Presbyopia: the lens stiffens with age and accommodation fails "
     "(near point recedes from ~10 cm at 10 years to ~80-100 cm at 65), needing reading glasses from 40-50. "
     "Snellen 20/20 is normal acuity; 20/100 means seeing at 20 ft what a normal eye sees at 100 ft."),
    ("Retinal detachment",
     "Separation of the neural layer of the retina from the pigmented layer - the two walls of the embryonic "
     "optic cup that are held together only by the vitreous and the pumping of the pigment epithelium. "
     "Commonest is rhegmatogenous: a tear (often at the ora serrata or a lattice area, after posterior vitreous "
     "detachment, more likely in high myopia) lets liquefied vitreous in. Symptoms: flashes, a shower of "
     "floaters, then a shadow or curtain across the field; central vision goes when the macula detaches. An "
     "emergency - repaired by laser, cryotherapy, a scleral buckle, pneumatic retinopexy or vitrectomy."),
    ("Age-related macular degeneration",
     "The leading cause of irreversible central vision loss in older people in high-income countries. Dry "
     "(atrophic) form: drusen beneath the pigmented layer and slow atrophy of the macula. Wet (neovascular) form: "
     "new vessels from the choroid break through Bruch membrane and leak or bleed under the macula, distorting "
     "straight lines (Amsler grid) and destroying central vision within weeks; treated with intravitreal "
     "anti-VEGF injections. Peripheral vision is preserved, so patients do not go completely blind."),
    ("Red eye: conjunctivitis and its mimics",
     "Conjunctivitis inflames the bulbar and palpebral conjunctiva: diffuse redness greatest towards the fornices, "
     "grittiness and discharge - purulent (bacterial), watery with follicles and a preauricular node "
     "(adenovirus, very contagious), itchy with papillae (allergic), or chronic follicular (Chlamydia - "
     "trachoma scars the lids and turns the lashes in). Vision and pupils are normal. Red flags pointing "
     "elsewhere: pain, photophobia, reduced vision, redness concentrated around the limbus (ciliary flush) - "
     "keratitis, iritis (anterior uveitis) or acute angle-closure glaucoma."),
    ("Chalazion, stye and blepharitis",
     "A chalazion is a blocked tarsal (meibomian) gland whose retained lipid provokes a painless granulomatous "
     "lump within the tarsal plate; treated with warm compresses, occasionally incision and curettage from the "
     "conjunctival side. A stye (hordeolum) is an acute staphylococcal abscess - external in a lash follicle "
     "gland of Zeis or Moll, internal in a tarsal gland - red, tender and pointing. Meibomian gland dysfunction "
     "and blepharitis thin the tear film's lipid layer and cause evaporative dry eye."),
    ("Extraocular nerve palsies",
     "LR6 SO4, the rest 3. CN III palsy: the eye rests down and out, with ptosis (levator) and, if the "
     "compressive cause reaches its superficial pupillary fibres (posterior communicating artery aneurysm, "
     "uncal herniation), a dilated pupil; ischaemic (diabetic) palsies usually spare the pupil. CN IV palsy: "
     "vertical diplopia worse looking down and in (stairs, reading), head tilted away. CN VI palsy: the eye "
     "cannot abduct and turns in - an early, non-localising sign of raised intracranial pressure. Test the "
     "muscles in the 'H' pattern: each rectus and oblique acts purely in one position of gaze."),
    ("Papilloedema and optic disc swelling",
     "Raised intracranial pressure is transmitted along the subarachnoid space within the dural sheath of the "
     "optic nerve, blocking axoplasmic flow and compressing the central retinal vein: both discs swell with "
     "blurred margins, venous engorgement and loss of spontaneous venous pulsation, with enlarged blind spots but "
     "initially preserved acuity. Causes: tumours, haemorrhage, idiopathic intracranial hypertension, venous sinus "
     "thrombosis. Never do a lumbar puncture before imaging in a patient with papilloedema."),
    ("Watery and dry eyes",
     "Epiphora (tears spilling) comes from too many tears (reflex from corneal irritation) or blocked drainage: "
     "a lid margin that has turned out (ectropion), punctal stenosis, canalicular injury or nasolacrimal duct "
     "obstruction, congenital (common, usually opens by one year) or acquired with dacryocystitis. Dry eye comes "
     "from too little aqueous (lacrimal gland failure, Sjögren syndrome, ageing, anticholinergics) or too much "
     "evaporation (meibomian gland dysfunction, incomplete lid closure in facial nerve palsy)."),
]


def register_all(register):
    model = MicroModel(
        "eyeball", "Eye: eyeball and accessory structures",
        "A right eye cut in a (para)sagittal plane through the pupil and the optic nerve, seen from the nasal side. "
        "The three tunics: "
        "fibrous (sclera, cornea, limbus with the canal of Schlemm), vascular (choroid, ciliary body with its "
        "muscle and processes, iris with sphincter and dilator pupillae) and nervous (pigmented and neural retina "
        "ending at the ora serrata, with the macula, fovea and optic disc). The lens hangs in its capsule from the "
        "zonular fibres; aqueous humor fills the anterior and posterior chambers and vitreous humor the posterior "
        "segment. Behind, the optic nerve in its dural sheath carries the central retinal vessels, whose branches "
        "spread over the fundus. Around the globe: the six extrinsic muscles (with the trochlea and the common "
        "tendinous ring) and the levator; the eyelids with tarsal plates, tarsal glands, orbicularis and lashes; "
        "the conjunctiva with its fornices; and the lacrimal apparatus from gland to nasolacrimal duct. Untick Cut "
        "to see the whole eye from the front or the side.",
        build_eyeball, targets={"structures": EYE_TARGETS},
        histology=["retina", "cornea", "eye"], related=["retina", "cornea"],
        # a parasagittal plane turned 8 degrees from the sagittal, so that it passes through the pupil and the lens
        # on the optical axis and through the optic disc and nerve, which lie 3 mm nasal to the posterior pole;
        # the nasal half is removed (the second plane sits far away, so it removes nothing on its own)
        cutaway=((-0.9901, 0.0, -0.1407), (0.0, 0.0, 1.0)), cut_at=(1.273 / 12.0, -100.0),
        clinical=EYE_CLINICAL,
        scale_note="Block scale: 2 units = 24 mm, the axial length of the globe. Drawn to scale except the thin "
                   "coats (choroid, retina, conjunctiva, lens capsule, zonular fibres), the canal of Schlemm and "
                   "the retinal vessels, which are thickened to be visible; the retina's fovea and disc are real "
                   "pits and holes.")
    model.home_view = (1.38, 0.16)        # from the nasal side, square onto the cut face
    register(model)
