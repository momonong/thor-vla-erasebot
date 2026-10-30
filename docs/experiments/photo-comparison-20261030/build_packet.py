"""Allowlisted export of frozen local evidence; does not run models or modify sources."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ORIGINS = {}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inventory(source):
    return [{"path": p.relative_to(source).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
            for p in sorted(source.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE.parents[2] / "experiments/photo-comparison-20261030")
    args = parser.parse_args()
    source = args.source.resolve()
    before = inventory(source)
    assert len(before) == 395 and sum(x["bytes"] for x in before) == 3041240, "Unexpected private source snapshot; review before exporting."

    def put(path, data, origins=(), note="Portable derivative; original bytes retained locally."):
        dest = HERE / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n" if not isinstance(data, str) else data, encoding="utf-8", newline="\n")
        ORIGINS[path] = {"disposition": "transformed" if origins else "generated", "conversion": note,
                         "private_sources": [{"path": str(p), "sha256": sha(source / p)} for p in origins]}

    def cp(origin, dest):
        target = HERE / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / origin, target)
        ORIGINS[dest] = {"disposition": "byte_exact_copy", "private_source_path": origin,
                         "private_source_sha256": sha(source / origin), "conversion": "None; exact source bytes, including CRLF."}

    questions = read(source / "questions.json")
    qids = {i["id"]: [q["id"] for q in i["questions"]] for i in questions["images"]}
    qpublic = copy.deepcopy(questions)
    for image in qpublic["images"]:
        image["path"] = f"assets/prepared/{image['id']}.png"
    put("data/questions.json", qpublic, ["questions.json"], "Rebased image paths to the actual prepared inputs; question objects and wording unchanged.")
    cp("reference.json", "data/reference.ai.json")
    cp("sources.json", "sources.json")
    cp("requirements-frozen.txt", "config/requirements-frozen.txt")
    image_records = read(source / "prepared/manifest.json")["images"]
    for record in image_records:
        name = record["id"]
        cp(f"prepared/{name}.png", f"assets/prepared/{name}.png")
        ocr = read(source / f"ocr/{name}.json")
        ocr["image_path"] = f"assets/prepared/{name}.png"
        put(f"data/ocr/{name}.json", ocr, [f"ocr/{name}.json"], "Rebased image_path only; raw line/CTC boxes, candidates and colour measurements unchanged.")
    put("data/images.json", [{k: r[k] for k in ("id", "source_sha256", "original_size", "exif_transposed_size", "prepared_sha256", "prepared_size", "resize")} |
        {"prepared": f"assets/prepared/{r['id']}.png", "source_file": Path(r["source"]).name} for r in image_records], ["prepared/manifest.json"], "Replaced absolute source/prepared locators with public input paths and original source filenames.")
    models = {"llm": read(source / "llm-model-assets.json"), "vlm": read(source / "vlm-model-assets.json"),
              "ocr_config": read(source / "ocr/config.json"), "ocr_assets": []}
    for m in read(source / "ocr/model-assets.json"):
        models["ocr_assets"].append({"file": Path(m["path"]).name, "bytes": m["bytes"], "sha256": m["sha256"]})
    put("config/models.json", models, ["llm-model-assets.json", "vlm-model-assets.json", "ocr/config.json", "ocr/model-assets.json"], "Retained model IDs/revisions/filenames/hashes and OCR settings; removed absolute asset paths.")

    # All 45 attempts remain; only 42 generated an answer. Failed VLM prompts are exact duplicates.
    attempts, result_to_call = [], {}
    first = read(source / "runs/20261030T024109Z/ledger.json")["jobs"]
    repaired = read(source / "runs/20261030T024513Z/ledger.json")["jobs"]
    plans = []
    for item in first + repaired:
        route, image = item["route"], item["image"]
        batch = "20261030T024513Z" if item in repaired else "20261030T024109Z"
        relative = f"runs/{batch}/{route}-{image}"
        plans.append(("batch", route, image, qids[image], relative, item["elapsed_s"], 2 if item in repaired else 1))
    single_ledger = read(source / "single-question/runs/20261030T060241Z/ledger.json")
    for job in single_ledger["jobs"]:
        for attempt in job["attempts"]:
            relative = f"single-question/runs/20261030T060241Z/{job['route']}-{job['image_id']}/{job['question_id']}/attempt-{attempt['attempt']}"
            plans.append(("single", job["route"], job["image_id"], [job["question_id"]], relative, attempt["process_wall_s"], attempt["attempt"]))
    for phase, route, image, ids, relative, wall, attempt_no in plans:
        local = source / relative
        r = read(local / "result.json")
        base = f"calls/batch/{route}-{image}" if phase == "batch" else f"calls/single/{route}/{ids[0]}"
        call_id = base.removeprefix("calls/") + f"/attempt-{attempt_no}"
        result_to_call[str((local / "result.json").resolve())] = call_id
        if r["status"] == "completed":
            cp(f"{relative}/raw.txt", f"{base}/raw.txt")
            cp(f"{relative}/prompt.txt", f"{base}/prompt.txt")
        record = {"id": call_id, "phase": phase, "route": route, "image_id": image, "question_ids": ids,
                  "attempt": attempt_no, "status": r["status"], "private_source_result_sha256": sha(local / "result.json"),
                  "prompt_file": f"{base}/prompt.txt", "prompt_sha256": sha(local / "prompt.txt"),
                  "model": r["model"], "model_revision": r["model_revision"], "dtype": r["dtype"], "generation": r["generation"],
                  "seed": 0, "torch_threads": 4, "torch_interop_threads": 1, "attention_implementation": "sdpa",
                  "prepared_file": f"assets/prepared/{image}.png", "prepared_sha256": r["image_sha256"],
                  "process_wall_s": wall, "model_total_s_excludes_import": r.get("total_s"),
                  "recorded_parser_result": r.get("parsed"), "raw_file": None,
                  "source_runner_sha256": r["runner_sha256"]}
        for key in ("generation_s", "generated_tokens", "input_tokens", "last_token_eos", "model_load_and_preprocess_s", "actual_model_device", "vision_tensors"):
            if key in r:
                record[key] = r[key]
        if r["status"] == "completed":
            record.update(raw_file=f"{base}/raw.txt", raw_sha256=sha(local / "raw.txt"), private_source_rendered_chat_sha256=sha(local / "rendered-chat.txt"))
        else:
            record["technical_error"] = {"type": r["error"]["type"], "stage": "processor_initialization_before_generation", "reason": "AutoVideoProcessor required missing torchvision; no answer generated.", "raw_traceback_published": False}
        if phase == "single":
            control = read(local / "control.json")
            record["single_question_control"] = {k: control[k] for k in ("question_id", "question_count", "baseline_prompt_prefix_sha256", "baseline_questions_file_sha256", "prepared_sha256", "ocr_sha256", "post_infer_control_checks", "all_control_checks_pass")}
        attempts.append(record)
    assert len(attempts) == 45
    for record in attempts:
        assert sha(HERE / record["prompt_file"]) == record["prompt_sha256"]
    put("calls/index.json", {"kind": "derived_portable_attempt_summaries_not_original_result_json", "attempts": attempts,
        "notes": ["All three pre-generation failures remain; their prompt files are shared only after byte-identity checks.", "Raw answers/prompt files are exact copies; metadata is a separately hashed derivative. Full local tracebacks/stdout/stderr are not published.", "Rendered chats are retained locally; their original hashes are recorded, without claiming the omitted bytes are in this packet."]},
        [f"{p[4]}/result.json" for p in plans], "Allowlisted inference/settings/timing/parser fields; paths rebased, executable locations and raw tracebacks omitted. Raw responses are separate byte-exact files.")

    for phase, rel in (("batch", "adjudication.json"), ("single", "single-question/adjudication.json")):
        a = read(source / rel)
        a["evaluator"] = "AI visual adjudication with independent AI review; not human-accepted ground truth."
        a["reference"] = "data/reference.ai.json"
        a["reference_review"] = "annotations/reviews.json"
        a.pop("valid_model_run_paths", None)
        for key in ("questions_sha256", "baseline_adjudication_sha256"):
            if key in a:
                a["private_source_" + key] = a.pop(key)
        if "questions" in a:
            a["questions"] = "data/questions.json"
            a["questions_sha256"] = sha(HERE / "data/questions.json")
        if "baseline_adjudication" in a:
            a["baseline_adjudication"] = "annotations/batch-adjudication.ai.json"
        a.pop("batch", None)
        for case in a["cases"]:
            for route in ("ocr_llm", "vlm"):
                value = case[route]
                if "run_dir" in value:
                    value["call_id"] = result_to_call[str((Path(value.pop("run_dir")) / "result.json").resolve())]
                if "result_sha256" in value:
                    value["private_source_result_sha256"] = value.pop("result_sha256")
        put(f"annotations/{phase}-adjudication.ai.json", a, [rel], "Scores/notes/labels unchanged; file links rebased, reviewer alias generalized; original-result hashes explicitly labelled private-source hashes.")
    comparison = read(source / "single-question/comparison.json")
    comparison.update(baseline="annotations/batch-adjudication.ai.json", single="annotations/single-adjudication.ai.json")
    put("annotations/comparison.json", comparison, ["single-question/comparison.json"], "Only reference file links rebased; scores, transitions and limitations unchanged.")
    reviews = {}
    for key, rel in (("reference", "reference-review.json"), ("batch", "final-review.json"), ("single", "single-question/final-review.json")):
        value = read(source / rel)
        value["reviewer"] = "independent_ai_reviewer"
        if "questions_sha256" in value:
            value["private_source_questions_sha256"] = value.pop("questions_sha256")
        if "reviewed_artifacts" in value:
            value["private_source_reviewed_artifacts"] = value.pop("reviewed_artifacts")
        reviews[key] = value
    reviews["test_receipts"] = [{"scope": "baseline runner contracts", "passed": 6, "private_source_receipt_sha256": sha(source / "runner-tests.txt")},
                                {"scope": "single-question adapter controls", "passed": 4, "private_source_receipt_sha256": sha(source / "single-question/adapter-tests.txt")}]
    reviews["existing_fixture_suite"] = {"tests": 39, "failures": 2, "errors": 0, "posix_skips": 6, "rerun_for_release": False,
        "failed_tests": ["test_deep_snapshot_cannot_drop_validation_diagnostics_or_later_cases", "test_structurally_invalid_suites_execute_no_cases"],
        "private_source_receipt_sha256": sha(source / "fixture-tests-local-tmp-utf8.txt")}
    put("annotations/reviews.json", reviews, ["reference-review.json", "final-review.json", "single-question/final-review.json"], "Generalized agent identity and explicitly marked hashes of omitted private-source review documents; preserved all verdicts and scoring boundaries.")
    env = read(source / "environment.json")
    single_execution = read(source / "single-question/execution-summary.json")
    put("config/runtime.json", {"python": env["python"], "platform": env["platform"], "packages": env["packages"] | {"torchvision": env["technical_repair"]["torchvision"]},
        "device": "cpu", "torch_threads": 4, "torch_interop_threads": 1, "technical_repair": env["technical_repair"],
        "single_routes": single_execution["routes"], "single_batch_wall_s": single_execution["batch_total_wall_s"],
        "postflight_checks": {k: v for k, v in single_execution["postflight"].items() if isinstance(v, bool)},
        "timing_definition": env["timing_definition"]}, ["environment.json", "single-question/execution-summary.json"], "Retained non-secret platform/packages/settings/timings/check results; removed executable, local environment/cache and model asset locators.")

    cp("figures/diagnostic-comparison.png", "assets/figures/diagnostic-comparison.png")
    cp("single-question/figures/vlm-batch-vs-single.png", "assets/figures/vlm-batch-vs-single.png")
    provenance = {}
    for key, rel in (("initial", "figures/diagnostic-comparison.json"), ("paired", "single-question/figures/vlm-batch-vs-single.json")):
        v = read(source / rel)
        v.pop("prepared_input", None)
        for panel in v.get("evidence", v.get("panels", [])):
            if "result" in panel:
                panel["call_id"] = result_to_call[str(Path(panel.pop("result")).resolve())]
            if "result_sha256" in panel:
                panel["private_source_result_sha256"] = panel.pop("result_sha256")
            panel.pop("raw", None)
        provenance[key] = v
    put("assets/figures/provenance.json", provenance, ["figures/diagnostic-comparison.json", "single-question/figures/vlm-batch-vs-single.json"], "Only locators rebased to call IDs; actual drawn target objects and raw/image hashes retained. Public PNGs are byte-exact copies.")
    for rel in ("runner.py", "batch.py", "test_runner.py", "single-question/adapter.py", "single-question/launch.py", "single-question/test_adapter.py"):
        cp(rel, "source/" + rel)

    text = (source / "single-question/RESULTS.md").read_text(encoding="utf-8")
    image = (source / "single-question/figures/vlm-batch-vs-single.png").resolve().as_posix()
    text = text.replace(image, "assets/figures/vlm-batch-vs-single.png")
    replacements = {"adjudication.json": "annotations/single-adjudication.ai.json", "comparison.json": "annotations/comparison.json",
        "figures/vlm-batch-vs-single.json": "assets/figures/provenance.json", "figures/README.md": "ATTRIBUTION.md", "../sources.json": "sources.json",
        "../RESULTS.md": "README.md", "../adjudication.json": "annotations/batch-adjudication.ai.json",
        "baseline-manifest.json": "manifest.json", "postflight-verification.json": "manifest.json", "execution-summary.json": "config/runtime.json",
        "EXECUTION.md": "METHOD.md", "final-review.json": "annotations/reviews.json", "adapter-tests.txt": "annotations/reviews.json",
        "../fixture-tests-local-tmp-utf8.txt": "annotations/reviews.json"}
    for old, new in replacements.items():
        text = text.replace(f"]({old})", f"]({new})")
    text = text.replace("root", "主責 AI")
    text = text.replace("- [baseline manifest](manifest.json) 與 [完成後驗證](manifest.json)：66 個原始檔、17 個模型資產及安裝版本未變，所有 control／prefix／VLM vision tensor 對照一致。",
        "- [原 baseline／postflight 檔案 hash](manifest.json) 與[原實驗驗證摘要](config/runtime.json)：原實驗完成時核對了 66 個檔案、17 個模型資產、版本與各 control。公開包只提供原紀錄 hash／非秘密摘要；全量紀錄與權重仍保留本機，portable 分析沒有重驗未公開的模型資產。")
    text = text.replace("- [執行摘要](config/runtime.json) 與 [精確重現入口／耗時定義](METHOD.md)：每題 EOS、token、時間、raw hash、設定及各 attempt 均可追查。",
        "- [公開執行摘要](config/runtime.json)、[45 次呼叫摘要](calls/index.json)及[耗時定義](METHOD.md)：每題 EOS、token、時間、raw hash 與設定均可追查。[推論重跑邊界](RERUN.md)另行標示；沒有在新公開目錄驗證模型重跑。")
    text = text.replace("[獨立複核紀錄](annotations/reviews.json)", "[獨立複核摘要](annotations/reviews.json)")
    text = text.replace("[四項 adapter 檢查](annotations/reviews.json)", "[四項 adapter 歷史收據摘要](annotations/reviews.json)")
    text = text.replace("見 [先前日誌](annotations/reviews.json)", "見[先前測試收據摘要](annotations/reviews.json)，完整日誌仍保留本機")
    text = text.replace("或 Git mutations。", "或 Git mutations（此限制僅指原實驗執行階段；本次封存另有文件及版本交付）。")
    for route in ("ocr_llm", "vlm"):
        for image_id, ids in qids.items():
            for qid in ids:
                text = text.replace(f"runs/20261030T060241Z/{route}-{image_id}/{qid}/attempt-1/raw.txt", f"calls/single/{route}/{qid}/raw.txt")
    text += "\n本公開報告是可攜衍生文件，來源與公開檔 hash 分別列在 manifest；不是私有原報告的 byte-exact 複本。\n"
    put("RESULTS.md", text, ["single-question/RESULTS.md"], "Public links/locators and reviewer wording rebased; labels distinguish private hashes, public summaries, historical receipts and unverified inference reruns. Tables, decisions and original-experiment caveats preserved; Git boundary scoped to experiment phase.")

    put("README.md", """# 白板照片離線比較：2026-10-30

