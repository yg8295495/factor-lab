"""
Feature Registry — 因子注册表 (v2.0, frozen after Phase A 2026-06-08)

17 factors: 12 MAIN + 5 AUX (auxiliary/observation).
Algorithm definitions verified by Phase A testing.

Each factor has:
  name, name_cn, category(MAIN|AUX), dimension, formula, storage
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class FactorDef:
    name: str
    name_cn: str
    category: str               # MAIN / AUX
    dimension: str              # trend / momentum / volatility / breadth / volume / leadership / style
    tier: int                   # 1=single-asset 2=cross-section 3=style/regime
    description: str
    formula: str
    params: Dict = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    storage: Optional[str] = None
    status: str = 'active'

FACTOR_REGISTRY: Dict[str, FactorDef] = {

    # ════════════════════════════════════════════
    # ① Trend / Momentum (5 factors: 3 MAIN + 2 AUX)
    # ════════════════════════════════════════════

    'RS20': FactorDef(
        name='RS20', name_cn='20日相对强度',
        category='MAIN', dimension='trend', tier=1,
        description='(1+标的收益)/(1+基准收益)比值。>1=跑赢基准，<1=跑输。经典相对强度定义，非超额收益。',
        formula='(P(t)/P(t-20)) / (BM(t)/BM(t-20))',
        params={'lookback': 20, 'benchmark': 'index.000985.SH'},
        dependencies=['close'], storage='rs20_cross',
    ),

    'MOM20': FactorDef(
        name='MOM20', name_cn='20日时序动量',
        category='MAIN', dimension='momentum', tier=1,
        description='标的自身20日涨跌幅(不含基准对比)。和RS20的区别：MOM20是绝对回报，RS20是相对强度。',
        formula='P(t)/P(t-20) - 1',
        params={'lookback': 20},
        dependencies=['close'], storage='time_momentum20',
    ),

    'MOM60': FactorDef(
        name='MOM60', name_cn='60日时序动量',
        category='MAIN', dimension='momentum', tier=1,
        description='标的自身60日涨跌幅。',
        formula='P(t)/P(t-60) - 1',
        params={'lookback': 60},
        dependencies=['close'], storage='time_momentum60',
    ),

    'ACCEL': FactorDef(
        name='ACCEL', name_cn='动量加速度',
        category='MAIN', dimension='momentum', tier=1,
        description='MOM20的5日差分。正值=动量加速，负值=动量减速。拐点敏感。',
        formula='MOM20(t) - MOM20(t-5)',
        params={'lookback': 5},
        dependencies=['close'], storage=None,  # 实时计算
    ),

    'RS60': FactorDef(
        name='RS60', name_cn='60日相对强度',
        category='AUX', dimension='trend', tier=1,
        description='60日比值的相对强度。和RS20同源，长周期参考。',
        formula='(P(t)/P(t-60)) / (BM(t)/BM(t-60))',
        params={'lookback': 60, 'benchmark': 'index.000985.SH'},
        dependencies=['close'], storage='rs60_cross',
    ),

    # ════════════════════════════════════════════
    # ② Volatility (2 factors: 1 MAIN + 1 AUX)
    # ════════════════════════════════════════════

    'VOL20': FactorDef(
        name='VOL20', name_cn='20日波动率',
        category='MAIN', dimension='volatility', tier=1,
        description='每个行业独立计算的20日收益率标准差(非市场平均)。高vol=剧烈波动，低vol=蓄势。',
        formula='std(ret[t-20:t])，ddof=1',
        params={'lookback': 20},
        dependencies=['close'], storage='volatility_20d',
    ),

    'VOL_RATIO': FactorDef(
        name='VOL_RATIO', name_cn='波动率比值',
        category='AUX', dimension='volatility', tier=1,
        description='当前Vol20 / 20日前Vol20。>1.2=波动扩张，<0.8=波动压缩，连续值不做二值化。',
        formula='Vol20(t) / Vol20(t-20)',
        params={'lookback': 20},
        dependencies=['close'], storage=None,  # 实时计算
    ),

    # ════════════════════════════════════════════
    # ③ Breadth / Diffusion (3 factors: 2 MAIN + 1 AUX)
    # ════════════════════════════════════════════

    'PART_RATE': FactorDef(
        name='PART_RATE', name_cn='行业参与度',
        category='MAIN', dimension='breadth', tier=2,
        description='行业内above MA20股票比例。越高说明行业参与度越广。',
        formula='above_ma20_ratio（DB字段直读）',
        dependencies=['close'], storage='above_ma20_ratio',
    ),

    'BREADTH_CHG': FactorDef(
        name='BREADTH_CHG', name_cn='广度变化率',
        category='MAIN', dimension='breadth', tier=2,
        description='above_ma20_ratio的5日差分。连续正数=广度扩张，连续负数=广度收缩。最稳定的正向信号源。',
        formula='above_ma20_ratio(t) - above_ma20_ratio(t-5)',
        dependencies=['above_ma20_ratio'], storage=None,  # 实时计算
    ),

    'NEW_HIGH': FactorDef(
        name='NEW_HIGH', name_cn='20日新高比例',
        category='AUX', dimension='breadth', tier=2,
        description='行业内创20日新高的股票比例。极端值(>0.3或<0.05)有参考价值。',
        formula='new_high_20d_ratio（DB字段直读）',
        dependencies=['close'], storage='new_high_20d_ratio',
    ),

    # ════════════════════════════════════════════
    # ④ Price-Volume (2 factors: 1 MAIN + 1 AUX)
    # ════════════════════════════════════════════

    'AMT_RATIO': FactorDef(
        name='AMT_RATIO', name_cn='量比',
        category='MAIN', dimension='volume', tier=1,
        description='当日成交额/20日均成交额。>1=放量，<1=缩量。极端市场(股灾/反弹)中IC最高。',
        formula='amount(t) / SMA20(amount)',
        dependencies=['amount'], storage='amount_ratio',
    ),

    'VOL_BKOUT': FactorDef(
        name='VOL_BKOUT', name_cn='放量加速度',
        category='AUX', dimension='volume', tier=1,
        description='量比减去5日量比均值。区分持续温和放量和脉冲式放量。连续值不做阈值触发。',
        formula='AmtRatio(t) - SMA5(AmtRatio)',
        dependencies=['amount_ratio'], storage=None,  # 实时计算
    ),

    # ════════════════════════════════════════════
    # ⑤ Leadership / Structure (3 factors: 2 MAIN + 1 AUX)
    # ════════════════════════════════════════════

    'CR3': FactorDef(
        name='CR3', name_cn='Top3成交额集中度',
        category='MAIN', dimension='leadership', tier=2,
        description='成交额Top3行业之和/全部行业之和。全场最强因子(Avg|IC|=0.232)。集中度越高=资金越聚焦。',
        formula='sum(Top3_amount) / sum(all_sector_amount)',
        dependencies=['amount'], storage=None,  # 实时计算
    ),

    'CR5': FactorDef(
        name='CR5', name_cn='Top5成交额集中度',
        category='MAIN', dimension='leadership', tier=2,
        description='成交额Top5行业之和/全部行业之和。与CR3互补使用。',
        formula='sum(Top5_amount) / sum(all_sector_amount)',
        dependencies=['amount'], storage=None,  # 实时计算
    ),

    'TOP_DISP': FactorDef(
        name='TOP_DISP', name_cn='领导力强度',
        category='AUX', dimension='leadership', tier=2,
        description='Top3行业涨幅均值 - Bottom3行业涨幅均值。高值=龙头带领(集中度高)，低值=散乱(无主线)。',
        formula='mean(Top3_ret) - mean(Bottom3_ret)',
        dependencies=['close'], storage=None,  # 实时计算
    ),

    # ════════════════════════════════════════════
    # ⑥ Style (2 MAIN factors — Layer 4预备)
    # ════════════════════════════════════════════

    'SC_SPREAD': FactorDef(
        name='SC_SPREAD', name_cn='大小票剪刀差',
        category='MAIN', dimension='style', tier=3,
        description='中证2000(小盘)RS20 - 沪深300(大盘)RS20。正值=小票强，负值=大票强。Layer4市场风格变量。',
        formula='index.932000.SH ret20 - index.000300.SH ret20',
        params={'lookback': 20},
        dependencies=['close'], storage='small_cap_spread',
    ),

    'ADV_DECL': FactorDef(
        name='ADV_DECL', name_cn='行业涨跌比',
        category='MAIN', dimension='style', tier=2,
        description='30个申万行业中上涨家数/有数据行业总数。行业级涨跌比(非全市场指数级)。',
        formula='sector_adv_count / sector_total_valid',
        dependencies=['close'], storage='adv_decline_ratio',
    ),
}

# ════════════════════════════════════════════
# 查询辅助
# ════════════════════════════════════════════

def get_by_category(cat: str) -> Dict[str, FactorDef]:
    """按MAIN/AUX获取"""
    return {k: v for k, v in FACTOR_REGISTRY.items() if v.category == cat}

def get_by_dimension(dim: str) -> Dict[str, FactorDef]:
    """按维度获取"""
    return {k: v for k, v in FACTOR_REGISTRY.items() if v.dimension == dim}

def list_factors() -> List[Dict]:
    """返回简洁因子列表"""
    return [{'name': f.name, 'name_cn': f.name_cn, 'category': f.category,
             'dimension': f.dimension, 'formula': f.formula, 'status': f.status}
            for f in FACTOR_REGISTRY.values() if f.status == 'active']

def get_main_factors() -> List[str]:
    return [k for k, v in FACTOR_REGISTRY.items() if v.category == 'MAIN']

def get_aux_factors() -> List[str]:
    return [k for k, v in FACTOR_REGISTRY.items() if v.category == 'AUX']
