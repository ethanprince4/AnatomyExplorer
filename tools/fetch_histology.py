"""Harvest normal human histology images from Wikimedia Commons into data/histology.

Stages (each cached, so the script can be re-run):
  crawl     - walk histology category trees and collect file titles
  search    - add per-tissue full-text search results
  info      - fetch image info, descriptions, licences and categories
  classify  - score every image against tools/histology_catalog.py
  download  - fetch chosen images (1280 px) and build thumbnails + catalog.json

Usage: python tools/fetch_histology.py [stage ...]     (default: all)
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from histology_catalog import TISSUES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "histology"
CACHE = OUT / "cache"
IMAGES = OUT / "images"
THUMBS = OUT / "thumbs"
for d in (CACHE, IMAGES, THUMBS):
    d.mkdir(parents=True, exist_ok=True)

UA = "AnatomyExplorer/1.0 (personal offline histology atlas; contact: none) python-urllib"
API = "https://commons.wikimedia.org/w/api.php"
MAX_PER_TISSUE = 14

ROOTS = [
    ("Category:Human histology", 3),
    ("Category:Histology by organ system", 3),
    ("Category:Histology from CNX Anatomy & Physiology Textbook", 1),
    ("Category:Mikael Häggström/Micrographs", 3),
    ("Category:Micrographs of blood", 1),
    ("Category:Histological schematic", 2),
    ("Category:Compendium of histology", 2),
    ("Category:Microscopic images by body part", 3),
    ("Category:Text-book of normal histology", 1),
    ("Category:Manual of human histology", 1),
]

SKIP_CAT = re.compile(r"immunohistochem|by country|publication|video|histologists|plant|animal|fish|reptil|mammal|"
                      r"dog|rat\b|mouse|mice|leporid|chondrichth|limulus|insect|bird|frog|cat\b|pig\b|cattle|horse|"
                      r"sheep|monkey|macaque|carcinoma|tumou?r|neoplas|cancer|lymphoma|patholog|disease|infection|"
                      r"parasit|fossil|metallograph|mineral|bacteri|fung|virus|protist|diatom|pollen|algae|gene|"
                      r"chromosom|syndrome|dementia|disorder|protein|molecul|dna|rna\b|karyotyp|mutation|drug|"
                      r"cell line|culture|stem cell|embryo|fetus|foet|surgery|patient|x-ray|radiograph|ct scan|mri|"
                      r"ultrasound|photograph|people|portrait|museum|book|journal|anatomy \(|artwork|paint|logo", re.I)

PATHOLOGY = re.compile(r"carcinoma|adenocarcinoma|cancer|tumou?r|neoplas|metasta|lymphoma|leuka?emia|sarcoma|melanoma|"
                       r"adenoma|carcinoid|dysplas|hyperplas|metaplas|infarct|necros|fibrosis|cirrhos|hepatitis|"
                       r"\w{3,}itis\b|infection|infected|parasit|amyloid|granulom|abscess|ulcer|polyp|\bcyst\b|disease|"
                       r"syndrome|lesion|patholog|mutation|atroph|haemorrhag|hemorrhag|thromb|calcinosis|tubercul|fungal|"
                       r"virus|viral|\bhpv\b|barrett|coeliac|celiac|crohn|endometriosis|keratosis|gout|sclerosis|"
                       r"degenerat|malignan|benign|lipoma|nevus|naevus|wart|papilloma|hamartoma|teratoma|glioma|"
                       r"blastoma|seminoma|mesothelioma|myeloma|immunohistochem|\bihc\b|immunostain|cd\d+\b|ki-?67|"
                       r"\bp53\b|\bp16\b|abnormal|lesional|autopsy finding|toxicity|injury|damage|atypia|\btb\b|"
                       r"edema|oedema|congest|inflamm|steatosis|fatty liver|psoriasis|eczema|acne|"
                       r"hashimoto|graves|endometrioma|pregnancy loss|hydatid", re.I)

ANIMAL = re.compile(r"\brats?\b|\bmice\b|\bmouse\b|murine|\bdogs?\b|canine|\bcats?\b|feline|\bpigs?\b|porcine|swine|"
                    r"\bsheep\b|ovine|\bcows?\b|bovine|cattle|\bhorses?\b|equine|rabbit|monkey|macaque|primate|chicken|"
                    r"\bbirds?\b|avian|\bfish\b|zebrafish|frog|amphibian|reptil|lizard|snake|turtle|insect|drosophila|"
                    r"hamster|guinea pig|\bbats?\b|whale|dolphin|ferret|goat|caprine|deer|shark|salamander|axolotl|"
                    r"worm|octopus|squid|crab|shrimp|snail|mollus|cephalopod|\bmink\b|opossum|kangaroo|elephant",
                    re.I)

HISTO_CUE = re.compile(r"histolog|micrograph|microscop|\bh&e\b|\bhe stain|haematoxylin|hematoxylin|eosin|\bstain|"
                       r"magnification|\bx\s?\d{2,3}\b|\d{2,3}\s?x\b|\bsection\b|slide|light microscop|electron micro|"
                       r"trichrome|pas stain|silver stain|masson|van gieson|toluidine|\bsem\b|\btem\b", re.I)

last_request = [0.0]


MIN_INTERVAL = [1.1]

# From manual review of chosen titles: genetics plots, non-human organisms, art, cytology smears, research figures
GLOBAL_REJECT = re.compile(
    r"gwas|manhattan plot|allele|cohort|galaxy|nike of|dinosaur|loves you|pretty|a rose for you|tooth smile|death eyes|"
    r"glazed eyes|polycera|longidorus|mayaweckelia|caridea|ascaris|hippocampus barbouri|desmodus|iguana|varanus|"
    r"cambridge natural history|origin of vertebrates|forest of memory|tree of life|coral reef|blue leopards|"
    r"microscopic maze|new lifes|teekond|img-\d|clonal hematopoiesis|drugdelivery|sars-cov|patch ?clamp|hulecs|"
    r"^cell niche|^cell membrane|^cell surface|trisomy|clue cells|vaginal flora|rouleaux|smudge cell|pap smear|"
    r"kb stain|basophilic stippling|плазмоциты|nail polish|hair cuticle|proper care of the hair|animals and man|"
    r"the chordates|clinical gyncology|journal of roentgenology|reference handbook|manual of human physiology|"
    r"atlas of clinical microscopy|psammoma|transection|macular artifact|crumpling artifact|canal of nuck|"
    r"ama antibodies|pylori|langerhans cell histiocytosis|renal hemocyte|turbulen|aneurisma|стаз|unk cells|"
    r"обрезанный|сперматозоид|cardiocyte|egg cell fertilization|cilia with cumulus|卵泡|placental msc|ocp use|"
    r"calcification of a term|sil eg|reactive mesothelium|hernia sac|peritoneal fluid|hamartoma|osseointegration|"
    r"bony nidus|osteoporotic|trabecular bone with|dormant population|hematopoiesis simple|whole-organ|scaffold|"
    r"zooming a tongue|intrapulpal denticles|eosinophil in esophageal|pvs-0|std 190219|westgate|brady microscopy|"
    r"nucleus of cardiac fibroblasts|figure 33 02|figure 40 03|sensory neuron test|нейроны стриатума|"
    r"immunofluorescent staining|synaptic contacts|vikingplot|computer rendering|gaba colocalization|gfp-f|"
    r"pathways of retinal ganglion|receptive fields|satellite glial|spiral ganglion neurons|molecular marker expression|"
    r"growth hormone receptor|bdnf|golgi 1885|hippocampus migration|ependymal cilia|ependyma-derived|self-renew|"
    r"mural cells|schematic representation of the cell types|innate immunity components|club cell|"
    r"identified cell types|lymphatic progenitor|^energy$|retinal cell's microtubule|lateral inhibition|"
    r"dendritic cell activation|t-cell and microvillus|imunohistochemical|stages 1.9 of the seminiferous|"
    r"hist\.technik|predictive model|cytokeratin 19 expression|h-caldesmon|retinol-binding|bile duct formation|"
    r"hepatic circulation and micro|hepatocito golgi|pancreatic stellate|functions of tuft|nudemouse|"
    r"transmission electron micrographs showing|cytology of precursor|stacked cells|two views of cochlear|bapta|"
    r"capturing pgcs|chochlear amplifier|tip-links|ngfr expression|s100\+sox9|electron micrograph of a section cut|"
    r"britannica|anatomy and physiology of animals|spectral domain oct|thalamic neuron|mast cells in bone marrow|"
    r"neutrophil development|stages of neutrophil|hematopoietic system, extracted|pluripotency of human gingival|"
    r"my own oral mucosa|supplementary figure|fnana-|hemidesmosome formation|mesenchymal-stem|bonemetabolism|"
    r"cartilage with$|cartilage without$|bone microvasculature|woven bone matrix|stain - liver tissue|"
    r"the galaxy within|girls are|circle of salt and pepper|cells differentiate|breast lobules$|^normal$|"
    r"molecular profiling of human sweat|imaging of the 3d structure|histological anatomies of basement|"
    r"endometrium ocp|physiological hypertrophy of uterus|postmenopausal myometrium|spatial relationships between|"
    r"β2-tanycytes|functional repopulation|thymus lobule \(nih|nih bioart|interaction between|spiral arteries|"
    r"sinoatrial node|umbilical|vein valves, from alberti|wellcome|human umbilical vein endothelial|nailfold|"
    r"capillary supply in young human pineal|well developed capillary supply|the animals|dendritic cells in corneal|"
    r"зріз голови тритона|cartilage types$|figure 39 01|figure 28 02|oseophagus histology of diagram|thuc quan",
    re.I)

# candidates that matched the wrong tissue on a shared keyword
TISSUE_REJECT = {
    "blood": re.compile(r"pituitary|pars distalis", re.I),
    "cerebral_cortex": re.compile(r"pituitary|pineal|spinal|thalamic|striat", re.I),
    "appendix": re.compile(r"epididymis|gray1074", re.I),
    "islets": re.compile(r"celu|cel langerhans|celulas langerhans|macr[oó]fago|histiocytosis|hemocyte", re.I),
    "eye": re.compile(r"gwas|pigmentation|parietal eye|pineal eye|death|glazed|allele|manhattan", re.I),
    "cornea": re.compile(r"caridea|endothelium in situ|cell surface|cell membrane|cell niche", re.I),
    "simple_squamous": re.compile(r"cytology", re.I),
    "serosa": re.compile(r"cytology|lung", re.I),
    "loose_ct": re.compile(r"layers of the gi tract", re.I),
    "thin_skin": re.compile(r"pacinian|heat lo|macaco", re.I),
    "thick_skin": re.compile(r"gray942", re.I),
    "capillaries": re.compile(r"parathyroid|pineal|lymphatic", re.I),
    "meninges_cp": re.compile(r"pineal|spinal cord ependy", re.I),
    "ganglion": re.compile(r"retina|ganglion cell|cochlea|spiral", re.I),
    "bone_marrow": re.compile(r"clonal", re.I),
    "cardiac_muscle": re.compile(r"endocardium", re.I),
    "skin_receptors": re.compile(r"submucous plexus", re.I),
    "muscular_artery": re.compile(r"arteriole elastic", re.I),
    "elastic_artery": re.compile(r"normal lung", re.I),
    "bronchiole": re.compile(r"normal lung - elastic", re.I),
    "jejunum": re.compile(r"epithelial tissues", re.I),
    "kidney_cortex": re.compile(r"fetal|kidney-medulla", re.I),
    "pituitary": re.compile(r"pinealocytes", re.I),
    "nail": re.compile(r"hair|mayaweckelia", re.I),
    "penis": re.compile(r"polycera", re.I),
    "ductus_deferens": re.compile(r"gray1079", re.I),
    "seminal_vesicle": re.compile(r"gray1079", re.I),
    "anal_canal": re.compile(r"^mucosa", re.I),
    "stomach": re.compile(r"castor", re.I),
    "ear": re.compile(r"elastic cartilage", re.I),
    "tonsil": re.compile(r"roentgenology|cambridge", re.I),
    "hippocampus": re.compile(r"macular", re.I),
}


def get(url, binary=False, retries=8):
    for attempt in range(retries):
        wait = MIN_INTERVAL[0] - (time.time() - last_request[0])
        if wait > 0:
            time.sleep(wait)
        last_request[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            MIN_INTERVAL[0] = max(1.1, MIN_INTERVAL[0] * 0.97)
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(15 * (attempt + 1), 120)
            if e.code == 429:
                MIN_INTERVAL[0] = min(MIN_INTERVAL[0] * 1.5, 6.0)
            print(f"  HTTP {e.code}; waiting {delay:.0f}s (interval now {MIN_INTERVAL[0]:.1f}s)")
            time.sleep(delay)
        except Exception as e:  # noqa: BLE001
            print(f"  retry {attempt + 1} for {url[:100]}: {e}")
            time.sleep(5 + attempt * 5)
    return None


def api(params):
    params = dict(params, format="json", formatversion=2)
    return get(API + "?" + urllib.parse.urlencode(params))


def cache_load(name, default):
    p = CACHE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def cache_save(name, data):
    (CACHE / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- crawl
def category_members(cat):
    files, subcats = [], []
    cont = {}
    while True:
        r = api(dict({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmlimit": 500,
                      "cmtype": "file|subcat"}, **cont))
        if not r:
            return None, None
        for m in r.get("query", {}).get("categorymembers", []):
            (files if m["ns"] == 6 else subcats).append(m["title"])
        if "continue" in r:
            cont = r["continue"]
        else:
            break
    return files, subcats


def stage_crawl():
    state = cache_load("crawl.json", {"files": {}, "seen_cats": []})
    files = state["files"]
    seen = set(state["seen_cats"])
    roots = list(ROOTS)
    r = api({"action": "query", "list": "search", "srsearch": "intitle:\"histology of\"", "srnamespace": 14,
             "srlimit": 200})
    for x in (r or {}).get("query", {}).get("search", []):
        if not SKIP_CAT.search(x["title"]):
            roots.append((x["title"], 2))
    for root, depth in roots:
        queue = [(root, 0)]
        while queue:
            cat, d = queue.pop(0)
            if cat in seen:
                continue
            seen.add(cat)
            fs, subs = category_members(cat)
            if fs is None:
                seen.discard(cat)
                print(f"FAILED {cat}")
                continue
            for f in fs:
                files.setdefault(f, [])
                if cat not in files[f]:
                    files[f].append(cat)
            print(f"{cat} (depth {d}): {len(fs)} files, {len(subs)} subcats; total files {len(files)}")
            if d < depth:
                for s in subs:
                    if not SKIP_CAT.search(s):
                        queue.append((s, d + 1))
            if len(seen) % 20 == 0:
                cache_save("crawl.json", {"files": files, "seen_cats": sorted(seen)})
    cache_save("crawl.json", {"files": files, "seen_cats": sorted(seen)})


def stage_search():
    found = cache_load("search.json", {})
    for t in TISSUES:
        if t["id"] in found:
            continue
        titles = set()
        for q in (f"{t['query']} histology", f"{t['query']} micrograph"):
            r = api({"action": "query", "list": "search", "srsearch": q, "srnamespace": 6, "srlimit": 40})
            for x in (r or {}).get("query", {}).get("search", []):
                titles.add(x["title"])
        found[t["id"]] = sorted(titles)
        print(f"search {t['id']}: {len(titles)}")
        cache_save("search.json", found)


# targeted queries for tissues that came out thin after the first pass
EXTRA_QUERIES = {
    "strat_squamous_k": ["keratinized stratified squamous epithelium", "epidermis histology layers"],
    "heart_valve": ["heart valve histology", "endocardium histology", "epicardium histology", "mitral valve histology",
                    "aortic valve histology"],
    "sublingual": ["sublingual gland histology", "sublingual gland"],
    "eye": ["sclera histology", "iris histology", "lens histology", "eyelid histology", "ciliary body histology",
            "conjunctiva histology", "lacrimal gland histology"],
    "nasal_mucosa": ["nasal mucosa histology", "olfactory epithelium histology", "olfactory mucosa"],
    "larynx": ["larynx histology", "vocal fold histology", "epiglottis histology"],
    "gej": ["gastroesophageal junction histology", "esophagogastric junction histology"],
    "parotid": ["parotid gland histology", "serous acini salivary gland"],
    "nail": ["nail histology", "nail bed histology", "nail matrix histology"],
    "penis": ["penis histology", "corpus cavernosum histology", "glans penis histology"],
    "anal_canal": ["anal canal histology", "anorectal junction histology"],
    "oral_mucosa": ["lip histology", "gingiva histology", "oral mucosa histology", "buccal mucosa histology"],
    "urethra": ["urethra histology", "penile urethra histology"],
    "kidney_medulla": ["renal medulla histology", "collecting duct histology", "renal papilla histology"],
    "thick_skin": ["thick skin histology", "palm skin histology", "stratum lucidum", "sole skin histology"],
    "skin_receptors": ["Meissner corpuscle", "Pacinian corpuscle histology", "Merkel cell histology"],
    "dense_irregular": ["dermis histology collagen", "dense irregular connective tissue"],
    "bronchus": ["bronchus histology", "bronchial wall histology"],
    "gallbladder": ["gallbladder histology", "gallbladder mucosa"],
    "ductus_deferens": ["vas deferens histology", "ductus deferens"],
    "seminal_vesicle": ["seminal vesicle histology"],
    "strat_cub_col": ["stratified cuboidal epithelium", "stratified columnar epithelium"],
    "elastic_artery": ["aorta histology", "elastic artery histology"],
}


def stage_extra():
    found = cache_load("search.json", {})
    for tid, queries in EXTRA_QUERIES.items():
        key = f"extra:{tid}"
        if key in found:
            continue
        titles = set()
        for q in queries:
            r = api({"action": "query", "list": "search", "srsearch": q, "srnamespace": 6, "srlimit": 40})
            for x in (r or {}).get("query", {}).get("search", []):
                titles.add(x["title"])
        found[key] = sorted(titles)
        print(f"extra search {tid}: {len(titles)}")
        cache_save("search.json", found)


# --------------------------------------------------------------------------- info
def strip_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def stage_info():
    crawl = cache_load("crawl.json", {"files": {}})["files"]
    search = cache_load("search.json", {})
    titles = set(crawl) | {t for v in search.values() for t in v}
    titles = sorted(t for t in titles if re.search(r"\.(jpe?g|png|tiff?|svg|gif|webp)$", t, re.I))
    info = cache_load("info.json", {})
    todo = [t for t in titles if t not in info]
    print(f"info: {len(titles)} titles, {len(todo)} to fetch")
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        cont = {}
        pages = {}
        while True:
            r = api(dict({"action": "query", "titles": "|".join(batch), "prop": "imageinfo|categories",
                          "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280,
                          "iiextmetadatafilter": "ImageDescription|Artist|LicenseShortName|ObjectName|Credit",
                          "clshow": "!hidden", "cllimit": "max"}, **cont))
            if not r:
                break
            for p in r.get("query", {}).get("pages", []):
                entry = pages.setdefault(p["title"], {"categories": []})
                if p.get("imageinfo"):
                    ii = p["imageinfo"][0]
                    md = ii.get("extmetadata", {})
                    entry.update({
                        "url": ii.get("url"), "thumb": ii.get("thumburl"), "width": ii.get("width"),
                        "height": ii.get("height"), "mime": ii.get("mime"), "page": ii.get("descriptionurl"),
                        "description": strip_html(md.get("ImageDescription", {}).get("value", ""))[:1500],
                        "object": strip_html(md.get("ObjectName", {}).get("value", "")),
                        "artist": strip_html(md.get("Artist", {}).get("value", ""))[:200],
                        "license": md.get("LicenseShortName", {}).get("value", ""),
                    })
                for c in p.get("categories", []):
                    if c["title"] not in entry["categories"]:
                        entry["categories"].append(c["title"])
            if "continue" in r:
                cont = r["continue"]
            else:
                break
        for t in batch:
            info[t] = pages.get(t, {"missing": True})
        print(f"  {min(i + 50, len(todo))}/{len(todo)}")
        if (i // 50) % 10 == 0:
            cache_save("info.json", info)
    cache_save("info.json", info)


# --------------------------------------------------------------------------- classify
def kw_regex(kw):
    whole = kw.endswith("$")
    k = re.escape(kw.rstrip("$").lower())
    return re.compile(r"(?<![a-z])" + k + (r"(?![a-z])" if whole else ""))


def stage_classify():
    crawl = cache_load("crawl.json", {"files": {}})["files"]
    search = cache_load("search.json", {})
    info = cache_load("info.json", {})
    searched_by = defaultdict(set)
    for tid, titles in search.items():
        for t in titles:
            searched_by[t].add(tid.split(":")[-1])
    compiled = []
    for t in TISSUES:
        compiled.append((t, [kw_regex(k) for k in t["kw"]], [kw_regex(k) for k in t["neg"]],
                         [c.lower() for c in t["cats"]]))
    ranked = defaultdict(list)
    rejected = defaultdict(int)
    for title, meta in info.items():
        if meta.get("missing") or not meta.get("thumb"):
            continue
        if meta.get("mime") not in ("image/jpeg", "image/png", "image/svg+xml", "image/tiff", "image/gif",
                                    "image/webp"):
            continue
        if (meta.get("width") or 0) < 300:
            rejected["small"] += 1
            continue
        name = re.sub(r"^File:|\.\w+$", "", title).replace("_", " ")
        cats = " | ".join(meta.get("categories", []) + crawl.get(title, [])).lower()
        desc = (meta.get("description", "") + " " + meta.get("object", "")).lower()
        text = f"{name.lower()} || {desc} || {cats}"
        if PATHOLOGY.search(name) or PATHOLOGY.search(desc[:400]) or PATHOLOGY.search(cats):
            rejected["pathology"] += 1
            continue
        if ANIMAL.search(name) or ANIMAL.search(desc[:400]) or ANIMAL.search(cats):
            rejected["animal"] += 1
            continue
        if GLOBAL_REJECT.search(name) or GLOBAL_REJECT.search(desc[:300]):
            rejected["reviewed junk"] += 1
            continue
        in_histo_tree = title in crawl
        if not in_histo_tree and not HISTO_CUE.search(text):
            rejected["no cue"] += 1
            continue
        diagram = meta.get("mime") == "image/svg+xml" or bool(re.search(r"schemat|diagram|drawing|illustration|"
                                                                          r"gray\d|gray's|sobotta|plate", text))
        scores = []
        for t, kws, negs, tcats in compiled:
            if any(n.search(name.lower()) or n.search(desc[:300]) for n in negs):
                continue
            if t["id"] in TISSUE_REJECT and TISSUE_REJECT[t["id"]].search(name):
                continue
            s = 0
            if any(c in cats for c in tcats):
                s += 6
            if any(k.search(name.lower()) for k in kws):
                s += 5
            elif any(k.search(desc[:500]) for k in kws):
                s += 3
            elif any(k.search(cats) for k in kws):
                s += 2
            if s == 0:
                continue
            if t["id"] in searched_by.get(title, ()):
                s += 1
            scores.append((s, t["id"]))
        if not scores:
            rejected["unmatched"] += 1
            continue
        best = max(s for s, _ in scores)
        if best < 3:
            rejected["weak"] += 1
            continue
        quality = 0
        if re.search(r"\bnormal\b", text):
            quality += 2
        if re.search(r"micrograph|h&e|hematoxylin|haematoxylin|\bhe\b", text):
            quality += 1
        if "häggström" in text or "haggstrom" in text:
            quality += 1
        if "cnx" in cats or "openstax" in text:
            quality += 2
        if diagram:
            quality -= 2
        quality += min((meta.get("width") or 0) / 1500.0, 1.0)
        for s, tid in scores:
            if s >= best - 1:
                ranked[tid].append({"title": title, "score": s + quality, "diagram": diagram})
    chosen = {}
    for t in TISSUES:
        items = sorted(ranked[t["id"]], key=lambda x: -x["score"])
        picks, diagrams = [], 0
        for it in items:
            if it["diagram"]:
                if diagrams >= 3:
                    continue
                diagrams += 1
            picks.append(it)
            if len(picks) >= MAX_PER_TISSUE:
                break
        chosen[t["id"]] = picks
        print(f"{t['id']:22s} candidates {len(items):4d}  chosen {len(picks)}")
    print("rejected:", dict(rejected))
    cache_save("chosen.json", chosen)


# --------------------------------------------------------------------------- download
def safe_name(title):
    stem = re.sub(r"^File:", "", title)
    stem = re.sub(r"\.\w+$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:90]
    import hashlib
    return f"{stem}_{hashlib.md5(title.encode('utf-8')).hexdigest()[:6]}"


def make_thumb(src, dst):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage(str(src))
    if img.isNull():
        return False
    img.scaled(208, 156, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, 208, 156).save(
        str(dst), "JPG", 88)
    return True


MAX_SIDE = 1600
DOWNLOAD_INTERVAL = 6.0


def fetch_image(meta, path):
    """Fetch the 1280 px thumbnail (a standard Wikimedia size, served from cache; non-standard sizes and bulk
    original downloads are rejected with HTTP 429) and store it at most MAX_SIDE px."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    MIN_INTERVAL[0] = max(MIN_INTERVAL[0], DOWNLOAD_INTERVAL)
    data = get(meta["thumb"].split("?")[0], binary=True)
    if not data or len(data) < 2000:
        return False
    img = QImage()
    if not img.loadFromData(data):
        return False
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if path.suffix == ".jpg":
        img = img.convertToFormat(QImage.Format_RGB32)
        return img.save(str(path), "JPG", 90)
    return img.save(str(path), "PNG")


