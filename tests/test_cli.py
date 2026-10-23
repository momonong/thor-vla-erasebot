"""透過真實子程序核對 CLI 的 JSON、退出碼與檔案邊界。"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMAND = '{"schema_version":1,"fixture":true,"action":"erase","text":"apple","color":"red"}'
SCENE = '{"schema_version":1,"fixture":true,"coordinate_frame":"image","unit":"px","image_size":{"width":640,"height":480},"targets":[{"id":"word-1","text":"apple","color":"red","bbox":[20,30,120,70]}]}'


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "erasebot", *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=10)

    def check_json(self, completed, status, exit_code):
        self.assertEqual(completed.returncode, exit_code, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], status)
        self.assertIs(result["fixture"], True)
        self.assertIs(result["dry_run"], True)
        self.assertNotIn("motor", result)
        self.assertNotIn("actions", result)
        if status != "selected":
            self.assertIsNone(result["selected_target"])
        return result

    def run_documents(self, cmd=COMMAND, observed=SCENE):
        with tempfile.TemporaryDirectory() as directory:
            command_path, scene_path = Path(directory) / "command.json", Path(directory) / "scene.json"
            command_path.write_text(cmd, encoding="utf-8")
            scene_path.write_text(observed, encoding="utf-8")
            return self.run_cli("--command", command_path, "--scene", scene_path)

    def test_supplied_fixtures_are_executable(self):
        result = self.check_json(self.run_cli("--command", "fixtures/command.json", "--scene", "fixtures/scene.json"), "selected", 0)
        self.assertEqual(result["candidate_ids"], ["word-1"])

    def test_all_selection_statuses_have_distinct_exit_codes(self):
        self.check_json(self.run_documents(), "selected", 0)
        self.check_json(self.run_documents(cmd=COMMAND.replace("apple", "pear")), "no_match", 1)
        observed = json.loads(SCENE)
        observed["targets"].append({"id": "word-2", "text": "apple", "color": "red", "bbox": [150, 30, 250, 70]})
        result = self.check_json(self.run_documents(observed=json.dumps(observed)), "ambiguous", 2)
        self.assertEqual(result["candidate_ids"], ["word-1", "word-2"])
        self.check_json(self.run_documents(cmd="[]"), "invalid_input", 3)

    def test_missing_files_and_directory_inputs_return_read_diagnostics(self):
        for path in [ROOT / "fixtures" / "absent.json", ROOT / "fixtures"]:
            with self.subTest(path=path):
                result = self.check_json(self.run_cli("--command", path, "--scene", "fixtures/scene.json"), "invalid_input", 3)
                self.assertEqual(result["diagnostics"]["stage"], "read")
                self.assertEqual(result["diagnostics"]["errors"][0]["path"], "command")

    def test_invalid_utf8_returns_read_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_bytes(b"\xff")
            result = self.check_json(self.run_cli("--command", path, "--scene", "fixtures/scene.json"), "invalid_input", 3)
            self.assertEqual(result["diagnostics"]["stage"], "read")

    def test_malformed_json_duplicate_keys_and_nonfinite_constants_are_rejected(self):
        for document, cmd, observed in [
            ("command", "{", SCENE),
            ("command", COMMAND.replace('"text":"apple"', '"text":"pear","text":"apple"'), SCENE),
            ("scene", COMMAND, SCENE.replace('"width":640', '"width":640,"width":1')),
            ("scene", COMMAND, SCENE.replace("20,30", "NaN,30")),
            ("scene", COMMAND, SCENE.replace("20,30", "Infinity,30")),
            ("scene", COMMAND, SCENE.replace("20,30", "-Infinity,30")),
        ]:
            with self.subTest(command=cmd, scene=observed):
                result = self.check_json(self.run_documents(cmd, observed), "invalid_input", 3)
                self.assertEqual(result["diagnostics"]["stage"], "json")
                self.assertEqual(result["diagnostics"]["errors"][0]["path"], document)
                self.assertTrue(result["diagnostics"]["errors"][0]["message"])

    def test_overflowing_json_number_is_rejected_by_coordinate_validation(self):
        result = self.check_json(self.run_documents(observed=SCENE.replace("20,30", "1e999,30")), "invalid_input", 3)
        self.assertEqual(result["diagnostics"]["stage"], "validation")

    def test_schema_and_coordinate_errors_return_json_without_traceback(self):
        for observed in [SCENE.replace('"unit":"px"', '"unit":"mm"'), SCENE.replace("20,30", "-1,30")]:
            with self.subTest(scene=observed):
                result = self.check_json(self.run_documents(observed=observed), "invalid_input", 3)
                self.assertEqual(result["diagnostics"]["stage"], "validation")

    def test_argument_errors_return_invalid_input_json(self):
        for args in [[], ["--command", "fixtures/command.json"], ["--wat"],
                     ["--command", "fixtures/command.json", "--scene", "fixtures/scene.json", "--extra"]]:
            with self.subTest(args=args):
                result = self.check_json(self.run_cli(*args), "invalid_input", 3)
                self.assertEqual(result["diagnostics"]["stage"], "arguments")

    def test_help_is_human_readable(self):
        completed = self.run_cli("--help")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertIn("--command", completed.stdout)
        self.assertIn("--scene", completed.stdout)
        self.assertIn("dry-run", completed.stdout)


if __name__ == "__main__":
    unittest.main()
