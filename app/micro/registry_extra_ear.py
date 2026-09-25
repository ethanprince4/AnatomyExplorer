"""The ear: external, middle and inner ear in a coronal section through the right temporal bone."""
from .base import MicroModel
from .ear import MM, build_ear, to_model

EAR_CLINICAL = [
    ("Otitis media and otitis externa",
     "Acute otitis media follows a cold in young children, whose auditory tube is short, wide and horizontal: "
     "Streptococcus pneumoniae, non-typeable Haemophilus influenzae or Moraxella fill the tympanic cavity with pus - "
     "ear pain, fever, a red bulging tympanic membrane, sometimes perforation and discharge. Otitis media with "
     "effusion (glue ear) leaves fluid behind a dull, retracted drum and is the commonest cause of conductive hearing "
     "loss in children (grommets ventilate the middle ear). Complications: mastoiditis, facial palsy, labyrinthitis, "
     "meningitis and temporal lobe abscess through the thin tegmen. Otitis externa is infection of the meatal skin "
     "(swimmers; Pseudomonas): pain on pulling the auricle or pressing the tragus, a swollen canal, a normal drum if "
     "it can be seen. In elderly diabetics, necrotising (malignant) otitis externa spreads to the skull base."),
    ("Conductive vs sensorineural loss: Weber and Rinne",
     "Conductive loss = sound fails to reach the cochlea (wax, perforation, effusion, otosclerosis, ossicular "
     "discontinuity); sensorineural = the cochlea, the cochlear nerve or the brainstem pathway fails (noise, age, "
     "ototoxic drugs, Ménière, vestibular schwannoma, meningitis). Tuning fork (512 Hz; 256 Hz in some courses): "
     "Rinne compares air conduction (beside the meatus) with bone conduction (on the mastoid) in each ear - normally "
     "air > bone ('positive'); bone > air ('negative') means a conductive loss in that ear of roughly 20 dB or more. "
     "Weber places the fork on the vertex or forehead: normally heard in the midline; it lateralises TOWARDS the ear "
     "with a conductive loss (that ear is no longer masked by room noise and its trapped sound is louder) and AWAY "
     "from the ear with a sensorineural loss (to the better cochlea). So: Weber left + Rinne negative left = left "
     "conductive; Weber left + Rinne positive both sides = right sensorineural. Try it on yourself by blocking one "
     "meatus with a finger. Audiometry confirms: an air-bone gap means conductive loss."),
    ("Otosclerosis",
     "Abnormal remodelling of the otic capsule, usually starting just in front of the oval window, fixes the stapes "
     "footplate in the annular ligament. Autosomal dominant with incomplete penetrance, commoner in women and often "
     "worse in pregnancy; progressive bilateral conductive loss from the 20s-40s, often with tinnitus, a normal "
     "tympanic membrane (sometimes a pink Schwartze sign), a negative Rinne, absent stapedial reflexes and a Carhart "
     "notch at 2 kHz. If the focus spreads into the cochlea the loss becomes mixed. Treatment: hearing aid or "
     "stapedotomy - a piston prosthesis from the incus through a hole in the footplate."),
    ("Ménière disease",
     "Endolymphatic hydrops: excess endolymph distends the cochlear duct and saccule, probably from failed "
     "resorption in the endolymphatic sac. Episodes of rotatory vertigo lasting 20 minutes to hours, with "
     "fluctuating low-frequency sensorineural hearing loss, tinnitus and a feeling of fullness in the ear, often "
     "with nausea and vomiting; hearing deteriorates stepwise over years. Management: salt restriction, "
     "betahistine and diuretics, vestibular sedatives in attacks, intratympanic steroid or gentamicin (which kills "
     "vestibular hair cells), endolymphatic sac surgery or labyrinthectomy for intractable cases."),
    ("Benign paroxysmal positional vertigo (BPPV)",
     "The commonest cause of vertigo: otoconia shed from the utricular macula float into a semicircular duct - "
     "almost always the posterior, the most dependent in the upright and supine head (canalolithiasis). Moving "
     "the head in that canal's plane (lying down, rolling over, looking up) makes the debris fall, drag endolymph "
     "and deflect the cupula: brief (<1 min) violent vertigo. Dix-Hallpike test: turning the head 45 degrees and "
     "lying back with it hanging provokes, after a few seconds' latency, torsional upbeating nystagmus that fatigues. "
     "The Epley manoeuvre rolls the particles round the canal and back into the utricle; no hearing loss."),
    ("Noise-induced hearing loss and presbycusis",
     "Loud sound (above ~85 dB for long periods; gunfire, machinery, music through headphones) first damages the "
     "outer hair cells and their stereocilia at the 3-6 kHz region of the basal turn, producing the classic notch at "
     "4 kHz on the audiogram, tinnitus and difficulty following speech in noise; synapses to the cochlear nerve may "
     "be lost even earlier. A temporary threshold shift after a concert recovers; repeated exposure becomes "
     "permanent, because mammalian hair cells do not regenerate. Presbycusis, the age-related loss, is bilateral, "
     "symmetrical and high-frequency (sensory, strial and neural types), making consonants hard to hear. Both are "
     "sensorineural. Prevention: hearing protection and limiting exposure time; treatment: hearing aids and, when "
     "severe, cochlear implants."),
    ("Vestibular schwannoma (acoustic neuroma)",
     "A benign tumour of the Schwann cells of the vestibular nerve in the internal acoustic meatus, growing into the "
     "cerebellopontine angle. Progressive unilateral sensorineural hearing loss and tinnitus (asymmetric loss needs an "
     "MRI), mild imbalance rather than vertigo; larger tumours compress V (loss of corneal reflex), VII and the "
     "cerebellum, and eventually cause hydrocephalus. Bilateral tumours = neurofibromatosis type 2."),
    ("Cholesteatoma",
     "Keratinising squamous epithelium growing in the middle ear, usually from a retraction pocket of the pars "
     "flaccida into the epitympanum. It is not a tumour but it erodes bone enzymatically: the ossicles (the long "
     "process of the incus first), the lateral semicircular canal (fistula - vertigo on pressing the tragus), the "
     "facial canal and the tegmen. Chronic foul-smelling discharge and conductive loss; treated surgically."),
    ("Ototoxicity",
     "Aminoglycosides (gentamicin - mainly vestibular; amikacin and neomycin - mainly cochlear) enter hair cells "
     "through the transduction channels and kill them, starting with basal outer hair cells; the risk is raised by "
     "the mitochondrial MT-RNR1 m.1555A>G variant and by loop diuretics. Cisplatin causes permanent high-frequency "
     "loss; loop diuretics (stria vascularis) and high-dose salicylates (reversible tinnitus) also affect the ear."),
]


