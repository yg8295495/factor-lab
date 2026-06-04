"""
Phase 2: Compute pct_chg_raw, limit_up_flag, limit_down_flag for stock rows.
"""

import sqlite3, sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

DB_PATH = "data/quant_engine.db"
CHUNK_SIZE = 100


def main():
    print("=" * 60)
    print("Phase 2: Compute pct_chg_raw / limit_up / limit_down for stocks")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    cursor = conn.cursor()

    # Get all stock symbols
    cursor.execute("""
        SELECT DISTINCT m.symbol FROM market_daily_data m
        JOIN asset_master a ON m.symbol = a.symbol
        WHERE a.asset_type='stock' AND m.close IS NOT NULL
    """)
    symbols = [r[0] for r in cursor.fetchall()]
    total = len(symbols)
    print(f"\nStock symbols: {total}")

    total_rows = 0
    t0 = time.time()

    for start in range(0, total, CHUNK_SIZE):
        chunk = symbols[start : start + CHUNK_SIZE]
        ph = ",".join("?" * len(chunk))

        cursor.execute(
            f"SELECT symbol, trade_date, close FROM market_daily_data "
            f"WHERE symbol IN ({ph}) AND close IS NOT NULL ORDER BY symbol, trade_date",
            chunk,
        )
        rows = cursor.fetchall()

        updates = []
        prev_sym = None
        prev_close = None
        for symbol, trade_date, close in rows:
            if symbol != prev_sym:
                prev_sym = symbol
                prev_close = close
                continue
            if prev_close is not None and prev_close != 0 and close is not None:
                pct = (close - prev_close) / abs(prev_close) * 100.0
                lu = 1 if pct >= 9.8 else 0
                ld = 1 if pct <= -9.8 else 0
                updates.append((round(pct, 4), lu, ld, symbol, trade_date))
            prev_close = close

        if updates:
            cursor.executemany(
                "UPDATE market_daily_data SET pct_chg_raw=?, limit_up_flag=?, limit_down_flag=? "
                "WHERE symbol=? AND trade_date=?",
                updates,
            )
            total_rows += len(updates)
        conn.commit()

        elapsed = time.time() - t0
        done = min(start + CHUNK_SIZE, total)
        print(f"  [{done}/{total}] {total_rows} rows  ({elapsed:.1f}s)")

    elapsed = time.time() - t0
    print(f"\nDone: {total_rows} rows in {elapsed:.1f}s")

    # Verification
    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM market_daily_data WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL")
    sym_cov = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'stock.%' AND pct_chg_raw IS NOT NULL")
    row_cov = cursor.fetchone()[0]
    tot = cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'stock.%'").fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'stock.%' AND limit_up_flag=1")
    lu = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM market_daily_data WHERE symbol LIKE 'stock.%' AND limit_down_flag=1")
    ld = cursor.fetchone()[0]

    print(f"\nSymbols covered: {sym_cov} / {total}")
    print(f"Rows covered: {row_cov:,} / {tot:,} ({row_cov/tot*100:.1f}%)")
    print(f"Limit-up: {lu:,}  Limit-down: {ld:,}")
    conn.close()


if __name__ == "__main__":
    main()
