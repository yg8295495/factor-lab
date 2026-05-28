# 00_data.md — Data Rules

> Read this only for data fields, sources, schema, or price-adjustment questions.
> Do not use this file as a live collection progress log.

## Database Shape

The project uses a personal research database:

```text
SQLite + semi-wide market_daily_data + small number of core tables
```

Default rule:

- Daily raw data, factors, breadth, and structure evidence usually append fields to `market_daily_data`.
- `asset_master.stable_industry` stores one primary industry.
- `asset_master.tags` stores multi-label static categories.
- Do not add normalized tables unless point-in-time historical membership is required.

## Key Tables

- `asset_master`: asset identity and static metadata
- `market_daily_data`: OHLCV, valuation, factors, breadth, daily tags
- `market_state_history`: final market-state output, later stage
- `theme_tracking`: dynamic theme tracking, later stage
- `ai_analysis_reports`: large AI report text, later stage
- `ai_memory`: long-term AI memory, later stage

Exact schema lives in `docs/database_schema.md`.

## Symbol Convention

```text
index.000985.SH   # 中证全指, benchmark
index.000300.SH   # 沪深300
sector.801780.SW  # 申万行业
stock.000001.SZ   # A 股个股
```

Use `index.000985.SH`, not `index.000985.CSI`.

## Price Adjustment Policy

Target field semantics:

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

Back-adjusted high/low if needed later:

```text
high_hfq = high * hfq_factor
low_hfq = low * hfq_factor
```

Short-term Layer 2/3 work mainly needs `close_hfq`, not stored `high_hfq` / `low_hfq`.

## Data Sources

Current individual-stock collection uses `TickFlow` scripts:

- `backend/collectors/tickflow_collector.py`
- `backend/collectors/tickflow_retry.py`

External data tools such as `a-stock-data` may be used as provider adapters, but
they do not define the repo's data contract. Normalize every provider into the
symbol, adjustment, unit, and field policy above before writing to the database.

Runtime rules and execution SOP:

```text
docs/research/data_runtime_spec_v1.md
```

Data-source troubleshooting and one-off collection notes belong in `docs/archive/`.
After the one-time full-A collection is complete, do not keep collection progress in startup docs.
