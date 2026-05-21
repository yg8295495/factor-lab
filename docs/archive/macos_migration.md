# macOS 迁移指南

> 将 factor-lab 从 Windows 迁移到 macOS 的完整步骤。

---

## 1. 前置检查

```bash
# 确认 Homebrew 已安装
brew --version

# 安装 Python（如未安装）
brew install python@3.12

# 确认 Node.js 已安装
node --version   # ≥ 18
npm --version
```

---

## 2. Python 依赖

```bash
# ⚠️ 必须安装以下所有包，缺一不可
pip3 install akshare pandas numpy scipy sqlalchemy \
            fastapi uvicorn requests
```

**关键依赖说明：**

| 包 | 用途 | 是否必需 |
|-----|------|:-------:|
| `fastapi` | 后端 API 框架 | ✅ 必需 |
| `uvicorn` | ASGI 服务器（启动 `backend/server.py`） | ✅ 必需 |
| `akshare` | 数据采集（指数/申万/腾讯源） | ✅ 必需 |
| `pandas` | 因子计算引擎的数据处理 | ✅ 必需 |
| `numpy` | 数值计算（RS/斜率/百分位） | ✅ 必需 |
| `sqlalchemy` | ORM（可选，当前用 sqlite3 直连） | ✅ 推荐 |
| `requests` | 东方财富 API 补采 | ✅ 必需 |

---

## 3. 数据库

数据库文件 `data/quant_engine.db` 已包含全部迁移数据，直接使用：

```bash
# 校验数据库完整性
python3 -c "
import sqlite3
conn = sqlite3.connect('data/quant_engine.db')
cur = conn.execute('SELECT COUNT(*) FROM asset_master')
print(f'资产: {cur.fetchone()[0]}')
cur = conn.execute('SELECT COUNT(*) FROM market_daily_data')
print(f'数据行: {cur.fetchone()[0]}')
cur = conn.execute('SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data')
dr = cur.fetchone()
print(f'日期范围: {dr[0]} ~ {dr[1]}')
conn.close()
"
```

预期输出：
```
资产: 55
数据行: 239651
日期范围: 1990-01-01 ~ 2026-05-19
```

如需重新采集数据（覆盖已有数据）：

```bash
# 方式 A：从东方财富 API 批量补采（推荐）
python3 backend/refetch.py

# 方式 B：从 akshare 申万接口更新
python3 backend/collectors/sw_daily.py
```

---

## 4. 前端依赖

```bash
cd frontend
npm install
cd ..
```

---

## 5. 一键启动（开发模式）

```bash
chmod +x start.sh
./start.sh
```

脚本会自动启动：
- 后端 API → `http://127.0.0.1:8000`
- 前端界面 → `http://localhost:5173`

按 `Ctrl+C` 同时停止两个服务。

---

## 6. 分步启动（手动模式）

```bash
# 终端 1：后端
cd factor-lab
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload

# 终端 2：前端
cd factor-lab/frontend
npm run dev
```

浏览器打开 `http://localhost:5173`

---

## 7. 常见问题

### Q: `pip3 install` 报权限错误

使用 `--user` 或在虚拟环境中安装：

```bash
pip3 install --user akshare pandas ... fastapi uvicorn requests
```

### Q: 后端启动报 `ModuleNotFoundError: No module named 'backend'`

确保在 `factor-lab/` 根目录执行命令：

```bash
cd /path/to/factor-lab
python3 -m uvicorn backend.server:app --port 8000
```

### Q: 前端启动报 `port 5173` 被占用

```bash
# 修改 vite 端口
cd frontend
npx vite --port 5174
```

### Q: 东方财富 API 在 macOS 上无法连接

如果遇到 SSL 或代理问题，使用腾讯源接口替代：

```python
import akshare as ak
df = ak.stock_zh_index_daily_tx(symbol="sh000300")
```