這是產品 CLI 之外的研究證據包。產品仍只有 fixture dry-run；本包已完成三張公開照片、18 固定題的兩輪 CPU 實驗，沒有訓練或手臂操作。AI 近似參考與獨立 AI 複核尚非人工 GT／驗收。

| 原始回答內容的 AI 核對 | OCR＋Qwen2.5-1.5B | Qwen3-VL-2B |
| --- | ---: | ---: |
| 每圖六題一起問 | 4/18 | 10/18 |
| 每次一題 | 4/18 | 11/18 |

拆題改變回答，但改善有限，不能把錯誤全歸因於一起問。[完整結果與18題表](RESULTS.md)、[方法與成本](METHOD.md)、[來源與各別素材授權](ATTRIBUTION.md)、[未驗證推論重跑邊界](RERUN.md)。另見[非中國模型備案研究](../../model-alternatives-2026-10-30.md)，它尚未下載或實測。

`calls/index.json` 保留45次attempt，其中42次產生原文，3次在缺少torchvision時生成前失敗。42份raw與42份canonical prompt均逐byte複製；失敗的三份prompt和成功重跑完全相同，因此共享同hash的檔案。全部格式錯誤、漏答、技術失敗都保留，沒有修補raw。

離線查核不需模型或第三方套件，從本資料夾執行 `python -B analyze.py`；它驗證hash、JSON、連結、45次呼叫、42份原文的原解析結果，以及72個方法／題目判定的彙總／轉移。分數來自已存AI adjudication，不是腳本重新判讀圖片或答案。

