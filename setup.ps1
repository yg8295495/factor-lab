# factor-lab 环境一键安装脚本 (Windows PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File setup.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  factor-lab 环境安装" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# 1. Python 依赖
Write-Host "`n[1/4] 安装 Python 依赖..." -ForegroundColor Yellow
pip install akshare pandas numpy scipy sqlalchemy fastapi uvicorn requests 2>&1 | Select-Object -Last 3

# 2. Node.js 前端
Write-Host "`n[2/4] 安装前端依赖..." -ForegroundColor Yellow
Set-Location frontend
npm install 2>&1 | Select-Object -Last 3
Set-Location ..

# 3. 数据库重建
Write-Host "`n[3/4] 重建数据库..." -ForegroundColor Yellow
python backend/rebuild_db.py

# 4. 因子计算
Write-Host "`n[4/4] 因子计算..." -ForegroundColor Yellow
python -c "
import sys; sys.path.insert(0, '.')
from backend.research.features.calculator import run_all
run_all()
"

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "`n  启动方式:" -ForegroundColor White
Write-Host "  后端:  python -m uvicorn backend.server:app --port 8000" -ForegroundColor White
Write-Host "  前端:  cd frontend && npm run dev" -ForegroundColor White
Write-Host "  打开:  http://localhost:5173" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Green
