"""Small offline font-rendered development pilot; no model or robot execution."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFont, __version__ as PILLOW_VERSION


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
PREFIX_SOURCE = REPO / "docs/experiments/photo-comparison-20261030/calls/single/vlm/C-Q1/prompt.txt"
COLOR_ZH = {"red": "紅", "blue": "藍", "green": "綠", "black": "黑", "purple": "紫", "orange": "橘"}
CATEGORY_ZH = {"fruit": "水果", "animal": "動物", "tool": "工具", "vehicle": "交通工具", "insect": "昆蟲"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def png_bytes(im: Image.Image) -> bytes:
    stream = io.BytesIO()
    im.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def normalized_bbox(bbox: list[int], size: tuple[int, int]) -> list[float]:
    return [round(v * 1000 / size[i % 2], 3) for i, v in enumerate(bbox)]


def word_mask(word: str, font_path: str, size: int, angle: int) -> Image.Image:
    font = ImageFont.truetype(font_path, size)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    bounds = measure.textbbox((0, 0), word, font=font, stroke_width=1)
    mask = Image.new("L", (bounds[2] - bounds[0] + 20, bounds[3] - bounds[1] + 20))
    ImageDraw.Draw(mask).text((10 - bounds[0], 10 - bounds[1]), word, font=font, fill=255, stroke_width=1)
    mask = mask.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError(f"Empty word mask: {word!r}")
    mask = mask.crop(bounds)
    if mask.width > 245:
        # Width constraint is part of the declared renderer, not a silent font fallback.
        mask = mask.resize((245, round(mask.height * 245 / mask.width)), Image.Resampling.LANCZOS)
    return mask


def choose_ids(scene: dict, rule: dict) -> list[str]:
    targets = scene["targets"]
    kind = rule["kind"]
    if kind == "text":
        chosen = [t for t in targets if t["text"].casefold() == rule["text"].casefold()]
    elif kind == "ink_color":
        chosen = [t for t in targets if t["ink_color"] == rule["color"]]
    elif kind == "leftmost_text":
        candidates = [t for t in targets if t["text"].casefold() == rule["text"].casefold()]
        chosen = [min(candidates, key=lambda t: t["bbox_px"][0] + t["bbox_px"][2])] if candidates else []
    elif kind == "fully_above_text":
        anchor = [t for t in targets if t["text"].casefold() == rule["anchor_text"].casefold()]
        if len(anchor) != 1:
            raise ValueError("Spatial anchor must be unique")
        chosen = [t for t in targets if t["bbox_px"][3] < anchor[0]["bbox_px"][1]]
    elif kind in {"semantic_erase", "semantic_preserve"}:
        chosen = [t for t in targets if (rule["category"] in t["semantic_categories"]) == (kind == "semantic_erase")]
    else:
        raise ValueError(f"Unknown rule kind: {kind}")
    return [t["id"] for t in chosen]


def queries(family: dict, family_index: int) -> list[dict]:
    words = family["words"]
    semantic_category = "insect" if family_index % 4 == 3 else ["fruit", "vehicle", "tool"][family_index % 3]
    preserve_category = "animal" if family_index % 2 == 0 else "fruit"
    return [
        {"slot": "Q1", "category": "exact_color", "instruction": f"只擦掉文字 {words[0]}。", "rule": {"kind": "text", "text": words[0]}},
        {"slot": "Q2", "category": "exact_color", "instruction": "擦掉所有紅色墨水的文字，依墨色判斷，不依單字意思。", "rule": {"kind": "ink_color", "color": "red"}},
        {"slot": "Q3", "category": "spatial", "instruction": f"只擦掉最左邊的 {words[1]}。", "rule": {"kind": "leftmost_text", "text": words[1]}},
        {"slot": "Q4", "category": "spatial", "instruction": f"擦掉完全位於 {words[4]} 上方的所有單字。", "rule": {"kind": "fully_above_text", "anchor_text": words[4]}},
        {"slot": "Q5", "category": "semantic", "instruction": f"擦掉所有{CATEGORY_ZH[semantic_category]}名稱。", "rule": {"kind": "semantic_erase", "category": semantic_category}},
        {"slot": "Q6", "category": "semantic", "instruction": f"保留所有{CATEGORY_ZH[preserve_category]}名稱，擦掉其他文字。", "rule": {"kind": "semantic_preserve", "category": preserve_category}},
    ]


def render_dataset() -> dict[str, bytes]:
    """Return deterministic artifact bytes; verifier can replay without writing."""
    spec_bytes = (ROOT / "source/spec.json").read_bytes()
    lexicon_bytes = (ROOT / "source/lexicon.json").read_bytes()
    prefix_source_bytes = PREFIX_SOURCE.read_bytes()
    spec = json.loads(spec_bytes)
    lexicon = json.loads(lexicon_bytes)
    prefix = prefix_source_bytes.decode("utf-8").split("題目=", 1)[0].replace("\r\n", "\n")
    rng = random.Random(spec["seed"])
    size = tuple(spec["image_size"])
    palette = spec["palette"]
    colors = list(palette)
    blobs: dict[str, bytes] = {"model_inputs/prompt-prefix.txt": prefix.encode("utf-8")}
    font_records = []
    for font in spec["fonts"]:
        path = Path(font["path"])
        if not path.is_file():
            raise FileNotFoundError(f"Required installed font is absent: {path}; no fallback permitted")
        font_records.append({**font, "sha256": sha256(path.read_bytes()), "copied_into_dataset": False})
    model_index = []
    ground_truth = []
    pair_records = []
    preview_images = []
    for family_index, family in enumerate(spec["families"]):
        family_id = family["id"]
        slots = list(range(8))
        # Duplicate occurrences must occupy different columns for a clear leftmost query.
        for _ in range(100):
            rng.shuffle(slots)
            if slots[1] % 4 != slots[2] % 4:
                break
        else:
            raise RuntimeError("Could not create distinct duplicate columns")
        font_info = spec["fonts"][family_index % len(spec["fonts"])]
        masks = []
        geometry_targets = []
        for word_index, word in enumerate(family["words"]):
            font_size = rng.choice([46, 50, 54, 58])
            angle = rng.choice([-4, -2, 0, 2, 4])
            small = word_mask(word, font_info["path"], font_size, angle)
            slot = slots[word_index]
            center = (int([180, 485, 790, 1095][slot % 4] + rng.randint(-10, 10)), int([225, 555][slot // 4] + rng.randint(-8, 8)))
            xy = (center[0] - small.width // 2, center[1] - small.height // 2)
            full = Image.new("L", size, 0)
            full.paste(small, xy)
            bbox = list(full.getbbox() or ())
            if len(bbox) != 4 or xy[0] < 40 or bbox[2] > size[0] - 40:
                raise ValueError("Mask escaped the board interior")
            target_id = f"{family_id}-occ{word_index + 1:02d}"
            mask_path = f"supervision/masks/{family_id}/{target_id}.png"
            blobs[mask_path] = png_bytes(full)
            masks.append(full)
            geometry_targets.append({
                "id": target_id, "text": word, "bbox_px": bbox,
                "bbox_1000": normalized_bbox(bbox, size), "mask_path": mask_path,
                "font_id": font_info["id"], "font_size": font_size, "rotation_degrees": angle,
                "semantic_categories": [name for name, entries in lexicon.items() if isinstance(entries, list) and word.casefold() in entries],
            })
        union = Image.new("L", size, 0)
        for mask in masks:
            if ImageChops.multiply(union, mask).getbbox():
                raise ValueError("Word masks overlap")
            union = ImageChops.lighter(union, mask)
        initial_colors = [colors[(family_index + index) % len(colors)] for index in range(8)]
        literal_color = family["words"][0].casefold()
        # Check both ends of the pair: advancing once can itself land on the
        # literal color, even when the newly mapped color would be different.
        while initial_colors[0] == literal_color or spec["counterfactual_color_map"][initial_colors[0]] == literal_color:
            initial_colors[0] = spec["counterfactual_color_map"][initial_colors[0]]
        question_templates = queries(family, family_index)
        pair = {"family_id": family_id, "variants": [], "shared_mask_ids": [t["id"] for t in geometry_targets], "expected_invariant_query_slots": ["Q1", "Q3", "Q4", "Q5", "Q6"], "expected_changed_query_slots": ["Q2"]}
        for variant in ["clean", "color_swap"]:
            image_id = f"{family_id}_{variant}"
            board = Image.new("RGB", size, tuple(spec["background_rgb"]))
            draw = ImageDraw.Draw(board)
            draw.rounded_rectangle((19, 19, size[0] - 20, size[1] - 20), radius=9, outline=(139, 145, 143), width=5)
            # Fixed non-text distractors are deliberately absent from target masks.
            draw.line((70, 105, 1205, 105), fill=(169, 173, 171), width=3)
            draw.line((72, 729, 192, 729), fill=(101, 108, 105), width=4)
            draw.line((1115, 703, 1195, 703, 1180, 690), fill=(101, 108, 105), width=4)
            targets = []
            for index, (base, mask) in enumerate(zip(geometry_targets, masks)):
                color = initial_colors[index]
                if variant == "color_swap":
                    color = spec["counterfactual_color_map"][color]
                board.paste(tuple(palette[color]), (0, 0), mask)
                targets.append({**base, "ink_color": color, "ink_rgb": palette[color]})
            scene = {"schema_version": 1, "evidence_kind": "font_rendered_synthetic", "split": spec["split"], "family_id": family_id, "image_id": image_id, "variant": variant, "image_size": list(size), "coordinate_frame": "image", "bbox_format": "xyxy_exclusive", "targets": targets}
            image_path = f"images/{image_id}.png"
            blobs[image_path] = png_bytes(board)
            blobs[f"supervision/scenes/{image_id}.json"] = json_bytes(scene)
            pair["variants"].append({"image_id": image_id, "image_path": image_path})
            preview_images.append((image_id, board))
            for template in question_templates:
                question_id = f"{image_id}-{template['slot']}"
                question = {"id": question_id, "category": template["category"], "instruction": template["instruction"]}
                prompt_path = f"model_inputs/prompts/{question_id}.txt"
                prompt = prefix + "題目=" + json.dumps([question], ensure_ascii=False, separators=(",", ":")) + "\n"
                blobs[prompt_path] = prompt.encode("utf-8")
                model_index.append({"id": question_id, "image": image_path, "prompt": prompt_path})
                selected_ids = choose_ids(scene, template["rule"])
                selected = [t for t in targets if t["id"] in selected_ids]
                ground_truth.append({
                    "id": question_id, "image_id": image_id, "family_id": family_id,
                    "slot": template["slot"], "category": template["category"],
                    "instruction": template["instruction"], "rule": template["rule"],
                    "status": "selected" if selected else "no_match",
                    "erased_target_ids": selected_ids,
                    "retained_target_ids": [t["id"] for t in targets if t["id"] not in selected_ids],
                    "reference_answer": {"answers": [{"id": question_id, "status": "selected" if selected else "no_match", "targets": [{"text": t["text"], "bbox": t["bbox_1000"]} for t in selected]}]},
                    "provenance": "programmatic_rule_ground_truth_not_human_annotation",
                })
        pair_records.append(pair)
    blobs["model_inputs/index.jsonl"] = b"".join((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8") for row in model_index)
    blobs["supervision/ground-truth.json"] = json_bytes(ground_truth)
    blobs["supervision/pairs.json"] = json_bytes(pair_records)
    sheet = Image.new("RGB", (960, 12 * 324), (231, 234, 232))
    label_font = ImageFont.truetype(spec["fonts"][1]["path"], 17)
    for i, (label, board) in enumerate(preview_images):
        x = (i % 2) * 480
        y = (i // 2) * 324
        sheet.paste(board.resize((480, 307), Image.Resampling.LANCZOS), (x, y + 17))
        ImageDraw.Draw(sheet).text((x + 8, y - 2), label, font=label_font, fill=(30, 36, 34))
    blobs["contact-sheet.png"] = png_bytes(sheet)
    manifest = {
        "schema_version": 1, "dataset_id": spec["dataset_id"], "split": spec["split"],
        "seed": spec["seed"], "evidence_kind": "font_rendered_synthetic",
        "counts": {"base_families": len(spec["families"]), "images": len(preview_images), "questions": len(ground_truth), "unique_occurrence_masks": len(spec["families"]) * 8, "questions_by_category": dict(Counter(q["category"] for q in ground_truth)), "questions_by_status": dict(Counter(q["status"] for q in ground_truth))},
        "renderer": {"python": platform.python_version(), "pillow": PILLOW_VERSION, "implementation": sys.implementation.name, "platform": platform.platform()},
        "inputs": {"source/spec.json": sha256(spec_bytes), "source/lexicon.json": sha256(lexicon_bytes), "generate.py": sha256(Path(__file__).read_bytes()), str(PREFIX_SOURCE.relative_to(REPO)).replace("\\", "/"): sha256(prefix_source_bytes)},
        "fonts": font_records,
        "pixel_bbox_convention": "xyxy half-open: right and lower bounds exclusive; computed from each final transformed mask",
        "model_input_allowlist": "Only model_inputs/index.jsonl image and prompt paths; never supervision or manifest metadata",
        "reproducibility_scope": "Same inputs, installed font bytes, Python/Pillow/platform; cross-version byte identity not promised",
        "model_execution": False, "training": False, "robot_execution": False,
        "artifact_sha256": {path: sha256(data) for path, data in sorted(blobs.items())},
    }
    blobs["dataset-manifest.json"] = json_bytes(manifest)
    return blobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "generated")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        raise SystemExit("Output must remain inside this disposable pilot directory")
    blobs = render_dataset()
    existing = [path for path in output.rglob("*") if path.is_file()] if output.exists() else []
    unknown = [path for path in existing if path.relative_to(output).as_posix() not in blobs]
    if unknown:
        raise SystemExit(f"Refusing to overwrite directory with unrecognized files: {unknown[:3]}")
    for path, data in sorted(blobs.items()):
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(json.dumps({"output": str(output), "files": len(blobs), "images": 24, "questions": 144, "model_execution": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
