# 襯材評估的人工合成案例

所有 JSON 都是手寫邏輯案例，沒有照片、物理模擬、示範軌跡或真實操作。時間與循環數為假設值，禁止當作實測或回放到手臂。

`target.json` 的 4 × 2 像素格網只有左側四格是目標區域；不是 12 × 12 cm 材料，也不是校正結果。每個觀測都綁定同一個 canonical SHA256，`wrong-target.json` 故意填入錯誤指紋。

| 案例 | 固定預期 | 手算／原因 |
| --- | --- | --- |
| clear | criteria_met，退出碼 0 | 交集 4、聯集 4，假設其他紀錄符合 |
| partial | criteria_not_met，退出碼 1 | 交集 3、聯集 5；coverage 0.75、IoU 0.6 |
| folded | criteria_not_met，退出碼 1 | 面積全覆蓋，但假設仍有摺角 |
| unknown-fold | insufficient_evidence，退出碼 2 | 沒有摺角檢查結果 |
| not-run | not_run，退出碼 4 | 觀測／量測全為 null；不得補零 |
| wrong-target | invalid_input，退出碼 3 | 目標內容指紋不符 |

`expected.json` 是人工固定的預期表；不是由評估器輸出回填。操作方法見 [使用文件](../../docs/liner-offline-evaluation.md)，本輪實際結果見 [本次整合驗證](../../docs/validation-0.3.0.md)。
