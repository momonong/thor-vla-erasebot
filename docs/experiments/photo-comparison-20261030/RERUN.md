# 可攜分析與推論重跑是兩回事

已驗證的portable入口只有 `python -B analyze.py`：它不讀模型權重、不呼叫外部API、不訓練或接硬體，僅驗證已存檔案與原parser結果，重新加總AI adjudication。內容對錯仍是已有AI判定，沒有冒稱程式自動重評圖片。

source/保留六個歷史原檔的精確bytes：runner.py、batch.py、test_runner.py、single-question/adapter.py、launch.py、test_adapter.py。原runner中的通用model-cache/相對資料位置是當時程式的設定模板，不是這個公開包的可攜設定；metadata中的個人機器實際locator則沒有發佈。不要直接執行這些封存推論CLI並假定會成功。

本次沒有為新目錄移植推論、下載權重、安裝套件或重跑模型，因而沒有portable inference成功證據。未來若獲授權重跑，需另行配置固定revision的本機模型、適配資料路徑與相容runtime，保存新輸出並標示新環境／processor／量化與hash；不得覆寫本包raw，或把新結果冒稱當時的原始執行。

build_packet.py只從本機完整原實驗建立本包，使用明確allowlist和原件hash；預設輸入是repo中未追蹤的experiments/photo-comparison-20261030。原件未隨repo發布，外部讀者只需analyze.py，不需重建導出，也不能只靠SHA還原被省略的實機metadata。Git子目錄.gitattributes使用-text保留CRLF；重新格式化raw/prompt會改變實驗封存hash。
