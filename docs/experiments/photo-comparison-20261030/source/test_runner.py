import unittest

from runner import normalise_box, parse_answer, resized_size


class ContractTests(unittest.TestCase):
    def test_resize_preserves_ratio_and_does_not_upscale(self):
        self.assertEqual(resized_size(2000, 1000, 1024), (1024, 512))
        self.assertEqual(resized_size(640, 480, 1024), (640, 480))

    def test_polygon_box_is_normalised_to_image(self):
        self.assertEqual(normalise_box([[10, 20], [30, 20], [30, 40], [10, 40]], 100, 200), [100, 100, 300, 200])

    def test_duplicate_question_is_rejected(self):
        raw = '{"answers":[{"id":"q1","status":"no_match","target_ids":[]},{"id":"q1","status":"no_match","target_ids":[]}]}'
        result = parse_answer(raw, "ocr_llm", ["q1", "q2"], {"t1"})
        self.assertFalse(result["valid"])
        self.assertIn("question_ids", result["errors"])

    def test_unknown_id_and_inconsistent_status_rejected(self):
        raw = '{"answers":[{"id":"q1","status":"no_match","target_ids":["invented"]}]}'
        result = parse_answer(raw, "ocr_llm", ["q1"], {"t1"})
        self.assertFalse(result["valid"])
        self.assertIn("q1:unknown_target_id", result["errors"])
        self.assertIn("q1:status_targets", result["errors"])

    def test_fenced_json_valid_but_no_prose_repair(self):
        raw = '```json\n{"answers":[{"id":"q1","status":"selected","target_ids":["t1"]}]}\n```'
        self.assertTrue(parse_answer(raw, "ocr_llm", ["q1"], {"t1"})["valid"])
        self.assertFalse(parse_answer("Here is the answer: " + raw, "ocr_llm", ["q1"], {"t1"})["valid"])

    def test_vlm_invalid_coordinates_rejected(self):
        for box in ([0, 0, 1001, 10], [4, 2, 1, 5], [True, 0, 4, 5]):
            import json
            raw = json.dumps({"answers": [{"id": "q1", "status": "selected", "targets": [{"text": "a", "bbox": box}]}]})
            self.assertFalse(parse_answer(raw, "vlm", ["q1"], set())["valid"])


if __name__ == "__main__":
    unittest.main()
