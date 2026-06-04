# Research Index

> Start here before reading long experiment reports.

| ID | Topic | Method | Status | Key Result | Detail |
|----|-------|--------|--------|------------|--------|
| EXP-001 | Sector strength v1 | Static single-point score: RS rank, win rate, volume ratio, consistency | ❌ Deprecated | Top-3 hit rate 8.3%; biased toward defensive sectors | `behavior_scoring_v1.md` |
| EXP-002 | W1/W2/W3 behavior score v0.1 | Loop-based rolling sector behavior score | ✅ Baseline | 253 windows, +142.5% excess vs index.000985.SH | `behavior_scoring_v1.md` |
| EXP-003 | Market state-aware behavior score | Base W1/W2/W3 + market state filter + sector breadth/amount confirmation | ✅ Complete | **Variant D (baseline):** +985.3% return, +340.6% excess, -45.9% maxDD. State=position framework validated. CHAOS=engine. | `experiments/EXP-003-breadth-enhanced-behavior-score.md` |
| EXP-004 | Market state recognition v0 | 5-dimension rule-based scoring -> 5 states | ✅ Complete | 6 iterations (v0->v0.5). Bear false MAIN_UP 3.0%. Rule boundary reached. | `experiments/EXP-004-market-state-recognition-v0.md` |
| EXP-006 | Signal lifecycle analysis | TOP1/TOP3 W1/W2/W3 -> 5/10/20/40/60D curves + Delta stratification | ✅ Complete | 20D capture peak. Delta=lifecycle position factor. Winner window profiles. | `backend/research/analysis/output/exp006*` |
| EXP-007 | State x Lifecycle fusion | Variant E: add Delta rules to Variant D | ✅ Complete (Negative) | Both E variants underperformed D. Delta is explanatory, not a trading filter. Industry behavior layer closed. | `experiments/EXP-007-state-lifecycle-fusion.md` |
| REF-001 | Historical phase leadership | 13 market phases and sector leadership review | Reference | Provides bull/bear phase context and sector leadership examples | `phase_sector_leadership_v1.md` |
| REF-002 | Factor scope v1 | Market-state vs main-line sector factor role split | Reference | Existing factor pool is enough for v1; prioritize data mapping and second-pass aggregation | `factor_scope_v1.md` |
| DATA-001 | Data readiness v1 | Stock / sector / mapping / second-pass field audit | Complete | All 6 pre-backtest tasks done | `data_readiness_v1.md` |
| DATA-002 | Data runtime spec v1 | Provider adapters, SQL/storage contract, second-pass SOP | Reference | External tools are adapters; factor-lab owns normalization, persistence, validation | `data_runtime_spec_v1.md` |
| REF-003 | ETF flow as signal | Evaluate tushare etf_share_size as future volume signal enhancer | Reference | ETF净申赎是真实资金流动指标，建议v1暂不做 | `etf_flow_as_signal_v1.md` |

## Rules

- Add one row before or during each new experiment.
- Keep this file short.
- Put full details in `docs/research/experiments/`.
- Promote only durable conclusions to `LESSONS.md`.
