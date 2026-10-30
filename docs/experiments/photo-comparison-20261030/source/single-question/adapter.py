"""Single-question adapter; baseline runner is imported without modification."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def load_runner():
    spec = importlib.util.spec_from_file_location("photo_comparison_baseline", BASE / "runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def old_run(route, image):
    batch = "20261030T024109Z" if route == "ocr_llm" else "20261030T024513Z"
    return BASE / "runs" / batch / f"{route}-{image}"


def single_payload(data, image_id, question_id):
    images = [i for i in data["images"] if i["id"] == image_id]
    if len(images) != 1:
        raise ValueError(f"unknown or duplicate image for question: {image_id}")
    selected = [q for q in images[0]["questions"] if q["id"] == question_id]
    if len(selected) != 1:
        raise ValueError(f"unknown or duplicate question for {image_id}: {question_id}")
    result = copy.deepcopy(data)
    image = copy.deepcopy(images[0])
    image["questions"] = copy.deepcopy(selected)
    result["images"] = [image]
    return result


def split_prompt(value):
    marker = "\n題目=".encode("utf-8")
    prefix, separator, suffix = value.rpartition(marker)
    if not separator:
        raise ValueError("prompt question-array delimiter missing")
    return prefix + separator, suffix


def native_prompt_bytes(value):
    # Baseline Path.write_text uses Windows text newline translation.
    return value.replace("\n", os.linesep).encode("utf-8")


def prepare_prompt(route, image_id, question_id):
    if route not in {"ocr_llm", "vlm"}:
        raise ValueError(f"unknown route: {route}")
    runner = load_runner()
    data = single_payload(runner.questions(), image_id, question_id)
    runner.questions = lambda: copy.deepcopy(data)
    prompt = native_prompt_bytes(runner.make_prompt(data["images"][0], route))
    old_prefix = split_prompt((old_run(route, image_id) / "prompt.txt").read_bytes())[0]
    prefix, suffix = split_prompt(prompt)
    if prefix != old_prefix or json.loads(suffix) != data["images"][0]["questions"]:
        raise ValueError("single-question prompt changed outside the final question array")
    return {"runner": runner, "data": data, "prompt_bytes": prompt,
            "prefix_sha256": hashlib.sha256(prefix).hexdigest()}


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_light_manifest(manifest):
    for item in manifest["frozen_files"]:
        if sha(item["path"]) != item["sha256"]:
            raise ValueError(f"frozen baseline file changed: {item['path']}")


def execute(route, image_id, question_id, run_dir):
    # Validate qid and exact prompt before creating output directories or importing torch.
    job = prepare_prompt(route, image_id, question_id)
    manifest_path = HERE / "baseline-manifest.json"
    manifest = read(manifest_path)
    check_light_manifest(manifest)
    expected = manifest["baseline_configs"][f"{route}-{image_id}"]
    if job["prefix_sha256"] != manifest["prompt_checks"][f"{route}-{image_id}"]["prefix_sha256"]:
        raise ValueError("prompt prefix does not match the frozen baseline")
    if run_dir.exists():
        raise ValueError("run directory already exists; existing results must be preserved")
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    runner = job["runner"]
    control_path = run_dir.parent / f"{run_dir.name}.control.json"
    control = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "question_id": question_id,
        "route": route, "image_id": image_id, "question_count": 1,
        "adapter_sha256": sha(Path(__file__)), "launcher_sha256": sha(HERE / "launch.py"),
        "baseline_manifest_sha256": sha(manifest_path), "baseline_prompt_prefix_sha256": job["prefix_sha256"],
        "baseline_questions_file_sha256": sha(BASE / "questions.json"),
        "selected_question_payload": job["data"]["images"][0]["questions"],
        "prepared_sha256": sha(BASE / "prepared" / f"{image_id}.png"),
        "ocr_sha256": sha(BASE / "ocr" / f"{image_id}.json"),
        "expected_baseline_config": expected, "fresh_subprocess_fresh_conversation": True,
        "model_weights_verified_by_preflight_manifest": True,
        "baseline_light_files_verified_before_infer": True,
    }
    runner.dump(control_path, control)
    code = runner.infer(route, image_id, run_dir)
    if (run_dir / "result.json").exists():
        result = read(run_dir / "result.json")
        checks = {key: result.get(key) == expected[key] for key in ("model", "model_revision", "dtype", "generation", "runner_sha256")}
        checks["prepared_sha256"] = result["image_sha256"] == control["prepared_sha256"]
        checks["questions_file_sha256"] = result["questions_sha256"] == control["baseline_questions_file_sha256"]
        checks["actual_prompt_bytes"] = (run_dir / "prompt.txt").read_bytes() == job["prompt_bytes"]
        if result["status"] == "completed":
            checks["device_cpu"] = result["actual_model_device"] == "cpu"
            checks["threads_unchanged"] = result["runtime"]["torch_threads"] == 4 and result["runtime"]["torch_interop_threads"] == 1
        control["post_infer_control_checks"] = checks
        control["all_control_checks_pass"] = all(checks.values())
        control["inference_status"] = result["status"]
        runner.dump(run_dir / "control.json", control)
        runner.dump(control_path, control)
        if not control["all_control_checks_pass"]:
            return 3
    return code


def main():
    os.environ.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
                       "OPENBLAS_NUM_THREADS": "4", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
                       "HF_HUB_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True, choices=["ocr_llm", "vlm"])
    parser.add_argument("--image", required=True, choices=["colour", "fruits", "english"])
    parser.add_argument("--question", required=True)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        return execute(args.route, args.image, args.question, args.run_dir.resolve())
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
