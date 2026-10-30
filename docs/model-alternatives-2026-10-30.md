# 非中國發布機構模型備案：2026-10-30 研究紀錄

建議保留現有 Qwen 結果作基準，主要備案先研究 **Gemma 4 E2B／E4B**，以 **SmolVLM2** 作低成本對照、**Phi-4-multimodal** 作較重候選；OCR 優先查核 **docTR**，並保留 **Tesseract＋顏色量測＋有限規則**的低成本底線。這些候選本次**未下載、未推論、未訓練，也未驗證本機／Thor 效能**；以下是研究選擇，不是新一輪實驗結果。

使用者當次表示尚無明確競賽限制，目前只預先準備備案，不能宣稱主辦允許或禁止特定模型。現有兩個指定 checkpoint 官方模型卡都標示 Apache 2.0：[Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)、[Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)。開源授權不等於競賽核准。[competition.md](competition.md) 保留原 2026-10-26 歷史核對，沒有冒稱今日已向主辦確認。

## 先定義要排除哪一層

「非中國品牌」不代表整條來源鏈都沒有中國來源。後續篩選應分開記錄：開發／發布機構、實際權重與底模、教師／合成資料，以及 runtime／轉換／量化供應者。沒有揭露的部分標為未知，不能以改名或換包裝推定通過限制。

