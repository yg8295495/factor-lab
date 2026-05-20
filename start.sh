#!/bin/bash
# factor-lab 一键启动脚本（macOS / Linux）
# 同时启动后端 API + 前端开发服务器
# 按 Ctrl+C 同时停止两个服务

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

cleanup() {
    echo ""
    echo -e "${DIM}正在关闭服务...${NC}"
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null
        echo -e "  ${DIM}✕ 后端 (PID $BACKEND_PID)${NC}"
    fi
    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null
        echo -e "  ${DIM}✕ 前端 (PID $FRONTEND_PID)${NC}"
    fi
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
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
sleep 2

# 检查后端是否成功启动
if kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} 后端运行中  PID=$BACKEND_PID"
else
    echo -e "  ${RED}✕${NC} 后端启动失败，请检查依赖"
    exit 1
fi

# ── 启动前端 ──
echo -e "${CYAN}▶ 启动前端...${NC}"
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!
sleep 2

if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} 前端运行中  PID=$FRONTEND_PID"
else
    echo -e "  ${RED}✕${NC} 前端启动失败"
fi

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}后端 API${NC}  http://127.0.0.1:8000"
echo -e "  ${GREEN}前端界面${NC}  http://localhost:5173"
echo ""
echo -e "  ${DIM}按 Ctrl+C 停止所有服务${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 等待任意子进程退出
wait
