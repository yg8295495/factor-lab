# Research Index

> Start here before reading long experiment reports.

| ID | Topic | Method | Status | Key Result | Detail |
|----|-------|--------|--------|------------|--------|
| EXP-001 | Sector strength v1 | Static single-point score: RS rank, win rate, volume ratio, consistency | Deprecated | Top-3 hit rate 8.3%; biased toward defensive sectors | `behavior_scoring_v1.md` |
| EXP-002 | W1/W2/W3 behavior score v0.1 | Loop-based rolling sector behavior score | Current base | 130 rebalances, +60.5% excess, 53.1% win rate in bull phases | `behavior_scoring_v1.md` |
| EXP-003 | Market state-aware behavior score | Base W1/W2/W3 + market state filter + sector breadth/amount confirmation | Design draft | Compare EXP-002 baseline vs state filter vs state + sector confirmation; evaluate per-state performance | `experiments/EXP-003-breadth-enhanced-behavior-score.md` |
| EXP-004 | Market state recognition v0 | 5-dimension rule-based scoring → MAIN_UP_CONFIRMED/REBOUND/CROWDING/RETREAT/CHAOS | Complete | 6 iterations (v0→v0.5). Bear false MAIN_UP 3.0%, bull MAIN_UP recall 10.5%. Diagnostics confirmed rule boundary reached. | `experiments/EXP-004-market-state-recognition-v0.md` |
| REF-001 | Historical phase leadership | 13 market phases and sector leadership review | Reference | Provides bull/bear phase context and sector leadership examples | `phase_sector_leadership_v1.md` |
| REF-002 | Factor scope v1 | Market-state vs main-line sector factor role split | Reference | Existing factor pool is enough for v1; prioritize data mapping and second-pass aggregation | `factor_scope_v1.md` |
| DATA-001 | Data readiness v1 | Stock / sector / mapping / second-pass field audit | Complete | All 6 pre-backtest tasks done: mapping 94% covered, pct_chg_raw 97.3% populated, market emotion + sector breadth + amount_ratio 30/30 industries written | `data_readiness_v1.md` |
| DATA-002 | Data runtime spec v1 | Provider adapters, SQL/storage contract, second-pass SOP | Reference | External tools such as a-stock-data are adapters; factor-lab owns normalization, persistence, validation, and workflow | `data_runtime_spec_v1.md` |
| REF-003 | ETF flow as signal | Evaluate tushare etf_share_size as future volume signal enhancer | Reference | ETF净申赎是真实资金流动指标（非大单猜测），建议v1暂不做，等回测基线建立后作为改进方向 | `etf_flow_as_signal_v1.md` |

## Rules

- Add one row before or during each new experiment.
- Keep this file short.
- Put full details in `docs/research/experiments/`.
- Promote only durable conclusions to `LESSONS.md`.
