# W5 服务层架构（M4 模板 + M5 API）

## 分层

```
HTTP 客户端（前端工作台 W6）
   │  X-API-Token
FastAPI（backend/app/main.py）
   ├─ POST /api/v1/sessions         创建会话 → 入任务队列
   ├─ GET  /api/v1/sessions/{id}    状态/报告
   ├─ GET  /api/v1/sessions/{id}/events   SSE 阶段事件流
   └─ GET  /api/health
TaskQueue（tasks.py）
   ├─ ThreadPoolQueue  开发态（无 Redis）
   └─ RQQueue          生产态（RQ+Redis，requirements-prod.txt）
ReportService（report_service.py，worker 线程内运行）
   └─ ReportPipeline（agent/orchestrator.py）
        └─ 研究 Agent → 质检 Agent → 修订循环（M4 模板：daily/weekly/deep）
EventBus（events.py）→ 阶段事件 → SSE；终态事件积压（晚连接客户端立即可得）
SessionStore（db.py）→ sessions/reports 表
```

## M4 研报模板

| 类型 | 结构 | 篇幅底线 |
|---|---|---|
| daily | 今日要闻/关键数据/一句话点评 | 300 字 |
| weekly | 概述/关键动态/数据透视/展望 | 400 字 |
| deep | 摘要/行业背景/公司分析/数据透视/风险与展望 | 600 字 |

## 关键设计决策

1. **队列双实现**：同一 `TaskQueue` 接口，开发态线程池、生产态 RQ——切换只改一行装配（W2 选型结论落地）
2. **事件积压**：done/error 事件按会话保留，SSE 晚连接也能立即收到终态（测试里验证过）
3. **懒构建**：知识库（模型+索引，约 1 分钟）在第一个任务里构建一次，全局复用；app 启动不被阻塞
4. **鉴权**：X-API-Token（单用户产品足够）；W6 前端从环境变量注入
5. **FastAPI 0.141 踩坑**：裸 Pydantic 参数被当作 query 参数（需显式 `Body(...)`）；函数内定义的模型 pydantic 解析不了（移到模块级）

## 冒烟测试（2026-08-14，3 轮会话实测）

| 会话 | 结果 |
|---|---|
| #1 | error：质检 final_answer 传 dict 导致 JSON 解析崩溃 → 修复 `_extract_json` 支持 dict |
| #2 | done：但质检输出无法解析（模型格式不稳）→ 加固：每轮重试 2 次 + 强制 `final_answer(dict)` |
| #3 | **done ✅**：质检正确解析，给出 3 条真实质疑（TSMC 营收来源、ASML 指引数字、瑞银解读），修订 2 轮后交付并附质检结论 |

验证项：健康检查 ✅ / 鉴权 401 ✅ / 会话创建 ✅ / 任务队列 ✅ / SSE 终态积压回放 ✅ / 报告落盘 ✅

## 生产化观察（下一轮优化）

- 质检输出格式是链路最脆弱环节（LLM 输出不稳）→ 重试 + 强制 dict 已缓解，后续可加"格式校验器"兜底
- 修订循环 token 成本高 → 只回填问题段落（W6 前端后优化）
- 单次日报生成 ~4.5 分钟（含首次知识库构建 ~1 分钟），性能基线已记录
