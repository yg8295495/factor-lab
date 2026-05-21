# 个股日线数据源调研报告

> 目的：为因子实验室采集 A 股个股日线数据，评估各数据源可行性。
> 测试环境：MacBook Air（Intel i5），Clash Verge 代理。
> 更新日期：2026-05-21

---

## 一、需求梳理

个股日线需要以下字段：

| 字段 | 用途 | 备注 |
|------|------|------|
| open/high/low/close | 基础行情 | 未复权 |
| volume / amount | 成交量/额 | 未复权 |
| close_hfq | 后复权收盘价 | 回测、因子计算、breadth |
| pct_chg_raw | 原始涨跌幅 | 涨跌停判定(±9.8%/±4.8%/±19.5%) |
| hfq_factor | 复权因子 | close_hfq / close 本地计算 |

---

## 二、数据源测试结果

### 2.1 baostock

| 项目 | 结果 |
|------|------|
| 登录 | ✅ 成功 |
| adjustflag=1（后复权 close） | ⚠️ 前 100 笔正常，之后连接卡死 |
| adjustflag=3（未复权 OHLC + pctChg） | ⚠️ 同上 |
| 多线程并发 | ❌ 单 socket 连接，并发导致数据流交错、解压失败 |
| 成功率 | ~95%（次新股 5% 解压失败可跳过） |

**问题**：
1. 线程安全：10 线程并发查同一 socket → 数据流混叠 → `'utf-8' codec can't decode` + `Error -3 while decompressing`  
   **解决**：加全局锁 `_BS_LOCK`，串行化查询 ✅
2. 服务端限流：同一连接约 100 笔后服务端静默掐断 → 客户端 `recv()` 永远挂着  
   **解决**：设 `socket.setdefaulttimeout(25)` + 每 80 笔自动 logout/login 重连

**速度**：~2.1 支/秒（串行，仅 date+close 两字段），646 支约 5 分钟（实测 142 支/69s）

### 2.2 mootdx（通达信协议）

| 项目 | 结果 |
|------|------|
| 未复权 OHLC + volume + amount | ✅ 全量（2005~2026），~5000行/支 |
| 后复权 close | ❌ 无 adjust 参数，仅返回不复权 |
| 涨跌幅 | ❌ 无 pct_chg 字段，需从 close 自算（无偏差） |
| 复权因子 xdxr | ✅ 返回分红送配事件数据 |
| 多线程 | ✅ 各自独立连接，5 线程正常 |
| 成功率 | 620/646（95.9%），失败为次新股/停牌 |

**速度**：5 线程并行，~3.8 支/秒（全量历史），646 支约 3 分钟（实测 142 支/37s）

### 2.3 akshare 腾讯源 stock_zh_a_hist_tx

| 项目 | 结果 |
|------|------|
| 不复权 OHLC + amount | ✅ 通，无封 IP |
| 后复权 close | ✅ adjust='hfq' 直接返回 |
| volume | ❌ 缺成交量 |
| 涨跌幅 | ❌ 需自算 |

**速度**：~0.15 支/秒（串行），646 支约 65 分钟（太慢）

### 2.4 akshare 东方财富 stock_zh_a_hist

| 项目 | 结果 |
|------|------|
| 本机 | ❌ `push2his.eastmoney.com:443` 连接超时（IP/代理限制） |
| 是否全局不可用 | ❌ 仅本机网络受限，浏览器 + Playwright + cookie 可通 |

**结论**：仅东财独有数据时才用 Playwright 方案

---

## 三、推荐方案：mootdx（主）+ baostock（辅）

### 分工

| 数据 | 来源 | 原因 |
|------|------|------|
| 未复权 OHLC + vol + amount | mootdx 并行 | 实测 3.8支/秒、有volume、无连接限制 |
| pct_chg_raw | mootdx close 自算 | = (close_t - close_t-1) / close_t-1 × 100，无偏差 |
| close_hfq（后复权） | baostock adjustflag=1 | 官方直接提供，不需要 xdxr 自算 |
| hfq_factor | 本地计算 | close_hfq / close，简单除法 |

