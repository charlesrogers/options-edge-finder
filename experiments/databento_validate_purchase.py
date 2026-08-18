"""
§4 validation of the purchased files.

1. Every new file loads through the same DBNStore path backtest_engine uses.
2. Missing-bar % in the 5-20% OTM / 20-60 DTE CALL region -- the region the
   strategy actually sells and buys back. This is the number that matters; the
   global missing-bar % is not.
3. Sanity: AAPL 2020 must visibly contain the March crash. A clean-looking
   March 2020 means a broken pull, not a calm market.

Spot via put-call parity from the option data itself (split-proof; AAPL split
4:1 in Aug 2020 so any split-adjusted vendor price would be meaningless here).
"""

import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import databento as db

RAW_DIR = os.path.expanduser("~/Documents/options-tool/data/databento/raw")

NEW_FILES = [
    ("AAPL", "2020 Feb-Jun (crash)", "AAPL_ohlcv_1d_2020feb_jun.dbn.zst"),
    ("DIS",  "2020 Feb-Jun (crash)", "DIS_ohlcv_1d_2020feb_jun.dbn.zst"),
    ("GOOGL","2020 Feb-Jun (crash)", "GOOGL_ohlcv_1d_2020feb_jun.dbn.zst"),
    ("TMUS", "2020 Feb-Jun (crash)", "TMUS_ohlcv_1d_2020feb_jun.dbn.zst"),
    ("KKR",  "2020 Feb-Jun (crash)", "KKR_ohlcv_1d_2020feb_jun.dbn.zst"),
    ("AAPL", "2020 Jul-Sep (meltup)","AAPL_ohlcv_1d_2020jul_sep.dbn.zst"),
    ("TMUS", "2022 full (bear)",     "TMUS_ohlcv_1d_2022.dbn.zst"),
]

OTM_BAND = (0.05, 0.20)   # spec §4.2 region
DTE_BAND = (20, 60)
STRIKE_TOL = 0.025


def parse_occ(sym):
    m = re.search(r"(\d{6})([CP])(\d{8})", str(sym).strip())
    if not m:
        return None, None, None
    try:
        return (datetime.strptime("20" + m.group(1), "%Y%m%d"),
                float(m.group(3)) / 1000, m.group(2))
    except Exception:
        return None, None, None


def load(path):
    df = db.DBNStore.from_file(path).to_df().reset_index()
    parsed = df["symbol"].apply(lambda s: pd.Series(parse_occ(s),
                                index=["expiration", "strike", "right"]))
    df = pd.concat([df, parsed], axis=1).dropna(subset=["strike", "right"])
    df["date"] = pd.to_datetime(df["ts_event"]).dt.tz_localize(None).dt.normalize()
    return (df.groupby(["date", "symbol", "expiration", "strike", "right"],
                       as_index=False)
              .agg(close=("close", "mean"), volume=("volume", "sum")))


def infer_spot(day):
    best = None
    for exp, grp in day.groupby("expiration"):
        c = grp[grp["right"] == "C"].set_index("strike")["close"]
        p = grp[grp["right"] == "P"].set_index("strike")["close"]
        common = c.index.intersection(p.index)
        if len(common) < 10:
            continue
        est = (c[common] - p[common] + common).astype(float)
        s = float(np.median(est))
        near = est[(est.index > s * 0.9) & (est.index < s * 1.1)]
        if len(near) < 5:
            continue
        if best is None or exp < best[0]:
            best = (exp, float(np.median(near)))
    return best[1] if best else None


