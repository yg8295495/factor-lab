"""
factor-lab 全局配置
"""
import os

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据库路径
DB_PATH = os.path.join(ROOT_DIR, "data", "quant_engine.db")

# 标注数据路径
LABELS_DIR = os.path.join(ROOT_DIR, "backend", "research", "labeling", "labels")

# 数据采集配置
COLLECTOR_CONFIG = {
    "akshare": {
        "trust_env": False,  # 绕过代理（东方财富等被屏蔽时使用）
    },
    "baostock": {},
}

# 因子计算默认参数
FEATURE_DEFAULTS = {
    "rolling_window": 250,       # 滚动窗口（交易日 ≈ 1年）
    "rs_benchmark": "index.801003.SW",  # 申万Ａ指（2026-06-09 切换）
    "momentum_periods": [5, 20, 60],
}
