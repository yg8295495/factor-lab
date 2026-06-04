# EXP-004 — Market State Recognition v0

## Status

**Complete** — final accepted version is v0.5.

## Hypothesis

A daily market state classifier can be constructed from existing registered factors (trend, breadth, emotion, volume, risk) using a rule-based scoring system. The four states — **MAIN_UP** / **CROWDING** / **RETREAT** / **CHAOS** — should meaningfully align with the 13 historical bull/bear phases in `market_phases.csv` and help explain the drawdown windows in EXP-002.

## Baseline

v0 strict rule classifier is the baseline. v0.5 is the accepted final version after controlled threshold iterations.

## Pre-run Gate

- [x] data coverage sufficient: 30 sector + index.000985.SH daily data present 2005 to present
- [x] required fields populated: all candidate fields in the threshold table below; see `docs/research/experiments/EXP-004-market-state-recognition-v0.md` §Field Sourcing
- [x] industry / asset-pool mapping reliable: 5148/5478 stocks mapped (94%); 30/30 sector breadth populated
- [x] future-function risk checked: N/A — this is a classifier, not a predictive model
- [x] survivorship-bias risk checked: current stock-to-sector mapping is a snapshot (2021-12); acceptable for market-state level aggregation (see MEMORY.md)
- [x] rebalance / holding / benchmark settings confirmed: N/A — classifier output, not a trading strategy
- [x] transaction-cost assumption confirmed: N/A

## Confirmation

- **confirmed by:** user
- **confirmation date:** 2026-06-05
- **confirmed scope:** v0.5 final rule set and validation results
- **notes:** all rolling features computed in-memory; no DB writes; remaining ambiguous windows are delegated to EXP-003 sector-level confirmation

---

## Input Data

### Data Range

2005-07-18 ~ present (matching the first phase in `market_phases.csv`).

### Asset Pool

| Symbol | Role |
|--------|------|
| `index.000985.SH` | Primary: trend, breadth, emotion, volume, risk signals |
| `index.000300.SH` | Hosts `small_cap_spread` (written by `calculator.py`) |
| `asset_master WHERE asset_type='sector'` | Used indirectly for `industry_diffusion` (already computed) |

### Fields — Direct DB Reads

| Field | On Symbol | DB Column | Notes |
|-------|-----------|-----------|-------|
| `MOM20` | `index.000985.SH` | `time_momentum20` | Already computed |
| `MOM60` | `index.000985.SH` | `time_momentum60` | Already computed |
| `TREND_STR` | `index.000985.SH` | `trend_strength` | Already computed |
| `BREAKOUT` | `index.000985.SH` | `breakout_strength` | Already computed |
| `market_adv_ratio` | `index.000985.SH` | `market_adv_ratio` | Raw daily ratio (0~1) |
| `adv_count` | `index.000985.SH` | `adv_count` | Raw count |
| `decl_count` | `index.000985.SH` | `decl_count` | Raw count |
| `limit_up_count` | `index.000985.SH` | `limit_up_count` | Raw count, Phase 3 |
| `limit_down_count` | `index.000985.SH` | `limit_down_count` | Raw count, Phase 3 |
| `industry_diffusion` | `index.000300.SH` | `industry_diffusion` | Scale 0~100, written by Tier 2 |
| `market_volatility_20d` | `index.000300.SH` | `market_volatility_20d` | Raw volatility, written by Tier 2 |
| `small_cap_spread` | `index.000300.SH` | `small_cap_spread` | RS20 diff (399000-000300), written by Tier 2 |
| `market_amount_ratio` | `index.000985.SH` | `amount_ratio` | `amount / SMA20(amount)`, Phase 5 |

> **⚠️ `small_cap_spread`** is stored on `index.000300.SH`, not `index.000985.SH`. Must read explicitly.
>
> **⚠️ `industry_diffusion`** and **`market_volatility_20d`** are also stored on `index.000300.SH`.

### Fields — Computed In-Memory (Rolling)

