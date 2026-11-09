# Thor 0.3.0：整合驗證

2026-11-09，Linux x86_64、CPython 3.12.3。全新隔離候選自 main 整合襯材單筆評分與 Calcifer 已驗收的批次 patch；原本開發目錄未被改寫。

```sh
UV_CACHE_DIR=/tmp/thor-release-uv-cache uv sync --locked --offline --no-python-downloads
UV_CACHE_DIR=/tmp/thor-release-uv-cache uv run --locked --offline python -B -m unittest discover -s tests -v
```

**81 tests passed，exit 0**：39 項歷史離線回歸、16 項襯材評分、8 項批次 worker 測試、18 項獨立 host 驗收。歷史 55 與隔離任務 42 含重疊，不額外相加。新增 host acceptance 原本在 Calcifer 保護測試範圍，現在以可攜測試保存。

批次原始 patch SHA256：`9c5c5ff11bef0deb272798677537ea910233a5b18b5a83a37ccb64c7e5fb12d9`。整合前驗證 hash 與 `git apply --check`；文件後續更新交付狀態及平台限制，不改寫原始私有收據。

六個手寫合成案例涵蓋 1 項符合、2 項不符合、1 項證據不足、1 項無效輸入、1 項未執行；未知成功率保持 null。這是工具驗證，不是六次實機實驗。48 案／144 列研究模板仍 planned／not_run。

原生 Windows／WSL 尚未執行本版驗收。單筆 CLI 可在 Windows Python 3.12 作局部檢查；批次工具依賴 POSIX fd／O_NOFOLLOW，不能在原生 Windows 當成可用。Windows 適用命令與下一步見 [交接](handoffs/windows-2026-11-09.md)。

本次沒有照片辨識、馬達動作、真實示範採集、訓練、GPU、Thor 部署或正式送件。真實需求與團隊經驗尚待確認；未把其他論文／歷史白板成果改寫成本題能力。
