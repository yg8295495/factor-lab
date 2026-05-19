# factor-lab — 因子研究实验室

> 从原始行情数据到因子发现、统计验证、结构研究的完整流水线。
> 定位：AI-DMS 系统的**因子研究内核**，聚焦 Layer 1→Layer 2→Layer 3→Layer 9。

---

## 项目定位

从现有量化投研系统中提取因子研究能力，独立为新的工程内核。**不包含**仪表盘、ETF分类、持仓监控等前端功能。

### 核心能力

| 能力 | 说明 |
|------|------|
| 数据采集 | 从 akshare/baostock 采集日频行情 + 估值数据 |
| 因子定义 (Feature Registry) | 统一注册、管理、查询所有因子 |
| 因子计算 | Layer 2 特征层，计算 RS、动量、量价、波动率等因子 |
| 因子统计 | percentile、z-score、IC、相关性矩阵 |
| 因子可视化 | 从原项目提取 DualAxisChart，泛化为通用因子走势图 |
| 回测对接 | 导出因子数据到 qlib/Alphalens |
| 市场标注 | 人工标注市场状态，用于结构研究 |
| 状态时间轴 | Replay 历史场景，观察因子行为 |
| 结构研究 | 多因子组合 → 市场结构语法 |

---

## 架构

基于 **Market State Engine v2.0** 的 10 层分层架构，本项目覆盖以下层级：

```
Layer 0  基础设施层 (Infrastructure)    ← 数据库、配置、调度
Layer 1  原始数据层 (Raw Data)          ← 数据采集
Layer 2  特征层 (Feature)               ← 因子计算 ⭐
Layer 3  结构层 (Structure)             ← 因子组合 → 市场结构
Layer 9  前端展示层 (Frontend)          ← 因子可视化
```

### 数据流

```
采集 (akshare/baostock)
    ↓ 写入
market_daily_data (宽表)
    ↓ 读取
Feature Calculator (Layer 2)
    ↓ 写入因子字段
market_daily_data (带因子值)
    ↓ 读取
Statistics (percentile/zscore/IC)
    ↓
Feature Chart (DualAxisChart 泛化)
    ↓
Structure Grammar (Layer 3)
```

---

## 目录结构

```
factor-lab/
├── README.md                           ← 本文件
├── PLAN.md                             ← 当前任务及计划（新人必读）
├── config.py                           ← 全局配置
├── requirements.txt                    ← Python 依赖
├── data/
│   └── quant_engine.db                 ← SQLite 数据库（6张表）
├── backend/
│   ├── data/
│   │   ├── database.py                 ← 数据库连接
│   │   └── models.py                   ← ORM 模型
│   ├── collectors/                     ← Layer 1: 数据采集
│   │   ├── base.py
│   │   ├── index_daily.py              ← 指数日线
│   │   └── valuation.py                ← 估值数据
│   └── research/                       ← 因子研究内核
│       ├── features/                   ← Layer 2: 特征/因子
│       │   ├── registry.py             ← Feature Registry（因子注册表）
│       │   ├── calculator.py           ← 因子计算引擎
│       │   └── loader.py               ← 从DB加载因子值
│       ├── statistics/                 ← 因子统计
│       │   ├── percentile.py           ← 滚动百分位
│       │   ├── zscore.py               ← 标准差偏离
│       │   └── ic.py                   ← 信息系数
│       ├── labeling/                   ← 市场状态标注
│       │   ├── loader.py
│       │   └── labels/
│       │       └── market_labels.csv
│       ├── structures/                 ← Layer 3: 结构
│       │   └── grammar.py
│       ├── replay/                     ← 历史回放
│       │   └── state_timeline.py
│       └── experiments/                ← 实验管理
│           └── tracker.py
└── frontend/                           ← Layer 9: 前端
    ├── FactorChart.tsx                 ← 泛化 DualAxisChart
    ├── ResearchPanel.tsx               ← 因子统计面板
    └── FactorSelector.tsx              ← 因子选择器
```

---

## 数据库

6 张表（schema 已冻结，不改结构不改主键）：

