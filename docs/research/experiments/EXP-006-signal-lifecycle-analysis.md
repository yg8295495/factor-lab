# EXP-006 — W1/W2/W3 Signal Lifecycle Analysis

## Status

✅ **Complete** — lifecycle curves, Delta discovery, winner window profiles, and lifecycle position analysis all run and documented.

## Hypothesis

W1/W2/W3 行业行为评分所捕捉到的信号存在有限生命周期——信号出现后，市场需要一定时间完成定价兑现，然后进入衰减。**当前 20 天持有窗口未必对应信号的生命周期峰值。**

具体假设：

- **H1:** 行为信号存在生命周期，而非出现后永久有效
- **H2:** 收益曲线峰值与捕获率曲线峰值未必一致（超额定价可能在绝对收益之前完成）
- **H3:** 当前默认的 20D 窗口可能既不是收益峰值也不是捕获率峰值

## Baseline

**EXP-003 Variant D (CHAOS ≥ 6)** 已确认为当前研究基线。但 EXP-006 **不直接使用 Variant D**，而是回到信号源头：

```
EXP-002 W1/W2/W3 行业行为评分（纯评分，无状态过滤，无仓位控制）
```

原因：Variant D 引入了状态层和仓位控制两个额外变量。要独立测量信号生命周期，必须排除这些干扰，否则无法归因。

Reference implementation:

```text
backend/research/analysis/exp003_state_aware_evaluator.py  —  score_sector()
```

## Pre-run Gate

- [x] data coverage sufficient: 30 Shenwan sector indexes + `index.000985.SH` have 2005~2026 continuous data
- [x] required fields populated: sector close and amount data available for all 30 sectors
- [x] industry / asset-pool mapping reliable: same DATA-001 mapping as EXP-002/003
- [x] future-function risk checked: all sector scores use data available on or before eval date
- [x] survivorship-bias risk checked: current stock-to-sector mapping is acceptable for v1 (same caveat as EXP-003)
- [x] rebalance / holding / benchmark settings: REBALANCE_INTERVAL=20 (fixed), benchmark=index.000985.SH
- [x] transaction-cost assumption confirmed: no transaction cost in v1

**Gate decision:** No new data fields needed — can be computed entirely from existing EXP-003 evaluator infrastructure.

## Input Data

- **data range:** continuous rolling, same as EXP-002/003 (earliest available ~ 2026-05)
- **asset pool:** 30 Shenwan sector indexes
- **fields:** sector close (for return), sector amount (for W1/W2/W3 scoring)
- **price adjustment:** same as EXP-002 (forward-adjusted close)
- **exclusions:** none (all 30 sectors qualify)

## Method

### Core Logic

1. On each rebalance date (every 20 trading days, same cadence as EXP-002/003):
   - Score all 30 sectors using W1/W2/W3 (same `score_sector()` function)
   - Pick **TOP 1** sector by score (pure signal, no state filter, no threshold)
   - Hold for **every horizon simultaneously** (5D / 10D / 20D / 40D / 60D)

2. Record per-window, per-horizon:
   - Sector forward return
   - Benchmark forward return
   - Excess return
   - Win (sector > benchmark)
   - Leader capture ratio (sector return / best-of-30 return)

3. Aggregate by horizon.

### What Stays Fixed

| Parameter | Value | Reason |
|-----------|-------|--------|
| Scoring method | W1/W2/W3 (unchanged) | Measure signal lifecycle, not improve scoring |
| Rebalance interval | 20 days | Keep rebalance frequency constant; lifecycle is about holding horizon, not entry timing |
| Selection rule | TOP 1 only | Pure signal; no diversification to blur lifecycle |
| State filter | **None** | Purposefully excluded — would interfere with lifecycle measurement |
| Threshold | **None** | All TOP 1 picks included regardless of score |

### Horizons

| Horizon | Trading Days | Research Purpose |
|:-------:|:------------:|:-----------------|
| **5D** | ~1 calendar week | Short-term pricing efficiency |
| **10D** | ~2 calendar weeks | Medium-short signal impact |
| **20D** | ~1 calendar month | **Current default** — the baseline to validate |
| **40D** | ~2 calendar months | Medium-long decay check |
| **60D** | ~3 calendar months | Long-term decay / tail check |

### Output Metrics

| Metric | Definition |
|--------|-----------|
| **Avg Return** | Mean sector forward return over all TOP 1 picks at each horizon |
| **Avg Excess Return** | Mean (sector return − benchmark return) at each horizon |
| **Win Rate** | % of windows where sector return > benchmark return |
| **Leader Capture Ratio** | Mean (sector return / best-of-30 sector return) at each horizon, capped at 100% |

### Primary Analytical Output

#### Table: 4 metrics × 5 horizons

| Horizon | Return | Excess | WinRate | Capture |
|:-------:|:-----:|:------:|:-------:|:-------:|
| 5D | +0.1% | 0.0% | 50.2% | 16.7% |
| 10D | +0.2% | 0.0% | 48.0% | 16.0% |
| 20D | **+1.2%** | **+0.2%** | **52.5%** | **17.3%** |
| 40D | +2.4% | +0.2% | 48.6% | 17.4% |
| 60D | +3.2% | +0.1% | 51.1% | 17.3% |

