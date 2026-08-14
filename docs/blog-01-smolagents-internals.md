# 技术博客①：smolagents 内核剖析——一个 1800 行的 Agent 引擎是如何工作的（初稿）

> 这是我"半导体行业研报 Agent"项目系列博客的第一篇。
> 项目基于 Hugging Face 的 smolagents（Apache-2.0）二次开发；本篇记录我精读其核心源码的收获。
> 精读对象：`agents.py`（1813 行）、`memory.py`、`models.py`（master @ v1.27.0.dev0）。

## 为什么选它精读

在 LangChain/LangGraph、AutoGen、CrewAI 等一众框架里，smolagents 的定位很特殊：**"barebones"——极简内核**。核心循环只有 1800 行，一个周末能精读完。对想真正理解 Agent 工作原理、并在此基础上做生产化改造的人来说，这种"小而完整"的代码库是最佳教材。

## 模块地图

| 文件 | 职责 |
|---|---|
| `agents.py` | `MultiStepAgent` 抽象基类 + 两个子类：`ToolCallingAgent`（函数调用式）、`CodeAgent`（代码式） |
| `models.py` | LLM 适配层：统一 `generate()` 接口，屏蔽 OpenAI/Transformers/vLLM 等差异 |
| `tools.py` | `@tool` 装饰器：从函数签名 + Google 风格 docstring **自动生成 JSON Schema** |
| `memory.py` | 步骤记忆模型 + `CallbackRegistry` 回调注册表 |
| `local_python_executor.py` | CodeAgent 的受限 Python 沙箱（模块白名单） |
| `monitoring.py` | 终端可视化 + token 统计 |

## 主循环：run → _run_stream

```python
# agents.py 精简还原
def run(self, task, stream=False, reset=True, additional_args=None):
    self.state.update(additional_args)                 # 1. 注入外部变量（数据源快照等）
    self.memory.system_prompt = SystemPromptStep(...)
    if reset: self.memory.reset()
    steps = list(self._run_stream(task, max_steps))    # 2. 核心循环
    return steps[-1].output                            # 3. 只取 FinalAnswerStep

def _run_stream(self, task, max_steps):
    while not returned_final_answer and step_number <= max_steps:
        if planning_interval 命中: yield _generate_planning_step()   # 可选规划步
        action_step = ActionStep(...)
        for output in _step_stream(action_step):       # 子类实现单步执行
            yield output
            if output.is_final_answer:
                for check in final_answer_checks:      # ← 最终答案校验链
                    assert check(final_answer, memory, agent=self)
                returned_final_answer = True
        memory.steps.append(action_step); step_number += 1
```

三个设计点值得注意：

**1. 错误分级：谁的锅，谁负责。**
- `AgentGenerationError` = 框架/产品自己的实现 bug → **直接抛出**，快速失败
- 其余 `AgentError`（如 `AgentParsingError` 模型输出坏 JSON）= 模型犯错 → **记入 `action_step.error`，继续下一轮**，靠模型在下一轮看到错误信息后自我修正

这个分级在实际生产化时非常关键：如果混在一起，你的告警系统将分不清"模型抽风"（重试即可）和"代码有 bug"（重试无用）。

**2. `final_answer_checks`：最终答案校验链。**
在模型宣布"我完成了"之后、结果返回给用户之前，内核会依次跑一组断言函数。这就是我做**质检 Agent 的挂载点**——报告数字必须能回溯到知识库引用、篇幅必须达标，否则整个 run 失败重来。

**3. `step_callbacks`：每一步结束的钩子。**
`CallbackRegistry` 按步骤类型（`ActionStep`/`PlanningStep`/`FinalAnswerStep`）注册回调，`_finalize_step` 统一触发。官方用它做 token 监控，我用它做 **SSE 流式推送到前端**，让用户在浏览器里实时看到 Agent 的每一步思考——这也是产品化的关键。

## 记忆模型：为什么上下文能一直保持

`AgentMemory` 维护 `MemoryStep` 序列：`TaskStep → SystemPromptStep → (PlanningStep) → ActionStep×N → FinalAnswerStep`。每个 `ActionStep` 记录模型输出、工具执行结果、错误、token 消耗、耗时。

`write_memory_to_messages()` 把步骤折叠成消息列表喂给模型——因为每一步的"执行日志"都会回填，模型下一轮就能看到上一轮的结果和错误，这就是多轮自我修正的机制。`run(reset=False)` 则让多个任务共享上下文，实现会话连续性。

## CodeAgent 的独特设计：让模型写代码

`ToolCallingAgent` 走经典函数调用路线（模型输出 JSON 工具调用），而 `CodeAgent` 让模型**直接生成 Python 代码**，在受限沙箱里执行：

- 单步可以做复合操作：取数 → 计算 → 绘图 → 总结，**步数更省**（我的第一个 demo 全程只用了 3 步）
- 工具以 Python 函数形式注入沙箱命名空间，`final_answer(...)` 是哨兵函数
- 安全靠模块白名单（`BASE_BUILTIN_MODULES`），生产环境可换 Docker 远端执行器

## 对我产品的意义

读懂这 1800 行后，二次开发的路线图非常清晰：

| 内核机制 | 我的改造 |
|---|---|
| `step_callbacks` | → Redis Pub/Sub → SSE → 前端实时执行视图 |
| `final_answer_checks` | → 质检：数字与引用交叉核对 |
| `managed_agents` | → 研究/数据/质检三 Agent 编排 |
| `prompt_templates` | → 半导体研报专家垂直化 prompt |
| `state`/`additional_args` | → 注入当日数据源快照 |

**结论：选一个能读透的内核，比选一个功能全但读不懂的框架，对"做产品"这件事重要得多。** 下一篇我会写多 Agent 编排与质检链路的具体实现。

---
*本系列博客持续更新，项目代码见仓库 README。*
