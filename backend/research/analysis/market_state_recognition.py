"""
EXP-004: Market State Recognition v0

⚠️ 本文件硬编码 index.000985.SH（旧基准）。
如需在 801003 上使用，改 BM 后重跑确认分布一致。完成后删除本行。

Rule-based classifier: 5 dimensions (trend/breadth/emotion/volume/risk)
→ 5 states: MAIN_UP (CONFIRMED) / REBOUND / CROWDING / RETREAT / CHAOS (v0.4+)

Read-only from DB. All rolling features computed in-memory.
Outputs JSON to output/ directory for analysis.

Usage:
    python backend/research/analysis/market_state_recognition.py
"""

import sqlite3
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
BM_SYMBOL = 'index.000985.SH'
BM2_SYMBOL = 'index.000300.SH'
PHASES_CSV = Path(__file__).resolve().parents[1] / 'labeling' / 'labels' / 'market_phases.csv'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'

# ────────────────────────────────────────────
# Threshold table (v0, from EXP-004 design doc)
# ────────────────────────────────────────────

THRESHOLDS = {
    'trend': {
        'trend_str_strong': 60,
        'trend_str_weak': 40,
    },
    'breadth': {
        'adv_ratio_strong': 0.55,
        'adv_ratio_weak': 0.45,
        'diffusion_strong': 60,
        'diffusion_weak': 40,
        'diffusion_falling_threshold': -15,  # percentage points over 20d
    },
    'emotion': {
        'adv_ratio_strong': 0.55,
        'adv_ratio_weak': 0.45,
        'lu_ratio_strong': 0.015,
        'ld_ratio_weak': 0.008,
        'ld_ratio_strong': 0.003,
    },
    'volume': {
        'amount_ratio_strong': 1.10,
        'amount_ratio_weak': 0.90,
    },
    'risk': {
        'vol_percentile_upper': 80,
        'vol_percentile_lower': 70,
        'drawdown_weak': -8.0,  # v0: -8%; v0.1 overrides to -5%
        'drawdown_strong': -5.0,
        'ld_ratio_weak': 0.008,
    },
}

# Experiment version — set via --experiment argument
EXPERIMENT_VERSION = 'v0'

# ────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────

def load_phase_labels():
    """Load market_phases.csv as phase labels."""
    if not PHASES_CSV.exists():
        print(f"  [WARN] Phase labels not found: {PHASES_CSV}")
        return None
    phases = pd.read_csv(PHASES_CSV, comment='#', parse_dates=['start_date', 'end_date'])
    # Handle "至今" for the last phase
    last = phases.iloc[-1]
    if pd.isna(last['end_date']) or str(last['end_date']).strip() == '至今':
        phases.at[phases.index[-1], 'end_date'] = datetime.now().strftime('%Y-%m-%d')
        phases['end_date'] = pd.to_datetime(phases['end_date'])
    return phases


def load_benchmark_data(cursor):
    """Load all needed fields from index.000985.SH and index.000300.SH."""
    # Benchmark primary fields
    cursor.execute(
        "SELECT trade_date, close, time_momentum20, time_momentum60, "
        "trend_strength, breakout_strength, market_adv_ratio, "
        "adv_count, decl_count, limit_up_count, limit_down_count, "
        "amount_ratio "
        "FROM market_daily_data "
        "WHERE symbol = ? "
        "ORDER BY trade_date",
        (BM_SYMBOL,),
    )
    bm = pd.DataFrame(
        cursor.fetchall(),
        columns=[
            'trade_date', 'close', 'mom20', 'mom60',
            'trend_str', 'breakout', 'market_adv_ratio',
            'adv_count', 'decl_count', 'limit_up_count', 'limit_down_count',
            'amount_ratio',
        ],
    )
    bm['trade_date'] = pd.to_datetime(bm['trade_date'])
    bm = bm.set_index('trade_date').sort_index()

    # Load from index.000300.SH (hosts industry_diffusion, volatility, small_cap_spread)
    cursor.execute(
        "SELECT trade_date, industry_diffusion, market_volatility_20d, small_cap_spread "
        "FROM market_daily_data "
        "WHERE symbol = ? "
        "ORDER BY trade_date",
        (BM2_SYMBOL,),
    )
    bm2 = pd.DataFrame(
        cursor.fetchall(),
        columns=['trade_date', 'industry_diffusion', 'market_volatility_20d', 'small_cap_spread'],
    )
    bm2['trade_date'] = pd.to_datetime(bm2['trade_date'])
    bm2 = bm2.set_index('trade_date').sort_index()

    # Merge on trade_date
    combined = bm.join(bm2, how='inner')

    print(f"  Benchmark data: {len(combined)} rows ({combined.index[0].date()} ~ {combined.index[-1].date()})")
    return combined


