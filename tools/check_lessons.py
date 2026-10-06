"""Validate the lesson library: every name resolves, every key is real, every cross-reference exists.

Lab-course and lecture-exam lessons get more: their `course` or `lecture` place, every `practice` item (exact atlas names for find/name, part
names that resolve in the 3D model for find_micro and micro_focus - exactly as the model viewer resolves them: a
part's name, a group's name or one of the model's aliases - valid multiple-choice answers), every `diagram` file,
and every `practice_from` reference.

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
LECTURE_ID = re.compile(r"^lec\d-(ch\d{2}|review)-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")


class _NeverCancelled:
    """The cancellation token a deferred (library) model's CPU preparation polls."""
    cancelled = False

    def check(self):
        return None


class MicroParts:
    """Each 3D model of the catalogue, loaded (procedural ones built or read from data/micro_cache) the first time
    one is asked about."""

    def __init__(self, models):
        self.models = models
        self.loaded = {}

    def get(self, model_id):
        """The loaded model; None when there is no such model (yet); an exception when it will not load."""
        if model_id not in self.models:
            return None
        if model_id not in self.loaded:
            print(f"  (loading 3D model {model_id}…)", flush=True)
            entry = self.models[model_id]
            try:
                if hasattr(entry, "load"):
                    self.loaded[model_id] = entry.load()
                else:
                    self.loaded[model_id] = entry.prepare_cpu(_NeverCancelled())
            except Exception as exc:                   # noqa: BLE001 - a model mid-edit must not stop the check
                self.loaded[model_id] = exc
        return self.loaded[model_id]

    def resolves(self, model_id, name):
        model = self.get(model_id)
        hits, _missing = self.models[model_id].resolve(model, [name])
        return bool(hits)

    def names(self, model_id):
        model = self.get(model_id)
        return [it.name for it in model.items] + [g.title for g in model.groups] + \
            list(getattr(self.models[model_id], "aliases", {}))


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
    content = ContentIndex(ds)
    MODELS = content.micro_models
    tissues = set(content.tissues)
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
        """The loaded model, or None (with one warning per model) when it is not in the catalogue or will not
        load."""
        model = micro.get(model_id)
        if isinstance(model, Exception):
            if model_id not in warned_models:
                warned_models.add(model_id)
                warn(f"{where}: 3D model {model_id!r} does not load right now ({model!r}) - its part names "
                     "were not checked")
            return None
        if model is None and model_id not in warned_models:
            warned_models.add(model_id)
            fail(f"{where}: 3D model {model_id!r} is unavailable")
        return model

    def check_part(model_id, part, where):
        model = parts_of(model_id, where)
        if model is not None and not micro.resolves(model_id, part):
            near = difflib.get_close_matches(part, micro.names(model_id), n=4, cutoff=0.5)
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

    def check_lecture(lesson, where):
        c = lesson.lecture
        if lesson.course is not None:
            fail(f"{where}: a lesson belongs to the lab course or a lecture exam, not both")
        if not isinstance(c.get("exam"), int) or isinstance(c.get("exam"), bool):
            fail(f"{where}: lecture needs an integer 'exam'")
        chapter = c.get("chapter")
        if chapter is not None and (not isinstance(chapter, int) or isinstance(chapter, bool)):
            fail(f"{where}: lecture 'chapter' must be a number, or absent for the exam's full review")
        if not isinstance(c.get("order"), int):
            fail(f"{where}: lecture needs an integer 'order'")
        if not c.get("unit"):
            fail(f"{where}: lecture needs a 'unit' topic")
        if not LECTURE_ID.match(lesson.id):
            fail(f"{where}: a lecture-exam id looks like lec2-ch20-03-chambers-valves or lec2-review-04-practice-exam")
        elif lesson.lecture_key:
            exam, chapter = lesson.lecture_key
            if not lesson.id.startswith(f"lec{exam}-ch{chapter:02d}-" if chapter else f"lec{exam}-review-"):
                fail(f"{where}: id does not match lecture exam {exam}, chapter {chapter or 'review'}")
            if chapter and len(lesson.practice) < 6:
                warn(f"{where}: {len(lesson.practice)} practice items - aim for 6-15")
        for ref in lesson.practice_from:
            if not any(unit_matches(other, ref) for other in lessons if other is not lesson):
                fail(f"{where}: practice_from {ref!r} matches no lesson or chapter")
        for k, item in enumerate(lesson.practice, 1):
            check_item(item, f"{where} practice {k}")

    def check_course(lesson, where):
        c = lesson.course
        if lesson.lecture is not None:
            check_lecture(lesson, where)
            return
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
                # A released lesson must not offer a model that is unavailable.
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
    lecture = [x for x in lessons if x.lecture]
    print(f"{len(lessons)} lessons, {steps} steps, {checks} recall questions; "
          f"{len(course)} lab-course and {len(lecture)} lecture-exam lessons with {practice} practice items")
    if warnings:
        print(f"{warnings} warnings")
    print("OK" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
