# Agent 评测指标（Harness）

> 最近一次运行：见 `results_latest.json`（提交进 git）。
>
> ⚠️ **2026-08-17 更正（P1-2）**：下表为 P1-1 首跑基线（3 条）。当时「缺工具」列全标
> missing 是 **harness 工具检测 bug**（真实轨迹里代码在 `python_interpreter` 的
> arguments 中，检测只扫了 model_output）——已于 P1-2 修复
> （`agent/traces.py::collect_agent_steps` 两处扫描 + 去重，回归测试锁定），
> 全量 20 条重跑后此表将被替换。

## 汇总

| 指标 | 值 |
|---|---|
| 任务数（成功/错误） | 3/0 |
| **任务成功率** | 1.0 |
| **无引用数字率（均值）** | 0.668 |
| **平均步骤数** | 70.7 |
| 平均工具调用 | 52.3 |
| 平均错误数 | 22.0 |
| 平均耗时（s） | 207.4 |
| 平均预算字符 | 1084152 |

## 逐任务

| id | 状态 | 成功 | 无引用率 | 步数 | 工具调用 | 错误 | 耗时s | 缺工具 |
|---|---|---|---|---|---|---|---|---|
| t01 | done | True | 0.623 | 73 | 58 | 14 | 272.6 | query_filings,search_knowledge |
| t02 | done | True | 0.702 | 54 | 32 | 33 | 77.2 | query_filings,search_knowledge |
| t03 | done | True | 0.678 | 85 | 67 | 19 | 272.4 | query_filings |