def load_valid_stock_counts(cursor):
    """
    Load daily valid_stock_count: number of stock rows with non-null pct_chg_raw.
    """
    cursor.execute(
        "SELECT trade_date, COUNT(*) as valid_cnt "
        "FROM market_daily_data "
        "WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL "
        "GROUP BY trade_date "
        "ORDER BY trade_date",
    )
    rows = cursor.fetchall()
    counts = pd.DataFrame(rows, columns=['trade_date', 'valid_cnt'])
    counts['trade_date'] = pd.to_datetime(counts['trade_date'])
    counts = counts.set_index('trade_date').sort_index()
    print(f"  Valid stock counts: {len(counts)} days")
    return counts


# ────────────────────────────────────────────
# Feature computation (in-memory rolling)
# ────────────────────────────────────────────

def compute_rolling_features(df):
    """Compute all derived rolling features. Operates on df in-place."""
    t = df.copy()

    # market_adv_ratio rolling
    t['market_adv_ratio_5d'] = t['market_adv_ratio'].rolling(5).mean()
    t['market_adv_ratio_20d'] = t['market_adv_ratio'].rolling(20).mean()

    # amount_ratio rolling
    t['market_amount_ratio_20d'] = t['amount_ratio'].rolling(20).mean()

    # industry_diffusion change (percentage points)
    t['industry_diffusion_20d_change'] = t['industry_diffusion'].diff(20)

    # Volatility percentile (250-day rolling)
    t['volatility_20d_percentile'] = t['market_volatility_20d'].rolling(250).rank(pct=True) * 100

    # Drawdown: (close - rolling_max) / rolling_max * 100
    t['index_drawdown_20d'] = (t['close'] - t['close'].rolling(20).max()) / t['close'].rolling(20).max() * 100
    t['index_drawdown_60d'] = (t['close'] - t['close'].rolling(60).max()) / t['close'].rolling(60).max() * 100
    t['index_drawdown_120d'] = (t['close'] - t['close'].rolling(120).max()) / t['close'].rolling(120).max() * 100
    # MA120 for medium-term trend filter (v0.3+)
    t['ma120'] = t['close'].rolling(120).mean()

    return t


def compute_emotion_ratios(df, valid_counts):
    """
    Compute daily limit_up_ratio and limit_down_ratio using valid_stock_count.
    Falls back to adv_count + decl_count with approximation flag.
    """
    t = df.copy()
    # Try using valid_counts first
    t = t.join(valid_counts, how='left')
    use_approx = valid_counts is None or valid_counts.empty

    if use_approx:
        t['valid_stock_count'] = t['adv_count'] + t['decl_count']
        t['valid_approx'] = True
    else:
        t['valid_stock_count'] = t['valid_cnt']
        t['valid_approx'] = False
        # Fill any missing valid_cnt with approximation
        missing = t['valid_stock_count'].isna()
        if missing.any():
            t.loc[missing, 'valid_stock_count'] = t.loc[missing, 'adv_count'] + t.loc[missing, 'decl_count']
            t.loc[missing, 'valid_approx'] = True

    # Raw daily ratios
    t['limit_up_ratio'] = t['limit_up_count'] / t['valid_stock_count'].replace(0, np.nan)
    t['limit_down_ratio'] = t['limit_down_count'] / t['valid_stock_count'].replace(0, np.nan)

    # Smoothed
    t['limit_up_ratio_5d'] = t['limit_up_ratio'].rolling(5).mean()
    t['limit_down_ratio_5d'] = t['limit_down_ratio'].rolling(5).mean()

    return t


# ────────────────────────────────────────────
# Dimension scoring
# ────────────────────────────────────────────

def score_trend(row):
    """trend_score: -1 / 0 / +1"""
    if (row['mom20'] > 0 and row['mom60'] > 0
            and row['breakout'] > 0
            and row['trend_str'] >= THRESHOLDS['trend']['trend_str_strong']):
        return 1
    if (row['mom20'] < 0 and row['mom60'] < 0
            and row['breakout'] < 0
            and row['trend_str'] <= THRESHOLDS['trend']['trend_str_weak']):
        return -1
    return 0


def score_breadth(row):
    """breadth_score: -1 / 0 / +1 (v0: AND for weak)"""
    adv_ratio = row['market_adv_ratio_20d']
    diffusion = row['industry_diffusion']

    if pd.isna(adv_ratio) or pd.isna(diffusion):
        return 0

    if adv_ratio >= THRESHOLDS['breadth']['adv_ratio_strong'] and diffusion >= THRESHOLDS['breadth']['diffusion_strong']:
        return 1
    if adv_ratio <= THRESHOLDS['breadth']['adv_ratio_weak'] and diffusion <= THRESHOLDS['breadth']['diffusion_weak']:
        return -1
    return 0


