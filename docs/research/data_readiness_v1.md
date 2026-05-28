# Data Readiness v1

> Purpose: record the current data readiness state before market-state and
> main-line sector factor-combination backtests.

## Current Snapshot

SQLite tables currently present:

- `asset_master`
- `market_daily_data`
- `market_state_history`
- `theme_tracking`
- `ai_analysis_reports`
- `ai_memory`

Asset counts from `asset_master`:

| Asset Type | Count |
|------------|------:|
| index | 25 |
| sector | 30 |
| stock | 5478 |

Daily data snapshot:

| Scope | Distinct Symbols | Date Range | Rows |
|-------|-----------------:|------------|-----:|
| stock rows | 5183 | 1996-12-17 ~ 2026-05-22 | 14,991,735 |
| sector rows | 30 | 1999-12-30 ~ 2026-05-19 | 133,084 |

## Key Findings

### Stock-To-Sector Mapping

`asset_master.stable_industry` is empty for all stock rows.

This means the database does not currently contain a reusable stock-to-sector
mapping in `asset_master`. Full-sector internal breadth cannot be recomputed
from stock rows until this mapping is rebuilt or loaded from a constituent
source.

This does not mean the stock data is unusable. It means sector aggregation needs
a mapping source before it can cover all 30 sectors.

### Stock Daily Data

The full-A stock daily data is already mostly present.

Important field coverage:

| Field | Stock Coverage |
|-------|---------------:|
| `close_hfq` | 100.00% |
| `hfq_factor` | 99.96% |
| `pct_chg_raw` | 0.47% |
| `limit_up_flag` | 0.51% |
| `limit_down_flag` | 0.51% |

Interpretation:

- Adjusted close data is available and suitable for MA/new-high style breadth.
- Raw pct change and limit flags are not broadly populated yet.
- Limit-up/down and raw pct-change fields should be recomputed from raw close or
  restored from the collection pipeline before emotion factors are used.

### Sector Breadth

Current sector breadth is only populated for 3 sectors:

| Sector | Rows | Date Range |
|--------|-----:|------------|
| `sector.801080.SW` | 5171 | 2005-01-04 ~ 2026-05-19 |
| `sector.801120.SW` | 5171 | 2005-01-04 ~ 2026-05-19 |
| `sector.801780.SW` | 2958 | 2014-02-21 ~ 2026-05-19 |

These rows came from earlier pilot data collection and should not be treated as
full-market breadth coverage.

### Historical Script Drift

Older archive notes refer to `backend/collectors/stock_pilot.py`, but that file
is not present in the current worktree.

The current visible stock collection script is:

```text
backend/collectors/tickflow_collector.py
```

Before extending old pilot logic, inspect the current collector and decide
whether to rebuild the missing pilot functionality or write a new second-pass
aggregation script.

## Data Work Before Backtests

Required before formal market-state / main-line sector backtests:

1. Build or load all-30-sector stock membership.
2. Decide whether to persist membership in `asset_master.stable_industry` or a
   separate generated mapping artifact.
3. Recompute `pct_chg_raw`, `limit_up_flag`, and `limit_down_flag` for stock rows
   where possible.
4. Aggregate market emotion fields onto `index.000985.SH` rows:
   - `adv_count`
   - `decl_count`
   - `market_adv_ratio`
   - `limit_up_count`
   - `limit_down_count`
5. Aggregate sector internal breadth for all 30 sector rows:
   - sector advance ratio
   - `above_ma20_ratio`
   - `above_ma60_ratio`
   - `new_high_20d_ratio`
   - sector limit-up / limit-down counts and ratios
6. Aggregate amount-strength fields:
   - market amount ratio
   - sector amount ratio
   - sector amount share
   - sector amount share change

## Open Design Decision

For repeatable research, market and sector aggregation fields should generally be
persisted in `market_daily_data` once the calculation formula is confirmed.

Ad hoc live calculation is acceptable for inspection, but formal backtests
should read stable persisted fields or deterministic generated artifacts.

