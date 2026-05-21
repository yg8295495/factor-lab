"""
向量化 vs 循环版评分对比测试

在同一日期、同一行业上同时运行两套评分方法，
逐窗口比较 W1/W2/W3 信号是否一致。
"""
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

# 确保能导入同目录下的模块
sys.path.insert(0, str(Path(__file__).parent))
from sector_behavior_score import (
    load_data, calc_sector_rolling_score,
    calc_sector_score_vectorized, precompute_sector_metrics
)


def test_single_sector(sym, close_series, amount_series, bm_close, bm_amount, 
                       metrics, eval_idx, eval_date, sec_name):
    """对单个行业、单个评分日，对比两种方法的结果"""
    
    # ── 方法 A: 循环版 (calc_sector_rolling_score) ──
    result_loop = calc_sector_rolling_score(
        close_series, amount_series, bm_close, bm_amount
    )
    
    # ── 方法 B: 向量化版 (calc_sector_score_vectorized) ──
    score_vec = calc_sector_score_vectorized(sym, metrics, eval_idx)
    
    # ── 对齐对比 ──
    name = sec_name.get(sym, sym)
    
    if result_loop is None:
        return {
            'sym': sym, 'name': name, 'date': str(eval_date.date()),
            'loop': None, 'vec': int(score_vec),
            'match': False, 'reason': 'loop returned None (not enough data)'
        }
    
    loop_total = result_loop['total']
    vec_total = int(score_vec)
    
    # 逐窗口对比
    windows = ['W1_放量震荡', 'W2_缩量洗盘', 'W3_初升试探']
    details = {}
    all_match = True
    mismatches = []
    
    for w in windows:
        lv = result_loop.get(w, 0)
        
        # 从向量化版反推窗口得分比较困难（它不返回细项）
        # 但我们至少能比总分
        details[w] = {'loop': lv}
    
    # 反推向量化版各窗口得分：用约束总分的组合
    # 实际上向量化版的总分算法与循环版不同，
    # 我们只从总分的分布看差异
    total_match = (loop_total == vec_total)
    
    return {
        'sym': sym,
        'name': name,
        'date': str(eval_date.date()),
        'loop_total': loop_total,
        'vec_total': vec_total,
        'total_match': total_match,
        'details': details,
    }


