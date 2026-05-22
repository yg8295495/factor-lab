# Codex Project Memory

> This file is a compact working memory for future Codex sessions.
> Read it together with `AGENT.md`, `README.md`, and `PLAN.md` before making research or code decisions.

## Project Identity

`factor-lab` is the factor research branch of the broader AI-DMS / Market State Engine system.
Its role is not to build a full dashboard or trading platform, but to provide the research kernel for:

- Layer 1: raw market data
- Layer 2: single-variable features/factors
- Layer 3: market structure evidence
- Layer 9: lightweight factor visualization

The broader Market State Engine v2.0 has 10 frozen layers:

```text
Layer 0 Infrastructure
Layer 1 Raw Data
Layer 2 Feature
Layer 3 Structure
Layer 4 Regime
Layer 5 Expectation
Layer 6 State
Layer 7 Strategy
Layer 8 Interpretation
Layer 9 Frontend
```

Current `factor-lab` work should stay inside Layer 1/2/3/9. Do not prematurely move research logic into final state or strategy conclusions.

## Current Repository State

Important local files:

- `README.md`: project overview, architecture, factor philosophy
- `PLAN.md`: current milestone and next tasks
- `AGENT.md`: AI navigation map and important caveats
- `backend/server.py`: FastAPI JSON API for frontend
- `backend/research/features/registry.py`: Layer 2 Feature Registry
- `backend/research/features/calculator.py`: factor calculation engine
- `backend/research/analysis/sector_behavior_score.py`: sector behavior scoring experiments
- `frontend/src/FactorChart.tsx`: Vite/React/ECharts factor chart
- `data/quant_engine.db`: local SQLite database

Database currently has 6 core tables:

- `asset_master`
- `market_daily_data`
- `market_state_history`
- `theme_tracking`
- `ai_analysis_reports`
- `ai_memory`

The local database has been designed as a personal research database: semi-wide table first, query convenience first, few tables. Avoid over-normalizing unless the data shape truly cannot fit the existing model.

## Database Design Decision

The database design is intentionally:

```text
semi-wide market_daily_data + small number of core functional tables
```

Important rules:

- Existing fields, unique constraints, and table meanings are considered frozen.
- New daily market/factor fields should usually be appended to `market_daily_data`.
- `asset_master.stable_industry` stores one primary stable industry.
- `asset_master.tags` stores multi-label static classifications such as `AI`, `internet`, `growth`, `small_cap`.
- `market_daily_data.ai_theme_tag` / `ai_sentiment_tag` are dynamic daily AI labels.
- Do not add normalized tag mapping tables unless historical, point-in-time tag membership becomes necessary.

Current `market_daily_data` uniqueness is:

```sql
UNIQUE(symbol, trade_date)
```

This is not the same as `trade_date` being a primary key. It is ideal for per-symbol time series queries. If full-A stock data is added and date-level cross-section scans become slow, add a non-destructive index such as:

```sql
CREATE INDEX idx_market_daily_trade_date
ON market_daily_data(trade_date);
```

## Symbol Convention

Actual project code/database currently uses prefixed symbols:

```text
index.000985.SH
index.000300.SH
sector.801780.SW
stock.000001.SZ
```

Known issue: some config/registry text may still refer to `index.000985.CSI`. The actual database and code path use `index.000985.SH`. Keep this consistent when editing.

## Vectorized Scoring Is Forbidden

The vectorized implementation in `sector_behavior_score.py` has already been tested and confirmed unreliable. It does not match the loop implementation because different sector calendars and global pivot alignment create window semantic drift.

Hard rule:

```text
Do not use vectorized sector behavior scores as research evidence.
Use the loop version only.
```

Relevant context:

- `calc_sector_rolling_score()` is the trusted loop-style rolling scorer.
- `calc_sector_score_vectorized()` and vectorized daily rolling paths are historical experiments only.
- `--daily` is documented as polluted by vectorized logic and should not be used for conclusions.
- All backtests must use rolling evaluation, not static hit rate.

## Research Philosophy

The core research problem is market structure, not isolated indicator discovery.

Market state is not just trend:

```text
main uptrend = trend up + breadth up + volume up + risk preference up
crowding     = core assets up + breadth down
chaos        = index sideways + low volatility + weak style persistence
retreat      = trend down + breadth down + leaders breaking down
```

Layer 2 features must not directly claim a market conclusion.
Layer 3 combines multiple Layer 2 features into structure evidence.

Feature explosion control:

For every new feature, answer:

1. What does it measure?
2. Which state dimension does it belong to?
3. How is it orthogonal to existing features?
4. Does it add genuinely new information?

## Current Layer 2 / Layer 3 Direction

Current important Layer 2 features:

- RS20 / RS60
- RS_SLOPE
- MOM20 / MOM60
- TREND_STR
- BREAKOUT
- ADV_DECLINE_RATIO
- INDUSTRY_DIFFUSION
- VOLATILITY_20D
- SMALL_CAP_SPREAD
- PE_PERCENTILE / PE_CHANGE_RATE
- PRICE_VOL_DIVERGENCE

Near-term proposed additions:

- RS acceleration / delta RS20
- market breadth from all-A stocks
- limit-up / limit-down counts
- sector breadth:
  - `above_ma20_ratio`
  - `above_ma60_ratio`
  - `new_high_20d_ratio`
  - `rs_positive_ratio`
