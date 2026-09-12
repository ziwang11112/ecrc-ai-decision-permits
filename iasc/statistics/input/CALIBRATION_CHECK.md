# 校准约束冗余核查

日期：2026-09-11。只读原代码、冻结预测与归档结果；没有重训、改变采用的阈值、修改结果或主稿。补充审计文件全部写在本目录。

## 结论

**Pro 的代数意见成立，且实际校准代码与数据满足前提。** 在当前每人 alert 8 + review 2 的校准设置下，pooled action precision ≥ 0.60 已蕴含 false actions ≤ 4.210526/100 decisions；因此 9/100 的可行性约束不会排除任何满足 precision 条件的候选阈值。15 个外层训练校准选择均为 feasible，9/100 在这些选择中不具有额外筛选作用。这是一个需要澄清的方法性质，不构成预测结果失效，也不需要重新训练。

当前补充文件提供了逐参与者 policy 指标/计数，但没有提供最终汇总的 participant-equal policy precision/coverage 敏感性分析。S4 的 macro AUROC 不能替代这项政策指标敏感性。

## 1. 代码里的量确实是什么

相对路径均以项目根目录为起点。

| 前提 | 核查证据 |
|---|---|
| 校准 alert cap = 8，review cap = 2；precision floor = 0.60；false limit = 9/100 | `experiment_reproducibility/icair_2026/framework_v1/e1/config.py:24`、`:25`、`:32`、`:33`；归档 `evidence_v2/experiment_config.json` 一致。|
| 每人的 action 总数最多 10，且 alert/review 互斥 | `e1/routing.py:23` 的路由函数按 subject 累计两种候选；`:107`–`:115` 检查 one-hot 路由和逐人容量。|
| precision 同时包括 alert 和 human_review | `e1/routing.py:120`–`:132`：`action = alert | review`，`true_action = sum(y[action])`，`false_action = n_action - true_action`。|
| 错误行动率分母是全部校准 decision 数 N，不是 action 数、候选数或人数 | `e1/routing.py:121`、`:159`–`:160`：`action_precision = true_action/n_action`；`false_actions_per_100 = 100*false_action/n`。|
| 选择时确实同时检查两条约束 | `e1/routing.py:180`–`:202` 对 0.30–0.85、步长 0.01 的 56 点逐个路由，再筛 `n_action > 0`、false ≤ 9、finite precision ≥ .60。|
| 不把内层验证片段当成多个 episode，也没有只留下少量 eligible decisions | `e1/models.py:144` 起的 `grouped_oof_predictions` 按完整 subject 分组，拼回全部训练池的每个 subject/trial，并在返回前检查没有重复、行数等于 `len(train_pool)`。`run_e1.py:192`–`:203` 把这份完整校准表送入选择器。|
| 最终冻结阈值仅用开发 OOF | `run_e1.py:245`–`:264`，随后才在所有开发资料上 fit 并 score 外部数据。外部 200-trial episode 不是阈值选择输入。|

开发冻结预测的每人长度重新计数为：95 decisions × 15 人、100 × 504 人、150 × 98 人；总计 617 人、66,525 decisions，三种生成器完全一致。按保存的外层 subject assignment 取每次训练池，人数和行数与 15 行 `outer_fold_operating_points.csv` 的 `n_training_participants`、`n_calibration_participants`、`n_calibration_decisions` 全部一致；各训练池的最短 episode 均为 95。

## 2. 代数成立的范围

令 m 为校准参与者数，N 为其全部 decisions，A 为 alert 与 review 的合计，TP 为其中 proxy positives，F = A − TP。对于选择器要求的 A > 0：

\[
\frac{TP}{A}\ge 0.60
\quad\Rightarrow\quad
F\le 0.40 A\le 0.40(8+2)m=4m.
\]

因为 N ≥ 95m，

\[
\frac{100F}{N}\le\frac{400m}{N}\le\frac{400}{95}
=4.210526\ldots <9.
\]

