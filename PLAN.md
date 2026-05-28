# PLAN.md — Current Sprint

## Current Focus

Stabilize the factor-research workflow after full-A data ingestion:

- Keep documentation lightweight for new AI sessions.
- Build a repeatable experiment loop for Layer 2 factors and Layer 3 combinations.
- Current research direction: finish data readiness for market-state and main-line sector recognition before formal factor-combination backtests.
- Use the existing registered factor pool first; do not expand external factors until current data-derived factors are audited.

## Immediate Tasks

- [x] Reorganize AI guidance into short startup docs plus research index/lessons.
- [x] Freeze the experiment record template under `docs/research/experiments/`.
- [x] Define the research memory and experiment confirmation workflow.
- [x] Record the first-pass factor scope decision.
- [x] Audit stock-to-sector mapping coverage for all 30 Shenwan sectors.
- [x] Audit raw stock fields needed for breadth, emotion, and amount aggregation.
- [x] Define data runtime spec and provider-adapter SOP.
- [ ] Design second-pass calculations for market emotion, sector breadth, and amount strength.
- [ ] After data readiness, define the market-state and main-line sector combination backtests.

## Do Not Track Here

- One-off data collection logs
- Long experiment reports
- Archived data-source troubleshooting

Those belong in `docs/archive/` or `docs/research/experiments/`.
