# 02_experiments.md — Experiment Workflow

> Read this before changing factor formulas, scoring rules, or backtests.

## Goal

The repo should preserve research memory without forcing every new AI session to load long historical reports.

Default reading order:

1. `docs/research/MEMORY.md`
2. `docs/research/INDEX.md`
3. `docs/research/LESSONS.md`
4. Only the specific experiment or archive file if needed

## Experiment Loop

Every experiment should follow this control flow:

```text
idea -> data audit -> experiment design -> user confirmation -> implementation -> run -> result note -> lessons promotion
```

Rules:

- Do not run a formal backtest or write a conclusion before the data audit and experiment design are confirmed.
- Read-only data audits are allowed before confirmation.
- Unconfirmed pilots must not be promoted into `INDEX.md`, `LESSONS.md`, or experiment conclusions.
- Change one major variable at a time.
- Use loop-based rolling backtest.
- Compare against a clearly defined baseline.
- Store full details in one experiment file.
- Promote only durable conclusions to `LESSONS.md`.

Before implementation, the experiment record must answer:

- Is the data coverage sufficient for the proposed asset pool and date range?
- Are required fields populated and using the right price adjustment policy?
- Is the industry / asset-pool mapping reliable enough for the test?
- What future-function or survivorship-bias risks remain?
- Are rebalance frequency, holding period, benchmark, and transaction-cost assumptions confirmed?

## File Layout

```text
docs/research/MEMORY.md                # short date/keyword navigation memory
docs/research/INDEX.md                 # table of all experiments
docs/research/LESSONS.md               # distilled durable lessons
docs/research/experiments/EXP-xxx.md   # full single-experiment notes
docs/archive/                          # one-off source tests and troubleshooting
```

Existing long reports may remain in `docs/research/` as source material, but new sessions should start from `MEMORY.md`, `INDEX.md`, and `LESSONS.md`.

## Existing Durable Conclusions

- Static single-point sector strength scoring failed and is deprecated.
- W1/W2/W3 loop-based behavior scoring is the current validated base.
- Vectorized behavior scoring is forbidden for conclusions.
- Rolling backtest quality matters more than static top-3 hit rate.