用实际训练池大小而不只用最短长度，15 个外层选择对应的更紧上界为 **3.707464–3.711495/100**；全开发 OOF 的上界为 **3.709884/100**。整数计数还可能使上界稍紧，但不影响结论。

这不是说 false-action 限制对任意容量、任意 episode 长度或任意 precision 定义都冗余；也不保证无容量限制的 arm 满足 9/100。它只说明当前校准可行集中的第二条约束冗余。选择器另有 infeasible fallback（`e1/routing.py:216`–`:230`），但本次全部 15 个外层与 3 个最终选择都有 feasible 阈值，因此实际选择没有走这个 fallback。

若只从 eligible 条件移除 `false_actions_per_100 <= 9` 而保留原排序与 tie-break，可行集合相同，所选阈值必然相同。不能因为冗余而事后把 9 调紧到某个会产生“活动约束”的值，再把新结果当作原先方法。

## 3. 已保存结果与可重建网格

原选择器把所有网格行放在局部 `rows`，最终只返回 selected（`e1/routing.py:183`、`:230`–`:235`）。`run_e1.py:587`–`:596` 保存 selected operating points、外层预测与 route 结果，未保存各外层训练池的完整 fitted-model inner-OOF 校准预测或逐阈值网格。本次查找没有发现这些缺失网格的独立归档；`a4_permission_grid.csv` 是政策 arm 对照，不是训练侧阈值搜索记录。

因此分三层报告：

1. **15 个外层 selected rows：实际核对。** 全部 precision ≥ .60、全部 `selection_constraints_satisfied=True`；动作计数、分母和 false rate 全部可由归档计数重算。false rate 为 2.383107–3.238615/100，距 9 至少 5.761385/100。
2. **8 个完整网格：可从已有正确 score set 重建。** 三种最终冻结阈值使用全部开发 OOF 预测，因此可以重建 3 × 56 点。history 不需要 fit，其分数在任意 inner fold 都相同，因此再按每个外层训练 subject 集重建 5 × 56 点；选中行计数与归档完全复现。
3. **其余 10 个 fitted-model 外层训练网格：材料缺失，不能冒充重建。** 不能把保存的全开发 outer-OOF 预测简单去掉某一 fold，当作该 outer-training pool 的 inner-OOF 预测。其满足 precision 但违反 false limit 的数量仍可由上述代数严格判为零，但未实际枚举其所有阈值，也不知道完整 feasible 个数。没有为此重训。

可重建的 8 个网格共 **448 个阈值行**，其中 **348 行满足 precision eligibility，违反 9/100 的数量为 0**。更强的实际观察是：这 448 行中即使不先要求 precision ≥ .60，也没有一行 false rate > 9（最大为 4.060128/100）；这个“全网格”观察不能扩展到没有保存的 10 个 fitted-model 校准网格。

| 正确校准输入 | 模型 / 外层 fold | 网格数 | precision 合格行数 | 合格且 false > 9 | 原阈值 / 去掉 false filter 后阈值 |
|---|---|---:|---:|---:|---|
| 全开发 OOF | HGB | 56 | 51 | 0 | .60 / .60 |
| 全开发 OOF | History | 56 | 41 | 0 | .43 / .43 |
| 全开发 OOF | Logistic | 56 | 47 | 0 | .58 / .58 |
| 外层训练 History | fold 0 | 56 | 40 | 0 | .43 / .43 |
| 外层训练 History | fold 1 | 56 | 46 | 0 | .39 / .39 |
| 外层训练 History | fold 2 | 56 | 41 | 0 | .43 / .43 |
| 外层训练 History | fold 3 | 56 | 41 | 0 | .43 / .43 |
| 外层训练 History | fold 4 | 56 | 41 | 0 | .43 / .43 |

`calibration_selected_audit.csv` 完整列出 15 个外层选择及约束余量。其所选阈值依次为：History [.43, .39, .43, .43, .43]；Logistic [.61, .59, .59, .59, .60]；HGB [.60, .59, .61, .61, .60]。

