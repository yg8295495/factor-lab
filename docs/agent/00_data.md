# 00_data.md — Data Rules

> Read this only for data fields, sources, schema, or price-adjustment questions.

## 基准

- **主基准:** `index.801003.SW`（申万Ａ指，唯一真正全A指数，~4119只成分股）
- 备用: `index.801001.SW`（申万50，仅50只大盘股，已标记）
- 全A替代: `index.000985.SH`（中证全指，K线保留供参考）

## Database Shape

```text
SQLite + semi-wide market_daily_data + 2 database files
```

- `data/quant_engine.db` — 完整版 (~2.8GB)，含全部个股行，台式研究用
- `data/quant_engine_base.db` — 随身版 (~64MB)，仅行业+指数+宏观+801003，无个股行

两者通过 `daily_update.py` 统一增量更新。

## Key Tables

- `asset_master`: asset identity and static metadata
- `market_daily_data`: OHLCV, valuation, factors, breadth, daily tags
- `market_state_history`: final market-state output, later stage

Exact schema in `docs/database_schema.md`.

## Symbol Convention

```text
index.801003.SW   # 申万Ａ指 (全A), benchmark
sector.801780.SW  # 申万行业
stock.000001.SZ   # A 股个股
```

## Price Adjustment Policy

| Field | Meaning | Main Use |
|------|---------|----------|
| `open/high/low/close` | raw unadjusted OHLC | exchange-rule facts, chart source |
| `volume/amount` | raw values | volume/turnover analysis |
| `pct_chg_raw` | raw pct change | limit-up/down flags |
| `close_hfq` | back-adjusted close | returns, RS, Momentum, MA breadth |
| `hfq_factor` | `close_hfq / close` | derive adjusted OHLC when needed |

Frontend forward-adjusted K-line:

```text
qfq_factor(t) = hfq_factor(t) / hfq_factor(latest_date)
qfq_ohlc(t) = raw_ohlc(t) * qfq_factor(t)
```

## Data Collection

### 每日增量更新（主入口）

```bash
# 更新 base.db 仅801003（最快，日常推荐）
python backend/collectors/daily_update.py --db data/quant_engine_base.db --only-benchmark

# 更新 base.db 全部（含行业+宏观）
python backend/collectors/daily_update.py --db data/quant_engine_base.db

# 更新 full.db 全部（含个股聚合重算）
python backend/collectors/daily_update.py
```

### 一次性/初始化脚本

| 脚本 | 用途 | 运行频率 |
|:-----|:-----|:---------|
| `build_sector_mapping.py` | stock-to-sector 行业映射 | 一次 |
| `compute_stock_fields.py` | 个股涨跌幅/涨跌停标记 | 一次 |
| `aggregate_sector_breadth.py` | 行业内部宽度(ma20/ma60/new_high) | 按需 |
| `sw_daily.py` | 30行业K线全量采集 | 一次性初始化 |
| `tickflow_collector.py` | 个股日线全量采集 + 增量 | 持续 |
| `fetch_macro_data.py` | 国债收益率 + 两融余额 | 按需 |

> `daily_update.py` 已覆盖 801003 K线/PE/派生字段 + 行业K线 + 宏观 + 额比回算。无需再单独跑 `add_801003.py`。
