#!/bin/bash
# factor-lab 环境一键安装脚本 (macOS / Linux)
# 用法: chmod +x setup.sh && ./setup.sh

set -e

echo "============================================"
echo "  factor-lab 环境安装"
echo "============================================"

# 1. Python 依赖
echo ""
echo "[1/4] 安装 Python 依赖..."
pip3 install akshare pandas numpy scipy sqlalchemy fastapi uvicorn requests 2>&1 | tail -3

# 2. Node.js 前端
echo ""
echo "[2/4] 安装前端依赖..."
cd frontend
npm install 2>&1 | tail -3
cd ..

# 3. 数据库重建
echo ""
echo "[3/4] 重建数据库（从各数据源拉取全部数据）..."
python3 backend/rebuild_db.py

# 4. 因子计算
echo ""
echo "[4/4] 因子计算..."
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.research.features.calculator import run_all
run_all()
"

echo ""
echo "============================================"
echo "  安装完成!"
echo ""
echo "  启动方式:"
echo "  后端:  cd factor-lab && python3 -m uvicorn backend.server:app --port 8000"
echo "  前端:  cd factor-lab/frontend && npm run dev"
echo "  打开:  http://localhost:5173"
echo "============================================"
