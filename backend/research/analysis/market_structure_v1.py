"""
Market Structure v1 — Swing Point + 四概率输出 (Bottom/Bull/Top/Bear)
=====================================================================
⚠️ 本文件硬编码 SYMBOL = 'index.801001.SW'（旧基准）。
如需在 801003 上使用，改 SYMBOL = 'index.801003.SW' 后重跑。完成后删除本行。

三层架构：
  Layer1（估值层）+ Layer2（结构层）+ Layer3（行为层，初步）
  → 四个独立概率 (0-100)，可叠加展示

输出：
  - bottom_score / bull_score / top_score / bear_score: 四概率
  - structure_score: 结构强度（参考）
  - state: 展示用状态标签（不做决策）
  - swing_highs / swing_lows: 摆动点记录

全部基于 T+0 时可用的 trailing 数据，无未来函数。
"""

import numpy as np
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'
SYMBOL = 'index.801001.SW'


def ema(arr, w):
    out = np.full(len(arr), np.nan)
    k = 2.0 / (w + 1)
    out[0] = arr[0] if not np.isnan(arr[0]) else 0
    for i in range(1, len(arr)):
        if np.isnan(arr[i]):
            out[i] = out[i - 1]
        elif np.isnan(out[i - 1]):
            out[i] = arr[i]
        else:
            out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def rolling_range(arr, window):
    n = len(arr)
    mx = np.full(n, np.nan)
    mn = np.full(n, np.nan)
    for i in range(window - 1, n):
        mx[i] = np.max(arr[i - window + 1:i + 1])
        mn[i] = np.min(arr[i - window + 1:i + 1])
    return mx, mn


