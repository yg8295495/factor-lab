# factor-lab 开发计划

> ⚠️ **新人必读**：本文件是 factor-lab 的"任务总纲"。新会话或上下文被压缩后，先读此文件 + README.md 恢复上下文。

---

## 全局里程碑

```
Phase 1 ─ 骨架搭建 + 数据通道 ───────────────── 当前阶段
  ├─ 目录结构 & README/PLAN           ✅ Done
  ├─ 数据库导入 & 确认                  ⏳ 等待
  ├─ database.py / models.py            📝 待做
  ├─ 数据采集管道                        📝 待做
  └─ Feature Registry 初版              📝 待做

Phase 2 ─ 因子统计 + 可视化提取
  ├─ statistics/ (percentile/zscore/IC)
  ├─ 从现有项目提取 DualAxisChart → FactorChart
  ├─ FactorSelector + ResearchPanel 前端
  └─ 因子值 + 统计语义叠加显示

Phase 3 ─ 标注系统 + 状态时间轴
  ├─ labeling/ 加载 + labels CSV
  ├─ Replay + 状态时间轴
  ├─ 前端时间轴染色（主升/退潮背景色）
  └─ 手动观察 + 积累结构认知

Phase 4 ─ 结构研究 + qlib 对接
  ├─ Structure Grammar 初版
  ├─ qlib 因子导出 + 回测管道
  ├─ IC 分析面板
  └─ 实验管理系统
```

---

## 当前任务（Phase 1）

### 📌 已完成

- [x] **目录骨架建立** — `backend/` (data/collectors/research/features/statistics/labeling/structures/replay/experiments) + `frontend/` + `data/`
- [x] **`__init__.py` 填充** — 所有 Python 包的初始化文件
- [x] **`config.py`** — 全局配置（DB路径、采集参数、因子默认值）
- [x] **`requirements.txt`** — 依赖清单
- [x] **`README.md`** — 项目总览（架构、目录、数据库、核心概念 + 核心哲学）
- [x] **`PLAN.md`** — 本文件
- [x] **数据库导入 & 确认** — `quant_engine.db` 已复制到 `data/`，6 张表结构完全匹配 spec ✅

### 📌 当前 Phase 1 状态

> **数据库已就位：55个资产，51个有数据（宽基已更新至2026-05-19，申万截止05-15）**
> **4个缺失资产暂缺：990001/930713/931719/000819（东财系统无此代码）**

#### ✅ 已完成

- [x] 数据库一键重建（55个资产，239,651行，全部 2026-05-19）
- [x] 数据源踩坑记录 → `docs/data_source_troubleshooting.md`
- [x] 数据采集清单 → `docs/data_collection_manifest.md`（含知识库/移植指南）
- [x] 完成全部数据源调研 → 已测试可用/不可用/需日频积累 三类清单
- [x] 确认统一采集方案：CSI接口(25指数+PE) + 申万接口(30行业) + Daily+腾讯(创业板)
- [x] database.py + models.py（ORM模型）
- [x] Feature Registry（17个因子，Four Dimensions）

#### 📝 接下来（按优先级）

| 优先级 | 任务 | 文件 |
|--------|------|------|
| **P0** | `database.py + models.py` — ORM 模型 | `backend/data/database.py`, `models.py` |
| **P0** | `Feature Registry` — 按 Four Dimensions 定义14个因子 | `backend/research/features/registry.py` |
| **P1** | `calculator.py` — 因子计算引擎（Tier 1 + Tier 2） | `backend/research/features/calculator.py` |
| **P1** | 申万数据更新 — 用 `index_hist_sw()` 批量更新到最新 | `backend/collectors/sw_daily.py` |
| **P2** | 提取 DualAxisChart → 泛化为 FactorChart | `frontend/FactorChart.tsx` |
| **P3** | 4个缺失资产的补采方案 | 待定 |

#### 因子清单（确认不变）

| 维度 | Tier | 因子 | 来源 |
|------|------|------|------|
| RS | Tier 1 | RS20, RS60, RS_SLOPE | market_daily_data 直接计算 |
| Breadth | Tier 2 | ADV_DECLINE_RATIO, INDUSTRY_DIFFUSION | 横截面聚合 |
| Volatility | Tier 2 | VOLATILITY_20D | 横截面聚合 |
| Style Spread | Tier 2 | SMALL_CAP_SPREAD | 横截面聚合 |
| 辅助上下文 | Tier 1 | MOM20, MOM60, TREND_STR, PE_PERCENTILE, PB_PERCENTILE, DIV_YIELD, PRICE_VOL_DIVERGENCE, BREAKOUT | 计算/聚合 |
| （预留） | Tier 3 | ETF_FLOW_STRENGTH, LEADER_RS, SEALING_RATE (pending) | 需新数据源 |

---

## 重要设计决策（新会话必读）

### 1. 根目录

本项目设计为独立根目录。新开 AI 会话时，将工作目录指向 `factor-lab/`，所有路径以此为基准。

### 2. 数据库

- `data/quant_engine.db` — SQLite，6 张表，schema 已冻结（不改字段不改主键）
- 符号编码：`{asset_type}.{ticker}.{exchange}`（如 `index.000300.CSI`）

### 3. 项目来源

- 前端 DualAxisChart 从现有投研系统项目提取并泛化
- 提取原则：只搬核心渲染能力，不搬仪表盘/ETF/持仓等无关代码

### 4. 外部系统

- 数据源：akshare（主）/ baostock（备），东方财富系需 `trust_env=False` 绕过代理
- 回测：后续对接 qlib / Alphalens

### 5. 认知框架（核心哲学）

- **市场状态 ≠ 趋势** — 趋势只是多维状态空间中的一个维度
- **市场状态是横截面现象** — 单个资产的因子值无法判定市场状态
- **Four Dimensions Focus** — Phase 1 只聚焦 RS / Breadth / Volatility / Style Spread 四个维度

### 6. Feature Explosion 防控（硬规则）

每增加一个 Feature，必须回答：
1. 它测量什么？
2. 它属于哪个状态维度？
3. 它和已有 Feature 区别是什么？（正交性）
4. 它是否真的增加新的信息？（必要性）

> 宁缺毋滥。10 个正交的因子胜过 50 个冗余的因子。

### 7. 工作方式

- 先人工标注市场状态 → 手动 replay 观察 → 积累认知 → 再上自动结构识别
- **不要一开始就上 ML**
- 研究中必须记录观察笔记（`experiments/tracker.py`），否则等于没做

---

## 备注

- 文档 `docs/spec.md` 和 `docs/architecture.md` 的完整版在 AI-DMS 项目仓库中
- 标注文件 `market_labels.csv` 在 `backend/research/labeling/labels/` 下
