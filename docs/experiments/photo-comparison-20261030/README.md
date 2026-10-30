# 白板照片離線比較：2026-10-30

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
