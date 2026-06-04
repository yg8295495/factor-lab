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

## Current Scope Decision

The current registered factor pool is enough for the first market-state and
main-line sector research loop. Do not add external factor libraries by default.

The near-term bottleneck is data readiness and second-pass aggregation:

- complete stock-to-sector mapping for all 30 Shenwan sectors
- market advance / decline and limit-up / limit-down aggregation
- sector internal breadth aggregation
- market and sector amount-strength aggregation

Stock-level data is mainly used for aggregation. The first version does not need
to calculate `RS20`, `MOM20`, or trend scores for every stock unless a later
experiment explicitly tests stock-level relative strength.

Detailed scope note:

```text
docs/research/factor_scope_v1.md
```

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

## W1/W2/W3 Behavior Score (Sector Leadership v1)

### Structure

The behavior score divides the past 90 trading days into three 20-day windows:

```
T-90         T-60    T-40    T-20       T
 │            │       │       │          │
 ─────┴────────┴───────┴───────┴──────────┴───
              │       │       │          │
              W1      W2      W3         eval
           放量震荡   缩量洗盘  初升试探
```

Each window scores 0-3 sub-points, total 0-9.

### Two Information Layers (discovered in EXP-006)

| Layer | Source | Answers | Use |
|-------|--------|---------|-----|
| `Total Score` | W1+W2+W3 | 是否值得关注 (worth watching?) | Ranking across sectors |
| `Delta = W2 - W3` | W2 sub-score − W3 sub-score | 处于什么阶段 (lifecycle stage?) | Position explanation (EXP-007 confirmed: explanatory, not a trading filter) |

### Delta Interpretation

| Delta Range | Meaning | Lifecycle Curve |
|:----------:|---------|:---------------:|
| ≥ 2 (Wash >> Launch) | 洗盘充分，启动不足 | −1.2% @10D → +4.9% @40D (先弱后强) |
| 0.5~2 (Wash > Launch) | 洗盘略强 | +1.1% @20D (适中) |
| −0.5~0.5 (Balanced) | 整理和启动均衡 | +2.4% @20D, 60.4% win (最稳健) |
| −2~−0.5 (Launch > Wash) | 已启动但整理不足 | +0.3% @20D, 46.6% win (短期惯性, 衰减) |
| ≤ −2 (Launch >> Wash) | 已明显启动, 追高 | +1.2% @20D, 40.9% win (短期好, 后继弱) |

### Current Baseline (Variant D)

```
MAIN_UP_CONFIRMED → TOP 3 equal weight
REBOUND           → TOP 2 equal weight
CHAOS             → TOP 1 (total score ≥ 6)
CROWDING          → TOP 1 equal weight
RETREAT           → no holdings
```

Performance: 253 windows (2005~2026), +985.3% return, +340.6% excess vs `index.000985.SH`, −45.9% maxDD.

**Key validation:** CHAOS contributes 46.4% of total return — the framework's value lies in identifying local themes during chaotic markets, not amplifying bull runs.

### Forbidden Path

- Delta(W2-W3) is NOT a trading filter. EXP-007 tested State × Lifecycle fusion; both variants underperformed D. Delta explains lifecycle position in hindsight only.
- Despite positive excess, Top1 hit rate (~3.5%) is near random. The system has direction filtering ability (Top3 coverage 3× random) but not champion prediction.
