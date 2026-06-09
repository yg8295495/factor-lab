#!/bin/bash
# factor-lab 本地开发服务器启动
# 同时启动后端 API + 前端图表
# 按 Ctrl+C 同时停止两个服务
#
# 注意：前端目前仍硬编码 index.801001.SW（旧基准），
# 图表数据基于旧基准。待后续更新为 801003。

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python}"
BACKEND_PID=""
FRONTEND_PID=""
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${DIM}正在关闭服务...${NC}"
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo -e "  ${DIM}✕ 后端${NC}"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo -e "  ${DIM}✕ 前端${NC}"
    echo -e "${GREEN}已停止${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  factor-lab  开发服务器${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── 启动后端 ──
echo -e "${CYAN}▶ 启动后端 API...${NC}"
cd "$ROOT_DIR"
$PYTHON -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
sleep 3

if kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} 后端运行中"
else
    echo -e "  ${DIM}✕ 后端启动失败。可设置 PYTHON=python3（macOS）或 PYTHON=/path/to/python（Windows conda）${NC}"
    exit 1
fi

# ── 检查前端依赖 ──
if [ -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo -e "${CYAN}▶ 启动前端...${NC}"
    cd "$ROOT_DIR/frontend"
    npm run dev &
    FRONTEND_PID=$!
    sleep 2
    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} 前端运行中"
    else
        echo -e "  ${DIM}✕ 前端启动失败${NC}"
    fi
else
    echo -e "  ${DIM}⚠ 前端依赖未安装，跳过 (需先执行 cd frontend && npm install)${NC}"
fi

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}后端 API${NC}  http://127.0.0.1:8000"
if [ -n "$FRONTEND_PID" ]; then
    echo -e "  ${GREEN}前端界面${NC}  http://localhost:5173"
    echo -e "  ${DIM}  注意：前端数据基于旧基准（801001），待更新${NC}"
fi
echo ""
echo -e "  ${DIM}按 Ctrl+C 停止所有服务${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

wait
