# 数据源方案备案：mootdx + baostock（A方案）

## 适用场景
TickFlow 主方案不可用时（接口下线、限速过严、IP被封等）的降级备选。

## 方案简介
- **未复权 OHLC + volume/amount** — mootdx 并行采集（ThreadPoolExecutor 5线程）
- **后复权 close** — baostock `adjustflag=1` 串行采集
- **hfq_factor** — 本地计算 `close_hfq / close`
- **pct_chg_raw** — 本地计算 `(close[t] - close[t-1]) / close[t-1] * 100`
- **涨跌停判定** — 基于 pct_chg_raw 阈值

## 实测速度

| 阶段 | 单只耗时 | 5000只预估 |
|------|---------|-----------|
| mootdx 未复权 | ~0.26s/只（并行5线程，3.8只/秒） | ~22分 |
| baostock 后复权 | ~0.50s/只（串行，80次需重连） | ~42分 |
| 合并+写入 | — | ~5分 |
| **总计** | | **~69分钟** |

## 已知坑

### mootdx
1. **Quotes 客户端需每次新建**（`client = Quotes()`) — 不能复用，否则线程不安全。pilot 已验证
2. **volume/amount 单位**：mootdx 的 volume 单位是**手**，与 baostock 一致
3. **停牌日无数据返回** — close 为 None，pct_chg_raw 也为 None
4. **AH股代码**：仅支持沪深 A 股，不支持港股

### baostock
1. **80次/连接限制**：服务端 ~100 次后静默掐断，实测 80 次必须重连（`_BS_MAX_QUERIES=80`）
2. **全串行**：baostock 登录是进程级单例，不支持多线程
3. **重连逻辑**：`bs.logout()` → sleep(0.3) → `bs.login()`，需 threading.Lock 保护
4. **socket 超时**：需 `socket.setdefaulttimeout(25)` 在 login 前设置
5. **locale 依赖**：baostock 内部依赖中文 locale，需在 import 前设置（macOS 常见问题）
6. **只拉 `date,close` 两个字段** — `adjustflag=1` 模式下
7. **20%+ 的股票 baostock 可能缺失** — 已有 pilot 验证 142/142 全部成功

### 数据库写入
1. `INSERT OR REPLACE` 以 symbol + trade_date 为唯一键
2. WAL 模式 + synchronous=OFF 加速写入
3. 先插入 asset_master，再写 market_daily_data

## Pilot 脚本参考
`backend/collectors/stock_pilot.py` — 覆盖了 3 行业 142 只个股，可直接改参数扩展。
