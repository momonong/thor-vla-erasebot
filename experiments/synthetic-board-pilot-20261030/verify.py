"""Direct integrity/replay checks for this pilot; not an evaluation of any model."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

import generate


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "generated"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def independent_answer(question: dict, scene: dict, lexicon: dict, measured: dict) -> list[str]:
    """Separate rule implementation; do not call generator selection helpers."""
    rule = question["rule"]
    entries = scene["targets"]
    kind = rule["kind"]
    result = []
    if kind == "text":
        for entry in entries:
            if entry["text"].lower() == rule["text"].lower():
                result.append(entry["id"])
    elif kind == "ink_color":
        for entry in entries:
            if measured[entry["id"]]["color"] == rule["color"]:
                result.append(entry["id"])
    elif kind == "leftmost_text":
        matches = [entry for entry in entries if entry["text"].lower() == rule["text"].lower()]
        check(len(matches) == 2, "Leftmost query must exercise two duplicate occurrences")
        ordered = sorted(matches, key=lambda entry: sum(measured[entry["id"]]["bbox"][0:3:2]))
        centers = [sum(measured[entry["id"]]["bbox"][0:3:2]) for entry in ordered]
        check(centers[0] != centers[1], "Leftmost duplicate geometry is tied")
        result = [ordered[0]["id"]]
    elif kind == "fully_above_text":
        anchors = [entry for entry in entries if entry["text"].lower() == rule["anchor_text"].lower()]
        check(len(anchors) == 1, "Above relation anchor is not unique")
        top = measured[anchors[0]["id"]]["bbox"][1]
        for entry in entries:
            if measured[entry["id"]]["bbox"][3] < top:
                result.append(entry["id"])
    elif kind in {"semantic_erase", "semantic_preserve"}:
        allowed = {word.lower() for word in lexicon[rule["category"]]}
        for entry in entries:
            belongs = entry["text"].lower() in allowed
            if (kind == "semantic_erase" and belongs) or (kind == "semantic_preserve" and not belongs):
                result.append(entry["id"])
    else:
        raise AssertionError(f"Unrecognized query rule {kind!r}")
    return result


def main() -> None:
    spec = load_json(ROOT / "source/spec.json")
    lexicon = load_json(ROOT / "source/lexicon.json")
    check(set(lexicon["insect"]) <= set(lexicon["animal"]), "Semantic dictionary must label every insect as an animal too")
    manifest = load_json(DATA / "dataset-manifest.json")
    truth = load_json(DATA / "supervision/ground-truth.json")
    pairs = load_json(DATA / "supervision/pairs.json")
    model_index = [json.loads(line) for line in (DATA / "model_inputs/index.jsonl").read_text(encoding="utf-8").splitlines()]
    scenes = {path.stem: load_json(path) for path in sorted((DATA / "supervision/scenes").glob("*.json"))}
    image_paths = sorted((DATA / "images").glob("*.png"))
    check(len(spec["families"]) == len(pairs) == 12, "Expected exactly 12 base families")
    check(len(scenes) == len(image_paths) == 24, "Expected exactly 24 paired images")
    check(len(truth) == len(model_index) == 144, "Expected exactly 144 questions")
    check(len({row["id"] for row in truth}) == 144, "Question IDs are not unique")
    check({row["id"] for row in truth} == {row["id"] for row in model_index}, "GT/model-input ID mismatch")
    check(manifest["split"] == "development_pilot", "Pilot must not be called held-out")
    check(not any(manifest[field] for field in ["model_execution", "training", "robot_execution"]), "Unexpected execution claim")
    check(Counter(row["category"] for row in truth) == {"exact_color": 48, "spatial": 48, "semantic": 48}, "Category counts mismatch")
    check(all(count == 6 for count in Counter(row["image_id"] for row in truth).values()), "An image does not have exactly 6 questions")
    for relpath, expected_hash in manifest["artifact_sha256"].items():
        path = DATA / relpath
        check(path.is_relative_to(DATA) and path.is_file(), f"Artifact missing: {relpath}")
        check(hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash, f"Artifact SHA mismatch: {relpath}")
    prefix = (DATA / "model_inputs/prompt-prefix.txt").read_text(encoding="utf-8")
    original_prefix = generate.PREFIX_SOURCE.read_text(encoding="utf-8").split("題目=", 1)[0]
    check(prefix == original_prefix, "VLM contract prefix changed")
    by_truth = {row["id"]: row for row in truth}
    for row in model_index:
        check(set(row) == {"id", "image", "prompt"}, "Model index contains additional metadata")
        check(row["image"].startswith("images/") and row["prompt"].startswith("model_inputs/prompts/"), "Model input allowlist escaped")
        text = (DATA / row["prompt"]).read_text(encoding="utf-8")
        check(text.startswith(prefix + "題目="), "Prompt contract missing")
        question_list = json.loads(text[len(prefix + "題目="):])
        reference = by_truth[row["id"]]
        check(question_list == [{"id": row["id"], "category": reference["category"], "instruction": reference["instruction"]}], "Prompt includes GT/scene or mismatched instruction")
        check(all(marker not in text for marker in ["erased_target_ids", "retained_target_ids", "reference_answer", "semantic_categories", "mask_path", "bbox_px", "-occ"]), "GT leaked into prompt")
    mask_count = 0
    measured_scenes = {}
    size = tuple(spec["image_size"])
    for image_id, scene in scenes.items():
        image = Image.open(DATA / f"images/{image_id}.png").convert("RGB")
        check(image.size == size == tuple(scene["image_size"]), "Image size mismatch")
        check(scene["split"] == "development_pilot", "Scene split incorrect")
        check(len(scene["targets"]) == len({entry["id"] for entry in scene["targets"]}) == 8, "Target count/IDs incorrect")
        measured = {}
        union = Image.new("L", size, 0)
        for entry in scene["targets"]:
            mask = Image.open(DATA / entry["mask_path"]).convert("L")
            box = mask.getbbox()
            check(mask.size == size and box is not None, f"Empty/wrong-size mask: {entry['id']}")
            check(list(box) == entry["bbox_px"], f"Actual mask bbox mismatch: {entry['id']}")
            check(0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1], "BBox out of image bounds")
            norm = [round(box[0] * 1000 / size[0], 3), round(box[1] * 1000 / size[1], 3), round(box[2] * 1000 / size[0], 3), round(box[3] * 1000 / size[1], 3)]
            check(norm == entry["bbox_1000"], "Normalized bbox mismatch")
            check(ImageChops.multiply(union, mask).getbbox() is None, "Occurrence masks overlap")
            union = ImageChops.lighter(union, mask)
            # Independently derive the ink color from opaque rendered pixels.
            opaque = mask.point(lambda value: 255 if value == 255 else 0)
            opaque_box = opaque.getbbox()
            check(opaque_box is not None, "No opaque ink pixels for independent color check")
            histogram = Counter(rgb for rgb, alpha in zip(image.crop(box).getdata(), opaque.crop(box).getdata()) if alpha == 255)
            check(len(histogram) == 1, f"Mixed colors inside one opaque word: {entry['id']}")
            ink_rgb = next(iter(histogram))
            color_matches = [name for name, rgb in spec["palette"].items() if tuple(rgb) == ink_rgb]
            check(len(color_matches) == 1, "Rendered ink not in palette")
            check(color_matches[0] == entry["ink_color"] and list(ink_rgb) == entry["ink_rgb"], "Image/metadata color mismatch")
            independently_labeled = [name for name, words in lexicon.items() if isinstance(words, list) and entry["text"].lower() in {word.lower() for word in words}]
            check(independently_labeled == entry["semantic_categories"], "Metadata semantic labels differ from finite dictionary")
            measured[entry["id"]] = {"bbox": list(box), "color": color_matches[0]}
            mask_count += 1
        measured_scenes[image_id] = measured
        for question in [q for q in truth if q["image_id"] == image_id]:
            expected = independent_answer(question, scene, lexicon, measured)
            check(expected == question["erased_target_ids"], f"Independent rule mismatch: {question['id']}")
            all_ids = [entry["id"] for entry in scene["targets"]]
            check(set(expected) <= set(all_ids), "Expected target is absent")
            check(question["retained_target_ids"] == [tid for tid in all_ids if tid not in expected], "Retention complement mismatch")
            check(question["status"] == ("selected" if expected else "no_match"), "GT status mismatch")
            response = question["reference_answer"]["answers"]
            targets = [{"text": entry["text"], "bbox": entry["bbox_1000"]} for entry in scene["targets"] if entry["id"] in expected]
            check(response == [{"id": question["id"], "status": question["status"], "targets": targets}], "Reference output contract mismatch")
    changed_color_pairs = 0
    invariant_queries = 0
    for pair in pairs:
        clean_id, swapped_id = [variant["image_id"] for variant in pair["variants"]]
        check(clean_id == pair["family_id"] + "_clean" and swapped_id == pair["family_id"] + "_color_swap", "Incorrect pair membership")
        a, b = scenes[clean_id], scenes[swapped_id]
        check([t["id"] for t in a["targets"]] == pair["shared_mask_ids"], "Pair shared masks not bound to target IDs")
        union = Image.new("L", size, 0)
        for ta, tb in zip(a["targets"], b["targets"]):
            clean_geometry = {k: v for k, v in ta.items() if k not in {"ink_color", "ink_rgb"}}
            swapped_geometry = {k: v for k, v in tb.items() if k not in {"ink_color", "ink_rgb"}}
            check(clean_geometry == swapped_geometry, "A pair changed geometry/text/masks")
            check(tb["ink_color"] == spec["counterfactual_color_map"][ta["ink_color"]], "Color map mismatch")
            mask = Image.open(DATA / ta["mask_path"]).convert("L")
            union = ImageChops.lighter(union, mask)
        # Pixel equality outside word-mask support establishes that only ink changed.
        ia = Image.open(DATA / f"images/{clean_id}.png").convert("RGB")
        ib = Image.open(DATA / f"images/{swapped_id}.png").convert("RGB")
        diff = ImageChops.difference(ia, ib).convert("L")
        outside = union.point(lambda value: 0 if value else 255)
        check(diff.getbbox() is not None and ImageChops.multiply(diff, outside).getbbox() is None, "Color-swap changed pixels outside occurrence masks")
        literal = a["targets"][0]["text"].lower()
        check(all(s["targets"][0]["ink_color"] != literal for s in [a, b]), "Literal-color conflict was not retained")
        for slot in pair["expected_invariant_query_slots"]:
            qa, qb = by_truth[f"{clean_id}-{slot}"], by_truth[f"{swapped_id}-{slot}"]
            check(qa["rule"] == qb["rule"] and qa["instruction"] == qb["instruction"], "Pair query changed")
            check(qa["erased_target_ids"] == qb["erased_target_ids"], "Text/spatial/semantic invariance failed")
            invariant_queries += 1
        check(by_truth[f"{clean_id}-Q2"]["erased_target_ids"] != by_truth[f"{swapped_id}-Q2"]["erased_target_ids"], "Color query must change under counterfactual")
        changed_color_pairs += 1
    check(mask_count == 192 and len(list((DATA / "supervision/masks").rglob("*.png"))) == 96, "Unexpected occurrence/mask count")
    check(sum(q["status"] == "no_match" for q in truth) > 0, "Missing no-match cases")
    check(sum(q["rule"]["kind"] == "semantic_preserve" for q in truth) == 24, "Missing preservation cases")
    for variant in ["clean", "color_swap"]:
        check(by_truth[f"B03_{variant}-Q5"]["status"] == "no_match", "B03 tool query must supply a non-insect semantic no-match")
        check("B03-occ06" in by_truth[f"B03_{variant}-Q6"]["retained_target_ids"], "B03 animal-preservation query must retain beetle")
        check(by_truth[f"B08_{variant}-Q5"]["erased_target_ids"] == ["B08-occ08"], "B08 insect query must select bee")
    # Byte-for-byte replay in memory does not produce a second directory or alter evidence.
    replay = generate.render_dataset()
    actual_paths = {path.relative_to(DATA).as_posix() for path in DATA.rglob("*") if path.is_file()}
    check(actual_paths == set(replay), "Generated directory contains missing or unlisted files")
    for relpath, data in replay.items():
        check((DATA / relpath).read_bytes() == data, f"Same-seed byte replay failed: {relpath}")
    report = {
        "status": "passed", "scope": "dataset_integrity_and_deterministic_replay_only",
        "counts": manifest["counts"], "verified_artifact_hashes": len(manifest["artifact_sha256"]),
        "image_occurrences_checked": mask_count, "unique_mask_bboxes_checked": 96,
        "independent_rule_answers_checked": len(truth), "input_prompts_checked_for_supervision_leakage": len(model_index),
        "counterfactual_pairs_checked": changed_color_pairs, "invariant_query_pairs_checked": invariant_queries,
        "same_seed_replay_files_identical": len(replay), "model_execution": False,
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": ["24 images / 12 families / 144 questions", "actual final-mask boxes and image bounds", "opaque image pixels agree with declared ink", "independent text/color/spatial/finite-lexicon rules", "insect subset animal multi-label consistency and B03 beetle retention", "B03 tool no-match and B08 insect positive coverage", "expected targets and retention complements", "same geometry and only ink pixels changed in paired images", "color query changes and other query invariance", "original VLM prompt prefix and GT-free single-question inputs", "manifest SHA256 and same-seed byte replay"],
    }
    (ROOT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
