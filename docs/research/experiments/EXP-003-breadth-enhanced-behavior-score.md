# EXP-003 — Breadth-Enhanced Behavior Score

## Status

Planned.

## Hypothesis

Sector and market breadth can improve the W1/W2/W3 behavior score by filtering short-lived rebound volume and confirming true main-line participation.

## Baseline

Base model:

```text
loop-based W1/W2/W3 behavior score
```

Reference implementation:

```text
backend/research/analysis/sector_behavior_score.py
```

Trusted scorer:

```text
calc_sector_rolling_score()
```

## Candidate Inputs

- `above_ma20_ratio`
- `above_ma60_ratio`
- `new_high_20d_ratio`
- `rs_positive_ratio`
- `adv_count`
- `decl_count`
- `limit_up_count`
- `limit_down_count`
- `market_adv_ratio`

## Backtest Settings

To be filled before running:

- data range:
- asset pool:
- rebalance frequency:
- holding period:
- benchmark: `index.000985.SH`
- transaction cost assumption:
- baseline output file:
- experiment output file:

## Results

Pending.

## Conclusion

Pending.

## Next Step

Define the exact breadth adjustment formula and run `base` vs `base + breadth` with identical rolling settings.
