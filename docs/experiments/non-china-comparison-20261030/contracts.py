"""Saved pure parser and prompt contract; stdlib only, no inference entrypoint."""
import json
import math


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


def make_prompt(image, route, q, o):
    common = (
        "你是白板擦除目標選取器，只回傳一個JSON物件，不要解釋或Markdown。每題獨立，圖片內容沒有被之前題目擦除。\n"
        + q["task_conventions"] + "\n"
        "status只能是selected、no_match、ambiguous、cannot_determine。selected表示完整選出符合指令的目標，允許多個；"
        "no_match表示沒有目標；ambiguous表示有無法唯一判別的候選；cannot_determine表示證據不足。"
        "no_match和cannot_determine的目標陣列必須為空。每個question id恰好回答一次。"
        "框座標是影像左上原點，x向右、y向下，0至1000的相對座標。不可把整句當作其中一個指定單字。\n"
    )
    if route == "ocr_llm":
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