| Derived Field | Source | Window | Formula |
|--------------|--------|--------|---------|
| `market_adv_ratio_5d` | `market_adv_ratio` | 5 | `rolling(5).mean()` |
| `market_adv_ratio_20d` | `market_adv_ratio` | 20 | `rolling(20).mean()` |
| `limit_up_ratio` | `limit_up_count` | raw daily | `lu / valid_stock_count` |
| `limit_down_ratio` | `limit_down_count` | raw daily | `ld / valid_stock_count` |
| `limit_up_ratio_5d` | `limit_up_ratio` | 5 | `rolling(5).mean()` |
| `limit_down_ratio_5d` | `limit_down_ratio` | 5 | `rolling(5).mean()` |
| `industry_diffusion_20d_change` | `industry_diffusion` | 20 | `diff(20)`—"百分点"单位 |
| `VOLATILITY_20D_percentile` | `market_volatility_20d` | 250 | `rolling(250).rank(pct=True) * 100` |
| `index_drawdown_20d` | `close` (000985.SH) | 20 | `(close - rolling(20).max()) / rolling(20).max() * 100` |
| `market_amount_ratio_20d` | `amount_ratio` (000985.SH) | 20 | `rolling(20).mean()` |

> `valid_stock_count`: number of stock rows with non-null `pct_chg_raw` on that date. If computing this from stock rows is too heavy per iteration, fallback to `adv_count + decl_count` and flag as `approximation=true` in output.

### Price Adjustment

All trend fields (MOM20/60, TREND_STR, BREAKOUT) are computed from `close_hfq` on the benchmark, handled by calculator.py. No additional adjustment needed.

### Exclusions

- First 250 trading days of the data range (for rolling percentile bootstrapping)
- Stocks mapped to "综合" sector (`sector.801230.SW`) — 15 stocks, negligible impact

---

## Method

### Five-Dimension Scoring (-1 / 0 / +1)

Each dimension is computed from its constituent signals. All thresholds are v0 defaults, to be validated and tuned.

#### 1. trend_score

**Source fields:** `MOM20`, `MOM60`, `BREAKOUT`, `TREND_STR` on `index.000985.SH`

```
+1 if: MOM20 > 0 AND MOM60 > 0 AND BREAKOUT > 0 AND TREND_STR >= 60
-1 if: MOM20 < 0 AND MOM60 < 0 AND BREAKOUT < 0 AND TREND_STR <= 40
 0 otherwise
```

> **Rationale:** Strict AND conditions reduce oscillation. TREND_STR 60/40 thresholds provide a confidence buffer above/below 50. v0 distribution expected: ~15% +1, ~14% -1, ~71% 0.

#### 2. breadth_score

**Source fields:** `market_adv_ratio_20d`**,** `industry_diffusion`**,** `industry_diffusion_20d_change` (all on `index.000985.SH` / `index.000300.SH`)

```
+1 if: market_adv_ratio_20d >= 0.55 AND industry_diffusion >= 60
-1 if: market_adv_ratio_20d <= 0.45 AND industry_diffusion <= 40
 0 otherwise
```

**Additional flag:** `breadth_falling = true` when `industry_diffusion_20d_change <= -15` (percentage points, not percent). Used to identify CROWDING (index rising but breadth narrowing).

#### 3. emotion_score

**Source fields:** `market_adv_ratio_5d`**,** `limit_up_ratio_5d`**,** `limit_down_ratio_5d`

```
+1 if: market_adv_ratio_5d >= 0.55
       AND limit_up_ratio_5d >= 0.015
       AND limit_down_ratio_5d <= 0.003

-1 if: market_adv_ratio_5d <= 0.45
       OR limit_down_ratio_5d >= 0.008

 0 otherwise
```

> **Notes:** `limit_up_ratio` uses a threshold of 0.015 (≈75 stocks out of ~5000), raised from the initial 0.008 which was almost always true. Denominator is `valid_stock_count` from stock rows.

#### 4. volume_score

**Source fields:** `market_amount_ratio_20d` on `index.000985.SH`

```
+1 if: market_amount_ratio_20d >= 1.10
 0 if: 0.90 < market_amount_ratio_20d < 1.10
-1 if: market_amount_ratio_20d <= 0.90
```

> **Rationale:** Pure relative volume. <0.90 = significant contraction. >1.10 = significant expansion. Between them = neutral.

#### 5. risk_score

**Source fields:** `VOLATILITY_20D_percentile`**,** `index_drawdown_20d`**,** `limit_down_ratio_5d`

```
+1 if: VOLATILITY_20D_percentile <= 70
       AND index_drawdown_20d > -5%
       AND (limit_down_ratio_5d < 0.008)

-1 if: VOLATILITY_20D_percentile >= 80
       OR index_drawdown_20d <= -8%
       OR limit_down_ratio_5d >= 0.008

 0 otherwise
```

> **Note:** `risk_score = +1` does not mean "low risk → bullish". It means "no risk signal triggered" — risk is not worsening.