- structure-layer score mode:
  - base W1/W2/W3 behavior score
  - breadth adjustment
  - rolling A/B backtest: base vs base + breadth

Preferred implementation style:

- Keep Layer 2 `FeatureDef` registry, but add metadata rather than replacing it with a nested ontology.
- Useful metadata candidates:
  - `family`: relative / breadth / structure / context
  - `scope`: asset / sector / market / cross_sector
  - `layer`: 2 or 3
  - `structure_role`: trend / participation / confirmation / risk / style
- Put Layer 3 combination rules under `backend/research/structures/`, not mixed into raw Layer 2 factor definitions.

## Raw Stock Data Plan

Planned A-track:

- Use baostock for all-A daily stock data.
- Approximate range: 2005-01-01 to present.
- Store stock rows in `market_daily_data` with `asset_type='stock'`.
- Keep raw stock data locally so breadth can be recomputed without redownloading.
- Expected scale: about 15M rows, still acceptable for local SQLite with appropriate indexes and careful batch writes.

Suggested rollout:

1. Run a small sample first: 2-3 sectors / around 100 stocks.
2. Validate schema, units, price adjustment, pct change, limit flags, and breadth output.
3. Then run full collection with checkpoint/retry/manifest.

Do not compute only "favored sectors" at the data layer. It is better to compute breadth for all 30 sectors and apply favored-sector filtering only in experiments/backtests.

## Price Adjustment Policy

Different tasks need different price conventions.

Recommended fields:

```text
open, high, low, close  -> raw unadjusted OHLC
volume, amount          -> raw values, never adjusted
pct_chg_raw             -> raw pct change from baostock, for limit-up/down rules
preclose_raw            -> optional but strongly recommended
close_hfq               -> back-adjusted close for returns/RS/Momentum
hfq_factor              -> close_hfq / raw close
```

Do not store `qfq_factor` unless a strong need appears. Frontend forward-adjusted K-line can be generated dynamically:

```text
qfq_factor(date) = hfq_factor(date) / hfq_factor(latest_date)
qfq_ohlc = raw_ohlc * qfq_factor(date)
```

Use cases:

- Limit-up/down, raw daily pct change: use `pct_chg_raw` / raw prices.
- Backtest returns, NAV, RS, Momentum, MA-based breadth: use `close_hfq`.
- Human chart/K-line display: use dynamically generated forward-adjusted OHLC.
- Volume and amount: use raw values only.

Short-term Layer 2/3 work does not require storing `open_hfq`, `high_hfq`, or `low_hfq`.
If future strategies need high/low based calculations such as ATR, Donchian/turtle breakout, or intraday breakout structure, derive:

```text
open_hfq = open_raw * hfq_factor
high_hfq = high_raw * hfq_factor
low_hfq  = low_raw  * hfq_factor
```

Before relying on this, sample-validate against vendor-provided adjusted OHLC.

## Limit-Up / Limit-Down Policy

Limit-up/down detection must use raw exchange-rule data, not adjusted prices.

Preferred:

```text
pct_chg_raw from baostock
```

Basic threshold such as `>= 9.8%` is only a first approximation. More rigorous future handling should consider:

- ST stocks around 5%
- ChiNext / STAR Market 20% after registration reform dates
- board-specific listing rules
- new-stock special periods

For market-state research, a first version can use approximate thresholds but must document the approximation.

## Current Work Plan Assessment

The dual-track plan is directionally sound:

```text
A track: raw all-A data + market/sector breadth
B track: ontology/metadata + Layer 3 structure scoring + rolling backtest
```

Recommended refinements:

- Keep the semi-wide table design. Do not add three new breadth tables by default.
- Add breadth fields to `market_daily_data`:
  - market-level fields on `index.000985.SH` rows
  - sector-level breadth fields on `sector.*.SW` rows
- Only add new tables if point-in-time historical membership becomes required.
- Add a date index before large cross-section workloads if needed.
- Remove or guard vectorized scoring paths before they contaminate new experiments.
- Run small-sample data validation before full-A ingestion.
- Document every approximation explicitly, especially current-constituent backfill and limit-up rules.

## Known Risks / Open Issues

- `index.000985.CSI` vs `index.000985.SH` inconsistency should be cleaned.
- `sector_behavior_score.py` still contains vectorized/historical code paths that can be accidentally run.
- Current database has index/sector rows but no stock rows yet.
- `market_daily_data` currently lacks raw pct change, adjusted close, and adjustment factor fields needed for strict all-A research.
- Historical sector membership may introduce survivorship bias if current constituents are backfilled to 2005.
- If all-A cross-section queries are frequent, `(symbol, trade_date)` unique index alone may be insufficient; add a date index.

## Preferred Next Steps

1. Freeze and document price adjustment policy.
2. Add missing raw/adjustment fields to `market_daily_data`.
3. Fix benchmark symbol consistency.
4. Guard or deprecate vectorized behavior-scoring entry points.
5. Build small-sample baostock ingestion.
6. Validate raw vs adjusted prices, pct change, limit-up/down flags.
7. Compute all-sector breadth on the sample.
8. Integrate breadth adjustment into loop-based rolling backtest.
9. Only then run full-A ingestion.

