"""Allowlisted evidence export. No inference, downloads, packages, or source writes."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROUTES = ("qwen_llm", "qwen_vlm", "smolvlm", "doctr_smollm", "gemma", "phi")
ORIGINS = {}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root):
    return [(p.relative_to(root).as_posix(), p.stat().st_size, sha(p))
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def write(relative, value, sources=(), note="Generated archive documentation or metadata."):
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_text(data, encoding="utf-8", newline="\n")
    ORIGINS[relative] = {"disposition": "transformed" if sources else "generated", "conversion": note,
                         "source_receipts": [{"source": label, "sha256": sha(origin)} for label, origin in sources]}


def cp(origin, relative, label):
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origin, path)
    ORIGINS[relative] = {"disposition": "byte_exact_copy", "source": label,
                         "source_sha256": sha(origin), "conversion": "None; original bytes including line endings."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE.parents[2] / "experiments/non-china-comparison-20261030")
    parser.add_argument("--baseline", type=Path, default=HERE.parent / "photo-comparison-20261030")
    args = parser.parse_args()
    source, base = args.source.resolve(), args.baseline.resolve()
    before, base_before = inventory(source), inventory(base)
    assert len(before) == 484 and sum(x[1] for x in before) == 1331754, "Unexpected source snapshot; review first."

    def new_copy(rel, dest=None):
        cp(source / rel, dest or rel, "new_experiment/" + rel)

    def old_copy(rel, dest=None):
        cp(base / rel, dest or rel, "published_baseline/" + rel)

    for rel in ("data/questions.json", "data/reference.ai.json", "data/images.json", "sources.json"):
        old_copy(rel)
    for image in ("colour", "fruits", "english"):
        old_copy(f"assets/prepared/{image}.png")
        old_copy(f"data/ocr/{image}.json")
        new_copy(f"ocr/{image}.json", f"data/doctr/{image}.json")
    old_copy("config/models.json", "config/baseline-models.json")
    new_copy("ocr/config.json", "config/doctr.json")
    new_copy("ocr/prompt-contract.json", "receipts/doctr-prompt-contract.json")
    new_copy("environments.json", "config/environments.json")
    new_copy("environments-after-repair.json", "config/environments-after-repair.json")
    new_copy("gpu-preflight.json", "receipts/gpu-preflight.json")
    new_copy("contract-checks.json", "receipts/contract-checks.json")
    new_copy("smol-technical-repair.json", "receipts/smol-technical-repair.json")
    new_copy("verification.json", "receipts/historical-verification.json")
    assets = read(source / "model-assets.json")
    for model in assets["models"]:
        model.pop("local_dir", None)
    write("config/model-assets.json", assets, [("new_experiment/model-assets.json", source / "model-assets.json")],
          "Removed local_dir locators only; model IDs, revisions, per-file bytes and SHA/LFS hashes unchanged. Weights are omitted.")
    ocr_assets = read(source / "ocr/assets.json")
    for asset in ocr_assets:
        asset["file"] = asset.pop("path").replace("\\", "/").split("/")[-1]
    write("config/doctr-assets.json", ocr_assets, [("new_experiment/ocr/assets.json", source / "ocr/assets.json")],
          "Replaced weight locators with filenames; hashes and sizes unchanged. Weights are omitted.")

    # Extract pure functions without importing or executing any inference runner.
    original = (base / "source/runner.py").read_text(encoding="utf-8")
    functions = {node.name: ast.get_source_segment(original, node) for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)}
    saved_parser = functions["parse_answer"]
    saved_prompt = functions["make_prompt"].replace("def make_prompt(image, route):", "def make_prompt(image, route, q, o):")
    saved_prompt = saved_prompt.replace("    q = questions()\n", "")
    saved_prompt = saved_prompt.replace('        o = json.loads((HERE / "ocr" / f"{image[\'id\']}.json").read_text(encoding="utf-8"))\n', "")
    assert "HERE" not in saved_prompt and "questions()" not in saved_prompt
    write("contracts.py", '"""Saved pure parser and prompt contract; stdlib only, no inference entrypoint."""\nimport json\nimport math\n\n\n'
          + saved_parser + "\n\n\n" + saved_prompt + "\n", [("published_baseline/source/runner.py", base / "source/runner.py")],
          "Extracted parse_answer function text unchanged after LF normalization. make_prompt only accepts explicit q/o inputs instead of loading files; returned prompt construction unchanged. No runner is imported or included as an execution entrypoint.")
    write("config/contracts.json", {"historical_parser_runner_sha256": sha(base / "source/runner.py"),
          "parser_function_lf_sha256": hashlib.sha256(saved_parser.encode()).hexdigest(),
          "prompt_function_lf_sha256": hashlib.sha256(saved_prompt.encode()).hexdigest(),
          "generation_settings": {"do_sample": False, "max_new_tokens": 3072, "max_time": 840,
                                  "use_cache": True, "repetition_penalty": 1.0},
          "parser_routes": {r: "ocr_llm" if r in ("qwen_llm", "doctr_smollm") else "vlm" for r in ROUTES},
          "runner_source_receipts": [{"source": name, "sha256": sha(source / name)}
                                     for name in ("source-versions/runner-initial.py", "runner.py")],
          "runner_source_included": False, "parser_function_text_unchanged": True,
          "prompt_adaptation": "Explicit q/o arguments replace only questions()/OCR-file reads; no inference or environment setup retained."})

    calls = []
    run = "runs/gpu-baseline-and-alternatives"
    for route in ROUTES:
        attempt = 2 if route == "smolvlm" else 1
        folder = f"{run}/{route}/attempt-{attempt}"
        new_copy(folder + "/summary.json", f"config/routes/{route}.json")
        for record_path in sorted((source / folder).glob("*/result.json")):
            qid = record_path.parent.name
            for name in ("raw.txt", "prompt.txt", "result.json", "rendered-chat.txt"):
                new_copy(f"{folder}/{qid}/{name}", f"calls/{route}/{qid}/{name}")
            calls.append({"route": route, "question_id": qid, "attempt": attempt, "directory": f"calls/{route}/{qid}"})
    assert len(calls) == 108
    write("calls/index.json", {"calls": calls, "generated_answers": 108, "pre_generation_failed_model_attempts": 1,
          "technical_retries": 1, "answer_based_retries": 0})
    ledger = read(source / f"{run}/ledger.json")
    for attempt in ledger["attempts"]:
        attempt.pop("pid", None)
        attempt.pop("out", None)
    retry = read(source / f"{run}/smolvlm/retry-ledger.json")
    retry.pop("pid", None)
    retry["repair_receipt"] = "receipts/smol-technical-repair.json"
    write("receipts/execution.json", {"main": ledger, "retry": retry,
          "first_smol_attempt": {"status": "pre_generation_failure", "answers_generated": 0,
             "reason": "Missing num2words; checkpoint-specific SmolVLM model class corrected before one technical retry.",
             "full_stderr_published": False, "source_summary_sha256": sha(source / f"{run}/smolvlm/attempt-1/summary.json")}},
          [("new_experiment/" + rel, source / rel) for rel in (f"{run}/ledger.json", f"{run}/smolvlm/retry-ledger.json")],
          "Removed process IDs/output locators and rebased repair receipt; all timestamps, budgets, outcomes, timing and planned denominator retained. Raw logs omitted.")

    reviews = read(source / "review-notes.json")
    for route in reviews["routes"].values():
        route["independent_reviewer"] = "independent_ai_reviewer"
    write("review-notes.json", reviews, [("new_experiment/review-notes.json", source / "review-notes.json")],
          "Generalized reviewer identity only; all labels, correct-question lists, notes and existing replacement characters unchanged; no new judging.")
    adjudication = read(source / "adjudication.ai.json")
    adjudication["reference"] = "data/reference.ai.json"
    adjudication["source_review_notes_sha256"] = adjudication["review_notes_sha256"]
    adjudication["review_notes_sha256"] = sha(HERE / "review-notes.json")
    for row in adjudication["cases"]:
        row["independent_reviewer"] = "independent_ai_reviewer"
        row["raw"] = f"calls/{row['route']}/{row['question_id']}/raw.txt"
        # result/raw files are byte-exact copies: their original hash bindings remain valid.
        assert row["result_sha256"] == sha(HERE / f"calls/{row['route']}/{row['question_id']}/result.json")
        assert row["raw_sha256"] == sha(HERE / row["raw"])
    write("adjudication.ai.json", adjudication, [("new_experiment/adjudication.ai.json", source / "adjudication.ai.json")],
          "Generalized reviewer IDs and rebased raw/reference links; rebound public review_notes_sha256, retaining source_review_notes_sha256. Every existing judgment/reason/schema/raw/result hash unchanged.")
    results = read(source / "results.json")
    results["source_adjudication_sha256"] = results["adjudication_sha256"]
    results["adjudication_sha256"] = sha(HERE / "adjudication.ai.json")
    results["source_model_assets_receipt_sha256"] = results["model_assets_receipt_sha256"]
    results["model_assets_receipt_sha256"] = sha(HERE / "config/model-assets.json")
    results["verification_scope"] = "verification is a historical source receipt; run verify.py for current portable checks."
    write("results.json", results, [("new_experiment/results.json", source / "results.json")],
          "Preserved scores/timings/historical verification; rebound adjudication and model-assets hashes to public derivatives, preserving original hashes under source_ keys. No new accuracy judgment.")
    new_copy("figures/gemma-grounding.png", "assets/figures/gemma-grounding.png")
    write("assets/figures/provenance.json", {"figure": "assets/figures/gemma-grounding.png",
          "source_plot_script_sha256": sha(source / "plot_grounding.py"), "reference_sha256": sha(HERE / "data/reference.ai.json"),
          "panels": [{"image": f"assets/prepared/{image}.png", "question_id": qid,
                      "result": f"calls/gemma/{qid}/result.json", "result_sha256": sha(HERE / f"calls/gemma/{qid}/result.json")}
                     for image, qid in (("colour", "C-Q1"), ("fruits", "F-Q4"), ("english", "E-Q1"))],
          "generated_by_archive_build": False, "model_boxes_or_images_changed": False})

    report = (source / "RESULTS.md").read_text(encoding="utf-8")
    for call in calls:
        old = f"{run}/{call['route']}/attempt-{call['attempt']}/{call['question_id']}/raw.txt"
        report = report.replace(old, call["directory"] + "/raw.txt")
    report = report.replace("figures/gemma-grounding.png", "assets/figures/gemma-grounding.png")
    report = report.replace("[EXECUTION.md](EXECUTION.md)", "[執行收據](receipts/execution.json)")
    report = report.replace("[model-assets.json](model-assets.json)", "[模型資產收據](config/model-assets.json)")
    report = report.replace("- `analyze.py` 通過", "- 原實驗的 `analyze.py` 歷史驗證通過")
    report = report.replace("- **本輪新成果只保存在本機，未提交／合併／推送。** tracked 檔案未改，HEAD 仍為 `6848723ac9751b06720567f01e82270cd40d2b12`。先前 Qwen 成果已在 main 保留。模型程序全部結束；未停止其他使用者服務。",
                            "- 上述驗證與 Git 狀態是 2026-10-30 的實驗收據；公開封存於 2026-11-02 另行整理，提交／合併／推送狀態由本次交付另報，不能沿用舊收據判定。")
    report += "\n本公開包是具來源 SHA 與轉換說明的可攜封存；執行 `python -I -S -B verify.py` 可離線重播 parser 與既有 AI 判定加總。36 個舊 CPU chat 相等及舊私有 tree 只保留歷史收據，本入口不再存取私有舊樹。原 review 理由已有 U+FFFD 編碼損失，本次原樣保留，沒有補寫或重新判題。辨識研究於本次封存後暫停。\n"
    write("RESULTS.md", report, [("new_experiment/RESULTS.md", source / "RESULTS.md")],
          "Rebased published links and historical-status wording; tables, scores, raw labels and experiment limitations preserved. Added portable verification, existing encoding-loss and pause boundaries.")
    method = (source / "METHOD.md").read_text(encoding="utf-8")
    start = method.index("在 repo 根目錄以現有環境執行：")
    end = method.index("發布機構是備案篩選線索")
    method = method[:start] + """在本公開包目錄使用 Python 3.12+ 標準函式庫：