def score_breadth_v01(row):
    """breadth_score: -1 / 0 / +1 (v0.1: OR for weak)"""
    adv_ratio = row['market_adv_ratio_20d']
    diffusion = row['industry_diffusion']

    if pd.isna(adv_ratio) or pd.isna(diffusion):
        return 0

    if adv_ratio >= THRESHOLDS['breadth']['adv_ratio_strong'] and diffusion >= THRESHOLDS['breadth']['diffusion_strong']:
        return 1
    if adv_ratio <= THRESHOLDS['breadth']['adv_ratio_weak'] or diffusion <= THRESHOLDS['breadth']['diffusion_weak']:
        return -1
    return 0


def breadth_falling(row):
    """Check if breadth is actively falling."""
    chg = row['industry_diffusion_20d_change']
    if pd.isna(chg):
        return False
    return chg <= THRESHOLDS['breadth']['diffusion_falling_threshold']


def score_emotion(row):
    """emotion_score: -1 / 0 / +1"""
    adv_5d = row['market_adv_ratio_5d']
    lu_5d = row['limit_up_ratio_5d']
    ld_5d = row['limit_down_ratio_5d']

    if pd.isna(adv_5d) or pd.isna(lu_5d) or pd.isna(ld_5d):
        return 0

    # Strong: broad advance + enough limit-ups + not many limit-downs
    if (adv_5d >= THRESHOLDS['emotion']['adv_ratio_strong']
            and lu_5d >= THRESHOLDS['emotion']['lu_ratio_strong']
            and ld_5d <= THRESHOLDS['emotion']['ld_ratio_strong']):
        return 1

    # Weak: broad decline or too many limit-downs
    if adv_5d <= THRESHOLDS['emotion']['adv_ratio_weak'] or ld_5d >= THRESHOLDS['emotion']['ld_ratio_weak']:
        return -1

    return 0


def score_volume(row):
    """volume_score: -1 / 0 / +1"""
    ar = row['market_amount_ratio_20d']
    if pd.isna(ar):
        return 0

    if ar >= THRESHOLDS['volume']['amount_ratio_strong']:
        return 1
    if ar <= THRESHOLDS['volume']['amount_ratio_weak']:
        return -1
    return 0


def score_risk(row):
    """risk_score: -1 / 0 / +1"""
    vol_pct = row['volatility_20d_percentile']
    dd = row['index_drawdown_20d']
    ld_5d = row['limit_down_ratio_5d']

    # Risk ON (no signal): vol not extreme, drawdown mild, no limit-down panic
    risk_on = True
    if not pd.isna(vol_pct) and vol_pct > THRESHOLDS['risk']['vol_percentile_lower']:
        risk_on = False
    if not pd.isna(dd) and dd <= THRESHOLDS['risk']['drawdown_strong']:
        risk_on = False
    if not pd.isna(ld_5d) and ld_5d >= THRESHOLDS['risk']['ld_ratio_weak']:
        risk_on = False

    if risk_on:
        return 1

    # Risk OFF: vol extreme OR deep drawdown OR limit-down panic
    risk_off = False
    if not pd.isna(vol_pct) and vol_pct >= THRESHOLDS['risk']['vol_percentile_upper']:
        risk_off = True
    if not pd.isna(dd) and dd <= THRESHOLDS['risk']['drawdown_weak']:
        risk_off = True
    if not pd.isna(ld_5d) and ld_5d >= THRESHOLDS['risk']['ld_ratio_weak']:
        risk_off = True

    if risk_off:
        return -1

    return 0


# ────────────────────────────────────────────
# State combination
# ────────────────────────────────────────────

