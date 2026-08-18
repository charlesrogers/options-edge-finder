"""Diagnose the two anomalies in §4 validation: KKR 0% coverage, AAPL -78.8%."""
import os, re, sys
from datetime import datetime
import numpy as np, pandas as pd, databento as db

RAW = os.path.expanduser("~/Documents/options-tool/data/databento/raw")


def parse_occ(s):
    m = re.search(r"(\d{6})([CP])(\d{8})", str(s).strip())
    if not m:
        return None, None, None
    try:
        return datetime.strptime("20"+m.group(1), "%Y%m%d"), float(m.group(3))/1000, m.group(2)
    except Exception:
        return None, None, None


def load(f):
    df = db.DBNStore.from_file(os.path.join(RAW, f)).to_df().reset_index()
    p = df["symbol"].apply(lambda s: pd.Series(parse_occ(s), index=["expiration","strike","right"]))
    df = pd.concat([df, p], axis=1).dropna(subset=["strike","right"])
    df["date"] = pd.to_datetime(df["ts_event"]).dt.tz_localize(None).dt.normalize()
    return df.groupby(["date","symbol","expiration","strike","right"], as_index=False).agg(
        close=("close","mean"), volume=("volume","sum"))


print("="*72); print("KKR 2020 — why 0% coverage?"); print("="*72)
k = load("KKR_ohlcv_1d_2020feb_jun.dbn.zst")
print(f"rows {len(k):,}  contracts {k['symbol'].nunique():,}  days {k['date'].nunique()}")
print(f"calls {len(k[k['right']=='C']):,}   puts {len(k[k['right']=='P']):,}")
print(f"strike range ${k['strike'].min():.2f} - ${k['strike'].max():.2f}")
# matched pairs per day
pairs = []
for d, day in k.groupby("date"):
    n = 0
    for exp, g in day.groupby("expiration"):
        c = set(g[g["right"]=="C"]["strike"]); p = set(g[g["right"]=="P"]["strike"])
        n = max(n, len(c & p))
    pairs.append(n)
print(f"max matched call/put strikes on a single expiry, per day:")
print(f"  median {np.median(pairs):.0f}  max {max(pairs)}  "
      f"days with >=10 (parity threshold): {sum(1 for x in pairs if x>=10)}/{len(pairs)}")
print(f"contracts per day: median {k.groupby('date')['symbol'].nunique().median():.0f}")
print("=> parity spot inference needs >=10 matched pairs AND >=5 near-the-money.")

print()
print("="*72); print("AAPL Jul-Sep 2020 — split check (4:1 on 2020-08-31)"); print("="*72)
a = load("AAPL_ohlcv_1d_2020jul_sep.dbn.zst")
for label, lo, hi in [("pre-split  Jul01-Aug28","2020-07-01","2020-08-28"),
                      ("post-split Aug31-Sep30","2020-08-31","2020-09-30")]:
    sub = a[(a["date"]>=lo) & (a["date"]<=hi)]
    if sub.empty: continue
    print(f"{label}: strikes ${sub['strike'].min():.0f}-${sub['strike'].max():.0f}  "
          f"contracts {sub['symbol'].nunique():,}  days {sub['date'].nunique()}")
print("=> if strike ranges differ ~4x, the file spans the split and any backtest")
print("   crossing 2020-08-31 must handle it. The -78.8% 'drawdown' is the split.")
