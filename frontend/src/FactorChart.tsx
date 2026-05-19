import React, { useState, useEffect, useMemo, useRef } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  CandlestickChart, LineChart, BarChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, CanvasRenderer,
]);

const API_BASE = 'http://127.0.0.1:8000';

// ─── 数据类型 ───
interface Asset {
  symbol: string;
  name: string;
  asset_type: string;
}

interface FactorDef {
  name: string;
  name_cn: string;
  dimension: string;
  tier: number;
  description: string;
  display: { color: string; chart: string; y_axis: string };
}

interface KlineRow {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  amount?: number;
}

// ─── 辅助函数 ───
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
    const k = 2 / (p + 1);
    const r = [d[0]];
    for (let i = 1; i < d.length; i++) r.push(d[i] * k + r[i - 1] * (1 - k));
    return r;
  };
  const ema12 = ema(data, 12);
  const ema26 = ema(data, 26);
  const dif = ema12.map((v, i) => v - ema26[i]);
  const dea = ema(dif, 9);
  const macd = dif.map((v, i) => 2 * (v - dea[i]));
  return { dif, dea, macd };
}

// ─── 组件 ───
const FactorChart: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [factors, setFactors] = useState<FactorDef[]>([]);
  const [selectedAsset, setSelectedAsset] = useState('');
  const [selectedFactor, setSelectedFactor] = useState('');
  const [subChart, setSubChart] = useState<'macd' | 'volume'>('volume');
  const [timeRange, setTimeRange] = useState(756);
  const [rawData, setRawData] = useState<KlineRow[]>([]);
  const [factorData, setFactorData] = useState<any[]>([]);
  const chartRef = useRef<any>(null);

  // 加载资产列表
  useEffect(() => {
    fetch(`${API_BASE}/api/assets`)
      .then(r => r.json())
      .then(setAssets)
      .catch(() => {});
    fetch(`${API_BASE}/api/factors`)
      .then(r => r.json())
      .then(setFactors)
      .catch(() => {});
  }, []);

  // 默认选中
  useEffect(() => {
    if (!selectedAsset && assets.length > 0) setSelectedAsset(assets[0].symbol);
    if (!selectedFactor && factors.length > 0) setSelectedFactor(factors[0].name);
  }, [assets, factors]);

  // 加载数据
  useEffect(() => {
    if (!selectedAsset) return;
    const fields = 'trade_date,open,high,low,close,volume,amount';
    fetch(`${API_BASE}/api/data/${selectedAsset}?fields=${fields}&limit=5000`)
      .then(r => r.json())
      .then(data => setRawData((data || []).reverse()))
      .catch(() => {});

    if (selectedFactor) {
      fetch(`${API_BASE}/api/factor-data/${selectedAsset}/${selectedFactor}?limit=5000`)
        .then(r => r.json())
        .then(data => setFactorData((data?.data || []).reverse()))
        .catch(() => {});
    }
  }, [selectedAsset, selectedFactor]);

  // 截取时间窗口
  const displayData = useMemo(() => {
    if (rawData.length === 0) return [];
    return rawData.slice(-timeRange);
  }, [rawData, timeRange]);

  const dates = displayData.map(d => d.trade_date);
  const close = displayData.map(d => d.close);

  // MACD
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

  const factorNameCn = factors.find(f => f.name === selectedFactor)?.name_cn || selectedFactor;
  const factorColor = factors.find(f => f.name === selectedFactor)?.display?.color || '#ff6600';

  // ─── ECharts Option ───
  const option = useMemo(() => {
    if (displayData.length === 0) return {};

    const isKline = displayData[0]?.open != null;

    // ── 主图系列 ──
    const mainSeries: any[] = [];

    if (isKline) {
      mainSeries.push({
        name: 'K线', type: 'candlestick', yAxisIndex: 0,
        data: displayData.map(d => [d.open, d.close, d.low, d.high]),
        itemStyle: { color: '#F53F3F', color0: '#00B42A', borderColor: '#F53F3F', borderColor0: '#00B42A' },
      });
    } else {
      mainSeries.push({
        name: '收盘', type: 'line', yAxisIndex: 0,
        data: displayData.map(d => d.close),
        lineStyle: { color: '#165DFF', width: 2 },
        itemStyle: { color: '#165DFF' },
      });
    }

    // 因子线（右轴）
    if (alignedFactorValues.length > 0) {
      mainSeries.push({
        name: factorNameCn, type: 'line', yAxisIndex: 1,
        data: alignedFactorValues,
        lineStyle: { color: factorColor, width: 2 },
        itemStyle: { color: factorColor },
        symbol: 'none',
      });
    }

    // ── 副图系列 ──
    const subSeries: any[] = [];
    let subYAxis: any = {};

    if (subChart === 'volume' && displayData[0]?.amount != null) {
      const vol = displayData.map(d => d.amount ?? 0);
      const colors = displayData.map(d => (d.close >= d.open ? '#F53F3F' : '#00B42A'));
      subSeries.push({
        name: '成交额', type: 'bar', yAxisIndex: 2,
        data: vol, itemStyle: { color: (p: any) => colors[p.dataIndex] },
      });
      // 5日均量线
      const ma5 = calcSMA(vol, 5);
      if (ma5.some(v => v != null)) {
        subSeries.push({
          name: 'MA5', type: 'line', yAxisIndex: 2,
          data: ma5, lineStyle: { color: '#FF7D00', width: 1 },
          symbol: 'none',
        });
      }
      subYAxis = { type: 'value', splitNumber: 3, axisLabel: { fontSize: 10 } };
    } else if (subChart === 'macd' && macd.dif.length > 0) {
      subSeries.push(
        { name: 'DIF', type: 'line', yAxisIndex: 2, data: macd.dif, lineStyle: { color: '#fff', width: 1.5 }, symbol: 'none' },
        { name: 'DEA', type: 'line', yAxisIndex: 2, data: macd.dea, lineStyle: { color: '#ff0', width: 1.5 }, symbol: 'none' },
        {
          name: 'MACD', type: 'bar', yAxisIndex: 2,
          data: macd.macd.map((v: number) => v),
          itemStyle: { color: (p: any) => (p.value >= 0 ? '#F53F3F' : '#00B42A') },
        },
      );
      subYAxis = { type: 'value', splitNumber: 3, axisLabel: { fontSize: 10 } };
    }

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', link: [{ xAxisIndex: [0, 1] }] },
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

  // 十字光标联动
  const onChartReady = (instance: any) => {
    chartRef.current = instance;
    instance.on('dataZoom', (params: any) => {});
  };

  return (
    <div style={{ padding: 16, fontFamily: 'sans-serif' }}>
      <h2>因子研究图表</h2>

      <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={selectedAsset} onChange={e => setSelectedAsset(e.target.value)}
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}>
          {assets.map(a => (
            <option key={a.symbol} value={a.symbol}>{a.name} ({a.symbol.split('.').slice(0, 2).join('.')})</option>
          ))}
        </select>

        <select value={selectedFactor} onChange={e => setSelectedFactor(e.target.value)}
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}>
          {factors.filter(f => f.tier === 1).map(f => (
            <option key={f.name} value={f.name}>{f.name_cn} ({f.name})</option>
          ))}
        </select>

        <select value={subChart} onChange={e => setSubChart(e.target.value as any)}
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}>
          <option value="volume">成交额</option>
          <option value="macd">MACD</option>
        </select>

        <select value={timeRange} onChange={e => setTimeRange(Number(e.target.value))}
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc' }}>
          <option value={252}>1年</option>
          <option value={756}>3年</option>
          <option value={1260}>5年</option>
          <option value={5000}>全部</option>
        </select>
      </div>

      <ReactEChartsCore
        ref={chartRef}
        echarts={echarts}
        option={option}
        style={{ height: 520 }}
        notMerge
        lazyUpdate
        onChartReady={onChartReady}
      />
    </div>
  );
};

export default FactorChart;
