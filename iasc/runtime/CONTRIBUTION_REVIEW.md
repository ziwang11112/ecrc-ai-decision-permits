# ECRC contribution and recovery-contract review

核实日期：2026-09-11。范围：只读当前 IASC 引言、相关工作、方法，以及归档 governance 实现和本轮 `PROTOCOL.md`、`PROTOCOL_SERVICE.md`、`service.py`。本文件是审稿与设计草稿，**不是新增实验的结果报告**；未改论文、未运行实验、未调用模型或付费 API。以下“目标”必须由实际运行记录验证后才能改成结果。

## 1. 建议的贡献定位

建议将论文定位为：**一个面向重复决策的可执行许可契约，以及该契约在分配、执行和恢复中的可检验边界**。ECRC 的具体对象是证据资格、有限声明、最终路由、稀缺容量与一次逻辑操作之间的绑定；贡献不是新预测器、事务 outbox、幂等 API 或通用 exactly-once 算法。

行为实验解释固定分数经许可和分配后发生什么；独立语义检查解释哪些规则实际起作用；本轮恢复实验解释一份已接受的许可跨进程交付时，哪些身份、容量和收据约束仍应成立。三类证据各回答一个问题，不应把系统恢复成功推导成预测或干预有效性。

同信息普通事务实现若与 ECRC 持平，这是可信结果：它说明所需保证可由普通记录、事务和幂等服务实现，ECRC 提供的是明确的契约及其验证材料。不能据此声称新结构在恢复正确性上优于 outbox，或者 typed artifact 是获得这些保证的必要条件。单主机循环回 HTTP 的延迟差异也不能自动外推成生产部署优势。

## 2. 已有实现与新增工作分界

| 对象 | 已核实内容 | 当前不能据此声称的内容 |
|---|---|---|
| 归档 `PEPSimulator` | `enforcement.py:11–16` 明示模拟；`execute()` 调用 `ledger.complete_execution()`。后者在单个 SQLite 事务中消费许可、处理容量并记录模拟效果与收据。 | 没有向独立服务执行动作，也没有跨数据库恢复。 |
| 归档许可/容量/验证器 | 固定字段、canonical hash、issued registry、容量事务与有限声明约束可复用。`reap_expired_reservations()` 只回收符合条件的未签发 reservation。 | hash 不是来源认证；有限 claim closure 不是自由文本事实验证；已签发但未形成 durable intent 的崩溃缺口未自动解决。 |
| 本轮 durable adapter | 协议规定把已验证许可注册为 durable intent，再经独立 HTTP 服务交付，最后在本地事务中对账；这是新增适配实现。 | 本报告未执行 adapter 测试，不能把其目标写成已验证结果。 |
| 本轮独立 sink | `service.py` 已实现独立进程/数据库、唯一 key、payload conflict 检查，并把 effect 与 key/hash 在同一服务事务中提交后才返回成功。 | 独立 SQLite 中的合成效果记录不是实际告警送达或临床干预；单机进程崩溃测试不是多主机一致性或断电耐久性证明。 |

原方法 §3.5 保留其单 SQLite 模拟语义；建议新增一个短的“Independent-service recovery extension”段落，明确 post hoc engineering extension。不要把原 `complete_execution()` 的模拟 `side_effect_id` 当作服务返回的效果标识。

## 3. 状态机：与本轮固定协议一致的最小版本

令一个逻辑动作为 `o`，持久 key 为 `k(o)`。其 immutable binding 至少包含许可 ID/hash、策略 ID/revision/hash、路由、reservation ID、许可绑定的证据/声明，以及实际 HTTP payload 的 canonical 表示/hash。key 代表逻辑操作，不能以重试次数、进程 ID 或时间重新生成；相同 payload 的两次合法独立动作也不应被错误合并。

本轮协议的授权线性化点是**本地 arm 事务提交**：在同一事务内验证现行策略、许可有效期、注册身份和 reservation，并登记唯一 intent。其后恢复执行已接受的授权，不是重新签发许可。尚未 arm 的过期或已撤销许可不能创建新 intent。已 arm 的动作不会被后续到期/撤销取消；这项不可撤回授权语义必须在方法中直述。

