# PLAN.md — Current Sprint

## Current Focus

EXP-003 first evaluator run complete. Key finding: state filtering reduces drawdown but is too conservative (MAIN_UP_CONFIRMED only 6.3% of windows). Needs analysis before iteration.

- Next: analyze EXP-003 results, decide whether to relax state rules or change Variant action logic.
- See `backend/research/analysis/output/exp003_state_aware_behavior_score.json` for preliminary numbers.

## Immediate Tasks

- [x] All 6 data readiness tasks (mapping, pct_chg_raw, emotion, breadth, amount_ratio).
- [x] Schema cleanup: rolled back 4 unauthorized columns.
- [x] **EXP-004: Market state recognition v0** — 6 iterations, finalized at v0.5.
- [x] EXP-003: design draft + first evaluator run.
- [ ] Analyze EXP-003 results and decide next iteration direction.
- [ ] Main-line sector recognition v0 (synthesis of market state + sector scoring).

## Do Not Track Here

- One-off data collection logs
- Long experiment reports
- Archived data-source troubleshooting

Those belong in `docs/archive/` or `docs/research/experiments/`.
