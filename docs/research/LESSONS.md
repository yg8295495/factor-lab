# Research Lessons

> Durable conclusions only. Keep this file short enough to read in new sessions.

## Methodology

- Rolling backtest is mandatory. Static hit rate is not accepted as research evidence.
- Change one main variable per experiment, otherwise attribution becomes unclear.
- Always compare a new scoring layer against a named baseline.
- Record data range, asset pool, rebalance frequency, holding period, benchmark, and transaction-cost assumption.

## Validated Conclusions

- Static single-point sector strength scoring failed. It tends to select low-volatility defensive sectors and misses early bull-market leaders.
- W1/W2/W3 behavior scoring is the current base model for sector rotation research.
- Vectorized sector behavior scoring is invalid for conclusions. The tested match rate against the loop version was only 34.7%.
- Sector rotation value should be judged by rolling excess return and phase-level performance, not only top-3 hit rate.

## Open Questions

- Can sector breadth filter W3 rebound volume from true main-line volume?
- Should `eval_offset` become dynamic rather than fixed?
- Can market breadth reduce bear-market drawdown without destroying bull-market participation?
- Which breadth features add orthogonal information instead of duplicating RS/Momentum?
