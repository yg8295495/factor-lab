"""
Feature Registry — 因子注册表

按 Four Dimensions 组织，所有因子在此统一注册。
新增因子必须在这里定义，不允许散落在各处代码中。

每增加一个 Feature，必须回答:
1. 它测量什么？（定义）
2. 它属于哪个状态维度？（归属）
3. 它和已有 Feature 区别是什么？（正交性）
4. 它是否真的增加新的信息？（必要性）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FeatureDef:
    """单个因子的完整定义"""
    # ── 身份 ──
    name: str                           # 英文标识符，如 RS20
    name_cn: str                        # 中文名
    dimension: str                      # rs / breadth / volatility / style / context
    tier: int                           # 1=单资产计算 2=横截面聚合 3=需新数据源

    # ── 描述 ──
    description: str                    # 因子含义说明

    # ── 计算 ──
    compute_fn: str                     # calculator.py 中的函数名
    params: Dict = field(default_factory=dict)    # 计算参数
    dependencies: List[str] = field(default_factory=list)  # 依赖的原始字段
    storage: Optional[str] = None       # 写入 market_daily_data 的字段名

    # ── 统计 ──
    default_normalization: str = 'percentile'  # percentile / zscore / raw
    default_window: int = 250           # 默认滚动窗口

    # ── 展示 ──
    display: Dict = field(default_factory=lambda: {
        'color': '#666666',
        'chart': 'line',        # line / bar / area
        'y_axis': 'right',      # left / right / sub
    })

    # ── 状态 ──
    status: str = 'active'      # active / pending / deprecated


# ────────────────────────────────────────────
# 全量因子注册表
# ────────────────────────────────────────────

FEATURE_REGISTRY: Dict[str, FeatureDef] = {

    # ═══════════════════════════════════════════
    # RS 维度 — 趋势方向与强度 (Tier 1)
    # ═══════════════════════════════════════════

    'RS20': FeatureDef(
        name='RS20',
        name_cn='20日相对强度',
        dimension='rs',
        tier=1,
        description='标的相对于基准指数（中证全指）的20日滚动相对强弱。'
                    '使用 rolling_mean_ratio 算法: 标的收盘/标的20日均值。',
        compute_fn='calc_rs',
        params={'lookback': 20, 'method': 'rolling_mean_ratio', 'benchmark': 'index.000985.CSI'},
        dependencies=['close'],
        storage='rs20_cross',
        display={'color': '#ff6600', 'chart': 'line', 'y_axis': 'right'},
        default_normalization='percentile',
    ),

    'RS60': FeatureDef(
        name='RS60',
        name_cn='60日相对强度',
        dimension='rs',
        tier=1,
        description='标的相对于基准指数的60日滚动相对强弱。',
        compute_fn='calc_rs',
        params={'lookback': 60, 'method': 'rolling_mean_ratio', 'benchmark': 'index.000985.CSI'},
        dependencies=['close'],
        storage='rs60_cross',
        display={'color': '#ff9933', 'chart': 'line', 'y_axis': 'right'},
    ),

    'RS_SLOPE': FeatureDef(
        name='RS_SLOPE',
        name_cn='RS斜率',
        dimension='rs',
        tier=1,
        description='RS20的20日线性回归斜率。RS20值相同时，斜率方向指示趋势加速还是衰减。',
        compute_fn='calc_rs_slope',
        params={'lookback': 20, 'rs_source': 'RS20'},
        dependencies=['rs20_cross'],
        display={'color': '#cc4400', 'chart': 'line', 'y_axis': 'right'},
        default_normalization='zscore',
    ),

    # ═══════════════════════════════════════════
    # Breadth 维度 — 趋势是否扩散 (Tier 2)
    # ═══════════════════════════════════════════

    'ADV_DECLINE_RATIO': FeatureDef(
        name='ADV_DECLINE_RATIO',
        name_cn='涨跌比',
        dimension='breadth',
        tier=2,
        description='全市场（申万31行业）中上涨行业数/下跌行业数。>1=普涨，<1=普跌。'
                    '用于判断主升 vs 抱团（抱团时涨跌比低但指数涨）。',
        compute_fn='calc_adv_decline_ratio',
        params={},
        dependencies=['close'],
        display={'color': '#00b42a', 'chart': 'line', 'y_axis': 'left'},
    ),

    'INDUSTRY_DIFFUSION': FeatureDef(
        name='INDUSTRY_DIFFUSION',
        name_cn='行业扩散率',
        dimension='breadth',
        tier=2,
        description='申万31行业中RS20>50的行业占比。0~1之间，越高说明趋势扩散越广。'
                    '主升时>0.7，抱团时<0.4。',
        compute_fn='calc_industry_diffusion',
        params={'threshold': 50, 'rs_lookback': 20},
        dependencies=['close'],
        display={'color': '#69c0ff', 'chart': 'line', 'y_axis': 'left'},
    ),

    # ═══════════════════════════════════════════
    # Volatility 维度 — 蓄势/释放 (Tier 2)
    # ═══════════════════════════════════════════

    'VOLATILITY_20D': FeatureDef(
        name='VOLATILITY_20D',
        name_cn='20日波动率',
        dimension='volatility',
        tier=2,
        description='申万31行业平均的20日收益率标准差。'
                    '波动率压缩→蓄势，波动率扩张→释放。混沌状态常伴随波动率低位。',
        compute_fn='calc_market_volatility',
        params={'lookback': 20},
        dependencies=['close'],
        display={'color': '#722ed1', 'chart': 'line', 'y_axis': 'left'},
        default_normalization='zscore',
    ),

    # ═══════════════════════════════════════════
    # Style Spread 维度 — 资金偏好 (Tier 2)
    # ═══════════════════════════════════════════

    'SMALL_CAP_SPREAD': FeatureDef(
        name='SMALL_CAP_SPREAD',
        name_cn='大小票剪刀差',
        dimension='style',
        tier=2,
        description='中证2000(小盘)与沪深300(大盘)的RS20差值。'
                    '正数=小票强，负数=大票强。抱团时差值显著为负。',
        compute_fn='calc_small_cap_spread',
        params={'small_cap': 'index.932000.SH', 'large_cap': 'index.000300.SH', 'lookback': 20},
        dependencies=['close'],
        display={'color': '#eb2f96', 'chart': 'line', 'y_axis': 'left'},
        default_normalization='zscore',
    ),

    # ═══════════════════════════════════════════
    # 辅助上下文 (Tier 1/2)
    # ═══════════════════════════════════════════

    'MOM20': FeatureDef(
        name='MOM20',
        name_cn='20日时序动量',
        dimension='context',
        tier=1,
        description='标的自身20日涨跌幅（收盘价时序）。'
                    '正数=上涨趋势，负数=下跌趋势。与RS20的区别: RS20是相对基准，MOM20是绝对自身。',
        compute_fn='calc_time_momentum',
        params={'lookback': 20},
        dependencies=['close'],
        storage='time_momentum20',
        display={'color': '#165dff', 'chart': 'line', 'y_axis': 'right'},
    ),

    'MOM60': FeatureDef(
        name='MOM60',
        name_cn='60日时序动量',
        dimension='context',
        tier=1,
        description='标的自身60日涨跌幅。',
        compute_fn='calc_time_momentum',
        params={'lookback': 60},
        dependencies=['close'],
        storage='time_momentum60',
        display={'color': '#4096ff', 'chart': 'line', 'y_axis': 'right'},
    ),

    'TREND_STR': FeatureDef(
        name='TREND_STR',
        name_cn='趋势综合评分',
        dimension='context',
        tier=1,
        description='RS20、MOM20、RS斜率的综合评分，0~100。'
                    '用于快速判断趋势置信度。',
        compute_fn='calc_trend_strength',
        params={},
        dependencies=['rs20_cross', 'time_momentum20'],
        storage='trend_strength',
        display={'color': '#52c41a', 'chart': 'line', 'y_axis': 'right'},
    ),

    'PE_PERCENTILE': FeatureDef(
        name='PE_PERCENTILE',
        name_cn='PE历史百分位',
        dimension='context',
        tier=1,
        description='滚动市盈率在历史250日的百分位。95%=极度高估，5%=极度低估。'
                    '绝对PE无意义，百分位才有结构意义。',
        compute_fn='calc_percentile',
        params={'field': 'pe_ttm', 'window': 250},
        dependencies=['pe_ttm'],
        display={'color': '#fa8c16', 'chart': 'line', 'y_axis': 'left'},
    ),

    'PE_CHANGE_RATE': FeatureDef(
        name='PE_CHANGE_RATE',
        name_cn='PE扩张速度',
        dimension='context',
        tier=1,
        description='PE_TTM的20日变化率。快速扩张可能预示估值泡沫。',
        compute_fn='calc_change_rate',
        params={'field': 'pe_ttm', 'lookback': 20},
        dependencies=['pe_ttm'],
        display={'color': '#d4380d', 'chart': 'line', 'y_axis': 'left'},
        default_normalization='zscore',
    ),

    'DIV_YIELD': FeatureDef(
        name='DIV_YIELD',
        name_cn='股息率',
        dimension='context',
        tier=1,
        description='股息率原始值。红利风格判定用。',
        compute_fn='calc_dividend_yield_percentile',
        params={'window': 250},
        dependencies=['dividend_yield'],
        storage='dividend_yield',
        display={'color': '#237804', 'chart': 'line', 'y_axis': 'left'},
    ),

    'PRICE_VOL_DIVERGENCE': FeatureDef(
        name='PRICE_VOL_DIVERGENCE',
        name_cn='量价背离',
        dimension='context',
        tier=2,
        description='价格方向与成交量方向的背离度。'
                    '放量滞涨=顶背离（风险信号），缩量下跌=底背离（机会信号）。',
        compute_fn='calc_price_vol_divergence',
        params={'lookback': 5},
        dependencies=['close', 'volume'],
        display={'color': '#f5222d', 'chart': 'line', 'y_axis': 'left'},
        default_normalization='zscore',
    ),

    'BREAKOUT': FeatureDef(
        name='BREAKOUT',
        name_cn='突破强度',
        dimension='context',
        tier=1,
        description='收盘价突破20日均线的幅度。正数=向上突破，负数=向下突破。',
        compute_fn='calc_breakout',
        params={'lookback': 20},
        dependencies=['close'],
        storage='breakout_strength',
        display={'color': '#ff4d4f', 'chart': 'line', 'y_axis': 'right'},
    ),
}


# ────────────────────────────────────────────
# 辅助工具
# ────────────────────────────────────────────

def get_features_by_dimension(dimension: str) -> Dict[str, FeatureDef]:
    """按维度获取所有因子"""
    return {k: v for k, v in FEATURE_REGISTRY.items() if v.dimension == dimension}


def get_features_by_tier(tier: int) -> Dict[str, FeatureDef]:
    """按 Tier 获取所有因子"""
    return {k: v for k, v in FEATURE_REGISTRY.items() if v.tier == tier}


def get_active_features() -> Dict[str, FeatureDef]:
    """获取所有激活状态的因子"""
    return {k: v for k, v in FEATURE_REGISTRY.items() if v.status == 'active'}


def list_features() -> List[Dict]:
    """返回简洁的因子列表（给前端用）"""
    result = []
    for name, f in FEATURE_REGISTRY.items():
        if f.status != 'active':
            continue
        result.append({
            'name': name,
            'name_cn': f.name_cn,
            'dimension': f.dimension,
            'tier': f.tier,
            'description': f.description,
            'default_normalization': f.default_normalization,
            'display': f.display,
        })
    return result
