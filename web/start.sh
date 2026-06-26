#!/usr/bin/env bash
# XAU 策略全栈控制系统启动脚本
# 启动后端 FastAPI + 前端 Vite 开发服务器

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

echo "=== XAU 策略控制系统启动 ==="

# ── 检查 Python 环境 ──
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

# ── 安装后端依赖 ──
echo "[1/4] 安装后端依赖..."
cd "$BACKEND_DIR"
pip install -r requirements.txt -q

# ── 安装前端依赖 ──
echo "[2/4] 安装前端依赖..."
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
    npm install --silent
fi

# ── 创建配置目录 ──
echo "[3/4] 创建配置和日志目录..."
mkdir -p "$FRONTEND_DIR/../configs"
mkdir -p "$FRONTEND_DIR/../diagnosis_output"

# ── 启动服务 ──
echo "[4/4] 启动服务..."
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"

# 启动后端（后台运行）
cd "$BACKEND_DIR"
CONFIG_DIR="$FRONTEND_DIR/../configs" \
DIAGNOSIS_DIR="$FRONTEND_DIR/../diagnosis_output" \
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 启动前端（前台运行）
cd "$FRONTEND_DIR"
npx vite --host 0.0.0.0 --port 5173

# 停止后端
kill $BACKEND_PID 2>/dev/null
echo "服务已停止。"
