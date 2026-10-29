"""以真實 CLI 核對 fixture 重播帳本、比較及整份 suite 驗證。"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "fixtures/replay/suite.json"
COMMAND = {"schema_version": 1, "fixture": True, "action": "erase", "text": "apple", "color": "red"}
SCENE = {
    "schema_version": 1, "fixture": True, "coordinate_frame": "image", "unit": "px",
    "image_size": {"width": 640, "height": 480},
    "targets": [{"id": "word-1", "text": "apple", "color": "red", "bbox": [20, 30, 120, 70]}],
}
SELECTED = {"status": "selected", "selected_target_id": "word-1", "candidate_ids": ["word-1"],
            "diagnostic_stage": "selection", "error_paths": []}


def suite():
    return {"schema_version": 1, "fixture": True, "suite_id": "test-suite", "cases": [
        {"id": "single", "command": "command.json", "scene": "scene.json", "expected": copy.deepcopy(SELECTED)}
    ]}


class ReplayTests(unittest.TestCase):
    def run_cli(self, *args, timeout=10):
        return subprocess.run([sys.executable, "-m", "erasebot.replay", *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=timeout)

    def run_suite(self, document=None, command=COMMAND, scene=SCENE):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "command.json").write_text(json.dumps(command), encoding="utf-8")
            (base / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
            content = suite() if document is None else document
            (base / "suite.json").write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            return self.run_cli("--suite", base / "suite.json")

    def check_report(self, completed, status, exit_code):
        self.assertEqual(completed.returncode, exit_code, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        report = json.loads(completed.stdout, parse_constant=lambda value: self.fail(f"非法 JSON 常數 {value}"))
        self.assertEqual(report["schema_version"], 1)
        self.assertIs(report["fixture"], True)
        self.assertIs(report["dry_run"], True)
        self.assertEqual(report["evidence_kind"], "fixture_replay")
        self.assertEqual(report["status"], status)
        return report

    def test_single_case_cli_keeps_full_actual_result_and_input_snapshots(self):
        report = self.check_report(self.run_suite(), "passed", 0)
        self.assertEqual(report["suite_id"], "test-suite")
        self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0,
            "by_selector_status": {"selected": 1, "no_match": 0, "ambiguous": 0, "invalid_input": 0}})
        case = report["cases"][0]
        self.assertEqual(case["id"], "single")
        self.assertEqual((case["command"], case["scene"]), ("command.json", "scene.json"))
        self.assertEqual(case["inputs"], {"command": COMMAND, "scene": SCENE})
        self.assertEqual(case["expected"], SELECTED)
        self.assertIs(case["passed"], True)
        self.assertEqual(case["mismatches"], [])
        self.assertEqual(case["actual"], {
            "schema_version": 1, "fixture": True, "dry_run": True, "status": "selected",
            "selected_target": {"id": "word-1", "text": "apple", "color": "red", "bbox": [20, 30, 120, 70]},
            "candidate_ids": ["word-1"],
            "coordinates": {"coordinate_frame": "image", "unit": "px", "image_size": {"width": 640, "height": 480}},
            "diagnostics": {"stage": "selection", "target_count": 1, "candidate_count": 1, "errors": []},
        })

    def test_five_hand_authored_cases_account_for_all_four_selector_statuses(self):
        report = self.check_report(self.run_cli("--suite", DEMO), "passed", 0)
        self.assertEqual(report["summary"], {"total": 5, "passed": 5, "failed": 0,
            "by_selector_status": {"selected": 1, "no_match": 1, "ambiguous": 1, "invalid_input": 2}})
        expected = [
            ("replay-selected", "selected", "word-1", ["word-1"], "selection", []),
            ("replay-no-match", "no_match", None, [], "selection", []),
            ("replay-ambiguous", "ambiguous", None, ["apple-a", "apple-b"], "selection", []),
            ("replay-invalid-bbox", "invalid_input", None, [], "validation", ["scene.targets[1].bbox"]),
            ("replay-invalid-command", "invalid_input", None, [], "validation", ["command.text"]),
        ]
        for case, (identifier, status, selected, candidates, stage, paths) in zip(report["cases"], expected, strict=True):
            with self.subTest(case=identifier):
                self.assertEqual(case["id"], identifier)
                self.assertEqual(case["expected"], {"status": status, "selected_target_id": selected,
                    "candidate_ids": candidates, "diagnostic_stage": stage, "error_paths": paths})
                actual = case["actual"]
                self.assertEqual(actual["status"], status)
                self.assertEqual(actual["candidate_ids"], candidates)
                self.assertEqual(actual["diagnostics"]["stage"], stage)
                self.assertEqual([error["path"] for error in actual["diagnostics"]["errors"]], paths)
                self.assertEqual(actual["selected_target"]["id"] if selected else actual["selected_target"], selected)
                self.assertEqual(set(actual), {"schema_version", "fixture", "dry_run", "status", "selected_target",
                                              "candidate_ids", "coordinates", "diagnostics"})
                self.assertIs(case["passed"], True)
                self.assertEqual(case["mismatches"], [])
        self.assertEqual(report["cases"][0]["actual"]["selected_target"]["bbox"], [20, 30, 120, 70])
        self.assertIsNone(report["cases"][3]["actual"]["coordinates"])
        self.assertEqual(report["cases"][3]["inputs"]["scene"]["targets"][0]["id"], "valid-apple")

    def test_wrong_selected_id_and_candidate_order_are_mismatches(self):
        document = suite()
        document["cases"][0]["expected"].update(selected_target_id="wrong", candidate_ids=["wrong"])
        report = self.check_report(self.run_suite(document), "failed", 1)
        self.assertEqual(report["cases"][0]["mismatches"], [
            {"field": "selected_target_id", "expected": "wrong", "actual": "word-1"},
            {"field": "candidate_ids", "expected": ["wrong"], "actual": ["word-1"]},
        ])
        observed = copy.deepcopy(SCENE)
        observed["targets"].append({"id": "word-2", "text": "apple", "color": "red", "bbox": [150, 30, 250, 70]})
        document["cases"][0]["expected"] = {"status": "ambiguous", "selected_target_id": None,
            "candidate_ids": ["word-2", "word-1"], "diagnostic_stage": "selection", "error_paths": []}
        report = self.check_report(self.run_suite(document, scene=observed), "failed", 1)
        self.assertEqual(report["cases"][0]["mismatches"], [
            {"field": "candidate_ids", "expected": ["word-2", "word-1"], "actual": ["word-1", "word-2"]}])

    def test_failed_middle_case_does_not_drop_later_cases(self):
        document = suite()
        middle = copy.deepcopy(document["cases"][0])
        middle["id"] = "middle"
        middle["expected"] = {"status": "no_match", "selected_target_id": None,
                              "candidate_ids": [], "diagnostic_stage": "selection", "error_paths": []}
        last = copy.deepcopy(document["cases"][0])
        last["id"] = "last"
        document["cases"].extend([middle, last])
        report = self.check_report(self.run_suite(document), "failed", 1)
        self.assertEqual([case["id"] for case in report["cases"]], ["single", "middle", "last"])
        self.assertEqual([case["passed"] for case in report["cases"]], [True, False, True])
        self.assertEqual(report["summary"], {"total": 3, "passed": 2, "failed": 1,
            "by_selector_status": {"selected": 3, "no_match": 0, "ambiguous": 0, "invalid_input": 0}})
        self.assertEqual([item["field"] for item in report["cases"][1]["mismatches"]],
                         ["status", "selected_target_id", "candidate_ids"])

    def test_missing_file_cannot_satisfy_an_expected_validation_failure(self):
        document = suite()
        document["cases"][0]["scene"] = "absent.json"
        document["cases"][0]["expected"] = {"status": "invalid_input", "selected_target_id": None,
            "candidate_ids": [], "diagnostic_stage": "validation", "error_paths": ["scene.targets[1].bbox"]}
        report = self.check_report(self.run_suite(document), "failed", 1)
        case = report["cases"][0]
        self.assertEqual(case["inputs"], {"command": COMMAND, "scene": None})
        self.assertEqual(case["actual"]["diagnostics"]["stage"], "read")
        self.assertEqual(case["mismatches"], [
            {"field": "diagnostic_stage", "expected": "validation", "actual": "read"},
            {"field": "error_paths", "expected": ["scene.targets[1].bbox"], "actual": ["scene"]}])
        self.assertEqual(report["summary"]["total"], 1)
        document["cases"][0]["expected"].update(diagnostic_stage="read", error_paths=["scene"])
        self.check_report(self.run_suite(document), "passed", 0)

    def test_case_json_failures_remain_in_ledger_with_null_unloaded_snapshot(self):
        document = suite()
        document["cases"][0]["expected"] = {"status": "invalid_input", "selected_target_id": None,
            "candidate_ids": [], "diagnostic_stage": "json", "error_paths": ["scene"]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "command.json").write_text(json.dumps(COMMAND), encoding="utf-8")
            (base / "scene.json").write_text('{"fixture": true, "fixture": true}', encoding="utf-8")
            (base / "suite.json").write_text(json.dumps(document), encoding="utf-8")
            report = self.check_report(self.run_cli("--suite", base / "suite.json"), "passed", 0)
        self.assertEqual(report["cases"][0]["inputs"], {"command": COMMAND, "scene": None})
        self.assertEqual(report["cases"][0]["actual"]["diagnostics"]["stage"], "json")

    def test_paths_resolve_from_suite_parent_including_dot_dot(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "nested").mkdir()
            (base / "command.json").write_text(json.dumps(COMMAND), encoding="utf-8")
            (base / "scene.json").write_text(json.dumps(SCENE), encoding="utf-8")
            document = suite()
            document["cases"][0].update(command="../command.json", scene="../scene.json")
            (base / "nested/suite.json").write_text(json.dumps(document), encoding="utf-8")
            report = self.check_report(self.run_cli("--suite", base / "nested/suite.json"), "passed", 0)
        self.assertEqual(report["cases"][0]["command"], "../command.json")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "需要 POSIX FIFO")
    def test_fifo_suite_and_symlink_fail_as_read_before_any_case_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo, link = Path(directory) / "suite.json", Path(directory) / "link.json"
            os.mkfifo(fifo)
            link.symlink_to(fifo)
            for path in (fifo, link):
                with self.subTest(path=path.name):
                    try:
                        completed = self.run_cli("--suite", path, timeout=1)
                    except subprocess.TimeoutExpired:
                        self.fail("FIFO suite 阻塞超過 1 秒；子程序已終止並回收")
                    report = self.check_report(completed, "invalid_suite", 2)
                    self.assertEqual(report["diagnostics"]["stage"], "read")
                    self.assertEqual([error["path"] for error in report["diagnostics"]["errors"]], ["suite"])
                    self.assertEqual(report["cases"], [])
                    self.assertEqual(report["summary"]["total"], 0)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "需要 POSIX FIFO")
    def test_fifo_case_read_results_keep_later_cases_and_mismatched_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            os.mkfifo(base / "blocked.json")
            (base / "link.json").symlink_to(base / "blocked.json")
            (base / "command.json").write_text(json.dumps(COMMAND), encoding="utf-8")
            (base / "scene.json").write_text(json.dumps(SCENE), encoding="utf-8")
            for field in ("command", "scene"):
                for filename in ("blocked.json", "link.json"):
                    for expected_stage in ("read", "validation"):
                        with self.subTest(field=field, filename=filename, expected_stage=expected_stage):
                            document = suite()
                            document["cases"][0].update(id="blocked-input", expected={"status": "invalid_input",
                                "selected_target_id": None, "candidate_ids": [], "diagnostic_stage": expected_stage,
                                "error_paths": [field]})
                            document["cases"][0][field] = filename
                            document["cases"].append({"id": "later-valid", "command": "command.json", "scene": "scene.json",
                                                      "expected": copy.deepcopy(SELECTED)})
                            path = base / "suite.json"
                            path.write_text(json.dumps(document), encoding="utf-8")
                            try:
                                completed = self.run_cli("--suite", path, timeout=1)
                            except subprocess.TimeoutExpired:
                                self.fail("FIFO case 阻塞超過 1 秒；子程序已終止並回收")
                            passed = expected_stage == "read"
                            report = self.check_report(completed, "passed" if passed else "failed", 0 if passed else 1)
                            self.assertEqual(report["summary"], {"total": 2, "passed": 2 if passed else 1,
                                "failed": 0 if passed else 1, "by_selector_status": {
                                    "selected": 1, "no_match": 0, "ambiguous": 0, "invalid_input": 1}})
                            first, later = report["cases"]
                            self.assertEqual([first["id"], later["id"]], ["blocked-input", "later-valid"])
                            self.assertEqual(first["actual"]["status"], "invalid_input")
                            self.assertEqual(first["actual"]["diagnostics"]["stage"], "read")
                            self.assertEqual([error["path"] for error in first["actual"]["diagnostics"]["errors"]], [field])
                            self.assertIsNone(first["inputs"][field])
                            self.assertEqual(first["mismatches"], [] if passed else [
                                {"field": "diagnostic_stage", "expected": "validation", "actual": "read"}])
                            self.assertIs(later["passed"], True)
                            self.assertEqual(later["actual"]["selected_target"]["id"], "word-1")

    @unittest.skipUnless(os.name == "posix", "本輪只驗證 POSIX symlink")
    def test_regular_file_symlinks_work_for_suite_and_case_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for field, content in (("command", COMMAND), ("scene", SCENE)):
                (base / f"{field}.json").write_text(json.dumps(content), encoding="utf-8")
                (base / f"{field}-link.json").symlink_to(base / f"{field}.json")
            document = suite()
            document["cases"][0].update(command="command-link.json", scene="scene-link.json")
            (base / "suite.json").write_text(json.dumps(document), encoding="utf-8")
            (base / "suite-link.json").symlink_to(base / "suite.json")
            report = self.check_report(self.run_cli("--suite", base / "suite-link.json"), "passed", 0)
            self.assertEqual(report["cases"][0]["inputs"], {"command": COMMAND, "scene": SCENE})

    def test_structurally_invalid_suites_execute_no_cases(self):
        invalid = [None, [], {}, {**suite(), "cases": []}, {**suite(), "cases": "bad"},
                   {**suite(), "fixture": 1}, {**suite(), "schema_version": True},
                   {**suite(), "schema_version": 1.0}, {**suite(), "suite_id": " "},
                   {**suite(), "extra": True}]
        for field in ("schema_version", "fixture", "suite_id", "cases"):
            document = suite()
            del document[field]
            invalid.append(document)
        for field, value in [("id", " "), ("command", ""), ("scene", 3), ("command", "/tmp/command.json"),
                             ("scene", "bad\x00.json"), ("extra", True), ("expected", [])]:
            document = suite()
            document["cases"][0][field] = value
            invalid.append(document)
        for field in ("id", "command", "scene", "expected"):
            document = suite()
            del document["cases"][0][field]
            invalid.append(document)
        for field, value in [("status", "unknown"), ("selected_target_id", None), ("selected_target_id", " "),
                             ("candidate_ids", "word-1"), ("candidate_ids", [" "]),
                             ("candidate_ids", ["word-1", "word-1"]), ("diagnostic_stage", "arguments"),
                             ("error_paths", [""]), ("error_paths", "command"), ("extra", None),
                             ("diagnostic_stage", "read"), ("error_paths", ["command.text"])]:
            document = suite()
            document["cases"][0]["expected"][field] = value
            invalid.append(document)
        for field in SELECTED:
            document = suite()
            del document["cases"][0]["expected"][field]
            invalid.append(document)
        for expected in [
            {"status": "selected", "selected_target_id": "other", "candidate_ids": ["word-1"], "diagnostic_stage": "selection", "error_paths": []},
            {"status": "no_match", "selected_target_id": None, "candidate_ids": ["word-1"], "diagnostic_stage": "selection", "error_paths": []},
            {"status": "ambiguous", "selected_target_id": None, "candidate_ids": ["word-1"], "diagnostic_stage": "selection", "error_paths": []},
            {"status": "invalid_input", "selected_target_id": None, "candidate_ids": [], "diagnostic_stage": "selection", "error_paths": ["command"]},
            {"status": "invalid_input", "selected_target_id": None, "candidate_ids": [], "diagnostic_stage": "validation", "error_paths": []},
        ]:
            document = suite()
            document["cases"][0]["expected"] = expected
            invalid.append(document)
        duplicate = suite()
        duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
        invalid.append(duplicate)
        late_invalid = suite()
        late_invalid["cases"][0]["scene"] = "missing.json"
        late_invalid["cases"].append({"id": "late-invalid"})
        invalid.append(late_invalid)
        for document in invalid:
            with self.subTest(document=document):
                # JSON null must not select the helper's default suite.
                report = self.check_report(self.run_suite(json.dumps(document)), "invalid_suite", 2)
                self.assertEqual(report["cases"], [])
                self.assertEqual(report["summary"]["total"], 0)
                self.assertEqual(report["diagnostics"]["stage"], "validation")
                self.assertTrue(report["diagnostics"]["errors"])

    def test_suite_read_json_and_argument_failures_are_structured(self):
        for args, stage in [([], "arguments"), (["--wat"], "arguments"), (["--suite"], "arguments"),
                            (["--suite", DEMO, "--extra"], "arguments"),
                            (["--suite", ROOT / "fixtures/replay/absent.json"], "read")]:
            with self.subTest(args=args):
                report = self.check_report(self.run_cli(*args), "invalid_suite", 2)
                self.assertEqual(report["diagnostics"]["stage"], stage)
                self.assertEqual(report["cases"], [])
        raw = json.dumps(suite())
        for content in ["{", raw.replace('"fixture": true', '"fixture": true, "fixture": true'),
                        raw.replace('"status": "selected"', '"status": "selected", "status": "selected"'),
                        *[raw.replace('"schema_version": 1', f'"schema_version": {value}')
                          for value in ("NaN", "Infinity", "-Infinity")]]:
            with self.subTest(content=content):
                report = self.check_report(self.run_suite(content), "invalid_suite", 2)
                self.assertEqual(report["diagnostics"]["stage"], "json")
                self.assertEqual(report["cases"], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suite.json"
            path.write_bytes(b"\xff")
            report = self.check_report(self.run_cli("--suite", path), "invalid_suite", 2)
            self.assertEqual(report["diagnostics"]["stage"], "read")

    def test_nonfinite_parsed_snapshot_is_explicit_without_breaking_report_json(self):
        document = suite()
        document["cases"][0]["expected"] = {"status": "invalid_input", "selected_target_id": None,
            "candidate_ids": [], "diagnostic_stage": "validation", "error_paths": ["scene.targets[0].bbox[0]"]}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "command.json").write_text(json.dumps(COMMAND), encoding="utf-8")
            (base / "scene.json").write_text(json.dumps(SCENE).replace("20, 30", "1e999, 30"), encoding="utf-8")
            (base / "suite.json").write_text(json.dumps(document), encoding="utf-8")
            report = self.check_report(self.run_cli("--suite", base / "suite.json"), "passed", 0)
        case = report["cases"][0]
        self.assertIsNone(case["inputs"]["scene"])
        self.assertEqual(case["inputs"]["command"], COMMAND)
        self.assertEqual(case["snapshot_diagnostics"], [{"input": "scene", "reason": "nonfinite_number"}])
        self.assertEqual(case["actual"]["status"], "invalid_input")

    def test_deep_snapshot_cannot_drop_validation_diagnostics_or_later_cases(self):
        document = suite()
        document["cases"][0].update(id="deep-input", command="deep-command.json", expected={
            "status": "invalid_input", "selected_target_id": None, "candidate_ids": [],
            "diagnostic_stage": "validation", "error_paths": ["command.extra"]})
        document["cases"].append({"id": "later-valid", "command": "command.json", "scene": "scene.json",
                                  "expected": copy.deepcopy(SELECTED)})
        # Python 3.12.3 可載入且單獨編碼此 snapshot；嵌入整份報告後原本超過 encoder 邊界。
        depth = 9990
        raw_command = json.dumps(COMMAND)[:-1] + ', "extra": ' + '[' * depth + '0' + ']' * depth + '}'
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "deep-command.json").write_text(raw_command, encoding="utf-8")
            (base / "command.json").write_text(json.dumps(COMMAND), encoding="utf-8")
            (base / "scene.json").write_text(json.dumps(SCENE), encoding="utf-8")
            (base / "suite.json").write_text(json.dumps(document), encoding="utf-8")
            report = self.check_report(self.run_cli("--suite", base / "suite.json"), "passed", 0)
        self.assertEqual(report["summary"], {"total": 2, "passed": 2, "failed": 0,
            "by_selector_status": {"selected": 1, "no_match": 0, "ambiguous": 0, "invalid_input": 1}})
        first, later = report["cases"]
        self.assertEqual([first["id"], later["id"]], ["deep-input", "later-valid"])
        self.assertEqual(first["actual"]["status"], "invalid_input")
        self.assertEqual(first["actual"]["diagnostics"]["stage"], "validation")
        self.assertEqual([error["path"] for error in first["actual"]["diagnostics"]["errors"]], ["command.extra"])
        self.assertIsNone(first["inputs"]["command"])
        self.assertEqual(first["inputs"]["scene"], SCENE)
        self.assertEqual(first["snapshot_diagnostics"], [{"input": "command", "reason": "excessive_nesting"}])
        self.assertEqual(first["mismatches"], [])
        self.assertEqual(later["inputs"], {"command": COMMAND, "scene": SCENE})
        self.assertEqual(later["actual"]["selected_target"]["id"], "word-1")
        self.assertEqual(later["snapshot_diagnostics"], [])

    def test_identical_input_produces_identical_output_and_help_is_readable(self):
        first = self.run_cli("--suite", DEMO)
        self.check_report(first, "passed", 0)
        second = self.run_cli("--suite", DEMO)
        self.check_report(second, "passed", 0)
        self.assertEqual(first.stdout, second.stdout)
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertEqual(help_result.stderr, "")
        self.assertIn("--suite", help_result.stdout)
        self.assertIn("fixture", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