def main():
    print('=' * 72)
    print('  TEST: 循环版评分 vs 向量化版评分')
    print('=' * 72)
    
    # ── 加载数据 ──
    print('\n加载数据...')
    bm, sec_close, sec_amount, sec_name = load_data()
    bm_close = bm['close']
    bm_amount = bm['amount']
    all_dates = bm_close.index
    sym_list = list(sec_close.columns)
    print(f'  全指: {len(all_dates)}天, 行业: {len(sec_close.columns)}个')
    print(f'  日期范围: {all_dates[0].date()} ~ {all_dates[-1].date()}')
    
    # ── 预计算向量化指标 ──
    print('\n预计算向量化指标...')
    metrics = precompute_sector_metrics(sec_close, sec_amount, bm_close)
    print('  完成')
    
    # ── 选 3 个评分日期 ──
    # 分散在全周期内
    test_dates_idx = [
        len(all_dates) // 4,      # 约 1/4 处
        len(all_dates) // 2,      # 约 1/2 处
        len(all_dates) - 50,      # 近期（留 50 天做持有期）
    ]
    test_eval_indices = [
        max(120, idx - 90)  # 确保有 120 天历史
        for idx in test_dates_idx
    ]
    
    # ── 逐日期逐行业对比 ──
    all_results = []
    
    for eval_idx in test_eval_indices:
        if eval_idx >= len(all_dates) - 20:
            continue
        eval_date = all_dates[eval_idx]
        print(f'\n{"─" * 72}')
        print(f'评分日: {eval_date.date()} (索引 {eval_idx})')
        print(f'{"─" * 72}')
        
        date_results = []
        
        for sym in sym_list:
            if sym not in sec_close.columns:
                continue
            
            close_series = sec_close[sym].iloc[:eval_idx + 1].dropna()
            amount_series = sec_amount[sym].iloc[:eval_idx + 1].dropna()
            
            if len(close_series) < 100 or len(amount_series) < 100:
                continue
            
            result = test_single_sector(
                sym, close_series, amount_series,
                bm_close.iloc[:eval_idx + 1],
                bm_amount.iloc[:eval_idx + 1],
                metrics, eval_idx, eval_date, sec_name
            )
            date_results.append(result)
            all_results.append(result)
        
        # 统计这个日期的匹配情况
        n_total = len(date_results)
        n_match = sum(1 for r in date_results if r.get('total_match'))
        n_loop_none = sum(1 for r in date_results if r.get('loop_total') is None)
        
        # TOP3 排名对比
        loop_scores = [(r['sym'], r['loop_total']) for r in date_results 
                       if r.get('loop_total') is not None]
        vec_scores = [(r['sym'], r['vec_total']) for r in date_results]
        
        loop_ranked = sorted(loop_scores, key=lambda x: x[1], reverse=True)
        vec_ranked = sorted(vec_scores, key=lambda x: x[1], reverse=True)
        
        loop_top3 = set(s for s, _ in loop_ranked[:3])
        vec_top3 = set(s for s, _ in vec_ranked[:3])
        top3_overlap = len(loop_top3 & vec_top3)
        
        print(f'  有效行业: {n_total}, 总分匹配: {n_match}/{n_total-n_loop_none}')
        print(f'  循环版无法评分: {n_loop_none}')
        print(f'  TOP3 重叠: {top3_overlap}/3')
        
        if n_match < n_total - n_loop_none:
            print(f'\n  ⚠️  不匹配详情:')
            for r in date_results:
                if r.get('loop_total') is not None and not r['total_match']:
                    print(f'    {r["name"]:<10} 循环={r["loop_total"]}  向量={r["vec_total"]}')
    
    # ── 全局汇总 ──
    print(f'\n{"=" * 72}')
    print(f'  全局汇总')
    print(f'{"=" * 72}')
    
    valid_results = [r for r in all_results if r.get('loop_total') is not None]
    total = len(valid_results)
    matched = sum(1 for r in valid_results if r['total_match'])
    
    print(f'  总对比次数: {total}')
    print(f'  总分匹配:   {matched}/{total} = {matched/total*100:.1f}%')
    print(f'  总分不匹配: {total - matched}/{total} = {(total-matched)/total*100:.1f}%')
    
    if matched < total:
        print(f'\n  差异统计:')
        diffs = [(r['loop_total'] - r['vec_total'], r) for r in valid_results if not r['total_match']]
        avg_diff = np.mean([d[0] for d in diffs])
        max_diff = max([abs(d[0]) for d in diffs])
        print(f'    平均差值 (循环-向量): {avg_diff:+.2f}')
        print(f'    最大绝对差值: {max_diff}')
        
        # 展示最极端的差异
        diffs_sorted = sorted(diffs, key=lambda x: abs(x[0]), reverse=True)
        print(f'\n  差异最大的 10 条:')
        for diff, r in diffs_sorted[:10]:
            print(f'    {r["name"]:<10} {r["date"]}  循环={r["loop_total"]}  向量={r["vec_total"]}  差={diff:+d}')
    
    # ── 保存结果 ──
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / 'vector_vs_loop_test.json'
    
    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return str(obj) if hasattr(obj, 'isoformat') else obj
    
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_comparisons': total,
                'matched': matched,
                'match_rate': round(matched/total*100, 1) if total > 0 else 0,
            },
            'results': all_results,
        }, f, ensure_ascii=False, indent=2, default=convert)
    print(f'\n  已保存: {out_path}')


if __name__ == '__main__':
    main()