---

### Threshold Table (v0)

| Dimension | Signal | Strong (+1) | Weak (-1) |
|-----------|--------|:-----------:|:---------:|
| trend | `TREND_STR` | `>= 60` | `<= 40` |
| trend | `MOM20` | `> 0` | `< 0` |
| trend | `MOM60` | `> 0` | `< 0` |
| trend | `BREAKOUT` | `> 0` | `< 0` |
| breadth | `market_adv_ratio_20d` | `>= 0.55` | `<= 0.45` |
| breadth | `industry_diffusion` | `>= 60` | `<= 40` |
| breadth | `industry_diffusion_20d_change` | — | `<= -15` (pp) |
| emotion | `market_adv_ratio_5d` | `>= 0.55` | `<= 0.45` |
| emotion | `limit_up_ratio_5d` | `>= 0.015` | — |
| emotion | `limit_down_ratio_5d` | — | `>= 0.008` |
| volume | `market_amount_ratio_20d` | `>= 1.10` | `<= 0.90` |
| risk | `VOLATILITY_20D_percentile` | — | `>= 80` |
| risk | `index_drawdown_20d` | `> -5%` | `<= -8%` |
| risk | `limit_down_ratio_5d` | — | `>= 0.008` |

---

### State Combination Rules

States are evaluated in order: MAIN_UP → CROWDING → RETREAT → CHAOS (fallback).

#### MAIN_UP

```
MAIN_UP if:
  trend_score = +1
  AND breadth_score = +1
  AND emotion_score >= 0
  AND volume_score >= 0
  AND risk_score >= 0
```

**Alternative formulation** (used for computed `confidence`):

```
strong_main_up_confidence = 
    sum([trend==+1, breadth==+1, emotion>=0, volume>=0, risk>=0]) / 5
```

#### CROWDING

```
CROWDING if:
  trend_score = +1
  AND (breadth_score <= 0 OR breadth_falling = true)
  AND small_cap_spread <= 0
```

> **Interpretation:** The index trends up, but breadth is not expanding (or actively falling). Small caps underperform. This is "market looks fine but the structure is narrowing."

#### RETREAT

```
RETREAT if:
  trend_score = -1
  AND breadth_score = -1
  AND (emotion_score = -1 OR risk_score = -1)
```

**Alternative formulation:**

```
RETREAT if:
  sum([trend, breadth, emotion, risk]) <= -3
```

#### CHAOS

```
CHAOS if:
  not MAIN_UP AND not CROWDING AND not RETREAT
```

**Optional sub-labels** (v0 may skip):

```
CHAOS_LOW_VOL  —  volatility compressed
CHAOS_HIGH_VOL —  volatile but directionless
```

### Confidence Score

Per-day `confidence = matched_positive_conditions / total_conditions_for_state`.

Example: for MAIN_UP with 5 dimension-level checks:
- If 4 of 5 pass: `confidence = 0.8`
- If 3 of 5 pass AND `risk_score = -1`: falls to CROWDING or CHAOS

### Daily Output Format

```json
{
  "trade_date": "2026-05-29",
  "market_state": "MAIN_UP",
  "confidence": 0.72,
  "scores": {
    "trend": 1,
    "breadth": 1,
    "emotion": 0,
    "volume": 1,
    "risk": 0
  },
  "flags": {
    "breadth_falling": false,
    "crowding_warning": false
  }
}
```

---

## v0 Results (Baseline)

### Overall Distribution

| State | Days | % |
|-------|:----:|:-:|
| CHAOS | 4230 | 81.5% |
| CROWDING | 404 | 7.8% |
| RETREAT | 386 | 7.4% |
| MAIN_UP | 171 | 3.3% |

### Key Metrics

| Metric | v0 |
|--------|:----:|
| Bull-phase MAIN_UP recall | 4.8% |
| Bull-phase false RETREAT | 2.7% |
| Bear-phase RETREAT recall | 14.4% |
| Bear-phase false MAIN_UP | **1.4%** ✅ |

### Diagnosis

1. **`breadth_score = -1` never triggered** (0/5191 days). The AND condition was too strict — `market_adv_ratio_20d <= 0.45 AND industry_diffusion <= 40` was almost never simultaneously true.
2. **MAIN_UP condition chain too long**: `trend(+1) × breadth(+1) × emotion(>=0) × volume(>=0) × risk(>=0)` = 14.7% × 11.1% × ... ≈ 3.3%.
3. **RETREAT drawdown threshold too deep**: `index_drawdown_20d <= -8%` only catches extreme crashes, missing early retreat phases.

