# 襯材整備啟動包

這是 protocol 0.1 的**測試規劃與空白紀錄**，不是模型資料、物理模擬或實測結果。[完整定題規格](../../liner-research-plan.md)是本包的依據。

- `trial-plan.csv`：2 種規劃尺寸 × 4 種起始狀態 × 3 種起始位置 × 2 次重設，共 48 列。A 為核心 24 列；B 為不同尺寸挑戰 24 列。每列均為 planned。
- `results-template.csv`：每個規劃場景對應 fixed_script、visual_feedback、learned_policy 三方法，共 144 列。每列均為 not_run；量測、成功判斷及證據路徑全部空白。

## 起始條件

| 欄位值 | 操作定義 |
| --- | --- |
| A / B | 同一候選材料的 12 × 12 cm／12 × 16 cm。尺寸是初始提案，未量測可達性 |
| flat | 無摺角，仍可能偏位；包括檢查不需動作時能否正確停止 |
| corner_ne / corner_nw / corner_sw | 僅指定角向內折一次；三角形摺角深度先以短邊約 15% 作提案 |
| centered | 初始中心與目標中心一致 |
| shifted_left | 往左偏移約短邊 10%，不得超出已核對工作區 |
| rotated | 以中心旋轉約 10 度，方向須記錄 |

上列方向依固定俯視畫面。所有長度／姿態需在機械關卡後實量、凍結、記錄；表不是可執行命令。各 repetition 必須重新放置，保留 before／after 證據。

## 記錄規則

試驗時複製空表到有 protocol 版本的結果檔；保留模板。`status` 從 not_run 改為 completed、failed 或 aborted，並填 evidence_kind=real_robot。離線人工標註改用 offline_annotation；不得與真機成績合併。

`first_cycle_success`：第一次觀察與至多一個操作循環後是否滿足全部成功條件；一開始就達標且正確停止也算，須標註 zero_action_success。`success`：6 循環、90 秒內，零人工介入，coverage ≥ 0.95、IoU ≥ 0.90、fold_free=true。fold_free 要有獨立側面／現場檢查證據，不能只靠面積推定。

`duration_s` 自該次開始觀察至最後結果判定；`cycles` 是已執行的操作循環數。`human_interventions` 是開始後的人為接觸／重設次數。失敗也填時間與原因；未知數值留白，不能填 0。保留 setup_id、episode_id 與 protocol_version 供分組／追溯。

三方法須從獨立重設的場景開始，交錯順序並保留初始影像。B 未參與訓練或調參；A／B 分開報告分子與分母。not_run 排除成績計算並單獨報未完成數；failed／aborted 不移除。

## 先處理的缺口

1. 真實襯材照片與材料厚度；沒有就只做資料流程準備。
2. 手臂／供電／校正／相機／停止方式；沒有就不做動作。
3. 10 次抓邊提拉機械關卡；不通過就不投入示範與訓練。
4. 初選實景經驗影片、正式隊伍資料及到場能力；不可用本包補造。