### 预估耗时（2026-05-22 实测更新）

| 阶段 | pilot 3 行业（142支） | 全量（6000支） | 实测 |
|------|---------------------|--------------|------|
| mootdx 未复权 | ~40s | ~26 分钟 | 37s（3.8支/秒） |
| baostock 后复权 close | ~70s | ~48 分钟 | 69s（2.1支/秒） |
| 合并+写入+breadth | ~15s | ~5 分钟 | 13s（269,201行） |
| **总计** | **~2 分钟** | **~79 分钟** | **2分5秒** |

### 注意事项

1. **baostock 连接限制**：socket 超时设 25s，每 80 笔自动重连（`bs.logout() → bs.login()`）
2. **mootdx 失败率**：~4% 次新股/停牌可跳过，不影响 breadth 统计
3. **后复权不自己算**：xdxr 虽有复权因子但计算复杂易出错，坚持 baostock 直取

---

## 四、pilot 验证建议

> 目的：验证数据可靠性 + 采集管道可行性，非全量跑完

1. 每个行业只取前 **50-70 支**（共约 200 支）
2. 验证项目：
   - [x] mootdx 未复权数据字段完整（OHLC + vol + amount）— 142/142 全成功
   - [x] baostock 后复权 close 可稳定采集（带重连）— 142/142 全成功
   - [x] hfq_factor 计算正确（close_hfq / close）— max_err=0.000000
   - [x] pct_chg_raw 自算 — 未复权 close 自算
   - [x] 涨跌停标记逻辑正确 — 写入 limit_up_flag/limit_down_flag
   - [x] breadth 写入并可在验证报告看到 — 3行业 × 5190天
3. 验证通过后，再扩到全量

---

## 五、环境依赖

```bash
# 必装
pip install akshare baostock mootdx
```

**注意**：`mootdx` 依赖通达信公共行情服务器（TCP 协议，不需注册），首次运行会自动测速选最快服务器。如在内网/受限环境可能需要指定服务器 IP。

---

## 六、当前脚本状态

`backend/collectors/stock_pilot.py` 已按双源方案重写并通过 pilot 验证：

- **mootdx** 并行（5线程）→ 未复权 OHLC + vol + amount
- **baostock** 串行 + 自动重连 + socket 超时 → 后复权 close（仅 date,close 两字段，轻量）
- 合并写入 market_daily_data + breadth 计算 + 验证报告
- 实测 142 支 / 2分5秒 / 269,201行 / 0失败

直接运行：

```bash
python3 backend/collectors/stock_pilot.py
```

修改 `MAX_STOCKS_PER_SECTOR` 控制采样数量。全量采集需先通过 pilot 验证。

---

## 七、已知问题与前置条件

> ⚠️ **首次运行前必须完成以下步骤**，否则脚本会报错。

### 7.1 数据库缺少列

`market_daily_data` 表缺少 `close_hfq`、`hfq_factor` 列，需手动添加：

```sql
ALTER TABLE market_daily_data ADD COLUMN close_hfq REAL;
ALTER TABLE market_daily_data ADD COLUMN hfq_factor REAL;
```

### 7.2 Locale 影响 Pandas 日期解析

`stock_pilot.py` 顶部为 baostock 兼容设置了 `locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')`，这会改变 pandas 的日期格式推断，导致 `pd.to_datetime('2026-01-05')` 在 breadth 计算时报错：
```
ValueError: time data "2026-01-05" doesn't match format "%Y-%b-%d"
```

**已修复**：breadth 计算中的 `pd.to_datetime()` 显式指定 `format='%Y-%m-%d'`。

### 7.3 DB_PATH 路径

脚本的 `DB_PATH` 指向项目根目录的 `data/quant_engine.db`，使用 `Path(__file__).resolve().parents[2]`。如果脚本移动到不同目录层级，需相应调整。

### 7.4 异常捕获太宽

写入循环的 `except Exception: pct_fail += 1` 会吞掉所有错误，排查困难。已记录为待改进项。
