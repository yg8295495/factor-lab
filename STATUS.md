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

### EXP-003 — 市场状态感知行业行为评分 ✅ 验证完成

| 项目 | 内容 |
|:-----|:------|
| 方法 | EXP-002 W1/W2/W3 + EXP-004 市场状态过滤 + 行业宽度/额比确认 |
| 实现 | `exp003_state_aware_evaluator.py`（只读，不写 DB） |
| 输出 | `output/exp003_state_aware_behavior_score.json` + `output/exp003_chaos_top1_diagnostics.json` |
| 对照 | **A:** EXP-002 基线 / **B:** 状态过滤 / **C:** 状态+行业确认 / **D:** 状态=仓位 |

**最终对照结果（253 个再平衡窗口）：**

| Variant | 策略收益 | 基准收益 | 超额 | 最大回撤 |
|:--------|:-------:|:--------:|:----:|:--------:|
| A: EXP-002 基线 | 787.2% | 644.8% | **+142.5%** | -53.0% |
| B: 状态过滤 | 253.6% | 644.8% | -391.1% | -32.3% |
| C: 状态+行业确认 | 58.0% | 644.8% | -586.8% | -56.9% |
| **🟢 D: 状态=仓位 (≥6)** | **985.3%** | 644.8% | **+340.6%** | **-45.9%** |
| D_sens_ge7 | 421.6% | 644.8% | -223.2% | -34.4% |
| D_sens_ge8 | 189.9% | 644.8% | -454.9% | -32.3% |

**Variant D 动作规则（当前基线）：**

| 状态 | 动作 |
|:-----|:------|
| `MAIN_UP_CONFIRMED` | TOP 3 等权 |
| `REBOUND` | TOP 2 等权 |
| `CHAOS` | TOP 1 等权（要求 score ≥ 6） |
| `CROWDING` | TOP 1 等权 |
| `RETREAT` | 空仓 |

**关键发现：**
- D(≥6) 同时实现收益更高（+985% vs +787%）、回撤更低（-46% vs -53%），双重改善
- CHAOS 收益占比 46.4%，MAIN_UP 仅 15.2% — 证明价值在于混乱市场找局部主线，而非放大牛市
- 各周期均有正超额收益，不存在单一时期集中
- 记录：`docs/research/experiments/EXP-003-breadth-enhanced-behavior-score.md`

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

## 四、当前状态与下一步

### 当前研究基线

**EXP-003 Variant D (CHAOS ≥ 6)** — 已验证为「主线行业识别 v0」的基础框架。

```
MAIN_UP_CONFIRMED → TOP 3
REBOUND           → TOP 2
CHAOS             → TOP 1 (score ≥ 6)
CROWDING          → TOP 1
RETREAT           → 空仓
```

基线指标（253 窗口，2005~2026）：
- 总收益 **+985.3%**，超额 **+340.6%**，最大回撤 **-45.9%**
- CHAOS 贡献 46.4% 收益（94 次交易，胜率 54.3%）
- 各五年周期超额收益均为正，不存在单时期集中

### 主线捕获分析

衡量策略对市场真正主线（未来20天最佳行业）的识别能力：

| 指标 | D(≥6) | A(基线) | 随机水平 | 解读 |
|:-----|:----:|:-------:|:-------:|:-----|
| Top1 命中率 | 3.5% | 2.8% | 3.3%（1/30） | ❌ 噪声过高，已废弃 |
| Top3 覆盖率 | 16.3% | **31.0%** | 10.0%（3/30） | A显著高于随机（3×），**方向筛选有效** |
| **平均捕获率** | **21.6%** | 16.2% | — | 吃到 Leader 涨幅的比例，D > A，但仍偏低 |

**当前结论（分两层）：**
- ✅ **已验证：方向筛选有效** — W1/W2/W3 评分能显著提高选中未来强势行业的概率（3×随机）
- ⚠️ **待验证：主线识别能力强弱** — 捕获率仅 21.6%，收益优势主要来自风控（减少非主线窗口亏损），而非冠军预测的精确性。不能简单将「赚钱 = 识别主线成功」

**自然引出的问题：** 捕获率偏低暗示 20 天持有周期可能与信号生命周期不匹配。W1/W2/W3 信号出现后，市场需要多久兑现？

### EXP-006 — 信号生命周期分析 ✅ 完成

