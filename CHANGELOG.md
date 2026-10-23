# 版本紀錄

## 0.1.0 — 2026-10-24

首個版本提供 fixture-only 離線目標選擇基礎，以及可供約四人討論的企劃草稿。

- 以人工準備的指令與場景 JSON 驗證輸入，按文字及顏色精確選取；輸出 `selected`、`no_match`、`ambiguous` 或 `invalid_input` 診斷。
- 使用 uv 與 Python 3.12 隔離環境，固定專案解析，零第三方依賴；影像座標為 `image`／`px`。
- 第一階段在既有與全新隔離環境各通過 21 項測試；[驗證紀錄](docs/verification.json)另列本輪離線檢查。
- 納入[企劃原稿](docs/proposal-discussion.md)及[可下載 HTML](docs/proposal-discussion.html)，包含 A～D 四人分工提案、8 張診斷起點及可選探索。分工、投入與探索方向仍待團隊定案。

本版未啟動照片驗證，沒有 OCR、座標校正或實機控制；Thor／ARM64／JetPack 相容性尚未驗證。fixture 選取與測試結果不代表照片辨識、擦拭能力或競賽實機驗收。