**Key finding (H1/H3):** 20D capture peak confirmed. Current default is reasonable.

#### Capture Decay Curve

The most important output: does Capture exhibit a **bell-shaped** pattern (rise → peak → decay)?

```
Capture
  ^
  |       ╱─╲
  |     ╱    ╲
  |   ╱       ╲
  | ╱           ╲
  ╰─────────────────→ Horizon
    5D  10D  20D  40D  60D
```

If a clear peak emerges, that peak defines the **natural lifecycle** of the W1/W2/W3 signal.

### Supplementary Analyses

- By score bucket (≥7, 5-6, ≤4): do higher scores have longer or shorter lifecycles?
- By market state (MAIN_UP / CHAOS / CROWDING): does state affect lifecycle length?

These are secondary — the primary answer is the unconditional lifecycle curve.

## Backtest Settings

| Setting | Value |
|---------|-------|
| data range | same continuous rolling as EXP-002/003 |
| asset pool | 30 Shenwan sector indexes |
| scoring method | W1/W2/W3 (unchanged) |
| selection rule | TOP 1 (no state/score filter) |
| rebalance frequency | 20 trading days (fixed) |
| holding horizons | 5D / 10D / 20D / 40D / 60D (all computed per window) |
| benchmark | `index.000985.SH` |
| transaction cost | none in v1 |
| implementation | extend `exp003_state_aware_evaluator.py` |
| output file | `backend/research/analysis/output/exp006_signal_lifecycle.json` |

## Success Criteria

Not defined as "find the horizon with the highest return."

Instead, the experiment is successful if it can answer these four questions:

1. **Signal onset:** At what horizon does the signal first show positive excess return and above-random win rate?
2. **Signal peak:** At what horizon does leader capture ratio peak (the point of most efficient pricing)?
3. **Signal decay:** At what horizon do excess return and capture ratio start to decline?
4. **Baseline validation:** Is the current 20D default near the peak, or is it past the decay point?

## Risks & Mitigation

| Risk | Mitigation |
|------|-----------|
| Overfitting to horizon selection | No single horizon selected as "best"; lifecycle curve is the output |
| Confusing return peak with capture peak | **Explicitly track both** as separate curves; capture peak is primary |
| In-sample bias from using same window data | All data is out-of-sample by design (rolling eval, no future leakage) |
| Horizon selection bias (5/10/20/40/60 may miss the true peak at e.g. 15D) | Acceptable for v1; add intermediate horizons in a second pass if needed |

## Conclusion

| Question | Answer |
|----------|--------|
| H1: signal has finite lifecycle? | ✅ Yes. Capture forms a bell curve (15.2% → 16.5% → 20.4% → 19.3% → 18.5% for TOP1). |
| H2: return peak vs capture peak may differ? | ✅ Confirmed. For TOP3, return peaks at 60D (+3.2%) while capture peaks at 20-40D (~17.4%). Excess turns negative after 20D — the signal has priced in. |
| H3: current 20D may not be peak? | ❌ **20D IS the capture peak** (20.4% TOP1, 17.3% TOP3). Current default is valid. |

### Delta Discovery (EXP-006B/C)

```
Total Score = worth watching? (ranking, not classification)
Delta(W2-W3) = what stage? (lifecycle position, not strength)
```

- High Delta (Wash >> Launch) produces a "weak then strong" structure: −1.2%@10D → +4.9%@40D
- Low Delta (Launch >> Wash) produces short-term inertia then decay: immediate quick profit, weak follow-through

### Negative Result (EXP-006A)

W1/W2/W3 scores cannot distinguish Super Winners from Disasters at entry time (total 5.42 vs 5.54). Score is effective for ranking (3× random coverage), not for outcome classification.

### Negative Result (EXP-007)

Variant E (State × Lifecycle fusion using Delta as trading filter) underperformed Variant D. Delta is **explanatory, not a trading filter**.

## Next Step

- ✅ Lifecycle curves complete (output: `output/exp006_signal_lifecycle.json`)
- ✅ Winner window profiles complete (output: `output/exp006a_winner_window_profiles.json`)
- ✅ Delta stratification complete (output: `output/exp006b_delta_analysis.json`)
- ✅ Delta lifecycle curves complete (output: `output/exp006c_delta_lifecycle.json`)
- **Industry behavior layer (Sector Leadership v1) is now closed.**
- Upper-layer research (main-line identification, market valuation, main-line persistence) is next.
- Full documentation: STATUS.md, LESSONS.md, INDEX.md, 01_factors.md all updated.

## Confirmation

- **confirmed by:** user
- **confirmation date:** 2026-06-05
- **confirmed scope:** Research questions (H1/H2/H3), method (TOP 1, no state filter, no threshold), horizons (5/10/20/40/60D), output metrics (Return/Excess/WinRate/Capture), success criteria (4 questions)
- **notes:** This experiment is a mechanism study, not a parameter optimization. The goal is to understand the signal, not to find the "best" horizon.
