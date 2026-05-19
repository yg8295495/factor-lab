"""
数据模型 — 对应 quant_engine.db 的6张表

schema 已冻结，不删不改现有字段。
新因子只加字段，不加新表。
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class AssetMaster:
    """资产主表 — 全系统资产身份证"""
    symbol: str           # 编码: {asset_type}.{ticker}.{exchange}
    name: str             # 中文名称
    asset_type: str       # stock / index / etf / sector
    exchange: Optional[str] = None  # SH / SZ / CSI / SW ...
    stable_industry: Optional[str] = None  # 申万一级行业
    tags: Optional[str] = None        # JSON数组
    is_active: int = 1    # 1=跟踪中 0=已停用


@dataclass
class MarketDailyData:
    """核心宽表 — 日频研究数据"""
    symbol: str                    # 资产标识
    trade_date: date               # 交易日

    # 行情
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None   # 成交量(手)
    amount: Optional[float] = None   # 成交额(元)
    turnover_rate: Optional[float] = None

    # 估值
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    peg: Optional[float] = None
    dividend_yield: Optional[float] = None

    # 成长质量
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None

    # 趋势因子 (Layer 2 填充)
    rs20_cross: Optional[float] = None
    rs60_cross: Optional[float] = None
    time_momentum20: Optional[float] = None
    time_momentum60: Optional[float] = None
    trend_strength: Optional[float] = None

    # 量价因子
    volume_ratio: Optional[float] = None
    amount_ratio: Optional[float] = None
    price_volume_state: Optional[str] = None
    breakout_strength: Optional[float] = None

    # 情绪
    limit_up_flag: Optional[int] = None
    limit_down_flag: Optional[int] = None
    bust_flag: Optional[int] = None

    # 风格
    growth_score: Optional[float] = None
    dividend_score: Optional[float] = None
    small_cap_score: Optional[float] = None
    institution_score: Optional[float] = None

    # AI辅助
    ai_theme_tag: Optional[str] = None
    ai_sentiment_tag: Optional[str] = None


@dataclass
class MarketStateHistory:
    """市场状态表"""
    id: Optional[int] = None
    trade_date: date = None
    market_state: Optional[str] = None     # 主升/分歧/退潮/混沌
    style_state: Optional[str] = None      # 小票主导/机构抱团/成长风格/红利风格
    risk_state: Optional[str] = None       # Risk On / Risk Off
    main_theme: Optional[str] = None       # 当前主线
    confidence: Optional[float] = None     # 置信度 0-1
    comment: Optional[str] = None


@dataclass
class ThemeTracking:
    """主题跟踪表"""
    id: Optional[int] = None
    trade_date: date = None
    theme_name: str = None
    strength_score: Optional[float] = None
    heat_score: Optional[float] = None
    leader_symbol: Optional[str] = None
    continuity_score: Optional[float] = None


@dataclass
class AiAnalysisReport:
    """AI分析报告表"""
    id: Optional[int] = None
    trade_date: date = None
    symbol: Optional[str] = None
    report_type: str = None   # 日报/周报/行业分析/风险提示
    content: Optional[str] = None
    source_refs: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class AiMemory:
    """AI长期经验库"""
    id: Optional[int] = None
    topic: str = None
    summary: Optional[str] = None
    evidence_dates: Optional[str] = None
    confidence: Optional[float] = None
    created_at: Optional[date] = None
    updated_at: Optional[date] = None
