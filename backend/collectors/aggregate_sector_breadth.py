"""
Phase 4: Aggregate sector internal breadth for all 30 Shenwan sectors.

Per sector per trading day, computes from constituent stocks:
    above_ma20_ratio   = % of stocks with close_hfq > SMA(close_hfq, 20)
    above_ma60_ratio   = % of stocks with close_hfq > SMA(close_hfq, 60)
    new_high_20d_ratio = % of stocks at 20d high (close_hfq)
    rs_positive_ratio  = % of stocks with rs20_cross > 0 (if available)

Method: process one sector at a time.

Usage:
    python backend/collectors/aggregate_sector_breadth.py
"""

import sqlite3
import sys
import os
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

DB_PATH = "data/quant_engine.db"


def compute_breadth(stock_symbols, cursor):
    """
    Compute per-date breadth metrics for a group of stocks.
    Returns list of (trade_date, ma20_r, ma60_r, nh_r, rs_r).
    """
    ph = ",".join("?" * len(stock_symbols))
    cursor.execute(
        f"SELECT symbol, trade_date, close_hfq, rs20_cross "
        f"FROM market_daily_data "
        f"WHERE symbol IN ({ph}) AND close_hfq IS NOT NULL "
        f"ORDER BY symbol, trade_date",
        stock_symbols,
    )
    rows = cursor.fetchall()
    if not rows:
        return None

    # Group by symbol
    sym_data = defaultdict(list)
    for sym, dt, hfq, rs20 in rows:
        sym_data[sym].append((dt, hfq, rs20))

    # Accumulate per-date counts
    date_counts = defaultdict(lambda: {"n": 0, "ma20": 0, "ma60": 0, "nh": 0, "rs_pos": 0, "rs_n": 0})

    for sym, data in sym_data.items():
        hfqs = [d[1] for d in data]
        for i, (dt, hfq, rs20) in enumerate(data):
            cc = date_counts[dt]
            cc["n"] += 1

            # MA20
            if i >= 19:
                ma20 = sum(hfqs[i-19:i+1]) / 20.0
                if hfq > ma20:
                    cc["ma20"] += 1

            # MA60
            if i >= 59:
                ma60 = sum(hfqs[i-59:i+1]) / 60.0
                if hfq > ma60:
                    cc["ma60"] += 1

            # New 20d high
            window = hfqs[max(0, i-19):i+1]
            if hfq == max(window):
                cc["nh"] += 1

            # RS20 positive
            if rs20 is not None:
                cc["rs_n"] += 1
                if rs20 > 0:
                    cc["rs_pos"] += 1

    result = []
    for dt in sorted(date_counts.keys()):
        cc = date_counts[dt]
        n = cc["n"]
        result.append((
            dt,
            round(cc["ma20"] / n, 4) if n > 0 else None,
            round(cc["ma60"] / n, 4) if n > 0 else None,
            round(cc["nh"] / n, 4) if n > 0 else None,
            round(cc["rs_pos"] / cc["rs_n"], 4) if cc["rs_n"] > 0 else None,
        ))
    return result


def main():
    print("=" * 60)
    print("Phase 4: Aggregate Sector Internal Breadth (30 sectors)")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    cursor = conn.cursor()

    # Get all sectors
    cursor.execute("SELECT symbol, name FROM asset_master WHERE asset_type='sector' ORDER BY symbol")
    sectors = cursor.fetchall()
    print(f"\nSectors: {len(sectors)}")

    # Check mapping
    cursor.execute(
        "SELECT COUNT(DISTINCT stable_industry) FROM asset_master "
        "WHERE asset_type='stock' AND stable_industry IS NOT NULL"
    )
    ind_count = cursor.fetchone()[0]
    print(f"Industries with stock mapping: {ind_count}")
    print(f"\nProcessing sectors...\n")

    total_updated, t0 = 0, time.time()

    for sym, name in sectors:
        st = time.time()
        # Find stocks in this sector
        cursor.execute(
            "SELECT symbol FROM asset_master WHERE asset_type='stock' AND stable_industry=?",
            (name,),
        )
        stocks = [r[0] for r in cursor.fetchall()]
        if not stocks:
            print(f"  [{sym}] {name}: 0 stocks — SKIP")
            continue

        # Compute
        result = compute_breadth(stocks, cursor)
        if not result:
            print(f"  [{sym}] {name}: {len(stocks)} stocks, 0 dates — SKIP")
            continue

        # Update
        cursor.executemany(
            "UPDATE market_daily_data SET above_ma20_ratio=?, above_ma60_ratio=?, "
            "new_high_20d_ratio=?, rs_positive_ratio=? "
            "WHERE symbol=? AND trade_date=?",
            [(r[1], r[2], r[3], r[4], sym, r[0]) for r in result],
        )
        conn.commit()
        total_updated += len(result)
        print(f"  [{sym}] {name}: {len(stocks)} stocks, {len(result)} dates ({time.time()-st:.1f}s)")

    t1 = time.time()
    print(f"\nTotal: {total_updated} sector-date rows in {t1-t0:.1f}s")

    # Verify
    for f in ['above_ma20_ratio', 'above_ma60_ratio', 'new_high_20d_ratio', 'rs_positive_ratio']:
        cnt = cursor.execute(
            f"SELECT COUNT(DISTINCT symbol) FROM market_daily_data "
            f"WHERE symbol LIKE 'sector.%' AND {f} IS NOT NULL"
        ).fetchone()[0]
        print(f"  Sectors with {f}: {cnt}/{len(sectors)}")

    conn.close()


if __name__ == "__main__":
    main()