```powershell
python -I -S -B verify.py
```

此入口不推論、不下載、不連線、不載入套件／GPU／快取、不讀私有 experiments 樹，也不 import 任一 inference runner。只載入本包 contracts.py 的純 parser／prompt 函式，核對封存會員清單、hash、108 個答案／prompt／圖片／設定／parser 與既有 AI 判定加總。可把整個資料夾單獨複製到其他目錄後驗證。

原始 raw、prompt、rendered-chat、result 與 route summary 逐 byte 保留。公開 review／adjudication／results／model-assets 等 JSON 因去識別或路徑轉換而改變 bytes：manifest 逐檔記錄來源 SHA 與轉換；下游公開 hash 重新綁定，原 hash 另標 source_，不得宣稱這些衍生 JSON 是原件。parser 函式原文抽取並保留，prompt 函式只將檔案讀取改成顯式 q/o 參數；contracts.json 分別記錄函式與歷史來源 SHA。未 import 原 runner，也未驗證此目錄可重新推論。

36 個舊 Qwen CPU chat 相等、舊私有 tree hash／395 檔／3,041,240 bytes 與模型資產 hash 驗證，只保留原實驗歷史收據，不在公開 verifier 重新存取未發布原件或權重。既有 AI 分數不重新看圖判斷；中文 review 理由原本含 U+FFFD 編碼損失，本次保留且不補寫。獨立 AI 複核不是人工 GT 或驗收。

