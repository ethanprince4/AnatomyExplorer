"""Validate the lesson library: every name resolves, every key is real, every cross-reference exists.

Lab-course lessons get more: their `course` place, every `practice` item (exact atlas names for find/name, exact
part names in a built microanatomy model for find_micro and micro_focus, valid multiple-choice answers), every
`diagram` file, and every `practice_from` reference.

    python tools/check_lessons.py                       the whole library
    python tools/check_lessons.py draft.json            also a draft file that is not in data/content yet
    python tools/check_lessons.py --only lab03          just the lessons whose id starts with lab03
"""
import argparse
import difflib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR                                     # noqa: E402
from app.data import Dataset                                        # noqa: E402
from app.lessons import LEVEL_NAME, REGION_NAME, SYSTEM_NAME        # noqa: E402
from app.lessons import PRACTICE_TYPES, diagram_path, unit_matches   # noqa: E402
from app.lessons import Resolver, load_lessons                      # noqa: E402

COURSE_ID = re.compile(r"^(lab\d{2}|exam\d)-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")


class MicroParts:
    """Part names of each microanatomy model, built (or read from data/micro_cache) the first time one is asked."""

    def __init__(self, models):
        self.models = models
        self.names = {}

    def get(self, model_id):
        """[part names]; None when the model is not registered (yet); an exception when it will not build."""
        if model_id not in self.models:
            return None
        if model_id not in self.names:
            print(f"  (loading micro model {model_id}…)", flush=True)
            try:
                self.names[model_id] = [p.name for p in self.models[model_id].parts()]
            except Exception as exc:                   # noqa: BLE001 - a model mid-edit must not stop the check
                self.names[model_id] = exc
        return self.names[model_id]


