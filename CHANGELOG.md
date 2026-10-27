# 版本紀錄

## 0.1.1 — 2026-10-27

- 更新專案與 lockfile metadata 至 0.1.1；應用選取行為、fixture 契約與依賴沿用 0.1.0。
- 納入[首輪照片採集包](docs/drafts/first-photo-kit-2026-10-27/README.md)：8 張拍攝卡、14 題指令與採集／評分空模板；實測欄位尚未填寫。
- 納入[逐鏡證據表](docs/drafts/first-photo-kit-2026-10-27/shot-evidence-map.md)與[90 秒紙上走查](docs/drafts/first-photo-kit-2026-10-27/paper-walkthrough-90s.md)，整理 7 鏡預算、案例覆蓋與缺素材相依；尚未錄製或計時，不構成擦拭效能證據。
- 保留既有研究稿、企劃 MD／HTML 與歷史驗證紀錄；未加入 OCR、實拍、模型或硬體操作。

## 2026-10-26 研究規劃更新（應用程式維持 0.1.0）

- 新增[參賽研究與準備稿](docs/submission-plan.md)，整合選擇性擦拭主軸、三項可驗證主張、候選架構、完整／備案展示、90 秒素材腳本、測試與四人候選分工。
- 更新官方資訊核對日期、投稿附件疑問與文件入口；推薦方案及日期均為規劃，尚未成為團隊承諾或排程。
- 保留 10/24 企劃原稿、HTML 與驗證紀錄不變；只更新文件，未啟動照片驗證、新實作、模型下載或硬體操作，未重跑 21 項既有測試。

## 0.1.0 — 2026-10-24

首個版本提供 fixture-only 離線目標選擇基礎，以及可供約四人討論的企劃草稿。

- 以人工準備的指令與場景 JSON 驗證輸入，按文字及顏色精確選取；輸出 `selected`、`no_match`、`ambiguous` 或 `invalid_input` 診斷。
- 使用 uv 與 Python 3.12 隔離環境，固定專案解析，零第三方依賴；影像座標為 `image`／`px`。
- 第一階段在既有與全新隔離環境各通過 21 項測試；[驗證紀錄](docs/verification.json)另列本輪離線檢查。
- 納入[企劃原稿](docs/proposal-discussion.md)及[可下載 HTML](docs/proposal-discussion.html)，包含 A～D 四人分工提案、8 張診斷起點及可選探索。分工、投入與探索方向仍待團隊定案。

本版未啟動照片驗證，沒有 OCR、座標校正或實機控制；Thor／ARM64／JetPack 相容性尚未驗證。fixture 選取與測試結果不代表照片辨識、擦拭能力或競賽實機驗收。
