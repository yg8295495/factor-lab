"""
Phase 1: Build stock-to-sector mapping for all 30 Shenwan (申万) primary industries.

Uses akshare's sw_index_first_info() + index_component_sw() to fetch constituent
stock codes per industry, then writes the mapping into asset_master.stable_industry.

Usage:
    python backend/collectors/build_sector_mapping.py

Output:
    - Updates asset_master.stable_industry for matching stock rows
    - Prints coverage report
"""

import sqlite3
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import akshare as ak
import pandas as pd

DB_PATH = "data/quant_engine.db"

# Exchange mapping for A-share stock codes
def _determine_exchange(ticker: str) -> str:
    """Determine exchange based on stock ticker prefix."""
    ticker = ticker.strip()
    if ticker.startswith("6"):
        return "SH"
    elif ticker.startswith(("0", "3")):
        return "SZ"
    elif ticker.startswith(("4", "8")):
        return "BJ"
    else:
        return None


def fetch_industry_list() -> pd.DataFrame:
    """Fetch all primary SW industry codes and names."""
    df = ak.sw_index_first_info()
    # Columns: 行业代码, 行业名称, 股份个数, 静态市盈率, TTM(滚动)市盈率, 市净率, 静态股息率
    df = df.rename(columns={
        df.columns[0]: "industry_code",
        df.columns[1]: "industry_name",
    })
    # The code format from akshare is like '801010.SI' — strip '.SI' for index_component_sw
    df["code_num"] = df["industry_code"].str.replace(r"\.SI$", "", regex=True)
    return df


def fetch_constituents(code_num: str, max_retries: int = 3) -> pd.DataFrame:
    """Fetch constituent stocks for one SW industry."""
    for attempt in range(max_retries):
        try:
            df = ak.index_component_sw(symbol=code_num)
            # Columns: 排名, 证券代码, 证券名称, 调入权重, 调入日期
            df = df.rename(columns={
                df.columns[1]: "ticker",
                df.columns[2]: "stock_name",
            })
            df["ticker"] = df["ticker"].astype(str).str.strip()
            return df
        except Exception as e:
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
            else:
                print(f"    [WARN] Failed after {max_retries} retries: {e}")
                return pd.DataFrame()


def build_mapping():
    """Main: fetch industry list, fetch constituents for each, write to DB."""
    print("=" * 60)
    print("Phase 1: Build Stock-to-Sector Mapping")
    print("=" * 60)

    # Step 1: fetch industry list
    print("\n[1/3] Fetching SW industry list...")
    industries = fetch_industry_list()
    print(f"  Found {len(industries)} primary industries")

    # Step 2: fetch constituents per industry
    print("\n[2/3] Fetching constituent stocks per industry...")
    all_mappings = []  # list of (ticker, industry_name, industry_code)

    for _, row in industries.iterrows():
        code_num = row["code_num"]
        name = row["industry_name"]
        print(f"  {code_num}  {name}...", end=" ", flush=True)

        constituents = fetch_constituents(code_num)
        if constituents.empty:
            print("SKIPPED (empty)")
            continue

        for ticker in constituents["ticker"]:
            all_mappings.append((ticker, name, code_num))
        print(f"{len(constituents)} stocks")

    print(f"\n  Total mappings collected: {len(all_mappings)}")

    # Step 3: write to database
    print("\n[3/3] Writing to asset_master.stable_industry...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Build ticker -> (industry_name, industry_code) lookup
    mapping_dict = {}
    for ticker, ind_name, ind_code in all_mappings:
        ticker = ticker.strip()
        if ticker not in mapping_dict:
            mapping_dict[ticker] = (ind_name, ind_code)
        # If a stock appears in multiple sectors (unlikely for primary), keep first

    # Get all existing stock symbols from asset_master
    cursor.execute(
        "SELECT symbol, name FROM asset_master WHERE asset_type = 'stock'"
    )
    stock_rows = cursor.fetchall()
    print(f"  Database has {len(stock_rows)} stock rows")

    updated = 0
    not_found = 0
    conflict_skip = 0

    for symbol, stock_name in stock_rows:
        # Extract ticker from symbol like 'stock.000001.SZ' -> '000001'
        parts = symbol.split(".")
        if len(parts) != 3:
            continue
        ticker = parts[1]

        if ticker in mapping_dict:
            industry_name, industry_code = mapping_dict[ticker]
            # Check if already set to a different industry (conflict)
            cursor.execute(
                "SELECT stable_industry FROM asset_master WHERE symbol = ?",
                (symbol,),
            )
            current = cursor.fetchone()[0]
            if current and current != industry_name:
                conflict_skip += 1
                continue
            cursor.execute(
                "UPDATE asset_master SET stable_industry = ? WHERE symbol = ?",
                (industry_name, symbol),
            )
            updated += 1
        else:
            not_found += 1

    conn.commit()
    conn.close()

    print(f"\n  Results:")
    print(f"    Updated:           {updated}")
    print(f"    Conflict skip:       {conflict_skip}")
    print(f"    Not found in SW:   {not_found}")

    # Final coverage report
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM asset_master WHERE asset_type = 'stock' "
        "AND stable_industry IS NOT NULL AND stable_industry != ''"
    )
    covered = cursor.fetchone()[0]
    total = len(stock_rows)
    print(f"\n  Final coverage: {covered} / {total} ({covered/total*100:.1f}%)")

    # Count by industry
    cursor.execute(
        "SELECT stable_industry, COUNT(*) FROM asset_master "
        "WHERE asset_type = 'stock' AND stable_industry IS NOT NULL "
        "AND stable_industry != '' "
        "GROUP BY stable_industry ORDER BY COUNT(*) DESC"
    )
    print("\n  Coverage by industry:")
    for ind_name, cnt in cursor.fetchall():
        print(f"    {ind_name}: {cnt}")
    conn.close()


if __name__ == "__main__":
    build_mapping()
