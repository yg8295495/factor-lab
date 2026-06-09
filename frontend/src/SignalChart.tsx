import React, { useState, useEffect, useMemo } from 'react';
import EChartsReact from 'echarts-for-react';
import 'echarts/charts';
import 'echarts/components';
import 'echarts/renderers';

const API_BASE = 'http://127.0.0.1:8000';

interface KlineRow { trade_date: string; open: number; close: number; low: number; high: number; }
interface PeriodInfo {
  state: string; start: string; end: string; trading_days: number;
  change_pct: number | null; start_close: number | null; end_close: number | null;
  top_warning?: boolean; top_score_max?: number; top_warn_date?: string;
}
interface DailyState {
  date: string; state: string; close: number | null;
  top_warning: boolean; top_score: number; top_reasons: string[];
  bottom_score: number;
}
interface StateData { regime_periods: PeriodInfo[]; daily_states: DailyState[]; params: any; }

function calcMA(data: number[], period: number): (number | null)[] {
  const r: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { r.push(null); continue; }
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += data[j];
    r.push(s / period);
  }
  return r;
}

const StateChart: React.FC = () => {
  const [kline, setKline] = useState<KlineRow[]>([]);
  const [stateData, setStateData] = useState<StateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [bmSymbol, setBmSymbol] = useState('');
  const [bmName, setBmName] = useState('');

  useEffect(() => {
    // 先获取当前基准
    fetch(`${API_BASE}/api/benchmark`)
      .then(r => r.json())
      .then(bm => {
        setBmSymbol(bm.symbol);
        setBmName(bm.name);
        // 然后加载数据
        return Promise.all([
          fetch(`${API_BASE}/api/data/${bm.symbol}?fields=trade_date,open,high,low,close&limit=6600`).then(r => r.json()),
          fetch(`${API_BASE}/api/market-state`).then(r => r.json()),
        ]);
      })
      .then(([kdata, sdata]: [KlineRow[], StateData]) => {
        setKline((kdata || []).reverse());
        setStateData(sdata && !(sdata as any).error ? sdata : null);
        setLoading(false);
      })
      .catch(e => {
        setError(`加载失败: ${e.message}`);
        setLoading(false);
      });
  }, []);

  const dates = kline.map(d => d.trade_date);
  const close = kline.map(d => d.close);
  const ma30 = useMemo(() => calcMA(close, 30), [close]);
  const ma60 = useMemo(() => calcMA(close, 60), [close]);
  const ma120 = useMemo(() => calcMA(close, 120), [close]);

  const option = useMemo(() => {
    if (kline.length === 0) return {};

    const periods = stateData?.regime_periods || [];
    const merged: PeriodInfo[] = [];
    for (const p of periods) {
      const last = merged[merged.length - 1];
      if (last && last.state === p.state && last.state !== 'BOTTOM') {
        last.end = p.end;
        last.trading_days += p.trading_days;
        if (p.change_pct !== null) last.change_pct = p.change_pct;
        last.end_close = p.end_close;
        if (p.top_warning) { last.top_warning = true; last.top_warn_date = p.top_warn_date; }
      } else {
        merged.push({ ...p });
      }
    }

    const markData: any[] = [];
    const topMarks: any[] = [];
    const bottomMarks: any[] = [];
    const topDates = new Set<string>();
    const bottomDates = new Set<string>();

    for (const p of merged) {
      if (p.trading_days < 10) continue;
      if (p.state === 'UP' || p.state === 'DOWN') {
        const color = p.state === 'UP' ? 'rgba(0,180,42,0.25)' : 'rgba(245,63,63,0.25)';
        markData.push([
          { xAxis: p.start, itemStyle: { color } },
          { xAxis: p.end },
        ]);
      }
      if (p.state === 'UP' && p.top_warning && p.top_warn_date && !topDates.has(p.top_warn_date)) {
        const di = dates.indexOf(p.top_warn_date);
        if (di >= 0 && close[di] !== undefined) {
          topMarks.push({ coord: [p.top_warn_date, close[di]] });
          topDates.add(p.top_warn_date);
        }
      }
    }

    for (const d of (stateData?.daily_states || [])) {
      if (d.state === 'BOTTOM' && d.close !== null) {
        const key = d.date + '_bottom';
        if (!bottomDates.has(key)) {
          const di = dates.indexOf(d.date);
          if (di >= 0 && close[di] !== undefined) {
            bottomMarks.push({ coord: [d.date, close[di]] });
            bottomDates.add(key);
          }
        }
      }
    }

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          const date = params[0]?.axisValue || '';
          const s = stateData?.daily_states?.find(d => d.date === date);
          let html = `<b>${date}</b><br/>`;
          const kp = params.find((p: any) => p.seriesName === 'K线');
          if (kp) html += `收盘: <b>${(+kp.value[1]).toFixed(2)}</b><br/>`;
          if (s) {
            html += `<div style="margin-top:4px;padding-top:4px;border-top:1px solid #555">`;
            html += `状态: <b>${s.state}</b>`;
            if (s.top_warning && s.top_score > 0) {
              html += ` | ⚠顶: ${s.top_score}分 (${(s.top_reasons || []).join(', ')})`;
            }
            html += `</div>`;
          }
          return html;
        },
      },
      legend: { data: ['K线', 'MA30', 'MA60', 'MA120'], top: 0 },
      grid: [{ left: 50, right: 30, top: 36, bottom: 40 }],
      xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
      yAxis: { type: 'value', scale: true, splitNumber: 4 },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, bottom: 2, height: 14 },
      ],
      series: [
        {
          name: '背景', type: 'line',
          data: new Array(dates.length).fill(null),
          markArea: { silent: true, data: markData },
          lineStyle: { width: 0 }, symbol: 'none',
          z: 0, tooltip: { show: false },
        },
        {
          name: 'K线', type: 'candlestick',
          data: kline.map(d => [d.open, d.close, d.low, d.high]),
          itemStyle: { color: '#F53F3F', color0: '#00B42A', borderColor: '#F53F3F', borderColor0: '#00B42A' },
          z: 10,
          markPoint: {
            silent: false,
            data: [
              ...topMarks.map(pt => ({
                coord: pt.coord, name: '顶预警',
                itemStyle: { color: '#FF7D00' },
                symbol: 'pin', symbolSize: 40,
                label: { formatter: '⚠顶', color: '#fff', fontSize: 11, fontWeight: 'bold' },
              })),
              ...bottomMarks.map(pt => ({
                coord: pt.coord, name: '底部',
                itemStyle: { color: '#722ED1' },
                symbol: 'diamond', symbolSize: 30,
                label: { formatter: '底', color: '#fff', fontSize: 11, fontWeight: 'bold' },
              })),
            ],
          },
        },
        { name: 'MA30', type: 'line', data: ma30, lineStyle: { color: '#FF7D00', width: 1.5 }, symbol: 'none', z: 11 },
        { name: 'MA60', type: 'line', data: ma60, lineStyle: { color: '#165DFF', width: 1.5 }, symbol: 'none', z: 11 },
        { name: 'MA120', type: 'line', data: ma120, lineStyle: { color: '#722ED1', width: 1.5, type: 'dashed' }, symbol: 'none', z: 11 },
      ],
    };
  }, [kline, ma30, ma60, ma120, stateData]);

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>加载中...</div>;
  if (error) return <div style={{ padding: 40, textAlign: 'center', color: '#F53F3F' }}>{error}</div>;

  return (
    <div style={{ padding: 16, fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif' }}>
      <h2 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 600 }}>{bmSymbol} {bmName} — 市场状态</h2>
      <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>
        <span style={{ background: 'rgba(0,180,42,0.25)', padding: '2px 6px', borderRadius: 4, marginRight: 8 }}>🟢 主升</span>
        <span style={{ background: 'rgba(245,63,63,0.25)', padding: '2px 6px', borderRadius: 4, marginRight: 8 }}>🔴 下跌</span>
        <span style={{ color: '#FF7D00', marginRight: 8 }}>🟠 顶预警</span>
        <span style={{ color: '#722ED1', marginRight: 8 }}>🔷 底部</span>
      </div>
      {!stateData && <div style={{ color: '#FF7D00', marginBottom: 8, fontSize: 13 }}>⚠ 市场状态数据未生成，需重跑分析脚本</div>}
      <EChartsReact option={option} style={{ height: 600, width: '100%' }} notMerge lazyUpdate />
    </div>
  );
};

export default StateChart;
