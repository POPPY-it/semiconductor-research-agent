# W6 报告：前端工作台（React + antd，E2E 验证通过）

## 交付

- 技术栈：React 18 + Vite 5 + TypeScript + Ant Design 5 + react-markdown（GFM 表格支持）
- 三视图：新建任务（选题/日报/周报/深度）→ 会话详情（5 步进度 + SSE 事件动态 + 质检结论面板 + 研报阅读器）→ 会话历史（表格，点击查看）
- 生产模式：`vite build` 产物由 FastAPI 直接托管（同源部署，单服务交付）
- 开发模式：`npm run dev` + Vite 代理 `/api` → 8000

## 后端配套改动

1. SSE 鉴权：EventSource 无法自定义 Header → `require_token` 支持 query 参数 `?token=`
2. CORS 中间件（允许 localhost:5173）
3. 新增 `GET /api/v1/sessions/{id}/report`（返回 report_md 供前端渲染）
4. 静态托管 frontend/dist + Windows MIME 注册（.js 显式 text/javascript）

## 踩坑记录

- **Windows mimetypes 陷阱**：Starlette StaticFiles 靠注册表猜 MIME，`.js` 返回 text/plain → 浏览器"Expected a JavaScript module script"拒绝加载。显式 `mimetypes.add_type` 修复
- **304 缓存陷阱**：改完 MIME 后浏览器 304 复用旧响应头 → 清缓存/换 profile 才生效
- **npm 12 默认拦截 install scripts**（esbuild postinstall）→ 无碍（二进制走 optionalDependencies）

## E2E 验证（真实浏览器，spikes/e2e_frontend.py）

1. 工作台首页渲染 ✅（表单元素齐全）
2. 提交任务 → 会话 #4 状态"生成中" + 5 步进度条 ✅
3. SSE 实时事件流 ✅（research 阶段 → 质检 passed=False 修订 2 轮 → done）
4. 最终"已完成" + 研报正文渲染 ✅
5. 全程截图：spikes/results/e2e_report.png

## 遗留优化（W7/W8）

- antd 全量打包 1.1MB（gzip 359KB）→ 可 manualChunks 拆分
- 会话详情进度条与后端 phase 的细粒度映射（当前 5 步粗粒度）
- 数据源状态面板（M6 计划内，未做）
