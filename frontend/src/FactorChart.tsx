import React, { useState, useEffect, useMemo, useRef } from 'react';
import EChartsReact from 'echarts-for-react';

import 'echarts/charts';
import 'echarts/components';
import 'echarts/renderers';

const API_BASE = 'http://127.0.0.1:8000';

interface Asset {
  symbol: string;
  name: string;
  asset_type: string;
}

const PERCENTILE_METRICS = [
  { key: 'pe_pct', name: 'PE分位', color: '#165DFF', desc: '低=便宜' },
  { key: 'ey_pct', name: '盈利率分位', color: '#F53F3F', desc: '高=便宜' },
  { key: 'erp_pct', name: '股债利差分位', color: '#00B42A', desc: '高=便宜' },
];

function calcSMA(data: (number | null)[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    let sum = 0, count = 0;
    for (let j = i - period + 1; j <= i; j++) {
      if (data[j] != null) { sum += data[j]!; count++; }
    }
    result.push(count > 0 ? sum / count : null);
  }
  return result;
}

function calcMACD(data: number[]) {
  const ema = (d: number[], p: number) => {
    const k = 2 / (p + 1); const r = [d[0]];
    for (let i = 1; i < d.length; i++) r.push(d[i] * k + r[i - 1] * (1 - k));
    return r;
  };
  const ema12 = ema(data, 12); const ema26 = ema(data, 26);
  const dif = ema12.map((v, i) => v - ema26[i]);
  const dea = ema(dif, 9);
  const macd = dif.map((v, i) => 2 * (v - dea[i]));
  return { dif, dea, macd };
}

