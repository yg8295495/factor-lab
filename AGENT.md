# AGENT.md — AI Startup Router

> Purpose: fast orientation for a new AI session. Keep this file short.
> Default startup should read only this file and `PLAN.md`.

## Module Scope

`factor-lab` is the lightweight factor research submodule of the broader AI-DMS / Market State Engine.

This repo only focuses on script-verifiable work:

- Layer 1: raw market data needed by factors
- Layer 2: single factors and cross-section features
- Layer 3: factor combinations / structure evidence
- Layer 9: lightweight chart inspection

Out of scope for this repo for now:

- macro research
- capex / fundamentals narrative research
- reports / news / NLP expectation layer
- final AI-DMS state explanation layer

## Hard Rules

- Use the semi-wide SQLite design. Prefer appending daily fields to `market_daily_data`; do not split tables unless the data shape truly requires it.
- Benchmark symbol is `index.000985.SH`.
- Vectorized sector behavior scoring is forbidden for research conclusions.
- Backtests must use rolling evaluation. Static hit rate is not accepted as evidence.
- Keep experiments narrow: change one main variable, run loop-based rolling backtest, record the result.
- Do not read `docs/archive/` or `docs/human/` unless the user explicitly asks or the current task needs it.
- `codex.md` is deep background from a prior alignment conversation; do not read it by default.

## What To Read

| Task | Read |
|------|------|
| Current priority / next work | `PLAN.md` |
| Data fields, sources, adjustment policy | `docs/agent/00_data.md` |
| Factor definitions, Layer 2/3 boundaries, backtest rules | `docs/agent/01_factors.md` |
| Experiment workflow and known conclusions | `docs/agent/02_experiments.md`, then `docs/research/INDEX.md` / `LESSONS.md` |
| Strategy/portfolio discussion | `docs/agent/03_strategy.md` |
| Exact schema details | `docs/database_schema.md` |

## Core Commands

```bash
# Factor calculation
python3 -m backend.research.features.calculator

# Trusted behavior-score experiments
python3 backend/research/analysis/sector_behavior_score.py --rolling
python3 backend/research/analysis/sector_behavior_score.py --continuous

# Historical sector leadership analysis
python3 backend/research/analysis/sector_leadership.py

# Local app
./start.sh
```

## Documentation Workflow

For each new experiment:

1. Add or update one row in `docs/research/INDEX.md`.
2. Write the full record under `docs/research/experiments/EXP-xxx-*.md`.
3. Promote only durable conclusions to `docs/research/LESSONS.md`.
4. Keep `PLAN.md` focused on the current sprint, not historical detail.