例如 RapidOCR 官方明載其 OCR 模型由 PaddleOCR 轉換，上游權重權利人包括 Baidu／PaddleOCR；只把推論換成 ONNX Runtime，沒有更換權重來源。[RapidOCR 模型來源與授權](https://github.com/RapidAI/RapidOCR#models)

## VLM 與文字選取器候選

| 優先角色 | 官方已知資訊 | 對本專案的實際限制 |
| --- | --- | --- |
| Google Gemma 4 E2B／E4B：主要備案 | Google DeepMind 發布，文字／圖像輸入、文字輸出，Apache 2.0。E2B 為 **2.3B effective、含 embeddings 5.1B**；E4B 為 **4.5B effective、含 embeddings 8B**，不能簡稱總量純 2B／4B。[官方模型卡](https://ai.google.dev/gemma/docs/core/model_card_4) | 官方 Core Capabilities 列開箱支援 **35+ 語言**、預訓練資料涵蓋 **140+ 語言**，不代表能正確處理本組繁中指令＋白板英文。視覺框選、重複出現及保留／擦除條件均未實測。 |
| Hugging Face SmolVLM2 500M／2.2B：低成本對照；256M 為成本下限 | 官方標示 Apache 2.0、英語，文字底模 SmolLM2，視覺底模為 Google SigLIP 系列。[2.2B 模型卡](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)、[500M 模型卡](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct) | 小模型不等於繁中指令或可靠 grounding。500M 卡的訓練表含 `magpie_pro_qwen2_72b_tt`；若規範追溯教師／合成資料，還需審查，不能稱完全無 Qwen 來源。[官方訓練表](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct#training-data) |
| Microsoft Phi-4-multimodal-instruct：較重備案 | MIT，總量約 **5.6B**，由 Phi-4 Mini 與 SigLIP 400M 等多模態元件構成；不是 2B 同級。官方文字語言包含中文，但 vision 語言欄為 English。[官方模型卡](https://huggingface.co/microsoft/Phi-4-multimodal-instruct) | CPU、Windows 與 Thor 在本專案都未驗證。官方 ONNX 頁面的 DirectML 路徑屬 GPU backend，不能當成 CPU 推論證據。[官方 ONNX 說明](https://huggingface.co/microsoft/Phi-4-multimodal-instruct-onnx) |

Gemma 4 的 [Google LiteRT-LM Windows CPU 文件](https://developers.google.com/edge/litert-lm/models/gemma-4) 與 [NVIDIA Thor VLM benchmark](https://nvidia.github.io/TensorRT-Edge-LLM/user_guide/performance/performance-benchmarks.html) 支持「有官方部署路徑可研究」。頁面的裝置、量化、輸入、runtime 與本機不同，不能把其速度抄成本專案實測。

OCR 後的文字選取器可另列 **SmolLM2-1.7B** 或 **SmolLM3-3B**。文字模型本身不讀圖、不產生可靠影像框；必須沿用 OCR 的 ID／座標資料介面，繁中語意條件也尚未測。SmolLM2 可由上述 SmolVLM2 的官方底模鏈追查；SmolLM3 官方文章明列 Qwen3／R1 相關生成資料，因此同樣不能用發布品牌代替完整來源審查。[SmolLM3 官方文章](https://huggingface.co/blog/smollm3)

## OCR 替代要先保留字框能力

**docTR** 原創於 Mindee，現由 t2k GmbH 持續維護，Apache 2.0；官方提供文字偵測＋辨識的兩階段流程及 word 層級資料。它適合列為候選，但具體 detection／recognition checkpoint 的底模、訓練資料、來源與 hash 仍要逐項記錄，不能把套件品牌視為全部權重來源保證；本白板手寫尚未測。[docTR 官方 repo](https://github.com/mindee/doctr)

**Tesseract** 官方歷史為 HP 英國／美國實驗室起源、後由 Google 開發，Apache 2.0；[官方歷史](https://github.com/tesseract-ocr/tesseract#brief-history) 可支持其工程來源線索。它可輸出 TSV 的位置、信心與文字欄位，但官方也明言主要針對印刷文字，手寫效果有限，因此只當低成本底線，不預設可取代白板手寫辨識。[TSV 框格式](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html#tsv-output)、[手寫限制](https://tesseract-ocr.github.io/tessdoc/FAQ#can-i-use-tesseract-for-handwriting-recognition)

後續可按以下對照拆開問題，而非同時替換所有元件：

1. **Tesseract＋HSV＋固定規則**：建立低成本底線。規則只能宣稱預先定義的文字／顏色／空間／有限語意範圍，不能把這 18 題的答案寫死。
2. **docTR＋相同固定規則**：固定 selector，比較 OCR 候選與字框缺口。
3. **docTR＋非中國發布機構小型文字 LLM**：固定 OCR，觀察語意條件與格式變化。

這只是未來對照設計，本次沒有新增這些規則、安裝套件或執行候選。

## 條件候選與授權差異

**TrOCR** 雖由 Microsoft 發布，但原論文作者單位包含 Beihang University，不能列為「完全非中國研發」。其 handwritten checkpoint 主要處理單行 crop→text，不自帶整頁 detector 或 word bbox；若要用於本流程，另需候選偵測與座標來源。[原論文作者單位](https://arxiv.org/html/2109.10282)、[官方 handwritten 模型卡](https://huggingface.co/microsoft/trocr-base-handwritten)

**Gemma 3** 的 1B 純文字／4B 視覺模型可作成熟對照，但需依其自訂 [Gemma Terms](https://ai.google.dev/gemma/terms) 另行查核；不可把 Gemma 4 的 Apache 2.0 套到 Gemma 3。這也不構成競賽核准。

## 若之後獲授權比較

先做零樣本候選診斷，無需預先訓練。沿用[同三張 prepared 圖、18 題及 AI 參考](experiments/photo-comparison-20261030/README.md)，單題 context；但這 18 題已看過並分析過，只能視為**診斷回歸集**，不是 held-out 泛化證據。真正泛化需要另外取得尚未看過的資料與人工接受標註。

保留原繁中題不改；若做英文譯題，另列語言消融，不能混入同一分數。每個候選記錄 model version／revision／hash、權重與教師來源、量化、processor、視覺 tokens、總／有效參數口徑、EOS／上限、呼叫次數及時間。失敗留在分母，內容、schema、粗定位、模型耗時與含 OCR 的端到端耗時分開報告；可重新加總已存結果，不假稱已在新機器重跑。

本文件只整理官方資料與待測方案。沒有下載新權重、推論新模型、訓練、硬體接入或修改原競賽歷史查核。repo 未新增整體 LICENSE；各模型及照片應分別遵守自己的條款。
