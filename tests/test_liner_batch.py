"""批次契約、證據分母與不可信輸入邊界；由主機執行。"""

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from erasebot.selection import InputError
from liner_evaluation import evaluate
from tools.liner_batch import evaluate_batch, main, render_markdown


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "liner-evaluation"
ALL_CASES = ("clear", "partial", "folded", "unknown-fold", "wrong-target", "not-run")
STATUSES = ("criteria_met", "criteria_not_met", "insufficient_evidence", "invalid_input", "not_run")
MAX_BYTES = 2 * 1024 * 1024


class BatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Resolve the host's temp alias before constructing our manifest path.
        self.root = Path(temporary.name).resolve()
        for name in ("target", *ALL_CASES):
            shutil.copyfile(FIXTURES / (name + ".json"), self.root / (name + ".json"))
        self.path = self.root / "batch.json"

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
        return path

    def observation(self, name="clear"):
        return json.loads((self.root / (name + ".json")).read_text(encoding="utf-8"))

    def entry(self, name="clear", **updates):
        entry = {"case_id": name, "material": "A", "method": "fixed_script",
                 "target": "target.json", "observation": name + ".json"}
        entry.update(updates)
        return entry

    def manifest(self, names=("clear",), entries=None):
        document = {"schema_version": 1,
                    "entries": [self.entry(name) for name in names] if entries is None else entries}
        return self.write_json("batch.json", document)

    def assert_invalid_case(self, path):
        report = evaluate_batch(path)
        self.assertEqual(len(report["cases"]), 1)
        case = report["cases"][0]
        self.assertEqual(case["status"], "invalid_input")
        self.assertIsNone(case["result"])
        self.assertTrue(case["diagnostics"]["errors"])
        self.assertEqual(report["groups"][0]["total"], 1)
        self.assertEqual(report["groups"][0]["counts"]["invalid_input"], 1)
        self.assertIsNone(report["groups"][0]["success_rate"])
        return case

    def test_six_cases_preserved_with_original_results_and_hashes(self):
        report = evaluate_batch(self.manifest(ALL_CASES))
        self.assertEqual([case["case_id"] for case in report["cases"]], list(ALL_CASES))
        self.assertEqual(Counter(case["status"] for case in report["cases"]),
                         dict(zip(STATUSES, (1, 2, 1, 1, 1))))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["mode"], "offline")
        self.assertIs(report["robot_validated"], False)
        self.assertIs(report["source_references_verified"], False)
        self.assertTrue(report["limitations"])
        goal = json.loads((self.root / "target.json").read_text(encoding="utf-8"))
        for case in report["cases"]:
            self.assertEqual(case["evidence_kind"], "synthetic_fixture")
            for source in case["sources"].values():
                self.assertEqual(source["sha256"], hashlib.sha256(
                    (self.root / source["path"]).read_bytes()).hexdigest())
            if case["status"] == "invalid_input":
                self.assertTrue(case["diagnostics"]["errors"])
            else:
                self.assertEqual(case["result"], evaluate(goal, self.observation(case["case_id"])))
        group = report["groups"][0]
        self.assertEqual((group["total"], group["attempted"]), (6, 4))
        self.assertIsNone(group["success_rate"])
        # A serializable report must never carry nonfinite JSON numbers.
        json.dumps(report, allow_nan=False)

    def test_denominators_include_unknown_attempts_but_not_unrun_or_invalid(self):
        scenarios = [
            (("clear", "partial"), 2, 0.5),
            (("partial",), 1, 0.0),
            (("not-run",), 0, None),
            (("clear", "not-run"), 1, 1.0),
            (("clear", "unknown-fold"), 2, None),
            (("clear", "wrong-target"), 1, None),
        ]
        for names, attempted, rate in scenarios:
            with self.subTest(names=names):
                group = evaluate_batch(self.manifest(names))["groups"][0]
                self.assertEqual(group["total"], len(names))
                self.assertEqual(group["attempted"], attempted)
                self.assertEqual(group["success_rate"], rate)
                self.assertEqual(set(group["counts"]), set(STATUSES))
                self.assertEqual(sum(group["counts"].values()), len(names))

    def test_material_method_and_evidence_are_independent_and_sorted(self):
        annotation = self.observation()
        annotation["evidence_kind"] = "offline_annotation"
        self.write_json("annotation.json", annotation)
        entries = [self.entry(material="B"), self.entry(method="visual_feedback"),
                   self.entry(method="learned_policy"), self.entry(),
                   self.entry(case_id="annotation", observation="annotation.json")]
        annotation["case_id"] = "annotation"
        self.write_json("annotation.json", annotation)
        report = evaluate_batch(self.manifest(entries=entries))
        keys = [(group["material"], group["method"], group["evidence_kind"])
                for group in report["groups"]]
        self.assertEqual(len(keys), 5)
        self.assertEqual(keys, sorted(keys))
        self.assertEqual({key[2] for key in keys}, {"offline_annotation", "synthetic_fixture"})
        self.assertTrue(all(group["total"] == 1 for group in report["groups"]))
        reversed_report = evaluate_batch(self.manifest(entries=list(reversed(entries))))
        self.assertEqual(report["groups"], reversed_report["groups"])

    def test_unknown_provenance_group_retains_unreadable_case(self):
        report = evaluate_batch(self.manifest(entries=[self.entry(),
            self.entry("missing", observation="missing.json")]))
        self.assertEqual(len(report["cases"]), 2)
        self.assertEqual(len(report["groups"]), 2)
        unknown = report["groups"][0]
        self.assertIsNone(unknown["evidence_kind"])
        self.assertIsNone(unknown["success_rate"])
        self.assertEqual(unknown["counts"]["invalid_input"], 1)
        self.assertEqual(sum(group["total"] for group in report["groups"]), 2)

    def test_duplicates_and_identity_mismatch_reject_entire_batch(self):
        with self.assertRaises(InputError):
            evaluate_batch(self.manifest(entries=[self.entry(), self.entry()]))
        with self.assertRaises(InputError):
            evaluate_batch(self.manifest(entries=[self.entry(case_id="different")]))
        # Even a target read failure must not hide a readable wrong identity.
        with self.assertRaises(InputError):
            evaluate_batch(self.manifest(entries=[self.entry(case_id="different", target="missing.json")]))

    def test_invalid_evaluator_fields_remain_cases(self):
        for changes in ({"target_sha256": "0" * 64}, {"cycles": True},
                        {"evidence_kind": "real_robot"}, {"extra": 1}):
            with self.subTest(changes=changes):
                observation = self.observation()
                observation.update(changes)
                self.write_json("bad.json", observation)
                case = self.assert_invalid_case(self.manifest(entries=[self.entry(observation="bad.json")]))
                self.assertIsNotNone(case["sources"]["observation"]["sha256"])
                if "evidence_kind" in changes:
                    self.assertIsNone(case["evidence_kind"])

    def test_missing_identity_is_a_case_schema_error(self):
        observation = self.observation()
        del observation["case_id"]
        self.write_json("bad.json", observation)
        self.assert_invalid_case(self.manifest(entries=[self.entry(observation="bad.json")]))

    def test_manifest_schema_is_exact_and_bounded(self):
        good = {"schema_version": 1, "entries": [self.entry()]}
        invalid = [None, [], {}, dict(good, schema_version=True), dict(good, schema_version=1.0),
                   dict(good, schema_version=2), dict(good, extra=1), dict(good, entries=[]),
                   dict(good, entries={}), dict(good, entries=[self.entry()] * 2001)]
        for field, value in (("case_id", " \t"), ("case_id", 1), ("material", []),
                             ("material", "C"), ("method", None), ("method", "other"),
                             ("target", 1), ("observation", " ")):
            invalid.append(dict(good, entries=[dict(self.entry(), **{field: value})]))
        invalid.extend([dict(good, entries=[None]), dict(good, entries=[dict(self.entry(), extra=1)])])
        missing = self.entry()
        del missing["target"]
        invalid.append(dict(good, entries=[missing]))
        for document in invalid:
            with self.subTest(document=str(document)[:120]):
                with self.assertRaises(InputError):
                    evaluate_batch(self.write_json("batch.json", document))

    def test_json_duplicate_keys_nonfinite_and_invalid_utf8(self):
        manifest = json.dumps({"schema_version": 1, "entries": [self.entry()]})
        broken_manifests = ["{", manifest.replace('"schema_version": 1', '"schema_version": true'),
                            manifest.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                            manifest.replace('"case_id": "clear"', '"case_id": "clear", "case_id": "clear"')]
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            broken_manifests.append(manifest.replace('"schema_version": 1', '"schema_version": ' + value))
        for text in broken_manifests:
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(InputError):
                    evaluate_batch(self.path)
        original = json.dumps(self.observation())
        bad_cases = [original.replace('"cycles": 2', '"cycles": 2, "cycles": 3'), "{"]
        bad_cases.extend(original.replace('"duration_s": 30.0', '"duration_s": ' + value)
                         for value in ("NaN", "Infinity", "-Infinity", "1e999"))
        for text in bad_cases:
            with self.subTest(text=text):
                raw = text.encode("utf-8")
                (self.root / "bad.json").write_bytes(raw)
                case = self.assert_invalid_case(self.manifest(entries=[self.entry(observation="bad.json")]))
                self.assertEqual(case["diagnostics"]["stage"], "json")
                self.assertIsNone(case["evidence_kind"])
                self.assertEqual(case["sources"]["observation"]["sha256"], hashlib.sha256(raw).hexdigest())
        (self.root / "bad.json").write_bytes(b"\xff")
        self.assert_invalid_case(self.manifest(entries=[self.entry(observation="bad.json")]))

    def test_absolute_parent_and_nul_paths_reject_manifest(self):
        for path in (str(self.root / "target.json"), "../target.json", "sub/../target.json",
                     "a\x00b", "C:\\outside\\target.json", "..\\target.json", "."):
            for field in ("target", "observation"):
                with self.subTest(path=path, field=field):
                    with self.assertRaises(InputError):
                        evaluate_batch(self.manifest(entries=[dict(self.entry(), **{field: path})]))

    def test_nested_regular_files_are_allowed(self):
        nested = self.root / "nested"
        nested.mkdir()
        shutil.copyfile(self.root / "clear.json", nested / "clear.json")
        report = evaluate_batch(self.manifest(entries=[self.entry(observation="nested/clear.json")]))
        self.assertEqual(report["cases"][0]["status"], "criteria_met")

    def test_missing_directory_and_oversize_files_preserve_null_hash(self):
        (self.root / "directory").mkdir()
        (self.root / "huge.json").write_bytes(b" " * (MAX_BYTES + 1))
        for name in ("missing.json", "directory", "huge.json"):
            with self.subTest(name=name):
                case = self.assert_invalid_case(self.manifest(entries=[self.entry(observation=name)]))
                self.assertIsNone(case["sources"]["observation"]["sha256"])
                self.assertIsNone(case["evidence_kind"])
        with self.assertRaises(InputError):
            evaluate_batch(self.root / "huge.json")
        with self.assertRaises(InputError):
            evaluate_batch(self.root / "directory")

    def test_exact_size_limit_is_allowed_and_hashes_original_bytes(self):
        raw = (self.root / "clear.json").read_bytes()
        padded = raw + b" " * (MAX_BYTES - len(raw))
        (self.root / "padded.json").write_bytes(padded)
        report = evaluate_batch(self.manifest(entries=[self.entry(observation="padded.json")]))
        case = report["cases"][0]
        self.assertEqual(case["status"], "criteria_met")
        self.assertEqual(case["sources"]["observation"]["sha256"], hashlib.sha256(padded).hexdigest())
        self.assertNotEqual(case["sources"]["observation"]["sha256"], hashlib.sha256(raw).hexdigest())

    @unittest.skipUnless(os.name == "posix", "POSIX symlink boundary")
    def test_symlink_files_and_directories_are_rejected(self):
        self.manifest()
        (self.root / "linked.json").symlink_to(self.root / "clear.json")
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        outside = Path(external.name).resolve() / "clear.json"
        shutil.copyfile(self.root / "clear.json", outside)
        (self.root / "outside.json").symlink_to(outside)
        for name in ("linked.json", "alias/clear.json", "outside.json"):
            with self.subTest(name=name):
                case = self.assert_invalid_case(self.manifest(entries=[self.entry(observation=name)]))
                self.assertIsNone(case["sources"]["observation"]["sha256"])
        (self.root / "manifest-link.json").symlink_to(self.path)
        with self.assertRaises(InputError):
            evaluate_batch(self.root / "manifest-link.json")
        with self.assertRaises(InputError):
            evaluate_batch(self.root / "alias" / "batch.json")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_fifo_is_rejected_without_a_writer(self):
        fifo = self.root / "pipe.json"
        os.mkfifo(fifo)
        case = self.assert_invalid_case(self.manifest(entries=[self.entry(observation="pipe.json")]))
        self.assertIsNone(case["sources"]["observation"]["sha256"])
        with self.assertRaises(InputError):
            evaluate_batch(fifo)

    def call_main(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(arguments)
        self.assertEqual(errors.getvalue(), "")
        return code, output.getvalue()

    def test_cli_exit_codes_json_markdown_and_invalid_arguments(self):
        for names, expected in ((("clear",), 0), (("clear", "partial"), 1),
                                (("not-run",), 1), (("unknown-fold",), 1), (("wrong-target",), 1)):
            with self.subTest(names=names):
                path = self.manifest(names)
                code, output = self.call_main(["--manifest", str(path)])
                self.assertEqual(code, expected)
                self.assertEqual(len(output.splitlines()), 1)
                report = json.loads(output)
                self.assertEqual(report, evaluate_batch(path))
                code, markdown = self.call_main(["--manifest", str(path), "--format", "markdown"])
                self.assertEqual(code, expected)
                self.assertEqual(markdown, render_markdown(report))
        for arguments in ([], ["--manifest", str(self.root / "missing.json")],
                          ["--manifest", str(self.path), "--format", "html"],
                          ["--manifest", "bad\x00path"]):
            code, output = self.call_main(arguments)
            self.assertEqual(code, 3)
            self.assertEqual(len(output.splitlines()), 1)
            self.assertEqual(json.loads(output)["status"], "invalid_input")
            self.assertNotIn("Traceback", output)
        self.path.write_text("{", encoding="utf-8")
        code, output = self.call_main(["--manifest", str(self.path), "--format", "markdown"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output)["diagnostics"]["stage"], "json")

    def test_help_uses_normal_argparse_behavior(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--manifest", output.getvalue())

    def test_markdown_unknowns_escape_injection_and_do_not_mutate_report(self):
        report = evaluate_batch(self.manifest(ALL_CASES))
        original = deepcopy(report)
        markdown = render_markdown(report)
        self.assertEqual(report, original)
        self.assertEqual(markdown, render_markdown(report))
        self.assertIn("not_run", markdown)
        self.assertIn("unknown", markdown)
        self.assertNotIn("0%", markdown)
        self.assertIn("未實機驗證", markdown)
        for case in report["cases"]:
            self.assertIn(case["case_id"], markdown)
            self.assertIn(case["status"].replace("_", "\\_"), markdown)
        hostile = 'injected|cell\n<script>x</script>![x](https://example.invalid/a.png)'
        report["cases"][0]["case_id"] = hostile
        report["cases"][0]["sources"]["target"]["path"] = hostile
        report["limitations"].append(hostile)
        markdown = render_markdown(report)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("![x]", markdown)
        self.assertNotIn("injected|cell", markdown)
        self.assertNotIn("\n<script>", markdown)
        self.assertIn("injected\\|cell", markdown)
        self.assertIn("&lt;script&gt;", markdown)


if __name__ == "__main__":
    unittest.main()