| 当前状态 | 允许事件与守卫 | 下一个状态及容量处理 |
|---|---|---|
| issued / unarmed | 注册许可匹配、策略与有效期通过、动作 reservation 正确；本地原子 arm 成功 | armed；该单位继续计入 reserved。事务回滚则无 intent、无 HTTP。 |
| issued / unarmed | 非动作路由，或授权前校验失败 | 不发送 HTTP；非动作本地终结与拒绝需区分。不要把已 dispatch 的未知结果记成这种拒绝。 |
| armed | 首次发送、重试、超时、断连、暂时不可用、查询暂未找到 | 仍为 armed / in doubt；复用同 key/body，保留容量。HTTP 不在本地写事务内执行。 |
| armed，服务尚无 key | 服务在独立事务内插入 effect 与 key/body；事务提交 | 服务 effect 已持久，本地仍可能 armed。成功回复丢失允许存在。 |
| armed，服务已有同 key/body | 并发或恢复重试 | 返回原 effect 身份，不新增效果。不同 body 必须冲突拒绝。 |
| armed，已获得并验证持久 acknowledgement | 本地事务同时插入唯一收据、reserved→committed、标记完成 | receipted；三项一起提交或一起回滚。 |
| receipted | 同一逻辑操作恢复/重试 | 返回原收据；不增加效果、不二次提交容量、不追加第二份成功收据。 |

`in doubt` 是客户端知识状态，不代表 sink 未提交。单次 404 与超时都不能证明迟到请求不会提交。当前协议不支持 arm 后取消，因此没有 `armed → released` 转移；无限期故障可能无限期占用 reservation。若未来要取消，需要服务端持久拒绝/取消记录或等价的拒绝迟到提交机制，不能靠客户端超时回收。

两个本地事务和一个服务事务之间是可恢复的一致性流程，不是跨库原子事务。允许暂时出现“一个服务效果、零份本地收据、一个 held 单位”；它是必须观测的恢复窗口。

## 4. 三个可检验不变量及有条件的完成性质

### I1：授权绑定与容量守恒

每份许可至多对应一个已 arm 的 immutable 逻辑操作；合法重试保持相同 key、许可和 payload。未 arm 或授权前被拒绝的动作不产生服务效果。对每个配置的 `(policy, revision, scope, route)`，在每次已提交状态中 `0 ≤ S + C ≤ L`。每个 armed 未决动作继续持有其单位，完成时恰好一次 `S→S−1, C→C+1`。

检查：独立读取 intent、许可/容量账本及 sink；比对绑定字段；统计各 checkpoint 与最终的 held/committed 单位。只测最终状态不能排除中途超额；checkpoint 检查本身也不是穷尽所有交错的形式化证明。容量是本协议的逻辑操作预算，不是服务线程的瞬时并发限制。

### I2：服务效果唯一性

对每个逻辑操作 `o`，持久效果计数 `0 ≤ E(o) ≤ 1`；同 key/body 的重试返回同 effect 身份，变更 body 不产生新效果。前提是可信 sink 把去重身份和完整效果原子持久化，去重记录保留覆盖所有允许的迟到请求，并且运行间 namespace 不串用。

检查：直接数独立服务数据库中每个 key 的 effect；并发重试、响应丢失、服务重启、冲突 body 都应纳入。该性质是“这个服务契约下每个逻辑操作至多一个效果”，不是任意 HTTP API 的 exactly-once。

### I3：成功收据有真实效果对应且本地终结唯一

设 `R(o)` 为成功收据数，则 `0 ≤ R(o) ≤ E(o) ≤ 1`，且收据中的 key、payload hash、effect ID 对应服务的持久记录。本地 receipt、容量 commitment 与 intent 完成状态必须原子一致。仅发出请求、收到 TCP 确认或不带持久结果的“已接受”回复，都不足以创建成功收据。

检查：对账使用服务真实记录，不只读 adapter 的 self-report。重点检查服务提交后/本地收据前，以及本地 reconciliation 事务提交前后的崩溃。`E=1, R=0` 暂时允许；`R=1, E=0` 或 `R>1` 不允许。

**完成性质另列，不能混成安全不变量。** 在通信和服务恢复、worker 持续重试、数据未损坏且幂等记录仍保留的前提下，armed 动作应最终进入 receipted。有限注入故障后的实际收敛支持指定场景的恢复，不能证明任意故障下活性，更不能保证无限期不可用时完成。

## 5. 能力对照：勾选只表示已核实的机制，不表示胜负

符号：✓ 为公开说明或归档代码明确提供的机制；“可组合”表示通过额外实现可提供，不能误写成不支持；“目标”仅为本轮共同协议要求，尚未在本报告验证运行。

