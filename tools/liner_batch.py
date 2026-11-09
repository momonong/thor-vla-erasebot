"""只讀本機 JSON 的離線批次證據報告；不代表實機成果。"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import stat

from erasebot.selection import InputError
from liner_evaluation import evaluate


MAX_BYTES = 2 * 1024 * 1024
STATUSES = ("criteria_met", "criteria_not_met", "insufficient_evidence",
            "invalid_input", "not_run")
METHODS = ("fixed_script", "visual_feedback", "learned_policy")
EVIDENCE_KINDS = ("synthetic_fixture", "offline_annotation")
LIMITATIONS = (
    "本報告僅為離線（offline）軟體判定，合成案例不是實機成果；未實機驗證。",
    "來源未驗真（source_references_verified=false）；來源標籤不會被開啟，SHA256 僅識別內容。",
    "A/B、方法與 evidence_kind 分組獨立；不得據此宣稱模型優劣或機器人成績。",
    "unknown／未知保留為 null；not_run 表示未執行，invalid_input 不得省略以提高成功率。",
)


def _invalid(path, message):
    raise InputError("validation", path, message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重複 JSON key：{key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"JSON 不允許非有限數字：{value}")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("JSON 數字超出有限浮點數範圍")
    return value


def _parse_json(content, label):
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError("json", label, f"JSON 解析失敗：{exc}") from exc


def _directory_flags():
    # Fail closed where descriptor-relative, no-follow traversal is unavailable.
    if (os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")):
        raise InputError("read", "manifest", "此平台不支援安全的目錄描述符／no-follow 讀取")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_root(parent):
    """逐層開啟 manifest 目錄，拒絕任何 symlink，固定目錄描述符。"""
    flags = _directory_flags()
    descriptor = None
    try:
        descriptor = os.open(parent.anchor, flags)
        for part in parent.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (OSError, UnicodeError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise InputError("read", "manifest", f"無法安全開啟 manifest 目錄：{exc}") from exc


def _read_bytes(root_fd, parts, label):
    """只沿根目錄內的非 symlink 子路徑讀取，限制 bytes 並驗證實際 fd。"""
    directory = None
    descriptor = None
    try:
        directory = os.dup(root_fd)
        for part in parts[:-1]:
            child = os.open(part, _directory_flags(), dir_fd=directory)
            os.close(directory)
            directory = child
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(parts[-1], flags, dir_fd=directory)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("只接受一般檔案（regular file）")
        if info.st_size > MAX_BYTES:
            raise OSError("單檔不可超過 2 MiB")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            content = source.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES or os.fstat(descriptor).st_size > MAX_BYTES:
            raise OSError("單檔不可超過 2 MiB")
        return content
    except (OSError, UnicodeError) as exc:
        raise InputError("read", label, f"無法安全讀取輸入：{exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def _relative_parts(value, label):
    if type(value) is not str or not value.strip() or "\x00" in value:
        _invalid(label, "路徑必須是非空白字串且不可含 NUL")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if (path.is_absolute() or windows_path.drive or windows_path.root
            or ".." in path.parts or ".." in windows_path.parts):
        _invalid(label, "只接受 manifest 目錄內的相對路徑，不可包含 '..'")
    if not path.parts:
        _invalid(label, "路徑必須指向檔案")
    return path.parts


def _exact_fields(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        _invalid(label, "必須是恰含以下欄位的 object：" + ", ".join(sorted(fields)))


def _validate_manifest(document):
    _exact_fields(document, {"schema_version", "entries"}, "manifest")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        _invalid("manifest.schema_version", "必須是整數 1，不能是 bool")
    entries = document["entries"]
    if type(entries) is not list or not 1 <= len(entries) <= 2000:
        _invalid("manifest.entries", "必須是長度 1..2000 的 list")
    seen = set()
    paths = []
    for index, entry in enumerate(entries):
        label = f"manifest.entries[{index}]"
        _exact_fields(entry, {"case_id", "material", "method", "target", "observation"}, label)
        if type(entry["case_id"]) is not str or not entry["case_id"].strip():
            _invalid(label + ".case_id", "必須是非空白字串")
        if type(entry["material"]) is not str or entry["material"] not in ("A", "B"):
            _invalid(label + ".material", "必須是 A 或 B")
        if type(entry["method"]) is not str or entry["method"] not in METHODS:
            _invalid(label + ".method", "未知方法")
        key = (entry["material"], entry["method"], entry["case_id"])
        if key in seen:
            _invalid(label, "(material, method, case_id) 不可重複")
        seen.add(key)
        paths.append({field: _relative_parts(entry[field], label + "." + field)
                      for field in ("target", "observation")})
    return paths


def _diagnostics(errors):
    return {"stage": errors[0].stage,
            "errors": [{"path": error.path, "message": str(error)} for error in errors]}


def _case(root_fd, entry, paths, index):
    case = {field: entry[field] for field in ("case_id", "material", "method")}
    case.update(evidence_kind=None, status="invalid_input", sources={}, result=None)
    documents = {}
    errors = []
    # Read both independently: an invalid target must not conceal identity spoofing.
    for field in ("target", "observation"):
        source = {"path": entry[field], "sha256": None}
        case["sources"][field] = source
        label = f"manifest.entries[{index}].{field}"
        try:
            content = _read_bytes(root_fd, paths[field], label)
            source["sha256"] = hashlib.sha256(content).hexdigest()
            documents[field] = _parse_json(content, label)
        except InputError as exc:
            errors.append(exc)
    observation = documents.get("observation")
    if type(observation) is dict:
        if "case_id" in observation and observation["case_id"] != entry["case_id"]:
            _invalid(f"manifest.entries[{index}].observation.case_id",
                     "觀測 case_id 與 manifest 不符；拒絕整份批次")
        kind = observation.get("evidence_kind")
        if type(kind) is str and kind in EVIDENCE_KINDS:
            case["evidence_kind"] = kind
    if not errors:
        try:
            result = evaluate(documents["target"], documents["observation"])
            case.update(status=result["status"], evidence_kind=result["evidence_kind"], result=result)
        except InputError as exc:
            errors.append(exc)
    if errors:
        case["diagnostics"] = _diagnostics(errors)
    return case


def _groups(cases):
    grouped = {}
    for case in cases:
        key = (case["material"], case["method"], case["evidence_kind"])
        if key not in grouped:
            grouped[key] = {"material": key[0], "method": key[1], "evidence_kind": key[2],
                            "counts": dict.fromkeys(STATUSES, 0)}
        grouped[key]["counts"][case["status"]] += 1
    groups = []
    for key in sorted(grouped, key=lambda item: (item[0], item[1], item[2] or "")):
        group = grouped[key]
        counts = group["counts"]
        attempted = sum(counts[status] for status in STATUSES[:3])
        rate = None
        if attempted and not counts["insufficient_evidence"] and not counts["invalid_input"]:
            rate = counts["criteria_met"] / attempted
        group.update(total=sum(counts.values()), attempted=attempted, success_rate=rate)
        groups.append(group)
    return groups


def evaluate_batch(manifest_path):
    """有效 manifest 回傳完整報告；結構／重複／身份不符拋出 InputError。"""
    try:
        path_text = os.fspath(manifest_path)
    except TypeError as exc:
        raise InputError("validation", "manifest", "manifest 必須是檔案路徑") from exc
    if type(path_text) is not str or not path_text.strip() or "\x00" in path_text:
        _invalid("manifest", "manifest 路徑不可為空或含 NUL，且須為文字路徑")
    path = Path(path_text)
    if ".." in path.parts:
        _invalid("manifest", "manifest 路徑不可包含 '..'")
    try:
        path = path.absolute()
    except OSError as exc:
        raise InputError("read", "manifest", f"無法解析 manifest 路徑：{exc}") from exc
    if not path.name:
        _invalid("manifest", "manifest 必須指向一般檔案")
    root_fd = _open_root(path.parent)
    try:
        document = _parse_json(_read_bytes(root_fd, (path.name,), "manifest"), "manifest")
        paths = _validate_manifest(document)
        cases = [_case(root_fd, entry, paths[index], index)
                 for index, entry in enumerate(document["entries"])]
    finally:
        os.close(root_fd)
    return {"schema_version": 1, "mode": "offline", "robot_validated": False,
            "source_references_verified": False, "cases": cases, "groups": _groups(cases),
            "limitations": list(LIMITATIONS)}


def _cell(value):
    if value is None:
        return "unknown"
    text = str(value).encode("utf-8", "backslashreplace").decode("utf-8")
    text = "\\n".join(text.splitlines()).replace("\\", "\\\\")
    for character in "|`*_{}[]()!#":
        text = text.replace(character, "\\" + character)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(values):
    return "| " + " | ".join(_cell(value) for value in values) + " |"


def render_markdown(report):
    """將 evaluate_batch 報告渲染為純 Markdown，未知不補零。"""
    lines = ["# Thor 離線批次證據報告", "", "未實機驗證／不是實機成果；來源未驗真。", "",
             "not_run 表示未執行，不計入 attempted；unknown／未知表示資料不足，不能當零或成功。",
             "含 insufficient_evidence 或 invalid_input 的組別不提供數字成功率；不計算跨組總成功率。",
             "", "## 分組", "",
             "| material | method | evidence_kind | total | attempted | criteria_met | criteria_not_met | insufficient_evidence | invalid_input | not_run | success_rate |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for group in report["groups"]:
        # Fractions avoid rounding a small known rate to zero percent.
        rate = group["success_rate"]
        rate_text = None if rate is None else f'{group["counts"]["criteria_met"]}/{group["attempted"]} ({rate:.6g})'
        lines.append(_row([group["material"], group["method"], group["evidence_kind"],
                           group["total"], group["attempted"],
                           *(group["counts"][status] for status in STATUSES), rate_text]))
    lines.extend(["", "## 案例（原始順序）", "",
                  "| case_id | material | method | evidence_kind | status | coverage | IoU | duration_s | cycles | human_interventions | diagnostics |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
    for case in report["cases"]:
        result = case["result"] or {}
        metrics = result.get("metrics") or {}
        recorded = result.get("recorded") or {}
        diagnostic = case.get("diagnostics")
        detail = "; ".join(f'{error["path"]}: {error["message"]}'
                           for error in diagnostic["errors"]) if diagnostic else "—"
        lines.append(_row([case["case_id"], case["material"], case["method"],
                           case["evidence_kind"], case["status"], metrics.get("coverage"),
                           metrics.get("iou"), recorded.get("duration_s"), recorded.get("cycles"),
                           recorded.get("human_interventions"), detail]))
    lines.extend(["", "## 來源（SHA256 為原始檔案 bytes）", "",
                  "| case_id | material | method | source | relative_path | sha256 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for case in report["cases"]:
        for field in ("target", "observation"):
            source = case["sources"][field]
            lines.append(_row([case["case_id"], case["material"], case["method"], field,
                               source["path"], source["sha256"]]))
    lines.extend(["", "## 證據限制", ""])
    lines.extend("- " + _cell(item) for item in report["limitations"])
    return "\n".join(lines) + "\n"


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("arguments", "arguments", message)


def main(argv=None):
    parser = _Parser(description="Thor 離線批次證據報告；未實機驗證。", allow_abbrev=False)
    parser.add_argument("--manifest", required=True, help="本機批次 manifest JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    try:
        args = parser.parse_args(argv)
        report = evaluate_batch(args.manifest)
    except InputError as exc:
        result = {"schema_version": 1, "mode": "offline", "robot_validated": False,
                  "source_references_verified": False, "status": "invalid_input",
                  "diagnostics": _diagnostics([exc])}
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
        return 3
    if args.format == "markdown":
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    return 0 if all(case["status"] == "criteria_met" for case in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