manifest明確區分原私有檔hash和公開衍生檔hash；原完整395檔在本機保留，未將本機locator、完整traceback/stdout/stderr、模型權重、cache或硬體附件公開。封存檔及本資料夾限定的.gitattributes停用Git換行轉換，以保留CRLF bytes。詳見[manifest](manifest.json)。

sources.json是下載時的歷史快照，其中當時「未做OCR」狀態不代表本輪現況。模型、圖片與套件設定見config；原演算法source只作歷史封存，不能冒稱在本目錄可直接執行推論。
""")
    put("METHOD.md", """# 固定方法、資料與時間口徑

兩輪共用[data/questions.json](data/questions.json)的18個原指令與[AI近似參考](data/reference.ai.json)。參考在首輪推論前凍結，獨立AI複核；不能報精準IoU或擦拭保留率。三張prepared PNG皆為實際模型輸入的byte-exact複本，尺寸為596×447、1024×768、1024×683，等比、長邊<=1024且不放大。VLM patch grid及tensor shape逐呼叫保存。

A使用RapidOCR的PP-OCRv5 mobile偵測／辨識，分類stage實際載入ch_ppocr_mobile_v2.0_cls_infer.onnx；ONNX CPU與原生CTC單字框，再以固定HSV筆畫量測顏色。CTC框是估計框。Qwen2.5-1.5B-Instruct只收候選id/text/bbox/color；B為Qwen3-VL-2B-Instruct直接讀同圖與題目。版本、資產hash及設定見[models](config/models.json)、[runtime](config/runtime.json)和[套件快照](config/requirements-frozen.txt)。

