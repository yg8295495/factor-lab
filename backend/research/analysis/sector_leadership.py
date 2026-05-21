"""
中证全指 → 阶段行业领涨分析

读取 market_phases.csv 的阶段划分 → 每个阶段找出行业 TOP 3
"""

import sqlite3
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).resolve().parents[3] / 'data' / 'quant_engine.db'
PHASES_CSV = Path(__file__).resolve().parents[1] / 'labeling' / 'labels' / 'market_phases.csv'
BM_SYMBOL = 'index.000985.SH'
OUTPUT_DIR = Path(__file__).resolve().parent / 'output'


def load_phases():
    """从 CSV 读取阶段定义"""
    df = pd.read_csv(PHASES_CSV, comment='#')
    df = df.dropna(subset=['start_date', 'end_date', 'phase_type'])
    phases = []
    for _, row in df.iterrows():
        end = row['end_date'].strip()
        if end == '至今':
            end = datetime.now().strftime('%Y-%m-%d')
        phases.append({
            'label': f"{row['phase_type']} #{len(phases)+1}",
            'start': row['start_date'].strip(),
            'end': end,
            'type': row['phase_type'].strip(),
            'notes': str(row.get('notes', '')).strip(),
        })
    return phases


def load_benchmark():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql(
        'SELECT trade_date, close FROM market_daily_data WHERE symbol = ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL,), parse_dates=['trade_date'], index_col='trade_date'
    )
    conn.close()
    return df['close']


def load_sector_data(start_date, end_date):
    """加载指定日期范围内所有行业的数据"""
    conn = sqlite3.connect(str(DB_PATH))
    query = '''
        SELECT d.symbol, a.name, d.trade_date, d.close
        FROM market_daily_data d
        JOIN asset_master a ON d.symbol = a.symbol
        WHERE a.asset_type = 'sector'
          AND d.trade_date >= ? AND d.trade_date <= ?
        ORDER BY d.symbol, d.trade_date
    '''
    df = pd.read_sql(query, conn, params=(start_date, end_date), parse_dates=['trade_date'])
    conn.close()
    return df


