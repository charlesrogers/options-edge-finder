"""
Price the two scopes Charles specified, then pick the package. FREE — $0 spent.

  (a) all 5 tradeable tickers, 2020-02-01 -> 2020-09-30  (crash AND melt-up)
  (b) AAPL only,              2020-07-01 -> 2020-09-30  (melt-up extension alone)

Preference order (Charles, 2026-08-17):
  1. If (a) <= $86: (a) + TMUS 2022 full year
  2. Else:          $55.77 crash window + (b) + TMUS 2022
  3. Else:          $55.77 crash window + TMUS 2022

Key is read from ~/.config/databento/key (never echoed, never a CLI arg).
"""

import os
import sys

import databento as db

DATASET = "OPRA.PILLAR"
SCHEMA = "ohlcv-1d"
STYPE = "parent"
TRADEABLE = ["AAPL", "DIS", "TMUS", "KKR", "GOOGL"]

SPENT_SO_FAR = 1.32          # coverage probe, already posted
ASSUMED_BALANCE = 125.00
FLOOR = 25.00


def load_key():
    p = os.path.expanduser("~/.config/databento/key")
    if os.path.exists(p):
        with open(p) as f:
            return f.read().strip()
    return os.environ.get("DATABENTO_API_KEY")


def cost(client, symbols, start, end):
    syms = [f"{s}.OPT" for s in symbols]
    usd = client.metadata.get_cost(dataset=DATASET, symbols=syms, schema=SCHEMA,
                                   start=start, end=end, stype_in=STYPE)
    try:
        rows = client.metadata.get_record_count(dataset=DATASET, symbols=syms,
                                                schema=SCHEMA, start=start,
                                                end=end, stype_in=STYPE)
    except Exception:
        rows = None
    return usd, rows


def main():
    key = load_key()
    if not key:
        print("ERROR: no key at ~/.config/databento/key")
        return 1
    client = db.Historical(key)

    headroom = ASSUMED_BALANCE - SPENT_SO_FAR - FLOOR
    print("=" * 72)
    print("PACKAGE PRICING — free metadata only, $0 spent")
    print(f"  assumed balance ${ASSUMED_BALANCE:.2f} | spent ${SPENT_SO_FAR:.2f} "
          f"| floor ${FLOOR:.2f} | HEADROOM ${headroom:.2f}")
    print("=" * 72)

    print("\n(a) all 5 tickers, 2020-02-01 -> 2020-09-30")
    a_total = 0.0
    for t in TRADEABLE:
        usd, rows = cost(client, [t], "2020-02-01", "2020-09-30")
        a_total += usd
        print(f"      {t:<6} ${usd:>7.2f}  {rows:>12,}" if rows else
              f"      {t:<6} ${usd:>7.2f}")
    print(f"      {'TOTAL':<6} ${a_total:>7.2f}")

    print("\n(b) AAPL only, 2020-07-01 -> 2020-09-30")
    b_total, b_rows = cost(client, ["AAPL"], "2020-07-01", "2020-09-30")
    print(f"      AAPL   ${b_total:>7.2f}  {b_rows:>12,}" if b_rows else
          f"      AAPL   ${b_total:>7.2f}")

    print("\n(c) crash window, all 5, 2020-02-01 -> 2020-06-30  [re-quote]")
    c_total = 0.0
    for t in TRADEABLE:
        usd, _ = cost(client, [t], "2020-02-01", "2020-06-30")
        c_total += usd
    print(f"      TOTAL  ${c_total:>7.2f}")

    print("\n(d) TMUS 2022 full year  [non-negotiable in every package]")
    d_total, d_rows = cost(client, ["TMUS"], "2022-01-01", "2022-12-31")
    print(f"      TMUS   ${d_total:>7.2f}  {d_rows:>12,}" if d_rows else
          f"      TMUS   ${d_total:>7.2f}")

    print("\n" + "=" * 72)
    print("PACKAGE SELECTION")
    print("=" * 72)
    if a_total <= 86.0:
        pkg, label = a_total + d_total, "1: (a) Feb-Sep all-5 + TMUS 2022"
    elif c_total + b_total + d_total <= headroom:
        pkg, label = c_total + b_total + d_total, "2: crash-window + (b) + TMUS 2022"
    else:
        pkg, label = c_total + d_total, "3: crash-window + TMUS 2022"
    print(f"  SELECTED -> package {label}")
    print(f"  estimated total: ${pkg:.2f}   headroom: ${headroom:.2f}")
    if pkg > headroom:
        print(f"  *** BREACHES FLOOR by ${pkg - headroom:.2f} — do not execute as-is ***")
    else:
        print(f"  ending balance if executed: ${ASSUMED_BALANCE - SPENT_SO_FAR - pkg:.2f}")
    print("\nNothing purchased. Quotes only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