def register_all(register):
    m = MicroModel(
        "ear", "Ear: external, middle and inner ear",
        "A coronal section through the right temporal bone, seen from in front and drawn to scale: the auricle and "
        "the S-shaped external acoustic meatus ending at the tympanic membrane; the tympanic cavity with the "
        "malleus, incus and stapes, their ligaments and muscles, the auditory tube and mastoid air cells; and, dug "
        "out of the petrous bone, the translucent bony labyrinth (perilymph) around the membranous labyrinth "
        "(endolymph) - utricle, saccule, semicircular ducts and the cochlea with its basal turn opened - with the "
        "vestibulocochlear and facial nerves. Beside it, magnified: a cochlear turn in section (organ of Corti), a "
        "crista ampullaris and a macula.",
        build_ear,
        targets={"structures": ["Malleus", "Incus", "Stapes", "Cochlea", "Vestibulocochlear nerve (VIII)",
                                "Cochlear nerve", "Vestibular nerve", "Tympanic membrane", "Auditory tube",
                                "Vestibule", "Chorda tympani", "Helix", "Antihelix", "Tragus", "Antitragus",
                                "Lobule of auricle", "Concha of auricle", "Mastoid process"],
                 "groups": ["Ear", "External ear", "Middle ear", "Internal ear", "Auditory ossicles"]},
        histology=["ear", "elastic_cartilage"], related=["retina", "cornea", "peripheral_nerve"],
        clinical=EAR_CLINICAL,
        # the optional cut-away sections the auricle through the concha
        cutaway=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), cut_at=tuple(float(v) for v in to_model((-19.0, 0.0, -8.0))[[0, 2]]),
        scale_note="Drawn to scale, 1 model unit = 40 mm: the auricle is ~62 mm tall, the meatus ~24 mm long, the "
                   "cochlea ~9 mm across and the stapes ~3 mm. The tympanic membrane, the membranous labyrinth and "
                   "the spiral organ are drawn a little thicker than life. Insets: cochlear duct ~x8, crista and "
                   "macula ~x10, with their cells further enlarged.")
    m.metres_per_unit = 0.001 / MM
    m.cut_on = False                    # the model is its own section; the cut-away is offered for the auricle
    m.home_view = (-0.38, 0.30)
    register(m)
