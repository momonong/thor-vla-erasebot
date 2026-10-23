"""目標比對與整份輸入驗證的行為契約。"""

import copy
import unittest

from erasebot.selection import select_target


def command():
    return {"schema_version": 1, "fixture": True, "action": "erase", "text": "apple", "color": "red"}


def scene():
    return {
        "schema_version": 1,
        "fixture": True,
        "coordinate_frame": "image",
        "unit": "px",
        "image_size": {"width": 640, "height": 480},
        "targets": [
            {"id": "word-1", "text": "apple", "color": "red", "bbox": [20, 30, 120, 70]},
            {"id": "word-2", "text": "apple", "color": "green", "bbox": [150, 30, 250, 70]},
            {"id": "word-3", "text": "pear", "color": "red", "bbox": [20, 100, 120, 140]},
        ],
    }


class SelectionTests(unittest.TestCase):
    def assert_invalid(self, cmd, observed, path):
        result = select_target(cmd, observed)
        self.assertEqual(result["status"], "invalid_input")
        self.assertIsNone(result["selected_target"])
        self.assertEqual(result["candidate_ids"], [])
        self.assertEqual(result["diagnostics"]["stage"], "validation")
        self.assertTrue(any(error["path"] == path for error in result["diagnostics"]["errors"]), result)

    def test_unique_match_reports_image_coordinates_and_counts(self):
        result = select_target(command(), scene())
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_target"]["id"], "word-1")
        self.assertEqual(result["selected_target"]["bbox"], [20, 30, 120, 70])
        self.assertEqual(result["candidate_ids"], ["word-1"])
        self.assertEqual(result["coordinates"], {
            "coordinate_frame": "image", "unit": "px", "image_size": {"width": 640, "height": 480}
        })
        self.assertEqual(result["diagnostics"], {
            "stage": "selection", "target_count": 3, "candidate_count": 1, "errors": []
        })
        self.assertIs(result["fixture"], True)
        self.assertIs(result["dry_run"], True)
        self.assertEqual(result["schema_version"], 1)

    def test_text_and_color_match_exactly_without_normalization(self):
        for field, value in [("text", "Apple"), ("text", "apple "), ("text", "蘋果"), ("color", "Red")]:
            with self.subTest(field=field, value=value):
                cmd = command()
                cmd[field] = value
                result = select_target(cmd, scene())
                self.assertEqual(result["status"], "no_match")
                self.assertIsNone(result["selected_target"])
                self.assertEqual(result["candidate_ids"], [])

    def test_empty_scene_returns_no_match(self):
        observed = scene()
        observed["targets"] = []
        result = select_target(command(), observed)
        self.assertEqual(result["status"], "no_match")
        self.assertEqual(result["diagnostics"]["target_count"], 0)
        self.assertEqual(result["diagnostics"]["candidate_count"], 0)
        self.assertIsNone(result["selected_target"])

    def test_multiple_matches_return_all_ids_without_selection(self):
        observed = scene()
        observed["targets"][1]["color"] = "red"
        result = select_target(command(), observed)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["candidate_ids"], ["word-1", "word-2"])
        self.assertEqual(result["diagnostics"]["candidate_count"], 2)
        self.assertIsNone(result["selected_target"])

    def test_invalid_command_types_versions_flags_and_fields(self):
        for value in [None, [], True, "erase"]:
            with self.subTest(value=value):
                self.assert_invalid(value, scene(), "command")
        invalid_values = {
            "schema_version": [True, 1.0, "1", 2, None],
            "fixture": [False, 1, "true", None],
            "action": ["move", "ERASE", None, []],
            "text": ["", "  ", None, 1, []],
            "color": ["", "\t", None, False, {}],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    cmd = command()
                    cmd[field] = value
                    self.assert_invalid(cmd, scene(), f"command.{field}")
        cmd = command()
        del cmd["text"]
        self.assert_invalid(cmd, scene(), "command.text")
        cmd = command()
        cmd["motor"] = 1
        self.assert_invalid(cmd, scene(), "command.motor")

    def test_invalid_scene_types_versions_flags_and_metadata(self):
        for value in [None, [], False, "scene"]:
            with self.subTest(value=value):
                self.assert_invalid(command(), value, "scene")
        invalid_values = {
            "schema_version": [True, 1.0, 2],
            "fixture": [False, 1],
            "coordinate_frame": ["robot", None, 1],
            "unit": ["mm", None, 1],
            "image_size": [None, [], {"width": 640}],
            "targets": [None, {}, "word-1"],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    observed = scene()
                    observed[field] = value
                    path = "scene.image_size.height" if value == {"width": 640} else f"scene.{field}"
                    self.assert_invalid(command(), observed, path)
        observed = scene()
        del observed["targets"]
        self.assert_invalid(command(), observed, "scene.targets")
        observed = scene()
        observed["extra"] = True
        self.assert_invalid(command(), observed, "scene.extra")

    def test_image_dimensions_require_positive_integers(self):
        for field in ["width", "height"]:
            for value in [0, -1, True, 640.0, "640", None]:
                with self.subTest(field=field, value=value):
                    observed = scene()
                    observed["image_size"][field] = value
                    self.assert_invalid(command(), observed, f"scene.image_size.{field}")
        observed = scene()
        observed["image_size"]["depth"] = 3
        self.assert_invalid(command(), observed, "scene.image_size.depth")

    def test_every_target_is_validated_before_selecting_matching_record(self):
        for value in [None, [], "word"]:
            with self.subTest(value=value):
                observed = scene()
                observed["targets"][2] = value
                self.assert_invalid(command(), observed, "scene.targets[2]")
        for field in ["id", "text", "color"]:
            for value in ["", " ", None, 4, True]:
                with self.subTest(field=field, value=value):
                    observed = scene()
                    observed["targets"][2][field] = value
                    self.assert_invalid(command(), observed, f"scene.targets[2].{field}")
        observed = scene()
        observed["targets"][2]["id"] = "word-1"
        self.assert_invalid(command(), observed, "scene.targets[2].id")
        observed = scene()
        del observed["targets"][2]["bbox"]
        self.assert_invalid(command(), observed, "scene.targets[2].bbox")
        observed = scene()
        observed["targets"][2]["confidence"] = 0.9
        self.assert_invalid(command(), observed, "scene.targets[2].confidence")

    def test_bbox_rejects_invalid_container_shape_types_and_nonfinite_numbers(self):
        bad_boxes = [None, {}, "20,30,120,70", [], [20, 30, 120], [20, 30, 120, 70, 80]]
        bad_boxes += [[value, 30, 120, 70] for value in [True, None, "20", [], float("nan"), float("inf"), -float("inf")]]
        for bbox in bad_boxes:
            with self.subTest(bbox=bbox):
                observed = scene()
                observed["targets"][2]["bbox"] = bbox
                result = select_target(command(), observed)
                self.assertEqual(result["status"], "invalid_input")
                self.assertIsNone(result["selected_target"])
                self.assertTrue(any(error["path"].startswith("scene.targets[2].bbox") for error in result["diagnostics"]["errors"]))

    def test_bbox_rejects_negative_degenerate_reversed_and_out_of_bounds(self):
        for bbox in [[-1, 30, 120, 70], [20, -1, 120, 70], [20, 30, 20, 70],
                     [20, 30, 120, 30], [120, 30, 20, 70], [20, 70, 120, 30],
                     [20, 30, 641, 70], [20, 30, 120, 481]]:
            with self.subTest(bbox=bbox):
                observed = scene()
                observed["targets"][2]["bbox"] = bbox
                self.assert_invalid(command(), observed, "scene.targets[2].bbox")

    def test_finite_float_boxes_and_exact_image_edges_are_valid(self):
        observed = scene()
        observed["targets"][0]["bbox"] = [0.0, 0, 640, 480.0]
        result = select_target(command(), observed)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_target"]["bbox"], [0.0, 0, 640, 480.0])

    def test_validation_reports_multiple_errors_without_mutating_inputs(self):
        cmd, observed = command(), scene()
        cmd["text"] = ""
        observed["targets"][2]["bbox"] = [-1, 30, 120, 70]
        before = copy.deepcopy((cmd, observed))
        result = select_target(cmd, observed)
        self.assertEqual(result["status"], "invalid_input")
        self.assertGreaterEqual(len(result["diagnostics"]["errors"]), 2)
        self.assertEqual((cmd, observed), before)


if __name__ == "__main__":
    unittest.main()