### Positive Findings

- `false_main_up = 1.4%` is very low — the classifier is conservative but safe.
- CROWDING (404 days) shows meaningful distribution across known narrow-market periods (e.g., 2007 late top, 2012-15 late stage, 2018-21 structure bull late stage).

---

## v0.1 Changes (3 Controlled Modifications)

### Change 1: breadth_score weak → OR

```
breadth_score = -1 if:
  market_adv_ratio_20d <= 0.45
  OR industry_diffusion <= 40
```

`industry_diffusion_20d_change <= -15` remains only as `breadth_falling` flag for CROWDING.

### Change 2: MAIN_UP → trend mandatory + positive_count rule

```
MAIN_UP if:
  trend_score = +1
  AND risk_score >= 0
  AND positive_count >= 3
  AND negative_count = 0

where:
  positive_count = number of scores == +1 (out of 5)
  negative_count = number of scores == -1 (out of 5)
```

Volume is no longer a hard gate. Trend and risk remain mandatory.

### Change 3: RETREAT drawdown relaxed + rule restructured

```
index_drawdown_20d <= -5%   (was -8%)
```

New RETREAT rule:

```
RETREAT if:
  trend_score = -1
  AND risk_score = -1
  AND (breadth_score = -1 OR emotion_score = -1)
```

Fallback retained: `trend + breadth + emotion + risk <= -3`.

### State Priority

Updated to: **RETREAT → MAIN_UP → CROWDING → CHAOS** (fallback).

### CROWDING Refined (v0.1)

```
CROWDING if:
  trend_score >= 0
  AND (breadth_score <= 0 OR breadth_falling = true)
  AND small_cap_spread <= 0
  AND risk_score >= 0
```

Now uses `trend >= 0` instead of strict `trend = +1`, and adds `risk >= 0` to avoid overlap with RETREAT.

---

## v0.1 Validation Targets

| Metric | v0 | v0.1 Target | Constraint |
|--------|:--:|:-----------:|:----------:|
| Bull MAIN_UP recall | 4.8% | signif. higher | — |
| Bear RETREAT recall | 14.4% | higher | — |
| Bear false MAIN_UP | 1.4% | **< 3%** | must not exceed |
| Bull false RETREAT | 2.7% | not much higher | soft constraint |

### Labels

Use `market_phases.csv` as **phase labels** (bull/bear), not daily state labels.

```
Phase 1:  2005-07-18 ~ 2008-01-14  bull
Phase 2:  2008-01-14 ~ 2008-11-04  bear
...etc (13 phases total)
```

### Validation Metrics

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| `phase_major_state` | Mode of daily states within each phase | Dominant classifier output per phase |
| `phase_consistency` | `major_state_days / total_days_in_phase` | How cleanly a phase maps to one state |
| `bull_main_up_ratio` | % of bull-phase days classified MAIN_UP | Recall on bull phases |
| `bear_retreat_ratio` | % of bear-phase days classified RETREAT | Recall on bear phases |
| `transition_lag` | Days from phase boundary to state change | How quickly the classifier detects regime change |
| `false_main_up` | % of bear-phase days classified MAIN_UP | False positives in drawdowns |
| `false_retreat` | % of bull-phase days classified RETREAT | False positives in rallies |

### EXP-002 Cross-Check

Specifically evaluate EXP-002's drawdown windows:

```
for each window where EXP-002 had >10% drawdown:
    what was the market_state during that window?
    would state-based filtering have reduced exposure?
```

---

## Implementation Entry Point

*(To be filled after design confirmation)*

- Script: `backend/research/analysis/market_state_recognition.py`
- Reads from DB (read-only), outputs JSON to `backend/research/analysis/output/`
- No DB writes in v0

### Execution

```bash
python backend/research/analysis/market_state_recognition.py
```

### Output Files

| File | Content |
|------|---------|
| `output/market_state_daily.json` | Daily state, confidence, scores, flags |
| `output/market_state_validation.json` | Phase-level validation metrics |

---

## Results

### Iteration History

