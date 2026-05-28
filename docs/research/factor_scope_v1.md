# Factor Scope v1

> Purpose: decide whether the current registered factor pool is enough for the
> first market-state and main-line sector research loop.

## Current Decision

Do not expand the factor pool from external platforms yet.

The current registered factors are sufficient for the first research loop. The
near-term bottleneck is data readiness and second-pass aggregation, not lack of
factor ideas.

## Two Research Targets

### Market State Recognition

Goal: classify broad market structure such as main-up, crowding, chaos, and
retreat.

Use market/index and cross-sector evidence:

| Role | Candidate Evidence |
|------|--------------------|
| trend | `MOM20`, `MOM60`, `BREAKOUT`, `TREND_STR` on broad indexes |
| breadth | market advance ratio, sector advance ratio, `INDUSTRY_DIFFUSION` |
| volatility / risk | `VOLATILITY_20D`, drawdown / volatility expansion |
| style | `SMALL_CAP_SPREAD` |
| emotion | `adv_count`, `decl_count`, `limit_up_count`, `limit_down_count`, `market_adv_ratio` |
| volume | market amount ratio, market amount expansion / contraction |

### Main-Line Sector Recognition

Goal: identify which sector is becoming the market main line.

Use sector-level trend plus internal sector diffusion:

| Role | Candidate Evidence |
|------|--------------------|
| sector trend | sector `RS20`, `RS60`, `RS_SLOPE`, `MOM20`, `MOM60` |
| sector breakout | sector `BREAKOUT` |
| sector volume | sector amount ratio, sector amount share, amount share change |
| sector diffusion | sector advance ratio, `above_ma20_ratio`, `above_ma60_ratio`, `new_high_20d_ratio` |
| sector emotion | sector limit-up / limit-down count and ratio |
| leader concentration | top-N amount share, top-N return contribution, leader-vs-tail dispersion |

## Stock-Level Role

The first version does not need to compute `RS20`, `MOM20`, or trend scores for
every stock.

Stock data is mainly used to aggregate market and sector structure:

- market advance / decline counts
- market limit-up / limit-down counts
- sector advance ratio
- sector above-MA ratios
- sector new-high ratios
- sector limit-up / limit-down counts
- leader-vs-tail and large-vs-small diffusion inside a sector

Stock-level relative strength may be useful later for a refined metric such as
"percentage of stocks outperforming the benchmark", but it is not required for
the first market-state or main-line sector loop.

## Data Readiness Priorities

Before formal backtests, finish these in order:

1. Confirm or build a stock-to-sector mapping for all 30 Shenwan sectors.
2. Audit stock raw close, `close_hfq`, `hfq_factor`, and `pct_chg_raw` coverage.
3. Compute market emotion fields from stock rows.
4. Compute sector internal breadth fields for all 30 sectors.
5. Compute market and sector volume / amount strength fields.
6. Only then design and confirm the market-state and main-line sector factor combinations.

## External Factor Policy

Do not add JoinQuant or other external factor libraries by default.

Use external sources only if the current price, amount, breadth, emotion, and
industry-structure evidence cannot explain important historical phases after
the first complete data-readiness pass.