精确等号“binding”与“是否改变最优选择”应区分：这些 selected precision 没有恰好等于 .60，history 为 .602081–.608158，logistic 为 .660904–.683550，HGB 为 .723931–.736886。仅凭余量不能判定 precision floor 是否影响离散网格最优解。在可重建网格中，另外只移除 precision floor、保留 false filter 和其余原排序规则：最终 history 由 .43 变 .39；history 外层 folds 0、2、3、4 依次变为 .39、.35、.39、.38，fold 1 仍 .39；最终 HGB/logistic 不变。这是审计用反事实选择，不是采用的新模型或新结果。10 个拟合模型外层 precision-floor 活动性仍未测定。

## 4. Participant-equal policy 指标是否已提供

**逐人材料有，宏平均政策结果尚未作为敏感性结果提供。**

- 原归档 `evidence_v2/participant_workload.csv` 有每人各 cap 的 alert/action precision、coverage 与分子分母；生成位置是 `e1/metrics.py:92`–`:112`。
- S1 协议明确要求对计数求和再作比例，且写明“never average participant precisions”；所以它的 participant-cluster bootstrap 不是 participant-equal point estimand。
- S3 `online/run_online.py:20`–`:25` 定义总计数比例，`:132` 起对 participant multiplicity × count matrix 求和再计算；`online_participant_statistics.csv.gz` 有补算所需全部计数，但 `online_estimates.csv` 没有 macro policy precision/coverage。
- S4 的 `within_auroc_macro` 是参与者等权 AUROC，不是 policy precision 或 coverage。

最小补充建议，不改变阈值和路由：先对现有 S3 全 2 cohorts × 3 models × 2 budgets × 2 allocators 计算 participant-equal alert precision 与 alert coverage，和 pooled 值并列，并报告有效人数。若正文强调 cap removal 导致两指标同升，则也应覆盖该被强调的 cap-removal/固定 cap 对照，而非只挑 S3 或只挑方向一致的模型。

- Macro precision：仅在该 arm 有 alert 的参与者上平均 TP_i/A_i，同时给出 A_i=0 的人数；没有 alert 的 precision 未定义，不能擅自填 0。
- Macro coverage：在 P_i>0 的参与者上平均 TP_i/P_i，零阳性参与者数另报。
- 对两政策 precision 的配对差，须明确是同一集合 `A_i,a>0 且 A_i,b>0` 的每人差值，还是两个 arm 各自非空接受人群的均值之差；二者不是同一估计对象。建议报告共同有效集合的敏感性及其人数，另保留各 arm 非空人群结果，不隐瞒政策改变了谁获得 alert。
- 如加条件区间，复用原参与者重抽样单位和配对逻辑，从每人指标重算宏均值；它仍条件于冻结预测/阈值。不要把宏平均更高自动解释为更公平或有干预收益。

这项补充可直接从现有 sufficient statistics 本地完成，不需新模型、新标签或重跑线上路由；本次只确认材料可用并给出定义，没有擅自增加这批结果。

## 5. 可直接采用的澄清文字

> Operating points were selected to maximize action coverage subject to pooled action precision of at least 0.60. The implementation also retained a limit of nine proxy-negative actions per 100 decisions. Under the calibration capacities of eight alerts and two reviews per participant and episode lengths of at least 95 decisions, the precision condition implies at most 4.21 proxy-negative actions per 100 decisions; the additional limit was therefore redundant in this calibration setting and did not alter feasible operating points.

无需据此重训或替换冻结结果。若沿用原方法文字列出两条条件，应增加上面这类透明说明，而非继续暗示两条约束分别提供了独立有效的限制。

## 审计产物与复现

`check_calibration.py` 读取保存的 score sets，重建 8 个网格并核对 15 个 selected rows；`calibration_audit.json` 保存版本、输入 hashes 与输入未改变检查。`calibration_reconstructed_grids.csv`、`calibration_grid_summary.csv`、`calibration_selected_audit.csv` 给出完整计数。`calibration_grid_activity.csv` 是由已重建网格按同一 coverage/precision/false-rate/action-rate/threshold 排序，额外计算去掉 precision floor 的审计结果。没有修改任何原代码、预测、正式结果或主稿。
