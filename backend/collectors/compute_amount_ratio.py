"""
Phase 5: Write amount_ratio (amount / SMA20(amount)) to sector + benchmark rows.

amount_ratio is an existing schema field. This computes it for all 30 sector rows
and index.000985.SH, using the same amount / SMA20(amount) formula.

Usage:
    python backend/collectors/compute_amount_ratio.py
"""

import sqlite3
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

DB_PATH = "data/quant_engine.db"


def compute_sma(values, window=20):
    """Simple moving average, returns list aligned to input."""
    result = []
    running = 0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            result.append(running / window)
        else:
            result.append(None)
    return result


def write_amount_ratio_for_symbol(cursor, symbol):
    """Compute and write amount_ratio for one symbol."""
    cursor.execute(
        "SELECT trade_date, amount FROM market_daily_data "
        "WHERE symbol = ? AND amount IS NOT NULL AND amount > 0 "
        "ORDER BY trade_date",
        (symbol,),
    )
    rows = cursor.fetchall()
    if len(rows) < 20:
        return 0

    dates = [r[0] for r in rows]
    amounts = [r[1] for r in rows]
    sma20 = compute_sma(amounts, 20)

    updates = []
    for i, dt in enumerate(dates):
        if sma20[i] is not None and sma20[i] > 0:
            ratio = round(amounts[i] / sma20[i], 4)
            updates.append((ratio, symbol, dt))

    if not updates:
        return 0

    cursor.executemany(
        "UPDATE market_daily_data SET amount_ratio = ? WHERE symbol = ? AND trade_date = ?",
        updates,
    )
    return len(updates)


def main():
    print("=" * 60)
    print("Phase 5: Write amount_ratio (amount / SMA20)")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    cursor = conn.cursor()

    # Targets: all 30 sectors + benchmark
    cursor.execute(
        "SELECT symbol, name FROM asset_master WHERE asset_type = 'sector' ORDER BY symbol"
    )
    sectors = [(r[0], r[1]) for r in cursor.fetchall()]

    targets = sectors + [("index.000985.SH", "中证全指")]
    print(f"\nTargets: {len(targets)} symbols ({len(sectors)} sectors + benchmark)")

    total_rows = 0
    t0 = time.time()

    for sym, name in targets:
        st = time.time()
        n = write_amount_ratio_for_symbol(cursor, sym)
        total_rows += n
        conn.commit()
        print(f"  [{sym}] {name}: {n} rows ({time.time()-st:.1f}s)")

    elapsed = time.time() - t0
    print(f"\nDone: {total_rows} total rows in {elapsed:.1f}s")

    # Verification
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'sector.%' AND amount_ratio IS NOT NULL")
    sec_covered = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'sector.%'")
    sec_total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol='index.000985.SH' AND amount_ratio IS NOT NULL")
    bm_covered = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol='index.000985.SH'")
    bm_total = cursor.fetchone()[0]

    print(f"\n  Sectors:    {sec_covered}/{sec_total} rows")
    print(f"  Benchmark:  {bm_covered}/{bm_total} rows")

    conn.close()


if __name__ == "__main__":
    main()
