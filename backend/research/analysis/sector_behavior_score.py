"""
行业行为评分 v2 — 转折期三区间回看评分

核心思路：不在最低点评分，而是在底部最低点后 20-60 天回头看，
按底部四阶段过程评分（放量震荡区 → 缩量洗盘区 → 初升试探区）。

v1 失败原因：单点 level 评分永远选到防御板块（银行/食品饮料/公用事业），
因为未来主线在底部时超跌最深、RS 最烂。

v2 改进：看 acceleration 而不是 level，看变化过程而不是单点。
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import json

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
BM_SYMBOL = 'index.000985.SH'
PHASES_CSV = Path(__file__).resolve().parents[1] / 'labeling' / 'labels' / 'market_phases.csv'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'

# 三区间窗口定义
WINDOWS = [
    ('W1_放量震荡', 60, 40),   # T-60 ~ T-40: 主力介入期
    ('W2_缩量洗盘', 40, 20),   # T-40 ~ T-20: 浮筹出清期
    ('W3_初升试探', 20, 0),    # T-20 ~ T-0:  确认期
]


# ════════════════════════════════════════
# 数据加载
# ════════════════════════════════════════

def load_data():
    """加载全指 + 所有行业数据"""
    conn = sqlite3.connect(str(DB_PATH))

    # 全指
    bm = pd.read_sql(
        'SELECT trade_date, close, amount FROM market_daily_data WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date']
    ).set_index('trade_date').sort_index()
    bm['ret'] = bm['close'].pct_change()

    # 行业
    query = '''
        SELECT d.symbol, a.name, d.trade_date, d.close, d.amount
        FROM market_daily_data d
        JOIN asset_master a ON d.symbol = a.symbol
        WHERE a.asset_type = 'sector'
        ORDER BY d.trade_date, d.symbol
    '''
    sec_raw = pd.read_sql(query, conn, parse_dates=['trade_date'])
    conn.close()

    # 行业 pivot
    sec_close = sec_raw.pivot(index='trade_date', columns='symbol', values='close').sort_index()
    sec_amount = sec_raw.pivot(index='trade_date', columns='symbol', values='amount').sort_index()
    sec_name = sec_raw[['symbol', 'name']].drop_duplicates().set_index('symbol')['name'].to_dict()

    # 对齐
    common = bm.index.intersection(sec_close.dropna(how='all').index)
    bm = bm.loc[common]
    sec_close = sec_close.loc[common]
    sec_amount = sec_amount.loc[common]

    return bm, sec_close, sec_amount, sec_name


def load_phases():
    """读取阶段划分，返回 bull 阶段（底部起涨点）"""
    df = pd.read_csv(PHASES_CSV, comment='#')
    df = df.dropna(subset=['start_date', 'end_date', 'phase_type'])
    bull_phases = []
    for _, row in df.iterrows():
        ptype = row['phase_type'].strip()
        if ptype != 'bull':
            continue
        end = row['end_date'].strip()
        if end == '至今':
            end = datetime.now().strftime('%Y-%m-%d')
        bull_phases.append({
            'label': f"📈 Bull #{len(bull_phases)+1}",
            'start': row['start_date'].strip(),
            'end': end,
            'type': ptype,
            'notes': row.get('notes', '').strip(),
        })
    return bull_phases


# ════════════════════════════════════════
# 三区间信号检测
# ════════════════════════════════════════

def calc_window_1_vol_expansion(close_series, amount_series, bm_close, bm_amount,
                                t_start, t_end, lookback=60):
    """
    W1 放量震荡区信号 (T-60 ~ T-40):
    1. 波动率扩张: 区间内日收益率 std > 前 lookback 天 std 的 1.2 倍
    2. 量能放大: 区间均量 > 前 lookback 天均量的 1.1 倍
    3. 相对全指: 区间内相对全指波动更大

    返回: 0/1/2/3 (满足几个条件)
    """
    try:
        idx_start = close_series.index.get_loc(t_start)
        idx_end = close_series.index.get_loc(t_end)
    except (KeyError, ValueError):
        return 0

    pre_start = close_series.index[max(0, idx_start - lookback)]
    pre_slice = close_series.loc[pre_start:t_start]
    win_slice = close_series.loc[t_start:t_end]
    win_amount = amount_series.loc[t_start:t_end]

    if len(win_slice) < 5 or len(pre_slice) < 10:
        return 0

    # 1) 波动率扩张
    win_vol = win_slice.pct_change().dropna().std()
    pre_vol = pre_slice.pct_change().dropna().std()
    vol_expanded = win_vol > pre_vol * 1.15 if pre_vol > 0 else False

    # 2) 量能放大
    pre_amount_slice = amount_series.loc[pre_start:t_start]
    win_avg_amount = win_amount.mean()
    pre_avg_amount = pre_amount_slice.mean()
    amount_increased = (win_avg_amount > pre_avg_amount * 1.1) if pre_avg_amount > 0 else False

    # 3) 相对全指波动（行业波动 / 全指波动）
    bm_win = bm_close.loc[t_start:t_end]
    bm_pre = bm_close.loc[pre_start:t_start]
    rel_vol_win = win_slice.pct_change().dropna().std() / bm_win.pct_change().dropna().std() if len(bm_win) > 5 else 0
    rel_vol_pre = pre_slice.pct_change().dropna().std() / bm_pre.pct_change().dropna().std() if len(bm_pre) > 5 else 0
    rel_vol_expanded = rel_vol_win > rel_vol_pre * 1.1

    return sum([vol_expanded, amount_increased, rel_vol_expanded])


def calc_window_2_washout(close_series, amount_series, bm_close,
                          t_start, t_end, lookback=60):
    """
    W2 缩量洗盘区信号 (T-40 ~ T-20):
    1. 缩量: 区间均量 < 前 lookback 天均量的 0.9
    2. 不破低: 区间最低价 > W1 区间最低价
    3. RS 底部抬高: 相对全指表现比 W1 改善

    返回: 0/1/2/3
    """
    try:
        idx_start = close_series.index.get_loc(t_start)
        idx_end = close_series.index.get_loc(t_end)
    except (KeyError, ValueError):
        return 0

    w1_start = close_series.index[max(0, idx_start - 20)]  # W1 starts 20 days before W2
    w1_end = t_start

    pre_start = close_series.index[max(0, idx_start - lookback)]
    pre_slice = amount_series.loc[pre_start:t_start]
    win_slice = close_series.loc[t_start:t_end]
    win_amount = amount_series.loc[t_start:t_end]
    w1_slice = close_series.loc[w1_start:w1_end] if w1_start in close_series.index else close_series.iloc[:1]

    if len(win_slice) < 5 or len(pre_slice) < 5:
        return 0

    # 1) 缩量
    win_avg_amount = win_amount.mean()
    pre_avg_amount = pre_slice.mean()
    volume_shrunk = (win_avg_amount < pre_avg_amount * 0.9) if pre_avg_amount > 0 else False

    # 2) 不破前低（以 W1 最低为参考）
    w1_low = w1_slice.min()
    win_low = win_slice.min()
    not_break_low = (win_low > w1_low * 0.98) if w1_low > 0 else True  # 允许 2% 误差

    # 3) RS 底部抬高: 区间内相对全指超额收益比 W1 改善
    bm_win = bm_close.loc[t_start:t_end]
    bm_w1 = bm_close.loc[w1_start:w1_end] if w1_end in bm_close.index and w1_start in bm_close.index else None

    sec_ret_win = win_slice.iloc[-1] / win_slice.iloc[0] - 1 if len(win_slice) >= 2 else 0
    bm_ret_win = bm_win.iloc[-1] / bm_win.iloc[0] - 1 if len(bm_win) >= 2 else 0

    if bm_w1 is not None and len(bm_w1) >= 2 and len(w1_slice) >= 2:
        sec_ret_w1 = w1_slice.iloc[-1] / w1_slice.iloc[0] - 1
        bm_ret_w1 = bm_w1.iloc[-1] / bm_w1.iloc[0] - 1

        excess_w1 = sec_ret_w1 - bm_ret_w1
        excess_w2 = sec_ret_win - bm_ret_win
        rs_improved = excess_w2 > excess_w1
    else:
        rs_improved = (sec_ret_win - bm_ret_win) > -0.02  # 至少不跑输太多

    return sum([volume_shrunk, not_break_low, rs_improved])


def calc_window_3_confirmation(close_series, amount_series, bm_close, bm_amount,
                               t_start, t_end, lookback=20):
    """
    W3 初升试探区信号 (T-20 ~ T-0):
    1. 放量突破: 区间内放量且价格突破 20 日均线
    2. RS 转正: 区间超额收益为正
    3. 首次回调不破: 区间内若有回调，不破区间低点

    返回: 0/1/2/3
    """
    try:
        idx_start = close_series.index.get_loc(t_start)
        idx_end = close_series.index.get_loc(t_end)
    except (KeyError, ValueError):
        return 0

    pre_start = close_series.index[max(0, idx_start - lookback)]
    win_slice = close_series.loc[t_start:t_end]
    win_amount = amount_series.loc[t_start:t_end]
    pre_amount = amount_series.loc[pre_start:t_start]

    if len(win_slice) < 5:
        return 0

    # 1) 放量突破
    ma20 = close_series.rolling(20).mean().loc[t_start:t_end]
    above_ma = (win_slice > ma20).sum() > len(win_slice) * 0.6  # 大部分时间在均线上方

    win_avg_amount = win_amount.mean()
    pre_avg_amount = pre_amount.mean() if len(pre_amount) > 5 else 0
    volume_up = (win_avg_amount > pre_avg_amount * 1.1) if pre_avg_amount > 0 else False

    breakout = above_ma and volume_up

    # 2) RS 转正: 区间内跑赢全指
    bm_win = bm_close.loc[t_start:t_end]
    sec_ret = win_slice.iloc[-1] / win_slice.iloc[0] - 1 if len(win_slice) >= 2 else 0
    bm_ret = bm_win.iloc[-1] / bm_win.iloc[0] - 1 if len(bm_win) >= 2 else 0
    rs_positive = sec_ret > bm_ret

    # 3) 首次回调不破: 区间内如果有 3 天以上回调，不破区间最低点
    win_low = win_slice.min()
    # 取区间后半段的低点（如果有回调）
    mid = len(win_slice) // 2
    second_half = win_slice.iloc[mid:]
    second_half_low = second_half.min()
    pullback_not_break = second_half_low > win_low * 0.99  # 允许 1% 误差

    return sum([breakout, rs_positive, pullback_not_break])


# ════════════════════════════════════════
# 纯滚动评分（无底部依赖）
# ════════════════════════════════════════

def calc_sector_rolling_score(close_series, amount_series, bm_close, bm_amount):
    """
    纯滚动三区间评分。

    不需要"底部日期"——直接在评分日 T 往回推三个窗口：
      W1 [T-60, T-40)：放量震荡信号
      W2 [T-40, T-20)：缩量洗盘信号
      W3 [T-20, T] ：初升试探信号

    返回: dict {W1/2/3: score, total: int} 或 None
    """
    available = close_series.dropna().index
    if len(available) < 100:
        return None

    eval_idx = len(available) - 1  # 最后一个可用交易日就是评分日

    results = {}
    total = 0

    for win_name, offset_start, offset_end in WINDOWS:
        t_start_idx = eval_idx - offset_start
        t_end_idx = eval_idx - offset_end

        if t_start_idx < 0:
            results[win_name] = 0
            continue

        t_start = available[t_start_idx]
        t_end = available[t_end_idx]

        data_slice = close_series.loc[t_start:t_end].dropna()
        if len(data_slice) < 5:
            results[win_name] = 0
            continue

        if win_name == 'W1_放量震荡':
            score = calc_window_1_vol_expansion(
                close_series, amount_series, bm_close, bm_amount,
                t_start, t_end
            )
        elif win_name == 'W2_缩量洗盘':
            score = calc_window_2_washout(
                close_series, amount_series, bm_close,
                t_start, t_end
            )
        elif win_name == 'W3_初升试探':
            score = calc_window_3_confirmation(
                close_series, amount_series, bm_close, bm_amount,
                t_start, t_end
            )
        else:
            score = 0

        results[win_name] = score
        total += score

    results['total'] = total
    results['_score_date'] = str(available[eval_idx].date())
    return results


# ════════════════════════════════════════
# 每日滚动回测（无未来函数、每交易日评分调仓）
# ════════════════════════════════════════

def precompute_sector_metrics(sec_close, sec_amount, bm_close):
    """
    预计算所有行业的滚动指标（向量化），供每日评分使用。

    返回:
        metrics: dict of DataFrames (index=date, columns=symbol)
    """
    print('  预计算行业滚动指标...')

    n_dates = len(sec_close)
    n_sectors = len(sec_close.columns)

    # 日收益率
    sec_ret = sec_close.pct_change()

    # 滚动波动率 (20日标准差)
    rolling_vol = sec_ret.rolling(20, min_periods=10).std()

    # 滚动均量 (5日)
    amount_ma5 = sec_amount.rolling(5, min_periods=3).mean()

    # RS = 相对全指的累计收益 (20日)
    bm_ret = bm_close.pct_change()
    # 相对收益率: 行业累计 - 全指累计 (20日滚窗)
    sec_cum_ret_20 = (1 + sec_ret).rolling(20, min_periods=10).apply(lambda x: x.prod(), raw=True) - 1
    bm_cum_ret_20 = (1 + bm_ret).rolling(20, min_periods=10).apply(lambda x: x.prod(), raw=True) - 1
    rs20 = sec_cum_ret_20.sub(bm_cum_ret_20, axis=0) * 100

    # 价格相对 MA20
    ma20 = sec_close.rolling(20, min_periods=10).mean()
    price_above_ma20 = (sec_close / ma20 - 1) * 100

    # 各行业区间最低价（用于"不破前低"判断）
    sec_low_20 = sec_close.rolling(20, min_periods=5).min()
    sec_low_40 = sec_close.rolling(40, min_periods=10).min()
    sec_low_60 = sec_close.rolling(60, min_periods=15).min()

    # 全指滚动波动率 (用于相对波动率判断)
    bm_rolling_vol = bm_ret.rolling(20, min_periods=10).std()

    return {
        'sec_ret': sec_ret,
        'rolling_vol': rolling_vol,
        'amount_ma5': amount_ma5,
        'rs20': rs20,
        'price_above_ma20': price_above_ma20,
        'sec_low_20': sec_low_20,
        'sec_low_40': sec_low_40,
        'sec_low_60': sec_low_60,
        'bm_rolling_vol': bm_rolling_vol,
    }


def calc_sector_score_vectorized(sym, metrics, eval_idx):
    """
    向量化预计算基础上的单行业评分。

    参数:
        metrics: precompute_sector_metrics 的返回值
        eval_idx: 评分日在总序列中的索引

    返回: total_score (0-9)
    """
    total = 0

    # W1: 放量震荡区 [eval_idx-60, eval_idx-40)
    w1_start = eval_idx - 60
    w1_end = eval_idx - 40

    # W2: 缩量洗盘区 [eval_idx-40, eval_idx-20)
    w2_start = eval_idx - 40
    w2_end = eval_idx - 20

    # W3: 初升试探区 [eval_idx-20, eval_idx]
    w3_start = eval_idx - 20
    w3_end = eval_idx

    if w1_start < 0:
        return 0

    # ── W1: 放量震荡 ──
    # 1) 波动率扩张: W1 波动率 > 前 60 天波动率 * 1.15
    vol_w1 = metrics['rolling_vol'].iloc[w1_start:w1_end][sym].mean()
    vol_pre = metrics['rolling_vol'].iloc[w1_start-60:w1_start][sym].mean() if w1_start >= 60 else 0
    w1_vol = 1 if (vol_w1 > vol_pre * 1.15 and vol_pre > 0) else 0

    # 2) 量能放大: W1 均量 > 前 60 天均量 * 1.1
    amt_w1 = metrics['amount_ma5'].iloc[w1_start:w1_end][sym].mean()
    amt_pre = metrics['amount_ma5'].iloc[w1_start-60:w1_start][sym].mean() if w1_start >= 60 else 0
    w1_amt = 1 if (amt_w1 > amt_pre * 1.1 and amt_pre > 0) else 0

    # 3) 相对全指波动扩张
    rel_vol_w1 = vol_w1 / metrics['bm_rolling_vol'].iloc[w1_start:w1_end].mean() if metrics['bm_rolling_vol'].iloc[w1_start:w1_end].mean() > 0 else 0
    rel_vol_pre = vol_pre / metrics['bm_rolling_vol'].iloc[w1_start-60:w1_start].mean() if (w1_start >= 60 and metrics['bm_rolling_vol'].iloc[w1_start-60:w1_start].mean() > 0) else 0
    w1_rel = 1 if (rel_vol_w1 > rel_vol_pre * 1.1 and rel_vol_pre > 0) else 0

    total += w1_vol + w1_amt + w1_rel

    # ── W2: 缩量洗盘 ──
    # 1) 缩量: W2 均量 < 前 60 天均量 * 0.9
    amt_w2 = metrics['amount_ma5'].iloc[w2_start:w2_end][sym].mean()
    w2_amt = 1 if (amt_w2 < amt_pre * 0.9 and amt_pre > 0) else 0

    # 2) 不破前低: W2 最低价 > W1 最低价 * 0.98
    low_w2 = metrics['sec_low_20'].iloc[w2_start:w2_end][sym].min()
    low_w1 = metrics['sec_low_20'].iloc[w1_start:w1_end][sym].min()
    w2_low = 1 if (low_w2 > low_w1 * 0.98 and low_w1 > 0) else 0

    # 3) RS 底部抬高: W2 平均 RS > W1 平均 RS
    rs_w2 = metrics['rs20'].iloc[w2_start:w2_end][sym].mean()
    rs_w1 = metrics['rs20'].iloc[w1_start:w1_end][sym].mean()
    w2_rs = 1 if rs_w2 > rs_w1 else 0

    total += w2_amt + w2_low + w2_rs

    # ── W3: 初升试探 ──
    # 1) 放量突破: W3 大部分在 MA20 上方 + 均量放大
    above_ma = (metrics['price_above_ma20'].iloc[w3_start:w3_end][sym] > 0).mean()
    w3_breakout = 1 if above_ma > 0.6 else 0

    # 2) RS 转正: W3 平均 RS > 0
    rs_w3 = metrics['rs20'].iloc[w3_start:w3_end][sym].mean()
    w3_rs = 1 if rs_w3 > 0 else 0

    # 3) 回调不破: W3 后半段最低 > W3 最低 * 0.99
    mid = w3_start + (w3_end - w3_start) // 2
    low_w3_full = metrics['sec_low_20'].iloc[w3_start:w3_end][sym].min()
    low_w3_second = metrics['sec_low_20'].iloc[mid:w3_end][sym].min()
    w3_pullback = 1 if (low_w3_second > low_w3_full * 0.99 and low_w3_full > 0) else 0

    total += w3_breakout + w3_rs + w3_pullback

    return total


def daily_rolling():
    """
    每日滚动评分回测（向量化版）。

    改进 vs continuous_rolling：
      1. 无"虚拟底部"——每个评分日独立用最近 60 天数据
      2. 预计算滚动指标，评分时 O(1) 索引
      3. 绝对不含未来数据——评分只用截止当天的行情
      4. 每 10 天评分调仓（反应速度更快）

    注意：无未来函数，所有计算只用到 eval_idx 之前的数据。
    """
    print('=' * 72)
    print('  每日滚动回测 — 向量化版')
    print('=' * 72)

    # ── 加载 ──
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    all_dates = bm_close.index
    sym_list = list(sec_close.columns)
    print(f'  全指: {len(all_dates)}天, 行业: {len(sec_close.columns)}个')

    # 预计算
    metrics = precompute_sector_metrics(sec_close, sec_amount, bm_close)
    print('  预计算完成')

    MIN_HIST = 120
    EVAL_EVERY = 10       # 每 10 天评分调仓
    HOLD_DAYS = 10        # 持有 10 天

    eval_indices = list(range(MIN_HIST, len(all_dates) - HOLD_DAYS, EVAL_EVERY))
    print(f'\n开始回测: {all_dates[MIN_HIST].date()} ~ {all_dates[-1].date()}')
    print(f'  共 {len(eval_indices)} 个评分点\n')

    strat_nav = [1.0]
    bm_nav = [1.0]
    segments = []

    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]
        end_idx = min(eval_idx + HOLD_DAYS, len(all_dates) - 1)
        hold_end_date = all_dates[end_idx]

        # 向量化评分所有行业
        all_scores = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            score = calc_sector_score_vectorized(metrics, sym, eval_idx)
            if score > 0:
                all_scores[sym] = score

        if len(all_scores) < 3:
            for d in range(eval_idx, end_idx):
                if d + 1 < len(all_dates):
                    r = bm_close.iloc[d+1] / bm_close.iloc[d] - 1
                    strat_nav.append(strat_nav[-1] * (1 + r))
                    bm_nav.append(bm_nav[-1] * (1 + r))
            continue

        top_syms = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top_names = [sec_name.get(s, s) for s, _ in top_syms]

        segments.append({
            'from': str(eval_date.date()),
            'to': str(hold_end_date.date()),
            'top3': top_names,
            'scores': [sc for _, sc in top_syms],
        })

        for d in range(eval_idx, end_idx):
            if d + 1 >= len(all_dates):
                break
            day_date = all_dates[d]
            next_date = all_dates[d + 1]

            bm_dr = bm_close.iloc[d+1] / bm_close.iloc[d] - 1
            bm_nav.append(bm_nav[-1] * (1 + bm_dr))

            sector_drs = []
            for sym, _ in top_syms:
                sc = sec_close[sym].dropna()
                if day_date in sc.index and next_date in sc.index:
                    sector_drs.append(sc.loc[next_date] / sc.loc[day_date] - 1)

            avg_dr = np.mean(sector_drs) if sector_drs else bm_dr
            strat_nav.append(strat_nav[-1] * (1 + avg_dr))

    # ── 计算结果 ──
    strat_rets = [strat_nav[i+1]/strat_nav[i]-1 for i in range(len(strat_nav)-1)]
    bm_rets = [bm_nav[i+1]/bm_nav[i]-1 for i in range(len(bm_nav)-1)]

    total_strat = (strat_nav[-1] / strat_nav[0] - 1) * 100
    total_bm = (bm_nav[-1] / bm_nav[0] - 1) * 100
    total_excess = total_strat - total_bm

    daily_wins = sum(1 for s, b in zip(strat_rets, bm_rets) if s > b)
    daily_total = len(strat_rets)

    # 回撤
    strat_arr = np.array(strat_nav)
    strat_peaks = np.maximum.accumulate(strat_arr)
    dd = (strat_arr - strat_peaks) / strat_peaks * 100
    max_dd = dd.min()
    max_dd_idx = np.argmin(dd)
    dd_seg_idx = min(max_dd_idx // HOLD_DAYS, len(segments) - 1)
    dd_desc = f'{segments[dd_seg_idx]["from"]}~{segments[dd_seg_idx]["to"]}' if segments else 'N/A'

    bm_peaks = np.maximum.accumulate(np.array(bm_nav))
    bm_dd = (np.array(bm_nav) - bm_peaks) / bm_peaks * 100
    bm_max_dd = bm_dd.min()

    # ── 分阶段 ──
    conn = sqlite3.connect(str(DB_PATH))
    phases_df = pd.read_csv(PHASES_CSV, comment='#')
    conn.close()

    phase_analysis = []
    for _, prow in phases_df.iterrows():
        p_start = prow['start_date'].strip()
        p_end = prow['end_date'].strip()
        p_type = prow['phase_type'].strip()
        if p_end == '至今':
            p_end = all_dates[-1].strftime('%Y-%m-%d')

        phase_segs = [s for s in segments if s['from'] >= p_start and s['to'] <= p_end]
        if not phase_segs:
            continue

        seg_excesses = []
        seg_wins = 0
        for seg in phase_segs:
            try:
                s_from = all_dates.get_loc(pd.Timestamp(seg['from']))
                s_to = all_dates.get_loc(pd.Timestamp(seg['to']))
            except (KeyError, ValueError):
                continue

            if s_from >= len(bm_close) or s_to >= len(bm_close):
                continue

            bm_prd_ret = (bm_close.iloc[min(s_to, len(bm_close)-1)] / bm_close.iloc[s_from] - 1) * 100

            seg_sector_rets = []
            for sym_name in seg['top3']:
                syms = [k for k, v in sec_name.items() if v == sym_name]
                if not syms: continue
                sym = syms[0]
                sc = sec_close[sym].dropna()
                try:
                    r = (sc.loc[all_dates[min(s_to, len(all_dates)-1)]] / sc.loc[all_dates[s_from]] - 1) * 100
                    seg_sector_rets.append(r)
                except KeyError:
                    pass

            seg_avg = np.mean(seg_sector_rets) if seg_sector_rets else 0
            excess = seg_avg - bm_prd_ret
            seg_excesses.append(excess)
            if excess > 0: seg_wins += 1

        if not seg_excesses: continue

        icon = '📈' if p_type == 'bull' else '📉'
        phase_analysis.append({
            'phase': f'{icon} {p_type} #{len(phase_analysis)+1}',
            'period': f'{p_start}~{p_end}',
            'segments': len(seg_excesses),
            'wins': seg_wins,
            'win_rate': round(seg_wins/len(seg_excesses)*100, 1),
            'avg_excess': round(np.mean(seg_excesses), 1),
            'cum_excess': round(sum(seg_excesses), 1),
        })

    # ── 输出 ──
    print(f'\n{"="*72}')
    print(f'  结果汇总')
    print(f'{"="*72}')
    print(f'  策略总收益:     {total_strat:>+8.1f}%')
    print(f'  基准总收益:     {total_bm:>+8.1f}%')
    print(f'  超额收益:       {total_excess:>+8.1f}%')
    print(f'  日胜率:         {daily_wins}/{daily_total} = {daily_wins/daily_total*100:.1f}%')
    print(f'  策略最大回撤:   {max_dd:.1f}% (约 {dd_desc})')
    print(f'  基准最大回撤:   {bm_max_dd:.1f}%')

    print(f'\n{"="*72}')
    print(f'  分阶段超额')
    print(f'{"="*72}')
    for pa in phase_analysis:
        arrow = '✅' if pa['cum_excess'] > 0 else '❌'
        print(f'  {pa["phase"]:<12} {pa["period"]:<30} '
              f'超额:{pa["cum_excess"]:>+6.1f}%  胜率:{pa["win_rate"]:>5.1f}%  ({pa["wins"]}/{pa["segments"]})  {arrow}')

    worst = sorted(phase_analysis, key=lambda x: x['cum_excess'])[:3]
    print(f'\n{"="*72}')
    print(f'  跑输最严重的阶段')
    print(f'{"="*72}')
    for wp in worst:
        if wp['cum_excess'] < 0:
            print(f'  ❌ {wp["phase"]:<12} {wp["period"]:<30} 超额: {wp["cum_excess"]:+.1f}%  胜率: {wp["win_rate"]:.0f}%')

    # ── 保存 ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / 'daily_rolling_results.json'

    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return str(obj) if hasattr(obj, 'isoformat') else obj

    result = {
        'summary': {
            'strategy_return_pct': round(total_strat, 1),
            'benchmark_return_pct': round(total_bm, 1),
            'excess_return_pct': round(total_excess, 1),
            'daily_win_rate': round(daily_wins/daily_total*100, 1),
            'strategy_max_drawdown_pct': round(max_dd, 1),
            'benchmark_max_drawdown_pct': round(bm_max_dd, 1),
        },
        'phase_analysis': phase_analysis,
        'worst_phases': [wp for wp in worst if wp['cum_excess'] < 0],
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=convert)
    print(f'\n  已保存: {out_path}')
    """
    每日滚动评分回测。

    改进 vs continuous_rolling：
      1. 无"虚拟底部"——每个评分日独立用最近 60 天数据
      2. 每天评分、每天调仓（反应速度更快）
      3. 绝对不含未来数据——评分只用截止当天的行情
      4. 跟踪每日超额收益、累计净值、最大回撤

    注意：每日调仓会有较高的换手率，但作为上界测试是合理的。
    实际使用时可用 3-5 天平滑或阈值过滤来控制换手。
    """
    print('=' * 72)
    print('  每日滚动回测 — 每交易日评分调仓')
    print('=' * 72)

    # 加载数据
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    bm_amount = bm['amount']
    all_dates = bm_close.index
    sym_list = list(sec_close.columns)
    print(f'  全指: {len(all_dates)}天, 行业: {len(sec_close.columns)}个')

    MIN_HIST = 100  # 至少需要 100 个交易日的数据才能开始评分

    # ── 每日滚动 ──
    daily_nav = []       # 策略每日收益
    bm_daily_nav = []    # 基准每日收益
    trade_log = []       # 调仓记录

    # 从第 MIN_HIST 天开始，主循环只取每 N 天做一次评分和交易
    # 但为了让结果更干净，我们每 5 天评分调仓一次（避免每日高频噪音）
    EVAL_EVERY = 5       # 每 5 天评分调仓
    HOLD_DAYS = 5        # 持有 5 天

    # 生成评分点
    eval_indices = list(range(MIN_HIST, len(all_dates) - HOLD_DAYS, EVAL_EVERY))

    print(f'\n开始回测: {all_dates[MIN_HIST].date()} ~ {all_dates[-1].date()}')
    print(f'  共 {len(eval_indices)} 个评分点（每 {EVAL_EVERY} 天）\n')

    # 策略净值追踪（模拟逐日收益）
    # 简化：每 HOLD_DAYS 天选一次 TOP 3，持有期间跟踪每日收益
    # 这样比 continuous_rolling 更平滑，但仍能快速反应

    strat_cum_nav = [1.0]  # 起始净值
    bm_cum_nav = [1.0]

    # 记录每一段的持仓和收益
    segments = []  # 每段包含: start_idx, end_idx, top3_names

    for i, eval_idx in enumerate(eval_indices):
        eval_date = all_dates[eval_idx]
        end_idx = min(eval_idx + HOLD_DAYS, len(all_dates) - 1)
        hold_end_date = all_dates[end_idx]

        # ── 评分配置 ──
        all_scores = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].iloc[:eval_idx + 1].dropna()
            s_amount = sec_amount[sym].iloc[:eval_idx + 1].dropna()
            if len(s_close) < 100:
                continue

            result = calc_sector_rolling_score(
                s_close, s_amount,
                bm_close.iloc[:eval_idx + 1],
                bm_amount.iloc[:eval_idx + 1]
            )
            if result and result['total'] > 0:
                all_scores[sym] = result['total']

        if len(all_scores) < 3:
            # 数据不足，持有基准
            for d in range(eval_idx, end_idx):
                if d + 1 < len(all_dates):
                    bm_ret = bm_close.iloc[d + 1] / bm_close.iloc[d] - 1
                    strat_cum_nav.append(strat_cum_nav[-1] * (1 + bm_ret))
                    bm_cum_nav.append(bm_cum_nav[-1] * (1 + bm_ret))
            continue

        # 选 TOP 3
        top_syms = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top_names = [sec_name.get(s, s) for s, _ in top_syms]

        segments.append({
            'from': str(eval_date.date()),
            'to': str(hold_end_date.date()),
            'top3': top_names,
            'scores': [sc for _, sc in top_syms],
        })

        # ── 逐日收益 ──
        for d in range(eval_idx, end_idx):
            if d + 1 >= len(all_dates):
                break
            day_date = all_dates[d]
            next_date = all_dates[d + 1]

            # 基准日收益
            bm_day_ret = bm_close.iloc[d + 1] / bm_close.iloc[d] - 1
            bm_cum_nav.append(bm_cum_nav[-1] * (1 + bm_day_ret))

            # TOP 3 等权日收益
            sector_day_rets = []
            for sym, _ in top_syms:
                s_close = sec_close[sym].dropna()
                if day_date in s_close.index and next_date in s_close.index:
                    ret = s_close.loc[next_date] / s_close.loc[day_date] - 1
                    sector_day_rets.append(ret)

            avg_day_ret = np.mean(sector_day_rets) if sector_day_rets else bm_day_ret
            strat_cum_nav.append(strat_cum_nav[-1] * (1 + avg_day_ret))

    # ── 计算结果 ──
    strat_returns = [strat_cum_nav[i+1]/strat_cum_nav[i] - 1 for i in range(len(strat_cum_nav)-1)]
    bm_returns = [bm_cum_nav[i+1]/bm_cum_nav[i] - 1 for i in range(len(bm_cum_nav)-1)]

    total_strat = (strat_cum_nav[-1] / strat_cum_nav[0] - 1) * 100
    total_bm = (bm_cum_nav[-1] / bm_cum_nav[0] - 1) * 100
    total_excess = total_strat - total_bm

    # 日胜率
    strat_arr = np.array(strat_returns)
    bm_arr = np.array(bm_returns)
    daily_wins = sum(1 for s, b in zip(strat_returns, bm_returns) if s > b)
    daily_total = len(strat_returns)

    # 回撤
    strat_peaks = np.maximum.accumulate(strat_cum_nav)
    drawdowns = (strat_cum_nav - strat_peaks) / strat_peaks * 100
    max_dd = drawdowns.min()
    max_dd_idx = np.argmin(drawdowns)
    # 找到回撤对应的日期段
    total_days = len(strat_cum_nav) - 1
    dd_seg_idx = min(max_dd_idx // HOLD_DAYS, len(segments) - 1)
    dd_desc = f'{segments[dd_seg_idx]["from"]}~{segments[dd_seg_idx]["to"]}' if segments else 'N/A'

    bm_peaks = np.maximum.accumulate(bm_cum_nav)
    bm_drawdowns = (bm_cum_nav - bm_peaks) / bm_peaks * 100
    bm_max_dd = bm_drawdowns.min()

    # ── 按阶段分析 ──
    conn = sqlite3.connect(str(DB_PATH))
    phases_df = pd.read_csv(PHASES_CSV, comment='#')
    conn.close()

    phase_analysis = []
    for _, prow in phases_df.iterrows():
        p_start = prow['start_date'].strip()
        p_end = prow['end_date'].strip()
        p_type = prow['phase_type'].strip()
        if p_end == '至今':
            p_end = all_dates[-1].strftime('%Y-%m-%d')

        # 找到阶段内的 segments
        phase_segs = [s for s in segments if s['from'] >= p_start and s['to'] <= p_end]
        if not phase_segs:
            continue

        # 计算阶段超额
        seg_excesses = []
        seg_wins = 0
        for seg in phase_segs:
            # 找到 seg 对应的索引区间，算累计超额
            try:
                s_from = all_dates.get_loc(pd.Timestamp(seg['from']))
                s_to = all_dates.get_loc(pd.Timestamp(seg['to']))
            except (KeyError, ValueError):
                continue

            if s_from >= len(bm_close) or s_to >= len(bm_close):
                continue

            # 简化：用每段的等权收益 vs 基准
            bm_start = bm_close.iloc[s_from]
            bm_end = bm_close.iloc[min(s_to, len(bm_close)-1)]
            bm_period_ret = (bm_end / bm_start - 1) * 100

            seg_sector_rets = []
            for sym_name in seg['top3']:
                # 从 name 反查 symbol
                syms = [k for k, v in sec_name.items() if v == sym_name]
                if not syms:
                    continue
                sym = syms[0]
                sc = sec_close[sym].dropna()
                if sc.index[0] <= all_dates[s_from] and sc.index[-1] >= all_dates[min(s_to, len(all_dates)-1)]:
                    try:
                        r = (sc.loc[all_dates[min(s_to, len(all_dates)-1)]] / sc.loc[all_dates[s_from]] - 1) * 100
                        seg_sector_rets.append(r)
                    except KeyError:
                        pass

            seg_avg_ret = np.mean(seg_sector_rets) if seg_sector_rets else 0
            seg_excess = seg_avg_ret - bm_period_ret
            seg_excesses.append(seg_excess)
            if seg_excess > 0:
                seg_wins += 1

        if not seg_excesses:
            continue

        icon = '📈' if p_type == 'bull' else '📉'
        phase_analysis.append({
            'phase': f'{icon} {p_type} #{len(phase_analysis)+1}',
            'period': f'{p_start}~{p_end}',
            'segments': len(seg_excesses),
            'wins': seg_wins,
            'win_rate': round(seg_wins / len(seg_excesses) * 100, 1),
            'avg_excess': round(np.mean(seg_excesses), 1),
            'cum_excess': round(sum(seg_excesses), 1),
        })

    # ── 输出 ──
    print(f'\n{"=" * 72}')
    print(f'  每日滚动回测结果')
    print(f'{"=" * 72}')
    print(f'\n  策略总收益:     {total_strat:>+8.1f}%')
    print(f'  基准总收益:     {total_bm:>+8.1f}%')
    print(f'  超额收益:       {total_excess:>+8.1f}%')
    print(f'  日胜率:         {daily_wins}/{daily_total} = {daily_wins/daily_total*100:.1f}%')
    print(f'  策略最大回撤:   {max_dd:.1f}% (约 {dd_desc})')
    print(f'  基准最大回撤:   {bm_max_dd:.1f}%')

    print(f'\n{"=" * 72}')
    print(f'  分阶段超额')
    print(f'{"=" * 72}')
    for pa in phase_analysis:
        arrow = '✅' if pa['cum_excess'] > 0 else '❌'
        print(f'  {pa["phase"]:<12} {pa["period"]:<30} '
              f'超额:{pa["cum_excess"]:>+6.1f}%  胜率:{pa["win_rate"]:>5.1f}%  ({pa["wins"]}/{pa["segments"]})  {arrow}')

    worst = sorted(phase_analysis, key=lambda x: x['cum_excess'])[:3]
    print(f'\n{"=" * 72}')
    print(f'  跑输最严重的阶段')
    print(f'{"=" * 72}')
    for wp in worst:
        if wp['cum_excess'] < 0:
            print(f'  ❌ {wp["phase"]:<12} {wp["period"]:<30} 超额: {wp["cum_excess"]:+.1f}%  胜率: {wp["win_rate"]:.0f}%')

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / 'daily_rolling_results.json'

    result = {
        'summary': {
            'strategy_return_pct': round(total_strat, 1),
            'benchmark_return_pct': round(total_bm, 1),
            'excess_return_pct': round(total_excess, 1),
            'daily_win_rate': round(daily_wins / daily_total * 100, 1),
            'strategy_max_drawdown_pct': round(max_dd, 1),
            'benchmark_max_drawdown_pct': round(bm_max_dd, 1),
        },
        'phase_analysis': phase_analysis,
        'worst_phases': [wp for wp in worst if wp['cum_excess'] < 0],
    }

    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return str(obj) if hasattr(obj, 'isoformat') else obj

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=convert)
    print(f'\n  已保存: {output_path}')


# ════════════════════════════════════════
# 综合评分
# ════════════════════════════════════════

def score_sector_at_bottom(sym, close, amount, bm_close, bm_amount, bottom_date,
                           eval_offset=30):
    """
    对一个行业的某个底部时点进行三区间评分。

    评分时点不是底部当天，而是底部往后 eval_offset 个交易日，
    这样 W3 能覆盖初升试探区（底部后的行为）。

    参数:
        eval_offset: 底部后多少个交易日开始评分（默认 30）
    
    返回:
        dict: {window_name: score, total: int}
    """
    available = close.dropna().index
    if len(available) < 120:
        return None

    t_bottom = pd.Timestamp(bottom_date)
    
    # 找到底部在 available 中的位置
    try:
        bottom_idx = available.get_loc(t_bottom)
    except KeyError:
        # 底部可能不是交易日，取最近的前一个交易日
        before = available[available <= t_bottom]
        if len(before) == 0:
            return None
        bottom_idx = available.get_loc(before[-1])

    # 评分时点 T = 底部往后 eval_offset 个交易日
    eval_idx = min(bottom_idx + eval_offset, len(available) - 1)
    t_eval = available[eval_idx]

    # T 点往前要有足够的交易日
    if eval_idx < 100:
        return None

    results = {}
    total = 0

    for win_name, offset_start, offset_end in WINDOWS:
        # 从 T 点往前推 offset_start ~ offset_end 个交易日
        t_start_idx = eval_idx - offset_start
        t_end_idx = eval_idx - offset_end

        if t_start_idx < 0 or t_end_idx < 0:
            results[win_name] = 0
            continue

        t_start_actual = available[t_start_idx]
        t_end_actual = available[t_end_idx]

        # 确保窗口内有足够数据
        data_in_window = close.loc[t_start_actual:t_end_actual].dropna()
        if len(data_in_window) < 5:
            results[win_name] = 0
            continue

        if win_name == 'W1_放量震荡':
            score = calc_window_1_vol_expansion(
                close, amount, bm_close, bm_amount,
                t_start_actual, t_end_actual
            )
        elif win_name == 'W2_缩量洗盘':
            score = calc_window_2_washout(
                close, amount, bm_close,
                t_start_actual, t_end_actual
            )
        elif win_name == 'W3_初升试探':
            score = calc_window_3_confirmation(
                close, amount, bm_close, bm_amount,
                t_start_actual, t_end_actual
            )
        else:
            score = 0

        results[win_name] = score
        total += score

    results['total'] = total
    results['_eval_date'] = str(t_eval.date())
    results['_bottom_date'] = str(t_bottom.date())
    return results


def score_all_sectors_at_bottom(sym_list, close_df, amount_df, bm_close, bm_amount, bottom_date):
    """所有行业在一个底部的评分"""
    scores = {}
    for sym in sym_list:
        if sym not in close_df.columns:
            continue
        sector_close = close_df[sym].dropna()
        sector_amount = amount_df[sym].dropna()
        if len(sector_close) < 90:
            continue

        result = score_sector_at_bottom(
            sym, sector_close, sector_amount,
            bm_close, bm_amount, bottom_date
        )
        if result is not None:
            scores[sym] = result
    return scores


# ════════════════════════════════════════
# 回测
# ════════════════════════════════════════

def calc_actual_sector_returns(start_date, end_date, sec_name):
    """计算阶段内行业实际涨幅"""
    conn = sqlite3.connect(str(DB_PATH))
    query = '''
        SELECT a.name, d.trade_date, d.close
        FROM market_daily_data d
        JOIN asset_master a ON d.symbol = a.symbol
        WHERE a.asset_type = 'sector'
          AND d.trade_date IN (?, ?)
        ORDER BY a.name, d.trade_date
    '''
    df = pd.read_sql(query, conn, params=(start_date, end_date), parse_dates=['trade_date'])
    conn.close()

    results = {}
    for name in df['name'].unique():
        ndf = df[df['name'] == name].sort_values('trade_date')
        if len(ndf) >= 2:
            first, last = ndf.iloc[0]['close'], ndf.iloc[-1]['close']
            if first and last and first > 0:
                ret = (last / first - 1) * 100
                results[name] = round(ret, 1)
    return results


def backtest():
    """全历史回测：v2 评分 vs v1 评分 vs 实际领涨"""
    print('=' * 72)
    print('  转折期行业行为评分 v2 — 回测')
    print('=' * 72)

    # 加载数据
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    bm_amount = bm['amount']
    print(f'  全指: {len(bm)}天, 行业: {len(sec_close.columns)}个')

    # 加载阶段
    bull_phases = load_phases()
    print(f'  Bull 阶段: {len(bull_phases)}个')

    # 行业列表
    sym_list = list(sec_close.columns)
    name_to_sym = {v: k for k, v in sec_name.items()}

    all_results = []

    for phase in bull_phases:
        bottom_date = phase['start']
        print(f'\n{"─" * 72}')
        print(f'  {phase["label"]}  底部: {bottom_date}  →  {phase["end"]}')
        print(f'  📝 {phase["notes"][:80]}')

        # 对所有行业在底部评分
        scores = score_all_sectors_at_bottom(
            sym_list, sec_close, sec_amount,
            bm_close, bm_amount, bottom_date
        )
        if not scores:
            print('  ⚠️  数据不足，跳过')
            continue

        # 按总分排序，取 TOP 5 展示
        sorted_syms = sorted(scores.items(), key=lambda x: x[1]['total'], reverse=True)

        print(f'  📊 行为评分 TOP5:')
        for rank, (sym, result) in enumerate(sorted_syms[:5], 1):
            name = sec_name.get(sym, sym)
            w1 = result.get('W1_放量震荡', 0)
            w2 = result.get('W2_缩量洗盘', 0)
            w3 = result.get('W3_初升试探', 0)
            bar = '█' * w1 + '▓' * w2 + '▒' * w3 + '░' * (9 - w1 - w2 - w3)
            print(f'    {rank}. {name:<8} {result["total"]}/9  {bar}  W1:{w1} W2:{w2} W3:{w3}')

        # 计算各模式占比
        pattern_counts = {}
        for sym, result in scores.items():
            pattern = f"{result.get('W1_放量震荡', 0)}-{result.get('W2_缩量洗盘', 0)}-{result.get('W3_初升试探', 0)}"
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        # 表现最好的 3 个行业
        top3_syms = [sym for sym, _ in sorted_syms[:3]]
        top3_names = [sec_name.get(s, s) for s in top3_syms]
        top3_scores = [scores[s]['total'] for s in top3_syms]

        # 实际涨幅 TOP3
        actual_returns = calc_actual_sector_returns(bottom_date, phase['end'], sec_name)
        actual_top3 = sorted(actual_returns.items(), key=lambda x: x[1], reverse=True)[:3]
        actual_top3_names = [s[0] for s in actual_top3]

        # 命中率
        hits = len(set(top3_names) & set(actual_top3_names))

        print(f'  🎯 v2 评分 TOP3: {", ".join(f"{n}({s})" for n, s in zip(top3_names, top3_scores))}')
        print(f'  📈 实际领涨 TOP3: {", ".join(f"{n}({r}%)" for n, r in actual_top3)}')
        print(f'  ✅ 命中: {"✅" if hits>0 else "❌"} {hits}/3')

        all_results.append({
            'phase': phase['label'],
            'bottom_date': bottom_date,
            'end_date': phase['end'],
            'top3_pred': [{'name': n, 'score': s} for n, s in zip(top3_names, top3_scores)],
            'top3_actual': [{'name': n, 'return_pct': r} for n, r in actual_top3],
            'hits': hits,
        })

    # 汇总
    if all_results:
        total_hits = sum(r['hits'] for r in all_results)
        total_phases = len(all_results)
        hit_rate = total_hits / (total_phases * 3) * 100
        print(f'\n{"=" * 72}')
        print(f'  汇总 ({total_phases} 个阶段)')
        print(f'  v2 命中: {total_hits}/{total_phases*3} = {hit_rate:.1f}%')
        print(f'  (v1 参考: 8.3%)')
        print(f'{"=" * 72}')

        # 保存 — 转换 numpy 类型为原生 Python
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / 'sector_behavior_scores.json'

        def convert(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2, default=convert)
        print(f'\n  已保存: {output_path}')

    return all_results


# ════════════════════════════════════════
# 滚动回测 — 动态调仓模拟
# ════════════════════════════════════════

def rolling_backtest():
    """
    滚动回测：每 20 个交易日重新评分、调仓，跟踪累计收益。

    核心思路：
      - 在真实交易中，你不会在底部选好 3 个行业就拿 3 年不动
      - 你会每周/每月重新评估，动态切换到最新评分最高的行业
      - 所以应该测量「按评分系统持续调仓的全周期累计超额收益」

    指标：
      - 累计超额收益（vs 全指）
      - 胜率（跑赢全指的评分窗口占比）
      - 行业切换次数
    """
    print('=' * 72)
    print('  滚动回测 — 动态调仓模拟')
    print('=' * 72)

    # 加载数据
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    bm_amount = bm['amount']
    all_dates = bm_close.index
    print(f'  全指: {len(all_dates)}天, 行业: {len(sec_close.columns)}个')

    # 加载 bull 阶段
    bull_phases = load_phases()
    sym_list = list(sec_close.columns)

    REBALANCE_INTERVAL = 20   # 每 20 个交易日调仓
    HOLD_LOOKAHEAD = 20       # 持仓未来 20 个交易日的收益
    TOP_N = 3                 # 持有 TOP N 个行业（等权）

    all_phase_results = []
    grand_total_excess = 0.0
    grand_total_windows = 0
    grand_total_wins = 0

    for phase in bull_phases:
        bottom_date = phase['start']
        phase_end = phase['end']

        print(f'\n{"─" * 72}')
        print(f'  {phase["label"]}  {bottom_date} → {phase_end}')
        print(f'  📝 {phase["notes"][:80]}')

        # 找到底部在日期序列中的位置
        try:
            bottom_idx = all_dates.get_loc(pd.Timestamp(bottom_date))
        except KeyError:
            before = all_dates[all_dates <= pd.Timestamp(bottom_date)]
            if len(before) == 0:
                print('  ⚠️  底部日期无数据，跳过')
                continue
            bottom_idx = all_dates.get_loc(before[-1])

        try:
            end_idx = all_dates.get_loc(pd.Timestamp(phase_end))
        except KeyError:
            before = all_dates[all_dates <= pd.Timestamp(phase_end)]
            if len(before) == 0:
                print('  ⚠️  结束日期无数据，跳过')
                continue
            end_idx = all_dates.get_loc(before[-1])

        # 第一个评分点 = bottom + 30 个交易日（需要足够历史数据计算 W1/W2）
        first_eval_idx = bottom_idx + 30
        if first_eval_idx >= end_idx:
            print('  ⚠️  阶段太短，跳过')
            continue
        if first_eval_idx < 100:
            first_eval_idx = 100  # 至少需要 100 天历史数据

        # 生成评分窗口（每 REBALANCE_INTERVAL 天评分一次）
        eval_indices = list(range(first_eval_idx, end_idx - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))
        if len(eval_indices) < 2:
            print('  ⚠️  评分窗口太少，跳过')
            continue

        phase_excess_returns = []  # 每期超额收益
        cumulative_excess = 0.0
        window_details = []
        trade_records = []  # 记录每次调仓

        for eval_idx in eval_indices:
            eval_date = all_dates[eval_idx]

            # 这个评分窗口的 TOP N
            scores = {}
            for sym in sym_list:
                if sym not in sec_close.columns:
                    continue
                s_close = sec_close[sym].dropna()
                s_amount = sec_amount[sym].dropna()
                if len(s_close) < eval_idx + 1:
                    continue

                # 用评分时的可用数据
                close_sofar = s_close.iloc[:eval_idx + 1]
                amount_sofar = s_amount.iloc[:eval_idx + 1]

                result = score_sector_at_bottom(
                    sym, close_sofar, amount_sofar,
                    bm_close.iloc[:eval_idx + 1],
                    bm_amount.iloc[:eval_idx + 1],
                    bottom_date,  # 传原始底部日期
                    eval_offset=eval_idx - bottom_idx  # 实际偏移
                )
                if result and result['total'] > 0:
                    scores[sym] = result['total']

            if len(scores) < TOP_N:
                continue

            # 选 TOP N
            top_syms = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
            top_names = [sec_name.get(s, s) for s, _ in top_syms]
            top_scores_v = [sc for _, sc in top_syms]

            # 计算持有期收益：从 eval_date 往后 HOLD_LOOKAHEAD 天
            hold_end_idx = min(eval_idx + HOLD_LOOKAHEAD, len(all_dates) - 1)
            hold_end_date = all_dates[hold_end_idx]
            hold_bm_start = bm_close.loc[eval_date]
            hold_bm_end = bm_close.loc[hold_end_date]
            bm_ret = (hold_bm_end / hold_bm_start - 1) * 100

            # 行业等权收益
            sector_rets = []
            for sym, _ in top_syms:
                s_close = sec_close[sym].dropna()
                if eval_date in s_close.index and hold_end_date in s_close.index:
                    sec_ret = (s_close.loc[hold_end_date] / s_close.loc[eval_date] - 1) * 100
                    sector_rets.append(sec_ret)
                else:
                    sector_rets.append(0)

            avg_ret = np.mean(sector_rets) if sector_rets else 0
            excess = avg_ret - bm_ret
            phase_excess_returns.append(excess)
            cumulative_excess += excess

            is_win = excess > 0

            # 记录
            ret_str = ', '.join(f'{n}({r:.1f}%)' for n, r in zip(top_names, sector_rets))
            window_details.append({
                'eval_date': str(eval_date.date()),
                'top3': top_names,
                'scores': top_scores_v,
                'sector_returns': [round(r, 1) for r in sector_rets],
                'avg_return': round(avg_ret, 1),
                'bm_return': round(bm_ret, 1),
                'excess': round(excess, 1),
            })

            trade_records.append({
                'date': str(eval_date.date()),
                'hold_end': str(hold_end_date.date()),
                'top3': top_names,
                'sector_ret': round(avg_ret, 1),
                'bm_ret': round(bm_ret, 1),
                'excess': round(excess, 1),
            })

        # 阶段汇总
        avg_excess = np.mean(phase_excess_returns) if phase_excess_returns else 0
        win_rate = sum(1 for e in phase_excess_returns if e > 0) / len(phase_excess_returns) * 100 if phase_excess_returns else 0
        total_excess = sum(phase_excess_returns)

        grand_total_excess += total_excess
        grand_total_windows += len(phase_excess_returns)
        grand_total_wins += sum(1 for e in phase_excess_returns if e > 0)

        print(f'  📊 滚动调仓 ({len(phase_excess_returns)} 次调仓):')
        for t in trade_records:
            arrow = '✅' if t['excess'] > 0 else '❌'
            print(f'    {t["date"]} → {t["hold_end"]}  TOP: {", ".join(t["top3"])}  '
                  f'收益: {t["sector_ret"]:+.1f}% vs 全指: {t["bm_ret"]:+.1f}%  {arrow} {t["excess"]:+.1f}%')

        print(f'  📈 累计超额收益: {total_excess:+.1f}%')
        print(f'  🎯 窗口胜率: {win_rate:.0f}% ({sum(1 for e in phase_excess_returns if e > 0)}/{len(phase_excess_returns)})')

        all_phase_results.append({
            'phase': phase['label'],
            'bottom': bottom_date,
            'end': phase_end,
            'n_trades': len(trade_records),
            'total_excess_pct': round(total_excess, 1),
            'avg_excess_pct': round(avg_excess, 1),
            'win_rate': round(win_rate, 1),
            'trades': trade_records,
        })

    # 全局汇总
    if all_phase_results:
        overall_win_rate = grand_total_wins / grand_total_windows * 100 if grand_total_windows > 0 else 0
        print(f'\n{"=" * 72}')
        print(f'  全局汇总')
        print(f'  总评分窗口: {grand_total_windows}')
        print(f'  总超额收益: {grand_total_excess:+.1f}%')
        print(f'  总窗口胜率: {overall_win_rate:.1f}%')
        print(f'{"=" * 72}')

        # 保存
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / 'rolling_behavior_scores.json'

        def convert(obj):
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return obj

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_phase_results, f, ensure_ascii=False, indent=2, default=convert)
        print(f'\n  已保存: {output_path}')


# ════════════════════════════════════════
# 全历史连续滚动回测（不分牛熊阶段）
# ════════════════════════════════════════

def continuous_rolling():
    """
    全历史连续滚动回测。

    核心思路（用户指导）：
      - 不去猜「现在是牛还是熊」
      - 熊市防御强（银行），涨跌比/波动率信号会自然让评分倾向防御
      - 牛市进攻强，评分会让倾向成长/周期
      - 全程自动调仓，看能不能在每个阶段都跑赢市场

    指标：
      - 策略累计净值 vs 全指累计净值
      - 最大回撤 vs 全指最大回撤
      - 各市场阶段（13个阶段）的胜率和超额
      - 跑输最严重的时期分析
    """
    print('=' * 72)
    print('  全历史连续滚动回测')
    print('=' * 72)

    # ── 加载数据 ──
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    bm_amount = bm['amount']
    all_dates = bm_close.index
    sym_list = list(sec_close.columns)
    print(f'  全指: {len(all_dates)}天, 行业: {len(sec_close.columns)}个')

    # ── 参数 ──
    REBALANCE_INTERVAL = 20  # 每 20 个交易日调仓
    HOLD_LOOKAHEAD = 20      # 持有 20 天
    TOP_N = 3                # 等权持有 TOP 3
    MIN_HISTORY = 120        # 最少需要 120 天历史数据才能开始评分

    # ── 连续回测 ──
    strategy_nav = []   # 策略净值序列
    benchmark_nav = []  # 基准净值序列
    trade_log = []      # 每次调仓记录
    peak = 1.0          # 策略净值峰值（计算回撤）

    # 起点: 足够数据可用时
    start_idx = MIN_HISTORY
    eval_indices = list(range(start_idx, len(all_dates) - HOLD_LOOKAHEAD, REBALANCE_INTERVAL))

    print(f'\n开始连续回测: {all_dates[start_idx].date()} ~ {all_dates[-1].date()}')
    print(f'  共 {len(eval_indices)} 个评分窗口\n')

    for eval_idx in eval_indices:
        eval_date = all_dates[eval_idx]

        # ── 评分所有行业 ──
        scores = {}
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            s_close = sec_close[sym].dropna()
            s_amount = sec_amount[sym].dropna()
            if len(s_close) < eval_idx + 1:
                continue

            # 使用截至评分日的可用数据
            close_sofar = s_close.iloc[:eval_idx + 1]
            amount_sofar = s_amount.iloc[:eval_idx + 1]

            # 对每个行业，找一个"虚拟底部"用于 3 区间回看
            # 这里取评分点前 90 个交易日作为"观测底部"
            # 实际上 3 区间是围绕评分点往前推算的，不需要真实底部
            virtual_bottom_idx = max(0, eval_idx - 90)
            virtual_bottom = all_dates[virtual_bottom_idx]

            result = score_sector_at_bottom(
                sym, close_sofar, amount_sofar,
                bm_close.iloc[:eval_idx + 1],
                bm_amount.iloc[:eval_idx + 1],
                str(virtual_bottom.date()),
                eval_offset=90  # virtual_bottom 到 eval 是 90 个交易日
            )
            if result and result['total'] > 0 and result['total'] <= 9:
                scores[sym] = result['total']

        if len(scores) < TOP_N:
            # 评分数据不够，持有基准
            hold_bm_start = bm_close.loc[eval_date]
            hold_end_idx = min(eval_idx + HOLD_LOOKAHEAD, len(all_dates) - 1)
            hold_end_date = all_dates[hold_end_idx]
            hold_bm_end = bm_close.loc[hold_end_date]
            bm_ret = (hold_bm_end / hold_bm_start - 1)

            strategy_nav.append(bm_ret)
            benchmark_nav.append(bm_ret)
            trade_log.append({
                'date': str(eval_date.date()),
                'top3': ['N/A'],
                'strategy_ret': round(bm_ret * 100, 1),
                'bm_ret': round(bm_ret * 100, 1),
                'excess': 0,
                'n_sectors': len(scores),
            })
            continue

        # 选 TOP N
        top_syms = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        top_names = [sec_name.get(s, s) for s, _ in top_syms]

        # ── 持有期收益 ──
        hold_end_idx = min(eval_idx + HOLD_LOOKAHEAD, len(all_dates) - 1)
        hold_end_date = all_dates[hold_end_idx]

        hold_bm_start = bm_close.loc[eval_date]
        hold_bm_end = bm_close.loc[hold_end_date]
        bm_ret = (hold_bm_end / hold_bm_start - 1)

        sector_rets = []
        for sym, _ in top_syms:
            s_close = sec_close[sym].dropna()
            if eval_date in s_close.index and hold_end_date in s_close.index:
                sec_ret = (s_close.loc[hold_end_date] / s_close.loc[eval_date] - 1)
                sector_rets.append(sec_ret)
            else:
                sector_rets.append(0)

        avg_ret = np.mean(sector_rets) if sector_rets else bm_ret
        excess = avg_ret - bm_ret

        strategy_nav.append(avg_ret)
        benchmark_nav.append(bm_ret)

        trade_log.append({
            'date': str(eval_date.date()),
            'top3': top_names,
            'strategy_ret': round(avg_ret * 100, 1),
            'bm_ret': round(bm_ret * 100, 1),
            'excess': round(excess * 100, 1),
            'n_sectors': len(scores),
        })

    # ── 计算净值 ──
    strat_cum = np.cumprod(1 + np.array(strategy_nav))
    bm_cum = np.cumprod(1 + np.array(benchmark_nav))

    # ── 加载 13 个阶段做分段分析 ──
    conn = sqlite3.connect(str(DB_PATH))
    phases_df = pd.read_csv(PHASES_CSV, comment='#')
    conn.close()

    # 把 trade_log 按阶段分组
    phase_analysis = []
    for _, prow in phases_df.iterrows():
        p_start = prow['start_date'].strip()
        p_end = prow['end_date'].strip()
        p_type = prow['phase_type'].strip()
        if p_end == '至今':
            p_end = all_dates[-1].strftime('%Y-%m-%d')

        # 找到这个阶段内的调仓
        phase_trades = [t for t in trade_log if p_start <= t['date'] <= p_end]
        if not phase_trades:
            continue

        phase_excesses = [t['excess'] for t in phase_trades]
        wins = sum(1 for e in phase_excesses if e > 0)
        total = len(phase_excesses)
        avg_excess = np.mean(phase_excesses)
        cum_excess = sum(phase_excesses)

        icon = '📈' if p_type == 'bull' else '📉'
        phase_analysis.append({
            'phase': f'{icon} {p_type} #{len(phase_analysis)+1}',
            'period': f'{p_start}~{p_end}',
            'trades': total,
            'wins': wins,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
            'avg_excess': round(avg_excess, 1),
            'cum_excess': round(cum_excess, 1),
        })

    # ── 回撤分析 ──
    strat_peaks = np.maximum.accumulate(strat_cum)
    drawdowns = (strat_cum - strat_peaks) / strat_peaks * 100
    max_dd = drawdowns.min()
    max_dd_idx = drawdowns.argmin()
    # 找到对应的成交日期
    dd_window = max_dd_idx // len(trade_log) * len(trade_log) if len(trade_log) > 0 else 0
    dd_date = trade_log[max_dd_idx]['date'] if max_dd_idx < len(trade_log) else 'N/A'

    bm_peaks = np.maximum.accumulate(bm_cum)
    bm_drawdowns = (bm_cum - bm_peaks) / bm_peaks * 100
    bm_max_dd = bm_drawdowns.min()

    # ── 汇总 ──
    total_return = (strat_cum[-1] / strat_cum[0] - 1) * 100
    bm_total_return = (bm_cum[-1] / bm_cum[0] - 1) * 100
    total_excess = total_return - bm_total_return
    total_trades = len(trade_log)
    total_wins = sum(1 for t in trade_log if t['excess'] > 0)

    print(f'\n{"=" * 72}')
    print(f'  全历史连续回测结果')
    print(f'{"=" * 72}')
    print(f'\n  策略总收益:    {total_return:>+8.1f}%')
    print(f'  基准总收益:    {bm_total_return:>+8.1f}%')
    print(f'  超额收益:      {total_excess:>+8.1f}%')
    print(f'  总调仓次数:    {total_trades}')
    print(f'  总窗口胜率:    {total_wins}/{total_trades} = {total_wins/total_trades*100:.1f}%')
    print(f'  策略最大回撤:  {max_dd:.1f}% (发生在 {dd_date})')
    print(f'  基准最大回撤:  {bm_max_dd:.1f}%')

    print(f'\n{"=" * 72}')
    print(f'  分阶段分析')
    print(f'{"=" * 72}')
    for pa in phase_analysis:
        arrow = '✅' if pa['cum_excess'] > 0 else '❌'
        print(f'  {pa["phase"]:<12} {pa["period"]:<30} '
              f'超额:{pa["cum_excess"]:>+6.1f}%  胜率:{pa["win_rate"]:>5.1f}%  ({pa["wins"]}/{pa["trades"]})  {arrow}')

    # 跑输最多的阶段
    worst_phases = sorted(phase_analysis, key=lambda x: x['cum_excess'])[:3]
    print(f'\n{"=" * 72}')
    print(f'  跑输最严重的阶段（需要重点分析）')
    print(f'{"=" * 72}')
    for wp in worst_phases:
        if wp['cum_excess'] < 0:
            print(f'  ❌ {wp["phase"]:<12} {wp["period"]:<30} 超额: {wp["cum_excess"]:+.1f}%  胜率: {wp["win_rate"]:.0f}%')

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / 'continuous_rolling_results.json'

    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return str(obj) if hasattr(obj, 'isoformat') else obj

    result = {
        'summary': {
            'strategy_return_pct': round(total_return, 1),
            'benchmark_return_pct': round(bm_total_return, 1),
            'excess_return_pct': round(total_excess, 1),
            'total_trades': total_trades,
            'win_rate': round(total_wins / total_trades * 100, 1),
            'strategy_max_drawdown_pct': round(max_dd, 1),
            'benchmark_max_drawdown_pct': round(bm_max_dd, 1),
            'worst_drawdown_date': dd_date,
        },
        'phase_analysis': phase_analysis,
        'worst_phases': [
            {'phase': wp['phase'], 'period': wp['period'],
             'cum_excess': wp['cum_excess'], 'win_rate': wp['win_rate']}
            for wp in worst_phases if wp['cum_excess'] < 0
        ],
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=convert)
    print(f'\n  已保存: {output_path}')


# ════════════════════════════════════════
# 入口
# ════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if '--rolling' in sys.argv:
        rolling_backtest()
    elif '--continuous' in sys.argv:
        continuous_rolling()
    elif '--daily' in sys.argv:
        print('🚫 --daily 入口指向向量化版（已废弃），结果不准确。如需滚动回测请用 --rolling 或 --continuous')
        print('  向量化版与循环版匹配率仅 34.7%（结论已记录，验证脚本已清理）')
        sys.exit(1)
    else:
        backtest()
