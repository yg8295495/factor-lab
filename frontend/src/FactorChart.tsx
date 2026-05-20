import React, { useState, useEffect, useMemo, useRef } from 'react';
import EChartsReact from 'echarts-for-react';

// 注册 ECharts 组件
import 'echarts/charts';
import 'echarts/components';
import 'echarts/renderers';

const API_BASE = 'http://127.0.0.1:8000';

interface Asset {
  symbol: string;
  name: string;
  asset_type: string;
}
interface FactorDef {
  name: string; name_cn: string; dimension: string; tier: number;
  description: string;
  display: { color: string; chart: string; y_axis: string };
  default_normalization?: string;
}

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

function calcPercentile(v: number, history: number[]): number {
  const below = history.filter(h => h < v).length;
  return Math.round((below / history.length) * 100);
}
function calcZscore(v: number, history: number[]): number {
  const mean = history.reduce((a, b) => a + b, 0) / history.length;
  const std = Math.sqrt(history.reduce((a, b) => a + (b - mean) ** 2, 0) / history.length);
  return std === 0 ? 0 : (v - mean) / std;
}

const FactorChart: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [factors, setFactors] = useState<FactorDef[]>([]);
  const [selectedAsset, setSelectedAsset] = useState('');
  const [selectedFactor, setSelectedFactor] = useState('RS20');
  const [subChart, setSubChart] = useState<'macd' | 'volume'>('volume');
  const [timeRange, setTimeRange] = useState(756);
  const [rawData, setRawData] = useState<any[]>([]);
  const [factorData, setFactorData] = useState<any[]>([]);
  const [benchmarkData, setBenchmarkData] = useState<any[]>([]);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const chartRef = useRef<any>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/assets`).then(r => r.json()),
      fetch(`${API_BASE}/api/factors`).then(r => r.json()),
    ]).then(([a, f]) => {
      setAssets(a); setFactors(f);
      if (a.length > 0) setSelectedAsset(a[0].symbol);
      setLoading(false);
    }).catch(e => { setError(`无法连接后端: ${e.message}`); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!selectedAsset) return;
    setLoading(true); setError('');
    const fields = 'trade_date,open,high,low,close,volume,amount';
    Promise.all([
      fetch(`${API_BASE}/api/data/${selectedAsset}?fields=${fields}&limit=5000`).then(r => r.json()),
      selectedFactor ? fetch(`${API_BASE}/api/factor-data/${selectedAsset}/${selectedFactor}?limit=5000`).then(r => r.json()).then(d => d.data || []) : Promise.resolve([]),
    ]).then(([price, factor]) => {
      setRawData((price || []).reverse());
      setFactorData((factor || []).reverse());
      setLoading(false);
    }).catch(e => { setError(`加载数据失败: ${e.message}`); setLoading(false); });
  }, [selectedAsset, selectedFactor]);

  // 加载基准数据（成交额占比计算依赖基准，始终加载；showBenchmark 只控制是否画线）
  useEffect(() => {
    fetch(`${API_BASE}/api/data/index.000985.SH?fields=trade_date,close,amount&limit=5000`)
      .then(r => r.json())
      .then(data => setBenchmarkData((data || []).reverse()))
      .catch(() => {});
  }, [selectedAsset]);

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

  // 因子值对齐
  const alignedFactorValues = useMemo(() => {
    if (factorData.length === 0) return [];
    const dateMap = new Map(factorData.map((d: any) => [d.trade_date, d.factor_value]));
    return dates.map(d => dateMap.get(d) ?? null);
  }, [factorData, dates]);

  // (无外部状态栏，tooltip 使用 ECharts 原生的轴指针)

  // 成交额占比历史序列（用于联动分位显示）
  const volRatioHistory = useMemo(() => {
    if (displayData.length === 0 || subChart !== 'volume' || !displayData[0]?.amount || benchmarkData.length === 0) return [];
    const vol = displayData.map((d: any) => d.amount ?? 0);
    const bmMap = new Map(benchmarkData.map((d: any) => [d.trade_date, d.amount ?? d.close]));
    return dates.map((d, i) => {
      const bm = bmMap.get(d);
      return (bm && bm > 0 && vol[i]) ? (vol[i] / bm) * 100 : null;
    });
  }, [displayData, benchmarkData, dates, subChart]);

  const volRatioAllValues = volRatioHistory.filter((v): v is number => v != null);
  const volRatioPctArray = volRatioHistory.map(v =>
    v != null && volRatioAllValues.length > 0 ? calcPercentile(v, volRatioAllValues) : null
  );

  const factorDef = factors.find(f => f.name === selectedFactor);
  const factorNameCn = factorDef?.name_cn || selectedFactor;
  const factorColor = factorDef?.display?.color || '#ff6600';
  // 全量百分位/Z-score 数组（给 tooltip 用）
  const factorAllValues = factorData.map((d: any) => d.factor_value).filter((v: any) => v != null);
  const pctArray = alignedFactorValues.map(v => 
    v != null && factorAllValues.length > 0 ? calcPercentile(v, factorAllValues) : null);
  const zArray = alignedFactorValues.map(v => 
    v != null && factorAllValues.length > 0 ? calcZscore(v, factorAllValues) : null);

  const option = useMemo(() => {
    if (displayData.length === 0) return {};
    const isKline = displayData[0]?.open != null;
    const mainSeries: any[] = [];

    // ── 价格比较模式 vs 普通模式 ──
    const isPriceCompare = showBenchmark && benchmarkData.length > 0;

    if (isPriceCompare) {
      // 双K线归一化到100，共用左轴
      const firstClose = displayData.find((d: any) => d.close != null)?.close ?? 1;
      mainSeries.push({
        name: '标的(归一化)', type: 'candlestick', yAxisIndex: 0,
        data: displayData.map((d: any) => [
          (d.open / firstClose) * 100, (d.close / firstClose) * 100,
          (d.low / firstClose) * 100, (d.high / firstClose) * 100,
        ]),
        itemStyle: { color: '#F53F3F', color0: '#00B42A', borderColor: '#F53F3F', borderColor0: '#00B42A' },
      });
      // 基准归一化线
      const bmMap = new Map(benchmarkData.map((d: any) => [d.trade_date, d.close]));
      const bmAligned = dates.map(d => bmMap.get(d) ?? null);
      const firstBm = bmAligned.find(v => v != null) ?? 1;
      const bmNormalized = bmAligned.map(v => v != null ? (v / firstBm) * 100 : null);
      mainSeries.push({
        name: '中证全指', type: 'line', yAxisIndex: 0,
        data: bmNormalized,
        lineStyle: { color: '#FF7D00', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#FF7D00' }, symbol: 'none',
      });
    } else if (isKline) {
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

    // 因子线（右轴）
    if (alignedFactorValues.length > 0) {
      mainSeries.push({
        name: factorNameCn, type: 'line', yAxisIndex: 1,
        data: alignedFactorValues,
        lineStyle: { color: factorColor, width: 2 },
        itemStyle: { color: factorColor }, symbol: 'none',
      });
    }

    const subSeries: any[] = [];
    let subYAxis: any = {};
    if (subChart === 'volume' && displayData[0]?.amount != null) {
      const vol = displayData.map((d: any) => d.amount ?? 0);
      // 成交额相对全市场占比（%）
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
          // ── 主图信息 ──
          let html = `<b>${date}</b><br/>`;
          // K线: 只取 close
          const kline = params.find((p: any) => Array.isArray(p.value));
          if (kline) html += `${kline.marker} 收盘: <b>${(+kline.value[1]).toFixed(2)}</b><br/>`;
          // 因子
          const factorParam = params.find((p: any) => !Array.isArray(p.value) && p.seriesName === factorNameCn);
          if (factorParam) {
            const fv = factorParam.value;
            html += `${factorParam.marker} ${factorNameCn}: <b>${typeof fv === 'number' ? fv.toFixed(1) : fv}</b>`;
            if (idx != null && pctArray && pctArray[idx] != null) {
              html += ` &nbsp; 百分位 <b>${pctArray[idx]!.toFixed(0)}%</b>`;
              html += ` &nbsp; Z <b>${(zArray[idx]! > 0 ? '+' : '') + zArray[idx]!.toFixed(2)}σ</b>`;
            }
            html += '<br/>';
          }
          // ── 分割线 + 副图信息 ──
          if (subChart === 'volume') {
            const volParam = params.find((p: any) => p.seriesName === '成交额占比%');
            const volVal = volParam ? volParam.value : (idx != null ? volRatioHistory[idx] : null);
            if (volVal != null) {
              html += '<div style="margin-top:2px;padding-top:4px;border-top:1px solid #555">';
              html += '📊 成交额占比: <b>' + (+volVal).toFixed(2) + '%</b>';
              const vp = idx != null && volRatioPctArray ? volRatioPctArray[idx] : null;
              if (vp != null) html += ' &nbsp; 历史分位 <b>' + vp.toFixed(0) + '%</b>';
              html += '</div>';
            }
          } else if (subChart === 'macd') {
            const dif = params.find((p: any) => p.seriesName === 'DIF');
            const dea = params.find((p: any) => p.seriesName === 'DEA');
            const macdVal = params.find((p: any) => p.seriesName === 'MACD');
            if (dif || dea || macdVal) {
              html += '<div style="margin-top:2px;padding-top:4px;border-top:1px solid #555">';
              if (dif) html += `DIF: ${(+dif.value).toFixed(2)} &nbsp; `;
              if (dea) html += `DEA: ${(+dea.value).toFixed(2)} &nbsp; `;
              if (macdVal) html += `MACD: ${(+macdVal.value).toFixed(2)}`;
              html += '</div>';
            }
          }
          return html;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: [0, 1] }]
      },
      legend: { data: ['K线', factorNameCn, '成交额', 'MA5', 'DIF', 'DEA', 'MACD'].filter(Boolean), top: 0 },
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
        { type: 'value', gridIndex: 0, scale: true, splitNumber: 4, splitLine: { show: false }, axisLabel: { formatter: (v: number) => v.toFixed(2) } },
        subYAxis,
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 2, height: 14 },
      ],
      series: [...mainSeries, ...subSeries],
    };
  }, [displayData, alignedFactorValues, macd, subChart, factorNameCn, factorColor, volRatioHistory, volRatioPctArray]);

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#666' }}>加载中，请确保后端已启动 (uvicorn backend.server:app --port 8000)...</div>;
  if (error) return <div style={{ padding: 40, textAlign: 'center', color: '#F53F3F' }}>{error} — 确认后端已启动: uvicorn backend.server:app --port 8000</div>;
  if (Object.keys(option).length === 0) return <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>暂无数据，请检查资产选择</div>;

  return (
    <div style={{ padding: 16, fontFamily: '"PingFang SC","Microsoft YaHei",sans-serif' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 600 }}>因子研究图表</h2>

      {/* 控制栏 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={selectedAsset} onChange={e => setSelectedAsset(e.target.value)}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13, minWidth: 160 }}>
          {assets.map(a => (
            <option key={a.symbol} value={a.symbol}>{a.name}</option>
          ))}
        </select>

        <select value={selectedFactor} onChange={e => setSelectedFactor(e.target.value)}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13, minWidth: 140 }}>
          {factors.filter(f => f.tier === 1).map(f => (
            <option key={f.name} value={f.name}>{f.name_cn}</option>
          ))}
        </select>

        <select value={subChart} onChange={e => setSubChart(e.target.value as any)}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13 }}>
          <option value="volume">成交额</option>
          <option value="macd">MACD</option>
        </select>

        <select value={timeRange} onChange={e => setTimeRange(Number(e.target.value))}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 13 }}>
          <option value={252}>1年</option>
          <option value={756}>3年</option>
          <option value={1260}>5年</option>
          <option value={5000}>全部</option>
        </select>

        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer', userSelect: 'none' }}>
          <input type="checkbox" checked={showBenchmark} onChange={e => setShowBenchmark(e.target.checked)}
            style={{ cursor: 'pointer' }} />
          显示基准(中证全指)
        </label>
      </div>

      {/* 图表 */}
      <EChartsReact
        ref={chartRef}
        option={option}
        style={{ height: 650, width: '100%' }}
        notMerge
        lazyUpdate
        onChartReady={() => {}}
      />
    </div>
  );
};

export default FactorChart;
