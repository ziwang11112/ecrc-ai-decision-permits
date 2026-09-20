"""Write an interpretation from the complete audited counts, retaining ties."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

metrics = read(ROOT / "AGGREGATE_METRICS.json")
review = read(ROOT / "review/postrun_01/REVIEW.json")
freeze = read(ROOT / "review/prerun_01/FREEZE.json")
summary = read(ROOT / "runs/batch_01/SUMMARY.json")
if not review["technical_integrity_pass"] or review["failures"]:
    raise RuntimeError("Complete independent audit required")
arms = {r["arm"]: r for r in metrics["arms"]}
full = arms["qualification_ecrc"]
labels = {"direct_native_dispatch": "直接执行基线", "qualification_ecrc": "完整 ECRC",
          "existing_rules_only": "普通规则流程", "without_claim_evidence_requirement": "去掉权限的正向资格证据要求"}
reason_labels = {"health": "健康原因", "other": "误订", "unspecified": "未提供原因"}
category_labels = {"eligible": "合格", "ineligible": "已知不合格", "unresolved_required_information": "必要信息不足",
                   "unresolved_or_transfer": "需要转交处理"}
def ratio(numerator, denominator):
    return f"{numerator}/{denominator}" if denominator else "不适用（0个候选）"
table = ["| 方案 | 合格操作完成 | 合格操作漏执行 | 已知不合格仍执行 | 缺必要信息仍执行 | 须转交处理仍执行 |",
         "|---|---:|---:|---:|---:|---:|"]
for arm in freeze["arms"]:
    r = arms[arm]
    table.append(f"| {labels[arm]} | {ratio(r['eligible_completed'], r['eligible_count'])} | {r['eligible_missed']} | {ratio(r['ineligible_executed'], r['ineligible_count'])} | {ratio(r['missing_information_executed'], r['missing_information_count'])} | {ratio(r['transfer_required_executed'], r['transfer_required_count'])} |")
reason_table = ["| 请求模板 | 合格 | 已知不合格 | 必要信息不足 | 须转交处理 |", "|---|---:|---:|---:|---:|"]
for r in metrics["by_reason"]:
    if r["arm"] == "qualification_ecrc":
        reason_table.append(f"| {reason_labels[r['reason']]} | {r['eligible_count']} | {r['ineligible_count']} | {r['missing_information_count']} | {r['transfer_required_count']} |")
calls = sum(r["native_calls"] for r in arms.values())
writes = sum(r["native_writes"] for r in arms.values())
pair_count = len(summary["comparisons"])
rules_equal = sum(c["rules_full_final_db_equal"] for c in summary["comparisons"])
claim_equal = sum(c["claim_off_raw_final_db_equal"] for c in summary["comparisons"])
qa = read(ROOT / "review/prerun_01/QA.json")

example = "本次没有选择符合预定展示条件的差异例；所有结果仍完整保留。"
contexts = review["candidate_population"]["candidate_contexts"]
grouped = {}
for c in contexts:
    grouped.setdefault(c["user_id"], {})[c["reason"]] = c
for uid, group in grouped.items():
    if group.get("health", {}).get("category") == "eligible" and group.get("other", {}).get("category") == "ineligible":
        health, other = group["health"], group["other"]
        rid = health["reservation_id"]
        rows = [r for r in review["rows"] if r["user_id"] == uid]
        lookup = {(r["arm"], r["reason"]): r for r in rows}
        lines = ["| 同一预订的请求原因 | 独立资格分类 | ECRC 实际取消 | 普通规则实际取消 | 去掉资格依赖后实际取消 |",
                 "|---|---|---:|---:|---:|"]
        for reason in ("health", "other", "unspecified"):
            g = group[reason]
            actual = [len(lookup[(a, reason)]["actual_cancelled_ids"]) for a in ("qualification_ecrc", "existing_rules_only", "without_claim_evidence_requirement")]
            lines.append(f"| {reason_labels[reason]} | {category_labels.get(g['category'], g['category'])} | {actual[0]} | {actual[1]} | {actual[2]} |")
        example = (f"预订 `{rid}` 的三种原因使用相同原生预订事实。\n\n" + "\n".join(lines)
                   + f"\n\n示例来自 `{health['case_id']}`、`{other['case_id']}` 及同账户 unspecified 条件。"
                   + "这是在完整结果中按原哈希顺序找到的首个健康原因合格、误订原因不合格的展示例；"
                   + "示例选择仅用于解释，未影响固定样本、主表或分母。")
        break

no_miss = ("本批没有观察到对合格操作的误拦截。" if full["eligible_count"] > 0 and full["eligible_missed"] == 0
           else "本批合格操作的漏执行情况必须按上表报告和解释。")
if full["eligible_count"] == 0:
    no_miss = "本批没有合格候选，不能估计合格操作完成或误拦截。"
full_vs_ablation_diff = any(
    c["observable_hashes"]["qualification_ecrc"]["after"] != c["observable_hashes"]["without_claim_evidence_requirement"]["after"]
    for c in summary["comparisons"])
mechanism_statement = ("观察到的完整组与消融组差异，支持资格结果是否约束执行权限会改变派发；"
                       "不能归于更好的模型、更聪明的规则或 ECRC 独有的业务智能。" if full_vs_ablation_diff
                       else "本批完整组与消融组没有观察到最终效果差异，不能据此声称该依赖改善了业务结果。")
positive_statement = ("这批数据扩大了资格与执行权限连接的受控覆盖，增加了应当获准执行的操作及同一预订在不同原因下的配对观察。"
                      if full["eligible_count"] > 0 else "这批数据增加了受控请求覆盖，但没有增加合格操作，原有正例不足的缺口仍在。")
text = f"""# 原生记录受控覆盖：结果与审查

