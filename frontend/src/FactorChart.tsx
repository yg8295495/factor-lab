import React, { useState, useEffect, useMemo, useRef } from 'react';
import EChartsReact from 'echarts-for-react';
import * as echarts from 'echarts';

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

  // 统计语义
  const latestFactorValue = alignedFactorValues.filter(v => v != null).slice(-1)[0] ?? null;
  const factorHistory = factorData.map((d: any) => d.factor_value).filter((v: any) => v != null);
  const latestPercentile = latestFactorValue != null && factorHistory.length > 0
    ? calcPercentile(latestFactorValue, factorHistory) : null;
  const latestZscore = latestFactorValue != null && factorHistory.length > 0
    ? calcZscore(latestFactorValue, factorHistory) : null;

  const factorDef = factors.find(f => f.name === selectedFactor);
  const factorNameCn = factorDef?.name_cn || selectedFactor;
  const factorColor = factorDef?.display?.color || '#ff6600';
  const factorDesc = factorDef?.description || '';

  const option = useMemo(() => {
    if (displayData.length === 0) return {};
    const isKline = displayData[0]?.open != null;
    const mainSeries: any[] = [];

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
      const colors = displayData.map((d: any) => (d.close >= d.open ? '#F53F3F' : '#00B42A'));
      subSeries.push({ name: '成交额', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: vol, itemStyle: { color: (p: any) => colors[p.dataIndex] } });
      const ma5 = calcSMA(vol, 5);
      if (ma5.some(v => v != null)) subSeries.push({ name: 'MA5', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: ma5, lineStyle: { color: '#FF7D00', width: 1 }, symbol: 'none' });
      subYAxis = { type: 'value', gridIndex: 1, splitNumber: 3, axisLabel: { fontSize: 10 } };
    } else if (subChart === 'macd' && macd.dif.length > 0) {
      subSeries.push(
        { name: 'DIF', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: macd.dif, lineStyle: { color: '#fff', width: 1.5 }, symbol: 'none' },
        { name: 'DEA', type: 'line', xAxisIndex: 1, yAxisIndex: 2, data: macd.dea, lineStyle: { color: '#ff0', width: 1.5 }, symbol: 'none' },
        { name: 'MACD', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: macd.macd, itemStyle: { color: (p: any) => (p.value >= 0 ? '#F53F3F' : '#00B42A') } },
      );
      subYAxis = { type: 'value', gridIndex: 1, splitNumber: 3, axisLabel: { fontSize: 10 } };
    }

    return {
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'cross', link: [{ xAxisIndex: [0, 1] }] },
        formatter: (params: any) => {
          const date = params[0]?.axisValue || '';
          let html = `<b>${date}</b><br/>`;
          params.forEach((p: any) => {
            if (p.seriesName !== 'K线') html += `${p.marker} ${p.seriesName}: ${typeof p.value === 'number' ? p.value.toFixed(2) : p.value}<br/>`;
          });
          return html;
        },
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
        { type: 'value', gridIndex: 0, scale: true, splitNumber: 4 },
        { type: 'value', gridIndex: 0, scale: true, splitNumber: 4, splitLine: { show: false } },
        subYAxis,
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 2, height: 14 },
      ],
      series: [...mainSeries, ...subSeries],
    };
  }, [displayData, alignedFactorValues, macd, subChart, factorNameCn, factorColor]);

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
      </div>

      {/* 统计语义卡片 */}
      {latestFactorValue != null && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 13, color: '#555' }}>
          <span>
            {factorNameCn}: <b style={{ color: factorColor, fontSize: 15 }}>{latestFactorValue.toFixed(1)}</b>
          </span>
          {latestPercentile != null && (
            <span>
              历史百分位: <b style={{ color: latestPercentile > 90 ? '#F53F3F' : latestPercentile < 10 ? '#00B42A' : '#555' }}>
                {latestPercentile}%
              </b>
            </span>
          )}
          {latestZscore != null && (
            <span>
              Z-score: <b style={{ color: Math.abs(latestZscore) > 2 ? '#F53F3F' : '#555' }}>
                {latestZscore > 0 ? '+' : ''}{latestZscore.toFixed(2)}σ
              </b>
            </span>
          )}
          <span style={{ color: '#999', cursor: 'help' }} title={factorDesc}>ⓘ</span>
        </div>
      )}

      {/* 图表 */}
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
