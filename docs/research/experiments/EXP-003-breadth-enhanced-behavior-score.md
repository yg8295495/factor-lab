# EXP-003 — Market State-Aware Sector Behavior Score

## Status

Planned — design draft, no implementation or backtest run yet.

## Hypothesis

EXP-002 proved that the rolling W1/W2/W3 sector behavior score has value, but it still needs market-state context and sector participation confirmation. EXP-003 tests whether the accepted EXP-004 market-state classifier can reduce wrong-way sector attacks, and whether sector breadth / amount confirmation can improve main-line industry selection inside eligible market states.

This experiment answers two questions:

1. Does EXP-004 state filtering improve EXP-002 W1/W2/W3 drawdown control?
2. Within eligible states, do sector breadth and amount signals improve the quality of selected main-line industries?

## Baseline

Base model:

```text
loop-based W1/W2/W3 sector behavior score from EXP-002
```

Reference implementation:

```text
backend/research/analysis/sector_behavior_score.py
```

Trusted scorer:

```text
calc_sector_rolling_score()
```

Market-state reference:

```text
backend/research/analysis/market_state_recognition.py
backend/research/analysis/output/market_state_daily.json
```

Accepted market-state version:

```text
EXP-004 v0.5 final
```

## Pre-run Gate

- [x] data coverage sufficient: 30 Shenwan sector indexes + `index.000985.SH` are available for the EXP-002 rolling range
- [x] required fields populated: EXP-002 W1/W2/W3 inputs, EXP-004 v0.5 state output (`market_state_daily_v05.json`), sector breadth fields (`above_ma20_ratio`, `above_ma60_ratio`, `new_high_20d_ratio`), sector `amount_ratio`
- [x] industry / asset-pool mapping reliable: DATA-001 snapshot mapping accepted for v1; mapping bias noted in result report
- [x] future-function risk checked: all sector scores and state labels use data available on or before the rebalance date
- [x] survivorship-bias risk checked: current stock-to-sector mapping is acceptable for v1 but cannot be hidden in conclusions
- [x] rebalance / holding / benchmark settings confirmed: REBALANCE_INTERVAL=20, HOLD_LOOKAHEAD=20, TOP_N=3, benchmark=index.000985.SH
- [x] transaction-cost assumption confirmed: no transaction cost in v1

## Candidate Inputs

### Market State

Read from EXP-004 output:

| Field | Source | Use |
|-------|--------|-----|
| `state` | `market_state_daily.json` | state-aware exposure / selection filter |
| `trend_score` | `market_state_daily.json` | diagnostics only |
| `breadth_score` | `market_state_daily.json` | diagnostics only |
| `emotion_score` | `market_state_daily.json` | diagnostics only |
| `volume_score` | `market_state_daily.json` | diagnostics only |
| `risk_score` | `market_state_daily.json` | diagnostics only |

Accepted state labels:

```text
MAIN_UP_CONFIRMED / REBOUND / CROWDING / RETREAT / CHAOS
```

### Sector Confirmation

Direct fields:

| Field | Scope | Use |
|-------|-------|-----|
| `RS20`, `RS60` | sector | already part of W1/W2/W3 behavior score |
| `MOM20`, `MOM60` | sector | already part of W1/W2/W3 behavior score |
| `TREND_STR` | sector | already part of W1/W2/W3 behavior score |
| `above_ma20_ratio` | sector | short-term participation confirmation |
| `above_ma60_ratio` | sector | medium-term participation confirmation |
| `new_high_20d_ratio` | sector | leader expansion confirmation |
| `amount_ratio` | sector | sector-level volume confirmation |

Computed in memory if needed:

| Field | Source | Use |
|-------|--------|-----|
| `sector_amount_share` | sector amount / all-sector amount | optional diagnostics; not a v1 hard rule |
| `sector_amount_rank` | cross-sector amount share rank | optional diagnostics; not a v1 hard rule |

Excluded for v1:

- stock-level `RS20` / `MOM20` as direct selection factors
- valuation factors
- newly imported external factor definitions
- ETF flow signals

## Initial Rule Design

### Variant A — EXP-002 Baseline

Use the original W1/W2/W3 behavior score and select the top sectors exactly as EXP-002 did.

Purpose: reproduce the known baseline.

### Variant B — State Filter Only

Use the original W1/W2/W3 ranking, but adjust exposure by market state:

