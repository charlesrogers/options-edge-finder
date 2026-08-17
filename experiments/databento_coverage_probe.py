"""
COVERAGE PROBE — the $79/$144 purchase gate.

Question this answers: in the 2020 crash, do the CALL strikes the covered-call
strategy actually sells (+7% to +15% above spot, 20-60 DTE) have OHLCV bars in
Databento's trade-based OPRA data? A strike that never traded has no bar, so a
stress backtest built on gappy data would silently invent its own reality.

Two metrics, both computed for 2020 (probe pull) and for 2025 (data already on
disk, which produced the backtests we currently trust):

  1. ENTRY COVERAGE  — on each trading day, does a call exist within tolerance
     of the target strike at each target DTE? If not, no trade can be opened.
  2. REPRICE COVERAGE — for a contract that did trade on day D, does it also
     have a bar on D+1, D+2, ...? This is the one that matters: buyback cost
     during an IV explosion is the whole reason for the purchase, and it is
     measured on the repricing bars, not the entry bar.

PASS BAR (derived, not invented): 2020 coverage must be no worse than the SAME
metric measured on AAPL 2025, the data every shipped backtest already runs on.
Formally: coverage_2020 >= coverage_2025 - 10pp on both metrics.
Rationale for the 10pp slack: it is an explicit tolerance for the fact that the
probe is 5 days vs 251, so its sampling error is large. It is a judgment call,
not a computed value, and is labelled as such.

Spot is inferred from put-call parity on the option data itself, NOT from
yfinance -- yfinance prices are split-adjusted and AAPL split 4:1 in Aug 2020,
so a yfinance 'spot' of ~$65 would be compared against pre-split strikes of
~$260 and every coverage number would be garbage.

Run:  python3 experiments/databento_coverage_probe.py            (pull + analyse)
      python3 experiments/databento_coverage_probe.py --no-pull  (analyse only)

COST: ~$1.32 on the first run. Re-runs read the cached file and cost nothing.
"""

import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import databento as db


DATASET = "OPRA.PILLAR"
SCHEMA = "ohlcv-1d"

# Canonical store -- the same directory the original $122 purchase lives in.
CANONICAL_RAW = os.path.expanduser(
    "~/Documents/options-tool/data/databento/raw"
)

PROBE_TICKER = "AAPL"
PROBE_START = "2020-03-16"
PROBE_END = "2020-03-20"
PROBE_FILE = "AAPL_ohlcv_1d_2020probe.dbn.zst"

# What the strategy actually sells (ticker_strategies.py): 7%-15% OTM calls,
# 20-60 DTE. We probe the full band so the answer covers every configured ticker.
OTM_BAND = (0.07, 0.15)
DTE_BAND = (20, 60)
# A target strike counts as covered if a listed strike sits within this much of
# it, as a fraction of spot. Strike grids are ~$5 on a ~$250 stock = 2%.
STRIKE_TOL = 0.025


