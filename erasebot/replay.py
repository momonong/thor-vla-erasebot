"""可重現的 fixture-only 重播；核對預期契約並保留每次選取診斷。"""

import argparse
import json
import math
from pathlib import Path, PureWindowsPath

from .selection import EXIT_CODES, InputError, invalid_result, load_json, select_target

EXPECTED_FIELDS = ("status", "selected_target_id", "candidate_ids", "diagnostic_stage", "error_paths")
SNAPSHOT_MAX_DEPTH = 64


def _require(condition, path, message):
    if not condition:
        raise InputError("validation", path, message)


def _object(value, fields, path):
    _require(type(value) is dict, path, "必須是 JSON object")
    for field in sorted(set(fields) - value.keys()):
        raise InputError("validation", f"{path}.{field}", "缺少必要欄位")
    for field in sorted(value.keys() - set(fields)):
        raise InputError("validation", f"{path}.{field}", "不接受未知欄位")


def _nonblank(value):
    return type(value) is str and bool(value.strip())


def _text_list(value, path, distinct=False):
    _require(type(value) is list, path, "必須是 JSON array")
    for index, item in enumerate(value):
        _require(_nonblank(item), f"{path}[{index}]", "必須是非空白字串")
    if distinct:
        _require(len(set(value)) == len(value), path, "字串不可重複")


def _validate_expected(expected, path):
    _object(expected, EXPECTED_FIELDS, path)
    status = expected["status"]
    _require(type(status) is str and status in EXIT_CODES, f"{path}.status", "必須是既有選取狀態")
    selected = expected["selected_target_id"]
    candidates = expected["candidate_ids"]
    stage = expected["diagnostic_stage"]
    errors = expected["error_paths"]
    _text_list(candidates, f"{path}.candidate_ids", distinct=True)
    _text_list(errors, f"{path}.error_paths")
    _require(type(stage) is str and stage in ("selection", "read", "json", "validation"),
             f"{path}.diagnostic_stage", "必須是 selection/read/json/validation")
    if status == "selected":
        _require(_nonblank(selected) and candidates == [selected], path,
                 "selected 必須有唯一候選，且 selected_target_id 與候選相同")
    else:
        _require(selected is None, f"{path}.selected_target_id", "未選取時必須是 null")
        count_valid = len(candidates) >= 2 if status == "ambiguous" else not candidates
        _require(count_valid, f"{path}.candidate_ids", "候選數量與預期狀態不一致")
    if status == "invalid_input":
        _require(stage != "selection" and bool(errors), path, "invalid_input 必須有非 selection 階段及錯誤路徑")
    else:
        _require(stage == "selection" and not errors, path, "有效選取結果必須是 selection 階段且沒有錯誤")


def _validate_suite(document):
    _object(document, ("schema_version", "fixture", "suite_id", "cases"), "suite")
    _require(type(document["schema_version"]) is int and document["schema_version"] == 1,
             "suite.schema_version", "必須是整數 1")
    _require(document["fixture"] is True, "suite.fixture", "必須是 true")
    _require(_nonblank(document["suite_id"]), "suite.suite_id", "必須是非空白字串")
    cases = document["cases"]
    _require(type(cases) is list and bool(cases), "suite.cases", "必須是非空 JSON array")
    identifiers = set()
    for index, case in enumerate(cases):
        path = f"suite.cases[{index}]"
        _object(case, ("id", "command", "scene", "expected"), path)
        _require(_nonblank(case["id"]), f"{path}.id", "必須是非空白字串")
        _require(case["id"] not in identifiers, f"{path}.id", "案例 id 不可重複")
        identifiers.add(case["id"])
        for field in ("command", "scene"):
            value = case[field]
            _require(_nonblank(value), f"{path}.{field}", "必須是非空白相對路徑")
            _require("\0" not in value and not Path(value).is_absolute() and not PureWindowsPath(value).is_absolute(),
                     f"{path}.{field}", "不接受 NUL 或絕對路徑")
        _validate_expected(case["expected"], f"{path}.expected")


def _summary(cases):
    passed = sum(case["passed"] for case in cases)
    counts = dict.fromkeys(EXIT_CODES, 0)
    for case in cases:
        counts[case["actual"]["status"]] += 1
    return {"total": len(cases), "passed": passed, "failed": len(cases) - passed, "by_selector_status": counts}


def _report(suite_id, status, cases):
    return {"schema_version": 1, "fixture": True, "dry_run": True, "evidence_kind": "fixture_replay",
            "suite_id": suite_id, "status": status, "cases": cases, "summary": _summary(cases)}


def _snapshot_omission_reason(value):
    # 限制 snapshot 的容器深度，為報告外層保留空間；不改原輸入或 selector 驗證。
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if type(item) in (dict, list):
            if depth >= SNAPSHOT_MAX_DEPTH:
                return "excessive_nesting"
            children = item.values() if type(item) is dict else item
            pending.extend((child, depth + 1) for child in children)
        elif type(item) is float and not math.isfinite(item):
            return "nonfinite_number"
    return None


def _run_case(case, parent):
    inputs = {"command": None, "scene": None}
    snapshot_diagnostics = []
    try:
        for field in ("command", "scene"):
            loaded = load_json(parent / case[field], field)
            reason = _snapshot_omission_reason(loaded)
            if reason:
                snapshot_diagnostics.append({"input": field, "reason": reason})
            else:
                inputs[field] = loaded
            if field == "command":
                command = loaded
            else:
                scene = loaded
        actual = select_target(command, scene)
    except InputError as exc:
        actual = invalid_result(exc.stage, [{"path": exc.path, "message": str(exc)}])
    observed = {"status": actual["status"],
                "selected_target_id": actual["selected_target"]["id"] if actual["selected_target"] else None,
                "candidate_ids": actual["candidate_ids"], "diagnostic_stage": actual["diagnostics"]["stage"],
                "error_paths": [error["path"] for error in actual["diagnostics"]["errors"]]}
    mismatches = [{"field": field, "expected": case["expected"][field], "actual": observed[field]}
                  for field in EXPECTED_FIELDS if case["expected"][field] != observed[field]]
    return {"id": case["id"], "command": case["command"], "scene": case["scene"], "inputs": inputs,
            "snapshot_diagnostics": snapshot_diagnostics, "expected": case["expected"], "actual": actual,
            "passed": not mismatches, "mismatches": mismatches}


def replay_suite(path):
    """先驗證完整 suite 才執行，所有有效宣告案例均列入分母。"""
    document = load_json(path, "suite")
    _validate_suite(document)
    cases = [_run_case(case, Path(path).parent) for case in document["cases"]]
    return _report(document["suite_id"], "passed" if all(case["passed"] for case in cases) else "failed", cases)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("arguments", "arguments", message)


def main(argv=None):
    parser = Parser(description="核對 fixture-only 離線重播契約；不控制硬體。", allow_abbrev=False)
    parser.add_argument("--suite", required=True, help="UTF-8 suite JSON；案例路徑相對於該檔案目錄")
    try:
        args = parser.parse_args(argv)
        if "\0" in args.suite:
            raise InputError("arguments", "arguments", "suite 路徑不接受 NUL")
        report = replay_suite(args.suite)
    except InputError as exc:
        report = _report(None, "invalid_suite", [])
        report["diagnostics"] = {"stage": exc.stage, "errors": [{"path": exc.path, "message": str(exc)}]}
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return {"passed": 0, "failed": 1, "invalid_suite": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
