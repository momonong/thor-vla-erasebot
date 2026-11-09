# 襯片離線評估工具（protocol 0.1）

本工具已實作「固定目標遮罩 → 觀測遮罩與紀錄 → 指標與判定」流程。它讓後續照片標註與實驗使用同一套可檢查的算式；目前範例完全是人工合成，沒有襯片實拍、學習策略或實機成果。

程式為根目錄的 `liner_evaluation.py`。沿用 Python 3.12、uv 與既有標準函式庫環境，無新增套件。必須從 repo 根目錄執行；相對輸入路徑也以該目錄為準。

## 立即執行

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_DOWNLOADS=never
uv run --locked --offline python -B -m liner_evaluation --target fixtures/liner-evaluation/target.json
uv run --locked --offline python -B -m liner_evaluation --target fixtures/liner-evaluation/target.json --observation fixtures/liner-evaluation/partial.json
```

第一個命令回報目標資訊與內容指紋；第二個案例的 coverage 為 `0.75`、IoU 為 `0.6`、status 為 `criteria_not_met`，退出碼 `1` 是預期結果。它不是命令執行故障。

替換觀測檔名即可執行其餘 [六個範例](../fixtures/liner-evaluation/README.md)。Linux 完整整合測試（包含 POSIX-only 批次工具）：

```bash
uv run --locked --offline python -B -m unittest discover -s tests -v
```

Windows 原生先用 `py -3.12 -B -m unittest discover -s tests -p test_liner_evaluation.py -v` 驗收本單筆工具；不以此宣稱批次／完整環境可用。

這是標準函式庫 CLI；不需要開服務、網路、GPU 或手臂。只讀使用者指定的兩個本機 JSON，stdout 輸出單行 JSON；`--help` 例外，提供人類可讀說明。輸入須為一般 UTF-8 檔案；拒絕目錄、FIFO、重複 JSON key、非有限數字與未知欄位。不建立輸出檔；如需保存結果，請導向新的檔名，避免覆蓋舊證據。

## 目標與座標

目標 schema 恰有四欄：

```json
{
  "schema_version": 1,
  "target_id": "A",
  "frame_id": "table-1",
  "mask_rows": ["1100", "1100"]
}
```

- `target_id`、`frame_id` 是非空白識別字串，採原值精確比較。A／B 應使用不同目標檔與 ID。
- `mask_rows` 是同寬的 ASCII 0／1 字串列；`1` 是區域內，`0` 是區域外。左上為格網原點，列向下、字元向右。長寬不可為零，總像素至多 4,000,000；目標至少一格為 1。
- 數值單位只有像素，不含厘米、手臂座標、內外參或校正能力。目標與觀測必須由同一個已固定的格網產生；工具只能檢查識別字與尺寸，不能發現「名稱相同但實際相機已移動」。
- `schema_version` 必須是整數 `1`，不能是 `true` 或 `1.0`。

目標指紋是經驗證目標物件的 canonical JSON SHA256：Python `json.dumps(target, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)` 的 UTF-8 bytes。空白排版與 key 順序不影響指紋；遮罩、ID 或 frame 改變會影響它。範例指紋為 `d6f22c9fde222f70129b4316cf1b7aa140f02445cb85a137bdc63cb9f508e31c`。

指紋用來核對內容一致，不能證明目標是何時固定、沒有被人同時替換，或校正正確。正式試驗仍須在觀測前封存目標、原圖、校正／裁切／縮放設定與來源紀錄；不能看完結果再重建較容易通過的目標。

## 觀測與證據欄位

以下欄位全部必填，不接受額外欄位：

| 欄位 | 型別／允許值 | 用途 |
| --- | --- | --- |
| schema_version | 整數 1 | 輸入格式版本 |
| case_id | 非空白字串 | 單筆紀錄識別；本工具不管理跨檔案唯一性 |
| evidence_kind | synthetic_fixture 或 offline_annotation | 合成案例，或離線人工標註 |
| source_ref | 非空白字串 | 原始來源標籤；不會開啟檔案或 URL |
| target_id／frame_id | 非空白字串 | 必須與目標一致 |
| target_sha256 | 非空白字串 | 必須與目標 canonical SHA256 完全一致 |
| mask_rows | 遮罩或 null | 遮罩尺寸須相同；全零合法且表示零覆蓋，null 表示未知 |
| fold_check | 恰有 status／reference 的物件 | 狀態 clear／folded／unknown |
| duration_s | 非負有限 int／float 或 null | 從開始觀察到最終判定的完整秒數，包含等待 |
| cycles | 非負整數或 null | 宏觀整理嘗試數，不是模型推論或 action step 數 |
| human_interventions | 非負整數或 null | 試驗中人工介入次數 |
| execution_status | completed／failed／aborted／not_run | 紀錄所描述的執行狀態，不是由工具確認的事實 |

所有數值都不接受 bool。未知量測保留 `null`，不要填 `0`。`fold_check.status` 為 clear／folded 時，`reference` 必須是非空白字串；unknown 可使用 null 或有內容的說明標籤。單張俯視遮罩無法證明無摺角：真實資料須用獨立檢查角度或人工檢查紀錄，再填入適當 reference。

`not_run` 必須將 mask_rows、duration_s、cycles、human_interventions 全填 null，摺角設為 `{"status":"unknown","reference":null}`。與未執行矛盾的觀測欄位會被拒絕。對於初始已合格且沒有操作的案例，可以是 completed、cycles 為 0，但仍須實際量測時間與檢查結果，後續統計要獨立呈現。

`real_robot` 在此版會被拒絕。使用真實照片的人工標註時填 `offline_annotation`，仍不表示工具驗證過相機、手臂、標註正確性或檔案真實性。所有輸出都含 `mode: offline`、`robot_validated: false`、`source_references_verified: false`。

## 算式與判定

令 T 為固定目標、M 為觀測遮罩：

- `coverage = |M ∩ T| / |T|`。
- `IoU = |M ∩ T| / |M ∪ T|`；移出目標的多餘區域會降低 IoU。
- 回報 target_area_px、observed_area_px、intersection_px、union_px，方便人工手算核對。

protocol 0.1 的通過條件沿用既有提案：coverage ≥0.95、IoU ≥0.90、摺角 clear、≤90 秒、≤6 個宏觀循環、零人工介入、execution_status 為 completed。**這是我們的擬定驗收門檻，不是主辦規則或實測成效。** 比例判斷使用整數交叉相乘，包含恰好達標的邊界。

| status | 退出碼 | 意義 |
| --- | ---: | --- |
| target_info | 0 | 僅驗證目標並產生指紋，沒有評估觀測 |
| criteria_met | 0 | 輸入紀錄符合全部門檻；只屬離線判定 |
| criteria_not_met | 1 | 至少一個已知條件不符；即使其他證據缺失仍回報失敗 |
| insufficient_evidence | 2 | 尚無已知失敗，但必要證據不足 |
| invalid_input | 3 | 參數、讀檔、JSON、結構、尺寸或目標指紋錯誤 |
| not_run | 4 | 明確標記未執行，無觀測指標 |

`checks` 中 true／false／null 分別代表符合、不符合、未知；`failed_checks` 與 `missing_evidence` 分開保留。錯誤回報 `diagnostics.stage` 與 `errors` 的 path／message。對 invalid_input 不產生分數，不能略過它再計算較高成功率。

## 後續如何接真實資料

第一個可接續的開發項目是**離線照片人工標註與遮罩匯出入口**：載入固定視角照片、分開標記目標與觀測、輸出此契約，保存原圖與處理設定。它不需要手臂；目前尚未實作，也尚無本題照片可驗證。

在來源與格網固定之後，再以獨立人工手算或第二位標註者核對少量案例。人工將襯片整理前後拍照只能證明評估流程可用，不是機器人成功。自動分割、摺角辨識、ACT、物理模擬、SO-101 控制及 Thor 延遲測試各是後續不同工作，不由本工具結果推定完成。

本工具只評估一筆紀錄；[批次工具](development/batch-report.md) 已補上去重與保留未知值的條件統計。兩者都不執行試驗重設或時間量測，也沒有真實方法比較成果。原本 48 案規劃與 144 列結果空表保持不變，未填入這些合成案例。

本次整合驗證見 [0.3.0 驗證摘要](validation-0.3.0.md)。
