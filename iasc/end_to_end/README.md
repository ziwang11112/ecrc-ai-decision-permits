# 原始请求到独立服务的 S8 复现

本目录是新增实验，原始运行时和 S6 结果没有改变。只依赖 Python 标准库；建议使用报告记载的 Python 3.12 环境。SQLite 随 Python 提供。程序只在本机回环地址启动子进程 HTTP 服务，不发送真实通知。

正式实验冻结以后，在本目录运行以下命令；输出目录必须尚不存在：

```text
python run_e2e.py --out reproduced --formal
python audit_e2e.py --out reproduced
python build_report.py --out reproduced
```

`--formal` 验证 CODE_FREEZE.json 中全部源码和输入 hash，并固定六场景、三重复、两实现共 36 次。它保存所有失败并继续其余计划场景。不同次执行的并发赢家、permit/effect IDs、进程、端口、实际时间和数据库字节可以不同；同输入、契约不变量和规定的状态计数才是比较依据。

`inputs/` 是两实现共用的原始 policy/proposal/evidence JSON，不含预签许可。`legacy_snapshot/` 是未修改的历史源快照。新增 ECRC 原子签发包装在 `ecrc_e2e.py`；普通独立签发在 `ordinary_e2e.py`。`PROTOCOL.md` 及运行前的 `PROTOCOL_AMENDMENTS.md` 明确新的事务和清理语义。

每次运行保留原始输入副本、client.sqlite、sink.sqlite、进程日志、trace.json 和各检查点的独立 SQLite 备份。`outcomes.csv` 保留全部 36 行；独立审核由 `audit_e2e.py` 直接读取数据库而非摘要计数。`build_report.py` 产生可编辑 LaTeX 状态表、表格 CSV、信息匹配结果和由真实结果生成的英文稿件片段。

开发资料（dev_*、普通实现小型检查和审计 corruption checks）与正式 out 分开，不混入 36 次分母。初次 Windows 连接清理异常及修补记录保留。正式实验不是 preregistration、随机故障可靠性研究或生产性能测试，也不证明 predictor 输入来源都获准。

第二轮修订补齐了已完成的第二套完整复跑，入口为 portable_reproduction/README.md；包含全部数据库、日志、逐次身份对照和验证清单。检查点计数应读为 126 对备份＝90 对非最终＋36 对最终状态备份，见 R2_CORRECTIONS.md。冻结 build_report.py 等历史代码不因文字勘误改动。
