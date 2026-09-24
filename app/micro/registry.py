from .base import MicroModel
from .skin import build_skin

SKIN_CLINICAL = [
    ("Blistering diseases",
     "Pemphigus vulgaris: IgG against desmoglein 3 splits cells within the stratum spinosum (suprabasal, flaccid "
     "blisters, Nikolsky positive). Bullous pemphigoid: IgG against hemidesmosomes (BP180/230) lifts the whole "
     "epidermis off the basement membrane (tense subepidermal blisters)."),
    ("Burn depth",
     "Superficial partial-thickness burns spare the dermal papillae and heal from follicle and gland epithelium in "
     "~2 weeks; full-thickness burns destroy all adnexal stem cells, are painless and need grafting."),
    ("Basal cell & squamous cell carcinoma",
     "Basal cell carcinoma arises from basal-layer-like cells (palisading nests); squamous cell carcinoma from "
     "keratinocytes of the spinosum (keratin pearls). Melanoma arises from basal melanocytes."),
]

MODELS = {}


def register(model):
    MODELS[model.id] = model


register(MicroModel(
    "thin_skin", "Thin (hairy) skin",
    "A block of typical body skin: a thin epidermis without stratum lucidum over a dermis containing hair "
    "follicles, sebaceous glands, arrector pili, eccrine glands, vessels and nerves.",
    lambda: build_skin("thin"),
    targets={"categories": ["skin"]},
    histology=["thin_skin", "hair_follicle", "sweat_glands", "strat_squamous_k"],
    related=["thick_skin", "scalp", "axillary_skin"], clinical=SKIN_CLINICAL,
    scale_note="Block ≈ 4 mm wide; epidermis thickness exaggerated for clarity."))
register(MicroModel(
    "thick_skin", "Thick (glabrous) skin",
    "Skin of the palms and soles: very thick stratum corneum, a stratum lucidum, epidermal ridges with dermal "
    "papillae full of Meissner corpuscles, many eccrine glands and no hair.",
    lambda: build_skin("thick"),
    targets={"structures": ["Palm", "Sole", "Heel region", "Palmar surfaces of digits of hand",
                            "Plantar surfaces of digits of foot", "Hallucial eminence"]},
    histology=["thick_skin", "skin_receptors", "sweat_glands"], related=["thin_skin"], clinical=SKIN_CLINICAL,
    scale_note="Block ≈ 4 mm wide; epidermal ridges form fingerprints."))
register(MicroModel(
    "scalp", "Scalp skin",
    "Hair-bearing skin with densely packed, deep terminal hair follicles grouped in follicular units, whose bulbs "
    "reach the subcutaneous fat, and large sebaceous glands, bound by fibrous septa to the galea aponeurotica.",
    lambda: build_skin("scalp"),
    targets={"structures": ["Hairs of head", "Parietal region", "Occipital region", "Frontal region",
                            "Temporal region"], "groups": ["Regions of epicranium"]},
    histology=["hair_follicle", "thin_skin"], related=["thin_skin"],
    clinical=[("Androgenetic alopecia & telogen effluvium",
               "Androgenetic alopecia miniaturises terminal follicles into vellus follicles (DHT-dependent). Telogen "
               "effluvium pushes many follicles into the resting phase 2–3 months after a stressor, causing diffuse "
               "shedding."),
              ("Scalp lacerations bleed profusely",
               "Vessels in the dense connective tissue layer are held open by fibrous septa and cannot retract, "
               "so scalp wounds bleed heavily.")],
    scale_note="Terminal follicles extend into the hypodermis."))
register(MicroModel(
    "axillary_skin", "Axillary skin (apocrine glands)",
    "Skin of the axilla showing large apocrine sweat glands deep in the dermis and hypodermis that empty into hair "
    "follicles, alongside eccrine glands.",
    lambda: build_skin("axilla"),
    targets={"structures": ["Lateral region of thorax"]},
    histology=["sweat_glands", "hair_follicle"], related=["thin_skin"],
    clinical=[("Hidradenitis suppurativa",
               "Follicular occlusion in apocrine-bearing skin (axilla, groin) leads to recurrent painful nodules, "
               "abscesses, sinus tracts and scarring."),
              ("Axillary hyperhidrosis",
               "Excess eccrine sweating driven by sympathetic cholinergic fibres; treated with aluminium salts, "
               "botulinum toxin or sympathectomy.")]))

from .registry_organs import register_all  # noqa: E402

register_all(register)

# Further models live in their own registry_extra_*.py files, each with a register_all(register) like registry_organs.
import importlib as _importlib  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

for _f in sorted(_Path(__file__).parent.glob("registry_extra_*.py")):
    _importlib.import_module(f"{__package__}.{_f.stem}").register_all(register)