def check_diagram(did, where, fail):
    path = diagram_path(did)
    if path is None:
        fail(f"{where}: diagram {did!r} has no file data/content/diagrams/{did}.svg")
        return
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        fail(f"{where}: diagram {path.name} is not valid XML: {exc}")
        return
    if not root.tag.endswith("svg"):
        fail(f"{where}: diagram {path.name} is not an SVG")
    elif not root.get("viewBox"):
        fail(f"{where}: diagram {path.name} has no viewBox, so it cannot be scaled to the panel")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("extra", nargs="*", help="further lesson files to load (drafts)")
    ap.add_argument("--only", default="", help="check only lessons whose id starts with this")
    args = ap.parse_args()
    ds = Dataset(DATA_DIR)
    res = Resolver(ds)                              # no fuzzy fallback: names must be exact
    pool = list(res.by_lower) + list(res.groups) + list(res.collections)
    from app.content import ContentIndex
    from app.micro.registry import MODELS
    tissues = set(ContentIndex(ds).tissues)
    systems = {s["key"] for s in ds.systems}
    regions = {r["key"] for r in ds.regions}
    lessons = load_lessons(args.extra)
    ids = {x.id for x in lessons}
    micro = MicroParts(MODELS)
    warned_models = set()
    try:
        from app.radiology import load_cases
        cases = {c.id for c in load_cases()}
    except (ImportError, OSError, ValueError):
        cases = set()

    bad = 0
    warnings = 0

    def fail(msg):
        nonlocal bad
        bad += 1
        print(msg)

    def warn(msg):
        nonlocal warnings
        warnings += 1
        print("warning: " + msg)

    def parts_of(model_id, where):
        """Part names, or None (with one warning per model) when the model is not registered yet."""
        names = micro.get(model_id)
        if isinstance(names, Exception):
            if model_id not in warned_models:
                warned_models.add(model_id)
                warn(f"{where}: micro model {model_id!r} does not build right now ({names!r}) - its part names "
                     "were not checked")
            return None
        if names is None and model_id not in warned_models:
            warned_models.add(model_id)
            warn(f"{where}: micro model {model_id!r} is not registered yet - its part names were not checked")
        return names

    def check_part(model_id, part, where):
        names = parts_of(model_id, where)
        if names is not None and part not in names:
            near = difflib.get_close_matches(part, names, n=4, cutoff=0.5)
            fail(f"{where}: {part!r} is not a part of {model_id} -> {near}")

    def check_name(name, where):
        if not name or not res.resolve(name):
            near = difflib.get_close_matches((name or "").lower(), pool, n=4, cutoff=0.6)
            fail(f"{where} {name!r} -> {near}")

    def check_item(item, where):
        kind = item.get("type")
        if kind not in PRACTICE_TYPES:
            fail(f"{where}: type {kind!r} is not one of {list(PRACTICE_TYPES)}")
            return
        if item.get("diagram"):
            check_diagram(item["diagram"], where, fail)
        if kind in ("find", "name"):
            check_name(item.get("structure"), f"{where} [{kind}]")
        elif kind == "find_micro":
            model = item.get("model")
            if not model or not item.get("part"):
                fail(f"{where}: find_micro needs a model and a part")
            else:
                check_part(model, item["part"], f"{where} [find_micro]")
        elif kind == "mcq":
            choices = item.get("choices")
            answer = item.get("answer")
            if not item.get("q"):
                fail(f"{where}: mcq has no question")
            if not isinstance(choices, list) or len(choices) < 2 or not all(isinstance(c, str) and c
                                                                            for c in choices):
                fail(f"{where}: mcq needs a list of at least two choices")
            elif len(set(choices)) != len(choices):
                fail(f"{where}: mcq has the same choice twice")
            elif not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(choices):
                fail(f"{where}: mcq answer {answer!r} is not an index into its {len(choices)} choices")
            elif len(choices) > 6:
                fail(f"{where}: mcq has {len(choices)} choices; the panel shows at most 6")
            if not item.get("why"):
                warn(f"{where}: mcq has no 'why'")
        elif kind == "recall":
            if not item.get("q") or not item.get("a"):
                fail(f"{where}: recall needs a question (q) and an answer (a)")
        elif kind == "order":
            rows = item.get("items")
            if not item.get("q"):
                fail(f"{where}: order has no question")
            if not isinstance(rows, list) or len(rows) < 2:
                fail(f"{where}: order needs at least two items")
            elif len(set(rows)) != len(rows):
                fail(f"{where}: order has the same item twice, so its order is ambiguous")

    def check_course(lesson, where):
        c = lesson.course
        if c is None:
            if lesson.practice or lesson.practice_from:
                warn(f"{where}: has practice items but no 'course' - it will not appear under My lab course")
        else:
            if (c.get("lab") is None) == (c.get("exam") is None):
                fail(f"{where}: course needs exactly one of 'lab' or 'exam'")
            elif not isinstance(c.get("lab", c.get("exam")), int):
                fail(f"{where}: course lab/exam must be a number")
            if not isinstance(c.get("order"), int):
                fail(f"{where}: course needs an integer 'order'")
            if not c.get("unit"):
                fail(f"{where}: course needs a 'unit' heading")
            if not COURSE_ID.match(lesson.id):
                fail(f"{where}: a lab-course id looks like lab03-02-formed-elements or exam1-05-practice-exam")
            elif lesson.unit_key:
                kind, n = lesson.unit_key
                if not lesson.id.startswith(f"lab{n:02d}-" if kind == "lab" else f"exam{n}-"):
                    fail(f"{where}: id does not match course {kind} {n}")
            if lesson.unit_key and lesson.unit_key[0] == "lab":
                if not 3 <= len(lesson) <= 6:
                    warn(f"{where}: {len(lesson)} steps - a mini lesson has 3-5")
                if len(lesson.practice) < 6:
                    warn(f"{where}: {len(lesson.practice)} practice items - aim for 6-15")
        for ref in lesson.practice_from:
            if not any(unit_matches(other, ref) for other in lessons if other is not lesson):
                fail(f"{where}: practice_from {ref!r} matches no lesson or lab")
        for k, item in enumerate(lesson.practice, 1):
            check_item(item, f"{where} practice {k}")

    for lesson in lessons:
        if args.only and not lesson.id.startswith(args.only):
            continue
        where = lesson.id
        if lesson.system not in SYSTEM_NAME:
            fail(f"{where}: system {lesson.system!r} is not one of {sorted(SYSTEM_NAME)}")
        if lesson.region not in REGION_NAME:
            fail(f"{where}: region {lesson.region!r} is not one of {sorted(REGION_NAME)}")
        if lesson.level not in LEVEL_NAME:
            fail(f"{where}: level {lesson.level!r} is not one of {sorted(LEVEL_NAME)}")
        if not lesson.objectives:
            fail(f"{where}: no objectives")
        if not lesson.takeaways:
            fail(f"{where}: no takeaways")
        for other in lesson.prereq:
            if other not in ids:
                fail(f"{where}: prereq {other!r} is not a lesson")
        for other in lesson.see_also.get("lessons", []):
            if other not in ids:
                fail(f"{where}: see_also lesson {other!r} does not exist")
        for cid in lesson.see_also.get("radiology", []):
            if cases and cid not in cases:
                fail(f"{where}: see_also radiology {cid!r} is not a case")
        for mid in lesson.see_also.get("micro", []):
            if mid not in MODELS:
                fail(f"{where}: see_also micro {mid!r} is not a model")
        for tid in lesson.see_also.get("histology", []):
            if tid not in tissues:
                fail(f"{where}: see_also histology {tid!r} is not a tissue")

        for i, step in enumerate(lesson.steps, 1):
            for field in ("show", "focus", "ghost_focus", "frame_on"):
                for name in step.get(field, []):
                    if not res.resolve(name):
                        near = difflib.get_close_matches(name.lower(), pool, n=4, cutoff=0.6)
                        fail(f"{where} step {i} [{field}] {name!r} -> {near}")
            if step.get("micro") and step["micro"] not in MODELS:
                # a model still being built by someone else: say so, but do not fail the library for it
                parts_of(step["micro"], f"{where} step {i}")
            if step.get("histology") and step["histology"] not in tissues:
                fail(f"{where} step {i} histology {step['histology']!r} is not a tissue")
            for key in step.get("systems", []):
                if key not in systems:
                    fail(f"{where} step {i} system {key!r} is unknown")
            for key in step.get("regions", []):
                if key not in regions:
                    fail(f"{where} step {i} region {key!r} is unknown")
            check = step.get("check")
            if check is not None and (not isinstance(check, dict) or not check.get("q") or not check.get("a")):
                fail(f"{where} step {i}: check needs both a question and an answer")
            if step.get("micro_focus"):
                if not step.get("micro"):
                    fail(f"{where} step {i}: micro_focus needs a micro model on the same step")
                else:
                    for part in step["micro_focus"]:
                        check_part(step["micro"], part, f"{where} step {i} micro_focus")
            if step.get("diagram"):
                check_diagram(step["diagram"], f"{where} step {i}", fail)

        check_course(lesson, where)

    steps = sum(len(x) for x in lessons)
    checks = sum(len(x.checks()) for x in lessons)
    practice = sum(len(x.practice) for x in lessons)
    course = [x for x in lessons if x.course]
    print(f"{len(lessons)} lessons, {steps} steps, {checks} recall questions; "
          f"{len(course)} lab-course lessons with {practice} practice items")
    if warnings:
        print(f"{warnings} warnings")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
