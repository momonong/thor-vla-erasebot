"""Verify this portable archive and recompute AI-adjudicated aggregates; no inference."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    manifest = read(HERE / "manifest.json")
    listed = {r["path"] for r in manifest["files"]}
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert actual == listed | {"manifest.json"}, (actual - listed, listed - actual)
    locator = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|/users/|/home/)|thread_id|/root/|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    assert not locator.search((HERE / "manifest.json").read_text(encoding="utf-8")), "local locator in manifest"
    for item in manifest["files"]:
        p = HERE / item["path"]
        assert digest(p) == item["sha256"], item["path"]
        if item["disposition"] == "byte_exact_copy":
            assert item["sha256"] == item["private_source_sha256"]
        if p.suffix in {".json", ".md", ".txt"}:
            text = p.read_text(encoding="utf-8-sig")
            assert not locator.search(text), f"local locator in {item['path']}"
        if p.suffix == ".json":
            read(p)
        if p.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf-8")):
                if not target.startswith(("https://", "http://", "#")):
                    assert (p.parent / target.split("#", 1)[0]).exists(), (item["path"], target)
    spec = importlib.util.spec_from_file_location("archived_photo_runner", HERE / "source/runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    candidates = {i: {t["id"] for t in read(HERE / f"data/ocr/{i}.json")["candidates"]} for i in ("colour", "fruits", "english")}
    calls = read(HERE / "calls/index.json")["attempts"]
    assert len(calls) == 45
    completed = [c for c in calls if c["status"] == "completed"]
    assert len(completed) == 42 and sum(c["status"] == "technical_error" for c in calls) == 3
    for call in calls:
        assert digest(HERE / call["prompt_file"]) == call["prompt_sha256"]
        if call["status"] == "completed":
            raw = HERE / call["raw_file"]
            assert digest(raw) == call["raw_sha256"]
            parsed = runner.parse_answer(raw.read_text(encoding="utf-8"), call["route"], call["question_ids"], candidates[call["image_id"]] if call["route"] == "ocr_llm" else set())
            assert parsed == call["recorded_parser_result"], call["id"]
    scores = {}
    for phase in ("batch", "single"):
        adjudication = read(HERE / f"annotations/{phase}-adjudication.ai.json")
        assert len(adjudication["cases"]) == 18
        scores[phase] = {}
        for route in ("ocr_llm", "vlm"):
            correct = sum(c[route]["content_target_set_correct"] for c in adjudication["cases"])
            assert correct == adjudication["summary"][route]["content_correct"]
            scores[phase][route] = correct
    comparison = read(HERE / "annotations/comparison.json")
    old = read(HERE / "annotations/batch-adjudication.ai.json")["cases"]
    new = read(HERE / "annotations/single-adjudication.ai.json")["cases"]
    for route in ("ocr_llm", "vlm"):
        for transition, before, after in (("wrong_to_correct", False, True), ("correct_to_wrong", True, False), ("correct_to_correct", True, True), ("wrong_to_wrong", False, False)):
            ids = [b["id"] for a, b in zip(old, new) if a[route]["content_target_set_correct"] == before and b[route]["content_target_set_correct"] == after]
            assert ids == comparison["routes"][route]["single"]["transitions"][transition]
    print(json.dumps({"files_verified": len(actual), "attempts": 45, "raw_responses_reparsed": 42,
                      "question_method_pairs": 72, "ai_adjudicated_content_correct": scores,
                      "inference_executed": False, "accuracy_independently_rescored": False}, indent=2))


if __name__ == "__main__":
    main()
