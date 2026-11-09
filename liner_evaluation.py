"""襯材遮罩與紀錄的離線評估；不讀感測器、不執行或產生機器人動作。"""

import argparse
import hashlib
import json
import math

from erasebot.selection import InputError, load_json


MAX_PIXELS = 4_000_000
PROTOCOL_VERSION = "0.1"
EXIT_CODES = {"target_info": 0, "criteria_met": 0, "criteria_not_met": 1,
              "insufficient_evidence": 2, "invalid_input": 3, "not_run": 4}
TARGET_FIELDS = {"schema_version", "target_id", "frame_id", "mask_rows"}
OBSERVATION_FIELDS = {
    "schema_version", "case_id", "evidence_kind", "source_ref", "target_id",
    "target_sha256", "frame_id", "mask_rows", "fold_check", "duration_s",
    "cycles", "human_interventions", "execution_status",
}


def _invalid(path, message):
    raise InputError("validation", path, message)


def _object(value, fields, path):
    if type(value) is not dict:
        _invalid(path, "必須是 JSON object")
    missing = fields - value.keys()
    if missing:
        _invalid(path, "缺少必要欄位：" + ", ".join(sorted(missing)))
    unknown = value.keys() - fields
    if unknown:
        _invalid(path, "不接受未知欄位：" + ", ".join(sorted(map(str, unknown))))


def _text(value, path):
    if type(value) is not str or not value.strip():
        _invalid(path, "必須是非空白字串")


def _version(document, path):
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        _invalid(path + ".schema_version", "必須是整數 1，不能是 bool")


def _choice(value, choices, path):
    if type(value) is not str or value not in choices:
        _invalid(path, "必須是其中之一：" + ", ".join(choices))


def _mask(rows, path):
    if type(rows) is not list or not rows or type(rows[0]) is not str or not rows[0]:
        _invalid(path, "必須是非空的 0／1 字串列")
    width = len(rows[0])
    if width * len(rows) > MAX_PIXELS:
        _invalid(path, f"遮罩不可超過 {MAX_PIXELS} 像素")
    area = 0
    for index, row in enumerate(rows):
        if type(row) is not str or len(row) != width or not set(row) <= {"0", "1"}:
            _invalid(f"{path}[{index}]", "每列須同寬且只含 ASCII 0／1")
        area += row.count("1")
    return {"width": width, "height": len(rows), "area_px": area}


def _target_info(target):
    _object(target, TARGET_FIELDS, "target")
    _version(target, "target")
    for field in ("target_id", "frame_id"):
        _text(target[field], "target." + field)
    info = _mask(target["mask_rows"], "target.mask_rows")
    if info["area_px"] == 0:
        _invalid("target.mask_rows", "目標區域不可為空")
    canonical = json.dumps(target, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"target_id": target["target_id"], "frame_id": target["frame_id"],
            "sha256": hashlib.sha256(canonical).hexdigest(), **info}


def target_digest(target):
    """驗證後傳回 canonical JSON SHA256；識別內容，不證明校正或來源。"""
    return _target_info(target)["sha256"]


def _measurement(value, path, integer=False):
    if value is None:
        return
    allowed = (int,) if integer else (int, float)
    if (type(value) not in allowed or value < 0
            or (type(value) is float and not math.isfinite(value))):
        _invalid(path, "必須是非負有限數值或 null；計數須為整數，不能是 bool")


def _validate_observation(observation, info):
    _object(observation, OBSERVATION_FIELDS, "observation")
    _version(observation, "observation")
    for field in ("case_id", "source_ref", "target_id", "target_sha256", "frame_id"):
        _text(observation[field], "observation." + field)
    _choice(observation["evidence_kind"], ("synthetic_fixture", "offline_annotation"),
            "observation.evidence_kind")
    _choice(observation["execution_status"], ("completed", "failed", "aborted", "not_run"),
            "observation.execution_status")
    for field, expected in (("target_id", info["target_id"]),
                            ("frame_id", info["frame_id"]), ("target_sha256", info["sha256"])):
        if observation[field] != expected:
            _invalid("observation." + field, "與固定目標不一致；請核對原始目標與座標")
    fold = observation["fold_check"]
    _object(fold, {"status", "reference"}, "observation.fold_check")
    _choice(fold["status"], ("clear", "folded", "unknown"), "observation.fold_check.status")
    if fold["status"] != "unknown" or fold["reference"] is not None:
        _text(fold["reference"], "observation.fold_check.reference")
    for field in ("duration_s", "cycles", "human_interventions"):
        _measurement(observation[field], "observation." + field, integer=field != "duration_s")
    observed_info = None
    if observation["mask_rows"] is not None:
        observed_info = _mask(observation["mask_rows"], "observation.mask_rows")
        if (observed_info["width"], observed_info["height"]) != (info["width"], info["height"]):
            _invalid("observation.mask_rows", "觀測與目標須使用相同像素格網與尺寸")
    if observation["execution_status"] == "not_run":
        for field in ("mask_rows", "duration_s", "cycles", "human_interventions"):
            if observation[field] is not None:
                _invalid("observation." + field, "not_run 必須使用 null，不可填入觀測或量測")
        if fold != {"status": "unknown", "reference": None}:
            _invalid("observation.fold_check", "not_run 的摺角狀態須為 unknown 且 reference 為 null")
    return observed_info


