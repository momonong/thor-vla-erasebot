"""Offline stdlib verification of frozen evidence; never imports an inference runner."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EXPECTED = {"qwen_llm": (4, 0), "qwen_vlm": (10, 17), "smolvlm": (0, 1),
            "doctr_smollm": (0, 0), "gemma": (8, 18), "phi": (1, 0)}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def main():
    manifest = read(HERE / "manifest.json")
    files = manifest["files"]
    listed = {item["path"] for item in files}
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    require(len(listed) == len(files), "Duplicate manifest member")
    require(actual == listed | {"manifest.json"}, f"Membership mismatch: extra={actual-listed-{'manifest.json'}}, missing={listed-actual}")
    # All archive data/documents are checked; scripts contain intentional locator-pattern literals.
    locator = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|/users/|/home/)|/root/|\.cache[\\/]|thread_id|(?:api[_-]?key|access[_-]?token)\s*[=:]")
    links = 0
    require(not locator.search((HERE / "manifest.json").read_text(encoding="utf-8")), "Private locator in manifest")
    for item in files:
        relative = Path(item["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, f"Unsafe member {relative}")
        path = HERE / relative
        require(path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], f"Hash/size mismatch: {relative}")
        if item["disposition"] == "byte_exact_copy":
            require(item["sha256"] == item["source_sha256"], f"Source-copy hash mismatch: {relative}")
        if path.suffix in {".json", ".md", ".txt"}:
            text = path.read_text(encoding="utf-8-sig")
            require(not locator.search(text), f"Private locator or credential assignment in {relative}")
        if path.suffix == ".json":
            read(path)
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if not target.startswith(("https://", "http://", "#")):
                    resolved = (path.parent / target.split("#", 1)[0]).resolve()
                    require(resolved.is_relative_to(HERE), f"Link escapes portable packet: {relative}: {target}")
                    require(resolved.exists(), f"Broken link: {relative}: {target}")
                    links += 1

    # Import only this saved pure contract module. No runner, torch or transformers imports.
    contract_text = (HERE / "contracts.py").read_text(encoding="utf-8")
    contract_ast = ast.parse(contract_text)
    require(all(isinstance(node, (ast.Import, ast.FunctionDef, ast.Expr)) for node in contract_ast.body), "Unexpected contract top-level code")
    require([alias.name for node in contract_ast.body if isinstance(node, ast.Import) for alias in node.names] == ["json", "math"], "Contract imports exceed stdlib allowlist")
    settings = read(HERE / "config/contracts.json")
    funcs = {node.name: ast.get_source_segment(contract_text, node) for node in contract_ast.body if isinstance(node, ast.FunctionDef)}
    require(set(funcs) == {"parse_answer", "make_prompt"}, "Unexpected contract functions")
    for name, key in (("parse_answer", "parser_function_lf_sha256"), ("make_prompt", "prompt_function_lf_sha256")):
        require(hashlib.sha256(funcs[name].encode()).hexdigest() == settings[key], f"Function hash mismatch: {name}")
    spec = importlib.util.spec_from_file_location("portable_saved_contracts", HERE / "contracts.py")
    contracts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contracts)
    questions = read(HERE / "data/questions.json")
    cases = {question["id"]: (image, question) for image in questions["images"] for question in image["questions"]}
    require(len(cases) == 18, "Expected 18 fixed questions")
    annotations = read(HERE / "adjudication.ai.json")
    require(annotations["review_notes_sha256"] == sha(HERE / "review-notes.json"), "Public review hash binding")
    require(annotations["reference_sha256"] == sha(HERE / "data/reference.ai.json"), "Reference hash binding")
    require(annotations["questions_sha256"] == sha(HERE / "data/questions.json"), "Question hash binding")
    require(not annotations["human_accepted"] and not annotations["reference_used_during_inference"], "Scoring boundary changed")
    rows = {(row["route"], row["question_id"]): row for row in annotations["cases"]}
    require(len(rows) == len(annotations["cases"]) == 108, "Adjudication cardinality")
    index = read(HERE / "calls/index.json")["calls"]
    require(len(index) == len({(call["route"], call["question_id"]) for call in index}) == 108, "Call cardinality")
    historical = read(HERE / "results.json")
    require(historical["adjudication_sha256"] == sha(HERE / "adjudication.ai.json"), "Public result/adjudication binding")
    require(historical["model_assets_receipt_sha256"] == sha(HERE / "config/model-assets.json"), "Public model-assets binding")
    reviews = read(HERE / "review-notes.json")["routes"]
    summaries = {}
    for route, (content_expected, schema_expected) in EXPECTED.items():
        summary = read(HERE / f"config/routes/{route}.json")
        require(summary["status"] == "finished" and not summary["not_executed"], route + " unfinished")
        require(summary["planned_questions"] == 18 and summary["seed"] == 0, route + " denominator/seed")
        require(summary["settings"] == settings["generation_settings"], route + " settings")
        require(summary["fresh_context_each_question"] and summary["model_loaded_once"], route + " context lifecycle")
        require(summary["actual_model_device"] == "cuda:0" and summary["actual_model_dtype"] == "torch.bfloat16", route + " historical device/dtype")
        require(summary["parser_sha256"] == settings["historical_parser_runner_sha256"], route + " historical parser hash")
        require(summary["runner_sha256"] in {r["sha256"] for r in settings["runner_source_receipts"]}, route + " historical runner hash")
        require(summary["questions_sha256"] == sha(HERE / "data/questions.json"), route + " questions")
        selected = [call for call in index if call["route"] == route]
        require({call["question_id"] for call in selected} == set(cases), route + " missing question")
        records, route_rows = [], []
        for call in selected:
            qid = call["question_id"]
            image, question = cases[qid]
            folder = HERE / call["directory"]
            require(call["directory"] == f"calls/{route}/{qid}", "Call directory binding")
            record = read(folder / "result.json")
            row = rows[(route, qid)]
            kind = settings["parser_routes"][route]
            candidate_file = f"data/doctr/{image['id']}.json" if route == "doctr_smollm" else f"data/ocr/{image['id']}.json"
            ocr = read(HERE / candidate_file)
            prompt = contracts.make_prompt({**image, "questions": [question]}, kind, questions, ocr)
            require((folder / "prompt.txt").read_bytes() == prompt.replace("\n", "\r\n").encode(), f"Prompt contract {route}/{qid}")
            require(record["model_input_prompt_lf_sha256"] == hashlib.sha256(prompt.encode()).hexdigest(), f"LF input binding {route}/{qid}")
            require(record["prompt_sha256"] == sha(folder / "prompt.txt"), f"Prompt hash {route}/{qid}")
            require(record["image_sha256"] == sha(HERE / f"assets/prepared/{image['id']}.png"), f"Image hash {route}/{qid}")
            require(record["question"] == question and record["question_id"] == qid and record["route"] == route, f"Question binding {route}/{qid}")
            require(record["status"] == "completed" and not record["reference_read_by_inference"], f"Inference boundary {route}/{qid}")
            require(record["settings"] == settings["generation_settings"], f"Generation settings {route}/{qid}")
            raw = folder / "raw.txt"
            require(record["raw_sha256"] == row["raw_sha256"] == sha(raw), f"Raw binding {route}/{qid}")
            require(row["result_sha256"] == sha(folder / "result.json") and row["raw"] == f"calls/{route}/{qid}/raw.txt", f"Judgment binding {route}/{qid}")
            parsed = contracts.parse_answer(raw.read_text(encoding="utf-8"), kind, [qid], {c["id"] for c in ocr["candidates"]})
            require(parsed == record["parsed"] and parsed["valid"] == row["schema_valid"], f"Parser replay {route}/{qid}")
            require(row["category"] == question["category"], f"Category {route}/{qid}")
            records.append(record)
            route_rows.append(row)
        content = sum(row["content_correct"] for row in route_rows)
        schema = sum(row["schema_valid"] for row in route_rows)
        require((content, schema) == (content_expected, schema_expected), route + " totals")
        require(set(reviews[route]["correct"]) == {row["question_id"] for row in route_rows if row["content_correct"]}, route + " review labels")
        recorded = historical["routes"][route]
        require(recorded["content_correct"] == content and recorded["schema_valid"] == schema, route + " recorded totals")
        require(recorded["content_and_schema"] == sum(row["content_correct"] and row["schema_valid"] for row in route_rows), route + " joint totals")
        require(recorded["generation_sum_s"] == sum(r["generation_s"] for r in records), route + " generation timing")
        require(recorded["generation_median_s"] == statistics.median(r["generation_s"] for r in records), route + " median timing")
        for category in ("exact_color", "spatial", "semantic"):
            group = [row for row in route_rows if row["category"] == category]
            require(len(group) == 6 and recorded["by_category"][category] == {"correct": sum(row["content_correct"] for row in group), "total": 6}, route + " category totals")
        summaries[route] = {"generated": 18, "content_correct": content, "schema_valid": schema}
    require(not any(name == "torch" or name.startswith("transformers") for name in sys.modules), "Inference package unexpectedly loaded")
    print(json.dumps({"files_verified": len(actual), "bytes_verified": sum((HERE / p).stat().st_size for p in actual),
          "raw_answers_reparsed": 108, "prompt_contracts_replayed": 108, "local_markdown_links_checked": links,
          "ai_adjudicated_totals": summaries, "inference_executed": False,
          "accuracy_independently_rescored": False, "private_tree_accessed": False,
          "historical_cpu_chat_equality": "receipt_only_not_reverified"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