可重建封存的 build_packet.py 僅供持有指定來源者使用，會讀取來源並輸出本目錄；一般讀者只執行 verify.py。完整 stderr/stdout、程序 ID、私有位置、快取、權重與原 inference runner 不發布。本次封存沒有重新推論、訓練、下載、安裝套件、硬體或服務操作；辨識研究於封存後暫停，下一階段須另行授權。

""" + method[end:]
    method = method.replace("[既有研究紀錄](../../docs/model-alternatives-2026-10-30.md)", "[推論前研究紀錄（固定版本）](https://github.com/momonong/thor-vla-erasebot/blob/6848723ac9751b06720567f01e82270cd40d2b12/docs/model-alternatives-2026-10-30.md)")
    write("METHOD.md", method, [("new_experiment/METHOD.md", source / "METHOD.md")],
          "Preserved original method and resource boundaries; replaced private-dependent rerun instructions with portable verification and explicit source/derivative, historical receipt and pause limits.")
    write("README.md", """# 六路白板辨識比較：可攜證據封存

2026-10-30 實測、2026-11-02 封存。六路 × 18 題，共 **108 個原始回答**；Gemma 4 E2B 內容／粗定位 8/18、格式 18/18，Qwen3-VL GPU 對照 10/18、格式 17/18。不是人工接受的 GT、泛化 benchmark 或可直接擦除的 mask。

