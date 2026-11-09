# Thor 離線批次證據報告

本工具彙整明確指定的本機 JSON，沿用 `liner_evaluation.evaluate` 的 protocol 0.1 判定。**未實機驗證／不是實機成果**；既有六筆 fixtures 都是手寫合成案例，時間、循環與摺角紀錄是假設值，不是量測成果。原本 48 案／144 列真實試驗規劃不受本工具影響。

## 使用方式

從專案根目錄執行，使用既有 Python 3.12 環境及標準函式庫，不新增依賴。本版批次檔案讀取要求 POSIX fd／O_NOFOLLOW；原生 Windows 會拒絕，Linux 已驗證，WSL 仍待環境驗收：

```bash
python -B -m tools.liner_batch --manifest /path/to/cases/batch.json
python -B -m tools.liner_batch --manifest /path/to/cases/batch.json --format json
python -B -m tools.liner_batch --manifest /path/to/cases/batch.json --format markdown
python -B -m tools.liner_batch --help
```

工具只讀檔並向 stdout 輸出，不建立報告檔。JSON 為單行；Markdown 包含所有分組、案例狀態、來源路徑、原始檔案 SHA256 與證據限制。不開啟來源標籤或網址，不連網、不呼叫 subprocess、不使用 GPU、硬體或服務。

公開 API：`evaluate_batch(manifest_path)` 回傳 dict；`render_markdown(report)` 接受該 dict 並回傳字串；`main(argv=None)` 回傳退出碼。Markdown 中未知值顯示 `unknown`；成功率用分數及小數呈現，避免四捨五入百分比掩蓋結果。自訂文字的換行、管線符號及 Markdown／HTML 特殊字元會轉義，不插入 HTML 或遠端圖片。

## Manifest 輸入契約

