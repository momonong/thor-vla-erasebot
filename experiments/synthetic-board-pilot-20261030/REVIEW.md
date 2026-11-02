# 本輪資料複核

本文件記錄 2026-10-30 的資料複核現場；下列當時 Git 狀態不代表 2026-11-02 的版本交付狀態。

核對版本：manifest SHA256 `0178c22c51b0614caa14a06cf7f7f5bfb1b0c5ba28f023fdd3f7d33d0f2b2fd0`。主責與獨立 AI 協作者完成唯讀複核，尚未經使用者人工驗收。

- 主責核對 293 個生成資產 hash、生成器／詞表／規格 hash 與最新驗證收據一致。實作者的同版驗證證據為 294 個產物同種子 byte replay 一致；沒有另跑模型。
- 已目視總覽與 B01 原尺寸配對，並核對修正後 B03／B08。B01 紅墨目標由 bus 變 hammer；指定 BLUE 與最左 apple 的 occurrence 不變。
- B03 工具題沒有目標，保留動物題保留 horse 與 beetle；B08 昆蟲題選 bee。詞表允許多重類別，insect 完整包含於 animal。
- index／prompt 只有模型所需圖片與單題指令，未見 supervision／答案框／mask／occurrence ID 洩漏。這是靜態資料隔離核對，尚無新模型 runner 或端到端執行證據。
- 原始三圖實驗 tree SHA 仍為 `c6993c45cb34785a878ee42768740fa9eafebc072af428d22ab4dee1a8269ac6`；tracked Git diff 為空，HEAD 仍是 `6848723ac9751b06720567f01e82270cd40d2b12`。未提交、合併或推送。

此版本沒有剩餘資料流程阻斷問題，但只有兩個字型、規則格狀布局與有限詞表，且已用於開發與修正；不視為 held-out、真實白板或泛化證據。程序 GT 自洽不代表開放式語意皆正確，擴詞與新指令仍須另行檢查。24 張圖片是 12 個 family 的配對變體，不能當成 24 個獨立場景。

`pair-preview.png` 是主責以 Pillow 合成的 B01 配對閱讀圖，附的 bus／hammer 答案由已保存的規則 GT 讀取；它不屬模型輸入，也沒有改寫原始兩張圖片。研究來源與後續方案在 [RESEARCH.md](RESEARCH.md)，操作入口在 [README.md](README.md)。
