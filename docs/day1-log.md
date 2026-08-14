# Day 1 日志：环境搭建 + 第一个 Agent 跑通

## 完成项

- [x] 环境检查：Python 3.10.7（venv）、git 2.35.1
- [x] clone smolagents 源码（master，v1.27.0.dev0）至 `smolagents-src/`（供精读）
- [x] venv 安装：smolagents 1.26.0 + openai 3.0.0 + python-dotenv 1.2.2（锁定见 requirements.txt）
- [x] DeepSeek API 配置写入 `.env`（已被 .gitignore 排除）
- [x] 第一个 CodeAgent demo 端到端跑通（`examples/01_hello_agent.py`）

## 环境关键信息（后续所有命令的前提）

| 项 | 值 |
|---|---|
| venv | `D:\qwen3.6\semiconductor-agent\.venv`（Python 3.10.7） |
| pip 源 | 清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`（10+ MB/s） |
| LLM | DeepSeek `deepseek-chat`，`https://api.deepseek.com`（可直连） |
| 网络 | GitHub/PyPI/DeepSeek API 均可直连；全局 `ALL_PROXY=socks5://127.0.0.1:10808` 会干扰 Python 网络栈 |

## 踩坑记录（重要，面试也能讲）

1. **PowerShell Invoke-WebRequest SSL 报错**：本机 pwsh 7.6.4 的 .NET HttpClient 走 WinINET 系统代理时 TLS 握手失败；`curl.exe`（schannel）正常。→ 网络探测统一用 curl.exe。
2. **pip 卡死**：旧 pip 22.2.2 + 全局代理 → 卡住不动。→ 运行 pip 前清空 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，走直连 + 清华镜像。
3. **smolagents 1.26.0 把 litellm 移出核心依赖**：`LiteLLMModel` 需要 `pip install smolagents[litellm]`。→ 改用内置 `OpenAIModel` + `openai` SDK（更轻，且 DeepSeek 本就是 OpenAI 兼容协议）。
4. **运行 Python 前必须清代理**：httpx2 读到 `ALL_PROXY=socks5://...` 会因缺 socksio 报错。→ 统一执行 `$env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:ALL_PROXY=""; $env:NO_PROXY="*"` 后再跑。
5. **@tool 装饰器要求 Google 风格 docstring**：每个参数必须有 `Args:` 段描述，否则 `DocstringParsingException`。

## Demo 运行结果摘要（examples/01_hello_agent.py）

CodeAgent 三步闭环：写代码调工具 → 自查约束（字数）→ final_answer。
总耗时约 5.8s，输入 2098+4367+6812 tokens。输出为 78 字带数字的行业速览。

## 下一步（Day 2-3）

精读 `smolagents-src/src/smolagents/agents.py`（1813 行）核心：
- `MultiStepAgent.run/_run_stream/step` 主循环
- `write_memory_to_messages` 记忆管理
- `_generate_planning_step` 计划生成
产出：架构笔记（类图 + 流程图）+ 技术博客①初稿
