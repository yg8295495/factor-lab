# Git 远程 & 环境配置

## 前置条件
在 Gitee/GitHub 上创建同名仓库 `factor-lab`（**不要勾选** 初始化 README）。

## 推送命令

### 方案A：Gitee 主力 + GitHub 备份

```bash
cd factor-lab
git remote add origin https://gitee.com/sunshine85/factor-lab.git
git remote set-url --add origin https://github.com/yg8295495/factor-lab.git
git push -u origin master
```

### 方案B：拆成两个独立 remote（更清楚）

```bash
cd factor-lab
git remote add origin https://gitee.com/sunshine85/factor-lab.git
git remote add github https://github.com/yg8295495/factor-lab.git
git push origin master
git push -u github master
```

## macOS/Linux 上首次安装

```bash
# 克隆
git clone https://gitee.com/sunshine85/factor-lab.git
cd factor-lab

# 一键安装（Python依赖 + 前端依赖 + 数据库重建 + 因子计算）
chmod +x setup.sh && ./setup.sh

# 或分步安装：
# 1. 装 Python 包
pip3 install akshare pandas numpy scipy sqlalchemy fastapi uvicorn requests

# 2. 装前端
cd frontend && npm install && cd ..

# 3. 重建数据库（从 CSI/申万/腾讯 拉取全部数据）
python3 backend/rebuild_db.py

# 4. 因子计算
python3 -c "import sys; sys.path.insert(0,'.'); from backend.research.features.calculator import run_all; run_all()"
```

## Windows 上首次安装

```powershell
# 克隆
git clone https://gitee.com/sunshine85/factor-lab.git
cd factor-lab

# 一键安装
powershell -ExecutionPolicy Bypass -File setup.ps1

# 或分步安装：
pip install akshare pandas numpy scipy sqlalchemy fastapi uvicorn requests
cd frontend && npm install && cd ..
python backend/rebuild_db.py
python -c "import sys; sys.path.insert(0,'.'); from backend.research.features.calculator import run_all; run_all()"
```

## 日常启动

```bash
# 终端1: 后端数据API
cd factor-lab && python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000

# 终端2: 前端图表
cd factor-lab/frontend && npm run dev

# 浏览器打开 http://localhost:5173
```