def split_into_three(start_date, end_date):
    """把一个阶段三等分"""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    total_days = max((end - start).days, 1)
    split1 = start + timedelta(days=total_days // 3)
    split2 = start + timedelta(days=total_days * 2 // 3)
    return [
        ('早期', start.strftime('%Y-%m-%d'), split1.strftime('%Y-%m-%d')),
        ('中期', split1.strftime('%Y-%m-%d'), split2.strftime('%Y-%m-%d')),
        ('末期', split2.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')),
    ]


def classify_sector(name):
    """给行业打类型标签"""
    defensive = ['银行', '公用事业', '交通运输', '煤炭', '石油石化', '钢铁']
    cyclical = ['有色金属', '化工', '钢铁', '建筑材料', '建筑装饰', '机械设备', '汽车', '房地产', '基础化工']
    growth = ['电子', '计算机', '通信', '传媒', '电力设备', '国防军工']
    consumer = ['食品饮料', '医药生物', '家用电器', '纺织服装', '轻工制造', '商贸零售', '社会服务', '美容护理', '农林牧渔']
    
    if name in defensive: return '防御'
    if name in cyclical: return '周期'
    if name in growth: return '成长'
    if name in consumer: return '消费'
    return '其他'


def analyze_phase(phase):
    """分析一个阶段的所有行业表现"""
    start, end = phase['start'], phase['end']
    phase_type = phase['type']
    
    # 基准涨跌幅
    conn = sqlite3.connect(str(DB_PATH))
    bm = pd.read_sql(
        'SELECT close FROM market_daily_data WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date',
        conn, params=(BM_SYMBOL, start, end)
    )
    conn.close()
    
    if bm.empty or len(bm) < 2:
        return None
    
    bm_return = (bm['close'].iloc[-1] / bm['close'].iloc[0] - 1) * 100
    
    # 行业数据
    sectors = load_sector_data(start, end)
    if sectors.empty:
        return None
    
    sector_list = []
    for sym in sectors['symbol'].unique():
        sdf = sectors[sectors['symbol'] == sym].sort_values('trade_date')
        name = sdf['name'].iloc[0]
        first_c = sdf['close'].iloc[0]
        last_c = sdf['close'].iloc[-1]
        
        if first_c == 0 or pd.isna(first_c) or pd.isna(last_c):
            continue
        
        ret = (last_c / first_c - 1) * 100
        excess = ret - bm_return
        category = classify_sector(name)
        
        sector_list.append({
            'name': name, 'return_pct': round(ret, 1),
            'excess_pct': round(excess, 1), 'category': category,
        })
    
    if not sector_list:
        return None
    
    df_ret = pd.DataFrame(sector_list)
    
    # 排序：上涨段看涨幅，下跌段看抗跌（跌幅小）
    df_sorted = df_ret.sort_values('return_pct', ascending=False)
    
    top3 = df_sorted.head(3)[['name', 'return_pct', 'excess_pct', 'category']].to_dict('records')
    bottom3 = df_sorted.tail(3)[['name', 'return_pct', 'excess_pct', 'category']].to_dict('records')
    
    # 子阶段分析
    sub_analysis = []
    sub_phases = split_into_three(start, end)
    for sub_label, sub_start, sub_end in sub_phases:
        sub_sectors = load_sector_data(sub_start, sub_end)
        if sub_sectors.empty:
            continue
        sub_list = []
        for sym in sub_sectors['symbol'].unique():
            sdf = sub_sectors[sub_sectors['symbol'] == sym].sort_values('trade_date')
            name = sdf['name'].iloc[0]
            first_c = sdf['close'].iloc[0]
            last_c = sdf['close'].iloc[-1]
            if first_c == 0 or pd.isna(first_c) or pd.isna(last_c):
                continue
            sub_list.append({'name': name, 'ret': (last_c/first_c - 1)*100})
        
        if sub_list:
            sub_df = pd.DataFrame(sub_list).sort_values('ret', ascending=False)
            sub_analysis.append({
                'stage': sub_label,
                'period': f'{sub_start}~{sub_end}',
                'top3_names': [s['name'] for s in sub_df.head(3).to_dict('records')],
                'top3_returns': [round(s['ret'], 1) for s in sub_df.head(3).to_dict('records')],
            })
    
    # 行业类型分布
    type_dist = df_sorted.head(5)['category'].value_counts().to_dict()
    
    return {
        'phase_name': phase['label'],
        'start': start, 'end': end,
        'type': phase_type,
        'notes': phase['notes'],
        'bm_return_pct': round(bm_return, 1),
        'sectors_count': len(sector_list),
        'top3': top3,
        'bottom3': bottom3,
        'top5_types': type_dist,
        'sub_stages': sub_analysis,
    }


def main():
    print('=' * 72)
    print('  中证全指阶段 × 行业领涨分析')
    print('=' * 72)
    
    phases = load_phases()
    print(f'\n📋 共 {len(phases)} 个阶段\n')
    
    all_results = []
    
    for p in phases:
        icon = '📈' if p['type'] == 'bull' else '📉'
        print(f'\n{"─" * 72}')
        print(f'  {icon} {p["label"]}  {p["start"]} → {p["end"]}')
        print(f'  📝 {p["notes"][:60]}')
        
        result = analyze_phase(p)
        if not result:
            print('  ⚠️ 数据不足')
            continue
        
        print(f'  基准涨跌: {result["bm_return_pct"]:+.1f}% | 行业: {result["sectors_count"]}个')
        
        # TOP 3
        print(f'  🏆 TOP3:')
        for i, s in enumerate(result['top3'], 1):
            arrow = '📗' if s['return_pct'] > 0 else '📕'
            print(f'     {i}. {s["name"]:<8} {arrow} {s["return_pct"]:>+7.1f}%  (超额 {s["excess_pct"]:>+6.1f}%) [{s["category"]}]')
        
        # BOTTOM 3
        print(f'  💩 BOTTOM3:')
        for i, s in enumerate(result['bottom3']):
            print(f'     {i}. {s["name"]:<8} 📉 {s["return_pct"]:>+7.1f}%  (超额 {s["excess_pct"]:>+6.1f}%) [{s["category"]}]')
        
        # 子阶段
        if result['sub_stages']:
            stages_str = ' | '.join(
                f"{s['stage']}: {' '.join(s['top3_names'][:2])}" 
                for s in result['sub_stages']
            )
            print(f'  🔬 轮动: {stages_str}')
        
        all_results.append(result)
    
    # 保存 JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / 'phase_analysis.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f'\n✅ 结果已保存: {output_path}')
    
    # ── 汇总表格 ──
    print(f'\n\n{"=" * 72}')
    print('  📊 汇总：每个阶段的领涨行业')
    print(f'{"=" * 72}')
    print(f'{"阶段":<14} {"类型":<5} {"基准%":>7} {"TOP1":<10} {"TOP2":<10} {"TOP3":<10}')
    print('-' * 72)
    for r in all_results:
        t = r['top3']
        top1 = f"{t[0]['name']}({t[0]['return_pct']:+.0f}%)" if t else '-'
        top2 = f"{t[1]['name']}({t[1]['return_pct']:+.0f}%)" if len(t) > 1 else '-'
        top3 = f"{t[2]['name']}({t[2]['return_pct']:+.0f}%)" if len(t) > 2 else '-'
        icon = '📈' if r['type'] == 'bull' else '📉'
        print(f'{r["phase_name"]:<14} {icon:<5} {r["bm_return_pct"]:>+7.1f} {top1:<10} {top2:<10} {top3:<10}')


if __name__ == '__main__':
    main()
