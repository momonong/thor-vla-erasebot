import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import adapter


class SingleQuestionTests(unittest.TestCase):
    def test_single_payload_is_one_exact_question_without_mutating_original(self):
        data = adapter.load_runner().questions()
        original = copy.deepcopy(data)
        for image in data["images"]:
            for question in image["questions"]:
                selected = adapter.single_payload(data, image["id"], question["id"])
                self.assertEqual(sum(len(i["questions"]) for i in selected["images"]), 1)
                self.assertEqual(selected["images"][0]["questions"], [question])
                self.assertEqual(selected["task_conventions"], data["task_conventions"])
                selected["images"][0]["questions"][0]["instruction"] = "test mutation"
                self.assertEqual(data, original)

    def test_every_single_prompt_prefix_matches_first_round_bytes(self):
        for route in ("ocr_llm", "vlm"):
            for image in adapter.load_runner().questions()["images"]:
                old = adapter.old_run(route, image["id"]) / "prompt.txt"
                old_prefix = adapter.split_prompt(old.read_bytes())[0]
                for q in image["questions"]:
                    job = adapter.prepare_prompt(route, image["id"], q["id"])
                    prefix, suffix = adapter.split_prompt(job["prompt_bytes"])
                    self.assertEqual(prefix, old_prefix)
                    self.assertEqual(json.loads(suffix), [q])

    def test_invalid_or_cross_image_question_is_rejected(self):
        data = adapter.load_runner().questions()
        for image, qid in (("colour", "C-Q99"), ("colour", "F-Q1"), ("absent", "C-Q1")):
            with self.subTest(image=image, qid=qid), self.assertRaises(ValueError):
                adapter.single_payload(data, image, qid)

    def test_invalid_question_cli_does_not_create_run_or_generate(self):
        out = Path(__file__).resolve().parent / "invalid-qid-must-not-exist"
        self.assertFalse(out.exists())
        result = subprocess.run([sys.executable, "-B", str(adapter.HERE / "adapter.py"), "--route", "ocr_llm",
                                 "--image", "colour", "--question", "C-Q99", "--run-dir", str(out)],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("question", result.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
