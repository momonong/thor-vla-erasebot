# 固定方法、資料與時間口徑

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