| 路線 | 內容／粗定位 | 格式 |
| --- | ---: | ---: |
| Qwen3-VL-2B | 10/18 | 17/18 |
| Gemma 4 E2B | 8/18 | 18/18 |
| RapidOCR＋Qwen2.5-1.5B | 4/18 | 0/18 |
| Phi-4-multimodal | 1/18 | 0/18 |
| SmolVLM2-2.2B | 0/18 | 1/18 |
| docTR＋SmolLM2-1.7B | 0/18 | 0/18 |

[逐題結果與限制](RESULTS.md)、[方法／驗證邊界](METHOD.md)、[AI 判定](adjudication.ai.json)、[既有 AI 複核](review-notes.json)、[機器可讀加總](results.json)、[素材授權](ATTRIBUTION.md)。[calls/index.json](calls/index.json) 可查全部原始 raw／prompt／result／rendered-chat；[模型 revisions 與資產收據](config/model-assets.json)、[原 Qwen／RapidOCR 資產收據](config/baseline-models.json)、[各路實際 runtime](config/routes/qwen_vlm.json) 亦在包內。

在此目錄執行 `python -I -S -B verify.py`，只需 Python 3.12+ 標準函式庫。整包可獨立搬移：不需要 repo、網路、GPU、權重、快取或私有 experiments。驗證會核對檔案清單／SHA、108 次 parser 與 prompt 契約，並加總已保存的 AI 判定，不會重新看圖評分或推論。

