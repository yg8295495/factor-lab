# EXP-007 — State × Lifecycle Fusion

## Status

❌ **Complete (Negative)** — Variant E both sub-variants underperformed Variant D. Delta is an explanatory factor, not a trading filter. Industry behavior layer research now closed.

## Hypothesis

Variant D (state=position, score=ranking) is the current baseline. EXP-006B/C showed that **Delta = W2 - W3** is a lifecycle position factor orthogonal to Total Score — sectors with high Delta (Wash >> Launch) are "pre-launch" and produce different lifecycle curves than low-Delta sectors.

EXP-007 tests: **Adding Delta-based selection within state buckets improves Variant D's return and/or drawdown.**

Specifically:
- **CHAOS + Wash>>Launch** was the strongest combination (N=7, WinRate=85.7%, Excess=+5.3%)
- **CHAOS + Launch>>Wash** was poor (WinRate=41.7%)
- **CROWDING + Wash>>Launch** was negative (Excess=-1.1%, WinRate=33.3%)

## Baseline

**EXP-003 Variant D (CHAOS ≥ 6)**:
```
MAIN_UP_CONFIRMED → TOP 3
REBOUND           → TOP 2
CHAOS             → TOP 1 (total score ≥ 6)
CROWDING          → TOP 1
RETREAT           → 空仓
```

## Variant E Design

### Principle

```
State → position size
Total Score → ranking
Delta(W2-W3) → refine selection within ranking
```

### State × Delta Rules

| State | Total Score Rule | Delta Rule | Rationale |
|-------|-----------------|------------|-----------|
| MAIN_UP_CONFIRMED | TOP 3, any delta | No delta filter | Strong trend, Delta matters less |
| REBOUND | TOP 2, any delta | No delta filter | Too few samples (2 windows) |
| **CHAOS** | TOP 1 (≥ 6) | **Prefer Delta ≥ 0** (W2 ≥ W3) | Wash>>Launch + CHAOS is the strongest combo; Launch>>Wash underperforms |
| **CROWDING** | TOP 1 | **Prefer Delta < 2** (avoid Wash>>Launch) | Wash>>Launch was negative in CROWDING; Balanced/Wash>Launch were positive |
| RETREAT | 空仓 | — | — |

Note: for CHAOS with Delta < 0, fallback to holding the TOP 1 anyway if score ≥ 6 (same as Variant D baseline — the Delta rule is a preference, not a hard block, because sample sizes are small).

### Sensitivity Variants

| Sub-variant | CHAOS Delta rule | CROWDING Delta rule |
|-------------|:----------------:|:-------------------:|
| **E_primary** | Prefer Delta ≥ 0 (W2 ≥ W3) | Avoid Wash>>Launch (Delta < 2) |
| E_sens_hard | **Hard filter**: Delta < 0 → skip window | Avoid Wash>>Launch (Delta < 2) |
| E_sens_nocrowd | Prefer Delta ≥ 0 | No CROWDING delta filter |

## Backtest Settings

| Setting | Value |
|---------|-------|
| data range | same as EXP-003 (continuous rolling) |
| asset pool | 30 Shenwan sector indexes |
| rebalance frequency | 20 trading days |
| holding period | 20 trading days |
| benchmark | `index.000985.SH` |
| transaction cost | none in v1 |
| output file | `output/exp007_state_lifecycle_fusion.json` |

## Results

| Variant | Return | Excess | MaxDD | vs D Baseline |
|:--------|:-----:|:------:|:-----:|:-------------:|
| **D (baseline)** | **985.3%** | **+340.6%** | **-45.9%** | — |
| E_state_lifecycle | 377.8% | -267.0% | -50.7% | 🔴 far worse |
| E_sens_hard | 633.1% | -11.6% | -56.7% | 🔴 far worse |

**Analysis of failure:**
1. In CHAOS windows, many TOP1 sectors have Delta < 0. Forcing Delta ≥ 0 caused selection of lower-scored sectors.
2. EXP-006B's CHAOS × Wash>>Launch finding was based on only N=7 samples; it did not generalize to the full dataset.
3. Delta functions as a **retrospective explanation** (why a window won or lost) but not a **predictive filter** (which sector to pick next).

## Conclusion

**Delta is an explanatory factor, not a trading filter.** It can explain lifecycle position in hindsight but cannot be used for real-time sector selection.

The EXP-003/006/007 chain forms a complete research loop:
1. EXP-003: Discover alpha (Variant D framework)
2. EXP-006: Explain alpha (lifecycle curves, Delta as position factor)
3. EXP-007: Test explanation as a rule (failed — Delta is explanatory, not predictive)

**Industry behavior layer (Sector Leadership v1) is now closed.**

Forbidden path for future sessions: Do NOT try to use Delta(W2-W3) as a real-time sector selection filter. It is retrospective analysis only.

## Next Step

- ✅ Design, implement, and run Variant E (E_state_lifecycle + E_sens_hard)
- ✅ Compare against D baseline — both underperformed
- **Industry behavior layer closed. Move to upper-layer research.**

## Confirmation

- **confirmed by:** user
- **confirmation date:** 2026-06-05
- **confirmed scope:** Variant E design rules, Delta thresholds