兩輪均CPU float32、Torch4/interop1、seed0、greedy、SDPA、3072 max_new_tokens、840s max_time、use_cache=True、repetition_penalty=1。每圖／每題各有全新程序和對話。第二輪只把最後題目陣列6→1，前綴bytes一致；沒有改OCR/圖片/prompt措辭或調參。原解析器允許移除整段code fence，不去掉多餘尾引號或修補內容。

| 同樣18題的模型程序成本 | A首輪→單題 | B首輪→單題 |
| --- | ---: | ---: |
| 呼叫／重載次數 | 3→18 | 3→18 |
| 子程序牆鐘秒數 | 162.063→420.312 | 362.969→850.593 |
| 實際生成tokens | 744→621 | 1448→2011 |

第二輪總牆鐘1271.235秒，36/36完成、無補跑、全部EOS，單題最多461tokens，未達token/時間上限。首輪另保留3次生成前缺少torchvision失敗，補裝0.24.1+cpu後只作一次技術修復；沒有因低分或格式錯重跑。每call cap相同不等於總budget相同，單題的總允許token上限與模型載入數為六倍。

程序牆鐘包含匯入、hash檢查、模型載入、前處理、生成、保存；result總時不含Python模組匯入，generation_s包含prefill/vision forward和解碼。上述模型成本不含先行OCR、下載、環境建立、評分，也不是常駐模型/GPU/Thor/手臂延遲。原始OCR呼叫約9.0/0.4/0.4秒，首圖含字型準備，不能當純推論延遲。