| 表 | 用途 |
|----|------|
| `asset_master` | 资产主表 — 每个跟踪标的的身份证 |
| `market_daily_data` | 核心宽表 — OHLCV + 估值 + 因子 + 风格 + AI |
| `market_state_history` | 市场状态判定记录 |
| `theme_tracking` | 市场主题跟踪 |
| `ai_analysis_reports` | AI 分析报告 |
| `ai_memory` | AI 长期经验库 |

详见 `docs/spec.md`（数据库结构规范）。

### 符号编码规范

```
格式: {asset_type}.{ticker}.{exchange}
示例:
  index.000300.CSI  → 沪深300
  stock.000001.SZ   → 平安银行
  sector.801780.SW  → 申万银行
```

---

## 核心哲学

> 这个项目**不是**在开发功能，而是在**研究市场结构**。下面几个认知决定了所有的设计决策。

### 1. 市场状态 ≠ 趋势

趋势（涨/跌）只是市场状态的一个维度。真实的"市场结构"是多维状态空间：

```
主升 = 趋势↑ + 广度↑ + 量能↑ + 风险偏好↑
抱团 = 核心资产↑ + 广度↓             (不是趋势问题，是结构问题)
混沌 = 指数横盘 + 波动率↓ + 风格无持续性  (甚至可能不跌)
退潮 = 趋势↓ + 广度↓ + 龙头崩塌
```

只看 RS/MOM 永远无法区分"主升"和"抱团"——两者都涨，但内部结构完全不同。

### 2. 市场状态是横截面现象

- 广度 = 全市场横截面统计
- 跌停潮 = 市场整体风险偏好坍塌
- 风格切换 = 不同资产群体之间的相对强弱变化

**单个资产的因子值无法判定市场状态**，Layer 3 天然依赖横截面聚合特征。

### 3. Four Dimensions Focus

Phase 1 只聚焦四个维度的因子，**不多不少**：

| 维度 | 核心问题 | 对应市场状态 |
|------|---------|------------|
| RS（相对强度） | 趋势方向与强度 | 全部四种状态 |
| Breadth（广度） | 趋势是否扩散 | 区分主升 vs 抱团 |
| Volatility（波动率） | 市场是否在蓄势/释放 | 判定混沌 |
| Style Spread（风格） | 资金偏好大小盘 | 区分抱团 vs 主升 |

### 4. Feature Explosion 防控

每增加一个 Feature，必须回答：

1. **它测量什么？**（定义）
2. **它属于哪个状态维度？**（归属）
3. **它和已有 Feature 区别是什么？**（正交性）
4. **它是否真的增加新的信息？**（必要性）

> 宁缺毋滥。10 个正交的因子胜过 50 个冗余的因子。

---

## 核心概念

### Feature Registry (因子注册表)

每个因子在 `registry.py` 中有统一定义。按 Four Dimensions 组织：

```python
FEATURE_REGISTRY = {
    # ── RS 维度 ──
    "RS20": {
        "name_cn": "20日相对强度",
        "dimension": "rs",          # Four Dimensions 归属
        "description": "标的相对于基准（中证全指）的20日滚动相对强弱",
        "compute_fn": "calc_rs",
        "params": {"lookback": 20},
        "dependencies": ["close"],
        "storage": "rs20_cross",
        "display": {"color": "#ff6600", "chart": "line", "y_axis": "right"},
    },
    # ── Breadth 维度 ──
    "ADV_DECLINE_RATIO": {
        "dimension": "breadth",
        # ...
    },
    # ...
}
```

### 统计语义

因子原始值本身无意义，通过以下统计量赋予解释力：

- **Percentile** — 过去 250 日滚动排名百分位
- **Z-score** — 偏离历史均值的标准差倍数
- **IC** — 因子值与未来收益的信息系数

---

## 开始使用

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 确认数据库
# 将 quant_engine.db 放入 data/ 目录

# 3. 启动数据采集
python -m backend.collectors.index_daily

# 4. 计算因子
python -m backend.research.features.calculator

# 5. 前端（后续）
cd frontend && npm install && npm run dev
```

---

## 关键原则

1. **schema 已冻结** — 不删不改现有字段，新因子只加字段
2. **层级已冻结** — 新增内容只往对应层填，不新增层级
3. **符号编码统一** — 全系统使用 `{type}.{ticker}.{exchange}` 格式
4. **因子是一等公民** — 所有因子通过 Registry 注册，不散落各处