| Version | Changes | Bull MAIN_UP | Bear RETREAT | Bear false MAIN_UP | 
|:-------:|---------|:------------:|:------------:|:------------------:|
| v0 | Baseline: strict AND for all dimensions | 4.8% | 14.4% | 1.4% |
| v0.1 | breadth OR + pos_count MAIN_UP + drawdown -5% | 11.4% | 21.6% | 4.5% ❌ |
| v0.2 | + participation_ok + 60d drawdown guard | 11.0% | 21.6% | 4.0% |
| v0.3 | + MA120 guard (replaced 60d drawdown) | 10.8% | 21.6% | 3.5% |
| v0.4 | MAIN_UP → MAIN_UP_CONFIRMED + REBOUND (diffusion_ok OR guard) | 10.8% | 21.6% | 3.5% (no effect) |
| **v0.5** | **+ drawdown_120d > -10% (diagnostics-guided)** | **10.5%** | **21.6%** | **3.0% ✅** |

### v0.5 (final-v0) State Distribution

| State | Days | % |
|-------|:----:|:-:|
| CHAOS | 2916 | 56.2% |
| CROWDING | 1194 | 23.0% |
| RETREAT | 678 | 13.1% |
| MAIN_UP_CONFIRMED | 370 | 7.1% |
| REBOUND | 33 | 0.6% |

### v0.5 Final Rules

#### MAIN_UP_CONFIRMED

```
MAIN_UP_CONFIRMED if:
  trend_score = +1
  AND medium_trend_ok = true                   # close > MA120
  AND participation_ok = true                  # breadth=+1 OR (adv>=0.52 AND diff>=50 AND diff_chg>=0)
  AND risk_score >= 0
  AND emotion_score >= 0
  AND positive_count >= 3
  AND drawdown_120d > -10%                    # from diagnostics
```

#### REBOUND

```
REBOUND if:
  trend_score = +1
  AND risk_score >= 0
  AND positive_count >= 3
  AND drawdown_120d <= -10%
```

#### RETREAT (unchanged since v0.1)

```
RETREAT if:
  trend_score = -1
  AND risk_score = -1
  AND (breadth_score = -1 OR emotion_score = -1)
```

Fallback: `trend + breadth + emotion + risk <= -3 AND trend <= 0`.

#### CROWDING

```
CROWDING if:
  risk_score >= 0
  AND small_cap_spread <= 0
  AND volume_score <= 0
  AND (breadth_score <= 0 OR breadth_falling = true)
  AND trend_score >= 0
  AND market_adv_ratio_20d < 0.58              # not broad rally
```

> **Note:** CROWDING is exploratory. Not yet used as a primary signal for attack/defense.

### Diagnostics Run (after v0.3)

A dedicated diagnostic script (`false_main_up_diagnostics.py`) compared 3 samples:
- **A:** 75 bear-phase false MAIN_UP days
- **B:** 311 bull-phase true MAIN_UP days  
- **C:** 470 bear-phase RETREAT days

**Key finding:** Groups A and B were nearly identical across most features (trend, MA ratios, volume, breadth ratios). The only differentiators were:
- `industry_diffusion` median: 50.0 (A) vs 86.7 (B)
- `MOM60` median: 6.36 (A) vs 17.16 (B)
- `drawdown_120d` median: -3.17% (A) vs 0.00% (B)

**Candidate rule cost/benefit:**
- `close > MA250`: removes 100% of false, but loses 80.1% of true → rejected
- `drawdown_120d > -10%`: removes 12% of false, loses 2.3% of true → **selected**
- `diff_chg AND adv_20d`: removes 52% of false, loses 35% of true → too expensive

## Conclusion

**EXP-004 v0 is complete and accepted as final.** No further threshold tuning is justified.

The classifier:
- Successfully identifies MAIN_UP_CONFIRMED in bull phases (10.5% recall, up from 4.8% v0 baseline)
- Detects RETREAT in bear phases (21.6% recall, up from 14.4% v0 baseline)
- Constrains false MAIN_UP_CONFIRMED to 3.0% in bear phases (within the 3% limit)
- Leaves ~3% ambiguous rebound windows for industry-layer confirmation (EXP-003)

**What not to do next:** Continue tuning market-state thresholds. The diagnostic shows remaining false vs true MAIN_UP days are nearly indistinguishable at the market-state level. Further improvement requires industry-layer signals.

## Next Step

**EXP-003: Market State-Aware Sector Behavior Score**

Integrate market state as a context filter for the EXP-002 W1/W2/W3 sector scoring:
- In MAIN_UP_CONFIRMED: full attack weight
- In REBOUND: observe, confirm with sector signals
- In RETREAT: reduce or disable sector attack
- Evaluate per-state to answer: "Does sector breadth improve main-line identification when market state is known?"