def region_coverage(df):
    dates = sorted(df["date"].unique())
    hits = total = 0
    spots = {}
    for d in dates:
        day = df[df["date"] == d]
        spot = infer_spot(day)
        if spot is None:
            continue
        spots[d] = spot
        calls = day[day["right"] == "C"]
        for otm in np.arange(OTM_BAND[0], OTM_BAND[1] + 1e-9, 0.01):
            target_k = spot * (1 + otm)
            for dte in range(DTE_BAND[0], DTE_BAND[1] + 1, 5):
                texp = pd.Timestamp(d) + pd.Timedelta(days=dte)
                cand = calls[(calls["expiration"] >= texp - pd.Timedelta(days=5)) &
                             (calls["expiration"] <= texp + pd.Timedelta(days=5))]
                total += 1
                if cand.empty:
                    continue
                if not cand[(cand["strike"] - target_k).abs() <= spot * STRIKE_TOL].empty:
                    hits += 1
    cov = 100.0 * hits / total if total else 0.0
    return cov, 100.0 - cov, len(dates), spots


def main():
    print("=" * 78)
    print("§4 VALIDATION OF PURCHASED FILES")
    print("=" * 78)

    all_ok = True
    for ticker, label, fname in NEW_FILES:
        path = os.path.join(RAW_DIR, fname)
        print(f"\n--- {ticker} {label} ---")
        if not os.path.exists(path):
            print(f"  MISSING: {fname}")
            all_ok = False
            continue
        df = load(path)
        if df.empty:
            print("  FAIL: parsed to zero rows")
            all_ok = False
            continue
        mb = os.path.getsize(path) / 1e6
        print(f"  loaded {len(df):,} aggregated rows from {mb:.1f} MB, "
              f"{df['symbol'].nunique():,} contracts")
        cov, missing, ndays, spots = region_coverage(df)
        print(f"  trading days: {ndays}")
        if not spots:
            # Parity needs >=10 matched call/put strikes on one expiry. Thin
            # names (KKR 2020: median 4) never reach it, so spot is None every
            # day and coverage computes to 0% BY CONSTRUCTION. That is an
            # unmeasured file, not an empty one -- do not report it as 0%.
            print(f"  5-20% OTM / 20-60 DTE call region: UNMEASURED — "
                  f"put-call parity could not infer spot on any day "
                  f"(too few matched strikes). Needs a stock-price spot source.")
            all_ok = False
            continue
        print(f"  5-20% OTM / 20-60 DTE call region: "
              f"{cov:.1f}% covered, {missing:.1f}% MISSING")
        if spots:
            sv = list(spots.values())
            sd = sorted(spots.keys())
            print(f"  spot (parity): first {sd[0].date()}=${sv[0]:.2f}  "
                  f"last {sd[-1].date()}=${sv[-1]:.2f}  "
                  f"min ${min(sv):.2f}  max ${max(sv):.2f}  "
                  f"drawdown {100*(min(sv)/max(sv)-1):.1f}%")

        # AAPL split 4:1 on 2020-08-31. A file spanning it shows a fake ~-75%
        # "drawdown" and carries strikes on two different bases.
        if ticker == "AAPL" and spots:
            sd = sorted(spots.keys())
            if sd[0] <= pd.Timestamp("2020-08-31") <= sd[-1]:
                print("  *** SPLIT WARNING: this file spans AAPL's 4:1 split on "
                      "2020-08-31. Strikes before/after are on different bases; "
                      "the apparent drawdown is the split, not the market. Any "
                      "backtest crossing that date must handle it. ***")

        # Sanity: the crash must be visible in AAPL Feb-Jun 2020.
        if ticker == "AAPL" and "crash" in label and spots:
            sv = list(spots.values())
            dd = 100 * (min(sv) / max(sv) - 1)
            if dd < -20:
                print(f"  SANITY PASS: {dd:.1f}% drawdown — March 2020 is present.")
            else:
                print(f"  *** SANITY FAIL: only {dd:.1f}% drawdown. A calm-looking "
                      f"March 2020 means a broken pull. ***")
                all_ok = False

    print("\n" + "=" * 78)
    print("RESULT:", "ALL FILES VALID" if all_ok else "PROBLEMS FOUND — see above")
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