| 能力 | 通用策略引擎接口，以 OPA 为例 | 事务 outbox + 合约明确的持久幂等 sink | 归档 ECRC | 本轮普通 JSON/事务基线 | 本轮 ECRC adapter |
|---|---|---|---|---|---|
| 对结构化输入计算策略结果 | ✓ | 可组合 | ✓ | 共享授权 fixture 后独立校验；目标 | 共享授权 fixture 后适配校验；目标 |
| 本文 E/C/R/有限 claim 的显式许可字段绑定 | 可组合 | 可组合 | ✓ | 同字段、同规则；目标 | 复用许可字段；目标 |
| 按指定 scope/route 原子 reservation 及预算限制 | 可组合 | 可组合 | ✓ | 目标 | 目标 |
| 本地状态与待交付 intent 同事务登记 | 可组合 | ✓，outbox 的本地机制 | 原模拟无需独立交付；未实现此 adapter | 目标 | 目标 |
| 远端 key/body 冲突检查、effect 与去重记录同事务 | 可组合 | ✓，要求 sink 实现该契约 | 未涉及独立服务 | 共用本轮 sink；待端到端验证 | 共用本轮 sink；待端到端验证 |
| 本文定义的许可—容量—服务效果—收据恢复对账 | 可组合 | 可组合 | 仅单库模拟边界 | 目标 | 目标 |
| 任意外部服务 exactly-once / 即时远端撤销 | 未主张 | 未主张 | 未主张 | 不在协议内 | 不在协议内 |