例如將以下 `batch.json` 與指定的 `target.json`、`clear.json`、`not-run.json` 放在同一個資料夾：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "case_id": "clear",
      "material": "A",
      "method": "fixed_script",
      "target": "target.json",
      "observation": "clear.json"
    },
    {
      "case_id": "not-run",
      "material": "A",
      "method": "fixed_script",
      "target": "target.json",
      "observation": "not-run.json"
    }
  ]
}
```

- 頂層恰有 `schema_version` 與 `entries`。版本必須是整數 `1`，拒絕 `true` 和 `1.0`；entries 必須為 1–2000 筆的陣列。
- 每筆恰有上述五欄，拒絕未知或缺少欄位。`case_id` 為非空白字串，保留原值精確比對。`material` 只接受 `A`、`B`；`method` 只接受 `fixed_script`、`visual_feedback`、`learned_policy`。
- `(material, method, case_id)` 不可重複；不同材料或方法可使用相同 case_id。每個可解析觀測中已有的 case_id 必須與 entry 一致，否則拒絕整批，即使該案例的 target 另有讀取錯誤。觀測缺少 case_id 屬單筆 schema 錯誤。
- target／observation 為相對 **manifest 所在資料夾** 的非空白路徑，可使用子目錄；不是相對執行命令的工作目錄。拒絕 NUL、絕對路徑、Windows drive/root 形式及 `..` 路徑片段。來源 reference 標籤不作為待讀路徑。
- 每個檔案（包含 manifest）最多 2 MiB，即 2,097,152 bytes，且須為一般 UTF-8 JSON 檔。拒絕 symlink、目錄、FIFO；拒絕重複 JSON key、NaN、Infinity、-Infinity 及溢位成無限大的數字（如 `1e999`）。
- 讀取使用 POSIX descriptor-relative `O_NOFOLLOW`／`O_DIRECTORY` 逐層限制，不跟隨目錄或檔案 symlink；非阻塞開啟後再次確認實際描述符為一般檔案，並限制實際讀入長度。manifest 的祖先目錄也不得包含 symlink，manifest 路徑不得含 `..`。平台缺少這些安全能力時明確回報 InputError，不降級為不安全讀取。Windows 尚未支援此讀取方式。

target 與 observation 的其他欄位、目標 canonical SHA256 綁定、格網、not_run 一致性與門檻皆由既有評估器驗證。批次 material／method 是輸入標籤，不證明來源的材料或執行方法屬實，也不額外改寫 target_id。

## 報告、分母與成功率

頂層包含 `schema_version=1`、`mode="offline"`、`robot_validated=false`、`source_references_verified=false`、`cases`、`groups`、`limitations`。不加入執行時間戳；相同輸入產生穩定順序與內容。

`cases` 依 manifest 原順序完整保留，每筆包含 case_id、material、method、evidence_kind、status、sources、result；無效案例另含 diagnostics。`sources.target` 與 `sources.observation` 各有 `path`（manifest 原始相對路徑）及 `sha256`（實際讀入的原始 bytes 指紋）。無法安全讀取的檔案 hash 為 null；安全讀到但 JSON 或欄位無效時仍可保留該 bytes 指紋。這與評估器的 canonical target SHA256 不同：排版會改變檔案指紋，不會改變 canonical target 指紋。

有效案例的 `result` 完整保留既有 evaluate 回傳，包含 metrics、checks、failed_checks、missing_evidence、recorded 與證據旗標；無效案例為 null。若可從成功解析的觀測取得允許的 evidence_kind，無效案例仍保留該分類；無法取得或值不合法時為 null，不猜測來源。

groups 依 `(material, method, evidence_kind)` 分組排序；未知 evidence_kind 在同材料／方法內排最前。A/B、三種方法、synthetic_fixture／offline_annotation 與未知來源分開，不混池，也不產生跨組成功率。每組的 counts 完整列出五種狀態，即使數量為零：

| 狀態 | 意義 | 計入 attempted |
| --- | --- | --- |
| criteria_met | 紀錄符合離線門檻 | 是 |
| criteria_not_met | 至少一項已知不符，含失敗或中止 | 是 |
| insufficient_evidence | 尚無已知不符，但必要證據缺失 | 是 |
| invalid_input | 讀檔、JSON 或評估器輸入錯誤 | 否，但阻止該組回報成功率 |
| not_run | 明確未執行，量測未知 | 否，不當成功或失敗 |

`total` 是五種 counts 總和。`attempted = criteria_met + criteria_not_met + insufficient_evidence`。

只有該組 `insufficient_evidence == 0`、`invalid_input == 0` 且 `attempted > 0`，才提供 `success_rate = criteria_met / attempted`；否則為 null，Markdown 顯示 unknown／未知。不得刪掉 invalid_input 再宣稱較高成功率。未知來源的無效案例仍有獨立組與 total；其他組的成功率只適用於各自組別，不能推廣至整批。

一成功一失敗為 attempted=2、success_rate=0.5；純 not_run 為 attempted=0、success_rate=null；一成功加 not_run 為 attempted=1、success_rate=1，並保留 total=2 與未執行計數。加入 insufficient_evidence 或同組 invalid_input 後成功率為 null。六筆既有合成案例應保留 1 criteria_met、2 criteria_not_met、1 insufficient_evidence、1 invalid_input、1 not_run，total=6、attempted=4、success_rate=null。

## 失敗處理與退出碼

manifest 讀取／JSON／結構錯誤、非法路徑文字、重複 tuple、觀測身份不符，公開 API 拋出既有 `erasebot.selection.InputError`，不回傳部分批次。單筆來源讀檔錯誤（含 symlink、非一般檔案、超大檔案）、JSON 錯誤及 evaluate 的 InputError 則保留該筆 `invalid_input`，附 `diagnostics.stage` 和 errors 的 path／message；不計算該筆分數。目標與觀測分別嘗試安全讀取，避免目標錯誤遮蔽可辨識的觀測身份不符。

| CLI 退出碼 | 意義 |
| --- | --- |
| 0 | 有效批次且全部案例 criteria_met；仍僅是離線判定 |
| 1 | 有效批次中任何案例為其他狀態，包含 not_run、insufficient_evidence、invalid_input |
| 3 | 參數錯誤或整批 InputError；stdout 單行 JSON invalid_input 診斷，無 traceback，即使指定 Markdown 亦同 |

`--help` 沿用 argparse 正常說明與退出行為。批次退出碼不同於單筆評估器的狀態退出碼，不以退出碼 1 判斷工具故障。

## 證據與驗證界線

coverage ≥0.95、IoU ≥0.90、摺角 clear、≤90 秒、≤6 循環、零人工介入及 completed 的門檻完全沿用既有評估器；未知不補零，已知失敗仍優先於缺證據。這是已確認的離線驗收契約，不是主辦規則或實測成效。

來源未驗真：SHA256 只能核對讀到的內容，不能證明來源真實、目標預先固定、標註正確或校正有效。多檔讀取不是整個資料夾的原子快照，使用者應在輸入穩定後執行。`offline_annotation` 亦不代表相機、手臂或學習策略已驗證；`real_robot` 仍由單筆評估器拒絕。本工具不比較模型優劣，不填寫真實試驗成果。

本次提供 `tests/test_liner_batch.py`，涵蓋六筆合成案例、統計分母、獨立分組、整批拒絕與單筆保留、來源 hash、JSON／路徑／大小／symlink／FIFO 邊界，以及 CLI 和 Markdown。依當次授權，模型未執行測試；驗證由主機執行 `checks/test_batch_acceptance.py`、`checks/test_original_evaluator.py` 與 `checks/test_worker_tests.py`（載入新測試）。原隔離任務的主機驗收已通過 42 項（16 項原評分器、8 項 worker 測試、18 項獨立驗收）；不與歷史 55 項相加。此次整合的實際結果見 [版本驗證](../validation-0.3.0.md)，人工與實機接受仍待完成。