def _base_result(status):
    return {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "mode": "offline",
            "status": status, "robot_validated": False, "source_references_verified": False}


def evaluate(target, observation):
    """評估一筆紀錄；未知不當零，已知失敗優先於證據不足。"""
    info = _target_info(target)
    observed_info = _validate_observation(observation, info)
    metrics = None
    if observed_info is not None:
        intersection = sum(a == b == "1" for goal_row, seen_row in
                           zip(target["mask_rows"], observation["mask_rows"])
                           for a, b in zip(goal_row, seen_row))
        union = info["area_px"] + observed_info["area_px"] - intersection
        metrics = {"target_area_px": info["area_px"], "observed_area_px": observed_info["area_px"],
                   "intersection_px": intersection, "union_px": union,
                   "coverage": intersection / info["area_px"], "iou": intersection / union}

    # 比例以整數交叉相乘判門檻，避免恰好 95%／90% 的浮點邊界誤判。
    fold = observation["fold_check"]["status"]
    checks = {
        "coverage": None if metrics is None else metrics["intersection_px"] * 100 >= info["area_px"] * 95,
        "iou": None if metrics is None else metrics["intersection_px"] * 10 >= metrics["union_px"] * 9,
        "fold_clear": None if fold == "unknown" else fold == "clear",
        "duration_s": None if observation["duration_s"] is None else observation["duration_s"] <= 90,
        "cycles": None if observation["cycles"] is None else observation["cycles"] <= 6,
        "human_interventions": None if observation["human_interventions"] is None else observation["human_interventions"] == 0,
        "execution_completed": None if observation["execution_status"] == "not_run" else observation["execution_status"] == "completed",
    }
    failed = [name for name, passed in checks.items() if passed is False]
    missing = [name for name, passed in checks.items() if passed is None]
    if observation["execution_status"] == "not_run":
        status = "not_run"
    elif failed:
        status = "criteria_not_met"
    elif missing:
        status = "insufficient_evidence"
    else:
        status = "criteria_met"
    return {
        **_base_result(status), "case_id": observation["case_id"],
        "evidence_kind": observation["evidence_kind"], "source_ref": observation["source_ref"],
        "target": info, "metrics": metrics, "checks": checks,
        "failed_checks": failed, "missing_evidence": missing,
        "recorded": {field: observation[field] for field in
                     ("fold_check", "duration_s", "cycles", "human_interventions", "execution_status")},
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("arguments", "arguments", message)


def main(argv=None):
    parser = _Parser(description="襯材離線遮罩評估：只讀本機 JSON；結果不代表實機驗證。", allow_abbrev=False)
    parser.add_argument("--target", required=True, help="固定目標 JSON；單獨使用時輸出指紋與尺寸")
    parser.add_argument("--observation", help="觀測／合成案例 JSON；參照標籤不會被開啟")
    try:
        args = parser.parse_args(argv)
        for field in ("target", "observation"):
            path = getattr(args, field)
            if path is not None and (not path or "\x00" in path):
                raise InputError("arguments", field, "路徑不可為空或含 NUL")
        target = load_json(args.target, "target")
        if args.observation is None:
            result = {**_base_result("target_info"), "target": _target_info(target)}
        else:
            result = evaluate(target, load_json(args.observation, "observation"))
    except InputError as exc:
        result = {**_base_result("invalid_input"), "diagnostics": {
            "stage": exc.stage, "errors": [{"path": exc.path, "message": str(exc)}]}}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