OPA 官方说明把决策计算与执行分离，并允许结构化输出；不能写成只能 allow/deny 或天生不能表达本文规则。outbox 本身不定义本文 evidence/claim/capacity 语义；这只是职责范围，不是已证实的能力缺陷。[OPA 官方文档](https://www.openpolicyagent.org/docs)

公平对照必须共享实际可用信息、策略版本、key 作用域、payload 绑定、capacity、sink、持久设置、重试机会和故障时点。普通基线不应故意去掉字段校验。两臂共用 ECRC 签发的预先 fixture，意味着本轮比较的是交付/恢复实现，而不是独立许可签发算法。共同 HTTP 传输和 sink 也必须披露，不能称完全独立的整栈重复。

## 6. 必须处理的两处语义接缝

1. **原验证器的时间语义与新授权契约不同。** `governance/verifier.py:51–54` 要求 `permit.issued_at ≤ receipt.executed_at < permit.expires_at`。新协议允许 arm 后许可到期，而首次 sink effect 更晚提交。不能把 arm 时间填入 `executed_at` 掩盖事实。新 adapter 应明确区分 `authorized_at`、服务实际 `committed_at`、本地 `completed_at`，并使用有名称/版本说明的新恢复验证规则；原验证器可继续验证其原语义的归档收据。时间分离与规则差异必须在代码和方法里一致。
2. **签发到 arm 之前的恢复不是本轮默认覆盖。** 归档签发与 outbox arm 不在一个事务里，issued registry 不保存全部可重建许可文档。协议以完整持久的预签发 fixture 为起点是可接受的最小范围，但应直述。不要把本轮 after-intent 故障覆盖写成从任意 adjudication 步骤起的端到端恢复。

此外，当前 `ECRC_BOUNDARY_REVIEW.md` 的早期建议曾把 in-flight 到期/撤销列为可排除范围；最终采用的 `PROTOCOL.md` 已选择 arm 时不可撤回授权。以最终协议为准，并保留此选择的明确解释，避免同时引用互相不同的时间契约。

## 7. 最少新增来源与可直接采用的引文元数据

建议增加下列 3 项即可，不再堆叠新 preprint。网页未显示可靠发表日期，使用 `n.d.` 和访问日期，不把本次访问年份冒充发表年份。原有 Helland CACM 引用可保留；本轮未成功重新取得其全文，因此不额外扩展它的引证范围。不要把 CACM DOI `10.1145/2160718.2160734` 与 ACM Queue 版本的元数据混用。

| 来源 | 本轮核实定位及用途 | 不应外推 |
|---|---|---|
| AWS Prescriptive Guidance, *Transactional outbox pattern* | “Issues and considerations” 的重复消息条目；“Using an outbox table with a relational database” 的同事务写状态/outbox 和独立转发者。支持 outbox 处理本地双写与转发的讨论。 | 该页关于特定 SQS FIFO 的措辞不是任意下游应用效果 exactly-once 的证明。 |
| Malcolm Featonby, *Making retries safe with idempotent APIs*, Amazon Builders’ Library | “Reducing client complexity” 的显式 caller request ID 及去重 token/变更原子提交；“Late arriving requests”；“Same client request ID, different intent”。支持稳定操作身份、服务端幂等与保留期边界。 | 幂等 key 不是免费获得的全系统语义，过期后的 key 重用也不在无限保证内。 |
| Fielding, Nottingham, Reschke, *HTTP Semantics*, RFC 9110, 2022, §9.2.2 | 定义方法幂等性与自动重试的条件。本文 POST 的可重试性来自明确应用契约。 | HTTP POST 或网络库本身不保证业务效果去重；幂等性也不要求每次响应完全相同。 |

Primary URLs，均于 2026-09-11 实际打开核对：

- [AWS transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [Featonby, idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- [RFC 9110, §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#name-idempotent-methods)
- [OPA 官方文档，已有 bibliography 项可复用](https://www.openpolicyagent.org/docs)

```bibtex
@misc{awsTransactionalOutbox,
  author = {{Amazon Web Services}},
  title = {Transactional outbox pattern},
  howpublished = {AWS Prescriptive Guidance},
  year = {n.d.},
  url = {https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html},
  note = {Accessed 11 September 2026}
}

@misc{featonbyIdempotentAPIs,
  author = {Featonby, Malcolm},
  title = {Making retries safe with idempotent {APIs}},
  howpublished = {The Amazon Builders' Library},
  year = {n.d.},
  url = {https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/},
  note = {Accessed 11 September 2026}
}

@techreport{rfc9110,
  author = {Fielding, R. and Nottingham, M. and Reschke, J.},
  title = {{HTTP} Semantics},
  institution = {RFC Editor},
  type = {RFC},
  number = {9110},
  year = {2022},
  month = jun,
  url = {https://www.rfc-editor.org/rfc/rfc9110.html},
  note = {Section 9.2.2; accessed 11 September 2026}
}
```

## 8. 可用英文段落草稿

以下段落没有新增实验数字；只在新增实现及运行结果完成、且保持上述协议时采用。引言第一段可替换现有关于执行衔接的泛化描述；贡献段落对应当前的三条研究问题，不需要增加新的 AI 研究问题。

**Introduction / positioning**

> Reliable retries require an explicit contract for what was authorized, what may still occur after a lost response, and what a completion record establishes. We study these questions for repeated decisions with policy-defined evidence eligibility, finite claim scope and scarce action capacity. ECRC binds these elements to a registered permit. We examine both its effect on allocation over frozen proposals and the consistency of its permit lifecycle. A separate engineering extension connects accepted permits to a durable local HTTP service, allowing the recovery boundary to be tested beyond the archived single-database simulator.

**Contributions**

> We make three contributions: an executable permission contract that binds evidence, capacity, route and finite claim scope; a fixed-proposal evaluation that separates score discrimination from candidate selection and budget allocation; and an implementation study that combines independent semantic checks with process-failure recovery against a conventional transactional baseline given the same authorization records and service contract. The recovery extension uses established outbox and idempotency mechanisms. Its purpose is to test whether permit bindings, capacity accounting and effect-backed receipts remain consistent at specified failure boundaries, rather than to introduce a new delivery guarantee.

**Related work, short replacement/addition**

> Policy engines provide a substrate for structured authorization decisions, while transactional outboxes and idempotent APIs address established persistence and retry problems. An outbox records local changes and delivery intent together; avoiding duplicate remote effects additionally requires a suitable service-side contract. ECRC specifies the evidence, claim and capacity bindings carried through this process. A conventional implementation can provide the same bindings, so our matched comparison does not treat specialized record types as necessary for recovery correctness. \cite{opaDocumentation,awsTransactionalOutbox,featonbyIdempotentAPIs}

**Recovery boundary, method paragraph**

> The archived runtime performs simulated effects and receipt reconciliation within one SQLite transaction. The new adapter instead commits an immutable delivery intent before contacting a separate local HTTP service. Authorization is fixed when that intent is armed: later expiry or revocation prevents new intents but does not cancel this accepted operation. Retries use the same operation key and payload, and uncertain outcomes retain their capacity reservation. The service atomically records the effect and its idempotency binding; the client then reconciles the acknowledged effect, capacity commitment and receipt in a local transaction. These are separate transactions linked by recovery. The guarantee is restricted to this trusted, durable idempotent service and does not extend to arbitrary external APIs. \cite{awsTransactionalOutbox,featonbyIdempotentAPIs,rfc9110}

**If the matched arms tie, permissible result interpretation**

> Both implementations met the observed recovery checks under the specified faults. This supports the feasibility of preserving the permission contract with conventional transactional and idempotency mechanisms; it does not establish a correctness advantage for ECRC or equivalence under untested failures.

最后一句仅在真实结果允许时使用；若有失败，报告失败状态和影响范围，不能为保持定位而删去失败场景。
