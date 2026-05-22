# 02_experiments.md — Experiment Workflow

> Read this before changing factor formulas, scoring rules, or backtests.

## Goal

The repo should preserve research memory without forcing every new AI session to load long historical reports.

Default reading order:

1. `docs/research/INDEX.md`
2. `docs/research/LESSONS.md`
3. Only the specific experiment file if needed

## Experiment Loop

Every experiment should follow this control flow:

```text
hypothesis -> one main change -> loop-based rolling backtest -> JSON output -> experiment note -> lessons update
```

Rules:

- Change one major variable at a time.
- Use loop-based rolling backtest.
- Compare against a clearly defined baseline.
- Store full details in one experiment file.
- Promote only durable conclusions to `LESSONS.md`.

## File Layout

```text
docs/research/INDEX.md                 # table of all experiments
docs/research/LESSONS.md               # distilled durable lessons
docs/research/experiments/EXP-xxx.md   # full single-experiment notes
```

Existing long reports may remain in `docs/research/` as source material, but new sessions should start from `INDEX.md` and `LESSONS.md`.

## Existing Durable Conclusions

- Static single-point sector strength scoring failed and is deprecated.
- W1/W2/W3 loop-based behavior scoring is the current validated base.
- Vectorized behavior scoring is forbidden for conclusions.
- Rolling backtest quality matters more than static top-3 hit rate.
