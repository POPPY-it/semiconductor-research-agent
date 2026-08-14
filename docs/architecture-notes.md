# smolagents 内核架构笔记（Day 2-3 精读产出）

> 对应源码：`smolagents-src/src/smolagents/agents.py`（1813 行）、`memory.py`、`models.py`
> 精读版本：master v1.27.0.dev0；运行版本：PyPI 1.26.0

## 1. 模块地图

| 文件 | 职责 |
|---|---|
| `agents.py` | 核心：`MultiStepAgent`（抽象基类）→ `ToolCallingAgent` / `CodeAgent` |
| `models.py` | LLM 适配层：`Model` 基类 → `OpenAIModel` / `TransformersModel` / `LiteLLMModel` 等 |
| `tools.py` | `Tool` 定义、`@tool` 装饰器（从签名+docstring 生成 JSON Schema）、参数校验 |
| `memory.py` | 步骤记忆模型 + `CallbackRegistry` 回调注册表 |
| `local_python_executor.py` | CodeAgent 的 Python 代码沙箱执行器 |
| `monitoring.py` | `AgentLogger`（rich 终端渲染）+ `Monitor`（token 统计） |

## 2. 主循环（ReAct 变体，读 run → _run_stream）

```
run(task, stream, reset)
 ├─ state.update(additional_args)          # 注入数据源等变量
 ├─ memory.system_prompt = SystemPromptStep
 ├─ python_executor.send_variables(tools)  # CodeAgent 把工具注入沙箱
 └─ _run_stream(task, max_steps):
     while not final_answer and step_number <= max_steps:
       ├─ [可选] _generate_planning_step → PlanningStep
       ├─ ActionStep(step_number)
       ├─ _step_stream(action_step):        # 子类实现（ToolCalling/Code 各自实现）
       │     yield ...; 若 ActionOutput.is_final_answer → 标记完成
       │     └─ final_answer_checks 逐个断言校验（我们的质检挂载点！）
       ├─ except AgentGenerationError: raise   # 实现 bug → 直接炸
       ├─ except AgentError: 记入 step.error  # 模型犯错 → 记录后继续
       ├─ _finalize_step(step): step_callbacks.callback(step)  # 回调（SSE 挂载点！）
       └─ step_number += 1
     └─ 超步数 → _handle_max_steps_reached（强制让模型给 final_answer）
```

**错误分级设计（面试好素材）**：
- `AgentGenerationError` = 我们（框架/产品）的 bug → 抛出、快速失败
- `AgentError` 其余子类 = 模型输出问题（解析失败/工具报错）→ 记入 `action_step.error`，让模型下一轮自我修正

## 3. 记忆模型（memory.py）

- `MemoryStep` 家族：`TaskStep`（任务）→ `SystemPromptStep` → `PlanningStep`（可选计划）→ `ActionStep`×N（每步含 `model_output`/`action_output`/`tool_calls`/`error`/`token_usage`/`timing`）→ `FinalAnswerStep`
- `AgentMemory.write_memory_to_messages()`：把步骤序列折叠成 messages 喂给模型 → 支持多轮上下文、跨 run 保留（`reset=False`）
- `CallbackRegistry`：按 `MemoryStep` 类型注册回调，`_finalize_step` 时统一触发

## 4. 我们的产品要挂载的 4 个扩展点（重点！）

| smolagents 机制 | 我们的用法 |
|---|---|
| `step_callbacks`（CallbackRegistry） | 注册 `ActionStep/PlanningStep/FinalAnswerStep` 回调 → 推送到 Redis Pub/Sub → SSE → 前端"Agent 思考过程"实时可视化 |
| `final_answer_checks` | 挂质检函数：报告数字是否与知识库引用一致、篇幅约束 → 校验失败触发重写 |
| `managed_agents` | 研究/数据/质检三个 Agent 以受管 Agent 互调（每个需要 `name` + `description`） |
| `prompt_templates` | 把通用 system prompt 替换为"半导体研报专家"模板（日报/周报/深度三套） |
| `state` + `additional_args` | 注入当日数据源快照、用户选题参数 |

## 5. CodeAgent 特有机制

- 模型生成 **Python 代码**（而非 JSON 工具调用），由 `LocalPythonExecutor` 在受限命名空间执行（`BASE_BUILTIN_MODULES` 白名单）
- 工具以 Python 函数形式注入沙箱；`final_answer` 是注入的哨兵函数
- 优点：单步可做"取数→计算→绘图→总结"复合操作，步数更省（我们 demo 只用了 3 步）
- 安全考量：白名单模块 + 可选远端沙箱（E2B/Docker）——生产环境我们上 Docker executor

## 6. 面试考点速记

1. 为什么 ReAct 循环里 planning 是可选的（`planning_interval`）？→ 短任务免规划省 token，长报告任务开启
2. token 统计怎么做的？→ `Model.generate` 返回 `token_usage`，`Monitor` 通过 ActionStep 回调累加
3. 模型中途输出坏 JSON/坏代码怎么办？→ 解析失败抛 `AgentParsingError`（属 AgentError）→ 记 error 继续下一轮，靠模型自我修正
4. 我们怎么做到"流式"？→ 内核 `run(stream=True)` 返回生成器，每步 yield；我们进一步用 step_callbacks 转成 SSE
