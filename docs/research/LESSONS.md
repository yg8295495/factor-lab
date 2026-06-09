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
- **W1/W2/W3 is effective for ranking, not for classification.** The score alone cannot distinguish Super Winner windows (total=5.42) from Disaster windows (total=5.54) at entry time. Use it for relative strength ranking across sectors, not for predicting outcome magnitude.
- **W1 has near-zero predictive power.** W1≈0 (+1.3%) vs W1>0 (+1.2%) show no difference. History beyond ~40 trading days is noise for sector momentum.
- **W2 has modest positive predictive power.** W2≥1.5 (+1.2%) outperforms W2≈0 (+0.2%). Wash/consolidation is a valid signal phase.
- **W3 is inversely related to forward return.** W3≤1 (+2.1%) vs W3≈max (+0.3%). W3 measures what has already happened, not what will happen. It functions as a stage identifier, not a buy signal.
- **W2 - W3 delta is a lifecycle position factor, not a strength factor.** High Delta (Wash >> Launch) produces a "weak then strong" return structure (−1.2% at 10D → +4.9% at 40D), confirming it measures stage of sector lifecycle, not filtering power.
- **Market state as on/off switch fails** (Variant B: -391% excess). **Market state as position size works** (Variant D: +341% excess).
- **CHAOS is the engine**: 46.4% of D's total return comes from CHAOS windows, not MAIN_UP. Value lies in identifying local themes in chaotic markets.
- **W1/W2/W3 direction filtering is validated** (Top3 coverage 31% vs random 10%), **but main-line identification strength remains unconfirmed** (capture ratio only 21.6%).
- **Delta(W2-W3) is an explanatory factor, not a trading filter.** Variant E (State × Lifecycle fusion) underperformed Variant D. Delta explains lifecycle position in hindsight but cannot be used for real-time sector selection.

## Open Questions

- **W1/W2/W3 behavior layer is now closed.** All three phases have been rigorously tested: W1=noise, W2=weak positive, W3=inverse. The model works for direction filtering (3× random) and lifecycle description, but not for main-line prediction. Further optimization of W1/W2/W3 has diminishing returns.
- **What orthogonal information sources can improve main-line identification?** — Sector breadth change rate, concentration, ETF flow, margin, valuation percentile, news coverage — all unstudied.
- **How long does a main line persist?** — Sector lifecycle ≠ main-line lifecycle.
- **What is the market macro-state?** — PE percentile, ERP, risk premium — all blank.