def load_key():
    key = os.environ.get("DATABENTO_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("DATABENTO_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


def parse_occ(sym):
    """OCC symbol -> (expiration, strike, right) or (None, None, None)."""
    m = re.search(r"(\d{6})([CP])(\d{8})", str(sym).strip())
    if not m:
        return None, None, None
    try:
        exp = datetime.strptime("20" + m.group(1), "%Y%m%d")
        return exp, float(m.group(3)) / 1000, m.group(2)
    except Exception:
        return None, None, None


def pull_probe():
    """Pull the probe window and save it to the canonical store. COSTS ~$1.32."""
    os.makedirs(CANONICAL_RAW, exist_ok=True)
    dest = os.path.join(CANONICAL_RAW, PROBE_FILE)
    if os.path.exists(dest):
        print(f"  probe file already present, skipping pull: {dest}")
        return dest

    key = load_key()
    if not key:
        print("ERROR: no DATABENTO_API_KEY")
        return None
    client = db.Historical(key)

    cost = client.metadata.get_cost(
        dataset=DATASET, symbols=[f"{PROBE_TICKER}.OPT"], schema=SCHEMA,
        start=PROBE_START, end=PROBE_END, stype_in="parent",
    )
    print(f"  quoted cost: ${cost:.4f}")
    if cost > 3.00:
        print(f"  ABORT: quote ${cost:.2f} exceeds the $3.00 probe ceiling.")
        return None

    print(f"  pulling {PROBE_TICKER} {PROBE_START} -> {PROBE_END} ...")
    data = client.timeseries.get_range(
        dataset=DATASET, symbols=[f"{PROBE_TICKER}.OPT"], schema=SCHEMA,
        start=PROBE_START, end=PROBE_END, stype_in="parent",
    )
    data.to_file(dest)
    size_mb = os.path.getsize(dest) / 1e6
    print(f"  saved {size_mb:.1f} MB -> {dest}")
    return dest


def load_dbn(path):
    df = db.DBNStore.from_file(path).to_df()
    if df.empty:
        return df
    df = df.reset_index()
    parsed = df["symbol"].apply(lambda s: pd.Series(parse_occ(s),
                                index=["expiration", "strike", "right"]))
    df = pd.concat([df, parsed], axis=1)
    df = df.dropna(subset=["strike", "right"])
    df["date"] = pd.to_datetime(df["ts_event"]).dt.tz_localize(None).dt.normalize()
    # Aggregate across exchanges -- OPRA reports the same contract many times.
    df = (df.groupby(["date", "symbol", "expiration", "strike", "right"], as_index=False)
            .agg(close=("close", "mean"), volume=("volume", "sum")))
    return df


def infer_spot(day_df):
    """Spot via put-call parity: S = C - P + K, median over ATM-ish strikes.

    Split-proof and vendor-independent. Returns None if the day has too few
    matched call/put pairs to be trustworthy.
    """
    # Use the nearest expiry that has a decent number of matched pairs.
    best = None
    for exp, grp in day_df.groupby("expiration"):
        calls = grp[grp["right"] == "C"].set_index("strike")["close"]
        puts = grp[grp["right"] == "P"].set_index("strike")["close"]
        common = calls.index.intersection(puts.index)
        if len(common) < 10:
            continue
        est = (calls[common] - puts[common] + common).astype(float)
        # Parity is tightest near the money; trim the tails.
        s = float(np.median(est))
        near = est[(est.index > s * 0.9) & (est.index < s * 1.1)]
        if len(near) < 5:
            continue
        cand = float(np.median(near))
        if best is None or exp < best[0]:
            best = (exp, cand)
    return best[1] if best else None


def analyse(df, label):
    """Compute entry + reprice coverage for the call strikes we actually sell."""
    dates = sorted(df["date"].unique())
    print(f"\n  --- {label} ---")
    print(f"  trading days: {len(dates)}  contracts: {df['symbol'].nunique():,}")

    entry_hits, entry_total = 0, 0
    tracked = []   # (symbol, entry_date) for reprice measurement
    spots = {}

    for d in dates:
        day = df[df["date"] == d]
        spot = infer_spot(day)
        if spot is None:
            print(f"  {pd.Timestamp(d).date()}: spot inference failed, day skipped")
            continue
        spots[d] = spot
        calls = day[day["right"] == "C"]

        for otm in np.arange(OTM_BAND[0], OTM_BAND[1] + 0.001, 0.01):
            target_k = spot * (1 + otm)
            for dte in range(DTE_BAND[0], DTE_BAND[1] + 1, 5):
                target_exp = pd.Timestamp(d) + pd.Timedelta(days=dte)
                # Nearest listed expiry within +/- 5 days of the DTE target.
                cand = calls[(calls["expiration"] >= target_exp - pd.Timedelta(days=5)) &
                             (calls["expiration"] <= target_exp + pd.Timedelta(days=5))]
                entry_total += 1
                if cand.empty:
                    continue
                near = cand[(cand["strike"] - target_k).abs() <= spot * STRIKE_TOL]
                if near.empty:
                    continue
                entry_hits += 1
                pick = near.iloc[(near["strike"] - target_k).abs().argsort()[:1]]
                tracked.append((pick.iloc[0]["symbol"], d))

    entry_cov = 100.0 * entry_hits / entry_total if entry_total else 0.0
    print(f"  spot (parity): {', '.join(f'{pd.Timestamp(k).date()}=${v:.2f}' for k, v in list(spots.items())[:5])}")
    print(f"  ENTRY coverage:   {entry_cov:5.1f}%  ({entry_hits:,}/{entry_total:,} target slots filled)")

    # Reprice: for each tracked contract, what fraction of the following trading
    # days in this window also have a bar?
    by_symbol = df.groupby("symbol")["date"].apply(set).to_dict()
    rep_hits, rep_total = 0, 0
    for sym, entry_d in set(tracked):
        later = [d for d in dates if d > entry_d]
        if not later:
            continue
        have = by_symbol.get(sym, set())
        rep_total += len(later)
        rep_hits += sum(1 for d in later if d in have)
    rep_cov = 100.0 * rep_hits / rep_total if rep_total else float("nan")
    print(f"  REPRICE coverage: {rep_cov:5.1f}%  ({rep_hits:,}/{rep_total:,} follow-on days have a bar)")
    print(f"  distinct contracts the strategy would have opened: {len(set(s for s, _ in tracked)):,}")
    return entry_cov, rep_cov


def load_2025_baseline():
    """AAPL 2025 from the existing purchase, restricted to a 5-day window so the
    comparison is apples-to-apples with the 5-day probe."""
    path = os.path.join(CANONICAL_RAW, "AAPL_ohlcv_1d.dbn.zst")
    if not os.path.exists(path):
        print(f"  baseline missing: {path}")
        return None
    df = load_dbn(path)
    if df.empty:
        return None
    # Take a mid-sample 5-day window (avoids the ragged first/last week).
    dates = sorted(df["date"].unique())
    mid = dates[len(dates) // 2: len(dates) // 2 + 5]
    return df[df["date"].isin(mid)]


def main():
    do_pull = "--no-pull" not in sys.argv

    print("=" * 70)
    print("DATABENTO 2020 COVERAGE PROBE")
    print("=" * 70)

    print("\n[1/3] Probe data")
    if do_pull:
        path = pull_probe()
        if not path:
            return 1
    else:
        path = os.path.join(CANONICAL_RAW, PROBE_FILE)
        if not os.path.exists(path):
            print(f"  ERROR: {path} not present and --no-pull given")
            return 1

    print("\n[2/3] Baseline: AAPL 2025 (data already owned)")
    base = load_2025_baseline()
    base_entry = base_rep = None
    if base is not None:
        base_entry, base_rep = analyse(base, "AAPL 2025 (5-day window)")

    print("\n[3/3] Probe: AAPL 2020 crash week")
    probe = load_dbn(path)
    if probe.empty:
        print("  ERROR: probe file parsed to zero rows")
        return 1
    p_entry, p_rep = analyse(probe, "AAPL 2020-03-16 -> 2020-03-20")

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    if base_entry is None:
        print("  INCONCLUSIVE — no 2025 baseline to compare against.")
        return 0
    ok_entry = p_entry >= base_entry - 10.0
    ok_rep = (not np.isnan(p_rep)) and p_rep >= base_rep - 10.0
    print(f"  entry    2020 {p_entry:5.1f}%  vs  2025 {base_entry:5.1f}%   "
          f"(bar: >= {base_entry - 10:.1f}%)  {'PASS' if ok_entry else 'FAIL'}")
    print(f"  reprice  2020 {p_rep:5.1f}%  vs  2025 {base_rep:5.1f}%   "
          f"(bar: >= {base_rep - 10:.1f}%)  {'PASS' if ok_rep else 'FAIL'}")
    print()
    if ok_entry and ok_rep:
        print("  => PASS. 2020 data is as usable as the data every shipped")
        print("     backtest already runs on. The purchase is justified.")
    else:
        print("  => FAIL. 2020 strikes at the distances we sell are materially")
        print("     gappier than 2025. Do NOT buy the full window; a stress")
        print("     backtest on this would be measuring holes, not crashes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
