"""
Phase 3: Aggregate market emotion fields onto index.000985.SH (中证全指).

Computes from stock pct_chg_raw and limit_up/down_flag:
    adv_count       = COUNT(stocks with pct_chg_raw > 0)
    decl_count      = COUNT(stocks with pct_chg_raw < 0)
    market_adv_ratio = adv_count / (adv_count + decl_count)  — only when both > 0
    limit_up_count   = COUNT(stocks with limit_up_flag = 1)
    limit_down_count = COUNT(stocks with limit_down_flag = 1)

Updates existing rows in market_daily_data for index.000985.SH.

Usage:
    python backend/collectors/aggregate_market_emotion.py
"""

import sqlite3
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

DB_PATH = "data/quant_engine.db"


def main():
    print("=" * 60)
    print("Phase 3: Aggregate Market Emotion onto index.000985.SH")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    cursor = conn.cursor()

    # Step 1: Ensure pct_chg_raw is computed first
    cursor.execute("""
        SELECT COUNT(DISTINCT symbol) FROM market_daily_data
        WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL
    """)
    stock_with_pct = cursor.fetchone()[0]
    cursor.execute("""
        SELECT COUNT(DISTINCT symbol) FROM market_daily_data WHERE symbol LIKE 'stock.%'
    """)
    total_stocks = cursor.fetchone()[0]
    print(f"\nStock symbols with pct_chg_raw: {stock_with_pct} / {total_stocks}")

    # Step 2: Aggregate per trading day using SQL
    print("\n[1/2] Aggregating daily market emotion from stock data...")
    t0 = time.time()

    cursor.execute("""
        CREATE TEMP TABLE market_emotion AS
        SELECT
            trade_date,
            SUM(CASE WHEN pct_chg_raw > 0 THEN 1 ELSE 0 END) AS adv_count,
            SUM(CASE WHEN pct_chg_raw < 0 THEN 1 ELSE 0 END) AS decl_count,
            SUM(CASE WHEN limit_up_flag = 1 THEN 1 ELSE 0 END) AS limit_up_count,
            SUM(CASE WHEN limit_down_flag = 1 THEN 1 ELSE 0 END) AS limit_down_count
        FROM market_daily_data
        WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL
        GROUP BY trade_date
        ORDER BY trade_date
    """)
    conn.commit()

    temp_rows = cursor.execute("SELECT COUNT(*) FROM market_emotion").fetchone()[0]
    t1 = time.time()
    print(f"  Temp table: {temp_rows} trading days in {t1-t0:.1f}s")

    # Step 3: Update market_daily_data for index.000985.SH
    print("\n[2/2] Writing to index.000985.SH rows...")
    cursor.execute("""
        UPDATE market_daily_data
        SET adv_count = e.adv_count,
            decl_count = e.decl_count,
            market_adv_ratio = ROUND(
                CASE WHEN (e.adv_count + e.decl_count) > 0
                THEN e.adv_count * 1.0 / (e.adv_count + e.decl_count)
                ELSE NULL END, 4
            ),
            limit_up_count = e.limit_up_count,
            limit_down_count = e.limit_down_count
        FROM market_emotion AS e
        WHERE market_daily_data.symbol = 'index.000985.SH'
          AND market_daily_data.trade_date = e.trade_date
    """)
    conn.commit()
    t2 = time.time()
    print(f"  Updated {cursor.rowcount} rows in {t2-t1:.1f}s")

    # Verify
    cursor.execute("""
        SELECT COUNT(*) FROM market_daily_data
        WHERE symbol='index.000985.SH' AND adv_count IS NOT NULL
    """)
    verified = cursor.fetchone()[0]
    total_985 = cursor.execute(
        "SELECT COUNT(*) FROM market_daily_data WHERE symbol='index.000985.SH'"
    ).fetchone()[0]
    print(f"\nCoverage: {verified} / {total_985} rows on index.000985.SH")

    # Show date range
    cursor.execute("""
        SELECT MIN(trade_date), MAX(trade_date) FROM market_daily_data
        WHERE symbol='index.000985.SH' AND adv_count IS NOT NULL
    """)
    dr = cursor.fetchone()
    print(f"Date range: {dr[0]} ~ {dr[1]}")
    print(f"Total time: {t2-t0:.1f}s")

    conn.close()


if __name__ == "__main__":
    main()
