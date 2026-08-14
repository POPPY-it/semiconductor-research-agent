# W8 企业级加固报告（面试官视角整改）

> 对照"面试官五追问"逐条修复。全部有测试覆盖（tests/test_enterprise.py，32 个测试全绿）。

## 1. 🔐 安全（追问 3：SSE token 泄露）

| 问题 | 修复 |
|---|---|
| SSE token 走 query（进日志/历史） | `POST /api/v1/auth/login` 用 X-API-Token 换 **HttpOnly Cookie**（HMAC 签名 + 过期时间），SSE 同源自动携带，URL 零敏感信息 |
| 无速率限制 | 中间件滑动窗口限流：建任务 5/min、登录 10/min、查询 120/min（429 响应） |
| 无审计 | X-Request-ID 注入 + 结构化访问日志（method/path/status/耗时） |
| 弱 token | `.env.example` 模板 + 文档要求强随机串 |

代码：`backend/app/auth.py`（HMAC Cookie）、`middleware.py`（日志/限流/指标）。

## 2. 📋 质检交付策略（追问 2：质检不过怎么办）

可配置 `QA_POLICY`：
- `caveat`（默认）：未通过 → 正文顶部注入"⚠️ 质检未通过"警示横幅 + 问题清单后交付
- `reject`：未通过 → 拒绝交付正文（verdict 保留，用户可见为何未交付）

代码：`report_service._apply_qa_policy`，前端质检面板同步展示。

## 3. ♻️ 任务可靠性（追问 4：进程挂了任务丢吗）

- **启动恢复**：`SessionStore.recover_stale()` —— 进程重启时把中断在 queued/running 的会话标记为 error（应用启动时自动执行）
- **失败重试**：`POST /api/v1/sessions/{id}/retry` + 前端"重试"按钮
- **并发安全**：修复了真实并发 bug——SQLite 跨线程事务冲突（限流测试暴露）→ 锁 + 自动提交模式
- 队列持久化（跨进程）：RQ+Redis 路径代码就绪（`APP_QUEUE=rq`），单机线程池为默认（见 deploy.md 架构决策）

## 4. 💰 LLM 治理（追问 5：成本与可用性）

- **Token 预算熔断**：`BudgetedModel` 包装模型，累计估算字符超 `TOKEN_BUDGET_CHARS`（默认 120 万）即抛 `BudgetExceededError` 终止任务（曾实测单轮 52 万 token）
- **备用模型**：主模型连接/超时/限流类错误自动切换 `FALLBACK_LLM_*` 一次；结果记录 model_used
- 预算用量、模型标识进入 SSE 阶段事件与结果

代码：`agent/llm.py`、`orchestrator.py`（guarded_run）。

## 5. 📊 可观测性

- `GET /api/metrics`：Prometheus 文本格式（http_requests/4xx/5xx/429、report_tasks_total{status}、report_task_duration_ms_sum）
- `GET /api/health` 深度检查：版本/鉴权状态/队列深度/文章数/QA 策略/LLM 配置
- CI 三 job：pytest（32 tests）+ 前端构建 + Docker 镜像构建

## 冒烟验证（真实任务）

- Cookie 登录 → Cookie 建会话 → 401 拦截 → 完整日报生成 done（3.5 分钟）→ 指标上报 ✅
- 过程中修复：BudgetedModel 未兼容 ChatMessage 对象（smolagents 传对象非 dict）

## 遗留（诚实清单，按优先级）

1. 中文新闻正文覆盖率低（反爬）→ 引入第三方解析服务或更多 RSS 源
2. Docker 配置未在本地实测（本机无 Docker）→ CI docker build 在推送后验证
3. CodeAgent 本地代码执行 → 生产建议 Docker executor（模块白名单已内置，需文档化）
4. 多进程横向扩展（RQ worker + Redis Pub/Sub 事件总线）→ 预留接口，负载需要时启用
