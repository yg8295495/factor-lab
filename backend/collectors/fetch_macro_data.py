"""
补充宏观数据到 market_daily_data：10年国债收益率 + 两市融资融券余额

数据源：
  1. 中国10年期国债收益率 — akshare.bond_zh_us_rate()
  2. 沪深两市融资融券余额 — akshare.macro_china_market_margin_sh/sz()

写入方式：
  注册为新 symbol 写入 market_daily_data，close 字段存数值。
"""

import akshare as ak
import sqlite3
import time
import urllib3
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "quant_engine.db"


def log(msg: str):
    print(f"  {msg}", flush=True)


def ensure_symbol(conn, symbol, name, asset_type="macro"):
    conn.execute(
        "INSERT OR IGNORE INTO asset_master (symbol, name, asset_type, exchange, is_active) "
        "VALUES (?, ?, ?, 'CN', 1)",
        (symbol, name, asset_type),
    )
    conn.commit()


def insert_series(conn, symbol, rows):
    """批量写入 (trade_date, close) 到 market_daily_data"""
    conn.executemany(
        "INSERT OR REPLACE INTO market_daily_data "
        "(symbol, trade_date, open, high, low, close, close_hfq, hfq_factor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(symbol, d, v, v, v, v, v, 1.0) for d, v in rows if v is not None],
    )
    conn.commit()


def step1_bond_yield(conn):
    """中国10年期国债收益率"""
    log("[1/2] 中国10年期国债收益率 ...")
    t0 = time.time()

    df = ak.bond_zh_us_rate()
    df = df[["日期", "中国国债收益率10年"]].dropna()
    df["日期"] = df["日期"].astype(str)
    df["中国国债收益率10年"] = df["中国国债收益率10年"].astype(float)

    SYMBOL = "macro.CN10Y"
    ensure_symbol(conn, SYMBOL, "中国10年期国债收益率")
    insert_series(conn, SYMBOL, df.values.tolist())

    cnt = conn.execute(
        "SELECT COUNT(*) FROM market_daily_data WHERE symbol=?", (SYMBOL,)
    ).fetchone()[0]
    dr = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data WHERE symbol=?",
        (SYMBOL,),
    ).fetchone()
    log(f"  写入 {cnt} 行, {dr[0]} ~ {dr[1]} ({time.time()-t0:.1f}s)")


def step2_margin_balance(conn):
    """沪深两市融资融券余额（合并）"""
    log("[2/2] 两市融资融券余额 ...")
    t0 = time.time()

    df_sh = ak.macro_china_market_margin_sh()
    df_sz = ak.macro_china_market_margin_sz()

    # 两市合并
    df_sh = df_sh[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "sh"})
    df_sz = df_sz[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "sz"})
    df_sh["日期"] = df_sh["日期"].astype(str)
    df_sz["日期"] = df_sz["日期"].astype(str)

    merged = df_sh.merge(df_sz, on="日期", how="outer")
    merged["total"] = merged["sh"].fillna(0).astype(float) + merged["sz"].fillna(0).astype(float)
    merged = merged.dropna(subset=["total"])
    merged = merged[merged["total"] > 0]

    SYMBOL = "macro.MARGIN_TOTAL"
    ensure_symbol(conn, SYMBOL, "两市融资融券余额合计")
    insert_series(conn, SYMBOL, merged[["日期", "total"]].values.tolist())

    cnt = conn.execute(
        "SELECT COUNT(*) FROM market_daily_data WHERE symbol=?", (SYMBOL,)
    ).fetchone()[0]
    dr = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data WHERE symbol=?",
        (SYMBOL,),
    ).fetchone()
    # 显示一下数值量级
    sample = conn.execute(
        "SELECT trade_date, close FROM market_daily_data WHERE symbol=? ORDER BY trade_date DESC LIMIT 3",
        (SYMBOL,),
    ).fetchall()
    for r in sample:
        log(f"    {r[0]}  {r[1]:.0f} (亿元)")
    log(f"  写入 {cnt} 行, {dr[0]} ~ {dr[1]} ({time.time()-t0:.1f}s)")


def verify(conn):
    log("\n" + "=" * 40)
    log("验证宏观数据")
    log("=" * 40)
    for sym, name in [("macro.CN10Y", "10Y国债收益率"), ("macro.MARGIN_TOTAL", "两融余额合计")]:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM market_daily_data WHERE symbol=?", (sym,)
        ).fetchone()[0]
        dr = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data WHERE symbol=?",
            (sym,),
        ).fetchone()
        val = conn.execute(
            "SELECT trade_date, close FROM market_daily_data WHERE symbol=? AND close IS NOT NULL ORDER BY trade_date DESC LIMIT 1",
            (sym,),
        ).fetchone()
        latest = f"{val[0]}={val[1]}" if val else "N/A"
        log(f"  {name:15s}: {cnt}行, {dr[0]}~{dr[1]}, 最新={latest}")


def main():
    t_start = time.time()
    print("=" * 45)
    print("补充宏观数据")
    print("=" * 45)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    try:
        step1_bond_yield(conn)
        step2_margin_balance(conn)
        verify(conn)
    finally:
        conn.close()

    print(f"\n完成 ({time.time()-t_start:.1f}s)")


if __name__ == "__main__":
    main()
