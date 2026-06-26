# XAU 策略全栈控制系统 — Docker 部署
# 使用多阶段构建：Node 前端 + Python 后端

# ── 阶段 1: 构建前端 ──
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm ci --silent
COPY web/frontend/ ./
RUN npm run build

# ── 阶段 2: 构建后端 ──
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制后端
COPY web/backend/ ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# 复制前端产物
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 创建配置和日志目录
RUN mkdir -p /app/configs /app/diagnosis_output

# 环境变量
ENV CONFIG_DIR=/app/configs
ENV DIAGNOSIS_DIR=/app/diagnosis_output
ENV JWT_SECRET=change-me-in-production
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 8000

# 启动后端
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