固定的 **{full['unique_accounts']} 个账户、{full['unique_reservations']} 个预订、{full['constructed_request_count']} 条构造请求 × 4 组，共 {len(summary['rows'])} 次执行**已经结束，独立审计通过。
完整 ECRC 的合格操作完成数为 {ratio(full['eligible_completed'], full['eligible_count'])}；这些合格请求涉及 **{full['unique_accounts_with_eligible_request']} 个不同账户／预订**。{no_miss}
同一预订的三个原因条件有相关性；合格请求数不等于同样多的独立用户。

## 为什么补这一组

此前原生业务消融只有一个合格操作，无法充分检查应当执行的操作是否被拦住。
本轮先检查官方剩余 test 请求，发现历史记录已将整个 test 分区用于开发筛选，而且存在账户与请求重复；该分区不再能充当未知确认集。
其六个初始取消请求仍独立完成了 30 次扩展执行并保留零正例的结果，见相邻 `ecrc_airline_test_validation_2026-09-15/RESULTS_REVIEW_ZH.md`。

本研究使用同一 pinned 原生数据库中的更广记录和人工请求模板，明确属于**受控业务接口覆盖验证**。
它不是新官方 benchmark 任务、未知数据集、完整自动对话或现场用户实验。没有为构造请求借用原任务 ID 或 gold 分数。

## 数据和实际结果

原库有 500 个账户、2,000 个预订。按结构关联形成 452 个可用账户，排除公开任务与固定历史查询涉及的 34 个账户，剩 418 个。
在未使用票种、保险、状态、资格或比较结果选样的前提下，按固定种子取前 100 个账户，每账户一个预订；再固定构造 health、other、unspecified 三个请求。
100 是预先固定的本地资源范围，不是功效计算所得的达标门槛。没有为了取得更多正例重抽或扩大样本。

以下按构造请求机会统计。分母分别是对应资格类别的总数，不能合成为真实用户总体发生率。

{chr(10).join(table)}

分类构成如下；同一行在四个实现条件下使用相同原始事实和独立分类。

{chr(10).join(reason_table)}

缺少取消原因与需要转交处理分开保留。停止派发不等于完成澄清或转交，不能把这两类统一称为正确完成任务。
合格操作“完成”以真实 native 调用、响应和完整数据库变化共同核实；它指本地模拟预订变化，不代表实际退款、座位释放或避免损失。

## 机制解释与更强对照

完整 ECRC 与普通规则流程在 {rules_equal}/{pair_count} 个请求的完整最终数据库上相同；去掉资格依赖与直接执行在 {claim_equal}/{pair_count} 个请求上相同。
这些打平关系是观察结果，不是完整性审计的通过条件。普通规则结果始终保留。

所有组共用既有事实查询、对象选择和确认流程。普通规则直接按公开业务条件判断是否执行；完整 ECRC 把正向资格证据设为许可依赖。
消融只删除这个依赖，保留原业务资格计算及其否定结论，没有伪造正向证明。
{mechanism_statement}

{example}

## 核对与适用范围

运行前 {qa['tests']} 项合成 QA 通过，冻结 {len(freeze['sources'])} 个源／输入／选择证据文件以及 {len(freeze['vendor_sources'])} 个 vendor 文件；原有规则、解析器、ScopeGate、核心和独立业务评价器均未修改。
每格使用新 native 环境；共用初态文件以逐格哈希确认，终态采用完整 gzip JSON 保存。
主执行累计 {calls:,} 次 native 工具调用、{writes:,} 次写操作；等量工具调用在新环境另行重放以核对响应与状态，重放不增加统计样本。
事后独立审核重构了全部 {len(summary['rows'])} 格、{len(review['pairs'])} 组配对及 {len(review['permissions'])} 条许可记录，并复核抽样、原始确认和数据库效果。
新的事后审核包装器记录了自身哈希，但不追溯声称它在运行前已冻结；它依赖的原独立审核函数属于运行前冻结材料。

容量 100 在单预订请求中不构成约束。本轮没有注入元数据故障、并发争用或恢复故障，也没有把航空动作接入原子完成回执；禁止用这批结果证明所有 ECRC 部分的效益。
许可账本的 armed/held 与 native 预订效果分别记录，没有制造 finish、committed 支出或完成回执来替代缺失的集成。
模型调用与模型 API 费用均为 0。局部计时不包含全部准备、压缩和重放，且另一项本地扩展曾并行运行，不用于速度优势结论。

## 对论文能增加什么

{positive_statement}
可按表中完整结果讨论错误放行、漏执行、缺信息和转交边界，并保留普通规则的表现。
它不能独自证明复杂多步任务成功率、真实客户收益、未知分布泛化或相比所有普通实现的优势。
因此适合补强方法的业务接口验证；新请求来自人工模板这一边界须写清楚，不能包装成完整 benchmark 突破。

结果文件：`ARM_METRICS.csv`、`REASON_METRICS.csv`、`CASE_METRICS.csv`、`AGGREGATE_METRICS.json`。
独立审计：`review/postrun_01/REVIEW.json`。全部运行结果和脚本按固定版本归档；本轮未改论文、Overleaf 或 GitHub。
"""
with (ROOT / "RESULTS_REVIEW_ZH.md").open("x", encoding="utf-8") as stream:
    stream.write(text)
print(json.dumps({"report_written": True, "eligible_contexts": full["eligible_count"],
                  "eligible_unique_accounts": full["unique_accounts_with_eligible_request"]}))
