import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("—", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


@dataclass
class SearchEntry:
    kind: str                # "structure", "group", "landmark"
    title: str
    subtitle: str
    sids: list
    system: str = None
    landmark: int = None
    node: str = None
    alt: str = ""
    norm: str = field(default="", repr=False)
    norm_alt: str = field(default="", repr=False)
    words: tuple = field(default=(), repr=False)


SYNONYMS = {
    "thigh bone": "femur", "shin bone": "tibia", "kneecap": "patella", "collarbone": "clavicle",
    "shoulder blade": "scapula", "breastbone": "sternum", "jaw": "mandible", "voice box": "larynx",
    "windpipe": "trachea", "gullet": "esophagus", "oesophagus": "esophagus", "tailbone": "coccyx",
    "biceps": "biceps brachii", "triceps": "triceps brachii", "quads": "quadriceps femoris",
    "hamstrings": "biceps femoris", "lats": "latissimus dorsi", "pecs": "pectoralis major",
    "traps": "trapezius", "delts": "deltoid", "calf": "gastrocnemius", "achilles": "calcaneal tendon",
    "funny bone": "ulnar nerve", "atlas": "atlas c1", "axis": "axis c2", "ear drum": "tympanic membrane",
}


EPONYM = re.compile(r"\b((?:[A-Z][a-zé'\-]+[ -]){1,3}(?:syndrome|sign|signs|fracture|disease|palsy|triad|test|"
                    r"lesion|lesions|hernia|contracture|neuralgia|angina|aphasia|malformation|haematoma|"
                    r"tenosynovitis|thyroiditis|node|nodule|tumour|phenomenon|manoeuvre|procedure|ulcer))\b")


class SearchIndex:
    def __init__(self, dataset):
        self.ds = dataset
        self.entries = []
        seen = {}
        sysname = {s["key"]: s["name"] for s in dataset.systems}
        for s in dataset.structures:
            key = (s["base"], s["system"], s["role"], s["name"])
            if key in seen:
                seen[key].sids.append(s["id"])
                continue
            sub = s["subsystem"] or ""
            subtitle = sysname[s["system"]] + (f" · {sub}" if sub else "")
            if s["system"] == "attachments" and "on" in s:
                subtitle = f"Muscle attachment on {dataset.structures[s['on']]['base']}"
            e = SearchEntry("structure", s["name"], subtitle, [s["id"]], s["system"], alt=s.get("latin") or "")
            seen[key] = e
            self.entries.append(e)
        for nid, node in dataset.nodes.items():
            if node["kind"] == "group" and node["count"] > 1:
                e = SearchEntry("group", node["name"], f"Group · {node['count']} structures · {sysname[node['system']]}",
                                None, node["system"], node=nid, alt=node.get("latin") or "")
                self.entries.append(e)
        lm_seen = {}
        for i, lm in enumerate(dataset.landmarks):
            host = dataset.structures[lm["sid"]]
            key = (lm["name"], host["base"])
            if key in lm_seen:
                lm_seen[key].sids.append(lm["sid"])
                continue
            e = SearchEntry("landmark", lm["name"], f"Landmark on {host['base']}", [lm["sid"]], host["system"],
                            landmark=i, alt=lm.get("latin") or "")
            lm_seen[key] = e
            self.entries.append(e)
        self._prepare(self.entries)

    @staticmethod
    def _prepare(entries):
        for e in entries:
            e.norm = normalize(e.title)
            e.norm_alt = normalize(e.alt)
            e.words = tuple(e.norm.split())

    def add_content(self, content):
        """Index clinical correlations, histology tissues and microanatomy models from a ContentIndex."""
        ds = self.ds
        by_base = {}
        for s in ds.structures:
            if not s.get("role"):
                by_base.setdefault(s["base"].lower(), []).append(s["id"])
        group_of = {n["name"].lower(): nid for nid, n in ds.nodes.items() if n["kind"] != "structure"}
        added = []
        for entry in content.clinical:
            sids = []
            for t in entry["targets"]:
                key = t.lower()
                if key in by_base:
                    sids += by_base[key]
                elif key in group_of:
                    sids += ds.node_structures(group_of[key])
            if not sids:
                continue
            system = ds.structures[sids[0]]["system"]
            # named signs, syndromes and fractures in the text ("Colles fracture", "Horner syndrome") are searchable
            terms = EPONYM.findall(entry["text"])
            alt = " · ".join(dict.fromkeys(terms)) or " ".join(entry.get("tags", []))
            added.append(SearchEntry("clinical", entry["title"], "Clinical · " + ", ".join(entry["targets"][:3]),
                                     list(dict.fromkeys(sids)), system, alt=alt))
        for t in content.tissues.values():
            if t.get("images"):
                added.append(SearchEntry("tissue", t["name"], "Histology · " + " › ".join(t["path"]), [], None,
                                         node=t["id"]))
        for m in content.micro_models.values():
            added.append(SearchEntry("micro", m.name, "3D microanatomy model", [], None, node=m.id))
        self._prepare(added)
        self.entries.extend(added)

    def add_lessons(self, lessons):
        """So that searching 'carpal tunnel' offers the guided lesson as well as the structures."""
        added = []
        for lesson in lessons:
            keywords = " ".join(n for step in lesson.steps for n in step.get("focus", []) + step.get("show", []))
            added.append(SearchEntry("lesson", lesson.title,
                                     f"Lesson · {lesson.system_name} · {lesson.region_name} · {len(lesson)} steps",
                                     [], None, node=lesson.id,
                                     alt=" ".join([lesson.summary, keywords] + lesson.tags + lesson.objectives)))
        self._prepare(added)
        self.entries.extend(added)

    def add_radiology(self, cases):
        """So that searching 'chest x-ray', 'scaphoid' or 'CT head' offers the matching case."""
        added = []
        for case in cases:
            keywords = " ".join(dict.fromkeys([lab.text for lab in case.labels]
                                              + [n for lab in case.labels for n in lab.structures]))
            added.append(SearchEntry("radiology", case.title,
                                     f"Radiology · {case.modality} · {case.region}", [], None,
                                     node=case.id, alt=f"{case.modality} {case.summary} {keywords}"))
        self._prepare(added)
        self.entries.extend(added)

    def add_sketchfab(self, models):
        """So that searching 'glomerulus' or 'elastic artery' offers the online Sketchfab model too."""
        added = []
        for m in models:
            where = "3D model, downloaded" if m.local else "Online 3D model"
            added.append(SearchEntry("sketchfab", m.name, f"{where} · {m.author} · Sketchfab", [], None,
                                     node=m.uid, alt=" ".join([m.summary] + m.structures)))
        self._prepare(added)
        self.entries.extend(added)

    def search(self, query, limit=150):
        q = normalize(query)
        if not q:
            return []
        q = SYNONYMS.get(q, q)
        qwords = q.split()
        results = []
        for e in self.entries:
            score = self._score(e.norm, e.words, q, qwords)
            if e.norm_alt:
                alt = self._score(e.norm_alt, tuple(e.norm_alt.split()), q, qwords)
                score = max(score, alt - 4 if alt else 0)
            if score <= 0:
                continue
            score += {"structure": 3, "group": 2, "landmark": 0, "clinical": 1, "tissue": 1, "micro": 1,
                      "lesson": 2, "radiology": 2, "sketchfab": 2}[e.kind]
            if e.system == "attachments":
                score -= 6
            elif e.system == "reference":
                score -= 3
            score -= min(len(e.norm), 80) * 0.05
            results.append((score, e))
        if not results and len(q) >= 4:
            for e in self.entries:
                r = max((SequenceMatcher(None, q, w).ratio() for w in e.words), default=0)
                r = max(r, SequenceMatcher(None, q, e.norm).ratio())
                if r >= 0.78:
                    results.append((r * 40, e))
        results.sort(key=lambda x: -x[0])
        return [e for _, e in results[:limit]]

    @staticmethod
    def _score(norm, words, q, qwords):
        if not norm:
            return 0
        if norm == q:
            return 100
        if norm.startswith(q):
            return 90
        if all(any(w.startswith(qw) for w in words) for qw in qwords):
            first = words[0].startswith(qwords[0]) if words else False
            return 80 if first else 75
        if q in norm:
            return 65
        return 0
