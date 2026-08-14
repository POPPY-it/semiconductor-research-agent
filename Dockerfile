# ---- 前端构建 ----
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json ./
RUN npm install --registry=https://registry.npmmirror.com --no-fund --no-audit
COPY frontend ./
RUN npm run build

# ---- 运行时 ----
FROM python:3.10-slim
WORKDIR /app

# 清华镜像加速；生产依赖含 rq/redis（规模化路径，默认 APP_QUEUE=thread 不启用）
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY backend ./backend
COPY agent ./agent
COPY data ./data
COPY scripts ./scripts
COPY reports ./reports
COPY --from=frontend-build /build/dist ./frontend/dist

# 模型首次启动时经 hf-mirror 下载（volume 挂载 data/ 可持久化）
ENV HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_DISABLE_XET=1 \
    PYTHONUTF8=1

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
