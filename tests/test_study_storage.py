"""Damaged study-file and interrupted-save regression fixtures."""
import json
import datetime
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QStatusBar

from test_state_and_recovery import QAPP  # isolates preferences before app imports
from app.content import ContentIndex
from app.lessons import LessonProgress
from app.ui.quiz import QuizController
from app.ui.practice import PracticeController
from app import srs
from app.storage import write_json


class StudyStorageTests(unittest.TestCase):
    def test_finite_extreme_review_intervals_cannot_break_answer_recording(self):
        day = datetime.date(2026, 9, 30)
        for raw in ({"reps": 3, "interval": 10**9, "ease": 2.5},
                    {"reps": 3, "interval": 21, "ease": 1e308}):
            with self.subTest(raw=raw):
                stat = srs.normalize_stats({"heart": raw})["heart"]
                srs.update(stat, srs.GRADE_GOOD, day)
                due = datetime.date.fromisoformat(stat["due"])
                self.assertGreater(due, day)
                self.assertEqual((due - day).days, stat["interval"])
                self.assertEqual(stat["reps"], 4)
                self.assertEqual(stat["history"], [day.isoformat()])
        normal = {"reps": 2, "interval": 4, "ease": 2.5}
        srs.update(normal, srs.GRADE_GOOD, day)
        self.assertEqual((normal["interval"], normal["due"]), (10, "2026-10-10"))

    def test_unavailable_saved_steps_do_not_complete_current_lesson(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lesson_progress.json"
            original = '{"fixture": {"seen": [999], "last": 999}}'
            path.write_text(original, encoding="utf-8")
            progress = LessonProgress(path)
            self.assertEqual(progress.fraction("fixture", 3), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            for index in (0, 1):
                progress.visit("fixture", index, 3)
                self.assertFalse(progress.is_done("fixture"))
                self.assertEqual(progress.seen("fixture"), set(range(index + 1)))
            progress.visit("fixture", 2, 3)
            self.assertTrue(progress.is_done("fixture"))
            backups = list(Path(folder).glob("lesson_progress.json.recovery-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_malformed_done_marker_cannot_claim_a_lesson_is_finished(self):
        for done in ([0], {"when": "2026-09-01"}, 1, "false", "2026-99-99"):
            with self.subTest(done=done), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "lesson_progress.json"
                original = json.dumps({"fixture": {"seen": [0], "done": done}})
                path.write_text(original, encoding="utf-8")
                progress = LessonProgress(path)
                self.assertFalse(progress.is_done("fixture"))
                self.assertEqual(progress.fraction("fixture", 3), 1 / 3)
                self.assertEqual(progress.seen("fixture"), {0})
                self.assertEqual(path.read_text(encoding="utf-8"), original)
                progress.visit("fixture", 1, 3)
                backups = list(Path(folder).glob("lesson_progress.json.recovery-*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
        for done in ("2026-09-01", True):
            with self.subTest(valid_done=done), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "lesson_progress.json"
                path.write_text(json.dumps({"fixture": {"done": done}}), encoding="utf-8")
                self.assertTrue(LessonProgress(path).is_done("fixture"), "keep dated and legacy boolean completion")

    def test_failed_grade_save_is_reported_and_retry_keeps_pending_results(self):
        for kind in ("quiz", "practice"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "quiz_stats.json"
                original = '{"heart": {"seen": 1, "miss": 0}}'
                path.write_text(original, encoding="utf-8")
                status = QStatusBar()
                messages = []
                status.messageChanged.connect(messages.append)
                win = SimpleNamespace(ds=None, state=None, statusBar=lambda: status)
                with patch("app.ui.quiz.STATS_PATH", path):
                    controller = QuizController(win) if kind == "quiz" else PracticeController(win, SimpleNamespace())
                    controller.stats["heart"]["seen"] = 2
                    save = controller.save_stats if kind == "quiz" else controller._save_stats
                    with patch("app.ui." + kind + ".write_json", side_effect=OSError("fixture disk full")):
                        self.assertFalse(save())
                    self.assertTrue(messages and "Could not save study results" in messages[-1])
                    self.assertEqual(path.read_text(encoding="utf-8"), original)
                    self.assertEqual(controller.stats["heart"]["seen"], 2)
                    self.assertTrue(save(), "retry must persist the pending results")
                    self.assertEqual(status.currentMessage(), "")
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["heart"]["seen"], 2)

    def test_serialization_failure_leaves_original_and_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.json"
            original = '{"heart": "Keep this"}'
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(TypeError):
                write_json(path, {"unserializable": {1, 2}}, backup=True)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_process_exit_before_replace_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "quiz_stats.json"
            original = '{"heart": {"seen": 8, "miss": 1}}'
            path.write_text(original, encoding="utf-8")
            code = ("import os, sys; from pathlib import Path; from app.storage import write_json; "
                    "os.replace = lambda *a, **k: os._exit(23); "
                    "write_json(Path(sys.argv[1]), {'heart': {'seen': 9}})")
            result = subprocess.run([sys.executable, "-B", "-c", code, str(path)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_recovered_saves_keep_exact_damaged_original_backups(self):
        for kind in ("notes", "progress", "quiz"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / f"{kind}.json"
                raw = {"heart": "Keep this note", "bad": 3} if kind == "notes" else \
                    {"heart": {"seen": [0]}, "bad": "recoverable original text"} if kind == "progress" else \
                    {"heart": {"seen": 8, "miss": 1, "history": ["2026-09-01"]}, "bad": "original"}
                original = json.dumps(raw, ensure_ascii=False).encode("utf-8")
                path.write_bytes(original)
                if kind == "notes":
                    with patch("app.content.USER_DIR", Path(folder)):
                        content = ContentIndex(None)
                    content.notes_path = path
                    # ContentIndex normally uses notes.json; the fixture uses that same name.
                    content.set_note("lung", "New note")
                elif kind == "progress":
                    progress = LessonProgress(path)
                    progress.visit("heart", 1, 3)
                else:
                    with patch("app.ui.quiz.STATS_PATH", path):
                        quiz = QuizController(SimpleNamespace(ds=None, state=None))
                        quiz.save_stats()
                backups = list(Path(folder).glob(f"{path.name}.recovery-*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("heart", saved)
                if kind == "quiz":
                    self.assertEqual(saved["heart"], raw["heart"])

    def test_notes_damage_is_filtered_without_rewriting_file(self):
        for raw in (None, [], {"heart": 12, "lung": "Keep this note"}):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "notes.json"
                text = json.dumps(raw)
                path.write_text(text, encoding="utf-8")
                with patch("app.content.USER_DIR", Path(folder)):
                    content = ContentIndex(None)
                self.assertIsInstance(content.notes, dict)
                self.assertTrue(all(isinstance(v, str) for v in content.notes.values()))
                if isinstance(raw, dict):
                    self.assertEqual(content.notes.get("lung"), "Keep this note")
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_progress_damage_does_not_break_read_or_future_visits(self):
        damaged = (None, [], {"lesson": "broken"},
                   {"lesson": {"seen": None, "last": None}},
                   {"lesson": {"seen": [{}, 0], "last": "broken"}},
                   {"lesson": {"practice": {"best": "broken", "sessions": None}}})
        for raw in damaged:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "lesson_progress.json"
                text = json.dumps(raw)
                path.write_text(text, encoding="utf-8")
                progress = LessonProgress(path)
                self.assertIsInstance(progress.seen("lesson"), set)
                self.assertIsInstance(progress.last_step("lesson"), int)
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                progress.visit("lesson", 1, 3)
                progress.record_practice("lesson", 2, 3)
                progress.set_done("lesson", 3)
                self.assertTrue(progress.is_done("lesson"))
                self.assertEqual(progress.seen("lesson"), {0, 1, 2})

    def test_quiz_damage_does_not_break_review_or_progress(self):
        damaged = (None, [], {"heart": "broken"},
                   {"heart": {"seen": "broken", "miss": None, "interval": float("nan"),
                              "ease": float("inf"), "history": None}})
        for raw in damaged:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "quiz_stats.json"
                text = json.dumps(raw)
                path.write_text(text, encoding="utf-8")
                with patch("app.ui.quiz.STATS_PATH", path):
                    quiz = QuizController(SimpleNamespace(ds=None, state=None))
                self.assertIsInstance(quiz.stats, dict)
                srs.summary(quiz.stats)
                srs.due_bases(quiz.stats)
                srs.weakest(quiz.stats)
                for stat in quiz.stats.values():
                    srs.update(stat, srs.GRADE_GOOD)
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_failed_notes_save_keeps_previous_file_and_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.json"
            original = '{"heart": "Original note"}'
            path.write_text(original, encoding="utf-8")
            content = ContentIndex.__new__(ContentIndex)
            content.notes_path = path
            content.notes = {"heart": "Original note"}
            write_text = Path.write_text

            def fail_target(candidate, text, *args, **kwargs):
                if candidate == path:
                    write_text(candidate, "{", encoding="utf-8")
                    raise OSError("fixture interrupted destination write")
                return write_text(candidate, text, *args, **kwargs)

            with patch.object(Path, "write_text", fail_target), \
                    patch.object(Path, "replace", side_effect=OSError("fixture replacement denied")):
                with self.assertRaises(OSError):
                    content.set_note("heart", "New note")
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(content.notes, {"heart": "Original note"})

    def test_failed_progress_and_quiz_save_keep_previous_files(self):
        for kind in ("progress", "quiz"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / f"{kind}.json"
                original = '{"original": {"seen": [0]}}' if kind == "progress" else '{"heart": {"seen": 1}}'
                path.write_text(original, encoding="utf-8")
                write_text = Path.write_text

                def fail_target(candidate, text, *args, **kwargs):
                    if candidate == path:
                        write_text(candidate, "{", encoding="utf-8")
                        raise OSError("fixture interrupted destination write")
                    return write_text(candidate, text, *args, **kwargs)

                with patch.object(Path, "write_text", fail_target), \
                        patch.object(Path, "replace", side_effect=OSError("fixture replacement denied")):
                    if kind == "progress":
                        progress = LessonProgress(path)
                        progress.visit("new", 1, 3)
                    else:
                        with patch("app.ui.quiz.STATS_PATH", path):
                            quiz = QuizController(SimpleNamespace(ds=None, state=None))
                            quiz.stats["new"] = {"seen": 2}
                            quiz.save_stats()
                self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
