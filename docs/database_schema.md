# 数据库结构规范

> 对应 `data/quant_engine.db`（SQLite）。
> schema 已冻结：不删不改现有主键，新因子只加字段，不新增表。

---

## 一、总览

| 表 | 行数 | 用途 | 更新频率 |
|:---|:----:|:-----|:--------|
| `asset_master` | ~55 | 资产主表 — 每个跟踪标的的身份证 | 新增标的手动写入 |
| `market_daily_data` | ~23万 | 核心宽表 — OHLCV + 估值 + 因子 + 情绪指标 | 每日采集/计算后写入 |
| `market_state_history` | — | 市场状态判定记录 | AI分析后写入 |
| `theme_tracking` | — | 市场主题跟踪 | AI分析后写入 |
| `ai_analysis_reports` | — | AI 分析报告 | AI分析后写入 |
| `ai_memory` | — | AI 长期经验库 | AI分析后写入 |

---

## 二、asset_master — 资产主表

| 字段 | 类型 | 必填 | 说明 |
|:-----|:----:|:----:|:-----|
| `symbol` | TEXT | ✅ | 唯一编码，格式 `{type}.{ticker}.{exchange}` |
| `name` | TEXT | ✅ | 中文名称 |
| `asset_type` | TEXT | ✅ | `stock` / `index` / `etf` / `sector` |
| `exchange` | TEXT | | 交易所：`SH` / `SZ` / `CSI` / `SW` 等 |
| `stable_industry` | TEXT | | 申万一级行业 |
| `tags` | TEXT | | JSON 数组，用于标记分类 |
| `is_active` | INT | | `1`=跟踪中，`0`=已停用 |

### 符号编码规范

```
格式：{asset_type}.{ticker}.{exchange}
示例：
  index.801003.SW    → 申万Ａ指（benchmark，真正的全A指数）
  index.801001.SW    → 申万50（仅50只大盘股，已废弃为基准）
  sector.801780.SW   → 申万银行
  stock.000001.SZ    → 平安银行
```

---

## 三、market_daily_data — 核心宽表

### 3.1 主键与资产身份

| 字段 | 类型 | 必填 | 说明 |
|:-----|:----:|:----:|:-----|
| `symbol` | TEXT | ✅ | 资产标识，关联 `asset_master.symbol` |
| `trade_date` | DATE | ✅ | 交易日 |

### 3.2 行情数据（原始采集）

| 字段 | 类型 | 复权口径 | 说明 |
|:-----|:----:|:---------|:-----|
| `open` | REAL | **未复权** | 开盘价 |
| `high` | REAL | **未复权** | 最高价 |
| `low` | REAL | **未复权** | 最低价 |
| `close` | REAL | **未复权** | **收盘价——当前为未复权原始值** |
| `volume` | REAL | 原始值，不复权 | 成交量（手） |
| `amount` | REAL | 原始值，不复权 | 成交额（元） |
| `turnover_rate` | REAL | — | 换手率 |
| `pct_chg_raw` | REAL | **未复权** | **原始涨跌幅**，用于涨跌停判定。来源：未复权 close 自算 `(close[t] - close[t-1]) / close[t-1] * 100` |

### 3.3 后复权价格

| 字段 | 类型 | 复权口径 | 说明 |
|:-----|:----:|:---------|:-----|
| `close_hfq` | REAL | **后复权** | **后复权收盘价**，用于收益回测/净值/RS/Momentum 等连续价格计算 |
| `hfq_factor` | REAL | — | **后复权因子**，`= close_hfq / close`，用于推导前复权价格 |

> **前复权价格**不直接存储，通过公式动态计算：
> `qfq_factor(t) = hfq_factor(t) / hfq_factor(最新交易日)`
> `qfq_price(t) = 未复权价格(t) × qfq_factor(t)`
>
> 这样前端 K 线始终锚定最新真实价格，未来分红送转后只需更新 `hfq_factor`。

