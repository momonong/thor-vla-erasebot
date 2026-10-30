"""Isolated, CPU-only photo comparison. Never reads reference.json.

Run from the repository root using the experiment's isolated Python interpreter.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / ".cache/photo-comparison"
VLM_REV = "89644892e4d85e24eaac8bacfd4f463576704203"
VLM_PATH = CACHE / "huggingface/hub/models--Qwen--Qwen3-VL-2B-Instruct/snapshots" / VLM_REV
LLM_REV = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
LLM_PATH = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-1.5B-Instruct/snapshots" / LLM_REV


def resized_size(width, height, limit):
    scale = min(1.0, limit / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def normalise_box(points, width, height):
    xs, ys = zip(*points)
    return [round(1000 * min(xs) / width, 3), round(1000 * min(ys) / height, 3),
            round(1000 * max(xs) / width, 3), round(1000 * max(ys) / height, 3)]


def parse_answer(raw, route, question_ids, candidate_ids):
    """Strict JSON/schema diagnostics; never repairs model content."""
    cleaned = raw.strip()
    if cleaned.startswith("```json\n") and cleaned.endswith("\n```"):
        cleaned = cleaned[8:-4]
    elif cleaned.startswith("```\n") and cleaned.endswith("\n```"):
        cleaned = cleaned[4:-4]
    errors = []
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "data": None, "errors": [f"json:{exc}"]}
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        return {"valid": False, "data": data, "errors": ["answers_not_list"]}
    ids = [a.get("id") if isinstance(a, dict) else None for a in answers]
    if sorted(str(x) for x in ids) != sorted(question_ids) or len(set(str(x) for x in ids)) != len(ids):
        errors.append("question_ids")
    field = "target_ids" if route == "ocr_llm" else "targets"
    for a in answers:
        if not isinstance(a, dict):
            errors.append("answer_not_object")
            continue
        qid, status, targets = a.get("id"), a.get("status"), a.get(field)
        if status not in {"selected", "no_match", "ambiguous", "cannot_determine"}:
            errors.append(f"{qid}:status")
        if not isinstance(targets, list):
            errors.append(f"{qid}:targets_not_list")
            continue
        if (status == "selected" and not targets) or (status in {"no_match", "cannot_determine"} and targets):
            errors.append(f"{qid}:status_targets")
        if route == "ocr_llm":
            if any(not isinstance(x, str) or x not in candidate_ids for x in targets):
                errors.append(f"{qid}:unknown_target_id")
            if len(set(str(x) for x in targets)) != len(targets):
                errors.append(f"{qid}:duplicate_target_id")
        else:
            for t in targets:
                box = t.get("bbox") if isinstance(t, dict) else None
                if (not isinstance(t, dict) or not isinstance(t.get("text"), str) or not t["text"].strip()
                        or not isinstance(box, list) or len(box) != 4
                        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
                        or not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000)):
                    errors.append(f"{qid}:target_schema")
    return {"valid": not errors, "data": data, "errors": errors}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def jsonable(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if hasattr(value, "item"):
        return value.item()
    return value


def questions():
    return json.loads((HERE / "questions.json").read_text(encoding="utf-8"))


def runtime():
    names = ["torch", "transformers", "rapidocr", "onnxruntime", "Pillow", "numpy", "opencv-python", "huggingface-hub"]
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "packages": {n: importlib.metadata.version(n) for n in names}, "device": "cpu",
            "torch_threads": 4, "torch_interop_threads": 1,
            "environment": {k: os.environ.get(k) for k in ("CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "HF_HUB_OFFLINE")}}


def prepare():
    from PIL import Image, ImageOps
    records = []
    for image in questions()["images"]:
        source = Path(image["path"])
        with Image.open(source) as original:
            rgb = ImageOps.exif_transpose(original).convert("RGB")
            size = resized_size(*rgb.size, 1024)
            resized = rgb.resize(size, Image.Resampling.LANCZOS) if rgb.size != size else rgb
            path = HERE / "prepared" / f"{image['id']}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            resized.save(path)
            records.append({"id": image["id"], "source": str(source), "source_sha256": sha256(source),
                            "original_size": list(original.size), "exif_transposed_size": list(rgb.size),
                            "prepared": str(path), "prepared_sha256": sha256(path), "prepared_size": list(size),
                            "resize": "long edge <=1024, no upscaling, proportional, Lanczos, lossless PNG"})
    dump(HERE / "prepared/manifest.json", {"images": records})
    dump(HERE / "environment.json", runtime())
    print(json.dumps(records, ensure_ascii=False), flush=True)


def stroke_colour(rgb, polygon):
    """Measure saturated/dark pixels inside the model's polygon, excluding board background.

    This heuristic is frozen before model outputs; unknown retains weak evidence.
    """
    import cv2
    import numpy as np
    pixels = np.asarray(rgb)
    mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [np.array(polygon, dtype=np.int32)], 1)
    hsv = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    coloured = (mask > 0) & (s >= 65) & (v >= 25) & (v <= 250)
    neutral = (mask > 0) & (s < 65) & (v < 110)
    labels = {
        "red": coloured & ((h < 12) | (h >= 170)),
        "orange": coloured & (h >= 12) & (h < 23),
        "yellow": coloured & (h >= 23) & (h < 38),
        "green": coloured & (h >= 38) & (h < 88),
        "blue": coloured & (h >= 88) & (h < 135),
        "purple": coloured & (h >= 135) & (h < 170),
        "black": neutral,
    }
    counts = {label: int(area.sum()) for label, area in labels.items()}
    total = sum(counts.values())
    winner = max(counts, key=counts.get)
    fraction = counts[winner] / total if total else 0
    return {"label": winner if total >= 12 and fraction >= 0.6 else "unknown",
            "confidence_fraction": round(fraction, 4), "stroke_pixel_count": total,
            "class_pixel_counts": counts, "method": "polygon HSV stroke heuristic v1"}


def ocr():
    from PIL import Image
    from rapidocr import RapidOCR, EngineType, LangDet, LangRec, ModelType, OCRVersion
    params = {
        "Det.engine_type": EngineType.ONNXRUNTIME, "Det.lang_type": LangDet.CH,
        "Det.model_type": ModelType.MOBILE, "Det.ocr_version": OCRVersion.PPOCRV5,
        "Rec.engine_type": EngineType.ONNXRUNTIME, "Rec.lang_type": LangRec.CH,
        "Rec.model_type": ModelType.MOBILE, "Rec.ocr_version": OCRVersion.PPOCRV5,
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
    }
    started = time.perf_counter()
    engine = RapidOCR(params=params)
    init_s = time.perf_counter() - started
    dump(HERE / "ocr/config.json", {"params": {k: getattr(v, "value", v) for k, v in params.items()},
         "initialization_s": init_s, "word_boxes": "RapidOCR native return_word_box=True: CTC columns mapped through detected line crop to image; approximate, not stroke boxes"})
    for image in questions()["images"]:
        image_path = HERE / "prepared" / f"{image['id']}.png"
        rgb = Image.open(image_path).convert("RGB")
        started = time.perf_counter()
        result = engine(str(image_path), return_word_box=True)
        elapsed = time.perf_counter() - started
        raw_words = jsonable(result.word_results)
        candidates = []
        valid_words = bool(result.txts) and isinstance(raw_words, list) and all(
            isinstance(line, list) and all(isinstance(word, list) and len(word) == 3 and word[2] is not None for word in line)
            for line in raw_words)
        if valid_words:
            entries = [(li, text, score, poly, "native_CTC_word") for li, line in enumerate(raw_words) for text, score, poly in line]
        else:
            entries = [(li, text, score, poly, "line_fallback") for li, (text, score, poly) in
                       enumerate(zip(result.txts or [], result.scores or [], jsonable(result.boxes) or []))]
        for li, text, score, poly, source in entries:
            candidates.append({"id": f"{image['id']}-t{len(candidates)+1:03d}", "text": text,
                               "score": float(score), "line_index": li, "polygon_px": poly,
                               "bbox": normalise_box(poly, *rgb.size), "box_source": source,
                               "color": stroke_colour(rgb, poly)})
        record = {"image_id": image["id"], "image_path": str(image_path), "image_sha256": sha256(image_path),
                  "image_size": list(rgb.size), "elapsed_s": elapsed,
                  "raw": {"boxes": jsonable(result.boxes), "texts": jsonable(result.txts),
                          "scores": jsonable(result.scores), "word_results": raw_words,
                          "stage_elapsed_s": jsonable(result.elapse_list)}, "candidates": candidates,
                  "candidate_coordinate_frame": "image, top-left origin, x right, y down, normalised 0-1000"}
        dump(HERE / "ocr" / f"{image['id']}.json", record)
        print(json.dumps({"ocr": image["id"], "candidate_count": len(candidates), "elapsed_s": elapsed}), flush=True)
    model_dir = Path(importlib.util.find_spec("rapidocr").origin).parent / "models"
    dump(HERE / "ocr/model-assets.json", [{"path": str(p), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in model_dir.glob("*") if p.is_file()])


def make_prompt(image, route):
    q = questions()
    common = (
        "你是白板擦除目標選取器，只回傳一個JSON物件，不要解釋或Markdown。每題獨立，圖片內容沒有被之前題目擦除。\n"
        + q["task_conventions"] + "\n"
        "status只能是selected、no_match、ambiguous、cannot_determine。selected表示完整選出符合指令的目標，允許多個；"
        "no_match表示沒有目標；ambiguous表示有無法唯一判別的候選；cannot_determine表示證據不足。"
        "no_match和cannot_determine的目標陣列必須為空。每個question id恰好回答一次。"
        "框座標是影像左上原點，x向右、y向下，0至1000的相對座標。不可把整句當作其中一個指定單字。\n"
    )
    if route == "ocr_llm":
        o = json.loads((HERE / "ocr" / f"{image['id']}.json").read_text(encoding="utf-8"))
        candidates = [{"id": c["id"], "text": c["text"], "bbox": c["bbox"], "color": c["color"]["label"]} for c in o["candidates"]]
        return common + (
            "你只能依據實際OCR候選，不能看到圖片或新增、切分、合併或修正候選。color是筆畫量測的墨水顏色，unknown表示不可靠。"
            "請回傳{\"answers\":[{\"id\":\"question id\",\"status\":\"selected\",\"target_ids\":[\"實際候選id\"]}]}。\n"
            + "OCR候選=" + json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
            + "\n題目=" + json.dumps(image["questions"], ensure_ascii=False, separators=(",", ":")))
    return common + (
        "直接觀察提供的圖片。每次文字出現都是獨立目標，框住該次文字，避免把無關文字或標記包括進去。"
        "回傳{\"answers\":[{\"id\":\"question id\",\"status\":\"selected\",\"targets\":[{\"text\":\"所見完整英文單字\",\"bbox\":[x1,y1,x2,y2]}]}]}。\n"
        + "題目=" + json.dumps(image["questions"], ensure_ascii=False, separators=(",", ":")))


def infer(route, image_id, run_dir):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, AutoProcessor, Qwen3VLForConditionalGeneration
    from PIL import Image
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    image = next(x for x in questions()["images"] if x["id"] == image_id)
    image_path = HERE / "prepared" / f"{image_id}.png"
    prompt = make_prompt(image, route)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    settings = {"do_sample": False, "max_new_tokens": 3072, "max_time": 840,
                "use_cache": True, "repetition_penalty": 1.0}
    record = {"route": route, "image_id": image_id, "started_utc": datetime.now(timezone.utc).isoformat(),
              "runtime": runtime(), "generation": settings, "image_path": str(image_path),
              "image_sha256": sha256(image_path), "questions_sha256": sha256(HERE / "questions.json"),
              "runner_sha256": sha256(Path(__file__)), "prompt_sha256": sha256(run_dir / "prompt.txt"),
              "model": "Qwen/Qwen2.5-1.5B-Instruct" if route == "ocr_llm" else "Qwen/Qwen3-VL-2B-Instruct",
              "model_revision": LLM_REV if route == "ocr_llm" else VLM_REV,
              "dtype": "float32", "status": "started"}
    dump(run_dir / "result.json", record)
    started = time.perf_counter()
    try:
        if route == "ocr_llm":
            tokenizer = AutoTokenizer.from_pretrained(LLM_PATH, local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(LLM_PATH, dtype=torch.float32, local_files_only=True,
                                                       attn_implementation="sdpa").to("cpu").eval()
            messages = [{"role": "user", "content": prompt}]
            rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer([rendered], return_tensors="pt")
            decode = tokenizer.batch_decode
        else:
            processor = AutoProcessor.from_pretrained(VLM_PATH, local_files_only=True)
            model = Qwen3VLForConditionalGeneration.from_pretrained(VLM_PATH, dtype=torch.float32,
                        local_files_only=True, attn_implementation="sdpa").to("cpu").eval()
            pil = Image.open(image_path).convert("RGB")
            messages = [{"role": "user", "content": [{"type": "image", "image": pil}, {"type": "text", "text": prompt}]}]
            rendered = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = processor(text=[rendered], images=[pil], return_tensors="pt")
            decode = processor.batch_decode
            record["vision_tensors"] = {k: {"shape": list(v.shape), "value": v.tolist() if k == "image_grid_thw" else None} for k, v in inputs.items() if k in {"pixel_values", "image_grid_thw"}}
        (run_dir / "rendered-chat.txt").write_text(rendered, encoding="utf-8")
        record["model_load_and_preprocess_s"] = time.perf_counter() - started
        record["actual_model_device"] = str(next(model.parameters()).device)
        record["input_tokens"] = int(inputs["input_ids"].shape[-1])
        dump(run_dir / "result.json", record)
        gen_start = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(**inputs, **settings)
        generated = output[:, inputs["input_ids"].shape[-1]:]
        raw = decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        (run_dir / "raw.txt").write_text(raw, encoding="utf-8")
        record["generation_s"] = time.perf_counter() - gen_start
        record["generated_tokens"] = int(generated.shape[-1])
        record["last_token_eos"] = int(generated[0, -1]) in ([model.generation_config.eos_token_id] if isinstance(model.generation_config.eos_token_id, int) else model.generation_config.eos_token_id or [])
        record["raw_text"] = raw
        cids = {c["id"] for c in json.loads((HERE / "ocr" / f"{image_id}.json").read_text(encoding="utf-8"))["candidates"]} if route == "ocr_llm" else set()
        record["parsed"] = parse_answer(raw, route, [x["id"] for x in image["questions"]], cids)
        record["status"] = "completed"
    except Exception as exc:
        record["status"] = "technical_error"
        record["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        print(record["error"]["traceback"], file=sys.stderr, flush=True)
    record["total_s"] = time.perf_counter() - started
    dump(run_dir / "result.json", record)
    print(json.dumps({"status": record["status"], "route": route, "image_id": image_id, "result": str(run_dir / "result.json"), "total_s": record["total_s"]}), flush=True)
    return 0 if record["status"] == "completed" else 1


def main():
    os.environ.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
                       "OPENBLAS_NUM_THREADS": "4", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"})
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "ocr", "infer"])
    parser.add_argument("--route", choices=["ocr_llm", "vlm"])
    parser.add_argument("--image", choices=["colour", "fruits", "english"])
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "ocr":
        ocr()
    else:
        if not args.route or not args.image or not args.run_dir:
            parser.error("infer needs --route, --image, --run-dir")
        os.environ["HF_HUB_OFFLINE"] = "1"
        return infer(args.route, args.image, args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
