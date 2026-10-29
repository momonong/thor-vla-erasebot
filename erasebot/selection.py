"""驗證整份 fixture，再以文字及顏色精確選取目標。"""

import json
import math
import os
import stat

EXIT_CODES = {"selected": 0, "no_match": 1, "ambiguous": 2, "invalid_input": 3}


class InputError(ValueError):
    """可直接轉為 JSON 診斷的輸入錯誤。"""

    def __init__(self, stage, path, message):
        super().__init__(message)
        self.stage = stage
        self.path = path


def invalid_result(stage, errors):
    return {
        "schema_version": 1,
        "fixture": True,
        "dry_run": True,
        "status": "invalid_input",
        "selected_target": None,
        "candidate_ids": [],
        "coordinates": None,
        "diagnostics": {"stage": stage, "target_count": None, "candidate_count": 0, "errors": errors},
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重複 JSON key：{key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"JSON 不允許非有限數字：{value}")


def load_json(path, document):
    """只讀一般檔案的 UTF-8 JSON，拒絕重複 key 與非標準數字常數。"""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise OSError("只接受一般檔案（regular file）")
        # POSIX 上 nonblocking open 避免檢查後被換入 FIFO 而等待 writer；再驗實際 fd。
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("實際開啟的輸入必須是一般檔案（regular file）")
            with os.fdopen(descriptor, encoding="utf-8", closefd=False) as source:
                content = source.read()
        finally:
            os.close(descriptor)
    except (OSError, UnicodeError) as exc:
        raise InputError("read", document, f"無法讀取 UTF-8 JSON：{exc}") from exc
    try:
        return json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise InputError("json", document, f"JSON 解析失敗：{exc}") from exc


def _error(errors, path, message):
    errors.append({"path": path, "message": message})


def _object(value, path, fields, errors):
    if type(value) is not dict:
        _error(errors, path, "必須是 JSON object")
        return False
    for field in sorted(fields - value.keys()):
        _error(errors, f"{path}.{field}", "缺少必要欄位")
    for field in sorted(value.keys() - fields):
        _error(errors, f"{path}.{field}", "不接受未知欄位")
    return True


def _literal(obj, field, expected, path, errors):
    if field in obj and (type(obj[field]) is not type(expected) or obj[field] != expected):
        _error(errors, f"{path}.{field}", f"必須是 {expected!r}")


def _text(obj, field, path, errors):
    if field in obj and (type(obj[field]) is not str or not obj[field].strip()):
        _error(errors, f"{path}.{field}", "必須是非空白字串")


def _validate_command(command, errors):
    if not _object(command, "command", {"schema_version", "fixture", "action", "text", "color"}, errors):
        return
    _literal(command, "schema_version", 1, "command", errors)
    _literal(command, "fixture", True, "command", errors)
    _literal(command, "action", "erase", "command", errors)
    _text(command, "text", "command", errors)
    _text(command, "color", "command", errors)


def _validate_bbox(bbox, path, width, height, errors):
    if type(bbox) is not list or len(bbox) != 4:
        _error(errors, path, "必須是四個有限數值的 [x_min, y_min, x_max, y_max]")
        return
    valid = True
    for index, value in enumerate(bbox):
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            _error(errors, f"{path}[{index}]", "必須是有限 int/float，不能是 bool")
            valid = False
    if not valid:
        return
    x_min, y_min, x_max, y_max = bbox
    if x_min < 0 or y_min < 0 or x_min >= x_max or y_min >= y_max:
        _error(errors, path, "座標須非負，且 x_min < x_max、y_min < y_max")
    if width is not None and height is not None and (x_max > width or y_max > height):
        _error(errors, path, "bbox 不可超出 image_size 邊界")


def _validate_scene(scene, errors):
    fields = {"schema_version", "fixture", "coordinate_frame", "unit", "image_size", "targets"}
    if not _object(scene, "scene", fields, errors):
        return
    for field, expected in [("schema_version", 1), ("fixture", True), ("coordinate_frame", "image"), ("unit", "px")]:
        _literal(scene, field, expected, "scene", errors)
    width = height = None
    if "image_size" in scene and _object(scene["image_size"], "scene.image_size", {"width", "height"}, errors):
        for field in ("width", "height"):
            if field in scene["image_size"]:
                value = scene["image_size"][field]
                if type(value) is not int or value <= 0:
                    _error(errors, f"scene.image_size.{field}", "必須是正整數，不能是 bool")
        dimensions = scene["image_size"]
        if all(type(dimensions.get(field)) is int and dimensions[field] > 0 for field in ("width", "height")):
            width, height = dimensions["width"], dimensions["height"]
    if "targets" not in scene:
        return
    if type(scene["targets"]) is not list:
        _error(errors, "scene.targets", "必須是 JSON array")
        return
    ids = set()
    for index, target in enumerate(scene["targets"]):
        path = f"scene.targets[{index}]"
        if not _object(target, path, {"id", "text", "color", "bbox"}, errors):
            continue
        for field in ("id", "text", "color"):
            _text(target, field, path, errors)
        identifier = target.get("id")
        if type(identifier) is str and identifier.strip():
            if identifier in ids:
                _error(errors, f"{path}.id", "id 不可重複")
            ids.add(identifier)
        if "bbox" in target:
            _validate_bbox(target["bbox"], f"{path}.bbox", width, height, errors)


def select_target(command, scene):
    """完整驗證成功才比對；非唯一結果永遠不選取任何目標。"""
    errors = []
    _validate_command(command, errors)
    _validate_scene(scene, errors)
    if errors:
        return invalid_result("validation", errors)
    candidates = [target for target in scene["targets"]
                  if target["text"] == command["text"] and target["color"] == command["color"]]
    count = len(candidates)
    status = "no_match" if count == 0 else "selected" if count == 1 else "ambiguous"
    return {
        "schema_version": 1,
        "fixture": True,
        "dry_run": True,
        "status": status,
        "selected_target": candidates[0] if count == 1 else None,
        "candidate_ids": [target["id"] for target in candidates],
        "coordinates": {"coordinate_frame": scene["coordinate_frame"], "unit": scene["unit"],
                        "image_size": scene["image_size"]},
        "diagnostics": {"stage": "selection", "target_count": len(scene["targets"]),
                        "candidate_count": count, "errors": []},
    }