| State | Action | Rationale |
|-------|--------|-----------|
| `MAIN_UP_CONFIRMED` | TOP 3, equal weight, full attack | trend and risk conditions are confirmed |
| `REBOUND` | **no sector holdings (observe-only)** | EXP-004 says rebound is ambiguous; avoid absorbing bounce noise |
| `CROWDING` | TOP 1, equal weight, reduced exposure | narrow leadership may continue but crowding risk is higher |
| `CHAOS` | no sector holdings | signal quality is weak |
| `RETREAT` | no sector holdings | drawdown control has priority |

If no cash-equivalent return series is available, use benchmark-neutral treatment for skipped windows in v1 reporting, and state the limitation explicitly.

**Sensitivity variants (informational only, not primary):**

| Variant | REBOUND handling | Purpose |
|---------|-----------------|---------|
| `main` | observe-only | **primary acceptance metric** |
| `rebound_top1` | REBOUND → TOP 1 | check if REBOUND captures meaningful recovery |
| `rebound_half_top3` | REBOUND → TOP 3 half weight | reference only, not primary |

### Variant C — State + Sector Confirmation

Same state-based exposure as Variant B, but within MAIN_UP_CONFIRMED and CROWDING,
the W1/W2/W3 base score is adjusted by sector breadth/amount confirmation:

```text
confirmed_score = base_w1w2w3_score + breadth_bonus + amount_bonus
```

Initial breadth bonus:

| Condition | Adjustment |
|-----------|-----------:|
| `above_ma20_ratio >= 0.60` | +0.5 |
| `above_ma60_ratio >= 0.50` | +0.5 |
| `new_high_20d_ratio >= 0.10` | +0.5 |
| `above_ma20_ratio <= 0.40` | -0.5 |

Initial amount bonus:

| Condition | Adjustment |
|-----------|-----------:|
| `amount_ratio >= 1.10` | +0.5 |
| `amount_ratio <= 0.90` | -0.5 |

The adjustment is intentionally smaller than the base behavior score. Its role is to confirm close calls, not replace W1/W2/W3.

## Backtest Settings (Confirmed)

| Setting | Value |
|---------|-------|
| data range | continuous rolling: from available data to latest (same as EXP-002 continuous_rolling) |
| asset pool | 30 Shenwan sector indexes |
| rebalance frequency | every 20 trading days (same as EXP-002) |
| holding period | 20 trading days (same as EXP-002) |
| selected sectors | MAIN_UP_CONFIRMED → TOP 3; CROWDING → TOP 1; otherwise none |
| benchmark | `index.000985.SH` |
| transaction cost | none in v1 |
| market state source | EXP-004 v0.5 daily output (`market_state_daily_v05.json`) |
| baseline output file | `backend/research/analysis/output/continuous_rolling_results.json` |
| experiment output file | `backend/research/analysis/output/exp003_state_aware_behavior_score.json` |

## Validation Metrics

Primary metrics:

- total return
- excess return versus `index.000985.SH`
- rolling window win rate
- max drawdown
- return / excess return by market state
- trade count by market state

Comparison questions:

- Variant B vs Variant A: does state filtering reduce EXP-002 drawdowns?
- Variant C vs Variant B: do sector breadth and amount confirmation improve selected-sector quality?
- `REBOUND` windows: should they be reduced exposure, observe-only, or treated like `MAIN_UP_CONFIRMED` only when sector confirmation is strong?
- `RETREAT` windows: does avoiding sector attack reduce loss without losing too much recovery?

EXP-002 drawdown explanation:

- identify EXP-002 major drawdown windows
- report EXP-004 state distribution inside those windows
- compare baseline sector exposure versus state-filtered exposure
- classify avoided losses and missed gains separately

## Confirmation

- **confirmed by:** user
- **confirmation date:** 2026-06-05
- **confirmed scope:** Variant A/B/C design, state action rules, backtest settings, sensitivity variants
- **notes:** this document is a design draft only; do not run formal EXP-003 until the read-only evaluator is implemented and produces the first JSON output

## Results

Pending.

## Conclusion

Pending.

## Next Step

Confirm the EXP-003 design and backtest settings. After confirmation, implement a read-only evaluator that reads existing EXP-002 / EXP-004 outputs plus sector breadth / amount fields, computes Variant A/B/C, and writes a JSON result report without modifying the database.