| 项目 | 内容 |
|:-----|:------|
| 方法 | TOP1/TOP3 纯信号（无状态过滤），5/10/20/40/60D 四维曲线 + Delta 分层 |
| 核心发现 | 20D 捕获率峰值（TOP1=20.4%, TOP3=17.3%），信号呈正偏态（VC模式） |
| 最高价值发现 | **Delta(W2-W3) 是生命周期位置因子，非强弱因子** — Wash>>Launch 呈先弱后强的生命周期曲线 |
| 详细结果 | `output/exp006_signal_lifecycle.json` / `exp006a/b/c_*.json` |

**Delta 生命周期曲线（Wash >> Launch = W2-W3 ≥ 2）：**

| Horizon | Return | Excess | WinRate | 阶段 |
|:-------:|:-----:|:------:|:-------:|:----|
| 5D | -0.8% | +0.3% | 53.3% | 洗盘延续 |
| 10D | -1.2% | +1.1% | 46.7% | 最后下跌 |
| **20D** | **+2.9%** | **+2.7%** | **66.7%** | 🟢 开始兑现 |
| **40D** | **+4.9%** | +1.7% | 60.0% | 🟢 主升 |
| 60D | +4.5% | +2.3% | **80.0%** | 延续 |

**认知升级：** W1/W2/W3 包含两层信息 — **Total Score 回答「值不值得关注」**，**Delta(W2-W3) 回答「处于什么阶段」**。CHAOS × Wash>>Launch 是最强组合（N=7, WinRate=85.7%, Excess=+5.3%）。

### EXP-007 — State × Lifecycle 融合 ❌ 行业层收口

| 项目 | 内容 |
|:-----|:------|
| 方法 | Variant E: 保留 D 的规则，在 CHAOS 中偏好 Delta ≥ 0，CROWDING 中避开 Delta ≥ 2 |
| 结果 | E_state_lifecycle(377.8%) / E_sens_hard(633.1%) **均远逊于 D(985.3%)** |
| 结论 | **Delta 是解释性因子，不是交易性因子**。可用于事后归因，不可用于事前筛选 |
| 记录 | `docs/research/experiments/EXP-007-state-lifecycle-fusion.md` |

**行业行为评分层（W1/W2/W3/Delta）研究收口。** 从 EXP-002 到 EXP-007 已构成完整研究闭环：发现→验证→生命周期→归因→融合测试。成果冻结为 **Sector Leadership v1**。

### 下一步方向 — 重新聚焦上层架构

| 层级 | 当前状态 | 下一步问题 |
|:----|:--------|:-----------|
| 🟢 **行业行为层** | **✅ 完成** | W1/W2/W3/Delta 已收口为 Sector Leadership v1 |
| 🟡 **市场状态层** | ✅ v0 已定型 | EXP-004 v0.5 已定型（bear false MAIN_UP=3%），是否改进交由上层决定 |
| 🔴 **主线识别层** | **未解决** | Top1命中率≈随机，主线是谁？主线走到哪一步？ |
| 🔴 **市场估值层** | **空白** | PE分位、ERP、股债利差、融资余额、换手率分位 — 均未研究 |
| 🔴 **主线持续性** | **空白** | 为何有的主线持续一年（AI/机器人）、有的仅三个月（元宇宙）？ |

### 短期待办

- [x] EXP-002/003/006/007 — 行业行为评分层研究收口
- [ ] 决定上层架构的下一个实验方向

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
    ├── exp003_state_aware_behavior_score.json  # EXP-003 结果 (A/B/C/D)
    ├── exp003_chaos_top1_diagnostics.json      # EXP-003 CHAOS 诊断
    ├── exp006_signal_lifecycle.json            # EXP-006 TOP1/TOP3 生命周期
    ├── exp006a_winner_window_profiles.json     # EXP-006A 赢家画像
    ├── exp006b_delta_analysis.json             # EXP-006B Delta 分层
    └── exp006c_delta_lifecycle.json            # EXP-006C Delta 生命周期曲线
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
    ├── EXP-004-market-state-recognition-v0.md
    ├── EXP-006-signal-lifecycle-analysis.md    # ✅ 完整生命周期分析
    └── EXP-007-state-lifecycle-fusion.md       # ❌ Delta 融合：负结果

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
