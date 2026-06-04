# factor-lab — 因子研究实验室：现状报告

> 生成日期：2026-06-05
> 用途：给任何新 AI 会话快速理解项目当前状态、已完成工作和待办事项。

---

## 一、项目定位

`factor-lab` 是轻量因子研究子模块，属于 AI-DMS / 市场状态机体系。
目标：通过因子组合识别**市场状态**和**主线行业**，为投资决策提供结构证据。

### 核心原则

- 所有回测使用**滚动评估**，静态命中率不作为证据
- 每次实验改变**一个主要变量**，否则归因不清
- 使用已有因子池，不随意引入外部因子平台
- 股票数据主用于聚合（涨跌家数/行业宽度/份额），不做个股级因子

---

## 二、数据层 — 6 项准备工作全部完成

| # | 任务 | 状态 | 关键指标 | 脚本 |
|:-:|:-----|:----:|:---------|:-----|
| 1 | stock-to-sector 映射 | ✅ | 5148/5478 股 (94%)，31 行业全覆盖 | `build_sector_mapping.py` |
| 2 | 个股 pct_chg_raw / 涨跌停 | ✅ | 14,980,924 行 (99.9%)，涨停 24.9 万行 | `compute_stock_fields.py` |
| 3 | 市场情绪 → index.000985.SH | ✅ | 5189/5191 行 (2004-12 ~ 2026-05) | `aggregate_market_emotion.py` |
| 4 | 行业内部宽度 → 30 行业 | ✅ | above_ma20/ma60/new_high_20d 全 30 行业 | `aggregate_sector_breadth.py` |
| 5 | amount_ratio → sector + 基准 | ✅ | sector 99.6%，benchmark 99.6% | `compute_amount_ratio.py` |
| 6 | Schema 清理 | ✅ | 回滚 4 个未授权 ALTER TABLE 列 | — |

**数据覆盖：** 5191 个交易日（1990-01 ~ 2026-05），30 个申万一级行业指数，约 5200 只个股日线。

---

## 三、实验进度

### EXP-001 — 静态行业强度评分 ❌ 废弃

| 项目 | 内容 |
|:-----|:------|
| 方法 | 单点 RS 排名 + 胜率 + 量比静态评分 |
| 结论 | Top-3 命中率 8.3%，偏向防御板块，失败 |
| 替代 | EXP-002 W1/W2/W3 行为评分 |

### EXP-002 — W1/W2/W3 行业行为评分 ✅ 当前基线

| 项目 | 内容 |
|:-----|:------|
| 方法 | 滚动窗口行业行为评分（W1 放量震荡/W2 缩量洗盘/W3 初升试探） |
| 实现 | `sector_behavior_score.py` — `continuous_rolling()` |
| 参数 | 再平衡 20 日，持有 20 日，选 TOP 3 等权，基准 `index.000985.SH` |
| 结果 | 130 次再平衡，超额 **+60.5%**，牛市窗口胜率 53.1% |
| 弱点 | 熊市/退潮阶段防守能力不足，最大回撤 **-53%** |
| 记录 | `docs/research/behavior_scoring_v1.md` |

### EXP-003 — 市场状态感知行业行为评分 ⏳ 初跑完成

| 项目 | 内容 |
|:-----|:------|
| 方法 | EXP-002 W1/W2/W3 + EXP-004 市场状态过滤 + 行业宽度/额比确认 |
| 实现 | `exp003_state_aware_evaluator.py`（只读，不写 DB） |
| 三组对照 | **A:** EXP-002 基线 / **B:** 状态过滤 / **C:** 状态 + 行业确认 |

**状态动作规则：**

| 状态 | 动作 |
|:-----|:------|
| `MAIN_UP_CONFIRMED` | TOP 3 等权满仓 |
| `REBOUND` | 观察不参与（主口径）；sensitivity 版 TOP 1 或半权重 |
| `CROWDING` | TOP 1 等权轻仓 |
| `CHAOS` | 不参与 |
| `RETREAT` | 不参与 |

**初跑结果（253 个再平衡窗口）：**

| Variant | 策略收益 | 基准收益 | 超额 | 最大回撤 |
|:--------|:-------:|:--------:|:----:|:--------:|
| A: EXP-002 基线 | 787.2% | 644.8% | **+142.5%** | -53.0% |
| B: 状态过滤 | 253.6% | 644.8% | **-391.1%** | **-32.3%** |
| C: 状态 + 行业确认 | 58.0% | 644.8% | -586.8% | -56.9% |

**关键发现：**
- 状态过滤确实降低了回撤（-53% → -32%）
- 但 EXP-004 v0.5 过于保守，仅 6.3% 窗口被标为 MAIN_UP_CONFIRMED，58.5% 为 CHAOS（空仓）
- 行业确认 bonus 在当前参数下帮倒忙
- **结论：状态过滤安全过头，需要放宽或改变框架**

**后续方向（待决策）：**
- 放宽 EXP-004 状态规则（v0.5 太保守）
- 或改变 Variant B/C 的动作规则（CHAOS 中也有条件参与）
- 或修改 sector bonus 参数
- 设计文档：`docs/research/experiments/EXP-003-breadth-enhanced-behavior-score.md`

