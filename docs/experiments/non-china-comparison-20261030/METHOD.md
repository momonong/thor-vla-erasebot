# 本輪比較口徑

本輪是已授權的零樣本診斷實驗，使用既有三張公開白板照片與 18 個繁中單題 context。不是新的 held-out benchmark，也沒有模型訓練、硬體連線、機器人座標或外部推論 API。先前 Qwen 結果保留於 `docs/experiments/photo-comparison-20261030/`，本輪另存，不覆寫舊結果。

## 固定與變動

- 固定 prepared image bytes、問題、任務約定、greedy、seed 0、max_new_tokens 3072、max_time 840 秒、repetition_penalty 1、use_cache=True；每題新 messages，不沿用其他題的 KV。VLM 與 Qwen 文字路線重用原 prompt bytes。原 Windows prompt 檔的 CRLF 在模型輸入正規化為 LF，和舊 runner 的實際 Python 字串一致。
- 本輪為 RTX 5090 Laptop GPU、BF16、不量化；模型載入一次後逐題執行。舊 Qwen 單題是 CPU float32、每題獨立程序，且 Transformers 版本不同；不能把差值只歸因於裝置或精度。
- 新 GPU Qwen 兩路作控制；這兩路的 36 個 rendered chat 與舊 CPU 對照逐題核對。不同品牌使用各自必要的 native processor/template，不宣稱視覺 tokens、架構、參數量相等。
- modern：Torch 2.9.1+cu128、Transformers 5.5.0；docTR＋SmolLM：Torch 同版、Transformers 4.57.3、python-doctr 1.1.0；Phi：Torch 同版、Transformers 4.48.2、PEFT 0.13.2。所有模型實際 device/dtype、input tensor shape 與版本在 route summary/result。
- Gemma 4 原生類別、`enable_thinking=False`；Phi 固定 revision 的官方 remote code 經閱讀，使用 eager attention、完整 VISION input_mode、原雙 EOS，未把其他模型的 EOS 套入；其餘 SDPA。Phi 的 Torch 版本偏離官方舊範例，這是本次 Windows 執行結果，不是所有官方 runtime 的效能結論。
- docTR 使用 db_resnet50＋crnn_vgg16_bn，CPU float32，word geometry 與原 HSV 顏色量測。偵測／辨識權重 hash、設定與原始 OCR 輸出均保存。此路同時更換 OCR 與 LLM，不能將差異全歸因於其中一個元件。

## 判定

沿用推論前凍結的 AI 近似參考與舊 rubric：每題應選的 occurrence 集合、status，以及文字與粗位置的對應。多選應保留詞、漏掉重複 occurrence、框到其他詞都失敗。沒有事後新增 IoU／完整筆畫覆蓋門檻；框裁切另列限制，粗定位通過也不是擦除 mask 通過。

主責逐題讀 raw，另由 AI 協作者獨立核對，並把判定與 raw/result SHA 綁定。不是人工接受的 ground truth。原 parser 保留原行為（允許移除整段 enclosing code fence），不修補括號、題號、尾引號或座標；內容診斷與格式契約分開，也列同時通過數。`analyze.py` 只重播 parser、核對完整性與加總既有人工式 AI 判定，不會自動重新看圖評分。

## 技術嘗試與資源

最多六路各 18 答案，共 108 答案。SmolVLM 第一次在產生答案前因缺 `num2words` 載入失敗；根因核對時也修正程式使用的模型類別，使其符合 checkpoint 的 SmolVLM 架構。初版 source、錯誤 stderr、processor smoke、修正後依賴均保留；只做一次技術重試，沒有依答案好壞重跑。

模型串行，每次載入要求至少 14 GiB 可用 VRAM；沒有停止其他使用者程序。HF 與 Torch 快取使用本專案新目錄，舊 CPU 環境與 checkpoint 唯讀。新增四組 HF 模型資產 33,868,916,490 bytes，另有 docTR 165,325,056 bytes，低於 45 GB 模型資產上限；模型資產逐檔 SHA/LFS hash 核對。

全程 90 分鐘模型執行上限，單題內部 840 秒、外層 960 秒無進展上限；連續兩次 runtime／時間門檻失敗則停止 route。token cap 是獨立記錄的生成停止原因。raw 僅在 generate 返回後保存：若外層強制中止，不保證留存生成中的 partial tokens，不能把未存內容當成已觀察答案。重試監看器等待主 run 完成才啟動，並沿用原 90 分鐘絕對期限。

## 可重播部分

在本公開包目錄使用 Python 3.12+ 標準函式庫：

```powershell
python -I -S -B verify.py
```

此入口不推論、不下載、不連線、不載入套件／GPU／快取、不讀私有 experiments 樹，也不 import 任一 inference runner。只載入本包 contracts.py 的純 parser／prompt 函式，核對封存會員清單、hash、108 個答案／prompt／圖片／設定／parser 與既有 AI 判定加總。可把整個資料夾單獨複製到其他目錄後驗證。

原始 raw、prompt、rendered-chat、result 與 route summary 逐 byte 保留。公開 review／adjudication／results／model-assets 等 JSON 因去識別或路徑轉換而改變 bytes：manifest 逐檔記錄來源 SHA 與轉換；下游公開 hash 重新綁定，原 hash 另標 source_，不得宣稱這些衍生 JSON 是原件。parser 函式原文抽取並保留，prompt 函式只將檔案讀取改成顯式 q/o 參數；contracts.json 分別記錄函式與歷史來源 SHA。未 import 原 runner，也未驗證此目錄可重新推論。

36 個舊 Qwen CPU chat 相等、舊私有 tree hash／395 檔／3,041,240 bytes 與模型資產 hash 驗證，只保留原實驗歷史收據，不在公開 verifier 重新存取未發布原件或權重。既有 AI 分數不重新看圖判斷；中文 review 理由原本含 U+FFFD 編碼損失，本次保留且不補寫。獨立 AI 複核不是人工 GT 或驗收。

可重建封存的 build_packet.py 僅供持有指定來源者使用，會讀取來源並輸出本目錄；一般讀者只執行 verify.py。完整 stderr/stdout、程序 ID、私有位置、快取、權重與原 inference runner 不發布。本次封存沒有重新推論、訓練、下載、安裝套件、硬體或服務操作；辨識研究於封存後暫停，下一階段須另行授權。

發布機構是備案篩選線索，不是完整來源鏈或競賽資格認證。候選官方資料與尚無明確禁令的背景保留於 [推論前研究紀錄（固定版本）](https://github.com/momonong/thor-vla-erasebot/blob/6848723ac9751b06720567f01e82270cd40d2b12/docs/model-alternatives-2026-10-30.md)。SmolVLM2 公開訓練表含 Qwen 合成資料；目前沒有宣稱任何候選「完全無中國來源」。