def main():
    print('=' * 60)
    print('MARKET STRUCTURE v1 — 四概率输出')
    print('=' * 60)

    # ── Load data ──
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT trade_date, high, low, close, pe_ttm, market_adv_ratio, new_high_20d_ratio "
        "FROM market_daily_data WHERE symbol=? ORDER BY trade_date",
        (SYMBOL,)
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT trade_date, close FROM market_daily_data "
        "WHERE symbol='macro.CN10Y' AND close IS NOT NULL ORDER BY trade_date"
    )
    bond_rows = cur.fetchall()
    conn.close()

    dates = [r[0] for r in rows]
    highs = np.array([float(r[1]) for r in rows])
    lows = np.array([float(r[2]) for r in rows])
    closes = np.array([float(r[3]) for r in rows])
    pe_vals = np.array([float(r[4]) if r[4] is not None else np.nan for r in rows])
    adv_vals = np.array([float(r[5]) if r[5] is not None else np.nan for r in rows])
    nh_vals = np.array([float(r[6]) if r[6] is not None else np.nan for r in rows])
    bond_map = {r[0]: float(r[1]) / 100 for r in bond_rows}
    n = len(dates)
    print(f'Loaded {n} days ({dates[0]} ~ {dates[-1]})')

    # ── Layer 2: Structure (v2.1 失速梯度模型) ──
    print('\n[1/4] Computing structure (v2.1 decay gradient)...')

    # Helper: rolling
    def rolling_fn(arr, w, fn):
        out = np.full(n, np.nan)
        for i in range(w - 1, n):
            out[i] = fn(arr[i - w + 1:i + 1])
        return out

    # --- Dim 1: Momentum Acceleration (30%) ---
    ret20 = np.full(n, np.nan)
    for i in range(19, n):
        ret20[i] = closes[i] / closes[i - 19] - 1

    mom_accel = np.full(n, np.nan)
    for i in range(39, n):
        prev = ret20[i - 20]
        if abs(prev) > 0.001:
            mc = (ret20[i] - prev) / abs(prev)
            if mc > 0.5:
                mom_accel[i] = 1.0
            elif mc < -0.5:
                mom_accel[i] = 0.0
            else:
                mom_accel[i] = (mc + 0.5)
        elif prev <= 0.001 and ret20[i] > 0:
            mom_accel[i] = 1.0
        else:
            mom_accel[i] = 0.3

    # 修正：动量加速度必须乘以"绝对水平因子"
    # 当 ret20 < 8% 时，即使变化率很大，也不应视为健康加速
    # ret20=8%→1.0, ret20=4%→0.5, ret20=0%→0.2, ret20<0→0.1
    level_factor = np.full(n, np.nan)
    for i in range(19, n):
        r = ret20[i]
        if r > 0.08:
            level_factor[i] = 1.0
        elif r > 0.04:
            level_factor[i] = 0.5 + (r - 0.04) / 0.08  # 0.04→0.5, 0.08→1.0
        elif r > 0:
            level_factor[i] = 0.2 + r / 0.04 * 0.3     # 0→0.2, 0.04→0.5
        else:
            level_factor[i] = 0.1

    for i in range(n):
        if not np.isnan(mom_accel[i]) and not np.isnan(level_factor[i]):
            mom_accel[i] = mom_accel[i] * level_factor[i]

    mom_score = ema(np.nan_to_num(mom_accel, nan=0.5), 10)
    print(f'  Momentum accel: {np.nanmin(mom_score):.2f} ~ {np.nanmax(mom_score):.2f}')

    # --- Dim 2: Diffusion Contraction (20%) ---
    nh_ma20 = rolling_fn(nh_vals, 20, np.nanmean)
    diff_slope = np.full(n, np.nan)
    for i in range(19, n):
        if not np.isnan(nh_vals[i]) and not np.isnan(nh_ma20[i]):
            diff = nh_vals[i] - nh_ma20[i]
            if diff > 0.02:
                diff_slope[i] = 1.0
            elif diff < -0.02:
                diff_slope[i] = 0.0
            else:
                diff_slope[i] = (diff + 0.02) / 0.04
    diff_score = ema(np.nan_to_num(diff_slope, nan=0.5), 5)
    print(f'  Diffusion: {np.nanmin(diff_score):.2f} ~ {np.nanmax(diff_score):.2f}')

    # --- Dim 3: Breakdown Rate + MA Slope (20%) ---
    ma20 = np.full(n, np.nan)
    for i in range(19, n):
        ma20[i] = np.mean(closes[i - 19:i + 1])

    below_ma20 = np.full(n, np.nan)
    for i in range(38, n):
        below_count = sum(1 for j in range(i - 19, i + 1) if closes[j] < ma20[j])
        below_ma20[i] = 1.0 - below_count / 20

    ma20_slope = np.full(n, np.nan)
    for i in range(24, n):
        slope = (ma20[i] - ma20[i - 5]) / ma20[i - 5]
        if slope > 0.005:
            ma20_slope[i] = 1.0
        elif slope < -0.005:
            ma20_slope[i] = 0.0
        else:
            ma20_slope[i] = (slope + 0.005) / 0.01

    ma_score = np.full(n, np.nan)
    for i in range(n):
        b = below_ma20[i] if not np.isnan(below_ma20[i]) else np.nan
        s = ma20_slope[i] if not np.isnan(ma20_slope[i]) else np.nan
        if not np.isnan(b) and not np.isnan(s):
            ma_score[i] = b * 0.6 + s * 0.4
        elif not np.isnan(b):
            ma_score[i] = b
    ma_score_s = ema(np.nan_to_num(ma_score, nan=0.5), 5)
    print(f'  MA structure: {np.nanmin(ma_score_s):.2f} ~ {np.nanmax(ma_score_s):.2f}')

    # --- Dim 4: Volatility Asymmetry (30%) ---
    daily_ret = np.full(n, np.nan)
    for i in range(1, n):
        daily_ret[i] = closes[i] / closes[i - 1] - 1

    vol_asym = np.full(n, np.nan)
    for i in range(20, n):
        up_rets = [daily_ret[j] for j in range(i - 19, i + 1) if daily_ret[j] > 0]
        dn_rets = [abs(daily_ret[j]) for j in range(i - 19, i + 1) if daily_ret[j] < 0]
        if len(up_rets) >= 3 and len(dn_rets) >= 3:
            up_vol = float(np.std(up_rets, ddof=1))
            dn_vol = float(np.std(dn_rets, ddof=1))
            if dn_vol > 0:
                ratio = up_vol / dn_vol
                if ratio > 1.3:
                    vol_asym[i] = 1.0
                elif ratio < 0.7:
                    vol_asym[i] = 0.0
                else:
                    vol_asym[i] = (ratio - 0.7) / 0.6
    vol_score = ema(np.nan_to_num(vol_asym, nan=0.5), 10)
    print(f'  Vol asymmetry: {np.nanmin(vol_score):.2f} ~ {np.nanmax(vol_score):.2f}')

    # --- Composite StructureScore v2.1 ---
    struct_score = np.full(n, np.nan)
    for i in range(n):
        s = (mom_score[i] * 0.30 +
             diff_score[i] * 0.20 +
             ma_score_s[i] * 0.20 +
             vol_score[i] * 0.30)
        struct_score[i] = s * 100
    print(f'  StructureScore v2.1: {np.nanmin(struct_score):.0f} ~ {np.nanmax(struct_score):.0f}')

    # ── Layer 1: Valuation (ERP) ──
    print('\n[2/4] Computing valuation layer...')
    ey_vals = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(pe_vals[i]) and pe_vals[i] > 0:
            ey_vals[i] = 1.0 / pe_vals[i]

    erp_all = np.full(n, np.nan)
    erp_hist = []
    for i in range(n):
        b = bond_map.get(dates[i])
        if b is not None and not np.isnan(ey_vals[i]):
            erp_v = ey_vals[i] - b
            erp_hist.append(erp_v)
            if len(erp_hist) >= 30:
                erp_all[i] = float(np.sum(erp_hist <= erp_v) / len(erp_hist))

    # ── Layer 3: Behavior (初步) ──
    print('\n[3/4] Computing behavior layer...')
    # market_adv_ratio 20d avg
    adv_avg = np.full(n, np.nan)
    for i in range(19, n):
        w = adv_vals[i - 19:i + 1]
        valid = w[~np.isnan(w)]
        if len(valid) >= 10:
            adv_avg[i] = float(np.mean(valid))

    # ── Four Probabilities ──
    print('\n[4/4] Computing four probabilities...')
    bottom = np.full(n, np.nan)
    bull = np.full(n, np.nan)
    top_prob = np.full(n, np.nan)
    bear = np.full(n, np.nan)

    for i in range(120, n):
        s = struct_score[i] if not np.isnan(struct_score[i]) else 50
        erp = erp_all[i] if not np.isnan(erp_all[i]) else 0.5
        adv = adv_avg[i] if not np.isnan(adv_avg[i]) else 0.5

        # Structure trend
        if i >= 140:
            ss_trend = s - np.nanmean(struct_score[i - 19:i + 1])
        else:
            ss_trend = 0.0

        # ── BottomScore ──
        cheap = erp * 100
        weak = max(0, (50 - s) / 50) * 100  # s=0→100, s=50→0
        panic = max(0, (0.30 - adv) / 0.30) * 100 if adv < 0.30 else 0
        bottom[i] = 0.35 * cheap + 0.35 * weak + 0.30 * panic
        if i > 120 and not np.isnan(bottom[i - 1]):
            bottom[i] = 0.85 * bottom[i - 1] + 0.15 * bottom[i]

        # ── BearScore ──
        trend_dn = max(0, -ss_trend / 15) * 100 if ss_trend < 0 else 0
        bear[i] = 0.50 * weak + 0.25 * (1 - adv) * 100 + 0.25 * trend_dn
        if i > 120 and not np.isnan(bear[i - 1]):
            bear[i] = 0.85 * bear[i - 1] + 0.15 * bear[i]

        # ── BullScore ──
        strong = max(0, (s - 30) / 70) * 100
        adv_ok = max(0, (adv - 0.30) / 0.50) * 100 if adv > 0.30 else 0
        trend_up = max(0, ss_trend / 15) * 100 if ss_trend > 0 else 0
        bull[i] = 0.40 * strong + 0.30 * adv_ok + 0.30 * trend_up
        if i > 120 and not np.isnan(bull[i - 1]):
            bull[i] = 0.85 * bull[i - 1] + 0.15 * bull[i]

        # ── TopScore (v2.1) ──
        # Gate: ERP 分位做阀门
        # erp 低=贵(顶相关), erp 高=便宜(顶无关)
        structure_decay = max(0, (65 - s) / 65) * 100 if s < 65 else 0
        diffusion_shrink = (1 - diff_score[i]) * 100 if not np.isnan(diff_score[i]) else 50

        top_raw = 0.15 * (100 - erp * 100) + 0.45 * structure_decay + 0.40 * diffusion_shrink

        # 估值门：低分位(贵)=不折扣，高分位(便宜)=打折
        if erp < 0.30:
            pass  # 贵，不折扣
        elif erp < 0.50:
            top_raw *= 0.6  # 中性略贵
        elif erp < 0.70:
            top_raw *= 0.3  # 中性略便宜
        else:
            top_raw *= 0.1  # 很便宜，基本不考虑顶

        top_prob[i] = top_raw
        if i > 120 and not np.isnan(top_prob[i - 1]):
            top_prob[i] = 0.70 * top_prob[i - 1] + 0.30 * top_prob[i]

    # Clip 0-100
    for arr in [bottom, bull, top_prob, bear]:
        for j in range(len(arr)):
            if not np.isnan(arr[j]):
                arr[j] = min(100, max(0, arr[j]))

    print(f'  Bottom: {np.nanmin(bottom):.0f}~{np.nanmax(bottom):.0f}')
    print(f'  Bull:   {np.nanmin(bull):.0f}~{np.nanmax(bull):.0f}')
    print(f'  Top:    {np.nanmin(top_prob):.0f}~{np.nanmax(top_prob):.0f}')
    print(f'  Bear:   {np.nanmin(bear):.0f}~{np.nanmax(bear):.0f}')

    # ── State label (展示) ──
    ma20 = np.full(n, np.nan)
    ma60 = np.full(n, np.nan)
    for i in range(19, n):
        ma20[i] = np.mean(closes[i - 19:i + 1])
    for i in range(59, n):
        ma60[i] = np.mean(closes[i - 59:i + 1])

    states = ['OTHER'] * n
    for i in range(120, n):
        s = struct_score[i] if not np.isnan(struct_score[i]) else 50
        if i >= 140:
            ss_tr = s - np.nanmean(struct_score[i - 19:i + 1])
        else:
            ss_tr = 0

        tp = top_prob[i] if not np.isnan(top_prob[i]) else 0
        bl = bull[i] if not np.isnan(bull[i]) else 0

        # 基于 v2.1 结构分的状态标签
        # TOPPING: Top 显著高于 Bull，或 Top 偏高且结构已走弱
        if tp > 55 and tp > bl * 1.2:
            states[i] = 'TOPPING'
        elif tp > 40 and tp >= bl and tp >= bear[i] and s < 55:
            states[i] = 'TOPPING'
        elif s < 30:
            states[i] = 'DOWN'
        elif s < 45:
            states[i] = 'BASE'
        elif 45 <= s < 65 and ss_tr >= -3:
            states[i] = 'EARLY_UP'
        elif s >= 65 and ss_tr < -2:
            states[i] = 'LATE_UP'
        elif s >= 65:
            states[i] = 'PRIMARY_UP'

    # ── Swing points (展示) ──
    w = 20
    swing_highs = []
    swing_lows = []
    seen = set()
    for i in range(w, n - w):
        if highs[i] == np.max(highs[i - w:i + w + 1]) and dates[i] not in seen:
            swing_highs.append({'date': dates[i], 'price': round(float(highs[i]), 2)})
            seen.add(dates[i])
    seen.clear()
    for i in range(w, n - w):
        if lows[i] == np.min(lows[i - w:i + w + 1]) and dates[i] not in seen:
            swing_lows.append({'date': dates[i], 'price': round(float(lows[i]), 2)})
            seen.add(dates[i])

    # ── Build output ──
    daily = []
    for i in range(n):
        daily.append({
            'date': dates[i],
            'close': round(float(closes[i]), 2) if not np.isnan(closes[i]) else None,
            'structure_score': round(float(struct_score[i]), 1) if not np.isnan(struct_score[i]) else None,
            'state': states[i],
            'bottom_score': round(float(bottom[i]), 1) if not np.isnan(bottom[i]) else None,
            'bull_score': round(float(bull[i]), 1) if not np.isnan(bull[i]) else None,
            'top_score': round(float(top_prob[i]), 1) if not np.isnan(top_prob[i]) else None,
            'bear_score': round(float(bear[i]), 1) if not np.isnan(bear[i]) else None,
        })

    output = {
        'experiment': 'Market-Structure-v1',
        'benchmark': SYMBOL,
        'total_days': n,
        'swing_highs': swing_highs,
        'swing_lows': swing_lows,
        'daily': daily,
    }

    out_path = OUTPUT_DIR / 'market_structure_v1.json'
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f'\nSaved: {out_path} ({n} days)')

    # ── Summary ──
    print(f'\n{"=" * 60}')
    print('STATE DISTRIBUTION')
    print(f'{"=" * 60}')
    cnt = {}
    for d in daily:
        s = d['state']
        cnt[s] = cnt.get(s, 0) + 1
    for s in ['DOWN', 'BASE', 'EARLY_UP', 'PRIMARY_UP', 'LATE_UP', 'TOPPING', 'OTHER']:
        c = cnt.get(s, 0)
        if c:
            print(f'  {s:12s}: {c:>5d} days ({c / n * 100:.1f}%)')

    print(f'\n{"=" * 60}')
    print('KEY HISTORICAL POINTS (四概率)')
    print(f'{"=" * 60}')
    dm = {d['date']: d for d in daily}
    keys = ['2005-07-18', '2007-10-16', '2008-11-04', '2012-12-03', '2015-06-12',
            '2018-10-18', '2024-02-05', '2024-09-13', '2024-09-30']
    print(f'  {"Date":12s} {"State":12s} {"Bot":>5s} {"Bull":>5s} {"Top":>5s} {"Bear":>5s}')
    print('  ' + '-' * 50)
    for kd in keys:
        d = dm.get(kd)
        if d:
            print(f'  {kd:12s} {d["state"]:12s} {d["bottom_score"] or 0:>5.0f} {d["bull_score"] or 0:>5.0f} {d["top_score"] or 0:>5.0f} {d["bear_score"] or 0:>5.0f}')

    print('\nDone.')


if __name__ == '__main__':
    main()