def classify_state(row):
    """Combine 5 dimension scores into a market state."""
    trend = row['trend_score']
    breadth = row['breadth_score']
    emotion = row['emotion_score']
    volume = row['volume_score']
    risk = row['risk_score']
    bf = row['breadth_falling']
    scs = row['small_cap_spread']  # from index.000300.SH

    # MAIN_UP
    if (trend == 1 and breadth == 1
            and emotion >= 0 and volume >= 0 and risk >= 0):
        # Confidence: how many of 5 conditions are satisfied
        conditions = [trend == 1, breadth == 1, emotion >= 0, volume >= 0, risk >= 0]
        confidence = sum(conditions) / 5.0
        return 'MAIN_UP', confidence

    # CROWDING
    if (trend == 1
            and (breadth <= 0 or bf)
            and (pd.isna(scs) or scs <= 0)):
        # Confidence: trend=1 + any breadth weakness + small_cap_weakness
        conds = [trend == 1, breadth <= 0 or bf, pd.isna(scs) or scs <= 0]
        confidence = sum(conds) / 3.0
        return 'CROWDING', confidence

    # RETREAT
    score_sum = trend + breadth + emotion + risk
    bf_sum = sum([trend == -1, breadth == -1, emotion == -1 or risk == -1])
    if (trend == -1 and breadth == -1 and (emotion == -1 or risk == -1)):
        confidence = bf_sum / 3.0
        return 'RETREAT', confidence

    # fallback: RETREAT via sum <= -3
    if score_sum <= -3 and trend <= 0:
        conds = [trend == -1, breadth == -1, emotion == -1 or risk == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence

    # CHAOS (fallback)
    return 'CHAOS', 0.0


def classify_state_v01(row):
    """Combine 5 dimension scores → market state (v0.1 rules).
    
    Priority: RETREAT → MAIN_UP → CROWDING → CHAOS.
    
    Changes vs v0:
    - breadth weak: AND → OR
    - MAIN_UP: trend mandatory + pos_count >= 3 + neg_count == 0
    - RETREAT: drawdown -5%, trend=-1 AND risk=-1 AND (breadth=-1 OR emotion=-1)
    - CROWDING: trend>=0, risk>=0 added
    """
    trend = row['trend_score']
    breadth = row['breadth_score']
    emotion = row['emotion_score']
    volume = row['volume_score']
    risk = row['risk_score']
    bf = row['breadth_falling']
    scs = row['small_cap_spread']

    scores_list = [trend, breadth, emotion, volume, risk]
    pos_count = sum(1 for s in scores_list if s == 1)
    neg_count = sum(1 for s in scores_list if s == -1)

    # ── RETREAT (checked first) ──
    if (trend == -1 and risk == -1
            and (breadth == -1 or emotion == -1)):
        conds = [trend == -1, risk == -1, breadth == -1 or emotion == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence

    # RETREAT fallback: sum score
    score_sum = trend + breadth + emotion + risk
    if score_sum <= -3 and trend <= 0:
        conds = [trend == -1, breadth == -1, emotion == -1 or risk == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence

    # ── MAIN_UP ──
    if (trend == 1 and risk >= 0
            and pos_count >= 3 and neg_count == 0):
        conditions = [trend == 1, risk >= 0, pos_count >= 3, neg_count == 0]
        confidence = sum(conditions) / 4.0
        return 'MAIN_UP', confidence

    # ── CROWDING ──
    if (trend >= 0 and risk >= 0
            and (breadth <= 0 or bf)
            and (pd.isna(scs) or scs <= 0)):
        conds = [trend >= 0, risk >= 0, breadth <= 0 or bf, pd.isna(scs) or scs <= 0]
        confidence = sum(conds) / 4.0
        return 'CROWDING', confidence

    # ── CHAOS (fallback) ──
    return 'CHAOS', 0.0


def participation_ok(row):
    """
    MAIN_UP guard: checks breadth participation without requiring breadth=+1.
    
    True if:
      breadth_score = +1
      OR (market_adv_ratio_20d >= 0.52 AND industry_diffusion >= 50 AND change >= 0)
    """
    if row['breadth_score'] == 1:
        return True
    
    adv = row['market_adv_ratio_20d']
    diff = row['industry_diffusion']
    diff_chg = row['industry_diffusion_20d_change']
    
    if pd.isna(adv) or pd.isna(diff) or pd.isna(diff_chg):
        return False
    
    return adv >= 0.52 and diff >= 50 and diff_chg >= 0


def medium_trend_ok(row):
    """close > MA120 — medium-term trend structure filter."""
    close = row.get('close')
    ma120 = row.get('ma120')
    if pd.isna(close) or pd.isna(ma120) or ma120 == 0:
        return False
    return close > ma120


def classify_state_v03(row):
    """
    v0.3: v0.2 improvements + MA120 medium-term filter + CROWDING relaxed.
    
    Changes from v0.2:
    - MAIN_UP: replace 60d drawdown with close > MA120 (medium_trend_ok)
    - CROWDING: relax to trend>=0 + volume<=0 + breadth/narrowing
    - RETREAT: unchanged from v0.2
    """
    trend = row['trend_score']
    breadth = row['breadth_score']
    emotion = row['emotion_score']
    volume = row['volume_score']
    risk = row['risk_score']
    bf = row['breadth_falling']
    scs = row['small_cap_spread']
    
    scores_list = [trend, breadth, emotion, volume, risk]
    pos_count = sum(1 for s in scores_list if s == 1)
    
    # ── RETREAT (checked first, unchanged from v0.2) ──
    if (trend == -1 and risk == -1
            and (breadth == -1 or emotion == -1)):
        conds = [trend == -1, risk == -1, breadth == -1 or emotion == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence
    
    score_sum = trend + breadth + emotion + risk
    if score_sum <= -3 and trend <= 0:
        conds = [trend == -1, breadth == -1, emotion == -1 or risk == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence
    
    # ── MAIN_UP ──
    if (trend == 1 and risk >= 0 and emotion >= 0
            and participation_ok(row)
            and medium_trend_ok(row)
            and pos_count >= 3):
        conditions = [
            trend == 1, risk >= 0, emotion >= 0,
            participation_ok(row), medium_trend_ok(row), pos_count >= 3,
        ]
        confidence = sum(conditions) / 6.0
        return 'MAIN_UP', confidence
    
    # ── CROWDING (relaxed: trend>=0 + volume<=0 + breadth weakness) ──
    if (risk >= 0
            and (pd.isna(scs) or scs <= 0)
            and volume <= 0
            and (breadth <= 0 or bf)
            and trend >= 0):
        conds = [
            risk >= 0, pd.isna(scs) or scs <= 0,
            volume <= 0, breadth <= 0 or bf, trend >= 0,
        ]
        confidence = sum(conds) / 5.0
        return 'CROWDING', confidence
    
    # ── CHAOS (fallback) ──
    return 'CHAOS', 0.0


def classify_state_v05(row):
    """
    v0.5 (final-v0): v0.3 MAIN_UP rules + drawdown_120d > -10%.
    
    Changes from v0.3:
    - MAIN_UP draws from v0.3 rules (medium_trend_ok, participation_ok)
    - Adds drawdown_120d > -10% (from diagnostics — best cost/benefit)
    - Maintains REBOUND classification for overflow
    - RETREAT unchanged from v0.3
    - CROWDING follows v0.4 (with adv < 0.58 guard)
    
    Note: see diagnostics for why no further tuning is justified.
    """
    trend = row['trend_score']
    breadth = row['breadth_score']
    emotion = row['emotion_score']
    volume = row['volume_score']
    risk = row['risk_score']
    bf = row['breadth_falling']
    scs = row['small_cap_spread']
    adv_20d = row['market_adv_ratio_20d']

    scores_list = [trend, breadth, emotion, volume, risk]
    pos_count = sum(1 for s in scores_list if s == 1)

    # ── RETREAT (unchanged) ──
    if (trend == -1 and risk == -1
            and (breadth == -1 or emotion == -1)):
        conds = [trend == -1, risk == -1, breadth == -1 or emotion == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence

    score_sum = trend + breadth + emotion + risk
    if score_sum <= -3 and trend <= 0:
        conds = [trend == -1, breadth == -1, emotion == -1 or risk == -1]
        confidence = sum(conds) / 3.0
        return 'RETREAT', confidence

    # ── MAIN_UP_CONFIRMED (v0.3 rules + drawdown_120d guard) ──
    dd120 = row['index_drawdown_120d']
    dd120_ok = pd.isna(dd120) or dd120 > -10.0

    if (trend == 1 and risk >= 0 and emotion >= 0
            and medium_trend_ok(row)
            and participation_ok(row)
            and pos_count >= 3
            and dd120_ok):
        conditions = [
            trend == 1, risk >= 0, emotion >= 0,
            medium_trend_ok(row), participation_ok(row),
            pos_count >= 3, dd120_ok,
        ]
        confidence = sum(conditions) / 7.0
        return 'MAIN_UP_CONFIRMED', confidence

    # ── REBOUND (overflow from MAIN_UP, filtered by dd120) ──
    if (trend == 1 and risk >= 0 and pos_count >= 3
            and not dd120_ok):
        conditions = [trend == 1, risk >= 0, pos_count >= 3]
        confidence = sum(conditions) / 3.0
        return 'REBOUND', confidence

    # ── CROWDING (v0.4, with adv < 0.58 guard) ──
    adv_ok = pd.isna(adv_20d) or adv_20d < 0.58
    if (risk >= 0
            and (pd.isna(scs) or scs <= 0)
            and volume <= 0
            and (breadth <= 0 or bf)
            and trend >= 0
            and adv_ok):
        conds = [
            risk >= 0, pd.isna(scs) or scs <= 0,
            volume <= 0, breadth <= 0 or bf, trend >= 0, adv_ok,
        ]
        confidence = sum(conds) / 6.0
        return 'CROWDING', confidence

    # ── CHAOS (fallback) ──
    return 'CHAOS', 0.0


# ────────────────────────────────────────────
# Version dispatch
# ────────────────────────────────────────────

def get_scoring_functions(version):
    """Return (score_breadth_fn, classify_state_fn, thresholds) for experiment version."""
    if version == 'v0':
        th = dict(THRESHOLDS)
        return score_breadth, classify_state, th
    elif version == 'v0.1':
        th = dict(THRESHOLDS)
        th['risk'] = dict(THRESHOLDS['risk'])
        th['risk']['drawdown_weak'] = -5.0
        return score_breadth_v01, classify_state_v01, th
    elif version == 'v0.2':
        th = dict(THRESHOLDS)
        th['risk'] = dict(THRESHOLDS['risk'])
        th['risk']['drawdown_weak'] = -5.0
        return score_breadth_v01, classify_state_v02, th
    elif version == 'v0.3':
        th = dict(THRESHOLDS)
        th['risk'] = dict(THRESHOLDS['risk'])
        th['risk']['drawdown_weak'] = -5.0
        return score_breadth_v01, classify_state_v03, th
    elif version == 'v0.4':
        th = dict(THRESHOLDS)
        th['risk'] = dict(THRESHOLDS['risk'])
        th['risk']['drawdown_weak'] = -5.0
        return score_breadth_v01, classify_state_v04, th
    elif version == 'v0.5':
        th = dict(THRESHOLDS)
        th['risk'] = dict(THRESHOLDS['risk'])
        th['risk']['drawdown_weak'] = -5.0
        return score_breadth_v01, classify_state_v05, th
    else:
        raise ValueError(f"Unknown experiment version: {version}")


# ────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────

def validate_against_phases(daily_results, phases):
    """Compare daily states against market_phases.csv phase labels."""
    if phases is None:
        return {"error": "No phase labels available"}

    # Build flat DataFrame from daily_results (which has nested scores dict)
    records = []
    for day in daily_results:
        rec = {
            'trade_date': day['trade_date'],
            'market_state': day['market_state'],
            'confidence': day['confidence'],
        }
        for dim, score in day['scores'].items():
            rec[f'{dim}_score'] = score
        rec['breadth_falling'] = day['flags']['breadth_falling']
        records.append(rec)

    results_df = pd.DataFrame(records)
    results_df['trade_date'] = pd.to_datetime(results_df['trade_date'])
    results_df = results_df.set_index('trade_date')

    validation = {}
    all_phase_stats = []

    for _, phase in phases.iterrows():
        start = phase['start_date']
        end = phase['end_date']
        ptype = phase['phase_type']
        notes = phase['notes'] if pd.notna(phase.get('notes')) else ''

        # Get dates in this phase
        mask = (results_df.index >= start) & (results_df.index <= end)
        phase_data = results_df[mask]

        if phase_data.empty:
            all_phase_stats.append({
                'phase': f"{start.date()} ~ {end.date()}",
                'type': ptype,
                'days': 0,
                'major_state': 'NO_DATA',
                'consistency': 0,
                'notes': notes,
            })
            continue

        # Major state
        state_counts = phase_data['market_state'].value_counts()
        major_state = state_counts.index[0]
        consistency = state_counts.iloc[0] / len(phase_data)

        # State distribution
        state_dist = {s: int(c) for s, c in state_counts.items()}

        all_phase_stats.append({
            'phase': f"{start.date()} ~ {end.date()}",
            'type': ptype,
            'days': len(phase_data),
            'major_state': major_state,
            'consistency': round(consistency, 3),
            'state_distribution': state_dist,
            'notes': notes,
        })

    validation['phase_stats'] = all_phase_stats

    # Aggregate metrics
    bull_phases = [p for p in all_phase_stats if p['type'] == 'bull' and p['days'] > 0]
    bear_phases = [p for p in all_phase_stats if p['type'] == 'bear' and p['days'] > 0]

    # v0.4+ uses MAIN_UP_CONFIRMED instead of MAIN_UP; detect which is present
    main_up_key = 'MAIN_UP_CONFIRMED' if any(
        'MAIN_UP_CONFIRMED' in p.get('state_distribution', {}) for p in all_phase_stats
    ) else 'MAIN_UP'

    # Bull-phase safe-main recall
    if bull_phases:
        bull_main_up = sum(
            p['state_distribution'].get(main_up_key, 0) for p in bull_phases
        )
        bull_total = sum(p['days'] for p in bull_phases)
        if main_up_key == 'MAIN_UP_CONFIRMED':
            validation['bull_main_up_confirmed_ratio'] = round(bull_main_up / bull_total, 4) if bull_total > 0 else 0
            bull_rebound = sum(
                p['state_distribution'].get('REBOUND', 0) for p in bull_phases
            )
            validation['bull_rebound_ratio'] = round(bull_rebound / bull_total, 4) if bull_total > 0 else 0
        else:
            validation['bull_main_up_ratio'] = round(bull_main_up / bull_total, 4) if bull_total > 0 else 0

        # False RETREAT in bull phases
        bull_retreat = sum(
            p['state_distribution'].get('RETREAT', 0) for p in bull_phases
        )
        validation['bull_false_retreat_ratio'] = round(bull_retreat / bull_total, 4) if bull_total > 0 else 0

    # Bear-phase metrics
    if bear_phases:
        bear_total = sum(p['days'] for p in bear_phases)

        # Bear-phase RETREAT recall
        bear_retreat = sum(
            p['state_distribution'].get('RETREAT', 0) for p in bear_phases
        )
        validation['bear_retreat_ratio'] = round(bear_retreat / bear_total, 4) if bear_total > 0 else 0

        # False MAIN_UP in bear phases
        bear_false = sum(
            p['state_distribution'].get(main_up_key, 0) for p in bear_phases
        )
        if main_up_key == 'MAIN_UP_CONFIRMED':
            validation['bear_false_main_up_confirmed_ratio'] = round(bear_false / bear_total, 4) if bear_total > 0 else 0
        else:
            validation['bear_false_main_up_ratio'] = round(bear_false / bear_total, 4) if bear_total > 0 else 0

        # REBOUND in bear phases (v0.4+)
        bear_rebound = sum(
            p['state_distribution'].get('REBOUND', 0) for p in bear_phases
        )
        if bear_rebound > 0:
            validation['bear_rebound_ratio'] = round(bear_rebound / bear_total, 4) if bear_total > 0 else 0

    # Score distribution
    all_scores = {}
    for dim in ['trend_score', 'breadth_score', 'emotion_score', 'volume_score', 'risk_score']:
        counts = results_df[dim].value_counts().to_dict()
        all_scores[dim] = {str(k): int(v) for k, v in sorted(counts.items())}
    validation['score_distribution'] = all_scores

    # State distribution (overall)
    state_dist = results_df['market_state'].value_counts()
    validation['overall_state_distribution'] = {
        s: int(c) for s, c in state_dist.items()
    }

    return validation


def exp002_cross_check(daily_results):
    """
    EXP-002 cross-check placeholder.
    Will be implemented after EXP-003 runs with state-aware evaluation.
    For now, outputs the state distribution per phase as raw data.
    """
    return {
        'note': 'EXP-002 drawdown cross-check TBD — requires EXP-003 state-aware run',
    }


# ────────────────────────────────────────────
# Main
# ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='EXP-004: Market State Recognition')
    parser.add_argument('--experiment', default='v0', choices=['v0', 'v0.1', 'v0.2', 'v0.3', 'v0.4', 'v0.5'],
                        help='Experiment version (default: v0)')
    args = parser.parse_args()
    version = args.experiment

    print("=" * 60)
    print(f"EXP-004: Market State Recognition ({version})")
    print("=" * 60)

    # Get version-specific functions
    breadth_fn, classify_fn, thresholds = get_scoring_functions(version)
    # Update global thresholds for risk_score (drawdown_weak differs)
    THRESHOLDS['risk']['drawdown_weak'] = thresholds['risk']['drawdown_weak']

    # Create output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load phases
    print("\n[1/6] Loading phase labels...")
    phases = load_phase_labels()
    if phases is not None:
        print(f"  {len(phases)} phases loaded")
    else:
        print("  Skipping phase validation")

    # Connect DB
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Load data
    print("\n[2/6] Loading benchmark data...")
    bm_data = load_benchmark_data(cursor)

    print("\n[3/6] Loading valid stock counts...")
    valid_counts = load_valid_stock_counts(cursor)

    conn.close()

    # Compute rolling features
    print("\n[4/6] Computing rolling features...")
    bm_data = compute_rolling_features(bm_data)
    bm_data = compute_emotion_ratios(bm_data, valid_counts)

    # A note about approximation
    if bm_data['valid_approx'].any():
        approx_days = bm_data['valid_approx'].sum()
        total_days = len(bm_data)
        print(f"  [NOTE] {approx_days}/{total_days} days use adv+decl approximation for valid_stock_count")

    # Score each dimension
    print(f"\n[5/6] Scoring dimensions and classifying states ({version})...")
    bm_data['trend_score'] = bm_data.apply(score_trend, axis=1)
    bm_data['breadth_score'] = bm_data.apply(breadth_fn, axis=1)  # version-specific
    bm_data['breadth_falling'] = bm_data.apply(breadth_falling, axis=1)
    bm_data['emotion_score'] = bm_data.apply(score_emotion, axis=1)
    bm_data['volume_score'] = bm_data.apply(score_volume, axis=1)
    bm_data['risk_score'] = bm_data.apply(score_risk, axis=1)

    # Classify
    states = bm_data.apply(classify_fn, axis=1, result_type='expand')
    bm_data['market_state'] = states[0]
    bm_data['confidence'] = states[1]

    # Drop rows without enough rolling data
    bm_data_valid = bm_data.dropna(subset=['market_state'])

    # Print score distribution
    print(f"\n  Rows classified: {len(bm_data_valid)}")
    print(f"\n  Score distribution (breadth uses {version} rules):")
    for dim in ['trend_score', 'breadth_score', 'emotion_score', 'volume_score', 'risk_score']:
        counts = bm_data_valid[dim].value_counts().sort_index()
        parts = [f"{k}: {v}" for k, v in counts.items()]
        print(f"    {dim:20s}  {'  '.join(parts)}")

    # State distribution
    state_counts = bm_data_valid['market_state'].value_counts()
    print(f"\n  State distribution ({version}):")
    for s, c in state_counts.items():
        print(f"    {s:12s}: {c} ({c/len(bm_data_valid)*100:.1f}%)")

    # Build daily output
    print("\n[6/6] Building output...")
    daily_output = []
    for idx, row in bm_data_valid.iterrows():
        entry = {
            'trade_date': idx.strftime('%Y-%m-%d'),
            'market_state': row['market_state'],
            'confidence': round(float(row['confidence']), 4),
            'scores': {
                'trend': int(row['trend_score']),
                'breadth': int(row['breadth_score']),
                'emotion': int(row['emotion_score']),
                'volume': int(row['volume_score']),
                'risk': int(row['risk_score']),
            },
            'flags': {
                'breadth_falling': bool(row['breadth_falling']),
            },
        }
        daily_output.append(entry)

    # Write daily states (version-specific filename)
    suffix = '' if version == 'v0' else f'_{version.replace(".", "")}'
    daily_path = OUTPUT_DIR / f'market_state_daily{suffix}.json'
    with open(daily_path, 'w') as f:
        json.dump(daily_output, f, indent=2, ensure_ascii=False)
    print(f"  Daily states: {daily_path} ({len(daily_output)} rows)")

    # Validation
    print(f"\n  Validating against phase labels...")
    validation = validate_against_phases(daily_output, phases)
    validation['experiment_version'] = version
    validation['exp002_cross_check'] = exp002_cross_check(daily_output)

    # Write validation
    val_path = OUTPUT_DIR / f'market_state_validation{suffix}.json'
    with open(val_path, 'w') as f:
        json.dump(validation, f, indent=2, ensure_ascii=False)
    print(f"  Validation: {val_path}")

    # Print quick summary
    print(f"\n{'='*60}")
    print(f"SUMMARY ({version})")
    print(f"{'='*60}")

    if 'bull_main_up_confirmed_ratio' in validation:
        print(f"  Bull-phase MAIN_UP_CONFIRMED: {validation['bull_main_up_confirmed_ratio']*100:.1f}%")
    if 'bull_rebound_ratio' in validation:
        print(f"  Bull-phase REBOUND:          {validation['bull_rebound_ratio']*100:.1f}%")
    if 'bull_main_up_ratio' in validation:
        print(f"  Bull-phase MAIN_UP recall:   {validation['bull_main_up_ratio']*100:.1f}%")
    if 'bull_false_retreat_ratio' in validation:
        print(f"  Bull-phase false RETREAT:    {validation['bull_false_retreat_ratio']*100:.1f}%")
    if 'bear_retreat_ratio' in validation:
        print(f"  Bear-phase RETREAT recall:   {validation['bear_retreat_ratio']*100:.1f}%")
    if 'bear_false_main_up_confirmed_ratio' in validation:
        print(f"  Bear-phase false MAIN_UP_CNF: {validation['bear_false_main_up_confirmed_ratio']*100:.1f}%")
    if 'bear_rebound_ratio' in validation:
        print(f"  Bear-phase REBOUND:          {validation['bear_rebound_ratio']*100:.1f}%")
    if 'bear_false_main_up_ratio' in validation:
        print(f"  Bear-phase false MAIN_UP:    {validation['bear_false_main_up_ratio']*100:.1f}%")

    print(f"\n  Phase stats written to: {val_path}")
    print(f"  Daily states written to: {daily_path}")
    print(f"\nEXP-004 {version} complete")


if __name__ == '__main__':
    main()
