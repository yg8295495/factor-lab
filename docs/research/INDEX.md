# Research Index

> Start here before reading long experiment reports.

| ID | Topic | Method | Status | Key Result | Detail |
|----|-------|--------|--------|------------|--------|
| EXP-001 | Sector strength v1 | Static single-point score: RS rank, win rate, volume ratio, consistency | Deprecated | Top-3 hit rate 8.3%; biased toward defensive sectors | `behavior_scoring_v1.md` |
| EXP-002 | W1/W2/W3 behavior score v0.1 | Loop-based rolling sector behavior score | Current base | 130 rebalances, +60.5% excess, 53.1% win rate in bull phases | `behavior_scoring_v1.md` |
| EXP-003 | Breadth-enhanced behavior score | Base W1/W2/W3 + sector/market breadth adjustment | Planned | Compare base vs base+breadth | `experiments/EXP-003-breadth-enhanced-behavior-score.md` |
| REF-001 | Historical phase leadership | 13 market phases and sector leadership review | Reference | Provides bull/bear phase context and sector leadership examples | `phase_sector_leadership_v1.md` |
| REF-002 | Factor scope v1 | Market-state vs main-line sector factor role split | Reference | Existing factor pool is enough for v1; prioritize data mapping and second-pass aggregation | `factor_scope_v1.md` |
| DATA-001 | Data readiness v1 | Stock / sector / mapping / second-pass field audit | Running | Stock rows mostly present; stock-to-sector mapping absent; emotion and full-sector breadth need recomputation | `data_readiness_v1.md` |
| DATA-002 | Data runtime spec v1 | Provider adapters, SQL/storage contract, second-pass SOP | Reference | External tools such as a-stock-data are adapters; factor-lab owns normalization, persistence, validation, and workflow | `data_runtime_spec_v1.md` |

## Rules

- Add one row before or during each new experiment.
- Keep this file short.
- Put full details in `docs/research/experiments/`.
- Promote only durable conclusions to `LESSONS.md`.