const FactorChart: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState('');
  const [selectedMetric, setSelectedMetric] = useState('erp_pct');
  const [windowSize, setWindowSize] = useState<'5y' | '10y' | 'all'>('5y');
  // 视图模式: 'valuation' = 百分位, 'structure' = 市场结构
  const [viewMode, setViewMode] = useState<'valuation' | 'structure'>('valuation');
  const [subChart, setSubChart] = useState<'macd' | 'volume'>('volume');
  const [timeRange, setTimeRange] = useState(756);
  const [rawData, setRawData] = useState<any[]>([]);
  const [percentileData, setPercentileData] = useState<any[]>([]);
  const [structureData, setStructureData] = useState<any[]>([]);
  const [benchmarkData, setBenchmarkData] = useState<any[]>([]);
  const [benchmarkSymbol, setBenchmarkSymbol] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const chartRef = useRef<any>(null);

  // 加载资产列表，只保留 index.* 和 sector.*
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/assets`).then(r => r.json()),
      fetch(`${API_BASE}/api/benchmark`).then(r => r.json()),
    ]).then(([list, bm]: [Asset[], any]) => {
      const filtered = list.filter(a =>
        a.symbol.startsWith('index.') || a.symbol.startsWith('sector.')
      );
      setAssets(filtered);
      if (filtered.length > 0) {
        // 默认选中当前基准，找不到则选第一个
        const def = filtered.find(a => a.symbol === bm.symbol) || filtered[0];
        setSelectedAsset(def.symbol);
      }
      // 记住基准symbol用于后续数据加载
      setBenchmarkSymbol(bm.symbol);
      setLoading(false);
    })
    .catch(e => { setError(`无法连接后端: ${e.message}`); setLoading(false); });
  }, []);

  // 加载K线 + 百分位或结构数据
  useEffect(() => {
    if (!selectedAsset) return;
    setLoading(true); setError('');
    const fields = 'trade_date,open,high,low,close,volume,amount';
    const promises: Promise<any>[] = [
      fetch(`${API_BASE}/api/data/${selectedAsset}?fields=${fields}&limit=7000`).then(r => r.json()),
    ];
    if (viewMode === 'valuation') {
      promises.push(fetch(`${API_BASE}/api/percentiles/${selectedAsset}?window=${windowSize}`).then(r => r.json()));
    } else {
      promises.push(fetch(`${API_BASE}/api/market-structure`).then(r => r.json()));
    }
    Promise.all(promises).then(([price, extra]) => {
      setRawData((price || []).reverse());
      if (viewMode === 'valuation') {
        setPercentileData((extra || []).reverse());
        setStructureData([]);
      } else {
        const sd = (extra?.daily || []).reverse();
        setStructureData(sd);
        setPercentileData([]);
      }
      setLoading(false);
    }).catch(e => { setError(`加载数据失败: ${e.message}`); setLoading(false); });
  }, [selectedAsset, windowSize, viewMode]);

  // 加载基准数据（成交额占比计算依赖基准）
  useEffect(() => {
    if (!benchmarkSymbol) return;
    fetch(`${API_BASE}/api/data/${benchmarkSymbol}?fields=trade_date,close,amount&limit=5000`)
      .then(r => r.json())
      .then(data => setBenchmarkData((data || []).reverse()))
      .catch(() => {});
  }, [selectedAsset, benchmarkSymbol]);

  const displayData = useMemo(() => {
    if (rawData.length === 0) return [];
    return rawData.slice(-timeRange);
  }, [rawData, timeRange]);

  const dates = displayData.map((d: any) => d.trade_date);
  const close = displayData.map((d: any) => d.close);

  const macd = useMemo(() => {
    if (close.length < 35) return { dif: [], dea: [], macd: [] };
    return calcMACD(close);
  }, [close]);

  // 百分位数据对齐
  const percentileMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of percentileData) {
      const v = d[selectedMetric];
      if (v != null) map.set(d.trade_date, v);
    }
    return map;
  }, [percentileData, selectedMetric]);

  const alignedPercentile = useMemo(() => {
    return dates.map(d => {
      const v = percentileMap.get(d);
      return v != null ? v * 100 : null;  // 转成0-100
    });
  }, [dates, percentileMap]);

  const metricDef = PERCENTILE_METRICS.find(m => m.key === selectedMetric);
  const metricName = metricDef?.name || selectedMetric;
  const metricColor = metricDef?.color || '#165DFF';

  // 结构数据对齐
  const structureMap = useMemo(() => {
    const map = new Map<string, any>();
    for (const d of structureData) {
      map.set(d.date, d);
    }
    return map;
  }, [structureData]);

  const alignedProbs = useMemo(() => {
    const bottom: (number | null)[] = [];
    const bull: (number | null)[] = [];
    const top: (number | null)[] = [];
    const bear: (number | null)[] = [];
    for (const d of dates) {
      const r = structureMap.get(d);
      bottom.push(r?.bottom_score ?? null);
      bull.push(r?.bull_score ?? null);
      top.push(r?.top_score ?? null);
      bear.push(r?.bear_score ?? null);
    }
    return { bottom, bull, top, bear, dates };
  }, [dates, structureMap]);

  const alignedState = useMemo(() => {
    return dates.map(d => {
      const r = structureMap.get(d);
      return r?.state ?? null;
    });
  }, [dates, structureMap]);

  const STATE_COLORS: Record<string, string> = {
    'PRIMARY_UP': '#F53F3F',   // 主升=红
    'EARLY_UP': '#FF7D00',     // 早升=橙
    'LATE_UP': '#722ED1',      // 后期上涨=紫
    'TOPPING': '#F77234',      // 筑顶=橙红
    'BASE': '#165DFF',         // 筑底=蓝
    'DOWN': '#00B42A',         // 下跌=绿
  };

  const PROB_CONFIG = [
    { key: 'bull', name: 'BullScore', color: '#F53F3F', bg: 'rgba(245,63,63,0.15)' },    // 上涨=红
    { key: 'bear', name: 'BearScore', color: '#00B42A', bg: 'rgba(0,180,42,0.15)' },     // 下跌=绿
    { key: 'bottom', name: 'BottomScore', color: '#165DFF', bg: 'rgba(22,93,255,0.15)' }, // 底部=蓝
    { key: 'top', name: 'TopScore', color: '#F77234', bg: 'rgba(247,114,52,0.15)' },      // 顶=橙
  ];

  // 右轴数据
  const rightAxisData = useMemo(() => {
    if (viewMode === 'valuation') {
      return {
        name: metricName,
        data: alignedPercentile,
        color: metricColor,
        refLines: [
          { name: '20%', value: 20, color: '#888' },
          { name: '80%', value: 80, color: '#888' },
        ],
        unit: '%',
      };
    }
    // 结构模式：不画单一右轴，用叠加面积图代替
    return null;
  }, [viewMode, alignedPercentile, metricName, metricColor]);

  // 成交额占比（用于 volume 副图）
  const volRatioHistory = useMemo(() => {
    if (displayData.length === 0 || subChart !== 'volume' || !displayData[0]?.amount || benchmarkData.length === 0) return [];
    const vol = displayData.map((d: any) => d.amount ?? 0);
    const bmMap = new Map(benchmarkData.map((d: any) => [d.trade_date, d.amount ?? d.close]));
    return dates.map((d, i) => {
      const bm = bmMap.get(d);
      return (bm && bm > 0 && vol[i]) ? (vol[i] / bm) * 100 : null;
    });
  }, [displayData, benchmarkData, dates, subChart]);

  const option = useMemo(() => {
    if (displayData.length === 0) return {};
    const isKline = displayData[0]?.open != null;
    const mainSeries: any[] = [];

    // ── 主图：K线 ──
    if (isKline) {
      mainSeries.push({
        name: 'K线', type: 'candlestick', yAxisIndex: 0,
        data: displayData.map((d: any) => [d.open, d.close, d.low, d.high]),
        itemStyle: { color: '#F53F3F', color0: '#00B42A', borderColor: '#F53F3F', borderColor0: '#00B42A' },
      });
    } else {
      mainSeries.push({
        name: '收盘', type: 'line', yAxisIndex: 0, data: displayData.map((d: any) => d.close),
        lineStyle: { color: '#165DFF', width: 2 }, itemStyle: { color: '#165DFF' },
      });
    }

    // ── 主图右轴：估值模式 → 百分位线 ──
    if (viewMode === 'valuation' && rightAxisData && rightAxisData.data.some(v => v != null)) {
      mainSeries.push({
        name: rightAxisData.name, type: 'line', yAxisIndex: 1,
        data: rightAxisData.data,
        lineStyle: { color: rightAxisData.color, width: 2 },
        itemStyle: { color: rightAxisData.color }, symbol: 'none',
      });
      for (const rl of rightAxisData.refLines) {
        mainSeries.push({
          name: rl.name, type: 'line', yAxisIndex: 1,
          data: dates.map(() => rl.value),
          lineStyle: { color: rl.color, width: 1, type: 'dashed' },
          symbol: 'none',
        });
      }
    }

    // ── 结构模式：K线上色 + 四个概率叠加副图 ──
    const subSeries: any[] = [];
    let subYAxis: any = {};

    if (viewMode === 'structure') {
      // K线上色
      if (alignedState.some(s => s != null) && mainSeries[0]) {
        const klineColors = displayData.map((_: any, i: number) => {
          const st = alignedState[i];
          return STATE_COLORS[st] || null;
        });
        mainSeries[0].itemStyle = {
          color: (p: any) => klineColors[p.dataIndex] || '#F53F3F',
          color0: '#00B42A',
          borderColor: (p: any) => klineColors[p.dataIndex] || '#F53F3F',
          borderColor0: '#00B42A',
        };
      }

      // 四概率叠加副图（使用副图区域）
      const probData = alignedProbs;
      for (const cfg of PROB_CONFIG) {
        const data = probData[cfg.key as keyof typeof probData] as (number | null)[];
        subSeries.push({
          name: cfg.name, type: 'line', xAxisIndex: 1, yAxisIndex: 2,
          data: data,
          lineStyle: { color: cfg.color, width: 2 },
          itemStyle: { color: cfg.color }, symbol: 'none',
          areaStyle: { color: cfg.bg },
        });
      }
      subYAxis = { type: 'value', gridIndex: 1, splitNumber: 3, min: 0, max: 100, axisLabel: { fontSize: 10, formatter: (v: number) => v + '' } };
    } else if (subChart === 'volume' && displayData[0]?.amount != null) {
      const vol = displayData.map((d: any) => d.amount ?? 0);
      const bmMap = new Map((benchmarkData || []).map((d: any) => [d.trade_date, d.amount ?? d.close]));
      const volRatio = dates.map((d, i) => {
        const bm = bmMap.get(d);
        return (bm && bm > 0 && vol[i]) ? (vol[i] / bm) * 100 : null;
      });
      subSeries.push({ name: '成交额占比%', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: volRatio, lineStyle: { color: '#722ED1', width: 2 }, itemStyle: { color: '#722ED1' }, symbol: 'none', areaStyle: { color: 'rgba(114,46,209,0.1)' } });
      const ma5 = calcSMA(volRatio.map(v => v ?? 0), 5);
      if (ma5.some(v => v != null)) subSeries.push({ name: 'MA5', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: ma5, lineStyle: { color: '#b37feb', width: 1 }, symbol: 'none' });
      subYAxis = { type: 'value', gridIndex: 1, splitNumber: 3, axisLabel: { fontSize: 10, formatter: (v: number) => v.toFixed(2) } };
    } else if (subChart === 'macd' && macd.dif.length > 0) {
      subSeries.push(
        { name: 'DIF', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: macd.dif, lineStyle: { color: '#fff', width: 1.5 }, symbol: 'none' },
        { name: 'DEA', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: macd.dea, lineStyle: { color: '#ff0', width: 1.5 }, symbol: 'none' },
        { name: 'MACD', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: macd.macd, itemStyle: { color: (p: any) => (p.value >= 0 ? '#F53F3F' : '#00B42A') } },
      );
      subYAxis = { type: 'value', gridIndex: 1, splitNumber: 3, axisLabel: { fontSize: 10, formatter: (v: number) => v.toFixed(2) } };
    }

    return {
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          const date = params[0]?.axisValue || '';
          const idx = params[0]?.dataIndex;
          let html = `<b>${date}</b><br/>`;
          const kline = params.find((p: any) => Array.isArray(p.value));
          if (kline) html += `${kline.marker} 收盘: <b>${(+kline.value[1]).toFixed(2)}</b><br/>`;
          // 右轴信息
          // 估值模式：显示百分位线
          if (viewMode === 'valuation' && rightAxisData) {
            const rightParam = params.find((p: any) => !Array.isArray(p.value) && p.seriesName === rightAxisData.name);
            if (rightParam && rightParam.value != null) {
              html += `${rightParam.marker} ${rightAxisData.name}: <b>${(+rightParam.value).toFixed(0)}%</b>`;
              if (metricDef?.desc) html += ` &nbsp; <span style="color:#888">(${metricDef.desc})</span>`;
              html += '<br/>';
            }
          }
          // 结构模式：显示四概率 + 状态标签
          if (viewMode === 'structure' && idx != null) {
            const prob = alignedProbs;
            const st = alignedState[idx];
            if (st) {
              const color = STATE_COLORS[st] || '#888';
              html += `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:4px"></span>`;
              html += `状态: <b style="color:${color}">${st}</b><br/>`;
            }
            html += `<div style="margin-top:2px;padding-top:4px;border-top:1px solid #555">`;
            // Bull → Bear → Bottom → Top（红绿蓝橙）
            const order = ['bull', 'bear', 'bottom', 'top'];
            for (const key of order) {
              const cfg = PROB_CONFIG.find(c => c.key === key);
              const vals = prob[key as keyof typeof prob] as (number | null)[];
              const v = idx != null ? vals[idx] : null;
              if (v != null && cfg) {
                html += `<span style="display:inline-block;width:10px;height:4px;border-radius:2px;background:${cfg.color};margin-right:4px"></span>`;
                html += `${cfg.name}: <b>${v.toFixed(0)}</b> &nbsp; `;
              }
            }
            html += `</div>`;
          }
          if (subChart === 'volume') {
            const volParam = params.find((p: any) => p.seriesName === '成交额占比%');
            if (volParam && volParam.value != null) {
              html += `<div style="margin-top:2px;padding-top:4px;border-top:1px solid #555">`;
              html += `📊 成交额占比: <b>${(+volParam.value).toFixed(2)}%</b>`;
              html += '</div>';
            }
          } else if (subChart === 'macd') {
            const dif = params.find((p: any) => p.seriesName === 'DIF');
            const dea = params.find((p: any) => p.seriesName === 'DEA');
            const macdVal = params.find((p: any) => p.seriesName === 'MACD');
            if (dif || dea || macdVal) {
              html += `<div style="margin-top:2px;padding-top:4px;border-top:1px solid #555">`;
              if (dif) html += `DIF: ${(+dif.value).toFixed(2)} &nbsp; `;
              if (dea) html += `DEA: ${(+dea.value).toFixed(2)} &nbsp; `;
              if (macdVal) html += `MACD: ${(+macdVal.value).toFixed(2)}`;
              html += '</div>';
            }
          }
          return html;
        },
      },
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      legend: { 
        data: viewMode === 'structure'
          ? ['K线', ...PROB_CONFIG.map(c => c.name)]
          : ['K线', rightAxisData?.name, ...(rightAxisData?.refLines?.map(r => r.name) || []), '成交额占比%', 'MA5', 'DIF', 'DEA', 'MACD'].filter(Boolean), 
        top: 0 
      },
      grid: [
        { left: 50, right: 60, top: 36, height: '52%' },
        { left: 50, right: 60, top: '72%', height: '16%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { rotate: 45, fontSize: 10 } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, splitNumber: 4, axisLabel: { formatter: (v: number) => v.toFixed(2) } },
        { type: 'value', gridIndex: 0, scale: true, splitNumber: 4, splitLine: { show: false }, axisLabel: { fontSize: 10, formatter: (v: number) => v.toFixed(0) } },
        subYAxis,
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 2, height: 14 },
      ],
      series: [...mainSeries, ...subSeries],
    };
  }, [displayData, rightAxisData, macd, subChart, viewMode, alignedState, alignedProbs, volRatioHistory, STATE_COLORS, metricDef]);

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>加载中...</div>;
  if (error) return <div style={{ padding: 40, textAlign: 'center', color: '#F53F3F' }}>{error}</div>;
  if (Object.keys(option).length === 0) return <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>暂无数据，请检查资产选择</div>;

  return (
    <div style={{ padding: 16, fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 600 }}>因子研究图表</h2>

      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        {/* 资产选择（仅index/sector） */}
        <select value={selectedAsset} onChange={e => setSelectedAsset(e.target.value)}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13, minWidth: 160 }}>
          {assets.map(a => (
            <option key={a.symbol} value={a.symbol}>{a.name}</option>
          ))}
        </select>

        {/* 视图模式 */}
        <select value={viewMode} onChange={e => setViewMode(e.target.value as any)}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13, fontWeight: 600 }}>
          <option value="valuation">📊 估值百分位</option>
          <option value="structure">🏗️ 市场结构</option>
        </select>

        {/* 百分位指标（仅在估值模式下显示） */}
        {viewMode === 'valuation' && (
          <>
            <select value={selectedMetric} onChange={e => setSelectedMetric(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13, minWidth: 140 }}>
              {PERCENTILE_METRICS.map(m => (
                <option key={m.key} value={m.key}>{m.name}</option>
              ))}
            </select>

            <select value={windowSize} onChange={e => setWindowSize(e.target.value as any)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13 }}>
              <option value="5y">近5年分位</option>
              <option value="10y">近10年分位</option>
              <option value="all">全历史分位</option>
            </select>
          </>
        )}

        {/* 副图切换（仅在估值模式下显示，结构中副图区域用于四概率） */}
        {viewMode === 'valuation' && (
          <select value={subChart} onChange={e => setSubChart(e.target.value as any)}
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13 }}>
            <option value="volume">成交额占比</option>
            <option value="macd">MACD</option>
          </select>
        )}

        {/* 时间范围 */}
        <select value={timeRange} onChange={e => setTimeRange(Number(e.target.value))}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13 }}>
          <option value={252}>1年</option>
          <option value={756}>3年</option>
          <option value={1260}>5年</option>
          <option value={5000}>全部</option>
        </select>
      </div>

      <EChartsReact
        ref={chartRef}
        option={option}
        style={{ height: 650, width: '100%' }}
        notMerge
        lazyUpdate
      />
    </div>
  );
};

export default FactorChart;