### 3.4 复权口径速查

| 场景 | 使用字段/数据 | 原因 |
|:-----|:-------------|:------|
| 涨跌停判定 | `pct_chg_raw` （baostock pctChg） | 原始涨跌幅，不受复权影响 |
| 收益回测/净值/RS/Momentum | `close_hfq` | 后复权，真实投资收益 |
| 人工看盘/K线展示 | `close_hfq` 或 `未复权 OHLC × qfq_factor` | 前复权，历史价格连续不失真 |
| ATR/布林/唐奇安/海龟突破 | `未复权 OHLC × hfq_factor` | 需要后复权的 high/low，避免除权假突破 |
| 成交额/成交量 | `amount` / `volume` | 原始值，不复权 |

### 3.5 估值数据

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `pe_ttm` | REAL | 滚动市盈率 |
| `pb` | REAL | 市净率 |
| `ps` | REAL | 市销率 |
| `peg` | REAL | 市盈率相对盈利增长比率 |
| `dividend_yield` | REAL | 股息率 |
| `roe` | REAL | 净资产收益率 |
| `gross_margin` | REAL | 毛利率 |
| `revenue_growth` | REAL | 营收增长率 |
| `profit_growth` | REAL | 利润增长率 |

### 3.6 Layer 2 因子字段（由 calculator.py 计算写入）

| 字段 | 类型 | 维度 | 说明 |
|:-----|:----:|:----:|:------|
| `rs20_cross` | REAL | RS | 20日相对强度（vs 中证全指） |
| `rs60_cross` | REAL | RS | 60日相对强度 |
| `rs_slope` | REAL | RS | RS20 的 20 日线性回归斜率 |
| `time_momentum20` | REAL | Context | 20 日时序动量（自身涨跌幅） |
| `time_momentum60` | REAL | Context | 60 日时序动量 |
| `trend_strength` | REAL | Context | 趋势综合评分（RS+MOM+斜率，0~100） |
| `breakout_strength` | REAL | Context | 突破强度（收盘价偏离 MA20 幅度） |
| `volume_ratio` | REAL | Context | 量比 |
| `amount_ratio` | REAL | Context | 额比 = amount / SMA20(amount)。对 sector 行和 benchmark 均适用 |
| `price_volume_state` | TEXT | Context | 量价状态标记 |
| `pe_ttm_pct` | REAL | Context | PE 历史 250 日百分位 |
| `pe_change_rate` | REAL | Context | PE_TTM 20 日变化率 |
| `dividend_yield_pct` | REAL | Context | 股息率历史百分位 |
| `price_vol_divergence` | REAL | Context | 量价背离度（z-score） |

> 所有趋势类因子（RS/MOM/突破等）基于 **`close_hfq`**（后复权 close）计算，确保时间序列连续可比。

### 3.7 Layer 2 横截面因子（跨资产聚合）

| 字段 | 类型 | 维度 | 说明 |
|:-----|:----:|:----:|:------|
| `adv_decline_ratio` | REAL | Breadth | 全市场（申万行业）上涨/下跌行业数比 |
| `industry_diffusion` | REAL | Breadth | RS20>50 的行业占比（0~1） |
| `market_volatility_20d` | REAL | Volatility | 申万行业平均 20 日收益率标准差 |
| `small_cap_spread` | REAL | Style | 中证2000 vs 沪深300 的 RS20 差值 |

### 3.8 情绪/涨跌停标记

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `limit_up_flag` | INT | 涨停标记（1=涨停），基于 `pct_chg_raw` 判定 |
| `limit_down_flag` | INT | 跌停标记（1=跌停） |
| `bust_flag` | INT | 崩盘标记 |

### 3.9 风格评分

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `growth_score` | REAL | 成长评分 |
| `dividend_score` | REAL | 红利评分 |
| `small_cap_score` | REAL | 小盘评分 |
| `institution_score` | REAL | 机构持仓评分 |

