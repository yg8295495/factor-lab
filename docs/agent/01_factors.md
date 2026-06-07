# 01_factors.md — Factor Definitions (v2.0)

> Read this for factor implementation, Layer 2/3 boundaries, or backtest decisions.
>
> This is the **frozen** version after Phase A completion.
> Do not modify factor definitions here without updating registry.py and calculator.py simultaneously.

---

## Layer Boundary

Layer 2 features are single-variable or direct cross-section measurements.
Layer 3 combines multiple Layer 2 features into structure evidence.

Do not make a Layer 2 feature claim a final market state by itself.

## Layer 2 Factor Registry (17 factors)

12 main factors + 5 auxiliary observation factors.
All algorithms confirmed via Phase A testing (2026-06-08).

### ① Trend / Momentum (3 main + 2 auxiliary = 5)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **RS20** | MAIN | `(P(t)/P(t-20))/(BM(t)/BM(t-20))` ratio, NOT excess | `rs20_cross` | 0.143 |
| **RS60** | AUX | `(P(t)/P(t-60))/(BM(t)/BM(t-60))` ratio | `rs60_cross` | 0.112 |
| **MOM20** | MAIN | `P(t)/P(t-20) - 1` raw return | `time_momentum20` | 0.188 |
| **MOM60** | MAIN | `P(t)/P(t-60) - 1` raw return | `time_momentum60` | 0.158 |
| **Accel** | MAIN | `MOM20(t) - MOM20(t-5)` unsmoothed momentum change | — (derived) | 0.177 |

### ② Volatility (1 main + 2 auxiliary = 3)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **Vol20** | MAIN | `std(ret[t-20:t])` per-sector independently | `volatility_20d` | 0.154 |
| **ATR20** | ❌ not registered | Replaced by Vol20 (higher IC) | — | 0.089 |
| **VolRatio** | AUX | `Vol20(t)/Vol20(t-20)` expansion/compression continuous | — (derived) | 0.114 |

### ③ Breadth / Diffusion (2 main + 1 auxiliary = 3)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **PartRate** | MAIN | `above_ma20_ratio` participation rate | `above_ma20_ratio` | 0.147 |
| **BreadthChg** | MAIN | `above_ma20_ratio(t) - above_ma20_ratio(t-5)` directional slope | — (derived) | 0.140 |
| **NewHigh** | AUX | `new_high_20d_ratio` absolute level | `new_high_20d_ratio` | 0.117 |

❌ Not registered: `NHChange` (0.079, too weak)

### ④ Price-Volume (1 main + 1 auxiliary = 2)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **AmtRatio** | MAIN | `amount(t)/SMA20(amount)` volume ratio | `amount_ratio` | 0.128 |
| **VolBkOut** | AUX | `AmtRatio(t) - SMA5(AmtRatio)` volume acceleration | — (derived) | 0.122 |

❌ Not registered: `PVD` (0.085, too sparse — 6/13 phases all zero)

### ⑤ Leadership / Structure (2 main + 1 auxiliary = 3)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **CR3** | MAIN | `sum(Top3_amt)/sum(all_amt)` cross-sector concentration | — (derived) | **0.232** |
| **CR5** | MAIN | `sum(Top5_amt)/sum(all_amt)` cross-sector concentration | — (derived) | 0.205 |
| **TopDisp** | AUX | `mean(Top3_ret) - mean(Bottom3_ret)` leadership strength | — (derived) | 0.150 |

❌ Not registered: `ReturnSkew` (top3-bottom3 equivalent, covered by TopDisp)

### ⑥ Style (MAIN — Layer 4预备)

| Factor | Category | Definition | Storage | Phase A Avg\|IC\| |
|:-------|:---------|:-----------|:--------|:----------------:|
| **SCSpread** | MAIN | `index.932000.SH ret20 - index.000300.SH ret20` small vs large cap | `small_cap_spread` | 0.205 |
| **AdvDecl** | MAIN | `adv_count_30sectors / total_valid` industry-level advance ratio | `adv_decline_ratio` | 0.181 |

---

## Factor Families

| Family | Factors | Data Basis |
|--------|---------|------------|
| Relative Strength | RS20, RS60 | `close` vs `index.000985.SH` |
| Momentum | MOM20, MOM60, Accel | `close` |
| Volatility | Vol20, VolRatio | `close` (per-sector) |
| Breadth | PartRate, BreadthChg, NewHigh | `above_ma20_ratio`, `new_high_20d_ratio` |
| Volume | AmtRatio, VolBkOut | `amount`, `amount_ratio` |
| Leadership | CR3, CR5, TopDisp | `amount` (cross-sector) |
| Style | SCSpread, AdvDecl | index + sector close |

## Data Price Basis

- **All sector and benchmark factors use `close`** (exchange-calculated index points, no adjustment needed).
- `close_hfq` is for stock-level use only. Not used for sector/index factors.

---

## Backtest Rules

- Use rolling evaluation only.
- Default comparison is excess return vs `index.000985.SH`.
- Prefer one main variable change per experiment.
- Record data range, asset pool, rebalance frequency, holding period, benchmark, and transaction-cost assumption.

---

## W1/W2/W3 (Sector Leadership v1 — Retired)

W1/W2/W3 is a **cross-class composite** (mixing trend + volume + volatility). Phase A confirmed this design is flawed — component signals cancel each other (RS20 is negative in 5/13 phases). The system should combine Layer 2 factors at Layer 3 (Structure), never inside a single composite.

**Current baseline (reference only):**
- EXP-003 Variant D: MAIN_UP→TOP3, CHAOS→TOP1(≥6), RETREAT→空仓
- +985.3% return, +340.6% excess, −45.9% maxDD (253 windows, 2005~2026)
- Held as reference baseline for Phase C comparison
