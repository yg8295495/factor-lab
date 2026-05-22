# 01_factors.md — Factor And Backtest Rules

> Read this for factor implementation, Layer 2/3 boundaries, or backtest decisions.

## Layer Boundary

Layer 2 features are single-variable or direct cross-section measurements.
Layer 3 combines multiple Layer 2 features into structure evidence.

Do not make a Layer 2 feature claim a final market state by itself.

## Registry

Feature definitions live in:

```text
backend/research/features/registry.py
```

Factor calculation lives in:

```text
backend/research/features/calculator.py
```

Prefer adding metadata to existing `FeatureDef` rather than replacing the registry with a complex hierarchy.

Useful metadata candidates:

- `family`: relative / breadth / structure / context
- `scope`: asset / sector / market / cross_sector
- `layer`: 2 / 3
- `structure_role`: trend / participation / confirmation / risk / style

Layer 3 combination rules should live under:

```text
backend/research/structures/
```

## Current Factor Families

| Family | Examples | Price/Data Basis |
|--------|----------|------------------|
| Relative strength | `rs20_cross`, `rs60_cross`, `rs_slope` | `close_hfq` vs `index.000985.SH` |
| Momentum | `time_momentum20`, `time_momentum60`, `trend_strength` | `close_hfq` |
| Breadth | `above_ma20_ratio`, `above_ma60_ratio`, `new_high_20d_ratio`, `rs_positive_ratio` | stock `close_hfq`, aggregated to sector rows |
| Emotion | `limit_up_count`, `limit_down_count`, `market_adv_ratio` | raw pct change / limit flags |
| Volume/amount | `volume_ratio`, `amount_ratio`, `price_vol_divergence` | raw volume/amount + adjusted price direction |
| Valuation/context | `pe_ttm_pct`, `pe_change_rate`, `dividend_yield_pct` | valuation fields |

## Backtest Rules

- Use rolling evaluation only.
- Default comparison is excess return vs `index.000985.SH`.
- Prefer one main variable change per experiment.
- Record data range, asset pool, rebalance frequency, holding period, benchmark, and transaction-cost assumption.

## Forbidden Path

Vectorized sector behavior scoring is not trusted.

Reason:

```text
Different sector calendars + pivot alignment changed window semantics.
Vectorized vs loop match rate was only 34.7%.
```

Use loop-based behavior scoring only:

```text
calc_sector_rolling_score()
```

Do not use `--daily` results from `sector_behavior_score.py` as research evidence.
