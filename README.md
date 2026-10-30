# thor-vla-erasebot

目前提供**僅使用 fixture 的離線目標選擇 dry-run**：讀取人工準備的指令與場景 JSON，完整驗證後，以文字及顏色精確比對，輸出單一 JSON 診斷。範例會選出 `word-1`，沒有可執行動作或馬達指令。0.2.0 新增批次 fixture 重播，逐案比較固定預期與實際結果，原單例 CLI 保持相容。

競賽資訊與準備稿中的日期屬歷史查核／規劃紀錄，參賽前須重新向官方確認；本次未更新官方資訊。

研究推薦以「擦對指定字、保留其他字、留下前後證據」為主軸。2026-10-30 已完成三張公開白板照片、18 題的兩輪本機 CPU 離線比較，另存為研究證據包；產品 CLI 仍只有 fixture dry-run，照片研究尚未整合產品流程與手臂。資料設計、實機採集包及展示腳本仍屬準備文件。

## 0.2.0／文件入口

- [fixture 批次重播](#fixture-批次重播)：5 案固定預期、輸入 snapshot、完整逐案診斷與結果帳本；只屬人工 fixture 證據。
- [兩輪照片離線比較證據包（2026-10-30）](docs/experiments/photo-comparison-20261030/README.md)：同三圖／18 題的六題批次與單題比較，含原始回答、AI 參考與核對、圖片及離線查核；沒有訓練或手臂操作。
- [非中國模型備案研究（2026-10-30）](docs/model-alternatives-2026-10-30.md)：Gemma／SmolVLM2／Phi 等候選與 OCR 來源鏈及授權邊界；未下載、未實測，不代表競賽核准。
- [首輪照片採集包（2026-10-27）](docs/drafts/first-photo-kit-2026-10-27/README.md)：8 張拍攝卡、14 題指令及採集／評分空模板，供團隊後續採用。
- [逐鏡證據表](docs/drafts/first-photo-kit-2026-10-27/shot-evidence-map.md)與[90 秒紙上走查](docs/drafts/first-photo-kit-2026-10-27/paper-walkthrough-90s.md)：7 鏡預算、案例覆蓋、缺素材相依與預備問答，尚未錄製或計時。
- [研究與準備稿（2026-10-26）](docs/submission-plan.md)：以「擦對指定字、保留其他字、前後證據」為主軸，整合推薦架構、完整／備案展示、素材、測試與四人候選分工。
- [競賽資訊](docs/competition.md)：官方來源、日期與尚待確認的規則。
- [版本紀錄](CHANGELOG.md)：0.2.0 批次 CLI、一般檔案讀取修正與歷史版本能力範圍。
- [10/24 企劃討論原稿](docs/proposal-discussion.md)與 [HTML 歷史草稿](docs/proposal-discussion.html)：保留當時四人 A～D 的探索提案；HTML 並未更新成本輪研究稿。
- [2026-10-24 驗證紀錄](docs/verification.json)：第一階段及當日離線檢查的既有證據。

2026-10-27 版本 metadata 更新為 0.1.1，應用選取行為與 fixture 契約沿用 0.1.0。該日採集材料是準備稿：實拍、人工 reference、方法輸出與評分欄當時未填，也沒有影片；8 張是診斷起點，並非泛化證據。7 鏡／90 秒只屬分鏡預算，其中 23 秒不是擦拭效能承諾；既有紅／綠 fixture 也不是 P04 紅／藍照片實測。上述採集包的歷史狀態與 2026-10-30 使用三張公開參考照片完成的離線研究分開閱讀；實機採集、推薦分工及工時仍待團隊採用。

## 環境與執行

請在本 repo 根目錄執行以下指令。須先有 `uv` 與 Python 3.12；本專案不安裝或修改系統工具。已驗證 Ubuntu 24.04.5 x86_64、Python 3.12.3、uv 0.9.5。選用 Python 是為了以標準函式庫快速驗證資料介面；限制 `>=3.12,<3.13`，縮小本階段環境差異，未驗證其他 Python 版本。

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_DOWNLOADS=never
uv sync --locked --offline
uv run --locked --offline python -m erasebot --command fixtures/command.json --scene fixtures/scene.json
uv run --locked --offline python -m erasebot --help
```

`uv sync` 在 repo 建立隔離的 `.venv`；零第三方依賴，使用 `uv.lock` 固定專案解析。`[tool.uv] package = false` 表示不安裝專案套件，故須從 repo 根目錄執行；輸入相對路徑也以目前目錄為基準。有本機 Python 3.12 與 uv 即可完全離線重建，`UV_PYTHON_DOWNLOADS=never` 禁止下載 Python。若缺工具，先另外安排安裝；不要移除 `--offline` 期待自動下載或變更全域環境。

```bash
uv lock --check --offline
uv run --locked --offline python -m unittest discover -s tests -v
```

不需啟用虛擬環境或執行 `pip install`。若要核對全新環境，可保留原 `.venv`，改用一個尚不存在的暫存位置：

```bash
UV_PROJECT_ENVIRONMENT="$(mktemp -d /tmp/erasebot-rebuild.XXXXXX)/.venv" uv sync --locked --offline
```

## 輸入契約（schema_version 1）

[`fixtures/command.json`](fixtures/command.json) 必須有 `schema_version: 1`、`fixture: true`、`action: "erase"`、非空白字串 `text`、`color`。

[`fixtures/scene.json`](fixtures/scene.json) 必須有 `schema_version: 1`、`fixture: true`、`coordinate_frame: "image"`、`unit: "px"`、`image_size` 與 `targets`：

- `image_size` 僅有正整數 `width`、`height`，不能是 bool。
- `targets` 是陣列，可為空；每筆僅有 `id`、`text`、`color`、`bbox`。三個文字欄位都須是非空白字串，`id` 不可重複。
- `bbox` 是 `[x_min, y_min, x_max, y_max]`，影像左上為原點，x 向右、y 向下，單位為像素。四值須為有限 int/float，不能是 bool、NaN、Infinity。
- 邊界須符合 `0 <= x_min < x_max <= width`、`0 <= y_min < y_max <= height`；允許恰好落在影像邊緣與有限小數，不接受負值、退化、反轉或越界框。

所有物件都拒絕未知欄位、缺少欄位、錯誤型別及重複 JSON key；版本與 fixture 標記須具備正確型別與值。先驗證整份資料，一筆無效也會拒絕整份輸入，不能選出其他看似正常的目標。

`text`、`color` 採大小寫敏感的原字串精確比對，不修剪空白、不轉大小寫、不做翻譯或同義詞推斷。例如 `Apple`、`apple ` 都不符合 `apple`。空白字串本身無效。

## 輸出與退出碼

正常執行與輸入錯誤時，stdout 都只有一行 JSON；`--help` 則提供一般人類說明。錯誤會回報診斷，不吐未處理的 traceback。

| status | 退出碼 | 意義 |
| --- | ---: | --- |
| `selected` | 0 | 唯一符合，`selected_target` 是該筆目標 |
| `no_match` | 1 | 零筆符合 |
| `ambiguous` | 2 | 多筆符合，不自行挑選 |
| `invalid_input` | 3 | 參數、讀檔、JSON、schema 或座標錯誤 |

所有結果含 `schema_version: 1`、`fixture: true`、`dry_run: true`、`status`、`selected_target`、`candidate_ids`、`coordinates` 與 `diagnostics`。非唯一成功的 `selected_target` 一律為 `null`；候選 ID 沿用輸入順序。`coordinates` 包含 `coordinate_frame`、`unit`、`image_size`。

`diagnostics` 包含 `stage`（`arguments`／`read`／`json`／`validation`／`selection`）、`target_count`、`candidate_count`、`errors`；錯誤項目有 `path` 與 `message`。例如 `scene.targets[2].bbox` 指出第三筆目標的框有誤。無效輸入不進行比對，候選為空、`coordinates` 與 `target_count` 為 `null`。重複 key／解析錯誤以 `command` 或 `scene` 標示文件，訊息補充原因。

單例輸入、replay suite 與案例輸入皆只接受一般 UTF-8 檔案，可使用指向一般檔案的 symlink；目錄、FIFO 與其他非一般檔案回報 `read` 診斷。已在 POSIX 驗證 FIFO 不等待 writer，也檢查實際開啟的 fd；未驗證其他平台，不保證一般檔案所在的任意檔案系統皆不會延遲或阻塞。

## fixture 批次重播

沿用上方離線環境設定，在 repo 根目錄執行：

```bash
uv run --locked --offline python -m erasebot.replay --suite fixtures/replay/suite.json
uv run --locked --offline python -m erasebot.replay --help
```

[`fixtures/replay/suite.json`](fixtures/replay/suite.json) 包含五個手寫人工案例：唯一紅色 apple、原場景中不存在的藍色 apple、兩個紅色 apple 的歧義、有效匹配旁有另一筆越界框，以及空白指令文字。預期值固定寫入 suite，沒有從 selector 輸出產生，也沒有匯入照片 Pxx 計畫或 reference。

suite 僅接受 `schema_version: 1`、`fixture: true`、非空白 `suite_id` 與非空 `cases`；每案僅有唯一非空白 `id`、非空白相對路徑 `command`／`scene` 與 `expected`。案例路徑以 **suite 所在目錄**為基準，允許 `../command.json` 重用原始 fixture，拒絕絕對路徑及 NUL。所有欄位必填，不接受未知欄位、重複 JSON key 或非標準數字常數；整份 suite 驗證通過才開始執行。

`expected` 僅有下列五欄，逐欄精確比較；陣列順序也要相同，錯誤只比路徑，不比依作業系統變化的訊息文字：

| 欄位 | 契約 |
| --- | --- |
| `status` | `selected`／`no_match`／`ambiguous`／`invalid_input` |
| `selected_target_id` | `selected` 時為唯一候選 ID，其他狀態為 `null` |
| `candidate_ids` | 不重複的非空白 ID；`selected` 一筆、`ambiguous` 至少兩筆、其餘空陣列 |
| `diagnostic_stage` | `selection`／`read`／`json`／`validation` |
| `error_paths` | 非空白路徑字串陣列；`invalid_input` 必須非空且階段不能是 `selection`，其餘必須為空且階段為 `selection` |

stdout 是一行 JSON，含 `schema_version: 1`、`fixture: true`、`dry_run: true`、`evidence_kind: "fixture_replay"`、`suite_id`、整體 `status`、逐案 `cases` 與 `summary`。每案保留原相對路徑、已載入的 `inputs` snapshot、固定 `expected`、含座標與診斷的完整 `actual`、`passed` 及結構化 `mismatches`（`field`／`expected`／`actual`）。讀檔或 JSON 失敗的未載入 snapshot 為 `null`；若數值溢位使已載入 snapshot 無法以標準 JSON 表示，或 snapshot 容器深度超過 64 層，該 snapshot 為 `null` 並在 `snapshot_diagnostics` 明列 `nonfinite_number` 或 `excessive_nesting`。原輸入仍由 selector 完整驗證，實際診斷與後續案例帳本均保留。

`summary` 列出全部有效 suite 宣告案例的 `total`／`passed`／`failed`，以及實際選取狀態的 `by_selector_status`；預期不符、檔案遺失或輸入無效都不會中止後續案例或移出分母。輸出沒有時間戳、耗時或隨機 ID，相同輸入會得到相同 JSON；需要保存時可由呼叫端將 stdout 導向新檔案。

| 整體 status | 退出碼 | 意義 |
| --- | ---: | --- |
| `passed` | 0 | 全部案例符合預期契約 |
| `failed` | 1 | 至少一案有欄位不符，完整帳本仍輸出 |
| `invalid_suite` | 2 | 參數、suite 讀檔／JSON／結構錯誤；`diagnostics` 說明原因，未執行案例 |

範例應為 5 案契約通過，實際狀態分別為 1 `selected`、1 `no_match`、1 `ambiguous`、2 `invalid_input`。預期的歧義或無效輸入符合契約也算通過，**不表示選到了物件或擦拭成功**。這只是人工 fixture 重播證據，不是照片／OCR 成績、泛化能力、實機擦拭成效或競賽分數。

## 能力邊界與下一步

產品 CLI 尚未整合 OCR、NLP、語音辨識、相機接入、座標校正、物理模擬、路徑規劃或實機控制；獨立照片研究見上方證據包。Thor／ARM64／JetPack 尚未驗證。fixture 與研究框座標只代表影像位置，不可直接當成機械手臂座標。

競賽當次來源核對、待確認問題與下一階段條件見 [`docs/competition.md`](docs/competition.md)。先確認規則、團隊投入及可用實機條件，再決定感知、校正與控制方案。