### EXP-004 — 市场状态识别 v0 ✅ 定型收口

| 项目 | 内容 |
|:-----|:------|
| 方法 | 5 维度打分（trend/breadth/emotion/volume/risk）→ 4+1 状态 |
| 实现 | `market_state_recognition.py`，支持 `--experiment v0` ~ `v0.5` |
| 状态 | `MAIN_UP_CONFIRMED` / `REBOUND` / `CROWDING` / `RETREAT` / `CHAOS` |
| 迭代 | 6 轮（v0→v0.5），最终版本 v0.5 |
| 验收 | bear_false_main_up=3.0%，bull_main_up_recall=10.5% |
| 诊断 | 运行 `false_main_up_diagnostics.py`，确认市场状态层已达规则边界 |
| 结论 | 剩余模糊窗口交给行业层（EXP-003）处理 |

**最终规则（v0.5）：**
```
MAIN_UP_CONFIRMED if:
  trend_score = +1
  AND close > MA120
  AND participation_ok                 # breadth=+1 OR (adv≥0.52 AND diff≥50 AND diff_chg≥0)
  AND risk_score >= 0
  AND emotion_score >= 0
  AND positive_count >= 3
  AND drawdown_120d > -10%

RETREAT if:
  trend_score = -1
  AND risk_score = -1
  AND (breadth_score = -1 OR emotion_score = -1)
  或兜底: trend+breadth+emotion+risk <= -3
```

---

## 四、当前问题与下一步

### 核心卡点

EXP-003 初跑显示：**状态过滤虽然降低了回撤，但安全过头**，因为 MAIN_UP_CONFIRMED 仅占 6.3% 窗口。需要决策：

1. 放宽 EXP-004 的 MAIN_UP_CONFIRMED 条件（牺牲精度换召回）？
2. 或改变 EXP-003 动作规则——让 CHAOS 中也有条件参与（比如只选 top 1）？
3. 或设计两阶段流程：先状态过滤，在非 RETREAT 状态下用行业层单独评分？

### 短期待办

- [ ] 分析 EXP-003 初跑结果，决定下一步方向
- [ ] 相应调整 EXP-003 规则后重跑
- [ ] 完成后合成"主线行业识别 v0"

### 长期研究储备

| 方向 | 参考文档 | 说明 |
|:-----|:---------|:-----|
| ETF 净申赎 | `docs/research/etf_flow_as_signal_v1.md` | 真实资金流向信号，需要 tushare 8000 积分 |
| 行情数据源 | `docs/agent/00_data.md` | 当前用 TickFlow + akshare |

---

## 五、项目地图

### 关键脚本

```
backend/collectors/
├── build_sector_mapping.py         # Phase 1: 行业映射
├── compute_stock_fields.py         # Phase 2: 涨跌幅/涨跌停
├── aggregate_market_emotion.py     # Phase 3: 市场情绪
├── aggregate_sector_breadth.py     # Phase 4: 行业宽度
├── compute_amount_ratio.py         # Phase 5: 额比
├── tickflow_collector.py           # 个股日线采集
└── sw_daily.py                     # 行业日线采集

backend/research/analysis/
├── sector_behavior_score.py        # EXP-002 行业行为评分
├── market_state_recognition.py     # EXP-004 市场状态识别
├── exp003_state_aware_evaluator.py # EXP-003 评估器
├── false_main_up_diagnostics.py    # EXP-004 诊断工具
└── output/                         # JSON 结果
    ├── continuous_rolling_results.json     # EXP-002 基线
    ├── market_state_daily_v05.json         # EXP-004 v0.5
    ├── market_state_false_main_up_diagnostics.json
    └── exp003_state_aware_behavior_score.json  # EXP-003 初跑
```

### 关键文档

```
PLAN.md                             # 当前 sprint
AGENT.md                            # 新会话启动读我
STATUS.md                           # ← 本文档

docs/research/
├── INDEX.md                        # 实验索引
├── MEMORY.md                       # 完成记录
├── LESSONS.md                      # 已验证结论
├── factor_scope_v1.md              # 因子分工决策
├── data_readiness_v1.md            # 数据就绪审计
├── data_runtime_spec_v1.md         # 运行规范
├── phase_sector_leadership_v1.md   # 13个市场阶段研究
├── etf_flow_as_signal_v1.md        # ETF方向研究
└── experiments/
    ├── TEMPLATE.md                 # 实验模板
    ├── EXP-003-breadth-enhanced-behavior-score.md
    └── EXP-004-market-state-recognition-v0.md

docs/agent/
├── 00_data.md                      # 数据字段/来源/复权口径
├── 01_factors.md                   # 因子定义
├── 02_experiments.md               # 实验工作流
└── 03_strategy.md                  # 策略讨论
```

### 数据库

- 位置：`data/quant_engine.db`（SQLite）
- 核心表：`asset_master`、`market_daily_data`（57 列宽表）
- Schema 文档：`docs/database_schema.md`