### 3.10 Layer 3 Breadth 指标（行业行专用）

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `above_ma20_ratio` | REAL | 行业内站上 MA20 的股票比例 |
| `above_ma60_ratio` | REAL | 行业内站上 MA60 的股票比例 |
| `new_high_20d_ratio` | REAL | 行业内创 20 日新高的股票比例（基于后复权价格） |
| `rs_positive_ratio` | REAL | 行业内 RS20>0 的股票比例 |

### 3.11 Layer 3 市场情绪指标（全指行专用）

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `adv_count` | INT | 全市场上涨家数 |
| `decl_count` | INT | 全市场下跌家数 |
| `limit_up_count` | INT | 全市场涨停家数 |
| `limit_down_count` | INT | 全市场跌停家数 |
| `market_adv_ratio` | REAL | 全市场涨跌比 |

### 3.12 AI 辅助

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `ai_theme_tag` | TEXT | AI 识别的主题标签 |
| `ai_sentiment_tag` | TEXT | AI 情绪标签 |

---

## 四、其他表

### market_state_history

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `id` | INTEGER | 主键 |
| `trade_date` | DATE | 交易日 |
| `market_state` | TEXT | 主升/分歧/退潮/混沌 |
| `style_state` | TEXT | 小票主导/机构抱团/成长风格/红利风格 |
| `risk_state` | TEXT | Risk On / Risk Off |
| `main_theme` | TEXT | 当前主线 |
| `confidence` | REAL | 置信度 0~1 |
| `comment` | TEXT | 分析备注 |

### theme_tracking

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `id` | INTEGER | 主键 |
| `trade_date` | DATE | 交易日 |
| `theme_name` | TEXT | 主题名称 |
| `strength_score` | REAL | 强度评分 |
| `heat_score` | REAL | 热度评分 |
| `leader_symbol` | TEXT | 领涨资产 |
| `continuity_score` | REAL | 持续性评分 |

### ai_analysis_reports

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `id` | INTEGER | 主键 |
| `trade_date` | DATE | 交易日 |
| `symbol` | TEXT | 关联资产（可选） |
| `report_type` | TEXT | 日报/周报/行业分析/风险提示 |
| `content` | TEXT | 报告内容 |
| `source_refs` | TEXT | 引用来源 |
| `confidence` | REAL | 置信度 |

### ai_memory

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `id` | INTEGER | 主键 |
| `topic` | TEXT | 话题标识 |
| `summary` | TEXT | 记忆摘要 |
| `evidence_dates` | TEXT | 证据日期范围 |
| `confidence` | REAL | 置信度 |
| `created_at` | DATE | 创建时间 |
| `updated_at` | DATE | 更新时间 |

---

## 五、数据源约定

| 数据 | 来源 | 说明 |
|:-----|:------|:------|
| 宽基指数日线 | akshare `stock_zh_index_daily_tx` | 腾讯源，缺 volume |
| 申万行业日线 | akshare `index_hist_sw` | 字段齐全 |
| 中证主题指数 | akshare `stock_zh_index_hist_csindex` | 覆盖全量，含 PE_TTM |
| 个股日线（主） | baostock `query_history_k_data_plus` | 双趟：未复权 + 后复权 |
| 个股补缺 | 新浪 `stock_zh_a_daily` | 仅 baostock 缺失的 ~5% |
| 个股成分股 | akshare `index_stock_cons` | 申万行业成分股 |
| 涨跌停判定 | baostock `pctChg` | 始终返回原始涨跌幅 |
| 绝对不做 | 东方财富系（`push2his.eastmoney.com`） | IP 封禁，不可靠 |

---

## 六、修订历史

| 日期 | 变更 | 说明 |
|:-----|:-----|:------|
| 2026-05-20 | 初版 | schema 冻结后的完整字段说明 |
| — | `close` 改为未复权 | 新增 `close_hfq` / `hfq_factor`，统一复权口径 |
