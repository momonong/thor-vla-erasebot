"""保護襯材評分的算式、證據與 CLI 邊界；不含硬體動作。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def target(rows=None):
    return {"schema_version": 1, "target_id": "A", "frame_id": "table-1",
            "mask_rows": rows or ["1100", "1100"]}


def document_hash(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def observation(goal):
    return {"schema_version": 1, "case_id": "example", "evidence_kind": "synthetic_fixture",
            "source_ref": "hand-authored fixture, not a photograph", "target_id": goal["target_id"],
            "target_sha256": document_hash(goal), "frame_id": goal["frame_id"],
            "mask_rows": list(goal["mask_rows"]),
            "fold_check": {"status": "clear", "reference": "fixture assumption"},
            "duration_s": 30.0, "cycles": 2, "human_interventions": 0, "execution_status": "completed"}


class LinerEvaluationTests(unittest.TestCase):
    def evaluate(self, goal, seen):
        # 延後 import，缺少模組時以可讀的 assertion 呈現 RED。
        try:
            from liner_evaluation import evaluate
        except ImportError:
            self.fail("缺少襯材評估功能 liner_evaluation.evaluate")
        return evaluate(goal, seen)

    def assert_invalid(self, goal, seen):
        from erasebot.selection import InputError
        with self.assertRaises(InputError):
            self.evaluate(goal, seen)

    def test_full_overlap_meets_only_offline_criteria(self):
        goal = target()
        result = self.evaluate(goal, observation(goal))
        self.assertEqual(result["status"], "criteria_met")
        self.assertEqual(result["metrics"]["coverage"], 1)
        self.assertEqual(result["metrics"]["iou"], 1)
        self.assertIs(result["robot_validated"], False)
        self.assertIs(result["source_references_verified"], False)
        self.assertEqual(result["evidence_kind"], "synthetic_fixture")

    def test_intersection_union_and_false_positive_area_are_hand_checked(self):
        goal = target()
        seen = observation(goal)
        seen["mask_rows"] = ["1110", "1000"]
        result = self.evaluate(goal, seen)
        self.assertEqual(result["metrics"], {"target_area_px": 4, "observed_area_px": 4,
                         "intersection_px": 3, "union_px": 5, "coverage": 0.75, "iou": 0.6})
        self.assertEqual(result["status"], "criteria_not_met")

    def test_exact_thresholds_are_inclusive_and_just_below_fails(self):
        for goal_rows, seen_rows, expected in [
            (["1" * 20], ["1" * 19 + "0"], "criteria_met"),
            (["1" * 20], ["1" * 18 + "00"], "criteria_not_met"),
            (["1" * 9 + "0"], ["1" * 10], "criteria_met"),
            (["1" * 9 + "00"], ["1" * 11], "criteria_not_met"),
        ]:
            with self.subTest(goal=goal_rows, seen=seen_rows):
                goal = target(goal_rows)
                seen = observation(goal)
                seen["mask_rows"] = seen_rows
                self.assertEqual(self.evaluate(goal, seen)["status"], expected)

    def test_full_area_does_not_hide_fold_or_missing_fold_evidence(self):
        goal = target()
        for fold, expected in [("folded", "criteria_not_met"), ("unknown", "insufficient_evidence")]:
            with self.subTest(fold=fold):
                seen = observation(goal)
                seen["fold_check"] = {"status": fold, "reference": None if fold == "unknown" else "fixture fold"}
                self.assertEqual(self.evaluate(goal, seen)["status"], expected)

    def test_missing_mask_or_measurements_never_turn_into_zero_or_success(self):
        goal = target()
        for field in ("mask_rows", "duration_s", "cycles", "human_interventions"):
            with self.subTest(field=field):
                seen = observation(goal)
                seen[field] = None
                result = self.evaluate(goal, seen)
                self.assertEqual(result["status"], "insufficient_evidence")
                if field == "mask_rows":
                    self.assertIsNone(result["metrics"])

    def test_time_cycle_and_intervention_limits(self):
        goal = target()
        for values, expected in [
            ({"duration_s": 90, "cycles": 6}, "criteria_met"),
            ({"duration_s": 90.01}, "criteria_not_met"),
            ({"cycles": 7}, "criteria_not_met"),
            ({"human_interventions": 1}, "criteria_not_met"),
        ]:
            with self.subTest(values=values):
                seen = observation(goal)
                seen.update(values)
                self.assertEqual(self.evaluate(goal, seen)["status"], expected)

    def test_known_failure_remains_failure_even_when_other_evidence_is_unknown(self):
        goal = target()
        seen = observation(goal)
        seen.update(duration_s=91, mask_rows=None)
        result = self.evaluate(goal, seen)
        self.assertEqual(result["status"], "criteria_not_met")
        self.assertIn("duration_s", result["failed_checks"])
        self.assertIn("coverage", result["missing_evidence"])

    def test_not_run_aborted_and_failed_are_not_success(self):
        goal = target()
        for status in ("failed", "aborted"):
            seen = observation(goal)
            seen["execution_status"] = status
            self.assertEqual(self.evaluate(goal, seen)["status"], "criteria_not_met")
        seen = observation(goal)
        seen.update(execution_status="not_run", mask_rows=None, duration_s=None,
                    cycles=None, human_interventions=None,
                    fold_check={"status": "unknown", "reference": None})
        result = self.evaluate(goal, seen)
        self.assertEqual(result["status"], "not_run")
        self.assertIsNone(result["metrics"])
        seen["duration_s"] = 0
        self.assert_invalid(goal, seen)

    def test_empty_observed_mask_is_a_failure_but_empty_target_is_invalid(self):
        goal = target()
        seen = observation(goal)
        seen["mask_rows"] = ["0000", "0000"]
        self.assertEqual(self.evaluate(goal, seen)["status"], "criteria_not_met")
        goal["mask_rows"] = ["0000", "0000"]
        self.assert_invalid(goal, observation(goal))

    def test_changed_target_id_frame_or_fingerprint_is_rejected(self):
        goal = target()
        for field, value in [("target_id", "B"), ("frame_id", "other-table"), ("target_sha256", "0" * 64)]:
            seen = observation(goal)
            seen[field] = value
            self.assert_invalid(goal, seen)
        seen = observation(goal)
        goal["mask_rows"] = ["1110", "1100"]
        self.assert_invalid(goal, seen)

    def test_real_robot_claim_is_rejected_and_offline_annotations_keep_provenance(self):
        goal = target()
        seen = observation(goal)
        seen["evidence_kind"] = "real_robot"
        self.assert_invalid(goal, seen)
        seen.update(evidence_kind="offline_annotation", source_ref="local/photo-01.png")
        result = self.evaluate(goal, seen)
        self.assertEqual(result["source_ref"], "local/photo-01.png")
        self.assertFalse(result["robot_validated"])

    def test_strict_schema_and_numerical_validation(self):
        goal = target()
        for field, value in [
            ("schema_version", True), ("evidence_kind", []), ("source_ref", " "),
            ("duration_s", True), ("duration_s", float("inf")), ("duration_s", -1),
            ("cycles", 1.5), ("cycles", True), ("human_interventions", -1),
            ("execution_status", "unknown"), ("mask_rows", ["111"]),
            ("mask_rows", ["1111", "10x1"]), ("mask_rows", []),
            ("fold_check", {"status": "clear", "reference": None}),
        ]:
            with self.subTest(field=field, value=value):
                seen = observation(goal)
                seen[field] = value
                self.assert_invalid(goal, seen)
        for doc_key in ("target", "observation"):
            g, o = deepcopy(goal), observation(goal)
            (g if doc_key == "target" else o)["unexpected"] = "not permitted"
            self.assert_invalid(g, o)


class LinerCliTests(unittest.TestCase):
    def run_cli(self, goal, seen=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.json").write_text(json.dumps(goal), encoding="utf-8")
            args = [sys.executable, "-B", "-m", "liner_evaluation", "--target", str(root / "target.json")]
            if seen is not None:
                (root / "observation.json").write_text(seen if isinstance(seen, str) else json.dumps(seen), encoding="utf-8")
                args.extend(["--observation", str(root / "observation.json")])
            result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.stderr, "", result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), 1)
            return result.returncode, json.loads(result.stdout)

    def test_target_info_is_stable_and_matches_observation_binding(self):
        goal = target()
        code, result = self.run_cli(goal)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "target_info")
        self.assertEqual(result["target"]["sha256"], document_hash(goal))

    def test_cli_verdict_exit_codes_and_no_motion_payload(self):
        goal = target()
        for updates, status, code in [
            ({}, "criteria_met", 0),
            ({"cycles": 7}, "criteria_not_met", 1),
            ({"duration_s": None}, "insufficient_evidence", 2),
            ({"cycles": True}, "invalid_input", 3),
            ({"execution_status": "not_run", "mask_rows": None, "duration_s": None,
              "cycles": None, "human_interventions": None,
              "fold_check": {"status": "unknown", "reference": None}}, "not_run", 4),
        ]:
            with self.subTest(status=status):
                seen = observation(goal)
                seen.update(updates)
                actual_code, result = self.run_cli(goal, seen)
                self.assertEqual(actual_code, code)
                self.assertEqual(result["status"], status)
                self.assertIs(result["robot_validated"], False)
                self.assertNotIn("actions", result)
                self.assertNotIn("motor", result)

    def test_cli_rejects_duplicate_keys_nonfinite_and_bad_json(self):
        goal = target()
        text = json.dumps(observation(goal))
        for broken in ["{", text.replace('"cycles": 2', '"cycles": 2, "cycles": 3'),
                       text.replace('"duration_s": 30.0', '"duration_s": NaN')]:
            with self.subTest(broken=broken):
                code, result = self.run_cli(goal, broken)
                self.assertEqual(code, 3)
                self.assertEqual(result["diagnostics"]["stage"], "json")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_fifo_input_is_rejected_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "input.json"
            os.mkfifo(fifo)
            result = subprocess.run([sys.executable, "-B", "-m", "liner_evaluation", "--target", str(fifo)],
                                    cwd=ROOT, text=True, capture_output=True, timeout=2)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)["diagnostics"]["stage"], "read")


if __name__ == "__main__":
    unittest.main()
