# thor-vla-erasebot

目前提供**僅使用 fixture 的離線目標選擇 dry-run**：讀取人工準備的指令與場景 JSON，完整驗證後，以文字及顏色精確比對，輸出單一 JSON 診斷。範例會選出 `word-1`，沒有可執行動作或馬達指令。

## 0.1.0／文件入口

- [版本紀錄](CHANGELOG.md)：首個 0.1.0 版的內容與能力範圍。
- [企劃討論原稿](docs/proposal-discussion.md)：四人 A～D 的目標、分工與探索提案。
- [可下載的企劃 HTML](docs/proposal-discussion.html)：下載後可直接用本機瀏覽器開啟，不需要新增服務。
- [驗證紀錄](docs/verification.json)：第一階段既有證據與本輪離線檢查結果。

8 張照片是第一輪診斷起點，並非探索上限。草稿中的可選探索與四人分工仍待團隊定案，尚未啟動照片驗證。

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

## 能力邊界與下一步

此階段沒有 OCR、NLP、語音辨識、相機接入、座標校正、物理模擬、路徑規劃或實機控制，也未驗證 Thor／ARM64／JetPack。fixture 座標只代表影像像素，不可直接當成機械手臂座標。

競賽當次來源核對、待確認問題與下一階段條件見 [`docs/competition.md`](docs/competition.md)。先確認規則、團隊投入及可用實機條件，再決定感知、校正與控制方案。