manifest.json 是本包會員與來源轉換表。raw／prompt／result／rendered-chat bytes 保留；去識別 JSON 的公開 hash 重新綁定且列原 source hash。36 次舊 CPU chat 對照與原私有 tree 完整性是[歷史收據](receipts/historical-verification.json)，公開 verifier 不重新驗證未發布原件。原 review 中文理由已有編碼損失，原樣保留，未重新判題。

SmolVLM 有一次產生答案前的技術失敗及一次修復重試；沒有按分數重跑。模型來源機構不等於全資料來源認證或競賽資格認證。原私有資料保留不動；本次只封存既有成果，辨識研究暫停，沒有啟動新推論、訓練或手臂操作。
""")
    write("ATTRIBUTION.md", """# 第三方照片與診斷圖來源

此文件僅說明個別照片及本次診斷圖的素材，不替整個 repo 或程式碼新增授權。

- 色字：nwales，[原始問題與圖片](https://stackoverflow.com/questions/28223727/how-to-achieve-adaptive-threshold-filter-with-color)，2015 年貢獻，依 [Stack Overflow 時間政策](https://stackoverflow.com/help/licensing) 適用 [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)。本包 prepared PNG 是先前等比 RGB 版本的 byte-exact 副本；新增診斷圖保留原實驗的框、標籤與排版，此色字改作部分依相同條款。
- 水果：Daniel Rosehill，[Whiteboards 資料集](https://huggingface.co/datasets/danielrosehill/Whiteboards)，revision `4b31e86e15743ffea20204a8f6992b0173ecbdf9`，sample06，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。沿用等比縮小 PNG，診斷圖另加實際模型／AI 參考框及文字；此素材及其改作依該條款。
- 英文：Thirdman，[Pexels 原照片](https://www.pexels.com/photo/text-written-on-whiteboard-6503132/)，適用 [Pexels License](https://www.pexels.com/license/)，不是公有領域。本包沿用研究縮圖，診斷圖包含此照片及模型／參考框，並非未修改原素材的 stock／wallpaper 再散布，也不表示作者背書。

本包[診斷合成 PNG](assets/figures/gemma-grounding.png) 原樣複製本次實驗，三張照片各自仍依以上條款；沒有重畫、修補或美化模型預測。來源詳見 [sources.json](sources.json)，尺寸及 prepared hash 見 [data/images.json](data/images.json)，診斷圖的結果及參考綁定見 [provenance](assets/figures/provenance.json)。
""")
    write(".gitattributes", "# Preserve frozen answer/prompt/result bytes on every checkout.\n* -text\n")

    assert inventory(source) == before, "Source changed during export."
    assert inventory(base) == base_before, "Published baseline changed during export."
    own = {"build_packet.py", "verify.py"}
    for rel in own:
        assert (HERE / rel).is_file()
        ORIGINS[rel] = {"disposition": "generated", "conversion": "Archive packaging/verification code; no inference entrypoint."}
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts} - {"manifest.json"}
    assert actual == set(ORIGINS), (actual - set(ORIGINS), set(ORIGINS) - actual)
    manifest = {"schema_version": 1, "archive_kind": "portable_frozen_evidence_no_inference", "packaged_date": "2026-11-02",
                "manifest_self_hash": "Not self-hashed; integrity anchor is the version-controlled manifest.",
                "private_source_preserved_during_export": True,
                "source_snapshot": {"files": len(before), "bytes": sum(x[1] for x in before),
                                    "tree_sha256": hashlib.sha256(json.dumps(before, separators=(",", ":")).encode()).hexdigest()},
                "files": [{"path": rel, "bytes": (HERE / rel).stat().st_size, "sha256": sha(HERE / rel), **ORIGINS[rel]}
                          for rel in sorted(ORIGINS)]}
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"files": len(actual) + 1, "bytes": sum(p.stat().st_size for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts),
                      "answers": len(calls), "source_files_unchanged": len(before), "baseline_files_unchanged": len(base_before)}, indent=2))


if __name__ == "__main__":
    main()