發布只做資料查核和原解析器重播，沒有重新推論。既有6項runner＋4項adapter測試收據及兩輪獨立AI複核見[reviews](annotations/reviews.json)。既有fixture的39tests曾有2個Windows failures、6個POSIX skips；未為本次發布重跑或修正，產品碼和原測試未修改。

公開metadata是明示衍生資料，不是原result JSON；只保留非秘密模型設定、時間、parser結果、EOS、控制及source hash。移除實機路徑、可執行檔位置、cache locator、agent/thread身份和原traceback。完整原件仍在本機，manifest列其395檔hash與每項公開轉換。
""")
    put("ATTRIBUTION.md", """# 圖源、改動及個別素材授權

此文件只說明第三方圖片與其改作，不新增整個repo或原始碼的授權。repo原本沒有LICENSE；不得把照片的CC條款當成全部程式碼授權。

- 色字：nwales，[原始問題與圖片](https://stackoverflow.com/questions/28223727/how-to-achieve-adaptive-threshold-filter-with-color)，2015年貢獻，依[Stack Overflow時間政策](https://stackoverflow.com/help/licensing)適用[CC BY-SA3.0](https://creativecommons.org/licenses/by-sa/3.0/)。prepared/colour.png為等比RGB PNG；第一張診斷圖另加框、文字與排版，該含色字照片的合成PNG依CC BY-SA3.0提供。
- 水果：Daniel Rosehill，[Whiteboards資料集](https://huggingface.co/datasets/danielrosehill/Whiteboards)，revision 4b31e86e15743ffea20204a8f6992b0173ecbdf9、sample06，[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)。prepared/fruits.png等比縮小，兩張診斷圖增加實際模型框、標籤與排版。只含水果的同題比較PNG依CC BY4.0；混合色字的第一張合成圖依前述BY-SA3.0，水果原素材仍依BY4.0。
- 英文：Thirdman，[Pexels原照片](https://www.pexels.com/photo/text-written-on-whiteboard-6503132/)，適用[Pexels License](https://www.pexels.com/license/)，不是公有領域。本包將其縮小為prepared/english.png作研究例圖，不放入兩張診斷合成圖；不表示作者背書，也不作stock/wallpaper再散布或商標用途。

原始照片未修改；prepared只作已記錄前處理，診斷框完全來自實際輸出，不生成、修補、美化或人工修正模型選取。圖片／raw檔是原件byte-exact副本，公開provenance JSON才是路徑轉換後衍生物。作者、原檔名、來源URL與限制完整保留在[sources](sources.json)，尺寸與input hash見[images](data/images.json)，模型框與raw/source-result hash見[figure provenance](assets/figures/provenance.json)。
""")
    put("RERUN.md", """# 可攜分析與推論重跑是兩回事

已驗證的portable入口只有 `python -B analyze.py`：它不讀模型權重、不呼叫外部API、不訓練或接硬體，僅驗證已存檔案與原parser結果，重新加總AI adjudication。內容對錯仍是已有AI判定，沒有冒稱程式自動重評圖片。

source/保留六個歷史原檔的精確bytes：runner.py、batch.py、test_runner.py、single-question/adapter.py、launch.py、test_adapter.py。原runner中的通用model-cache/相對資料位置是當時程式的設定模板，不是這個公開包的可攜設定；metadata中的個人機器實際locator則沒有發佈。不要直接執行這些封存推論CLI並假定會成功。

本次沒有為新目錄移植推論、下載權重、安裝套件或重跑模型，因而沒有portable inference成功證據。未來若獲授權重跑，需另行配置固定revision的本機模型、適配資料路徑與相容runtime，保存新輸出並標示新環境／processor／量化與hash；不得覆寫本包raw，或把新結果冒稱當時的原始執行。

build_packet.py只從本機完整原實驗建立本包，使用明確allowlist和原件hash；預設輸入是repo中未追蹤的experiments/photo-comparison-20261030。原件未隨repo發布，外部讀者只需analyze.py，不需重建導出，也不能只靠SHA還原被省略的實機metadata。Git子目錄.gitattributes使用-text保留CRLF；重新格式化raw/prompt會改變實驗封存hash。
""")
    # Source files never change. This comparison includes every private text/image byte.
    assert inventory(source) == before, "Private source evidence changed during export."
    files = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or p.name == "manifest.json" or "__pycache__" in p.parts:
            continue
        relative = p.relative_to(HERE).as_posix()
        files.append({"path": relative, "bytes": p.stat().st_size, "sha256": sha(p),
                      **ORIGINS.get(relative, {"disposition": "generated", "conversion": "Release-only analysis/export code or subtree Git attributes; not an original experiment artifact."})})
    manifest = {"schema_version": 1, "kind": "portable_public_derivative_of_retained_private_evidence", "files": files,
        "private_source_records": before, "private_source_files": len(before), "private_source_bytes": sum(x["bytes"] for x in before),
        "private_originals_retained_unchanged": True, "private_source_root_published": False,
        "inference_rerun_for_release": False, "model_weights_or_cache_included": False,
        "notes": ["Source SHA256 values identify retained original bytes. A transformed public JSON/Markdown has its own different SHA256; it is not claimed to have the original hash.",
                  "42 raw and 42 canonical prompt files, five PNGs, AI reference, sources, requirements, and six algorithm/test source snapshots are byte-exact copies.",
                  "All local executable/cache/image locators and full machine tracebacks remain private. Source inventory paths are experiment-relative, never host-absolute.",
                  "The retained full source inventory excludes two non-evidence bytecode cache files."]}
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"packet_files": len(files) + 1, "packet_bytes": sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file()),
                      "private_files_preserved": len(before), "private_bytes_preserved": sum(x['bytes'] for x in before),
                      "attempts": len(attempts), "generated_raw": 42}, indent=2))


if __name__ == "__main__":
    main()
