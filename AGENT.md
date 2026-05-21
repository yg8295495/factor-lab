# AGENT.md — AI 工作导航
> 本文件是**给 AI 看的项目地图**，不是给人看的。
> 新会话 / 上下文压缩后，先读这个 + `PLAN.md` + `README.md`。

---

## 一、项目总览

```yaml
project:
  name: factor-lab
  root: /path/to/project
  db: data/quant_engine.db              # SQLite, 99MB, 6张表, schema已冻结
  date_range: 2004-12-31 ~ 2026-05-19   # 5172 个交易日
  sectors: 30                           # 申万行业
  indices: 25                           # 宽基+主题指数
```

## 二、文档索引

```yaml
docs:
  human_readable:
    README.md:             "项目概述、架构说明、核心哲学（人看的）"
    PLAN.md:               "开发里程碑 + 当前待办（精简版）"
    docs/research/:
      phase_sector_leadership_v1.md: "13阶段 × 行业领涨TOP3分析报告"
      behavior_scoring_v1.md:   "行业行为评分v2 实验结论合集"
    docs/data_*.md:       "数据源接入状态、技术文档"
  ai_readable:
    AGENT.md:              "本文件 — AI 工作导航"
```

## 三、脚本路径

```yaml
scripts:
  calculate_factors:
    cmd: "python3 -m backend.research.features.calculator"
    desc: "计算所有Tier1+Tier2因子，写入market_daily_data"
    output: "数据库直写"
  
  sector_leadership_analysis:
    cmd: "python3 backend/research/analysis/sector_leadership.py"
    desc: "每个历史阶段的行业领涨TOP3分析"
    output: "backend/research/analysis/output/phase_analysis.json"
  
  behavior_score_v2:
    cmd: "python3 backend/research/analysis/sector_behavior_score.py"
    desc: "转折期行为评分（循环版，默认出口）"
    output: "backend/research/analysis/output/sector_behavior_scores.json"
    flags:
      --rolling:    "滚动回测（每20天调仓）"
      --continuous: "全历史连续滚动回测"
      --daily:      "每日滚动回测（已被__向量化版污染__，勿用）"
  
  strength_score_v1:
    cmd: "python3 backend/research/analysis/sector_strength_score.py"
    desc: "强度评分v1（向量化，仅参考）"
    output: "backend/research/analysis/output/sector_scores.json"
  
  stock_pilot:
    cmd: "python3 backend/collectors/stock_pilot.py"
    desc: "3行业个股数据pilot验证（电子/食品饮料/银行）"
    status: "脚本就绪，需在台式机执行（当前环境无外网）"
    note: "pilot通过后写全量脚本 + breadth计算"
```

## 四、关键设计决策

```yaml
design_decisions:
  - rule: "所有回测必须用滚动方式（每20天重评分→调仓→跟踪超额），禁止静态命中率"
    why: "实战中主线分阶段轮换，静态命中率扭曲回测价值"
    ref: "memory: workflow_accuracy_first"
  
  - rule: "循环版优先于向量化版"
    why: "不同行业交易日历不同（历史上有15→27→30个），pivot对齐导致窗口偏移。循环版用各行业独立dropna()定位窗口，结果准确"
    ref: "test: backend/research/analysis/test_vector_vs_loop.py (匹配率仅34.7%)"
  
  - rule: "涨跌停标记使用 baostock pctChg 字段"
    why: "baostock 的 pctChg 始终返回原始涨跌幅，不受 adjustflag 影响"
    price_convention:
      涨跌停/当日涨跌幅限制判定: "baostock pctChg 字段 (>= 9.8%)"
      收益回测/净值/RS/Momentum: "后复权 close"
      人工看盘/K线展示: "前复权"
      成交额/成交量: "原始值，不复权"
  
  - rule: "不使用未来数据验证"
    why: "评分点只用到当日可用的累计数据"
    ref: "section_behavior_score.py calc_sector_rolling_score()"
  
  - rule: "schema已冻结，不改结构不改主键"
    why: "已有6表23万行数据，新因子只加字段"
  
  - rule: "符号编码 {asset_type}.{ticker}.{exchange}"
    example: "index.000985.SH, sector.801780.SW"

  - rule: "个股数据源使用 baostock，不使用东方财富/akshare"
    why: "东方财富IP封禁严重。baostock adjustflag=1单次调用即可拿到后复权close + pctChg"
    ref: "baostock pctChg 字段不受复权影响"
    note: "~5%次新股解压错误跳过即可，不影响breadth统计"
  
  - rule: "因子通过Feature Registry注册，不散落各处"
    ref: "backend/research/features/registry.py"
```

## 五、实验状态

```yaml
experiments:
  sector_scoring_v1:
    status: "done"
    method: "单点评分（阳线率+RS排名+成交量+持续性）"
    result: "命中率8.3%，天然偏向防御板块，已废弃"
    doc: "docs/research/behavior_scoring_v1.md"
  
  sector_behavior_v2_v0.1:
    status: "done"
    method: "转折期3区间回看评分（W1放量震荡+W2缩量洗盘+W3初升试探）"
    result: "滚动回测130次调仓，全期累计超额+60.5%，胜率53.1%"
    doc: "docs/research/behavior_scoring_v1.md#v01-回测结果"
    next:
      - "区分'反弹放量'和'主线放量'——W3信号过滤"
      - "动态 eval_offset 替代固定30天"
  
  vector_vs_loop_test:
    status: "done"
    result: "向量化版与循环版匹配率仅34.7%，循环版为正确版本"
    code: "backend/research/analysis/test_vector_vs_loop.py"
    output: "backend/research/analysis/output/vector_vs_loop_test.json"
```

## 六、数据覆盖

```yaml
factor_coverage:
  rs20/rs60/mom20/mom60/breakout:        "90%+ ✅"
  industry_diffusion:                     "87% ✅"
  adv_decline_ratio:                      "99.7% ✅ （Tier2 bug修复后）"
  market_volatility_20d:                  "99.7% ✅"
  small_cap_spread:                       "50% ⚠️ 中证2000数据限制"
  pe_percentile:                          "22% ⚠️ 仅指数有PE"
  dividend_yield/limit_up_down/volume:    "0% ❌ 无数据源"
```

## 七、快速命令

```bash
# 计算因子
python3 -m backend.research.features.calculator

# 运行行为评分（循环版）
python3 backend/research/analysis/sector_behavior_score.py
python3 backend/research/analysis/sector_behavior_score.py --rolling
python3 backend/research/analysis/sector_behavior_score.py --continuous

# 运行行业领涨分析
python3 backend/research/analysis/sector_leadership.py

# 启动后端
cd backend && python3 server.py

# 前端
cd frontend && npm run dev
```