def stage_download():
    """Round-robin over tissues (first image of every tissue, then the second, ...) and rewrite catalog.json after
    every few files, so the app has usable coverage long before a rate-limited download finishes."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])  # noqa: F841
    info = cache_load("info.json", {})
    chosen = cache_load("chosen.json", {})
    images = {t["id"]: {} for t in TISSUES}
    failed = set(cache_load("failed.json", []))

    def entry(pick, fname):
        meta = info[pick["title"]]
        title = re.sub(r"^File:|\.\w+$", "", pick["title"]).replace("_", " ")
        return {"file": fname, "title": title, "description": meta.get("description", ""),
                "author": meta.get("artist", ""), "license": meta.get("license", ""), "source": meta.get("page", ""),
                "diagram": pick["diagram"]}

    def write_catalog():
        catalog = {"categories": [], "tissues": []}
        for t in TISSUES:
            e = {k: t[k] for k in ("id", "name", "path", "summary", "features", "structures", "groups", "contains",
                                   "categories")}
            order = [safe_name(p["title"]) for p in chosen.get(t["id"], [])]
            e["images"] = [images[t["id"]][n] for n in order if n in images[t["id"]]]
            catalog["tissues"].append(e)
        tmp = OUT / "catalog.json.tmp"
        tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(OUT / "catalog.json")

    rounds = max((len(v) for v in chosen.values()), default=0)
    total = 0
    for r in range(rounds):
        for t in TISSUES:
            picks = chosen.get(t["id"], [])
            if r >= len(picks) or picks[r]["title"] in failed:
                continue
            pick = picks[r]
            meta = info[pick["title"]]
            stem = safe_name(pick["title"])
            ext = ".png" if meta.get("mime") in ("image/svg+xml", "image/png", "image/gif") else ".jpg"
            path = IMAGES / (stem + ext)
            if not path.exists():
                if not fetch_image(meta, path):
                    failed.add(pick["title"])
                    cache_save("failed.json", sorted(failed))
                    continue
                total += 1
                print(f"  [{total}] {t['id']}: {pick['title'][5:70]}")
            thumb = THUMBS / (stem + ".jpg")
            if not thumb.exists() and not make_thumb(path, thumb):
                path.unlink(missing_ok=True)
                continue
            images[t["id"]][stem] = entry(pick, path.name)
            if total and total % 5 == 0:
                write_catalog()
        write_catalog()
        print(f"round {r + 1}/{rounds} done")
    write_catalog()
    keep = {e["file"] for v in images.values() for e in v.values()}
    for f in IMAGES.iterdir():
        if f.name not in keep:
            f.unlink()
            (THUMBS / (f.stem + ".jpg")).unlink(missing_ok=True)
    print(f"downloaded {total} new files; catalog has {len(keep)} images")


STAGES = {"crawl": stage_crawl, "search": stage_search, "extra": stage_extra, "info": stage_info, "classify": stage_classify,
          "download": stage_download}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STAGES):
        print(f"=== {name}")
        STAGES[name]()
