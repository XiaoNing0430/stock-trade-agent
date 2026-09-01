# 镜像源可覆盖（受限网络可用国内镜像源构建）：
#   docker build --build-arg REGISTRY=hub.rat.dev/library -t atlas-stock-desk .
ARG REGISTRY=docker.io/library

# Stage 1: 前端构建
FROM ${REGISTRY}/node:22-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
# 根级构建配置（vue-tsc / vite 需要 tsconfig.json 与 vite.config.ts 在项目根）
COPY tsconfig.json vite.config.ts vitest.config.ts ./
COPY frontend/ ./frontend/
RUN npm ci
RUN npm run build

# Stage 2: 后端运行
FROM ${REGISTRY}/python:3.13-slim
WORKDIR /app
# 安装系统依赖（psycopg 二进制需要）
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev && rm -rf /var/lib/apt/lists/*
# 复制运行依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# 复制后端源码 + 前端构建产物
COPY backend/ ./backend/
COPY server.py ./
COPY --from=frontend-build /app/frontend/dist/ ./frontend/dist/
# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4173/api/health')"
# 启动（容器内绑定 0.0.0.0 使 -p 端口映射与 compose 端口映射生效）
EXPOSE 4173
ENV HOST=0.0.0.0 PORT=4173
CMD ["python", "server.py"]
