"""Derive paper_engine/dividends.json — the most recent ACTUAL dividend per ticker.

Why a committed file rather than a live lookup: the engine runs on GitHub
Actions, where Yahoo blocks direct requests (hence yf_proxy), and the
Cloudflare worker's /history endpoint requests no dividend events and its
/info endpoint drops summaryDetail.dividendRate — so at run time there is no
trustworthy live source for the dividend AMOUNT. The correctness review found
`dividend_amount()` reading a 'Dividends' column that yf_proxy never returns,
which made the rational-early-exercise branch structurally unreachable and
biased the H41 (A−B) readout against the copilot for the whole study.

The amount feeds exactly one comparison: `extrinsic < dividend` in cc_core's
early-exercise branch. Dividend amounts move a cent or two per quarter, so a
committed value with a recorded as-of date is honest as long as its staleness
is loud — the engine warns via a counter when the file ages past the ticker's
payment interval. Never derive the amount from spot × dividendYield
(tasks/lessons.md 2026-08-16: a NaN yield sails through None-guards, and a
yield-derived amount is a modelled number wearing a measurement's clothes).

Run on a machine with direct Yahoo access (any dev laptop):

    python3 experiments/024_paper_engine/derive_dividends.py

Out: paper_engine/dividends.json — regenerate quarterly, or when a payer in
the universe announces a change. Every figure is regenerable from this script
(tasks/lessons.md 2026-08-17: a number no committed code can regenerate is not
evidence).
"""
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import ticker_strategies  # noqa: E402

OUT = os.path.join(ROOT, "paper_engine", "dividends.json")


def main():
    import yfinance as yf

    universe = sorted(t for t, c in ticker_strategies.TICKER_STRATEGIES.items()
                      if c.get("tier") != "skip")
    out = {"generated_on": date.today().isoformat(),
           "source": "yfinance Ticker().dividends — actual paid dividends, "
                     "most recent first; derived by this script, never typed in",
           "tickers": {}}
    for t in universe:
        series = yf.Ticker(t).dividends
        rows = [(str(d)[:10], float(a)) for d, a in series.items()]
        if not rows:
            out["tickers"][t] = {"amount": None, "last_paid": None,
                                 "interval_days": None,
                                 "note": "no dividend history — non-payer"}
            print(f"{t}: non-payer")
            continue
        last_date, amount = rows[-1]
        # Payment interval measured, not assumed: DIS pays semiannually and an
        # assumed quarterly cadence would halve its staleness window.
        interval = None
        if len(rows) >= 2:
            d1 = date.fromisoformat(rows[-2][0])
            d2 = date.fromisoformat(rows[-1][0])
            interval = (d2 - d1).days
        out["tickers"][t] = {"amount": amount, "last_paid": last_date,
                             "interval_days": interval}
        print(f"{t}: {amount} paid {last_date} (interval {interval}d)")

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
