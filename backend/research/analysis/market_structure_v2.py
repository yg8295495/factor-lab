"""
Market Structure v2.1 — 失速梯度模型 (Decay Gradient Model)
============================================================
⚠️ 本文件硬编码 SYMBOL = 'index.801001.SW'（旧基准）。
如需在 801003 上使用，改 SYMBOL = 'index.801003.SW' 后重跑。完成后删除本行。

从"强度系统"→"失速梯度系统"。

四个维度（全部每日可算，不依赖swing event）：
  1. 动量加速度 (30%) — (ret20 - ret20_20d_ago) / abs(ret20_20d_ago)
  2. 新高扩散斜率 (20%) — new_high_20d_ratio - MA20(new_high_20d_ratio)
  3. 破位率 (20%) — 过去20天跌破MA20的比例 + MA20斜率
  4. 波动非对称性 (30%) — 上涨日波动 / 下跌日波动

高分=结构健康，低分=失速
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
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            out[i] = out[i - 1] if i > 0 and not np.isnan(out[i - 1]) else 50
        elif i == 0 or np.isnan(out[i - 1]):
            out[i] = arr[i]
        else:
            out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def rolling(arr, w, fn):
    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(w - 1, n):
        out[i] = fn(arr[i - w + 1:i + 1])
    return out


def main():
    print('=' * 60)
    print('MARKET STRUCTURE v2.1 — 失速梯度模型')
    print('=' * 60)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT trade_date, close FROM market_daily_data "
        "WHERE symbol=? ORDER BY trade_date",
        (SYMBOL,)
    )
    rows = cur.fetchall()

    # 加载新高数据
    cur.execute(
        "SELECT trade_date, new_high_20d_ratio FROM market_daily_data "
        "WHERE symbol=? AND new_high_20d_ratio IS NOT NULL ORDER BY trade_date",
        (SYMBOL,)
    )
    nh_rows = cur.fetchall()
    conn.close()

    dates = [r[0] for r in rows]
    closes = np.array([float(r[1]) for r in rows])
    n = len(dates)

    # 新高数据对齐到 dates
    nh_map = {r[0]: float(r[1]) for r in nh_rows}
    nh_20d = np.array([nh_map.get(d, np.nan) for d in dates])

    print(f'Loaded {n} days ({dates[0]} ~ {dates[-1]})')
    print(f'  new_high_20d_ratio: {np.nansum(~np.isnan(nh_20d))} days')

    # ════════════════════════════════════════════
    # Dimension 1: Momentum Acceleration (30%)
    # ════════════════════════════════════════════
    print('\n[1/4] Momentum acceleration...')
    ret20 = np.full(n, np.nan)
    for i in range(19, n):
        ret20[i] = closes[i] / closes[i - 19] - 1

    # (ret20 - ret20_20d_ago) / abs(ret20_20d_ago)
    mom_accel = np.full(n, np.nan)
    for i in range(39, n):
        prev = ret20[i - 20]
        if abs(prev) > 0.001:
            mc = (ret20[i] - prev) / abs(prev)
            # mc 范围：负=动力衰减，正=动力增强
            # 映射到 0-1：mc < -0.5 → 0（失速），mc > 0.5 → 1（加速）
            if mc > 0.5:
                mom_accel[i] = 1.0
            elif mc < -0.5:
                mom_accel[i] = 0.0
            else:
                mom_accel[i] = (mc + 0.5)  # -0.5→0, 0→0.5, +0.5→1.0
        elif prev <= 0.001 and ret20[i] > 0:
            mom_accel[i] = 1.0
        else:
            mom_accel[i] = 0.3

    mom_score = ema(np.nan_to_num(mom_accel, nan=0.5), 10)
    print(f'  Score: {np.nanmin(mom_score):.2f} ~ {np.nanmax(mom_score):.2f}')

    # ════════════════════════════════════════════
    # Dimension 2: Diffusion Slope (20%)
    # ════════════════════════════════════════════
    print('\n[2/4] Diffusion contraction...')
    # new_high_20d_ratio - MA20(new_high_20d_ratio)
    nh_ma20 = rolling(nh_20d, 20, np.nanmean)
    diff_slope = np.full(n, np.nan)
    for i in range(19, n):
        if not np.isnan(nh_20d[i]) and not np.isnan(nh_ma20[i]):
            diff = nh_20d[i] - nh_ma20[i]
            # diff > 0 = 扩散加速, < 0 = 扩散收缩
            # 映射到 0-1
            if diff > 0.02:
                diff_slope[i] = 1.0
            elif diff < -0.02:
                diff_slope[i] = 0.0
            else:
                diff_slope[i] = (diff + 0.02) / 0.04

    diff_score = ema(np.nan_to_num(diff_slope, nan=0.5), 5)
    print(f'  Score: {np.nanmin(diff_score):.2f} ~ {np.nanmax(diff_score):.2f}')

    # ════════════════════════════════════════════
    # Dimension 3: Breakdown Rate (20%)
    # ════════════════════════════════════════════
    print('\n[3/4] Breakdown rate + MA slope...')
    ma20 = np.full(n, np.nan)
    for i in range(19, n):
        ma20[i] = np.mean(closes[i - 19:i + 1])

    # 过去20天中跌破MA20的天数比例
    below_ma20 = np.full(n, np.nan)
    for i in range(38, n):
        below_count = 0
        for j in range(i - 19, i + 1):
            if closes[j] < ma20[j]:
                below_count += 1
        below_ma20[i] = 1.0 - (below_count / 20)  # 高=健康(少跌破)

    # MA20斜率 (5日变化)
    ma20_slope = np.full(n, np.nan)
    for i in range(24, n):
        slope = (ma20[i] - ma20[i - 5]) / ma20[i - 5]
        # 映射：负=均线下降(不健康)
        if slope > 0.005:
            ma20_slope[i] = 1.0
        elif slope < -0.005:
            ma20_slope[i] = 0.0
        else:
            ma20_slope[i] = (slope + 0.005) / 0.01

    # 合成：跌破率 60% + MA20斜率 40%
    ma_score = np.full(n, np.nan)
    for i in range(n):
        b = below_ma20[i] if not np.isnan(below_ma20[i]) else np.nan
        s = ma20_slope[i] if not np.isnan(ma20_slope[i]) else np.nan
        if not np.isnan(b) and not np.isnan(s):
            ma_score[i] = b * 0.6 + s * 0.4
        elif not np.isnan(b):
            ma_score[i] = b

    ma_score_smooth = ema(np.nan_to_num(ma_score, nan=0.5), 5)
    print(f'  Score: {np.nanmin(ma_score_smooth):.2f} ~ {np.nanmax(ma_score_smooth):.2f}')

    # ════════════════════════════════════════════
    # Dimension 4: Volatility Asymmetry (30%)
    # ════════════════════════════════════════════
    print('\n[4/4] Volatility asymmetry...')
    # 日收益率
    daily_ret = np.full(n, np.nan)
    for i in range(1, n):
        daily_ret[i] = closes[i] / closes[i - 1] - 1

    # 过去20天：上涨日波动(涨幅标准差) / 下跌日波动(跌幅标准差)
    vol_asym = np.full(n, np.nan)
    for i in range(20, n):
        up_rets = [daily_ret[j] for j in range(i - 19, i + 1) if daily_ret[j] > 0]
        dn_rets = [abs(daily_ret[j]) for j in range(i - 19, i + 1) if daily_ret[j] < 0]
        if len(up_rets) >= 3 and len(dn_rets) >= 3:
            up_vol = float(np.std(up_rets, ddof=1))
            dn_vol = float(np.std(dn_rets, ddof=1))
            if dn_vol > 0:
                ratio = up_vol / dn_vol
                # ratio > 1 = 上涨波动更大(健康), <1 = 下跌波动更大(顶部)
                if ratio > 1.3:
                    vol_asym[i] = 1.0
                elif ratio < 0.7:
                    vol_asym[i] = 0.0
                else:
                    vol_asym[i] = (ratio - 0.7) / 0.6

    vol_score = ema(np.nan_to_num(vol_asym, nan=0.5), 10)
    print(f'  Score: {np.nanmin(vol_score):.2f} ~ {np.nanmax(vol_score):.2f}')

    # ════════════════════════════════════════════
    # Composite StructureScore v2.1
    # ════════════════════════════════════════════
    print('\nCompositing v2.1...')
    struct_v21 = np.full(n, np.nan)
    for i in range(n):
        s = (mom_score[i] * 0.30 +
             diff_score[i] * 0.20 +
             ma_score_smooth[i] * 0.20 +
             vol_score[i] * 0.30)
        struct_v21[i] = s * 100
    print(f'  v2.1 range: {np.nanmin(struct_v21):.0f} ~ {np.nanmax(struct_v21):.0f}')

    # ── Save ──
    daily = []
    for i in range(n):
        daily.append({
            'date': dates[i],
            'close': round(float(closes[i]), 2) if not np.isnan(closes[i]) else None,
            'structure_score': round(float(struct_v21[i]), 1) if not np.isnan(struct_v21[i]) else None,
        })

    out_path = OUTPUT_DIR / 'market_structure_v2.json'
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'Market-Structure-v2.1', 'benchmark': SYMBOL,
                    'total_days': n, 'daily': daily}, f, indent=2, ensure_ascii=False, default=str)
    print(f'\nSaved: {out_path}')

    # ── Key points summary ──
    print(f'\n{"="*80}')
    print('KEY HISTORICAL POINTS (v2.1 vs v2)')
    print(f'{"="*80}')
    date_map = {d: i for i, d in enumerate(dates)}
    keys = [('2005-07-18', '大底'), ('2007-10-16', '6124顶'), ('2008-11-04', '1664底'),
            ('2012-12-03', '1949底'), ('2015-06-12', '5178顶'), ('2016-01-28', '2638底'),
            ('2018-10-18', '2449底'), ('2021-02-10', '3731顶'), ('2024-02-05', '2635底'),
            ('2024-09-13', '2689底'), ('2024-09-30', '暴涨日')]
    print(f'  {"Date":12s} {"Event":10s} {"v2.1":>6s} {"Mom":>5s} {"Diff":>5s} {"MA":>5s} {"Vol":>5s}')
    print('  ' + '-' * 50)
    for kd, ev in keys:
        idx = date_map.get(kd)
        if idx is not None:
            print(f'  {kd:12s} {ev:10s} {struct_v21[idx]:>5.0f} '
                  f'{mom_score[idx]*100:>5.0f} {diff_score[idx]*100:>5.0f} '
                  f'{ma_score_smooth[idx]*100:>5.0f} {vol_score[idx]*100:>5.0f}')

    # ── Top advance test ──
    print(f'\n{"="*80}')
    print('TOP ADVANCE TEST — v2.1 在大顶前多少天开始下降')
    print(f'{"="*80}')
    for label, peak_date, lookback in [
        ('2007-10-16 6124顶', '2007-10-16', 120),
        ('2015-06-12 5178顶', '2015-06-12', 120),
        ('2021-02-10 3731顶', '2021-02-10', 120),
    ]:
        pi = date_map[peak_date]
        start_i = max(59, pi - lookback)
        # 找到 v2.1 的最高点和从最高点回落的时间
        window = struct_v21[start_i:pi + 1]
        if np.all(np.isnan(window)):
            continue
        max_v = np.nanmax(window)
        max_idx = start_i + np.nanargmax(window)
        # 从最高点跌到低于 max-10 的第一天
        trigger_day = None
        for j in range(max_idx + 1, pi + 1):
            if struct_v21[j] < max_v - 10:
                trigger_day = dates[j]
                break
        lead = None
        if trigger_day:
            from datetime import datetime
            t_peak = datetime.strptime(peak_date, '%Y-%m-%d')
            t_trig = datetime.strptime(trigger_day, '%Y-%m-%d')
            lead = (t_peak - t_trig).days
        print(f'\n  {label}')
        print(f'    v2.1 峰值: {max_v:.0f} ({dates[max_idx]})')
        print(f'    拐头点:    {trigger_day or "未触发"}')
        print(f'    领先天数:  {lead}天' if lead else '    领先天数: N/A')
        # 打印节点附近每个月的v2.1值
        for offset in [-90, -60, -40, -20, -10, 0, 10, 20]:
            idx = max(0, min(n - 1, pi + offset))
            marker = ' <<< 顶' if offset == 0 else ''
            print(f'    {dates[idx]:12s} close={closes[idx]:>8.1f} v2.1={struct_v21[idx]:>5.0f}{marker}')

    print('\nDone.')


if __name__ == '__main__':
    main()
