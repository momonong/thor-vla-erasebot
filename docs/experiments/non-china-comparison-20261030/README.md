# 六路白板辨識比較：可攜證據封存

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
